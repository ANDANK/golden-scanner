# scanners/page_manager.py — Page visibility management
#
# Controls which pages regular users (APP_PASSWORD) can access.
# Admin users (ADMIN_PASSWORD) always see ALL pages regardless of settings.
#
# Storage: data/page_settings.json (local file, persists across sessions).
# Cache:   st.session_state["_page_settings_cache"] — avoids disk reads
#          on every Streamlit rerun within a session.

import os
import json
import streamlit as st

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
)
SETTINGS_FILE = os.path.join(DATA_DIR, "page_settings.json")

# ── Canonical page registry ────────────────────────────────────
# Order matches sidebar NAV_GROUPS in app.py.
# 'required': True  → toggle is always ON and cannot be disabled.
# 'parent'         → key of parent page (marks this as a sub-page).
ALL_PAGES = [
    # ── Dashboard ──────────────────────────────────────────────
    {"group": "Dashboard", "key": "🏠  Market Overview",
     "label": "Market Overview",        "required": True},
    {"group": "Dashboard", "key": "📱  Social Trends",
     "label": "Social Trends"},
    {"group": "Dashboard", "key": "📅  Scheduled Scans",
     "label": "Scheduled Scans"},
    {"group": "Dashboard", "key": "📌  Tracking",
     "label": "Tracking"},
    {"group": "Dashboard", "key": "Performance",
     "label": "Performance",            "parent": "📌  Tracking"},
    {"group": "Dashboard", "key": "👁  WatchList",
     "label": "WatchList"},
    # ── Stocks ─────────────────────────────────────────────────
    {"group": "Stocks",    "key": "🔀  Golden Scan",
     "label": "Golden Scan"},
    {"group": "Stocks",    "key": "🔬  Stock Analysis",
     "label": "Stock Analysis"},
    {"group": "Stocks",    "key": "📰  Headlines & Catalysts",
     "label": "Headlines & Catalysts"},
    {"group": "Stocks",    "key": "⚡  3× Leveraged ETFs",
     "label": "3× Leveraged ETFs"},
    # ── Options ────────────────────────────────────────────────
    {"group": "Options",   "key": "💰  CSP — Stocks",
     "label": "CSP — Stocks"},
    {"group": "Options",   "key": "💰  CSP — ETFs",
     "label": "CSP — ETFs"},
    {"group": "Options",   "key": "📦  CC — Stocks",
     "label": "CC — Stocks"},
    {"group": "Options",   "key": "📦  CC — ETFs",
     "label": "CC — ETFs"},
    {"group": "Options",   "key": "🧨  LEAPS — Stocks",
     "label": "LEAPS — Stocks"},
    {"group": "Options",   "key": "🧨  LEAPS — ETFs",
     "label": "LEAPS — ETFs"},
    {"group": "Options",   "key": "⚡  3× ETF Options",
     "label": "3× ETF Options"},
    # ── Dividend ───────────────────────────────────────────────
    {"group": "Dividend",  "key": "💵  Upcoming Dividends",
     "label": "Upcoming Dividends"},
    {"group": "Dividend",  "key": "📅  Dividend + CC Capture",
     "label": "Dividend + CC Capture"},
    # ── Info ───────────────────────────────────────────────────
    {"group": "Info",      "key": "ℹ️  About & Guide",
     "label": "About & Guide"},
]

# Pages that are ALWAYS accessible — cannot be disabled by admin
_ALWAYS_ON = {"🏠  Market Overview", "⚙️  Admin Panel"}

# Group display config (icon for UI)
GROUP_META = {
    "Dashboard": {"icon": "🏠"},
    "Stocks":    {"icon": "📊"},
    "Options":   {"icon": "🎯"},
    "Dividend":  {"icon": "💵"},
    "Info":      {"icon": "ℹ️"},
}


# ── Persistence ────────────────────────────────────────────────

def _read_from_disk() -> dict:
    """Read JSON from disk, filling defaults for any page not yet recorded."""
    defaults = {p["key"]: True for p in ALL_PAGES}
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            defaults.update(saved)
        except Exception:
            pass
    # Required pages are always True regardless of what was saved
    for p in ALL_PAGES:
        if p.get("required"):
            defaults[p["key"]] = True
    return defaults


def load_page_settings() -> dict:
    """
    Return {page_key: bool} — True = page is enabled for regular users.
    Uses session-state as an in-session cache to avoid repeated disk reads.
    """
    if "_page_settings_cache" in st.session_state:
        return st.session_state["_page_settings_cache"]
    data = _read_from_disk()
    st.session_state["_page_settings_cache"] = data
    return data


def save_page_settings(settings: dict) -> None:
    """Persist settings to disk and refresh the in-session cache."""
    # Never allow required pages to be disabled
    for p in ALL_PAGES:
        if p.get("required"):
            settings[p["key"]] = True
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
    st.session_state["_page_settings_cache"] = dict(settings)


# ── Runtime check ──────────────────────────────────────────────

def is_page_enabled(page_key: str) -> bool:
    """
    Returns True if the page should be rendered for the current user.

    - Pages in _ALWAYS_ON → always True.
    - Admin session (_is_admin=True in session_state) → always True.
    - Regular user → check saved settings (default: True).
    """
    if page_key in _ALWAYS_ON:
        return True
    if st.session_state.get("_is_admin", False):
        return True
    return load_page_settings().get(page_key, True)
