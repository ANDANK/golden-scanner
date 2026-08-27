# scanners/range_history.py — the morning-range record the Spreads tab needs
# before it can honestly quote a breach rate on anything but QQQ and SPY.
#
# WHY THIS FILE EXISTS
#   The Spreads gate ("noon >= 70% of the morning range -> put credit
#   spread") rests on 59 sessions of QQQ and SPY. Every other underlying on
#   that tab is trading a transplanted threshold. To fix that we need, per
#   ticker per session: the 09:30-noon high and low, the price at noon, and
#   the closing print. Nothing else.
#
#   Those four numbers are cheap to compute and impossible to recover later.
#   Yahoo serves 5-minute bars for 60 CALENDAR days and no further back, and
#   that window ROLLS: waiting six months and then asking for more history
#   returns the same ~41 sessions, just a different 41. Daily OHLC goes back
#   decades but cannot tell you what happened before noon. So the sample only
#   grows if something writes each session down as it passes. That is this.
#
# TWO SOURCES, DELIBERATELY NOT POOLED
#   1. ACCUMULATED (interval 5m, window 09:30-12:00) — written once per
#      session after the close by scripts/headless_range_accumulator.py.
#      This is the real thing: the exact window the Spreads tab trades.
#
#   2. BACKFILLED (interval 60m, window 09:30-11:30) — Yahoo serves HOURLY
#      bars for ~730 days, which buys roughly two years of history today
#      instead of two years from now. The catch is unavoidable and is the
#      reason these are tagged separately: hourly bars are stamped 09:30,
#      10:30, 11:30, and the 11:30 bar spans 11:30-12:30, so including it
#      would leak half an hour of post-noon information into a "noon" read.
#      Dropping it leaves a 09:30-11:30 window read at 11:30 — a DIFFERENT
#      measurement, not a longer version of the same one.
#
#   Every record carries `window_end` and `interval`. Anything reading this
#   store must group by those or it is quietly averaging two studies. The
#   60-day overlap where both sources exist is what tells you how far apart
#   the 11:30 and 12:00 reads actually are; until that is measured, the
#   backfill is context, not evidence.
#
# STORAGE
#   One JSON file per (source, date) under data/range_history/, mirroring
#   scanners/scan_history.py and scanners/sector_history.py. The Streamlit
#   app only ever READS these — it has no git write access and would write a
#   file per page load. Only the scheduled headless scripts write.

from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP_DIR = os.path.join(ROOT, "data", "range_history")

ET = "US/Eastern"

MORNING_START_MIN = 9 * 60 + 30
REGULAR_CLOSE_MIN = 16 * 60
EARLY_CLOSE_MIN = 13 * 60

# The two measurement windows. Keyed by the bar interval that can support
# them: a 12:00 cut needs bars finer than an hour.
WINDOWS = {
    "5m":  12 * 60,        # 09:30-12:00, the window the tab trades
    "15m": 12 * 60,
    "30m": 12 * 60,
    "60m": 11 * 60 + 30,   # 09:30-11:30, all an hourly grid can honestly give
    "1h":  11 * 60 + 30,
}

# Keep everything. The whole point is that these cannot be re-fetched, so a
# retention policy here would be deleting the only copy of the evidence.
RETENTION_DAYS = None


# ── The universe ──────────────────────────────────────────────────────────
# `cadence` is a DECLARED expectation, used only to decide which table a
# ticker appears in and how loudly to warn. It is never a gate: the option
# chain is always asked what expiries actually exist, and
# observed_cadence() below re-derives the truth from what the accumulator
# recorded. Where the two disagree, the observation wins.
CADENCE_DAILY = "daily"
CADENCE_NON_DAILY = "non_daily"

UNIVERSE = [
    # ── Daily expiries (Mon-Fri) ──
    {"key": "QQQ",  "label": "QQQ",  "desc": "Nasdaq 100 ETF",
     "cadence": CADENCE_DAILY, "hint": "Mon-Fri", "validated": True, "group": "index"},
    {"key": "SPX",  "label": "SPX",  "desc": "S&P 500 index · cash settled",
     "cadence": CADENCE_DAILY, "hint": "Mon-Fri", "validated": True, "group": "index",
     "spot_symbol": "^SPX"},
    {"key": "IWM",  "label": "IWM",  "desc": "Russell 2000 ETF",
     "cadence": CADENCE_DAILY, "hint": "Mon-Fri", "validated": False, "group": "index"},

    # ── Non-daily: ETFs ──
    {"key": "SMH",  "label": "SMH",  "desc": "Semiconductors ETF",
     "cadence": CADENCE_NON_DAILY, "hint": "weekly", "validated": False, "group": "semis"},
    {"key": "GLD",  "label": "GLD",  "desc": "Gold ETF",
     "cadence": CADENCE_NON_DAILY, "hint": "2-3×/wk", "validated": False, "group": "gold"},

    # ── Non-daily: leveraged ETFs ──
    # Kept in their own group and never pooled with the single names. A 3x
    # fund rebalances its exposure into the close, which mechanically pushes
    # the last half hour further in the day's direction — a structural reason
    # to expect MORE afternoon continuation here than in QQQ, working against
    # a hold-to-close credit spread.
    {"key": "TQQQ", "label": "TQQQ", "desc": "3× Nasdaq 100",
     "cadence": CADENCE_NON_DAILY, "hint": "2-3×/wk", "validated": False, "group": "levered"},
    {"key": "SOXL", "label": "SOXL", "desc": "3× Semiconductors",
     "cadence": CADENCE_NON_DAILY, "hint": "2-3×/wk", "validated": False, "group": "levered"},

    # ── Non-daily: single names ──
    # `group` marks the correlation cluster. NVDA, AVGO, SMH and SOXL are one
    # semiconductor trade wearing four tickers; their breaches land on the
    # same days, so counting them as independent observations inflates the
    # sample by ~4x. See pooled_breach_rate(), which clusters by DATE.
    {"key": "NVDA", "label": "NVDA", "desc": "Nvidia",
     "cadence": CADENCE_NON_DAILY, "hint": "2-3×/wk", "validated": False, "group": "semis"},
    {"key": "AVGO", "label": "AVGO", "desc": "Broadcom",
     "cadence": CADENCE_NON_DAILY, "hint": "2-3×/wk", "validated": False, "group": "semis"},
    {"key": "TSLA", "label": "TSLA", "desc": "Tesla",
     "cadence": CADENCE_NON_DAILY, "hint": "2-3×/wk", "validated": False, "group": "megacap"},
    {"key": "META", "label": "META", "desc": "Meta Platforms",
     "cadence": CADENCE_NON_DAILY, "hint": "2-3×/wk", "validated": False, "group": "megacap"},
    {"key": "GOOGL", "label": "GOOGL", "desc": "Alphabet",
     "cadence": CADENCE_NON_DAILY, "hint": "2-3×/wk", "validated": False, "group": "megacap"},
    {"key": "MSFT", "label": "MSFT", "desc": "Microsoft",
     "cadence": CADENCE_NON_DAILY, "hint": "2-3×/wk", "validated": False, "group": "megacap"},
]

BY_KEY = {t["key"]: t for t in UNIVERSE}


def universe(cadence: str | None = None) -> list[dict]:
    return [t for t in UNIVERSE if cadence is None or t["cadence"] == cadence]


def spot_symbol(key: str) -> str:
    """The symbol to fetch bars for — usually the key, ^SPX for SPX."""
    return BY_KEY.get(key, {}).get("spot_symbol", key)


# ── Building one session record ───────────────────────────────────────────

def _to_et(df: pd.DataFrame) -> pd.DataFrame:
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    return df.set_axis(idx.tz_convert(ET))


def session_records(df: pd.DataFrame, ticker: str, interval: str,
                    today: object = None) -> list[dict]:
    """One record per finished trading day in `df`.

    Shared by the accumulator and the backfill so the two can never drift
    into computing the range differently — the only thing that varies is the
    window end, which is a function of the interval and is stamped on every
    record.
    """
    if df is None or df.empty or "Close" not in df:
        return []
    window_end = WINDOWS.get(interval)
    if window_end is None:
        raise ValueError(f"no measurement window defined for interval {interval!r}")

    df = _to_et(df).dropna(subset=["Close"]).sort_index()
    # Normalised through Timestamp so a str, date, datetime or Timestamp all
    # land on a date. Comparing a datetime.date against a string is silently
    # False, which would disable the unfinished-session guard below without
    # raising — the exact failure mode it exists to prevent.
    today = pd.Timestamp(today).date() if today is not None \
        else pd.Timestamp.now(tz=ET).date()
    # An hourly grid needs at least the 09:30 and 10:30 bars; a 5m grid
    # should have ~30. Require enough that a truncated feed cannot pass as a
    # narrow range.
    min_bars = 2 if window_end <= 11 * 60 + 30 else 6

    out = []
    for day, g in df.groupby(df.index.date):
        t = g.index
        mins = t.hour * 60 + t.minute
        morning = g[(mins >= MORNING_START_MIN) & (mins < window_end)]
        session = g[(mins >= MORNING_START_MIN) & (mins <= REGULAR_CLOSE_MIN)]
        if len(morning) < min_bars or session.empty:
            continue

        hi = float(morning["High"].max())
        lo = float(morning["Low"].min())
        if not np.isfinite(hi) or not np.isfinite(lo) or hi <= lo:
            continue

        last_min = int(session.index[-1].hour * 60 + session.index[-1].minute)
        # An unfinished session is not a data point: a "close" read at 12:35
        # is just a midday print wearing the wrong name.
        if day == today and last_min < REGULAR_CLOSE_MIN - 5:
            continue

        read_px = float(morning["Close"].iloc[-1])
        close_px = float(session["Close"].iloc[-1])
        rng = hi - lo
        pos = (read_px - lo) / rng * 100.0
        above_mid = pos > 50.0

        out.append({
            "ticker": ticker,
            "date": str(day),
            "interval": interval,
            "window_end": window_end,          # 720 = noon, 690 = 11:30
            "high": hi, "low": lo,
            "range_pct": rng / lo * 100.0,
            "read": read_px,                   # price at window_end
            "pos_pct": pos,
            "close": close_px,
            "above_mid": bool(above_mid),
            # The breach the gate is about: closed through the FAR side of
            # the morning range from where the read sat. Session close only —
            # a day that traded through and came back does not count.
            "breach": bool((above_mid and close_px < lo)
                           or (not above_mid and close_px > hi)),
            "closed_below_low": bool(close_px < lo),
            "closed_above_high": bool(close_px > hi),
            "early_close": bool(last_min <= EARLY_CLOSE_MIN + 30),
            "close_vs_read_pct": (close_px - read_px) / read_px * 100.0,
            # Afternoon travel, in the same units as the morning range. This
            # is what makes the gate portable: "70% of the range" means a
            # completely different number of afternoon moves on TSLA than on
            # QQQ, and this column is what lets that be normalised later.
            "afternoon_range_pct": _afternoon_range_pct(g, mins, window_end),
        })
    return out


def _afternoon_range_pct(g: pd.DataFrame, mins, window_end: int) -> float | None:
    """High-low of window_end -> close, as a % of the price at window_end."""
    aft = g[(mins >= window_end) & (mins <= REGULAR_CLOSE_MIN)]
    if aft.empty:
        return None
    hi, lo = float(aft["High"].max()), float(aft["Low"].min())
    ref = float(aft["Open"].iloc[0]) if "Open" in aft else float(aft["Close"].iloc[0])
    if not np.isfinite(hi) or not np.isfinite(lo) or not ref:
        return None
    return (hi - lo) / ref * 100.0


# ── Storage ───────────────────────────────────────────────────────────────

def _path(source: str, date_str: str) -> str:
    return os.path.join(SNAP_DIR, f"{source}_{date_str}.json")


def save_records(records: list[dict], source: str) -> list[str]:
    """Write records grouped by date. Returns the paths written.

    Re-running a day overwrites it rather than appending, so a re-run after a
    partial failure repairs the day instead of double-counting it.
    """
    if not records:
        return []
    os.makedirs(SNAP_DIR, exist_ok=True)
    by_date: dict[str, list[dict]] = {}
    for r in records:
        by_date.setdefault(r["date"], []).append(r)

    written = []
    for date_str, rows in sorted(by_date.items()):
        path = _path(source, date_str)
        existing = {}
        if os.path.exists(path):
            try:
                with open(path) as fh:
                    prev = json.load(fh)
                existing = {(r["ticker"], r.get("interval")): r
                            for r in prev.get("rows", [])}
            except (OSError, ValueError, KeyError):
                existing = {}
        for r in rows:
            existing[(r["ticker"], r.get("interval"))] = r
        payload = {
            "date": date_str,
            "source": source,
            "written_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "rows": sorted(existing.values(), key=lambda r: r["ticker"]),
        }
        with open(path, "w") as fh:
            json.dump(payload, fh, indent=1, sort_keys=True)
        written.append(path)
    return written


def load_records(source: str | None = None) -> pd.DataFrame:
    """Every stored record as a frame. Empty frame when nothing is stored."""
    pattern = f"{source}_*.json" if source else "*.json"
    rows = []
    for path in sorted(glob.glob(os.path.join(SNAP_DIR, pattern))):
        try:
            with open(path) as fh:
                payload = json.load(fh)
        except (OSError, ValueError):
            continue
        src = payload.get("source", "unknown")
        for r in payload.get("rows", []):
            rows.append({**r, "source": src})
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return df.sort_values(["date", "ticker"]).reset_index(drop=True)


# ── Reading the record back ───────────────────────────────────────────────

def observed_cadence(df: pd.DataFrame, ticker: str) -> dict:
    """What the record actually shows about how often this ticker trades.

    Deliberately derived from observation rather than trusting the `hint`
    field: the point of accumulating is that guesses get replaced by counts.
    """
    sub = df[df["ticker"] == ticker] if not df.empty else df
    if sub.empty:
        return {"sessions": 0, "weekdays": {}, "first": None, "last": None}
    days = pd.to_datetime(sub["date"])
    return {
        "sessions": int(len(sub)),
        "weekdays": days.dt.day_name().value_counts().to_dict(),
        "first": str(sub["date"].min()),
        "last": str(sub["date"].max()),
    }


# The Spreads tab's zone boundaries, restated here so the study can bucket
# sessions without importing the tab (which would drag streamlit into a
# headless script — and spreads.py imports THIS module, so the dependency
# only runs one way). test_range_history.py asserts the two agree on every
# boundary; if the tab ever retunes a threshold, that test fails rather than
# the store silently mis-bucketing every session.
PUT_GREEN_MIN = 70.0
PUT_AMBER_MIN = 60.0
CALL_MAX = 50.0


def zone_of(pos_pct: float) -> str:
    if pos_pct >= PUT_GREEN_MIN:
        return "put_green"
    if pos_pct >= PUT_AMBER_MIN:
        return "put_amber"
    if pos_pct >= CALL_MAX:
        return "put_block"
    return "call"


def pooled_breach_rate(df: pd.DataFrame, tickers: list[str] | None = None,
                       zone: str | None = None) -> dict:
    """Breach rate with the sample size stated two ways.

    `n_rows` counts ticker-days. `n_days` counts distinct DATES, which is the
    number that matters: NVDA, AVGO, SMH and SOXL breach on the same days, so
    six semis on one bad afternoon is one observation of "semis reversed",
    not six independent coin flips. Quoting n_rows would shrink the interval
    by roughly sqrt(tickers-per-day) for free, which is exactly the error
    that makes a thin study look conclusive.
    """
    if df.empty:
        return {"n_rows": 0, "n_days": 0, "breaches": 0, "rate_pct": None,
                "breach_days": 0, "day_rate_pct": None}
    sub = df
    if tickers:
        sub = sub[sub["ticker"].isin(tickers)]
    if zone:
        sub = sub[sub["pos_pct"].map(zone_of) == zone]
    if sub.empty:
        return {"n_rows": 0, "n_days": 0, "breaches": 0, "rate_pct": None,
                "breach_days": 0, "day_rate_pct": None}

    n_rows = int(len(sub))
    breaches = int(sub["breach"].sum())
    days = sub.groupby("date")["breach"].any()
    return {
        "n_rows": n_rows,
        "n_days": int(days.shape[0]),
        "breaches": breaches,
        "rate_pct": breaches / n_rows * 100.0,
        "breach_days": int(days.sum()),
        "day_rate_pct": float(days.mean() * 100.0),
    }


def window_comparison(df: pd.DataFrame) -> pd.DataFrame:
    """Where both windows cover the same ticker-day, how far apart are they?

    This is the check that decides whether the hourly backfill is usable as
    evidence or only as context. Until it says the 11:30 read tracks the
    12:00 read closely, the two must stay separate.
    """
    if df.empty or "window_end" not in df:
        return pd.DataFrame()
    noon = df[df["window_end"] == 720].set_index(["ticker", "date"])
    early = df[df["window_end"] == 690].set_index(["ticker", "date"])
    common = noon.index.intersection(early.index)
    if len(common) == 0:
        return pd.DataFrame()
    return pd.DataFrame({
        "ticker": [t for t, _ in common],
        "date": [d for _, d in common],
        "pos_noon": noon.loc[common, "pos_pct"].values,
        "pos_1130": early.loc[common, "pos_pct"].values,
        "pos_diff": noon.loc[common, "pos_pct"].values - early.loc[common, "pos_pct"].values,
        "zone_noon": [zone_of(p) for p in noon.loc[common, "pos_pct"].values],
        "zone_1130": [zone_of(p) for p in early.loc[common, "pos_pct"].values],
        "breach_noon": noon.loc[common, "breach"].values,
        "breach_1130": early.loc[common, "breach"].values,
    })


def coverage(df: pd.DataFrame) -> pd.DataFrame:
    """Per ticker: how much record exists, and how far from a usable sample.

    The target is the 43 green-zone sessions the QQQ/SPY study rested on.
    """
    if df.empty:
        return pd.DataFrame(columns=["ticker", "sessions", "green_sessions",
                                     "first", "last", "pct_of_target"])
    rows = []
    for ticker, sub in df.groupby("ticker"):
        green = int((sub["pos_pct"].map(zone_of) == "put_green").sum())
        rows.append({
            "ticker": ticker,
            "sessions": int(len(sub)),
            "green_sessions": green,
            "first": str(sub["date"].min()),
            "last": str(sub["date"].max()),
            "pct_of_target": round(green / 43.0 * 100.0, 1),
        })
    return pd.DataFrame(rows).sort_values("green_sessions", ascending=False)
