# scanners/iv_history.py — daily implied-volatility history, so "is this IV
# high?" can eventually be answered against the ticker's OWN past.
#
# scanners/option_premium.py can already say whether a premium is rich by
# comparing IV against REALISED volatility, which needs nothing stored. The
# strictly better measure — IV against its own past IV, i.e. a real IV rank —
# needs history, and no part of this repo was keeping any. yfinance serves the
# current chain only; there is no endpoint for "what was TQQQ's IV in March".
# The only way to have it is to start writing it down.
#
# Same shape as scanners/sector_history.py: one JSON per session under
# data/iv_history/, written once after the close by a GitHub Action (which has
# contents: write) and only ever READ by the Streamlit app.
#
# The honesty problem this file has to solve: a rank computed from three weeks
# of data looks exactly like a rank computed from a year, and is worthless. So
# rank_for() refuses to return a number until MIN_SESSIONS have accumulated,
# and always reports how many sessions it actually has, so the page can say
# "building, 12 of 60" instead of showing a confident-looking 74.

from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timedelta

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP_DIR = os.path.join(ROOT, "data", "iv_history")

# Sessions of history required before a rank is reported at all. Sixty is
# about three months -- enough to have seen both a calm stretch and a scare,
# which is the minimum for "high for this ticker" to mean anything. Below it
# the range is just whatever happened to occur since we started watching.
MIN_SESSIONS = 60

# Window the rank is measured over. A year is the convention; the store keeps
# a little more so the window is always full once it has matured.
RANK_WINDOW = 252
RETENTION_DAYS = 500

# What gets snapshotted. Starts with the long 3x funds the premium page
# covers, plus the three index ETFs as reference points -- they are the
# baseline every leveraged fund is a multiple of, and the other options
# scanners will want them when they move onto this engine. Kept here rather
# than imported from a scanner so the daily job has no UI dependency.
SNAPSHOT_UNIVERSE = [
    "TQQQ", "SOXL", "UPRO", "TECL", "FAS", "TNA", "LABU",
    "SPY", "QQQ", "IWM",
]


def _path(date_str: str) -> str:
    return os.path.join(SNAP_DIR, f"{date_str}.json")


def save_snapshot(rows: list[dict], date_str: str) -> str:
    """Write one session's IV readings. Returns the path written."""
    os.makedirs(SNAP_DIR, exist_ok=True)
    path = _path(date_str)
    payload = {
        "date": date_str,
        "saved_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "rows": rows,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return path


def load_snapshots(days: int | None = None) -> list[dict]:
    """All stored sessions, oldest first."""
    out = []
    for p in sorted(glob.glob(os.path.join(SNAP_DIR, "*.json"))):
        try:
            with open(p, encoding="utf-8") as f:
                out.append(json.load(f))
        except Exception:
            continue
    if days:
        cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        out = [s for s in out if s.get("date", "") >= cutoff]
    return sorted(out, key=lambda s: s.get("date", ""))


def prune_old(today_date_str: str, retention_days: int = RETENTION_DAYS) -> list[str]:
    cutoff = (datetime.strptime(today_date_str, "%Y-%m-%d")
              - timedelta(days=retention_days)).strftime("%Y-%m-%d")
    removed = []
    for p in glob.glob(os.path.join(SNAP_DIR, "*.json")):
        if os.path.basename(p)[:10] < cutoff:
            try:
                os.remove(p)
                removed.append(p)
            except OSError:
                continue
    return removed


def iv_series(ticker: str, field: str = "iv_atm",
              snapshots: list[dict] | None = None) -> pd.Series:
    """One ticker's stored IV readings as a date-indexed Series."""
    snaps = load_snapshots() if snapshots is None else snapshots
    dates, vals = [], []
    for s in snaps:
        for r in s.get("rows", []):
            if r.get("ticker") == ticker and r.get(field) is not None:
                dates.append(s.get("date"))
                vals.append(float(r[field]))
                break
    if not dates:
        return pd.Series(dtype=float)
    return pd.Series(vals, index=pd.to_datetime(dates)).sort_index()


def rank_for(ticker: str, iv_now: float, window: int = RANK_WINDOW,
             snapshots: list[dict] | None = None) -> dict:
    """Where today's IV sits within this ticker's own stored history.

    Returns {rank, percentile, sessions, ready, low, high}. `rank` and
    `percentile` are None until `sessions` reaches MIN_SESSIONS — a rank over
    three weeks of data is not a weak rank, it is a meaningless one, and
    returning it anyway is how the old approx_iv_rank misled for so long.

    rank       classic IV rank: position within the window's low-high range.
    percentile the share of stored sessions that were BELOW today. More
               robust than rank, which one freak spike can distort for a year.
    """
    s = iv_series(ticker, snapshots=snapshots)
    if window and len(s) > window:
        s = s.iloc[-window:]

    n = int(len(s))
    out = {"rank": None, "percentile": None, "sessions": n,
           "ready": n >= MIN_SESSIONS, "low": None, "high": None,
           "needed": max(0, MIN_SESSIONS - n)}
    if n == 0 or iv_now is None:
        return out

    lo, hi = float(s.min()), float(s.max())
    out["low"], out["high"] = round(lo, 4), round(hi, 4)
    if not out["ready"]:
        return out

    if hi > lo:
        out["rank"] = round((float(iv_now) - lo) / (hi - lo) * 100, 1)
        out["rank"] = float(max(0.0, min(100.0, out["rank"])))
    else:
        out["rank"] = 50.0
    out["percentile"] = round(float((s < float(iv_now)).sum()) / n * 100, 1)
    return out


def coverage() -> dict:
    """How far along the history is, for the page to report honestly."""
    snaps = load_snapshots()
    if not snaps:
        return {"sessions": 0, "ready": False, "needed": MIN_SESSIONS,
                "first": None, "last": None, "tickers": 0}
    tickers = {r.get("ticker") for s in snaps for r in s.get("rows", [])}
    n = len(snaps)
    return {"sessions": n, "ready": n >= MIN_SESSIONS,
            "needed": max(0, MIN_SESSIONS - n),
            "first": snaps[0].get("date"), "last": snaps[-1].get("date"),
            "tickers": len(tickers)}
