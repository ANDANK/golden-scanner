# utils.py — Technical Indicators, Scoring, UI Helpers

import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
from config import *


# ── Export filename helper ─────────────────────────────────────

def _cst_timestamp() -> str:
    """Current time in CST/CDT as YYYY-MM-DD-HH-MM-SS string."""
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime as _dt
        return _dt.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d-%H-%M-%S")
    except Exception:
        from datetime import datetime as _dt
        return _dt.now().strftime("%Y-%m-%d-%H-%M-%S")


def _export_filename(base: str) -> str:
    """Return base_YYYY-MM-DD-HH-MM-SS.csv (CST timestamped)."""
    return f"{base}_{_cst_timestamp()}.csv"


# ── Technical Indicators ───────────────────────────────────────

def calc_sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=1).mean()


def calc_ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False).mean()


def calc_rsi(series: pd.Series, period: int = 14) -> float:
    """Return latest RSI value using Wilder's smoothing (industry standard)."""
    if len(series) < period + 1:
        return 50.0
    delta = series.diff().dropna()
    gain = delta.clip(lower=0)
    loss = (-delta.clip(upper=0))
    # Wilder's EMA: alpha = 1/period
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    val = rsi.dropna()
    return float(val.iloc[-1]) if not val.empty else 50.0


def calc_macd(series: pd.Series) -> tuple:
    """Return (macd_line, signal_line, histogram, prev_histogram) as floats.

    Interpretation guide:
      hist > 0                          → MACD line crossed above signal (bullish)
      hist > 0  AND  hist > prev_hist   → confirmed bullish: histogram growing
                                           momentum is building, not fading
      hist[-2] <= 0 AND hist > 0        → fresh bullish crossover (just happened)
      hist > 0  AND  hist < prev_hist   → bullish but histogram shrinking —
                                           momentum decelerating, potential reversal
    """
    if len(series) < 26:
        return 0.0, 0.0, 0.0, 0.0
    ema12 = calc_ema(series, 12)
    ema26 = calc_ema(series, 26)
    macd = ema12 - ema26
    signal = calc_ema(macd, 9)
    hist = macd - signal
    valid = hist.dropna()
    prev_h = float(valid.iloc[-2]) if len(valid) >= 2 else 0.0
    return float(macd.iloc[-1]), float(signal.iloc[-1]), float(hist.iloc[-1]), prev_h


def calc_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Return latest ATR as % of close."""
    if df.empty or len(df) < period + 1:
        return 0.0
    high = df["High"]
    low  = df["Low"]
    close = df["Close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    pct = (atr / close.iloc[-1]) * 100
    return round(float(pct), 2)


def is_above_sma(close: pd.Series, window: int) -> bool:
    sma = calc_sma(close, window)
    if sma.empty:
        return False
    return float(close.iloc[-1]) > float(sma.iloc[-1])


def is_20d_high(close: pd.Series) -> bool:
    if len(close) < 20:
        return False
    return float(close.iloc[-1]) >= float(close.iloc[-20:].max())


def calc_relative_strength(close: pd.Series, bench: pd.Series) -> float:
    """RS = (ticker return) / (benchmark return) over lookback."""
    try:
        n = min(len(close), len(bench), 63)
        t_ret = (float(close.iloc[-1]) / float(close.iloc[-n])) if float(close.iloc[-n]) else 1
        b_ret = (float(bench.iloc[-1]) / float(bench.iloc[-n])) if float(bench.iloc[-n]) else 1
        return round(t_ret / b_ret, 3)
    except Exception:
        return 1.0


def atr_expanding(df: pd.DataFrame) -> bool:
    """True if current ATR > 20-day avg ATR."""
    if len(df) < 25:
        return False
    high = df["High"]; low = df["Low"]; close = df["Close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().dropna()
    if len(atr) < 10:
        return False
    return float(atr.iloc[-1]) > float(atr.iloc[-20:].mean())


# ── Signal Scoring ─────────────────────────────────────────────

def compute_momentum_score(price: float, sma50: float, sma200: float,
                            rsi: float, macd_hist: float, vol_ratio: float,
                            is_20dh: bool, rs: float) -> int:
    score = 0
    # Trend alignment (30 pts)
    if price > sma50 > sma200:
        score += 30
    elif price > sma50:
        score += 15
    # RSI in sweet spot (20 pts)
    if 55 <= rsi <= 68:
        score += 20
    elif 50 <= rsi < 55 or 68 < rsi <= 72:
        score += 10
    # MACD (20 pts)
    if macd_hist > 0:
        score += 20
    # Volume (15 pts)
    if vol_ratio >= 2.0:
        score += 15
    elif vol_ratio >= 1.5:
        score += 10
    elif vol_ratio >= 1.2:
        score += 5
    # Breakout (10 pts)
    if is_20dh:
        score += 10
    # Relative Strength (5 pts)
    if rs >= 1.1:
        score += 5
    elif rs >= 1.0:
        score += 3
    return min(score, 100)


def compute_value_score(pe: float, pb: float, roe: float, de: float,
                         fcf: float, above_200: bool) -> int:
    score = 0
    if 0 < pe < 15:   score += 25
    elif 0 < pe < 20: score += 15
    elif 0 < pe < 25: score += 8
    if pb < 1.5: score += 20
    elif pb < 2.5: score += 10
    elif pb < 3.0: score += 5
    if roe >= 20: score += 20
    elif roe >= 15: score += 12
    elif roe >= 12: score += 6
    if de < 0.3: score += 15
    elif de < 0.7: score += 10
    elif de < 1.0: score += 5
    if fcf > 0: score += 10
    if above_200: score += 10
    return min(score, 100)


def compute_options_score(iv_rank: float, delta: float, premium_pct: float,
                           spread_pct: float, trend_bull: bool) -> int:
    score = 0
    if iv_rank >= 50: score += 30
    elif iv_rank >= 35: score += 20
    elif iv_rank >= 25: score += 10
    if 0.18 <= delta <= 0.25: score += 25
    elif 0.15 <= delta <= 0.30: score += 15
    if premium_pct >= 2.0: score += 25
    elif premium_pct >= 1.5: score += 18
    elif premium_pct >= 1.0: score += 10
    if spread_pct <= 2: score += 10
    elif spread_pct <= 5: score += 5
    if trend_bull: score += 10
    return min(score, 100)


# ── Annualized Return ──────────────────────────────────────────

def annualized_return(premium: float, strike: float, dte: int) -> float:
    if strike <= 0 or dte <= 0:
        return 0.0
    daily = premium / strike
    return round(daily * (365 / dte) * 100, 2)


# ── IV Rank Approximation ──────────────────────────────────────

def approx_iv_rank(iv_current: float) -> float:
    """DEPRECATED — not an IV rank. Use scanners.option_premium.premium_rank.

    This maps IV onto a fixed 10-80% scale that is IDENTICAL for every
    ticker, so it has no idea what normal looks like for the name in front of
    it. Its practical effect was to turn every scanner's "IV Rank" slider into
    a hard, ticker-independent IV threshold:

        Min IV Rank 25  ==  IV >= 27.5%   (CSP: excluded AAPL, SPY, KO, JNJ
                                           however expensive their options got)
        Max IV Rank 35  ==  IV <= 34.5%   (LEAPS: excluded NVDA, TSLA, SOXL
                                           however cheap theirs got)

    Every scanner has been moved to premium_rank(), which compares IV against
    the ticker's own stored history when available and against its realised
    volatility otherwise. Kept only so nothing imported from here breaks; do
    not use it for new work.
    """
    iv_min, iv_max = 0.10, 0.80
    rank = (iv_current - iv_min) / (iv_max - iv_min) * 100
    return round(max(0, min(100, rank)), 1)


# ── UI Components ──────────────────────────────────────────────

def metric_card(label: str, value: str, delta: str = "", color: str = GOLD):
    delta_html = f'<span style="color:{ACCENT_GREEN if not delta.startswith("-") else ACCENT_RED};font-size:12px">{delta}</span>' if delta else ""
    st.markdown(f"""
    <div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-top:2px solid {color};
                border-radius:8px;padding:16px 20px;text-align:center;">
        <div style="color:{TEXT_MUTED};font-size:11px;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">{label}</div>
        <div style="color:{color};font-size:22px;font-weight:700;font-family:'Georgia',serif">{value}</div>
        {delta_html}
    </div>""", unsafe_allow_html=True)


def signal_badge(score: float) -> str:
    label, color = get_signal_label(score)
    return f'<span style="background:{color}22;color:{color};border:1px solid {color}55;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:600">{label}</span>'


def score_bar(score: float) -> str:
    color = ACCENT_GREEN if score >= 70 else (GOLD if score >= 50 else ACCENT_RED)
    return f"""<div style="background:#1a1a2a;border-radius:4px;height:6px;width:100%;margin-top:4px">
    <div style="background:{color};height:6px;border-radius:4px;width:{score}%"></div></div>
    <span style="color:{color};font-size:11px;font-weight:700">{int(score)}</span>"""


def trend_arrow(change_pct: float) -> str:
    if change_pct >= 1: return f'<span style="color:{ACCENT_GREEN}">▲ {change_pct:+.2f}%</span>'
    if change_pct <= -1: return f'<span style="color:{ACCENT_RED}">▼ {change_pct:+.2f}%</span>'
    return f'<span style="color:{TEXT_MUTED}">● {change_pct:+.2f}%</span>'


def section_header(icon: str, title: str, subtitle: str = ""):
    st.markdown(f"""
    <div style="margin-bottom:24px;border-bottom:1px solid {BORDER_COLOR};padding-bottom:16px">
        <h2 style="color:{GOLD};font-family:'Georgia',serif;font-size:26px;margin:0">
            {icon} {title}
        </h2>
        {f'<p style="color:{TEXT_MUTED};margin:4px 0 0 0;font-size:14px">{subtitle}</p>' if subtitle else ""}
    </div>""", unsafe_allow_html=True)


def empty_state(message: str = "No results found. Try adjusting filters."):
    st.markdown(f"""
    <div style="text-align:center;padding:60px 20px;color:{TEXT_MUTED}">
        <div style="font-size:48px;margin-bottom:16px">🔍</div>
        <div style="font-size:16px">{message}</div>
    </div>""", unsafe_allow_html=True)


# ── Scan Diagnostics ───────────────────────────────────────────

class ScanDiagnostics:
    """
    Tracks per-ticker scan outcomes so users can see why a scan returned
    few/no results. Replace silent `except Exception: continue` blocks with:

        diag = ScanDiagnostics()
        for ticker in tickers:
            try:
                ...
                if some_filter_fails: diag.skipped(ticker, "filter:rsi"); continue
                ...
                diag.passed(ticker)
            except Exception as e:
                diag.failed(ticker, type(e).__name__)
        diag.render()
    """
    def __init__(self):
        self.total = 0
        self.pass_count = 0
        self.skips = {}     # reason -> count
        self.errors = {}    # error_class -> count
        self._error_examples = {}

    def seen(self, ticker: str = None):
        self.total += 1

    def passed(self, ticker: str = None):
        self.pass_count += 1

    def skipped(self, ticker: str, reason: str = "no_match"):
        self.skips[reason] = self.skips.get(reason, 0) + 1

    def failed(self, ticker: str, error_class: str = "Exception"):
        self.errors[error_class] = self.errors.get(error_class, 0) + 1
        if error_class not in self._error_examples:
            self._error_examples[error_class] = ticker

    def render(self, hide_when_clean: bool = True):
        """Render an inline diagnostics line. Skips rendering if everything passed."""
        fail_total = sum(self.errors.values())
        skip_total = sum(self.skips.values())
        if hide_when_clean and fail_total == 0 and self.total > 0 and self.pass_count == self.total:
            return
        if self.total == 0:
            return

        bits = [
            f'<span style="color:{TEXT_MUTED}">Scanned</span> '
            f'<b style="color:{TEXT_PRIMARY}">{self.total}</b>',
            f'<span style="color:{ACCENT_GREEN}">{self.pass_count} matched</span>',
        ]
        if skip_total:
            top_skips = sorted(self.skips.items(), key=lambda x: -x[1])[:3]
            tail = ", ".join(f"{r} ({n})" for r, n in top_skips)
            bits.append(f'<span style="color:{TEXT_MUTED}">{skip_total} filtered ({tail})</span>')
        if fail_total:
            top_errs = sorted(self.errors.items(), key=lambda x: -x[1])[:2]
            tail = ", ".join(f"{e} ({n})" for e, n in top_errs)
            bits.append(f'<span style="color:{ACCENT_RED}">{fail_total} errors ({tail})</span>')

        st.markdown(
            f'<div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};'
            f'border-radius:6px;padding:8px 14px;margin-top:12px;font-size:12px">'
            f'{" · ".join(bits)}</div>',
            unsafe_allow_html=True,
        )


def _score_bar_html(score: float) -> str:
    """Score badge + progress bar — green ≥70, amber 50–69, red <50."""
    try:
        score = int(float(score))
        if score != score:   # NaN guard
            raise ValueError
    except Exception:
        return f'<span style="color:{TEXT_MUTED};font-size:11px">—</span>'
    if score >= 70:
        color, badge_bg, label = ACCENT_GREEN, "#14532d", "Strong"
    elif score >= 50:
        color, badge_bg, label = "#FBBF24", "#451a03", "Moderate"
    else:
        color, badge_bg, label = ACCENT_RED, "#450a0a", "Weak"
    return (
        f'<div style="display:flex;align-items:center;gap:6px">'
        # Pill badge
        f'<span style="background:{badge_bg};color:{color};font-weight:700;font-size:11px;'
        f'padding:2px 7px;border-radius:12px;border:1px solid {color}44;white-space:nowrap">'
        f'{score}</span>'
        # Mini bar
        f'<div style="flex:1;background:#1a1a2a;border-radius:3px;height:4px;min-width:40px">'
        f'<div style="background:{color};height:4px;border-radius:3px;width:{score}%"></div></div>'
        f'</div>'
    )


def _cell_color(col: str, val) -> str:
    """Return inline color style for specific column values."""
    col_l = col.lower()
    try:
        fval = float(str(val).replace('%','').replace('$','').replace(',','').replace('×','').replace('x',''))
    except Exception:
        fval = None

    # Change % columns
    if 'change' in col_l or 'chg' in col_l:
        if fval is not None:
            return ACCENT_GREEN if fval >= 0 else ACCENT_RED

    # Trend / direction text
    sval = str(val)
    if sval in ('✅ Bullish', 'Bullish', 'Strong Bull', '🟢 Bullish', '🟢 Bull'):
        return ACCENT_GREEN
    if sval in ('❌ Bearish', 'Bearish', '🔴 Bearish', '🔴 Bear'):
        return ACCENT_RED
    if '✅' in sval and '❌' not in sval:
        return ACCENT_GREEN
    if '❌' in sval:
        return ACCENT_RED
    if '🟢' in sval:
        return ACCENT_GREEN
    if '🔴' in sval:
        return ACCENT_RED
    if '⚠️' in sval or '🟡' in sval:
        return "#FBBF24"

    # Numeric green/red for specific cols
    if fval is not None:
        if col_l in ('rsi',):
            return ACCENT_GREEN if 50 <= fval <= 70 else (ACCENT_RED if fval > 75 else TEXT_MUTED)
        if 'score' in col_l:
            return ACCENT_GREEN if fval >= 70 else (GOLD if fval >= 50 else ACCENT_RED)
        if 'vol ratio' in col_l or 'vol_ratio' in col_l:
            return ACCENT_GREEN if fval >= 1.5 else TEXT_PRIMARY

    return TEXT_PRIMARY


def _extract_price(row: pd.Series) -> str:
    """Pull the best available price string from a result row."""
    for col in ["Price", "Last", "Underlying", "Stock Price", "Spot", "Close", "Current"]:
        if col in row.index:
            try:
                v = float(str(row[col]).replace("$", "").replace(",", ""))
                if v > 0:
                    return str(round(v, 2))
            except Exception:
                pass
    return ""


# ── Pre/Post market price helper ──────────────────────────────

def add_prepost_column(df: pd.DataFrame) -> pd.DataFrame:
    """
    Append a 'Pre/Post' column to a scanner results DataFrame.
    Fetches extended-hours prices in one batch yfinance call.
    Returns the original df if Ticker column is missing or all fetches fail.
    """
    if "Ticker" not in df.columns or df.empty:
        return df
    from data_loader import get_prepost_price
    tickers = df["Ticker"].dropna().tolist()
    prepost_map: dict = {}
    for tk in tickers:
        info = get_prepost_price(str(tk))
        if info:
            sign = "+" if info["change_pct"] >= 0 else ""
            prepost_map[str(tk)] = f"${info['price']} ({sign}{info['change_pct']:.1f}%)"
        else:
            prepost_map[str(tk)] = "—"
    df = df.copy()
    df.insert(2, "Pre/Post", df["Ticker"].map(prepost_map).fillna("—"))
    return df


# ── Tracker callbacks (on_click — fire before rerun) ──────────
def _cb_track(ticker, strategy, source, price_str, extra_meta=None, row_data=None):
    from scanners.gsheet_helper import add_to_tracking, add_to_performance
    ok, msg = add_to_tracking(ticker, strategy, source, price_str, extra_meta)
    # Also write to Performance tab if options data is present in the row
    if row_data:
        try:
            add_to_performance(ticker, strategy, source, price_str, row_data)
        except Exception:
            pass
    notes = st.session_state.setdefault("_tracker_notes", [])
    notes.append(("✅" if ok else "⚠️", msg))

def _cb_watch(ticker, source, price_str):
    from scanners.gsheet_helper import add_to_watchlist
    ok, msg = add_to_watchlist(ticker, source, price_str)
    notes = st.session_state.setdefault("_tracker_notes", [])
    notes.append(("✅" if ok else "⚠️", msg))


def render_tracker_widget(tickers: list, strategy: str = "Stock", source: str = "",
                          prices: dict | None = None):
    """Per-row Track/Watch strip — one row per ticker with on_click buttons."""
    if not tickers:
        return
    import re, hashlib

    def _safe(s):
        return re.sub(r"[^a-zA-Z0-9]", "_", str(s))

    key_base = hashlib.md5(f"{strategy}{source}{tickers[:3]}".encode()).hexdigest()[:6]

    st.markdown(
        f'<div style="color:{GOLD};font-size:11px;font-weight:600;letter-spacing:1px;'
        f'text-transform:uppercase;margin:14px 0 4px">📌 Track &nbsp;/&nbsp; 👁 Watch</div>',
        unsafe_allow_html=True,
    )

    for i, ticker in enumerate(tickers):
        price_str = (prices or {}).get(str(ticker), "")
        c_tkr, c_strat, c_price, c_trk, c_wch = st.columns([2, 2, 2, 1, 1])
        with c_tkr:
            st.markdown(
                f'<div style="padding:5px 0;color:{GOLD};font-family:\'DM Mono\',monospace;'
                f'font-weight:700;font-size:13px">{ticker}</div>',
                unsafe_allow_html=True,
            )
        with c_strat:
            st.markdown(
                f'<div style="padding:5px 0;color:{TEXT_MUTED};font-size:12px">{strategy}</div>',
                unsafe_allow_html=True,
            )
        with c_price:
            st.markdown(
                f'<div style="padding:5px 0;color:{TEXT_PRIMARY};font-family:\'DM Mono\',monospace;'
                f'font-size:12px">{"$" + price_str if price_str else "—"}</div>',
                unsafe_allow_html=True,
            )
        with c_trk:
            st.button("📌 Track",
                      key=f"trk_{key_base}_{i}_{_safe(ticker)}",
                      use_container_width=True,
                      help=f"Track {ticker} ({strategy}) — 100 shares or 1 contract",
                      on_click=_cb_track,
                      args=(ticker, strategy, source, price_str, {}))
        with c_wch:
            st.button("👁 Watch",
                      key=f"wch_{key_base}_{i}_{_safe(ticker)}",
                      use_container_width=True,
                      help=f"Add {ticker} to WatchList",
                      on_click=_cb_watch,
                      args=(ticker, source, price_str))


# ── Scanner abbreviation map (for source tag building) ────────
# Converts full scanner names (old cached data) → short codes
_SCANNER_ABBREV = {
    "Trend Cont.":           "TC",
    "Trend Continuation":    "TC",
    "Trend Stack":           "TS",
    "Trend Align":           "TA",
    "Trend Alignment":       "TA",
    "Multi-Factor":          "MF",
    "Reset Bounce":          "MRS",
    "Momentum Reset Bounce": "MRS",
    "Momentum":              "M",
    "Growth":                "G",
    "Golden Scan":           "GS",   # normalise legacy source tags stored as "AM·Golden Scan"
}

# ── Scanner display map (abbrev → timeframe + readable name) ───
# Used to render the "Scanners" column as clear DAILY/WEEKLY badges
# (e.g. "DAILY Momentum") instead of cryptic codes ("M"). The Style
# column shown alongside provides the descriptor ("Medium Swing").
# Keep the underlying "Scanners" data as abbreviations — only the
# on-screen display is expanded here.
_SCANNER_DISPLAY = {
    "M":   ("DAILY",  "Momentum"),
    "TS":  ("DAILY",  "Trend Stack"),
    "MF":  ("DAILY",  "Multi-Factor"),
    "G":   ("DAILY",  "Growth"),
    "TA":  ("WEEKLY", "Trend Align"),
    "TC":  ("WEEKLY", "Trend Cont."),
    "MRS": ("WEEKLY", "Reset Bounce"),
}


# ── Strategy-aware column sets ─────────────────────────────────
# These define the preferred column order per strategy type.
# Columns not present in the DataFrame are skipped automatically.
_STOCK_COLS = [
    "Ticker", "Price", "Pre/Post", "Change %", "RSI", "Vol Ratio",
    "RS vs SPY", "Score", "Scanners", "Signals", "Scanner Count", "Style", "Hold",
    "Est. Upside %", "Rev Growth %", "EPS Growth %", "P/E",
    "Sector", "Signal", "Direction", "Catalysts",
]
_OPTIONS_COLS = [
    # Removed: Breakeven, Assign Risk, Trend, Ann. Return, Read %
    "Ticker", "Stock Price", "Pre/Post", "Change %", "Score",
    "Strike", "Call Strike", "Premium", "Premium %", "Delta", "IV", "IV Rank",
    "DTE", "Expiry", "Side", "Bar", "Resistance", "Average",
]
# Golden Scan is stock-oriented
_GOLDEN_COLS = _STOCK_COLS

_OPTIONS_STRATS = {"CSP", "CC", "LEAPS", "ETF Options", "3x ETF Options",
                   "CSP-Stocks", "CC-Stocks", "LEAPS-Stocks",
                   "CSP-ETFs", "CC-ETFs", "LEAPS-ETFs"}

# Columns that belong ONLY to stock strategies — never shown for options
_STOCK_ONLY_COLS = {
    "RSI", "Vol Ratio", "RS vs SPY", "Scanners", "Signals", "Scanner Count",
    "Style", "Hold", "Est. Upside %", "Rev Growth %", "EPS Growth %",
    "P/E", "Sector", "Signal", "Direction", "Catalysts",
}

# Columns that belong ONLY to options strategies — never shown for stocks
_OPTIONS_ONLY_COLS = {
    "Strike", "Call Strike", "Premium", "Premium %", "Delta", "IV", "IV Rank",
    "DTE", "Expiry", "Side", "Bar", "Resistance", "Average",
    "Stock Price",    # options scans label it "Stock Price"; stock scans use "Price"
}

# Columns NEVER shown regardless of strategy (noisy / redundant)
_NEVER_SHOW_COLS = {
    "Breakeven", "Assign Risk", "Trend", "Ann. Return", "Ann. Return %",
    "Read %", "Upside Cap %", "P(Assign) %", "Near Resist.", "Leverage",
    "Spread %", "Yield %",
    "Universe",   # used internally for source-tag building; not a user-facing column
    "Icons",      # rendered inline inside the Ticker cell; never shown as a standalone column
}


def _strategy_cols(df: pd.DataFrame, strategy: str) -> list[str]:
    """
    Return ordered column list for the given strategy, filtered to:
      1. Only columns in the strategy's preferred set (with real data)
      2. Extra columns that have data AND are not cross-strategy or noisy

    Prevents stock-only columns (RSI, Vol Ratio …) appearing on options
    results and vice-versa, and removes universally-noisy columns.
    """
    strat_up = strategy.upper()
    is_options = any(s in strat_up for s in ("CSP", "CC", "LEAPS", "ETF OPT", "3X ETF"))

    if is_options:
        preferred = _OPTIONS_COLS
        excluded  = _STOCK_ONLY_COLS | _NEVER_SHOW_COLS
    elif "GOLDEN" in strat_up:
        preferred = _GOLDEN_COLS
        excluded  = _OPTIONS_ONLY_COLS | _NEVER_SHOW_COLS
    else:
        preferred = _STOCK_COLS
        excluded  = _OPTIONS_ONLY_COLS | _NEVER_SHOW_COLS

    # Only keep cols that exist AND have at least one real value
    def _has_data(col: str) -> bool:
        if col not in df.columns:
            return False
        s = df[col].astype(str).str.strip()
        return ((s != "") & (s.str.lower() != "nan") & (s != "None") & (s != "0")).any()

    ordered = [c for c in preferred if _has_data(c)]

    # Append extra columns that have data and are not excluded
    seen   = set(ordered)
    extras = [
        c for c in df.columns
        if c not in seen and c not in excluded and _has_data(c)
    ]
    return ordered + extras


def render_results_table(df: pd.DataFrame, score_col: str = "Score",
                         strategy: str = "Stock", source: str = "",
                         default_sort_col: str = "", default_sort_asc: bool = False):
    """Render results as columns-based rows with inline Track/Watch buttons."""
    if df.empty:
        empty_state()
        return

    import re, hashlib

    def _safe(s):
        return re.sub(r"[^a-zA-Z0-9]", "_", str(s))

    df = df.copy()
    if score_col in df.columns:
        df[score_col] = pd.to_numeric(df[score_col], errors="coerce").fillna(0).astype(int)

    # Optional pre/post market column (controlled by global sidebar toggle)
    if st.session_state.get("_show_prepost", False):
        with st.spinner("Fetching pre/post market prices…"):
            df = add_prepost_column(df)

    # ── Unique key for download button (prevents DuplicateElementId) ──
    first_ticker = str(df["Ticker"].iloc[0]) if "Ticker" in df.columns else "x"
    key_base = hashlib.md5(
        f"{strategy}{source}{first_ticker}{len(df)}".encode()
    ).hexdigest()[:8]

    # Export row
    c1, c2 = st.columns([3, 1])
    with c1:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:13px;padding:6px 0">'
            f'Found <b style="color:{GOLD}">{len(df)}</b> results</div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.download_button(
            "⬇ Export CSV", df.to_csv(index=False),
            _export_filename(f"gs_{strategy.lower().replace(' ','_')}"),
            "text/csv",
            use_container_width=True,
            key=f"dl_{key_base}",
        )

    # Tighten vertical spacing between rows
    st.markdown(
        "<style>"
        "div[data-testid='stHorizontalBlock']{gap:0 !important;margin-bottom:0 !important}"
        "div[data-testid='stHorizontalBlock'] > div[data-testid='stColumn']"
        "{padding-top:2px !important;padding-bottom:2px !important}"
        "</style>",
        unsafe_allow_html=True,
    )

    # Only show columns relevant for this strategy (drops all-nan columns)
    data_cols = _strategy_cols(df, strategy)

    # ── Sort control ─────────────────────────────────────────────
    _sortable = [c for c in data_cols if c in df.columns]
    _COUNT_SCORE = "Count + Score ↓"   # synthetic compound-sort option
    _has_count   = "Scanner Count" in df.columns

    # Build option list: "Count + Score" first (and default) when the column exists.
    # Caller may override with default_sort_col / default_sort_asc.
    if _has_count:
        _sort_opts = [_COUNT_SCORE] + _sortable
        _sort_def_idx = 0
    else:
        _sort_opts = _sortable
        _sort_def_idx = next((i for i, c in enumerate(_sortable) if c == "Score"), 0)

    # Apply caller-supplied default sort column (overrides the heuristic above)
    if default_sort_col and default_sort_col in _sort_opts:
        _sort_def_idx = _sort_opts.index(default_sort_col)

    _s1, _s2, _s3 = st.columns([0.6, 2.8, 0.7])
    with _s1:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:11px;padding:7px 0;white-space:nowrap">↕ Sort:</div>',
            unsafe_allow_html=True,
        )
    with _s2:
        _sort_by = st.selectbox(
            "Sort column", _sort_opts,
            index=_sort_def_idx,
            key=f"sort_col_{key_base}",
            label_visibility="collapsed",
        )
    with _s3:
        # Asc toggle hidden for compound sort (always desc).
        # default_sort_asc sets the initial direction when the caller specifies a default column.
        _toggle_default = default_sort_asc if (default_sort_col and _sort_by == default_sort_col) else False
        _sort_asc = False if _sort_by == _COUNT_SCORE else st.toggle("↑ Asc", value=_toggle_default, key=f"sort_asc_{key_base}")

    # Apply sort
    if _sort_by == _COUNT_SCORE:
        df = df.copy()
        df["__sc_num"] = pd.to_numeric(df.get("Score", 0), errors="coerce").fillna(0)
        df["__cnt"]    = pd.to_numeric(df.get("Scanner Count", 1), errors="coerce").fillna(1)
        df = df.sort_values(["__cnt", "__sc_num"], ascending=[False, False]).drop(columns=["__sc_num", "__cnt"])
    elif _sort_by and _sort_by in df.columns:
        _num = pd.to_numeric(df[_sort_by], errors="coerce")
        if _num.notna().sum() > len(df) * 0.3:   # mostly numeric → sort as number
            _fill = -1e9 if not _sort_asc else 1e9
            df = df.copy()
            df["__sort"] = _num.fillna(_fill)
            df = df.sort_values("__sort", ascending=_sort_asc).drop(columns=["__sort"])
        else:
            df = df.sort_values(_sort_by, ascending=_sort_asc, na_position="last")

    # Column width hints — wider for text-heavy columns, narrower for numbers
    _wide = {"Ticker", "Sector", "Catalysts", "Momentum", "Trap Risk", "Mkt Cap", "Signal", "Signals", "Scanners"}
    _med  = {"Score", "Strategy", "Direction", "MACD Bull", "FCF", ">200 SMA"}
    col_widths = []
    for c in data_cols:
        if c in _wide:    col_widths.append(1.4)
        elif c in _med:   col_widths.append(1.1)
        else:             col_widths.append(0.9)
    # Two button columns at the end
    col_widths += [0.85, 0.85]

    # ── Header row ──────────────────────────────────────────────
    hdr = st.columns(col_widths)
    for i, col_name in enumerate(data_cols):
        with hdr[i]:
            st.markdown(
                f'<div style="color:{GOLD};font-size:10px;font-weight:700;'
                f'text-transform:uppercase;letter-spacing:0.7px;'
                f'padding:6px 4px 4px;border-bottom:2px solid {GOLD}55;'
                f'white-space:nowrap">{col_name}</div>',
                unsafe_allow_html=True,
            )
    for label in ("📌", "👁"):
        with hdr[data_cols.__len__() + (0 if label == "📌" else 1)]:
            st.markdown(
                f'<div style="color:{GOLD};font-size:10px;font-weight:700;'
                f'padding:6px 4px 4px;border-bottom:2px solid {GOLD}55;'
                f'text-align:center">{label}</div>',
                unsafe_allow_html=True,
            )

    # ── Data rows ────────────────────────────────────────────────
    for row_i, (_, row) in enumerate(df.iterrows()):
        bg = BG_CARD if row_i % 2 == 0 else BG_PANEL
        ticker     = str(row.get("Ticker", "")) if "Ticker" in df.columns else ""
        price_str  = _extract_price(row)
        row_cols   = st.columns(col_widths)

        # Enriched source tag — format: [AM·|PM·|man·]GS·Scanner1 + Scanner2 (N)
        # Slot prefix so we know if the pick came from AM or PM scheduled scan
        _src_str  = str(source)
        slot_pfx  = ("AM·" if "Sched-AM" in _src_str else
                     "PM·" if "Sched-PM" in _src_str else "")
        row_source = source

        if "Scanners" in df.columns:
            sc = str(row.get("Scanners", "")).strip()
            parts = [p.strip() for p in sc.split(" + ")
                     if p.strip() and p.strip().lower() != "nan"]
            if parts:
                # Apply abbreviation map — handles both new abbreviations and old full names
                abbr_parts = [_SCANNER_ABBREV.get(p, p) for p in parts]
                names = " + ".join(abbr_parts[:6])   # show all (up to 6 codes)
                row_source = f"{slot_pfx}GS·{names} ({len(parts)})"
            elif slot_pfx:
                row_source = f"{slot_pfx}{strategy}"
        elif "Catalysts" in df.columns:
            cat = str(row.get("Catalysts", "")).strip()
            if cat and cat.lower() != "nan":
                row_source = f"{slot_pfx}H&C·{cat[:50]}"
            elif slot_pfx:
                row_source = f"{slot_pfx}{strategy}"
        elif slot_pfx:
            # Options/other scheduled scan — prefix with slot + strategy + universe (if available)
            _univ_val = str(row.get("Universe", "")).strip() if "Universe" in df.columns else ""
            _univ_sfx = f"·{_univ_val}" if _univ_val and _univ_val.lower() not in ("nan", "none", "") else ""
            row_source = f"{slot_pfx}{strategy}{_univ_sfx}"

        # Manual Track button gets "man·" prefix; scheduled scans keep AM·/PM· prefix
        track_source = row_source if slot_pfx else f"man·{row_source}"

        # Extra metadata for tracking
        extra_meta = {}
        for meta_key, col_name in [("Score_At_Track", "Score"), ("HOLD", "HOLD"),
                                    ("Est_Upside", "Est. Upside %"), ("Direction", "Direction"),
                                    ("Style", "Style")]:
            if col_name in df.columns:
                extra_meta[meta_key] = str(row.get(col_name, ""))

        for i, col_name in enumerate(data_cols):
            val = row[col_name]
            with row_cols[i]:
                if col_name == score_col:
                    st.markdown(
                        f'<div style="background:{bg};padding:6px 4px">'
                        f'{_score_bar_html(val)}</div>',
                        unsafe_allow_html=True,
                    )
                elif col_name == "Ticker":
                    _icons_html = str(row.get("Icons", "")).strip()
                    _icons_div  = (
                        f'<div style="margin-top:2px">{_icons_html}</div>'
                        if _icons_html else ""
                    )
                    st.markdown(
                        f'<div style="background:{bg};padding:6px 4px">'
                        f'<span style="color:{GOLD};font-family:\'DM Mono\',monospace;'
                        f'font-weight:700;font-size:13px">{val}</span>'
                        f'{_icons_div}</div>',
                        unsafe_allow_html=True,
                    )
                elif col_name == "Signals":
                    val_str = str(val).strip()
                    if val_str in ("—", "", "nan", "None"):
                        sig_html = f'<span style="color:{TEXT_MUTED};font-size:11px">—</span>'
                    else:
                        parts = []
                        for sig in [s.strip() for s in val_str.split(",")]:
                            if sig and sig != "—":
                                parts.append(
                                    f'<span style="background:{ACCENT_GREEN}1A;color:{ACCENT_GREEN};'
                                    f'border:1px solid {ACCENT_GREEN}44;padding:1px 5px;'
                                    f'border-radius:3px;font-size:10px;font-weight:600;'
                                    f'white-space:nowrap">{sig}</span>'
                                )
                        sig_html = (
                            '<div style="display:flex;flex-wrap:wrap;gap:3px">'
                            + "".join(parts) + "</div>"
                        ) if parts else f'<span style="color:{TEXT_MUTED};font-size:11px">—</span>'
                    st.markdown(
                        f'<div style="background:{bg};padding:6px 4px">{sig_html}</div>',
                        unsafe_allow_html=True,
                    )
                elif col_name == "Scanners":
                    # Expand "TC + TS" → stacked "WEEKLY Trend Cont." / "DAILY Trend Stack"
                    raw = str(val).strip()
                    parts = [p.strip() for p in raw.split(" + ")
                             if p.strip() and p.strip().lower() not in ("nan", "none", "")]
                    chips = []
                    for p in parts:
                        abbr = _SCANNER_ABBREV.get(p, p)          # normalise legacy full names
                        tf, name = _SCANNER_DISPLAY.get(abbr, ("", p))
                        if tf:
                            tf_color = ACCENT_BLUE if tf == "DAILY" else ACCENT_GREEN
                            chips.append(
                                f'<div style="white-space:nowrap;line-height:1.5">'
                                f'<span style="background:{tf_color}1A;color:{tf_color};'
                                f'border:1px solid {tf_color}44;padding:0 5px;border-radius:3px;'
                                f'font-size:9px;font-weight:700;letter-spacing:.4px">{tf}</span> '
                                f'<span style="color:{TEXT_PRIMARY};font-size:11px;font-weight:600">{name}</span>'
                                f'</div>'
                            )
                        else:
                            chips.append(
                                f'<div style="white-space:nowrap;color:{TEXT_PRIMARY};'
                                f'font-size:11px">{name}</div>'
                            )
                    inner = ("".join(chips) if chips
                             else f'<span style="color:{TEXT_MUTED};font-size:11px">—</span>')
                    st.markdown(
                        f'<div style="background:{bg};padding:6px 4px;display:flex;'
                        f'flex-direction:column;gap:2px">{inner}</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    color = _cell_color(col_name, val)
                    # Normalise: treat nan / None / empty string as "—"
                    _raw = str(val).strip()
                    display_val = "—" if _raw.lower() in ("nan", "none", "") else _raw
                    color = TEXT_MUTED if display_val == "—" else color
                    # Directional arrow prefix for upside/return columns
                    if display_val != "—" and (
                        "upside" in col_name.lower() or "return" in col_name.lower()
                    ):
                        try:
                            fv = float(display_val.replace("%", "").replace("+", "").strip())
                            arrow = "▲" if fv >= 0 else "▼"
                            color = ACCENT_GREEN if fv >= 0 else ACCENT_RED
                            display_val = f"{arrow} {display_val}"
                        except Exception:
                            pass
                    st.markdown(
                        f'<div style="background:{bg};padding:6px 4px">'
                        f'<span style="color:{color};font-size:12px;white-space:nowrap">'
                        f'{display_val}</span></div>',
                        unsafe_allow_html=True,
                    )

        with row_cols[-2]:
            st.button(
                "📌 Track",
                key=f"trk_{key_base}_{row_i}_{_safe(ticker)}",
                use_container_width=True,
                help=f"Track {ticker} ({strategy}) — 100 shares or 1 contract",
                on_click=_cb_track,
                args=(ticker, strategy, track_source, price_str, extra_meta, row.to_dict()),
            )
        with row_cols[-1]:
            st.button(
                "👁 Watch",
                key=f"wch_{key_base}_{row_i}_{_safe(ticker)}",
                use_container_width=True,
                help=f"Add {ticker} to WatchList",
                on_click=_cb_watch,
                args=(ticker, source, price_str),
            )


def mini_chart(df: pd.DataFrame, ticker: str) -> go.Figure:
    fig = go.Figure(go.Candlestick(
        x=df.index[-60:],
        open=df["Open"].iloc[-60:],
        high=df["High"].iloc[-60:],
        low=df["Low"].iloc[-60:],
        close=df["Close"].iloc[-60:],
        increasing_line_color=ACCENT_GREEN,
        decreasing_line_color=ACCENT_RED,
        name=ticker,
    ))
    sma20 = calc_sma(df["Close"], 20).iloc[-60:]
    sma50 = calc_sma(df["Close"], 50).iloc[-60:]
    fig.add_trace(go.Scatter(x=df.index[-60:], y=sma20, line=dict(color=GOLD, width=1.2), name="SMA20"))
    fig.add_trace(go.Scatter(x=df.index[-60:], y=sma50, line=dict(color=ACCENT_BLUE, width=1.2), name="SMA50"))
    fig.update_layout(
        paper_bgcolor=BG_CARD, plot_bgcolor=BG_PANEL,
        font_color=TEXT_PRIMARY, height=300,
        margin=dict(l=10, r=10, t=30, b=10),
        title=dict(text=f"{ticker} — 60D Price", font=dict(color=GOLD, size=14)),
        xaxis=dict(gridcolor=BORDER_COLOR, showgrid=False),
        yaxis=dict(gridcolor=BORDER_COLOR),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        xaxis_rangeslider_visible=False,
    )
    return fig
