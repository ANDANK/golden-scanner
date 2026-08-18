# scanners/overkill_shorts_perf.py
# How the YouTube Shorts stock calls actually performed.
#
# Distinct from scanners/overkill_performance.py ("Shorts Backtest"), which
# tracks a hand-curated list of OverKill scanner alerts with their own alert
# prices. This one is fully automatic: it measures the picks that
# scripts/overkill_shorts_scan.py extracted from the videos themselves, using
# the price captured at the time of each call.
#

# Bullish and Bearish are split into separate tables, and every column on a
# Bearish row is expressed in the CALL's direction rather than the price's: a
# bearish call wins when price FALLS, so its Perf flips sign AND its best
# moment is the price low. Both tables therefore read "best call at the top",
# and every row satisfies Best >= Perf >= Worst.
#
# An earlier version flipped only Perf and left the range raw, which put two
# sign conventions in one row -- Perf +11.6% beside % High +0.0% and % Low
# -16.7%. Every figure was correct and the row still looked broken.

import json
import os

import streamlit as st

from config import *
from scanners import scan_history
from scripts import yt_channels
from scanners.ui_tables import sortable_table_html

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data", "overkill_shorts.json")


def _load_picks() -> list[dict]:
    """One row per (ticker, bias), keyed to the EARLIEST call of that kind --
    channels repeat tickers across videos, and performance should be measured
    from when the call was first made, not from the latest mention. A ticker
    called Bullish in June and Bearish in August is two separate rows, which
    is correct: those are two different calls to score.

    Two exclusions, both deliberate:
      * Entries with no ticker are general takeaways ("the Fed cut rates"),
        which have nothing to price and so nothing to score.
      * Channels flagged scored=False in scripts/yt_channels.py -- tax, macro
        and personal-finance commentary. Their occasional ticker mentions
        aren't trade calls, and scoring them would make the hit rate answer a
        different question from the one it appears to answer."""
    try:
        with open(DATA_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []

    first: dict[tuple[str, str], dict] = {}
    for vid in data.get("videos", []):
        date = vid.get("date", "")
        # Videos captured before multi-channel support predate the field and
        # are all OverKill, which is scored.
        handle = vid.get("channel", "@overkilltrading")
        if not yt_channels.is_scored(handle):
            continue
        for p in vid.get("picks", []):
            ticker = (p.get("ticker") or "").strip().upper()
            bias = p.get("bias")
            if not ticker or bias not in ("Bullish", "Bearish"):
                continue
            key = (ticker, bias)
            if key not in first or date < first[key]["date"]:
                first[key] = {
                    "ticker": ticker,
                    "bias": bias,
                    "date": date,
                    "price": p.get("price"),
                    "url": vid.get("url", ""),
                    "title": vid.get("title", ""),
                    "channel": vid.get("channel_name") or yt_channels.channel_name(handle),
                }
    return sorted(first.values(), key=lambda r: (r["date"], r["ticker"]))


@st.cache_data(ttl=1800, show_spinner=False)
def _score(rows: list[dict]) -> list[dict]:
    """Attach current/high/low and the percentages. Entry price is whatever
    the scan captured; picks recorded before price capture existed fall back
    to the close on their call date, so older rows still score rather than
    being dropped."""
    if not rows:
        return []
    pairs = [(r["ticker"], r["date"]) for r in rows]
    stats = scan_history.fetch_range_stats(pairs, period="1y")

    missing = [(r["ticker"], r["date"]) for r in rows if not r.get("price")]
    backfill = scan_history.fetch_prices_on_dates(missing, period="1y") if missing else {}

    out = []
    for r in rows:
        s = stats.get(r["ticker"])
        entry = r.get("price") or backfill.get((r["ticker"], r["date"]))
        if not s or not entry:
            continue
        current, high, low = s["current"], s["high"], s["low"]
        # Everything expressed in the CALL's direction, not the price's: a
        # bearish call wins when price falls, so its best moment is the LOW.
        # Keeping Perf flipped while the range stayed raw put two sign
        # conventions in one row and made correct numbers look wrong.
        pct, best, best_pct, worst, worst_pct = scan_history.directional_stats(
            (current / entry - 1) * 100, high, (high / entry - 1) * 100,
            low, (low / entry - 1) * 100, bearish=(r["bias"] == "Bearish"))
        out.append({**r, "entry": entry, "current": current, "pct": pct,
                    "best": best, "best_pct": best_pct,
                    "worst": worst, "worst_pct": worst_pct})
    out.sort(key=lambda r: -r["pct"])
    return out


def _pct_html(v: float) -> str:
    col = ACCENT_GREEN if v >= 0 else ACCENT_RED
    return (f'<span style="color:{col};font-family:\'DM Mono\',monospace;'
            f'font-weight:700">{v:+.1f}%</span>')


def _money(v: float) -> str:
    return (f'<span style="color:{TEXT_PRIMARY};font-family:\'DM Mono\',monospace">'
            f'${v:,.2f}</span>')


_COLUMNS = [
    {"label": "Ticker", "type": "str"},
    {"label": "Channel", "type": "str"},
    {"label": "Called", "type": "str"},
    {"label": "Price @ Call", "type": "num"},
    {"label": "Now", "type": "num"},
    {"label": "Perf %", "type": "num"},
    {"label": "Best", "type": "num"},
    {"label": "% Best", "type": "num"},
    {"label": "Worst", "type": "num"},
    {"label": "% Worst", "type": "num"},
]


def _table_rows(rows: list[dict]) -> list[list[tuple[str, object]]]:
    out = []
    for r in rows:
        date_cell = (f'<a href="{r["url"]}" target="_blank" title="{r["title"]}" '
                     f'style="color:{TEXT_MUTED};text-decoration:none">{r["date"]} ↗</a>'
                     if r.get("url") else
                     f'<span style="color:{TEXT_MUTED}">{r["date"]}</span>')
        out.append([
            (f'<span style="color:{GOLD};font-family:\'DM Mono\',monospace;'
             f'font-weight:700">{r["ticker"]}</span>', r["ticker"]),
            (f'<span style="color:{ACCENT_BLUE};font-size:11px">{r.get("channel","")}</span>',
             r.get("channel", "")),
            (date_cell, r["date"]),
            (_money(r["entry"]), r["entry"]),
            (_money(r["current"]), r["current"]),
            (_pct_html(r["pct"]), r["pct"]),
            (_money(r["best"]), r["best"]),
            (_pct_html(r["best_pct"]), r["best_pct"]),
            (_money(r["worst"]), r["worst"]),
            (_pct_html(r["worst_pct"]), r["worst_pct"]),
        ])
    return out


def _summary(rows: list[dict], label: str, color: str) -> str:
    if not rows:
        return ""
    wins = sum(1 for r in rows if r["pct"] > 0)
    avg = sum(r["pct"] for r in rows) / len(rows)
    avg_col = ACCENT_GREEN if avg >= 0 else ACCENT_RED
    return (f'<div style="font-size:11px;color:{TEXT_MUTED};margin:2px 0 6px">'
            f'<b style="color:{color}">{label}</b> · {len(rows)} call(s) · '
            f'hit rate <b style="color:{TEXT_PRIMARY}">{wins}/{len(rows)}'
            f' ({wins / len(rows) * 100:.0f}%)</b> · '
            f'avg <b style="color:{avg_col}">{avg:+.1f}%</b></div>')


def render():
    import streamlit.components.v1 as components   # lazy: headless mocks `streamlit`

    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:12px;line-height:1.7;margin-bottom:10px">'
        f'How each Shorts stock call has done since it was made, measured '
        f'from the price on the day it was made. Scored per <b>first</b> call of each kind — '
        f'a ticker called Bullish in June and Bearish in August counts as two separate calls. '
        f'🔴 A bearish call wins when price falls, so its <b>Perf %</b> is flipped: a price <i>drop</i> '
        f'shows positive, meaning the call was right. <b>High/Low</b> are the raw range since '
        f'the call and are never flipped. Not financial advice.</div>',
        unsafe_allow_html=True,
    )

    scored = _score(_load_picks())
    if not scored:
        st.info("No scored picks yet — they appear once the Shorts scan has stored picks "
                "with prices, or once prices can be resolved for existing ones.")
        return

    for bias, label, color in (("Bullish", "🟢 Bullish — buy calls", ACCENT_GREEN),
                               ("Bearish", "🔴 Bearish — sell/short calls", ACCENT_RED)):
        rows = [r for r in scored if r["bias"] == bias]
        st.markdown(f"##### {label}")
        if not rows:
            st.caption("No calls of this type yet.")
            continue
        st.markdown(_summary(rows, label, color), unsafe_allow_html=True)
        components.html(
            sortable_table_html(_COLUMNS, _table_rows(rows),
                                default_sort_idx=4, default_desc=True,
                                max_height=380),
            height=min(380, 90 + 32 * len(rows)) + 20,
            scrolling=False,
        )
