#!/usr/bin/env python3
"""
scripts/headless_range_accumulator.py — write down today's morning range
before Yahoo forgets it.

WHAT IT DOES
    For every ticker in scanners/range_history.UNIVERSE, records the
    09:30-12:00 ET high and low, the price at noon, and the closing print.
    Four numbers per ticker per session, appended to data/range_history/.

WHY IT HAS TO RUN ON A SCHEDULE
    Yahoo serves 5-minute bars for 60 CALENDAR days, and that window rolls:
    every session gained at the front costs one off the back. Waiting and
    then running a longer study returns the same ~41 sessions, just a
    different 41. Daily OHLC reaches back years but cannot say what happened
    before noon. So this is the only way the sample grows.

    Two modes, both wanted:
      --mode append   (default) today only, run after the close.
      --mode backfill re-read the whole 60-day window and fill any gap. Safe
                      to run any time; days already stored are overwritten
                      with the same values, so it repairs a missed day
                      rather than duplicating a stored one.

WHY IT RECORDS EVERY SESSION, NOT ONLY EXPIRY DAYS
    The trade only exists on an expiry day, but the thing being measured —
    whether an afternoon closes back through the morning range — is a
    property of the STOCK, not of whether an option happens to expire. On a
    twice-weekly name, restricting to expiry days would collect ~2
    observations a week and need seven months to reach a usable sample.
    Recording every session collects 5, and whether expiry days differ is
    then a question the data can answer instead of an assumption.

Usage:
  python scripts/headless_range_accumulator.py [--mode append|backfill]
Env:
  RANGE_MODE      append | backfill   (default append)
  RANGE_TICKERS   comma-separated override of the universe
  RANGE_INTERVAL  bar size (default 5m)
"""

import argparse
import os
import sys
from unittest.mock import MagicMock

# Headless: no Streamlit server exists, so a mock goes into sys.modules
# BEFORE any project module is imported. st.cache_data becomes a passthrough
# and every UI call is a no-op. Copied verbatim from the other headless
# scripts — see CLAUDE.md.
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


def log(msg):
    print(f"[range] {msg}", flush=True)


def run(mode: str, tickers: list[str], interval: str) -> int:
    # Backfill asks for the full 60-day window; append still asks for a few
    # days because a Monday run must be able to see Friday if the scheduled
    # run was skipped (a holiday, a failed job, a rate limit).
    period = "60d" if mode == "backfill" else "5d"
    log(f"mode={mode} interval={interval} period={period} tickers={len(tickers)}")

    all_records, failures = [], []
    for key in tickers:
        symbol = rh.spot_symbol(key)
        try:
            df = get_price_history(symbol, period=period, interval=interval)
        except Exception as exc:                       # noqa: BLE001
            failures.append((key, f"{type(exc).__name__}: {exc}"))
            continue
        if df is None or df.empty:
            failures.append((key, "no bars returned"))
            continue

        recs = rh.session_records(df, key, interval)
        if mode == "append":
            # Keep only the most recent finished session. A 5d request spans
            # a week; storing all of it every day is harmless (same values
            # overwrite) but the log is clearer when append means append.
            recs = recs[-1:] if recs else []
        if not recs:
            failures.append((key, "no finished session in the window"))
            continue

        all_records += recs
        last = recs[-1]
        log(f"  {key:5} {len(recs):3} session(s) · latest {last['date']} "
            f"pos {last['pos_pct']:5.1f}% range {last['range_pct']:4.2f}% "
            f"{'BREACH' if last['breach'] else 'held'}")

    if failures:
        log(f"{len(failures)} ticker(s) produced nothing:")
        for key, why in failures:
            log(f"  {key:5} {why}")

    if not all_records:
        log("nothing to write")
        return 1 if failures else 0

    paths = rh.save_records(all_records, source="accum")
    log(f"wrote {len(all_records)} record(s) across {len(paths)} file(s)")

    stored = rh.load_records()
    cov = rh.coverage(stored)
    if not cov.empty:
        log("")
        log("coverage — green-zone sessions against the 43 the QQQ/SPY study used:")
        for _, r in cov.iterrows():
            bar = "#" * min(20, int(r["green_sessions"] / 43 * 20))
            log(f"  {r['ticker']:5} {r['sessions']:4} sessions  "
                f"green {r['green_sessions']:3}  {r['pct_of_target']:5.1f}%  {bar}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default=os.environ.get("RANGE_MODE", "append"),
                    choices=["append", "backfill"])
    ap.add_argument("--interval", default=os.environ.get("RANGE_INTERVAL", "5m"))
    ap.add_argument("--tickers", default=os.environ.get("RANGE_TICKERS", ""))
    args = ap.parse_args()

    if args.tickers.strip():
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = [t["key"] for t in rh.UNIVERSE]

    if args.interval not in rh.WINDOWS:
        log(f"interval {args.interval!r} has no defined measurement window "
            f"(known: {', '.join(sorted(rh.WINDOWS))})")
        return 2
    return run(args.mode, tickers, args.interval)


if __name__ == "__main__":
    sys.exit(main())
