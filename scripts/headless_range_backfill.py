#!/usr/bin/env python3
"""
scripts/headless_range_backfill.py — buy ~2 years of morning-range history
today, at a stated cost.

THE TRADE THIS SCRIPT MAKES
    Yahoo's intraday limits are per-interval:

        1m                 ~7 days
        2m / 5m / 15m / 30m ~60 days     <- what the accumulator uses
        60m (1h)           ~730 days     <- what this uses

    So hourly bars reach back roughly two years instead of two months. That
    is the entire reason this script exists.

WHAT IT COSTS — read this before quoting any number it produces
    Hourly bars for US equities are stamped 09:30, 10:30, 11:30, 12:30...
    The 11:30 bar SPANS 11:30-12:30. Including it to reach "noon" would fold
    half an hour of post-noon information into a number whose whole purpose
    is to be knowable AT noon — a look-ahead, and exactly the kind that
    makes a study look better than the trade.

    So the window here ends at 11:30, read at 11:30. That is a DIFFERENT
    measurement from the tab's 09:30-12:00, not a longer run of the same
    one. Records are tagged window_end=690 and source="backfill60m", and
    range_history.window_comparison() exists to measure, on the ~60 days
    where both sources overlap, how far the 11:30 read sits from the 12:00
    one — including how often the two disagree about which ZONE a session is
    in, which is the only difference that changes a trading decision.

    Until that comparison is run and read, treat this history as context for
    where to look, not as evidence for a gate.

Usage:
  python scripts/headless_range_backfill.py [--period 730d] [--tickers NVDA,TSLA]
Env:
  RANGE_BF_PERIOD   default "730d"
  RANGE_BF_TICKERS  comma-separated override of the universe
"""

import argparse
import os
import sys
from unittest.mock import MagicMock


class _FakeSessionState(dict):
    def __missing__(self, key):
        return None


class _MockStreamlit:
    session_state = _FakeSessionState()

    @staticmethod
    def cache_data(ttl=None, show_spinner=True, **kwargs):
        def _decorator(fn):
            return fn
        return _decorator

    @staticmethod
    def cache_resource(*a, **k):
        def _decorator(fn):
            return fn
        return _decorator

    def __getattr__(self, name):
        return MagicMock()


sys.modules["streamlit"] = _MockStreamlit()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pandas as pd  # noqa: E402

from data_loader import get_price_history  # noqa: E402
from scanners import range_history as rh  # noqa: E402

INTERVAL = "60m"


def log(msg):
    print(f"[backfill] {msg}", flush=True)


def run(tickers: list[str], period: str) -> int:
    log(f"interval={INTERVAL} period={period} tickers={len(tickers)}")
    log("window is 09:30-11:30 read at 11:30 — NOT the tab's 09:30-12:00. "
        "See the module docstring.")

    records, failures = [], []
    for key in tickers:
        symbol = rh.spot_symbol(key)
        try:
            df = get_price_history(symbol, period=period, interval=INTERVAL)
        except Exception as exc:                       # noqa: BLE001
            failures.append((key, f"{type(exc).__name__}: {exc}"))
            continue
        if df is None or df.empty:
            failures.append((key, "no bars returned"))
            continue

        recs = rh.session_records(df, key, INTERVAL)
        if not recs:
            failures.append((key, f"{len(df)} bars but no usable session"))
            continue
        records += recs
        log(f"  {key:5} {len(recs):4} sessions  {recs[0]['date']} -> {recs[-1]['date']}")

    if failures:
        log(f"{len(failures)} ticker(s) produced nothing:")
        for key, why in failures:
            log(f"  {key:5} {why}")
    if not records:
        log("nothing to write")
        return 1

    paths = rh.save_records(records, source="backfill60m")
    log(f"wrote {len(records)} record(s) across {len(paths)} file(s)")

    stored = rh.load_records()
    log("")
    log("── coverage (all sources) ──────────────────────────────────────")
    cov = rh.coverage(stored)
    for _, r in cov.iterrows():
        log(f"  {r['ticker']:5} {r['sessions']:5} sessions  green {r['green_sessions']:4}  "
            f"{r['first']} -> {r['last']}")

    # The honest headline number, per zone, clustered by date.
    log("")
    log("── pooled breach rate by zone (n_days is the number that counts) ──")
    for zone in ("put_green", "put_amber", "put_block", "call"):
        s = rh.pooled_breach_rate(stored, zone=zone)
        if not s["n_rows"]:
            continue
        log(f"  {zone:10} {s['breaches']:4}/{s['n_rows']:5} ticker-days "
            f"({s['rate_pct']:5.2f}%)   {s['breach_days']:4}/{s['n_days']:4} dates "
            f"({s['day_rate_pct']:5.2f}%)")

    cmp_df = rh.window_comparison(stored)
    if not cmp_df.empty:
        agree = (cmp_df["zone_noon"] == cmp_df["zone_1130"]).mean() * 100
        log("")
        log("── 11:30 vs 12:00, where both exist ────────────────────────────")
        log(f"  overlapping ticker-days : {len(cmp_df)}")
        log(f"  mean |position diff|    : {cmp_df['pos_diff'].abs().mean():.1f} pts")
        log(f"  median |position diff|  : {cmp_df['pos_diff'].abs().median():.1f} pts")
        log(f"  same zone               : {agree:.1f}%")
        log("  Read this before pooling the two sources. Disagreement on the "
            "ZONE is what changes a trade.")
    else:
        log("")
        log("No overlap yet between the hourly backfill and the 5m accumulator — "
            "run the accumulator in backfill mode to create it.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default=os.environ.get("RANGE_BF_PERIOD", "730d"))
    ap.add_argument("--tickers", default=os.environ.get("RANGE_BF_TICKERS", ""))
    args = ap.parse_args()
    if args.tickers.strip():
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = [t["key"] for t in rh.UNIVERSE]
    return run(tickers, args.period)


if __name__ == "__main__":
    sys.exit(main())
