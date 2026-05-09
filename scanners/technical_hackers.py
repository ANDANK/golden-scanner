# scanners/technical_hackers.py — Technical Hackers
# 5 precision breakout scanners: MACD Cross · Trend Stack · Squeeze · HVB · Multi-Factor

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import *
from utils import (section_header, empty_state, metric_card,
                   calc_sma, calc_ema, calc_rsi, calc_macd, calc_atr,
                   atr_expanding, is_20d_high, calc_relative_strength,
                   render_results_table)
from data_loader import get_price_history


# ══════════════════════════════════════════════════════════════
# SHARED INDICATOR LIBRARY
# ══════════════════════════════════════════════════════════════

def calc_bollinger(close: pd.Series, period: int = 20, std: float = 2.0):
    """Returns (upper, mid, lower, width_pct)."""
    mid   = calc_sma(close, period)
    sigma = close.rolling(period).std()
    upper = mid + std * sigma
    lower = mid - std * sigma
    width = ((upper - lower) / mid * 100).fillna(0)
    return upper, mid, lower, width


def calc_keltner(df: pd.DataFrame, period: int = 20, mult: float = 1.5):
    """Returns (upper, mid, lower) using True Range so gaps are included."""
    mid   = calc_ema(df["Close"].squeeze(), period)
    high  = df["High"].squeeze()
    low   = df["Low"].squeeze()
    close = df["Close"].squeeze()
    tr    = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr_s = tr.rolling(period).mean()
    upper = mid + mult * atr_s
    lower = mid - mult * atr_s
    return upper, mid, lower


def is_squeeze(df: pd.DataFrame, period: int = 20) -> bool:
    """True when BB is inside KC — the TTM Squeeze condition."""
    try:
        close          = df["Close"].squeeze()
        bb_up, _, bb_lo, _ = calc_bollinger(close, period)
        kc_up, _, kc_lo    = calc_keltner(df, period)
        return bool(bb_up.iloc[-1] < kc_up.iloc[-1] and
                    bb_lo.iloc[-1] > kc_lo.iloc[-1])
    except Exception:
        return False


def bb_width_20d_low(close: pd.Series, period: int = 20) -> bool:
    """True if current BB width is at or near its 20-day minimum."""
    _, _, _, width = calc_bollinger(close, period)
    w = width.dropna()
    if len(w) < 20:
        return False
    return float(w.iloc[-1]) <= float(w.iloc[-20:].quantile(0.15))


def price_above_upper_bb(close: pd.Series) -> bool:
    upper, _, _, _ = calc_bollinger(close)
    return float(close.iloc[-1]) > float(upper.iloc[-1])


def calc_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff().fillna(0))
    return (direction * volume).cumsum()


def vol_above_n_avg(volume: pd.Series, n: int = 20, mult: float = 1.5) -> float:
    avg = float(volume.iloc[:-1].rolling(n).mean().dropna().iloc[-1]) if len(volume) > n else float(volume.mean())
    curr = float(volume.iloc[-1])
    return curr / avg if avg > 0 else 0


def rsi_rising(close: pd.Series, lookback: int = 3) -> bool:
    if len(close) < 20:
        return False
    r_now  = calc_rsi(close)
    r_prev = calc_rsi(close.iloc[:-lookback])
    return r_now > r_prev


def sma200_sloping_up(close: pd.Series, lookback: int = 10) -> bool:
    if len(close) < 210:
        return False
    sma = calc_sma(close, 200)
    return float(sma.iloc[-1]) > float(sma.iloc[-1 - lookback])


def price_within_pct_of_high(close: pd.Series, days: int = 20, pct: float = 3.0) -> bool:
    if len(close) < days:
        return False
    hi = float(close.iloc[-days:].max())
    return float(close.iloc[-1]) >= hi * (1 - pct / 100)


def volume_trending_up(volume: pd.Series, days: int = 3) -> bool:
    """True if volume is higher than the prior `days` average."""
    if len(volume) < days + 1:
        return False
    recent_avg = float(volume.iloc[-days-1:-1].mean())
    return float(volume.iloc[-1]) > recent_avg


def gap_up(df: pd.DataFrame, pct: float = 1.0) -> bool:
    if len(df) < 2:
        return False
    prev_close = float(df["Close"].iloc[-2])
    today_open = float(df["Open"].iloc[-1])
    return (today_open - prev_close) / prev_close * 100 >= pct


def resistance_break(close: pd.Series, days: int = 50) -> bool:
    """Price breaks above the high of the last `days` period."""
    if len(close) < days + 1:
        return False
    prev_high = float(close.iloc[-days-1:-1].max())
    return float(close.iloc[-1]) > prev_high


# ══════════════════════════════════════════════════════════════
# BACKTESTER  (simple forward-return analysis)
# ══════════════════════════════════════════════════════════════

def simple_backtest(df: pd.DataFrame, signal_dates: list,
                    hold_days: int = 10) -> dict:
    """
    Given a list of past signal dates, compute avg forward return
    over hold_days.  Returns dict with stats.
    """
    if not signal_dates or df.empty:
        return {}
    close = df["Close"].squeeze()
    returns = []
    for sig_date in signal_dates:
        try:
            idx = close.index.get_indexer([sig_date], method="nearest")[0]
            if idx < 0 or idx + hold_days >= len(close):
                continue
            entry = float(close.iloc[idx])
            exit_ = float(close.iloc[idx + hold_days])
            ret   = (exit_ - entry) / entry * 100
            returns.append(ret)
        except Exception:
            continue
    if not returns:
        return {}
    arr = np.array(returns)
    return {
        "signals":    len(returns),
        "avg_return": round(float(arr.mean()), 2),
        "win_rate":   round(float((arr > 0).mean() * 100), 1),
        "max_win":    round(float(arr.max()), 2),
        "max_loss":   round(float(arr.min()), 2),
        "hold_days":  hold_days,
    }


def find_historical_signals_macd(close: pd.Series, volume: pd.Series,
                                  rsi_max: float = 70, vol_mult: float = 1.3) -> list:
    """Replay MACD cross logic over history → return signal dates."""
    dates = []
    if len(close) < 35:
        return dates
    ema12 = calc_ema(close, 12)
    ema26 = calc_ema(close, 26)
    macd  = ema12 - ema26
    sig   = calc_ema(macd, 9)
    hist  = macd - sig
    sma50 = calc_sma(close, 50)
    avg_v = volume.rolling(20).mean()

    for i in range(35, len(close) - 1):
        # Fresh cross: hist was negative, now positive
        if hist.iloc[i-1] <= 0 and hist.iloc[i] > 0:
            if close.iloc[i] > sma50.iloc[i]:
                rsi = calc_rsi(close.iloc[:i+1])
                if rsi < rsi_max:
                    vr = volume.iloc[i] / avg_v.iloc[i] if avg_v.iloc[i] > 0 else 0
                    if vr >= vol_mult:
                        dates.append(close.index[i])
    return dates


def find_historical_signals_hvb(close: pd.Series, volume: pd.Series,
                                  vol_mult: float = 2.0) -> list:
    """Replay high-volume breakout over history."""
    dates = []
    sma50 = calc_sma(close, 50)
    avg_v = volume.rolling(20).mean()
    for i in range(51, len(close) - 1):
        hi20 = close.iloc[max(0,i-20):i].max()
        if close.iloc[i] > hi20 and close.iloc[i] > sma50.iloc[i]:
            vr = volume.iloc[i] / avg_v.iloc[i] if avg_v.iloc[i] > 0 else 0
            if vr >= vol_mult:
                rsi = calc_rsi(close.iloc[:i+1])
                if rsi > 60:
                    dates.append(close.index[i])
    return dates


# ══════════════════════════════════════════════════════════════
# CHART BUILDER
# ══════════════════════════════════════════════════════════════

def build_breakout_chart(df: pd.DataFrame, ticker: str,
                          show_bb: bool = True, show_macd: bool = True,
                          show_volume: bool = True) -> go.Figure:
    """Rich multi-panel chart: candlestick + indicators + volume."""
    n = min(120, len(df))
    df_p = df.iloc[-n:].copy()
    close  = df_p["Close"].squeeze()
    volume = df_p["Volume"].squeeze()

    rows = 1 + int(show_macd) + int(show_volume)
    row_heights = [0.55] + ([0.25] if show_macd else []) + ([0.20] if show_volume else [])
    subplot_titles = [ticker] + (["MACD"] if show_macd else []) + (["Volume"] if show_volume else [])

    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True,
                        row_heights=row_heights, vertical_spacing=0.03,
                        subplot_titles=subplot_titles)

    # ── Candlestick ──
    fig.add_trace(go.Candlestick(
        x=df_p.index, open=df_p["Open"].squeeze(),
        high=df_p["High"].squeeze(), low=df_p["Low"].squeeze(),
        close=close,
        increasing_line_color=ACCENT_GREEN, decreasing_line_color=ACCENT_RED,
        name="Price", showlegend=False,
    ), row=1, col=1)

    # SMAs
    sma20 = calc_sma(close, 20)
    sma50 = calc_sma(close, 50)
    sma200= calc_sma(close, 200) if len(close) >= 200 else pd.Series(dtype=float)
    ema20 = calc_ema(close, 20)

    fig.add_trace(go.Scatter(x=df_p.index, y=ema20,  line=dict(color=GOLD, width=1.2, dash="dot"), name="EMA20"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_p.index, y=sma50,  line=dict(color=ACCENT_BLUE, width=1.2), name="SMA50"), row=1, col=1)
    if not sma200.empty:
        fig.add_trace(go.Scatter(x=df_p.index, y=sma200, line=dict(color="#A78BFA", width=1.0), name="SMA200"), row=1, col=1)

    # Bollinger Bands
    if show_bb:
        bb_up, bb_mid, bb_lo, _ = calc_bollinger(close)
        fig.add_trace(go.Scatter(x=df_p.index, y=bb_up,
            line=dict(color=GOLD, width=0.8, dash="dot"),
            fill=None, name="BB Upper"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_p.index, y=bb_lo,
            line=dict(color=GOLD, width=0.8, dash="dot"),
            fill="tonexty", fillcolor=f"{GOLD}08", name="BB Lower"), row=1, col=1)

    # ── MACD ──
    if show_macd:
        mr = 2
        ema12 = calc_ema(close, 12)
        ema26 = calc_ema(close, 26)
        macd  = ema12 - ema26
        sig_l = calc_ema(macd, 9)
        hist  = macd - sig_l
        colors = [ACCENT_GREEN if v >= 0 else ACCENT_RED for v in hist]
        fig.add_trace(go.Bar(x=df_p.index, y=hist, marker_color=colors,
                             name="MACD Hist", showlegend=False), row=mr, col=1)
        fig.add_trace(go.Scatter(x=df_p.index, y=macd,
            line=dict(color=GOLD, width=1.2), name="MACD"), row=mr, col=1)
        fig.add_trace(go.Scatter(x=df_p.index, y=sig_l,
            line=dict(color="#FB923C", width=1.0), name="Signal"), row=mr, col=1)
        fig.add_hline(y=0, line_color=BORDER_COLOR, line_width=0.5, row=mr, col=1)

    # ── Volume ──
    if show_volume:
        vr = rows
        avg_v = volume.rolling(20).mean()
        vol_colors = [ACCENT_GREEN if float(volume.iloc[i]) >= float(avg_v.iloc[i] or 0)
                      else ACCENT_RED for i in range(len(volume))]
        fig.add_trace(go.Bar(x=df_p.index, y=volume, marker_color=vol_colors,
                             name="Volume", showlegend=False), row=vr, col=1)
        fig.add_trace(go.Scatter(x=df_p.index, y=avg_v,
            line=dict(color=GOLD, width=1.0, dash="dot"),
            name="Avg Vol"), row=vr, col=1)

    fig.update_layout(
        paper_bgcolor=BG_CARD, plot_bgcolor=BG_PANEL,
        font_color=TEXT_PRIMARY, height=520,
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.01,
                    bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
        xaxis_rangeslider_visible=False,
    )
    for i in range(1, rows + 1):
        fig.update_xaxes(gridcolor=BORDER_COLOR, row=i, col=1, showgrid=False)
        fig.update_yaxes(gridcolor=BORDER_COLOR, row=i, col=1)

    return fig


# ══════════════════════════════════════════════════════════════
# SHARED UI HELPERS
# ══════════════════════════════════════════════════════════════

def _backtest_card(bt: dict, label: str = "Backtest"):
    if not bt:
        return
    win_color = ACCENT_GREEN if bt["win_rate"] >= 60 else (GOLD if bt["win_rate"] >= 50 else ACCENT_RED)
    ret_color = ACCENT_GREEN if bt["avg_return"] >= 0 else ACCENT_RED
    st.markdown(f"""
    <div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-left:3px solid {GOLD};
                border-radius:8px;padding:14px 18px;margin-top:12px">
        <div style="color:{GOLD};font-size:11px;font-weight:600;text-transform:uppercase;
                    letter-spacing:1px;margin-bottom:10px">📊 {label} ({bt['signals']} signals · {bt['hold_days']}d hold)</div>
        <div style="display:flex;gap:24px;flex-wrap:wrap">
            <div>
                <div style="color:{TEXT_MUTED};font-size:10px;text-transform:uppercase">Avg Return</div>
                <div style="color:{ret_color};font-size:20px;font-weight:700;font-family:'Cormorant Garamond',serif">
                    {bt['avg_return']:+.2f}%</div>
            </div>
            <div>
                <div style="color:{TEXT_MUTED};font-size:10px;text-transform:uppercase">Win Rate</div>
                <div style="color:{win_color};font-size:20px;font-weight:700;font-family:'Cormorant Garamond',serif">
                    {bt['win_rate']:.0f}%</div>
            </div>
            <div>
                <div style="color:{TEXT_MUTED};font-size:10px;text-transform:uppercase">Best</div>
                <div style="color:{ACCENT_GREEN};font-size:18px;font-weight:600">+{bt['max_win']:.1f}%</div>
            </div>
            <div>
                <div style="color:{TEXT_MUTED};font-size:10px;text-transform:uppercase">Worst</div>
                <div style="color:{ACCENT_RED};font-size:18px;font-weight:600">{bt['max_loss']:.1f}%</div>
            </div>
        </div>
        <div style="color:{TEXT_MUTED};font-size:10px;margin-top:8px">
            ⚠️ Backtest uses 1yr daily data · Past performance ≠ future results
        </div>
    </div>""", unsafe_allow_html=True)


def _top_pick_banner(ticker: str, price: float, chg: float, score: int, label: str = "Top Pick"):
    chg_color = ACCENT_GREEN if chg >= 0 else ACCENT_RED
    st.markdown(f"""
    <div style="background:linear-gradient(135deg,{BG_CARD},{BG_PANEL});
                border:1px solid {GOLD}55;border-left:4px solid {GOLD};
                border-radius:8px;padding:14px 20px;margin-bottom:16px">
        <div style="color:{TEXT_MUTED};font-size:10px;text-transform:uppercase;letter-spacing:1.5px">
            🏆 {label}</div>
        <div style="display:flex;align-items:baseline;gap:12px;margin-top:4px;flex-wrap:wrap">
            <span style="color:{GOLD};font-size:28px;font-family:'Cormorant Garamond',serif;font-weight:700">{ticker}</span>
            <span style="color:{TEXT_PRIMARY};font-size:18px">${price:.2f}</span>
            <span style="color:{chg_color};font-size:14px;font-weight:600">{chg:+.2f}%</span>
            <span style="color:{TEXT_MUTED};font-size:13px">Signal Score: {score}/100</span>
        </div>
    </div>""", unsafe_allow_html=True)


def _scanner_idle(icon, title, subtitle, criteria_list):
    items = "".join(f'<li style="margin-bottom:4px">{c}</li>' for c in criteria_list)
    st.markdown(f"""
    <div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:8px;
                padding:30px;text-align:center;color:{TEXT_MUTED}">
        <div style="font-size:40px;margin-bottom:12px">{icon}</div>
        <div style="font-size:17px;color:{TEXT_PRIMARY};margin-bottom:6px;
                    font-family:'Cormorant Garamond',serif">{title}</div>
        <div style="font-size:12px;color:{TEXT_MUTED};margin-bottom:16px">{subtitle}</div>
    </div>
    <div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:8px;
                padding:16px 20px;margin-top:12px">
        <div style="color:{GOLD};font-size:11px;font-weight:600;text-transform:uppercase;
                    letter-spacing:1px;margin-bottom:8px">Core Conditions</div>
        <ul style="color:{TEXT_PRIMARY};font-size:13px;line-height:2.0;margin:0;
                   padding-left:18px">{items}</ul>
    </div>""", unsafe_allow_html=True)


def _run_buttons():
    col1, col2, col3 = st.columns([1, 1, 4])
    with col1:
        run = st.button("▶ Run Scan", use_container_width=True)
    with col2:
        if st.button("🔄 Clear Cache", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    return run


def _sidebar_universe(label="Tech Hacker"):
    with st.sidebar:
        st.markdown(f'<div style="color:{GOLD};font-size:12px;font-weight:600;margin:16px 0 8px">⚙️ {label} Filters</div>',
                    unsafe_allow_html=True)
    return None  # filters set inline per scanner


def _fetch_spy():
    df = get_price_history("SPY", period="1y")
    return df["Close"].squeeze() if not df.empty else pd.Series()


# ══════════════════════════════════════════════════════════════
# 1. MACD POWER CROSS
# ══════════════════════════════════════════════════════════════

def scan_macd_cross(tickers, rsi_max, vol_mult, price_min, price_max, run_bt, bt_hold):
    results  = []
    progress = st.progress(0)
    status   = st.empty()

    for i, ticker in enumerate(tickers):
        progress.progress((i + 1) / len(tickers))
        status.markdown(f'<div style="color:{TEXT_MUTED};font-size:12px">Scanning {ticker}…</div>',
                        unsafe_allow_html=True)
        try:
            df = get_price_history(ticker, period="1y")
            if df.empty or len(df) < 60:
                continue
            close  = df["Close"].squeeze()
            volume = df["Volume"].squeeze()
            price  = float(close.iloc[-1])

            if not (price_min <= price <= price_max):
                continue

            sma50 = calc_sma(close, 50)
            if price < float(sma50.iloc[-1]):
                continue

            # MACD components
            ema12 = calc_ema(close, 12)
            ema26 = calc_ema(close, 26)
            macd  = ema12 - ema26
            sig_l = calc_ema(macd, 9)
            hist  = macd - sig_l

            # Fresh cross: histogram was ≤ 0 yesterday, > 0 today
            if not (float(hist.iloc[-2]) <= 0 and float(hist.iloc[-1]) > 0):
                continue

            rsi = calc_rsi(close)
            if rsi >= rsi_max:
                continue

            vr = vol_above_n_avg(volume, 20, vol_mult)
            if vr < vol_mult:
                continue

            rsi_up = rsi_rising(close)
            prev   = float(close.iloc[-2])
            chg    = (price - prev) / prev * 100
            atr_p  = calc_atr(df)

            # Optional: gap up
            gap = gap_up(df, 0.5)

            # Score
            score = 0
            if float(hist.iloc[-1]) > 0:            score += 25
            if price > float(sma50.iloc[-1]):        score += 20
            if 55 <= rsi < 70:                       score += 20
            elif rsi < 55:                           score += 10
            if vr >= 2.0:                            score += 20
            elif vr >= vol_mult:                     score += 12
            if rsi_up:                               score += 10
            if gap:                                  score += 5
            score = min(score, 100)

            # Backtest for this ticker
            bt = {}
            if run_bt:
                sig_dates = find_historical_signals_macd(close, volume, rsi_max, vol_mult)
                bt = simple_backtest(df, sig_dates, bt_hold)

            results.append({
                "Ticker":        ticker,
                "Price":         round(price, 2),
                "Change %":      round(chg, 2),
                "RSI":           round(rsi, 1),
                "MACD Hist":     round(float(hist.iloc[-1]), 4),
                "Vol Ratio":     round(vr, 2),
                "RSI Rising":    "✅" if rsi_up else "—",
                "Gap Up":        "✅" if gap else "—",
                "ATR %":         round(atr_p, 2),
                ">50 SMA":       "✅",
                "Score":         score,
                "_bt":           bt,
                "_ticker":       ticker,
            })
        except Exception:
            continue

    progress.empty(); status.empty()
    df_out = pd.DataFrame(results)
    if not df_out.empty:
        df_out = df_out.sort_values("Score", ascending=False).reset_index(drop=True)
    return df_out


def render_macd_cross():
    section_header("📡", "MACD Power Cross",
                   "Fresh MACD bullish crossover · Momentum ignition · Volume confirmed · RSI < 70")

    with st.sidebar:
        st.markdown(f'<div style="color:{GOLD};font-size:12px;font-weight:600;margin:16px 0 8px">⚙️ MACD Cross Filters</div>',
                    unsafe_allow_html=True)
        rsi_max  = st.slider("Max RSI (not overbought)", 60, 80, 70)
        vol_mult = st.slider("Min Volume Multiplier", 1.0, 4.0, 1.25, 0.05)
        price_min= st.number_input("Min Price ($)", 1.0, 100.0, 10.0)
        price_max= st.number_input("Max Price ($)", 50.0, 5000.0, 3000.0)
        run_bt   = st.checkbox("Run Backtest (slower)", value=True)
        bt_hold  = st.slider("Backtest Hold Days", 3, 30, 10)
        n        = st.slider("Universe Size", 20, len(SP500_SAMPLE), 200, 10)

    run = _run_buttons()

    if run:
        df = scan_macd_cross(SP500_SAMPLE[:n], rsi_max, vol_mult, price_min, price_max, run_bt, bt_hold)
        if df.empty:
            empty_state("No fresh MACD crosses found. Try lowering volume requirement or expanding universe.")
            return

        top = df.iloc[0]
        _top_pick_banner(top["Ticker"], top["Price"], top["Change %"], top["Score"],
                         "Strongest MACD Cross Signal")

        col1, col2, col3, col4 = st.columns(4)
        with col1: metric_card("Signals Found", str(len(df)), color=GOLD)
        with col2: metric_card("Avg RSI",  f"{df['RSI'].mean():.1f}", color=ACCENT_BLUE)
        with col3: metric_card("Avg Vol Ratio", f"{df['Vol Ratio'].mean():.2f}×", color=ACCENT_GREEN)
        with col4: metric_card("Avg Score", f"{df['Score'].mean():.0f}/100", color=GOLD)

        # Backtest summary for top pick
        if run_bt and top.get("_bt"):
            _backtest_card(top["_bt"], f"{top['Ticker']} Historical Signal Performance")

        # Chart top pick
        with st.expander(f"📈 Chart: {top['Ticker']}", expanded=True):
            df_c = get_price_history(top["Ticker"], period="6mo")
            if not df_c.empty:
                st.plotly_chart(build_breakout_chart(df_c, top["Ticker"],
                                show_bb=False, show_macd=True, show_volume=True),
                                use_container_width=True)

        display_df = df.drop(columns=["_bt","_ticker"], errors="ignore")
        render_results_table(display_df)
    else:
        _scanner_idle("📡", "MACD Power Cross",
                      "Earliest phase of breakout — momentum ignition signal", [
            "MACD line crosses above signal line (fresh bullish cross today)",
            "MACD histogram turns positive (was ≤ 0 yesterday)",
            "Price above 50 SMA",
            f"Volume ≥ {1.3}× 20-day average",
            "RSI rising but < 70 (not overbought)",
        ])


# ══════════════════════════════════════════════════════════════
# 2. TREND STACK BREAKOUT
# ══════════════════════════════════════════════════════════════

def scan_trend_stack(tickers, rsi_min, rsi_max, vol_mult, within_pct, rs_min, price_min):
    spy_close = _fetch_spy()
    results   = []
    progress  = st.progress(0)
    status    = st.empty()

    for i, ticker in enumerate(tickers):
        progress.progress((i + 1) / len(tickers))
        status.markdown(f'<div style="color:{TEXT_MUTED};font-size:12px">Scanning {ticker}…</div>',
                        unsafe_allow_html=True)
        try:
            df = get_price_history(ticker, period="1y")
            if df.empty or len(df) < 210:
                continue

            close  = df["Close"].squeeze()
            volume = df["Volume"].squeeze()
            price  = float(close.iloc[-1])
            if price < price_min:
                continue

            ema20  = calc_ema(close, 20)
            sma50  = calc_sma(close, 50)
            sma200 = calc_sma(close, 200)

            e20 = float(ema20.iloc[-1])
            s50 = float(sma50.iloc[-1])
            s200= float(sma200.iloc[-1])

            # Full trend stack: price > EMA20 > SMA50 > SMA200
            if not (price > e20 > s50 > s200):
                continue

            # 200 SMA sloping up
            if not sma200_sloping_up(close):
                continue

            rsi = calc_rsi(close)
            if not (rsi_min <= rsi <= rsi_max):
                continue

            if not price_within_pct_of_high(close, 20, within_pct):
                continue

            vr = vol_above_n_avg(volume, 20, vol_mult)
            if vr < vol_mult:
                continue

            rs = calc_relative_strength(close, spy_close) if not spy_close.empty else 1.0
            if rs < rs_min:
                continue

            atr_p   = calc_atr(df)
            atr_exp = atr_expanding(df)
            prev    = float(close.iloc[-2])
            chg     = (price - prev) / prev * 100
            is_20dh = is_20d_high(close)

            score = 0
            if price > e20 > s50 > s200:  score += 30
            if rsi_min <= rsi <= rsi_max:  score += 20
            if vr >= 2.0:                  score += 15
            elif vr >= vol_mult:           score += 10
            if is_20dh:                    score += 15
            if rs >= 1.10:                 score += 10
            elif rs >= rs_min:             score += 6
            if atr_exp:                    score += 10
            score = min(score, 100)

            results.append({
                "Ticker":     ticker,
                "Price":      round(price, 2),
                "Change %":   round(chg, 2),
                "RSI":        round(rsi, 1),
                "EMA20":      round(e20, 2),
                "SMA50":      round(s50, 2),
                "SMA200":     round(s200, 2),
                "Stack":      "✅ Full" if price > e20 > s50 > s200 else "Partial",
                "200 Slope":  "✅ Up",
                "20D High":   "✅" if is_20dh else "—",
                "Vol Ratio":  round(vr, 2),
                "RS vs SPY":  round(rs, 3),
                "ATR %":      round(atr_p, 2),
                "ATR Expand": "✅" if atr_exp else "—",
                "Score":      score,
            })
        except Exception:
            continue

    progress.empty(); status.empty()
    df_out = pd.DataFrame(results)
    if not df_out.empty:
        df_out = df_out.sort_values("Score", ascending=False).reset_index(drop=True)
    return df_out


def render_trend_stack():
    section_header("🏛", "Trend Stack",
                   "Price > EMA20 > SMA50 > SMA200 · Institutional trend alignment · 200 SMA sloping up")

    with st.sidebar:
        st.markdown(f'<div style="color:{GOLD};font-size:12px;font-weight:600;margin:16px 0 8px">⚙️ Trend Stack Filters</div>',
                    unsafe_allow_html=True)
        rsi_min, rsi_max = st.slider("RSI Range", 40, 80, (55, 68))
        vol_mult  = st.slider("Min Volume Multiplier", 1.0, 4.0, 1.25, 0.05)
        within_pct= st.slider("Within % of 20D High", 1.0, 10.0, 3.0, 0.5)
        rs_min    = st.slider("Min RS vs SPY", 0.90, 1.30, 1.05, 0.01)
        price_min = st.number_input("Min Price ($)", 5.0, 100.0, 15.0)
        n         = st.slider("Universe Size", 20, len(SP500_SAMPLE), 200, 10)

    run = _run_buttons()

    if run:
        df = scan_trend_stack(SP500_SAMPLE[:n], rsi_min, rsi_max, vol_mult, within_pct, rs_min, price_min)
        if df.empty:
            empty_state("No trend stack setups found. Requires 200+ days of data. Try loosening RSI or RS filters.")
            return

        top = df.iloc[0]
        _top_pick_banner(top["Ticker"], top["Price"], top["Change %"], top["Score"],
                         "Strongest Trend Stack Signal")

        col1, col2, col3, col4 = st.columns(4)
        with col1: metric_card("Setups Found", str(len(df)), color=GOLD)
        with col2: metric_card("Avg RSI", f"{df['RSI'].mean():.1f}", color=ACCENT_BLUE)
        with col3: metric_card("Avg RS vs SPY", f"{df['RS vs SPY'].mean():.3f}", color=ACCENT_GREEN)
        with col4: metric_card("Full Stack", str((df["Stack"] == "✅ Full").sum()), color=GOLD)

        with st.expander(f"📈 Chart: {top['Ticker']}", expanded=True):
            df_c = get_price_history(top["Ticker"], period="6mo")
            if not df_c.empty:
                st.plotly_chart(build_breakout_chart(df_c, top["Ticker"],
                                show_bb=True, show_macd=True, show_volume=True),
                                use_container_width=True)

        render_results_table(df)
    else:
        _scanner_idle("🏛", "Trend Stack Breakout",
                      "When all moving averages align, breakouts have highest continuation probability", [
            "Price > 20 EMA > 50 SMA > 200 SMA (full institutional stack)",
            "200 SMA sloping upward (macro trend confirmed)",
            "RSI between 55–68 (momentum, not extended)",
            "Price within 3% of 20-day high",
            f"Volume ≥ 1.5× 20-day average",
            "Relative Strength vs SPY > 1.05",
        ])


# ══════════════════════════════════════════════════════════════
# 3. VOLATILITY SQUEEZE
# ══════════════════════════════════════════════════════════════

def scan_squeeze(tickers, price_min, price_max, require_macd_up, require_vol_trend):
    results  = []
    progress = st.progress(0)
    status   = st.empty()

    for i, ticker in enumerate(tickers):
        progress.progress((i + 1) / len(tickers))
        status.markdown(f'<div style="color:{TEXT_MUTED};font-size:12px">Scanning {ticker}…</div>',
                        unsafe_allow_html=True)
        try:
            df = get_price_history(ticker, period="6mo")
            if df.empty or len(df) < 55:
                continue
            close  = df["Close"].squeeze()
            volume = df["Volume"].squeeze()
            price  = float(close.iloc[-1])

            if not (price_min <= price <= price_max):
                continue

            sma50 = calc_sma(close, 50)
            if price < float(sma50.iloc[-1]):
                continue

            # Squeeze: BB inside KC
            in_squeeze = is_squeeze(df)
            # BB width at 20-day low
            bb_compressed = bb_width_20d_low(close)

            # Need at least one squeeze condition
            if not (in_squeeze or bb_compressed):
                continue

            # Momentum turning up
            _, _, hist_vals = calc_macd(close)
            rsi = calc_rsi(close)
            macd_up = float(hist_vals) > 0 if not isinstance(hist_vals, pd.Series) else float(hist_vals.iloc[-1]) > 0
            rsi_up  = rsi_rising(close)

            if require_macd_up and not macd_up:
                continue

            # Volume increasing vs prior 3 days
            vol_trend = volume_trending_up(volume, 3)
            if require_vol_trend and not vol_trend:
                continue

            # Price breaking above upper BB = squeeze firing
            firing = price_above_upper_bb(close)
            _, _, _, bb_w = calc_bollinger(close)
            bb_width_now  = round(float(bb_w.iloc[-1]), 2)

            prev = float(close.iloc[-2])
            chg  = (price - prev) / prev * 100
            atr_p= calc_atr(df)
            vr   = vol_above_n_avg(volume)

            score = 0
            if in_squeeze:     score += 30
            if bb_compressed:  score += 20
            if macd_up:        score += 20
            if rsi_up:         score += 10
            if vol_trend:      score += 10
            if firing:         score += 10  # bonus: squeeze already firing
            score = min(score, 100)

            results.append({
                "Ticker":       ticker,
                "Price":        round(price, 2),
                "Change %":     round(chg, 2),
                "RSI":          round(rsi, 1),
                "BB in KC":     "✅" if in_squeeze else "—",
                "BB Compressed":"✅" if bb_compressed else "—",
                "BB Width %":   bb_width_now,
                "MACD Up":      "✅" if macd_up else "—",
                "Vol Trending":  "✅" if vol_trend else "—",
                "Firing!":      "🔥" if firing else "—",
                "Vol Ratio":    round(vr, 2),
                "ATR %":        round(atr_p, 2),
                "Score":        score,
            })
        except Exception:
            continue

    progress.empty(); status.empty()
    df_out = pd.DataFrame(results)
    if not df_out.empty:
        df_out = df_out.sort_values("Score", ascending=False).reset_index(drop=True)
    return df_out


def render_squeeze():
    section_header("🌀", "Volatility Squeeze",
                   "Bollinger Bands inside Keltner Channels · Compression → Expansion · Coiled spring setups")

    with st.sidebar:
        st.markdown(f'<div style="color:{GOLD};font-size:12px;font-weight:600;margin:16px 0 8px">⚙️ Squeeze Filters</div>',
                    unsafe_allow_html=True)
        price_min        = st.number_input("Min Price ($)", 5.0, 100.0, 10.0)
        price_max        = st.number_input("Max Price ($)", 50.0, 5000.0, 3000.0)
        require_macd_up  = st.checkbox("Require MACD bullish", value=True)
        require_vol_trend= st.checkbox("Require volume trending up", value=True)
        n                = st.slider("Universe Size", 20, len(SP500_SAMPLE), 200, 10)

    run = _run_buttons()

    if run:
        df = scan_squeeze(SP500_SAMPLE[:n], price_min, price_max, require_macd_up, require_vol_trend)
        if df.empty:
            empty_state("No squeeze setups found. Uncheck MACD/volume requirements to widen results.")
            return

        top = df.iloc[0]
        _top_pick_banner(top["Ticker"], top["Price"], top["Change %"], top["Score"],
                         "Tightest Squeeze — Most Coiled")

        col1, col2, col3, col4 = st.columns(4)
        with col1: metric_card("Setups Found", str(len(df)), color=GOLD)
        with col2: metric_card("BB in KC (true squeeze)", str((df["BB in KC"] == "✅").sum()), color=ACCENT_BLUE)
        with col3: metric_card("Already Firing", str((df["Firing!"] == "🔥").sum()), color=ACCENT_GREEN)
        with col4: metric_card("MACD Up", str((df["MACD Up"] == "✅").sum()), color=GOLD)

        with st.expander(f"📈 Chart: {top['Ticker']}", expanded=True):
            df_c = get_price_history(top["Ticker"], period="6mo")
            if not df_c.empty:
                st.plotly_chart(build_breakout_chart(df_c, top["Ticker"],
                                show_bb=True, show_macd=True, show_volume=True),
                                use_container_width=True)

        st.markdown(f"""
        <div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-left:3px solid {GOLD};
                    border-radius:6px;padding:10px 14px;margin-bottom:12px;font-size:12px;color:{TEXT_MUTED}">
            💡 <b style="color:{GOLD}">Reading the table:</b>
            <b>BB in KC</b> = true TTM Squeeze (Bollinger inside Keltner) ·
            <b>BB Compressed</b> = width at 20-day low ·
            <b>Firing!</b> = price already breaking above upper BB — squeeze releasing
        </div>""", unsafe_allow_html=True)

        render_results_table(df)
    else:
        _scanner_idle("🌀", "Volatility Squeeze",
                      "Finds coiled-spring setups before explosive expansion moves", [
            "Bollinger Bands width at 20-day low (compression)",
            "Keltner Channels outside Bollinger Bands (TTM Squeeze condition)",
            "Price above 50 SMA",
            "MACD or RSI turning up (momentum igniting)",
            "Volume increasing vs prior 3 days",
        ])


# ══════════════════════════════════════════════════════════════
# 4. HIGH-VOLUME BREAKOUT
# ══════════════════════════════════════════════════════════════

def scan_hvb(tickers, vol_mult, rsi_min, price_min, price_max, run_bt, bt_hold):
    results  = []
    progress = st.progress(0)
    status   = st.empty()

    for i, ticker in enumerate(tickers):
        progress.progress((i + 1) / len(tickers))
        status.markdown(f'<div style="color:{TEXT_MUTED};font-size:12px">Scanning {ticker}…</div>',
                        unsafe_allow_html=True)
        try:
            df = get_price_history(ticker, period="1y")
            if df.empty or len(df) < 55:
                continue
            close  = df["Close"].squeeze()
            volume = df["Volume"].squeeze()
            price  = float(close.iloc[-1])

            if not (price_min <= price <= price_max):
                continue

            sma50 = calc_sma(close, 50)
            if price < float(sma50.iloc[-1]):
                continue

            rsi = calc_rsi(close)
            if rsi < rsi_min:
                continue

            # Price breaks 20-day OR 50-day high
            hi20 = float(close.iloc[-21:-1].max()) if len(close) > 21 else float(close.max())
            hi50 = float(close.iloc[-51:-1].max()) if len(close) > 51 else float(close.max())
            breaks_20 = price > hi20
            breaks_50 = price > hi50

            if not (breaks_20 or breaks_50):
                continue

            vr = vol_above_n_avg(volume, 20, vol_mult)
            if vr < vol_mult:
                continue

            # Candle close above breakout level (close > open is a strong close)
            strong_close = float(df["Close"].iloc[-1]) > float(df["Open"].iloc[-1])
            gap_pct      = gap_up(df, 1.0)

            # OBV trend
            obv    = calc_obv(close, volume)
            obv_up = float(obv.iloc[-1]) > float(obv.iloc[-5])

            prev = float(close.iloc[-2])
            chg  = (price - prev) / prev * 100
            atr_p= calc_atr(df)

            bt = {}
            if run_bt:
                sig_dates = find_historical_signals_hvb(close, volume, vol_mult)
                bt = simple_backtest(df, sig_dates, bt_hold)

            score = 0
            if breaks_20:    score += 20
            if breaks_50:    score += 15
            if vr >= 3.0:    score += 25
            elif vr >= vol_mult: score += 15
            if rsi >= 65:    score += 15
            elif rsi >= rsi_min: score += 8
            if strong_close: score += 10
            if gap_pct:      score += 10
            if obv_up:       score += 5
            score = min(score, 100)

            results.append({
                "Ticker":      ticker,
                "Price":       round(price, 2),
                "Change %":    round(chg, 2),
                "RSI":         round(rsi, 1),
                "Vol Ratio":   round(vr, 2),
                "Breaks 20D":  "✅" if breaks_20 else "—",
                "Breaks 50D":  "✅" if breaks_50 else "—",
                "Strong Close":"✅" if strong_close else "—",
                "Gap Up":      "✅" if gap_pct else "—",
                "OBV Rising":  "✅" if obv_up else "—",
                "ATR %":       round(atr_p, 2),
                "Score":       score,
                "_bt":         bt,
                "_ticker":     ticker,
            })
        except Exception:
            continue

    progress.empty(); status.empty()
    df_out = pd.DataFrame(results)
    if not df_out.empty:
        df_out = df_out.sort_values("Score", ascending=False).reset_index(drop=True)
    return df_out


def render_hvb():
    section_header("🐋", "High-Volume Breakout",
                   "Institutional footprint · Price breaks 20/50D high · Volume ≥ 2× · OBV confirmation")

    with st.sidebar:
        st.markdown(f'<div style="color:{GOLD};font-size:12px;font-weight:600;margin:16px 0 8px">⚙️ HVB Filters</div>',
                    unsafe_allow_html=True)
        vol_mult = st.slider("Min Volume Multiplier", 1.0, 6.0, 1.25, 0.05)
        rsi_min  = st.slider("Min RSI", 40, 75, 60)
        price_min= st.number_input("Min Price ($)", 5.0, 100.0, 10.0)
        price_max= st.number_input("Max Price ($)", 50.0, 5000.0, 3000.0)
        run_bt   = st.checkbox("Run Backtest (slower)", value=True)
        bt_hold  = st.slider("Backtest Hold Days", 3, 30, 10)
        n        = st.slider("Universe Size", 20, len(SP500_SAMPLE), 200, 10)

    run = _run_buttons()

    if run:
        df = scan_hvb(SP500_SAMPLE[:n], vol_mult, rsi_min, price_min, price_max, run_bt, bt_hold)
        if df.empty:
            empty_state("No high-volume breakouts found. Lower RSI minimum or volume multiplier.")
            return

        top = df.iloc[0]
        _top_pick_banner(top["Ticker"], top["Price"], top["Change %"], top["Score"],
                         "Strongest Institutional Breakout")

        col1, col2, col3, col4 = st.columns(4)
        with col1: metric_card("Breakouts Found", str(len(df)), color=GOLD)
        with col2: metric_card("Avg Vol Ratio", f"{df['Vol Ratio'].mean():.2f}×", color=ACCENT_GREEN)
        with col3: metric_card("50D Breaks", str((df["Breaks 50D"] == "✅").sum()), color=ACCENT_BLUE)
        with col4: metric_card("Avg Score", f"{df['Score'].mean():.0f}/100", color=GOLD)

        if run_bt and top.get("_bt"):
            _backtest_card(top["_bt"], f"{top['Ticker']} HVB Historical Performance")

        with st.expander(f"📈 Chart: {top['Ticker']}", expanded=True):
            df_c = get_price_history(top["Ticker"], period="6mo")
            if not df_c.empty:
                st.plotly_chart(build_breakout_chart(df_c, top["Ticker"],
                                show_bb=False, show_macd=False, show_volume=True),
                                use_container_width=True)

        display_df = df.drop(columns=["_bt","_ticker"], errors="ignore")
        render_results_table(display_df)
    else:
        _scanner_idle("🐋", "High-Volume Breakout",
                      "Institutions leave footprints — volume spikes reveal big money moves", [
            "Price breaks above 20-day OR 50-day high",
            f"Volume ≥ 2× 20-day average (institutional participation)",
            "Price above 50 SMA",
            "RSI > 60 (momentum confirmed)",
            "Candle closes above breakout level (strong close)",
            "Optional: Gap-up > 1% · OBV rising",
        ])


# ══════════════════════════════════════════════════════════════
# 5. MULTI-FACTOR BREAKOUT
# ══════════════════════════════════════════════════════════════

def scan_multifactor(tickers, rsi_min, rsi_max, vol_mult, rs_min,
                     atr_req, within_pct, price_min, price_max):
    spy_close = _fetch_spy()
    results   = []
    progress  = st.progress(0)
    status    = st.empty()

    for i, ticker in enumerate(tickers):
        progress.progress((i + 1) / len(tickers))
        status.markdown(f'<div style="color:{TEXT_MUTED};font-size:12px">Scanning {ticker}…</div>',
                        unsafe_allow_html=True)
        try:
            df = get_price_history(ticker, period="1y")
            if df.empty or len(df) < 210:
                continue
            close  = df["Close"].squeeze()
            volume = df["Volume"].squeeze()
            price  = float(close.iloc[-1])

            if not (price_min <= price <= price_max):
                continue

            sma50  = calc_sma(close, 50)
            sma200 = calc_sma(close, 200)
            s50    = float(sma50.iloc[-1])
            s200   = float(sma200.iloc[-1])

            if not (price > s50 > s200):
                continue

            rsi = calc_rsi(close)
            if not (rsi_min <= rsi <= rsi_max):
                continue

            _, _, hist_val = calc_macd(close)
            if float(hist_val) <= 0:
                continue

            vr = vol_above_n_avg(volume, 20, vol_mult)
            if vr < vol_mult:
                continue

            atr_p   = calc_atr(df)
            atr_exp = atr_expanding(df)
            if atr_req and not atr_exp:
                continue

            if not price_within_pct_of_high(close, 20, within_pct):
                continue

            # Resistance break (close above 20D high)
            hi20 = float(close.iloc[-21:-1].max()) if len(close) > 21 else price
            res_break = price > hi20

            rs = calc_relative_strength(close, spy_close) if not spy_close.empty else 1.0
            if rs < rs_min:
                continue

            is_20dh  = is_20d_high(close)
            rsi_up   = rsi_rising(close)
            prev     = float(close.iloc[-2])
            chg      = (price - prev) / prev * 100
            gap      = gap_up(df, 0.5)

            # Composite scoring — all 7 factors weighted
            score = 0
            if price > s50 > s200:      score += 20  # trend foundation
            if rsi_min <= rsi <= rsi_max: score += 15  # momentum sweet spot
            if float(hist_val) > 0:     score += 15  # MACD confirmation
            if vr >= 2.0:               score += 15
            elif vr >= vol_mult:        score += 10
            if atr_exp:                 score += 10  # volatility expanding
            if res_break or is_20dh:    score += 10  # breakout level
            if rs >= 1.10:              score += 10
            elif rs >= rs_min:          score += 6
            if gap:                     score += 5
            score = min(score, 100)

            # Count how many of the 7 core conditions are met
            conditions_met = sum([
                price > s50 > s200,
                rsi_min <= rsi <= rsi_max,
                float(hist_val) > 0,
                vr >= vol_mult,
                atr_exp,
                res_break or is_20dh,
                rs >= rs_min,
            ])

            results.append({
                "Ticker":       ticker,
                "Price":        round(price, 2),
                "Change %":     round(chg, 2),
                "RSI":          round(rsi, 1),
                "MACD Hist":    round(float(hist_val), 4),
                "Vol Ratio":    round(vr, 2),
                "RS vs SPY":    round(rs, 3),
                "ATR %":        round(atr_p, 2),
                "ATR Expand":   "✅" if atr_exp else "—",
                "Res Break":    "✅" if res_break else "—",
                "Gap Up":       "✅" if gap else "—",
                "Conditions":   f"{conditions_met}/7",
                "Score":        score,
            })
        except Exception:
            continue

    progress.empty(); status.empty()
    df_out = pd.DataFrame(results)
    if not df_out.empty:
        df_out = df_out.sort_values("Score", ascending=False).reset_index(drop=True)
    return df_out


def render_multifactor():
    section_header("🎯", "Multi-Factor Breakout",
                   "All signals agree · Trend + Momentum + Volume + Volatility · Highest conviction setups")

    with st.sidebar:
        st.markdown(f'<div style="color:{GOLD};font-size:12px;font-weight:600;margin:16px 0 8px">⚙️ Multi-Factor Filters</div>',
                    unsafe_allow_html=True)
        rsi_min, rsi_max = st.slider("RSI Range", 40, 80, (55, 68))
        vol_mult  = st.slider("Min Volume Multiplier", 1.0, 4.0, 1.25, 0.05)
        rs_min    = st.slider("Min RS vs SPY", 0.90, 1.30, 1.05, 0.01)
        within_pct= st.slider("Within % of 20D High", 1.0, 10.0, 2.0, 0.5)
        atr_req   = st.checkbox("Require ATR expanding", value=True)
        price_min = st.number_input("Min Price ($)", 5.0, 100.0, 10.0)
        price_max = st.number_input("Max Price ($)", 50.0, 5000.0, 3000.0)
        n         = st.slider("Universe Size", 20, len(SP500_SAMPLE), 200, 10)

    run = _run_buttons()

    if run:
        df = scan_multifactor(SP500_SAMPLE[:n], rsi_min, rsi_max, vol_mult,
                               rs_min, atr_req, within_pct, price_min, price_max)
        if df.empty:
            empty_state("No multi-factor setups found. This is the strictest scanner — try disabling ATR requirement or expanding universe.")
            return

        top = df.iloc[0]
        _top_pick_banner(top["Ticker"], top["Price"], top["Change %"], top["Score"],
                         "Highest Conviction Breakout — All Signals Agree")

        col1, col2, col3, col4, col5 = st.columns(5)
        with col1: metric_card("Elite Setups", str(len(df)), color=GOLD)
        with col2: metric_card("Avg RSI", f"{df['RSI'].mean():.1f}", color=ACCENT_BLUE)
        with col3: metric_card("Avg RS", f"{df['RS vs SPY'].mean():.3f}", color=ACCENT_GREEN)
        with col4: metric_card("7/7 Conditions", str((df["Conditions"] == "7/7").sum()), color=GOLD)
        with col5: metric_card("Avg Score", f"{df['Score'].mean():.0f}/100", color=ACCENT_BLUE)

        # Conditions breakdown chart
        if len(df) >= 2:
            with st.expander("📊 Conditions Distribution", expanded=False):
                cond_counts = df["Conditions"].value_counts().sort_index()
                fig = go.Figure(go.Bar(
                    x=cond_counts.index.tolist(),
                    y=cond_counts.values.tolist(),
                    marker_color=[GOLD if c == "7/7" else ACCENT_BLUE for c in cond_counts.index],
                    text=cond_counts.values.tolist(),
                    textposition="outside",
                ))
                fig.update_layout(
                    paper_bgcolor=BG_CARD, plot_bgcolor=BG_PANEL,
                    font_color=TEXT_PRIMARY, height=180,
                    margin=dict(l=10,r=10,t=10,b=10),
                    xaxis=dict(gridcolor=BORDER_COLOR),
                    yaxis=dict(gridcolor=BORDER_COLOR),
                    showlegend=False,
                )
                st.plotly_chart(fig, use_container_width=True)

        with st.expander(f"📈 Chart: {top['Ticker']}", expanded=True):
            df_c = get_price_history(top["Ticker"], period="6mo")
            if not df_c.empty:
                st.plotly_chart(build_breakout_chart(df_c, top["Ticker"],
                                show_bb=True, show_macd=True, show_volume=True),
                                use_container_width=True)

        render_results_table(df)

        st.markdown(f"""
        <div style="background:{BG_PANEL};border:1px solid {GOLD}33;border-left:3px solid {GOLD};
                    border-radius:6px;padding:12px 16px;margin-top:16px;
                    color:{TEXT_MUTED};font-size:12px">
            <b style="color:{GOLD}">🎯 How to read Conditions X/7:</b>
            Each of the 7 core factors (Trend · RSI · MACD · Volume · ATR · Breakout · RS) scores as 1.
            7/7 = every single condition aligned. These are the rarest, highest-probability setups.
            Anything ≥ 6/7 is still a high-quality breakout candidate.
        </div>""", unsafe_allow_html=True)
    else:
        _scanner_idle("🎯", "Multi-Factor Breakout",
                      "The highest-quality breakout scanner — all 7 signals must agree", [
            "Price > 50 SMA > 200 SMA (trend foundation)",
            "RSI 55–68 (momentum sweet spot, not extended)",
            "MACD histogram > 0 (momentum confirmation)",
            "Volume ≥ 1.5× 20-day average (institutional participation)",
            "ATR rising (volatility expanding into breakout)",
            "Price within 2% of 20-day high (at resistance)",
            "Relative Strength vs SPY > 1.05 (leading the market)",
        ])
