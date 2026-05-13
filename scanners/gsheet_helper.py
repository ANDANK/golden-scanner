# scanners/gsheet_helper.py — Track / WatchList persistent storage
# Primary: Google Sheets via gspread
# Fallback: local CSV in data/ directory

import os
import csv
import streamlit as st
from datetime import datetime

# ── Constants ──────────────────────────────────────────────────
TRACKING_HEADERS  = ["Ticker","Strategy","Action","Qty","Entry_Price","Added_Date","Source","Score","HOLD","Est_Upside","Notes"]
WATCHLIST_HEADERS = ["Ticker","Added_Date","Source","Price_At_Add","Notes"]

_SELL_STRATEGIES   = {"CSP","CC","Dividend+CC","ETF Options"}
_OPTION_STRATEGIES = {"CSP","CC","LEAPS","ETF Options","3x ETF Options"}

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
TRACKING_CSV  = os.path.join(DATA_DIR, "tracking.csv")
WATCHLIST_CSV = os.path.join(DATA_DIR, "watchlist.csv")


# ── Google Sheets helpers ──────────────────────────────────────

def _gs_client():
    """Return authorised gspread client, or None if not configured."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        scopes = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        sec = st.secrets["gsheets"]
        info = {
            "type": sec["type"],
            "project_id": sec["project_id"],
            "private_key_id": sec["private_key_id"],
            "private_key": sec["private_key"].replace("\\n", "\n"),
            "client_email": sec["client_email"],
            "client_id": sec["client_id"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        return gspread.authorize(creds)
    except Exception:
        return None


def _gs_sheet(tab: str):
    """Return a worksheet, creating the tab if it doesn't exist."""
    try:
        client = _gs_client()
        if not client:
            return None
        sh = client.open_by_key(st.secrets["gsheets"]["sheet_id"])
        try:
            return sh.worksheet(tab)
        except Exception:
            ws = sh.add_worksheet(title=tab, rows=1000, cols=20)
            return ws
    except Exception:
        return None


def _ensure_headers(ws, headers: list):
    try:
        first = ws.row_values(1)
        if not first or first[0] != headers[0]:
            ws.insert_row(headers, 1)
    except Exception:
        pass


# ── CSV helpers (fallback) ─────────────────────────────────────

def _csv_read(path: str, headers: list) -> list:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(path):
        return []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [dict(r) for r in reader]
    except Exception:
        return []


def _csv_write(path: str, rows: list, headers: list):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


# ── Current price fetch ────────────────────────────────────────

def _current_price(ticker: str) -> str:
    try:
        import yfinance as yf
        p = yf.Ticker(ticker).fast_info["lastPrice"]
        return str(round(float(p), 2))
    except Exception:
        return ""


# ── Public API ─────────────────────────────────────────────────

def get_tracking() -> list:
    ws = _gs_sheet("Tracking")
    if ws:
        try:
            _ensure_headers(ws, TRACKING_HEADERS)
            return ws.get_all_records()
        except Exception:
            pass
    return _csv_read(TRACKING_CSV, TRACKING_HEADERS)


def get_watchlist() -> list:
    ws = _gs_sheet("WatchList")
    if ws:
        try:
            _ensure_headers(ws, WATCHLIST_HEADERS)
            return ws.get_all_records()
        except Exception:
            pass
    return _csv_read(WATCHLIST_CSV, WATCHLIST_HEADERS)


def add_to_tracking(ticker: str, strategy: str, source: str = "",
                    entry_price: str = "", extra_meta=None) -> tuple:
    """Returns (success: bool, message: str)."""
    ticker = ticker.upper().strip()
    today_str = datetime.now().strftime("%Y-%m-%d")
    existing = get_tracking()
    # Dedup: same ticker + same calendar date (allow re-tracking on future days)
    if any(
        str(r.get("Ticker", "")).upper() == ticker
        and str(r.get("Added_Date", "")).startswith(today_str)
        for r in existing
    ):
        return False, f"{ticker} already tracked today."

    action = "Sell" if strategy in _SELL_STRATEGIES else "Buy"
    qty    = "1 contract" if strategy in _OPTION_STRATEGIES else "100 shares"
    price  = entry_price if entry_price else _current_price(ticker)

    row = {
        "Ticker":     ticker,
        "Strategy":   strategy,
        "Action":     action,
        "Qty":        qty,
        "Entry_Price":price,
        "Added_Date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "Source":     source,
        "Score":      (extra_meta or {}).get("Score_At_Track", ""),
        "HOLD":       (extra_meta or {}).get("HOLD", ""),
        "Est_Upside": (extra_meta or {}).get("Est_Upside", ""),
        "Notes":      "",
    }

    ws = _gs_sheet("Tracking")
    if ws:
        try:
            _ensure_headers(ws, TRACKING_HEADERS)
            ws.append_row([row[h] for h in TRACKING_HEADERS])
            return True, f"{ticker} added to Tracking ({action} {qty})"
        except Exception as e:
            return False, f"Sheet error: {e}"
    else:
        rows = _csv_read(TRACKING_CSV, TRACKING_HEADERS)
        rows.append(row)
        _csv_write(TRACKING_CSV, rows, TRACKING_HEADERS)
        return True, f"{ticker} added to Tracking ({action} {qty})"


def add_to_watchlist(ticker: str, source: str = "", entry_price: str = "") -> tuple:
    ticker = ticker.upper().strip()
    existing = get_watchlist()
    if any(str(r.get("Ticker","")).upper() == ticker for r in existing):
        return False, f"{ticker} is already on your WatchList."

    price = entry_price if entry_price else _current_price(ticker)
    row = {
        "Ticker":      ticker,
        "Added_Date":  datetime.now().strftime("%Y-%m-%d %H:%M"),
        "Source":      source,
        "Price_At_Add":price,
        "Notes":       "",
    }

    ws = _gs_sheet("WatchList")
    if ws:
        try:
            _ensure_headers(ws, WATCHLIST_HEADERS)
            ws.append_row([row[h] for h in WATCHLIST_HEADERS])
            return True, f"{ticker} added to WatchList"
        except Exception as e:
            return False, f"Sheet error: {e}"
    else:
        rows = _csv_read(WATCHLIST_CSV, WATCHLIST_HEADERS)
        rows.append(row)
        _csv_write(WATCHLIST_CSV, rows, WATCHLIST_HEADERS)
        return True, f"{ticker} added to WatchList"


def remove_from_tracking(ticker: str, added_date: str = "") -> bool:
    """
    Remove exactly one tracking row matching ticker + added_date (first 10 chars = YYYY-MM-DD).
    If added_date is omitted, removes the first row with that ticker.
    """
    ticker = ticker.upper().strip()
    date_key = added_date[:10] if added_date else ""
    ws = _gs_sheet("Tracking")
    if ws:
        try:
            all_vals = ws.get_all_values()
            if not all_vals:
                return False
            headers = all_vals[0]
            tk_col   = headers.index("Ticker")   if "Ticker"     in headers else 0
            date_col = headers.index("Added_Date") if "Added_Date" in headers else -1
            for row_i, row_vals in enumerate(all_vals[1:], start=2):
                if len(row_vals) <= tk_col:
                    continue
                if row_vals[tk_col].upper().strip() != ticker:
                    continue
                if date_key and date_col >= 0 and len(row_vals) > date_col:
                    if not row_vals[date_col].startswith(date_key):
                        continue
                ws.delete_rows(row_i)
                return True
            return False
        except Exception:
            return False
    else:
        rows = _csv_read(TRACKING_CSV, TRACKING_HEADERS)
        new_rows, removed = [], False
        for r in rows:
            if (not removed
                and str(r.get("Ticker", "")).upper().strip() == ticker
                and (not date_key or str(r.get("Added_Date", "")).startswith(date_key))):
                removed = True
                continue
            new_rows.append(r)
        _csv_write(TRACKING_CSV, new_rows, TRACKING_HEADERS)
        return removed


def remove_from_watchlist(ticker: str) -> bool:
    ticker = ticker.upper().strip()
    ws = _gs_sheet("WatchList")
    if ws:
        try:
            cell = ws.find(ticker, in_column=1)
            if cell:
                ws.delete_rows(cell.row)
            return True
        except Exception:
            return False
    else:
        rows = _csv_read(WATCHLIST_CSV, WATCHLIST_HEADERS)
        rows = [r for r in rows if str(r.get("Ticker","")).upper() != ticker]
        _csv_write(WATCHLIST_CSV, rows, WATCHLIST_HEADERS)
        return True


def move_to_tracking(ticker: str, strategy: str = "Stock", source: str = "") -> tuple:
    """Move ticker from WatchList → Tracking."""
    remove_from_watchlist(ticker)
    return add_to_tracking(ticker, strategy, source)


def using_google_sheets() -> bool:
    """Return True if Google Sheets is configured and reachable."""
    return _gs_sheet("Tracking") is not None


def gsheets_configured() -> bool:
    """Return True if the [gsheets] secret block exists at all (even if auth fails)."""
    try:
        _ = st.secrets["gsheets"]["sheet_id"]
        return True
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════
# PERFORMANCE TAB — rich options / wheel strategy tracking
# ══════════════════════════════════════════════════════════════════

PERFORMANCE_HEADERS = [
    "Ticker", "Strategy", "Universe", "Option_Type",
    "Entry_Date", "Expiry_Date", "DTE",
    "Strike", "Premium", "Qty", "Entry_Stock_Price",
    "Status",                                   # Open / Expired / Assigned / Called / Closed
    "Close_Date", "Close_Stock_Price",
    "PL_Dollar", "PL_Pct", "Ann_Return",
    "Source", "Score", "Notes",
]
PERF_CSV = os.path.join(DATA_DIR, "performance.csv")

# ETF tickers used for universe detection
_ETF_SET = {
    "SPY","QQQ","IWM","DIA","GLD","SLV","TLT","HYG","LQD",
    "XLK","XLF","XLE","XLV","XLI","XLU","XLP","XLY","XLB","XLRE",
    "GDX","GDXJ","EEM","EFA","ARKK","SOXX","SMH","VNQ","IBB",
    "FXI","EWZ","KWEB","USO","UNG","UVXY","VXX","VTI","VOO",
    "SHY","IEF","AGG","BND","VCIT","VCSH","MUB","LQD","JETS",
    "XRT","KRE","IAT","ARKG","ARKW","IYR",
}


def get_performance() -> list:
    """Load all rows from the Performance tab (or CSV fallback)."""
    ws = _gs_sheet("Performance")
    if ws:
        try:
            _ensure_headers(ws, PERFORMANCE_HEADERS)
            return ws.get_all_records()
        except Exception:
            pass
    return _csv_read(PERF_CSV, PERFORMANCE_HEADERS)


def add_to_performance(ticker: str, strategy: str, source: str = "",
                       entry_price: str = "", row_data: dict = None) -> tuple:
    """Write a tracked position to the Performance tab with full options metadata.

    row_data should be the scanner result row converted to dict — it supplies
    Strike, Premium, Expiry, DTE, Score automatically.
    Returns (success: bool, message: str).
    """
    ticker   = ticker.upper().strip()
    row_data = row_data or {}
    now_str  = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── Extract options fields from the scanner row ────────────
    strike  = str(row_data.get("Strike") or row_data.get("Call Strike") or "")
    premium = str(row_data.get("Premium") or "")
    expiry  = str(row_data.get("Expiry") or "")
    dte     = str(row_data.get("DTE") or "")
    score   = str(row_data.get("Score") or "")

    strat_up = strategy.upper()
    if strat_up == "CSP":
        option_type = "Put"
    elif strat_up in ("CC", "LEAPS"):
        option_type = "Call"
    else:
        option_type = "Stock"

    # Determine universe from source tag or ticker symbol
    if "ETF" in source.upper():
        universe = "ETFs"
    elif ticker in _ETF_SET:
        universe = "ETFs"
    else:
        universe = "Stocks"

    # Annualised return at entry (informational)
    try:
        p, s, d = float(premium), float(strike), float(dte)
        ann = round((p / s) * (365 / d) * 100, 2) if s > 0 and d > 0 else ""
    except Exception:
        ann = ""

    row = {
        "Ticker":            ticker,
        "Strategy":          strategy,
        "Universe":          universe,
        "Option_Type":       option_type,
        "Entry_Date":        now_str,
        "Expiry_Date":       expiry,
        "DTE":               dte,
        "Strike":            strike,
        "Premium":           premium,
        "Qty":               "1",
        "Entry_Stock_Price": entry_price,
        "Status":            "Open",
        "Close_Date":        "",
        "Close_Stock_Price": "",
        "PL_Dollar":         "",
        "PL_Pct":            "",
        "Ann_Return":        str(ann) if ann != "" else "",
        "Source":            source,
        "Score":             score,
        "Notes":             "",
    }

    ws = _gs_sheet("Performance")
    if ws:
        try:
            _ensure_headers(ws, PERFORMANCE_HEADERS)
            ws.append_row([row[h] for h in PERFORMANCE_HEADERS])
            return True, f"{ticker} added to Performance ({strategy})"
        except Exception as e:
            return False, f"Performance sheet error: {e}"
    else:
        rows = _csv_read(PERF_CSV, PERFORMANCE_HEADERS)
        rows.append(row)
        _csv_write(PERF_CSV, rows, PERFORMANCE_HEADERS)
        return True, f"{ticker} added to Performance CSV ({strategy})"


def update_performance_row(row_index: int, fields: dict) -> bool:
    """Update specific cells in a Performance row.  row_index is 1-based (header=1)."""
    ws = _gs_sheet("Performance")
    if not ws:
        return False
    try:
        headers = ws.row_values(1)
        for field, value in fields.items():
            if field in headers:
                col = headers.index(field) + 1
                ws.update_cell(row_index, col, str(value))
        return True
    except Exception:
        return False


def show_storage_banner() -> None:
    """
    Display a one-time warning if Google Sheets is not set up.
    Call this at the top of tracking_page.render() and watchlist_page.render().
    Data stored in local CSV is ephemeral on Streamlit Cloud — lost on restart.
    """
    if using_google_sheets():
        return  # All good — Sheets is live
    if gsheets_configured():
        st.warning(
            "⚠️ **Google Sheets credentials found but connection failed.** "
            "Check that your service account has Editor access to the sheet "
            "and that the `sheet_id` in Secrets is correct. "
            "Tracking data is temporarily using local CSV (lost on app restart).",
            icon="⚠️",
        )
    else:
        st.warning(
            "⚠️ **Google Sheets not configured — tracking data will be lost on app restart.** "
            "To persist data: follow the setup guide and add `[gsheets]` credentials "
            "in **Streamlit Cloud → Settings → Secrets**.",
            icon="⚠️",
        )
