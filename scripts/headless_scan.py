#!/usr/bin/env python3
"""
scripts/headless_scan.py — Run options scans without a browser.

Called by GitHub Actions at 9 AM and 1 PM CST (Mon–Fri).
Saves results to:
  1. data/sched_{slot}_{date}.json  (committed back to repo)
  2. Google Sheets                  (if GOOGLE_SHEET_ID + GOOGLE_CREDS_JSON set)

Usage:
  SCAN_SLOT=am python scripts/headless_scan.py
  SCAN_SLOT=pm python scripts/headless_scan.py
"""

import os, sys, json, time, random
from datetime import datetime, date

# ── Add project root to path ──────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ── Mock Streamlit so scanner modules import without a server ──
from unittest.mock import MagicMock, patch

class _FakePH:
    """Fake Streamlit placeholder (st.empty / st.progress)."""
    def markdown(self, *a, **kw): pass
    def empty(self):              pass
    def progress(self, *a, **kw): pass

class _FakeSS(dict):
    """Fake st.session_state — behaves like a dict."""
    def __missing__(self, key):   return None

_SS = _FakeSS()

class _MockST:
    session_state = _SS

    @staticmethod
    def empty():            return _FakePH()
    @staticmethod
    def progress(n=0):     return _FakePH()
    @staticmethod
    def markdown(*a, **kw): pass
    @staticmethod
    def warning(*a, **kw):  pass
    @staticmethod
    def error(*a, **kw):    pass
    @staticmethod
    def info(*a, **kw):     pass
    @staticmethod
    def success(*a, **kw):  pass
    @staticmethod
    def spinner(*a, **kw):
        from contextlib import contextmanager
        @contextmanager
        def _ctx(): yield
        return _ctx()
    @staticmethod
    def cache_data(ttl=None, show_spinner=True):
        """Make @st.cache_data a passthrough — no caching in headless mode."""
        def _dec(fn): return fn
        return _dec
    @staticmethod
    def rerun(): pass
    @staticmethod
    def toast(*a, **kw): pass

sys.modules["streamlit"] = _MockST()

# ── Now safe to import project modules ────────────────────────
import pandas as pd
from config import SP500_SAMPLE, OPTIONS_ETF_UNIVERSE

SLOT          = os.environ.get("SCAN_SLOT", "am").lower()
DATA_DIR      = os.path.join(ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)

OPTIONS_SCAN_STOCKS = int(os.environ.get("OPTIONS_SCAN_STOCKS",  20))  # top N stocks for CSP / CC / LEAPS scans
GOLDEN_SCAN_TICKERS = int(os.environ.get("GOLDEN_SCAN_TICKERS",  50))  # top N stocks for Golden Scan
SCORE_MIN           = int(os.environ.get("SCORE_MIN",            60))  # auto-track threshold
BATCH_SIZE          = int(os.environ.get("SCAN_BATCH_SIZE",      20))  # tickers per batch
BATCH_PAUSE_S       = int(os.environ.get("SCAN_BATCH_PAUSE",     30))  # seconds between batches


def log(msg: str):
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}", flush=True)


# ── Batch pause (same logic as the Streamlit scanners) ────────
BATCH_SIZE    = 20
BATCH_PAUSE_S = 30


def _batch_sleep(i: int, total: int):
    """Pause between batches; log countdown."""
    if i > 0 and i % BATCH_SIZE == 0:
        batch_num    = i // BATCH_SIZE
        total_batches = max(1, (total - 1) // BATCH_SIZE + 1)
        log(f"⏸  Batch {batch_num}/{total_batches} done — cooling down {BATCH_PAUSE_S}s …")
        time.sleep(BATCH_PAUSE_S)
    else:
        time.sleep(1.5 + random.uniform(0, 0.75))


# ── Scan one strategy/universe ─────────────────────────────────

def _scan_csp(tickers):
    from scanners.csp_scanner import scan_csp
    df, _ = scan_csp(tickers, 25, 0.15, 0.30, 0.70, 20.0, 1, 45,
                     batch_size=BATCH_SIZE, batch_pause=BATCH_PAUSE_S)
    return df

def _scan_cc(tickers):
    from scanners.cc_scanner import scan_cc
    df, _ = scan_cc(tickers, 0.15, 0.25, 0.70, 1, 20,
                    batch_size=BATCH_SIZE, batch_pause=BATCH_PAUSE_S)
    return df

def _scan_leaps(tickers):
    from scanners.leaps_scanner import scan_leaps
    df, _ = scan_leaps(tickers, 300, 0.60, 0.75, 40, 5.0, 5000.0,
                       batch_size=BATCH_SIZE, batch_pause=BATCH_PAUSE_S)
    return df

def _scan_golden(tickers):
    from scanners.combined_scanner import run_combined
    df = run_combined(tickers, include_value=False, include_growth=False,
                      status_ph=_FakePH())
    return df


def run_all_scans() -> pd.DataFrame:
    stocks         = SP500_SAMPLE[:OPTIONS_SCAN_STOCKS]
    golden_tickers = SP500_SAMPLE[:GOLDEN_SCAN_TICKERS]
    etfs           = OPTIONS_ETF_UNIVERSE

    plan = [
        ("Golden Scan", "Stock",  _scan_golden, golden_tickers),
        ("CSP",         "Stocks", _scan_csp,    stocks),
        ("CSP",         "ETFs",   _scan_csp,    etfs),
        ("CC",          "Stocks", _scan_cc,     stocks),
        ("CC",          "ETFs",   _scan_cc,     etfs),
        ("LEAPS",       "Stocks", _scan_leaps,  stocks),
        ("LEAPS",       "ETFs",   _scan_leaps,  etfs),
    ]

    frames = []
    for strategy, universe, fn, tickers in plan:
        log(f"Running {strategy} — {universe} ({len(tickers)} tickers) …")
        try:
            df = fn(tickers)
            if not df.empty:
                df = df.copy()
                df["Strategy"] = strategy
                df["Universe"] = universe
                frames.append(df)
                log(f"  → {len(df)} setup(s) found")
            else:
                log("  → 0 setups")
        except Exception as e:
            log(f"  ✗ ERROR: {e}")

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    if "Score" in combined.columns:
        combined["Score"] = pd.to_numeric(combined["Score"], errors="coerce").fillna(0)
        combined = (combined
                    .sort_values("Score", ascending=False)
                    .drop_duplicates(subset=["Ticker", "Strategy"])
                    .reset_index(drop=True))
    return combined


# ── Compare AM vs PM and build diff ───────────────────────────

def compute_diff(df_am: pd.DataFrame, df_pm: pd.DataFrame) -> pd.DataFrame:
    def _keys(df):
        if df.empty or "Ticker" not in df.columns:
            return set()
        strat = df.get("Strategy", pd.Series(["?"] * len(df)))
        return set(zip(df["Ticker"].astype(str), strat.astype(str)))

    am_keys = _keys(df_am)
    pm_keys = _keys(df_pm)
    new_keys = pm_keys - am_keys

    rows = []
    for tk, strat in sorted(new_keys):
        match = df_pm[df_pm["Ticker"] == tk]
        if match.empty:
            continue
        r = match.iloc[0].to_dict()
        r["Change"] = "New in PM"
        rows.append(r)

    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ── Google Sheets auto-track ───────────────────────────────────

def auto_track_to_sheets(df_new: pd.DataFrame, source: str = "Sched-PM"):
    """Write high-scoring setups to the Google Sheets Tracking tab.

    Args:
        df_new:  DataFrame of scan results to consider.
        source:  Tag written to the Source column — use "Sched-AM" or "Sched-PM"
                 so you can tell which run added each row.
    """
    sheet_id  = os.environ.get("GOOGLE_SHEET_ID", "")
    creds_raw = os.environ.get("GOOGLE_CREDS_JSON", "")
    if not sheet_id or not creds_raw:
        log("No Google Sheets credentials — skipping cloud tracking.")
        return

    try:
        import gspread
        from google.oauth2.service_account import Credentials
        creds_dict = json.loads(creds_raw)
        scopes = ["https://spreadsheets.google.com/feeds",
                  "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc    = gspread.authorize(creds)
        sh    = gc.open_by_key(sheet_id)

        try:
            ws = sh.worksheet("Tracking")
        except Exception:
            ws = sh.add_worksheet("Tracking", rows=1000, cols=20)

        today = date.today().isoformat()
        existing = ws.get_all_records()
        existing_keys = {
            (str(r.get("Ticker", "")).upper(), str(r.get("Added_Date", ""))[:10])
            for r in existing
        }

        added = 0
        for _, row in df_new.iterrows():
            tk = str(row.get("Ticker", "")).upper()
            score = int(float(str(row.get("Score", 0))))
            if score < SCORE_MIN:
                continue
            if (tk, today) in existing_keys:
                log(f"  Skipping {tk} — already tracked today")
                continue
            strat   = str(row.get("Strategy", ""))
            price   = str(row.get("Stock Price", row.get("Price", "")))
            new_row = [tk, strat, source, price, today, score, "Auto-Sched"]
            ws.append_row(new_row)
            existing_keys.add((tk, today))
            added += 1
            log(f"  ✅ Auto-tracked {tk} ({strat}, score {score}) [{source}]")

        log(f"Google Sheets: {added} ticker(s) added to Tracking [{source}].")
    except Exception as e:
        log(f"Google Sheets error: {e}")


# ── Save JSON results ──────────────────────────────────────────

def save_results(slot: str, df: pd.DataFrame):
    path = os.path.join(DATA_DIR, f"sched_{slot}_{date.today().isoformat()}.json")
    data = {
        "run_at":  datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "slot":    slot,
        "results": df.to_dict("records") if not df.empty else [],
    }
    with open(path, "w") as f:
        json.dump(data, f, default=str)
    log(f"Results saved → {path}  ({len(df)} rows)")


def load_results(slot: str) -> pd.DataFrame:
    path = os.path.join(DATA_DIR, f"sched_{slot}_{date.today().isoformat()}.json")
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        with open(path) as f:
            d = json.load(f)
        return pd.DataFrame(d.get("results", []))
    except Exception:
        return pd.DataFrame()


# ── Entry point ────────────────────────────────────────────────

if __name__ == "__main__":
    log(f"=== Headless scan starting  slot={SLOT.upper()} ===")

    df_current = run_all_scans()
    save_results(SLOT, df_current)

    if SLOT == "am":
        # Auto-track all AM setups with score ≥ SCORE_MIN
        if not df_current.empty:
            high_score_am = df_current[
                pd.to_numeric(df_current.get("Score", 0), errors="coerce").fillna(0) >= SCORE_MIN
            ]
            log(f"AM: {len(high_score_am)} setup(s) with score ≥ {SCORE_MIN} → auto-tracking")
            auto_track_to_sheets(high_score_am, source="Sched-AM")
        else:
            log("AM scan returned no results — nothing to track.")

    elif SLOT == "pm":
        # Auto-track all PM setups with score ≥ SCORE_MIN
        # (existing_keys check in auto_track_to_sheets prevents duplicates from AM)
        if not df_current.empty:
            high_score_pm = df_current[
                pd.to_numeric(df_current.get("Score", 0), errors="coerce").fillna(0) >= SCORE_MIN
            ]
            log(f"PM: {len(high_score_pm)} setup(s) with score ≥ {SCORE_MIN} → auto-tracking new ones")
            auto_track_to_sheets(high_score_pm, source="Sched-PM")

        # Also compute diff and log what's new vs AM
        df_am = load_results("am")
        if not df_am.empty and not df_current.empty:
            log("Comparing PM vs AM results …")
            df_diff = compute_diff(df_am, df_current)
            log(f"  {len(df_diff)} ticker(s) changed between AM and PM")
        else:
            log("No AM results to compare against — skipping diff.")

    log("=== Scan complete ===")
