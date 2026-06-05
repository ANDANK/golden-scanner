# scanners/mtpa_page.py — MTPA Scanner Page (Momentum Trend Price Action)
# ─────────────────────────────────────────────────────────────────────────────
# Admin-only Streamlit page.
# Displays three filtered tables:
#   Table 1 — PRIME   (full alignment across all timeframes)
#   Table 2 — STRONG  (weekly clean + daily confirmed)
#   Table 3 — BUILDING (daily signal only)
# No scoring. Each table shows identical columns with color-coded cells.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
from datetime import datetime

from config import (
    GOLD, GOLD_DARK, BG_CARD, BG_PANEL, BG_DARK,
    ACCENT_GREEN, ACCENT_RED, ACCENT_BLUE,
    TEXT_PRIMARY, TEXT_MUTED, BORDER_COLOR,
    SP500_SAMPLE, MTPA_200,
)
from utils import section_header
from scanners.mtpa_scanner import run_mtpa_scan
from scanners.gsheet_helper import export_mtpa_scan


# ── FTF section renderer (shared with strategies_page) ────────────────────────

def render_ftf_section(ftf_rows: list[dict], context: str = "mtpa") -> None:
    """
    Render the 'First Things First' section.
    ftf_rows: output of run_ftf_scan() — empty list = nothing qualified.
    context:  'mtpa' or 'csp' (controls wording slightly).
    """
    G  = ACCENT_GREEN
    GL = GOLD
    P  = "#A78BFA"

    # ── Section header ─────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="background:linear-gradient(135deg,{GL}12,{G}08);'
        f'border-left:4px solid {GL};border-radius:0 10px 10px 0;'
        f'padding:12px 18px;margin:0 0 10px">'
        f'<div style="display:flex;align-items:center;gap:10px">'
        f'<span style="font-size:22px">🎯</span>'
        f'<div>'
        f'<div style="color:{GL};font-size:14px;font-weight:700;letter-spacing:0.3px">'
        f'First Things First</div>'
        f'<div style="color:{TEXT_MUTED};font-size:10px;margin-top:1px">'
        f'Stocks passing ALL weekly + daily + cross-TF conditions simultaneously — '
        f'highest-conviction setups right now</div>'
        f'</div></div>'
        f'<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:10px">'
        + "".join(
            f'<span style="background:{c}14;color:{c};border:1px solid {c}33;'
            f'font-size:9px;font-weight:700;padding:2px 8px;border-radius:10px">{t}</span>'
            for t, c in [
                ("W: Not Extended", G), ("W: RSI 35-75", G),
                ("W: MACD>Sig", G), ("W: Vol 0.7-3×", G),
                ("W: P>SMA20W", G), ("W: Uptrend", G),
                ("D: Not Ext'd", "#60A5FA"), ("D: RSI 35-70", "#60A5FA"),
                ("D: MACD>Sig", "#60A5FA"), ("D: P>SMA9", "#60A5FA"),
                ("D: Hist↑", "#60A5FA"), ("D: Vol>Avg", "#60A5FA"),
                ("ADX>16", P), ("No Bearish Div", P),
            ]
        )
        + f'</div></div>',
        unsafe_allow_html=True,
    )

    if not ftf_rows:
        # Empty state — always show section
        st.markdown(
            f'<div style="background:{BG_PANEL};border:1px dashed {BORDER_COLOR};'
            f'border-radius:10px;padding:28px;text-align:center;margin-bottom:20px">'
            f'<div style="font-size:28px;margin-bottom:8px">🔍</div>'
            f'<div style="color:{TEXT_PRIMARY};font-size:13px;font-weight:600;'
            f'margin-bottom:4px">No Setups Qualify Right Now</div>'
            f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.7">'
            f'All 14 conditions (6 weekly + 6 daily + ADX + no divergence) must pass '
            f'simultaneously. This is intentionally strict — when something appears '
            f'here, it\'s the highest-conviction setup in the current market.</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        return

    # ── Table ──────────────────────────────────────────────────────────────────
    _HD = (f'background:#0f172a;color:{GL};font-size:9px;font-weight:700;'
           f'text-transform:uppercase;letter-spacing:0.7px;padding:8px 12px;'
           f'border-bottom:2px solid {GL}33;white-space:nowrap;text-align:left')
    hdr = "".join(
        f'<th style="{_HD}">{c}</th>'
        for c in ["Ticker", "Price",
                  "W-RSI", "W-MACD Hist",
                  "D-RSI", "D-Hist↑", "ADX", "Supply Gap",
                  "Demand Zone", "Bear Div"]
    )

    rows_html = ""
    for i, r in enumerate(ftf_rows):
        bg  = BG_CARD if i % 2 == 0 else BG_PANEL
        wd  = r.get("w_detail", {})
        dd  = r.get("d_detail", {})

        rsi_w_v = wd.get("rsi_w", 0)
        rsi_d_v = dd.get("rsi_d", 0)
        rsi_w_col = ACCENT_GREEN if 50 <= rsi_w_v <= 65 else (GOLD if 35 <= rsi_w_v < 50 or 65 < rsi_w_v <= 75 else TEXT_MUTED)
        rsi_d_col = ACCENT_GREEN if 50 <= rsi_d_v <= 65 else (GOLD if 35 <= rsi_d_v < 50 or 65 < rsi_d_v <= 70 else TEXT_MUTED)

        hist_w = wd.get("hist_w", 0); hist_w_p = wd.get("hist_w_prev", 0)
        hist_d = dd.get("hist_d", 0); hist_d_p = dd.get("hist_d_prev", 0)
        hw_col = ACCENT_GREEN if hist_w > 0 else ACCENT_RED
        hd_col = ACCENT_GREEN if hist_d > 0 else ACCENT_RED

        adx_v   = dd.get("adx")
        adx_col = ACCENT_GREEN if (adx_v and adx_v >= 25) else (GOLD if (adx_v and adx_v >= 16) else TEXT_MUTED)

        supply_gap = dd.get("pct_below_high", 0)
        sg_col     = ACCENT_GREEN if supply_gap >= 5 else (GOLD if supply_gap >= 3 else ACCENT_RED)

        in_demand  = dd.get("in_demand", False)
        bear_div   = dd.get("bearish_div", False)

        rows_html += (
            f'<tr>'
            f'<td style="background:{bg};padding:8px 12px;white-space:nowrap">'
            f'<span style="color:{GL};font-family:\'DM Mono\',monospace;'
            f'font-weight:700;font-size:13px">{r["ticker"]}</span></td>'
            f'<td style="background:{bg};padding:8px 12px">'
            f'<span style="color:{TEXT_PRIMARY};font-family:\'DM Mono\',monospace">'
            f'${r["price"]:.2f}</span></td>'
            # W-RSI
            f'<td style="background:{bg};padding:8px 12px">'
            f'<span style="color:{rsi_w_col};font-weight:700">{rsi_w_v:.1f}</span></td>'
            # W-MACD Hist
            f'<td style="background:{bg};padding:8px 12px;font-size:11px">'
            f'<span style="color:{hw_col};font-family:\'DM Mono\',monospace">'
            f'{hist_w:.4f}</span>'
            f'<span style="color:{hw_col};font-size:10px"> {"↑" if hist_w > hist_w_p else "↓"}</span></td>'
            # D-RSI
            f'<td style="background:{bg};padding:8px 12px">'
            f'<span style="color:{rsi_d_col};font-weight:700">{rsi_d_v:.1f}</span></td>'
            # D-MACD Hist
            f'<td style="background:{bg};padding:8px 12px;font-size:11px">'
            f'<span style="color:{hd_col};font-family:\'DM Mono\',monospace">'
            f'{hist_d:.4f}</span>'
            f'<span style="color:{ACCENT_GREEN};font-size:10px"> ↑</span></td>'
            # ADX
            f'<td style="background:{bg};padding:8px 12px">'
            f'<span style="color:{adx_col};font-weight:700">'
            f'{"—" if adx_v is None else f"{adx_v:.1f}"}</span>'
            f'{"↑" if dd.get("adx_rising") else ""}</td>'
            # Supply gap
            f'<td style="background:{bg};padding:8px 12px">'
            f'<span style="color:{sg_col};font-weight:700">{supply_gap:.1f}% clear</span></td>'
            # Demand zone
            f'<td style="background:{bg};padding:8px 12px;text-align:center;font-size:13px">'
            f'{"💚" if in_demand else "—"}</td>'
            # Bearish divergence
            f'<td style="background:{bg};padding:8px 12px;text-align:center;font-size:13px">'
            f'{"❌" if bear_div else "✅"}</td>'
            f'</tr>'
        )

    n = len(ftf_rows)
    st.markdown(
        f'<div style="color:{G};font-size:12px;font-weight:600;margin-bottom:6px">'
        f'⭐ {n} stock{"s" if n != 1 else ""} passed all conditions'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="overflow-x:auto;border:1px solid {GL}44;border-radius:10px;'
        f'margin-bottom:20px">'
        f'<table style="width:100%;border-collapse:collapse;font-family:\'Inter\',sans-serif">'
        f'<thead><tr>{hdr}</tr></thead>'
        f'<tbody>{rows_html}</tbody>'
        f'</table></div>',
        unsafe_allow_html=True,
    )


# ── Session state key ──────────────────────────────────────────────────────────
_SESSION_KEY = "_mtpa_results"


# ── Color helpers ──────────────────────────────────────────────────────────────

def _badge(text: str, bg: str, fg: str) -> str:
    """Return an inline HTML badge span."""
    return (
        f'<span style="background:{bg};color:{fg};'
        f'border-radius:4px;padding:2px 7px;font-size:11px;'
        f'font-weight:700;white-space:nowrap">{text}</span>'
    )


def _icon(condition: bool, true_icon: str = "✅", false_icon: str = "❌") -> str:
    return true_icon if condition else false_icon


# ── Cell renderers for each column ────────────────────────────────────────────

def _render_weekly_pattern(val: str) -> str:
    if val == "HH/HL":
        return f'{_badge("HH/HL", ACCENT_GREEN + "22", ACCENT_GREEN)} 📈'
    if val == "Tight Base":
        return f'{_badge("Tight Base", ACCENT_BLUE + "22", ACCENT_BLUE)} 🔲'
    return f'{_badge("Mixed", TEXT_MUTED + "22", TEXT_MUTED)} ➖'


def _render_weekly_extended(val: bool) -> str:
    if val:
        return f'⚠️ {_badge("ON", "#44220044", ACCENT_RED)}'
    return f'✅ {_badge("OFF", ACCENT_GREEN + "22", ACCENT_GREEN)}'


def _render_rsi(value: float, status: str) -> str:
    color = {
        "GREEN":   ACCENT_GREEN,
        "YELLOW":  "#FBBF24",
        "NEUTRAL": TEXT_MUTED,
    }.get(status, TEXT_MUTED)
    return (
        f'<span style="color:{TEXT_PRIMARY};font-weight:600">{value:.1f}</span> '
        f'{_badge(status, color + "22", color)}'
    )


def _render_macd_above(val: bool) -> str:
    return "✅" if val else "❌"


def _render_macd_zone(val: str) -> str:
    icons = {
        "NEAR_ZERO": "🎯 Near Zero",
        "POSITIVE":  "📈 Positive",
        "NEGATIVE":  "📉 Negative",
    }
    return icons.get(val, val)


def _render_volume(ratio: float, ok: bool) -> str:
    color = ACCENT_GREEN if ok else (ACCENT_RED if ratio >= 1.8 else TEXT_MUTED)
    return f'<span style="color:{color};font-weight:600">{ratio:.2f}×</span>'


def _render_earnings(days: int, flag: str) -> str:
    if days < 0:
        return f'<span style="color:{TEXT_MUTED}">—</span>'
    color = {
        "SKIP": ACCENT_RED,
        "WARN": "#FBBF24",
        "OK":   ACCENT_GREEN,
    }.get(flag, TEXT_MUTED)
    return f'<span style="color:{color};font-weight:600">{days}d</span>'


def _render_candles(patterns: list) -> str:
    if not patterns:
        return f'<span style="color:{TEXT_MUTED}">—</span>'
    return f'<span style="color:{GOLD};font-size:11px">' + ", ".join(patterns) + '</span>'


def _render_rs(status: str, pct: str) -> str:
    color = {
        "OUTPERFORM":  ACCENT_GREEN,
        "MATCH":       TEXT_MUTED,
        "UNDERPERFORM": ACCENT_RED,
    }.get(status, TEXT_MUTED)
    return (
        f'{_badge(status[:4], color + "22", color)} '
        f'<span style="color:{color};font-size:11px">{pct}</span>'
    )


def _render_sector(etf: str, trending: bool) -> str:
    trend_icon = "✅" if trending else "❌"
    return f'<span style="color:{GOLD};font-weight:600">{etf}</span> {trend_icon}'


def _render_wk_macd_t4(line: float, hist: float, rising: bool) -> str:
    """Weekly MACD cell for Table 4: Line value + Hist value + rising arrow."""
    lc = ACCENT_GREEN if line > 0 else ACCENT_RED
    hc = ACCENT_GREEN if hist > 0 else ACCENT_RED
    arrow = (
        f'<span style="color:{ACCENT_GREEN};font-size:13px;font-weight:700"> ↑</span>'
        if rising else
        f'<span style="color:{TEXT_MUTED};font-size:12px"> →</span>'
    )
    return (
        f'<span style="color:{TEXT_MUTED};font-size:10px">L:</span>'
        f'<span style="color:{lc};font-family:\'DM Mono\',monospace;font-size:11px;'
        f'margin:0 5px 0 2px">{line:+.2f}</span>'
        f'<span style="color:{TEXT_MUTED};font-size:10px">H:</span>'
        f'<span style="color:{hc};font-family:\'DM Mono\',monospace;font-size:11px;'
        f'margin-left:2px">{hist:+.2f}</span>'
        f'{arrow}'
    )


def _render_dly_macd_t4(line: float, hist: float) -> str:
    """Daily MACD cell for Table 4: Line value + Hist value."""
    lc = ACCENT_GREEN if line > 0 else ACCENT_RED
    hc = ACCENT_GREEN if hist > 0 else ACCENT_RED
    return (
        f'<span style="color:{TEXT_MUTED};font-size:10px">L:</span>'
        f'<span style="color:{lc};font-family:\'DM Mono\',monospace;font-size:11px;'
        f'margin:0 5px 0 2px">{line:+.2f}</span>'
        f'<span style="color:{TEXT_MUTED};font-size:10px">H:</span>'
        f'<span style="color:{hc};font-family:\'DM Mono\',monospace;font-size:11px;'
        f'margin-left:2px">{hist:+.2f}</span>'
    )


def _render_rsi_combined(wk_rsi: float, dly_rsi: float) -> str:
    """Combined W/D RSI cell — each value color-coded by range."""
    def _c(v: float) -> str:
        if 50 <= v <= 70:
            return ACCENT_GREEN
        if 40 <= v < 50:
            return "#FBBF24"
        return TEXT_MUTED

    return (
        f'<span style="color:{TEXT_MUTED};font-size:10px">W:</span>'
        f'<span style="color:{_c(wk_rsi)};font-weight:600;margin:0 8px 0 3px">'
        f'{wk_rsi:.1f}</span>'
        f'<span style="color:{TEXT_MUTED};font-size:10px">D:</span>'
        f'<span style="color:{_c(dly_rsi)};font-weight:600;margin-left:3px">'
        f'{dly_rsi:.1f}</span>'
    )


def _render_flags(flags: list) -> str:
    if not flags:
        return f'<span style="color:{TEXT_MUTED}">—</span>'
    parts = []
    for f in flags:
        color = "#FBBF24" if f in ("Vol Spike", "Extended", "Gap Up", "Gap Down", "Earnings Soon") else ACCENT_GREEN
        if f in ("RS Extreme",):
            color = ACCENT_RED
        parts.append(_badge(f, color + "22", color))
    return " ".join(parts)


# ── Build the HTML table ───────────────────────────────────────────────────────

def _get_columns(benchmark_label: str = "RS vs SPY") -> list:
    return [
        ("Ticker",         "130px"),
        ("Price",          "70px"),
        ("Wk Pattern",     "110px"),
        ("Wk Ext.",        "80px"),
        ("RSI",            "130px"),
        ("MACD>Sig",       "80px"),
        ("MACD Zone",      "110px"),
        ("Vol Ratio",      "90px"),
        (">SMA20",         "70px"),
        (">SMA9",          "70px"),
        ("Earnings",       "80px"),
        ("Candles",        "180px"),
        (benchmark_label,  "160px"),
        ("Sector ETF",     "120px"),
        ("Flags",          "220px"),
    ]


def _row_html(r: dict, bg: str) -> str:
    """Render a single data row as an HTML <tr>."""
    cells = [
        # Ticker — bold gold
        f'<td style="background:{bg};padding:7px 10px;white-space:nowrap">'
        f'<span style="color:{GOLD};font-family:\'DM Mono\',monospace;'
        f'font-weight:700;font-size:13px">{r["ticker"]}</span></td>',
        # Price
        f'<td style="background:{bg};padding:7px 10px;color:{TEXT_PRIMARY};'
        f'font-family:\'DM Mono\',monospace;font-size:12px">${r["price"]:.2f}</td>',
        # Weekly pattern
        f'<td style="background:{bg};padding:7px 10px">{_render_weekly_pattern(r["weekly_pattern"])}</td>',
        # Weekly extended
        f'<td style="background:{bg};padding:7px 10px">{_render_weekly_extended(r["weekly_extended"])}</td>',
        # RSI
        f'<td style="background:{bg};padding:7px 10px">{_render_rsi(r["rsi_value"], r["rsi_status"])}</td>',
        # MACD > Signal
        f'<td style="background:{bg};padding:7px 10px;text-align:center">{_render_macd_above(r["macd_above_signal"])}</td>',
        # MACD Zone
        f'<td style="background:{bg};padding:7px 10px;font-size:12px;color:{TEXT_PRIMARY}">'
        f'{_render_macd_zone(r["macd_zone"])}</td>',
        # Vol Ratio
        f'<td style="background:{bg};padding:7px 10px">{_render_volume(r["volume_ratio"], r["volume_ok"])}</td>',
        # >SMA20
        f'<td style="background:{bg};padding:7px 10px;text-align:center">'
        f'{"✅" if r["price_above_sma20"] else "❌"}</td>',
        # >SMA9
        f'<td style="background:{bg};padding:7px 10px;text-align:center">'
        f'{"✅" if r["price_above_sma9"] else "❌"}</td>',
        # Earnings
        f'<td style="background:{bg};padding:7px 10px;text-align:center">'
        f'{_render_earnings(r["days_to_earnings"], r["earnings_flag"])}</td>',
        # Candles
        f'<td style="background:{bg};padding:7px 10px">{_render_candles(r["candle_patterns"])}</td>',
        # RS vs SPY
        f'<td style="background:{bg};padding:7px 10px">{_render_rs(r["rs_status"], r["rs_pct"])}</td>',
        # Sector ETF
        f'<td style="background:{bg};padding:7px 10px">{_render_sector(r["sector_etf"], r["sector_trending"])}</td>',
        # Flags
        f'<td style="background:{bg};padding:7px 10px">{_render_flags(r["flags"])}</td>',
    ]
    return "<tr>" + "".join(cells) + "</tr>"


def _build_table_html(rows: list[dict], benchmark_label: str = "RS vs SPY") -> str:
    """Build a complete scrollable HTML table for the given rows."""
    # Header
    th_style = (
        f'style="background:{BG_PANEL};color:{GOLD};font-size:10px;'
        f'font-weight:700;text-transform:uppercase;letter-spacing:0.8px;'
        f'padding:8px 10px;white-space:nowrap;'
        f'border-bottom:2px solid {GOLD}55;position:sticky;top:0;z-index:5"'
    )
    header_cells = "".join(
        f'<th {th_style} width="{w}">{col}</th>'
        for col, w in _get_columns(benchmark_label)
    )
    header = f"<thead><tr>{header_cells}</tr></thead>"

    # Body rows alternating background
    body_rows = "".join(
        _row_html(r, BG_CARD if i % 2 == 0 else BG_PANEL)
        for i, r in enumerate(rows)
    )
    body = f"<tbody>{body_rows}</tbody>"

    return (
        f'<div style="overflow-x:auto;max-height:520px;overflow-y:auto;'
        f'border:1px solid {BORDER_COLOR};border-radius:8px">'
        f'<table style="border-collapse:collapse;width:100%;font-size:12px">'
        f'{header}{body}'
        f'</table></div>'
    )


# ── Table 4 columns, row builder, and table builder ──────────────────────────

def _get_columns_t4(benchmark_label: str = "RS vs SPY") -> list:
    return [
        ("Ticker",        "130px"),
        ("Price",         "70px"),
        ("Wk MACD",       "170px"),
        ("Dly MACD",      "150px"),
        ("RSI  W / D",    "155px"),
        ("Vol Ratio",     "90px"),
        ("Candles",       "185px"),
        (benchmark_label, "160px"),
        ("Sector ETF",    "120px"),
        ("Flags",         "210px"),
    ]


def _row_html_t4(r: dict, bg: str) -> str:
    """Render a single Table 4 data row as an HTML <tr>."""
    # Ticker cell — gold monospace + coloured circle if also in Tables 1–3
    _table_circle = {1: ("🟢", "PRIME"),
                     2: ("🟡", "STRONG"),
                     3: ("🔵", "BUILDING")}
    _tbl = r.get("in_main_tables", 0)
    ticker_html = (
        f'<span style="color:{GOLD};font-family:\'DM Mono\',monospace;'
        f'font-weight:700;font-size:13px">{r["ticker"]}</span>'
    )
    if _tbl in _table_circle:
        _circle, _label = _table_circle[_tbl]
        ticker_html += (
            f' <span title="Also in Table {_tbl} — {_label}" '
            f'style="font-size:12px">{_circle}</span>'
        )

    cells = [
        f'<td style="background:{bg};padding:7px 10px;white-space:nowrap">{ticker_html}</td>',
        # Price
        f'<td style="background:{bg};padding:7px 10px;color:{TEXT_PRIMARY};'
        f'font-family:\'DM Mono\',monospace;font-size:12px">${r["price"]:.2f}</td>',
        # Weekly MACD
        f'<td style="background:{bg};padding:7px 10px">'
        f'{_render_wk_macd_t4(r["wk_macd_line"], r["wk_macd_hist"], r["wk_macd_hist_rising"])}</td>',
        # Daily MACD
        f'<td style="background:{bg};padding:7px 10px">'
        f'{_render_dly_macd_t4(r["macd_value"], r["macd_hist"])}</td>',
        # RSI W / D
        f'<td style="background:{bg};padding:7px 10px">'
        f'{_render_rsi_combined(r["wk_rsi_value"], r["rsi_value"])}</td>',
        # Vol Ratio
        f'<td style="background:{bg};padding:7px 10px">'
        f'{_render_volume(r["volume_ratio"], r["volume_ok"])}</td>',
        # Candles
        f'<td style="background:{bg};padding:7px 10px">'
        f'{_render_candles(r["candle_patterns"])}</td>',
        # RS vs SPY
        f'<td style="background:{bg};padding:7px 10px">'
        f'{_render_rs(r["rs_status"], r["rs_pct"])}</td>',
        # Sector ETF
        f'<td style="background:{bg};padding:7px 10px">'
        f'{_render_sector(r["sector_etf"], r["sector_trending"])}</td>',
        # Flags
        f'<td style="background:{bg};padding:7px 10px">'
        f'{_render_flags(r["flags"])}</td>',
    ]
    return "<tr>" + "".join(cells) + "</tr>"


def _build_table_html_t4(rows: list[dict], benchmark_label: str = "RS vs SPY") -> str:
    """Build a complete scrollable HTML table for Table 4 rows."""
    th_style = (
        f'style="background:{BG_PANEL};color:{GOLD};font-size:10px;'
        f'font-weight:700;text-transform:uppercase;letter-spacing:0.8px;'
        f'padding:8px 10px;white-space:nowrap;'
        f'border-bottom:2px solid {GOLD}55;position:sticky;top:0;z-index:5"'
    )
    header_cells = "".join(
        f'<th {th_style} width="{w}">{col}</th>'
        for col, w in _get_columns_t4(benchmark_label)
    )
    header = f"<thead><tr>{header_cells}</tr></thead>"

    body_rows = "".join(
        _row_html_t4(r, BG_CARD if i % 2 == 0 else BG_PANEL)
        for i, r in enumerate(rows)
    )
    body = f"<tbody>{body_rows}</tbody>"

    return (
        f'<div style="overflow-x:auto;max-height:520px;overflow-y:auto;'
        f'border:1px solid {BORDER_COLOR};border-radius:8px">'
        f'<table style="border-collapse:collapse;width:100%;font-size:12px">'
        f'{header}{body}'
        f'</table></div>'
    )


# ── Summary bar ───────────────────────────────────────────────────────────────

def _summary_bar(results: dict) -> None:
    n1 = len(results["table1"])
    n2 = len(results["table2"])
    n3 = len(results["table3"])
    n4 = len(results.get("table4", []))
    elapsed = results["scan_time"]
    total   = results["total_scanned"]

    # Count Table 4 tickers that are also in Tables 1–3 (by table)
    n4_cross = sum(1 for r in results.get("table4", []) if r.get("in_main_tables", 0) > 0)

    st.markdown(
        f'<div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};'
        f'border-radius:8px;padding:12px 20px;margin:12px 0;'
        f'display:flex;flex-wrap:wrap;gap:20px;align-items:center">'
        f'<span style="color:{TEXT_MUTED};font-size:13px">'
        f'Scanned <b style="color:{TEXT_PRIMARY}">{total}</b> stocks'
        f'</span>'
        f'<span style="color:{ACCENT_GREEN};font-size:13px;font-weight:700">'
        f'🟢 Table 1: {n1}</span>'
        f'<span style="color:#FBBF24;font-size:13px;font-weight:700">'
        f'🟡 Table 2: {n2}</span>'
        f'<span style="color:{ACCENT_BLUE};font-size:13px;font-weight:700">'
        f'🔵 Table 3: {n3}</span>'
        f'<span style="color:#A78BFA;font-size:13px;font-weight:700">'
        f'💜 Table 4: {n4}'
        + (f' <span style="font-size:11px;color:{TEXT_MUTED}">(💚 {n4_cross} cross)</span>' if n4_cross else '')
        + f'</span>'
        f'<span style="color:{TEXT_MUTED};font-size:12px">'
        f'⏱ Time: {elapsed:.1f}s</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ── Table section (expander + table + qualifier note) ────────────────────────

def _render_table_section(
    title: str,
    rows: list[dict],
    qualifier_note: str,
    expanded: bool,
    benchmark_label: str = "RS vs SPY",
) -> None:
    with st.expander(title, expanded=expanded):
        if not rows:
            st.markdown(
                f'<div style="text-align:center;padding:32px;color:{TEXT_MUTED};font-size:14px">'
                f'No setups found in this category for the current universe.</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(_build_table_html(rows, benchmark_label), unsafe_allow_html=True)

        # Qualifier note
        st.markdown(
            f'<div style="background:{BG_CARD};border-left:3px solid {GOLD}55;'
            f'border-radius:0 6px 6px 0;padding:10px 16px;margin-top:12px;'
            f'color:{TEXT_MUTED};font-size:12px;line-height:1.6">'
            f'<b style="color:{GOLD}">Qualifier:</b> {qualifier_note}</div>',
            unsafe_allow_html=True,
        )


# ── Tech details help content ──────────────────────────────────────────────────

def _render_tech_details() -> None:
    """Collapsible technical reference section for MTPA conditions."""
    with st.expander("📖 MTPA Technical Reference — Conditions & Definitions", expanded=False):
        st.markdown(f"""
<div style="color:{TEXT_PRIMARY};font-size:13px;line-height:1.9">

<b style="color:{GOLD}">MTPA Scanner — Momentum Trend Price Action</b><br>
A pure-filter, no-score scanner that categorizes stocks by how many timeframes are aligned.

<hr style="border-color:{BORDER_COLOR};margin:12px 0">

<b style="color:{GOLD}">Weekly Conditions</b>
<ul>
<li><b>HH/HL</b> — Last 6 weekly bars show consecutively higher highs AND higher lows (clean uptrend structure).</li>
<li><b>Tight Base</b> — Average weekly ATR% (High − Low) / Close over last 5 bars &lt; 4.5% (low-volatility consolidation).</li>
<li><b>Mixed</b> — Neither pattern detected.</li>
<li><b>Wk Extended</b> — Weekly close is &gt; Weekly EMA(20) × 1.10 (stretched, risk of mean-reversion).
  PRIME and STRONG tables require this to be OFF.</li>
</ul>

<b style="color:{GOLD}">Daily Conditions</b>
<ul>
<li><b>RSI GREEN</b> — RSI(14) is 50–70 AND rising vs 2 bars ago (momentum building in sweet spot).</li>
<li><b>RSI YELLOW</b> — RSI(14) is 40–50 AND rising (recovering from weakness).</li>
<li><b>RSI NEUTRAL</b> — All other cases (not rising or outside range).</li>
<li><b>MACD &gt; Sig</b> — EMA(12) − EMA(26) &gt; Signal line (9-period EMA of MACD). Indicates bullish crossover.</li>
<li><b>MACD Zone</b> — 🎯 Near Zero: |MACD| ≤ 3 (display label only). 📈 Positive: &gt;3. 📉 Negative: &lt;−3.
  Table 1 uses price-normalised threshold (|MACD| ≤ 1% of price) rather than the fixed ±3 display zones.</li>
<li><b>Vol Ratio</b> — Today's volume ÷ 20-day average. Volume OK = 1.0–1.8× (healthy interest, not a spike).</li>
<li><b>&gt;SMA20 / &gt;SMA9</b> — Price above its 20-day or 9-day simple moving average.</li>
</ul>

<b style="color:{GOLD}">Earnings Proximity</b>
<ul>
<li><b>SKIP (red)</b> — Earnings in ≤ 7 days. Excluded from PRIME table to avoid event risk.</li>
<li><b>WARN (orange)</b> — Earnings in 8–14 days. Shown in all tables; flagged as "Earnings Soon".</li>
<li><b>OK (green)</b> — Earnings &gt; 14 days away or unknown.</li>
</ul>

<b style="color:{GOLD}">Candlestick Patterns (last 3 bars)</b><br>
Hammer · Bullish Engulfing · Morning Star · Piercing Line · Bullish Harami ·
Three White Soldiers · Dragonfly Doji · Inverted Hammer · Tweezer Bottom

<b style="color:{GOLD}">Relative Strength vs SPY (10-day)</b>
<ul>
<li><b>OUTPERFORM</b> — Ticker 10-day return / SPY 10-day return &gt; 1.02.</li>
<li><b>MATCH</b> — Ratio 0.95–1.02.</li>
<li><b>UNDERPERFORM</b> — Ratio &lt; 0.95.</li>
</ul>

<b style="color:{GOLD}">Table Assignment (dedup, Table 1 priority)</b>
<ul>
<li><b>🟢 PRIME (Table 1)</b> — Weekly HH/HL or Tight Base · Not extended · RSI GREEN/YELLOW ·
  MACD &gt; Signal · Volume OK · Price &gt; SMA20 · |MACD| ≤ 1% of price (fresh crossover) · Earnings not SKIP</li>
<li><b>🟡 STRONG (Table 2)</b> — Not extended · RSI GREEN/YELLOW · MACD &gt; Signal · Price &gt; SMA20</li>
<li><b>🔵 BUILDING (Table 3)</b> — RSI GREEN/YELLOW · MACD &gt; Signal</li>
</ul>
Each ticker appears in at most one table (highest priority wins).

<b style="color:#A78BFA">💜 MACD MOMENTUM (Table 4) — Independent, no dedup</b>
<ul>
<li><b>Weekly</b>: MACD Line &gt; 0 (EMA12 &gt; EMA26 on weekly) · Histogram &gt; 0 (MACD &gt; Signal) ·
  Histogram ↑ rising (accelerating momentum, not peaking)</li>
<li><b>Daily</b>: MACD Line &gt; 0 · Histogram &gt; 0</li>
<li>Appears independently of Tables 1–3. A ticker may appear in both Table 4 and Table 1/2/3.</li>
<li><b>🟢 🟡 🔵 Circle indicator</b> — ticker also qualifies in Table 1 (PRIME), Table 2 (STRONG), or Table 3 (BUILDING) respectively. Hover over the circle to see which table. No circle = MACD signal only, not yet confirmed by full structure.</li>
<li>RSI column shows <b>W: weekly RSI</b> and <b>D: daily RSI</b> side-by-side, color-coded:
  <span style="color:#22C55E">■ GREEN</span> = 50–70 · <span style="color:#FBBF24">■ YELLOW</span> = 40–50 · grey = outside range.</li>
</ul>
</div>""", unsafe_allow_html=True)


# ── Main render function ───────────────────────────────────────────────────────

def render() -> None:
    """Entry point — renders the MTPA Scanner admin page."""

    section_header(
        "📊",
        "MTPA Scanner — Momentum Trend Price Action",
        "Admin Only · Multi-Timeframe Filter · No Scoring",
    )

    # ── Market selector ────────────────────────────────────────────
    market_choice = st.radio(
        "Market",
        options=["🇺🇸 US Stocks  (MTPA 200)", "🇮🇳 Indian Stocks  (Nifty 150)"],
        index=0,
        horizontal=True,
        key="_mtpa_market",
        label_visibility="collapsed",
    )
    market_code = "IN" if "Indian" in market_choice else "US"

    # ── Scan controls ──────────────────────────────────────────────
    _has_results = _SESSION_KEY in st.session_state
    c1, c2, c3, _gap = st.columns([2, 1, 1.5, 3])
    with c1:
        run_btn = st.button("▶ Run MTPA Scan", use_container_width=True, key="_mtpa_run")
    with c2:
        if st.button("🔄 Clear", use_container_width=True, key="_mtpa_clear"):
            st.session_state.pop(_SESSION_KEY, None)
            st.cache_data.clear()
            st.rerun()
    with c3:
        export_btn = st.button(
            "📤 Export to Sheets",
            use_container_width=True,
            key="_mtpa_export",
            disabled=not _has_results,
            help="Export all tables to 'MTPA Tracker' Google Sheet (tab = today's date)",
        )

    # Last scan time display
    if _SESSION_KEY in st.session_state:
        ts = st.session_state.get("_mtpa_scan_ts", "")
        if ts:
            st.markdown(
                f'<div style="color:{TEXT_MUTED};font-size:11px;margin-top:4px">'
                f'Last scan: {ts}</div>',
                unsafe_allow_html=True,
            )

    # ── Run scan ───────────────────────────────────────────────────
    if run_btn:
        _universe_label = (
            "MTPA 200 universe" if market_code == "US" else "India 150 universe"
        )
        with st.spinner(f"Running MTPA scan across {_universe_label}…"):
            _label_ph = st.empty()
            _prog_ph  = st.progress(0)
            results = run_mtpa_scan(
                tickers=None,            # scanner chooses list based on market
                progress_label=_label_ph,
                progress_bar=_prog_ph,
                market=market_code,
            )
        st.session_state[_SESSION_KEY]    = results
        st.session_state["_mtpa_scan_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # FTF results come directly from the MTPA scan — zero extra API calls
        st.session_state["_mtpa_ftf"]     = results.get("table_ftf", [])

        st.rerun()

    # ── Display results ────────────────────────────────────────────
    results = st.session_state.get(_SESSION_KEY)

    if results is None:
        # Pre-scan landing state
        st.markdown(
            f'<div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};'
            f'border-radius:8px;padding:40px;text-align:center;margin-top:20px">'
            f'<div style="font-size:40px;margin-bottom:14px">📊</div>'
            f'<div style="font-size:16px;color:{TEXT_PRIMARY};margin-bottom:8px">'
            f'MTPA — Momentum Trend Price Action</div>'
            f'<div style="font-size:13px;color:{TEXT_MUTED};line-height:1.8">'
            f'Filters stocks by weekly structure, daily MACD/RSI alignment, volume health,<br>'
            f'earnings proximity, candlestick patterns, and relative strength.<br>'
            f'No scoring — pure qualification into three tier tables.</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:11px;margin-top:16px;'
            f'padding:10px 14px;background:{BG_PANEL};border-radius:6px;'
            f'border-left:3px solid {BORDER_COLOR}">'
            f'📖 Full filter logic, table criteria, and candlestick reference → '
            f'<b style="color:{GOLD}">Admin → Tech Details → MTPA Reference</b> tab'
            f'</div>',
            unsafe_allow_html=True,
        )
        return

    # ── Handle Export ──────────────────────────────────────────────
    if export_btn:
        with st.spinner("Exporting to MTPA Tracker…"):
            _ok, _msg = export_mtpa_scan(results)
        if _ok:
            st.toast(f"✅ {_msg}", icon="📊")
        else:
            st.toast(f"❌ {_msg}", icon="⚠️")

    # ── Market mismatch notice ──────────────────────────────────────
    _result_market = results.get("market", "US")
    if _result_market != market_code:
        _was = "🇺🇸 US" if _result_market == "US" else "🇮🇳 Indian"
        _want = "🇮🇳 Indian" if market_code == "IN" else "🇺🇸 US"
        st.info(
            f"Results below are for **{_was} stocks**. "
            f"Click ▶ Run to scan **{_want} stocks**.",
            icon="ℹ️",
        )

    # ── Pull benchmark label from actual scan results ───────────────
    _benchmark_label = results.get("benchmark_label", "RS vs SPY")

    # Summary bar
    _summary_bar(results)

    # Error/failure notice (non-crashing)
    failed = results.get("failed", [])
    if failed:
        with st.expander(f"⚠️ {len(failed)} ticker(s) failed to scan", expanded=False):
            st.markdown(
                f'<div style="color:{TEXT_MUTED};font-size:12px">'
                + "<br>".join(failed)
                + "</div>",
                unsafe_allow_html=True,
            )

    # ── First Things First ─────────────────────────────────────────
    ftf_rows = st.session_state.get("_mtpa_ftf", [])
    render_ftf_section(ftf_rows, context="mtpa")

    # ── Table 1 — PRIME ────────────────────────────────────────────
    n1 = len(results["table1"])
    _render_table_section(
        title=f"🟢 PRIME Setups — Full Alignment ({n1} stocks)",
        rows=results["table1"],
        qualifier_note=(
            "Weekly HH/HL or Tight Base · Not Over-Extended · "
            "RSI GREEN or YELLOW · MACD &gt; Signal · Volume OK (1–1.8×) · "
            "Price &gt; SMA20 · |MACD| ≤ 1% of price (fresh setup) · Earnings &gt; 7 days"
        ),
        expanded=True,
        benchmark_label=_benchmark_label,
    )

    # ── Table 2 — STRONG ───────────────────────────────────────────
    n2 = len(results["table2"])
    _render_table_section(
        title=f"🟡 STRONG Setups — Weekly Clean + Daily Confirmed ({n2} stocks)",
        rows=results["table2"],
        qualifier_note=(
            "Not Over-Extended (weekly) · RSI GREEN or YELLOW · "
            "MACD &gt; Signal · Price &gt; SMA20 · (Any MACD zone allowed)"
        ),
        expanded=False,
        benchmark_label=_benchmark_label,
    )

    # ── Table 3 — BUILDING ─────────────────────────────────────────
    n3 = len(results["table3"])
    _render_table_section(
        title=f"🔵 BUILDING Setups — Daily Signal Only ({n3} stocks)",
        rows=results["table3"],
        qualifier_note=(
            "RSI GREEN or YELLOW · MACD &gt; Signal · "
            "(Weekly structure and volume not required)"
        ),
        expanded=False,
        benchmark_label=_benchmark_label,
    )

    # ── Table 4 — MACD MOMENTUM ────────────────────────────────────
    t4_rows = results.get("table4", [])
    n4      = len(t4_rows)
    n4_cross = sum(1 for r in t4_rows if r.get("in_main_tables"))
    cross_note = (
        f' · <b style="color:{ACCENT_GREEN}">💚 = {n4_cross} also in Tables 1–3</b>'
        if n4_cross else ""
    )
    with st.expander(
        f"💜 MACD MOMENTUM — Both Timeframes Confirmed ({n4} stocks)",
        expanded=False,
    ):
        if not t4_rows:
            st.markdown(
                f'<div style="text-align:center;padding:32px;color:{TEXT_MUTED};font-size:14px">'
                f'No tickers met the MACD Momentum criteria for the current universe.</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(_build_table_html_t4(t4_rows, _benchmark_label), unsafe_allow_html=True)

        st.markdown(
            f'<div style="background:{BG_CARD};border-left:3px solid #A78BFA55;'
            f'border-radius:0 6px 6px 0;padding:10px 16px;margin-top:12px;'
            f'color:{TEXT_MUTED};font-size:12px;line-height:1.6">'
            f'<b style="color:#A78BFA">Qualifier:</b> '
            f'Weekly MACD Line &gt; 0 · Weekly Hist &gt; 0 · Weekly Hist ↑ rising · '
            f'Daily MACD Line &gt; 0 · Daily Hist &gt; 0 · '
            f'Independent — no dedup vs Tables 1–3 · 🟢 also in PRIME · 🟡 also in STRONG · 🔵 also in BUILDING{cross_note}</div>',
            unsafe_allow_html=True,
        )

    # ── Tech reference pointer ─────────────────────────────────────
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:10px;text-align:right;'
        f'margin-top:8px">📖 Filter logic & definitions → '
        f'<b style="color:{GOLD}">Admin → Tech Details → MTPA Reference</b></div>',
        unsafe_allow_html=True,
    )
