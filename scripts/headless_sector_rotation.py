#!/usr/bin/env python3
"""
scripts/headless_sector_rotation.py — write one post-close snapshot of the
Sector Rotation table to data/sector_rotation/.

Run once per session AFTER the close (see
.github/workflows/sector_rotation_history.yml). Timing is the point: the
rotation table is computed off the last bar, and during market hours that
bar is still forming, so a snapshot taken at 11am is not comparable with one
taken at 2pm. Only a settled close gives a series where a change from one
row to the next means the market moved rather than the clock did.

The Streamlit app deliberately never writes here — it has no git write
access and would produce a file per page load. GitHub Actions has
`contents: write`, runs once, and commits.

Usage:
  python scripts/headless_sector_rotation.py

Optional env vars:
  SECTOR_SNAPSHOT_SLOT     slot tag for the filename (default "close")
  SECTOR_SNAPSHOT_FORCE    "1" to snapshot even if the last bar is still
                           live (default off — refuses rather than writing
                           an intraday reading into a daily series)
"""

import os
import sys
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

from data_loader import get_price_history, prefetch_tickers  # noqa: E402
from scanners import sector_history  # noqa: E402
from scanners.sector_rotation import SECTORS, run_sector_rotation, _is_live_bar  # noqa: E402

SLOT = os.environ.get("SECTOR_SNAPSHOT_SLOT", "close").lower()
FORCE = os.environ.get("SECTOR_SNAPSHOT_FORCE", "").strip() == "1"


def main() -> int:
    tickers = [t for t, _ in SECTORS] + ["SPY"]
    print(f"Prefetching {len(tickers)} tickers…")
    prefetch_tickers(tickers, "1y", "1d")

    spy = get_price_history("SPY", period="1y", interval="1d")
    if spy is None or spy.empty:
        print("ERROR: no SPY data — refusing to write a snapshot with no benchmark.")
        return 1

    spy_close = spy["Close"].squeeze()
    live = _is_live_bar(spy_close)
    if live and not FORCE:
        print("Last bar is still forming (market open). A daily series must be built "
              "from settled closes only — skipping. Set SECTOR_SNAPSHOT_FORCE=1 to override.")
        return 0

    bar_date = pd.Timestamp(spy_close.index[-1]).strftime("%Y-%m-%d")
    print(f"Scanning sector rotation as of {bar_date}…")

    df, mkt = run_sector_rotation()
    if df is None or df.empty:
        print("ERROR: scan returned no rows — refusing to write an empty snapshot.")
        return 1

    # File is dated by the BAR, not by the wall clock. A job that runs at
    # 21:15 UTC Friday and one that runs at 00:30 UTC Saturday are describing
    # the same session, and dating by wall clock would file them as two.
    rows = sector_history.to_snapshot_rows(df)
    path = sector_history.save_snapshot(rows, mkt, bar_date, slot=SLOT)
    print(f"Wrote {len(rows)} rows → {os.path.relpath(path, ROOT)}")

    top = df.head(3)[["Ticker", "RS vs SPY", "Trade Idea"]].to_dict("records")
    print("Leaders: " + " · ".join(
        f'{r["Ticker"]} RS {r["RS vs SPY"]:.3f} ({r["Trade Idea"]})' for r in top
    ))

    removed = sector_history.prune_old(datetime.utcnow().strftime("%Y-%m-%d"))
    if removed:
        print(f"Pruned {len(removed)} snapshot(s) past the retention window.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
