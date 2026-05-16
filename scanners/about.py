# scanners/about.py — About & User Guide

import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *
from utils import section_header


def _expander(icon: str, title: str, what: str, how_to_use: str, tip: str = ""):
    with st.expander(f"{icon}  {title}", expanded=False):
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:13px;line-height:1.8;margin-bottom:10px">{what}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div style="color:{TEXT_PRIMARY};font-size:13px;line-height:1.9">'
            f'<b style="color:{GOLD}">How to use it:</b><br>{how_to_use}</div>',
            unsafe_allow_html=True,
        )
        if tip:
            st.markdown(
                f'<div style="background:{BG_PANEL};border-left:3px solid {GOLD};'
                f'padding:8px 14px;border-radius:4px;color:{TEXT_MUTED};'
                f'font-size:12px;margin-top:10px">&#128161; {tip}</div>',
                unsafe_allow_html=True,
            )


def render():
    section_header("ℹ️", "About & Guide",
                   "How to use Golden Scanner · Feature reference · Disclaimer")

    # ── Hero ──────────────────────────────────────────────────────
    st.markdown(
        f'<div style="background:linear-gradient(135deg,{BG_CARD},{BG_PANEL});'
        f'border:1px solid {GOLD}44;border-radius:12px;padding:32px;'
        f'text-align:center;margin-bottom:28px">'
        f'<div style="font-family:\'Cormorant Garamond\',serif;font-size:40px;'
        f'color:{GOLD};font-weight:700;letter-spacing:3px">&#10022; GOLDEN SCANNER</div>'
        f'<div style="color:{TEXT_MUTED};font-size:12px;letter-spacing:3px;'
        f'text-transform:uppercase;margin:8px 0 16px">Precision Trading Intelligence Platform</div>'
        f'<div style="color:{TEXT_PRIMARY};font-size:15px;max-width:620px;margin:0 auto;line-height:1.9">'
        f'A professional-grade multi-scanner platform that surfaces high-probability trade setups '
        f'across stocks, options, ETFs, and market trends — cutting through noise so you can act '
        f'with speed and conviction.</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    tabs = st.tabs([
        "&#128210; Getting Started",
        "&#128257; Scanners",
        "&#128241; Social Trends",
        "&#127919; Options",
        "&#9889; 3&#215; Leveraged",
        "&#128181; Dividends",
        "&#128202; Reading Results",
        "&#9888;&#65039; Disclaimer",
    ])

    # ── Tab 1: Getting Started ─────────────────────────────────────
    with tabs[0]:
        st.markdown(
            f'<div style="color:{TEXT_PRIMARY};line-height:1.9;font-size:14px">'

            f'<h3 style="color:{GOLD};font-family:\'Cormorant Garamond\',serif">Quick Start</h3>'
            f'<p><b>1. Choose a section</b> from the sidebar. Start with <b style="color:{GOLD}">Market Overview</b> '
            f'for a pulse on current market conditions and strategy signals.</p>'
            f'<p><b>2. Run a scan</b> by clicking &#9654; Run Scan. Stock scans typically complete in 30–90 seconds. '
            f'Options scans take 1–3 minutes as they retrieve live options data per ticker.</p>'
            f'<p><b>3. Read results</b> sorted by Signal Score (highest conviction first). '
            f'Use column headers to re-sort by any metric.</p>'
            f'<p><b>4. Adjust filters</b> in the sidebar to tighten or widen the scan criteria. '
            f'Default values are calibrated for quality — change them when you want a broader or narrower view.</p>'
            f'<p><b>5. Export</b> any result set to CSV using the &#11015; Export button below the table.</p>'

            f'<h3 style="color:{GOLD};font-family:\'Cormorant Garamond\',serif;margin-top:24px">Navigation</h3>'
            f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:12px 0">',
            unsafe_allow_html=True,
        )

        nav_items = [
            ("&#127968;", "Market Overview",   "Live market indices + strategy signals for SPY, QQQ, TSLA"),
            ("&#128241;", "Social Trends",     "Financial news, Reddit discussions, YouTube — signal-scored"),
            ("&#128197;", "Scheduled Scans",   "Auto-runs at 10:30 AM & 1:00 PM CST — Golden Scan + CSP + LEAPS results"),
            ("&#128257;", "Golden Scan",       "All stock scanners merged — multi-signal picks ranked first"),
            ("&#128300;", "Stock Analysis",    "Deep single-ticker technical breakdown across multiple timeframes"),
            ("&#9889;&#128202;", "3&#215; Leveraged ETFs", "High-velocity directional momentum setups"),
            ("&#128176;", "Cash-Secured Puts", "Income from selling puts on stocks you want to own"),
            ("&#128248;", "LEAPS",             "Long-dated calls as a capital-efficient stock replacement"),
            ("&#9889;&#128200;", "3&#215; ETF Options",    "Premium selling on leveraged instruments"),
            ("&#128200;", "ETF Options",       "Premium selling on broad, liquid ETF options"),
            ("&#128181;", "Upcoming Dividends","Ex-dividend plays with strong chart setups"),
            ("&#128451;", "Tracking",          "Log trade setups — auto-populated from AM/PM scheduled scans"),
        ]
        cards = "".join(
            f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:8px;padding:10px 14px">'
            f'<div style="font-size:16px;margin-bottom:4px">{icon}</div>'
            f'<div style="color:{GOLD};font-size:12px;font-weight:700;margin-bottom:3px">{name}</div>'
            f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.5">{desc}</div>'
            f'</div>'
            for icon, name, desc in nav_items
        )
        st.markdown(
            f'<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px;margin:12px 0">'
            f'{cards}</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            f'<h3 style="color:{GOLD};font-family:\'Cormorant Garamond\',serif;margin-top:24px">Tips</h3>'
            f'<ul style="color:{TEXT_PRIMARY};font-size:13px;line-height:2.2">'
            f'<li>Check <b>Scheduled Scans</b> first — Golden Scan + CSP + LEAPS run automatically at 10:30 AM &amp; 1:00 PM CST</li>'
            f'<li>Start with <b>Golden Scan</b> — tickers appearing in multiple scanners (high Scanner Count) have the highest conviction</li>'
            f'<li>Check <b>Social Trends</b> to see what the market is talking about before trading</li>'
            f'<li>For options (CSP / LEAPS), always confirm the underlying stock trend before entering</li>'
            f'<li>3&#215; ETF trades should be sized conservatively — they move fast in both directions</li>'
            f'<li>Data refreshes every 5 minutes. Use the &#128260; Refresh button to force an update</li>'
            f'<li>The Score column ranks quality — it is a relative ranking tool, not a binary buy/sell trigger</li>'
            f'</ul>'
            f'<p style="color:{TEXT_MUTED};font-size:12px;margin-top:8px">'
            f'Data is sourced from Yahoo Finance. Options data may carry a short delay. '
            f'Fundamental data (P/E, earnings growth) is end-of-day.</p>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── Tab 2: Scanners ────────────────────────────────────────────
    with tabs[1]:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:13px;padding:8px 0 16px">'
            f'All stock scanners share a common universe of S&P 500 stocks and key ETFs. '
            f'<b style="color:{GOLD}">Golden Scan</b> runs them all at once — use individual scanners '
            f'when you want focused results for a specific strategy. '
            f'Golden Scan also runs automatically at <b style="color:{GOLD}">10:30 AM &amp; 1:00 PM CST</b> '
            f'on market days — check the Scheduled Scans page for the latest results.</div>',
            unsafe_allow_html=True,
        )

        _expander("🔀", "Golden Scan",
            "The flagship scanner. Runs every stock scanner simultaneously, merges all results into one table, "
            "and ranks tickers by how many independent scanners confirmed them. A ticker showing up in three "
            "different scanners — each looking at different signals — has much stronger confirmation than one "
            "that appears in only one.",
            "Set the universe size in the sidebar (default 200 tickers, key ETFs always included). "
            "Toggle Value and Growth scanners on or off — they are slower due to fundamental data fetching. "
            "Sort by Scanner Count to see the multi-confirmed picks at the top. "
            "Est. Upside % shows the distance to the 52-week high as a rough target.",
            "Multi-signal picks are not guarantees — they just mean multiple independent signals agree. "
            "Still do your own research before trading any result."
        )
        _expander("⚡", "Momentum",
            "Finds stocks in strong directional uptrends with healthy price action and above-average participation. "
            "This scanner is looking for the kind of move where price, trend, momentum, and volume all "
            "point in the same direction at the same time.",
            "Best for swing trades lasting 1–4 weeks. Results with the highest scores show the cleanest "
            "alignment across all signals. The top result (expanded by default) often represents the "
            "clearest near-term opportunity in the scan.",
            "Avoid chasing results that already moved significantly. Look for stocks just breaking out, "
            "not ones already extended."
        )
        _expander("💎", "Value",
            "Identifies companies that may be trading below their fundamental worth — solid businesses at "
            "reasonable prices. This scanner looks at valuation ratios and balance sheet health together, "
            "filtering for companies that are cheap for good reasons rather than bad ones.",
            "Best for long-term position trades (3 months to 1 year). Check the Trap Risk column — "
            "High risk means the low valuation may be a value trap rather than an opportunity. "
            "Prefer results that are also above their long-term moving average.",
            "Value investing requires patience. These setups are not short-term momentum plays."
        )
        _expander("🚀", "Growth",
            "Surfaces companies with accelerating revenue and earnings expansion — businesses growing "
            "meaningfully faster than the market. High growth stocks tend to attract institutional "
            "buying, which creates sustained upward price pressure.",
            "Best for trend-following positions held 1–6 months. The RS vs SPY column shows whether "
            "the stock is outperforming the market — strong growth stocks should be leading the index, "
            "not lagging it.",
            "Earnings beats often cause growth stocks to gap up sharply. Consider running this scanner "
            "after earnings season begins."
        )
        _expander("📰", "Headlines & Catalysts",
            "Captures stocks making significant moves on catalysts — earnings surprises, analyst upgrades, "
            "M&A news, or regulatory decisions. Volume confirms whether the move is a real institutional "
            "reaction or just noise.",
            "Best for same-day or next-day trades. Sort by Change % to see the biggest movers. "
            "Check the Catalyst column to understand what's driving the move before trading it. "
            "High volume on a big move = institutions reacting, not retail.",
            "Catalyst-driven moves can reverse sharply once the news is digested. Use tight stops."
        )
        _expander("🔬", "Stock Analysis",
            "A deep-dive single-ticker view that combines technical indicators across multiple timeframes "
            "into one comprehensive panel. Unlike the scanners which scan many stocks quickly, "
            "Stock Analysis goes deep on up to 5 individual tickers you specify.",
            "Enter up to 5 tickers separated by commas, then click Analyze. Each ticker gets its own "
            "panel showing trend direction, momentum, volume profile, and a consolidated Buy/Sell/Neutral "
            "signal with confidence percentage. The interactive chart shows key indicators overlaid on price.",
            "Use this after a scanner surfaces a setup — run the scanner to find candidates, then "
            "use Stock Analysis to go deep on the best ones before deciding to trade."
        )

    # ── Tab 3: Social Trends ───────────────────────────────────────
    with tabs[2]:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:13px;padding:8px 0 16px">'
            f'Real-time market intelligence from financial news and social media, '
            f'filtered for signal quality and scored by relevance.</div>',
            unsafe_allow_html=True,
        )
        _expander("🔥", "Hot News",
            "Aggregates financial news from major sources — Yahoo Finance, CNBC, Reuters, MarketWatch, "
            "and Benzinga — filtered to show only market-relevant stories. Duplicate stories covering "
            "the same ticker and event are merged into one card.",
            "Each card shows a sentiment badge (Bullish / Bearish / Neutral) and a Signal Score. "
            "Use the ticker filter at the top to see only news about a specific stock. "
            "Turn on Signal Mode to show only the highest-conviction items.",
            "The Trending Tickers panel at the top shows tickers mentioned in multiple articles "
            "simultaneously — a strong indicator that the market is focused on those names."
        )
        _expander("💬", "Reddit",
            "Monitors discussions across major investing subreddits. Posts are filtered for financial "
            "relevance and minimum engagement — only posts with meaningful community discussion are shown. "
            "Deep Dive posts (flaired as DD or Analysis) are highlighted with a star badge.",
            "The Trending Tickers panel shows which tickers are being discussed most across all "
            "subreddits combined with the sentiment breakdown. Use this to spot emerging crowd "
            "sentiment shifts before they move price.",
            "Social media sentiment is a lagging indicator for large moves but can be an early signal "
            "for smaller-cap stocks. Use it as context, not as a primary trade signal."
        )
        _expander("🎥", "YouTube",
            "Monitors financial YouTube channels for recent videos with actionable ticker analysis. "
            "Activated when a YouTube API key is added to app secrets.",
            "Add YOUTUBE_API_KEY to your Streamlit secrets to enable this section. "
            "The channel list monitors well-known financial creators focused on stocks and options.",
            "YouTube content is often educational rather than time-sensitive. Videos take time to produce "
            "so they typically reflect analysis from 1–3 days ago."
        )
        _expander("🌐", "Combined Feed",
            "All sources merged into a single unified feed, sorted by Signal Score. "
            "The highest-scoring item combines strong recency, high engagement, specific ticker "
            "mentions, and clear directional sentiment.",
            "This is the fastest way to see what is moving markets right now. "
            "Signal Mode filters to only show high-conviction items across all sources.",
            "Use the ticker filter to research a specific stock across all social sources at once."
        )

    # ── Tab 4: Options ─────────────────────────────────────────────
    with tabs[3]:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:13px;padding:8px 0 16px">'
            f'Options scanners surface premium-selling and capital-efficient buying opportunities. '
            f'CSP and LEAPS run automatically in scheduled scans (10:30 AM &amp; 1:00 PM CST) on 75 '
            f'top stocks + liquid ETF universe. Higher implied volatility = more premium collected.</div>',
            unsafe_allow_html=True,
        )
        _expander("💰", "Cash-Secured Puts (CSP)",
            "You sell a put option on a stock you are willing to own at a lower price. "
            "The buyer pays you a premium upfront. If the stock stays above your strike price, "
            "you keep the entire premium as profit. If it falls below, you buy the stock at "
            "the strike — which you wanted anyway.",
            "The scanner surfaces stocks with elevated option premiums and bullish trends — "
            "the ideal environment for selling puts. Key columns: Strike (the price at which "
            "you'd buy the stock), Premium % (annualized return if the put expires worthless), "
            "and Breakeven (the price below which you start losing money). "
            "Default: premium ≥ 0.65% of stock price, DTE 25–35 days.",
            "Best candidates: stocks you would genuinely want to own at a 5–15% discount. "
            "Never sell puts on stocks you are not comfortable holding."
        )
        _expander("🧨", "LEAPS",
            "Long-dated deep-in-the-money call options that behave similarly to owning shares, "
            "but require significantly less capital. Instead of buying 100 shares, you buy one "
            "LEAP that gives you similar exposure for a fraction of the cost.",
            "Key columns: Delta (how closely the option tracks the stock — higher is more stock-like), "
            "Leverage Ratio (how much stock exposure you get per dollar invested), "
            "and IV Rank (lower is better when buying options — you want to buy when premium is cheap). "
            "Look for strong underlying trends — LEAPS work best in extended bull moves.",
            "LEAPS require more monitoring than stock ownership. The option loses value as time passes, "
            "even if the stock is flat. Set a reminder to review every 30–60 days."
        )
        _expander("📈", "ETF Options",
            "Premium selling on major ETF options — SPY, QQQ, IWM, sector ETFs. "
            "ETFs tend to have tighter bid/ask spreads and more predictable behavior than "
            "individual stocks because they carry no single-company earnings risk.",
            "These are ideal for traders who want to sell premium consistently without "
            "the risk of a single stock gapping down on bad news. The same CSP and CC "
            "strategies apply — the scanner applies them to a curated list of liquid ETFs.",
            "ETF options are a favorite of institutional traders for exactly this reason: "
            "diversified underlying + liquid options + no binary events."
        )

    # ── Tab 5: 3× Leveraged ────────────────────────────────────────
    with tabs[4]:
        st.markdown(
            f'<div style="background:{ACCENT_RED}15;border:1px solid {ACCENT_RED}44;border-radius:8px;'
            f'padding:12px 16px;margin-bottom:16px;color:{TEXT_PRIMARY};font-size:13px">'
            f'&#9888;&#65039; <b style="color:{ACCENT_RED}">Important:</b> 3&#215; leveraged instruments are designed for '
            f'short-term directional trades only. They are not suitable for long-term holding. '
            f'Always size positions conservatively.</div>',
            unsafe_allow_html=True,
        )
        _expander("⚡📊", "3× Leveraged ETFs",
            "Triple-leverage ETFs aim to deliver 3× the daily return of their benchmark index. "
            "TQQQ tracks 3× QQQ. SOXL tracks 3× semiconductors. UPRO tracks 3× SPY. "
            "In a strong directional trend, these can generate outsized returns quickly. "
            "In choppy or sideways markets, they lose value due to compounding effects.",
            "The scanner finds leveraged ETFs in strong momentum conditions with rising volatility — "
            "the environment where they perform best. Direction filter lets you scan Bull (long) or "
            "Bear (inverse) ETFs separately. ATR Warning column shows current volatility level "
            "so you can size accordingly.",
            "These are best held for 1–5 days in a clear trend. Exit at the first sign of reversal. "
            "Never hold through high-volatility periods or unexpected market events."
        )
        _expander("⚡📈", "3× ETF Options",
            "Options on 3× ETFs carry extreme implied volatility, which creates very high premiums. "
            "This makes them attractive for premium sellers who understand the underlying risks. "
            "The potential income is significantly higher than standard ETF options.",
            "Premium % and ATR % are the two most important columns here. Premium/Risk ratio "
            "tells you how much you are being paid relative to the instrument's daily movement range — "
            "the higher this ratio, the better the risk/reward for the seller. Use short expirations.",
            "The same volatility that generates high premium can work against you quickly. "
            "Position sizes should be smaller than you would use for standard ETF options."
        )

    # ── Tab 6: Dividends ───────────────────────────────────────────
    with tabs[5]:
        _expander("💵", "Upcoming Dividends",
            "Identifies stocks approaching their ex-dividend date with strong technical setups. "
            "To receive a dividend, you must own the stock before the ex-dividend date. "
            "This scanner helps you find dividend-paying stocks that are also technically sound "
            "— not just high-yield traps.",
            "Key columns: Ex-Date (you must own shares before this date), Yield % (annual dividend "
            "as a percentage of stock price), and DTE (days until ex-dividend). "
            "Sort by Yield % to see the highest income opportunities. Check the Score column "
            "to confirm the stock has a healthy technical setup.",
            "A high dividend yield on a falling stock is often a warning sign, not an opportunity. "
            "The technical score filters help avoid these situations."
        )

    # ── Tab 7: Reading Results ─────────────────────────────────────
    with tabs[6]:
        st.markdown(
            f'<h3 style="color:{GOLD};font-family:\'Cormorant Garamond\',serif">Signal Score (0–100)</h3>'
            f'<p style="color:{TEXT_MUTED};font-size:13px;line-height:1.8">Every result includes a composite '
            f'Signal Score that combines multiple independent signals into one number. '
            f'Use it to rank and prioritize — higher score means more signals aligned, not a guaranteed outcome.</p>',
            unsafe_allow_html=True,
        )

        score_rows = [
            (ACCENT_GREEN, "80 – 100", "&#128293; Strong Setup",
             "Near-perfect alignment across all measured signals. Highest conviction — act with appropriate sizing."),
            ("#86EFAC",    "60 – 79",  "&#9989; Solid Setup",
             "Most signals aligned. Good risk/reward ratio. Worth detailed review before trading."),
            (TEXT_MUTED,   "40 – 59",  "&#9898; Neutral",
             "Mixed signals. Some criteria met, others not. Wait for stronger alignment or wider context."),
            ("#FCA5A5",    "20 – 39",  "&#128315; Weak",
             "Few signals aligned. Low-conviction setup. Avoid or monitor for improvement."),
            (ACCENT_RED,   "0 – 19",   "&#128128; Avoid",
             "Setup does not meet quality criteria. Move on."),
        ]
        for color, rng, label, desc in score_rows:
            st.markdown(
                f'<div style="background:{BG_CARD};border:1px solid {color}44;border-left:3px solid {color};'
                f'border-radius:6px;padding:12px 16px;margin-bottom:8px">'
                f'<div style="display:flex;justify-content:space-between;align-items:center">'
                f'<span style="color:{color};font-weight:700;font-size:15px">{label}</span>'
                f'<span style="color:{color};font-family:\'DM Mono\',monospace;font-size:13px">{rng}</span>'
                f'</div>'
                f'<div style="color:{TEXT_MUTED};font-size:12px;margin-top:5px">{desc}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        st.markdown(
            f'<h3 style="color:{GOLD};font-family:\'Cormorant Garamond\',serif;margin-top:24px">Common Columns</h3>',
            unsafe_allow_html=True,
        )
        columns = [
            ("RSI", "Relative Strength Index — measures momentum. Values above 50 indicate buying pressure. Very high RSI suggests the move may be overextended."),
            ("Vol Ratio", "Current volume compared to recent average. Above 1.0 means more activity than usual, which confirms price moves are real."),
            ("RS vs SPY", "Relative strength compared to the S&P 500. Above 1.0 means the stock is outperforming the index — a sign of institutional interest."),
            ("ATR %", "Average True Range as a percentage — measures how much the stock typically moves per day. Use this to size positions and set stop distances."),
            ("MACD Bull", "Whether short-term momentum is accelerating to the upside. ✅ = positive momentum. ❌ = momentum fading."),
            ("Change %", "Today's price change as a percentage. Color-coded: green = up, red = down."),
            ("Score", "The composite Signal Score. Higher = more signals aligned = higher conviction setup."),
            ("Hold", "Recommended holding period for the strategy type. Not a hard rule — your risk management overrides this."),
            ("Est. Upside %", "Rough estimate of potential upside to the 52-week high. A target zone, not a price prediction."),
        ]
        col_html = "".join(
            f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:6px;padding:10px 14px">'
            f'<div style="color:{GOLD};font-family:\'DM Mono\',monospace;font-size:12px;font-weight:700;margin-bottom:4px">{col}</div>'
            f'<div style="color:{TEXT_MUTED};font-size:12px;line-height:1.6">{meaning}</div>'
            f'</div>'
            for col, meaning in columns
        )
        st.markdown(
            f'<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:8px;margin-top:8px">'
            f'{col_html}</div>',
            unsafe_allow_html=True,
        )

    # ── Tab 8: Disclaimer ──────────────────────────────────────────
    with tabs[7]:
        st.markdown(
            f'<div style="background:{BG_CARD};border:2px solid {ACCENT_RED}44;border-radius:10px;'
            f'padding:28px;color:{TEXT_PRIMARY};line-height:1.9;font-size:14px">'
            f'<h3 style="color:{ACCENT_RED};font-family:\'Cormorant Garamond\',serif;font-size:22px">'
            f'&#9888;&#65039; Important Disclaimer</h3>'
            f'<p><b>Golden Scanner is an educational and research tool only.</b> Nothing on this platform '
            f'constitutes financial advice, investment advice, trading advice, or any other form of advice.</p>'
            f'<p>Signals, scores, and data are generated from publicly available market data for '
            f'<b>informational and educational purposes only</b> and should not be interpreted as '
            f'recommendations to buy, sell, or hold any security.</p>'
            f'<p><b>Trading involves substantial risk of loss.</b> Options trading carries significant '
            f'leverage risk. 3&#215; leveraged ETFs are complex instruments subject to volatility '
            f'decay and compounding losses — they are not suitable for most investors.</p>'
            f'<p>Past performance of any signals or scanner criteria is <b>not indicative of future results.</b> '
            f'Markets change. Historical patterns do not guarantee future performance.</p>'
            f'<p>Always consult a qualified financial advisor before making investment decisions. '
            f'Always do your own due diligence. Never risk capital you cannot afford to lose.</p>'
            f'<div style="margin-top:20px;padding:14px;background:{BG_PANEL};border-radius:6px;'
            f'color:{TEXT_MUTED};font-size:12px">'
            f'Data sourced from Yahoo Finance. Options data may have delays. '
            f'Fundamental data is end-of-day. Neither this platform nor its creators are registered '
            f'investment advisors. Use entirely at your own risk.</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
