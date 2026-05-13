# scanners/dividend_cc_scanner.py — Dividend Capture + Covered Call
#
# Strategy:
#   1. Buy 100 shares before ex-dividend date (1–8 days away)
#   2. Immediately sell an ATM/slightly-OTM covered call expiring AFTER ex-div
#   3. Hold through ex-div → capture dividend
#   4. If called away: (Strike − Buy Price) + CC Premium + Dividend ≥ 0  (never lose)
#   5. If not called:  keep premium + dividend, hold or sell shares

from __future__ import annotations
import streamlit as st
import pandas as pd
from datetime import datetime, date
import time
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import *
from utils import *
from data_loader import get_price_history, get_options_chain, get_info


# ── Universe: dividend-paying large/mid caps with liquid options ──
DIV_CC_UNIVERSE = [
    # Mega-cap / tech dividends
    "AAPL", "MSFT", "ORCL", "IBM", "INTC", "CSCO", "QCOM", "TXN", "ADI",
    # Healthcare
    "JNJ", "ABBV", "BMY", "MRK", "PFE", "AMGN", "GILD", "MDT", "ABT",
    # Consumer staples
    "PG", "KO", "PEP", "MCD", "CL", "KMB", "GIS", "HSY", "STZ", "KR",
    "SYY", "MO", "PM", "WMT", "TGT", "COST",
    # Financials
    "JPM", "BAC", "WFC", "C", "USB", "TFC", "PNC", "MS", "GS", "BK",
    "PRU", "MET", "AFL", "ALL", "TRV", "AIG",
    # Consumer discretionary
    "HD", "LOW", "MCD", "YUM",
    # Industrials
    "CAT", "DE", "GE", "HON", "MMM", "RTX", "LMT", "NOC", "EMR", "ITW",
    "UNP", "UPS", "FDX",
    # Energy
    "XOM", "CVX", "COP", "SLB", "KMI", "WMB", "OKE", "OXY", "PSX",
    "MPC", "VLO",
    # Utilities
    "DUK", "SO", "NEE", "D", "AEP", "EXC",
    # Telecom
    "T", "VZ",
    # REITs (options-liquid)
    "O", "PSA", "AMT", "SPG", "DLR", "AVB", "WELL",
]
# De-duplicate preserving order
_seen = set()
DIV_CC_UNIVERSE = [t for t in DIV_CC_UNIVERSE if not (t in _seen or _seen.add(t))]


# ── Scanner ──────────────────────────────────────────────────────

def scan_div_cc(tickers, ex_div_days_max, div_amt_min, price_min, price_max,
                cc_otm_max_pct, min_income_pct):

    diag = ScanDiagnostics()
    today = date.today()

    _scan_label = st.empty()
    _scan_prog  = st.progress(0)
    results = []

    for i, ticker in enumerate(tickers):
        _scan_label.markdown(f'<div style="color:#C9A84C;font-size:12px">🔍 Scanning {i+1} of {len(tickers)} — {ticker}</div>', unsafe_allow_html=True)
        _scan_prog.progress((i + 1) / len(tickers))
        diag.seen(ticker)
        time.sleep(0.10)  # throttle — avoid Yahoo Finance rate-limit on cloud
        try:
            info = get_info(ticker)
            if not info:
                diag.skipped(ticker, "no fundamental data"); continue

            # ── Ex-dividend date ──────────────────────────────
            ex_div_raw = info.get("exDividendDate")
            if not ex_div_raw:
                diag.skipped(ticker, "no ex-div date"); continue

            try:
                if isinstance(ex_div_raw, (int, float)):
                    ex_div = datetime.utcfromtimestamp(int(ex_div_raw)).date()
                else:
                    ex_div = datetime.strptime(str(ex_div_raw)[:10], "%Y-%m-%d").date()
            except Exception:
                diag.skipped(ticker, "bad ex-div date format"); continue

            days_to_ex = (ex_div - today).days
            # Must own BEFORE ex-div date (days_to_ex >= 1)
            if not (1 <= days_to_ex <= ex_div_days_max):
                diag.skipped(ticker, f"ex-div {days_to_ex}d away"); continue

            # ── Dividend amount per share ──────────────────────
            div_amt = float(info.get("lastDividendValue", 0) or 0)
            if div_amt <= 0:
                ann_rate = float(info.get("dividendRate", 0) or 0)
                div_amt = round(ann_rate / 4, 4)   # assume quarterly
            if div_amt < div_amt_min:
                diag.skipped(ticker, "dividend too small"); continue

            # ── Current price ──────────────────────────────────
            price = float(info.get("currentPrice") or
                          info.get("regularMarketPrice") or 0)
            if not price or not (price_min <= price <= price_max):
                diag.skipped(ticker, "price out of range"); continue

            # ── Options chain — first expiry AFTER ex-div date ─
            _, _, expiries = get_options_chain(ticker)
            if not expiries:
                diag.skipped(ticker, "no options"); continue

            exp_str, exp_dte = None, None
            # Need expiry >= ex_div+1 so we hold through ex-div
            for exp in expiries:
                try:
                    exp_dt = datetime.strptime(exp, "%Y-%m-%d").date()
                    dte = (exp_dt - today).days
                    # Must expire at least 1 day after ex-div
                    if dte >= days_to_ex and dte <= days_to_ex + 28:
                        exp_str, exp_dte = exp, dte
                        break
                except Exception:
                    continue

            if exp_str is None:
                diag.skipped(ticker, "no expiry after ex-div"); continue

            calls_ch, _, _ = get_options_chain(ticker, exp_str)
            if calls_ch.empty:
                diag.skipped(ticker, "empty calls chain"); continue

            # ── Find ATM or slightly OTM call (strike >= price) ─
            max_strike = price * (1 + cc_otm_max_pct / 100)
            atm = calls_ch[
                (calls_ch["strike"] >= price) &
                (calls_ch["strike"] <= max_strike)
            ].copy()

            if atm.empty:
                diag.skipped(ticker, "no ATM call in range"); continue

            # Closest to current price (prefer ATM)
            atm["_dist"] = (atm["strike"] - price).abs()
            row = atm.sort_values("_dist").iloc[0]

            cc_strike  = float(row["strike"])
            bid        = float(row.get("bid", 0) or 0)
            ask        = float(row.get("ask", 0) or 0)
            last_price = float(row.get("lastPrice", 0) or 0)

            if bid > 0 and ask > 0:
                cc_premium = (bid + ask) / 2
                spread_pct = (ask - bid) / cc_premium * 100
            else:
                cc_premium = last_price
                spread_pct = 0.0

            if cc_premium <= 0:
                diag.skipped(ticker, "zero CC premium"); continue

            iv    = float(row.get("impliedVolatility", 0) or 0)
            delta = abs(float(row.get("delta", 0.5) or 0.5))

            # ── Key metrics ───────────────────────────────────
            net_cost         = price - cc_premium          # effective buy cost
            total_income     = cc_premium + div_amt        # premium + dividend
            income_pct       = total_income / price * 100  # % of stock price

            # P&L if stock is called away at expiry (stock >= strike)
            called_pnl       = (cc_strike - price) + cc_premium + div_amt
            called_pnl_pct   = called_pnl / price * 100

            # The core rule: NEVER lose if called away
            if called_pnl < 0:
                diag.skipped(ticker, "loss if called away"); continue

            if income_pct < min_income_pct:
                diag.skipped(ticker, "income % too low"); continue

            # Downside protection: premium shields from stock drop
            downside_prot_pct = cc_premium / price * 100

            # Dividend yield for this period (not annualized)
            div_yield_pct = div_amt / price * 100

            # ── Score ─────────────────────────────────────────
            score = 0
            if income_pct >= 2.5:  score += 35
            elif income_pct >= 1.5: score += 25
            elif income_pct >= 0.8: score += 15

            if days_to_ex == 1:    score += 30   # ex-div tomorrow = ideal
            elif days_to_ex <= 3:  score += 22
            elif days_to_ex <= 5:  score += 14
            else:                  score += 6

            if called_pnl_pct >= 1.5: score += 20
            elif called_pnl_pct >= 0.5: score += 12
            else:                        score += 5

            if downside_prot_pct >= 1.5: score += 10
            elif downside_prot_pct >= 0.5: score += 5

            if spread_pct <= 5: score += 5
            score = min(score, 100)

            div_annual_yield = float(info.get("dividendYield", 0) or 0) * 100
            sector           = info.get("sector", "N/A")

            prev_df = get_price_history(ticker, period="5d")
            chg_pct = 0.0
            if prev_df is not None and len(prev_df) >= 2:
                c = prev_df["Close"].squeeze()
                chg_pct = (float(c.iloc[-1]) - float(c.iloc[-2])) / float(c.iloc[-2]) * 100

            results.append({
                "Ticker":          ticker,
                "Sector":          sector,
                "Price":           round(price, 2),
                "Chg %":           round(chg_pct, 2),
                "Ex-Div Date":     str(ex_div),
                "Days to Ex-Div":  days_to_ex,
                "Div/Share":       round(div_amt, 3),
                "Ann. Yield %":    round(div_annual_yield, 2),
                "CC Strike":       round(cc_strike, 2),
                "CC Premium":      round(cc_premium, 3),
                "CC Expiry":       exp_str,
                "DTE":             exp_dte,
                "IV":              f"{iv*100:.1f}%",
                "Net Cost":        round(net_cost, 2),
                "Total Income":    round(total_income, 3),
                "Income %":        round(income_pct, 2),
                "If Called P&L":   round(called_pnl, 3),
                "If Called %":     round(called_pnl_pct, 2),
                "Downside Prot%":  round(downside_prot_pct, 2),
                "Score":           score,
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


# ── Render ───────────────────────────────────────────────────────

def render():
    section_header("📅", "Dividend Capture + Covered Call",
                   "Buy shares · Sell ATM call expiring after ex-div · Capture dividend · Exit clean — never lose if called away")

    with st.sidebar:
        st.markdown(f'<div style="color:{GOLD};font-size:12px;font-weight:600;margin:16px 0 8px">⚙️ Div-CC Filters</div>', unsafe_allow_html=True)
        ex_div_days_max  = st.slider("Max Days to Ex-Dividend", 1, 25, 5)
        div_amt_min      = st.number_input("Min Dividend / Share ($)", 0.01, 5.0, 0.05, step=0.01)
        min_income_pct   = st.slider("Min Total Income % (Premium + Div)", 0.1, 5.0, 0.5, 0.05)
        cc_otm_max_pct   = st.slider("Max CC Strike OTM % above price", 0.0, 7.0, 3.0, 0.5)
        price_min        = st.number_input("Min Stock Price ($)", 1.0, 200.0, 5.0)
        price_max        = st.number_input("Max Stock Price ($)", 10.0, 2000.0, 600.0)
        universe_size    = st.slider("Universe Size", 10, len(DIV_CC_UNIVERSE),
                                     len(DIV_CC_UNIVERSE), 5)

    tickers = DIV_CC_UNIVERSE[:universe_size]

    # ── Strategy explainer ────────────────────────────────────────
    wrap_s  = f"background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-left:3px solid {GOLD};border-radius:8px;padding:16px 20px;margin-bottom:16px"
    head_s  = f"color:{GOLD};font-size:13px;font-weight:700;margin-bottom:10px"
    body_s  = f"color:{TEXT_MUTED};font-size:12px;line-height:2"
    row_s   = f"display:flex;gap:10px;align-items:baseline"
    num_s   = f"color:{GOLD};font-family:'DM Mono',monospace;font-weight:700;min-width:18px"
    txt_s   = f"color:{TEXT_PRIMARY};font-size:12px"
    sub_s   = f"color:{TEXT_MUTED};font-size:11px"
    steps = [
        ("1", f"<b style='{txt_s}'>Buy</b> <span style='{sub_s}'>100 shares before ex-div date (within {ex_div_days_max} days)</span>"),
        ("2", f"<b style='{txt_s}'>Sell ATM covered call</b> <span style='{sub_s}'>— strike ≥ buy price, expiring AFTER ex-div</span>"),
        ("3", f"<b style='{txt_s}'>Hold through ex-div</b> <span style='{sub_s}'>— dividend is locked in (you're on record)</span>"),
        ("4", f"<b style='{txt_s}'>If called away</b> <span style='{sub_s}'>— (Strike − Buy) + CC Premium + Dividend ≥ 0 · guaranteed no loss</span>"),
        ("5", f"<b style='{txt_s}'>If not called</b> <span style='{sub_s}'>— keep dividend + premium; sell shares or run again</span>"),
    ]
    rows_html = "".join(
        f'<div style="{row_s};margin-bottom:4px"><span style="{num_s}">{n}</span><div>{txt}</div></div>'
        for n, txt in steps
    )
    st.markdown(f'<div style="{wrap_s}"><div style="{head_s}">📘 How This Strategy Works</div>{rows_html}</div>', unsafe_allow_html=True)

    st.info("⏱ Scan checks ex-dividend dates + live options data — allow 60–120 seconds.")

    col1, _ = st.columns([1, 5])
    with col1:
        run = st.button("▶ Run Scan", use_container_width=True)

    if run:
        df, diag = scan_div_cc(
            tickers, ex_div_days_max, div_amt_min, price_min, price_max,
            cc_otm_max_pct, min_income_pct,
        )
        st.session_state["_divcc_r"] = (df, diag)

    _divcc_r = st.session_state.get("_divcc_r")
    if _divcc_r is not None:
        df, diag = _divcc_r
        if df.empty:
            empty_state(
                "No setups found. Try: increase 'Max Days to Ex-Div', "
                "lower 'Min Dividend/Share', or lower 'Min Income %'."
            )
            diag.render(hide_when_clean=False)
        else:
            c1, c2, c3, c4 = st.columns(4)
            with c1: metric_card("Setups Found",    str(len(df)),                            color=GOLD)
            with c2: metric_card("Avg Income %",    f"{df['Income %'].mean():.2f}%",         color=ACCENT_GREEN)
            with c3: metric_card("Avg If Called %", f"{df['If Called %'].mean():.2f}%",      color=ACCENT_BLUE)
            with c4: metric_card("Avg Div/Share",   f"${df['Div/Share'].mean():.3f}",        color=GOLD)

            st.markdown("<br>", unsafe_allow_html=True)
            render_results_table(df, strategy="Dividend+CC", source="Dividend+CC Capture")
            diag.render()

            # Legend
            leg_s = f"background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:6px;padding:12px 16px;margin-top:16px;color:{TEXT_MUTED};font-size:12px;line-height:1.9"
            g = ACCENT_GREEN
            b = ACCENT_BLUE
            st.markdown(
                f'<div style="{leg_s}">'
                f'💡 <b style="color:{TEXT_PRIMARY}">Reading the table:</b><br>'
                f'<b style="color:{g}">Income %</b> = (CC Premium + Div/Share) ÷ Price — total return per share if called away.<br>'
                f'<b style="color:{g}">If Called %</b> = (Strike − Price + Premium + Div) ÷ Price — your P&L %; always ≥ 0 in this scan.<br>'
                f'<b style="color:{b}">Net Cost</b> = Price − CC Premium — your effective cost basis after selling the call.<br>'
                f'<b style="color:{b}">Downside Prot%</b> = CC Premium ÷ Price — how far the stock can drop before you lose money.<br>'
                f'<b style="color:{GOLD}">Days to Ex-Div</b> = 1 means tomorrow is ex-div — buy <b>today</b> to qualify for the dividend.'
                f'</div>',
                unsafe_allow_html=True,
            )
    else:
        ph_s = f"background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:8px;padding:30px;text-align:center;color:{TEXT_MUTED}"
        st.markdown(
            f'<div style="{ph_s}">'
            f'<div style="font-size:36px;margin-bottom:12px">📅</div>'
            f'<div style="font-size:16px;color:{TEXT_PRIMARY};margin-bottom:8px">Dividend Capture + Covered Call Finder</div>'
            f'<div style="font-size:13px">Finds stocks with ex-div in ≤ {ex_div_days_max} days where you can sell an ATM call,<br>'
            f'capture the dividend, and never lose money if the stock is called away.<br><br>'
            f'Criteria: Ex-div within {ex_div_days_max} days · Div ≥ ${div_amt_min:.2f}/share · '
            f'Income ≥ {min_income_pct}% · CC strike within {cc_otm_max_pct}% OTM</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
