# scanners/trade_pipeline.py — Auto Scan & Track
# Merges: Scheduled Scans · Tracking · Performance
# Full-width green tabs + pipeline flow diagram

import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *


# ── Tab CSS (full-width green buttons) ────────────────────────

_TAB_CSS = (
    f'<style>'
    f'div[data-testid="stTabs"] > div:first-child {{'
    f'  gap:0 !important;'
    f'  border-bottom:2px solid {ACCENT_GREEN}55 !important;'
    f'  margin-bottom:0 !important;'
    f'  padding:0 !important;'
    f'}}'
    f'div[data-testid="stTabs"] > div:first-child > button {{'
    f'  flex:1 1 0 !important;'
    f'  justify-content:center !important;'
    f'  font-size:14px !important;'
    f'  font-weight:600 !important;'
    f'  letter-spacing:0.4px !important;'
    f'  padding:14px 0 !important;'
    f'  border-radius:0 !important;'
    f'  background:transparent !important;'
    f'  color:{TEXT_MUTED} !important;'
    f'  border-bottom:3px solid transparent !important;'
    f'  transition:background 0.15s,color 0.15s !important;'
    f'}}'
    f'div[data-testid="stTabs"] > div:first-child > button:hover {{'
    f'  background:{ACCENT_GREEN}12 !important;'
    f'  color:{ACCENT_GREEN} !important;'
    f'}}'
    f'div[data-testid="stTabs"] > div:first-child > button[aria-selected="true"] {{'
    f'  background:{ACCENT_GREEN}18 !important;'
    f'  color:{ACCENT_GREEN} !important;'
    f'  border-bottom:3px solid {ACCENT_GREEN} !important;'
    f'  font-weight:700 !important;'
    f'}}'
    f'div[data-testid="stTabs"] > div:first-child > button[aria-selected="true"]::after {{'
    f'  display:none !important;'
    f'}}'
    f'</style>'
)


# ── Pipeline flow diagram ─────────────────────────────────────

def _render_pipeline_diagram():
    G  = ACCENT_GREEN
    BL = "#60A5FA"
    GL = GOLD

    # ── Outer wrapper ─────────────────────────────────────────
    st.markdown(
        f'<div style="background:linear-gradient(135deg,{BG_CARD},{BG_PANEL});'
        f'border:1px solid {G}33;border-radius:12px;padding:22px 24px 18px;margin-bottom:0">'

        # Title row
        f'<div style="color:{TEXT_MUTED};font-size:10px;font-weight:700;'
        f'text-transform:uppercase;letter-spacing:1.5px;margin-bottom:16px">'
        f'&#9889; How Auto Scan &amp; Track Works</div>'

        # Stage flex container
        f'<div style="display:flex;align-items:stretch;gap:0;width:100%">'

        # ── Stage 1 ────────────────────────────────────────
        f'<div style="flex:1;background:{G}0E;border:1px solid {G}44;'
        f'border-radius:10px;padding:14px 16px">'
        f'<div style="color:{G};font-size:10px;font-weight:800;text-transform:uppercase;'
        f'letter-spacing:1px;margin-bottom:5px">1 · Auto-Scanner</div>'
        f'<div style="color:{TEXT_PRIMARY};font-size:16px;font-weight:700;'
        f'margin-bottom:7px;line-height:1.25">Runs every<br>market day</div>'
        f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.75">'
        f'&#8987; <b style="color:{TEXT_PRIMARY}">10:30 AM CST</b> — Morning scan<br>'
        f'&#8987; <b style="color:{TEXT_PRIMARY}">1:00 PM CST</b> — Afternoon scan<br><br>'
        f'Scans: <b style="color:{G}">Golden Scan</b> (top 250 stocks), '
        f'<b style="color:{G}">CSP</b> &amp; <b style="color:{G}">LEAPS</b> '
        f'(75 stocks + options ETFs).<br><br>'
        f'Results are saved as JSON and appear instantly on the '
        f'<b>Scheduled Scans</b> tab — no manual action needed.'
        f'</div></div>'

        # ── Arrow 1 → 2 ────────────────────────────────────
        f'<div style="display:flex;flex-direction:column;align-items:center;'
        f'justify-content:center;padding:0 10px;flex-shrink:0">'
        f'<div style="color:{G};font-size:26px;line-height:1">&#8594;</div>'
        f'<div style="color:{TEXT_MUTED};font-size:9px;text-align:center;'
        f'margin-top:3px;white-space:nowrap">Score &#8805; 60</div>'
        f'</div>'

        # ── Stage 2 ────────────────────────────────────────
        f'<div style="flex:1;background:{BL}0E;border:1px solid {BL}44;'
        f'border-radius:10px;padding:14px 16px">'
        f'<div style="color:{BL};font-size:10px;font-weight:800;text-transform:uppercase;'
        f'letter-spacing:1px;margin-bottom:5px">2 · Auto-Tracking</div>'
        f'<div style="color:{TEXT_PRIMARY};font-size:16px;font-weight:700;'
        f'margin-bottom:7px;line-height:1.25">High-score<br>setups logged</div>'
        f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.75">'
        f'Any setup scoring <b style="color:{BL}">&#8805; 60</b> is automatically '
        f'written to the <b>Tracking</b> sheet in Google Sheets.<br><br>'
        f'De-duplication runs on every write — same ticker + strategy + date '
        f'is never added twice, even if both AM and PM scans surface it.<br><br>'
        f'You can also add setups manually from any scanner page.'
        f'</div></div>'

        # ── Arrow 2 → 3 ────────────────────────────────────
        f'<div style="display:flex;flex-direction:column;align-items:center;'
        f'justify-content:center;padding:0 10px;flex-shrink:0">'
        f'<div style="color:{GL};font-size:26px;line-height:1">&#8594;</div>'
        f'<div style="color:{TEXT_MUTED};font-size:9px;text-align:center;'
        f'margin-top:3px;white-space:nowrap">Score &gt; 70<br>AM/PM only</div>'
        f'</div>'

        # ── Stage 3 ────────────────────────────────────────
        f'<div style="flex:1;background:{GL}0E;border:1px solid {GL}44;'
        f'border-radius:10px;padding:14px 16px">'
        f'<div style="color:{GL};font-size:10px;font-weight:800;text-transform:uppercase;'
        f'letter-spacing:1px;margin-bottom:5px">3 · Performance</div>'
        f'<div style="color:{TEXT_PRIMARY};font-size:16px;font-weight:700;'
        f'margin-bottom:7px;line-height:1.25">Outcomes<br>tracked</div>'
        f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.75">'
        f'Only <b style="color:{GL}">AM&#183; / PM&#183;</b> scan results with '
        f'score <b style="color:{GL}">&gt; 70</b> are promoted to Performance '
        f'— the highest-conviction automated picks only.<br><br>'
        f'Manually tracked items and lower-score setups stay in Tracking only.<br><br>'
        f'Use Performance to measure scanner signal quality over time.'
        f'</div></div>'

        f'</div>'  # end stage flex

        # ── Footer legend ──────────────────────────────────
        f'<div style="display:flex;gap:20px;flex-wrap:wrap;margin-top:14px;'
        f'padding-top:12px;border-top:1px solid {BORDER_COLOR}44">'
        f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.8">'
        f'<b style="color:{G}">Scheduled Scans tab</b> — Latest AM &amp; PM results, '
        f'compare what changed between runs, export CSV.</div>'
        f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.8">'
        f'<b style="color:{BL}">Tracking tab</b> — All tracked setups (auto + manual), '
        f'add notes, update outcomes.</div>'
        f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.8">'
        f'<b style="color:{GL}">Performance tab</b> — P&amp;L dashboard, win rates, '
        f'monthly breakdown for scheduled-scan picks.</div>'
        f'</div>'

        f'</div>',  # end outer wrapper
        unsafe_allow_html=True,
    )


# ── Main render ────────────────────────────────────────────────

def render():
    st.markdown(_TAB_CSS, unsafe_allow_html=True)

    _render_pipeline_diagram()

    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs([
        "📅  Scheduled Scans",
        "📌  Tracking",
        "📈  Performance",
    ])

    with tab1:
        from scanners.scheduled_scans import render as _render_scans
        _render_scans()

    with tab2:
        from scanners.tracking_page import render as _render_tracking
        _render_tracking()

    with tab3:
        try:
            from scanners.performance_summary import render as _render_perf
        except ImportError:
            from scanners.tracking_page import render as _render_perf
        _render_perf()
