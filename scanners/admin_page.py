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


# ── Scanner Tech & Rankings data ──────────────────────────────

_RANKINGS = [
    {
        "scanner":    "Trend Continuation",
        "tier":       "Tier 1",
        "rating":     9.8,
        "hold":       "2–6 months",
        "confidence": "Extremely High",
        "count":      "Low",
        "noise":      "Very Low",
        "rec":        "Must Keep",
        "icon":       "📈",
    },
    {
        "scanner":    "Trend Stack",
        "tier":       "Tier 1",
        "rating":     9.5,
        "hold":       "1–4 months",
        "confidence": "Extremely High",
        "count":      "Low",
        "noise":      "Very Low",
        "rec":        "Must Keep",
        "icon":       "🏛",
    },
    {
        "scanner":    "Trend Alignment",
        "tier":       "Tier 1",
        "rating":     9.4,
        "hold":       "1–4 months",
        "confidence": "Very High",
        "count":      "Medium",
        "noise":      "Low",
        "rec":        "Must Keep",
        "icon":       "🎯",
    },
    {
        "scanner":    "Multi-Factor",
        "tier":       "Tier 1",
        "rating":     9.2,
        "hold":       "1–3 months",
        "confidence": "Very High",
        "count":      "Medium",
        "noise":      "Low",
        "rec":        "Must Keep",
        "icon":       "🎯",
    },
    {
        "scanner":    "Momentum Reset Bounce",
        "tier":       "Tier 1",
        "rating":     9.2,
        "hold":       "1–3 months",
        "confidence": "Very High",
        "count":      "Low–Medium",
        "noise":      "Low",
        "rec":        "Must Keep",
        "icon":       "🔄",
    },
    {
        "scanner":    "Momentum",
        "tier":       "Tier 2",
        "rating":     8.7,
        "hold":       "2–8 weeks",
        "confidence": "High",
        "count":      "Medium–High",
        "noise":      "Moderate",
        "rec":        "Keep",
        "icon":       "⚡",
    },
]

_CONF_COLOR = {
    "Extremely High": ACCENT_GREEN,
    "Very High":      "#60A5FA",
    "High":           GOLD,
    "Moderate":       "#FBBF24",
}
_NOISE_COLOR = {
    "Very Low": ACCENT_GREEN,
    "Low":      "#60A5FA",
    "Moderate": "#FBBF24",
    "High":     ACCENT_RED,
}
_REC_COLOR = {
    "Must Keep": ACCENT_GREEN,
    "Keep":      GOLD,
    "Review":    "#FBBF24",
}


def _render_scanner_tech():
    """Tab: Scanner Tech & Rankings"""

    # ── 1. Ratings table ─────────────────────────────────────────
    st.markdown(
        f'<div style="color:{GOLD};font-size:13px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:1.2px;margin-bottom:12px">&#127942; Scanner Rankings</div>',
        unsafe_allow_html=True,
    )

    th = (f'color:{TEXT_MUTED};font-size:10px;font-weight:700;letter-spacing:.8px;'
          f'text-transform:uppercase;padding:9px 14px;border-bottom:2px solid {GOLD}55;'
          f'background:{BG_PANEL};white-space:nowrap')
    headers = ["Scanner", "Tier", "Rating", "Best Hold", "Confidence\nWks→Months",
               "Stock Count", "Noise", "Recommendation"]
    hdr_html = "".join(f'<th style="{th}">{h}</th>' for h in headers)

    rows_html = []
    for i, r in enumerate(_RANKINGS):
        bg      = BG_CARD if i % 2 == 0 else BG_PANEL
        rating  = r["rating"]
        bar_w   = int(rating / 10 * 100)
        bar_c   = ACCENT_GREEN if rating >= 9.3 else (GOLD if rating >= 8.5 else "#FBBF24")
        tier_c  = GOLD if r["tier"] == "Tier 1" else TEXT_MUTED
        conf_c  = _CONF_COLOR.get(r["confidence"], TEXT_MUTED)
        noise_c = _NOISE_COLOR.get(r["noise"], TEXT_MUTED)
        rec_c   = _REC_COLOR.get(r["rec"], TEXT_MUTED)
        td      = f'padding:9px 14px;border-bottom:1px solid {BORDER_COLOR}22;background:{bg}'

        rows_html.append(f"""
        <tr>
          <td style="{td};color:{GOLD};font-weight:700;font-size:13px">
            {r['icon']} {r['scanner']}</td>
          <td style="{td};color:{tier_c};font-size:11px;font-weight:600">{r['tier']}</td>
          <td style="{td}">
            <div style="display:flex;align-items:center;gap:8px">
              <div style="flex:1;background:#1a1a2a;border-radius:3px;height:5px;min-width:60px">
                <div style="background:{bar_c};height:5px;border-radius:3px;width:{bar_w}%"></div>
              </div>
              <span style="color:{bar_c};font-weight:800;font-family:'DM Mono',monospace;
                           font-size:13px;white-space:nowrap">{rating}/10</span>
            </div>
          </td>
          <td style="{td};color:{TEXT_PRIMARY};font-size:12px">{r['hold']}</td>
          <td style="{td};color:{conf_c};font-weight:600;font-size:12px">{r['confidence']}</td>
          <td style="{td};color:{TEXT_MUTED};font-size:12px">{r['count']}</td>
          <td style="{td};color:{noise_c};font-size:12px">{r['noise']}</td>
          <td style="{td}">
            <span style="background:{rec_c}22;color:{rec_c};border:1px solid {rec_c}44;
                         padding:2px 9px;border-radius:4px;font-size:11px;font-weight:700">
              {r['rec']}</span>
          </td>
        </tr>""")

    st.markdown(
        f'<div style="overflow-x:auto;border-radius:8px;border:1px solid {BORDER_COLOR}44;margin-bottom:28px">'
        f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
        f'<thead><tr>{hdr_html}</tr></thead>'
        f'<tbody>{"".join(rows_html)}</tbody>'
        f'</table></div>',
        unsafe_allow_html=True,
    )

    # ── 2. Technical documentation ────────────────────────────────
    st.markdown(
        f'<div style="height:1px;background:linear-gradient(90deg,transparent,{GOLD}44,transparent);'
        f'margin:4px 0 24px"></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="color:{GOLD};font-size:13px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:1.2px;margin-bottom:16px">&#128203; Technical Documentation</div>',
        unsafe_allow_html=True,
    )

    _DOC_SECTIONS = [
        # ── Weekly setups ──────────────────────────────────────────
        {
            "key":   "Trend Alignment",
            "icon":  "🎯",
            "badge": "WEEKLY + DAILY",
            "badge_c": ACCENT_BLUE,
            "style": "Breakout Entry · 15–45 day hold",
            "color": GOLD,
            "intro": (
                "Catches the early stage of a breakout using <b>both daily and weekly signals</b>. "
                "The daily MACD cross provides timing; the weekly chart provides trend context and "
                "a genuine resistance break. ADX filters out directionless, choppy markets."
            ),
            "conditions": [
                ("Daily MACD fresh cross", "MACD histogram ≤ 0 the prior bar, > 0 today — confirms momentum ignition. Old crosses (histogram already positive) are ignored."),
                ("Daily RSI 55–70", "Momentum is building but not extended. Hard blocks: RSI > 78 (overbought), RSI < 55 (not yet trending)."),
                ("ADX > 20 (daily)", "Average Directional Index confirms a trend is present — not a sideways, choppy market. ADX > 30 earns bonus score."),
                ("Price > rising 30-week SMA", "Macro trend filter. Ticker must trade above its 30-week moving average AND that MA must be sloping upward. Declining 30W MA = hard skip — never fight a downtrend."),
                ("Breaks 8-week weekly resistance", "Current weekly close exceeds the highest close of the prior 8 weekly bars. Confirms price is pushing through supply."),
                ("Weekly volume ≥ 1.2× avg", "Volume expansion on the breakout week signals institutional participation. 1.5× earns additional score."),
                ("Daily avg volume > 200k", "Minimum liquidity gate — excludes thinly traded stocks where fills are difficult."),
                ("No earnings within 14 days", "Optional safety filter — avoids binary event risk around earnings announcements."),
            ],
            "avoid": [
                "RSI already above 78–80 (extended, likely to pull back)",
                "30-week SMA declining (fighting a downtrend)",
                "Avg daily volume < 200k (thin liquidity, wide spreads)",
                "Earnings within 1–2 weeks (binary risk)",
                "ADX < 20 (no confirmed trend — sideways chop)",
            ],
            "scoring": [
                ("Fresh MACD cross", "25 pts", "Required gate — no cross, no entry"),
                ("RSI 55–65", "15 pts", "8 pts if RSI 65–70 (slightly extended)"),
                ("ADX ≥ 30", "15 pts", "10 pts if 25–30, 5 pts if 20–25"),
                ("Above rising 30W SMA", "15 pts", "Required gate"),
                ("Weekly volume ≥ 1.5×", "10 pts", "6 pts if 1.2–1.5×"),
                ("RS vs SPY ≥ 1.10", "10 pts", "6 pts if RS ≥ 1.0"),
                ("Weekly resistance break", "10 pts", "Required gate — always true here"),
            ],
        },
        {
            "key":   "Trend Continuation",
            "icon":  "📈",
            "badge": "WEEKLY",
            "badge_c": ACCENT_GREEN,
            "style": "Institutional Momentum · 20–60 day hold",
            "color": ACCENT_GREEN,
            "intro": (
                "Highest-conviction weekly setup. Designed to catch tickers <b>in early-to-mid stage 2</b> "
                "of a longer uptrend, ideally just breaking out of a multi-week base. All logic runs "
                "on weekly bars — cuts through daily noise entirely."
            ),
            "conditions": [
                ("Price above rising 30-week SMA", "Macro trend confirmed. MA must be sloping upward (higher than 4 weeks ago)."),
                ("10-week SMA > 30-week SMA", "The shorter MA is above the longer MA — the trend has enough momentum to pull the fast average above the slow one. Both must be rising."),
                ("Weekly RSI 60–75", "Strong but not overextended momentum on the weekly timeframe. RSI < 60 means not yet in breakout mode; RSI > 75 means likely extended."),
                ("Weekly close near candle high (≥ 96%)", "A weekly close in the upper 4% of the week's range shows consistent buying into Friday's close — a mark of institutional accumulation."),
                ("8–20 week consolidation breakout", "Price was in a tight range (≤ 15% width) for 8–20 weeks, then closed above the high of that range. Classic Stage 2 base breakout pattern."),
                ("Weekly volume ≥ 1.5× 20-week avg", "Volume confirms the breakout. Below-average volume breakouts are frequently false."),
                ("RS vs SPY at new 26-week high", "Relative strength line is making new highs simultaneously with price — the strongest confirmation of leadership."),
            ],
            "avoid": [
                "10W SMA below 30W SMA (MAs not yet aligned)",
                "Weekly RSI < 60 (not yet in breakout momentum mode)",
                "Weekly RSI > 75 (extended — better to wait for a reset)",
                "Below-average volume on the breakout week",
                "RS line declining relative to SPY",
            ],
            "scoring": [
                ("Above rising 30W SMA + 10W > 30W", "20 pts", "Required dual MA alignment"),
                ("Weekly RSI 62–72", "15 pts", "8 pts if 60–62 or 72–75"),
                ("Consolidation breakout", "20 pts", "Highest-weight signal — base breakouts have best risk/reward"),
                ("Weekly close near high", "10 pts", "Strong close = institutional demand"),
                ("Volume spike ≥ 1.5×", "15 pts", "8 pts if 1.2–1.5×"),
                ("RS at new highs", "15 pts", "8 pts if RS ≥ 1.05, 5 pts if RS ≥ 1.0"),
                ("RS ≥ 1.10 bonus", "5 pts", "Extra for strong outperformers"),
            ],
        },
        {
            "key":   "Momentum Reset Bounce",
            "icon":  "🔄",
            "badge": "WEEKLY",
            "badge_c": ACCENT_BLUE,
            "style": "Pullback Re-entry · 10–30 day hold",
            "color": "#60A5FA",
            "intro": (
                "Catches re-entries after a <b>healthy pullback in an established uptrend</b>. "
                "Rather than chasing highs, this setup waits for the stock to cool, touch a key "
                "weekly EMA, and then show fresh buying interest — MACD histogram turning positive "
                "and a bullish reversal candle. All signals evaluated on weekly bars."
            ),
            "conditions": [
                ("Price above rising 30-week SMA", "Long-term uptrend must still be intact — the pullback is a correction within an uptrend, not a trend reversal."),
                ("Pullback to 10-week or 21-week EMA", "The weekly low touched within 4% of either the 10W EMA (tighter, faster) or 21W EMA (standard Weinstein/IBD level). Price must still close at or above the EMA — not fallen through."),
                ("Weekly RSI cooled to 48–62", "RSI has reset from a higher reading — the stock has worked off overbought conditions. Combined with upward turn requirement."),
                ("RSI turning upward vs 3 weeks ago", "Current weekly RSI > RSI 3 weeks ago — momentum is inflecting from the low. Avoids catching a falling knife."),
                ("Weekly MACD histogram turns positive", "Histogram crosses from negative to zero or positive on the weekly chart — the most powerful single signal for a reset bounce. Already positive also scores."),
                ("Bullish reversal candle (weekly)", "Weekly close > weekly open AND weekly close in upper 60% of the week's range. Shows buyers took control by Friday's close."),
                ("Volume higher than prior week", "The rebound week has more volume than the prior week — buyers are stepping up, not just a low-volume drift."),
                ("Market bullish context (SPY > 30W SMA)", "SPY must itself be above its own 30-week SMA — avoids buying pullbacks in a bear market."),
            ],
            "avoid": [
                "Price fallen below 30-week SMA (trend broken — not a pullback, it's a breakdown)",
                "RSI below 48 and still falling (not yet inflecting)",
                "Weekly MACD histogram still deeply negative (no sign of reversal)",
                "Price closed below the EMA it 'touched' (failed retest)",
                "SPY itself below its 30-week SMA (bear market context)",
                "Bearish reversal candle (close in lower half of week's range)",
            ],
            "scoring": [
                ("Above rising 30W SMA", "20 pts", "Required — ensures it's a pullback not a breakdown"),
                ("Touch 10W EMA", "15 pts", "10 pts for 21W touch only (tighter EMA = stronger signal)"),
                ("RSI turning upward", "15 pts", "5 pts if RSI is in range but flat"),
                ("MACD histogram turns + (fresh cross)", "15 pts", "8 pts if already positive but not fresh cross"),
                ("Bullish reversal candle", "10 pts", ""),
                ("Volume increasing on rebound", "10 pts", ""),
                ("Market bullish (SPY > 30W SMA)", "8 pts", ""),
                ("RS vs SPY ≥ 1.0", "7 pts", ""),
            ],
        },
        # ── Daily setups ───────────────────────────────────────────
        {
            "key":   "Trend Stack",
            "icon":  "🏛",
            "badge": "DAILY",
            "badge_c": "#A78BFA",
            "style": "Trend Following · 20–60 day hold",
            "color": "#A78BFA",
            "intro": (
                "The strictest daily MA alignment scanner. All four moving averages must stack in "
                "perfect bullish order AND the 200 SMA must be sloping upward — confirming the "
                "macro trend is healthy. Produces the fewest signals with the highest continuation probability."
            ),
            "conditions": [
                ("Price > EMA20 > SMA50 > SMA200", "Full institutional stack — all four levels of smart money aligned bullishly. No partial alignment accepted."),
                ("200 SMA sloping upward", "The 200-day SMA value must be higher than it was 10 days ago. A flat or declining 200 SMA indicates a macro trend that hasn't yet recovered."),
                ("RSI 50–72", "Momentum present but not extended. Range is slightly wider than other scanners to accommodate the stricter MA filter."),
                ("Price within 3% of 20-day high", "The stock is near the top of its recent range — not extended from resistance, near breakout levels."),
                ("Volume ≥ 1.1× 20-day average", "At minimum slightly elevated — confirms participation."),
                ("RS vs SPY > 1.0", "Must be outperforming the market. Trend-stacked stocks lagging SPY are lower-probability."),
                ("ATR expanding", "Volatility is increasing into the move — confirms the trend has energy behind it."),
            ],
            "avoid": [],
            "scoring": [
                ("Full MA stack (Price>EMA20>SMA50>SMA200)", "30 pts", "All 4 levels aligned"),
                ("RSI 50–72", "20 pts", ""),
                ("Volume ≥ 2×", "15 pts", "10 pts if ≥ 1.1×"),
                ("At 20-day high", "15 pts", ""),
                ("RS vs SPY ≥ 1.10", "10 pts", "6 pts if RS ≥ 1.0"),
                ("ATR expanding", "10 pts", ""),
            ],
        },
        {
            "key":   "Multi-Factor",
            "icon":  "🎯",
            "badge": "DAILY",
            "badge_c": "#A78BFA",
            "style": "Confirmed Setup · 10–30 day hold · 7 conditions scored",
            "color": GOLD,
            "intro": (
                "The highest-conviction daily scanner. Requires <b>7 independent conditions</b> to all be "
                "true simultaneously, then scores each for a composite signal. A 7/7 ticker means every "
                "technical dimension agrees — the rarest and highest-probability setup."
            ),
            "conditions": [
                ("Price > SMA50 > SMA200 (condition 1/7)", "Trend foundation — the two major institutional MAs are stacked."),
                ("RSI 50–72 (condition 2/7)", "Momentum in the sweet spot — trending without being extended."),
                ("MACD histogram > 0 (condition 3/7)", "Short-term momentum is bullish — MACD line above signal line."),
                ("Volume ≥ 1.1× 20-day avg (condition 4/7)", "Institutional participation confirmed."),
                ("ATR expanding (condition 5/7)", "Volatility is increasing — trend has energy."),
                ("Price within 5% of 20-day high OR breaks 20D high (condition 6/7)", "At or near resistance — breakout zone."),
                ("RS vs SPY ≥ 1.0 (condition 7/7)", "Outperforming the market on a relative basis."),
            ],
            "avoid": [],
            "scoring": [
                ("Price > SMA50 > SMA200", "20 pts", ""),
                ("RSI 50–72", "15 pts", ""),
                ("MACD histogram > 0", "15 pts", ""),
                ("Volume ≥ 2×", "15 pts", "10 pts if ≥ 1.1×"),
                ("ATR expanding", "10 pts", ""),
                ("Near/above 20D high", "10 pts", ""),
                ("RS vs SPY ≥ 1.10", "10 pts", "6 pts if RS ≥ 1.0"),
                ("Gap up > 0.5%", "5 pts", "Bonus signal"),
            ],
        },
        {
            "key":   "Momentum",
            "icon":  "⚡",
            "badge": "DAILY",
            "badge_c": "#A78BFA",
            "style": "Medium Swing · 2–8 week hold",
            "color": "#34D399",
            "intro": (
                "Finds stocks trending with institutional momentum on the daily chart. "
                "Broadest of the daily scanners — produces the most signals with moderate noise. "
                "Best used to surface candidates, with weekly scanners confirming the strongest setups."
            ),
            "conditions": [
                ("Price > SMA50", "Primary trend filter. Does not require the full 3-MA stack."),
                ("RSI 50–72", "Momentum present — same range as Multi-Factor."),
                ("MACD histogram > 0", "Bullish momentum confirmed."),
                ("Volume ≥ 1.1× 20-day avg", "Participation check."),
                ("Market cap ≥ $1B", "Large-cap filter for stocks — ETFs skip this check."),
                ("No earnings within 7 days", "Optional binary event avoidance."),
            ],
            "avoid": [
                "Price below SMA50",
                "MACD histogram ≤ 0 (momentum not yet bullish)",
                "Earnings within 7 days if filter enabled",
                "Market cap < $1B (micro-cap risk)",
            ],
            "scoring": [
                ("Price > SMA50 > SMA200", "Higher bonus if full stack", "Partial stack still passes"),
                ("RSI 55–68", "Best zone", ""),
                ("Volume ≥ 2×", "Higher score", "Minimum 1.1×"),
                ("At 20D high", "Bonus", ""),
                ("RS vs SPY", "Proportional", ""),
            ],
        },
        {
            "key":   "Growth (optional)",
            "icon":  "🚀",
            "badge": "FUNDAMENTALS",
            "badge_c": "#818CF8",
            "style": "Growth Play · 30–180 day hold · Off by default (slower)",
            "color": "#818CF8",
            "intro": (
                "Identifies companies with <b>accelerating revenue and EPS growth</b> trading above their "
                "50-day MA. Uses yfinance fundamentals data — significantly slower than technical scanners. "
                "ETFs generally don't have meaningful Rev/EPS data and are skipped by this scanner. "
                "Enable from the Golden Scan sidebar when you want fundamental confirmation."
            ),
            "conditions": [
                ("Revenue growth YoY > 15%", "Top-line expansion — company is growing its business."),
                ("EPS growth YoY > 12%", "Earnings are accelerating — profitability is increasing."),
                ("RS vs SPY > 0.95", "Minimum market relative strength — not a laggard."),
                ("Price > SMA50", "Trend filter — growth stocks below their 50-day are typically in correction."),
                ("MACD histogram > 0", "Bonus: technical momentum aligns with fundamental momentum."),
                ("Volume ≥ 1.5×", "Bonus: elevated participation."),
            ],
            "avoid": [],
            "scoring": [
                ("Rev growth ≥ 30%", "25 pts", "18 pts if 20–30%, 10 pts if 15–20%"),
                ("EPS growth ≥ 25%", "25 pts", "15 pts if 15–25%"),
                ("RS ≥ 1.15", "20 pts", "12 pts if 1.05–1.15"),
                ("Price > SMA50", "15 pts", ""),
                ("MACD histogram > 0", "10 pts", ""),
                ("Volume ≥ 1.5×", "5 pts", ""),
            ],
        },
    ]

    for doc in _DOC_SECTIONS:
        color  = doc["color"]
        badge_c = doc["badge_c"]
        with st.expander(
            f"{doc['icon']}  **{doc['key']}** — {doc['style']}",
            expanded=False,
        ):
            # Header bar
            st.markdown(
                f'<div style="border-left:4px solid {color};padding:12px 16px;'
                f'background:linear-gradient(90deg,{color}18,{BG_PANEL});'
                f'border-radius:0 8px 8px 0;margin-bottom:16px">'
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">'
                f'<span style="background:{badge_c}22;color:{badge_c};border:1px solid {badge_c}44;'
                f'font-size:9px;font-weight:800;padding:2px 7px;border-radius:3px;letter-spacing:1px">'
                f'{doc["badge"]}</span>'
                f'<span style="color:{color};font-size:11px;font-weight:600">{doc["style"]}</span>'
                f'</div>'
                f'<span style="color:{TEXT_PRIMARY};font-size:13px;line-height:1.6">{doc["intro"]}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

            c_left, c_right = st.columns([3, 2])

            with c_left:
                # Core conditions
                st.markdown(
                    f'<div style="color:{color};font-size:10px;font-weight:700;'
                    f'text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">'
                    f'&#9989; Core Conditions</div>',
                    unsafe_allow_html=True,
                )
                cond_items = "".join(
                    f'<div style="padding:7px 0;border-bottom:1px solid {BORDER_COLOR}22">'
                    f'<div style="color:{TEXT_PRIMARY};font-size:12px;font-weight:600;margin-bottom:2px">{name}</div>'
                    f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.5">{detail}</div>'
                    f'</div>'
                    for name, detail in doc["conditions"]
                )
                st.markdown(
                    f'<div style="background:{BG_PANEL};border-radius:6px;padding:4px 12px 2px">'
                    f'{cond_items}</div>',
                    unsafe_allow_html=True,
                )

                # Avoid list (if any)
                if doc.get("avoid"):
                    st.markdown(
                        f'<div style="color:{ACCENT_RED};font-size:10px;font-weight:700;'
                        f'text-transform:uppercase;letter-spacing:1px;margin:12px 0 6px">'
                        f'&#128683; Avoid These Conditions</div>',
                        unsafe_allow_html=True,
                    )
                    avoid_items = "".join(
                        f'<li style="color:{TEXT_MUTED};font-size:12px;margin-bottom:4px;line-height:1.4">{a}</li>'
                        for a in doc["avoid"]
                    )
                    st.markdown(
                        f'<ul style="margin:0;padding-left:18px;'
                        f'background:{BG_PANEL};border-radius:6px;padding:8px 8px 8px 28px">'
                        f'{avoid_items}</ul>',
                        unsafe_allow_html=True,
                    )

            with c_right:
                # Scoring breakdown
                st.markdown(
                    f'<div style="color:{GOLD};font-size:10px;font-weight:700;'
                    f'text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">'
                    f'&#127919; Score Breakdown (0–100)</div>',
                    unsafe_allow_html=True,
                )
                score_rows = "".join(
                    f'<tr>'
                    f'<td style="padding:5px 10px;color:{TEXT_PRIMARY};font-size:11px;'
                    f'border-bottom:1px solid {BORDER_COLOR}22">{cond}</td>'
                    f'<td style="padding:5px 10px;color:{GOLD};font-weight:700;font-size:11px;'
                    f'font-family:\'DM Mono\',monospace;border-bottom:1px solid {BORDER_COLOR}22;'
                    f'white-space:nowrap">{pts}</td>'
                    f'<td style="padding:5px 10px;color:{TEXT_MUTED};font-size:10px;'
                    f'border-bottom:1px solid {BORDER_COLOR}22">{note}</td>'
                    f'</tr>'
                    for cond, pts, note in doc["scoring"]
                )
                st.markdown(
                    f'<div style="background:{BG_PANEL};border-radius:6px;overflow:hidden">'
                    f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
                    f'<thead><tr>'
                    f'<th style="padding:6px 10px;color:{TEXT_MUTED};font-size:9px;font-weight:700;'
                    f'text-transform:uppercase;letter-spacing:.7px;background:{BG_CARD};'
                    f'border-bottom:1px solid {BORDER_COLOR}44">Condition</th>'
                    f'<th style="padding:6px 10px;color:{TEXT_MUTED};font-size:9px;font-weight:700;'
                    f'text-transform:uppercase;letter-spacing:.7px;background:{BG_CARD};'
                    f'border-bottom:1px solid {BORDER_COLOR}44">Pts</th>'
                    f'<th style="padding:6px 10px;color:{TEXT_MUTED};font-size:9px;font-weight:700;'
                    f'text-transform:uppercase;letter-spacing:.7px;background:{BG_CARD};'
                    f'border-bottom:1px solid {BORDER_COLOR}44">Notes</th>'
                    f'</tr></thead>'
                    f'<tbody>{score_rows}</tbody>'
                    f'</table></div>',
                    unsafe_allow_html=True,
                )

    # ── Footer note ───────────────────────────────────────────────
    st.markdown(
        f'<div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-left:3px solid {GOLD};'
        f'border-radius:0 6px 6px 0;padding:12px 16px;margin-top:20px;'
        f'color:{TEXT_MUTED};font-size:12px;line-height:1.7">'
        f'<b style="color:{GOLD}">&#128161; Multi-Signal Ranking:</b> '
        f'Golden Scan merges all scanner results. A ticker appearing in 2+ scanners is ranked above '
        f'single-signal tickers regardless of score — <b style="color:{TEXT_PRIMARY}">convergence across '
        f'independent methods = highest conviction</b>. Weekly scanners and daily scanners use completely '
        f'different data frequencies, so a match in both (e.g. Trend Continuation + Trend Stack) '
        f'represents a particularly strong setup.</div>',
        unsafe_allow_html=True,
    )


# ── Stock Analysis Methodology ─────────────────────────────────

def _render_stock_analysis_methodology():
    """Tab: How the Stock Analysis page computes its scores and signals."""

    ACCENT_BLUE_LOCAL = "#3B82F6"
    PURPLE = "#A78BFA"
    YELLOW = "#FBBF24"   # not exported from config — define locally

    # ── Intro blurb ───────────────────────────────────────────────
    st.markdown(
        f'<div style="background:{BG_PANEL};border:1px solid {GOLD}33;border-left:4px solid {GOLD};'
        f'border-radius:0 8px 8px 0;padding:14px 18px;margin-bottom:24px;'
        f'color:{TEXT_MUTED};font-size:13px;line-height:1.7">'
        f'The <b style="color:{GOLD}">Stock Analysis page</b> runs 9 independent indicator modules on '
        f'<b style="color:{TEXT_PRIMARY}">Daily + Weekly</b> price data and combines them into three '
        f'composite scores (Momentum, Trend Strength, Buy Pressure) plus an overall '
        f'<b style="color:{TEXT_PRIMARY}">Confidence %</b> signal. '
        f'All scores are 0–100. A ticker appearing in the green zones across most indicators = '
        f'highest-conviction trade setup.</div>',
        unsafe_allow_html=True,
    )

    # ══ Section 1: Composite score formulas ══════════════════════
    st.markdown(
        f'<div style="color:{GOLD};font-size:13px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:1.2px;margin:4px 0 14px">&#127919; Composite Score Formulas</div>',
        unsafe_allow_html=True,
    )

    _SCORES = [
        {
            "name":  "🔥 Momentum Score",
            "color": ACCENT_GREEN,
            "desc":  "Measures short-to-medium-term price acceleration. Weighted toward MACD + RSI because they are the earliest leading indicators of a momentum shift.",
            "rows": [
                ("MACD Histogram > 0 (Daily)",    "20 pts", "MACD line above signal — primary momentum trigger"),
                ("MACD Line > Signal (Daily)",     "15 pts", "Confirmed bullish cross on daily chart"),
                ("MACD Histogram > 0 (Weekly)",    "10 pts", "Weekly momentum aligns with daily — higher conviction"),
                ("MACD Line > Signal (Weekly)",    " 8 pts", "Weekly cross bonus — rare, very bullish"),
                ("RSI 55–68 (Daily)",              "25 pts", "Momentum sweet spot — trending without overbought risk"),
                ("RSI 50–55 or 68–72 (Daily)",    "12 pts", "Partial credit for adjacent zones"),
                ("Volume Spike ≥ 1.5× avg",        "12 pts", "High-volume moves show institutional participation"),
                ("OBV Rising (5-bar slope > 0)",   "10 pts", "On-Balance Volume confirms accumulation"),
            ],
            "note": "Max: 100 pts (capped). Formula: sum of all applicable points.",
        },
        {
            "name":  "📈 Trend Strength Score",
            "color": ACCENT_BLUE_LOCAL,
            "desc":  "Measures how well the moving-average structure is aligned for a sustained uptrend. Requires the full institutional stack to score highest.",
            "rows": [
                ("Price > EMA 20",          "14 pts", "Short-term momentum — price above fast MA"),
                ("EMA 20 > SMA 50",         "14 pts", "Fast MA above medium MA — uptrend building"),
                ("Price > SMA 50",          "14 pts", "Medium-term trend confirmed"),
                ("Price > SMA 200",         "20 pts", "Long-term bull market structure intact"),
                ("SMA 50 > SMA 200 (Golden Cross)", "14 pts", "Classic Golden Cross — highest weight long-term signal"),
                ("SMA 200 Slope > 0 (10-bar)", "12 pts", "200-day MA is actively rising — macro trend healthy"),
                ("SMA 50 Slope > 0 (10-bar)",  "12 pts", "50-day MA is rising — medium-term trend intact"),
            ],
            "note": "Max: 100 pts (capped). A full-stack score (all 7 conditions) = 100.",
        },
        {
            "name":  "🌊 Buy Pressure Score",
            "color": PURPLE,
            "desc":  "Measures whether smart money is actually entering the stock right now — combines volume, OBV, money flow, breakout proximity, and relative strength.",
            "rows": [
                ("Volume Spike ≥ 1.5× avg",    "20 pts", "High volume = institutional conviction"),
                ("OBV Rising (5-bar slope)",    "15 pts", "On-Balance Volume trending up = accumulation phase"),
                ("MFI > 60",                    "15 pts", "Money Flow Index: buying pressure dominant"),
                ("MFI 50–60",                   " 8 pts", "Neutral-to-positive money flow"),
                ("Price at New 20-Day High",    "20 pts", "Breakout highs attract momentum buyers"),
                ("Price Within 2% of 20D High", "10 pts", "Near-breakout zone — partial credit"),
                ("RS vs SPY ≥ 1.05",            "15 pts", "Outperforming the market = money rotating in"),
                ("MACD Histogram > 0 (Daily)",  "15 pts", "Short-term confirmation of buying momentum"),
            ],
            "note": "Max: 100 pts (capped). All 8 conditions can contribute simultaneously.",
        },
        {
            "name":  "💡 Confidence % (Final Signal)",
            "color": GOLD,
            "desc":  "The single combined signal shown in the ticker header. It is NOT a simple average — it is a weighted composite with directional bias adjustments applied last.",
            "rows": [
                ("Momentum Score × 35%",              "35 pts max", "Highest weight — momentum leads price"),
                ("Trend Strength Score × 35%",         "35 pts max", "Equal weight — structural backbone of the trade"),
                ("Buy Pressure Score × 30%",           "30 pts max", "Confirms smart money entry"),
                ("Full MA Stack bonus",                "+8 pts",     "All 4 MAs aligned = regime confirmation"),
                ("Below SMA 50 penalty",               "−10 pts",    "Failing the primary trend filter"),
                ("MACD Cross + Histogram > 0",         "+5 pts",     "Both bullish = momentum accelerating"),
                ("MACD below signal penalty",          "−5 pts",     "Momentum not yet bullish"),
                ("RSI 55–68 bonus",                    "+5 pts",     "Ideal momentum zone"),
                ("RSI > 75 penalty",                   "−8 pts",     "Extended / overbought"),
                ("RSI < 30 penalty",                   "−4 pts",     "Oversold — possible reversal but not buy signal"),
                ("RS vs SPY ≥ 1.05 bonus",             "+4 pts",     "Outperforming = leadership"),
                ("RS vs SPY < 0.92 penalty",           "−4 pts",     "Lagging = avoid"),
            ],
            "note": "Final score: 0–100. ≥ 60 = BUY signal. ≤ 40 = SELL signal. 41–59 = NEUTRAL/HOLD.",
        },
    ]

    for sc in _SCORES:
        color = sc["color"]
        with st.expander(f"{sc['name']}", expanded=False):
            st.markdown(
                f'<div style="border-left:4px solid {color};padding:10px 16px;'
                f'background:linear-gradient(90deg,{color}18,{BG_PANEL});'
                f'border-radius:0 8px 8px 0;margin-bottom:14px;'
                f'color:{TEXT_PRIMARY};font-size:13px;line-height:1.6">{sc["desc"]}</div>',
                unsafe_allow_html=True,
            )
            th = (f"padding:7px 12px;color:{TEXT_MUTED};font-size:10px;font-weight:700;"
                  f"text-transform:uppercase;letter-spacing:.7px;background:{BG_CARD};"
                  f"border-bottom:1px solid {BORDER_COLOR}44")
            score_rows = "".join(
                f'<tr>'
                f'<td style="padding:7px 12px;color:{TEXT_PRIMARY};font-size:12px;'
                f'border-bottom:1px solid {BORDER_COLOR}22">{cond}</td>'
                f'<td style="padding:7px 12px;color:{color};font-weight:800;font-size:12px;'
                f'font-family:\'DM Mono\',monospace;border-bottom:1px solid {BORDER_COLOR}22;white-space:nowrap">{pts}</td>'
                f'<td style="padding:7px 12px;color:{TEXT_MUTED};font-size:11px;'
                f'border-bottom:1px solid {BORDER_COLOR}22">{note}</td>'
                f'</tr>'
                for cond, pts, note in sc["rows"]
            )
            st.markdown(
                f'<div style="overflow-x:auto;border-radius:8px;border:1px solid {BORDER_COLOR}33">'
                f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
                f'<thead><tr>'
                f'<th style="{th}">Condition</th>'
                f'<th style="{th}">Points</th>'
                f'<th style="{th}">Notes</th>'
                f'</tr></thead>'
                f'<tbody>{score_rows}</tbody>'
                f'</table></div>'
                f'<div style="color:{TEXT_MUTED};font-size:11px;margin-top:8px;font-style:italic">&#128203; {sc["note"]}</div>',
                unsafe_allow_html=True,
            )

    # ══ Section 2: Indicator importance ranking ══════════════════
    st.markdown(
        f'<div style="height:1px;background:linear-gradient(90deg,transparent,{GOLD}44,transparent);'
        f'margin:24px 0 20px"></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="color:{GOLD};font-size:13px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:1.2px;margin-bottom:14px">&#127942; Indicator Importance Ranking — Highest to Lowest</div>',
        unsafe_allow_html=True,
    )

    _INDICATORS = [
        # (rank, indicator, timeframe, why, color_tier)
        (1,  "MACD Weekly Cross + Histogram",    "Weekly",       "Best leading signal for swing trades. Weekly confirmation eliminates daily noise. A fresh weekly MACD cross after a pullback = highest-conviction entry.", ACCENT_GREEN),
        (2,  "MA Trend Stack (Full Alignment)",  "Daily",        "Price > EMA20 > SMA50 > SMA200. When all 4 levels of institutional money are aligned, continuation probability is highest. Partial stacks are significant discounts.", ACCENT_GREEN),
        (3,  "RSI Zone (Daily + Weekly)",        "Daily+Weekly", "RSI 55–68 is the momentum sweet spot — trending but not overbought. Weekly RSI in this zone confirms a healthy, sustained move. RSI >75 = fade the move.", ACCENT_GREEN),
        (4,  "MACD Daily Cross + Histogram",     "Daily",        "Confirms short-term momentum direction. Histogram turning positive = momentum starting. Already positive = momentum ongoing. MACD divergence vs price is a major warning sign.", "#60A5FA"),
        (5,  "Volume Spike (≥ 1.5× avg)",        "Daily",        "Volume is conviction. A price move on low volume frequently reverses. High volume + breakout = institutional buying. Never trust a breakout on <1× volume.", "#60A5FA"),
        (6,  "Relative Strength vs SPY",         "Daily (63d)",  "Winners lead the market. RS ≥ 1.05 over 63 days = the stock is genuinely outperforming. This filters out stocks that look good in a rising tide but have no alpha.", "#60A5FA"),
        (7,  "On-Balance Volume (OBV) Slope",    "Daily",        "OBV rising = accumulation (smart money buying). OBV falling while price is flat/up = distribution warning. Divergence between OBV and price often precedes reversals by 1–2 weeks.", GOLD),
        (8,  "Money Flow Index (MFI)",            "Daily",        "Combines price + volume to measure buying/selling pressure. MFI >60 = money flowing in. More meaningful than volume alone because it weights by dollar flow, not just share count.", GOLD),
        (9,  "SMA 200 Slope",                    "Daily",        "The 200-day SMA slope tells you the macro trend's health. A rising 200 SMA = long-term uptrend. Flat 200 = transition. Declining 200 = bear market — only short or sit out.", GOLD),
        (10, "Bollinger Band %B + Squeeze",      "Daily",        "BB Squeeze (bandwidth at 15th percentile) precedes high-volatility directional moves. %B >80% inside a squeeze with volume = high-probability breakout setup.", GOLD),
        (11, "Breakout: New 20/50-Day High",     "Daily",        "New price highs with volume confirmation signal demand exceeding supply at prior resistance. 50-day new high is more significant than 20-day. Always check volume.", "#FBBF24"),
        (12, "ATR % + Expansion",                "Daily",        "ATR expanding = trend has energy. Contracting ATR into a BB squeeze = coiled spring. Use ATR to set stop distances — not a round dollar amount.", "#FBBF24"),
        (13, "SMA 50 Slope",                     "Daily",        "Rising SMA50 = medium-term trend healthy. Useful for confirming the MA stack is improving, not just a one-day pop above the line.", "#FBBF24"),
        (14, "Relative Strength vs Sector ETF",  "Daily (63d)",  "After confirming RS vs SPY, check RS vs the sector ETF. A stock outperforming both the broad market AND its sector = true sector leader. Best setups have both.", TEXT_MUTED),
        (15, "Short Interest % + Days to Cover", "Snapshot",     "High short interest (>15% float) combined with rising price = short squeeze fuel. Use as a bonus, not primary signal — fundamentals must support the price.", TEXT_MUTED),
    ]

    th = (f"padding:8px 12px;color:{TEXT_MUTED};font-size:10px;font-weight:700;"
          f"text-transform:uppercase;letter-spacing:.7px;background:{BG_PANEL};"
          f"border-bottom:2px solid {GOLD}44;white-space:nowrap")
    ind_rows = ""
    for rank, name, tf, why, color in _INDICATORS:
        bar_w  = max(4, int((16 - rank) / 15 * 120))
        bar_c  = color
        td     = f"padding:9px 12px;border-bottom:1px solid {BORDER_COLOR}22;vertical-align:top"
        ind_rows += (
            f'<tr>'
            f'<td style="{td};text-align:center;width:36px">'
            f'<span style="background:{color}22;color:{color};border:1px solid {color}44;'
            f'padding:2px 7px;border-radius:4px;font-weight:800;font-size:12px;font-family:\'DM Mono\',monospace">#{rank}</span>'
            f'</td>'
            f'<td style="{td}">'
            f'<div style="color:{color};font-size:12px;font-weight:700;margin-bottom:3px">{name}</div>'
            f'<div style="background:#1a1a2a;border-radius:2px;height:4px;width:{bar_w}px">'
            f'<div style="background:{bar_c};height:4px;border-radius:2px;width:100%"></div>'
            f'</div>'
            f'</td>'
            f'<td style="{td};white-space:nowrap">'
            f'<span style="background:{BG_CARD};color:{TEXT_MUTED};border:1px solid {BORDER_COLOR}44;'
            f'padding:2px 8px;border-radius:3px;font-size:10px">{tf}</span>'
            f'</td>'
            f'<td style="{td};color:{TEXT_MUTED};font-size:11px;line-height:1.6">{why}</td>'
            f'</tr>'
        )

    st.markdown(
        f'<div style="overflow-x:auto;border-radius:8px;border:1px solid {BORDER_COLOR}44;margin-bottom:20px">'
        f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
        f'<thead><tr>'
        f'<th style="{th}">#</th>'
        f'<th style="{th}">Indicator</th>'
        f'<th style="{th}">Timeframe</th>'
        f'<th style="{th}">Why It Matters (Highest → Lowest)</th>'
        f'</tr></thead>'
        f'<tbody>{ind_rows}</tbody>'
        f'</table></div>',
        unsafe_allow_html=True,
    )

    # ══ Section 3: Signal thresholds ═════════════════════════════
    TEAL = "#2DD4BF"
    st.markdown(
        f'<div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:8px;'
        f'padding:16px 20px;margin-top:4px">'
        f'<div style="color:{GOLD};font-size:12px;font-weight:700;margin-bottom:10px;'
        f'text-transform:uppercase;letter-spacing:1px">&#128397; Signal Thresholds</div>'
        f'<div style="display:flex;gap:16px;flex-wrap:wrap">'
        # BUY
        f'<div style="background:{ACCENT_GREEN}15;border:1px solid {ACCENT_GREEN}44;border-radius:6px;'
        f'padding:10px 20px;text-align:center;min-width:110px">'
        f'<div style="color:{ACCENT_GREEN};font-size:22px;font-weight:800">≥ 60%</div>'
        f'<div style="color:{ACCENT_GREEN};font-size:11px;font-weight:700;margin-top:2px">🟢 BUY</div>'
        f'<div style="color:{TEXT_MUTED};font-size:10px;margin-top:4px;line-height:1.4">'
        f'Composite ≥ 60<br>Most indicators bullish</div>'
        f'</div>'
        # NEUTRAL
        f'<div style="background:{YELLOW}15;border:1px solid {YELLOW}44;border-radius:6px;'
        f'padding:10px 20px;text-align:center;min-width:110px">'
        f'<div style="color:{YELLOW};font-size:22px;font-weight:800">41–59%</div>'
        f'<div style="color:{YELLOW};font-size:11px;font-weight:700;margin-top:2px">🟡 NEUTRAL</div>'
        f'<div style="color:{TEXT_MUTED};font-size:10px;margin-top:4px;line-height:1.4">'
        f'Mixed signals<br>Wait for resolution</div>'
        f'</div>'
        # SETUP
        f'<div style="background:{TEAL}15;border:1px solid {TEAL}44;border-radius:6px;'
        f'padding:10px 20px;text-align:center;min-width:130px">'
        f'<div style="color:{TEAL};font-size:20px;font-weight:800">≤ 40% + 🔄</div>'
        f'<div style="color:{TEAL};font-size:11px;font-weight:700;margin-top:2px">🔵 SETUP / WATCH</div>'
        f'<div style="color:{TEXT_MUTED};font-size:10px;margin-top:4px;line-height:1.4">'
        f'Composite &lt; 40 BUT<br>Weekly MACD turned ✅<br>RSI 28–64 (reset zone)</div>'
        f'</div>'
        # SELL
        f'<div style="background:{ACCENT_RED}15;border:1px solid {ACCENT_RED}44;border-radius:6px;'
        f'padding:10px 20px;text-align:center;min-width:110px">'
        f'<div style="color:{ACCENT_RED};font-size:22px;font-weight:800">≤ 40%</div>'
        f'<div style="color:{ACCENT_RED};font-size:11px;font-weight:700;margin-top:2px">🔴 SELL</div>'
        f'<div style="color:{TEXT_MUTED};font-size:10px;margin-top:4px;line-height:1.4">'
        f'Composite ≤ 40<br>Avoid or short bias</div>'
        f'</div>'
        # Explanation
        f'<div style="flex:1;min-width:200px;color:{TEXT_MUTED};font-size:11px;line-height:1.9;padding:4px 0">'
        f'<b style="color:{TEXT_PRIMARY}">Confidence % is directional</b> — BUY shows the raw composite; '
        f'SELL shows 100 − composite (so a 85% SELL = composite of 15 = heavily bearish).<br>'
        f'<b style="color:{TEAL}">SETUP 🔄</b> is a special tier for stocks where the MA stack is broken '
        f'(bearish composite) but the <b style="color:{TEXT_PRIMARY}">Weekly MACD just turned positive on '
        f'a reset RSI</b> — the classic Momentum Reset Bounce entry signal. Not a buy YET, but watch closely. '
        f'An ⚡ W-MACD conflict badge also appears in the summary table when these signals disagree.'
        f'</div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    # ══ Section 4: SETUP signal — what it means & how to trade ═══
    st.markdown(
        f'<div style="height:1px;background:linear-gradient(90deg,transparent,{GOLD}44,transparent);'
        f'margin:24px 0 20px"></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="color:{GOLD};font-size:13px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:1.2px;margin-bottom:14px">&#x1F535; SETUP &#x1F504; Signal — What It Means &amp; How to Trade It</div>',
        unsafe_allow_html=True,
    )

    # What it is
    st.markdown(
        f'<div style="background:{TEAL}0D;border:1px solid {TEAL}44;border-left:4px solid {TEAL};'
        f'border-radius:0 8px 8px 0;padding:14px 18px;margin-bottom:16px">'
        f'<div style="color:{TEAL};font-size:12px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:1px;margin-bottom:8px">&#128161; What SETUP Means</div>'
        f'<div style="color:{TEXT_PRIMARY};font-size:13px;line-height:1.8">'
        f'<b>SETUP = "The engine is warming up, but the car hasn\'t moved yet."</b><br>'
        f'The stock has been in a correction or downtrend (MA stack broken, composite &lt; 40), '
        f'but the <b style="color:{TEAL}">Weekly MACD just turned positive</b> while RSI is in the '
        f'28–64 reset zone. This is the early signal of the '
        f'<b style="color:{TEXT_PRIMARY}">Momentum Reset Bounce</b> pattern — smart money starting '
        f'to accumulate before the trend officially recovers. You are seeing it <b>before</b> the '
        f'breakout, not after. That\'s the opportunity — and the risk.</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Three conditions
    cond_rows = [
        (f"Weekly MACD cross ✅ (MACD &gt; Signal line)", TEAL,
         "The most important signal. Weekly MACD crossing above its signal line means medium-term momentum is inflecting from bearish to bullish. One weekly candle does not confirm — watch for 2–3 consecutive weeks of positive histogram to build confidence."),
        (f"Weekly MACD histogram &gt; 0", TEAL,
         "The histogram measures the distance between MACD and signal. Growing positive histogram = momentum accelerating. Shrinking or negative histogram after a cross = false start, stay out."),
        (f"Weekly RSI 28–64 (reset zone)", ACCENT_BLUE_LOCAL,
         "RSI has cooled from a prior high (worked off overbought) and is turning up from a low base. This is ideal entry timing — not oversold panic, not yet overbought. RSI below 28 = still falling, wait. RSI above 64 = already moving, chasing risk."),
        (f"MA stack NOT yet rebuilt (that's the point)", YELLOW,
         "The stock is still below SMA50 or the full MA alignment hasn't recovered. This is why the signal is SETUP not BUY. The MA stack rebuilding is the confirmation you wait for — it signals the recovery is real, not just a dead-cat bounce."),
    ]
    for cond, color, detail in cond_rows:
        st.markdown(
            f'<div style="display:flex;gap:12px;padding:9px 0;border-bottom:1px solid {BORDER_COLOR}22">'
            f'<div style="width:4px;background:{color};border-radius:2px;flex-shrink:0"></div>'
            f'<div>'
            f'<div style="color:{color};font-size:12px;font-weight:700;margin-bottom:3px">{cond}</div>'
            f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.6">{detail}</div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    # Action table
    st.markdown(
        f'<div style="color:{GOLD};font-size:11px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:1px;margin-bottom:10px">&#127919; Action Plan — What To Do With a SETUP Signal</div>',
        unsafe_allow_html=True,
    )

    action_rows = [
        ("Watch only", f"background:{BG_CARD}", TEXT_MUTED,
         "SETUP just appeared with no other confirmation",
         "Zero position. Add to watchlist. Check back in 1–2 weeks.",
         "Too early. One weekly MACD cross can reverse. No conviction yet."),
        ("Starter position (25–33%)", f"background:{TEAL}0D", TEAL,
         "Weekly MACD positive 2nd consecutive week AND Daily MACD also turning Bull AND RSI daily crossing 50",
         "Enter 25–33% of intended position size. Set stop below recent swing low.",
         "Early entry with controlled risk. You get in before the crowd at lower price."),
        ("Add to half size (50%)", f"background:{ACCENT_GREEN}0D", ACCENT_GREEN,
         "Price reclaims EMA20 on daily with expanding volume",
         "Add another 25% position. Raise stop to breakeven on first tranche.",
         "Price is now showing buying momentum. First confirmation of recovery."),
        ("Full position (100%)", f"background:{ACCENT_GREEN}18", ACCENT_GREEN,
         "Price reclaims SMA50 with volume + RSI daily in 55–68 zone",
         "Add final tranche. This is now a BUY signal — the SETUP has resolved.",
         "Full MA recovery = high-conviction trend resumption. Institutional buyers confirmed."),
        ("Exit the idea", f"background:{ACCENT_RED}0D", ACCENT_RED,
         "Weekly RSI falls back below 28 OR weekly MACD histogram turns negative again",
         "Cut the position. The setup failed — this is a downtrend continuation, not a bounce.",
         "Failed setups happen ~40% of the time. Small loss early beats large loss later."),
    ]

    th = (f"padding:8px 12px;color:{TEXT_MUTED};font-size:9px;font-weight:700;"
          f"text-transform:uppercase;letter-spacing:.7px;background:{BG_PANEL};"
          f"border-bottom:2px solid {GOLD}44;white-space:nowrap")
    act_html = ""
    for action, row_bg, color, trigger, trade, reason in action_rows:
        act_html += (
            f'<tr style="{row_bg}">'
            f'<td style="padding:9px 12px;font-weight:700;font-size:12px;color:{color};white-space:nowrap">{action}</td>'
            f'<td style="padding:9px 12px;color:{TEXT_PRIMARY};font-size:11px;line-height:1.5">{trigger}</td>'
            f'<td style="padding:9px 12px;color:{TEXT_PRIMARY};font-size:11px;line-height:1.5">{trade}</td>'
            f'<td style="padding:9px 12px;color:{TEXT_MUTED};font-size:11px;line-height:1.5">{reason}</td>'
            f'</tr>'
        )

    st.markdown(
        f'<div style="overflow-x:auto;border-radius:8px;border:1px solid {BORDER_COLOR}33;margin-bottom:20px">'
        f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
        f'<thead><tr>'
        f'<th style="{th}">Action</th>'
        f'<th style="{th}">Trigger / Confirmation</th>'
        f'<th style="{th}">What to Do</th>'
        f'<th style="{th}">Why</th>'
        f'</tr></thead>'
        f'<tbody>{act_html}</tbody>'
        f'</table></div>',
        unsafe_allow_html=True,
    )

    # Key insight box
    st.markdown(
        f'<div style="background:{BG_PANEL};border:1px solid {TEAL}33;border-left:3px solid {TEAL};'
        f'border-radius:0 6px 6px 0;padding:12px 16px;margin-bottom:8px;'
        f'color:{TEXT_MUTED};font-size:12px;line-height:1.8">'
        f'<b style="color:{TEAL}">&#128161; Key insight:</b> '
        f'SETUP stocks fail ~35–40% of the time (the weekly MACD cross reverses). '
        f'The edge comes from <b style="color:{TEXT_PRIMARY}">position sizing</b> — '
        f'starter positions mean a failed setup costs you 1–2%, while a successful setup '
        f'that becomes a BUY can return 15–40% before you add full size. '
        f'The &#9889; W-MACD conflict badge (SELL overall but weekly MACD bullish) is the '
        f'earliest-possible SETUP precursor — watch those especially on high-quality tickers '
        f'(NVDA, MSFT, AAPL, etc.) during market pullbacks.'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ══ Section 5: Standard Watchlist reference ═══════════════════
    st.markdown(
        f'<div style="height:1px;background:linear-gradient(90deg,transparent,{GOLD}44,transparent);'
        f'margin:24px 0 20px"></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="color:{GOLD};font-size:13px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:1.2px;margin-bottom:14px">&#128202; Standard Watchlist — How It Works</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f'<div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:8px;'
        f'padding:16px 20px;margin-bottom:16px">'
        f'<div style="color:{TEXT_PRIMARY};font-size:13px;line-height:1.8;margin-bottom:12px">'
        f'The <b style="color:{GOLD}">📋 Standard Watchlist</b> tab (inside Stock Analysis) runs the full '
        f'9-indicator engine on a fixed list of 117 pre-loaded tickers with a single button press. '
        f'No typing required. Results are cached for 4 hours — pressing the button again within '
        f'4 hours returns the cached table instantly without re-fetching data.'
        f'</div>'
        f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px">'

        f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:6px;padding:12px">'
        f'<div style="color:{GOLD};font-size:11px;font-weight:700;margin-bottom:6px">&#9654; Run Scan</div>'
        f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.6">Runs all 117 tickers. '
        f'If results are &lt; 4h old, shows cached table immediately. Progress bar shown on fresh scan.</div>'
        f'</div>'

        f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:6px;padding:12px">'
        f'<div style="color:{GOLD};font-size:11px;font-weight:700;margin-bottom:6px">&#x1F504; Clear &amp; Rescan</div>'
        f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.6">Forces a full fresh scan '
        f'regardless of cache age. Use when market has moved significantly since last scan.</div>'
        f'</div>'

        f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:6px;padding:12px">'
        f'<div style="color:{GOLD};font-size:11px;font-weight:700;margin-bottom:6px">&#128465; Clear Cache</div>'
        f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.6">Wipes the cached results '
        f'without triggering a new scan. Returns to the landing screen.</div>'
        f'</div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    # Table column guide
    st.markdown(
        f'<div style="color:{GOLD};font-size:11px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:1px;margin-bottom:10px">&#128203; Standard Table Columns Explained</div>',
        unsafe_allow_html=True,
    )

    col_rows = [
        ("🟢/🔵/🟡/🔴", "Signal circle",    "Green=Buy · Blue=Setup · Yellow=Neutral · Red=Sell at a glance"),
        ("Ticker",        "Symbol + price",   "Current price and day change %. Click ticker in Deep Analysis for full report."),
        ("Signal %",      "Confidence badge", "BUY: raw composite (higher=more bullish). SELL: 100−composite (higher=more bearish). SETUP: raw composite shown in teal."),
        ("W-MACD",        "Weekly MACD",      "Bull/Bear cross on weekly chart + raw MACD/Signal values. Weekly confirmation is highest-weight signal. ⚡ conflict badge when weekly bullish but overall SELL."),
        ("D-MACD ★",      "Daily MACD",       "NEW COLUMN. Bull=cross up + histogram positive. Cross~=crossed but histogram still negative (weak signal). Bear=below signal. Shows short-term momentum direction."),
        ("RSI D/W",       "RSI daily/weekly", "D=daily RSI, W=weekly RSI. Green=55–68 momentum zone. Red=overbought >70 or oversold <30. Yellow=neutral."),
        ("Trend",         "MA stack label",   "Full=Price>EMA20>SMA50>SMA200 (strongest). Part=partial alignment. Weak=broken stack. Score bar shows 0–100."),
        ("Mom",           "Momentum score",   "0–100 bar. MACD+RSI+Volume+OBV combined. ≥70 green, 50–69 yellow, <50 red."),
        ("Buy↑",          "Buy Pressure",     "0–100 bar. Volume spike+OBV+MFI+breakout proximity+RS vs SPY combined."),
        ("Vol/RS",        "Volume + RS",       "Volume ratio vs 20-day avg (🔥=spike ≥1.5×). RS=relative strength vs SPY (>1.05=outperforming)."),
        ("Breakout ★",    "Breakout status",  "NEW COLUMN. 🚀 Confirmed=new 20-day high + volume spike. ⚡ Near=within 2% of high. —=no breakout."),
    ]

    th2 = (f"padding:7px 12px;color:{TEXT_MUTED};font-size:9px;font-weight:700;"
           f"text-transform:uppercase;letter-spacing:.7px;background:{BG_PANEL};"
           f"border-bottom:2px solid {GOLD}44")
    col_html = ""
    for i, (col, label, desc) in enumerate(col_rows):
        bg = BG_CARD if i % 2 == 0 else BG_PANEL
        new_tag = f'<span style="background:{TEAL}22;color:{TEAL};border:1px solid {TEAL}44;font-size:8px;font-weight:700;padding:1px 5px;border-radius:3px;margin-left:4px">NEW</span>' if "★" in col else ""
        col_clean = col.replace(" ★", "")
        col_html += (
            f'<tr style="background:{bg}">'
            f'<td style="padding:8px 12px;color:{GOLD};font-weight:700;font-size:12px;white-space:nowrap;font-family:\'DM Mono\',monospace">{col_clean}{new_tag}</td>'
            f'<td style="padding:8px 12px;color:{TEXT_MUTED};font-size:11px;white-space:nowrap">{label}</td>'
            f'<td style="padding:8px 12px;color:{TEXT_PRIMARY};font-size:11px;line-height:1.6">{desc}</td>'
            f'</tr>'
        )

    st.markdown(
        f'<div style="overflow-x:auto;border-radius:8px;border:1px solid {BORDER_COLOR}33;margin-bottom:16px">'
        f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
        f'<thead><tr>'
        f'<th style="{th2}">Column</th>'
        f'<th style="{th2}">What it is</th>'
        f'<th style="{th2}">How to read it</th>'
        f'</tr></thead>'
        f'<tbody>{col_html}</tbody>'
        f'</table></div>',
        unsafe_allow_html=True,
    )

    # Workflow tip
    st.markdown(
        f'<div style="background:{BG_PANEL};border:1px solid {GOLD}33;border-left:3px solid {GOLD};'
        f'border-radius:0 6px 6px 0;padding:12px 16px;color:{TEXT_MUTED};font-size:12px;line-height:1.8">'
        f'<b style="color:{GOLD}">&#128161; Recommended workflow:</b> '
        f'Run Standard Watchlist each morning → filter by <b style="color:{TEXT_PRIMARY}">BUY + SETUP</b> → '
        f'sort by <b style="color:{TEXT_PRIMARY}">Confidence ↓</b> → '
        f'for any SETUP tickers with D-MACD also turning Bull, open the '
        f'<b style="color:{GOLD}">Deep Analysis</b> tab and type the ticker for a full report including '
        f'RSI gauge, Bollinger Bands, breakout chart, short squeeze data, and ATR for stop placement.'
        f'</div>',
        unsafe_allow_html=True,
    )


# ── Main render ────────────────────────────────────────────────

def _render_page_management():
    """Admin tab — toggle page visibility for regular users. 3-column card layout."""
    from scanners.page_manager import ALL_PAGES, GROUP_META, _load_settings, save_page_settings

    # ── Info banner ───────────────────────────────────────────
    st.markdown(
        f'<div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};'
        f'border-left:3px solid {GOLD};border-radius:8px;padding:16px 20px;margin-bottom:28px">'
        f'<div style="color:{GOLD};font-size:15px;font-weight:600;margin-bottom:8px">'
        f'ℹ️ How Page Visibility Works</div>'
        f'<div style="color:{TEXT_MUTED};font-size:14px;line-height:1.9">'
        f'<strong style="color:{TEXT_PRIMARY}">Regular users</strong> (APP_PASSWORD) only see '
        f'<em>enabled</em> pages. Disabled pages show a "Contact Admin" screen instead of content.<br>'
        f'<strong style="color:{TEXT_PRIMARY}">Admin users</strong> (ADMIN_PASSWORD) always see '
        f'<em>all pages</em> regardless of these settings. &nbsp;'
        f'<strong style="color:{TEXT_PRIMARY}">🔒 Required</strong> pages cannot be disabled.</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Load fresh settings (bypasses session cache — reads GSheets/disk directly)
    settings = _load_settings()

    # Build ordered group dict
    groups: dict = {}
    for p in ALL_PAGES:
        g = p["group"]
        if g not in groups:
            groups[g] = []
        groups[g].append(p)

    new_settings: dict = {}
    group_list = list(groups.items())

    # ── 3-column card grid ────────────────────────────────────
    # Groups: Dashboard | Stocks | Options  (row 1)
    #         Dividend  | Info   | —        (row 2)
    grid = st.columns(3, gap="large")

    for gi, (group_name, pages) in enumerate(group_list):
        icon = GROUP_META.get(group_name, {"icon": "📁"})["icon"]

        with grid[gi % 3]:
            # Group card header
            st.markdown(
                f'<div style="background:linear-gradient(135deg,rgba(245,200,66,0.16),rgba(245,200,66,0.04));'
                f'border:1px solid rgba(245,200,66,0.28);border-radius:8px;'
                f'padding:11px 18px;margin-bottom:14px;">'
                f'<span style="color:{GOLD};font-size:14px;font-weight:700;'
                f'letter-spacing:1.8px;text-transform:uppercase">'
                f'{icon}&nbsp; {group_name}</span></div>',
                unsafe_allow_html=True,
            )

            for pi, p in enumerate(pages):
                is_required = p.get("required", False)
                is_sub      = "parent" in p
                current_val = settings.get(p["key"], True)
                widget_key  = f"_pm_tog_{gi}_{pi}"

                lbl_col, tog_col = st.columns([6, 1])

                with lbl_col:
                    indent  = "padding-left:22px;" if is_sub else ""
                    prefix  = "↳" if is_sub else "•"
                    txt_clr = TEXT_MUTED if is_required else TEXT_PRIMARY
                    req_badge = (
                        f'&nbsp;<span style="background:rgba(245,200,66,0.14);color:{GOLD};'
                        f'font-size:10px;font-weight:700;letter-spacing:0.6px;'
                        f'text-transform:uppercase;padding:2px 8px;border-radius:10px;'
                        f'border:1px solid rgba(245,200,66,0.30)">REQUIRED</span>'
                        if is_required else ""
                    )
                    st.markdown(
                        f'<div style="{indent}color:{txt_clr};font-size:15px;'
                        f'padding:7px 0;line-height:1.5">'
                        f'{prefix}&nbsp;{p["label"]}{req_badge}</div>',
                        unsafe_allow_html=True,
                    )

                with tog_col:
                    if is_required:
                        try:
                            st.toggle("", value=True, disabled=True, key=widget_key)
                        except Exception:
                            st.checkbox("", value=True, disabled=True, key=widget_key)
                        new_settings[p["key"]] = True
                    else:
                        try:
                            val = st.toggle("", value=current_val, key=widget_key)
                        except Exception:
                            val = st.checkbox("", value=current_val, key=widget_key)
                        new_settings[p["key"]] = val

    # ── Save bar ──────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(
        f'<div style="height:1px;background:linear-gradient(90deg,transparent,{GOLD}44,transparent);'
        f'margin-bottom:22px"></div>',
        unsafe_allow_html=True,
    )

    _disabled_count = sum(1 for v in new_settings.values() if not v)
    _enabled_count  = len(new_settings) - _disabled_count

    col_save, col_status, _ = st.columns([2, 5, 1])
    with col_save:
        if st.button("💾  Save Page Settings", key="_pm_save_btn", use_container_width=True):
            save_page_settings(new_settings)
            st.success(
                f"✅ Saved — {_enabled_count} pages enabled, "
                f"{_disabled_count} disabled. Changes are live immediately."
            )
    with col_status:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:15px;padding:8px 4px">'
            f'<strong style="color:{GOLD}">{_enabled_count}</strong> enabled &nbsp;·&nbsp; '
            f'<strong style="color:#EF4444">{_disabled_count}</strong> disabled</div>',
            unsafe_allow_html=True,
        )


def render():
    # ── Admin password gate ────────────────────────────────────
    if not st.session_state.get("_admin_auth", False):
        st.markdown("<br>", unsafe_allow_html=True)
        _, col, _ = st.columns([1, 2, 1])
        with col:
            st.markdown(
                f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};'
                f'border-top:3px solid {GOLD};border-radius:12px;padding:36px 32px;text-align:center;margin-top:40px">'
                f'<div style="font-size:44px;margin-bottom:12px">🔐</div>'
                f'<div style="font-family:\'Cormorant Garamond\',serif;font-size:26px;color:{GOLD};'
                f'font-weight:700;letter-spacing:2px;margin-bottom:8px">Admin Panel</div>'
                f'<div style="color:{TEXT_MUTED};font-size:11px;letter-spacing:2px;'
                f'text-transform:uppercase;margin-bottom:28px">Restricted Access — Enter Password</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            pwd = st.text_input(
                "Admin password",
                type="password",
                placeholder="Admin password…",
                label_visibility="collapsed",
                key="_admin_pwd_input",
            )
            if st.button("🔓  Unlock Admin Panel", use_container_width=True, key="_admin_unlock_btn"):
                try:
                    correct = st.secrets["ADMIN_PASSWORD"]
                except Exception:
                    correct = os.environ.get("ADMIN_PASSWORD", "admin!")
                if pwd == correct:
                    st.session_state["_admin_auth"] = True
                    st.rerun()
                else:
                    st.error("❌ Incorrect admin password. Please try again.")
            st.markdown(
                f'<div style="color:{TEXT_MUTED};font-size:10px;text-align:center;margin-top:14px">'
                f'🔒 Admin access is logged for security purposes.</div>',
                unsafe_allow_html=True,
            )
        return   # ← stop here; don't render panel content

    # ── Lock button ────────────────────────────────────────────
    _hdr_col, _lock_col = st.columns([11, 1])
    with _lock_col:
        if st.button("🔒 Lock", key="_admin_lock_btn", help="Lock the Admin Panel"):
            st.session_state["_admin_auth"] = False
            st.rerun()

    section_header("⚙️", "Admin Panel", "Scanner reference · Stock universe browser · System info")

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Scanner Tech & Rankings",
        "📖 Scanner Guide",
        "🗃️ Stock Universe",
        "🔬 Stock Analysis",
        "🗂️ Page Management",
    ])

    with tab1:
        _render_scanner_tech()

    with tab2:
        _render_guide()

    with tab3:
        _render_universe()

    with tab4:
        _render_stock_analysis_methodology()

    with tab5:
        _render_page_management()
