# scanners/admin_page.py — Admin Panel
# Tab 1: Scanner guide with parameters
# Tab 2: Deduplicated stock universe browser

import streamlit as st
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *
from utils import section_header, metric_card


# ── Scanner catalog ────────────────────────────────────────────

SCANNERS = [
    {
        "key":   "Golden Scan",
        "emoji": "🔀",
        "color": GOLD,
        "desc":  "Combines all scanners, scores each signal, and ranks by multi-factor conviction. Best starting point for daily scans.",
        "params": [
            ("Universe", f"{len(SP500_SAMPLE)} tickers", "Stocks + ETFs"),
            ("Scoring",  "Multi-factor", "Price · Volume · Technicals · Fundamentals"),
        ],
        "criteria": "Runs Momentum, Growth, Value, and Headlines sub-scans. Each ticker is scored 0–100 and ranked.",
    },
    {
        "key":   "Momentum",
        "emoji": "🔥",
        "color": ACCENT_GREEN,
        "desc":  "Finds stocks with strong price momentum, elevated RSI, above-average volume, and relative strength vs SPY.",
        "params": [
            ("RSI Range",    f"{MOMENTUM_DEFAULTS['rsi_min']}–{MOMENTUM_DEFAULTS['rsi_max']}", "Overbought but not extended"),
            ("Vol Spike",    f"{MOMENTUM_DEFAULTS['vol_mult']}×", "Minimum vs 20-day average"),
            ("Min Price",    f"${MOMENTUM_DEFAULTS['price_min']}", "Filters sub-penny stocks"),
            ("Min Mkt Cap",  f"${MOMENTUM_DEFAULTS['mcap_min']/1e9:.0f}B", "Large-cap only by default"),
        ],
        "criteria": "Price > SMA50 · RSI 55–68 · MACD bullish · Volume spike · RS vs SPY",
    },
    {
        "key":   "Growth",
        "emoji": "🚀",
        "color": "#818CF8",
        "desc":  "Identifies companies with accelerating revenue and EPS growth trading above their 50-day moving average.",
        "params": [
            ("Rev Growth", f"≥ {GROWTH_DEFAULTS['rev_growth_min']}%", "Year-over-year"),
            ("EPS Growth", f"≥ {GROWTH_DEFAULTS['eps_growth_min']}%", "Year-over-year"),
            ("RS vs SPY",  f"≥ {GROWTH_DEFAULTS['rs_min']}×",        "6-month relative strength"),
            ("Min Price",  f"${GROWTH_DEFAULTS['price_min']}",        ""),
        ],
        "criteria": "Revenue growth · EPS expansion · Price above SMA50 · Positive MACD histogram",
    },
    {
        "key":   "Value",
        "emoji": "💎",
        "color": ACCENT_BLUE,
        "desc":  "Screens for undervalued companies with strong balance sheets, positive free cash flow, and low debt.",
        "params": [
            ("Max P/E",  f"≤ {VALUE_DEFAULTS['pe_max']}",         "Trailing or forward"),
            ("Max P/B",  f"≤ {VALUE_DEFAULTS['pb_max']}",         "Price-to-book"),
            ("Min ROE",  f"≥ {VALUE_DEFAULTS['roe_min']}%",       "Return on equity"),
            ("Max D/E",  f"≤ {VALUE_DEFAULTS['de_max']}×",        "Debt-to-equity"),
        ],
        "criteria": "Positive FCF · Below P/E and P/B thresholds · ROE above minimum · Price above 200 SMA",
    },
    {
        "key":   "Headlines",
        "emoji": "📰",
        "color": "#F472B6",
        "desc":  "Detects stocks making outsized moves on news catalysts — earnings surprises, upgrades, M&A, product launches.",
        "params": [
            ("Min Move",    "≥ 3%",   "Absolute daily price change"),
            ("Vol Spike",   "≥ 1.25×","Vs prior 4-day average"),
            ("Gap Filter",  "≥ 1.5%", "Optional gap-up/down filter"),
        ],
        "criteria": "Large price move · Volume spike · Gap detection · Catalyst tagging (Mega Move / Major Move / News)",
    },
    {
        "key":   "CSP",
        "emoji": "💰",
        "color": ACCENT_GREEN,
        "desc":  "Cash-Secured Puts — sell OTM puts on stocks you want to own. Collects premium while waiting for a better entry.",
        "params": [
            ("IV Rank",   f"≥ {CSP_DEFAULTS['iv_rank_min']}",      "High IV = fat premium"),
            ("Delta",     f"{CSP_DEFAULTS['delta_min']}–{CSP_DEFAULTS['delta_max']}", "Strike selection"),
            ("Premium",   f"≥ {CSP_DEFAULTS['premium_pct_min']}%",  "Of stock price per week"),
            ("DTE",       f"{CSP_DEFAULTS['dte_min']}–{CSP_DEFAULTS['dte_max']} days", "Days to expiration"),
        ],
        "criteria": "Sell action · Strike below market · Positive theta · Bid/ask spread check",
    },
    {
        "key":   "CC",
        "emoji": "📦",
        "color": ACCENT_BLUE,
        "desc":  "Covered Calls — sell OTM calls against a long stock position to generate income.",
        "params": [
            ("Delta",    f"{CC_DEFAULTS['delta_min']}–{CC_DEFAULTS['delta_max']}", "Strike above market"),
            ("Premium",  f"≥ {CC_DEFAULTS['premium_pct_min']}%",  "Of stock price"),
            ("DTE",      f"{CC_DEFAULTS['dte_min']}–{CC_DEFAULTS['dte_max']} days", ""),
        ],
        "criteria": "Sell action · OTM call · Premium yield per expiration · Bid/ask spread check",
    },
    {
        "key":   "LEAPS",
        "emoji": "🧨",
        "color": "#A78BFA",
        "desc":  "Long-term equity anticipation securities — deep ITM calls as leveraged stock replacement with defined risk.",
        "params": [
            ("DTE",      f"≥ {LEAPS_DEFAULTS['dte_min']} days",     "12–24 month expirations"),
            ("Delta",    f"{LEAPS_DEFAULTS['delta_min']}–{LEAPS_DEFAULTS['delta_max']}", "Deep ITM"),
            ("IV Rank",  f"≤ {LEAPS_DEFAULTS['iv_rank_max']}",      "Buy when IV is low"),
        ],
        "criteria": "Buy action · High delta (ITM) · Long dated · Low IV environment preferred",
    },
    {
        "key":   "Dividend",
        "emoji": "💵",
        "color": "#34D399",
        "desc":  "Upcoming ex-dividend event scanner — find stocks paying dividends soon with quality yield and volume filters.",
        "params": [
            ("Window",    "1–12 weeks", "Ahead of ex-div date"),
            ("Yield",     "1–20%",      "Annual dividend yield range"),
            ("Min Volume","0.1M+",      "Avg daily volume"),
        ],
        "criteria": "Ex-div date within window · Yield in range · Above volume threshold · Price history available",
    },
    {
        "key":   "Div+CC",
        "emoji": "📅",
        "color": "#FCD34D",
        "desc":  "Dividend + Covered Call Capture — buy dividend stock, sell CC expiring after ex-div, collect both income streams.",
        "params": [
            ("Max Days to Ex-Div", "≤ 25 days", "Short window for entry"),
            ("Min Income %",       "≥ 0.5%",    "Premium + dividend combined"),
            ("Max OTM %",          "≤ 7%",      "CC strike above spot price"),
        ],
        "criteria": "Combined income yield · CC premium + dividend ≥ threshold · Strike within OTM band",
    },
    {
        "key":   "3x ETFs",
        "emoji": "⚡",
        "color": ACCENT_RED,
        "desc":  "3× Leveraged ETF scanner — momentum signals on leveraged funds (TQQQ, SOXL, UPRO, etc.) for short-term trades.",
        "params": [
            ("RSI Range",  f"{ETF3X_DEFAULTS['rsi_min']}–{ETF3X_DEFAULTS['rsi_max']}", ""),
            ("Vol Spike",  f"{ETF3X_DEFAULTS['vol_mult']}×",   ""),
            ("Min Price",  f"${ETF3X_DEFAULTS['price_min']}",  ""),
            ("Universe",   f"{len(ETF_3X_UNIVERSE)} ETFs",     "Bull + bear leveraged funds"),
        ],
        "criteria": "Price above SMA20 · RSI in range · MACD bullish · Volume spike confirmation",
    },
]


# ── Universe builder ───────────────────────────────────────────

def _build_universe_df() -> pd.DataFrame:
    """Deduplicated ticker table from all config universe lists."""
    # Map ticker → set of universe names
    ticker_map: dict[str, list] = {}

    def _add(tickers, label):
        for t in tickers:
            ticker_map.setdefault(t, [])
            if label not in ticker_map[t]:
                ticker_map[t].append(label)

    _add(SP500_SAMPLE[:200],            "Stock Universe (top 200)")
    _add(SP500_SAMPLE[200:],            "Stock Universe (extended)")
    _add(ETF_UNIVERSE,                  "ETF Universe")
    _add(ETF_3X_UNIVERSE,               "3× ETF Scanner")
    _add(OPTIONS_ETF_UNIVERSE,          "Options ETF")

    rows = [
        {
            "Ticker":     t,
            "Used In":    ", ".join(v),
            "# Lists":    len(v),
        }
        for t, v in sorted(ticker_map.items())
    ]
    return pd.DataFrame(rows)


# ── Render helpers ─────────────────────────────────────────────

def _render_guide():
    # Summary strip — scanner count + quick stat
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("📡 Scanners Available", str(len(SCANNERS)))
    with c2:
        st.metric("🗂️ Universe Size", f"{len(SP500_SAMPLE):,} tickers")
    with c3:
        st.metric("⚡ Options ETFs", f"{len(OPTIONS_ETF_UNIVERSE)} liquid ETFs")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:12px;margin-bottom:12px">'
        f'Click any scanner to expand its default parameters and technical criteria. '
        f'All filters are adjustable via the sidebar at run time.</div>',
        unsafe_allow_html=True,
    )

    # Group scanners visually
    groups = {
        "📊 Multi-Factor": ["Golden Scan"],
        "📈 Equity Scans": ["Momentum", "Growth", "Value", "Headlines"],
        "🎯 Options Strategies": ["CSP", "CC", "LEAPS"],
        "💰 Income & Dividends": ["Dividend", "Div+CC"],
        "⚡ Leveraged": ["3x ETFs"],
    }

    for group_name, keys in groups.items():
        st.markdown(
            f'<div style="color:{GOLD};font-size:11px;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:1.2px;margin:16px 0 6px;padding-bottom:4px;'
            f'border-bottom:1px solid {GOLD}33">{group_name}</div>',
            unsafe_allow_html=True,
        )
        group_scanners = [sc for sc in SCANNERS if sc["key"] in keys]
        for sc in group_scanners:
            color = sc["color"]
            with st.expander(f"{sc['emoji']}  **{sc['key']}**", expanded=False):
                # Accent header bar
                st.markdown(
                    f'<div style="border-left:4px solid {color};padding:10px 16px;'
                    f'background:linear-gradient(90deg,{color}18,{BG_PANEL});'
                    f'border-radius:0 8px 8px 0;margin-bottom:14px">'
                    f'<span style="color:{TEXT_PRIMARY};font-size:13px;line-height:1.5">{sc["desc"]}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                # Default param metric cards
                if sc["params"]:
                    cols = st.columns(min(len(sc["params"]), 4))
                    for col, (label, value, help_text) in zip(cols, sc["params"]):
                        with col:
                            st.metric(label=label, value=value, help=help_text or None)

            # Technical criteria
            st.markdown(
                f'<div style="color:{TEXT_MUTED};font-size:11px;margin-top:10px;'
                f'border-top:1px solid {BORDER_COLOR};padding-top:8px">'
                f'<b style="color:{color}">Criteria: </b>{sc["criteria"]}</div>',
                unsafe_allow_html=True,
            )


def _render_universe():
    df = _build_universe_df()
    total_unique = len(df)
    multi_list   = int((df["# Lists"] >= 2).sum())
    etf_count    = int(df["Ticker"].isin(ETF_UNIVERSE + OPTIONS_ETF_UNIVERSE + ETF_3X_UNIVERSE).sum())

    # Summary metrics
    m1, m2, m3, m4 = st.columns(4)
    with m1: st.metric("Unique Tickers",  f"{total_unique:,}")
    with m2: st.metric("In Multiple Lists", f"{multi_list}")
    with m3: st.metric("ETF / Fund Count",  f"{etf_count}")
    with m4: st.metric("Stock-Only",  f"{total_unique - etf_count:,}")

    st.markdown("<br>", unsafe_allow_html=True)

    # Search
    c1, c2 = st.columns([4, 1])
    with c1:
        search = st.text_input("", placeholder="🔍 Search ticker or universe name…",
                               label_visibility="collapsed")
    with c2:
        filter_multi = st.checkbox("Multi-list only", value=False,
                                   help="Show only tickers appearing in 2+ universe lists")

    filtered = df.copy()
    if search:
        mask = (filtered["Ticker"].str.contains(search.upper(), na=False) |
                filtered["Used In"].str.contains(search, case=False, na=False))
        filtered = filtered[mask]
    if filter_multi:
        filtered = filtered[filtered["# Lists"] >= 2]

    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:12px;margin-bottom:6px">'
        f'Showing <b style="color:{GOLD}">{len(filtered)}</b> of {total_unique} tickers</div>',
        unsafe_allow_html=True,
    )

    # Colour-code rows: gold = 3+ lists, green = 2 lists, default = 1 list
    def _style_rows(row):
        if row["# Lists"] >= 3:
            bg = f"background-color: {GOLD}22; color: {GOLD};"
        elif row["# Lists"] == 2:
            bg = f"background-color: {ACCENT_GREEN}11; color: {ACCENT_GREEN};"
        else:
            bg = ""
        return [bg] * len(row)

    styled = filtered.style.apply(_style_rows, axis=1)

    import streamlit.components.v1 as components
    st.dataframe(
        styled,
        use_container_width=True,
        height=min(620, max(220, len(filtered) * 35 + 45)),
        hide_index=True,
        column_config={
            "Ticker":   st.column_config.TextColumn("Ticker", width="small"),
            "Used In":  st.column_config.TextColumn("Universe Lists", width="large"),
            "# Lists":  st.column_config.NumberColumn("# Lists", width="small", format="%d"),
        },
    )

    # Legend
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11px;margin-top:8px">'
        f'<span style="color:{GOLD};font-weight:600">■</span> Gold row = appears in 3+ lists &nbsp;·&nbsp; '
        f'<span style="color:{ACCENT_GREEN};font-weight:600">■</span> Green = 2 lists &nbsp;·&nbsp; '
        f'Plain = single list only</div>',
        unsafe_allow_html=True,
    )


# ── Main render ────────────────────────────────────────────────

def render():
    section_header("⚙️", "Admin Panel", "Scanner reference · Stock universe browser · System info")

    tab1, tab2 = st.tabs(["📖 Scanner Guide", "🗃️ Stock Universe"])

    with tab1:
        _render_guide()

    with tab2:
        _render_universe()
