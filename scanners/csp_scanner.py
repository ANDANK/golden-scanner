# pages/csp_scanner.py — Cash-Secured Puts

import streamlit as st
import pandas as pd
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import *
from utils import *
from data_loader import (
    get_price_history, get_options_chain,
    find_best_expiry, pick_strike,
)


def scan_csp(tickers, iv_rank_min, delta_min, delta_max, premium_pct_min,
             spread_pct_max, dte_min, dte_max):

    diag = ScanDiagnostics()
    cfg = OPTIONS_STRIKE_RANGES["CSP"]

    with st.spinner(f"Scanning {len(tickers)} tickers for CSP setups…"):
        results = []
        progress = st.progress(0)

        for i, ticker in enumerate(tickers):
            progress.progress((i + 1) / len(tickers))
            diag.seen(ticker)
            try:
                df = get_price_history(ticker, period="6mo")
                if df.empty or len(df) < 50:
                    diag.skipped(ticker, "no price history"); continue

                close = df["Close"].squeeze()
                price = float(close.iloc[-1])
                sma50 = float(calc_sma(close, 50).iloc[-1])
                trend_bull = price > sma50

                _, puts, expiries = get_options_chain(ticker)
                if puts.empty or not expiries:
                    diag.skipped(ticker, "no options chain"); continue

                exp_pick = find_best_expiry(expiries, dte_min, dte_max)
                if exp_pick is None:
                    diag.skipped(ticker, "no expiry in DTE range"); continue
                exp_str, dte = exp_pick

                _, puts_chain, _ = get_options_chain(ticker, exp_str)
                if puts_chain.empty:
                    diag.skipped(ticker, "empty puts chain"); continue

                row = pick_strike(puts_chain, price, "CSP", cfg)
                if row is None:
                    diag.skipped(ticker, "no strike in target range"); continue

                strike = float(row["strike"])
                bid = float(row.get("bid", 0) or 0)
                ask = float(row.get("ask", 0) or 0)
                last = float(row.get("lastPrice", 0) or 0)

                # yfinance often returns bid=0 (no live quote); fall back to lastPrice
                # and skip spread check — can't compute spread without both sides
                if bid > 0 and ask > 0:
                    mid = (bid + ask) / 2
                    spread_pct = (ask - bid) / mid * 100
                else:
                    mid = last
                    spread_pct = 0.0

                if mid <= 0:
                    diag.skipped(ticker, "no premium"); continue

                if spread_pct > spread_pct_max:
                    diag.skipped(ticker, "spread too wide"); continue

                premium_pct = (mid / strike) * 100
                if premium_pct < premium_pct_min:
                    diag.skipped(ticker, "premium too low"); continue

                iv = float(row.get("impliedVolatility", 0.30) or 0.30)
                iv_rank = approx_iv_rank(iv)
                if iv_rank < iv_rank_min:
                    diag.skipped(ticker, "IV rank too low"); continue

                delta_val = float(row.get("delta", -cfg["target_delta"]) or -cfg["target_delta"])
                delta_abs = abs(delta_val)

                ann_ret = annualized_return(mid, strike, dte)
                breakeven = strike - mid

                assign_risk = (
                    "🔴 High" if delta_abs > 0.35 else
                    "🟡 Moderate" if delta_abs > 0.25 else
                    "🟢 Low"
                )
                score = compute_options_score(iv_rank, delta_abs, premium_pct, spread_pct, trend_bull)

                prev = float(close.iloc[-2]) if len(close) > 1 else price
                chg_pct = (price - prev) / prev * 100

                results.append({
                    "Ticker":       ticker,
                    "Stock Price":  round(price, 2),
                    "Change %":     round(chg_pct, 2),
                    "Strike":       round(strike, 2),
                    "Premium":      round(mid, 2),
                    "Premium %":    round(premium_pct, 2),
                    "Delta":        round(delta_abs, 3),
                    "IV":           f"{iv*100:.1f}%",
                    "IV Rank":      round(iv_rank, 1),
                    "DTE":          dte,
                    "Ann. Return%": round(ann_ret, 2),
                    "Breakeven":    round(breakeven, 2),
                    "Spread %":     round(spread_pct, 2),
                    "Assign Risk":  assign_risk,
                    "Trend":        "✅ Bullish" if trend_bull else "❌ Bearish",
                    "Expiry":       exp_str,
                    "Score":        score,
                })
                diag.passed(ticker)
            except Exception as e:
                diag.failed(ticker, type(e).__name__)
                continue

        progress.empty()

    df_out = pd.DataFrame(results)
    if not df_out.empty:
        df_out = df_out.sort_values("Score", ascending=False).reset_index(drop=True)
    return df_out, diag


def render():
    section_header("💰", "Cash-Secured Puts",
                   "High IV · OTM delta 0.15–0.30 · Premium ≥ 1% · Bullish underlying trend")

    with st.sidebar:
        st.markdown(f'<div style="color:{GOLD};font-size:12px;font-weight:600;margin:16px 0 8px">⚙️ CSP Filters</div>', unsafe_allow_html=True)
        iv_rank_min    = st.slider("Min IV Rank", 0, 100, 25)
        delta_min, delta_max = st.slider("Delta Range (abs)", 0.05, 0.50, (0.15, 0.30), 0.01)
        premium_pct_min= st.slider("Min Premium % of Strike", 0.3, 5.0, 0.70, 0.05)
        spread_pct_max = st.slider("Max Bid/Ask Spread %", 1.0, 50.0, 20.0, 0.5)
        dte_min, dte_max = st.slider("DTE Range (days)", 1, 90, (7, 45))
        universe_size  = st.slider("Universe Size", 10, len(SP500_SAMPLE), 200, 5)

    tickers = SP500_SAMPLE[:universe_size]
    st.info("⏱ Options data requires multiple API calls — scan may take 60–120 sec depending on universe size.")

    col1, _ = st.columns([1, 5])
    with col1:
        run = st.button("▶ Run Scan", use_container_width=True)

    if run:
        df, diag = scan_csp(tickers, iv_rank_min, delta_min, delta_max, premium_pct_min,
                            spread_pct_max, dte_min, dte_max)

        if df.empty:
            empty_state("No CSP setups found. Try lowering IV Rank minimum or expanding DTE range.")
            diag.render(hide_when_clean=False)
        else:
            c1, c2, c3, c4 = st.columns(4)
            with c1: metric_card("Setups Found", str(len(df)), color=GOLD)
            with c2: metric_card("Avg Premium %", f"{df['Premium %'].mean():.2f}%", color=ACCENT_GREEN)
            with c3: metric_card("Avg Ann. Return", f"{df['Ann. Return%'].mean():.1f}%", color=ACCENT_BLUE)
            with c4:
                bull_pct = (df["Trend"] == "✅ Bullish").mean() * 100
                metric_card("Bullish Underlying", f"{bull_pct:.0f}%", color=GOLD)

            st.markdown("<br>", unsafe_allow_html=True)
            render_results_table(df)
            diag.render()

            st.markdown(f"""
            <div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:6px;padding:12px 16px;margin-top:16px;color:{TEXT_MUTED};font-size:12px">
                💡 <b>How to read this:</b> Sell a put at the Strike price, collect the Premium.
                If stock stays above Strike at expiry, keep full premium (Ann. Return% assumes full cycle).
                Breakeven = Strike − Premium. Only trade CSPs on stocks you're willing to own.
            </div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:8px;padding:30px;text-align:center;color:{TEXT_MUTED}">
            <div style="font-size:36px;margin-bottom:12px">💰</div>
            <div style="font-size:16px;color:{TEXT_PRIMARY};margin-bottom:8px">Cash-Secured Put Finder</div>
            <div style="font-size:13px">Find premium-rich OTM puts with favorable risk/reward.<br>Criteria: IV Rank &gt; {iv_rank_min} · Delta {delta_min}–{delta_max} · Premium ≥ {premium_pct_min}%</div>
        </div>""", unsafe_allow_html=True)
