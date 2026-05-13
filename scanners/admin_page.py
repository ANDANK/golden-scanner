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
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:12px;margin-bottom:16px">'
        f'Default parameters for each scanner. Filters are adjustable via the sidebar when running a scan.</div>',
        unsafe_allow_html=True,
    )

    for sc in SCANNERS:
        color = sc["color"]
        with st.expander(f"{sc['emoji']}  {sc['key']}", expanded=False):
            # Description strip
            st.markdown(
                f'<div style="border-left:3px solid {color};padding:8px 14px;'
                f'background:{BG_PANEL};border-radius:0 6px 6px 0;margin-bottom:12px;'
                f'color:{TEXT_PRIMARY};font-size:13px">{sc["desc"]}</div>',
                unsafe_allow_html=True,
            )

            # Default param metrics
            if sc["params"]:
                cols = st.columns(len(sc["params"]))
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

    c1, c2 = st.columns([3, 1])
    with c1:
        search = st.text_input("🔍 Search ticker or universe name…", placeholder="SPY, 3× ETF, Options ETF…",
                               label_visibility="collapsed")
    with c2:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:12px;padding:8px 0">'
            f'<b style="color:{GOLD}">{len(df)}</b> unique tickers across <b style="color:{GOLD}">'
            f'{len(SP500_SAMPLE) + len(ETF_3X_UNIVERSE) + len(ETF_UNIVERSE) + len(OPTIONS_ETF_UNIVERSE)}'
            f'</b> total entries</div>',
            unsafe_allow_html=True,
        )

    if search:
        mask = (df["Ticker"].str.contains(search.upper(), na=False) |
                df["Used In"].str.contains(search, case=False, na=False))
        df = df[mask]

    # Colour-code rows by # of lists
    def _row_style(row):
        if row["# Lists"] >= 3:
            return [f"color:{GOLD}"] * len(row)
        elif row["# Lists"] == 2:
            return [f"color:{ACCENT_GREEN}"] * len(row)
        return [""] * len(row)

    st.dataframe(
        df.style.apply(_row_style, axis=1),
        use_container_width=True,
        height=min(600, max(200, len(df) * 35 + 40)),
        hide_index=True,
    )

    # Legend
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11px;margin-top:6px">'
        f'<span style="color:{GOLD}">Gold</span> = in 3+ lists &nbsp;·&nbsp; '
        f'<span style="color:{ACCENT_GREEN}">Green</span> = in 2 lists &nbsp;·&nbsp; '
        f'White = single list</div>',
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
