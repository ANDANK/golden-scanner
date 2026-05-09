# pages/about.py — About & User Guide

import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *
from utils import section_header


def render():
    section_header("ℹ️", "About & Guide",
                   "How to use Golden Scanner · Strategy guides · Disclaimer")

    # ── Hero ──────────────────────────────────────────────────
    st.markdown(f"""
    <div style="background:linear-gradient(135deg,{BG_CARD},{BG_PANEL});border:1px solid {GOLD}44;
                border-radius:12px;padding:32px;text-align:center;margin-bottom:28px">
        <div style="font-family:'Cormorant Garamond',serif;font-size:42px;color:{GOLD};font-weight:700;letter-spacing:3px">
            ✦ GOLDEN SCANNER
        </div>
        <div style="color:{TEXT_MUTED};font-size:13px;letter-spacing:3px;text-transform:uppercase;margin:8px 0 16px">
            Precision Trading Intelligence Platform
        </div>
        <div style="color:{TEXT_PRIMARY};font-size:15px;max-width:600px;margin:0 auto;line-height:1.8">
            A professional-grade multi-scanner platform designed to surface high-probability 
            trade setups across stocks, options, and ETFs — reducing noise so you can act faster 
            with more conviction.
        </div>
    </div>""", unsafe_allow_html=True)

    # ── Scanner Guide ─────────────────────────────────────────
    tabs = st.tabs(["📖 How It Works", "📊 Stock Scanners", "🎯 Options Scanners", "📈 ETF Scanners", "⚙️ Signal Score", "⚠️ Disclaimer"])

    with tabs[0]:
        st.markdown(f"""
        <div style="color:{TEXT_PRIMARY};line-height:1.9;font-size:14px">
        <h3 style="color:{GOLD};font-family:'Cormorant Garamond',serif">Getting Started</h3>

        <p><b style="color:{TEXT_PRIMARY}">1. Pick a Scanner</b> — Use the sidebar to navigate to the scanner that matches your trading style and timeframe.</p>

        <p><b style="color:{TEXT_PRIMARY}">2. Set Your Filters</b> — Each scanner has a filter panel in the sidebar. 
        Start with default values (already calibrated for quality signals), then adjust to your risk tolerance.</p>

        <p><b style="color:{TEXT_PRIMARY}">3. Run the Scan</b> — Click ▶ Run Scan. 
        Stock scans run in ~30–60 seconds. Options scans take 60–180 seconds due to API calls per ticker.</p>

        <p><b style="color:{TEXT_PRIMARY}">4. Read the Results</b> — Results are sorted by Score (0–100).
        Higher score = more criteria aligned = higher conviction setup. Click column headers to re-sort.</p>

        <p><b style="color:{TEXT_PRIMARY}">5. Export & Trade</b> — Download results as CSV with the ⬇ Export button.
        Do your own due diligence before trading any setup.</p>

        <h3 style="color:{GOLD};font-family:'Cormorant Garamond',serif;margin-top:24px">Data Sources</h3>
        <p>All data is sourced from <b>Yahoo Finance (yfinance)</b>, updated every 5 minutes via Streamlit caching.
        Options data may have 15-minute delays. Fundamental data (P/E, ROE, etc.) is updated daily.</p>

        <h3 style="color:{GOLD};font-family:'Cormorant Garamond',serif;margin-top:24px">Tips for Best Results</h3>
        <ul style="line-height:2.2">
            <li>Run momentum scans during the first hour of the trading session for freshest signals</li>
            <li>Cross-reference options setups with the underlying stock trend before trading</li>
            <li>Use the Score column as a ranking tool, not a binary buy/sell signal</li>
            <li>For 3× ETFs: only trade with conviction and use very small position sizes</li>
            <li>Cache is cleared automatically every 5 min — use 🔄 Clear Cache to force refresh</li>
        </ul>
        </div>""", unsafe_allow_html=True)

    with tabs[1]:
        scanners = [
            ("⚡ Momentum", "Finds stocks in strong uptrends with institutional accumulation signals.",
             ["Price > 50 SMA > 200 SMA (trend alignment)", "RSI 55–68 (momentum sweet spot — not overbought)",
              "MACD histogram > 0 (bullish crossover)", "Volume ≥ 1.5× 20-day average (institutional participation)",
              "Optional: 20-day high breakout", "ATR expanding (volatility confirming move)"],
             "Best for swing trades (1–4 weeks). High-RS stocks relative to SPY are institutional favorites."),
            ("💎 Value", "Identifies companies trading below intrinsic value with healthy balance sheets.",
             ["P/E below 25 (adjustable)", "P/B below 3 (asset-based value floor)",
              "ROE > 12% (management quality)", "Debt/Equity < 1 (balance sheet health)",
              "Positive free cash flow", "Price above 200 SMA (trend confirmation)"],
             "Best for position trades (1–6 months). Check 'Trap Risk' column — avoid High Debt + Low ROE combos."),
            ("🚀 Growth", "Finds companies with accelerating revenue and earnings growth.",
             ["Revenue growth > 15% YoY", "EPS growth > 12% YoY",
              "Relative strength > 1.02 vs SPY", "Price above 50 SMA"],
             "Best for trend-following after earnings beats. Higher RS = stronger institutional demand."),
            ("📰 Headlines", "Captures news-driven explosive moves with volume confirmation.",
             ["Price move > 3% (intraday or overnight)", "Volume spike ≥ 2× average",
              "Gap detection ≥ 1.5%", "Catalyst tagging (Earnings, M&A, Upgrade)"],
             "Best for same-day trading. High moves + high volume = real institutional reaction, not noise."),
        ]

        for title, desc, criteria, tip in scanners:
            with st.expander(title, expanded=False):
                st.markdown(f"""
                <div style="color:{TEXT_MUTED};font-size:13px;margin-bottom:10px">{desc}</div>
                <b style="color:{GOLD};font-size:12px">CRITERIA:</b>
                <ul style="color:{TEXT_PRIMARY};font-size:13px;line-height:2.0">
                    {"".join(f"<li>{c}</li>" for c in criteria)}
                </ul>
                <div style="background:{BG_PANEL};border-left:3px solid {GOLD};padding:8px 12px;border-radius:4px;color:{TEXT_MUTED};font-size:12px">
                    💡 {tip}
                </div>""", unsafe_allow_html=True)

    with tabs[2]:
        options_guides = [
            ("💰 Cash-Secured Puts (CSP)",
             "Sell OTM puts on bullish stocks to collect premium with a controlled entry price.",
             ["IV Rank > 30 (elevated premium environment)", "Delta 0.15–0.30 (OTM, less assignment risk)",
              "Premium ≥ 1% of strike price", "Bid/ask spread < 5% (liquidity)", "Bullish underlying trend"],
             "The ideal CSP: stock you want to own at a discount, with premium paying you to wait. Breakeven = Strike − Premium."),
            ("📦 Covered Calls (CC)",
             "Sell OTM calls against long stock to generate monthly income.",
             ["Delta 0.15–0.25 (OTM — protects upside capture)", "Premium ≥ 0.8% of stock price",
              "Price near resistance (natural ceiling for calls)", "DTE 21–45 days (theta sweet spot)"],
             "Best when you expect sideways or mild upside. Yield % = (premium / stock price). Upside Cap = how much you can gain before stock is called away."),
            ("🧨 LEAPS",
             "Deep ITM long-dated calls (300+ days) as a leveraged stock replacement.",
             ["Expiration ≥ 300 days (time decay is minimal)", "Delta 0.60–0.75 (acts like owning ~65–70% of a share)",
              "IV Rank < 40 (buy when IV is low)", "Strong underlying trend (price > 50 SMA)"],
             "Leverage ratio shows capital efficiency. A 2× ratio means your call controls equivalent exposure for half the capital of owning shares. Delta fades as time passes — monitor regularly."),
        ]

        for title, desc, criteria, tip in options_guides:
            with st.expander(title, expanded=False):
                st.markdown(f"""
                <div style="color:{TEXT_MUTED};font-size:13px;margin-bottom:10px">{desc}</div>
                <b style="color:{GOLD};font-size:12px">CRITERIA:</b>
                <ul style="color:{TEXT_PRIMARY};font-size:13px;line-height:2.0">
                    {"".join(f"<li>{c}</li>" for c in criteria)}
                </ul>
                <div style="background:{BG_PANEL};border-left:3px solid {GOLD};padding:8px 12px;border-radius:4px;color:{TEXT_MUTED};font-size:12px">
                    💡 {tip}
                </div>""", unsafe_allow_html=True)

    with tabs[3]:
        etf_guides = [
            ("📊 ETF Trends",
             "Identifies sector ETFs in strong uptrends with relative strength leadership.",
             ["Price > 50 SMA and 200 SMA", "Relative strength > 1.02 vs S&P 500",
              "RSI 50–70 (trending not extended)", "Volume-based flow signal"],
             "Sector rotation signals: when XLK outperforms, tech leads. When XLE leads, energy is in favor. Follow the money."),
            ("📈 ETF Options",
             "Premium selling on liquid ETF options — typically tighter spreads than single stocks.",
             ["High AUM ETFs (SPY, QQQ, IWM, XLK, etc.)", "IV Rank > 25 for decent premium",
              "Delta 0.15–0.30 for OTM", "Tight bid/ask spread (ETFs are more liquid)"],
             "ETF options are preferred by institutional traders for premium selling due to no earnings risk and persistent liquidity."),
            ("⚡📊 3× Leveraged ETFs",
             "High-velocity directional plays — for short-term traders only.",
             ["Price > 20 SMA and 50 SMA", "RSI 55–70 (momentum without extreme extension)",
              "Volume ≥ 1.2× average", "Rising ATR (volatility fueling the move)"],
             "3× ETFs lose value from volatility decay (beta slippage) when held long-term. Use for 1–5 day trades maximum with strict stops."),
            ("⚡📈 3× ETF Options",
             "Ultra-high premium from extreme implied volatility in leveraged instruments.",
             ["IV Rank > 40 (these are always high-IV by nature)", "Premium % typically 3–10× normal ETFs",
              "Short DTE (14–35 days) preferred due to extreme theta exposure"],
             "Premium/Risk ratio (Prem % ÷ ATR %) is the key metric here. If ATR is 8% and premium is 4%, you're getting paid half the daily risk range — evaluate carefully."),
        ]

        for title, desc, criteria, tip in etf_guides:
            with st.expander(title, expanded=False):
                st.markdown(f"""
                <div style="color:{TEXT_MUTED};font-size:13px;margin-bottom:10px">{desc}</div>
                <b style="color:{GOLD};font-size:12px">CRITERIA:</b>
                <ul style="color:{TEXT_PRIMARY};font-size:13px;line-height:2.0">
                    {"".join(f"<li>{c}</li>" for c in criteria)}
                </ul>
                <div style="background:{BG_PANEL};border-left:3px solid {GOLD};padding:8px 12px;border-radius:4px;color:{TEXT_MUTED};font-size:12px">
                    💡 {tip}
                </div>""", unsafe_allow_html=True)

    with tabs[4]:
        st.markdown(f"""
        <div style="color:{TEXT_PRIMARY};font-size:14px;line-height:1.9">
        <h3 style="color:{GOLD};font-family:'Cormorant Garamond',serif">Signal Score (0–100)</h3>
        <p>Every scanner result includes a composite <b>Signal Score</b> that aggregates multiple technical and fundamental factors into a single number.</p>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:16px 0">
        """, unsafe_allow_html=True)

        score_ranges = [
            (ACCENT_GREEN, "80–100", "🔥 Strong Setup", "Near-perfect alignment across all criteria. Highest conviction."),
            ("#86EFAC", "60–79", "✅ Solid Setup", "Most criteria aligned. Good risk/reward."),
            (TEXT_MUTED, "40–59", "⚪ Neutral", "Mixed signals. More work needed before trading."),
            ("#FCA5A5", "20–39", "🔻 Weak", "Few criteria met. Avoid or wait for improvement."),
            (ACCENT_RED, "0–19", "💀 Avoid", "Almost no criteria met. High risk, low reward."),
        ]

        for color, rng, label, desc in score_ranges:
            st.markdown(f"""
            <div style="background:{BG_CARD};border:1px solid {color}44;border-left:3px solid {color};
                        border-radius:6px;padding:12px 16px;margin-bottom:8px">
                <div style="color:{color};font-weight:700;font-size:16px">{rng} — {label}</div>
                <div style="color:{TEXT_MUTED};font-size:13px;margin-top:4px">{desc}</div>
            </div>""", unsafe_allow_html=True)

        st.markdown(f"""
        <div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:6px;padding:16px;margin-top:12px;color:{TEXT_MUTED};font-size:13px">
            <b style="color:{TEXT_PRIMARY}">Score Components vary by scanner:</b><br><br>
            <b>Momentum Score:</b> Trend alignment (30pts) + RSI range (20pts) + MACD (20pts) + Volume (15pts) + Breakout (10pts) + RS (5pts)<br><br>
            <b>Value Score:</b> P/E level (25pts) + P/B level (20pts) + ROE strength (20pts) + Debt level (15pts) + FCF positive (10pts) + Price vs 200 SMA (10pts)<br><br>
            <b>Options Score:</b> IV Rank level (30pts) + Delta in range (25pts) + Premium % (25pts) + Spread tightness (10pts) + Trend direction (10pts)
        </div>""", unsafe_allow_html=True)

    with tabs[5]:
        st.markdown(f"""
        <div style="background:{BG_CARD};border:2px solid {ACCENT_RED}55;border-radius:10px;padding:28px;color:{TEXT_PRIMARY};line-height:1.9;font-size:14px">
        <h3 style="color:{ACCENT_RED};font-family:'Cormorant Garamond',serif;font-size:22px">⚠️ Important Disclaimer</h3>

        <p><b>Golden Scanner is an educational and research tool only.</b> Nothing on this platform constitutes financial advice, investment advice, trading advice, or any other form of advice.</p>

        <p>The signals, scores, and data presented are generated algorithmically using publicly available market data. They are provided for <b>informational and educational purposes only</b> and should not be interpreted as recommendations to buy, sell, or hold any security.</p>

        <p><b>Trading involves substantial risk of loss.</b> Options trading in particular carries significant leverage risk. 3× leveraged ETFs are complex instruments subject to volatility decay and are not suitable for most investors.</p>

        <p>Past performance of any scanner criteria is <b>not indicative of future results.</b> Market conditions change, and historical patterns do not guarantee future performance.</p>

        <p>Always consult a qualified financial advisor before making investment decisions. Always do your own due diligence. Never risk capital you cannot afford to lose.</p>

        <div style="margin-top:20px;padding:16px;background:{BG_PANEL};border-radius:6px;color:{TEXT_MUTED};font-size:12px">
            Data sourced from Yahoo Finance via yfinance. Options data may have 15-minute delays.
            Fundamental data is end-of-day. Neither the platform nor its creators are registered investment advisors.
            Use at your own risk.
        </div>
        </div>""", unsafe_allow_html=True)
