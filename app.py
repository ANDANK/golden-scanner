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

# ── Page Config ────────────────────────────────────────────────
st.set_page_config(
    page_title="Golden Scanner",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="collapsed",
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

/* ── Desktop: force sidebar always visible ── */
@media (min-width: 769px) {{
    section[data-testid="stSidebar"] {{
        transform: translateX(0) !important;
        min-width: 320px !important; width: 320px !important;
        visibility: visible !important; display: block !important;
    }}
    section[data-testid="stSidebar"] > div:first-child {{
        transform: translateX(0) !important;
        width: 320px !important; min-width: 320px !important;
    }}
    [data-testid="stSidebarCollapseButton"],
    [data-testid="stSidebarCollapsedControl"],
    button[title="Close sidebar"], button[title="Collapse sidebar"],
    button[aria-label="Close sidebar"], button[aria-label="Collapse sidebar"] {{
        display: none !important;
    }}
}}

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
   ============================================================ */
[data-testid="stSidebar"] .stButton > button {{
    background: transparent !important;
    color: {TEXT_PRIMARY} !important;
    border: none !important;
    border-left: 2px solid transparent !important;
    border-radius: 4px !important;
    box-shadow: none !important;
    padding: 6px 12px !important;
    font-size: 12.5px !important;
    font-weight: 400 !important;
    letter-spacing: 0 !important;
    text-align: left !important;
    justify-content: flex-start !important;
    min-height: 32px !important;
    transition: background 0.15s ease, color 0.15s ease !important;
}}
[data-testid="stSidebar"] .stButton > button:hover {{
    background: rgba(245,200,66,0.06) !important;
    color: {TEXT_PRIMARY} !important;
    transform: none !important;
    box-shadow: none !important;
}}
/* Active nav item — marked by an extra invisible <span class="gs-active-marker"/>
   we render right before the button via st.markdown */
.gs-active-marker + div .stButton > button {{
    background: {BG_DARK} !important;
    color: {GOLD} !important;
    border-left: 2px solid {GOLD} !important;
    font-weight: 600 !important;
}}

/* Sub-item rail — indented + gold left border */
.gs-sub-rail {{
    padding-left: 12px;
    margin-left: 14px;
    border-left: 1px solid rgba(245,200,66,0.18);
}}
.gs-sub-rail .stButton > button {{
    font-size: 11.5px !important;
    color: #C9CCD3 !important;
    padding: 5px 10px !important;
    min-height: 28px !important;
}}

/* ============================================================
   GOLD GRADIENT GROUP HEADERS (st.expander)
   Style each expander summary to look like a uniform section.
   ============================================================ */
[data-testid="stSidebar"] [data-testid="stExpander"] {{
    background: transparent !important;
    border: none !important;
    margin: 4px 0 !important;
}}
[data-testid="stSidebar"] [data-testid="stExpander"] details {{
    background: transparent !important;
    border: none !important;
}}
[data-testid="stSidebar"] [data-testid="stExpander"] summary {{
    background: linear-gradient(90deg, rgba(245,200,66,0.16), rgba(245,200,66,0.04)) !important;
    border: 1px solid rgba(245,200,66,0.22) !important;
    border-radius: 6px !important;
    color: {GOLD} !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 11px !important;
    font-weight: 700 !important;
    letter-spacing: 1.4px !important;
    text-transform: uppercase !important;
    padding: 7px 12px !important;
    cursor: pointer !important;
    transition: background 0.18s ease, border-color 0.18s ease !important;
    list-style: none !important;
}}
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {{
    background: linear-gradient(90deg, rgba(245,200,66,0.28), rgba(245,200,66,0.10)) !important;
    border-color: rgba(245,200,66,0.45) !important;
}}
[data-testid="stSidebar"] [data-testid="stExpander"] summary svg {{ fill: {GOLD} !important; }}
/* Admin section — dimmed via a class we add */
[data-testid="stSidebar"] .gs-admin-group + [data-testid="stExpander"] summary {{
    background: linear-gradient(90deg, rgba(245,200,66,0.08), rgba(245,200,66,0.02)) !important;
    border-color: rgba(245,200,66,0.14) !important;
    opacity: 0.6 !important;
}}
[data-testid="stSidebar"] .gs-admin-group + [data-testid="stExpander"] summary:hover {{ opacity: 1 !important; }}

/* ⚙️ Global block — same filled-header treatment as group headers */
.gs-global-row {{
    margin: 6px 0 4px;
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
/* Checkbox inside global row — make it inline + gold */
[data-testid="stSidebar"] .gs-global-host [data-testid="stCheckbox"] label {{
    color: {TEXT_PRIMARY} !important;
    font-size: 11px !important;
    font-weight: 500 !important;
    text-transform: none !important;
    letter-spacing: 0 !important;
}}
[data-testid="stSidebar"] .gs-global-host [data-testid="stCheckbox"] {{ margin-top: -32px; margin-left: 96px; }}

/* DataFrames */
[data-testid="stDataFrame"] {{ border: 1px solid {BORDER_COLOR}; border-radius: 8px; overflow: hidden; }}
.dvn-scroller {{ background: {BG_CARD}; }}

/* Metric */
[data-testid="stMetric"] {{ background: {BG_CARD}; border: 1px solid {BORDER_COLOR}; border-radius: 8px; padding: 12px 16px; }}
[data-testid="stMetricLabel"] {{ color: {TEXT_MUTED} !important; font-size: 11px !important; text-transform: uppercase; letter-spacing: 0.8px; }}
[data-testid="stMetricValue"] {{ color: {GOLD} !important; font-family: 'Cormorant Garamond', serif !important; font-size: 28px !important; }}
[data-testid="stMetricDelta"] {{ font-size: 12px !important; }}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {{ background: {BG_PANEL}; border-radius: 8px; gap: 2px; }}
.stTabs [data-baseweb="tab"] {{ color: {TEXT_MUTED} !important; font-size: 13px; }}
.stTabs [aria-selected="true"] {{ color: {GOLD} !important; background: {BG_CARD} !important; }}

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

/* Section dividers */
.section-divider {{
    height: 1px;
    background: linear-gradient(90deg, transparent, {GOLD}44, transparent);
    margin: 20px 0;
}}
</style>
""", unsafe_allow_html=True)

# ── Password Gate ──────────────────────────────────────────────
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if not st.session_state["authenticated"]:
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown(f"""
        <div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-top:3px solid {GOLD};
                    border-radius:12px;padding:40px 32px;text-align:center;margin-top:80px">
            <div style="font-family:'Cormorant Garamond',serif;font-size:36px;color:{GOLD};font-weight:700;letter-spacing:3px;margin-bottom:6px">✦ GOLDEN SCANNER</div>
            <div style="color:{TEXT_MUTED};font-size:11px;letter-spacing:3px;text-transform:uppercase;margin-bottom:32px">Precision Trading Intelligence</div>
            <div style="color:{TEXT_MUTED};font-size:13px;margin-bottom:16px">Enter your access password to continue</div>
        </div>
        """, unsafe_allow_html=True)
        pwd = st.text_input("Password", type="password", placeholder="Enter password…", label_visibility="collapsed")
        if st.button("🔓  Enter Golden Scanner", use_container_width=True):
            try:
                correct = st.secrets["APP_PASSWORD"]
            except Exception:
                correct = os.environ.get("APP_PASSWORD", "password!")
            if pwd == correct:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Incorrect password. Please try again.")
        st.markdown(f'<div style="color:{TEXT_MUTED};font-size:10px;text-align:center;margin-top:16px">⚠️ Not financial advice · Educational use only</div>', unsafe_allow_html=True)
    st.stop()


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
            {
                "key": "📌  Tracking",
                "children": [
                    {"key": "📈  Performance Summary"},
                ],
            },
            {"key": "👁  WatchList"},
        ],
    },
    {
        "sep": "Stocks", "icon": "📊", "expanded": False,
        "items": [
            {"key": "🔀  Golden Scan"},
            {"key": "🔬  Stock Analysis"},
            {"key": "📰  Headlines & Catalysts"},
            {"key": "⚡📊  3× Leveraged ETFs"},
        ],
    },
    {
        "sep": "Options", "icon": "🎯", "expanded": False,
        "items": [
            {"key": "💰  Cash-Secured Puts"},
            {"key": "📦  Covered Calls"},
            {"key": "🧨  LEAPS"},
            {"key": "⚡📈  3× ETF Options"},
        ],
    },
    {
        "sep": "Dividend", "icon": "💵", "expanded": False,
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
        "items": [],   # No admin tools yet — placeholder section
    },
]

if "nav_page" not in st.session_state:
    st.session_state["nav_page"] = "🏠  Market Overview"

def _go(page_key: str):
    st.session_state["nav_page"] = page_key
    st.rerun()

def _go_home():
    _go("🏠  Market Overview")

# Auto-expand the group containing the currently active page
def _initial_expanded(group):
    if group.get("expanded"):
        return True
    cur = st.session_state.get("nav_page")
    for it in group["items"]:
        if it["key"] == cur:
            return True
        for ch in it.get("children", []) or []:
            if ch["key"] == cur:
                return True
    return False

# ── Sidebar ────────────────────────────────────────────────────
with st.sidebar:
    # Logo block (unchanged from source)
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
        host = st.container()
        with host:
            if indent:
                st.markdown('<div class="gs-sub-rail">', unsafe_allow_html=True)
            # Active-state marker (CSS targets the immediately-following div)
            if is_active:
                st.markdown('<span class="gs-active-marker"></span>', unsafe_allow_html=True)
            label = it["key"]
            btn_key = f"_nav_{label}"
            if st.button(label, key=btn_key, use_container_width=True):
                _go(it["key"])
            if indent:
                st.markdown('</div>', unsafe_allow_html=True)

    def _render_item_with_children(it):
        # Parent button + a separate "▾/▸" toggle for the sub-menu
        sub_open_key = f"_sub_open_{it['key']}"
        if sub_open_key not in st.session_state:
            # auto-open if the active page is one of the children
            st.session_state[sub_open_key] = any(
                c["key"] == current_page for c in it.get("children", [])
            )

        c1, c2 = st.columns([5, 1])
        with c1:
            if it["key"] == current_page:
                st.markdown('<span class="gs-active-marker"></span>', unsafe_allow_html=True)
            if st.button(it["key"], key=f"_nav_{it['key']}", use_container_width=True):
                _go(it["key"])
        with c2:
            chev = "▾" if st.session_state[sub_open_key] else "▸"
            if st.button(chev, key=f"_chev_{it['key']}", use_container_width=True):
                st.session_state[sub_open_key] = not st.session_state[sub_open_key]
                st.rerun()

        if st.session_state[sub_open_key]:
            for child in it.get("children", []):
                _render_nav_item(child, indent=True)

    for grp in NAV_GROUPS:
        if grp.get("dim"):
            st.markdown('<div class="gs-admin-group"></div>', unsafe_allow_html=True)
        count = sum(1 for _ in grp["items"]) + sum(
            len(it.get("children", []) or []) for it in grp["items"]
        )
        header = f"{grp['icon']}  {grp['sep'].upper()}  ·  {count}"
        with st.expander(header, expanded=_initial_expanded(grp)):
            if not grp["items"]:
                st.markdown(
                    f'<div style="padding:6px 12px;color:{TEXT_MUTED};font-size:11px;font-style:italic">No admin tools yet</div>',
                    unsafe_allow_html=True,
                )
            for it in grp["items"]:
                if it.get("children"):
                    _render_item_with_children(it)
                else:
                    _render_nav_item(it)

    # ── ⚙️ Global block — same gold-header treatment ─────────
    st.markdown('<div class="gs-global-host">', unsafe_allow_html=True)
    st.markdown('<div class="gs-global-row">⚙️ Global</div>', unsafe_allow_html=True)
    st.session_state["_show_prepost"] = st.checkbox(
        "Pre/Post Market Price",
        value=st.session_state.get("_show_prepost", False),
        help="Appends current extended-hours price to every scanner result table. Adds ~1s per ticker.",
    )
    st.markdown('</div>', unsafe_allow_html=True)

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
        st.button("🏠 Home", key="_main_home", use_container_width=True, on_click=_go_home)
    st.markdown(f'<div style="height:2px;background:linear-gradient(90deg,{GOLD}44,transparent);margin-bottom:8px"></div>', unsafe_allow_html=True)

# ── Page Router ────────────────────────────────────────────────
if page == "🏠  Market Overview":
    from scanners.home import render
    render()
elif page == "📱  Social Trends":
    from scanners.social_trends import render
    render()
elif page == "📌  Tracking":
    from scanners.tracking_page import render
    render()
elif page == "📈  Performance Summary":
    # NEW route — Performance Summary sub-page under Tracking.
    # Falls back to tracking_page render if the dedicated module isn't present yet.
    try:
        from scanners.performance_summary import render
    except ImportError:
        from scanners.tracking_page import render
        st.info("ℹ️  Add `scanners/performance_summary.py` to customize this view. "
                "Showing the Tracking page as a placeholder.")
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
elif page == "⚡📊  3× Leveraged ETFs":
    from scanners.etf_3x_scanner import render
    render()
elif page == "⚡📈  3× ETF Options":
    from scanners.etf_3x_options_scanner import render
    render()
elif page == "💰  Cash-Secured Puts":
    from scanners.csp_scanner import render
    render()
elif page == "📦  Covered Calls":
    from scanners.cc_scanner import render
    render()
elif page == "🧨  LEAPS":
    from scanners.leaps_scanner import render
    render()
elif page == "💵  Upcoming Dividends":
    from scanners.dividend_hacker import render
    render()
elif page == "📅  Dividend + CC Capture":
    from scanners.dividend_cc_scanner import render
    render()
elif page == "ℹ️  About & Guide":
    from scanners.about import render
    render()
