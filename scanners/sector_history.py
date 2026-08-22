# scanners/sector_history.py — time-series history for the Sector Rotation table.
#
# Why this exists: the rotation table is computed off `close.iloc[-1]`, and
# during market hours that bar is still forming. Refresh at 10:05 and again
# at 11:40 and every RS, RSI and Trade Idea has moved, because the inputs
# genuinely moved. Without a record of what the table said yesterday there
# is no way to tell "this sector is churning" from "I keep looking at it at
# different moments of the same day".
#
# Two independent sources of history, deliberately:
#
#   1. BACKFILL (backfill_from_prices) — replays compute_row() over the
#      trailing price series we already download for the live scan, so the
#      history tab has months of data the first time it is opened, with
#      nothing stored anywhere. Every point is a SETTLED close, so it is the
#      honest answer to "how much does this really move day to day". This is
#      the primary source and needs no infrastructure at all.
#
#   2. SNAPSHOTS (save_snapshot) — what the scanner ACTUALLY printed on a
#      given day, written once per session after the close by
#      scripts/headless_sector_rotation.py (GitHub Actions has contents:
#      write; the Streamlit app does not, and would spam a file per page
#      load, so the app only ever reads). Backfill can drift from this if
#      the thresholds in sector_rotation.py are ever retuned — snapshots are
#      the audit trail that survives such a change, backfill is always
#      "what today's code would have said".
#
# Storage mirrors scanners/scan_history.py: one JSON file per
# (date, slot) under data/sector_rotation/, holding a flat list of rows.

from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timedelta

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP_DIR = os.path.join(ROOT, "data", "sector_rotation")

# ~18 months. Sector leadership cycles run quarters, not days, so a year-plus
# is the shortest window in which "XLE led for two months then handed off" is
# even visible.
RETENTION_DAYS = 550

# Columns carried from a live scan row into a stored snapshot row. Kept
# snake_case on disk (scan_history convention) and mapped back on read.
_FIELD_MAP = {
    "Ticker":      "ticker",
    "Sector":      "sector",
    "Rank":        "rank",
    "Price":       "price",
    "1M Ret %":    "ret_1m",
    "3M Ret %":    "ret_3m",
    "RS vs SPY":   "rs",
    "RS Trend":    "rs_trend",
    "RSI":         "rsi",
    "Vol Ratio":   "vol_ratio",
    "vs EMA9":     "vs_ema9",
    "vs SMA50":    "vs_sma50",
    "above_sma50": "above_sma50",
    "Trade Idea":  "idea",
}
_REVERSE_MAP = {v: k for k, v in _FIELD_MAP.items()}


# ── Snapshot store ─────────────────────────────────────────────────────────────

def _path(date_str: str, slot: str) -> str:
    return os.path.join(SNAP_DIR, f"{date_str}_{slot}.json")


def to_snapshot_rows(df: pd.DataFrame) -> list[dict]:
    """Live-scan DataFrame → storable rows (snake_case, JSON-safe)."""
    if df is None or df.empty:
        return []
    rows = []
    for _, r in df.iterrows():
        row = {}
        for col, key in _FIELD_MAP.items():
            if col not in df.columns:
                continue
            v = r[col]
            # numpy scalars are not JSON-serialisable
            if hasattr(v, "item"):
                v = v.item()
            row[key] = v
        rows.append(row)
    return rows


def save_snapshot(rows: list[dict], mkt: dict, date_str: str, slot: str = "close") -> str:
    """Write one session's rows to disk. Returns the path written."""
    os.makedirs(SNAP_DIR, exist_ok=True)
    path = _path(date_str, slot)
    payload = {
        "date":       date_str,
        "slot":       slot,
        "saved_utc":  datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "market":     mkt or {},
        "rows":       rows,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return path


def load_snapshots(days: int | None = None) -> list[dict]:
    """All stored snapshots, oldest first, optionally limited to the last
    `days` calendar days."""
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
    return sorted(out, key=lambda s: (s.get("date", ""), s.get("slot", "")))


def prune_old(today_date_str: str, retention_days: int = RETENTION_DAYS) -> list[str]:
    """Delete snapshots older than the retention window. Returns paths removed."""
    cutoff = (datetime.strptime(today_date_str, "%Y-%m-%d")
              - timedelta(days=retention_days)).strftime("%Y-%m-%d")
    removed = []
    for p in glob.glob(os.path.join(SNAP_DIR, "*.json")):
        if os.path.basename(p).split("_")[0] < cutoff:
            try:
                os.remove(p)
                removed.append(p)
            except OSError:
                continue
    return removed


def snapshots_to_frame(snapshots: list[dict]) -> pd.DataFrame:
    """Stored snapshots → long DataFrame with one row per (date, ticker)."""
    recs = []
    for s in snapshots:
        for r in s.get("rows", []):
            rec = {_REVERSE_MAP.get(k, k): v for k, v in r.items()}
            rec["Date"] = s.get("date", "")
            rec["Slot"] = s.get("slot", "")
            recs.append(rec)
    df = pd.DataFrame(recs)
    if not df.empty and "Rank" not in df.columns:
        df = _stamp_ranks(df)
    return df


# ── Backfill: replay the live scan over past settled closes ────────────────────

def _stamp_ranks(df: pd.DataFrame) -> pd.DataFrame:
    """Add a per-date Rank column (1 = highest RS) to a long frame."""
    df = df.sort_values(["Date", "RS vs SPY"], ascending=[True, False]).copy()
    df["Rank"] = df.groupby("Date").cumcount() + 1
    return df


def backfill_from_prices(price_map: dict, spy_close, sectors: list[tuple[str, str]],
                         sessions: int = 120, drop_live_bar: bool = True,
                         progress_fn=None) -> pd.DataFrame:
    """Recompute the rotation table as it would have looked on each of the
    last `sessions` SETTLED closes.

    price_map     {ticker: DataFrame with Close/Volume}, as already fetched
                  for the live scan — no extra network calls are made.
    spy_close     SPY close series (the RS denominator).
    sectors       [(ticker, name), ...] — the SECTORS list.
    sessions      how many past closes to replay.
    drop_live_bar drop today's still-forming bar so every point in the
                  series is a settled close and the history is comparable
                  bar to bar. This is the whole reason the backfilled series
                  is steadier than consecutive intraday refreshes.

    Returns a long DataFrame: Date, Ticker, Sector, Rank, RS vs SPY, RSI,
    Trade Idea, ... — one row per (date, ticker).
    """
    from scanners.sector_rotation import _is_live_bar, compute_row

    if spy_close is None or len(spy_close) < 80:
        return pd.DataFrame()

    if drop_live_bar and _is_live_bar(spy_close):
        spy_close = spy_close.iloc[:-1]

    # Replay dates: the trailing `sessions` closes that still leave enough
    # history behind them for a 63-day RS plus the 20-day RS-trend offset.
    min_bars = 84
    if len(spy_close) <= min_bars:
        return pd.DataFrame()
    dates = list(spy_close.index[min_bars:])[-sessions:]
    if not dates:
        return pd.DataFrame()

    # Pre-slice each ticker once, aligned on SPY's calendar so a ticker with
    # a missing bar can never silently compare a different window than the
    # benchmark it is being divided by.
    series: dict[str, tuple] = {}
    for ticker, name in sectors:
        df = price_map.get(ticker)
        if df is None or getattr(df, "empty", True):
            continue
        close = df["Close"].squeeze()
        vol = df["Volume"].squeeze() if "Volume" in df.columns else None
        close = close.reindex(spy_close.index).ffill().dropna()
        if vol is not None:
            vol = vol.reindex(spy_close.index).ffill().dropna()
        if len(close) < min_bars:
            continue
        series[ticker] = (name, close, vol)

    recs = []
    total = len(dates)
    for i, d in enumerate(dates):
        if progress_fn and (i % 10 == 0 or i == total - 1):
            progress_fn(i, total, pd.Timestamp(d).strftime("%Y-%m-%d"))
        bench = spy_close.loc[:d]
        for ticker, (name, close, vol) in series.items():
            try:
                c = close.loc[:d]
                v = vol.loc[:d] if vol is not None else None
                row = compute_row(ticker, name, c, v, bench)
            except Exception:
                row = None
            if row:
                row["Date"] = pd.Timestamp(d).strftime("%Y-%m-%d")
                recs.append(row)

    df = pd.DataFrame(recs)
    if df.empty:
        return df
    return _stamp_ranks(df).reset_index(drop=True)


# ── Change / stability metrics ─────────────────────────────────────────────────

def rank_deltas(history: pd.DataFrame, current: pd.DataFrame) -> dict:
    """{ticker: rank change vs the most recent history date}.

    Positive = moved UP the leaderboard (rank 5 → 2 is +3). None when the
    ticker has no prior observation to compare against.
    """
    if history is None or history.empty or current is None or current.empty:
        return {}
    if "Rank" not in current.columns:
        current = current.reset_index(drop=True)
        current = current.assign(Rank=current.index + 1)
    last_date = history["Date"].max()
    prev = history[history["Date"] == last_date].set_index("Ticker")["Rank"].to_dict()
    out = {}
    for _, r in current.iterrows():
        p = prev.get(r["Ticker"])
        out[r["Ticker"]] = None if p is None else int(p) - int(r["Rank"])
    return out


def stability_report(history: pd.DataFrame) -> pd.DataFrame:
    """Per-sector: how much does this row ACTUALLY move day to day?

    Columns:
      Sessions        observations in the window
      Avg Rank        mean leaderboard position
      Best / Worst    best and worst rank reached
      Rank Churn      mean absolute rank change between consecutive sessions
      RS Churn        mean absolute daily change in RS vs SPY
      Idea Flips      how many times Trade Idea changed
      Idea Hold       average consecutive sessions an idea survives
      Current Streak  sessions the current Trade Idea has held
    """
    if history is None or history.empty:
        return pd.DataFrame()

    rows = []
    for ticker, g in history.sort_values("Date").groupby("Ticker"):
        ranks = g["Rank"].astype(float)
        rs = g["RS vs SPY"].astype(float)
        ideas = list(g["Trade Idea"])

        flips = sum(1 for a, b in zip(ideas, ideas[1:]) if a != b)
        streak = 1
        for a, b in zip(reversed(ideas), reversed(ideas[:-1])):
            if a == b:
                streak += 1
            else:
                break

        rows.append({
            "Ticker":         ticker,
            "Sector":         g["Sector"].iloc[-1],
            "Sessions":       int(len(g)),
            "Avg Rank":       round(float(ranks.mean()), 1),
            "Best":           int(ranks.min()),
            "Worst":          int(ranks.max()),
            "Rank Churn":     round(float(ranks.diff().abs().mean()), 2) if len(g) > 1 else 0.0,
            "RS Churn":       round(float(rs.diff().abs().mean()), 4) if len(g) > 1 else 0.0,
            "Idea Flips":     flips,
            "Idea Hold":      round(len(g) / (flips + 1), 1),
            "Current Idea":   ideas[-1] if ideas else "",
            "Current Streak": streak if ideas else 0,
        })

    return (pd.DataFrame(rows)
            .sort_values("Avg Rank")
            .reset_index(drop=True))


def churn_summary(history: pd.DataFrame, top_n: int = 3) -> dict:
    """Window-level answer to "does this thing change as fast as it feels?".

    top_turnover_pct   % of sessions where the top-N set gained/lost a member
    median_rank_move   median absolute rank change per sector per session
    idea_change_pct    % of (sector, session) observations where Trade Idea
                       differed from the prior session
    leader_changes     how many times the #1 sector changed hands
    """
    if history is None or history.empty or history["Date"].nunique() < 2:
        return {}

    dates = sorted(history["Date"].unique())
    by_date = {d: g for d, g in history.groupby("Date")}

    top_sets, leaders = [], []
    for d in dates:
        g = by_date[d].sort_values("Rank")
        top_sets.append(frozenset(g["Ticker"].head(top_n)))
        leaders.append(g["Ticker"].iloc[0])

    turnover = sum(1 for a, b in zip(top_sets, top_sets[1:]) if a != b)
    leader_changes = sum(1 for a, b in zip(leaders, leaders[1:]) if a != b)

    moves, flips, obs = [], 0, 0
    for _, g in history.sort_values("Date").groupby("Ticker"):
        moves.extend(g["Rank"].astype(float).diff().abs().dropna().tolist())
        ideas = list(g["Trade Idea"])
        flips += sum(1 for a, b in zip(ideas, ideas[1:]) if a != b)
        obs += max(0, len(ideas) - 1)

    transitions = len(dates) - 1
    return {
        "sessions":          len(dates),
        "first_date":        dates[0],
        "last_date":         dates[-1],
        "top_n":             top_n,
        "top_turnover_pct":  round(turnover / transitions * 100, 0),
        "leader_changes":    leader_changes,
        "median_rank_move":  round(float(pd.Series(moves).median()), 1) if moves else 0.0,
        "max_rank_move":     round(float(pd.Series(moves).max()), 0) if moves else 0.0,
        "idea_change_pct":   round(flips / obs * 100, 0) if obs else 0.0,
    }


def leadership_spells(history: pd.DataFrame, top_n: int = 3) -> list[dict]:
    """Contiguous stretches each sector spent inside the top N, newest first.

    This is the view that actually answers "is XLE really leading, or did it
    poke into the top 3 for a day?" — a two-day spell and a six-week spell
    look identical in a single-day snapshot.
    """
    if history is None or history.empty:
        return []

    dates = sorted(history["Date"].unique())
    spells, open_spell = [], {}
    for d in dates:
        g = history[history["Date"] == d].sort_values("Rank")
        top = set(g["Ticker"].head(top_n))
        for t in list(open_spell):
            if t not in top:
                s = open_spell.pop(t)
                s["end"] = s["last_seen"]
                spells.append(s)
        for t in top:
            if t in open_spell:
                open_spell[t]["last_seen"] = d
                open_spell[t]["sessions"] += 1
            else:
                open_spell[t] = {"ticker": t, "start": d, "last_seen": d,
                                 "sessions": 1, "ongoing": False}
    for t, s in open_spell.items():
        s["end"] = s["last_seen"]
        s["ongoing"] = True
        spells.append(s)

    return sorted(spells, key=lambda s: s["start"], reverse=True)
