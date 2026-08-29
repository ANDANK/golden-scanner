# scanners/combo_lab_tab.py — the Combo Lab tab.
#
# READS ONLY. The study fetches ~500 tickers on two timeframes and tests 191
# combinations; that is a GitHub Actions job, not something to run inside a
# page load. scripts/headless_combo_lab.py writes data/combo_lab/latest.json
# and this renders it — the same split every other history-backed tab in this
# repo uses, and for the same reason (the app has no git write access).
#
# Plain HTML tables throughout: st.dataframe paints to a canvas and, when it
# fails to lay out, leaves a blank box with no error to explain it.

from __future__ import annotations

import json
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    GOLD, BG_PANEL, BG_CARD, BORDER_COLOR, TEXT_PRIMARY, TEXT_MUTED,
    ACCENT_GREEN, ACCENT_RED, ACCENT_BLUE,
)
from scanners import combo_lab as cl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data", "combo_lab")

# What each factor code means, so the table is readable without the spec.
GLOSSARY = {
    "A1": "MACD crossed up, above zero",
    "A2": "MACD crossed up, below zero",
    "B1": "RSI 30-45",
    "B2": "RSI 45-60",
    "B3": "RSI 60+",
    "C1": "EMA20>50 cross · price above EMA20",
    "C2": "EMA20>50 cross · price between the EMAs",
    "C3": "EMA20>50 cross · price below EMA50",
    "D1": "ADX 20-50 (trending, not exhausted)",
    "V1": "Volume >= 1.2x its 20-bar average",
}

VERDICT_COLOUR = {
    "Holds everywhere": ACCENT_GREEN,
    "Mostly holds": GOLD,
    "Inconsistent": TEXT_MUTED,
    "Not enough data": ACCENT_RED,
}


def _rgba(hex_colour: str, alpha: float) -> str:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


@st.cache_data(ttl=900, show_spinner=False)
def load_latest() -> dict | None:
    path = os.path.join(DATA_DIR, "latest.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _num(v, fmt="{:+.2f}%", dash="—"):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return dash
    return fmt.format(v)


def _edge_colour(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return TEXT_MUTED
    return ACCENT_GREEN if v > 0 else ACCENT_RED


_TD = ("padding:5px 9px;font-size:11.5px;font-family:'DM Mono',monospace;"
       "border-bottom:1px solid rgba(255,255,255,.045);white-space:nowrap")


def _cell(v, colour=TEXT_PRIMARY, align="right", weight=700) -> str:
    return (f'<td style="{_TD};text-align:{align};color:{colour};'
            f'font-weight:{weight}">{v}</td>')


def consensus_html(rows: list[dict], window_names: list[str],
                   min_trades: int, only: str | None = None) -> str:
    """The headline: one row per combination, one column pair per window.

    Ranked by how many INDEPENDENT windows a combination held up in, then by
    size of edge. Four separate ranked tables would invite reading the top of
    one of them, which is exactly how a combination that worked in a single
    window gets mistaken for one that works.
    """
    head = ('<th style="padding:7px 9px;text-align:left;color:%s;font-size:9.5px;'
            'font-weight:800;letter-spacing:.06em;text-transform:uppercase;'
            'border-bottom:1px solid %s">Combination</th>'
            '<th style="padding:7px 9px;text-align:left;color:%s;font-size:9.5px;'
            'font-weight:800;letter-spacing:.06em;text-transform:uppercase;'
            'border-bottom:1px solid %s">Verdict</th>' %
            (TEXT_MUTED, BORDER_COLOR, TEXT_MUTED, BORDER_COLOR))
    for w in window_names:
        head += (f'<th colspan="2" style="padding:7px 9px;text-align:center;'
                 f'color:{TEXT_MUTED};font-size:9.5px;font-weight:800;'
                 f'letter-spacing:.05em;text-transform:uppercase;'
                 f'border-bottom:1px solid {BORDER_COLOR};'
                 f'border-left:1px solid {BORDER_COLOR}">{w}</th>')
    for h in ("Mean edge", "Worst", "Min n"):
        head += (f'<th style="padding:7px 9px;text-align:right;color:{TEXT_MUTED};'
                 f'font-size:9.5px;font-weight:800;letter-spacing:.06em;'
                 f'text-transform:uppercase;border-bottom:1px solid {BORDER_COLOR};'
                 f'border-left:1px solid {BORDER_COLOR}">{h}</th>')
    sub = f'<th></th><th></th>'
    for _ in window_names:
        sub += (f'<th style="padding:2px 9px;text-align:right;color:{TEXT_MUTED};'
                f'font-size:8.5px;border-left:1px solid {BORDER_COLOR}">edge</th>'
                f'<th style="padding:2px 9px;text-align:right;color:{TEXT_MUTED};'
                f'font-size:8.5px">n</th>')
    sub += '<th></th><th></th><th></th>'

    body = []
    for r in rows:
        if only and r.get("verdict") != only:
            continue
        vc = VERDICT_COLOUR.get(r.get("verdict"), TEXT_MUTED)
        tint = (f'background:{_rgba(ACCENT_GREEN, 0.055)};'
                if r.get("verdict") == "Holds everywhere" else "")
        tr = f'<tr style="{tint}">'
        tr += _cell(r["combo"], TEXT_PRIMARY, "left", 800)
        tr += (f'<td style="{_TD};text-align:left"><span style="background:'
               f'{_rgba(vc, 0.14)};color:{vc};font-size:9px;font-weight:800;'
               f'padding:2px 6px;border-radius:4px">{r.get("verdict","")}</span></td>')
        for w in window_names:
            edge, n = r.get(f"{w}_edge"), r.get(f"{w}_n")
            thin = n is None or pd.isna(n) or n < min_trades
            tr += (f'<td style="{_TD};text-align:right;font-weight:700;'
                   f'border-left:1px solid {BORDER_COLOR};'
                   f'color:{TEXT_MUTED if thin else _edge_colour(edge)};'
                   f'{"opacity:.45" if thin else ""}">{_num(edge)}</td>')
            tr += _cell("—" if n is None or pd.isna(n) else f"{int(n):,}",
                        ACCENT_RED if thin else TEXT_MUTED, "right", 600)
        tr += (f'<td style="{_TD};text-align:right;font-weight:800;'
               f'border-left:1px solid {BORDER_COLOR};'
               f'color:{_edge_colour(r.get("mean_edge"))}">'
               f'{_num(r.get("mean_edge"))}</td>')
        tr += _cell(_num(r.get("worst_edge")), _edge_colour(r.get("worst_edge")))
        tr += _cell(f'{int(r["min_n"]):,}' if r.get("min_n") is not None else "—",
                    TEXT_MUTED, "right", 600)
        body.append(tr + "</tr>")

    if not body:
        body = [f'<tr><td colspan="{2 + 2 * len(window_names) + 3}" '
                f'style="{_TD};color:{TEXT_MUTED};text-align:center;padding:20px">'
                f'Nothing in this category.</td></tr>']
    return (f'<div style="overflow-x:auto"><table style="width:100%;'
            f'border-collapse:collapse;background:{BG_PANEL};'
            f'border:1px solid {BORDER_COLOR};border-radius:10px">'
            f'<thead><tr>{head}</tr><tr>{sub}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def window_html(rows: list[dict], min_trades: int, limit: int = 40) -> str:
    """One (timeframe x period x hold) cell, ranked, low-N sorted to the end."""
    cols = [("Combination", "left"), ("Trades", "right"), ("Win %", "right"),
            ("Avg ret", "right"), ("Avg excess", "right"), ("Total", "right"),
            ("Max DD", "right"), ("Sharpe", "right"), ("Sortino", "right"),
            ("t-stat", "right")]
    head = "".join(
        f'<th style="padding:7px 9px;text-align:{a};color:{TEXT_MUTED};'
        f'font-size:9.5px;font-weight:800;letter-spacing:.06em;'
        f'text-transform:uppercase;border-bottom:1px solid {BORDER_COLOR};'
        f'white-space:nowrap">{h}</th>' for h, a in cols)
    body = []
    for r in rows[:limit]:
        thin = r.get("low_n")
        tr = f'<tr style="{"opacity:.5" if thin else ""}">'
        tr += _cell(r["combo"], TEXT_PRIMARY, "left", 800)
        tr += _cell(f'{int(r["trades"]):,}',
                    ACCENT_RED if thin else TEXT_MUTED, "right", 600)
        tr += _cell(_num(r.get("win_rate"), "{:.1f}%"), TEXT_PRIMARY)
        tr += _cell(_num(r.get("avg_return")), _edge_colour(r.get("avg_return")))
        tr += _cell(_num(r.get("avg_excess")), _edge_colour(r.get("avg_excess")), "right", 800)
        tr += _cell(_num(r.get("total_return"), "{:+.0f}%"), _edge_colour(r.get("total_return")))
        tr += _cell(_num(r.get("max_drawdown"), "{:.0f}%"), ACCENT_RED)
        tr += _cell(_num(r.get("sharpe"), "{:.2f}"), TEXT_PRIMARY)
        tr += _cell(_num(r.get("sortino"), "{:.2f}"), TEXT_MUTED)
        tr += _cell(_num(r.get("t_stat"), "{:+.2f}"),
                    TEXT_PRIMARY if abs(r.get("t_stat") or 0) >= 2 else TEXT_MUTED)
        body.append(tr + "</tr>")
    return (f'<div style="overflow-x:auto"><table style="width:100%;'
            f'border-collapse:collapse;background:{BG_PANEL};'
            f'border:1px solid {BORDER_COLOR};border-radius:10px">'
            f'<thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def render() -> None:
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11.5px;line-height:1.6;'
        f'margin-bottom:10px">'
        f'Every cross-combination of <b>MACD</b> state, <b>RSI</b> band, '
        f'<b>EMA20/50</b> structure, <b>ADX</b> and <b>volume</b> — '
        f'<b style="color:{TEXT_PRIMARY}">191 in all</b>, each single factor '
        f'included as its own baseline — tested on daily and weekly bars over '
        f'two <b>non-overlapping</b> periods.<br>'
        f'Ranked by how many of the four cells a combination held up in, '
        f'<i>then</i> by size of edge — one that only works in one cell sorts '
        f'below one that works in all four, however big its best number. '
        f'The two <b>periods</b> share no trades, so agreement across them is '
        f'out-of-sample; the two <b>timeframes</b> cover the same calendar, so '
        f'agreement across those says the signal survives a change of bar size, '
        f'which is weaker.</div>', unsafe_allow_html=True)

    payload = load_latest()
    if not payload:
        st.markdown(
            f'<div style="border:1px dashed {BORDER_COLOR};border-radius:10px;'
            f'padding:30px;text-align:center;color:{TEXT_MUTED};font-size:12px">'
            f'No study stored yet.<br>Run the '
            f'<b style="color:{GOLD}">Combo Lab</b> workflow in GitHub Actions — '
            f'it fetches ~500 tickers and writes <code>data/combo_lab/</code>.'
            f'<br><span style="font-size:10.5px">Too heavy for a page load, so '
            f'this tab only ever reads what that job produced.</span></div>',
            unsafe_allow_html=True)
        return

    wins = payload.get("windows", {})
    st.caption(
        f"{payload.get('universe')} · {payload.get('usable_daily', 0)} daily / "
        f"{payload.get('usable_weekly', 0)} weekly tickers · benchmark "
        f"{payload.get('benchmark')} · "
        + " · ".join(f"{k} {v[0]}→{v[1]}" for k, v in wins.items())
        + f" · generated {payload.get('generated_utc', '')}")

    cons = payload.get("consensus", [])
    window_names = [k for k in payload.get("tables", {})]
    headline_windows = [f"{tf} {w}" for tf in ("Daily", "Weekly") for w in wins]
    min_trades = payload.get("min_trades", cl.MIN_TRADES)

    held = [r for r in cons if r.get("verdict") == "Holds everywhere"]
    mostly = [r for r in cons if r.get("verdict") == "Mostly holds"]

    st.markdown(
        f'<div style="display:flex;gap:10px;margin:6px 0 12px 0;flex-wrap:wrap">'
        f'<div style="background:{_rgba(ACCENT_GREEN,0.10)};border:1px solid '
        f'{_rgba(ACCENT_GREEN,0.30)};border-radius:8px;padding:9px 14px">'
        f'<span style="color:{ACCENT_GREEN};font-size:20px;font-weight:800">'
        f'{len(held)}</span><span style="color:{TEXT_MUTED};font-size:11px;'
        f'margin-left:8px">hold up in all four cells</span></div>'
        f'<div style="background:{_rgba(GOLD,0.10)};border:1px solid '
        f'{_rgba(GOLD,0.30)};border-radius:8px;padding:9px 14px">'
        f'<span style="color:{GOLD};font-size:20px;font-weight:800">'
        f'{len(mostly)}</span><span style="color:{TEXT_MUTED};font-size:11px;'
        f'margin-left:8px">hold up in three of four</span></div>'
        f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};'
        f'border-radius:8px;padding:9px 14px">'
        f'<span style="color:{TEXT_PRIMARY};font-size:20px;font-weight:800">'
        f'{len(cons)}</span><span style="color:{TEXT_MUTED};font-size:11px;'
        f'margin-left:8px">tested</span></div></div>', unsafe_allow_html=True)

    if not held:
        st.markdown(
            f'<div style="background:#1a1410;border:1px solid '
            f'rgba(240,112,74,0.18);border-radius:10px;padding:11px 13px;'
            f'font-size:11.5px;color:#c9a99a;line-height:1.6;margin-bottom:10px">'
            f'<b style="color:#f0704a">Nothing held up in all four cells.</b> '
            f'That is a result, not a failed run: no combination beat '
            f'{payload.get("benchmark")} on both timeframes in both periods with '
            f'an adequate sample. Read the "mostly holds" rows as candidates, '
            f'not conclusions.</div>', unsafe_allow_html=True)

    view = st.radio("Show", ["Holds everywhere", "Mostly holds",
                             "Single factors only", "Everything"],
                    horizontal=True, key="combo_view", label_visibility="collapsed")
    if view == "Single factors only":
        rows = [r for r in cons if r.get("n_factors") == 1]
    elif view == "Everything":
        rows = cons
    else:
        rows = [r for r in cons if r.get("verdict") == view]
    st.markdown(consensus_html(rows, headline_windows, min_trades),
                unsafe_allow_html=True)

    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:10.5px;margin-top:8px;'
        f'line-height:1.6">Edge = average return per trade minus '
        f'{payload.get("benchmark")} over the same bars. A greyed cell had '
        f'fewer than {min_trades} trades and is not counted toward the verdict. '
        f'<b>Min n</b> is the smallest sample across the four windows — the '
        f'number that limits what the row can claim.</div>',
        unsafe_allow_html=True)

    with st.expander("What each code means"):
        st.markdown(
            "".join(f'<div style="font-size:11.5px;color:{TEXT_MUTED};'
                    f'padding:2px 0"><b style="color:{TEXT_PRIMARY};'
                    f'font-family:monospace">{k}</b> — {v}</div>'
                    for k, v in GLOSSARY.items()), unsafe_allow_html=True)
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:11px;margin-top:10px;'
            f'line-height:1.65">'
            f'<b style="color:{TEXT_PRIMARY}">Entry</b> the bar after every '
            f'condition is true, at that bar\'s open. '
            f'<b style="color:{TEXT_PRIMARY}">Exit</b> a fixed number of bars '
            f'later, identical for every combination, so differences are '
            f'attributable to the entry alone. Holds are deliberately short — '
            f'doubling them was tested and made results worse in three of four '
            f'cells, and a long hold measures the stock rather than the '
            f'signal.<br>'
            f'<b style="color:{TEXT_PRIMARY}">Crossovers</b> read "crossed '
            f'within the last {payload.get("cross_window", {}).get("daily", 5)} '
            f'bars (daily) / {payload.get("cross_window", {}).get("weekly", 3)} '
            f'(weekly)" — demanding two separate crossovers on the same bar '
            f'would leave most cells empty.<br>'
            f'<b style="color:{ACCENT_RED}">C2 is rare by construction.</b> At '
            f'a crossover EMA20 and EMA50 are equal, so the band between them '
            f'is a sliver price is seldom inside. Expect it under the low-N '
            f'flag.</div>', unsafe_allow_html=True)

    with st.expander("Per-window detail (every cell and holding period)"):
        pick = st.selectbox("Window", window_names, key="combo_window")
        rows = payload["tables"].get(pick, [])
        st.markdown(window_html(rows, min_trades), unsafe_allow_html=True)

    st.markdown(
        f'<div style="background:#1a1410;border:1px solid rgba(240,112,74,0.18);'
        f'border-radius:10px;padding:11px 13px;font-size:11px;color:#c9a99a;'
        f'line-height:1.6;margin-top:16px">'
        f'<b style="color:#f0704a">Read before acting on any row.</b> '
        f'{len(cons)} combinations tested at once is {len(cons)} chances for one '
        f'to look good by luck — at a 5% threshold roughly '
        f'{max(1, len(cons) // 20)} should print "significant" with no edge at '
        f'all. That is precisely why the ranking is by consistency across the four '
        f'cells rather than by any single number, and why a t-stat in the '
        f'per-window table is a hint rather than a verdict. Note too that only '
        f'the two periods are independent of each other — the daily and weekly '
        f'views of one period share a calendar, so "holds everywhere" is a '
        f'filter that removes the fragile, not a proof that what remains is '
        f'real. '
        f'The universe is today\'s list, so delisted and acquired names are '
        f'absent and every result is flattered equally. No slippage or '
        f'commission is modelled.</div>', unsafe_allow_html=True)
