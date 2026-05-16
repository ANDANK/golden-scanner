# app.py — Golden Scanner Main Entry
# ─────────────────────────────────────────────────────────────────
# PATCHED 2026-05 to apply the Golden Scanner Design System v1:
#   • Sidebar nav rewritten as 6 uniform collapsible groups
#     (Dashboard / Stocks / Options / Dividend / Info / Admin)
#   • Filled gold-gradient section headers (st.expander styled)
#   • Tracking now has a sub-menu: "📈 Performance Summary"
#   • Primary CTA button glow is the DEFAULT state (was hover-only)
#   • ⚙️ Global block uses the same filled-header treatment
#   • Collapsed-section state persists in st.session_state
# Drop this file in to replace your existing app.py.
# Requires (NEW): scanners/performance_summary.py — see CHANGES.md.
# ─────────────────────────────────────────────────────────────────

import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from config import *

# ── Maintenance check BEFORE set_page_config ──────────────────
# is_maintenance_mode() uses only Python stdlib — safe before any st.* call.
# We check here so we can pass initial_sidebar_state="hidden" to set_page_config,
# which removes the sidebar at the Streamlit framework level (no CSS battle).
from scanners.page_manager import is_maintenance_mode as _early_maint_fn
_early_in_maint = (
    _early_maint_fn()
    and not st.session_state.get("_is_admin", False)
)

# ── Page Config ────────────────────────────────────────────────
st.set_page_config(
    page_title="Golden Scanner",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Sidebar CSS — force-visible on normal pages, hidden during maintenance ──
# Plain strings (not f-strings) so CSS braces pass through unchanged when
# interpolated into the outer f-string below.
if _early_in_maint:
    # During maintenance: hide sidebar and its toggle completely.
    # No force-visible rules are emitted, so this CSS wins unopposed.
    _sidebar_force_css = (
        "section[data-testid=\"stSidebar\"],\n"
        "[data-testid=\"stSidebarCollapsedControl\"],\n"
        "button[data-testid=\"stSidebarCollapseButton\"],\n"
        "button[title=\"Open sidebar\"],\n"
        "button[aria-label=\"Open sidebar\"] {\n"
        "    display: none !important;\n"
        "    visibility: hidden !important;\n"
        "    width: 0 !important;\n"
        "    min-width: 0 !important;\n"
        "}\n"
        "[data-testid=\"stAppViewContainer\"] > .main {\n"
        "    margin-left: 0 !important;\n"
        "    padding-left: 2rem !important;\n"
        "    width: 100% !important;\n"
        "}\n"
    )
else:
    # Normal mode: force sidebar always visible on desktop.
    _sidebar_force_css = (
        "@media (min-width: 769px) {\n"
        "    section[data-testid=\"stSidebar\"] {\n"
        "        transform: translateX(0) !important;\n"
        "        min-width: 320px !important; width: 320px !important;\n"
        "        visibility: visible !important; display: block !important;\n"
        "    }\n"
        "    section[data-testid=\"stSidebar\"] > div:first-child {\n"
        "        transform: translateX(0) !important;\n"
        "        width: 320px !important; min-width: 320px !important;\n"
        "    }\n"
        "    [data-testid=\"stSidebarCollapseButton\"],\n"
        "    [data-testid=\"stSidebarCollapsedControl\"],\n"
        "    button[title=\"Close sidebar\"], button[title=\"Collapse sidebar\"],\n"
        "    button[aria-label=\"Close sidebar\"], button[aria-label=\"Collapse sidebar\"] {\n"
        "        display: none !important;\n"
        "    }\n"
        "}\n"
    )

# ── Global CSS ─────────────────────────────────────────────────
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,600;0,700;1,400&family=DM+Mono:wght@300;400;500&family=Inter:wght@300;400;500;600&display=swap');

:root {{
    --gold: {GOLD};
    --gold-dark: {GOLD_DARK};
    --bg-dark: {BG_DARK};
    --bg-card: {BG_CARD};
    --bg-panel: {BG_PANEL};
    --accent-green: {ACCENT_GREEN};
    --accent-red: {ACCENT_RED};
    --accent-blue: {ACCENT_BLUE};
    --text-primary: {TEXT_PRIMARY};
    --text-muted: {TEXT_MUTED};
    --border: {BORDER_COLOR};
}}

html, body, [data-testid="stApp"] {{
    background: {BG_DARK};
    color: {TEXT_PRIMARY};
    font-family: 'Inter', sans-serif;
}}

/* Hide Streamlit branding & auto multipage nav */
#MainMenu, footer {{ visibility: hidden; }}
@media (min-width: 769px) {{ header {{ visibility: hidden; }} }}

.block-container {{
    padding-top: 0.5rem !important;
    padding-bottom: 1rem !important;
}}
[data-testid="stSidebar"] > div:first-child {{ padding-top: 0 !important; }}
[data-testid="stToolbarActions"],
[data-testid="stDecoration"],
button[title="Fork this app"],
button[aria-label="Fork this app"] {{ display: none !important; }}
[data-testid="stSidebarNav"],
[data-testid="stSidebarNavItems"],
[data-testid="stSidebarNavSeparator"],
section[data-testid="stSidebarNav"],
div[data-testid="stSidebarNavItems"] {{ display: none !important; }}
.st-emotion-cache-1rtdyuf,
.st-emotion-cache-eczf2c {{ display: none !important; }}

/* ── Desktop: force sidebar always visible (omitted during maintenance) ── */
{_sidebar_force_css}

/* ── Mobile ── */
@media (max-width: 768px) {{
    header {{ background: {BG_CARD} !important; border-bottom: 1px solid {BORDER_COLOR} !important; }}
    header button, header [data-testid="stBaseButton-headerNoPadding"] {{ color: {GOLD} !important; font-size: 22px !important; }}
    .block-container {{ padding-left: 0.6rem !important; padding-right: 0.6rem !important; padding-top: 1rem !important; max-width: 100vw !important; overflow-x: hidden !important; }}
    section[data-testid="stSidebar"] > div:first-child {{ overflow-y: auto !important; height: 100vh !important; padding-bottom: 40px !important; }}
    .stButton > button {{ min-height: 44px !important; font-size: 14px !important; }}
    .stTabs [data-baseweb="tab-list"] {{ flex-wrap: nowrap !important; overflow-x: auto !important; -webkit-overflow-scrolling: touch !important; }}
    .stTabs [data-baseweb="tab"] {{ white-space: nowrap !important; font-size: 12px !important; padding: 6px 10px !important; flex-shrink: 0 !important; }}
    [data-testid="stMetricValue"] {{ font-size: 20px !important; }}
    div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:first-child,
    div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:last-child {{ display: none !important; }}
    div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:nth-child(2) {{ flex: 1 1 100% !important; width: 100% !important; min-width: 100% !important; }}
    [data-testid="stDataFrame"] {{ max-width: 100% !important; overflow-x: auto !important; }}
    .gs-logo {{ font-size: 20px !important; }}
}}

/* Sidebar shell */
[data-testid="stSidebar"] {{
    background: {BG_CARD} !important;
    border-right: 1px solid {BORDER_COLOR};
}}

/* Inputs in sidebar — kept consistent */
[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] .stRadio label {{
    color: {TEXT_MUTED} !important;
    font-size: 11px !important;
    text-transform: uppercase;
    letter-spacing: 1px;
}}
.stSlider > div, .stSelectbox > div > div {{ background: {BG_PANEL} !important; }}

/* ============================================================
   PRIMARY CTA BUTTONS (main content area)
   Glow is the DEFAULT state. Hover lifts and brightens.
   ============================================================ */
.stButton > button {{
    background: linear-gradient(135deg, {GOLD_DARK}, {GOLD}) !important;
    color: {BG_DARK} !important;
    border: none !important;
    font-weight: 600 !important;
    font-family: 'Inter', sans-serif !important;
    letter-spacing: 0.5px;
    box-shadow: 0 4px 20px rgba(245,200,66,0.27);
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}}
.stButton > button:hover {{
    transform: translateY(-1px);
    box-shadow: 0 6px 26px rgba(245,200,66,0.45);
}}

/* Download button — kept ghost */
.stDownloadButton > button {{
    background: transparent !important;
    color: {GOLD} !important;
    border: 1px solid {GOLD}55 !important;
    font-size: 12px !important;
    box-shadow: none !important;
}}
.stDownloadButton > button:hover {{ transform: none !important; box-shadow: none !important; background: rgba(245,200,66,0.06) !important; }}

/* ============================================================
   SIDEBAR NAV BUTTONS — override the primary CTA styling
   These are the per-item links inside each collapsible group.
   Compact, list-style (not button-style) spacing.
   ============================================================ */
/* Streamlit wraps every widget (incl. each <span class="gs-active-marker"/>
   markdown call) in its own element-container with 1rem margin. That's
   what creates the big gaps between sibling nav items. Zero it out for
   EVERY widget type in the sidebar so markers become truly invisible. */
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"],
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {{
    gap: 0 !important;
}}
section[data-testid="stSidebar"] .element-container,
section[data-testid="stSidebar"] [data-testid="element-container"],
section[data-testid="stSidebar"] [data-testid="stMarkdown"],
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
section[data-testid="stSidebar"] .stMarkdown,
section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] {{
    margin: 0 !important;
    padding: 0 !important;
    line-height: 0 !important;
}}
/* Re-allow line-height inside actual markdown text (descendants of the
   gs-global-row, list explanation, etc.) so headings/text aren't collapsed. */
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] > * {{
    line-height: 1.4 !important;
}}
section[data-testid="stSidebar"] .stButton,
section[data-testid="stSidebar"] [data-testid="stButton"] {{
    margin: 0 !important;
    padding: 0 !important;
}}

[data-testid="stSidebar"] .stButton > button {{
    background: transparent !important;
    color: {TEXT_PRIMARY} !important;
    border: none !important;
    border-left: 2px solid transparent !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    padding: 3px 6px 3px 14px !important;
    margin: 0 !important;
    font-size: 12.5px !important;
    font-weight: 400 !important;
    letter-spacing: 0 !important;
    text-align: left !important;
    justify-content: flex-start !important;
    align-items: center !important;
    min-height: 24px !important;
    height: auto !important;
    line-height: 1.4 !important;
    transition: background 0.12s ease, color 0.12s ease !important;
}}
/* Force left-alignment through Streamlit's nested div + p */
[data-testid="stSidebar"] .stButton > button > div,
[data-testid="stSidebar"] .stButton > button > div > div {{
    text-align: left !important;
    width: 100% !important;
    display: flex !important;
    justify-content: flex-start !important;
}}
[data-testid="stSidebar"] .stButton > button p {{
    text-align: left !important;
    margin: 0 !important;
    width: 100%;
}}
[data-testid="stSidebar"] .stButton > button:hover {{
    background: transparent !important;
    color: {GOLD} !important;
    border-left-color: rgba(245,200,66,0.4) !important;
    transform: none !important;
    box-shadow: none !important;
}}
/* Sub-item — quieter color, smaller font, indented via padding + gold rail
   directly on the button (no st.columns layout, which was adding gap). */
section[data-testid="stSidebar"] .element-container:has(.gs-sub-marker) + .element-container .stButton > button,
section[data-testid="stSidebar"] [data-testid="element-container"]:has(.gs-sub-marker) + [data-testid="element-container"] .stButton > button {{
    color: #C9CCD3 !important;
    font-size: 11.5px !important;
    min-height: 22px !important;
    height: auto !important;
    padding: 3px 8px 3px 22px !important;
    margin-left: 30px !important;
    width: calc(100% - 30px) !important;
    border-left: 1px solid rgba(245,200,66,0.25) !important;
}}

/* Active nav item — marked by <span class="gs-active-marker"/>. Comes AFTER
   sub-item rule so that when BOTH apply (an active sub-item like Summary),
   active wins on color and border without touching the indent properties. */
section[data-testid="stSidebar"] .element-container:has(.gs-active-marker) + .element-container .stButton > button,
section[data-testid="stSidebar"] [data-testid="element-container"]:has(.gs-active-marker) + [data-testid="element-container"] .stButton > button {{
    background: transparent !important;
    color: {GOLD} !important;
    border-left-color: {GOLD} !important;
    border-left-width: 2px !important;
    font-weight: 600 !important;
}}

/* Force ALL marker-only element-containers to collapse to zero height.
   The empty marker spans (gs-active, gs-sub, gs-group, gs-admin) live inside
   their own stMarkdownContainer; without this rule each one would add ~6-10px
   of vertical space between adjacent nav items even with line-height:0. */
section[data-testid="stSidebar"] .element-container:has(.gs-active-marker),
section[data-testid="stSidebar"] .element-container:has(.gs-sub-marker),
section[data-testid="stSidebar"] .element-container:has(.gs-group-marker),
section[data-testid="stSidebar"] .element-container:has(.gs-admin-marker),
section[data-testid="stSidebar"] [data-testid="element-container"]:has(.gs-active-marker),
section[data-testid="stSidebar"] [data-testid="element-container"]:has(.gs-sub-marker),
section[data-testid="stSidebar"] [data-testid="element-container"]:has(.gs-group-marker),
section[data-testid="stSidebar"] [data-testid="element-container"]:has(.gs-admin-marker) {{
    height: 0 !important;
    min-height: 0 !important;
    max-height: 0 !important;
    overflow: hidden !important;
    margin: 0 !important;
    padding: 0 !important;
}}

/* Parent-with-children row — REMOVED. Chevrons on both sides of the label
   (rendered in Python) do all the "expands" signalling now. Hover still
   tints the row gold via the base sidebar button hover rule. */

/* Logo overlay button — REMOVED by user request. The legacy rules below
   are kept commented out for easy restore.
section[data-testid="stSidebar"] .element-container:has(.gs-logo-marker) + .element-container .stButton {{ ... }}
*/
/* Legacy class — harmless now that columns layout is gone. */
.gs-sub-rail-line {{
    border-left: 1px solid rgba(245,200,66,0.25);
    height: 22px;
    margin-left: 8px;
}}

/* ============================================================
   GOLD GRADIENT GROUP HEADERS — accordion-style.
   Headers are now styled st.button widgets (not st.expander) so we
   can enforce one-open-at-a-time. The `.gs-group-marker` is rendered
   just before the button via st.markdown.
   ============================================================ */
section[data-testid="stSidebar"] .element-container:has(.gs-group-marker) + .element-container .stButton > button,
section[data-testid="stSidebar"] [data-testid="element-container"]:has(.gs-group-marker) + [data-testid="element-container"] .stButton > button {{
    background: linear-gradient(90deg, rgba(245,200,66,0.16), rgba(245,200,66,0.04)) !important;
    border: 1px solid rgba(245,200,66,0.22) !important;
    border-left: 1px solid rgba(245,200,66,0.22) !important;
    border-radius: 6px !important;
    color: {GOLD} !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 11px !important;
    font-weight: 700 !important;
    letter-spacing: 1.4px !important;
    text-transform: uppercase !important;
    padding: 7px 12px !important;
    min-height: 34px !important;
    height: 34px !important;
    margin-top: 10px !important;
    box-shadow: none !important;
    transition: background 0.18s ease, border-color 0.18s ease !important;
}}
section[data-testid="stSidebar"] .element-container:has(.gs-group-marker) + .element-container .stButton > button:hover,
section[data-testid="stSidebar"] [data-testid="element-container"]:has(.gs-group-marker) + [data-testid="element-container"] .stButton > button:hover {{
    background: linear-gradient(90deg, rgba(245,200,66,0.28), rgba(245,200,66,0.10)) !important;
    border-color: rgba(245,200,66,0.45) !important;
    color: {GOLD} !important;
    border-left-color: rgba(245,200,66,0.45) !important;
}}
/* Admin group — dimmed */
section[data-testid="stSidebar"] .element-container:has(.gs-admin-marker) + .element-container .stButton > button,
section[data-testid="stSidebar"] [data-testid="element-container"]:has(.gs-admin-marker) + [data-testid="element-container"] .stButton > button {{
    background: linear-gradient(90deg, rgba(245,200,66,0.08), rgba(245,200,66,0.02)) !important;
    border: 1px solid rgba(245,200,66,0.14) !important;
    border-radius: 6px !important;
    color: {GOLD} !important;
    font-size: 11px !important;
    font-weight: 700 !important;
    letter-spacing: 1.4px !important;
    text-transform: uppercase !important;
    padding: 7px 12px !important;
    min-height: 34px !important;
    height: 34px !important;
    margin-top: 10px !important;
    opacity: 0.55 !important;
}}
section[data-testid="stSidebar"] .element-container:has(.gs-admin-marker) + .element-container .stButton > button:hover {{ opacity: 1 !important; }}

/* ⚙️ Settings block — same filled-header treatment as group headers */
.gs-global-row {{
    margin: 10px 0 0;
    background: linear-gradient(90deg, rgba(245,200,66,0.16), rgba(245,200,66,0.04));
    border: 1px solid rgba(245,200,66,0.22);
    border-radius: 6px;
    padding: 8px 12px;
    color: {GOLD};
    font-family: 'Inter', sans-serif;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.4px;
    text-transform: uppercase;
}}
/* Pre/Post checkbox — indented like a sub-item under Settings */
section[data-testid="stSidebar"] [data-testid="stCheckbox"] {{
    margin-left: 14px !important;
    padding: 4px 0 4px 12px !important;
    border-left: 1px solid rgba(245,200,66,0.18) !important;
}}
section[data-testid="stSidebar"] [data-testid="stCheckbox"] label {{
    color: #C9CCD3 !important;
    font-size: 11.5px !important;
    font-weight: 500 !important;
    text-transform: none !important;
    letter-spacing: 0 !important;
}}
section[data-testid="stSidebar"] [data-testid="stCheckbox"] label span {{
    color: #C9CCD3 !important;
    font-size: 11.5px !important;
}}

/* DataFrames */
[data-testid="stDataFrame"] {{ border: 1px solid {BORDER_COLOR}; border-radius: 8px; overflow: hidden; }}
.dvn-scroller {{ background: {BG_CARD}; }}

/* Metric */
[data-testid="stMetric"] {{ background: {BG_CARD}; border: 1px solid {BORDER_COLOR}; border-radius: 8px; padding: 12px 16px; }}
[data-testid="stMetricLabel"] {{ color: {TEXT_MUTED} !important; font-size: 11px !important; text-transform: uppercase; letter-spacing: 0.8px; }}
[data-testid="stMetricValue"] {{ color: {GOLD} !important; font-family: 'Cormorant Garamond', serif !important; font-size: 28px !important; }}
[data-testid="stMetricDelta"] {{ font-size: 12px !important; }}

/* Tabs — bigger, bolder, 3D bevelled gold-pill design.
   Applies globally so Market Overview, Social Trends, About, Stock Analysis,
   Summary, and every other st.tabs() call share the same treatment. */
.stTabs [data-baseweb="tab-list"] {{
    background: linear-gradient(180deg, {BG_PANEL}, {BG_DARK}) !important;
    border: 1px solid {BORDER_COLOR} !important;
    border-radius: 10px !important;
    padding: 6px !important;
    gap: 4px !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.5),
                inset 0 1px 0 rgba(255,255,255,0.04) !important;
    margin-bottom: 18px !important;
}}
.stTabs [data-baseweb="tab"] {{
    height: 46px !important;
    padding: 0 22px !important;
    font-size: 15px !important;
    font-weight: 700 !important;
    letter-spacing: 0.6px !important;
    color: {TEXT_MUTED} !important;
    background: linear-gradient(180deg, {BG_CARD}, #0c0c12) !important;
    border: 1px solid {BORDER_COLOR} !important;
    border-radius: 8px !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.03),
                0 2px 4px rgba(0,0,0,0.4) !important;
    transition: all 0.18s ease !important;
    position: relative !important;
    top: 0 !important;
}}
.stTabs [data-baseweb="tab"]:hover {{
    color: {GOLD} !important;
    border-color: rgba(245,200,66,0.35) !important;
    top: -1px !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.04),
                0 4px 10px rgba(0,0,0,0.55),
                0 0 12px rgba(245,200,66,0.18) !important;
}}
.stTabs [aria-selected="true"] {{
    color: {BG_DARK} !important;
    background: linear-gradient(180deg, #FFE07A, {GOLD} 45%, {GOLD_DARK}) !important;
    border-color: {GOLD_DARK} !important;
    font-weight: 800 !important;
    top: -2px !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.35),
                inset 0 -2px 0 rgba(0,0,0,0.18),
                0 6px 18px rgba(245,200,66,0.45),
                0 2px 6px rgba(0,0,0,0.55) !important;
}}
/* Kill Streamlit's default underline highlight bar — it fights the bevel. */
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] {{
    display: none !important;
}}

/* Number input */
.stNumberInput input, .stTextInput input {{
    background: {BG_PANEL} !important;
    color: {TEXT_PRIMARY} !important;
    border: 1px solid {BORDER_COLOR} !important;
}}

/* Spinners + alerts */
.stSpinner {{ color: {GOLD} !important; }}
.stAlert {{ background: {BG_PANEL} !important; border: 1px solid {BORDER_COLOR} !important; }}
hr {{ border-color: {BORDER_COLOR}; }}

/* Scrollbar */
::-webkit-scrollbar {{ width: 6px; height: 6px; }}
::-webkit-scrollbar-track {{ background: {BG_DARK}; }}
::-webkit-scrollbar-thumb {{ background: {BORDER_COLOR}; border-radius: 3px; }}
::-webkit-scrollbar-thumb:hover {{ background: {GOLD_DARK}; }}

/* VIS-3: Sticky table headers — works for all HTML tables rendered via st.markdown */
div[data-testid="stMarkdownContainer"] table thead th {{
    position: sticky !important;
    top: 0 !important;
    z-index: 10 !important;
    background: {BG_PANEL} !important;
    box-shadow: 0 2px 4px rgba(0,0,0,0.4) !important;
}}
/* Scrollable wrapper so sticky actually activates */
div[data-testid="stMarkdownContainer"] div[style*="overflow-x:auto"] {{
    max-height: 520px;
    overflow-y: auto !important;
}}

/* Section dividers */
.section-divider {{
    height: 1px;
    background: linear-gradient(90deg, transparent, {GOLD}44, transparent);
    margin: 20px 0;
}}

/* ── Expander headers — light-blue tinted background ── */
[data-testid="stExpander"] summary {{
    background: rgba(59, 130, 246, 0.10) !important;
    border: 1px solid rgba(59, 130, 246, 0.22) !important;
    border-radius: 6px !important;
    padding: 8px 14px !important;
}}
[data-testid="stExpander"] summary:hover {{
    background: rgba(59, 130, 246, 0.18) !important;
    border-color: rgba(59, 130, 246, 0.40) !important;
}}
[data-testid="stExpander"] summary p,
[data-testid="stExpander"] summary span {{
    color: {TEXT_PRIMARY} !important;
}}
</style>
""", unsafe_allow_html=True)

# ── Session state init ─────────────────────────────────────────
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "_is_admin" not in st.session_state:
    st.session_state["_is_admin"] = False

# ── Password Gate ──────────────────────────────────────────────
if not st.session_state["authenticated"]:
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown(
            f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};'
            f'border-top:3px solid {GOLD};border-radius:12px;padding:40px 32px;'
            f'text-align:center;margin-top:80px">'
            f'<div style="font-family:\'Cormorant Garamond\',serif;font-size:36px;color:{GOLD};'
            f'font-weight:700;letter-spacing:3px;margin-bottom:6px">✦ GOLDEN SCANNER</div>'
            f'<div style="color:{TEXT_MUTED};font-size:11px;letter-spacing:3px;'
            f'text-transform:uppercase;margin-bottom:32px">Precision Trading Intelligence</div>'
            f'<div style="color:{TEXT_MUTED};font-size:13px;margin-bottom:16px">'
            f'Enter your access password to continue</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        pwd = st.text_input(
            "Password", type="password",
            placeholder="Enter password…", label_visibility="collapsed",
        )
        if st.button("🔓  Enter Golden Scanner", use_container_width=True):
            try:
                app_pwd   = st.secrets["APP_PASSWORD"]
                admin_pwd = st.secrets["ADMIN_PASSWORD"]
            except Exception:
                app_pwd   = os.environ.get("APP_PASSWORD",   "password!")
                admin_pwd = os.environ.get("ADMIN_PASSWORD", "admin!")
            if pwd == admin_pwd:
                # Admin: sees all pages + Admin menu fully open
                st.session_state["authenticated"] = True
                st.session_state["_is_admin"]     = True
                st.rerun()
            elif pwd == app_pwd:
                # Regular user: sees only enabled pages
                st.session_state["authenticated"] = True
                st.session_state["_is_admin"]     = False
                st.rerun()
            else:
                st.error("Incorrect password. Please try again.")
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:10px;text-align:center;margin-top:16px">'
            f'⚠️ Not financial advice · Educational use only</div>',
            unsafe_allow_html=True,
        )
    st.stop()


# ── Deep-link query param handler ─────────────────────────────
# Usage:  https://your-app.streamlit.app/?goto=gold_standard
# Supported values → nav destinations:
#   gold_standard   → Stock Analysis  (auto-selects Gold Standard tab)
#   stock_analysis  → Stock Analysis  (Deep Analysis tab)
#   tracking        → Tracking
#   watchlist       → WatchList
#   golden_scan     → Golden Scan
#   (any nav key)   → routed directly if it matches a known page key

_GOTO_MAP = {
    "gold_standard":  ("🔬  Stock Analysis",   "Stocks", True),
    "stock_analysis": ("🔬  Stock Analysis",   "Stocks", False),
    "tracking":       ("📌  Tracking",          "Dashboard", False),
    "watchlist":      ("👁  WatchList",         "Dashboard", False),
    "golden_scan":    ("🔀  Golden Scan",       "Stocks", False),
    "csp":            ("💰  CSP — Stocks",      "Options", False),
    "leaps":          ("🧨  LEAPS — Stocks",    "Options", False),
}
try:
    _goto_param = st.query_params.get("goto", "").strip().lower()
    if _goto_param and _goto_param in _GOTO_MAP:
        _nav_dest, _nav_group, _open_gs = _GOTO_MAP[_goto_param]
        st.session_state["nav_page"]          = _nav_dest
        st.session_state["_nav_open_group"]   = _nav_group
        if _open_gs:
            st.session_state["_open_gold_standard"] = True
        st.query_params.clear()          # remove param from URL after consuming it
        st.rerun()
except Exception:
    pass   # st.query_params not available on older Streamlit — silently skip

# ── Tracker notifications ─────────────────────────────────────
_pending = st.session_state.get("_tracker_notes", [])
if _pending:
    for _icon, _msg in _pending:
        st.toast(_msg, icon=_icon)
    st.session_state["_tracker_notes"] = []


# ── Nav state helpers ──────────────────────────────────────────
# Page keys mirror what the existing router dispatches on.
NAV_GROUPS = [
    {
        "sep": "Dashboard", "icon": "🏠", "expanded": True,
        "items": [
            {"key": "🏠  Market Overview"},
            {"key": "📱  Social Trends"},
            {"key": "🔄  Auto Scan & Track"},
            {"key": "👁  WatchList"},
        ],
    },
    {
        "sep": "Stocks", "icon": "📊", "expanded": False,
        "items": [
            {"key": "🔀  Golden Scan"},
            {"key": "🔬  Stock Analysis"},
            {"key": "📰  Headlines & Catalysts"},
            {"key": "⚡  3× Leveraged ETFs"},
        ],
    },
    {
        "sep": "Options", "icon": "🎯", "expanded": False,
        "items": [
            {"key": "💰  CSP — Stocks"},
            {"key": "💰  CSP — ETFs"},
            {"key": "🧨  LEAPS — Stocks"},
            {"key": "🧨  LEAPS — ETFs"},
            {"key": "⚡  3× ETF Options"},
        ],
    },
    {
        "sep": "Dividend", "icon": "💵", "expanded": False,
        "hidden_for_users": True,          # completely hidden from non-admin users
        "items": [
            {"key": "💵  Upcoming Dividends"},
            {"key": "📅  Dividend + CC Capture"},
        ],
    },
    {
        "sep": "Info", "icon": "ℹ️", "expanded": False,
        "items": [
            {"key": "ℹ️  About & Guide"},
        ],
    },
    {
        "sep": "Admin", "icon": "🔐", "expanded": False, "dim": True,
        "items": [
            {"key": "⚙️  Admin Panel", "label": "Admin Panel", "icon": "⚙️"},
            {"key": "🔧  Tech Details", "label": "Tech Details", "icon": "🔧"},
        ],
    },
]

if "nav_page" not in st.session_state:
    st.session_state["nav_page"] = "🏠  Market Overview"

def _go(page_key: str):
    st.session_state["nav_page"] = page_key
    # Open the owning group; close all others (accordion).
    for g in NAV_GROUPS:
        if any(it["key"] == page_key for it in g["items"]):
            st.session_state["_nav_open_group"] = g["sep"]; break
        if any(
            c["key"] == page_key
            for it in g["items"] for c in (it.get("children") or [])
        ):
            st.session_state["_nav_open_group"] = g["sep"]; break
    st.rerun()

def _go_home():
    _go("🏠  Market Overview")

# Initialize accordion state: open the group that owns the active page
def _owning_group_for(page_key: str) -> str:
    for g in NAV_GROUPS:
        if any(it["key"] == page_key for it in g["items"]):
            return g["sep"]
        if any(
            c["key"] == page_key
            for it in g["items"] for c in (it.get("children") or [])
        ):
            return g["sep"]
    return "Dashboard"

if "_nav_open_group" not in st.session_state:
    st.session_state["_nav_open_group"] = _owning_group_for(
        st.session_state.get("nav_page", "🏠  Market Overview")
    )

# ── Page visibility helper (needed by sidebar nav labels) ──────
from scanners.page_manager import is_page_enabled as _page_enabled


def _group_all_disabled(grp: dict) -> bool:
    """
    True when every navigable page in this group is disabled for the current user.
    Uses is_page_enabled() — the exact same function the individual nav items use
    to decide whether to show 🔒 — so the two are guaranteed to agree.
    Admins always see everything → always returns False.
    """
    if st.session_state.get("_is_admin", False):
        return False
    items = grp.get("items", [])
    if not items:
        return False
    # Re-use is_page_enabled: if an item shows 🔒, this must agree.
    from scanners.page_manager import is_page_enabled as _ipe
    for it in items:
        if _ipe(it["key"]):          # page is still enabled → group NOT fully locked
            return False
        for child in it.get("children", []):
            if _ipe(child["key"]):
                return False
    return True

# ── Sidebar ────────────────────────────────────────────────────
# Maintenance check BEFORE the sidebar renders — if active the sidebar is
# simply never added to the DOM (no CSS battles with the force-visible rules).
from scanners.page_manager import is_maintenance_mode as _maint_check_fn
_in_maintenance = (
    not st.session_state.get("_is_admin", False)
    and st.session_state.get("nav_page", "🏠  Market Overview") != "⚙️  Admin Panel"
    and _maint_check_fn()
)

if not _in_maintenance:
    with st.sidebar:
        # Logo block — display only, NOT clickable. (Removed by user request.)
        st.markdown(f"""
        <div style="display:flex;align-items:center;gap:10px;padding:16px 8px 6px 8px;border-bottom:1px solid {BORDER_COLOR};margin-bottom:6px">
            <svg width="36" height="36" viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg" style="flex-shrink:0">
                <circle cx="18" cy="18" r="16" stroke="{GOLD}" stroke-width="1.5" fill="none" opacity="0.35"/>
                <circle cx="18" cy="18" r="10" stroke="{GOLD}" stroke-width="1.5" fill="none" opacity="0.6"/>
                <circle cx="18" cy="18" r="3" fill="{GOLD}" opacity="0.9"/>
                <line x1="18" y1="2" x2="18" y2="8" stroke="{GOLD}" stroke-width="1.5" opacity="0.7"/>
                <line x1="18" y1="28" x2="18" y2="34" stroke="{GOLD}" stroke-width="1.5" opacity="0.7"/>
                <line x1="2" y1="18" x2="8" y2="18" stroke="{GOLD}" stroke-width="1.5" opacity="0.7"/>
                <line x1="28" y1="18" x2="34" y2="18" stroke="{GOLD}" stroke-width="1.5" opacity="0.7"/>
                <line x1="13" y1="18" x2="23" y2="18" stroke="{GOLD}" stroke-width="1" opacity="0.4"/>
                <line x1="18" y1="13" x2="18" y2="23" stroke="{GOLD}" stroke-width="1" opacity="0.4"/>
            </svg>
            <div>
                <div style="font-family:'Cormorant Garamond',serif;font-size:18px;font-weight:700;color:{GOLD};letter-spacing:2px;line-height:1.1">GOLDEN SCANNER</div>
                <div style="color:{TEXT_MUTED};font-size:9px;letter-spacing:2.5px;text-transform:uppercase;margin-top:2px">Precision Trading Intelligence</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── Grouped, collapsible nav ──────────────────────────────
        current_page = st.session_state.get("nav_page", "🏠  Market Overview")

        def _render_nav_item(it, indent=False):
            is_active = it["key"] == current_page
            # Combine sub + active markers into ONE span so they share an
            # element-container. If kept separate, sub-marker's adjacent-sibling
            # selector ` + .element-container` points to the active-marker's
            # container instead of the button — losing the indent on active sub-items.
            classes = []
            if indent:
                classes.append("gs-sub-marker")
            if is_active:
                classes.append("gs-active-marker")
            if classes:
                st.markdown(f'<span class="{" ".join(classes)}"></span>', unsafe_allow_html=True)
            # Show 🔒 for regular users when the page is disabled
            _is_user = not st.session_state.get("_is_admin", False)
            lock_tag = " 🔴" if _is_user and not _page_enabled(it["key"]) else ""
            if st.button(it["key"] + lock_tag, key=f"_nav_{it['key']}", use_container_width=True):
                _go(it["key"])

        def _render_item_with_children(it):
            # Single-button design: clicking Tracking ALWAYS navigates to it.
            # Sub-menu visibility is derived from active state.
            is_active = it["key"] == current_page
            child_active = any(c["key"] == current_page for c in it.get("children", []))
            show_subs = is_active or child_active

            if is_active:
                st.markdown('<span class="gs-active-marker"></span>', unsafe_allow_html=True)
            # Show 🔒 for regular users when the page is disabled
            _is_user = not st.session_state.get("_is_admin", False)
            lock_tag = " 🔴" if _is_user and not _page_enabled(it["key"]) else ""
            # Chevrons on BOTH sides telegraph "this expands" without needing a rail.
            # Collapsed: ›  📌  Tracking  ‹    Expanded: ⌄  📌  Tracking  ⌄
            if show_subs:
                label = "⌄  " + it["key"] + lock_tag + "  ⌄"
            else:
                label = "›  " + it["key"] + lock_tag + "  ‹"
            if st.button(label, key=f"_nav_{it['key']}", use_container_width=True):
                _go(it["key"])

            if show_subs:
                for child in it.get("children", []):
                    _render_nav_item(child, indent=True)

        for grp in NAV_GROUPS:
            # Groups flagged hidden_for_users are invisible to non-admins.
            if grp.get("hidden_for_users") and not st.session_state.get("_is_admin", False):
                continue

            is_open = st.session_state.get("_nav_open_group") == grp["sep"]
            marker = "gs-admin-marker" if grp.get("dim") else "gs-group-marker"
            # Admin group (dim=True): locked for regular users, always open for admin.
            # All other groups: locked when every page in the group is disabled.
            if grp.get("dim"):
                _locked = not st.session_state.get("_is_admin", False)
            else:
                _locked = _group_all_disabled(grp)

            # If the currently open group just became fully locked, close it.
            if _locked and is_open:
                st.session_state["_nav_open_group"] = None
                is_open = False

            st.markdown(f'<span class="{marker}"></span>', unsafe_allow_html=True)

            if _locked:
                # ── Any locked group (Admin for non-admin users, or Options/Dividend
                #    when all pages are disabled) — identical non-interactive banner.
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:8px;'
                    f'padding:7px 14px;border-radius:6px;margin-top:10px;'
                    f'background:rgba(239,68,68,0.07);'
                    f'border:1px solid rgba(239,68,68,0.28);'
                    f'cursor:not-allowed;user-select:none">'
                    f'<span style="font-size:13px">🔒</span>'
                    f'<span style="color:{TEXT_MUTED};font-size:11px;font-weight:600;'
                    f'letter-spacing:1.5px;text-transform:uppercase;opacity:0.6">'
                    f'{grp["icon"]}  {grp["sep"].upper()}</span>'
                    f'<span style="margin-left:auto;color:#EF4444;font-size:9px;'
                    f'font-weight:700;letter-spacing:1px;'
                    f'background:rgba(239,68,68,0.15);padding:2px 7px;'
                    f'border-radius:4px;border:1px solid rgba(239,68,68,0.3)">LOCKED</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            else:
                # ── Normal group: accordion toggle ──
                header_label = f"{grp['icon']}  {grp['sep'].upper()}    {'▾' if is_open else '▸'}"
                if st.button(header_label, key=f"_grp_{grp['sep']}", use_container_width=True):
                    # Strict accordion: open this group, close all others.
                    # If clicking the already-open group, close it.
                    st.session_state["_nav_open_group"] = None if is_open else grp["sep"]
                    st.rerun()

                # Body — only render when this is the open group
                if is_open:
                    if not grp["items"]:
                        st.markdown(
                            f'<div style="padding:6px 12px;color:{TEXT_MUTED};font-size:11px;font-style:italic">No items yet</div>',
                            unsafe_allow_html=True,
                        )
                    for it in grp["items"]:
                        if it.get("children"):
                            _render_item_with_children(it)
                        else:
                            _render_nav_item(it)

        # ── ⚙️ Settings block — same gold-header treatment ───────
        st.markdown('<div class="gs-global-row">⚙️ Settings</div>', unsafe_allow_html=True)
        st.session_state["_show_prepost"] = st.checkbox(
            "Pre/Post Market Price",
            value=st.session_state.get("_show_prepost", False),
            help="Appends current extended-hours price to every scanner result table. Adds ~1s per ticker.",
        )

        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:10px;text-align:center;margin-top:14px;line-height:1.6">'
            f'Data via YFinance · Refreshes every 5 min<br>⚠️ Not financial advice</div>',
            unsafe_allow_html=True,
        )

# Expose `page` for the router below (legacy variable name preserved)
page = st.session_state.get("nav_page", "🏠  Market Overview")

# ── Main breadcrumb bar (shown on non-home pages) ─────────────
if page and page != "🏠  Market Overview":
    _c1, _c2 = st.columns([1, 11])
    with _c1:
        if st.button("🏠 Home", key="_main_home", use_container_width=True):
            _go_home()
    st.markdown(f'<div style="height:2px;background:linear-gradient(90deg,{GOLD}44,transparent);margin-bottom:8px"></div>', unsafe_allow_html=True)

# ── Page visibility guard ──────────────────────────────────────
# (_page_enabled already imported above, before the sidebar)

# Pages exempt from the visibility check (always rendered)
_ROUTER_ALWAYS_ON = {"🏠  Market Overview", "⚙️  Admin Panel"}


# ── Maintenance mode gate ──────────────────────────────────────
# _in_maintenance was evaluated BEFORE the sidebar rendered so the sidebar
# was never added to the DOM — no CSS battle needed.
# Admin Panel is always reachable so the admin can turn maintenance off.
if _in_maintenance:
    # Message is HARDCODED — never read from any storage (avoids "True" corruption).
    _MAINT_DISPLAY_MSG = "Cleaning Lenses! 🔭  Be right back."
    st.markdown(
        f'<div style="display:flex;align-items:center;justify-content:center;'
        f'min-height:70vh">'
        f'<div style="background:{BG_CARD};border:1px solid #EF444455;'
        f'border-top:4px solid #F59E0B;border-radius:14px;'
        f'padding:60px 48px;text-align:center;max-width:480px">'
        f'<div style="font-size:64px;margin-bottom:20px">🔭</div>'
        f'<div style="font-family:\'Cormorant Garamond\',serif;font-size:32px;'
        f'color:#F59E0B;font-weight:700;letter-spacing:2px;margin-bottom:16px">'
        f'Under Maintenance</div>'
        f'<div style="color:{TEXT_PRIMARY};font-size:16px;line-height:1.8;'
        f'margin-bottom:28px">'
        f'{_MAINT_DISPLAY_MSG}</div>'
        f'<div style="display:inline-flex;align-items:center;gap:8px;'
        f'background:rgba(245,158,11,0.10);border:1px solid rgba(245,158,11,0.30);'
        f'border-radius:20px;padding:8px 20px">'
        f'<span style="font-size:14px">⏱</span>'
        f'<span style="color:#F59E0B;font-size:12px;font-weight:600;letter-spacing:1px">'
        f'CHECK BACK SHORTLY</span>'
        f'</div>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.stop()


def _show_page_disabled(page_label: str) -> None:
    """Friendly 'page unavailable' screen for disabled pages."""
    st.markdown("<br><br>", unsafe_allow_html=True)
    _, _dcol, _ = st.columns([1, 2, 1])
    with _dcol:
        st.markdown(
            f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};'
            f'border-top:3px solid #EF4444;border-radius:12px;'
            f'padding:56px 36px;text-align:center;margin-top:40px">'
            f'<div style="font-size:56px;margin-bottom:18px">🔒</div>'
            f'<div style="font-family:\'Cormorant Garamond\',serif;font-size:30px;'
            f'color:#EF4444;font-weight:700;letter-spacing:1.5px;margin-bottom:12px">'
            f'Page Unavailable</div>'
            f'<div style="color:{TEXT_MUTED};font-size:14px;line-height:2;margin-bottom:28px">'
            f'<strong style="color:{TEXT_PRIMARY}">{page_label}</strong> is currently disabled.<br>'
            f'Please contact the administrator to request access.</div>'
            f'<div style="color:{TEXT_MUTED};font-size:11px;text-transform:uppercase;'
            f'letter-spacing:1.5px;border-top:1px solid {BORDER_COLOR};padding-top:18px">'
            f'📧&nbsp; Contact Admin for Access</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


# ── Page Router ────────────────────────────────────────────────
# Intercept disabled pages BEFORE the routing chain fires.
# Admin users and always-on pages bypass this check entirely.
if page not in _ROUTER_ALWAYS_ON and not _page_enabled(page):
    _label = page.split("  ", 1)[-1] if "  " in page else page
    _show_page_disabled(_label)
elif page == "🏠  Market Overview":
    from scanners.home import render
    render()
elif page == "📱  Social Trends":
    from scanners.social_trends import render
    render()
elif page == "🔄  Auto Scan & Track":
    from scanners.trade_pipeline import render
    render()
# ── Legacy keys (old session state / pre-merge nav keys) ───────
elif page in ("🔄  Trade Pipeline", "📅  Scheduled Scans", "📌  Tracking", "Performance"):
    from scanners.trade_pipeline import render
    render()
elif page == "👁  WatchList":
    from scanners.watchlist_page import render
    render()
elif page == "🔀  Golden Scan":
    from scanners.combined_scanner import render
    render()
elif page == "🔬  Stock Analysis":
    from scanners.deep_analysis import render
    render()
elif page == "📰  Headlines & Catalysts":
    from scanners.headlines_scanner import render
    render()
elif page == "⚡  3× Leveraged ETFs":
    from scanners.etf_3x_scanner import render
    render()
elif page == "⚡  3× ETF Options":
    from scanners.etf_3x_options_scanner import render
    render()
elif page == "💰  CSP — Stocks":
    from scanners.csp_scanner import render
    render(universe_mode="stocks")
elif page == "💰  CSP — ETFs":
    from scanners.csp_scanner import render
    render(universe_mode="etfs")
elif page == "🧨  LEAPS — Stocks":
    from scanners.leaps_scanner import render
    render(universe_mode="stocks")
elif page == "🧨  LEAPS — ETFs":
    from scanners.leaps_scanner import render
    render(universe_mode="etfs")
elif page in ("💵  Upcoming Dividends", "📅  Dividend + CC Capture"):
    # Dividend pages are admin-only (hidden from nav for regular users).
    if not st.session_state.get("_is_admin", False):
        st.session_state["nav_page"] = "🏠  Market Overview"
        st.rerun()
    elif page == "💵  Upcoming Dividends":
        from scanners.dividend_hacker import render
        render()
    else:
        from scanners.dividend_cc_scanner import render
        render()
elif page == "ℹ️  About & Guide":
    from scanners.about import render
    render()
elif page in ("⚙️  Admin Panel", "🔧  Tech Details"):
    # Admin pages are only reachable when logged in as admin (_is_admin=True).
    # If a non-admin somehow has an admin nav_page in session state, bounce home.
    if not st.session_state.get("_is_admin", False):
        st.session_state["nav_page"] = "🏠  Market Overview"
        st.rerun()
    elif page == "⚙️  Admin Panel":
        from scanners.admin_page import render
        render()
    elif page == "🔧  Tech Details":
        from scanners.tech_details import render
        render()
