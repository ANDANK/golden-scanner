# scanners/page_manager.py — Page visibility management
#
# Controls which pages regular users (APP_PASSWORD) can access.
# Admin users (ADMIN_PASSWORD) always see ALL pages regardless of settings.
#
# Storage priority:
#   1. Google Sheets tab "PageSettings" (persistent across Streamlit Cloud restarts)
#   2. data/page_settings.json (local fallback — ephemeral on Streamlit Cloud)
# Cache:
#   st.session_state["_page_settings_cache"] — one disk/sheet read per session.

import os
import json
import streamlit as st

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
)
SETTINGS_FILE  = os.path.join(DATA_DIR, "page_settings.json")
_MAINT_FILE    = os.path.join(DATA_DIR, "maintenance.json")
_GS_TAB = "PageSettings"

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
    # CC (Covered Call) removed — requires owning 100 shares per contract.
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

# Pages that are ALWAYS accessible — cannot be disabled
_ALWAYS_ON = {"🏠  Market Overview", "⚙️  Admin Panel"}

# Group display config
GROUP_META = {
    "Dashboard": {"icon": "🏠"},
    "Stocks":    {"icon": "📊"},
    "Options":   {"icon": "🎯"},
    "Dividend":  {"icon": "💵"},
    "Info":      {"icon": "ℹ️"},
}


# ── Google Sheets helpers ──────────────────────────────────────

def _gs_ws():
    """Return the PageSettings worksheet, or None if GSheets not configured."""
    try:
        from scanners.gsheet_helper import _gs_sheet
        return _gs_sheet(_GS_TAB)
    except Exception:
        return None


def _read_from_gsheets() -> dict | None:
    """
    Read settings from the PageSettings GSheet tab.
    Returns a {key: bool} dict, or None if unavailable.
    Maintenance keys are excluded — they live in maintenance.json, not here.
    """
    ws = _gs_ws()
    if not ws:
        return None
    try:
        rows = ws.get_all_records()
        if not rows:
            return None
        out = {}
        for row in rows:
            k = str(row.get("Key", "")).strip()
            # Skip maintenance keys — they are stored as strings in maintenance.json,
            # not as booleans, so the boolean-only parser here would corrupt them.
            if k in (_MAINT_KEY, _MAINT_MSG_KEY):
                continue
            v = str(row.get("Enabled", "true")).strip().lower()
            if k:
                out[k] = v not in ("false", "0", "no")
        return out if out else None
    except Exception:
        return None


def _save_to_gsheets(settings: dict) -> bool:
    """
    Overwrite the PageSettings tab with the current settings dict.
    Maintenance keys are excluded — they live in maintenance.json.
    Returns True on success.
    """
    ws = _gs_ws()
    if not ws:
        return False
    try:
        ws.clear()
        # Strip maintenance keys — they must not be stored here as booleans
        clean = {k: v for k, v in settings.items()
                 if k not in (_MAINT_KEY, _MAINT_MSG_KEY)}
        all_rows = [["Key", "Enabled"]] + [[k, str(v)] for k, v in clean.items()]
        ws.update(all_rows, "A1")
        return True
    except Exception:
        return False


# ── Local JSON fallback ────────────────────────────────────────

def _read_from_disk() -> dict:
    """Read settings from local JSON, merging with defaults."""
    defaults = {p["key"]: True for p in ALL_PAGES}
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            defaults.update(saved)
        except Exception:
            pass
    return defaults


def _save_to_disk(settings: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


# ── Unified load / save ────────────────────────────────────────

def _apply_required(settings: dict) -> dict:
    """Force required pages to True regardless of stored value."""
    for p in ALL_PAGES:
        if p.get("required"):
            settings[p["key"]] = True
    return settings


def _load_settings() -> dict:
    """
    Load from GSheets if available, else fall back to local JSON.
    Merges with defaults so any new pages are enabled by default.
    """
    defaults = {p["key"]: True for p in ALL_PAGES}

    # Try GSheets first (survives Streamlit Cloud restarts)
    gs = _read_from_gsheets()
    if gs is not None:
        defaults.update(gs)
        return _apply_required(defaults)

    # Fall back to local JSON
    disk = _read_from_disk()
    defaults.update(disk)
    return _apply_required(defaults)


def load_page_settings() -> dict:
    """
    Return {page_key: bool} — True = enabled for regular users.
    Uses session-state as an in-session cache (one sheet read per login).
    """
    if "_page_settings_cache" in st.session_state:
        return st.session_state["_page_settings_cache"]
    data = _load_settings()
    st.session_state["_page_settings_cache"] = data
    return data


def save_page_settings(settings: dict) -> None:
    """
    Persist settings. Tries GSheets first; falls back to local JSON.
    Updates the in-session cache so changes are visible immediately.
    """
    _apply_required(settings)

    # Try GSheets (primary — survives restarts)
    if not _save_to_gsheets(settings):
        # GSheets unavailable — write to local JSON
        _save_to_disk(settings)

    # Always update the in-session cache
    st.session_state["_page_settings_cache"] = dict(settings)


# ── Maintenance mode ───────────────────────────────────────────
# Stored in data/maintenance.json — a separate file from PageSettings.
#
# WHY a separate file?
#   PageSettings (GSheets) uses a boolean-only "Key / Enabled" schema.
#   Storing a string message there causes _read_from_gsheets() to parse
#   it as True (since the string isn't "false"/"0"/"no").  Keeping
#   maintenance state in its own JSON avoids any type corruption.

_MAINT_KEY     = "__maintenance__"   # kept for backward-compat filtering
_MAINT_MSG_KEY = "__maintenance_msg__"  # kept for backward-compat filtering
_MAINT_MSG_DEFAULT = "Cleaning Lenses! 🔭  Be right back."


# ── Local maintenance.json helpers ─────────────────────────────

def _read_maintenance_file() -> dict:
    """Return {enabled: bool, message: str} from data/maintenance.json."""
    defaults = {"enabled": False, "message": _MAINT_MSG_DEFAULT}
    if os.path.exists(_MAINT_FILE):
        try:
            with open(_MAINT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            defaults.update(data)
        except Exception:
            pass
    return defaults


def _write_maintenance_file(enabled: bool, message: str) -> None:
    """Persist maintenance state to data/maintenance.json."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(_MAINT_FILE, "w", encoding="utf-8") as f:
        json.dump({"enabled": enabled, "message": message}, f,
                  indent=2, ensure_ascii=False)


# ── Public API ─────────────────────────────────────────────────

def is_maintenance_mode() -> bool:
    """True when admin has enabled maintenance mode for regular users."""
    return bool(_read_maintenance_file().get("enabled", False))


def get_maintenance_message() -> str:
    """Return the current admin-set maintenance message (always a real string).
    Auto-heals corrupted boolean-as-string values left over from the old
    GSheets-based storage (e.g. 'True', 'False', '1', '0').
    """
    msg = _read_maintenance_file().get("message", _MAINT_MSG_DEFAULT)
    if not isinstance(msg, str) or msg.strip().lower() in ("true", "false", "1", "0", ""):
        # Corrupted value — reset to default and persist the healed file
        _write_maintenance_file(
            bool(_read_maintenance_file().get("enabled", False)),
            _MAINT_MSG_DEFAULT,
        )
        return _MAINT_MSG_DEFAULT
    return msg


def set_maintenance_mode(enabled: bool, message: str = "") -> None:
    """
    Enable or disable maintenance mode.  Persists to data/maintenance.json.
    Also clears the in-session page-settings cache so sidebar state refreshes.
    """
    msg = message.strip() if message.strip() else _MAINT_MSG_DEFAULT
    _write_maintenance_file(enabled, msg)
    # Invalidate the page-settings cache so any callers that gate on it
    # pick up the new state on the next request.
    st.session_state.pop("_page_settings_cache", None)


# ── Runtime check ──────────────────────────────────────────────

def is_page_enabled(page_key: str) -> bool:
    """
    True if the page should render for the current user.
    - _ALWAYS_ON pages → always True.
    - Admin session    → always True.
    - Regular user     → check saved settings (default True).
    """
    if page_key in _ALWAYS_ON:
        return True
    if st.session_state.get("_is_admin", False):
        return True
    return load_page_settings().get(page_key, True)
