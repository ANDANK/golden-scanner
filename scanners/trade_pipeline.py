# scanners/trade_pipeline.py — Trade Pipeline
# Merges: Scheduled Scans · Tracking · Performance
# Full-width green tabs + pipeline flow diagram

import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *


# ── Tab + page CSS ─────────────────────────────────────────────

_TAB_CSS = f"""
<style>
/* ── Full-width green tab bar ──────────────────────────────── */
div[data-testid="stTabs"] > div:first-child {{
    gap: 0 !important;
    border-bottom: 2px solid {ACCENT_GREEN}55 !important;
    margin-bottom: 0 !important;
    padding: 0 !important;
}}
div[data-testid="stTabs"] > div:first-child > button {{
    flex: 1 1 0 !important;
    justify-content: center !important;
    font-size: 14px !important;
    font-weight: 600 !important;
    letter-spacing: 0.4px !important;
    padding: 14px 0 !important;
    border-radius: 0 !important;
    background: transparent !important;
    color: {TEXT_MUTED} !important;
    border-bottom: 3px solid transparent !important;
    transition: background 0.15s, color 0.15s !important;
}}
div[data-testid="stTabs"] > div:first-child > button:hover {{
    background: {ACCENT_GREEN}12 !important;
    color: {ACCENT_GREEN} !important;
}}
div[data-testid="stTabs"] > div:first-child > button[aria-selected="true"] {{
    background: {ACCENT_GREEN}18 !important;
    color: {ACCENT_GREEN} !important;
    border-bottom: 3px solid {ACCENT_GREEN} !important;
    font-weight: 700 !important;
}}
/* Remove the default Streamlit tab underline override */
div[data-testid="stTabs"] > div:first-child > button[aria-selected="true"]::after {{
    display: none !important;
}}
</style>
"""


# ── Pipeline flow diagram ───────────────────────────────────

def _render_pipeline_diagram():
    G  = ACCENT_GREEN
    BL = "#60A5FA"    # blue accent
    GL = GOLD

    st.markdown(
        f"""
        <div style="background:linear-gradient(135deg,{BG_CARD},{BG_PANEL});
                    border:1px solid {G}33;border-radius:12px;
                    padding:24px 28px 20px;margin-bottom:0">

          <!-- Title -->
          <div style="color:{TEXT_MUTED};font-size:10px;font-weight:700;
                      text-transform:uppercase;letter-spacing:1.5px;margin-bottom:18px">
            ⚡ How the Trade Pipeline Works
          </div>

          <!-- Stage boxes + arrows -->
          <div style="display:flex;align-items:stretch;gap:0;width:100%">

            <!-- Stage 1: Auto-Scanner -->
            <div style="flex:1;background:{G}0E;border:1px solid {G}44;border-radius:10px;
                        padding:16px 18px;position:relative">
              <div style="color:{G};font-size:11px;font-weight:800;text-transform:uppercase;
                          letter-spacing:1px;margin-bottom:6px">1 · Auto-Scanner</div>
              <div style="color:{TEXT_PRIMARY};font-size:18px;font-weight:700;
                          margin-bottom:8px;line-height:1.2">Runs every<br>market day</div>
              <div style="color:{TEXT_MUTED};font-size:11px;line-height:1.7">
                ⏰ <b style="color:{TEXT_PRIMARY}">10:30 AM CST</b> — Morning scan<br>
                ⏰ <b style="color:{TEXT_PRIMARY}">1:00 PM CST</b> — Afternoon scan<br><br>
                Scans: <b style="color:{G}">Golden Scan</b> (top 250 stocks),
                <b style="color:{G}">CSP</b> &amp; <b style="color:{G}">LEAPS</b>
                (75 stocks + options ETFs).<br><br>
                Results are saved as JSON and appear instantly on the
                <b>Scheduled Scans</b> tab — no manual action needed.
              </div>
            </div>

            <!-- Arrow 1→2 -->
            <div style="display:flex;flex-direction:column;align-items:center;
                        justify-content:center;padding:0 10px;flex-shrink:0">
              <div style="color:{G};font-size:28px;line-height:1">→</div>
              <div style="color:{TEXT_MUTED};font-size:9px;text-align:center;
                          margin-top:4px;white-space:nowrap">Score ≥ 60</div>
            </div>

            <!-- Stage 2: Auto-Tracking -->
            <div style="flex:1;background:{BL}0E;border:1px solid {BL}44;border-radius:10px;
                        padding:16px 18px">
              <div style="color:{BL};font-size:11px;font-weight:800;text-transform:uppercase;
                          letter-spacing:1px;margin-bottom:6px">2 · Auto-Tracking</div>
              <div style="color:{TEXT_PRIMARY};font-size:18px;font-weight:700;
                          margin-bottom:8px;line-height:1.2">High-score<br>setups logged</div>
              <div style="color:{TEXT_MUTED};font-size:11px;line-height:1.7">
                Any setup scoring <b style="color:{BL}">≥ 60</b> is automatically written
                to the <b>Tracking</b> sheet in Google Sheets.<br><br>
                De-duplication runs on every write — same ticker + strategy + date
                is never added twice, even if both AM and PM scans surface it.<br><br>
                You can also add setups manually from any scanner page.
              </div>
            </div>

            <!-- Arrow 2→3 -->
            <div style="display:flex;flex-direction:column;align-items:center;
                        justify-content:center;padding:0 10px;flex-shrink:0">
              <div style="color:{GL};font-size:28px;line-height:1">→</div>
              <div style="color:{TEXT_MUTED};font-size:9px;text-align:center;
                          margin-top:4px;white-space:nowrap">Score &gt; 70<br>AM/PM only</div>
            </div>

            <!-- Stage 3: Performance -->
            <div style="flex:1;background:{GL}0E;border:1px solid {GL}44;border-radius:10px;
                        padding:16px 18px">
              <div style="color:{GL};font-size:11px;font-weight:800;text-transform:uppercase;
                          letter-spacing:1px;margin-bottom:6px">3 · Performance</div>
              <div style="color:{TEXT_PRIMARY};font-size:18px;font-weight:700;
                          margin-bottom:8px;line-height:1.2">Outcomes<br>tracked</div>
              <div style="color:{TEXT_MUTED};font-size:11px;line-height:1.7">
                Only <b style="color:{GL}">AM · / PM ·</b> scan results with
                score <b style="color:{GL}">&gt; 70</b> are promoted to Performance
                — the highest-conviction automated picks only.<br><br>
                Manually tracked items and lower-score setups stay in Tracking only.<br><br>
                Use Performance to measure the actual quality of the scanner signals
                over time and refine your entry criteria.
              </div>
            </div>

          </div><!-- end flex -->

          <!-- Footer note -->
          <div style="display:flex;gap:24px;flex-wrap:wrap;margin-top:16px;
                      padding-top:14px;border-top:1px solid {BORDER_COLOR}44">
            <div style="color:{TEXT_MUTED};font-size:11px;line-height:1.8">
              <b style="color:{G}">Scheduled Scans tab</b> — View latest AM &amp; PM
              results, compare what changed between runs, export CSV.
            </div>
            <div style="color:{TEXT_MUTED};font-size:11px;line-height:1.8">
              <b style="color:{BL}">Tracking tab</b> — Full list of all tracked setups
              (auto + manual), add notes, update outcomes.
            </div>
            <div style="color:{TEXT_MUTED};font-size:11px;line-height:1.8">
              <b style="color:{GL}">Performance tab</b> — P&amp;L dashboard, win rates,
              monthly breakdown — for scheduled scan picks only.
            </div>
          </div>

        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Main render ────────────────────────────────────────────────

def render():
    # Inject full-width green tab CSS
    st.markdown(_TAB_CSS, unsafe_allow_html=True)

    # Flow diagram (always visible, above tabs)
    _render_pipeline_diagram()

    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

    # ── Three full-width tabs ──────────────────────────────────
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
