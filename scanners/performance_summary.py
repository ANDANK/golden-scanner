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
        premium     = float(r.get("Premium", 0) or 0)
        strike      = float(r.get("Strike",  0) or 0)
        entry_stock = float(r.get("Entry_Stock_Price", 0) or 0)
        qty         = int(r.get("Qty", 1) or 1)
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
    raw = get_performance()
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
                pl, pl_pct = _mark_to_market(
                    str(row.get("Strategy","")),
                    float(row.get("Premium",0) or 0),
                    float(row.get("Strike",0)  or 0),
                    float(row.get("Entry_Stock_Price",0) or 0),
                    cp, int(row.get("Qty",1) or 1),
                )
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
            p = float(row.get("Premium",0) or 0)
            q = int(row.get("Qty",1) or 1)
            return round(p * 100 * q, 2)
        return float(row.get("PL_Dollar",0) or 0)

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
    if st.button(f"✖ Close", key=key, use_container_width=True,
                 help=f"Mark {ticker} as closed at today's price"):
        cp = _current_prices((ticker,)).get(ticker)
        if cp is None:
            st.warning("Could not fetch current price. Try again.")
            return
        strat  = str(row.get("Strategy","")).upper()
        try:
            pl, pl_pct = _calc_pl(
                strat,
                float(row.get("Premium",0) or 0),
                float(row.get("Strike",0) or 0),
                float(row.get("Entry_Stock_Price",0) or 0),
                cp, int(row.get("Qty",1) or 1),
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
        color = ACCENT_GREEN if v >= 0 else ACCENT_RED
        return f'<span style="color:{color};font-family:\'DM Mono\',monospace;font-weight:700">{"+" if v>=0 else ""}${v:,.2f}</span>'
    except Exception:
        return f'<span style="color:{TEXT_MUTED}">—</span>'


def _positions_table_html(df: pd.DataFrame, cols: list, show_close_signal: bool = False,
                          context: str = ""):
    """Rich HTML positions table with optional fuzzy close signal column."""
    if df.empty:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:12px;font-style:italic;'
            f'padding:16px;text-align:center;border:1px dashed {BORDER_COLOR};'
            f'border-radius:6px">No positions in this period.</div>',
            unsafe_allow_html=True,
        )
        return

    display_cols = cols + (["Close Signal"] if show_close_signal else []) + ["Action"]
    th_style = (f'color:{TEXT_MUTED};font-size:10px;font-weight:700;letter-spacing:0.8px;'
                f'text-transform:uppercase;padding:8px 10px;border-bottom:1px solid {BORDER_COLOR};'
                f'background:{BG_PANEL};white-space:nowrap')
    header_html = "".join(f'<th style="{th_style}">{c}</th>' for c in display_cols)

    rows_html = []
    for i, (ridx, r) in enumerate(df.iterrows()):
        bg     = BG_CARD if i % 2 == 0 else BG_PANEL
        cells  = []
        cp     = r.get("Current_Price")
        is_open = str(r.get("Status","")).lower() == "open"

        for c in cols:
            val   = r.get(c, "")
            style = f'padding:7px 10px;font-size:11px;background:{bg}'
            val_s = str(val) if val is not None and str(val) != "nan" else "—"

            if c == "Ticker":
                cells.append(f'<td style="{style};color:{GOLD};font-family:\'DM Mono\',monospace;font-weight:700;font-size:12px">{val_s}</td>')
            elif c in ("PL_Dollar","P/L $","Income"):
                cells.append(f'<td style="{style}">{_pl_html(val)}</td>')
            elif c in ("PL_Pct","P/L %"):
                try:
                    v = float(val)
                    col = ACCENT_GREEN if v >= 0 else ACCENT_RED
                    cells.append(f'<td style="{style};color:{col};font-family:\'DM Mono\',monospace;font-weight:600">{v:+.1f}%</td>')
                except Exception:
                    cells.append(f'<td style="{style};color:{TEXT_MUTED}">—</td>')
            elif c == "Status":
                cells.append(f'<td style="{style}">{_status_badge(val_s)}</td>')
            elif c == "Strategy":
                sc = {"CSP":"#86EFAC","CC":GOLD,"LEAPS":"#60A5FA","Golden Scan":"#A78BFA"}.get(val_s, TEXT_MUTED)
                cells.append(f'<td style="{style};color:{sc};font-weight:600">{val_s}</td>')
            elif c == "Premium":
                try:
                    cells.append(f'<td style="{style};color:{ACCENT_GREEN};font-family:\'DM Mono\',monospace">${float(val):.2f}</td>')
                except Exception:
                    cells.append(f'<td style="{style};color:{TEXT_MUTED}">—</td>')
            elif c == "Current_Price":
                try:
                    cells.append(f'<td style="{style};color:{TEXT_PRIMARY};font-family:\'DM Mono\',monospace">${float(val):.2f}</td>')
                except Exception:
                    cells.append(f'<td style="{style};color:{TEXT_MUTED}">—</td>')
            elif c == "Expiry_Date":
                exp = val_s[:10] if val_s != "—" else "—"
                cells.append(f'<td style="{style};color:{TEXT_MUTED}">{exp}</td>')
            else:
                cells.append(f'<td style="{style};color:{TEXT_PRIMARY}">{val_s}</td>')

        # ── Fuzzy close signal (stocks only) ─────────────────────
        if show_close_signal:
            strat = str(r.get("Strategy","")).upper()
            if strat in _STOCK_STRATS and is_open:
                sig_score, sig_label, sig_color = _fuzzy_close_signal(r.to_dict(), cp)
                cells.append(
                    f'<td style="padding:7px 10px;background:{bg}">'
                    f'<span style="color:{sig_color};font-size:10px;font-weight:700;'
                    f'background:{sig_color}22;padding:2px 8px;border-radius:10px;'
                    f'border:1px solid {sig_color}55">{sig_label} ({sig_score})</span></td>'
                )
            else:
                cells.append(f'<td style="padding:7px 10px;background:{bg};color:{TEXT_MUTED};font-size:10px">—</td>')

        # ── Action placeholder (Close button rendered separately) ─
        cells.append(f'<td style="padding:7px 10px;background:{bg};color:{TEXT_MUTED};font-size:10px">'
                     f'{"✖" if is_open else "✓"}</td>')

        rows_html.append(f'<tr>{"".join(cells)}</tr>')

    st.markdown(f"""
    <div style="border:1px solid {BORDER_COLOR};border-radius:8px;overflow:hidden;overflow-x:auto;margin-bottom:8px">
      <table style="width:100%;border-collapse:collapse;font-family:'Inter',sans-serif">
        <thead><tr>{header_html}</tr></thead>
        <tbody>{"".join(rows_html)}</tbody>
      </table>
    </div>""", unsafe_allow_html=True)

    # ── Close buttons (Streamlit widgets — rendered below table) ─
    open_rows = [(i, ridx, r) for i, (ridx, r) in enumerate(df.iterrows())
                 if str(r.get("Status","")).lower() == "open"]
    if open_rows:
        st.markdown(f'<div style="color:{TEXT_MUTED};font-size:10px;margin-bottom:4px">Close open positions at today\'s price:</div>', unsafe_allow_html=True)
        btn_cols = st.columns(min(len(open_rows), 6))
        for j, (i, ridx, r) in enumerate(open_rows):
            with btn_cols[j % 6]:
                _render_close_button(r.to_dict(), ridx + 2, context=context)


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
    closed     = df[df["Status"].str.lower().isin(["expired","closed","assigned","called"])]
    income_ytd = closed["Income"].sum()
    total      = len(df)
    wins       = (df["PL_Dollar"].fillna(0) > 0).sum()
    win_rate   = wins / total * 100 if total else 0
    avg_roi    = closed["PL_Pct"].dropna().mean() if not closed.empty else 0
    if not df["Entry_Date"].dropna().empty:
        days_active  = max(1, (date.today() - df["Entry_Date"].dropna().min().date()).days)
        avg_prem_day = income_ytd / days_active
    else:
        avg_prem_day = 0

    _section_label("🎯 Wheel Strategy Progress", GOLD)
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: _kpi("Income YTD",      f"${income_ytd:,.2f}",  color=ACCENT_GREEN if income_ytd>=0 else ACCENT_RED)
    with c2: _kpi("Total Trades",    str(total),              color=GOLD)
    with c3: _kpi("Win Rate",        f"{win_rate:.1f}%",
                  sub=f"{int(wins)} of {total}",
                  color=ACCENT_GREEN if win_rate>=60 else (GOLD if win_rate>=40 else ACCENT_RED))
    with c4: _kpi("Avg ROI/Trade",   f"{avg_roi:+.2f}%",     color=ACCENT_BLUE)
    with c5: _kpi("Avg Premium/Day", f"${avg_prem_day:,.2f}", color=GOLD)


def _render_ticker_snapshot(df: pd.DataFrame):
    _section_label("📋 Ticker Performance Snapshot", GOLD)
    by_tkr = (df.groupby("Ticker").agg(
        Total_Income=("Income","sum"),
        Trades=("Ticker","count"),
        Avg_ROI=("PL_Pct","mean"),
        Wins=("PL_Dollar", lambda x: (pd.to_numeric(x, errors="coerce").fillna(0) > 0).sum()),
    ).reset_index().sort_values("Total_Income", ascending=False))
    if by_tkr.empty:
        return

    def _ppd(tkr):
        sub  = df[df["Ticker"] == tkr]
        days = max(1, (date.today() - sub["Entry_Date"].dropna().min().date()).days) if not sub["Entry_Date"].dropna().empty else 1
        return sub["Income"].sum() / days

    by_tkr["Prem_Per_Day"] = by_tkr["Ticker"].apply(_ppd)
    by_tkr["Win_Rate"]     = (by_tkr["Wins"] / by_tkr["Trades"] * 100).round(1)

    th_s = (f'color:{TEXT_MUTED};font-size:10px;font-weight:700;letter-spacing:.8px;'
            f'text-transform:uppercase;padding:8px 12px;border-bottom:2px solid {GOLD}55;background:{BG_PANEL}')
    hdrs = ["TICKER","TOTAL INCOME","TRADES","WIN RATE","AVG ROI","PREM/DAY"]
    hdr  = "".join(f'<th style="{th_s}">{h}</th>' for h in hdrs)
    rows = []
    for i, (_, r) in enumerate(by_tkr.iterrows()):
        bg = BG_CARD if i % 2 == 0 else BG_PANEL
        inc = r["Total_Income"]; roi = r["Avg_ROI"] or 0; wr = r["Win_Rate"]; ppd = r["Prem_Per_Day"]
        ic  = ACCENT_GREEN if inc>=0 else ACCENT_RED
        rc  = ACCENT_GREEN if roi>=0 else ACCENT_RED
        wc  = ACCENT_GREEN if wr>=60 else (GOLD if wr>=40 else ACCENT_RED)
        rows.append(f'<tr>'
                    f'<td style="padding:8px 12px;background:{bg};color:{GOLD};font-family:\'DM Mono\',monospace;font-weight:800;font-size:13px">{r["Ticker"]}</td>'
                    f'<td style="padding:8px 12px;background:{bg};color:{ic};font-family:\'DM Mono\',monospace;font-weight:700">{"+" if inc>=0 else ""}${inc:,.2f}</td>'
                    f'<td style="padding:8px 12px;background:{bg};color:{TEXT_PRIMARY};text-align:center">{int(r["Trades"])}</td>'
                    f'<td style="padding:8px 12px;background:{bg};color:{wc};font-weight:700">{wr:.0f}%</td>'
                    f'<td style="padding:8px 12px;background:{bg};color:{rc};font-family:\'DM Mono\',monospace">{roi:+.2f}%</td>'
                    f'<td style="padding:8px 12px;background:{bg};color:{ACCENT_BLUE};font-family:\'DM Mono\',monospace">${ppd:,.2f}</td>'
                    f'</tr>')
    total_inc = by_tkr["Total_Income"].sum(); tc = ACCENT_GREEN if total_inc>=0 else ACCENT_RED
    footer = (f'<tr style="border-top:2px solid {GOLD}55">'
              f'<td style="padding:8px 12px;background:{BG_PANEL};color:{GOLD};font-weight:800;font-family:\'DM Mono\',monospace">TOTAL</td>'
              f'<td style="padding:8px 12px;background:{BG_PANEL};color:{tc};font-weight:800;font-family:\'DM Mono\',monospace">${total_inc:,.2f}</td>'
              f'<td style="padding:8px 12px;background:{BG_PANEL};color:{TEXT_PRIMARY};text-align:center;font-weight:700">{int(by_tkr["Trades"].sum())}</td>'
              f'<td colspan="3" style="padding:8px 12px;background:{BG_PANEL}"></td>'
              f'</tr>')
    st.markdown(f'<div style="border:1px solid {BORDER_COLOR};border-radius:8px;overflow:hidden;overflow-x:auto;margin:8px 0 20px">'
                f'<table style="width:100%;border-collapse:collapse;font-family:\'Inter\',sans-serif">'
                f'<thead><tr>{hdr}</tr></thead><tbody>{"".join(rows)}{footer}</tbody></table></div>',
                unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# 8. TAB RENDERERS
# ══════════════════════════════════════════════════════════════════

_OPT_COLS   = ["Ticker","Strategy","Universe","Strike","Premium","DTE","Expiry_Date",
               "Entry_Stock_Price","Current_Price","Status","PL_Dollar","PL_Pct"]
_STOCK_COLS = ["Ticker","Strategy","Entry_Stock_Price","Current_Price","Status",
               "PL_Dollar","PL_Pct","Source","Score"]


def _render_daily_tab(df: pd.DataFrame):
    today = date.today()
    st.markdown(f'<div style="color:{TEXT_MUTED};font-size:11px;letter-spacing:1.5px;text-transform:uppercase;margin:8px 0 14px">Trading Day · {today.strftime("%A %b %d, %Y")}</div>', unsafe_allow_html=True)
    _render_top_cards(df, today)

    for strat, label_text, color in [
        ("CSP",         "💰 Cash-Secured Puts (CSP)",  GOLD),
        ("CC",          "📦 Covered Calls (CC)",        "#A78BFA"),
        ("LEAPS",       "🧨 LEAPS",                    "#60A5FA"),
        ("Golden Scan", "📊 Stocks / Golden Scan",      ACCENT_GREEN),
    ]:
        sub = df[df["Strategy"] == strat].copy()
        if sub.empty:
            continue
        _section_label(f"{label_text} — {len(sub)} position(s)", color)
        is_stock = strat.upper() in _STOCK_STRATS
        show_cols = _STOCK_COLS if is_stock else [c for c in _OPT_COLS if c in sub.columns]
        show_cols = [c for c in show_cols if c in sub.columns]
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

    closed_m  = month_df[month_df["Status"].str.lower().isin(["expired","closed","assigned","called"])]
    income_m  = closed_m["Income"].sum()
    trades_m  = len(month_df)
    wins_m    = (month_df["PL_Dollar"].fillna(0) > 0).sum()
    wr_m      = wins_m / trades_m * 100 if trades_m else 0
    open_m    = month_df[month_df["Status"].str.lower() == "open"]

    c1, c2, c3, c4 = st.columns(4)
    with c1: _kpi("Income",         f"${income_m:,.2f}", color=ACCENT_GREEN if income_m>=0 else ACCENT_RED)
    with c2: _kpi("Trades",         str(trades_m),       color=GOLD)
    with c3: _kpi("Win Rate",       f"{wr_m:.0f}%",      sub=f"{int(wins_m)}/{trades_m}",
                  color=ACCENT_GREEN if wr_m>=60 else (GOLD if wr_m>=40 else ACCENT_RED))
    with c4: _kpi("Open Positions", str(len(open_m)),    color=ACCENT_BLUE)
    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    fa, fb = st.columns([3, 2])
    with fa:
        fig = _chart_monthly_income(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    with fb:
        fig = _chart_trade_outcomes(month_df)
        if fig:
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    _section_label(f"All Positions — {selected}", GOLD)
    show_cols = [c for c in ["Ticker","Strategy","Universe","Strike","Premium","DTE",
                              "Expiry_Date","Entry_Stock_Price","Current_Price","Status",
                              "PL_Dollar","PL_Pct","Source"] if c in month_df.columns]
    month_df2 = month_df.copy()
    if "Expiry_Date" in month_df2.columns:
        month_df2["Expiry_Date"] = pd.to_datetime(month_df2["Expiry_Date"], errors="coerce").dt.strftime("%Y-%m-%d")
    _positions_table_html(month_df2.sort_values("Entry_Date", ascending=False), show_cols,
                          context=f"monthly_{selected}")

    cg, cl = st.columns(2)
    by_tkr_m = df[df["Month"]==selected].groupby("Ticker")["Income"].sum().reset_index().sort_values("Income", ascending=False)
    def _bar(data, color, title):
        fig = go.Figure(go.Bar(x=data["Income"], y=data["Ticker"], orientation="h",
                               marker_color=color, text=[f"${v:+,.0f}" for v in data["Income"]],
                               textposition="outside", textfont=dict(color=TEXT_PRIMARY, size=11)))
        fig.update_layout(paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD,
                          height=max(150, 32*len(data)+40), margin=dict(l=8, r=70, t=30, b=8),
                          title=dict(text=title, font=dict(color=color, size=12), x=0.01),
                          xaxis=dict(showgrid=True, gridcolor=BORDER_COLOR, color=TEXT_MUTED, tickprefix="$"),
                          yaxis=dict(showgrid=False, color=GOLD, autorange="reversed"), showlegend=False)
        return fig
    with cg:
        _section_label("🏆 Top Gainers", ACCENT_GREEN)
        if not by_tkr_m.empty:
            st.plotly_chart(_bar(by_tkr_m.head(5), ACCENT_GREEN, ""), use_container_width=True, config={"displayModeBar": False})
    with cl:
        _section_label("📉 Top Losers", ACCENT_RED)
        losers = by_tkr_m[by_tkr_m["Income"] < 0].sort_values("Income").head(5)
        if not losers.empty:
            st.plotly_chart(_bar(losers, ACCENT_RED, ""), use_container_width=True, config={"displayModeBar": False})


def _render_analytics_tab(df: pd.DataFrame):
    _section_label("📊 Analytics — What Worked & What Didn't", GOLD)

    # Cumulative P&L
    fig = _chart_cumulative_pnl(df)
    if fig:
        st.markdown(f'<div style="color:{TEXT_MUTED};font-size:11px;margin-bottom:4px">Cumulative Realized Income Over Time</div>', unsafe_allow_html=True)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

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
        st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})
    with c2:
        _section_label("Strategy Mix", GOLD)
        fig3 = _chart_strategy_mix(df)
        if fig3:
            st.plotly_chart(fig3, use_container_width=True, config={"displayModeBar": False})

    # Top tickers + trade outcomes
    c3, c4 = st.columns([3, 2])
    with c3:
        _section_label("Top Income Tickers", GOLD)
        fig4 = _chart_top_tickers(df)
        if fig4:
            st.plotly_chart(fig4, use_container_width=True, config={"displayModeBar": False})
    with c4:
        _section_label("Trade Outcomes", ACCENT_BLUE)
        fig5 = _chart_trade_outcomes(df)
        if fig5:
            st.plotly_chart(fig5, use_container_width=True, config={"displayModeBar": False})

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
    all_strats = ["All"] + sorted(df["Strategy"].dropna().unique().tolist())
    sel        = st.selectbox("Filter by Strategy", all_strats, index=0, key="perf_strat_filter")
    if sel != "All":
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
