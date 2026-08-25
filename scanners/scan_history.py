# scanners/scan_history.py — shared snapshot history engine used by Best
# Scanners, OverKill and Fast Score to power "New" badges, first-found dates,
# and track-record (% performance since first sighting) tables.
#
# Any new caller MUST add its `kind` to _CONFIG below — the three functions
# that read _CONFIG index it directly, so an unregistered kind raises
# KeyError on the first prune/rollup rather than silently doing nothing.
#
# Write-once-a-day, read-anywhere design: only the headless email scripts
# (run once daily by GitHub Actions, which have `contents: write` on the
# workflow) call save_snapshot()/prune_old(). The interactive Streamlit app
# has no git write access and would spam a new file per page load anyway, so
# it only ever calls the read-side functions below. Both surfaces read the
# exact same on-disk JSON, so "New" / first-found / track-record always
# agree between the email and the live page.
#
# One JSON file per (kind, tag, date): data/<kind>/<date>_<tag>.json, each
# holding a flat list of row dicts. The schema of each row is caller-defined
# (Best Scanners rows carry verdict/combo/edge fields, OverKill rows carry
# color/stars) — this module only ever looks at "ticker" and "price".

from __future__ import annotations
import os, json, glob
from datetime import datetime, timedelta

from data_loader import prefetch_tickers, get_price_history

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_ROOT = os.path.join(ROOT, "data")

# Per-scanner tuning: how far back "New" looks (in stored scan-days), how
# wide the track-record rollup window is, and when stored files get pruned
# (comfortably past the rollup window so a slow week never clips it short).
_CONFIG = {
    # Best Scanners signals are daily-bar, 10-90 day hold horizons — 90 days
    # of history is plenty to cover a full hold cycle.
    "best_scanners": dict(new_window_scans=7, rollup_days=90, retention_days=100),
    # OverKill dots are weekly/monthly cadence — 90 days would only hold
    # ~12 weekly dots (and just 3 monthly ones), too thin to be meaningful.
    # 6 months (~26 weekly / ~6 monthly data points) is a better balance.
    "overkill": dict(new_window_scans=7, rollup_days=182, retention_days=195),
    # Fast Score runs once a WEEK (Friday after the close), so a "scan" here
    # is a week, not a day. new_window_scans=4 therefore means "new within
    # roughly the last month" — the same intent the other two express in
    # days. Retention is a full year because 52 snapshots a year is tiny on
    # disk and a weekly signal needs that long a window before its track
    # record says anything.
    "fast_score": dict(new_window_scans=4, rollup_days=182, retention_days=400),
}


def _kind_dir(kind: str) -> str:
    return os.path.join(DATA_ROOT, kind)


def _file_path(kind: str, tag: str, date_str: str) -> str:
    return os.path.join(_kind_dir(kind), f"{date_str}_{tag}.json")


def save_snapshot(kind: str, tag: str, date_str: str, rows: list[dict]) -> str:
    """Write today's rows to disk (one row per ticker, each dict must have at
    least "ticker" and "price"). Returns the path written."""
    os.makedirs(_kind_dir(kind), exist_ok=True)
    path = _file_path(kind, tag, date_str)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"date": date_str, "tag": tag, "rows": rows}, f, indent=2)
    return path


def _load_all(kind: str, tag: str) -> list[dict]:
    """All stored snapshots for this (kind, tag), oldest first."""
    paths = sorted(glob.glob(os.path.join(_kind_dir(kind), f"*_{tag}.json")))
    out = []
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                out.append(json.load(f))
        except Exception:
            continue
    return out


def prune_old(kind: str, tag: str, today_date_str: str) -> list[str]:
    """Delete stored snapshot files older than this kind's retention window.
    Returns the list of removed paths."""
    retention_days = _CONFIG[kind]["retention_days"]
    cutoff = (datetime.strptime(today_date_str, "%Y-%m-%d") - timedelta(days=retention_days)).strftime("%Y-%m-%d")
    removed = []
    for p in glob.glob(os.path.join(_kind_dir(kind), f"*_{tag}.json")):
        date_part = os.path.basename(p).split("_")[0]
        if date_part < cutoff:
            try:
                os.remove(p)
                removed.append(p)
            except OSError:
                continue
    return removed


def _event_date(row: dict, fallback: str) -> str:
    """A row's own signal date if it has one (e.g. OverKill's dot date,
    which can lag the scan date that noticed it by several bars), else the
    scan-day fallback. Best Scanners rows never set "event_date" since its
    signals are same-day by construction, so they always use the scan date."""
    return row.get("event_date") or fallback


def annotate_new_and_first_found(kind: str, tag: str, today_date_str: str, today_rows: list[dict]) -> dict:
    """For today's rows (list of dicts with a "ticker" key), returns
    {ticker: {"is_new": bool, "first_found": "YYYY-MM-DD"}}.

    "New" = ticker did not appear in any of the last `new_window_scans`
    STORED scan-days before today (today's own file, if it already exists
    on disk, is excluded so a re-run never counts itself as history).
    first_found = the earliest _event_date() (within the rollup window)
    this ticker showed up under; if it isn't found in stored history at
    all, first_found is today's own event date (first-ever sighting)."""
    cfg = _CONFIG[kind]
    snapshots = [s for s in _load_all(kind, tag) if s["date"] != today_date_str]
    snapshots.sort(key=lambda s: s["date"])

    recent = snapshots[-cfg["new_window_scans"]:]
    recent_tickers = {r["ticker"] for s in recent for r in s["rows"]}

    cutoff = (datetime.strptime(today_date_str, "%Y-%m-%d") - timedelta(days=cfg["rollup_days"])).strftime("%Y-%m-%d")
    first_found: dict[str, str] = {}
    for s in snapshots:
        if s["date"] < cutoff:
            continue
        for r in s["rows"]:
            first_found.setdefault(r["ticker"], _event_date(r, s["date"]))

    out = {}
    for r in today_rows:
        t = r["ticker"]
        out[t] = {
            "is_new": t not in recent_tickers,
            "first_found": first_found.get(t, _event_date(r, today_date_str)),
        }
    return out


def rollup_window(kind: str, tag: str, today_date_str: str, today_rows: list[dict]) -> list[dict]:
    """Every distinct ticker seen within the rollup window (including
    today), each carrying whatever fields its snapshot row had (verdict,
    combo, scanners, stars, color, ...) plus "first_found" (the row's own
    _event_date()) and "first_price". Does NOT fetch current/high/low prices
    — call fetch_range_stats() separately and join, since that needs a live
    network round-trip this function intentionally doesn't own."""
    cfg = _CONFIG[kind]
    snapshots = [s for s in _load_all(kind, tag) if s["date"] != today_date_str]
    cutoff = (datetime.strptime(today_date_str, "%Y-%m-%d") - timedelta(days=cfg["rollup_days"])).strftime("%Y-%m-%d")

    first_seen: dict[str, dict] = {}
    for s in snapshots:
        if s["date"] < cutoff:
            continue
        for r in s["rows"]:
            if r["ticker"] not in first_seen:
                first_seen[r["ticker"]] = {
                    **r, "first_found": _event_date(r, s["date"]), "first_price": r.get("price"),
                }
    for r in today_rows:
        if r["ticker"] not in first_seen:
            first_seen[r["ticker"]] = {
                **r, "first_found": _event_date(r, today_date_str), "first_price": r.get("price"),
            }

    return sorted(first_seen.values(), key=lambda v: v["first_found"])


def _align_to_index(dt, index):
    """Make a naive datetime comparable to a price index that may be
    timezone-aware. Comparing the two directly raises TypeError, which the
    callers swallow -- so the ticker would silently vanish from the table
    rather than fail loudly. yfinance returns naive daily indexes today, but
    that has changed before and the guard costs nothing."""
    tz = getattr(index, "tz", None)
    if tz is None:
        return dt
    import pandas as pd
    ts = pd.Timestamp(dt)
    return ts.tz_localize(tz) if ts.tzinfo is None else ts.tz_convert(tz)


def directional_stats(pct, high, high_pct, low, low_pct, bearish: bool):
    """Re-express a row's performance in the CALL'S terms rather than the
    price's, and return (pct, best, best_pct, worst, worst_pct).

    For a bullish call the two are the same thing: price up is good, so the
    high is the best moment and the low the worst. For a bearish call they
    invert -- the trade wins when price FALLS, so the low is its best moment
    and the high its worst, and every percentage flips sign.

    This exists because showing a flipped Perf beside a raw High/Low put two
    sign conventions in one row: a Red row could read Perf +11.6% next to
    % High +0.0% and % Low -16.7%, which looks broken even though every
    figure is correct. Expressed this way, every row satisfies
    best >= perf >= worst regardless of direction, and one reading works for
    both tables."""
    if not bearish:
        return pct, high, high_pct, low, low_pct
    neg = lambda v: None if v is None else -v
    return neg(pct), low, neg(low_pct), high, neg(high_pct)


def track_record(kind: str, tag: str, today_date_str: str, today_rows: list[dict]) -> list[dict]:
    """The full 'how did our past picks do' rollup, ready to render: every
    distinct ticker in the window with first-found date/price, current
    price + % performance since first sighting, and the high/low close
    reached anywhere between first-found and today (+ % move to each) --
    sorted best current performer first (tickers with no fetchable price
    sort last, pct=None). high/low are raw/factual (never direction-
    adjusted) since they're a trading range, not a verdict -- a caller that
    needs a bearish-call-aware "Perf" (e.g. OverKill's Red dots) should
    adjust `pct` itself and re-sort; this function has no notion of color."""
    base = rollup_window(kind, tag, today_date_str, today_rows)
    stats = fetch_range_stats([(r["ticker"], r["first_found"]) for r in base])
    out = []
    for r in base:
        s = stats.get(r["ticker"])
        current = s["current"] if s else None
        high = s["high"] if s else None
        low = s["low"] if s else None
        first_price = r.get("first_price")

        def _pct(target):
            return (target - first_price) / first_price * 100 if target is not None and first_price else None

        out.append({
            **r, "current_price": current, "pct": _pct(current),
            "high": high, "high_pct": _pct(high), "low": low, "low_pct": _pct(low),
        })
    out.sort(key=lambda r: (r["pct"] is None, -(r["pct"] if r["pct"] is not None else 0)))
    return out


def star_tier_breakdown(track_rows: list[dict]) -> list[dict]:
    """Aggregate track_record() rows by star rating, so a caller can compare
    e.g. 3-star vs 4-star vs 5-star hit rate/average return -- the raw
    track_record() list only carries stars per-row, with no rollup. Rows
    missing a "stars" field are grouped under 0. A row counts toward
    `hit_rate`/`avg_return` only if it has a fetchable current price
    (pct is not None); `count` always includes every row regardless.
    Sorted highest star rating first."""
    tiers: dict[int, list[dict]] = {}
    for r in track_rows:
        stars = int(r.get("stars") or 0)
        tiers.setdefault(stars, []).append(r)

    out = []
    for stars, rows in tiers.items():
        priced = [r for r in rows if r.get("pct") is not None]
        hit_rate = (sum(1 for r in priced if r["pct"] >= 0) / len(priced) * 100) if priced else None
        avg_return = (sum(r["pct"] for r in priced) / len(priced)) if priced else None
        out.append({
            "stars": stars, "count": len(rows), "priced": len(priced),
            "hit_rate": hit_rate, "avg_return": avg_return,
        })
    out.sort(key=lambda t: -t["stars"])
    return out


def fetch_prices_on_dates(ticker_dates: list[tuple[str, str]], period: str = "1y") -> dict[tuple[str, str], float]:
    """Batch best-effort close price for each (ticker, "YYYY-MM-DD") pair —
    the first available daily close ON OR AFTER that date within a shared
    `period`-length fetch (falls back to the last available bar if the date
    is beyond the fetched range, e.g. today). Used when a signal's own date
    lags the day it was actually noticed/scanned (e.g. OverKill's dot date),
    so "first price" reflects the actual signal, not a stale scan-day price."""
    pairs = sorted(set(ticker_dates))
    tickers = sorted({t for t, _ in pairs})
    if not tickers:
        return {}
    prefetch_tickers(tickers, period, "1d")
    out = {}
    for t, date_str in pairs:
        try:
            df = get_price_history(t, period=period, interval="1d")
            if df is None or df.empty:
                continue
            # Same NaN guard as fetch_range_stats: a trailing placeholder bar
            # with a null close would otherwise become a NaN entry price, and
            # every percentage derived from it renders as "nan%".
            close = df["Close"].dropna()
            if close.empty:
                continue
            idx = close.index
            target = _align_to_index(datetime.strptime(date_str, "%Y-%m-%d"), idx)
            eligible = idx[idx >= target]
            row_date = eligible[0] if len(eligible) else idx[-1]
            out[(t, date_str)] = float(close.loc[row_date])
        except Exception:
            continue
    return out


def fetch_range_stats(ticker_dates: list[tuple[str, str]], period: str = "1y") -> dict[str, dict]:
    """Batch-fetch, for each (ticker, since_date) pair, the latest close plus
    the highest and lowest close from since_date through today (inclusive).
    `period` must comfortably cover the widest since_date in the batch --
    1y default is safe for both scanners' rollup windows (90d / 182d). One
    entry per ticker in the returned dict (assumes each ticker appears with
    a single since_date per call, true for track_record()'s use — one row
    per ticker from rollup_window()). Missing/failed tickers are simply
    absent from the returned dict."""
    pairs = sorted(set(ticker_dates))
    tickers = sorted({t for t, _ in pairs})
    if not tickers:
        return {}
    prefetch_tickers(tickers, period, "1d")
    out = {}
    for t, date_str in pairs:
        try:
            df = get_price_history(t, period=period, interval="1d")
            if df is None or df.empty:
                continue
            # Drop NaN closes before anything else: yfinance can hand back a
            # trailing placeholder bar with a null close (halted names, or an
            # in-progress session), and taking .iloc[-1] off that put a literal
            # "$nan" and "+nan%" straight into the emailed table.
            close = df["Close"].dropna()
            if close.empty:
                continue
            since = _align_to_index(datetime.strptime(date_str, "%Y-%m-%d"), close.index)
            window = close[close.index >= since]
            if window.empty:
                # Found today, before today's bar exists. The range SINCE the
                # find is therefore just the current price -- no high or low
                # has had time to form. This previously fell back to the whole
                # fetched period, so a ticker first seen today reported its
                # 52-week high as "% High": LYFT, found today at $17.42,
                # showed High $24.57 (+41%) and Low $12.65 (-27%), neither of
                # which happened since the call.
                window = close.iloc[-1:]
            out[t] = {
                "current": float(close.iloc[-1]),
                "high": float(window.max()),
                "low": float(window.min()),
            }
        except Exception:
            continue
    return out
