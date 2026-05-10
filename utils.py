# utils.py — Technical Indicators, Scoring, UI Helpers

import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
from config import *


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
    """Return (macd_line, signal_line, histogram) as floats."""
    if len(series) < 26:
        return 0.0, 0.0, 0.0
    ema12 = calc_ema(series, 12)
    ema26 = calc_ema(series, 26)
    macd = ema12 - ema26
    signal = calc_ema(macd, 9)
    hist = macd - signal
    return float(macd.iloc[-1]), float(signal.iloc[-1]), float(hist.iloc[-1])


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
    """Very rough IV rank approximation (0-100)."""
    # Typical IV range ~15-80%; rank within that
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
    """Inline score bar for HTML table cells."""
    score = int(score)
    color = ACCENT_GREEN if score >= 70 else (GOLD if score >= 50 else ACCENT_RED)
    return (
        f'<div style="display:flex;align-items:center;gap:6px">'
        f'<div style="flex:1;background:#1a1a2a;border-radius:3px;height:5px;min-width:60px">'
        f'<div style="background:{color};height:5px;border-radius:3px;width:{score}%"></div></div>'
        f'<span style="color:{color};font-weight:700;font-size:12px;white-space:nowrap">{score}</span>'
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


def render_tracker_widget(tickers: list, strategy: str = "Stock", source: str = "",
                          prices: dict | None = None):
    """Per-row Track/Watch action strip — one row per ticker with buttons."""
    if not tickers:
        return
    import re, hashlib
    from scanners.gsheet_helper import add_to_tracking, add_to_watchlist

    def _safe(s):
        return re.sub(r"[^a-zA-Z0-9]", "_", str(s))

    key_base = hashlib.md5(f"{strategy}{source}{tickers[:3]}".encode()).hexdigest()[:6]

    st.markdown(
        f'<div style="color:{GOLD};font-size:11px;font-weight:600;letter-spacing:1px;'
        f'text-transform:uppercase;margin:14px 0 4px">📌 Track &nbsp;/&nbsp; 👁 Watch</div>',
        unsafe_allow_html=True,
    )
    # Compact CSS for the tiny action buttons in this strip
    st.markdown("""
    <style>
    div[data-testid="stHorizontalBlock"]:has(button[kind="secondary"].tw-btn) button {
        min-height: 32px !important; font-size: 12px !important; padding: 2px 6px !important;
    }
    </style>""", unsafe_allow_html=True)

    for i, ticker in enumerate(tickers):
        price_str = (prices or {}).get(ticker, "")
        c_tkr, c_strat, c_price, c_trk, c_wch = st.columns([2, 2, 2, 1, 1])
        with c_tkr:
            st.markdown(
                f'<div style="padding:4px 0;color:{GOLD};font-family:\'DM Mono\',monospace;'
                f'font-weight:700;font-size:13px">{ticker}</div>',
                unsafe_allow_html=True,
            )
        with c_strat:
            st.markdown(
                f'<div style="padding:4px 0;color:{TEXT_MUTED};font-size:12px">{strategy}</div>',
                unsafe_allow_html=True,
            )
        with c_price:
            st.markdown(
                f'<div style="padding:4px 0;color:{TEXT_PRIMARY};font-family:\'DM Mono\',monospace;'
                f'font-size:12px">{"$" + price_str if price_str else "—"}</div>',
                unsafe_allow_html=True,
            )
        with c_trk:
            if st.button("📌 Track", key=f"trk_{key_base}_{i}_{_safe(ticker)}",
                         use_container_width=True,
                         help=f"Track {ticker} — {strategy}"):
                ok, msg = add_to_tracking(ticker, strategy, source, price_str)
                st.toast(msg, icon="✅" if ok else "⚠️")
        with c_wch:
            if st.button("👁 Watch", key=f"wch_{key_base}_{i}_{_safe(ticker)}",
                         use_container_width=True,
                         help=f"Add {ticker} to WatchList"):
                ok, msg = add_to_watchlist(ticker, source, price_str)
                st.toast(msg, icon="✅" if ok else "⚠️")


def render_results_table(df: pd.DataFrame, score_col: str = "Score",
                         strategy: str = "Stock", source: str = ""):
    """Render results as a styled HTML table — always visible on any theme."""
    if df.empty:
        empty_state()
        return

    df = df.copy()
    if score_col in df.columns:
        df[score_col] = pd.to_numeric(df[score_col], errors="coerce").fillna(0).astype(int)

    # Export button row
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:13px;padding:6px 0">'
            f'Found <b style="color:{GOLD}">{len(df)}</b> results</div>',
            unsafe_allow_html=True
        )
    with col2:
        st.download_button(
            "⬇ Export CSV", df.to_csv(index=False),
            "golden_scanner_results.csv", "text/csv",
            use_container_width=True
        )

    # Build HTML table
    cols = df.columns.tolist()

    # Header row
    header_cells = "".join(
        f'<th style="background:{BG_PANEL};color:{GOLD};font-size:11px;font-weight:600;'
        f'text-transform:uppercase;letter-spacing:0.8px;padding:10px 14px;'
        f'border-bottom:2px solid {GOLD}44;white-space:nowrap;text-align:left">{c}</th>'
        for c in cols
    )

    # Data rows
    row_htmls = []
    for i, (_, row) in enumerate(df.iterrows()):
        bg = BG_CARD if i % 2 == 0 else BG_PANEL
        cells = []
        for col in cols:
            val = row[col]
            # Score column → progress bar
            if col == score_col:
                cell_content = _score_bar_html(val)
                cell_style = f'padding:8px 14px;vertical-align:middle;min-width:100px'
            else:
                color = _cell_color(col, val)
                # Ticker gets special treatment
                if col == "Ticker":
                    cell_content = (
                        f'<span style="color:{GOLD};font-family:\'DM Mono\',monospace;'
                        f'font-weight:600;font-size:13px">{val}</span>'
                    )
                else:
                    cell_content = f'<span style="color:{color};font-size:13px">{val}</span>'
                cell_style = f'padding:8px 14px;vertical-align:middle;white-space:nowrap'

            cells.append(
                f'<td style="{cell_style};border-bottom:1px solid {BORDER_COLOR}22;'
                f'background:{bg}">{cell_content}</td>'
            )
        row_htmls.append(f'<tr>{"".join(cells)}</tr>')

    table_html = f"""
    <div style="overflow-x:auto;border:1px solid {BORDER_COLOR};border-radius:8px;margin-top:8px">
      <table style="width:100%;border-collapse:collapse;font-family:'Inter',sans-serif">
        <thead><tr>{header_cells}</tr></thead>
        <tbody>{"".join(row_htmls)}</tbody>
      </table>
    </div>
    """
    st.markdown(table_html, unsafe_allow_html=True)

    # Per-row Track / Watch strip
    if "Ticker" in df.columns:
        tickers = df["Ticker"].dropna().tolist()
        prices  = {str(row["Ticker"]): _extract_price(row)
                   for _, row in df.iterrows() if pd.notna(row.get("Ticker"))}
        render_tracker_widget(tickers, strategy=strategy, source=source, prices=prices)


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
