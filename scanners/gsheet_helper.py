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
UNIVERSE_HEADERS  = ["Ticker","Name","Sector","Used_In","Num_Lists"]

_SELL_STRATEGIES   = {"CSP","CC","Dividend+CC","ETF Options"}
_OPTION_STRATEGIES = {"CSP","CC","LEAPS","ETF Options","3x ETF Options"}

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
TRACKING_CSV  = os.path.join(DATA_DIR, "tracking.csv")
WATCHLIST_CSV = os.path.join(DATA_DIR, "watchlist.csv")


# ── Google Sheets helpers ──────────────────────────────────────

@st.cache_resource(show_spinner=False)
def _gs_client():
    """
    Return an authorised gspread client, cached for the lifetime of the
    Streamlit process so we authenticate only once (not once per function call).

    Credential priority:
      1. st.secrets["gsheets"]  — Streamlit Cloud
      2. GOOGLE_CREDS_JSON env var — GitHub Actions / headless mode

    Uses gspread.service_account_from_dict() (gspread 5+, preferred).
    Falls back to gspread.authorize() with updated scopes for older versions.
    """
    try:
        import gspread, json as _json

        info = None

        # ── 1. Streamlit secrets ───────────────────────────────
        try:
            sec   = st.secrets["gsheets"]
            email = sec["client_email"]
            info  = {
                "type":                        sec["type"],
                "project_id":                  sec["project_id"],
                "private_key_id":              sec["private_key_id"],
                "private_key":                 sec["private_key"].replace("\\n", "\n"),
                "client_email":                email,
                "client_id":                   sec["client_id"],
                "auth_uri":                    "https://accounts.google.com/o/oauth2/auth",
                "token_uri":                   "https://oauth2.googleapis.com/token",
                # Required by newer gspread / google-auth versions:
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_x509_cert_url": (
                    f"https://www.googleapis.com/robot/v1/metadata/x509/"
                    f"{email.replace('@', '%40')}"
                ),
            }
        except Exception:
            pass

        # ── 2. Env-var fallback (headless / GitHub Actions) ────
        if info is None:
            creds_raw = os.environ.get("GOOGLE_CREDS_JSON", "")
            if not creds_raw:
                return None
            info = _json.loads(creds_raw)

        # ── Try modern service_account_from_dict (gspread 5+) ──
        try:
            return gspread.service_account_from_dict(info)
        except AttributeError:
            pass   # older gspread — fall through

        # ── Legacy authorize() with updated scopes ─────────────
        from google.oauth2.service_account import Credentials
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        return gspread.authorize(creds)

    except Exception:
        return None


@st.cache_resource(show_spinner=False)
def _gs_spreadsheet():
    """
    Return the opened gspread Spreadsheet, cached for the process lifetime.
    Opening the spreadsheet is an HTTP call — we want it to happen once, not
    once per page render.
    """
    try:
        client = _gs_client()
        if not client:
            return None
        try:
            sheet_id = st.secrets["gsheets"]["sheet_id"]
        except Exception:
            sheet_id = os.environ.get("GOOGLE_SHEET_ID", "")
        if not sheet_id:
            return None
        return client.open_by_key(sheet_id)
    except Exception:
        return None


def _gs_sheet(tab: str):
    """Return a worksheet object (creates the tab if it doesn't exist).
    Uses the cached spreadsheet — no re-authentication on each call.
    """
    try:
        sh = _gs_spreadsheet()
        if sh is None:
            return None
        try:
            return sh.worksheet(tab)
        except Exception:
            # Tab doesn't exist yet — create it
            return sh.add_worksheet(title=tab, rows=1000, cols=20)
    except Exception:
        return None


def _ws_get_all_records(ws) -> list:
    """
    Read all records from a worksheet, with a robust fallback for gspread
    API changes (get_all_records() behaviour changed in 5.x / 6.x).
    Falls back to get_all_values() → manual dict construction if needed.
    """
    try:
        # numericise_ignore keeps numbers as strings — avoids type-coercion errors
        try:
            return ws.get_all_records(numericise_ignore=["all"]) or []
        except TypeError:
            # Older gspread doesn't support numericise_ignore
            return ws.get_all_records() or []
    except Exception:
        # Final fallback: raw values → dicts
        try:
            all_vals = ws.get_all_values()
            if not all_vals or len(all_vals) < 2:
                return []
            headers = all_vals[0]
            return [
                {h: (row[i] if i < len(row) else "") for i, h in enumerate(headers)}
                for row in all_vals[1:]
                if any(row)   # skip blank rows
            ]
        except Exception:
            return []


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

@st.cache_data(ttl=120, show_spinner=False)
def get_tracking() -> list:
    """Read all Tracking rows. Cached 2 min — cleared automatically after writes."""
    ws = _gs_sheet("Tracking")
    if ws:
        _ensure_headers(ws, TRACKING_HEADERS)
        rows = _ws_get_all_records(ws)
        if rows is not None:   # empty list is valid (no data yet)
            return rows
    return _csv_read(TRACKING_CSV, TRACKING_HEADERS)


@st.cache_data(ttl=120, show_spinner=False)
def get_watchlist() -> list:
    """Read all WatchList rows. Cached 2 min — cleared automatically after writes."""
    ws = _gs_sheet("WatchList")
    if ws:
        _ensure_headers(ws, WATCHLIST_HEADERS)
        rows = _ws_get_all_records(ws)
        if rows is not None:
            return rows
    return _csv_read(WATCHLIST_CSV, WATCHLIST_HEADERS)


def add_to_tracking(ticker: str, strategy: str, source: str = "",
                    entry_price: str = "", extra_meta=None) -> tuple:
    """Returns (success: bool, message: str)."""
    ticker = ticker.upper().strip()
    today_str = datetime.now().strftime("%Y-%m-%d")
    existing = get_tracking()
    # Dedup: same ticker + same strategy + same calendar date.
    # Allowing different strategies (e.g. CSP + LEAPS on the same ticker same day).
    if any(
        str(r.get("Ticker", "")).upper() == ticker
        and str(r.get("Strategy", "")).upper() == strategy.upper()
        and str(r.get("Added_Date", "")).startswith(today_str)
        for r in existing
    ):
        return False, f"{ticker}/{strategy} already tracked today."

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
        "Notes":      (extra_meta or {}).get("Style", ""),  # Style stored in Notes
    }

    ws = _gs_sheet("Tracking")
    if ws:
        try:
            _ensure_headers(ws, TRACKING_HEADERS)
            ws.append_row([row[h] for h in TRACKING_HEADERS])
            get_tracking.clear()   # bust read cache so next render shows new row
            return True, f"{ticker} added to Tracking ({action} {qty})"
        except Exception as e:
            return False, f"Sheet error: {e}"
    else:
        rows = _csv_read(TRACKING_CSV, TRACKING_HEADERS)
        rows.append(row)
        _csv_write(TRACKING_CSV, rows, TRACKING_HEADERS)
        get_tracking.clear()
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
            get_watchlist.clear()   # bust read cache
            return True, f"{ticker} added to WatchList"
        except Exception as e:
            return False, f"Sheet error: {e}"
    else:
        rows = _csv_read(WATCHLIST_CSV, WATCHLIST_HEADERS)
        rows.append(row)
        _csv_write(WATCHLIST_CSV, rows, WATCHLIST_HEADERS)
        get_watchlist.clear()
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
                get_tracking.clear()   # bust read cache after delete
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
        get_tracking.clear()
        return removed


def remove_from_watchlist(ticker: str) -> bool:
    ticker = ticker.upper().strip()
    ws = _gs_sheet("WatchList")
    if ws:
        try:
            cell = ws.find(ticker, in_column=1)
            if cell:
                ws.delete_rows(cell.row)
            get_watchlist.clear()   # bust read cache after delete
            return True
        except Exception:
            return False
    else:
        rows = _csv_read(WATCHLIST_CSV, WATCHLIST_HEADERS)
        rows = [r for r in rows if str(r.get("Ticker","")).upper() != ticker]
        _csv_write(WATCHLIST_CSV, rows, WATCHLIST_HEADERS)
        get_watchlist.clear()
        return True


def move_to_tracking(ticker: str, strategy: str = "Stock", source: str = "") -> tuple:
    """Move ticker from WatchList → Tracking."""
    remove_from_watchlist(ticker)
    return add_to_tracking(ticker, strategy, source)


# ══════════════════════════════════════════════════════════════════
# MTPA TRACKER EXPORT
# ══════════════════════════════════════════════════════════════════

# Column headers for Tables 1-3 and Table 4
_MTPA_T123_HEADERS = [
    "Ticker", "Price", "Weekly Pattern", "Weekly Extended",
    "RSI", "RSI Status", "MACD>Signal", "MACD Zone", "MACD Value",
    "Vol Ratio", "Vol OK", ">SMA20", ">SMA9",
    "Days to Earnings", "Earnings Flag",
    "Candle Patterns", "RS Status", "RS Pct",
    "Sector ETF", "Sector Trending", "Flags",
]

_MTPA_T4_HEADERS = [
    "Ticker", "Price",
    "Wk MACD Line", "Wk MACD Hist", "Wk Hist Rising",
    "Daily MACD Line", "Daily MACD Hist",
    "Wk RSI", "Daily RSI",
    "Vol Ratio", "Candle Patterns", "RS Status", "RS Pct",
    "Sector ETF", "Sector Trending", "Flags", "Also In Table",
]


def _row_to_t123(r: dict) -> list:
    """Flatten a T1/T2/T3 result dict into a plain list for Sheets export."""
    def _f(v, decimals=2):
        try:
            return round(float(v), decimals)
        except Exception:
            return v
    return [
        r.get("ticker", ""),
        _f(r.get("price", "")),
        r.get("weekly_pattern", ""),
        "Yes" if r.get("weekly_extended") else "No",
        _f(r.get("rsi_value", ""), 1),
        r.get("rsi_status", ""),
        "Yes" if r.get("macd_above_signal") else "No",
        r.get("macd_zone", ""),
        _f(r.get("macd_value", ""), 3),
        _f(r.get("volume_ratio", ""), 2),
        "Yes" if r.get("volume_ok") else "No",
        "Yes" if r.get("price_above_sma20") else "No",
        "Yes" if r.get("price_above_sma9") else "No",
        r.get("days_to_earnings", ""),
        r.get("earnings_flag", ""),
        ", ".join(r.get("candle_patterns") or []),
        r.get("rs_status", ""),
        r.get("rs_pct", ""),
        r.get("sector_etf", ""),
        "Yes" if r.get("sector_trending") else "No",
        ", ".join(r.get("flags") or []),
    ]


def _row_to_t4(r: dict) -> list:
    """Flatten a T4 result dict into a plain list for Sheets export."""
    def _f(v, decimals=3):
        try:
            return round(float(v), decimals)
        except Exception:
            return v
    tbl_map = {1: "PRIME", 2: "STRONG", 3: "BUILDING", 0: ""}
    return [
        r.get("ticker", ""),
        _f(r.get("price", ""), 2),
        _f(r.get("wk_macd_line", ""), 3),
        _f(r.get("wk_macd_hist", ""), 3),
        "Yes" if r.get("wk_macd_hist_rising") else "No",
        _f(r.get("macd_value", ""), 3),
        _f(r.get("macd_hist", ""), 3),
        _f(r.get("wk_rsi_value", ""), 1),
        _f(r.get("rsi_value", ""), 1),
        _f(r.get("volume_ratio", ""), 2),
        ", ".join(r.get("candle_patterns") or []),
        r.get("rs_status", ""),
        r.get("rs_pct", ""),
        r.get("sector_etf", ""),
        "Yes" if r.get("sector_trending") else "No",
        ", ".join(r.get("flags") or []),
        tbl_map.get(r.get("in_main_tables", 0), ""),
    ]


def export_mtpa_scan(results: dict, date_str: str = "") -> tuple:
    """
    Export all four MTPA tables into the existing connected Google Spreadsheet.
    Tab name = 'MTPA-YYYY-MM-DD' (prefixed to avoid colliding with other tabs).
    If the tab already exists it is cleared and overwritten.
    Returns (success: bool, message: str).
    """
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    tab_name = f"MTPA-{date_str}"

    # Re-use the already-connected spreadsheet (same credentials, same sheet_id)
    sh = _gs_spreadsheet()
    if sh is None:
        return False, "Google Sheets not connected — check credentials in Secrets."

    # Get or create the tab
    try:
        try:
            ws = sh.worksheet(tab_name)
            ws.clear()
        except Exception:
            ws = sh.add_worksheet(title=tab_name, rows=2000, cols=25)
    except Exception as e:
        return False, f"Could not open/create tab '{tab_name}': {e}"

    t1 = results.get("table1", [])
    t2 = results.get("table2", [])
    t3 = results.get("table3", [])
    t4 = results.get("table4", [])
    scan_ts = results.get("scan_time", "")
    total   = results.get("total_scanned", 0)

    # ── Build rows ─────────────────────────────────────────────────
    all_rows: list = []

    # Meta info
    all_rows.append([
        f"MTPA Scan  {date_str}",
        f"Scanned: {total}",
        f"T1: {len(t1)}",
        f"T2: {len(t2)}",
        f"T3: {len(t3)}",
        f"T4: {len(t4)}",
        f"Time: {scan_ts:.1f}s" if isinstance(scan_ts, (int, float)) else "",
    ])
    all_rows.append([])

    # Table 1 — PRIME
    all_rows.append([f"TABLE 1 — PRIME  ({len(t1)} stocks)"])
    all_rows.append(_MTPA_T123_HEADERS)
    for r in t1:
        all_rows.append(_row_to_t123(r))
    all_rows.append([])

    # Table 2 — STRONG
    all_rows.append([f"TABLE 2 — STRONG  ({len(t2)} stocks)"])
    all_rows.append(_MTPA_T123_HEADERS)
    for r in t2:
        all_rows.append(_row_to_t123(r))
    all_rows.append([])

    # Table 3 — BUILDING
    all_rows.append([f"TABLE 3 — BUILDING  ({len(t3)} stocks)"])
    all_rows.append(_MTPA_T123_HEADERS)
    for r in t3:
        all_rows.append(_row_to_t123(r))
    all_rows.append([])

    # Table 4 — MACD MOMENTUM
    all_rows.append([f"TABLE 4 — MACD MOMENTUM  ({len(t4)} stocks)"])
    all_rows.append(_MTPA_T4_HEADERS)
    for r in t4:
        all_rows.append(_row_to_t4(r))

    # Write
    try:
        ws.update(all_rows, "A1")
        total_rows = len(t1) + len(t2) + len(t3) + len(t4)
        url = f"https://docs.google.com/spreadsheets/d/{sh.id}"
        return True, f"Exported {total_rows} stocks → tab '{tab_name}'  |  {url}"
    except Exception as e:
        return False, f"Write failed: {e}"


def using_google_sheets() -> bool:
    """Return True if Google Sheets is configured and reachable."""
    return _gs_sheet("Tracking") is not None


def gsheets_configured() -> bool:
    """Return True if GSheets credentials are present (Streamlit secrets or env vars)."""
    try:
        _ = st.secrets["gsheets"]["sheet_id"]
        return True
    except Exception:
        return bool(os.environ.get("GOOGLE_SHEET_ID") and os.environ.get("GOOGLE_CREDS_JSON"))


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


@st.cache_data(ttl=120, show_spinner=False)
def get_performance() -> list:
    """Load all Performance rows. Cached 2 min — cleared automatically after writes."""
    ws = _gs_sheet("Performance")
    if ws:
        _ensure_headers(ws, PERFORMANCE_HEADERS)
        rows = _ws_get_all_records(ws)
        if rows is not None:
            return rows
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
            get_performance.clear()   # bust read cache
            return True, f"{ticker} added to Performance ({strategy})"
        except Exception as e:
            return False, f"Performance sheet error: {e}"
    else:
        rows = _csv_read(PERF_CSV, PERFORMANCE_HEADERS)
        rows.append(row)
        _csv_write(PERF_CSV, rows, PERFORMANCE_HEADERS)
        get_performance.clear()
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
        get_performance.clear()   # bust read cache after cell update
        return True
    except Exception:
        return False


def show_storage_banner() -> None:
    """
    Display a one-time warning if Google Sheets is not set up or reachable.
    Call this at the top of tracking_page.render() and watchlist_page.render().
    Data stored in local CSV is ephemeral on Streamlit Cloud — lost on restart.
    """
    if using_google_sheets():
        return  # All good — Sheets is live

    if gsheets_configured():
        # Credentials exist but the connection failed.
        # Give the user specific things to check.
        _client_ok = _gs_client() is not None
        _sheet_ok  = _gs_spreadsheet() is not None if _client_ok else False
        if not _client_ok:
            _hint = (
                "Authentication failed — check that `private_key` in Secrets is "
                "correctly formatted (newlines as `\\n`, not literal line breaks)."
            )
        elif not _sheet_ok:
            _hint = (
                "Spreadsheet not found — verify `sheet_id` in Secrets is the "
                "long ID from the Google Sheet URL, and that the service account "
                "email has **Editor** access to that sheet."
            )
        else:
            _hint = (
                "Worksheet tab could not be opened — the sheet may have been "
                "renamed or the service account may lack Editor access."
            )
        st.warning(
            f"⚠️ **Google Sheets credentials found but connection failed.** "
            f"{_hint} "
            f"Tracking data is temporarily using local CSV (lost on app restart).",
            icon="⚠️",
        )
    else:
        st.warning(
            "⚠️ **Google Sheets not configured — tracking data will be lost on app restart.** "
            "To persist data: follow the setup guide and add `[gsheets]` credentials "
            "in **Streamlit Cloud → Settings → Secrets**.",
            icon="⚠️",
        )


# ══════════════════════════════════════════════════════════════════
# TRACKING → PERFORMANCE SYNC
# ══════════════════════════════════════════════════════════════════

# Minimum score to copy a Tracking row into Performance.
PERF_SYNC_SCORE_MIN = 70

# Strategies treated as options for dedup purposes.
_OPT_STRATS_SYNC = {"CSP", "CC", "LEAPS"}


def _is_sched_source(src: str) -> bool:
    """True when source tag comes from an AM or PM scheduled scan."""
    s = src.strip().upper()
    return s.startswith("AM·") or s.startswith("PM·")


def _perf_dedup_key(r: dict, use_tracking_fields: bool = False) -> tuple:
    """
    Build a dedup key for a Performance row.
    Stocks:  (ticker, strategy_upper, date)
    Options: (ticker, strategy_upper, date, strike, expiry[:10])
    use_tracking_fields=True reads Entry_Price/HOLD instead of Strike/Expiry
    (used when building key from a Tracking row, which lacks those fields).
    """
    tk   = str(r.get("Ticker", "")).upper().strip()
    st_  = str(r.get("Strategy", "")).upper().strip()
    dt   = str(r.get("Entry_Date" if not use_tracking_fields else "Added_Date", ""))[:10]
    if st_ in _OPT_STRATS_SYNC:
        strike = str(r.get("Strike", "")).strip()
        expiry = str(r.get("Expiry_Date" if not use_tracking_fields else "Expiry_Date", ""))[:10]
        return (tk, st_, dt, strike, expiry)
    return (tk, st_, dt, "", "")


def sync_tracking_to_performance() -> tuple:
    """
    Permanently copy qualifying Tracking rows into the Performance tab.

    Rules
    ─────
    • Source must start with "AM·" or "PM·"  (scheduled scan only — not
      manual scanner runs or individual page Track buttons)
    • Score must be > PERF_SYNC_SCORE_MIN  (default 70)
    • No duplicates:
        Stocks:  (ticker, strategy, entry_date)
        Options: (ticker, strategy, entry_date, strike, expiry)
      Note: Tracking does not store Strike/Expiry, so options dedup
      uses (ticker, strategy, date) — the same tuple with empty
      strike/expiry — which is sufficient to prevent same-day re-adds.

    Works in both Streamlit Cloud (st.secrets) and headless / GitHub
    Actions (GOOGLE_CREDS_JSON + GOOGLE_SHEET_ID env vars) because
    _gs_client() / _gs_sheet() now support both credential paths.

    Returns (added: int, skipped: int).
    """
    tracking = get_tracking()
    if not tracking:
        return 0, 0

    perf_raw = get_performance() or []

    # Build dedup set from rows already in Performance
    existing_keys: set = set()
    for r in perf_raw:
        existing_keys.add(_perf_dedup_key(r))
        # Also add the base (ticker, strategy, date) so tracking rows
        # (which have no strike/expiry) are caught too
        tk  = str(r.get("Ticker", "")).upper().strip()
        st_ = str(r.get("Strategy", "")).upper().strip()
        dt  = str(r.get("Entry_Date", ""))[:10]
        existing_keys.add((tk, st_, dt, "", ""))

    added = skipped = 0
    for t in tracking:
        src = str(t.get("Source", "")).strip()

        # ── Filter 1: must be from a scheduled AM/PM scan ────
        if not _is_sched_source(src):
            skipped += 1
            continue

        # ── Filter 2: score > threshold ──────────────────────
        try:
            score = float(str(t.get("Score", "0") or "0"))
        except Exception:
            score = 0.0
        if score <= PERF_SYNC_SCORE_MIN:
            skipped += 1
            continue

        tk    = str(t.get("Ticker", "")).upper().strip()
        strat = str(t.get("Strategy", "")).strip()
        dt    = str(t.get("Added_Date", ""))[:10]
        key   = (tk, strat.upper(), dt, "", "")   # tracking has no strike/expiry

        # ── Filter 3: dedup check ────────────────────────────
        if key in existing_keys:
            skipped += 1
            continue

        ok, _ = add_to_performance(
            tk, strat, src,
            entry_price=str(t.get("Entry_Price", "")),
            row_data={
                "Score":  str(t.get("Score", "")),
                "Notes":  str(t.get("Notes", "")),
                # Strike/Premium/Expiry/DTE not in Tracking — left blank
            },
        )
        if ok:
            existing_keys.add(key)
            added += 1
        else:
            skipped += 1

    return added, skipped


# ── Universe sheet helpers ─────────────────────────────────────

def save_universe(rows: list) -> tuple[bool, str]:
    """Write universe rows (Ticker, Name, Sector, Used_In, Num_Lists) to GSheet.
    Clears the sheet first, then writes headers + all rows.
    Returns (success, message).
    """
    ws = _gs_sheet("Universe")
    if ws is None:
        return False, "Google Sheets not connected."
    try:
        ws.clear()
        ws.append_row(UNIVERSE_HEADERS)
        if rows:
            ws.append_rows(
                [[str(r.get(h, "")) for h in UNIVERSE_HEADERS] for r in rows],
                value_input_option="RAW",
            )
        return True, f"Saved {len(rows)} rows to 'Universe' sheet."
    except Exception as e:
        return False, f"Save failed: {e}"


@st.cache_data(ttl=300, show_spinner=False)
def get_universe() -> list:
    """Read universe data (with Name/Sector) from GSheet Universe tab.
    Returns list of dicts or [] if not available.
    """
    ws = _gs_sheet("Universe")
    if ws:
        rows = _ws_get_all_records(ws)
        if rows:
            return rows
    return []
