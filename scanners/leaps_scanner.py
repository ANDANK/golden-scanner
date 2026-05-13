# pages/leaps_scanner.py — LEAPS Long-Term Directional Trades

import streamlit as st
import pandas as pd
from datetime import datetime
import time
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import *
from utils import *
from data_loader import (
    get_price_history, get_options_chain, get_options_error,
    find_best_expiry, pick_strike,
)


def scan_leaps(tickers, dte_min, delta_min, delta_max, iv_rank_max, price_min, price_max):

    diag = ScanDiagnostics()
    # LEAPS uses an open-ended DTE: dte_min upward
    cfg = OPTIONS_STRIKE_RANGES["LEAPS"]

    _scan_label = st.empty()
    _scan_prog  = st.progress(0)
    spy_df = get_price_history("SPY", period="12mo")
    spy_close = spy_df["Close"].squeeze() if not spy_df.empty else pd.Series()

    results = []

    for i, ticker in enumerate(tickers):
        _scan_label.markdown(f'<div style="color:#C9A84C;font-size:12px">🔍 Scanning {i+1} of {len(tickers)} — {ticker}</div>', unsafe_allow_html=True)
        _scan_prog.progress((i + 1) / len(tickers))
        diag.seen(ticker)
        time.sleep(0.25)   # throttle: ~4 tickers/sec — avoids Yahoo rate limit
        try:
            df = get_price_history(ticker, period="12mo")
            if df.empty or len(df) < 50:
                diag.skipped(ticker, "no price history"); continue

            close = df["Close"].squeeze()
            price = float(close.iloc[-1])
            if not (price_min <= price <= price_max):
                diag.skipped(ticker, "price out of range"); continue

            sma50  = float(calc_sma(close, 50).iloc[-1])
            sma200 = float(calc_sma(close, 200).iloc[-1]) if len(close) >= 200 else sma50 * 0.95
            if price < sma50:
                diag.skipped(ticker, "below 50-SMA"); continue

            rs = calc_relative_strength(close, spy_close) if not spy_close.empty else 1.0
            rsi = calc_rsi(close)
            _, _, hist = calc_macd(close)

            _, _, expiries = get_options_chain(ticker)   # dates-only call (calls empty by design)
            if not expiries:
                diag.skipped(ticker, get_options_error(ticker) or "no options chain"); continue

            # LEAPS: any expiry beyond dte_min, no upper bound
            exp_pick = find_best_expiry(expiries, dte_min, 3650, fallback=False)
            if exp_pick is None:
                diag.skipped(ticker, "no LEAPS expiry"); continue
            exp_str, dte = exp_pick

            calls_chain, _, _ = get_options_chain(ticker, exp_str)
            if calls_chain.empty:
                diag.skipped(ticker, "empty calls chain"); continue

            row = pick_strike(calls_chain, price, "LEAPS", cfg)
            if row is None:
                diag.skipped(ticker, "no ITM strike found"); continue

            strike = float(row["strike"])
            bid = float(row.get("bid", 0) or 0)
            ask = float(row.get("ask", 0) or 0)
            mid = (bid + ask) / 2 if bid + ask > 0 else float(row.get("lastPrice", 0) or 0)
            if mid <= 0:
                diag.skipped(ticker, "no premium"); continue

            delta_val = float(row.get("delta", cfg["target_delta"]) or cfg["target_delta"])
            delta_abs = abs(delta_val)

            if not (delta_min <= delta_abs <= delta_max):
                diag.skipped(ticker, "delta out of range"); continue

            iv = float(row.get("impliedVolatility", 0.30) or 0.30)
            iv_rank = approx_iv_rank(iv)
            if iv_rank > iv_rank_max:
                diag.skipped(ticker, "IV rank too high"); continue

            leverage_ratio = (price * 100) / (mid * 100) if mid > 0 else 0
            breakeven = strike + mid

            lt_score = 0
            if price > sma50 > sma200: lt_score += 30
            elif price > sma50: lt_score += 15
            if rs >= 1.1: lt_score += 20
            elif rs >= 1.0: lt_score += 10
            if rsi >= 50: lt_score += 15
            if hist > 0: lt_score += 10
            if iv_rank <= 30: lt_score += 15
            elif iv_rank <= iv_rank_max: lt_score += 8
            if delta_min <= delta_abs <= delta_max: lt_score += 10
            lt_score = min(lt_score, 100)

            prev = float(close.iloc[-2]) if len(close) > 1 else price
            chg_pct = (price - prev) / prev * 100
            trend = "Strong Bull" if price > sma50 > sma200 else "Partial Bull"

            results.append({
                "Ticker":       ticker,
                "Stock Price":  round(price, 2),
                "Change %":     round(chg_pct, 2),
                "Strike":       round(strike, 2),
                "Premium":      round(mid, 2),
                "Delta":        round(delta_abs, 3),
                "IV Rank":      round(iv_rank, 1),
                "DTE":          dte,
                "Expiry":       exp_str,
                "Breakeven":    round(breakeven, 2),
                "Leverage":     f"{leverage_ratio:.2f}×",
                "RS vs SPY":    round(rs, 3),
                "RSI":          round(rsi, 1),
                "Trend":        trend,
                "Score":        lt_score,
            })
            diag.passed(ticker)
        except Exception as e:
            diag.failed(ticker, type(e).__name__)
            continue

    _scan_label.empty()
    _scan_prog.empty()

    df_out = pd.DataFrame(results)
    if not df_out.empty:
        df_out = df_out.sort_values("Score", ascending=False).reset_index(drop=True)
    return df_out, diag


def render():
    section_header("🧨", "LEAPS",
                   "Long-dated calls ≥ 300 DTE · Deep ITM delta 0.60–0.75 · Low IV environment")

    with st.sidebar:
        st.markdown(f'<div style="color:{GOLD};font-size:12px;font-weight:600;margin:16px 0 8px">⚙️ LEAPS Filters</div>', unsafe_allow_html=True)
        dte_min = st.slider("Min DTE (days)", 180, 730, 300)
        delta_min, delta_max = st.slider("Delta Range", 0.40, 0.90, (0.60, 0.75), 0.01)
        iv_rank_max = st.slider("Max IV Rank", 10, 80, 40)
        price_min = st.number_input("Min Stock Price ($)", 5.0, 100.0, 20.0)
        price_max = st.number_input("Max Stock Price ($)", 50.0, 5000.0, 3000.0)
        universe_size = st.slider("Universe Size", 10, len(SP500_SAMPLE), 200, 5)

    include_etfs = st.checkbox("Include Liquid ETFs (SPY, QQQ, GLD…)", True,
                              help="Adds 34 highly-liquid ETFs with active options chains")

    tickers = SP500_SAMPLE[:universe_size]
    if include_etfs:
        tickers = OPTIONS_ETF_UNIVERSE + [t for t in tickers if t not in OPTIONS_ETF_UNIVERSE]
    st.info("⏱ LEAPS scan accesses long-dated expiries — may take 90–180 seconds.")

    col1, _ = st.columns([1, 5])
    with col1:
        run = st.button("▶ Run Scan", use_container_width=True)

    if run:
        df, diag = scan_leaps(tickers, dte_min, delta_min, delta_max, iv_rank_max, price_min, price_max)
        st.session_state["_leaps_r"] = (df, diag)
        from data_loader import show_api_warnings; show_api_warnings()

    _leaps_r = st.session_state.get("_leaps_r")
    if _leaps_r is not None:
        df, diag = _leaps_r
        if df.empty:
            empty_state("No LEAPS found. Check if long-dated options exist for these tickers, or lower DTE minimum.")
            diag.render(hide_when_clean=False)
        else:
            c1, c2, c3, c4 = st.columns(4)
            with c1: metric_card("LEAPS Found", str(len(df)), color=GOLD)
            with c2: metric_card("Avg DTE", f"{df['DTE'].mean():.0f}d", color=ACCENT_BLUE)
            with c3: metric_card("Avg Delta", f"{df['Delta'].mean():.2f}", color=ACCENT_GREEN)
            with c4: metric_card("Avg IV Rank", f"{df['IV Rank'].mean():.0f}", color=GOLD)

            st.markdown("<br>", unsafe_allow_html=True)
            render_results_table(df, strategy="LEAPS", source="LEAPS Scanner")
            diag.render()

            st.markdown(f"""
            <div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:6px;padding:12px 16px;margin-top:16px;color:{TEXT_MUTED};font-size:12px">
                💡 <b>LEAPS Strategy:</b> Deep ITM calls (delta 0.60–0.75) behave like stock ownership with less capital at risk.
                Breakeven = Strike + Premium. Buy when IV Rank is LOW (under 40) for better pricing.
                Leverage ratio shows how many "shares equivalent" your premium controls.
            </div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:8px;padding:30px;text-align:center;color:{TEXT_MUTED}">
            <div style="font-size:36px;margin-bottom:12px">🧨</div>
            <div style="font-size:16px;color:{TEXT_PRIMARY};margin-bottom:8px">LEAPS Opportunity Finder</div>
            <div style="font-size:13px">Deep ITM long-dated calls for leveraged directional exposure.<br>Criteria: DTE ≥ {dte_min} · Delta {delta_min}–{delta_max} · IV Rank &lt; {iv_rank_max}</div>
        </div>""", unsafe_allow_html=True)
