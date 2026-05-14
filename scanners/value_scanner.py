# pages/value_scanner.py — Deep Value Finder

import streamlit as st
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import *
from utils import *
from data_loader import get_price_history, get_info, get_batch_quotes


def scan_value(tickers, pe_max, pb_max, roe_min, de_max, div_filter,
               price_min, price_max):

    _scan_label = st.empty()
    _scan_prog  = st.progress(0)
    results = []

    for i, ticker in enumerate(tickers):
        _scan_label.markdown(f'<div style="color:#C9A84C;font-size:12px">🔍 Analyzing {i+1} of {len(tickers)} — {ticker}</div>', unsafe_allow_html=True)
        _scan_prog.progress((i + 1) / len(tickers))
        try:
            info = get_info(ticker)
            if not info:
                continue

            pe   = info.get("trailingPE")     or info.get("forwardPE")    or 0
            pb   = info.get("priceToBook")    or 0
            roe  = (info.get("returnOnEquity") or 0) * 100
            de   = info.get("debtToEquity")   or 0
            fcf  = info.get("freeCashflow")   or 0
            div  = info.get("dividendYield")  or 0
            div_pct = (div or 0) * 100

            price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
            if not (price_min <= price <= price_max):
                continue

            # Apply filters
            if pe <= 0 or pe > pe_max:
                continue
            if pb <= 0 or pb > pb_max:
                continue
            if roe < roe_min:
                continue
            if de > de_max:
                continue
            if div_filter and div_pct < 0.5:
                continue

            # Price above 200 SMA check
            df = get_price_history(ticker, period="12mo")
            above_200 = False
            if not df.empty and len(df) >= 200:
                close = df["Close"].squeeze()
                sma200 = float(calc_sma(close, 200).iloc[-1])
                above_200 = price > sma200

            score = compute_value_score(pe, pb, roe, de / 100, fcf, above_200)

            # Value trap risk flags
            # de from yfinance is in % units (e.g. 150 = 1.5× D/E ratio), so
            # compare against the equivalent % thresholds (70 = 0.7×, 80 = 0.8×)
            traps = []
            if de > 70:    traps.append("High Debt")
            if roe < 8:    traps.append("Low ROE")
            if fcf <= 0:   traps.append("Negative FCF")

            trap_str = ", ".join(traps) if traps else "✅ None"

            mcap = info.get("marketCap", 0) or 0
            mcap_str = f"${mcap/1e9:.1f}B" if mcap >= 1e9 else (f"${mcap/1e6:.0f}M" if mcap > 0 else "N/A")

            sector = info.get("sector", "N/A")

            prev = info.get("regularMarketPreviousClose") or price
            chg_pct = (price - prev) / prev * 100 if prev else 0

            results.append({
                "Ticker":      ticker,
                "Sector":      sector,
                "Price":       round(price, 2),
                "Change %":    round(chg_pct, 2),
                "P/E":         round(pe, 1),
                "P/B":         round(pb, 2),
                "ROE %":       round(roe, 1),
                "D/E":         round(de / 100, 2),
                "FCF":         "✅" if fcf > 0 else "❌",
                "Div Yield %": round(div_pct, 2),
                ">200 SMA":    "✅" if above_200 else "❌",
                "Trap Risk":   trap_str,
                "Mkt Cap":     mcap_str,
                "Score":       score,
            })
        except Exception:
            continue

    _scan_label.empty()
    _scan_prog.empty()

    df_out = pd.DataFrame(results)
    if not df_out.empty:
        df_out = df_out.sort_values("Score", ascending=False).reset_index(drop=True)
    return df_out


def render():
    section_header("💎", "Value",
                   "Undervalued companies · Strong fundamentals · Low debt · Positive FCF")

    with st.sidebar:
        st.markdown(f'<div style="color:{GOLD};font-size:12px;font-weight:600;margin:16px 0 8px">⚙️ Value Filters</div>', unsafe_allow_html=True)
        pe_max  = st.slider("Max P/E Ratio", 5, 50, 25)
        pb_max  = st.slider("Max P/B Ratio", 0.5, 5.0, 3.0, 0.1)
        roe_min = st.slider("Min ROE (%)", 0, 40, 12)
        de_max  = st.slider("Max Debt/Equity (×100)", 0, 300, 100)
        price_min = st.number_input("Min Price ($)", 1.0, 100.0, 5.0)
        price_max = st.number_input("Max Price ($)", 10.0, 5000.0, 3000.0)
        div_filter = st.checkbox("Dividend payers only", False)
        universe_size = st.slider("Universe Size", 20, len(SP500_SAMPLE), 200, 10)

    tickers = SP500_SAMPLE[:universe_size]

    col1, col2 = st.columns([1, 5])
    with col1:
        run = st.button("▶ Run Scan", use_container_width=True)

    if run:
        df = scan_value(tickers, pe_max, pb_max, roe_min, de_max,
                        div_filter, price_min, price_max)
        st.session_state["_val_r"] = df
    from data_loader import show_api_warnings; show_api_warnings()

    _val_r = st.session_state.get("_val_r")
    if _val_r is not None:
        df = _val_r
        if df.empty:
            empty_state("No value stocks matched. Try relaxing P/E, ROE, or D/E filters.")
        else:
            # Summary stats
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                metric_card("Results Found", str(len(df)), color=GOLD)
            with col2:
                avg_pe = df["P/E"].mean()
                metric_card("Avg P/E", f"{avg_pe:.1f}", color=ACCENT_BLUE)
            with col3:
                avg_roe = df["ROE %"].mean()
                metric_card("Avg ROE", f"{avg_roe:.1f}%", color=ACCENT_GREEN)
            with col4:
                no_trap = (df["Trap Risk"] == "✅ None").sum()
                metric_card("Clean (No Traps)", str(no_trap), color=GOLD)

            st.markdown("<br>", unsafe_allow_html=True)
            render_results_table(df, strategy="Stock", source="Value Scanner")

            st.markdown(
                f'<div style="color:{TEXT_MUTED};font-size:12px;margin:20px 0 6px">&#128200; Charts &amp; Price History</div>',
                unsafe_allow_html=True,
            )
            for idx, (_, row) in enumerate(df.iterrows()):
                ticker = str(row["Ticker"])
                chg    = float(row.get("Change %", 0))
                score  = int(row.get("Score", 0))
                label  = f"📈  {ticker}   ·   ${row['Price']:.2f}   ·   {chg:+.2f}%   ·   Score {score}/100"
                with st.expander(label, expanded=(idx == 0)):
                    df_c = get_price_history(ticker, period="6mo")
                    if not df_c.empty:
                        st.plotly_chart(mini_chart(df_c, ticker), width='stretch')
    else:
        st.markdown(f"""
        <div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:8px;padding:30px;text-align:center;color:{TEXT_MUTED}">
            <div style="font-size:36px;margin-bottom:12px">💎</div>
            <div style="font-size:16px;color:{TEXT_PRIMARY};margin-bottom:8px">Deep Value Finder</div>
            <div style="font-size:13px">Scans for undervalued companies trading below fair value.<br>Criteria: P/E &lt; {pe_max} · P/B &lt; {pb_max} · ROE &gt; {roe_min}% · Positive FCF</div>
        </div>""", unsafe_allow_html=True)
