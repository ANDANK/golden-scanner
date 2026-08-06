# scanners/scan_history.py — shared daily-snapshot history engine used by
# both Best Scanners and OverKill to power "New" badges, first-found dates,
# and track-record (% performance since first sighting) tables.
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
    _event_date()) and "first_price". Does NOT fetch current prices — call
    fetch_current_prices() separately and join, since that needs a live
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


def track_record(kind: str, tag: str, today_date_str: str, today_rows: list[dict]) -> list[dict]:
    """The full 'how did our past picks do' rollup, ready to render: every
    distinct ticker in the window with first-found date/price, current
    price, and % performance since first sighting — sorted best performer
    first (tickers with no fetchable current price sort last, pct=None)."""
    base = rollup_window(kind, tag, today_date_str, today_rows)
    prices = fetch_current_prices([r["ticker"] for r in base])
    out = []
    for r in base:
        current = prices.get(r["ticker"])
        first_price = r.get("first_price")
        pct = (current - first_price) / first_price * 100 if current is not None and first_price else None
        out.append({**r, "current_price": current, "pct": pct})
    out.sort(key=lambda r: (r["pct"] is None, -(r["pct"] if r["pct"] is not None else 0)))
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
            target = datetime.strptime(date_str, "%Y-%m-%d")
            idx = df.index
            eligible = idx[idx >= target]
            row_date = eligible[0] if len(eligible) else (idx[-1] if len(idx) else None)
            if row_date is None:
                continue
            out[(t, date_str)] = float(df.loc[row_date, "Close"])
        except Exception:
            continue
    return out


def fetch_current_prices(tickers: list[str]) -> dict[str, float]:
    """Batch-fetch the latest close for each ticker (short lookback — this
    is a "where is it now" check, not a chart). Missing/failed tickers are
    simply absent from the returned dict."""
    tickers = sorted(set(tickers))
    if not tickers:
        return {}
    prefetch_tickers(tickers, "5d", "1d")
    out = {}
    for t in tickers:
        try:
            df = get_price_history(t, period="5d", interval="1d")
            if df is None or df.empty:
                continue
            out[t] = float(df["Close"].squeeze().iloc[-1])
        except Exception:
            continue
    return out
