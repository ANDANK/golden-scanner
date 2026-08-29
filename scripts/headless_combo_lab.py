#!/usr/bin/env python3
"""
scripts/headless_combo_lab.py — run the indicator-combination study.

WHAT IT DOES
    Fetches ~500 names, computes every indicator condition, then tests all
    191 combinations (singles included) across four independent cells:

        Daily  x Recent 1y      Daily  x Prior 2y
        Weekly x Recent 1y      Weekly x Prior 2y

    The two periods DO NOT OVERLAP. A one-year window nested inside a
    three-year one shares its trades with it, so "confirmed in both" would
    partly be the same trades counted twice; here agreement between the two
    is real out-of-sample evidence.

CACHING
    Raw price frames are cached under .cache/combo_lab/ (gitignored) keyed by
    ticker and fetch date, so a re-run on the same day costs nothing at
    Yahoo. Delete the directory to force a refetch.

Usage:
  python scripts/headless_combo_lab.py
Env:
  COMBO_UNIVERSE   FTF / SP500 / MTPA        (default FTF)
  COMBO_LIMIT      cap the ticker count, for a smoke run (default 0 = all)
  COMBO_REFRESH    "1" to ignore the cache
"""

import json
import os
import sys
import time
from datetime import datetime
from unittest.mock import MagicMock


class _FakeSessionState(dict):
    def __missing__(self, key):
        return None


class _MockStreamlit:
    session_state = _FakeSessionState()

    @staticmethod
    def cache_data(ttl=None, show_spinner=True, **kwargs):
        def _d(fn):
            return fn
        return _d

    @staticmethod
    def cache_resource(*a, **k):
        def _d(fn):
            return fn
        return _d

    def __getattr__(self, name):
        return MagicMock()


sys.modules["streamlit"] = _MockStreamlit()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from data_loader import get_price_history  # noqa: E402
from scanners import combo_lab as cl  # noqa: E402
from scanners import fast_score as fs  # noqa: E402

OUT_DIR = os.path.join(ROOT, "data", "combo_lab")
CACHE_DIR = os.path.join(ROOT, ".cache", "combo_lab")

UNIVERSE_KIND = os.environ.get("COMBO_UNIVERSE", "FTF").upper()
LIMIT = int(os.environ.get("COMBO_LIMIT", "0") or 0)
REFRESH = os.environ.get("COMBO_REFRESH", "") == "1"

# Five years fetched, three years tested. The extra two years are indicator
# warmup: EMA50 on weekly bars needs a year of history before it means
# anything, and warmup drawn from before the test window is not look-ahead.
FETCH_PERIOD = "5y"


def log(msg):
    print(f"[combo] {msg}", flush=True)


# ── Data fetch + cache ────────────────────────────────────────────────────

def _cache_path(ticker: str) -> str:
    stamp = datetime.utcnow().strftime("%Y-%m-%d")
    safe = ticker.replace("/", "_").replace("^", "_")
    return os.path.join(CACHE_DIR, f"{safe}_{stamp}.pkl")


def fetch_daily(ticker: str) -> pd.DataFrame | None:
    """Daily OHLCV, cached per ticker per day."""
    path = _cache_path(ticker)
    if not REFRESH and os.path.exists(path):
        try:
            return pd.read_pickle(path)
        except Exception:                                   # noqa: BLE001
            pass
    try:
        df = get_price_history(ticker, period=FETCH_PERIOD, interval="1d")
    except Exception as exc:                                # noqa: BLE001
        log(f"  {ticker}: {type(exc).__name__}: {exc}")
        return None
    if df is None or df.empty:
        return None
    os.makedirs(CACHE_DIR, exist_ok=True)
    try:
        df.to_pickle(path)
    except Exception:                                       # noqa: BLE001
        pass
    return df


def to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Resample daily bars to weekly, labelled on the week's last session.

    Labelled on the LAST session rather than Monday so that a weekly bar's
    timestamp is a date on which the bar was actually complete — otherwise
    the window filter would admit a bar stamped before the information in it
    existed.
    """
    agg = {"Open": "first", "High": "max", "Low": "min",
           "Close": "last", "Volume": "sum"}
    out = df.resample("W-FRI").agg(agg).dropna(subset=["Close"])
    return out


# ── Windows ───────────────────────────────────────────────────────────────

def windows(index: pd.DatetimeIndex) -> dict[str, tuple]:
    """Recent 1 year, and the 2 years before it. Deliberately disjoint."""
    end = index.max()
    one_year_ago = end - pd.Timedelta(days=365)
    three_years_ago = end - pd.Timedelta(days=365 * 3)
    return {
        "Recent 1y": (one_year_ago + pd.Timedelta(days=1), end),
        "Prior 2y": (three_years_ago, one_year_ago),
    }


def run() -> int:
    universe = fs.universe_for(UNIVERSE_KIND)
    if LIMIT:
        universe = universe[:LIMIT]
    log(f"universe {UNIVERSE_KIND} ({len(universe)} tickers) · "
        f"fetch {FETCH_PERIOD} · cache {'OFF' if REFRESH else 'ON'}")

    t0 = time.time()
    daily_frames, weekly_frames, failed = {}, {}, []
    for i, ticker in enumerate(universe):
        raw = fetch_daily(ticker)
        if raw is None or raw.empty:
            failed.append(ticker)
            continue
        d = cl.indicator_frame(raw, "daily")
        w = cl.indicator_frame(to_weekly(raw), "weekly")
        if d is not None:
            daily_frames[ticker] = d
        if w is not None:
            weekly_frames[ticker] = w
        if (i + 1) % 50 == 0:
            log(f"  {i + 1}/{len(universe)} fetched "
                f"({time.time() - t0:.0f}s, {len(failed)} failed)")

    log(f"usable: {len(daily_frames)} daily / {len(weekly_frames)} weekly "
        f"({len(failed)} failed) in {time.time() - t0:.0f}s")
    if not daily_frames:
        log("no data — aborting")
        return 1

    bench_raw = fetch_daily(cl.BENCHMARK)
    bench_d = cl.indicator_frame(bench_raw, "daily") if bench_raw is not None else None
    bench_w = (cl.indicator_frame(to_weekly(bench_raw), "weekly")
               if bench_raw is not None else None)

    combos = cl.all_combinations()
    log(f"{len(combos)} combinations (singles included)")

    any_index = next(iter(daily_frames.values())).index
    wins = windows(any_index)
    for name, (s, e) in wins.items():
        log(f"  window {name}: {s.date()} -> {e.date()}")

    tables, headline = {}, {}
    for tf, frames, bench in (("Daily", daily_frames, bench_d),
                              ("Weekly", weekly_frames, bench_w)):
        for wname, (start, end) in wins.items():
            for hold in cl.HOLDS["daily" if tf == "Daily" else "weekly"]:
                key = f"{tf}-{wname}-{hold}b"
                t1 = time.time()
                tbl = cl.run_window(frames, bench, start, end, hold, combos)
                tables[key] = tbl
                ranked = cl.rank_table(tbl)
                ok = ranked[~ranked["low_n"]]
                log(f"  {key:26} {len(ok):3} rankable / {len(tbl)} · "
                    f"{time.time() - t1:.0f}s")
                if len(ok):
                    top = ok.iloc[0]
                    log(f"      best: {top['combo']:20} "
                        f"excess {top['avg_excess']:+.2f}% "
                        f"win {top['win_rate']:.0f}% n={int(top['trades'])}")

    # The headline consensus uses ONE hold per timeframe (the shorter of the
    # two) so the four cells being compared differ only in timeframe and
    # period, never in exit. Mixing holds into the same consensus would make
    # "holds everywhere" ambiguous about what held.
    for tf, hold in (("Daily", cl.HOLDS["daily"][0]),
                     ("Weekly", cl.HOLDS["weekly"][0])):
        for wname in wins:
            headline[f"{tf} {wname}"] = tables[f"{tf}-{wname}-{hold}b"]
    cons = cl.consensus(headline)

    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y-%m-%d")
    tag = f"{stamp}_{UNIVERSE_KIND}"

    for key, tbl in tables.items():
        cl.rank_table(tbl).to_csv(
            os.path.join(OUT_DIR, f"{tag}_{key.replace(' ', '')}.csv"),
            index=False)
    cons.to_csv(os.path.join(OUT_DIR, f"{tag}_CONSENSUS.csv"), index=False)

    payload = {
        "generated_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "universe": UNIVERSE_KIND,
        "universe_size": len(universe),
        "usable_daily": len(daily_frames),
        "usable_weekly": len(weekly_frames),
        "benchmark": cl.BENCHMARK,
        "min_trades": cl.MIN_TRADES,
        "cross_window": cl.CROSS_WINDOW,
        "holds": cl.HOLDS,
        "windows": {k: [str(v[0].date()), str(v[1].date())]
                    for k, v in wins.items()},
        "consensus": json.loads(cons.to_json(orient="records")),
        "tables": {k: json.loads(cl.rank_table(v).to_json(orient="records"))
                   for k, v in tables.items()},
    }
    with open(os.path.join(OUT_DIR, f"{tag}.json"), "w") as fh:
        json.dump(payload, fh, indent=1)
    with open(os.path.join(OUT_DIR, "latest.json"), "w") as fh:
        json.dump(payload, fh, indent=1)

    log("")
    log("── what holds up in all four windows ───────────────────────────")
    held = cons[cons["verdict"] == "Holds everywhere"]
    if held.empty:
        log("  NOTHING. No combination was positive against SPY in all four")
        log("  independent windows with an adequate sample. That is a result,")
        log("  not a failure of the run.")
    else:
        for _, r in held.head(15).iterrows():
            log(f"  {r['combo']:22} mean edge {r['mean_edge']:+.2f}%  "
                f"worst {r['worst_edge']:+.2f}%  min n={int(r['min_n'])}")
    singles = cons[cons["n_factors"] == 1]
    log("")
    log("── single factors, for comparison ──────────────────────────────")
    for _, r in singles.iterrows():
        log(f"  {r['combo']:6} {r['verdict']:18} mean edge "
            f"{r['mean_edge']:+.2f}%  min n={int(r['min_n'])}")
    log("")
    log(f"wrote {len(tables) + 2} files to data/combo_lab/")
    return 0


if __name__ == "__main__":
    sys.exit(run())
