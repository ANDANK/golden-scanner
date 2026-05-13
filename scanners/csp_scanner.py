# pages/csp_scanner.py — Cash-Secured Puts

import streamlit as st
import pandas as pd
from datetime import datetime
import time, random
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import *
from utils import *
from data_loader import (
    get_price_history, get_options_chain, get_options_error,
    find_best_expiry, pick_strike,
)


BATCH_SIZE    = 20   # tickers per batch before a cooldown pause
BATCH_PAUSE_S = 30   # seconds to wait between batches


def _batch_pause_ui(ph, batch_num: int, total_batches: int, seconds: int = BATCH_PAUSE_S):
    """Show a live countdown between batches so the user knows what's happening."""
    for remaining in range(seconds, 0, -1):
        ph.markdown(
            f'<div style="color:{GOLD};font-size:12px;padding:4px 8px;'
            f'background:#1a1a2a;border-radius:4px;border-left:3px solid {GOLD}">'
            f'⏸ Batch {batch_num} of {total_batches} complete — '
            f'cooling down {remaining}s before next batch…</div>',
            unsafe_allow_html=True,
        )
        time.sleep(1)
    ph.empty()


def scan_csp(tickers, iv_rank_min, delta_min, delta_max, premium_pct_min,
             spread_pct_max, dte_min, dte_max):

    diag = ScanDiagnostics()
    cfg = OPTIONS_STRIKE_RANGES["CSP"]
    st.session_state.pop("_rl_hit", None)   # clear stale rate-limit flag

    total_batches = max(1, (len(tickers) - 1) // BATCH_SIZE + 1)

    _scan_label  = st.empty()
    _batch_label = st.empty()
    _scan_prog   = st.progress(0)
    results = []

    for i, ticker in enumerate(tickers):
        # ── Proactive batch pause every BATCH_SIZE tickers ──────────
        if i > 0 and i % BATCH_SIZE == 0:
            _scan_label.empty()
            _batch_pause_ui(_batch_label, i // BATCH_SIZE, total_batches)

        _scan_label.markdown(f'<div style="color:#C9A84C;font-size:12px">🔍 Scanning {i+1} of {len(tickers)} — {ticker} (batch {i // BATCH_SIZE + 1}/{total_batches})</div>', unsafe_allow_html=True)
        _scan_prog.progress((i + 1) / len(tickers))
        diag.seen(ticker)
        time.sleep(1.5 + random.uniform(0, 0.75))   # ~2s with jitter within batch
        try:
            df = get_price_history(ticker, period="6mo")
            if df.empty or len(df) < 50:
                diag.skipped(ticker, "no price history"); continue

            close = df["Close"].squeeze()
            price = float(close.iloc[-1])
            sma50 = float(calc_sma(close, 50).iloc[-1])
            trend_bull = price > sma50

            _, _, expiries = get_options_chain(ticker)   # dates-only call (puts empty by design)
            if not expiries:
                diag.skipped(ticker, get_options_error(ticker) or "no options chain"); continue

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

    _scan_label.empty()
    _scan_prog.empty()

    df_out = pd.DataFrame(results)
    if not df_out.empty:
        df_out = df_out.sort_values("Score", ascending=False).reset_index(drop=True)
    return df_out, diag


def render(universe_mode: str = "stocks"):
    """
    universe_mode: "stocks"  → top 30 S&P 500 stocks
                   "etfs"    → 33 liquid options ETFs (OPTIONS_ETF_UNIVERSE)
    """
    is_etf  = universe_mode == "etfs"
    mode_lbl = "ETFs" if is_etf else "Stocks"
    mk       = f"csp_{universe_mode}"          # unique widget-key prefix
    sess_key = f"_csp_{universe_mode}_r"       # separate results per mode

    section_header("💰", f"Cash-Secured Puts — {mode_lbl}",
                   "High IV · OTM delta 0.15–0.30 · Premium ≥ 1% · Bullish underlying trend")

    with st.sidebar:
        st.markdown(f'<div style="color:{GOLD};font-size:12px;font-weight:600;margin:16px 0 8px">⚙️ CSP — {mode_lbl} Filters</div>', unsafe_allow_html=True)
        iv_rank_min     = st.slider("Min IV Rank",               0,    100,   25,          key=f"{mk}_iv")
        delta_min, delta_max = st.slider("Delta Range (abs)",    0.05, 0.50, (0.15, 0.30), 0.01, key=f"{mk}_delta")
        premium_pct_min = st.slider("Min Premium % of Strike",   0.3,  5.0,   0.70,        0.05, key=f"{mk}_prem")
        spread_pct_max  = st.slider("Max Bid/Ask Spread %",      1.0,  50.0,  20.0,        0.5,  key=f"{mk}_sprd")
        dte_min, dte_max = st.slider("DTE Range (days)",         1,    90,   (1, 45),             key=f"{mk}_dte")
        if not is_etf:
            universe_size = st.slider("Universe Size (top stocks)", 10, len(SP500_SAMPLE), 20, 10, key=f"{mk}_sz")

    tickers = OPTIONS_ETF_UNIVERSE if is_etf else SP500_SAMPLE[:universe_size]

    n = len(tickers)
    n_batches = max(1, (n - 1) // BATCH_SIZE + 1)
    est_secs  = n * 2 + (n_batches - 1) * BATCH_PAUSE_S
    est_str   = f"{est_secs // 60}m {est_secs % 60}s" if est_secs >= 60 else f"{est_secs}s"
    st.info(f"⏱ Scanning {n} {'ETFs' if is_etf else 'stocks'} in {n_batches} batch(es) of {BATCH_SIZE} · Est. time: ~{est_str}")

    col1, _ = st.columns([1, 5])
    with col1:
        run = st.button("▶ Run Scan", use_container_width=True, key=f"{mk}_run")

    if run:
        df, diag = scan_csp(tickers, iv_rank_min, delta_min, delta_max, premium_pct_min,
                            spread_pct_max, dte_min, dte_max)
        st.session_state[sess_key] = (df, diag)
        from data_loader import show_api_warnings; show_api_warnings()

    result = st.session_state.get(sess_key)
    if result is not None:
        df, diag = result
        if df.empty:
            empty_state("No CSP setups found. Try lowering IV Rank minimum or expanding DTE range.")
            diag.render(hide_when_clean=False)
        else:
            c1, c2, c3, c4 = st.columns(4)
            with c1: metric_card("Setups Found",       str(len(df)),                           color=GOLD)
            with c2: metric_card("Avg Premium %",      f"{df['Premium %'].mean():.2f}%",       color=ACCENT_GREEN)
            with c3: metric_card("Avg Ann. Return",    f"{df['Ann. Return%'].mean():.1f}%",    color=ACCENT_BLUE)
            with c4:
                bull_pct = (df["Trend"] == "✅ Bullish").mean() * 100
                metric_card("Bullish Underlying", f"{bull_pct:.0f}%", color=GOLD)

            st.markdown("<br>", unsafe_allow_html=True)
            render_results_table(df, strategy="CSP", source=f"CSP-{mode_lbl}")
            diag.render()

            st.markdown(f"""
            <div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:6px;padding:12px 16px;margin-top:16px;color:{TEXT_MUTED};font-size:12px">
                💡 <b>How to read this:</b> Sell a put at the Strike price, collect the Premium.
                If {'ETF' if is_etf else 'stock'} stays above Strike at expiry, keep full premium.
                Breakeven = Strike − Premium. Only trade CSPs on assets you're willing to own.
            </div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:8px;padding:30px;text-align:center;color:{TEXT_MUTED}">
            <div style="font-size:36px;margin-bottom:12px">💰</div>
            <div style="font-size:16px;color:{TEXT_PRIMARY};margin-bottom:8px">Cash-Secured Puts — {mode_lbl}</div>
            <div style="font-size:13px">Scanning {len(tickers)} {mode_lbl.lower()} for premium-rich OTM puts.<br>Criteria: IV Rank &gt; {iv_rank_min} · Delta {delta_min}–{delta_max} · Premium ≥ {premium_pct_min}% · DTE {dte_min}–{dte_max}</div>
        </div>""", unsafe_allow_html=True)
