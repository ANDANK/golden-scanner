# app.py — Golden Scanner Main Entry

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
/* Hide header only on desktop — on mobile the header IS the hamburger/nav bar */
@media (min-width: 769px) {{ header {{ visibility: hidden; }} }}
/* Hide fork / share / deploy toolbar buttons on all screen sizes */
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

/* Radio items: disable pointer on separator rows */
[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(> div > p:empty),
[data-testid="stSidebar"] div[data-testid="stRadio"] [data-baseweb="radio"]:has(+ div > p:empty) {{
    pointer-events: none;
    opacity: 0.45;
}}

/* ── Desktop: force sidebar always visible ── */
@media (min-width: 769px) {{
    section[data-testid="stSidebar"] {{
        transform: translateX(0) !important;
        min-width: 310px !important;
        width: 310px !important;
        visibility: visible !important;
        display: block !important;
    }}
    section[data-testid="stSidebar"] > div:first-child {{
        transform: translateX(0) !important;
        width: 310px !important;
        min-width: 310px !important;
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
    /* Style the visible Streamlit header bar on mobile */
    header {{
        background: {BG_CARD} !important;
        border-bottom: 1px solid {BORDER_COLOR} !important;
    }}
    /* Style the hamburger / sidebar toggle buttons inside the header */
    header button, header [data-testid="stBaseButton-headerNoPadding"] {{
        color: {GOLD} !important;
        font-size: 22px !important;
    }}
    /* Content breathing room below the header */
    .block-container {{
        padding-left: 0.6rem !important;
        padding-right: 0.6rem !important;
        padding-top: 1rem !important;
        max-width: 100vw !important;
        overflow-x: hidden !important;
    }}
    /* Sidebar: full-height scrollable overlay on mobile */
    section[data-testid="stSidebar"] > div:first-child {{
        overflow-y: auto !important;
        height: 100vh !important;
        padding-bottom: 40px !important;
    }}
    /* Bigger tap targets for all buttons */
    .stButton > button {{
        min-height: 48px !important;
        font-size: 15px !important;
    }}
    /* Sidebar radio rows: bigger for finger tap */
    [data-testid="stSidebar"] div[data-testid="stRadio"] label {{
        padding: 8px 4px !important;
        min-height: 40px !important;
    }}
    /* Tabs: scroll horizontally instead of wrapping */
    .stTabs [data-baseweb="tab-list"] {{
        flex-wrap: nowrap !important;
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch !important;
    }}
    .stTabs [data-baseweb="tab"] {{
        white-space: nowrap !important;
        font-size: 12px !important;
        padding: 6px 10px !important;
        flex-shrink: 0 !important;
    }}
    /* Metrics: tighter on small screens */
    [data-testid="stMetricValue"] {{
        font-size: 20px !important;
    }}
    /* Password screen: make form full-width */
    div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:first-child,
    div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:last-child {{
        display: none !important;
    }}
    div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:nth-child(2) {{
        flex: 1 1 100% !important;
        width: 100% !important;
        min-width: 100% !important;
    }}
    /* DataFrames: scroll instead of overflow */
    [data-testid="stDataFrame"] {{
        max-width: 100% !important;
        overflow-x: auto !important;
    }}
    /* Logo: compact on phone */
    .gs-logo {{ font-size: 20px !important; }}
}}

/* Sidebar */
[data-testid="stSidebar"] {{
    background: {BG_CARD} !important;
    border-right: 1px solid {BORDER_COLOR};
}}
[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] .stRadio label {{
    color: {TEXT_MUTED} !important;
    font-size: 11px !important;
    text-transform: uppercase;
    letter-spacing: 1px;
}}

/* Inputs */
.stSlider > div, .stSelectbox > div > div {{
    background: {BG_PANEL} !important;
}}

/* Buttons */
.stButton > button {{
    background: linear-gradient(135deg, {GOLD_DARK}, {GOLD}) !important;
    color: {BG_DARK} !important;
    border: none !important;
    font-weight: 600 !important;
    font-family: 'Inter', sans-serif !important;
    letter-spacing: 0.5px;
    transition: all 0.2s;
}}
.stButton > button:hover {{
    transform: translateY(-1px);
    box-shadow: 0 4px 20px {GOLD}44;
}}

/* Download button */
.stDownloadButton > button {{
    background: transparent !important;
    color: {GOLD} !important;
    border: 1px solid {GOLD}55 !important;
    font-size: 12px !important;
}}

/* DataFrames */
[data-testid="stDataFrame"] {{
    border: 1px solid {BORDER_COLOR};
    border-radius: 8px;
    overflow: hidden;
}}
.dvn-scroller {{
    background: {BG_CARD};
}}

/* Metric */
[data-testid="stMetric"] {{
    background: {BG_CARD};
    border: 1px solid {BORDER_COLOR};
    border-radius: 8px;
    padding: 12px 16px;
}}
[data-testid="stMetricLabel"] {{ color: {TEXT_MUTED} !important; font-size: 11px !important; text-transform: uppercase; letter-spacing: 0.8px; }}
[data-testid="stMetricValue"] {{ color: {GOLD} !important; font-family: 'Cormorant Garamond', serif !important; font-size: 28px !important; }}
[data-testid="stMetricDelta"] {{ font-size: 12px !important; }}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {{
    background: {BG_PANEL};
    border-radius: 8px;
    gap: 2px;
}}
.stTabs [data-baseweb="tab"] {{
    color: {TEXT_MUTED} !important;
    font-size: 13px;
}}
.stTabs [aria-selected="true"] {{
    color: {GOLD} !important;
    background: {BG_CARD} !important;
}}

/* Expander */
.streamlit-expanderHeader {{
    background: {BG_PANEL} !important;
    color: {TEXT_PRIMARY} !important;
    border: 1px solid {BORDER_COLOR} !important;
    border-radius: 6px !important;
}}

/* Number input */
.stNumberInput input, .stTextInput input {{
    background: {BG_PANEL} !important;
    color: {TEXT_PRIMARY} !important;
    border: 1px solid {BORDER_COLOR} !important;
}}

/* Spinners */
.stSpinner {{ color: {GOLD} !important; }}

/* Alerts */
.stAlert {{
    background: {BG_PANEL} !important;
    border: 1px solid {BORDER_COLOR} !important;
}}

/* Horizontal rule */
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

/* Tiny sidebar home button */
[data-testid="stSidebar"] [data-testid="stButton"]:has(button[title="Market Overview"]) button,
[data-testid="stSidebar"] [data-testid="stButton"]:has(button[aria-label="Market Overview"]) button {{
    background: transparent !important;
    border: 1px solid {BORDER_COLOR} !important;
    color: {GOLD} !important;
    font-size: 18px !important;
    padding: 4px 0 !important;
    min-height: 36px !important;
    width: 100% !important;
    border-radius: 6px !important;
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
            # Read from Streamlit secrets (cloud) or fall back to env / hardcoded
            try:
                correct = st.secrets["APP_PASSWORD"]
            except Exception:
                import os
                correct = os.environ.get("APP_PASSWORD", "password!")
            if pwd == correct:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Incorrect password. Please try again.")
        st.markdown(f'<div style="color:{TEXT_MUTED};font-size:10px;text-align:center;margin-top:16px">⚠️ Not financial advice · Educational use only</div>', unsafe_allow_html=True)
    st.stop()


# ── Tracker notifications (on_click callbacks store here; shown every rerun) ──
_pending = st.session_state.get("_tracker_notes", [])
if _pending:
    for _icon, _msg in _pending:
        st.toast(_msg, icon=_icon)
    st.session_state["_tracker_notes"] = []

# ── Pre-render nav fixes (MUST be before any widget with key="nav_page") ──
# on_click callback used by all Home buttons — fires before widget renders
def _go_home():
    st.session_state["nav_page"] = "🏠  Market Overview"

# If a separator row somehow got selected, reset it now before radio renders
_cur_nav = st.session_state.get("nav_page", "🏠  Market Overview")
if _cur_nav and "──" in _cur_nav:
    st.session_state["nav_page"] = "🏠  Market Overview"

# ── Sidebar Navigation ─────────────────────────────────────────
with st.sidebar:
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

    _hcol1, _hcol2 = st.columns([1, 4])
    with _hcol1:
        st.button("🏠", key="_sidebar_home", help="Market Overview", use_container_width=True, on_click=_go_home)

    st.markdown(f'<div style="color:{TEXT_MUTED};font-size:10px;text-transform:uppercase;letter-spacing:1px;margin:4px 0 6px">Navigate</div>', unsafe_allow_html=True)

    page = st.radio(
        "Navigation",
        key="nav_page",
        options=[
            "🏠  Market Overview",
            "📱  Social Trends",
            "── PORTFOLIO ──",
            "📌  Tracking",
            "👁  WatchList",
            "── STOCKS ──",
            "🔀  Golden Scan",
            "🔬  Stock Analysis",
            "📰  Headlines & Catalysts",
            "── 3X ──",
            "⚡📊  3× Leveraged ETFs",
            "⚡📈  3× ETF Options",
            "── OPTIONS ──",
            "💰  Cash-Secured Puts",
            "📦  Covered Calls",
            "🧨  LEAPS",
            "📈  ETF Options",
            "── DIVIDEND ──",
            "💵  Upcoming Dividends",
            "📅  Dividend + CC Capture",
            "── INFO ──",
            "ℹ️  About & Guide",
        ],
        label_visibility="collapsed",
    )

    st.markdown("---")
    st.markdown(
        f'<div style="color:{GOLD};font-size:10px;font-weight:600;'
        f'text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">⚙️ Global</div>',
        unsafe_allow_html=True,
    )
    st.session_state["_show_prepost"] = st.checkbox(
        "Show Pre/Post Market Price",
        value=st.session_state.get("_show_prepost", False),
        help="Appends current extended-hours price to every scanner result table. Adds ~1s per ticker.",
    )
    st.markdown("---")
    st.markdown(f'<div style="color:{TEXT_MUTED};font-size:10px;text-align:center">Data via YFinance · Refreshes every 5 min<br>⚠️ Not financial advice</div>', unsafe_allow_html=True)


# ── Home button in main content (uses on_click — safe after radio renders) ─
if page and page != "🏠  Market Overview" and "──" not in page:
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
elif page == "📈  ETF Options":
    from scanners.etf_options_scanner import render
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
