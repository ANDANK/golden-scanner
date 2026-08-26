#!/usr/bin/env python3
"""
scripts/headless_noon_reversal.py — morning-range / noon-position study.

THE QUESTION
    Mark each session's High and Low from the open (09:30 ET) to noon (12:00
    ET). Take the price at noon. If it sits ABOVE the midpoint of that
    morning range, how often does the session nonetheless CLOSE below the
    morning low? And the mirror: noon below the midpoint, closing above the
    morning high?

    That is a full reversal through the far side of the morning range — the
    market spending its morning in one half of the range and finishing
    outside the other end of it.

DEFINITIONS, stated because each one changes the answer
  * Morning window  bars timestamped 09:30 <= t < 12:00 ET. High is the max
    of those bars' highs, Low the min of their lows.
  * Noon price      the CLOSE of the last morning bar (the 11:55 bar on 5m
    data), not the open of the 12:00 bar. Both are defensible; this one uses
    only information available AT noon.
  * Position %      (noon - low) / (high - low) * 100. 0 = noon sat exactly
    on the morning low, 100 = exactly on the high, 50 = the midpoint.
  * Close           the last regular-session bar's close (16:00 ET, or 13:00
    on an early-close day — those are flagged and counted separately).
  * Reversal        close < morning low when noon was above the midpoint, or
    close > morning high when noon was below it. Session close only: a day
    that traded through the level intraday and came back does NOT count.

DATA LIMIT — read before quoting the sample size
    Yahoo serves at most 60 CALENDAR days of intraday bars, so a 5-minute
    request yields roughly 41 trading sessions, not 90. Every figure here
    rests on that sample, which is thin. The script prints the exact count
    and refuses to pretend otherwise.

Usage:
  python scripts/headless_noon_reversal.py
Env:
  NOON_TICKERS   comma-separated (default "QQQ,SPY")
  NOON_INTERVAL  bar size (default "5m")
  NOON_PERIOD    lookback (default "60d")
"""

import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TICKERS = [t.strip().upper() for t in os.environ.get("NOON_TICKERS", "QQQ,SPY").split(",") if t.strip()]
INTERVAL = os.environ.get("NOON_INTERVAL", "5m")
PERIOD = os.environ.get("NOON_PERIOD", "60d")
OUT_DIR = os.path.join(ROOT, "data", "noon_reversal")
ET = "US/Eastern"

MORNING_START = (9, 30)
NOON = (12, 0)
REGULAR_CLOSE = (16, 0)
EARLY_CLOSE = (13, 0)


def log(msg):
    print(f"[noon] {msg}", flush=True)


def _to_et(df: pd.DataFrame) -> pd.DataFrame:
    """Index in US/Eastern. Yahoo returns intraday bars tz-aware but not
    necessarily in exchange time, and a naive index would silently shift the
    whole 09:30/12:00 window."""
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    return df.set_axis(idx.tz_convert(ET))


def sessions(df: pd.DataFrame) -> list[dict]:
    """One record per trading day."""
    out = []
    for day, g in df.groupby(df.index.date):
        g = g.sort_index()
        t = g.index
        mins = t.hour * 60 + t.minute
        m_start = MORNING_START[0] * 60 + MORNING_START[1]
        m_end = NOON[0] * 60 + NOON[1]

        morning = g[(mins >= m_start) & (mins < m_end)]
        session = g[(mins >= m_start) & (mins <= REGULAR_CLOSE[0] * 60)]
        if len(morning) < 6 or session.empty:
            continue  # truncated feed or a stub day — not a session

        hi = float(morning["High"].max())
        lo = float(morning["Low"].min())
        if not np.isfinite(hi) or not np.isfinite(lo) or hi <= lo:
            continue

        noon_px = float(morning["Close"].iloc[-1])
        close_px = float(session["Close"].iloc[-1])
        last_min = int(session.index[-1].hour * 60 + session.index[-1].minute)
        early = last_min <= EARLY_CLOSE[0] * 60 + 30

        rng = hi - lo
        pos = (noon_px - lo) / rng * 100.0
        above_mid = pos > 50.0

        out.append({
            "date": str(day),
            "high": hi, "low": lo, "range_pct": rng / lo * 100.0,
            "noon": noon_px, "close": close_px,
            "pos_pct": pos,
            "above_mid": bool(above_mid),
            "closed_above_high": bool(close_px > hi),
            "closed_below_low": bool(close_px < lo),
            "closed_inside": bool(lo <= close_px <= hi),
            # The reversal the question asks about: finished through the
            # opposite end of the morning range from where noon sat.
            "reversal": bool((above_mid and close_px < lo) or (not above_mid and close_px > hi)),
            # The same-side continuation, for contrast.
            "continuation": bool((above_mid and close_px > hi) or (not above_mid and close_px < lo)),
            "early_close": bool(early),
            "close_vs_noon_pct": (close_px - noon_px) / noon_px * 100.0,
        })
    return out


def summarise(rows: list[dict]) -> dict:
    def block(sub, label):
        n = len(sub)
        if not n:
            return None
        rev = sum(r["reversal"] for r in sub)
        con = sum(r["continuation"] for r in sub)
        ins = sum(r["closed_inside"] for r in sub)
        drift = np.array([r["close_vs_noon_pct"] for r in sub])
        return {
            "label": label, "n": n,
            "reversal": rev, "reversal_pct": rev / n * 100.0,
            "continuation": con, "continuation_pct": con / n * 100.0,
            "inside": ins, "inside_pct": ins / n * 100.0,
            "mean_drift": float(drift.mean()), "median_drift": float(np.median(drift)),
        }

    above = [r for r in rows if r["above_mid"]]
    below = [r for r in rows if not r["above_mid"]]

    deciles = []
    for lo in range(0, 100, 10):
        sub = [r for r in rows if lo <= r["pos_pct"] < lo + 10 or (lo == 90 and r["pos_pct"] >= 100)]
        if sub:
            deciles.append({
                "band": f"{lo}-{lo+10}%", "n": len(sub),
                "closed_above_high": sum(r["closed_above_high"] for r in sub),
                "closed_below_low": sum(r["closed_below_low"] for r in sub),
                "closed_inside": sum(r["closed_inside"] for r in sub),
                "mean_drift": float(np.mean([r["close_vs_noon_pct"] for r in sub])),
            })

    return {
        "n_sessions": len(rows),
        "n_early_close": sum(r["early_close"] for r in rows),
        "date_min": min((r["date"] for r in rows), default=None),
        "date_max": max((r["date"] for r in rows), default=None),
        "above_mid": block(above, "Noon ABOVE midpoint → closed BELOW morning low"),
        "below_mid": block(below, "Noon BELOW midpoint → closed ABOVE morning high"),
        "deciles": deciles,
        "mean_range_pct": float(np.mean([r["range_pct"] for r in rows])) if rows else None,
    }


def run():
    import yfinance as yf

    os.makedirs(OUT_DIR, exist_ok=True)
    payload = {"generated": datetime.utcnow().isoformat() + "Z",
               "interval": INTERVAL, "period": PERIOD, "tickers": {}}

    for tkr in TICKERS:
        log(f"{tkr}: downloading {PERIOD} of {INTERVAL} bars…")
        df = yf.download(tkr, period=PERIOD, interval=INTERVAL,
                         progress=False, auto_adjust=False, prepost=False)
        if df is None or df.empty:
            log(f"{tkr}: no data returned — skipping.")
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = _to_et(df.dropna(subset=["Close"]))

        rows = sessions(df)
        if not rows:
            log(f"{tkr}: no usable sessions — skipping.")
            continue
        summ = summarise(rows)
        payload["tickers"][tkr] = {"summary": summ, "sessions": rows}

        log(f"{tkr}: {summ['n_sessions']} sessions "
            f"({summ['date_min']} → {summ['date_max']}), "
            f"{summ['n_early_close']} early-close day(s)")
        for key in ("above_mid", "below_mid"):
            b = summ[key]
            if b:
                log(f"    {b['label']}")
                log(f"      n={b['n']}  reversal={b['reversal']} ({b['reversal_pct']:.1f}%)  "
                    f"continuation={b['continuation']} ({b['continuation_pct']:.1f}%)  "
                    f"inside={b['inside']} ({b['inside_pct']:.1f}%)")

    if not payload["tickers"]:
        log("Nothing computed.")
        return
    path = os.path.join(OUT_DIR, "latest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
    log(f"Wrote {path}")


if __name__ == "__main__":
    run()
