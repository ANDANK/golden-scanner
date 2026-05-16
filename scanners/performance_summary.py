# scanners/performance_summary.py — Trading Performance Dashboard
# ─────────────────────────────────────────────────────────────────
# Reddit-style wheel options + stocks performance tracker.
#
# Primary data source: Google Sheets "Performance" tab.
# Positions are added via:
#   a) The "➕ Add Position" form directly on this page, OR
#   b) Clicking 📌 Track on any CSP/CC/LEAPS scanner result.
#
# Auto-close:  Options only (CSP/CC/LEAPS) — fetches historical price
#              on expiry date and computes final P&L.
# Fuzzy close: Stocks — no expiry, so we compute a Close Signal score
#              (0–100) from RSI, trend, gain/loss, hold-time signals.
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta, date
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *
from utils import section_header
from scanners.gsheet_helper import (
    get_performance, update_performance_row,
    add_to_performance, using_google_sheets, PERFORMANCE_HEADERS,
)

# ── Constants ──────────────────────────────────────────────────
_SELL_STRATS  = {"CSP", "CC"}
_DEBIT_STRATS = {"LEAPS"}
_STOCK_STRATS = {"GOLDEN SCAN", "MOMENTUM", "STOCK", "VALUE", "GROWTH"}

_STATUS_COLORS = {
    "Open":     "#60A5FA",
    "Expired":  ACCENT_GREEN,
    "Assigned": "#FBBF24",
    "Called":   "#A78BFA",
    "Closed":   ACCENT_GREEN,
    "Loss":     ACCENT_RED,
}

_CLOSE_SIGNAL_LABELS = {
    (0,  30): ("🟢 Hold",             ACCENT_GREEN),
    (31, 60): ("🟡 Consider Closing", "#FBBF24"),
    (61,100): ("🔴 Close Signal",     ACCENT_RED),
}

# ══════════════════════════════════════════════════════════════════
# 1. PRICE / INDICATOR HELPERS
# ══════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300, show_spinner=False)
def _hist_close(ticker: str, target_date: str) -> float | None:
    """Closing price on or just before target_date."""
    try:
        import yfinance as yf
        td    = datetime.strptime(target_date[:10], "%Y-%m-%d").date()
        start = (td - timedelta(days=5)).isoformat()
        end   = (td + timedelta(days=2)).isoformat()
        df    = yf.download(ticker, start=start, end=end,
                            auto_adjust=True, progress=False)
        if df.empty:
            return None
        return float(df["Close"].squeeze().dropna().iloc[-1])
    except Exception:
        return None


@st.cache_data(ttl=120, show_spinner=False)
def _current_prices(tickers: tuple) -> dict:
    """Batch latest close prices."""
    if not tickers:
        return {}
    try:
        import yfinance as yf
        data = yf.download(list(tickers), period="2d",
                           auto_adjust=True, progress=False, group_by="ticker")
        out = {}
        for t in tickers:
            try:
                col = data["Close"] if len(tickers) == 1 else data[t]["Close"]
                out[t] = round(float(col.dropna().iloc[-1]), 2)
            except Exception:
                out[t] = None
        return out
    except Exception:
        return {}


@st.cache_data(ttl=300, show_spinner=False)
def _tech_signals(ticker: str) -> dict:
    """Fetch RSI + SMA50 for a ticker. Used by fuzzy close logic."""
    try:
        import yfinance as yf
        df = yf.download(ticker, period="6mo", auto_adjust=True, progress=False)
        if df.empty or len(df) < 14:
            return {}
        close = df["Close"].squeeze()
        # RSI-14
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss.replace(0, np.nan)
        rsi   = float((100 - 100 / (1 + rs)).iloc[-1])
        # SMA-50
        sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
        price = float(close.iloc[-1])
        return {"rsi": rsi, "sma50": sma50, "price": price}
    except Exception:
        return {}


def _fuzzy_close_signal(row: dict, current_price: float | None) -> tuple[int, str, str]:
    """
    Compute a 0–100 Close Signal score for stock positions.
    Returns (score, label, color).
    """
    score = 0
    entry = float(row.get("Entry_Stock_Price") or 0)
    hold_days = 0
    try:
        ed = datetime.strptime(str(row.get("Entry_Date",""))[:10], "%Y-%m-%d").date()
        hold_days = (date.today() - ed).days
    except Exception:
        pass

    if current_price and entry > 0:
        pct_change = (current_price - entry) / entry * 100
        # Take-profit signal
        if pct_change >= 15:
            score += 20
        # Stop-loss signal
        if pct_change <= -8:
            score += 30
        # Held too long with little gain
        if hold_days >= 30 and pct_change < 5:
            score += 15

    # Technical signals
    tech = _tech_signals(str(row.get("Ticker", "")).upper())
    if tech:
        rsi   = tech.get("rsi")
        sma50 = tech.get("sma50")
        price = tech.get("price") or current_price
        if rsi and rsi >= 70:
            score += 25   # overbought
        if rsi and rsi <= 30:
            score += 10   # oversold — may recover, mild signal
        if sma50 and price and price < sma50:
            score += 25   # below 50-SMA — trend broken

    score = min(score, 100)
    for (lo, hi), (label, color) in _CLOSE_SIGNAL_LABELS.items():
        if lo <= score <= hi:
            return score, label, color
    return score, "🟢 Hold", ACCENT_GREEN


# ══════════════════════════════════════════════════════════════════
# 2. P&L CALCULATIONS
# ══════════════════════════════════════════════════════════════════

def _calc_pl(strategy: str, premium: float, strike: float,
             entry_stock: float, close_price: float, qty: int) -> tuple[float, float]:
    """Realized P&L for a closed/expired position."""
    mult  = 100 * qty
    strat = strategy.upper()
    if strat == "CSP":
        pl    = (premium - max(0, strike - close_price)) * mult
        basis = strike * mult
    elif strat == "CC":
        pl    = (premium + strike - entry_stock) * mult if close_price > strike \
                else premium * mult
        basis = entry_stock * mult
    elif strat == "LEAPS":
        intrinsic = max(0.0, close_price - strike)
        pl        = (intrinsic - premium) * mult
        basis     = premium * mult
    else:                          # stock / golden scan
        pl    = (close_price - entry_stock) * mult
        basis = entry_stock * mult
    pl_pct = (pl / basis * 100) if basis > 0 else 0
    return round(pl, 2), round(pl_pct, 2)


def _nf(v, default: float = 0.0) -> float:
    """NaN-safe float: returns default when v is None, empty, or NaN.

    NOTE: Python's ``nan or 0`` evaluates to ``nan`` because NaN is truthy,
    so the common ``float(v or 0)`` pattern silently passes NaN through.
    This helper catches that.
    """
    try:
        f = float(v)
        return default if f != f else f   # f != f  ↔  math.isnan(f)
    except Exception:
        return default


def _mark_to_market(strategy: str, premium: float, strike: float,
                    entry_stock: float, current: float, qty: int) -> tuple[float, float]:
    """Unrealized P&L for open positions (intrinsic-value approximation)."""
    mult  = 100 * qty
    strat = strategy.upper()
    if strat == "CSP":
        pl    = (premium - max(0, strike - current)) * mult
        basis = strike * mult
    elif strat == "CC":
        pl    = (premium - max(0, current - strike)) * mult
        basis = entry_stock * mult
    elif strat == "LEAPS":
        pl    = (max(0, current - strike) - premium) * mult
        basis = premium * mult
    else:
        pl    = (current - entry_stock) * mult
        basis = entry_stock * mult
    pl_pct = (pl / basis * 100) if basis > 0 else 0
    return round(pl, 2), round(pl_pct, 2)


# ══════════════════════════════════════════════════════════════════
# 3. AUTO-CLOSE (OPTIONS ONLY)
# ══════════════════════════════════════════════════════════════════

def _auto_close_row(r: dict, row_i: int) -> dict:
    """
    If an option position's Expiry_Date has passed, fetch closing price,
    compute P&L, and persist updated status back to Google Sheets.
    Stocks are NEVER auto-closed here — they use fuzzy signals instead.
    """
    strat = str(r.get("Strategy", "")).upper()
    if strat not in (_SELL_STRATS | _DEBIT_STRATS):   # skip stocks
        return r

    expiry_str = str(r.get("Expiry_Date", "")).strip()
    if not expiry_str:
        return r
    try:
        expiry = datetime.strptime(expiry_str[:10], "%Y-%m-%d").date()
    except Exception:
        return r
    if expiry >= date.today():
        return r

    ticker      = str(r.get("Ticker", "")).upper()
    try:
        premium     = _nf(r.get("Premium"))
        strike      = _nf(r.get("Strike"))
        entry_stock = _nf(r.get("Entry_Stock_Price"))
        qty         = max(1, int(_nf(r.get("Qty"), 1.0)))
    except Exception:
        return r

    close_price = _hist_close(ticker, expiry_str)
    if close_price is None:
        return r

    pl, pl_pct = _calc_pl(strat, premium, strike, entry_stock, close_price, qty)

    if strat == "CSP":
        status = "Assigned" if close_price < strike else "Expired"
    elif strat == "CC":
        status = "Called"   if close_price > strike else "Expired"
    else:  # LEAPS
        status = "Closed"   if close_price > strike else "Expired"

    fields = {
        "Status":            status,
        "Close_Date":        expiry_str,
        "Close_Stock_Price": str(round(close_price, 2)),
        "PL_Dollar":         str(pl),
        "PL_Pct":            str(pl_pct),
    }
    try:
        update_performance_row(row_i, fields)
    except Exception:
        pass
    return {**r, **fields}


@st.cache_data(ttl=180, show_spinner=False)
def _load_and_process() -> pd.DataFrame:
    raw = list(get_performance() or [])

    # ── Also pull qualifying Tracking entries as open positions ─────
    # Only AM·/PM· scheduled-scan rows with score > 70 are shown here.
    # Manual scanner runs and low-score items are excluded to keep the
    # Performance dashboard clean.  The sync_tracking_to_performance()
    # function permanently writes these to the Performance GSheet tab;
    # this merge is a display-only fallback for the current session.
    try:
        from scanners.gsheet_helper import get_tracking as _get_tracking, PERF_SYNC_SCORE_MIN
        tracking_raw = _get_tracking() or []
        # Dedup set: for options use (ticker, strategy, date, strike, expiry);
        # for stocks use (ticker, strategy, date).
        _OPT = {"CSP","CC","LEAPS"}
        def _pk(r: dict) -> tuple:
            tk_ = str(r.get("Ticker","")).upper()
            st_ = str(r.get("Strategy","")).upper()
            dt_ = str(r.get("Entry_Date",""))[:10]
            if st_ in _OPT:
                return (tk_, st_, dt_,
                        str(r.get("Strike","")).strip(),
                        str(r.get("Expiry_Date",""))[:10])
            return (tk_, st_, dt_, "", "")
        perf_keys = {_pk(r) for r in raw}
        # Also add base (ticker, strategy, date) keys so tracking rows
        # (no strike/expiry) are caught by the dedup check
        for r in raw:
            tk_ = str(r.get("Ticker","")).upper()
            st_ = str(r.get("Strategy","")).upper()
            dt_ = str(r.get("Entry_Date",""))[:10]
            perf_keys.add((tk_, st_, dt_, "", ""))

        for t in tracking_raw:
            tk  = str(t.get("Ticker","")).upper().strip()
            st_ = str(t.get("Strategy","")).strip()
            dt  = str(t.get("Added_Date",""))[:10]
            src = str(t.get("Source","")).strip()

            if not tk:
                continue

            # ── Only AM·/PM· scheduled scans with score > threshold ──
            _is_sched = src.upper().startswith("AM·") or src.upper().startswith("PM·")
            try:
                _score_val = float(str(t.get("Score","0") or "0"))
            except Exception:
                _score_val = 0.0
            if not (_is_sched and _score_val > PERF_SYNC_SCORE_MIN):
                continue

            base_key = (tk, st_.upper(), dt, "", "")
            if base_key in perf_keys:
                continue   # already in Performance — skip
            # Convert tracking row → performance-compatible dict
            qty_raw = str(t.get("Qty","1"))
            try:
                qty_int = int("".join(filter(str.isdigit, qty_raw)) or "1")
            except Exception:
                qty_int = 1
            raw.append({
                "Ticker":            tk,
                "Strategy":          st_,
                "Universe":          t.get("Source","Tracking"),
                "Option_Type":       "",
                "Entry_Date":        t.get("Added_Date",""),
                "Expiry_Date":       "",
                "DTE":               "",
                "Strike":            "",
                "Premium":           "",
                "Qty":               str(qty_int),
                "Entry_Stock_Price": t.get("Entry_Price",""),
                "Status":            "Open",
                "Close_Date":        "",
                "Close_Stock_Price": "",
                "PL_Dollar":         "",
                "PL_Pct":            "",
                "Ann_Return":        "",
                "Source":            src,
                "Score":             t.get("Score",""),
                "Notes":             t.get("Notes",""),
            })
            perf_keys.add(base_key)   # prevent double-add within this loop
    except Exception:
        pass   # Tracking unavailable — continue with Performance only

    if not raw:
        return pd.DataFrame()

    df = pd.DataFrame(raw)

    # ── Normalise numeric columns ────────────────────────────────
    for col in ["Premium","Strike","Entry_Stock_Price","PL_Dollar","PL_Pct","Ann_Return","Qty","DTE"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["Qty"]     = df.get("Qty", pd.Series([1]*len(df))).fillna(1).astype(int)
    df["Status"]  = df["Status"].fillna("Open").astype(str).str.strip()
    df["Strategy"]= df["Strategy"].fillna("").astype(str).str.strip()
    df["Ticker"]  = df["Ticker"].fillna("").astype(str).str.upper().str.strip()

    # ── Parse dates ──────────────────────────────────────────────
    df["Entry_Date"]  = pd.to_datetime(df["Entry_Date"],  errors="coerce")
    df["Close_Date"]  = pd.to_datetime(df["Close_Date"],  errors="coerce")
    df["Expiry_Date"] = pd.to_datetime(df["Expiry_Date"], errors="coerce")
    df["Entry_Day"]   = df["Entry_Date"].dt.date
    df["Month"]       = df["Entry_Date"].dt.to_period("M").astype(str)

    # ── Auto-close expired OPTIONS ────────────────────────────────
    rows_out = []
    for idx, (_, row) in enumerate(df.iterrows()):
        if str(row.get("Status","")).strip().lower() == "open":
            rows_out.append(_auto_close_row(row.to_dict(), idx + 2))
        else:
            rows_out.append(row.to_dict())
    df = pd.DataFrame(rows_out)

    for col in ["Premium","Strike","Entry_Stock_Price","PL_Dollar","PL_Pct"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["Qty"]     = pd.to_numeric(df.get("Qty",1), errors="coerce").fillna(1).astype(int)
    df["Status"]  = df["Status"].fillna("Open").astype(str).str.strip()
    df["Strategy"]= df["Strategy"].fillna("").astype(str).str.strip()
    df["Ticker"]  = df["Ticker"].fillna("").astype(str).str.upper().str.strip()

    # ── Live prices for remaining Open positions ─────────────────
    open_mask    = df["Status"].str.lower() == "open"
    open_tickers = tuple(df.loc[open_mask, "Ticker"].dropna().unique().tolist())
    prices       = _current_prices(open_tickers) if open_tickers else {}

    def _fill_open(row):
        if str(row.get("Status","")).strip().lower() != "open":
            return row
        ticker = str(row.get("Ticker","")).upper()
        cp     = prices.get(ticker)
        row    = dict(row)
        row["Current_Price"] = cp
        if cp is not None:
            try:
                strat = str(row.get("Strategy","")).upper()
                prem  = _nf(row.get("Premium"))
                strk  = _nf(row.get("Strike"))
                entry = _nf(row.get("Entry_Stock_Price"))
                qty   = max(1, int(_nf(row.get("Qty"), 1.0)))

                # Options with no trade data (tracking-only rows) — skip P&L
                # rather than produce a nonsense number
                if strat in ("CSP", "CC", "LEAPS") and prem <= 0 and strk <= 0:
                    pass   # leave PL_Dollar / PL_Pct as-is → displays "—"
                else:
                    pl, pl_pct = _mark_to_market(strat, prem, strk, entry, cp, qty)
                    row["PL_Dollar"] = pl
                    row["PL_Pct"]    = pl_pct
            except Exception:
                pass
        return row

    df = pd.DataFrame([_fill_open(r) for r in df.to_dict("records")])
    for col in ["PL_Dollar","PL_Pct"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # ── Income column (premium × 100 for closed sell-strats) ─────
    def _income(row):
        st_   = str(row.get("Status","")).lower()
        strat = str(row.get("Strategy","")).upper()
        if strat in _SELL_STRATS and st_ in ("expired","closed","assigned","called"):
            return round(_nf(row.get("Premium")) * 100 * max(1, int(_nf(row.get("Qty"), 1.0))), 2)
        return _nf(row.get("PL_Dollar"))

    df["Income"] = df.apply(_income, axis=1)

    if "Entry_Day" not in df.columns:
        df["Entry_Day"] = pd.to_datetime(df["Entry_Date"], errors="coerce").dt.date
    if "Month" not in df.columns:
        df["Month"] = pd.to_datetime(df["Entry_Date"], errors="coerce").dt.to_period("M").astype(str)

    return df


# ══════════════════════════════════════════════════════════════════
# 4. ADD-POSITION FORM  (direct entry — no scanner needed)
# ══════════════════════════════════════════════════════════════════

def _render_add_position_form():
    """Sidebar / expander form to manually log a position into Performance tab."""
    with st.expander("➕ Add Position Manually", expanded=False):
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:11px;margin-bottom:10px">'
            f'Log a trade directly — no scanner required.</div>',
            unsafe_allow_html=True,
        )
        c1, c2 = st.columns(2)
        with c1:
            ticker   = st.text_input("Ticker", placeholder="e.g. AAPL", key="af_ticker").upper().strip()
            strategy = st.selectbox("Strategy", ["CSP","CC","LEAPS","Golden Scan","Momentum","Stock","Other"], key="af_strategy")
            strike   = st.number_input("Strike ($)", min_value=0.0, value=0.0, step=0.5, key="af_strike")
            premium  = st.number_input("Premium / share ($)", min_value=0.0, value=0.0, step=0.01, key="af_premium")
        with c2:
            entry_price = st.number_input("Entry Stock Price ($)", min_value=0.0, value=0.0, step=0.5, key="af_eprice")
            qty         = st.number_input("Qty (contracts / lots)", min_value=1, value=1, step=1, key="af_qty")
            expiry_raw  = st.date_input("Expiry Date (options only)", value=None, key="af_expiry")
            universe    = st.selectbox("Universe", ["Stocks","ETFs"], key="af_universe")
        notes = st.text_input("Notes (optional)", key="af_notes")

        if st.button("💾 Save Position", use_container_width=True, key="af_submit"):
            if not ticker:
                st.error("Ticker is required.")
                return
            expiry_str = expiry_raw.isoformat() if expiry_raw else ""
            dte_val    = (expiry_raw - date.today()).days if expiry_raw else ""
            try:
                ann = round((premium / strike) * (365 / dte_val) * 100, 2) \
                      if strike > 0 and dte_val and dte_val > 0 else ""
            except Exception:
                ann = ""

            # Map strategy → option type
            opt_type = {"CSP":"Put","CC":"Call","LEAPS":"Call"}.get(strategy, "Stock")

            row_data = {
                "Ticker":            ticker,
                "Strategy":          strategy,
                "Universe":          universe,
                "Option_Type":       opt_type,
                "Entry_Date":        datetime.now().strftime("%Y-%m-%d %H:%M"),
                "Expiry_Date":       expiry_str,
                "DTE":               str(dte_val),
                "Strike":            str(strike)   if strike   else "",
                "Premium":           str(premium)  if premium  else "",
                "Qty":               str(qty),
                "Entry_Stock_Price": str(entry_price) if entry_price else "",
                "Status":            "Open",
                "Close_Date":        "",
                "Close_Stock_Price": "",
                "PL_Dollar":         "",
                "PL_Pct":            "",
                "Ann_Return":        str(ann),
                "Source":            "Manual",
                "Score":             "",
                "Notes":             notes,
            }
            ws = None
            try:
                from scanners.gsheet_helper import _gs_sheet, _ensure_headers
                ws = _gs_sheet("Performance")
            except Exception:
                pass
            if ws:
                try:
                    _ensure_headers(ws, PERFORMANCE_HEADERS)
                    ws.append_row([row_data.get(h,"") for h in PERFORMANCE_HEADERS])
                    st.success(f"✅ {ticker} ({strategy}) saved to Performance tab.")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Sheet error: {e}")
            else:
                # CSV fallback
                import csv
                DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
                path = os.path.join(DATA_DIR, "performance.csv")
                os.makedirs(DATA_DIR, exist_ok=True)
                write_header = not os.path.exists(path)
                with open(path, "a", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=PERFORMANCE_HEADERS)
                    if write_header:
                        w.writeheader()
                    w.writerow({h: row_data.get(h,"") for h in PERFORMANCE_HEADERS})
                st.success(f"✅ {ticker} saved to local CSV.")
                st.cache_data.clear()
                st.rerun()


def _render_close_button(row: dict, row_index: int, context: str = ""):
    """Inline 'Close Position' button with current-price P&L confirmation."""
    ticker = str(row.get("Ticker","")).upper()
    # context disambiguates keys when the same ticker/row appears in multiple tabs
    import hashlib
    _ctx = hashlib.md5(f"{context}{ticker}{row_index}".encode()).hexdigest()[:6]
    key  = f"close_{_ctx}"
    if st.button("✖", key=key, use_container_width=True,
                 help=f"Close {ticker} at today's price"):
        cp = _current_prices((ticker,)).get(ticker)
        if cp is None:
            st.warning("Could not fetch current price. Try again.")
            return
        strat  = str(row.get("Strategy","")).upper()
        try:
            pl, pl_pct = _calc_pl(
                strat,
                _nf(row.get("Premium")),
                _nf(row.get("Strike")),
                _nf(row.get("Entry_Stock_Price")),
                cp, max(1, int(_nf(row.get("Qty"), 1.0))),
            )
        except Exception:
            pl, pl_pct = 0.0, 0.0
        fields = {
            "Status":            "Closed",
            "Close_Date":        date.today().isoformat(),
            "Close_Stock_Price": str(cp),
            "PL_Dollar":         str(pl),
            "PL_Pct":            str(pl_pct),
        }
        try:
            update_performance_row(row_index, fields)
            st.success(f"Closed {ticker} @ ${cp:.2f} · P&L {'+' if pl>=0 else ''}${pl:,.2f}")
            st.cache_data.clear()
            st.rerun()
        except Exception as e:
            st.error(f"Could not update sheet: {e}")


# ══════════════════════════════════════════════════════════════════
# 5. UI HELPERS
# ══════════════════════════════════════════════════════════════════

def _kpi(label: str, value: str, sub: str = "", color: str = None):
    color = color or GOLD
    sub_html = f'<div style="color:{TEXT_MUTED};font-size:11px;margin-top:3px">{sub}</div>' if sub else ""
    st.markdown(f"""
    <div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};
                border-top:3px solid {color};border-radius:8px;padding:14px 16px">
      <div style="color:{TEXT_MUTED};font-size:10px;text-transform:uppercase;
                  letter-spacing:1.2px;margin-bottom:6px">{label}</div>
      <div style="color:{color};font-family:'Cormorant Garamond',serif;
                  font-size:26px;font-weight:800;line-height:1.1">{value}</div>
      {sub_html}
    </div>""", unsafe_allow_html=True)


def _section_label(text: str, color: str = None):
    color = color or GOLD
    st.markdown(
        f'<div style="color:{color};font-size:12px;font-weight:700;letter-spacing:1.5px;'
        f'text-transform:uppercase;margin:18px 0 8px;border-left:3px solid {color};'
        f'padding-left:10px">{text}</div>',
        unsafe_allow_html=True,
    )


def _status_badge(status: str) -> str:
    color = _STATUS_COLORS.get(status, TEXT_MUTED)
    return (f'<span style="background:{color}22;color:{color};font-size:10px;'
            f'padding:2px 8px;border-radius:10px;font-weight:700;border:1px solid {color}55">'
            f'{status}</span>')


def _pl_html(val) -> str:
    try:
        v = float(val)
        if v != v:   # NaN: float(nan) succeeds without raising — must check explicitly
            return f'<span style="color:{TEXT_MUTED}">—</span>'
        color = ACCENT_GREEN if v >= 0 else ACCENT_RED
        return (f'<span style="color:{color};font-family:\'DM Mono\',monospace;font-weight:700">'
                f'{"+" if v>=0 else ""}${v:,.2f}</span>')
    except Exception:
        return f'<span style="color:{TEXT_MUTED}">—</span>'


def _positions_table_html(df: pd.DataFrame, cols: list, show_close_signal: bool = False,
                          context: str = ""):
    """Positions table rendered as per-row st.columns so Action holds a real close button."""
    if df.empty:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:12px;font-style:italic;'
            f'padding:16px;text-align:center;border:1px dashed {BORDER_COLOR};'
            f'border-radius:6px">No positions in this period.</div>',
            unsafe_allow_html=True,
        )
        return

    # Data columns (no "Action" — that's a separate Streamlit column at the end)
    display_cols = cols + (["Close Signal"] if show_close_signal else [])

    # Per-column width hints
    _narrow = {"DTE", "Qty", "Score"}
    _med    = {"Status", "PL_Pct", "Universe", "Strategy", "Source", "Style"}
    _wide   = {"Ticker", "Expiry_Date", "Entry_Stock_Price", "Current_Price",
               "PL_Dollar", "Close Signal"}
    col_widths = []
    for c in display_cols:
        if c in _narrow:  col_widths.append(0.5)
        elif c in _wide:  col_widths.append(1.2)
        elif c in _med:   col_widths.append(0.85)
        else:             col_widths.append(1.0)
    col_widths.append(0.55)   # inline Action column

    # Tighten Streamlit column gaps
    st.markdown(
        "<style>"
        "div[data-testid='stHorizontalBlock']{gap:0 !important;margin-bottom:0 !important}"
        "div[data-testid='stHorizontalBlock']>div[data-testid='stColumn']"
        "{padding-top:1px !important;padding-bottom:1px !important}"
        "</style>",
        unsafe_allow_html=True,
    )

    th = (f'color:{TEXT_MUTED};font-size:10px;font-weight:700;letter-spacing:0.7px;'
          f'text-transform:uppercase;padding:7px 5px;border-bottom:1px solid {BORDER_COLOR};'
          f'background:{BG_PANEL};white-space:nowrap;overflow:hidden;text-overflow:ellipsis')

    # ── Header row ──────────────────────────────────────────────
    hdr = st.columns(col_widths)
    for i, col_name in enumerate(display_cols):
        with hdr[i]:
            st.markdown(f'<div style="{th}">{col_name.replace("_"," ")}</div>',
                        unsafe_allow_html=True)
    with hdr[-1]:
        st.markdown(f'<div style="{th};text-align:center">ACTION</div>',
                    unsafe_allow_html=True)

    # ── Data rows ────────────────────────────────────────────────
    for i, (ridx, r) in enumerate(df.iterrows()):
        bg      = BG_CARD if i % 2 == 0 else BG_PANEL
        is_open = str(r.get("Status", "")).lower() == "open"
        cp      = r.get("Current_Price")
        row_c   = st.columns(col_widths)

        for j, c in enumerate(display_cols):
            val   = r.get(c, "")
            val_s = str(val) if val is not None and str(val) != "nan" else "—"
            td    = (f'padding:6px 5px;font-size:11px;background:{bg};'
                     f'overflow:hidden;text-overflow:ellipsis')

            with row_c[j]:
                if c == "Ticker":
                    st.markdown(
                        f'<div style="{td};color:{GOLD};font-family:\'DM Mono\',monospace;'
                        f'font-weight:700;font-size:12px">{val_s}</div>',
                        unsafe_allow_html=True)
                elif c in ("PL_Dollar", "P/L $", "Income"):
                    st.markdown(f'<div style="{td}">{_pl_html(val)}</div>',
                                unsafe_allow_html=True)
                elif c in ("PL_Pct", "P/L %"):
                    try:
                        v = float(val)
                        if v != v:   # NaN guard — float(nan) never raises
                            raise ValueError
                        cc = ACCENT_GREEN if v >= 0 else ACCENT_RED
                        st.markdown(
                            f'<div style="{td};color:{cc};font-family:\'DM Mono\','
                            f'monospace;font-weight:600">{v:+.1f}%</div>',
                            unsafe_allow_html=True)
                    except Exception:
                        st.markdown(f'<div style="{td};color:{TEXT_MUTED}">—</div>',
                                    unsafe_allow_html=True)
                elif c == "Status":
                    st.markdown(f'<div style="{td}">{_status_badge(val_s)}</div>',
                                unsafe_allow_html=True)
                elif c == "Strategy":
                    sc = {"CSP": "#86EFAC", "CC": GOLD,
                          "LEAPS": "#60A5FA", "Golden Scan": "#A78BFA"}.get(val_s, TEXT_MUTED)
                    st.markdown(f'<div style="{td};color:{sc};font-weight:600">{val_s}</div>',
                                unsafe_allow_html=True)
                elif c == "Premium":
                    try:
                        st.markdown(
                            f'<div style="{td};color:{ACCENT_GREEN};'
                            f'font-family:\'DM Mono\',monospace">${float(val):.2f}</div>',
                            unsafe_allow_html=True)
                    except Exception:
                        st.markdown(f'<div style="{td};color:{TEXT_MUTED}">—</div>',
                                    unsafe_allow_html=True)
                elif c == "Current_Price":
                    try:
                        st.markdown(
                            f'<div style="{td};color:{TEXT_PRIMARY};'
                            f'font-family:\'DM Mono\',monospace">${float(val):.2f}</div>',
                            unsafe_allow_html=True)
                    except Exception:
                        st.markdown(f'<div style="{td};color:{TEXT_MUTED}">—</div>',
                                    unsafe_allow_html=True)
                elif c == "Style":
                    # Style is stored in the Notes field for tracking rows
                    style_v = val_s if val_s not in ("—", "nan", "") else str(r.get("Notes", ""))
                    style_v = style_v if style_v not in ("nan", "") else "—"
                    st.markdown(
                        f'<div style="{td};color:#A78BFA;font-size:10px;font-weight:600">'
                        f'{style_v[:18]}</div>',
                        unsafe_allow_html=True)
                elif c == "Source":
                    # Abbreviate full scanner names then display; tooltip shows original
                    _src_abbr = val_s
                    for _full, _ab in [("Trend Continuation","TC"),("Trend Cont.","TC"),
                                       ("Trend Alignment","TA"),("Trend Align","TA"),
                                       ("Trend Stack","TS"),("Multi-Factor","MF"),
                                       ("Momentum Reset Bounce","MRS"),("Reset Bounce","MRS"),
                                       ("Momentum","M"),("Growth","G"),
                                       ("Golden Scan","GS")]:
                        _src_abbr = _src_abbr.replace(_full, _ab)
                    st.markdown(
                        f'<div style="{td};color:{TEXT_MUTED};font-size:10px" title="{val_s}">'
                        f'{_src_abbr}</div>',
                        unsafe_allow_html=True)
                elif c == "Expiry_Date":
                    exp = val_s[:10] if val_s != "—" else "—"
                    st.markdown(f'<div style="{td};color:{TEXT_MUTED}">{exp}</div>',
                                unsafe_allow_html=True)
                elif c == "Close Signal":
                    strat_r = str(r.get("Strategy", "")).upper()
                    if strat_r in _STOCK_STRATS and is_open:
                        sig_score, sig_label, sig_color = _fuzzy_close_signal(r.to_dict(), cp)
                        st.markdown(
                            f'<div style="{td}"><span style="color:{sig_color};font-size:10px;'
                            f'font-weight:700;background:{sig_color}22;padding:2px 6px;'
                            f'border-radius:10px;border:1px solid {sig_color}55">'
                            f'{sig_label} ({sig_score})</span></div>',
                            unsafe_allow_html=True)
                    else:
                        st.markdown(f'<div style="{td};color:{TEXT_MUTED}">—</div>',
                                    unsafe_allow_html=True)
                else:
                    st.markdown(f'<div style="{td};color:{TEXT_PRIMARY}">{val_s}</div>',
                                unsafe_allow_html=True)

        # ── Inline Action column (real Streamlit widget) ─────────
        with row_c[-1]:
            if is_open:
                _render_close_button(r.to_dict(), ridx + 2, context=context)
            else:
                st.markdown(
                    f'<div style="padding:5px 4px;font-size:14px;color:{ACCENT_GREEN};'
                    f'text-align:center;background:{bg}">✓</div>',
                    unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# 6. CHART BUILDERS
# ══════════════════════════════════════════════════════════════════

def _chart_monthly_income(df: pd.DataFrame) -> go.Figure | None:
    closed = df[df["Status"].str.lower().isin(["expired","closed","assigned","called"])]
    if closed.empty:
        return None
    monthly = closed.groupby("Month")["Income"].sum().reset_index().sort_values("Month")
    colors  = [ACCENT_GREEN if v >= 0 else ACCENT_RED for v in monthly["Income"]]
    fig = go.Figure(go.Bar(
        x=monthly["Month"], y=monthly["Income"], marker_color=colors,
        text=[f"${v:,.0f}" for v in monthly["Income"]], textposition="outside",
        textfont=dict(color=TEXT_PRIMARY, size=11, family="DM Mono"),
        hovertemplate="<b>%{x}</b><br>Income: $%{y:,.2f}<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="Monthly Income (Realized)", font=dict(color=GOLD, size=13, family="Cormorant Garamond"), x=0.01, y=0.95),
        paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD, height=280,
        margin=dict(l=8, r=8, t=40, b=8),
        xaxis=dict(showgrid=False, color=TEXT_MUTED, tickfont=dict(size=10)),
        yaxis=dict(showgrid=True, gridcolor=BORDER_COLOR, color=TEXT_MUTED, tickprefix="$", tickfont=dict(size=10, family="DM Mono")),
        showlegend=False,
    )
    return fig


def _chart_strategy_mix(df: pd.DataFrame) -> go.Figure | None:
    mix = df.groupby("Strategy").size().reset_index(name="Count")
    if mix.empty:
        return None
    colors = [{"CSP":GOLD,"CC":ACCENT_GREEN,"LEAPS":"#60A5FA","Golden Scan":"#A78BFA"}.get(s, TEXT_MUTED) for s in mix["Strategy"]]
    fig = go.Figure(go.Pie(
        labels=mix["Strategy"], values=mix["Count"], hole=0.55,
        marker=dict(colors=colors, line=dict(color=BG_DARK, width=2)),
        textfont=dict(color=TEXT_PRIMARY, size=11),
        hovertemplate="<b>%{label}</b><br>%{value} trades (%{percent})<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="Strategy Mix (YTD)", font=dict(color=GOLD, size=13, family="Cormorant Garamond"), x=0.01, y=0.97),
        paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD, height=280,
        margin=dict(l=8, r=8, t=40, b=8),
        legend=dict(font=dict(color=TEXT_MUTED, size=10), bgcolor=BG_CARD, orientation="h", y=-0.1),
    )
    return fig


def _chart_top_tickers(df: pd.DataFrame, n: int = 6) -> go.Figure | None:
    by_tkr = df.groupby("Ticker")["Income"].sum().reset_index().sort_values("Income", ascending=False).head(n)
    if by_tkr.empty:
        return None
    colors = [ACCENT_GREEN if v >= 0 else ACCENT_RED for v in by_tkr["Income"]]
    fig = go.Figure(go.Bar(
        x=by_tkr["Income"], y=by_tkr["Ticker"], orientation="h", marker_color=colors,
        text=[f"${v:+,.0f}" for v in by_tkr["Income"]], textposition="outside",
        textfont=dict(color=TEXT_PRIMARY, size=11, family="DM Mono"),
        hovertemplate="<b>%{y}</b><br>Income: $%{x:,.2f}<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="Top Income Tickers (YTD)", font=dict(color=GOLD, size=13, family="Cormorant Garamond"), x=0.01, y=0.97),
        paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD, height=max(220, 36*n+60),
        margin=dict(l=8, r=80, t=40, b=8),
        xaxis=dict(showgrid=True, gridcolor=BORDER_COLOR, color=TEXT_MUTED, tickprefix="$", tickfont=dict(size=10, family="DM Mono")),
        yaxis=dict(showgrid=False, color=GOLD, autorange="reversed", tickfont=dict(size=11, family="DM Mono", color=GOLD)),
        showlegend=False,
    )
    return fig


def _chart_trade_outcomes(df: pd.DataFrame) -> go.Figure | None:
    outcomes = df["Status"].value_counts().reset_index()
    outcomes.columns = ["Status","Count"]
    if outcomes.empty:
        return None
    colors = [_STATUS_COLORS.get(s, TEXT_MUTED) for s in outcomes["Status"]]
    fig = go.Figure(go.Pie(
        labels=outcomes["Status"], values=outcomes["Count"], hole=0.55,
        marker=dict(colors=colors, line=dict(color=BG_DARK, width=2)),
        textfont=dict(color=TEXT_PRIMARY, size=11),
        hovertemplate="<b>%{label}</b><br>%{value} trades (%{percent})<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="Trade Outcomes (YTD)", font=dict(color=GOLD, size=13, family="Cormorant Garamond"), x=0.01, y=0.97),
        paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD, height=280,
        margin=dict(l=8, r=8, t=40, b=8),
        legend=dict(font=dict(color=TEXT_MUTED, size=10), bgcolor=BG_CARD, orientation="h", y=-0.1),
    )
    return fig


def _chart_cumulative_pnl(df: pd.DataFrame) -> go.Figure | None:
    closed = df[df["Status"].str.lower().isin(["expired","closed","assigned","called"])].sort_values("Entry_Date")
    if closed.empty:
        return None
    closed = closed.copy()
    closed["Cumulative"] = closed["Income"].cumsum()
    fig = go.Figure(go.Scatter(
        x=closed["Entry_Date"], y=closed["Cumulative"],
        mode="lines+markers", line=dict(color=GOLD, width=2),
        marker=dict(color=GOLD, size=5),
        fill="tozeroy", fillcolor=f"{GOLD}18",
        hovertemplate="<b>%{x|%b %d}</b><br>Cumulative: $%{y:,.2f}<extra></extra>",
    ))
    fig.update_layout(
        paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD, height=240,
        margin=dict(l=8, r=8, t=16, b=8),
        xaxis=dict(showgrid=False, color=TEXT_MUTED, tickfont=dict(size=10)),
        yaxis=dict(showgrid=True, gridcolor=BORDER_COLOR, color=TEXT_MUTED, tickprefix="$", tickfont=dict(size=10, family="DM Mono")),
        showlegend=False,
    )
    return fig


# ══════════════════════════════════════════════════════════════════
# 7. SHARED SECTION RENDERERS
# ══════════════════════════════════════════════════════════════════

def _render_daily_summary_boxes(df: pd.DataFrame):
    """Two summary boxes: Golden Scan positions (by source) + Options positions."""
    box_style = (f'background:{BG_CARD};border:1px solid {BORDER_COLOR};'
                 f'border-radius:8px;padding:14px;height:100%')

    # ── Classify rows ──────────────────────────────────────────────
    gs_df  = df[df["Strategy"].str.upper().isin(_STOCK_STRATS)].copy()
    opt_df = df[df["Strategy"].str.upper().isin({"CSP","CC","LEAPS"})].copy()

    c1, c2 = st.columns(2)

    # ── BOX 1: Golden Scan / Stocks (grouped by Source) ───────────
    with c1:
        open_gs  = gs_df[gs_df["Status"].str.lower() == "open"]
        total_pl = gs_df["PL_Dollar"].fillna(0).sum()
        pl_color = ACCENT_GREEN if total_pl >= 0 else ACCENT_RED
        st.markdown(f'<div style="{box_style};border-top:3px solid {ACCENT_GREEN}">'
                    f'<div style="color:{ACCENT_GREEN};font-size:12px;font-weight:700;'
                    f'text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">'
                    f'📊 GS / Stock Positions ({len(gs_df)})</div>', unsafe_allow_html=True)
        if gs_df.empty:
            st.markdown(f'<div style="color:{TEXT_MUTED};font-size:12px;font-style:italic;'
                        f'padding:8px 0">No stock positions yet.</div>', unsafe_allow_html=True)
        else:
            # Group by source
            gs_df2 = gs_df.copy()
            gs_df2["_src"] = gs_df2["Source"].fillna("—").astype(str)
            for src, grp in gs_df2.groupby("_src"):
                grp_pl = grp["PL_Dollar"].fillna(0).sum()
                gc = ACCENT_GREEN if grp_pl >= 0 else ACCENT_RED
                tickers = " · ".join(grp["Ticker"].astype(str).tolist()[:6])
                st.markdown(
                    f'<div style="border-bottom:1px solid {BORDER_COLOR}22;'
                    f'padding:5px 0">'
                    f'<div style="color:{TEXT_MUTED};font-size:10px;font-weight:600;'
                    f'letter-spacing:.5px">{src[:60]}</div>'
                    f'<div style="display:flex;justify-content:space-between">'
                    f'<span style="color:{GOLD};font-family:\'DM Mono\',monospace;'
                    f'font-size:11px">{tickers}</span>'
                    f'<span style="color:{gc};font-family:\'DM Mono\',monospace;'
                    f'font-size:11px;font-weight:700">{"+" if grp_pl>=0 else ""}${grp_pl:,.0f}</span>'
                    f'</div></div>', unsafe_allow_html=True)
        st.markdown(
            f'<div style="margin-top:8px;padding-top:6px;border-top:1px solid {BORDER_COLOR}">'
            f'<span style="color:{TEXT_MUTED};font-size:10px">TOTAL STOCK P&L  </span>'
            f'<span style="color:{pl_color};font-family:\'DM Mono\',monospace;'
            f'font-weight:800;font-size:16px">{"+" if total_pl>=0 else ""}${total_pl:,.2f}'
            f'</span></div></div>', unsafe_allow_html=True)

    # ── BOX 2: Options (CSP / CC / LEAPS) ─────────────────────────
    with c2:
        open_opts    = opt_df[opt_df["Status"].str.lower() == "open"]
        expired_opts = opt_df[opt_df["Status"].str.lower().isin(["expired","closed","assigned","called"])]
        realized     = expired_opts["Income"].fillna(0).sum()
        _qty_mean    = open_opts["Qty"].fillna(1).mean() if not open_opts.empty else 1
        open_prem    = (_nf(open_opts["Premium"].mean()) *
                        100 * max(1, int(_qty_mean) if _qty_mean == _qty_mean else 1))
        rc           = ACCENT_GREEN if realized >= 0 else ACCENT_RED
        st.markdown(f'<div style="{box_style};border-top:3px solid {GOLD}">'
                    f'<div style="color:{GOLD};font-size:12px;font-weight:700;'
                    f'text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">'
                    f'⚙️ Options Positions ({len(opt_df)})</div>', unsafe_allow_html=True)
        if opt_df.empty:
            st.markdown(f'<div style="color:{TEXT_MUTED};font-size:12px;font-style:italic;'
                        f'padding:8px 0">No options positions yet.</div>', unsafe_allow_html=True)
        else:
            for strat, strat_color in [("CSP", "#86EFAC"), ("CC", GOLD), ("LEAPS", "#60A5FA")]:
                grp  = opt_df[opt_df["Strategy"].str.upper() == strat]
                if grp.empty:
                    continue
                exp_g   = grp[grp["Status"].str.lower().isin(["expired","closed","assigned","called"])]
                inc_g   = exp_g["Income"].fillna(0).sum()
                expiring = grp[grp["Status"].str.lower() == "open"]
                tickers  = " · ".join(expiring["Ticker"].astype(str).tolist()[:4])
                ic = ACCENT_GREEN if inc_g >= 0 else ACCENT_RED
                st.markdown(
                    f'<div style="border-bottom:1px solid {BORDER_COLOR}22;padding:5px 0">'
                    f'<div style="display:flex;justify-content:space-between">'
                    f'<span style="color:{strat_color};font-size:11px;font-weight:700">'
                    f'{strat} ({len(grp)})</span>'
                    f'<span style="color:{ic};font-family:\'DM Mono\',monospace;font-size:11px">'
                    f'{"+" if inc_g>=0 else ""}${inc_g:,.0f} realized</span></div>'
                    f'<div style="color:{TEXT_MUTED};font-size:10px">{tickers}</div>'
                    f'</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div style="margin-top:8px;padding-top:6px;border-top:1px solid {BORDER_COLOR}">'
            f'<span style="color:{TEXT_MUTED};font-size:10px">REALIZED INCOME  </span>'
            f'<span style="color:{rc};font-family:\'DM Mono\',monospace;font-weight:800;'
            f'font-size:16px">{"+" if realized>=0 else ""}${realized:,.2f}</span>'
            f'</div></div>', unsafe_allow_html=True)

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)


def _render_top_cards(df: pd.DataFrame, today: date):
    closed_today = df[df["Close_Date"].dt.date == today] if "Close_Date" in df.columns else pd.DataFrame()
    open_pos     = df[df["Status"].str.lower() == "open"]
    new_today    = df[df["Entry_Day"] == today]

    c1, c2, c3 = st.columns(3)

    # ── Closed Today ────────────────────────────────────────────
    with c1:
        total_pl  = closed_today["PL_Dollar"].fillna(0).sum() if not closed_today.empty else 0
        pl_color  = ACCENT_GREEN if total_pl >= 0 else ACCENT_RED
        st.markdown(f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-top:3px solid {ACCENT_GREEN};border-radius:8px;padding:14px">'
                    f'<div style="color:{ACCENT_GREEN};font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">✅ Closed Positions</div>', unsafe_allow_html=True)
        if closed_today.empty:
            st.markdown(f'<div style="color:{TEXT_MUTED};font-size:12px;font-style:italic;padding:8px 0">None closed today</div>', unsafe_allow_html=True)
        else:
            for _, r in closed_today.head(4).iterrows():
                try:
                    pl_v  = float(r.get("PL_Dollar",0) or 0)
                    plc   = ACCENT_GREEN if pl_v >= 0 else ACCENT_RED
                    pl_s  = f'+${pl_v:,.2f}' if pl_v >= 0 else f'-${abs(pl_v):,.2f}'
                except Exception:
                    plc, pl_s = TEXT_MUTED, "—"
                st.markdown(f'<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid {BORDER_COLOR}22">'
                            f'<span style="color:{GOLD};font-family:\'DM Mono\',monospace;font-size:11px;font-weight:700">{r["Ticker"]}</span>'
                            f'<span style="color:{TEXT_MUTED};font-size:10px">{r.get("Strategy","")}</span>'
                            f'<span style="color:{plc};font-family:\'DM Mono\',monospace;font-size:11px;font-weight:700">{pl_s}</span>'
                            f'</div>', unsafe_allow_html=True)
        st.markdown(f'<div style="margin-top:8px;padding-top:6px;border-top:1px solid {BORDER_COLOR}">'
                    f'<span style="color:{TEXT_MUTED};font-size:10px">TOTAL P/L  </span>'
                    f'<span style="color:{pl_color};font-family:\'DM Mono\',monospace;font-weight:800;font-size:16px">{"+" if total_pl>=0 else ""}${total_pl:,.2f}</span></div></div>',
                    unsafe_allow_html=True)

    # ── Open Positions ───────────────────────────────────────────
    with c2:
        total_credit = (open_pos["Premium"].fillna(0) * open_pos["Qty"].fillna(1) * 100).sum()
        st.markdown(f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-top:3px solid #60A5FA;border-radius:8px;padding:14px">'
                    f'<div style="color:#60A5FA;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">⏳ Open Positions ({len(open_pos)})</div>', unsafe_allow_html=True)
        if open_pos.empty:
            st.markdown(f'<div style="color:{TEXT_MUTED};font-size:12px;font-style:italic;padding:8px 0">No open positions</div>', unsafe_allow_html=True)
        else:
            for _, r in open_pos.head(4).iterrows():
                exp = str(r.get("Expiry_Date",""))[:10] if pd.notna(r.get("Expiry_Date")) else "—"
                try:
                    pl_v = float(r.get("PL_Dollar",0) or 0)
                    plc  = ACCENT_GREEN if pl_v >= 0 else ACCENT_RED
                    pl_s = f'{pl_v:+.2f}'
                except Exception:
                    plc, pl_s = TEXT_MUTED, "—"
                st.markdown(f'<div style="display:flex;justify-content:space-between;gap:6px;padding:4px 0;border-bottom:1px solid {BORDER_COLOR}22">'
                            f'<span style="color:{GOLD};font-family:\'DM Mono\',monospace;font-size:11px;font-weight:700;min-width:45px">{r["Ticker"]}</span>'
                            f'<span style="color:{TEXT_MUTED};font-size:10px">{r.get("Strategy","")} {exp}</span>'
                            f'<span style="color:{plc};font-family:\'DM Mono\',monospace;font-size:10px">${pl_s}</span>'
                            f'</div>', unsafe_allow_html=True)
        st.markdown(f'<div style="margin-top:8px;padding-top:6px;border-top:1px solid {BORDER_COLOR}">'
                    f'<span style="color:{TEXT_MUTED};font-size:10px">TOTAL OPEN PREMIUM  </span>'
                    f'<span style="color:#60A5FA;font-family:\'DM Mono\',monospace;font-weight:800;font-size:16px">${total_credit:,.2f}</span></div></div>',
                    unsafe_allow_html=True)

    # ── New Today ────────────────────────────────────────────────
    with c3:
        new_credit = (new_today["Premium"].fillna(0) * new_today["Qty"].fillna(1) * 100).sum()
        st.markdown(f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-top:3px solid {GOLD};border-radius:8px;padding:14px">'
                    f'<div style="color:{GOLD};font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">🆕 New Positions ({len(new_today)})</div>', unsafe_allow_html=True)
        if new_today.empty:
            st.markdown(f'<div style="color:{TEXT_MUTED};font-size:12px;font-style:italic;padding:8px 0">No new positions today</div>', unsafe_allow_html=True)
        else:
            for _, r in new_today.head(4).iterrows():
                exp = str(r.get("Expiry_Date",""))[:10] if pd.notna(r.get("Expiry_Date")) else "—"
                prem = f'${float(r.get("Premium",0) or 0):.2f}'
                st.markdown(f'<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid {BORDER_COLOR}22">'
                            f'<span style="color:{GOLD};font-family:\'DM Mono\',monospace;font-size:11px;font-weight:700">{r["Ticker"]}</span>'
                            f'<span style="color:{TEXT_MUTED};font-size:10px">{r.get("Strategy","")} {exp}</span>'
                            f'<span style="color:{ACCENT_GREEN};font-family:\'DM Mono\',monospace;font-size:11px">{prem}</span>'
                            f'</div>', unsafe_allow_html=True)
        st.markdown(f'<div style="margin-top:8px;padding-top:6px;border-top:1px solid {BORDER_COLOR}">'
                    f'<span style="color:{TEXT_MUTED};font-size:10px">NEW PREMIUM COLLECTED  </span>'
                    f'<span style="color:{GOLD};font-family:\'DM Mono\',monospace;font-weight:800;font-size:16px">${new_credit:,.2f}</span></div></div>',
                    unsafe_allow_html=True)

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    realized = df.loc[df["Status"].str.lower().isin(["expired","closed","assigned","called"]), "Income"].sum()
    open_pnl = df.loc[df["Status"].str.lower() == "open", "PL_Dollar"].fillna(0).sum()
    st.markdown(f"""
    <div style="display:flex;gap:20px;background:{BG_PANEL};border:1px solid {BORDER_COLOR};
                border-radius:8px;padding:12px 20px;margin-bottom:4px;flex-wrap:wrap">
      <div>
        <div style="color:{TEXT_MUTED};font-size:10px;text-transform:uppercase;letter-spacing:1px">Premium Realized</div>
        <div style="color:{'ACCENT_GREEN' if realized>=0 else 'ACCENT_RED'};color:{ACCENT_GREEN if realized>=0 else ACCENT_RED};
                    font-family:'Cormorant Garamond',serif;font-size:30px;font-weight:800">
          {"+" if realized>=0 else ""}${realized:,.2f}</div>
        <div style="color:{TEXT_MUTED};font-size:11px">Closed + Expired + Assigned</div>
      </div>
      <div style="width:1px;background:{BORDER_COLOR}"></div>
      <div>
        <div style="color:{TEXT_MUTED};font-size:10px;text-transform:uppercase;letter-spacing:1px">Open Unrealized P&L</div>
        <div style="color:{ACCENT_GREEN if open_pnl>=0 else ACCENT_RED};
                    font-family:'Cormorant Garamond',serif;font-size:30px;font-weight:800">
          {"+" if open_pnl>=0 else ""}${open_pnl:,.2f}</div>
        <div style="color:{TEXT_MUTED};font-size:11px">Mark-to-market (intrinsic value)</div>
      </div>
    </div>""", unsafe_allow_html=True)


def _render_progress_strip(df: pd.DataFrame):
    closed       = df[df["Status"].str.lower().isin(["expired","closed","assigned","called"])]
    # Options income: only CSP + CC sell strategies that expired/closed
    opt_closed   = closed[closed["Strategy"].str.upper().isin({"CSP", "CC"})]
    income_ytd   = opt_closed["Income"].sum()
    # Open unrealized P&L across all open positions
    open_pnl     = df[df["Status"].str.lower() == "open"]["PL_Dollar"].fillna(0).sum()
    # Stock P&L: closed stock/GS positions
    stock_closed = closed[closed["Strategy"].str.upper().isin(_STOCK_STRATS)]
    stock_pnl    = stock_closed["PL_Dollar"].fillna(0).sum()
    total        = len(df)
    # Avg premium/day: options sold (CSP+CC) income ÷ days since first such trade
    opt_dates    = opt_closed["Entry_Date"].dropna()
    if not opt_dates.empty:
        days_active  = max(1, (date.today() - opt_dates.min().date()).days)
        avg_prem_day = income_ytd / days_active
    else:
        avg_prem_day = 0.0

    _section_label("🎯 Wheel Strategy Progress", GOLD)
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: _kpi("Options Income YTD", f"${income_ytd:,.2f}",
                  color=ACCENT_GREEN if income_ytd >= 0 else ACCENT_RED)
    with c2: _kpi("Positions",          str(total),              color=GOLD)
    with c3: _kpi("Open P&L",           f"${open_pnl:+,.2f}",
                  color=ACCENT_GREEN if open_pnl >= 0 else ACCENT_RED)
    with c4: _kpi("Stock P&L (Closed)", f"${stock_pnl:+,.2f}",
                  color=ACCENT_GREEN if stock_pnl >= 0 else ACCENT_RED)
    with c5: _kpi("Opt. Premium/Day",   f"${avg_prem_day:,.2f}", color=GOLD)


def _render_ticker_snapshot(df: pd.DataFrame):
    _section_label("📋 Ticker Performance Snapshot", GOLD)
    by_tkr = (df.groupby("Ticker").agg(
        Total_Income=("Income",  "sum"),
        Trades=      ("Ticker",  "count"),
        Avg_ROI=     ("PL_Pct",  "mean"),
        Wins=        ("PL_Dollar", lambda x: (pd.to_numeric(x, errors="coerce").fillna(0) > 0).sum()),
    ).reset_index().sort_values("Total_Income", ascending=False))
    if by_tkr.empty:
        return

    # ── Scanner / source info per ticker (from merged Tracking rows) ──
    def _scanner_info(tkr):
        grp      = df[df["Ticker"] == tkr]
        scanners: list[str] = []
        max_score = None
        for _, row in grp.iterrows():
            src = str(row.get("Source", "")).strip()
            if src and src.lower() not in ("", "nan", "manual", "tracking"):
                if src.upper().startswith("GS-"):
                    # "GS-Momentum,Squeeze" → individual names
                    for part in src[3:].split(","):
                        p = part.strip()
                        if p and p not in scanners:
                            scanners.append(p)
                else:
                    if src not in scanners:
                        scanners.append(src)
            try:
                sv = float(str(row.get("Score", "")).replace("%", ""))
                if sv > 0 and (max_score is None or sv > max_score):
                    max_score = sv
            except Exception:
                pass
        return (
            " · ".join(scanners[:5]) if scanners else "—",
            len(scanners),
            int(max_score) if max_score is not None else "—",
        )

    scanner_data = {tkr: _scanner_info(tkr) for tkr in by_tkr["Ticker"]}

    def _ppd(tkr):
        sub  = df[df["Ticker"] == tkr]
        days = max(1, (date.today() - sub["Entry_Date"].dropna().min().date()).days) \
               if not sub["Entry_Date"].dropna().empty else 1
        return sub["Income"].sum() / days

    by_tkr["Prem_Per_Day"] = by_tkr["Ticker"].apply(_ppd)
    by_tkr["Win_Rate"]     = (by_tkr["Wins"] / by_tkr["Trades"] * 100).round(1)

    th_s = (f'color:{TEXT_MUTED};font-size:10px;font-weight:700;letter-spacing:.8px;'
            f'text-transform:uppercase;padding:8px 12px;border-bottom:2px solid {GOLD}55;'
            f'background:{BG_PANEL};white-space:nowrap')
    hdrs = ["TICKER", "TOTAL INCOME", "TRADES", "WIN RATE", "AVG ROI",
            "PREM/DAY", "SCANNERS", "# SCANNERS", "SCORE"]
    hdr  = "".join(f'<th style="{th_s}">{h}</th>' for h in hdrs)

    rows = []
    for i, (_, r) in enumerate(by_tkr.iterrows()):
        bg  = BG_CARD if i % 2 == 0 else BG_PANEL
        inc = r["Total_Income"]
        wr  = r["Win_Rate"]
        ppd = r["Prem_Per_Day"]
        ic  = ACCENT_GREEN if inc >= 0 else ACCENT_RED
        wc  = ACCENT_GREEN if wr >= 60 else (GOLD if wr >= 40 else ACCENT_RED)

        # Avg ROI — guard against NaN (tracking rows have no P&L yet)
        try:
            roi     = float(r["Avg_ROI"])
            rc      = ACCENT_GREEN if roi >= 0 else ACCENT_RED
            roi_str = f"{roi:+.2f}%"
        except (TypeError, ValueError):
            rc, roi_str = TEXT_MUTED, "—"

        sc_names, sc_count, sc_score = scanner_data.get(r["Ticker"], ("—", 0, "—"))
        sc_color = (ACCENT_GREEN if sc_count > 2 else
                    (GOLD        if sc_count >= 1 else TEXT_MUTED))
        score_color = (ACCENT_GREEN if isinstance(sc_score, int) and sc_score >= 70 else
                       (GOLD        if isinstance(sc_score, int) and sc_score >= 50 else
                        TEXT_MUTED))

        rows.append(
            f'<tr>'
            f'<td style="padding:8px 12px;background:{bg};color:{GOLD};'
            f'font-family:\'DM Mono\',monospace;font-weight:800;font-size:13px">'
            f'{r["Ticker"]}</td>'
            f'<td style="padding:8px 12px;background:{bg};color:{ic};'
            f'font-family:\'DM Mono\',monospace;font-weight:700">'
            f'{"+" if inc>=0 else ""}${inc:,.2f}</td>'
            f'<td style="padding:8px 12px;background:{bg};color:{TEXT_PRIMARY};'
            f'text-align:center">{int(r["Trades"])}</td>'
            f'<td style="padding:8px 12px;background:{bg};color:{wc};font-weight:700">'
            f'{wr:.0f}%</td>'
            f'<td style="padding:8px 12px;background:{bg};color:{rc};'
            f'font-family:\'DM Mono\',monospace">{roi_str}</td>'
            f'<td style="padding:8px 12px;background:{bg};color:{ACCENT_BLUE};'
            f'font-family:\'DM Mono\',monospace">${ppd:,.2f}</td>'
            # ── scanner columns ──────────────────────────────────────
            f'<td style="padding:8px 12px;background:{bg};color:{sc_color};font-size:11px;'
            f'max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" '
            f'title="{sc_names}">{sc_names}</td>'
            f'<td style="padding:8px 12px;background:{bg};color:{sc_color};'
            f'text-align:center;font-weight:700">'
            f'{sc_count if sc_count else "—"}</td>'
            f'<td style="padding:8px 12px;background:{bg};color:{score_color};'
            f'font-family:\'DM Mono\',monospace;font-weight:700;text-align:center">'
            f'{sc_score}</td>'
            f'</tr>'
        )

    total_inc = by_tkr["Total_Income"].sum()
    tc     = ACCENT_GREEN if total_inc >= 0 else ACCENT_RED
    footer = (
        f'<tr style="border-top:2px solid {GOLD}55">'
        f'<td style="padding:8px 12px;background:{BG_PANEL};color:{GOLD};'
        f'font-weight:800;font-family:\'DM Mono\',monospace">TOTAL</td>'
        f'<td style="padding:8px 12px;background:{BG_PANEL};color:{tc};'
        f'font-weight:800;font-family:\'DM Mono\',monospace">${total_inc:,.2f}</td>'
        f'<td style="padding:8px 12px;background:{BG_PANEL};color:{TEXT_PRIMARY};'
        f'text-align:center;font-weight:700">{int(by_tkr["Trades"].sum())}</td>'
        f'<td colspan="6" style="padding:8px 12px;background:{BG_PANEL}"></td>'
        f'</tr>'
    )
    st.markdown(
        f'<div style="border:1px solid {BORDER_COLOR};border-radius:8px;'
        f'overflow:hidden;overflow-x:auto;margin:8px 0 20px">'
        f'<table style="width:100%;border-collapse:collapse;font-family:\'Inter\',sans-serif">'
        f'<thead><tr>{hdr}</tr></thead>'
        f'<tbody>{"".join(rows)}{footer}</tbody></table></div>',
        unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# 8. TAB RENDERERS
# ══════════════════════════════════════════════════════════════════

# Columns shown in the daily/monthly positions table
_OPT_COLS   = ["Ticker", "Strategy", "Universe", "Strike", "Premium", "DTE",
               "Expiry_Date", "Entry_Stock_Price", "Current_Price", "Status",
               "PL_Dollar", "PL_Pct", "Source"]
_STOCK_COLS = ["Ticker", "Strategy", "Style", "Entry_Stock_Price", "Current_Price",
               "Status", "PL_Dollar", "PL_Pct", "Source", "Score"]

# Ordered strategy list — CSP → LEAPS → CC → Stocks (matches Scheduled Scans order)
_STRATEGY_ORDER = [
    ("CSP",         "💰 Cash-Secured Puts (CSP)",  GOLD),
    ("LEAPS",       "🧨 LEAPS",                    "#60A5FA"),
    ("CC",          "📦 Covered Calls (CC)",        "#A78BFA"),
    ("Golden Scan", "📊 Stocks / Golden Scan",      ACCENT_GREEN),
    ("Momentum",    "📈 Momentum",                  ACCENT_GREEN),
    ("Stock",       "🏦 Stocks",                   ACCENT_GREEN),
]


def _render_daily_tab(df: pd.DataFrame):
    today = date.today()
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11px;letter-spacing:1.5px;'
        f'text-transform:uppercase;margin:8px 0 14px">'
        f'Trading Day · {today.strftime("%A %b %d, %Y")}</div>',
        unsafe_allow_html=True)

    # Summary boxes (GS + Options) — replaces the old Closed/Open/New cards
    _render_daily_summary_boxes(df)

    for strat, label_text, color in _STRATEGY_ORDER:
        sub = df[df["Strategy"] == strat].copy()
        if sub.empty:
            continue
        is_stock = strat.upper() in _STOCK_STRATS
        show_cols = _STOCK_COLS if is_stock else [c for c in _OPT_COLS if c in sub.columns]
        show_cols = [c for c in show_cols if c in sub.columns]
        with st.expander(f"**{label_text}** — {len(sub)} position(s)", expanded=True):
            sub_sorted = sub.sort_values("PL_Dollar", ascending=False, na_position="last")
            _positions_table_html(sub_sorted, show_cols, show_close_signal=is_stock,
                                  context=f"daily_{strat}")


def _render_monthly_tab(df: pd.DataFrame):
    _section_label("📆 Monthly Income & Performance", GOLD)
    months = sorted(df["Month"].dropna().unique(), reverse=True)
    if not months:
        st.info("No data yet.")
        return
    selected = st.selectbox("Select Month", months, index=0, key="perf_month_sel")
    month_df = df[df["Month"] == selected].copy()

    # ── Split options vs stocks ────────────────────────────────────
    opt_mask   = month_df["Strategy"].str.upper().isin({"CSP","CC","LEAPS"})
    opt_m      = month_df[opt_mask]
    stock_m    = month_df[~opt_mask]

    # Options: income only from expired/closed
    opt_closed = opt_m[opt_m["Status"].str.lower().isin(["expired","closed","assigned","called"])]
    income_m   = opt_closed["Income"].fillna(0).sum()
    opt_wins   = (opt_closed["PL_Dollar"].fillna(0) > 0).sum()
    opt_total  = len(opt_closed)
    opt_wr     = opt_wins / opt_total * 100 if opt_total else 0

    # Stocks: closed positions P&L
    stk_closed = stock_m[stock_m["Status"].str.lower().isin(["closed","expired"])]
    stock_pnl  = stk_closed["PL_Dollar"].fillna(0).sum()
    stk_wins   = (stk_closed["PL_Dollar"].fillna(0) > 0).sum()
    stk_total  = len(stk_closed)
    stk_wr     = stk_wins / stk_total * 100 if stk_total else 0
    open_m     = month_df[month_df["Status"].str.lower() == "open"]

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: _kpi("Options Income",   f"${income_m:,.2f}",
                  color=ACCENT_GREEN if income_m >= 0 else ACCENT_RED)
    with c2: _kpi("Opt. Win Rate",    f"{opt_wr:.0f}%",
                  sub=f"{int(opt_wins)}/{opt_total} closed",
                  color=ACCENT_GREEN if opt_wr >= 60 else (GOLD if opt_wr >= 40 else ACCENT_RED))
    with c3: _kpi("Stock P&L",        f"${stock_pnl:+,.2f}",
                  color=ACCENT_GREEN if stock_pnl >= 0 else ACCENT_RED)
    with c4: _kpi("Stock Win Rate",   f"{stk_wr:.0f}%",
                  sub=f"{int(stk_wins)}/{stk_total} closed",
                  color=ACCENT_GREEN if stk_wr >= 60 else (GOLD if stk_wr >= 40 else ACCENT_RED))
    with c5: _kpi("Open Positions",   str(len(open_m)), color=ACCENT_BLUE)
    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    # ── Charts row: monthly income bar + 2 P&L pies ───────────────
    fa, fb, fc = st.columns([3, 2, 2])
    with fa:
        fig = _chart_monthly_income(df)
        if fig:
            st.plotly_chart(fig, width='stretch', config={"displayModeBar": False},
                            key="perf_monthly_income")
    with fb:
        # Options P&L pie (expired only)
        _section_label("Options P&L", GOLD)
        if not opt_closed.empty:
            outcomes_opt = opt_closed["Status"].value_counts().reset_index()
            outcomes_opt.columns = ["Status","Count"]
            colors_opt = [_STATUS_COLORS.get(s, TEXT_MUTED) for s in outcomes_opt["Status"]]
            fig_op = go.Figure(go.Pie(
                labels=outcomes_opt["Status"], values=outcomes_opt["Count"], hole=0.55,
                marker=dict(colors=colors_opt, line=dict(color=BG_DARK, width=2)),
                textfont=dict(color=TEXT_PRIMARY, size=11),
            ))
            fig_op.update_layout(paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD, height=220,
                                  margin=dict(l=4, r=4, t=10, b=4),
                                  legend=dict(font=dict(color=TEXT_MUTED, size=10),
                                              bgcolor=BG_CARD, orientation="h", y=-0.15),
                                  showlegend=True)
            st.plotly_chart(fig_op, width='stretch',
                            config={"displayModeBar": False}, key="perf_monthly_opt_pie")
        else:
            st.markdown(f'<div style="color:{TEXT_MUTED};font-size:11px;font-style:italic;'
                        f'padding:20px 0;text-align:center">No expired options this month</div>',
                        unsafe_allow_html=True)
    with fc:
        # Stocks P&L pie (closed)
        _section_label("Stocks P&L", ACCENT_GREEN)
        if not stk_closed.empty:
            grp_stk = stk_closed.copy()
            grp_stk["_pl_side"] = grp_stk["PL_Dollar"].fillna(0).apply(
                lambda v: "Gain" if v > 0 else ("Loss" if v < 0 else "Flat"))
            outcomes_stk = grp_stk["_pl_side"].value_counts().reset_index()
            outcomes_stk.columns = ["Side", "Count"]
            colors_stk = {"Gain": ACCENT_GREEN, "Loss": ACCENT_RED, "Flat": TEXT_MUTED}
            fig_sp = go.Figure(go.Pie(
                labels=outcomes_stk["Side"], values=outcomes_stk["Count"], hole=0.55,
                marker=dict(colors=[colors_stk.get(s, TEXT_MUTED) for s in outcomes_stk["Side"]],
                            line=dict(color=BG_DARK, width=2)),
                textfont=dict(color=TEXT_PRIMARY, size=11),
            ))
            fig_sp.update_layout(paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD, height=220,
                                  margin=dict(l=4, r=4, t=10, b=4),
                                  legend=dict(font=dict(color=TEXT_MUTED, size=10),
                                              bgcolor=BG_CARD, orientation="h", y=-0.15),
                                  showlegend=True)
            st.plotly_chart(fig_sp, width='stretch',
                            config={"displayModeBar": False}, key="perf_monthly_stk_pie")
        else:
            st.markdown(f'<div style="color:{TEXT_MUTED};font-size:11px;font-style:italic;'
                        f'padding:20px 0;text-align:center">No closed stocks this month</div>',
                        unsafe_allow_html=True)

    # ── Positions tables: Options then Stocks ──────────────────────
    opt_show = [c for c in _OPT_COLS if c in opt_m.columns]
    stk_show = [c for c in _STOCK_COLS if c in stock_m.columns]
    month_df2 = month_df.copy()
    if "Expiry_Date" in month_df2.columns:
        month_df2["Expiry_Date"] = (pd.to_datetime(month_df2["Expiry_Date"], errors="coerce")
                                    .dt.strftime("%Y-%m-%d"))

    if not opt_m.empty:
        with st.expander(f"**⚙️ Options Positions — {selected}** — {len(opt_m)} position(s)", expanded=True):
            _positions_table_html(
                month_df2[opt_mask].sort_values("Entry_Date", ascending=False),
                opt_show, context=f"monthly_opt_{selected}")

    if not stock_m.empty:
        with st.expander(f"**📊 Stock / GS Positions — {selected}** — {len(stock_m)} position(s)", expanded=True):
            _positions_table_html(
                month_df2[~opt_mask].sort_values("Entry_Date", ascending=False),
                stk_show, show_close_signal=True, context=f"monthly_stk_{selected}")

    # ── Top Gainers / Losers ───────────────────────────────────────
    by_tkr_m = (month_df.groupby("Ticker")["Income"].sum().reset_index()
                .sort_values("Income", ascending=False))

    def _bar(data, color, title):
        fig = go.Figure(go.Bar(
            x=data["Income"], y=data["Ticker"], orientation="h", marker_color=color,
            text=[f"${v:+,.0f}" for v in data["Income"]], textposition="outside",
            textfont=dict(color=TEXT_PRIMARY, size=11)))
        fig.update_layout(paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD,
                          height=max(150, 32*len(data)+40),
                          margin=dict(l=8, r=70, t=30, b=8),
                          title=dict(text=title, font=dict(color=color, size=12), x=0.01),
                          xaxis=dict(showgrid=True, gridcolor=BORDER_COLOR,
                                     color=TEXT_MUTED, tickprefix="$"),
                          yaxis=dict(showgrid=False, color=GOLD, autorange="reversed"),
                          showlegend=False)
        return fig

    cg, cl = st.columns(2)
    with cg:
        _section_label("🏆 Top Gainers", ACCENT_GREEN)
        if not by_tkr_m.empty:
            st.plotly_chart(_bar(by_tkr_m.head(5), ACCENT_GREEN, ""),
                            width='stretch', config={"displayModeBar": False},
                            key="perf_monthly_gainers")
    with cl:
        _section_label("📉 Top Losers", ACCENT_RED)
        losers = by_tkr_m[by_tkr_m["Income"] < 0].sort_values("Income").head(5)
        if not losers.empty:
            st.plotly_chart(_bar(losers, ACCENT_RED, ""),
                            width='stretch', config={"displayModeBar": False},
                            key="perf_monthly_losers")


def _render_analytics_tab(df: pd.DataFrame):
    _section_label("📊 Analytics — What Worked & What Didn't", GOLD)

    # Cumulative P&L
    fig = _chart_cumulative_pnl(df)
    if fig:
        st.markdown(f'<div style="color:{TEXT_MUTED};font-size:11px;margin-bottom:4px">Cumulative Realized Income Over Time</div>', unsafe_allow_html=True)
        st.plotly_chart(fig, width='stretch', config={"displayModeBar": False},
                        key="perf_analytics_cumulative")

    # Win rate + strategy mix
    c1, c2 = st.columns([3, 2])
    with c1:
        _section_label("Win Rate by Strategy", ACCENT_GREEN)
        df2 = df.copy(); df2["Win"] = df2["PL_Dollar"].fillna(0) > 0
        grp = df2.groupby("Strategy").agg(N=("Ticker","count"), Wins=("Win","sum")).reset_index()
        grp["Rate"] = (grp["Wins"]/grp["N"]*100).round(1)
        grp = grp.sort_values("Rate", ascending=False)
        colors = [ACCENT_GREEN if r>=60 else (GOLD if r>=40 else ACCENT_RED) for r in grp["Rate"]]
        fig2 = go.Figure(go.Bar(x=grp["Rate"], y=grp["Strategy"], orientation="h",
                                marker_color=colors,
                                text=[f"{r:.0f}%  ({w}/{n})" for r,w,n in zip(grp["Rate"],grp["Wins"],grp["N"])],
                                textposition="outside", textfont=dict(color=TEXT_PRIMARY, size=11)))
        fig2.update_layout(paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD, height=max(180, 40*len(grp)+40),
                           margin=dict(l=8, r=80, t=10, b=12),
                           xaxis=dict(showgrid=True, gridcolor=BORDER_COLOR, color=TEXT_MUTED, range=[0,115], ticksuffix="%"),
                           yaxis=dict(showgrid=False, color=GOLD, autorange="reversed", tickfont=dict(size=12, family="DM Mono", color=GOLD)),
                           showlegend=False)
        st.plotly_chart(fig2, width='stretch', config={"displayModeBar": False},
                        key="perf_analytics_winrate")
    with c2:
        _section_label("Strategy Mix", GOLD)
        fig3 = _chart_strategy_mix(df)
        if fig3:
            st.plotly_chart(fig3, width='stretch', config={"displayModeBar": False},
                            key="perf_analytics_strat_mix")

    # Top tickers + trade outcomes
    c3, c4 = st.columns([3, 2])
    with c3:
        _section_label("Top Income Tickers", GOLD)
        fig4 = _chart_top_tickers(df)
        if fig4:
            st.plotly_chart(fig4, width='stretch', config={"displayModeBar": False},
                            key="perf_analytics_top_tickers")
    with c4:
        _section_label("Trade Outcomes", ACCENT_BLUE)
        fig5 = _chart_trade_outcomes(df)
        if fig5:
            st.plotly_chart(fig5, width='stretch', config={"displayModeBar": False},
                            key="perf_analytics_outcomes")

    # What worked / what didn't
    df3 = df.copy(); df3["Win"] = df3["PL_Dollar"].fillna(0) > 0
    grp2 = df3.groupby(["Strategy","Universe"]).agg(N=("Ticker","count"), Wins=("Win","sum"),
               AvgPct=("PL_Pct","mean"), TotalInc=("Income","sum")).reset_index()
    grp2["Rate"] = (grp2["Wins"]/grp2["N"]*100).round(1)
    worked = grp2[(grp2["N"]>=2) & (grp2["Rate"]>=55)].sort_values("Rate", ascending=False)
    didnt  = grp2[(grp2["N"]>=2) & (grp2["Rate"]<45)].sort_values("Rate")

    def _list(rows, title, color, empty):
        _section_label(title, color)
        if rows.empty:
            st.markdown(f'<div style="color:{TEXT_MUTED};font-size:11px;font-style:italic;background:{BG_PANEL};border:1px dashed {BORDER_COLOR};border-radius:6px;padding:14px;text-align:center">{empty}</div>', unsafe_allow_html=True)
            return
        for _, r in rows.head(6).iterrows():
            avg = r["AvgPct"] or 0; inc = r["TotalInc"]
            st.markdown(f'<div style="display:flex;justify-content:space-between;align-items:center;padding:10px 14px;background:{BG_CARD};border:1px solid {BORDER_COLOR};border-left:3px solid {color};border-radius:4px;margin-bottom:4px">'
                        f'<div><div style="color:{TEXT_PRIMARY};font-size:13px;font-weight:600">{r["Strategy"]} — {r["Universe"]}</div>'
                        f'<div style="color:{TEXT_MUTED};font-size:10px">{int(r["N"])} trades · avg {avg:+.1f}% · income ${inc:,.0f}</div></div>'
                        f'<div style="text-align:right"><div style="color:{color};font-family:\'Cormorant Garamond\',serif;font-weight:800;font-size:20px">{r["Rate"]:.0f}%</div>'
                        f'<div style="color:{TEXT_MUTED};font-size:10px">win rate</div></div></div>', unsafe_allow_html=True)

    cw, cd = st.columns(2)
    with cw: _list(worked, "✅ What Worked",       ACCENT_GREEN, "Need ≥ 2 positions per group at 55%+ win rate.")
    with cd: _list(didnt,  "❌ What Didn't Work",   ACCENT_RED,   "Nothing below 45% win rate yet — keep trading!")

    # Fuzzy Close Signal for open stocks
    open_stocks = df[(df["Status"].str.lower()=="open") & (df["Strategy"].str.upper().isin(_STOCK_STRATS))].copy()
    if not open_stocks.empty:
        _section_label("🔮 Fuzzy Close Signals — Open Stock Positions", "#A78BFA")
        st.markdown(f'<div style="color:{TEXT_MUTED};font-size:11px;margin-bottom:10px">'
                    f'Composite signal (0–100) from RSI, SMA-50 trend, % gain/loss, hold time. '
                    f'🟢 0–30 Hold &nbsp;|&nbsp; 🟡 31–60 Consider Closing &nbsp;|&nbsp; 🔴 61+ Close Signal</div>',
                    unsafe_allow_html=True)
        tickers_open = tuple(open_stocks["Ticker"].unique().tolist())
        prices = _current_prices(tickers_open)
        rows_sig = []
        for _, r in open_stocks.iterrows():
            cp = prices.get(str(r.get("Ticker","")).upper())
            sc, label, color = _fuzzy_close_signal(r.to_dict(), cp)
            entry = float(r.get("Entry_Stock_Price", 0) or 0)
            chg   = f"{((cp-entry)/entry*100):+.1f}%" if cp and entry > 0 else "—"
            hold  = ""
            try:
                ed   = datetime.strptime(str(r.get("Entry_Date",""))[:10], "%Y-%m-%d").date()
                hold = f"{(date.today()-ed).days}d"
            except Exception:
                pass
            rows_sig.append({"Ticker": r["Ticker"], "Strategy": r.get("Strategy",""),
                              "Entry": f"${entry:.2f}", "Current": f"${cp:.2f}" if cp else "—",
                              "Change": chg, "Hold": hold, "Signal": label, "_color": color, "_score": sc})

        rows_sig.sort(key=lambda x: -x["_score"])
        th_s2 = (f'color:{TEXT_MUTED};font-size:10px;font-weight:700;letter-spacing:.8px;'
                 f'text-transform:uppercase;padding:8px 10px;border-bottom:1px solid {BORDER_COLOR};background:{BG_PANEL}')
        hdr2  = "".join(f'<th style="{th_s2}">{h}</th>' for h in ["TICKER","STRATEGY","ENTRY","CURRENT","CHANGE","HOLD","SIGNAL"])
        rows2 = []
        for i, r in enumerate(rows_sig):
            bg = BG_CARD if i % 2 == 0 else BG_PANEL
            chg_col = ACCENT_GREEN if "+" in str(r["Change"]) else ACCENT_RED
            rows2.append(f'<tr>'
                         f'<td style="padding:7px 10px;background:{bg};color:{GOLD};font-family:\'DM Mono\',monospace;font-weight:700">{r["Ticker"]}</td>'
                         f'<td style="padding:7px 10px;background:{bg};color:{TEXT_PRIMARY}">{r["Strategy"]}</td>'
                         f'<td style="padding:7px 10px;background:{bg};color:{TEXT_MUTED};font-family:\'DM Mono\',monospace">{r["Entry"]}</td>'
                         f'<td style="padding:7px 10px;background:{bg};color:{TEXT_PRIMARY};font-family:\'DM Mono\',monospace">{r["Current"]}</td>'
                         f'<td style="padding:7px 10px;background:{bg};color:{chg_col};font-family:\'DM Mono\',monospace;font-weight:600">{r["Change"]}</td>'
                         f'<td style="padding:7px 10px;background:{bg};color:{TEXT_MUTED}">{r["Hold"]}</td>'
                         f'<td style="padding:7px 10px;background:{bg}"><span style="color:{r["_color"]};font-size:10px;font-weight:700;background:{r["_color"]}22;padding:2px 8px;border-radius:10px;border:1px solid {r["_color"]}55">{r["Signal"]} ({r["_score"]})</span></td>'
                         f'</tr>')
        st.markdown(f'<div style="border:1px solid {BORDER_COLOR};border-radius:8px;overflow:hidden;overflow-x:auto;margin-bottom:12px">'
                    f'<table style="width:100%;border-collapse:collapse;font-family:\'Inter\',sans-serif">'
                    f'<thead><tr>{hdr2}</tr></thead><tbody>{"".join(rows2)}</tbody></table></div>',
                    unsafe_allow_html=True)

    # Parameter optimization suggestions
    _section_label("💡 Parameter Optimization Suggestions", ACCENT_BLUE)
    suggestions = []
    for strat_key, strat_label in [("CSP","CSP"), ("CC","CC"), ("LEAPS","LEAPS")]:
        sub_s = df[df["Strategy"]==strat_key].copy()
        if len(sub_s) < 2:
            continue
        sub_s["Win"] = sub_s["PL_Dollar"].fillna(0) > 0
        wr_s = sub_s["Win"].mean() * 100
        if strat_key == "CSP":
            if wr_s < 50:
                suggestions.append((strat_label, f"Win rate {wr_s:.0f}% — lower delta to 0.15–0.20 for higher-probability OTM strikes.", ACCENT_RED))
            elif wr_s > 75:
                suggestions.append((strat_label, f"Win rate {wr_s:.0f}% — consider higher delta (0.25–0.30) to collect more premium.", ACCENT_GREEN))
        elif strat_key == "CC":
            if wr_s < 50:
                suggestions.append((strat_label, f"Win rate {wr_s:.0f}% — underlying trending up. Avoid CC in strong bull; lower delta or skip.", ACCENT_RED))
        elif strat_key == "LEAPS":
            if wr_s < 40:
                suggestions.append((strat_label, f"Win rate {wr_s:.0f}% — check IV rank at entry (<30 ideal). High IV = expensive calls.", ACCENT_RED))

    # Sector rotation
    sector_map = {"XLK":"Tech","XLF":"Finance","XLE":"Energy","XLV":"Health","XLI":"Industrial",
                  "XLU":"Utilities","XLP":"Consumer Staples","XLY":"Consumer Disc.",
                  "GLD":"Gold","SLV":"Silver","TLT":"Bonds","QQQ":"Tech","SPY":"Broad Market"}
    df_sec = df.copy()
    df_sec["Sector"] = df_sec["Ticker"].map(sector_map).fillna("Individual Stocks")
    sec_grp = df_sec.groupby("Sector").agg(N=("Ticker","count"), Inc=("Income","sum")).reset_index().sort_values("Inc", ascending=False)
    if not sec_grp.empty:
        best = sec_grp.iloc[0]
        worst = sec_grp.iloc[-1] if len(sec_grp) > 1 else None
        suggestions.append(("Sector", f"Best sector: {best['Sector']} (${best['Inc']:,.0f}, {int(best['N'])} trades). Favor it in next scan.", ACCENT_GREEN))
        if worst is not None and worst["Inc"] < 0:
            suggestions.append(("Sector", f"Underperformer: {worst['Sector']} (${worst['Inc']:,.0f}). Pause until sector trend reverses.", ACCENT_RED))

    if not suggestions:
        suggestions.append(("General", "Keep trading! Need 10+ trades per strategy for meaningful optimization.", GOLD))

    for strat_n, msg, color in suggestions:
        st.markdown(f'<div style="display:flex;gap:12px;align-items:flex-start;padding:10px 14px;background:{BG_CARD};border:1px solid {BORDER_COLOR};border-left:3px solid {color};border-radius:4px;margin-bottom:6px">'
                    f'<div style="color:{color};font-size:10px;font-weight:800;min-width:80px;text-transform:uppercase;letter-spacing:.5px;padding-top:1px">{strat_n}</div>'
                    f'<div style="color:{TEXT_PRIMARY};font-size:12px">{msg}</div></div>', unsafe_allow_html=True)

    _render_ticker_snapshot(df)


# ══════════════════════════════════════════════════════════════════
# 9. MAIN RENDER
# ══════════════════════════════════════════════════════════════════

def render():
    section_header("📈", "Performance Dashboard",
                   "Wheel options + stocks · Add positions · Auto-closes on expiry · Fuzzy close signals for stocks")

    storage = "Google Sheets ✓" if using_google_sheets() else "Local CSV (data/performance.csv)"
    ci, cr  = st.columns([4, 1])
    with ci:
        st.markdown(f'<div style="color:{TEXT_MUTED};font-size:11px;margin-bottom:4px">'
                    f'Storage: <b style="color:{GOLD}">{storage}</b> · '
                    f'Options auto-close on expiry · Stocks use fuzzy close signals</div>',
                    unsafe_allow_html=True)
    with cr:
        if st.button("🔄 Refresh", use_container_width=True, key="perf_refresh"):
            st.cache_data.clear()
            st.rerun()

    # ── Add Position form (always available) ─────────────────────
    _render_add_position_form()

    df = _load_and_process()

    if df.empty:
        st.markdown(f"""
        <div style="background:{BG_PANEL};border:1px dashed {BORDER_COLOR};border-radius:10px;
                    padding:50px 20px;text-align:center;color:{TEXT_MUTED}">
          <div style="font-size:48px;margin-bottom:16px">📈</div>
          <div style="font-size:18px;color:{TEXT_PRIMARY};margin-bottom:8px">No Performance Data Yet</div>
          <div style="font-size:13px">Use the <b style="color:{GOLD}">➕ Add Position Manually</b> form above,<br>
          or click <b style="color:{GOLD}">📌 Track</b> on any CSP / CC / LEAPS scanner result.</div>
        </div>""", unsafe_allow_html=True)
        return

    # ── Strategy filter ──────────────────────────────────────────
    raw_strats = df["Strategy"].dropna().unique().tolist()
    # "Stocks" groups all stock-type strategies together
    has_stocks = any(s.upper() in _STOCK_STRATS for s in raw_strats)
    opt_strats = sorted(s for s in raw_strats if s.upper() not in _STOCK_STRATS)
    all_strats = ["All"] + opt_strats + (["Stocks"] if has_stocks else [])
    sel        = st.selectbox("Filter by Strategy", all_strats, index=0, key="perf_strat_filter")
    if sel == "Stocks":
        df = df[df["Strategy"].str.upper().isin(_STOCK_STRATS)]
    elif sel != "All":
        df = df[df["Strategy"] == sel]
    if df.empty:
        st.info(f"No positions for strategy: {sel}")
        return

    # ── Progress KPIs (always visible) ──────────────────────────
    _render_progress_strip(df)
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── Tab styling ──────────────────────────────────────────────
    st.markdown(f"""<style>
    .stTabs [data-baseweb="tab-list"] {{
        background:linear-gradient(180deg,{BG_PANEL},{BG_DARK}) !important;
        border:1px solid {BORDER_COLOR} !important;border-radius:10px !important;
        padding:6px !important;gap:4px !important;
        box-shadow:0 4px 12px rgba(0,0,0,.5) !important;margin-bottom:18px !important;}}
    .stTabs [data-baseweb="tab"] {{
        height:44px !important;padding:0 22px !important;font-size:14px !important;
        font-weight:700 !important;letter-spacing:.5px !important;color:{TEXT_MUTED} !important;
        background:linear-gradient(180deg,{BG_CARD},#0c0c12) !important;
        border:1px solid {BORDER_COLOR} !important;border-radius:8px !important;}}
    .stTabs [aria-selected="true"] {{
        color:{BG_DARK} !important;
        background:linear-gradient(180deg,#FFE07A,{GOLD} 45%,{GOLD_DARK}) !important;
        border-color:{GOLD_DARK} !important;font-weight:800 !important;
        box-shadow:0 6px 18px rgba(245,200,66,.45) !important;}}
    .stTabs [data-baseweb="tab-highlight"],
    .stTabs [data-baseweb="tab-border"] {{display:none !important;}}
    </style>""", unsafe_allow_html=True)

    tab_d, tab_m, tab_a = st.tabs(["📅  DAILY", "📆  MONTHLY", "📊  ANALYTICS"])
    with tab_d: _render_daily_tab(df)
    with tab_m: _render_monthly_tab(df)
    with tab_a: _render_analytics_tab(df)

    st.markdown(f'<div style="margin-top:24px;color:{TEXT_MUTED};font-size:10px;text-align:center">'
                f'Open P&L is mark-to-market (intrinsic value only). Options auto-close on expiry. '
                f'Stock close signals are advisory only — not financial advice.</div>',
                unsafe_allow_html=True)
