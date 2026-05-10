# pages/cc_scanner.py — Covered Calls Income Generator

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


def scan_cc(tickers, delta_min, delta_max, premium_pct_min, dte_min, dte_max):

    diag = ScanDiagnostics()
    cfg = OPTIONS_STRIKE_RANGES["CC"]

    with st.spinner(f"Scanning {len(tickers)} tickers for covered call setups…"):
        results = []
        progress = st.progress(0)

        for i, ticker in enumerate(tickers):
            progress.progress((i + 1) / len(tickers))
            diag.seen(ticker)
            try:
                df = get_price_history(ticker, period="3mo")
                if df.empty or len(df) < 20:
                    diag.skipped(ticker, "no price history"); continue

                close = df["Close"].squeeze()
                price = float(close.iloc[-1])

                # Price near resistance heuristic: within 5% of 20-day high
                high_20 = float(close.iloc[-20:].max())
                near_resistance = (price / high_20) >= 0.95

                calls, _, expiries = get_options_chain(ticker)
                if calls.empty or not expiries:
                    diag.skipped(ticker, "no options chain"); continue

                exp_pick = find_best_expiry(expiries, dte_min, dte_max)
                if exp_pick is None:
                    diag.skipped(ticker, "no expiry in DTE range"); continue
                exp_str, dte = exp_pick

                calls_chain, _, _ = get_options_chain(ticker, exp_str)
                if calls_chain.empty:
                    diag.skipped(ticker, "empty calls chain"); continue

                row = pick_strike(calls_chain, price, "CC", cfg)
                if row is None:
                    diag.skipped(ticker, "no strike in target range"); continue

                strike = float(row["strike"])
                bid = float(row.get("bid", 0) or 0)
                ask = float(row.get("ask", 0) or 0)
                mid = (bid + ask) / 2 if bid > 0 or ask > 0 else float(row.get("lastPrice", 0) or 0)
                if mid <= 0:
                    diag.skipped(ticker, "no premium"); continue

                premium_pct = (mid / price) * 100
                if premium_pct < premium_pct_min:
                    diag.skipped(ticker, "yield too low"); continue

                delta_val = float(row.get("delta", cfg["target_delta"]) or cfg["target_delta"])
                delta_abs = abs(delta_val)

                iv = float(row.get("impliedVolatility", 0.30) or 0.30)
                iv_rank = approx_iv_rank(iv)

                ann_ret = annualized_return(mid, price, dte)
                upside_capped_pct = (strike - price) / price * 100
                prob_assignment = delta_abs * 100
                yield_pct = (mid / price) * 100

                prev = float(close.iloc[-2]) if len(close) > 1 else price
                chg_pct = (price - prev) / prev * 100

                score = 0
                if delta_min <= delta_abs <= delta_max: score += 30
                if premium_pct >= 1.5: score += 25
                elif premium_pct >= 0.8: score += 15
                if near_resistance: score += 20
                if iv_rank >= 40: score += 15
                elif iv_rank >= 25: score += 8
                if dte_min <= dte <= dte_max: score += 10
                score = min(score, 100)

                results.append({
                    "Ticker":         ticker,
                    "Stock Price":    round(price, 2),
                    "Change %":       round(chg_pct, 2),
                    "Call Strike":    round(strike, 2),
                    "Premium":        round(mid, 2),
                    "Yield %":        round(yield_pct, 2),
                    "Ann. Return %":  round(ann_ret, 2),
                    "Delta":          round(delta_abs, 3),
                    "IV":             f"{iv*100:.1f}%",
                    "IV Rank":        round(iv_rank, 1),
                    "DTE":            dte,
                    "Upside Cap %":   round(upside_capped_pct, 2),
                    "P(Assign) %":    round(prob_assignment, 1),
                    "Near Resist.":   "✅" if near_resistance else "—",
                    "Expiry":         exp_str,
                    "Score":          score,
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
    section_header("📦", "Covered Calls",
                   "Income generation · OTM strikes near resistance · Delta 0.15–0.25")

    with st.sidebar:
        st.markdown(f'<div style="color:{GOLD};font-size:12px;font-weight:600;margin:16px 0 8px">⚙️ Covered Call Filters</div>', unsafe_allow_html=True)
        delta_min, delta_max = st.slider("Call Delta Range", 0.05, 0.50, (0.15, 0.25), 0.01)
        premium_pct_min = st.slider("Min Yield % (premium/price)", 0.3, 3.0, 0.70, 0.05)
        dte_min, dte_max = st.slider("DTE Range", 1, 60, (1, 20))
        universe_size = st.slider("Universe Size", 10, len(SP500_SAMPLE), 200, 10)

    tickers = SP500_SAMPLE[:universe_size]
    st.info("⏱ Options scanning takes 60–120 seconds depending on universe size.")

    col1, _ = st.columns([1, 5])
    with col1:
        run = st.button("▶ Run Scan", use_container_width=True)

    if run:
        df, diag = scan_cc(tickers, delta_min, delta_max, premium_pct_min, dte_min, dte_max)
        st.session_state["_cc_r"] = (df, diag)

    _cc_r = st.session_state.get("_cc_r")
    if _cc_r is not None:
        df, diag = _cc_r
        if df.empty:
            empty_state("No covered call setups. Lower premium threshold or adjust DTE.")
            diag.render(hide_when_clean=False)
        else:
            c1, c2, c3, c4 = st.columns(4)
            with c1: metric_card("Setups Found", str(len(df)), color=GOLD)
            with c2: metric_card("Avg Yield %", f"{df['Yield %'].mean():.2f}%", color=ACCENT_GREEN)
            with c3: metric_card("Avg Ann. Return", f"{df['Ann. Return %'].mean():.1f}%", color=ACCENT_BLUE)
            with c4: metric_card("Avg DTE", f"{df['DTE'].mean():.0f}d", color=GOLD)

            st.markdown("<br>", unsafe_allow_html=True)
            render_results_table(df, strategy="CC", source="Covered Calls")
            diag.render()

            st.markdown(f"""
            <div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:6px;padding:12px 16px;margin-top:16px;color:{TEXT_MUTED};font-size:12px">
                💡 <b>Note:</b> Covered calls cap your upside at the Call Strike. Best used when you expect sideways/slight upside movement.
                P(Assign) % ≈ delta × 100 — higher delta = more likely to be called away.
            </div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:8px;padding:30px;text-align:center;color:{TEXT_MUTED}">
            <div style="font-size:36px;margin-bottom:12px">📦</div>
            <div style="font-size:16px;color:{TEXT_PRIMARY};margin-bottom:8px">Covered Call Income Generator</div>
            <div style="font-size:13px">Find optimal OTM calls to sell against long positions.<br>Criteria: Delta {delta_min}–{delta_max} · Yield ≥ {premium_pct_min}% · DTE {dte_min}–{dte_max} days</div>
        </div>""", unsafe_allow_html=True)
