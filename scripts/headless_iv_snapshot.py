#!/usr/bin/env python3
"""
scripts/headless_iv_snapshot.py — record one session's implied volatility for
the options universe, so a real IV Rank can eventually be computed.

Why this exists: yfinance serves the CURRENT option chain and nothing else.
There is no endpoint for "what was TQQQ's IV three months ago", so the only
way to ever answer "is this IV high FOR THIS TICKER" is to write it down every
day starting now. Until roughly 60 sessions have accumulated the pages fall
back to IV-vs-realised-volatility, which needs no history — see
scanners/option_premium.py.

Run once per weekday AFTER the close (see
.github/workflows/iv_snapshot.yml). Timing matters less than it does for the
price snapshots — IV is a quote, not a bar — but reading it at a consistent
time each day is what makes the series comparable to itself.

Usage:
  python scripts/headless_iv_snapshot.py

Optional env vars:
  IV_SNAPSHOT_DTE_MIN / IV_SNAPSHOT_DTE_MAX
      Which part of the curve to read (default 21-45 days). Must stay stable
      run to run: a rank built from mixed horizons compares nothing.
  IV_SNAPSHOT_TICKERS
      Comma-separated override of the universe.
  IV_SNAPSHOT_PAUSE
      Seconds between tickers (default 2) — the chain endpoint rate-limits.
"""

import os
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ── Mock Streamlit so scanner modules import/run without a server, same
# approach as scripts/headless_scan.py — quiet logs, no-op UI calls, and
# st.cache_data becomes a passthrough (no caching needed for a single run).
from unittest.mock import MagicMock


class _FakeSS(dict):
    def __missing__(self, key):
        return None


class _MockST:
    session_state = _FakeSS()

    @staticmethod
    def cache_data(ttl=None, show_spinner=True):
        def _dec(fn):
            return fn
        return _dec

    def __getattr__(self, name):
        return MagicMock()


sys.modules["streamlit"] = _MockST()

# ── Now safe to import project modules ──────────────────────────────────
import pandas as pd  # noqa: E402

from data_loader import get_options_chain, get_price_history  # noqa: E402
from scanners import iv_history  # noqa: E402
from scanners.option_premium import (  # noqa: E402
    RV_WINDOW, chain_snapshot, iv_rv_ratio, pick_expiry, realized_vol,
)

DTE_MIN = int(os.environ.get("IV_SNAPSHOT_DTE_MIN", 21))
DTE_MAX = int(os.environ.get("IV_SNAPSHOT_DTE_MAX", 45))
PAUSE = float(os.environ.get("IV_SNAPSHOT_PAUSE", 2))
_env_tickers = os.environ.get("IV_SNAPSHOT_TICKERS", "").strip()
TICKERS = ([t.strip().upper() for t in _env_tickers.split(",") if t.strip()]
           if _env_tickers else list(iv_history.SNAPSHOT_UNIVERSE))


def main() -> int:
    print(f"Snapshotting IV for {len(TICKERS)} tickers "
          f"at {DTE_MIN}-{DTE_MAX} DTE…")

    rows, failures = [], {}

    def fail(ticker, reason):
        failures[ticker] = reason
        print(f"  {ticker:6} skipped — {reason}")

    bar_date = None
    for ticker in TICKERS:
        try:
            hist = get_price_history(ticker, period="6mo")
            if hist is None or hist.empty:
                fail(ticker, "no price history")
                continue
            close = hist["Close"].squeeze()
            price = float(close.iloc[-1])
            rv = realized_vol(close, RV_WINDOW)

            # Every row is stamped with the bar date of the underlying rather
            # than today's wall clock, so a job that runs late (or twice)
            # cannot file the same session under two different dates.
            if bar_date is None:
                bar_date = pd.Timestamp(close.index[-1]).strftime("%Y-%m-%d")

            _, _, expiries = get_options_chain(ticker)
            if not expiries:
                fail(ticker, "no option expiries")
                continue
            exp, dte = pick_expiry(expiries, DTE_MIN, DTE_MAX)
            if not exp:
                fail(ticker, "no expiry in range")
                continue

            _, puts, _ = get_options_chain(ticker, exp)
            snap = chain_snapshot(puts, price, dte)
            if not snap["iv_atm"] and not snap["iv_otm"]:
                fail(ticker, "chain carried no implied volatility")
                continue

            iv_atm = snap["iv_atm"]
            rows.append({
                "ticker":   ticker,
                "iv_atm":   iv_atm,
                "iv_otm":   snap["iv_otm"],
                "skew":     snap["skew"],
                "rv":       rv or None,
                "iv_rv":    iv_rv_ratio(iv_atm, rv) if iv_atm else None,
                "price":    round(price, 2),
                "dte":      dte,
                "spread_pct": snap["spread_pct"],
            })
            print(f"  {ticker:6} IV {(iv_atm or 0)*100:5.1f}%  "
                  f"RV {(rv or 0)*100:5.1f}%  "
                  f"IV/RV {snap and iv_rv_ratio(iv_atm, rv)}")
        except Exception as e:
            fail(ticker, f"{type(e).__name__}")
        finally:
            if PAUSE:
                time.sleep(PAUSE)

    if not rows:
        print("ERROR: no IV readings collected — refusing to write an empty "
              "snapshot, which would leave a hole in the series that looks "
              "like a quiet day.")
        return 1

    date_str = bar_date or datetime.utcnow().strftime("%Y-%m-%d")
    path = iv_history.save_snapshot(rows, date_str)
    print(f"\nWrote {len(rows)}/{len(TICKERS)} tickers → "
          f"{os.path.relpath(path, ROOT)}  (session {date_str})")
    if failures:
        print("Missing: " + ", ".join(f"{t} ({r})" for t, r in failures.items()))

    cov = iv_history.coverage()
    if cov["ready"]:
        print(f"IV Rank is live — {cov['sessions']} sessions stored "
              f"({cov['first']} → {cov['last']}).")
    else:
        print(f"IV Rank still building — {cov['sessions']} sessions stored, "
              f"{cov['needed']} more needed before a rank is trustworthy.")

    removed = iv_history.prune_old(date_str)
    if removed:
        print(f"Pruned {len(removed)} snapshot(s) past the retention window.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
