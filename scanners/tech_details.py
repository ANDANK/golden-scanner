# scanners/tech_details.py — Technical Details (moved from Admin Panel)
# Tabs: Scanner Guide · Universe Browser · Scanner Tech & Rankings · Stock Analysis Methodology

import streamlit as st
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *
from utils import section_header, metric_card


# ── Scanner catalog (CC removed) ───────────────────────────────

SCANNERS = [
    {
        "key":   "Golden Scan",
        "emoji": "🔀",
        "color": GOLD,
        "desc":  "Combines all scanners, scores each signal, and ranks by multi-factor conviction. Best starting point for daily scans. Also runs automatically at 10:30 AM and 1:00 PM CST on market days.",
        "params": [
            ("Universe", f"{len(SP500_SAMPLE)} tickers", "Stocks + ETFs"),
            ("Scoring",  "Multi-factor", "Price · Volume · Technicals · Fundamentals"),
            ("Auto-runs", "AM & PM", "Results on Scheduled Scans page"),
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
        "desc":  "Cash-Secured Puts — sell OTM puts on stocks you want to own. Collects premium while waiting for a better entry. Runs on 75 top stocks + options ETF universe in scheduled scans.",
        "params": [
            ("IV Rank",   f"≥ {CSP_DEFAULTS['iv_rank_min']}",      "High IV = fat premium"),
            ("Delta",     f"{CSP_DEFAULTS['delta_min']}–{CSP_DEFAULTS['delta_max']}", "Strike selection"),
            ("Premium",   "≥ 0.65%",                                "Of stock price per week"),
            ("DTE",       "25–35 days",                             "Days to expiration"),
        ],
        "criteria": "Sell action · Strike below market · Positive theta · Bid/ask spread check",
    },
    {
        "key":   "LEAPS",
        "emoji": "🧨",
        "color": "#A78BFA",
        "desc":  "Long-term equity anticipation securities — deep ITM calls as leveraged stock replacement with defined risk.",
        "params": [
            ("DTE",      f"≥ {LEAPS_DEFAULTS['dte_min']} days",     "12–24 month expirations"),
            ("Delta",    f"{LEAPS_DEFAULTS['delta_min']}–{LEAPS_DEFAULTS['delta_max']}", "Deep ITM"),
            ("IV Rank",  "≤ 35",                                     "Buy when IV is low"),
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
    {
        "key":   "First Things First",
        "emoji": "🎯",
        "color": GOLD,
        "desc":  "Highest-conviction multi-timeframe setup scanner. Applies 12 conditions simultaneously across weekly AND daily charts. Only stocks passing every condition are surfaced — quality over quantity. Universe: full S&P 500 + ETFs + 3× ETFs (~482 tickers).",
        "params": [
            ("Universe",    "~482 tickers",   "Full S&P 500 + ETFs + 3× ETFs"),
            ("Timeframes",  "Weekly + Daily",  "Both must pass independently"),
            ("Conditions",  "12 conditions",   "5 weekly · 5 daily · ADX · No BearDiv"),
            ("Sort Order",  "ADX descending",  "Strongest trending setups first"),
        ],
        "criteria": "W: Not Extended · RSI 35–70 · MACD>Signal · P>SMA20W · Uptrend  |  D: Not Ext'd · RSI 35–70 · MACD>Signal · P>EMA9 · Hist↑↑(2 bars) · ADX>16 · No BearDiv",
    },
]


# ── Universe builder ───────────────────────────────────────────

def _build_universe_df() -> pd.DataFrame:
    from scanners.deep_analysis import STANDARD_TICKERS
    from config import FTF_UNIVERSE
    ticker_map: dict[str, list] = {}

    def _add(tickers, label):
        for t in tickers:
            ticker_map.setdefault(t, [])
            if label not in ticker_map[t]:
                ticker_map[t].append(label)

    _add(SP500_SAMPLE[:200],   "Golden Scan (top 200)")
    _add(SP500_SAMPLE[200:],   "Golden Scan (extended)")
    _add(FTF_UNIVERSE,         "First Things First")
    _add(STANDARD_TICKERS,     "Stock Analysis Watchlist")
    _add(ETF_UNIVERSE,         "ETF Universe")
    _add(ETF_3X_UNIVERSE,      "3× ETF Scanner")
    _add(OPTIONS_ETF_UNIVERSE, "Options ETF")

    rows = [
        {"Ticker": t, "Used In": ", ".join(v), "# Lists": len(v)}
        for t, v in sorted(ticker_map.items())
    ]
    return pd.DataFrame(rows)


# ── Scanner Tech Rankings — per-scanner action guides ──────────

_RANKINGS = [
    {
        "scanner":    "Trend Continuation",
        "tier":       "Tier 1",
        "rating":     9.8,
        "hold":       "2–6 months",
        "confidence": "Extremely High",
        "count":      "Low",
        "noise":      "Very Low",
        "icon":       "📈",
        "action": {
            "brief":   "Base break + RS highs + Vol ≥ 1.5×",
            "sizing":  "MUST BUY → 1.5–2× position",
            "checks": [
                "Weekly chart shows 8–20 week tight base (price range ≤ 15% width)",
                "Current weekly bar closed above the prior 8-week high (resistance break)",
                "RS line vs SPY at a new 26-week high — rising faster than the market",
                "Weekly volume ≥ 1.5× the 20-week average on the breakout candle",
            ],
            "must_buy":     "All 4 confirmed simultaneously — highest conviction setup on the platform. Full size immediately.",
            "partial":      "3/4 confirmed → standard 1× size. 2/4 → watchlist only, wait for confirmation.",
            "sizing_detail":"1.5–2× standard. Reduce to 1× if daily RSI is already above 72 at entry (elevated).",
            "avoid":        "Volume below average on the breakout week — false breakout risk is high. Wait for next week.",
        },
    },
    {
        "scanner":    "Trend Stack",
        "tier":       "Tier 1",
        "rating":     9.5,
        "hold":       "1–4 months",
        "confidence": "Extremely High",
        "count":      "Low",
        "noise":      "Very Low",
        "icon":       "🏛",
        "action": {
            "brief":   "Full 4-MA stack + rising 200 SMA + RSI 50–65",
            "sizing":  "MUST BUY → 1–1.5× position",
            "checks": [
                "Daily chart: all 4 MAs visually stacked (Price > EMA20 > SMA50 > SMA200)",
                "200-day SMA is sloping upward — compare its level to 10 days ago",
                "Daily RSI is between 50–65 (not extended; 65–72 is elevated risk zone)",
                "Volume is at minimum slightly above the 20-day average line",
            ],
            "must_buy":     "Full 4-MA stack + 200 SMA rising + RSI 50–65 + any volume ≥ 1.1× → MUST BUY",
            "partial":      "Full stack but RSI 65–72: standard 1× with tighter stop. Stack incomplete: skip.",
            "sizing_detail":"1–1.5× standard at RSI 50–65. Drop to 0.5× if RSI 65–72 (entry risk higher).",
            "avoid":        "200 SMA flat or declining. Partial MA stack (only 3/4). RSI already > 72.",
        },
    },
    {
        "scanner":    "Trend Alignment",
        "tier":       "Tier 1",
        "rating":     9.4,
        "hold":       "1–4 months",
        "confidence": "Very High",
        "count":      "Medium",
        "noise":      "Low",
        "icon":       "🎯",
        "action": {
            "brief":   "Fresh MACD cross + weekly resistance break + rising 30W SMA",
            "sizing":  "MUST BUY → 1–1.25× position",
            "checks": [
                "Daily MACD histogram just crossed zero (check: yesterday ≤ 0, today > 0)",
                "Visually confirm 30-week SMA is sloping upward vs 4 weeks ago",
                "Weekly close is above the highest close of the prior 8 weekly bars",
                "ADX > 25 on daily chart (confirms a real trend, not sideways chop)",
            ],
            "must_buy":     "Fresh MACD cross + rising 30W SMA + weekly resistance break confirmed → MUST BUY",
            "partial":      "MACD cross but no resistance break yet: half size, wait for weekly break. Old MACD cross: skip.",
            "sizing_detail":"Standard 1×. Aggressive: 1.25× if ADX > 30 also confirmed.",
            "avoid":        "MACD histogram already positive for 3+ bars (not fresh — old signal, already priced in).",
        },
    },
    {
        "scanner":    "Multi-Factor",
        "tier":       "Tier 1",
        "rating":     9.2,
        "hold":       "1–3 months",
        "confidence": "Very High",
        "count":      "Medium",
        "noise":      "Low",
        "icon":       "🎯",
        "action": {
            "brief":   "7/7 conditions + Score ≥ 80 + near 20D high",
            "sizing":  "7/7 → 1.5×, 6/7 → 1×, ≤5/7 → watch only",
            "checks": [
                "Check the conditions count in the result (aim for 7/7 — all independent signals aligned)",
                "Price is at or within 2% of the 20-day high (breakout zone, not extended)",
                "MACD histogram bar is visually green and growing (not just barely positive)",
                "Volume bar is taller than the average line on the chart — confirms participation",
            ],
            "must_buy":     "Score ≥ 80 AND 7/7 conditions AND price near 20D high → MUST BUY. 7/7 is rare and highest conviction.",
            "partial":      "6/7 + score ≥ 70: standard size (1×). 5/7: watchlist or 0.5× max.",
            "sizing_detail":"7/7 → 1.5× standard. 6/7 → 1×. ≤5/7 → watchlist only.",
            "avoid":        "Score ≥ 80 but price extended far above 20D high (>5% above) — wait for a pullback.",
        },
    },
    {
        "scanner":    "Momentum Reset Bounce",
        "tier":       "Tier 1",
        "rating":     9.2,
        "hold":       "1–3 months",
        "confidence": "Very High",
        "count":      "Low–Medium",
        "noise":      "Low",
        "icon":       "🔄",
        "action": {
            "brief":   "EMA touch + weekly MACD turning + bullish candle + SPY ≥ 30W SMA",
            "sizing":  "Enter in two tranches: 50% now + 50% on EMA20 reclaim",
            "checks": [
                "Weekly chart: the week's low touched the 10W or 21W EMA line (price dipped to it, didn't break below)",
                "Weekly MACD histogram just crossed from negative to zero/positive (first green bar after red)",
                "Weekly candle is bullish: close > open AND close in the upper half of the week's range",
                "SPY daily chart is above its own 30-week SMA (bull market context must be intact)",
            ],
            "must_buy":     "All 4 confirmed: EMA touch (no close below) + fresh MACD cross + bullish candle + SPY bullish → enter first tranche",
            "partial":      "3/4: half size first tranche only. Wait 1 more weekly bar for full confirmation.",
            "sizing_detail":"Tranche 1: 50% of standard when MACD crosses. Tranche 2: +50% when daily EMA20 reclaimed.",
            "avoid":        "Price closed below the EMA it touched — that's a breakdown, not a bounce. Exit immediately.",
        },
    },
    {
        "scanner":    "Momentum",
        "tier":       "Tier 2",
        "rating":     8.7,
        "hold":       "2–8 weeks",
        "confidence": "High",
        "count":      "Medium–High",
        "noise":      "Moderate",
        "icon":       "⚡",
        "action": {
            "brief":   "Score ≥ 80 + RSI 55–65 + sector ETF also bullish",
            "sizing":  "Solo: 0.5–0.75×. Confirmed by weekly scanner: 1×",
            "checks": [
                "Check the sector ETF (e.g., XLK for tech, XLE for energy) is also above its SMA50",
                "Daily RSI is 55–65 — sweet spot. Above 68: wait for a pullback. Below 55: pass.",
                "MACD histogram has been positive for ≥ 2 bars (not just freshly crossed — needs follow-through)",
                "Cross-check with weekly scanners: same ticker in Trend Continuation or Trend Stack? If yes, upgrade to 1× size.",
            ],
            "must_buy":     "Score ≥ 80 + RSI 55–65 + sector ETF bullish + confirmed by a weekly scanner → full 1× position",
            "partial":      "Score ≥ 75 but no weekly confirmation: 0.5–0.75× max. High noise — use as watchlist feeder.",
            "sizing_detail":"0.5–0.75× standard as standalone. 1× standard if confirmed by Trend Continuation or Trend Stack.",
            "avoid":        "RSI > 68 (extended, chase risk). Sector ETF in downtrend. Score < 70 (insufficient alignment).",
        },
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


# ── Render: Scanner Guide ─────────────────────────────────────

def _render_guide():
    from config import FTF_UNIVERSE
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.metric("📡 Scanners Available", str(len(SCANNERS)))
    with c2: st.metric("🗂️ Golden Scan Universe", f"{len(SP500_SAMPLE):,} tickers")
    with c3: st.metric("🎯 FTF Universe", f"{len(FTF_UNIVERSE):,} tickers")
    with c4: st.metric("⚡ Options ETFs", f"{len(OPTIONS_ETF_UNIVERSE)} liquid ETFs")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:12px;margin-bottom:12px">'
        f'Click any scanner to expand its default parameters and technical criteria. '
        f'All filters are adjustable via the sidebar at run time.</div>',
        unsafe_allow_html=True,
    )

    groups = {
        "📊 Multi-Factor":       ["Golden Scan"],
        "🎯 High Conviction":    ["First Things First"],
        "📈 Equity Scans":       ["Momentum", "Growth", "Value", "Headlines"],
        "🎯 Options Strategies": ["CSP", "LEAPS"],
        "💰 Income & Dividends": ["Dividend", "Div+CC"],
        "⚡ Leveraged":          ["3x ETFs"],
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
                st.markdown(
                    f'<div style="border-left:4px solid {color};padding:10px 16px;'
                    f'background:linear-gradient(90deg,{color}18,{BG_PANEL});'
                    f'border-radius:0 8px 8px 0;margin-bottom:14px">'
                    f'<span style="color:{TEXT_PRIMARY};font-size:13px;line-height:1.5">{sc["desc"]}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                if sc["params"]:
                    cols = st.columns(min(len(sc["params"]), 4))
                    for col, (label, value, help_text) in zip(cols, sc["params"]):
                        with col:
                            st.metric(label=label, value=value, help=help_text or None)

            st.markdown(
                f'<div style="color:{TEXT_MUTED};font-size:11px;margin-top:10px;'
                f'border-top:1px solid {BORDER_COLOR};padding-top:8px">'
                f'<b style="color:{color}">Criteria: </b>{sc["criteria"]}</div>',
                unsafe_allow_html=True,
            )


# ── Name / Sector fetch (yfinance, cached 24h, on-demand) ─────

@st.cache_data(ttl=86400, show_spinner=False)
def _fetch_universe_meta(tickers: tuple) -> dict:
    """Batch-fetch shortName + sector for each ticker via yfinance.
    Falls back gracefully to '—' if a ticker fails or is blocked.
    """
    import yfinance as yf
    meta = {}
    for t in tickers:
        try:
            info = yf.Ticker(t).info
            meta[t] = {
                "Name":   (info.get("shortName") or info.get("longName") or t)[:45],
                "Sector": info.get("sector") or info.get("quoteType") or "—",
            }
        except Exception:
            meta[t] = {"Name": "—", "Sector": "—"}
    return meta


# ── Render: Universe Browser ──────────────────────────────────

def _render_universe():
    from scanners.gsheet_helper import save_universe, get_universe, using_google_sheets

    df = _build_universe_df()
    total_unique = len(df)
    multi_list   = int((df["# Lists"] >= 2).sum())
    etf_count    = int(df["Ticker"].isin(ETF_UNIVERSE + OPTIONS_ETF_UNIVERSE + ETF_3X_UNIVERSE).sum())

    m1, m2, m3, m4 = st.columns(4)
    with m1: st.metric("Unique Tickers",    f"{total_unique:,}")
    with m2: st.metric("In Multiple Lists", f"{multi_list}")
    with m3: st.metric("ETF / Fund Count",  f"{etf_count}")
    with m4: st.metric("Stock-Only",        f"{total_unique - etf_count:,}")

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    # ── Extract unique universe labels for filter ──────────────
    all_labels = sorted({
        lbl.strip()
        for row_labels in df["Used In"]
        for lbl in row_labels.split(",")
        if lbl.strip()
    })

    # ── Controls row ───────────────────────────────────────────
    c1, c2, c3 = st.columns([2.5, 2.5, 1])
    with c1:
        search = st.text_input("", placeholder="🔍 Search ticker, name or sector…",
                               key="uni_search", label_visibility="collapsed")
    with c2:
        list_filter = st.multiselect(
            "Universe", all_labels, default=[],
            placeholder="Filter by universe list…",
            key="uni_list_filter", label_visibility="collapsed",
        )
    with c3:
        filter_multi = st.checkbox("Multi-list only", value=False,
                                   key="uni_multi", help="2+ universe lists")

    # ── Load name/sector from GSheet or yfinance ──────────────
    # Priority: GSheet cache → yfinance fetch → blank
    meta: dict = {}

    # Check if GSheet has pre-saved universe data
    gs_rows = get_universe() if using_google_sheets() else []
    if gs_rows:
        meta = {r["Ticker"]: {"Name": r.get("Name","—"), "Sector": r.get("Sector","—")}
                for r in gs_rows if r.get("Ticker")}

    b1, b2, b3 = st.columns([1.4, 1.4, 4])
    with b1:
        load_btn = st.button("📥 Load Names & Sectors",
                             help="Fetch from yfinance (may take 1–2 min for full list)",
                             use_container_width=True)
    with b2:
        save_btn = st.button("💾 Save to GSheet",
                             disabled=not using_google_sheets(),
                             help="Save current Name/Sector data to 'Universe' sheet for faster future loads",
                             use_container_width=True)

    if load_btn:
        with st.spinner(f"Fetching name & sector for {total_unique} tickers…"):
            meta = _fetch_universe_meta(tuple(df["Ticker"].tolist()))
        st.session_state["_uni_meta"] = meta
        st.success(f"Loaded {len(meta)} tickers.", icon="✅")
    elif "_uni_meta" in st.session_state and not meta:
        meta = st.session_state["_uni_meta"]

    # ── Apply filters ─────────────────────────────────────────
    filtered = df.copy()
    if meta:
        filtered["Name"]   = filtered["Ticker"].map(lambda t: meta.get(t, {}).get("Name",   "—"))
        filtered["Sector"] = filtered["Ticker"].map(lambda t: meta.get(t, {}).get("Sector", "—"))
    else:
        filtered["Name"]   = "—"
        filtered["Sector"] = "—"

    if search:
        s = search.upper()
        mask = (
            filtered["Ticker"].str.contains(s, na=False) |
            filtered["Used In"].str.contains(search, case=False, na=False) |
            filtered["Name"].str.contains(search, case=False, na=False) |
            filtered["Sector"].str.contains(search, case=False, na=False)
        )
        filtered = filtered[mask]
    if list_filter:
        def _in_filter(used_in):
            return any(lbl.strip() in list_filter for lbl in used_in.split(","))
        filtered = filtered[filtered["Used In"].apply(_in_filter)]
    if filter_multi:
        filtered = filtered[filtered["# Lists"] >= 2]

    # ── Save to GSheet ────────────────────────────────────────
    if save_btn:
        if not meta:
            st.warning("Load Names & Sectors first, then save.")
        else:
            rows_to_save = [
                {
                    "Ticker":    row["Ticker"],
                    "Name":      row.get("Name", "—"),
                    "Sector":    row.get("Sector", "—"),
                    "Used_In":   row["Used In"],
                    "Num_Lists": str(int(row["# Lists"])),
                }
                for _, row in filtered.iterrows()
            ]
            ok, msg = save_universe(rows_to_save)
            (st.success if ok else st.error)(msg)
            if ok:
                get_universe.clear()

    # ── Count + export row ────────────────────────────────────
    has_meta = meta != {} and filtered["Name"].ne("—").any()
    export_cols = ["Ticker","Name","Sector","Used In","# Lists"] if has_meta else ["Ticker","Used In","# Lists"]
    export_df = filtered[[c for c in export_cols if c in filtered.columns]]

    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:12px;margin:8px 0">'
        f'Showing <b style="color:{GOLD}">{len(filtered)}</b> of {total_unique} tickers &nbsp;·&nbsp; '
        f'<span style="color:{GOLD};font-weight:600">■</span> Gold = 3+ lists &nbsp;·&nbsp; '
        f'<span style="color:{ACCENT_GREEN};font-weight:600">■</span> Green = 2 lists &nbsp;·&nbsp; '
        f'Plain = single list</div>',
        unsafe_allow_html=True,
    )

    exp_col, _ = st.columns([1, 5])
    with exp_col:
        st.download_button(
            "⬇ Export CSV", export_df.to_csv(index=False),
            "stock_universe.csv", "text/csv",
            use_container_width=True, key="uni_export",
        )

    # ── HTML table ────────────────────────────────────────────
    th = (f"padding:7px 14px;color:{TEXT_MUTED};font-size:10px;font-weight:700;"
          f"text-transform:uppercase;letter-spacing:.7px;background:{BG_PANEL};"
          f"border-bottom:2px solid {GOLD}44;white-space:nowrap")

    uni_rows = ""
    for _, row in filtered.iterrows():
        n = int(row["# Lists"])
        if n >= 3:
            bg, tc, nc = f"{GOLD}18", GOLD, GOLD
        elif n == 2:
            bg, tc, nc = f"{ACCENT_GREEN}0F", ACCENT_GREEN, ACCENT_GREEN
        else:
            bg, tc, nc = BG_CARD, TEXT_PRIMARY, TEXT_MUTED
        td = f"padding:7px 14px;border-bottom:1px solid {BORDER_COLOR}22;background:{bg}"
        name_val   = str(row.get("Name",   "—"))
        sector_val = str(row.get("Sector", "—"))
        uni_rows += (
            f'<tr>'
            f'<td style="{td};font-family:\'DM Mono\',monospace;font-weight:700;'
            f'font-size:12px;color:{tc};white-space:nowrap">{row["Ticker"]}</td>'
            f'<td style="{td};font-size:11px;color:{TEXT_PRIMARY}">'
            f'{"—" if name_val in ("—","nan","None","") else name_val}</td>'
            f'<td style="{td};font-size:11px;color:{ACCENT_BLUE}">'
            f'{"—" if sector_val in ("—","nan","None","") else sector_val}</td>'
            f'<td style="{td};font-size:11px;color:{TEXT_MUTED}">{row["Used In"]}</td>'
            f'<td style="{td};text-align:center;font-weight:700;font-size:12px;'
            f'color:{nc};white-space:nowrap">{n}</td>'
            f'</tr>'
        )

    st.markdown(
        f'<div style="overflow-x:auto;border-radius:8px;border:1px solid {BORDER_COLOR}44;'
        f'max-height:560px;overflow-y:auto">'
        f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
        f'<thead><tr>'
        f'<th style="{th}">Ticker</th>'
        f'<th style="{th}">Name</th>'
        f'<th style="{th}">Sector</th>'
        f'<th style="{th}">Universe Lists</th>'
        f'<th style="{th}"># Lists</th>'
        f'</tr></thead>'
        f'<tbody>{uni_rows}</tbody>'
        f'</table></div>',
        unsafe_allow_html=True,
    )


# ── Render: Scanner Tech & Rankings ──────────────────────────

def _render_scanner_tech():

    # ── 1. Rankings table ─────────────────────────────────────────
    st.markdown(
        f'<div style="color:{GOLD};font-size:13px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:1.2px;margin-bottom:12px">&#127942; Scanner Rankings</div>',
        unsafe_allow_html=True,
    )

    th = (f'color:{TEXT_MUTED};font-size:10px;font-weight:700;letter-spacing:.8px;'
          f'text-transform:uppercase;padding:9px 14px;border-bottom:2px solid {GOLD}55;'
          f'background:{BG_PANEL};white-space:nowrap')
    headers = ["Scanner", "Tier", "Rating", "Best Hold", "Confidence",
               "Stock Count", "Noise", "Action Guide"]
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
        td      = f'padding:9px 14px;border-bottom:1px solid {BORDER_COLOR}22;background:{bg}'

        action      = r["action"]
        must_color  = ACCENT_GREEN if r["tier"] == "Tier 1" else GOLD
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
            <div style="color:{must_color};font-size:11px;font-weight:700;margin-bottom:3px">
              {action['brief']}</div>
            <div style="color:{TEXT_MUTED};font-size:10px;line-height:1.4">{action['sizing']}</div>
          </td>
        </tr>""")

    st.markdown(
        f'<div style="overflow-x:auto;border-radius:8px;border:1px solid {BORDER_COLOR}44;margin-bottom:20px">'
        f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
        f'<thead><tr>{hdr_html}</tr></thead>'
        f'<tbody>{"".join(rows_html)}</tbody>'
        f'</table></div>',
        unsafe_allow_html=True,
    )

    # ── 2. Per-scanner action guide cards ─────────────────────────
    st.markdown(
        f'<div style="height:1px;background:linear-gradient(90deg,transparent,{GOLD}44,transparent);'
        f'margin:4px 0 20px"></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="color:{GOLD};font-size:13px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:1.2px;margin-bottom:14px">&#128203; Per-Scanner Action Playbook</div>',
        unsafe_allow_html=True,
    )

    for r in _RANKINGS:
        action  = r["action"]
        tier_c  = ACCENT_GREEN if r["tier"] == "Tier 1" else GOLD
        must_c  = ACCENT_GREEN if r["tier"] == "Tier 1" else GOLD

        with st.expander(f"{r['icon']}  **{r['scanner']}** — {r['hold']} hold · {r['confidence']} confidence",
                         expanded=False):
            st.markdown(
                f'<div style="border-left:4px solid {tier_c};padding:10px 16px;'
                f'background:linear-gradient(90deg,{tier_c}12,{BG_PANEL});'
                f'border-radius:0 8px 8px 0;margin-bottom:14px">'
                f'<span style="color:{TEXT_PRIMARY};font-size:13px;line-height:1.6">'
                f'<b style="color:{tier_c}">{r["tier"]}</b> scanner · Rating <b>{r["rating"]}/10</b> · '
                f'Noise: <b>{r["noise"]}</b></span>'
                f'</div>',
                unsafe_allow_html=True,
            )

            c_left, c_right = st.columns([3, 2])

            with c_left:
                st.markdown(
                    f'<div style="color:{tier_c};font-size:10px;font-weight:700;'
                    f'text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">'
                    f'&#9989; What to Check Manually Before Entering</div>',
                    unsafe_allow_html=True,
                )
                check_items = "".join(
                    f'<div style="padding:7px 0;border-bottom:1px solid {BORDER_COLOR}22;'
                    f'display:flex;gap:10px;align-items:flex-start">'
                    f'<span style="color:{tier_c};font-size:14px;flex-shrink:0">✓</span>'
                    f'<div style="color:{TEXT_PRIMARY};font-size:12px;line-height:1.5">{chk}</div>'
                    f'</div>'
                    for chk in action["checks"]
                )
                st.markdown(
                    f'<div style="background:{BG_PANEL};border-radius:6px;padding:4px 12px 2px">'
                    f'{check_items}</div>',
                    unsafe_allow_html=True,
                )

                if action.get("avoid"):
                    st.markdown(
                        f'<div style="background:{ACCENT_RED}0D;border:1px solid {ACCENT_RED}33;'
                        f'border-radius:6px;padding:10px 14px;margin-top:12px">'
                        f'<div style="color:{ACCENT_RED};font-size:10px;font-weight:700;'
                        f'text-transform:uppercase;letter-spacing:1px;margin-bottom:5px">&#128683; Avoid</div>'
                        f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.6">{action["avoid"]}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

            with c_right:
                st.markdown(
                    f'<div style="color:{must_c};font-size:10px;font-weight:700;'
                    f'text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">'
                    f'&#9889; MUST BUY Trigger</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<div style="background:{must_c}15;border:1px solid {must_c}44;'
                    f'border-radius:6px;padding:12px 14px;margin-bottom:10px">'
                    f'<div style="color:{must_c};font-size:12px;font-weight:700;margin-bottom:6px">&#127942; MUST BUY when:</div>'
                    f'<div style="color:{TEXT_PRIMARY};font-size:12px;line-height:1.7">{action["must_buy"]}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                st.markdown(
                    f'<div style="color:{GOLD};font-size:10px;font-weight:700;'
                    f'text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">'
                    f'&#128176; Position Sizing</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<div style="background:{BG_PANEL};border-radius:6px;padding:10px 14px;margin-bottom:8px">'
                    f'<div style="color:{GOLD};font-size:12px;font-weight:700;margin-bottom:5px">{action["sizing"]}</div>'
                    f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.6">{action["sizing_detail"]}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                if action.get("partial"):
                    st.markdown(
                        f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};'
                        f'border-radius:6px;padding:9px 12px">'
                        f'<div style="color:{TEXT_MUTED};font-size:10px;font-weight:700;'
                        f'text-transform:uppercase;letter-spacing:0.8px;margin-bottom:4px">Partial Signal</div>'
                        f'<div style="color:{TEXT_PRIMARY};font-size:11px;line-height:1.5">{action["partial"]}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

    # ── 3. Technical documentation ────────────────────────────────
    st.markdown(
        f'<div style="height:1px;background:linear-gradient(90deg,transparent,{GOLD}44,transparent);'
        f'margin:20px 0 24px"></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="color:{GOLD};font-size:13px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:1.2px;margin-bottom:16px">&#128203; Technical Documentation — Scanner Conditions & Scoring</div>',
        unsafe_allow_html=True,
    )

    _DOC_SECTIONS = [
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
            "key":   "First Things First (FTF)",
            "icon":  "🎯",
            "badge": "WEEKLY + DAILY",
            "badge_c": GOLD,
            "style": "Highest Conviction · 12 conditions · ~482-ticker universe",
            "color": GOLD,
            "intro": (
                "The strictest scanner in the platform. Requires <b>all 12 conditions</b> to pass simultaneously "
                "across <b>weekly AND daily</b> timeframes. Weekly conditions act as the primary gate — only "
                "stocks with a confirmed weekly trend structure proceed to daily evaluation. "
                "Universe: full S&P 500 stocks + liquid ETFs + sector ETFs + 3× leveraged ETFs (~482 tickers). "
                "Expect 0–10 results per scan — this is intentional. "
                "Best run <b>30–60 min after market open</b> when volume is established."
            ),
            "conditions": [
                ("W2 — Not Extended (Weekly)", "Price ≤ SMA20W × 1.15 — within 15% above the 20-week MA. Prevents chasing extended moves; tighter = better weekly risk/reward."),
                ("W3 — RSI 35–70 (Weekly)", "Weekly RSI in the healthy momentum zone. Below 35 = downtrend excluded. Above 70 = overbought weekly excluded. Matches daily RSI range."),
                ("W4 — MACD > Signal (Weekly)", "Weekly MACD line above the signal line — confirms the weekly trend has bullish momentum. Hard gate."),
                ("W6 — Price > SMA20W (Weekly)", "Price must be above its 20-week moving average — basic weekly uptrend requirement."),
                ("W9 — Uptrend (Weekly)", "Price > SMA50W OR higher highs + higher lows confirmed. Ensures the macro weekly trend is intact."),
                ("D1 — Not Extended (Daily)", "Price ≤ EMA9 × 1.08 — within 8% above the 9-day EMA. Entries close to near-term support = better risk/reward."),
                ("D2 — RSI 35–70 (Daily)", "Daily RSI in the momentum zone. Below 35 = oversold excluded. Above 70 = overbought daily excluded."),
                ("D3 — MACD > Signal (Daily)", "Daily MACD line above signal — short-term momentum bullish."),
                ("D4 — Price > EMA9 (Daily)", "Price above the 9-day EMA — the most sensitive daily trend check."),
                ("D5 — Histogram Rising 2 Consecutive Bars (Daily)", "hist[-1] > hist[-2] AND hist[-2] > hist[-3]. Momentum must be accelerating for TWO consecutive days — eliminates one-day bounces and ensures sustained daily momentum build."),
                ("X1 — ADX > 16 (Cross-TF)", "Average Directional Index above 16 — confirms a real trend exists, not sideways chop. Calculated from daily OHLC data."),
                ("X2 — No Bearish Divergence (Cross-TF)", "Price not making higher highs while RSI makes lower highs over the last 14 bars. Bearish divergence = momentum fading despite rising price = excluded."),
            ],
            "avoid": [
                "Expecting many results — FTF returns 0–15 tickers on most days; intentionally strict",
                "Scanning at market open — D5 uses yesterday's completed bars; runs reliably any time of day",
                "Ignoring the scan funnel (Weekly pass N → Final pass N) — reveals which gate is the bottleneck",
                "D6 removed — volume gate was failing 99% of tickers at open; D3+D5 already confirm participation",
                "W5 removed — weekly volume from resampled daily data unreliable; D conditions cover this",
            ],
            "scoring": [
                ("All 12 conditions pass", "Qualified", "Binary pass/fail — no partial credit"),
                ("Sorted by ADX", "Descending", "Higher ADX = stronger confirmed trend"),
                ("W gate", "5 checks", "W2 W3 W4 W6 W9"),
                ("D/X gate", "7 checks", "D1 D2 D3 D4 D5 X1 X2"),
                ("Universe", "~482 tickers", "Full S&P 500 + ETFs + 3× ETFs"),
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
        color   = doc["color"]
        badge_c = doc["badge_c"]
        with st.expander(f"{doc['icon']}  **{doc['key']}** — {doc['style']}", expanded=False):
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


# ── Render: Stock Analysis Methodology ───────────────────────

def _render_stock_analysis_methodology():
    ACCENT_BLUE_LOCAL = "#3B82F6"
    PURPLE = "#A78BFA"
    YELLOW = "#FBBF24"
    TEAL   = "#2DD4BF"

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

    # badge · how it fires in Golden Scan (None = not surfaced as a badge)
    _BADGE_INFO = {
        1:  ("MACDw",  "Ticker in Trend Cont. (TC) or Trend Align (TA) scanner — both require weekly MACD cross"),
        2:  ("MAStk",  "Ticker in Trend Stack (TS) scanner — passes only when Price > EMA20 > SMA50 > SMA200"),
        3:  ("RSIz",   "RSI column value between 45 and 70 — the bullish momentum zone"),
        4:  ("MACDd",  "Ticker in Trend Align (TA) or Multi-Factor (MF) scanner — both confirm daily MACD cross"),
        5:  ("Vol×",   "Vol Ratio column ≥ 1.5 — price move backed by ≥ 1.5× average 20-day volume"),
        10: ("BBsq",   "Not yet auto-detected — requires separate BB bandwidth computation (planned)"),
    }

    _INDICATORS = [
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
        td     = f"padding:9px 12px;border-bottom:1px solid {BORDER_COLOR}22;vertical-align:top"
        badge_info = _BADGE_INFO.get(rank)
        if badge_info:
            badge_label, badge_how = badge_info
            badge_color = ACCENT_GREEN if badge_label != "BBsq" else TEXT_MUTED
            badge_cell = (
                f'<span style="background:{badge_color}1A;color:{badge_color};'
                f'border:1px solid {badge_color}44;padding:2px 7px;border-radius:3px;'
                f'font-size:11px;font-weight:700;font-family:\'DM Mono\',monospace;'
                f'white-space:nowrap">{badge_label}</span>'
                f'<div style="color:{TEXT_MUTED};font-size:10px;margin-top:5px;'
                f'line-height:1.5;max-width:220px">{badge_how}</div>'
            )
        else:
            badge_cell = f'<span style="color:{TEXT_MUTED};font-size:11px">—</span>'
        ind_rows += (
            f'<tr>'
            f'<td style="{td};text-align:center;width:36px">'
            f'<span style="background:{color}22;color:{color};border:1px solid {color}44;'
            f'padding:2px 7px;border-radius:4px;font-weight:800;font-size:12px;font-family:\'DM Mono\',monospace">#{rank}</span>'
            f'</td>'
            f'<td style="{td}">'
            f'<div style="color:{color};font-size:12px;font-weight:700;margin-bottom:3px">{name}</div>'
            f'<div style="background:#1a1a2a;border-radius:2px;height:4px;width:{bar_w}px">'
            f'<div style="background:{color};height:4px;border-radius:2px;width:100%"></div>'
            f'</div>'
            f'</td>'
            f'<td style="{td};white-space:nowrap">'
            f'<span style="background:{BG_CARD};color:{TEXT_MUTED};border:1px solid {BORDER_COLOR}44;'
            f'padding:2px 8px;border-radius:3px;font-size:10px">{tf}</span>'
            f'</td>'
            f'<td style="{td};color:{TEXT_MUTED};font-size:11px;line-height:1.6">{why}</td>'
            f'<td style="{td}">{badge_cell}</td>'
            f'</tr>'
        )

    st.markdown(
        f'<div style="overflow-x:auto;border-radius:8px;border:1px solid {BORDER_COLOR}44;margin-bottom:16px">'
        f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
        f'<thead><tr>'
        f'<th style="{th}">#</th>'
        f'<th style="{th}">Indicator</th>'
        f'<th style="{th}">Timeframe</th>'
        f'<th style="{th}">Why It Matters (Highest → Lowest)</th>'
        f'<th style="{th}">Golden Scan Badge</th>'
        f'</tr></thead>'
        f'<tbody>{ind_rows}</tbody>'
        f'</table></div>',
        unsafe_allow_html=True,
    )

    # ── Signals column reference card ──────────────────────────────
    _SIGNAL_BADGES = [
        ("MACDw", "#1", "Weekly MACD cross",       "TC or TA scanner fired",         ACCENT_GREEN),
        ("MAStk", "#2", "MA Trend Stack aligned",   "TS scanner fired",               ACCENT_GREEN),
        ("RSIz",  "#3", "RSI in zone 45–70",        "RSI column value",               ACCENT_GREEN),
        ("MACDd", "#4", "Daily MACD cross/confirm", "TA or MF scanner fired",         ACCENT_GREEN),
        ("Vol×",  "#5", "Volume spike ≥ 1.5×",      "Vol Ratio column ≥ 1.5",         ACCENT_GREEN),
        ("BBsq",  "#10","BB squeeze setup",          "Planned — not yet auto-detected", TEXT_MUTED),
    ]
    badge_pills = "".join(
        f'<span style="background:{bc}1A;color:{bc};border:1px solid {bc}44;'
        f'padding:3px 10px;border-radius:4px;font-size:12px;font-weight:700;'
        f'font-family:\'DM Mono\',monospace;white-space:nowrap">{bl}</span>'
        for bl, _, _, _, bc in _SIGNAL_BADGES
    )
    sb_th = (f"padding:7px 12px;color:{TEXT_MUTED};font-size:10px;font-weight:700;"
             f"text-transform:uppercase;letter-spacing:.7px;background:{BG_PANEL};"
             f"border-bottom:1px solid {GOLD}33")
    sb_rows = ""
    for badge, rank, meaning, source, bc in _SIGNAL_BADGES:
        sb_td = f"padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22;vertical-align:middle"
        sb_rows += (
            f'<tr>'
            f'<td style="{sb_td}">'
            f'<span style="background:{bc}1A;color:{bc};border:1px solid {bc}44;'
            f'padding:2px 8px;border-radius:3px;font-size:11px;font-weight:700;'
            f'font-family:\'DM Mono\',monospace">{badge}</span></td>'
            f'<td style="{sb_td};text-align:center">'
            f'<span style="background:{bc}22;color:{bc};border:1px solid {bc}44;'
            f'padding:1px 7px;border-radius:3px;font-weight:800;font-size:11px;'
            f'font-family:\'DM Mono\',monospace">{rank}</span></td>'
            f'<td style="{sb_td};color:{TEXT_PRIMARY};font-size:12px">{meaning}</td>'
            f'<td style="{sb_td};color:{TEXT_MUTED};font-size:11px">{source}</td>'
            f'</tr>'
        )
    st.markdown(
        f'<div style="background:{BG_PANEL};border:1px solid {ACCENT_GREEN}33;'
        f'border-radius:10px;padding:18px 20px;margin-bottom:20px">'
        f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">'
        f'<div style="color:{ACCENT_GREEN};font-size:13px;font-weight:700;'
        f'text-transform:uppercase;letter-spacing:1px">&#9889; Signals Column — Golden Scan Reference</div>'
        f'<div style="color:{TEXT_MUTED};font-size:11px">Appears between Scanners and Scanner Count in every Golden Scan result row</div>'
        f'</div>'
        f'<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px">{badge_pills}</div>'
        f'<div style="overflow-x:auto;border-radius:6px;border:1px solid {BORDER_COLOR}33">'
        f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
        f'<thead><tr>'
        f'<th style="{sb_th}">Badge</th>'
        f'<th style="{sb_th}">Rank</th>'
        f'<th style="{sb_th}">Meaning</th>'
        f'<th style="{sb_th}">Derived From</th>'
        f'</tr></thead>'
        f'<tbody>{sb_rows}</tbody>'
        f'</table></div>'
        f'<div style="color:{TEXT_MUTED};font-size:10px;margin-top:10px;line-height:1.6">'
        f'&#9432; Multiple badges can appear simultaneously. '
        f'A ticker showing <b style="color:{ACCENT_GREEN}">MACDw + MAStk + RSIz</b> has the three highest-ranked indicators '
        f'aligned — highest conviction setup. No badge = scanner passed its own filter but none of the top-5 indicators fired independently.'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Signal Thresholds ─────────────────────────────────────────
    st.markdown(
        f'<div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:8px;'
        f'padding:16px 20px;margin-top:4px">'
        f'<div style="color:{GOLD};font-size:12px;font-weight:700;margin-bottom:10px;'
        f'text-transform:uppercase;letter-spacing:1px">&#128397; Signal Thresholds</div>'
        f'<div style="display:flex;gap:16px;flex-wrap:wrap">'
        f'<div style="background:{ACCENT_GREEN}15;border:1px solid {ACCENT_GREEN}44;border-radius:6px;'
        f'padding:10px 20px;text-align:center;min-width:110px">'
        f'<div style="color:{ACCENT_GREEN};font-size:22px;font-weight:800">≥ 60%</div>'
        f'<div style="color:{ACCENT_GREEN};font-size:11px;font-weight:700;margin-top:2px">🟢 BUY</div>'
        f'<div style="color:{TEXT_MUTED};font-size:10px;margin-top:4px;line-height:1.4">'
        f'Composite ≥ 60<br>Most indicators bullish</div></div>'
        f'<div style="background:{YELLOW}15;border:1px solid {YELLOW}44;border-radius:6px;'
        f'padding:10px 20px;text-align:center;min-width:110px">'
        f'<div style="color:{YELLOW};font-size:22px;font-weight:800">41–59%</div>'
        f'<div style="color:{YELLOW};font-size:11px;font-weight:700;margin-top:2px">🟡 NEUTRAL</div>'
        f'<div style="color:{TEXT_MUTED};font-size:10px;margin-top:4px;line-height:1.4">'
        f'Mixed signals<br>Wait for resolution</div></div>'
        f'<div style="background:{TEAL}15;border:1px solid {TEAL}44;border-radius:6px;'
        f'padding:10px 20px;text-align:center;min-width:130px">'
        f'<div style="color:{TEAL};font-size:20px;font-weight:800">≤ 40% + 🔄</div>'
        f'<div style="color:{TEAL};font-size:11px;font-weight:700;margin-top:2px">🔵 SETUP / WATCH</div>'
        f'<div style="color:{TEXT_MUTED};font-size:10px;margin-top:4px;line-height:1.4">'
        f'Composite &lt; 40 BUT<br>Weekly MACD turned ✅<br>RSI 28–64 (reset zone)</div></div>'
        f'<div style="background:{ACCENT_RED}15;border:1px solid {ACCENT_RED}44;border-radius:6px;'
        f'padding:10px 20px;text-align:center;min-width:110px">'
        f'<div style="color:{ACCENT_RED};font-size:22px;font-weight:800">≤ 40%</div>'
        f'<div style="color:{ACCENT_RED};font-size:11px;font-weight:700;margin-top:2px">🔴 SELL</div>'
        f'<div style="color:{TEXT_MUTED};font-size:10px;margin-top:4px;line-height:1.4">'
        f'Composite ≤ 40<br>Avoid or short bias</div></div>'
        f'<div style="flex:1;min-width:200px;color:{TEXT_MUTED};font-size:11px;line-height:1.9;padding:4px 0">'
        f'<b style="color:{TEXT_PRIMARY}">Confidence % is directional</b> — BUY shows the raw composite; '
        f'SELL shows 100 − composite (so a 85% SELL = composite of 15 = heavily bearish).<br>'
        f'<b style="color:{TEAL}">SETUP 🔄</b> is a special tier for stocks where the MA stack is broken '
        f'(bearish composite) but the <b style="color:{TEXT_PRIMARY}">Weekly MACD just turned positive on '
        f'a reset RSI</b> — the classic Momentum Reset Bounce entry signal.'
        f'</div></div></div>',
        unsafe_allow_html=True,
    )

    # ── SETUP Signal Action Plan ──────────────────────────────────
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
        f'to accumulate before the trend officially recovers.</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    action_rows = [
        ("Watch only", f"background:{BG_CARD}", TEXT_MUTED,
         "SETUP just appeared with no other confirmation",
         "Zero position. Add to watchlist. Check back in 1–2 weeks.",
         "Too early. One weekly MACD cross can reverse. No conviction yet."),
        ("Starter (25–33%)", f"background:{TEAL}0D", TEAL,
         "Weekly MACD positive 2nd consecutive week AND Daily MACD also turning Bull AND RSI daily crossing 50",
         "Enter 25–33% of intended position size. Set stop below recent swing low.",
         "Early entry with controlled risk. You get in before the crowd at lower price."),
        ("Add to half (50%)", f"background:{ACCENT_GREEN}0D", ACCENT_GREEN,
         "Price reclaims EMA20 on daily with expanding volume",
         "Add another 25% position. Raise stop to breakeven on first tranche.",
         "Price is now showing buying momentum. First confirmation of recovery."),
        ("Full (100%)", f"background:{ACCENT_GREEN}18", ACCENT_GREEN,
         "Price reclaims SMA50 with volume + RSI daily in 55–68 zone",
         "Add final tranche. This is now a BUY signal — the SETUP has resolved.",
         "Full MA recovery = high-conviction trend resumption. Institutional buyers confirmed."),
        ("Exit the idea", f"background:{ACCENT_RED}0D", ACCENT_RED,
         "Weekly RSI falls back below 28 OR weekly MACD histogram turns negative again",
         "Cut the position. The setup failed — this is a downtrend continuation, not a bounce.",
         "Failed setups happen ~40% of the time. Small loss early beats large loss later."),
    ]

    th_a = (f"padding:8px 12px;color:{TEXT_MUTED};font-size:9px;font-weight:700;"
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
        f'<th style="{th_a}">Action</th>'
        f'<th style="{th_a}">Trigger / Confirmation</th>'
        f'<th style="{th_a}">What to Do</th>'
        f'<th style="{th_a}">Why</th>'
        f'</tr></thead>'
        f'<tbody>{act_html}</tbody>'
        f'</table></div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f'<div style="background:{BG_PANEL};border:1px solid {TEAL}33;border-left:3px solid {TEAL};'
        f'border-radius:0 6px 6px 0;padding:12px 16px;margin-bottom:8px;'
        f'color:{TEXT_MUTED};font-size:12px;line-height:1.8">'
        f'<b style="color:{TEAL}">&#128161; Key insight:</b> '
        f'SETUP stocks fail ~35–40% of the time. The edge comes from '
        f'<b style="color:{TEXT_PRIMARY}">position sizing</b> — '
        f'starter positions mean a failed setup costs 1–2%, while a successful setup '
        f'that becomes a BUY can return 15–40% before you add full size.</div>',
        unsafe_allow_html=True,
    )

    # ── Core Stocks Analysis reference ──────────────────────────────────
    st.markdown(
        f'<div style="height:1px;background:linear-gradient(90deg,transparent,{GOLD}44,transparent);'
        f'margin:24px 0 20px"></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="color:{GOLD};font-size:13px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:1.2px;margin-bottom:14px">&#10022; Core Stocks Analysis — How It Works</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:8px;'
        f'padding:16px 20px;margin-bottom:16px">'
        f'<div style="color:{TEXT_PRIMARY};font-size:13px;line-height:1.8;margin-bottom:12px">'
        f'The <b style="color:{GOLD}">✦ Core Stocks Analysis</b> tab (inside Stock Analysis) runs the full '
        f'9-indicator engine on a fixed list of 117 pre-loaded tickers with a single button press. '
        f'No typing required. Results are cached for 4 hours.'
        f'</div>'
        f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px">'
        f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:6px;padding:12px">'
        f'<div style="color:{GOLD};font-size:11px;font-weight:700;margin-bottom:6px">&#9654; Run Scan</div>'
        f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.6">Runs all 117 tickers. '
        f'If results are &lt; 4h old, shows cached table immediately.</div></div>'
        f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:6px;padding:12px">'
        f'<div style="color:{GOLD};font-size:11px;font-weight:700;margin-bottom:6px">&#x1F504; Clear &amp; Rescan</div>'
        f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.6">Forces a full fresh scan '
        f'regardless of cache age. Use when market has moved significantly.</div></div>'
        f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:6px;padding:12px">'
        f'<div style="color:{GOLD};font-size:11px;font-weight:700;margin-bottom:6px">&#128465; Clear Cache</div>'
        f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.6">Wipes cached results '
        f'without triggering a new scan. Returns to the landing screen.</div></div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f'<div style="background:{BG_PANEL};border:1px solid {GOLD}33;border-left:3px solid {GOLD};'
        f'border-radius:0 6px 6px 0;padding:12px 16px;color:{TEXT_MUTED};font-size:12px;line-height:1.8">'
        f'<b style="color:{GOLD}">&#128161; Recommended workflow:</b> '
        f'Run Core Stocks Analysis each morning → filter by <b style="color:{TEXT_PRIMARY}">BUY + SETUP</b> → '
        f'sort by <b style="color:{TEXT_PRIMARY}">Confidence ↓</b> → '
        f'for SETUP tickers with D-MACD also turning Bull, open the '
        f'<b style="color:{GOLD}">Custom Stock Analysis</b> tab for a full report.</div>',
        unsafe_allow_html=True,
    )

    # ── Signal circle legend ───────────────────────────────────────
    st.markdown(
        f'<div style="height:1px;background:linear-gradient(90deg,transparent,{GOLD}44,transparent);'
        f'margin:24px 0 20px"></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="color:{GOLD};font-size:13px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:1.2px;margin-bottom:14px">&#11044; Signal Circle Legend — Core Stocks Analysis &amp; Custom Stock Analysis</div>',
        unsafe_allow_html=True,
    )

    _CIRCLES = [
        ("🟢", "BUY",      ACCENT_GREEN, "≥ 70",   "sig == \"BUY\"",
         "Composite score ≥ 70. MA stack aligned, MACD bull on daily + weekly, RSI in momentum zone. "
         "Highest-conviction automated pick — full position sizing appropriate."),
        ("🔵", "SETUP",    "#2DD4BF",    "40–69",  "\"SETUP\" in sig",
         "Weekly MACD just turned positive while MA stack is still broken / recovering. "
         "Early-entry signal. Start with 25–33% position and scale in as price confirms. "
         "Fails ~35–40% of the time — always use a stop."),
        ("🟡", "NEUTRAL",  "#FACC15",    "40–69",  "else (default)",
         "Mixed signals — some indicators positive, others flat or negative. No clear directional edge. "
         "Watch only. Re-check in 1–2 weeks or wait for a BUY or SETUP trigger."),
        ("🟠", "EXTENDED", "#FB923C",    "any",    "\"EXTENDED\" in sig",
         "Stock is overbought or has run far above its moving averages. RSI typically > 75 or price "
         "well above Bollinger upper band. Avoid new entries — existing positions: tighten stops / take partial profits."),
        ("🔴", "SELL",     ACCENT_RED,   "< 40",   "sig == \"SELL\"",
         "Composite score < 40. MA stack broken, MACD bearish, RSI below 45. Downtrend confirmed. "
         "Exit longs, do not buy. Short setups only for experienced traders."),
    ]

    sc_th = (f"padding:7px 14px;color:{TEXT_MUTED};font-size:10px;font-weight:700;"
             f"text-transform:uppercase;letter-spacing:.7px;background:{BG_PANEL};"
             f"border-bottom:2px solid {GOLD}44;white-space:nowrap")
    sc_rows = ""
    for circle, label, color, score_range, code, meaning in _CIRCLES:
        sc_td = f"padding:10px 14px;border-bottom:1px solid {BORDER_COLOR}22;vertical-align:top"
        sc_rows += (
            f'<tr>'
            f'<td style="{sc_td};text-align:center;font-size:20px;white-space:nowrap">{circle}</td>'
            f'<td style="{sc_td};white-space:nowrap">'
            f'<span style="background:{color}22;color:{color};border:1px solid {color}44;'
            f'padding:3px 10px;border-radius:4px;font-weight:700;font-size:12px">{label}</span>'
            f'</td>'
            f'<td style="{sc_td};white-space:nowrap">'
            f'<span style="background:{BG_CARD};color:{TEXT_MUTED};border:1px solid {BORDER_COLOR}44;'
            f'padding:2px 8px;border-radius:3px;font-size:11px;font-family:\'DM Mono\',monospace">'
            f'{score_range}</span>'
            f'</td>'
            f'<td style="{sc_td}">'
            f'<code style="background:{BG_CARD};color:{ACCENT_BLUE};border:1px solid {BORDER_COLOR}44;'
            f'padding:2px 8px;border-radius:3px;font-size:10px;white-space:nowrap">{code}</code>'
            f'</td>'
            f'<td style="{sc_td};color:{TEXT_MUTED};font-size:11px;line-height:1.6">{meaning}</td>'
            f'</tr>'
        )

    st.markdown(
        f'<div style="overflow-x:auto;border-radius:8px;border:1px solid {BORDER_COLOR}44;margin-bottom:8px">'
        f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
        f'<thead><tr>'
        f'<th style="{sc_th}">Circle</th>'
        f'<th style="{sc_th}">Signal</th>'
        f'<th style="{sc_th}">Score Range</th>'
        f'<th style="{sc_th}">Code Logic</th>'
        f'<th style="{sc_th}">What It Means / How to Act</th>'
        f'</tr></thead>'
        f'<tbody>{sc_rows}</tbody>'
        f'</table></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:10px;line-height:1.6;margin-bottom:4px">'
        f'&#9432; Priority order in code: BUY → EXTENDED → SETUP → SELL → NEUTRAL (default). '
        f'A ticker can only have one circle at a time. The circle appears in the leftmost column of '
        f'every row in the Core Stocks Analysis table and the Custom Stock Analysis summary table.</div>',
        unsafe_allow_html=True,
    )

    # ── Core Stocks Analysis Ticker Icons ────────────────────────
    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
    st.markdown(
        f'<div style="color:{GOLD};font-size:13px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:1.2px;margin-bottom:14px">&#127381; Core Stocks Analysis — Ticker Icons</div>',
        unsafe_allow_html=True,
    )

    _ICONS = [
        # (icon_html, name, timeframe, condition_a, condition_b, condition_c, notes)
        (
            "💚", "Weekly Green Heart", "Weekly",
            "MACD line &gt; Signal <b>AND</b> MACD line &gt; 0 <b>AND</b> histogram &gt; 0",
            "Weekly RSI between 50 and 70",
            "Price &gt; weekly EMA20 <b>AND</b> price ≤ 10% above it (not over-extended)",
            "ALL 3 conditions required. Zero extra API calls — weekly data already fetched. "
            "Strongest bullish confirmation available on the weekly chart.",
        ),
        (
            "💜", "Daily Purple Heart", "Daily",
            "MACD line &gt; Signal <b>AND</b> MACD line &gt; 0 <b>AND</b> histogram &gt; 0",
            "Daily RSI between 50 and 70",
            "Price &gt; daily EMA20 <b>AND</b> price ≤ 10% above it (not over-extended)",
            "ALL 3 conditions required. Same logic as 💚 but on the daily timeframe. "
            "When both 💚 and 💜 appear together, both timeframes are aligned bullish.",
        ),
        (
            "💔", "Broken Red Heart", "Daily + Weekly",
            "MACD fully bearish: line &lt; Signal, MACD line &lt; 0, histogram &lt; 0 — on daily <i>OR</i> weekly",
            "Weekly RSI &lt; 45 <i>OR</i> &gt; 70 (oversold or overbought extremes)",
            "Price below daily EMA20 <i>OR</i> below weekly EMA20",
            "ALL 3 conditions required simultaneously. A single broken condition is not enough. "
            "Bearish MACD on either timeframe qualifies for condition (a). "
            "Price below EMA20 on either timeframe qualifies for condition (c).",
        ),
        (
            "▲", "Green Triangle", "Daily",
            "Full MA stack intact: Price &gt; EMA20 &gt; SMA50 &gt; SMA200 (all 4 levels)",
            "Daily RSI between 50 and 70",
            "— (only 2 conditions)",
            "Uses the pre-computed <code>full_stack</code> boolean — no extra math. "
            "The triangle indicates a structurally healthy uptrend in its ideal momentum zone. "
            "Often stacks with 💜 when the daily is fully aligned.",
        ),
        (
            "○", "Hollow Green Circle", "Daily",
            "Bollinger Band width ≤ 15th percentile of the last 20 bars (squeeze condition)",
            "%B position &gt; 80% (price near the upper Bollinger Band inside the squeeze)",
            "Daily volume ≥ 1.5× the 20-day average (institutional participation)",
            "The classic 'BB Squeeze into upper band with volume' breakout setup. "
            "All 3 daily fields (<code>bb_squeeze</code>, <code>pct_b</code>, <code>vol_spike</code>) "
            "are pre-computed in <code>compute_analysis()</code>. Zero extra API calls.",
        ),
    ]

    ic_th = (f"padding:7px 12px;color:{TEXT_MUTED};font-size:10px;font-weight:700;"
             f"text-transform:uppercase;letter-spacing:.7px;background:{BG_PANEL};"
             f"border-bottom:2px solid {GOLD}44;white-space:nowrap")
    ic_rows = ""
    for icon, name, tf, ca, cb, cc, notes in _ICONS:
        ic_td = f"padding:9px 12px;border-bottom:1px solid {BORDER_COLOR}22;vertical-align:top"
        ic_rows += (
            f'<tr>'
            f'<td style="{ic_td};text-align:center;font-size:22px;white-space:nowrap">{icon}</td>'
            f'<td style="{ic_td};white-space:nowrap">'
            f'<span style="color:{TEXT_PRIMARY};font-size:12px;font-weight:700">{name}</span><br>'
            f'<span style="color:{TEXT_MUTED};font-size:10px">{tf}</span>'
            f'</td>'
            f'<td style="{ic_td}">'
            f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.7">'
            f'<b style="color:{TEXT_PRIMARY}">a.</b> {ca}<br>'
            f'<b style="color:{TEXT_PRIMARY}">b.</b> {cb}<br>'
            f'<b style="color:{TEXT_PRIMARY}">c.</b> {cc}'
            f'</div>'
            f'</td>'
            f'<td style="{ic_td};color:{TEXT_MUTED};font-size:11px;line-height:1.6">{notes}</td>'
            f'</tr>'
        )

    st.markdown(
        f'<div style="overflow-x:auto;border-radius:8px;border:1px solid {BORDER_COLOR}44;margin-bottom:8px">'
        f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
        f'<thead><tr>'
        f'<th style="{ic_th}">Icon</th>'
        f'<th style="{ic_th}">Name</th>'
        f'<th style="{ic_th}">Trigger Conditions (ALL must be true unless noted)</th>'
        f'<th style="{ic_th}">Implementation Notes</th>'
        f'</tr></thead>'
        f'<tbody>{ic_rows}</tbody>'
        f'</table></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:10px;line-height:1.7;margin-bottom:4px">'
        f'&#9432; <b style="color:{TEXT_PRIMARY}">Stacking:</b> icons accumulate horizontally in the Ticker cell when '
        f'multiple conditions fire simultaneously for the same ticker — e.g. 💚💜▲ means weekly bullish, '
        f'daily bullish, and full MA stack all align at once. &nbsp;'
        f'&#9432; <b style="color:{TEXT_PRIMARY}">API cost:</b> zero additional yfinance calls — daily (6mo) and weekly (2y) '
        f'bars are already fetched by <code>compute_analysis()</code>. Weekly EMA20 is a single in-memory '
        f'<code>calc_ema(close_w, 20)</code> on the cached weekly series. &nbsp;'
        f'&#9432; <b style="color:{TEXT_PRIMARY}">Where rendered:</b> both the Summary table '
        f'(<code>_render_summary_table</code>) and the Watchlist Analysis table '
        f'(<code>_render_standard_table</code>) in <code>deep_analysis.py</code>.</div>',
        unsafe_allow_html=True,
    )


# ── Trading View reference ─────────────────────────────────────

def _tv_section(title: str, icon: str, border_color: str, rows: list[tuple],
                col_heads: tuple = ("What you see", "What it is", "What to look for"),
                note: str = ""):
    """Render one Trading View indicator section as a styled card + table."""
    G = border_color
    # Section header card
    st.markdown(
        f'<div style="background:linear-gradient(135deg,{G}18,{G}08);'
        f'border-left:4px solid {G};border-radius:0 8px 8px 0;'
        f'padding:10px 16px;margin:18px 0 0">'
        f'<span style="font-size:18px">{icon}</span>'
        f'<span style="color:{G};font-size:14px;font-weight:700;'
        f'margin-left:8px;letter-spacing:0.3px">{title}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    # Column header row
    h1, h2, h3 = col_heads
    hdr_style = (f'background:{G}22;color:{G};font-size:10px;font-weight:700;'
                 f'text-transform:uppercase;letter-spacing:1px;padding:8px 14px;'
                 f'border-bottom:2px solid {G}55')
    cell_style_base = ('font-size:12px;padding:9px 14px;vertical-align:top;'
                       'border-bottom:1px solid #ffffff0d')

    row_html = ""
    for i, row in enumerate(rows):
        bg = f"background:{'#ffffff06' if i % 2 == 0 else 'transparent'};"
        # col 0: badge-style "what you see" with dot color
        dot_color, see_text, is_text, look_text = row
        badge = (
            f'<span style="display:inline-flex;align-items:center;gap:6px">'
            f'<span style="width:9px;height:9px;border-radius:50%;'
            f'background:{dot_color};flex-shrink:0;display:inline-block;'
            f'box-shadow:0 0 4px {dot_color}88"></span>'
            f'<span style="color:{TEXT_PRIMARY};font-weight:600;font-size:12px;'
            f'font-family:\'DM Mono\',monospace">{see_text}</span>'
            f'</span>'
        )
        row_html += (
            f'<tr style="{bg}">'
            f'<td style="{cell_style_base};width:24%;white-space:nowrap">{badge}</td>'
            f'<td style="{cell_style_base};width:26%;color:{TEXT_MUTED}">{is_text}</td>'
            f'<td style="{cell_style_base};width:50%;color:{TEXT_PRIMARY};line-height:1.6">'
            f'{look_text}</td>'
            f'</tr>'
        )

    table = (
        f'<div style="overflow-x:auto;border:1px solid {G}33;border-radius:0 0 8px 8px;'
        f'margin-bottom:4px">'
        f'<table style="width:100%;border-collapse:collapse;font-family:\'Inter\',sans-serif">'
        f'<thead><tr>'
        f'<th style="{hdr_style};width:24%;text-align:left">{h1}</th>'
        f'<th style="{hdr_style};width:26%;text-align:left">{h2}</th>'
        f'<th style="{hdr_style};width:50%;text-align:left">{h3}</th>'
        f'</tr></thead>'
        f'<tbody>{row_html}</tbody>'
        f'</table></div>'
    )
    if note:
        table += (
            f'<div style="color:{TEXT_MUTED};font-size:10px;font-style:italic;'
            f'padding:4px 6px 0;margin-bottom:2px">{note}</div>'
        )
    st.markdown(table, unsafe_allow_html=True)


def _render_trading_view():
    """Full TradingView indicator reference guide."""

    # ── Intro banner ───────────────────────────────────────────────
    st.markdown(
        f'<div style="background:linear-gradient(135deg,{BG_CARD},{BG_PANEL});'
        f'border:1px solid {GOLD}44;border-radius:12px;padding:20px 24px;margin-bottom:4px">'
        f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:10px">'
        f'<span style="font-size:28px">📺</span>'
        f'<div>'
        f'<div style="color:{GOLD};font-size:16px;font-weight:700;'
        f'font-family:\'Cormorant Garamond\',serif;letter-spacing:0.4px">'
        f'TradingView Chart Indicator Reference</div>'
        f'<div style="color:{TEXT_MUTED};font-size:11px;margin-top:2px">'
        f'A complete visual guide to every indicator, label, and signal on the custom chart setup.</div>'
        f'</div></div>'
        f'<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:4px">'
        + "".join([
            f'<span style="background:{c}18;border:1px solid {c}44;color:{c};'
            f'font-size:10px;font-weight:600;padding:3px 10px;border-radius:20px">{t}</span>'
            for t, c in [
                ("Moving Averages", "#22D3EE"), ("Bollinger Bands", "#60A5FA"),
                ("CPR Pivots", "#818CF8"), ("Order Blocks", "#86EFAC"),
                ("Candlestick Patterns", GOLD), ("Chart Patterns", "#F472B6"),
                ("MACD Signals", "#34D399"), ("Composite BUY/SELL", "#22C55E"),
                ("Setup Alerts", "#A78BFA"),
            ]
        ])
        + f'</div></div>',
        unsafe_allow_html=True,
    )

    # ── Confluence highlight card ──────────────────────────────────
    _GA = "#A78BFA"   # purple  — Group A (MACD)
    _GB = "#86EFAC"   # green   — Group B (Order Blocks)
    _GC = "#60A5FA"   # blue    — Group C (BB Squeeze)
    _GS = "#22C55E"   # bright green — composite score

    st.markdown(
        # ── Outer card ────────────────────────────────────────────
        f'<div style="background:linear-gradient(135deg,#1a1a2e,#12122a);'
        f'border:1px solid {_GA}55;border-radius:12px;padding:22px 24px 20px;margin:20px 0 4px">'

        # ── Headline ───────────────────────────────────────────────
        f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">'
        f'<span style="font-size:22px">⚡</span>'
        f'<div style="color:#ffffff;font-size:15px;font-weight:700;letter-spacing:0.2px;'
        f'font-family:\'Cormorant Garamond\',serif">'
        f'When the Groups Align — That\'s the Trade</div>'
        f'</div>'

        # ── Sub-headline ───────────────────────────────────────────
        f'<div style="color:#a0aec0;font-size:12px;line-height:1.7;margin-bottom:18px;'
        f'max-width:780px">'
        f'The highest-probability setups occur when two or three Setup Groups fire '
        f'<b style="color:#ffffff">simultaneously</b>. '
        f'That\'s exactly what the <b style="color:{_GS}">composite BUY n/5 score</b> measures — '
        f'when A, B, and C all point the same direction at once, it\'s far stronger than '
        f'any single group reaching step 3 on its own.'
        f'</div>'

        # ── Three group cards ──────────────────────────────────────
        f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:18px">'

        # A
        f'<div style="background:{_GA}12;border:1px solid {_GA}44;border-radius:9px;padding:14px 16px">'
        f'<div style="color:{_GA};font-size:10px;font-weight:800;text-transform:uppercase;'
        f'letter-spacing:1.2px;margin-bottom:6px">Group A · MACD Momentum</div>'
        f'<div style="color:#ffffff;font-size:13px;font-weight:700;margin-bottom:6px">'
        f'Momentum is turning.</div>'
        f'<div style="color:#a0aec0;font-size:11px;line-height:1.65">'
        f'<b style="color:#e2e8f0">A alone</b> — momentum is shifting, but is price at a '
        f'<em>meaningful level</em>? Could be triggering in the middle of nowhere.</div>'
        f'</div>'

        # B
        f'<div style="background:{_GB}10;border:1px solid {_GB}44;border-radius:9px;padding:14px 16px">'
        f'<div style="color:{_GB};font-size:10px;font-weight:800;text-transform:uppercase;'
        f'letter-spacing:1.2px;margin-bottom:6px">Group B · Order Block Zones</div>'
        f'<div style="color:#ffffff;font-size:13px;font-weight:700;margin-bottom:6px">'
        f'Price is at a key level.</div>'
        f'<div style="color:#a0aec0;font-size:11px;line-height:1.65">'
        f'<b style="color:#e2e8f0">B alone</b> — price is at a strong institutional zone, '
        f'but is momentum actually <em>turning</em> here? The level matters; the turn matters more.</div>'
        f'</div>'

        # C
        f'<div style="background:{_GC}10;border:1px solid {_GC}44;border-radius:9px;padding:14px 16px">'
        f'<div style="color:{_GC};font-size:10px;font-weight:800;text-transform:uppercase;'
        f'letter-spacing:1.2px;margin-bottom:6px">Group C · BB Squeeze</div>'
        f'<div style="color:#ffffff;font-size:13px;font-weight:700;margin-bottom:6px">'
        f'A big move is loading.</div>'
        f'<div style="color:#a0aec0;font-size:11px;line-height:1.65">'
        f'<b style="color:#e2e8f0">C is a standalone trade type.</b> Squeeze breakouts rarely '
        f'coincide with OB or MACD conditions — and that\'s fine. When C3 fires on volume, '
        f'it\'s its own high-conviction signal.</div>'
        f'</div>'

        f'</div>'  # end grid

        # ── A + B confluence highlight ─────────────────────────────
        f'<div style="background:linear-gradient(135deg,{_GA}18,{_GB}14);'
        f'border:1px solid {_GA}55;border-radius:9px;padding:14px 18px;'
        f'display:flex;align-items:center;gap:16px">'
        f'<div style="font-size:28px;flex-shrink:0">🎯</div>'
        f'<div>'
        f'<div style="color:#ffffff;font-size:13px;font-weight:700;margin-bottom:4px">'
        f'A + B Together = Highest-Conviction Entry</div>'
        f'<div style="color:#a0aec0;font-size:11px;line-height:1.7">'
        f'Momentum turning <b style="color:{_GA}">(A)</b> at an institutional demand zone '
        f'<b style="color:{_GB}">(B)</b> is the cleanest setup on the chart. '
        f'Institutions pre-place orders at OBs — when MACD confirms the turn right there, '
        f'you\'re entering alongside smart money. Add a BUY 3–4/5 label and you have '
        f'<b style="color:{_GS}">maximum confluence</b>.'
        f'</div></div>'
        f'</div>'  # end A+B bar

        f'</div>',  # end outer card
        unsafe_allow_html=True,
    )

    # ── 1. Moving Averages ─────────────────────────────────────────
    _tv_section("Moving Averages", "〰️", "#22D3EE", [
        ("#22D3EE", "Aqua line",            "20 EMA",
         "Short-term trend. Price above = bullish momentum. Acts as <b>first support</b> in uptrends."),
        ("#22C55E", "Green line",           "50 SMA",
         'Medium-term trend. The key <b>"are we in a swing trade?"</b> line.'),
        ("#EF4444", "Red line",             "100 SMA",
         "Intermediate support/resistance. Strong bounce off this = <b>high-conviction entry</b>."),
        ("#7f1d1d", "Faint dark maroon",    "200 SMA",
         "Long-term trend. Above = <b>bull market</b>. Below = <b>bear market</b>."),
    ])

    # ── 2. Bollinger Bands ─────────────────────────────────────────
    _tv_section("Bollinger Bands", "📐", "#60A5FA", [
        ("#60A5FA", "Navy lines + light blue fill", "BB (20, 2)",
         "Price touching <b>lower band + reversal candle</b> = buy setup. "
         "<b>Narrow bands (squeeze)</b> = big move coming."),
    ])

    # ── 3. CPR — Pivot Levels ──────────────────────────────────────
    _tv_section("CPR — Central Pivot Range", "⊕", "#818CF8", [
        ("#3B82F6", "Solid blue line",       "Daily Pivot (CP)",
         "Bias line for the day. <b>Above CP = bullish day bias</b>."),
        ("#EC4899", "Fuchsia lines",         "Daily BC / TC",
         "<b>Narrow CPR</b> = trending day. <b>Wide CPR</b> = choppy/range-bound."),
        ("#22C55E", "Solid green line",      "Daily S1 / R1",
         "First <b>support and resistance targets</b> for the day."),
        ("#EF4444", "Solid red line",        "Daily S1 / R1 (resistance)",
         "Price above R1 = extended; price below S1 = weak."),
        ("#F97316", "Orange circles",        "Weekly Pivot",
         "Bias line for the week. <b>Major magnet</b> for price."),
        ("#86EFAC", "Green circles",         "Weekly S1",
         "Weekly support level. Strong, high-timeframe level."),
        ("#FCA5A5", "Red circles",           "Weekly R1",
         "Weekly resistance level. Strong, high-timeframe level."),
        ("#2DD4BF", "Teal crosses",          "Monthly Pivot",
         "Big-picture anchor. Rarely hit but <b>very significant</b> when it is."),
    ])

    # ── 4. Golden / Death Cross ────────────────────────────────────
    _tv_section("Golden / Death Cross", "✦", GOLD, [
        ("#22C55E", '🔷 Green diamond "GOLDEN"', "50 SMA crossed above 200 SMA",
         "<b>Long-term bull signal.</b> Look for pullback buys after this. Institutions reload on dips."),
        ("#EF4444", '🔻 Red diamond "DEATH"',   "50 SMA crossed below 200 SMA",
         "<b>Long-term bear signal.</b> Rallies are sell opportunities. Risk-off posture."),
    ])

    # ── 5. Dynamic Support & Resistance ───────────────────────────
    _tv_section("Dynamic Support & Resistance", "⟷", "#86EFAC", [
        ("#22C55E", "Green dashed lines",  "Support (price above it)",
         "Buy near these if other signals agree. <b>More lines = stronger zone.</b>"),
        ("#EF4444", "Red dashed lines",    "Resistance (price below it)",
         "Sell / take profit near these. Cluster of red lines = wall."),
        ("#F97316", 'Orange dot "R!"',     "Price within 0.5% of resistance",
         "<b>Warning</b> — don't chase longs. Watch for rejection candle or reversal."),
    ])

    # ── 6. Order Blocks ────────────────────────────────────────────
    _tv_section("Order Blocks — Demand & Supply Zones", "⬜", "#4ADE80", [
        ("#bbf7d0", 'Light green "OB 45m Demand"',  "45-min demand zone",
         "Price re-entering = potential <b>quick bounce trade</b>. Shorter time frame — faster reaction."),
        ("#fecaca", 'Light red "OB 45m Supply"',    "45-min supply zone",
         "Price re-entering = potential <b>short or exit longs</b>."),
        ("#16a34a", 'Green "Daily Demand OB"',      "Daily demand zone",
         "<b>Stronger zone.</b> High-conviction buy area if RSI not overbought."),
        ("#dc2626", 'Red "Daily Supply OB"',        "Daily supply zone",
         "<b>Stronger resistance.</b> Good profit-taking area. Watch for exhaustion candles."),
        ("#84cc16", 'Lime green "Weekly Demand OB"', "Weekly demand zone",
         "<b>Highest conviction.</b> Major institutional buy zone. Scale-in entries."),
        ("#7f1d1d", 'Maroon "Weekly Supply OB"',    "Weekly supply zone",
         "<b>Major institutional sell zone.</b> Strong ceiling. Reduce risk near here."),
    ], note="⚠️ Box disappears automatically when price closes through it — the zone is invalidated.")

    # ── 7. Candlestick Patterns ────────────────────────────────────
    _tv_section("Candlestick Patterns", "🕯️", GOLD, [
        ("#22C55E", '▲ Green "H"',   "Hammer",              "Long lower wick near support. <b>Buyers rejected the selloff.</b> Confirm with next green candle."),
        ("#22C55E", '▲ Green "BE"',  "Bullish Engulfing",   "Big green candle swallows prior red one. <b>Strong reversal.</b> Best at key support / demand zone."),
        ("#22C55E", '▲ Green "3W"',  "Three White Soldiers","Three consecutive strong green candles. <b>Sustained buying pressure.</b>"),
        ("#EF4444", '▼ Red "SS"',    "Shooting Star",       "Long upper wick near resistance. <b>Sellers rejected the rally.</b> Confirm with next red candle."),
        ("#EF4444", '▼ Red "BE"',    "Bearish Engulfing",   "Big red candle swallows prior green one. <b>Strong reversal.</b> Best at key resistance / supply zone."),
        ("#EF4444", '▼ Red "3C"',    "Three Black Crows",   "Three consecutive strong red candles. <b>Sustained selling pressure.</b>"),
    ])

    # ── 8. Chart Patterns ─────────────────────────────────────────
    _tv_section("Chart Patterns", "📈", "#F472B6", [
        ("#22C55E", 'Green "DB"',    "Double Bottom",
         "Two lows at same level, price breaks up. Classic reversal. <b>Enter on breakout candle.</b>"),
        ("#EF4444", 'Red "DT"',      "Double Top",
         "Two highs at same level, price breaks down. Classic reversal. <b>Exit or short.</b>"),
        ("#22C55E", 'Green "IH&amp;S"', "Inverse Head &amp; Shoulders",
         "Three lows (middle lowest). Price breaking neckline = <b>strong buy</b>."),
        ("#EF4444", 'Red "H&amp;S"', "Head &amp; Shoulders Top",
         "Three highs (middle highest). Price breaking neckline = <b>strong sell.</b>"),
        ("#22C55E", 'Green "FLAG"',  "Bull Flag",
         "Strong rally → tight consolidation → breakout on volume. <b>Momentum continuation.</b>"),
        ("#EF4444", 'Red "BF"',      "Bear Flag",
         "Sharp drop → tight bounce → break lower on volume. <b>Momentum continuation down.</b>"),
    ])

    # ── 9. MACD Signals ───────────────────────────────────────────
    _tv_section("MACD Signals", "〜", "#34D399", [
        ("#22C55E", '▲ Green "M+0"', "MACD bullish cross near zero",
         "<b>High-quality buy signal</b> — cross happening right at the zero line means low-risk entry; "
         "downside is limited if wrong."),
        ("#EF4444", '▼ Red "M-0"',   "MACD bearish cross near zero",
         "<b>High-quality sell signal</b> — same logic in reverse. Cross at zero = late shorts are trapped."),
    ])

    # ── 10. MTF Breakout ──────────────────────────────────────────
    _tv_section("Multi-Timeframe (MTF) Breakout", "⚡", "#FBBF24", [
        ("#22C55E", 'Green "D+BO"', "Daily breakout on volume",
         "Price broke above <b>yesterday's high</b> with above-average volume. Momentum entry."),
        ("#EF4444", 'Red "D-BD"',   "Daily breakdown on volume",
         "Price broke below <b>yesterday's low</b> with volume. Exit longs / short entry."),
        ("#22C55E", 'Green "W+BO"', "Weekly breakout on volume",
         "<b>Bigger signal</b> — broke last week's high. Strong multi-day momentum. Add size."),
        ("#EF4444", 'Red "W-BD"',   "Weekly breakdown on volume",
         "<b>Major warning.</b> Trend likely turning. Reduce exposure, re-assess thesis."),
    ])

    # ── 11. Composite Signals ─────────────────────────────────────
    _tv_section("Composite Signals — Main BUY / SELL Labels", "🎯", "#22C55E", [
        ("#22C55E", 'Green "BUY 2/5"',  "2 or more buy conditions met",
         "Moderate buy. Look for <b>confirmation before entering</b>. Good for alerts."),
        ("#22C55E", 'Green "BUY 4/5"',  "4 buy conditions met",
         "<b>Strong buy.</b> Multiple independent systems agreeing — highest conviction setup."),
        ("#EF4444", 'Red "SELL 2/5"',   "2 or more sell conditions met",
         "Moderate sell / take-profit signal. Tighten stops or reduce size."),
        ("#EF4444", 'Red "SELL 4/5"',   "4 sell conditions met",
         "<b>Strong sell.</b> Exit or short with confidence. All systems pointing down."),
    ], note=(
        "Score components (each worth 1 pt): "
        "BB touch · RSI in zone · MACD cross · Order Block location · Classic candlestick/chart pattern."
    ))

    # ── 12. Setup Building — Purple Alerts ────────────────────────
    _tv_section("Setup Building Alerts (Purple — Watch This Bar)", "🔮", "#A78BFA", [
        ("#A78BFA", 'Purple "A1 MACD"',       "Step 1: MACD histogram building near zero",
         "<b>Early alert.</b> Not a trade yet — just awareness. Start watching the ticker."),
        ("#A78BFA", 'Purple "A2 MACD+EMA"',   "Step 2: Also above 20 EMA",
         "Getting interesting. Start watching closely. Risk/reward improving."),
        ("#A78BFA", 'Purple "A3 MACD+Vol"',   "Step 3: Volume confirmed",
         "<b>Setup complete.</b> Wait for the BUY label to confirm and pull the trigger."),
        ("#A78BFA", 'Purple "B1 / B2 / B3"',  "Order Block setup building",
         "Price approaching/entering a demand zone. B3 = high-conviction OB entry setup."),
        ("#A78BFA", 'Purple "C1 / C2 / C3"',  "BB Squeeze setup building",
         "Squeeze detected, momentum building. <b>C3 = breakout confirmed.</b> Size up."),
        ("#A78BFA", 'Purple "D1 / D2 / D3"',  "Bearish MACD setup",
         "Mirror of A-series — watch for selling opportunity developing."),
        ("#A78BFA", 'Purple "E1 / E2 / E3"',  "Bearish OB setup",
         "Price approaching supply zone — potential exit or short building."),
    ])

    # ── General rules footer ───────────────────────────────────────
    st.markdown(
        f'<div style="background:{BG_CARD};border:1px solid #A78BFA44;border-radius:10px;'
        f'padding:16px 20px;margin-top:20px">'
        f'<div style="color:#A78BFA;font-size:11px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:1px;margin-bottom:10px">&#9998; General Rules of Thumb</div>'
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">'
        f'<div style="background:#A78BFA12;border-radius:8px;padding:12px 14px">'
        f'<div style="color:#A78BFA;font-size:11px;font-weight:700;margin-bottom:4px">'
        f'🟣 Purple Label = Something is Building</div>'
        f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.7">'
        f'A setup alert tells you <b style="color:{TEXT_PRIMARY}">something is developing</b>. '
        f'Not a trade yet — add to watchlist and monitor. The higher the step number, '
        f'the closer the trade.</div></div>'
        f'<div style="background:#22C55E12;border-radius:8px;padding:12px 14px">'
        f'<div style="color:#22C55E;font-size:11px;font-weight:700;margin-bottom:4px">'
        f'🟢 Green / 🔴 Red Label = Act Now</div>'
        f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.7">'
        f'A BUY or SELL label says <b style="color:{TEXT_PRIMARY}">conditions are met right now</b>. '
        f'The <b>/5 score</b> tells you how many systems agree — '
        f'<b style="color:#22C55E">4/5 or 5/5 = highest conviction</b>. '
        f'Lower scores warrant smaller size or waiting for confirmation.</div></div>'
        f'</div>'
        f'<div style="color:{TEXT_MUTED};font-size:10px;margin-top:10px;line-height:1.7;'
        f'border-top:1px solid {BORDER_COLOR}33;padding-top:10px">'
        f'&#9432; <b style="color:{TEXT_PRIMARY}">Confluence is everything.</b> '
        f'A BUY label at a Weekly Demand OB, above the 20 EMA, with RSI in the 50–65 zone, '
        f'and a MACD cross near zero = maximum conviction entry. '
        f'Any single signal alone carries more noise than signal — always look for 2–3 agreeing indicators '
        f'before sizing up a position.</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ── ToS-Chart reference ────────────────────────────────────────

def _tos_part_header(num: str, title: str, subtitle: str, color: str):
    st.markdown(
        f'<div style="background:linear-gradient(135deg,{color}18,{color}08);'
        f'border-left:4px solid {color};border-radius:0 10px 10px 0;'
        f'padding:12px 18px;margin:24px 0 2px">'
        f'<div style="color:{color};font-size:10px;font-weight:800;text-transform:uppercase;'
        f'letter-spacing:1.4px;margin-bottom:3px">Part {num}</div>'
        f'<div style="color:#ffffff;font-size:15px;font-weight:700;margin-bottom:2px">{title}</div>'
        f'<div style="color:#a0aec0;font-size:11px">{subtitle}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_tos_chart():
    """ThinkorSwim MTF indicator complete field guide."""

    # ── Hero banner ────────────────────────────────────────────────
    G = "#22C55E"; B = "#60A5FA"; GL = GOLD; P = "#A78BFA"
    st.markdown(
        f'<div style="background:linear-gradient(135deg,#0f172a,#1e1b4b);'
        f'border:1px solid {GL}44;border-radius:14px;padding:24px 28px 20px;margin-bottom:6px">'
        f'<div style="display:flex;align-items:flex-start;gap:16px">'
        f'<div style="font-size:36px;line-height:1">📊</div>'
        f'<div>'
        f'<div style="color:{GL};font-size:18px;font-weight:700;'
        f'font-family:\'Cormorant Garamond\',serif;letter-spacing:0.3px;margin-bottom:4px">'
        f'ThinkorSwim MTF Score Indicator — Complete Field Guide</div>'
        f'<div style="color:#a0aec0;font-size:12px;line-height:1.7;max-width:720px">'
        f'A Multi-TimeFrame (MTF) scoring system that evaluates weekly and daily technical '
        f'alignment simultaneously. The score is not a trigger — it is a <b style="color:#ffffff">probability filter</b>. '
        f'High scores mean the odds are in your favour; low scores mean they are not.</div>'
        f'</div></div>'
        f'<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:16px">'
        + "".join(
            f'<span style="background:{c}18;border:1px solid {c}44;color:{c};'
            f'font-size:10px;font-weight:600;padding:3px 12px;border-radius:20px">{t}</span>'
            for t, c in [
                ("Score Hierarchy", GL), ("Step-by-Step", B),
                ("Daily vs Weekly", G), ("7 Scenarios", P),
                ("Entry Checklist", "#F472B6"), ("MTF Quick-Ref", "#FBBF24"),
            ]
        )
        + f'</div></div>',
        unsafe_allow_html=True,
    )

    # ══════════════════════════════════════════════════════════════
    # PART 1 — SCORE HIERARCHY
    # ══════════════════════════════════════════════════════════════
    _tos_part_header("1", "The Score Hierarchy", "What to focus on — not all components are equal", GL)

    _P1_ROWS = [
        ("1", "#22C55E", "EMA20 > EMA50",  "20",
         "Structural trend.",
         "If this is <b>OFF</b>, everything else is noise. A stock can look bullish on MACD and RSI "
         "during a dead-cat bounce — EMA alignment filters that out."),
        ("2", "#86EFAC", "Price > EMA50",  "18",
         "Most-watched institutional level.",
         "Funds buy pullbacks to the 50 EMA. Price above it = market has accepted the uptrend."),
        ("3", "#60A5FA", "MACD > Signal",  "18",
         "Momentum confirmation.",
         "Confirms buyers are controlling momentum. Without this, structure exists but momentum does not."),
        ("4", "#FBBF24", "RSI 50–70",      "16",
         "Momentum health check.",
         "Below 50 = not confirmed. Above 70 = overheated."),
        ("5", "#A78BFA", "Price > EMA20",  "12",
         "Short-term trend intact.",
         "Lower weight because if the top two pass, this almost always passes too."),
        ("6", "#F472B6", "Not Extended",   "8",
         "Risk filter.",
         "Prevents buying parabolic moves."),
        ("7", "#94A3B8", "MACD Near Zero", "8",
         "Entry timing refinement.",
         "Nice to have, not a requirement."),
    ]

    hdr = (f'<th style="background:#1e293b;color:{GL};font-size:10px;font-weight:700;'
           f'text-transform:uppercase;letter-spacing:0.8px;padding:10px 14px;'
           f'border-bottom:2px solid {GL}44;text-align:left">')
    rows_html = ""
    for pri, col, comp, wt, why_short, why_long in _P1_ROWS:
        rows_html += (
            f'<tr>'
            f'<td style="padding:10px 14px;border-bottom:1px solid #ffffff0d;vertical-align:middle;'
            f'background:{"#ffffff06" if int(pri)%2==0 else "transparent"}">'
            f'<span style="background:{col}22;color:{col};border:1px solid {col}44;'
            f'font-size:11px;font-weight:800;padding:3px 9px;border-radius:20px">{pri}</span></td>'
            f'<td style="padding:10px 14px;border-bottom:1px solid #ffffff0d;vertical-align:middle;'
            f'background:{"#ffffff06" if int(pri)%2==0 else "transparent"}">'
            f'<span style="color:{col};font-family:\'DM Mono\',monospace;font-weight:700;font-size:12px">'
            f'{comp}</span></td>'
            f'<td style="padding:10px 14px;border-bottom:1px solid #ffffff0d;vertical-align:middle;'
            f'background:{"#ffffff06" if int(pri)%2==0 else "transparent"}">'
            f'<span style="background:{col}22;color:{col};border:1px solid {col}55;'
            f'font-size:11px;font-weight:800;padding:2px 10px;border-radius:6px">{wt}</span></td>'
            f'<td style="padding:10px 14px;border-bottom:1px solid #ffffff0d;vertical-align:top;'
            f'background:{"#ffffff06" if int(pri)%2==0 else "transparent"}">'
            f'<div style="color:#ffffff;font-size:11px;font-weight:600;margin-bottom:2px">{why_short}</div>'
            f'<div style="color:#94a3b8;font-size:11px;line-height:1.6">{why_long}</div></td>'
            f'</tr>'
        )

    st.markdown(
        f'<div style="overflow-x:auto;border:1px solid {GL}33;border-radius:0 0 10px 10px">'
        f'<table style="width:100%;border-collapse:collapse;font-family:\'Inter\',sans-serif">'
        f'<thead><tr>'
        f'{hdr}Priority</th>{hdr}Component</th>{hdr}Weight</th>{hdr}Why It Matters Most</th>'
        f'</tr></thead><tbody>{rows_html}</tbody></table></div>'
        f'<div style="background:#EF444418;border:1px solid #EF444444;border-radius:8px;'
        f'padding:10px 16px;margin-top:8px;font-size:11px;color:#FCA5A5;line-height:1.7">'
        f'⚠️ <b>Rule of Thumb:</b> If the top three components (EMA20>EMA50, Price>EMA50, MACD>Signal) '
        f'are all <b>OFF</b> — walk away regardless of the total score.</div>',
        unsafe_allow_html=True,
    )

    # ══════════════════════════════════════════════════════════════
    # PART 2 — STEP BY STEP
    # ══════════════════════════════════════════════════════════════
    _tos_part_header("2", "Step by Step: Finding High-Probability Setups", "Follow this sequence every time", B)

    _STEPS = [
        ("1", "#60A5FA", "Filter by MTF Score",
         f'Start in the TOS Scanner. Set <b style="color:#60A5FA">MTF Score ≥ 75</b> as a minimum filter. '
         f'This immediately narrows to stocks where weekly <em>and</em> daily are both reasonably aligned.'),
        ("2", "#22C55E", "Check Weekly Score First",
         f'Open the chart. Look at <b>WKLY Score</b> before anything else.<br>'
         f'<span style="color:#22C55E">&#9679; ≥ 80</span> — weekly trend is strong. Proceed.<br>'
         f'<span style="color:#FBBF24">&#9679; 60–79</span> — weekly is mixed. Raise your standard for the daily score.<br>'
         f'<span style="color:#EF4444">&#9679; &lt; 60</span> — weekly is broken or bearish. <b>Stop here regardless of daily.</b><br>'
         f'<span style="color:#94a3b8;font-size:10px">Weekly carries 70% of the MTF score. A weak weekly cannot be saved by a strong daily.</span>'),
        ("3", "#A78BFA", "Check the Two Non-Negotiables on Weekly",
         f'Manually verify on the weekly chart:<br>'
         f'<b style="color:#A78BFA">EMA20 > EMA50: ON</b> — the intermediate uptrend is structurally intact<br>'
         f'<b style="color:#A78BFA">P&gt;EMA50: ON</b> — price is above the institutional support level<br>'
         f'If either is <b>OFF</b> on the weekly, the setup is not ready. Put it on a watchlist and come back.'),
        ("4", GOLD, "Drop to Daily Chart",
         f'Now check <b>DLY Score</b>:<br>'
         f'<span style="color:#22C55E">&#9679; ≥ 80</span> — daily is fully aligned. Strong entry candidate.<br>'
         f'<span style="color:#FBBF24">&#9679; 60–79</span> — daily is building. Check RSI and MACD specifically.<br>'
         f'<span style="color:#EF4444">&#9679; &lt; 60</span> — daily is lagging. Wait or pass.'),
        ("5", "#34D399", "Check Entry Timing on Daily",
         f'<b>RSI</b> — ideally 50–65. GREEN = confirmed. YELLOW (45–50) = potential early entry — valid if weekly is strong.<br>'
         f'<b>|MACD| near zero: ON</b> — MACD has not run too far from zero, meaning the momentum move is early or resetting.'),
        ("6", "#F472B6", "Check Earnings",
         f'<span style="color:#EF4444"><b>Earnings ≤ 7d</b> — pass entirely.</span> Binary risk invalidates the technical setup.<br>'
         f'<span style="color:#FBBF24"><b>7–14d</b></span> — proceed with smaller size or tighter stop.'),
        ("7", "#FBBF24", "Volume Confirmation",
         f'<b>Vol: ON</b> confirms institutional participation. A setup where everything else is green but '
         f'volume is OFF is a lower-conviction entry — not disqualifying, but <b>size down</b>.'),
    ]

    for step_num, col, title, body in _STEPS:
        st.markdown(
            f'<div style="display:flex;gap:14px;align-items:flex-start;'
            f'background:{col}0A;border:1px solid {col}33;border-radius:10px;'
            f'padding:14px 16px;margin-bottom:8px">'
            f'<div style="background:{col};color:#000;font-size:12px;font-weight:900;'
            f'width:26px;height:26px;border-radius:50%;display:flex;align-items:center;'
            f'justify-content:center;flex-shrink:0;margin-top:1px">{step_num}</div>'
            f'<div style="flex:1">'
            f'<div style="color:{col};font-size:13px;font-weight:700;margin-bottom:5px">{title}</div>'
            f'<div style="color:#cbd5e1;font-size:11px;line-height:1.75">{body}</div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )

    # ══════════════════════════════════════════════════════════════
    # PART 3 — DAILY vs WEEKLY
    # ══════════════════════════════════════════════════════════════
    _tos_part_header("3", "Daily vs Weekly: When to Use Each", "The right timeframe for the right decision", G)

    _wk_items = [
        ("Stock selection", "deciding whether a stock deserves attention at all"),
        ("Trend direction", "the authoritative view of where the stock is going"),
        ("Hold decisions", "whether to stay in a position or exit"),
        ("Major S/R", "weekly EMAs and MACD tell you where the real levels are"),
        ("Thesis check", "before entering any swing trade, the weekly should agree"),
    ]
    _d_items = [
        ("Entry timing", "pinpointing when to buy, not just whether to buy"),
        ("Stop placement", "daily structure gives logical stop levels"),
        ("Position monitoring", "tracking whether the setup is developing or breaking down"),
        ("Pullback entries", "RSI dipping to 45–50 on daily within a weekly uptrend = buy signal, not a warning"),
    ]

    def _tf_card(title, icon, col, items):
        rows = "".join(
            f'<div style="display:flex;gap:8px;align-items:flex-start;margin-bottom:8px">'
            f'<span style="color:{col};font-size:12px;margin-top:1px">&#9679;</span>'
            f'<div><span style="color:#ffffff;font-size:11px;font-weight:600">{label}</span>'
            f'<span style="color:#94a3b8;font-size:11px"> — {desc}</span></div>'
            f'</div>'
            for label, desc in items
        )
        return (
            f'<div style="background:{col}0E;border:1px solid {col}44;border-radius:10px;padding:16px 18px">'
            f'<div style="color:{col};font-size:13px;font-weight:700;margin-bottom:12px">'
            f'{icon} {title}</div>{rows}</div>'
        )

    col_w, col_d = st.columns(2)
    with col_w:
        st.markdown(_tf_card("Weekly Chart", "📅", "#60A5FA", _wk_items), unsafe_allow_html=True)
    with col_d:
        st.markdown(_tf_card("Daily Chart", "📈", "#22C55E", _d_items), unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════
    # PART 4 — ALL SCENARIOS
    # ══════════════════════════════════════════════════════════════
    _tos_part_header("4", "All Scenarios: What Each Combination Means", "7 complete setups with action guidance", P)

    _SCENARIOS = [
        ("1", "#22C55E", "✅", "Weekly HIGH + Daily HIGH",   "MTF ≥ 80",
         "The ideal setup. Highest probability. All timeframes aligned.",
         [("Enter with full intended position size", G),
          ("Stop below daily EMA20 or EMA50 depending on volatility", G),
          ("Expect follow-through — weekly trend is confirming daily momentum", G),
          ("The only scenario where you act with full conviction", G)]),
        ("2", "#86EFAC", "🟡", "Weekly HIGH + Daily MEDIUM", "MTF 65–79",
         "Weekly trend intact, daily is building. Most common setup you will encounter.",
         [("RSI YELLOW (45–50 on daily) = pullback-to-support buy. Enter 50–75% size", "#86EFAC"),
          ("RSI RED + MACD &lt; Signal = daily still correcting. Wait — do not force entry", "#EF4444"),
          ("MACD near zero ON = good entry timing, momentum is resetting", "#86EFAC"),
          ("Add to full size once daily score crosses 80", "#86EFAC")]),
        ("3", "#FBBF24", "⏳", "Weekly HIGH + Daily LOW",    "MTF 55–70",
         "Stock in longer-term uptrend but daily is in active correction or consolidation.",
         [("Do NOT enter — daily weakness is real even if weekly is strong", "#EF4444"),
          ("Add to watchlist — these often become the best Scenario 1 setups within 1–3 weeks", "#FBBF24"),
          ("Watch for EMA20>EMA50 to turn ON on daily — that is the re-evaluate signal", "#FBBF24"),
          ("Exception: price on weekly EMA50 + high weekly score = small speculative entry with tight stop", "#94a3b8")]),
        ("4", "#60A5FA", "🔵", "Weekly MEDIUM + Daily HIGH", "MTF 60–74",
         "Daily is fully bullish but weekly has not confirmed. Daily is leading, not following.",
         [("Weekly EMA alignment just turned ON = beginning of new trend. Valid with smaller size", "#60A5FA"),
          ("Weekly EMA alignment still OFF = daily move may not sustain. High risk", "#EF4444"),
          ("Take partial profit quickly if weekly does not catch up within 2–3 weeks", "#60A5FA"),
          ("Tighter stops required", "#FBBF24")]),
        ("5", "#F97316", "⚠️", "Daily HIGH + Weekly LOW",    "MTF &lt; 60 despite high daily",
         "The most dangerous scenario. Daily bullish but weekly is broken.",
         [("Counter-trend or dead-cat bounce in a downtrend — do NOT enter for swing", "#EF4444"),
          ("The 70% weekly weight keeps MTF low despite high daily — system is correctly warning you", "#F97316"),
          ("Only valid for intraday or 1–2 day traders with strict stops", "#F97316"),
          ("The daily will almost certainly fail to follow through", "#EF4444")]),
        ("6", "#EF4444", "🔴", "Both LOW",                   "MTF &lt; 55",
         "Stock is in a downtrend on both timeframes.",
         [("No action. Do not look for reasons to buy", "#EF4444"),
          ("Remove from active watchlist", "#EF4444"),
          ("Re-evaluate only if weekly EMA alignment turns ON and weekly score crosses 60", "#94a3b8")]),
        ("7", "#A78BFA", "📈", "Both IMPROVING",             "MTF 55–65, rising",
         "Score is moderate but direction of change matters — a rising score is more interesting than a falling one.",
         [("Watch for weekly EMA alignment turning ON — that is the inflection point", "#A78BFA"),
          ("Build in stages: partial at first confirmation, add when weekly crosses 70", "#A78BFA"),
          ("A score rising from 40→60 is more interesting than a score falling from 80→65", "#A78BFA")]),
    ]

    for num, col, icon, title, range_lbl, summary, actions in _SCENARIOS:
        acts_html = "".join(
            f'<div style="display:flex;gap:8px;align-items:flex-start;margin-bottom:5px">'
            f'<span style="color:{ac};font-size:10px;margin-top:2px;flex-shrink:0">&#9654;</span>'
            f'<span style="color:{ac};font-size:11px;line-height:1.5">{at}</span></div>'
            for at, ac in actions
        )
        st.markdown(
            f'<div style="background:{col}0C;border:1px solid {col}44;border-radius:10px;'
            f'padding:14px 18px;margin-bottom:8px">'
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">'
            f'<span style="font-size:18px">{icon}</span>'
            f'<div style="flex:1">'
            f'<span style="color:{col};font-size:13px;font-weight:700">Scenario {num}: {title}</span>'
            f'<span style="background:{col}22;color:{col};border:1px solid {col}44;'
            f'font-size:10px;font-weight:700;padding:2px 9px;border-radius:20px;'
            f'margin-left:10px">{range_lbl}</span>'
            f'</div></div>'
            f'<div style="color:#cbd5e1;font-size:11px;margin-bottom:10px;'
            f'padding-bottom:8px;border-bottom:1px solid {col}22">{summary}</div>'
            f'{acts_html}</div>',
            unsafe_allow_html=True,
        )

    # ══════════════════════════════════════════════════════════════
    # PART 5 — VALIDATION CHECKLIST
    # ══════════════════════════════════════════════════════════════
    _tos_part_header("5", "Validation Checklist Before Entry", "Run through this mentally for every trade", "#F472B6")

    _CHECKS = [
        ("Weekly Score ≥ 70",           "#22C55E", True),
        ("EMA20 > EMA50 ON (weekly)",   "#22C55E", True),
        ("P>EMA50 ON (weekly)",         "#22C55E", True),
        ("Daily Score ≥ 65",            "#60A5FA", True),
        ("MACD>Sig ON (daily)",         "#60A5FA", True),
        ("RSI GREEN or YELLOW — not RED", "#FBBF24", False),
        ("Extended: OFF",               "#F472B6", False),
        ("Earnings > 14d (preferred) / > 7d minimum", "#F97316", False),
        ("Vol: ON (confirms participation)", "#A78BFA", False),
        ("MTF Score ≥ 72",              GOLD,      True),
    ]

    items_html = "".join(
        f'<div style="display:flex;align-items:center;gap:10px;'
        f'background:{col}0E;border:1px solid {col}33;border-radius:8px;'
        f'padding:10px 14px">'
        f'<span style="width:18px;height:18px;border:2px solid {col};border-radius:4px;'
        f'display:inline-flex;align-items:center;justify-content:center;'
        f'flex-shrink:0;font-size:10px;color:{col}">{"★" if must else "○"}</span>'
        f'<span style="color:#e2e8f0;font-size:11px;font-weight:{"700" if must else "400"}">{label}</span>'
        f'</div>'
        for label, col, must in _CHECKS
    )

    st.markdown(
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px">'
        f'{items_html}</div>'
        f'<div style="background:#1e293b;border:1px solid #334155;border-radius:8px;'
        f'padding:12px 16px;font-size:11px;color:#94a3b8;line-height:1.7">'
        f'<b style="color:#ffffff">★ = Non-negotiable &nbsp;|&nbsp; ○ = Important but flexible</b><br>'
        f'<b style="color:#22C55E">Six or more boxes checked</b> = proceed with entry. &nbsp;'
        f'<b style="color:#EF4444">Fewer than five</b> = wait or pass.</div>',
        unsafe_allow_html=True,
    )

    # ══════════════════════════════════════════════════════════════
    # PART 6 — MTF QUICK REFERENCE
    # ══════════════════════════════════════════════════════════════
    _tos_part_header("6", "The One-Sentence Summary for Each Score Level", "MTF Score quick-reference", "#FBBF24")

    _MTF_ROWS = [
        ("85–100", "#22C55E", "Full alignment, both timeframes bullish",      "Buy with conviction",              "full"),
        ("72–84",  "#86EFAC", "Strong setup, minor gaps",                     "Buy with standard size",           "standard"),
        ("60–71",  "#FBBF24", "Building, one timeframe lagging",              "Watch — partial entry possible",   "partial"),
        ("45–59",  "#F97316", "Mixed signals, no clear trend",                "Watchlist only",                   "watch"),
        ("< 45",   "#EF4444", "Downtrend or broken structure",                "Avoid",                            "avoid"),
    ]

    size_badge = {
        "full":     ("#22C55E", "Full Size"),
        "standard": ("#86EFAC", "Standard Size"),
        "partial":  ("#FBBF24", "Partial Entry"),
        "watch":    ("#F97316", "Watch Only"),
        "avoid":    ("#EF4444", "Avoid"),
    }

    rows2 = ""
    for score, col, meaning, action, sz in _MTF_ROWS:
        bc, bl = size_badge[sz]
        bg = "#ffffff08" if _MTF_ROWS.index((score, col, meaning, action, sz)) % 2 == 0 else "transparent"
        rows2 += (
            f'<tr style="background:{bg}">'
            f'<td style="padding:11px 16px;border-bottom:1px solid #ffffff0d">'
            f'<span style="background:{col}22;color:{col};border:1px solid {col}44;'
            f'font-family:\'DM Mono\',monospace;font-size:12px;font-weight:700;'
            f'padding:3px 12px;border-radius:20px">{score}</span></td>'
            f'<td style="padding:11px 16px;border-bottom:1px solid #ffffff0d;'
            f'color:#cbd5e1;font-size:11px">{meaning}</td>'
            f'<td style="padding:11px 16px;border-bottom:1px solid #ffffff0d;'
            f'color:#e2e8f0;font-size:11px;font-weight:600">{action}</td>'
            f'<td style="padding:11px 16px;border-bottom:1px solid #ffffff0d">'
            f'<span style="background:{bc}22;color:{bc};border:1px solid {bc}44;'
            f'font-size:10px;font-weight:700;padding:2px 10px;border-radius:20px">{bl}</span></td>'
            f'</tr>'
        )

    h2 = (f'background:#1e293b;color:#FBBF24;font-size:10px;font-weight:700;'
          f'text-transform:uppercase;letter-spacing:0.8px;padding:10px 16px;'
          f'border-bottom:2px solid #FBBF2444;text-align:left')
    st.markdown(
        f'<div style="overflow-x:auto;border:1px solid #FBBF2433;border-radius:10px;margin-bottom:6px">'
        f'<table style="width:100%;border-collapse:collapse;font-family:\'Inter\',sans-serif">'
        f'<thead><tr>'
        f'<th style="{h2};width:14%">MTF Score</th>'
        f'<th style="{h2};width:42%">What It Means</th>'
        f'<th style="{h2};width:28%">Action</th>'
        f'<th style="{h2};width:16%">Size</th>'
        f'</tr></thead><tbody>{rows2}</tbody></table></div>',
        unsafe_allow_html=True,
    )


# ── Main render ────────────────────────────────────────────────

def _render_mtpa_reference():
    """MTPA Scanner — Filter Logic & Reference Guide."""
    G  = ACCENT_GREEN
    GL = GOLD
    B  = ACCENT_BLUE
    P  = "#A78BFA"

    def _sec(title, color, icon=""):
        st.markdown(
            f'<div style="background:linear-gradient(135deg,{color}18,{color}08);'
            f'border-left:4px solid {color};border-radius:0 8px 8px 0;'
            f'padding:10px 16px;margin:20px 0 6px">'
            f'<span style="font-size:16px">{icon}</span>'
            f'<span style="color:{color};font-size:13px;font-weight:700;margin-left:8px">'
            f'{title}</span></div>',
            unsafe_allow_html=True,
        )

    def _row(label, desc, col=None):
        lc = col or GL
        return (
            f'<tr>'
            f'<td style="padding:8px 14px;border-bottom:1px solid #ffffff0d;'
            f'white-space:nowrap;vertical-align:top">'
            f'<span style="color:{lc};font-weight:700;font-size:12px">{label}</span></td>'
            f'<td style="padding:8px 14px;border-bottom:1px solid #ffffff0d;'
            f'color:#cbd5e1;font-size:12px;line-height:1.65">{desc}</td>'
            f'</tr>'
        )

    def _table(rows_html, col_a="Term", col_b="Definition"):
        _HD = (f'background:#0f172a;color:{GL};font-size:10px;font-weight:700;'
               f'text-transform:uppercase;letter-spacing:0.7px;padding:8px 14px;'
               f'border-bottom:2px solid {GL}33;text-align:left')
        return (
            f'<div style="overflow-x:auto;border:1px solid #1e293b;border-radius:8px;margin-bottom:4px">'
            f'<table style="width:100%;border-collapse:collapse;font-family:\'Inter\',sans-serif">'
            f'<thead><tr><th style="{_HD};width:22%">{col_a}</th>'
            f'<th style="{_HD};width:78%">{col_b}</th></tr></thead>'
            f'<tbody>{rows_html}</tbody></table></div>'
        )

    # ── Hero banner ────────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="background:linear-gradient(135deg,#0f172a,#1e1b4b);'
        f'border:1px solid {GL}44;border-radius:12px;padding:18px 24px;margin-bottom:8px">'
        f'<div style="color:{GL};font-size:16px;font-weight:700;margin-bottom:6px">'
        f'📊 MTPA Scanner — Momentum Trend Price Action</div>'
        f'<div style="color:#a0aec0;font-size:12px;line-height:1.7">'
        f'A <b style="color:#fff">pure-filter, no-score</b> scanner that categorises stocks by '
        f'how many timeframes are aligned. No black-box weighting — a stock either passes a '
        f'condition or it doesn\'t. Each table represents a distinct level of conviction.</div>'
        f'<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:12px">'
        + "".join(
            f'<span style="background:{c}18;border:1px solid {c}44;color:{c};'
            f'font-size:10px;font-weight:700;padding:3px 10px;border-radius:20px">{t}</span>'
            for t, c in [
                ("🟢 PRIME", G), ("🟡 STRONG", "#FBBF24"),
                ("🔵 BUILDING", B), ("💜 MACD MOMENTUM", P),
                ("🎯 First Things First", GL),
            ]
        )
        + f'</div></div>',
        unsafe_allow_html=True,
    )

    # ── Weekly conditions ──────────────────────────────────────────────────────
    _sec("Weekly Conditions", GL, "📅")
    st.markdown(_table(
        _row("HH / HL", "Last 5 weekly bars show consecutively higher highs AND higher lows — clean uptrend structure. The stock is printing a staircase pattern.", G) +
        _row("Tight Base", "Average weekly ATR% (High − Low) / Close over last 5 bars < 4.5%. Low-volatility consolidation — energy coiling before a move.", B) +
        _row("Mixed", "Neither HH/HL nor Tight Base detected. Structure is unclear.", TEXT_MUTED) +
        _row("Wk Extended", "Weekly close > Weekly EMA(20) × 1.10. Stock is stretched — risk of mean-reversion. PRIME and STRONG tables require this to be OFF.", ACCENT_RED),
        "Pattern", "What it means"
    ), unsafe_allow_html=True)

    # ── Daily conditions ───────────────────────────────────────────────────────
    _sec("Daily Conditions", B, "📈")
    st.markdown(_table(
        _row("RSI GREEN", "RSI(14) is 50–70 AND rising vs 2 bars ago — momentum building in the bullish sweet spot.", G) +
        _row("RSI YELLOW", "RSI(14) is 40–50 AND rising — recovering from weakness, worth watching.", "#FBBF24") +
        _row("RSI NEUTRAL", "All other cases: not rising, or outside the 40–70 range.", TEXT_MUTED) +
        _row("MACD > Signal", "EMA(12) − EMA(26) is above its 9-period signal line — bullish crossover confirmed.", G) +
        _row("MACD Zone", "🎯 Near Zero: |MACD| ≤ 1% of price (freshest signal). 📈 Positive: above zero. 📉 Negative: below zero. Table 1 (PRIME) requires Near Zero.", GL) +
        _row("Vol Ratio", "Today's volume ÷ 20-day average. <b>Vol OK = 1.0–1.8×</b> (healthy interest without a blow-off spike).", G) +
        _row("Price > SMA20", "Price is above its 20-day simple moving average — short/medium-term trend intact.", G) +
        _row("Price > SMA9", "Price is above its 9-day EMA — very short-term trend intact. Used in PRIME criteria.", G),
        "Condition", "Definition"
    ), unsafe_allow_html=True)

    # ── Earnings ───────────────────────────────────────────────────────────────
    _sec("Earnings Proximity", "#F97316", "📅")
    st.markdown(_table(
        _row("🔴 SKIP",   "Earnings in ≤ 7 days. Excluded from PRIME — binary risk invalidates the technical setup.", ACCENT_RED) +
        _row("🟡 WARN",   "Earnings in 8–14 days. Shown in all tables; flagged as 'Earnings Soon'. Size down.", "#FBBF24") +
        _row("🟢 OK",     "Earnings > 14 days away or unknown. Full confidence in the setup duration.", G),
        "Flag", "Action"
    ), unsafe_allow_html=True)

    # ── Table assignment ───────────────────────────────────────────────────────
    _sec("Table Assignment — Qualification Criteria", GL, "📋")

    _tier_rows = [
        ("🟢 PRIME (Table 1)", G,
         "Weekly HH/HL or Tight Base · Not extended · RSI GREEN or YELLOW · "
         "MACD > Signal · Volume OK (1–1.8×) · Price > SMA20 · "
         "|MACD| ≤ 1% of price (fresh crossover) · Earnings not SKIP"),
        ("🟡 STRONG (Table 2)", "#FBBF24",
         "Not extended (weekly) · RSI GREEN or YELLOW · MACD > Signal · "
         "Price > SMA20 · (Any MACD zone allowed — structure confirmed, timing flexible)"),
        ("🔵 BUILDING (Table 3)", B,
         "RSI GREEN or YELLOW · MACD > Signal · "
         "(Weekly structure and volume not required — daily signal only)"),
    ]
    tier_html = ""
    for lbl, col, crit in _tier_rows:
        tier_html += (
            f'<div style="background:{col}0E;border:1px solid {col}44;'
            f'border-radius:8px;padding:12px 16px;margin-bottom:8px">'
            f'<div style="color:{col};font-size:12px;font-weight:700;margin-bottom:5px">{lbl}</div>'
            f'<div style="color:#cbd5e1;font-size:11px;line-height:1.7">{crit}</div>'
            f'</div>'
        )
    tier_html += (
        f'<div style="color:{TEXT_MUTED};font-size:11px;padding:6px 4px">'
        f'&#9432; Each ticker appears in <b style="color:#fff">at most one table</b> '
        f'(highest priority wins — PRIME beats STRONG beats BUILDING).</div>'
    )
    st.markdown(tier_html, unsafe_allow_html=True)

    # ── MACD Momentum (Table 4) ────────────────────────────────────────────────
    _sec("💜 MACD Momentum — Table 4", P, "")
    st.markdown(_table(
        _row("Weekly", "MACD Line > 0 (EMA12 > EMA26) · Histogram > 0 (MACD > Signal) · Histogram rising (accelerating momentum, not peaking).", P) +
        _row("Daily", "MACD Line > 0 · Histogram > 0.", P) +
        _row("Independence", "Table 4 runs independently — a ticker can appear here AND in Table 1/2/3 simultaneously. No dedup applied.", GL) +
        _row("Circle indicator", "🟢 = also in Table 1 (PRIME) · 🟡 = Table 2 (STRONG) · 🔵 = Table 3 (BUILDING) · No circle = MACD signal only.", G) +
        _row("RSI column", "Shows <b>W: weekly RSI</b> and <b>D: daily RSI</b> side-by-side. 🟢 GREEN = 50–70 · 🟡 YELLOW = 40–50 · grey = outside range.", B),
        "Aspect", "Detail"
    ), unsafe_allow_html=True)

    # ── Candlesticks ───────────────────────────────────────────────────────────
    _sec("Candlestick Patterns Detected (last 3 bars)", GL, "🕯️")
    candles = [
        ("Hammer", "Long lower wick near support — buyers rejected the selloff"),
        ("Bullish Engulfing", "Big green candle swallows the prior red candle"),
        ("Morning Star", "3-candle reversal: down · small · up — bottom confirmation"),
        ("Piercing Line", "Green candle closes above midpoint of prior red candle"),
        ("Bullish Harami", "Small green candle inside prior large red — indecision → bulls"),
        ("Three White Soldiers", "Three consecutive strong green candles — sustained buying"),
        ("Dragonfly Doji", "Open = Close at the high, long lower shadow near support"),
        ("Inverted Hammer", "Long upper wick at a low — buyers testing after a down move"),
        ("Tweezer Bottom", "Two candles with identical lows — double rejection of lower prices"),
    ]
    c_html = "".join(_row(p, d, G) for p, d in candles)
    st.markdown(_table(c_html, "Pattern", "Signal"), unsafe_allow_html=True)

    # ── RS vs SPY ──────────────────────────────────────────────────────────────
    _sec("Relative Strength vs SPY (10-day)", B, "📊")
    st.markdown(_table(
        _row("OUTPERFORM", "Ticker 10-day return / SPY 10-day return > 1.02 — stock is leading the market.", G) +
        _row("MATCH", "Ratio 0.95–1.02 — moving roughly in line with the market.", TEXT_MUTED) +
        _row("UNDERPERFORM", "Ratio < 0.95 — lagging the market. Caution for swing entries.", ACCENT_RED),
        "Status", "Threshold"
    ), unsafe_allow_html=True)

    # ── First Things First ─────────────────────────────────────────────────────
    _sec("🎯 First Things First — High-Conviction Setup Filter", GL, "")
    ftf_rows_w = [
        ("W2", "Not Extended (≤15% above SMA20W)", "Prevents chasing parabolic moves"),
        ("W3", "RSI 35–70 (weekly)", "Healthy momentum zone — matches daily RSI range"),
        ("W4", "MACD > Signal (weekly)", "Weekly momentum bullish"),
        ("W6", "Price > SMA20W", "Above 20-week moving average"),
        ("W9", "Uptrend — Price > SMA50W or HH/HL", "Macro weekly trend confirmed"),
    ]
    ftf_rows_d = [
        ("D1", "Not Extended (≤8% above EMA9)", "Entry close to near-term support"),
        ("D2", "RSI 35–70 (daily)", "Daily momentum in healthy zone"),
        ("D3", "MACD > Signal (daily)", "Daily momentum bullish"),
        ("D4", "Price > EMA9", "Above short-term daily trend"),
        ("D5", "Histogram rising — 2 consecutive bars", "Momentum accelerating for 2 days straight, not a 1-day bounce"),
        ("X1", "ADX > 16", "Confirmed trend — not sideways chop"),
        ("X2", "No bearish divergence", "Price making higher highs but RSI not = excluded"),
    ]
    ftf_html = (
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">'
        f'<div>'
        f'<div style="color:{G};font-size:11px;font-weight:700;'
        f'text-transform:uppercase;letter-spacing:0.8px;margin-bottom:8px">'
        f'Weekly (all 5 must hold)</div>'
        + _table("".join(_row(k, f"<b>{v}</b> — {n}", G) for k, v, n in ftf_rows_w), "#", "Condition")
        + f'</div><div>'
        f'<div style="color:{B};font-size:11px;font-weight:700;'
        f'text-transform:uppercase;letter-spacing:0.8px;margin-bottom:8px">'
        f'Daily + Cross-TF (all 7 must hold)</div>'
        + _table("".join(_row(k, f"<b>{v}</b> — {n}", B) for k, v, n in ftf_rows_d), "#", "Condition")
        + f'</div></div>'
        f'<div style="color:{TEXT_MUTED};font-size:11px;margin-top:8px;padding:8px 12px;'
        f'background:{BG_PANEL};border-radius:6px">'
        f'&#9432; All 12 conditions must hold simultaneously (5 weekly + 5 daily + ADX + no divergence). '
        f'Universe: ~482 tickers (full S&amp;P 500 + ETFs + 3× ETFs). '
        f'Removed: W1 W5 W7 (redundant/unreliable), D6 (volume — redundant with MACD+Hist filters). '
        f'D5 requires 2 consecutive rising histogram bars (not just 1). '
        f'Results sorted by ADX descending (strongest trend first).'
        f'</div>'
    )
    st.markdown(ftf_html, unsafe_allow_html=True)


# ── Render: Summary — Scanner × Technicals Matrix ─────────────
# Grouped matrices: technicals as rows, scanners as columns.
# Cell legend: value/threshold = hard gate · "+sc" = scored only ·
#              "chart" = drawn not filtered · "—" = not used.

def _summary_header(title: str, subtitle: str = ""):
    sub = (f'<div style="color:{TEXT_MUTED};font-size:12px;margin-top:2px">{subtitle}</div>'
           if subtitle else "")
    st.markdown(
        f'<div style="color:{GOLD};font-size:14px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:1.2px;margin:18px 0 8px;padding-bottom:6px;'
        f'border-bottom:1px solid {GOLD}33">{title}</div>{sub}',
        unsafe_allow_html=True,
    )


def _render_summary_matrix():
    st.markdown(
        f'<div style="border-left:4px solid {GOLD};padding:10px 16px;'
        f'background:linear-gradient(90deg,{GOLD}18,{BG_PANEL});border-radius:0 8px 8px 0;'
        f'margin-bottom:10px"><span style="color:{TEXT_PRIMARY};font-size:13px;line-height:1.6">'
        f'Every scanner in the platform mapped against the technical indicators it uses. '
        f'There are <b>23 distinct scanners</b>, grouped into 4 families for readability.'
        f'</span></div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        "**Legend** &nbsp; a value/threshold = **hard gate** (must pass) · "
        "`+sc` = feeds the score only · `chart` = drawn but not filtered · `—` = not used."
    )

    # ── Group 1 ──────────────────────────────────────────────────
    _summary_header("Group 1 — Daily Stock, Trend & Breakout Scanners")
    st.markdown("""
| Technical | ⚡ Momentum | 🚀 Growth | 💎 Value | 📡 MACD Cross | 🏛 Trend Stack | 🌀 Squeeze | 🐋 HVB | 🎯 Multi-Factor |
|---|---|---|---|---|---|---|---|---|
| **Price range** | $10–3000 | $10–3000 | $5–3000 | $10–3000 | ≥$15 | $10–3000 | $10–3000 | $10–3000 |
| **SMA20** | over-ext guard (>15%→skip) | over-ext guard | — | — | — | — | — | — |
| **SMA50** | price > 50 (gate) | price > 50 (gate) | — | price > 50 (gate) | in stack | price > 50 (gate) | price > 50 (gate) | price>50>200 (gate) |
| **SMA200** | +sc (50>200) | — | price>200 +sc | — | stack + slope-up (gate) | — | — | gate (50>200) |
| **EMA20** | — | — | — | — | price>EMA20>50>200 (gate) | — | — | — |
| **RSI** | 55–68 (gate) | <75 guard | — | <70 (gate) | 55–68 (gate) | rising +sc | ≥60 (gate) | 55–68 (gate) |
| **MACD** | hist>0 **and** rising (gate) | +sc | — | fresh bull cross (gate) | chart | turning up (opt gate) | — | hist>0 (gate) |
| **Volume ratio** | ≥1.25× (gate) | +sc (≥1.5) | — | ≥1.25× (gate) | ≥1.25× (gate) | trending up (opt gate) | ≥2× (gate) | ≥1.25× (gate) |
| **ATR / expansion** | +sc | shown | — | shown | +sc | shown | shown | expanding (gate) |
| **Bollinger Bands** | — | — | — | — | chart | width@20d-low + break upper (gate) | — | chart |
| **Keltner / TTM Squeeze** | — | — | — | — | — | BB inside KC (gate) | — | — |
| **OBV** | — | — | — | — | — | — | +sc | — |
| **RS vs SPY** | +sc | ≥1.02 (gate) | — | — | ≥1.05 (gate) | — | — | ≥1.05 (gate) |
| **20D high / breakout** | +sc | — | — | — | within 3% (gate) | — | breaks 20/50D high (gate) | within 2% + res-break (gate) |
| **Gap up** | — | — | — | +sc | — | — | +sc | +sc |
| **Fundamentals** | — | Rev>X%, EPS>X% (gate) | P/E,P/B,ROE,D/E,FCF (gate) | — | — | — | — | — |
| **Market cap** | min (gate) | shown | shown | — | — | — | — | — |
| **Earnings proximity** | optional exclude | — | — | — | — | — | — | — |
| **Backtest engine** | — | — | — | ✅ win-rate/avg | — | — | ✅ win-rate/avg | — |
| **Score basis** | trend+RSI+MACD+vol+20DH+RS | rev/EPS+RS+trend | P/E+P/B+ROE+D/E+FCF+>200 | cross+RSI+vol+gap | stack+RSI+vol+20DH+RS+ATR | squeeze+BB+MACD+vol+firing | breakout+vol+RSI+OBV | 0–100 + "X/7 conditions" |
| **When / how to use** | bull swings 10–30d | growth names 30–180d | cheap quality, reversion | earliest momentum | trend ride | pre-breakout coils | volume breakouts | strict all-agree entry |
| **Why good** | clean momentum filter | fundamentals + technicals | trap-screened value | catches moves early | strongest MA alignment | times expansion | big-money footprint | highest probability (7 gates) |
| **Why weak** | lags bottom; chop whipsaw | needs fundamentals | value traps; ignores momentum | early = false starts | needs 200+ bars; late | fires either direction | can buy the spike top | very few results |
""")

    # ── Group 2 ──────────────────────────────────────────────────
    _summary_header("Group 2 — Weekly Setups, Aggregator & MTPA (Admin)")
    st.markdown("""
| Technical | 🎯 Trend Align | 📈 Trend Cont. | 🔄 Reset Bounce | ✦ Golden Scan | 📊 MTPA (T1–T4 + FTF) |
|---|---|---|---|---|---|
| **Timeframe** | daily + weekly | weekly | weekly | merges all daily+weekly | daily + weekly |
| **Daily MACD** | fresh cross ≤3 bars (gate) | — | — | via members | line>signal (gate); near-zero T1 |
| **Weekly MACD** | — | chart | hist turns/positive (gate) | via members | T4: line>0 + hist>0 + rising |
| **Daily RSI** | 55–78 (gate) | — | — | 45–70 signal | 50–70 rising = GREEN |
| **Weekly RSI** | — | 60–75 (gate) | 48–62 + rising (gate) | — | shown; FTF 35–75 |
| **ADX** | >18 daily (gate) | — | — | — | FTF: >16 (gate) |
| **30-week SMA** | price>30W + rising (gate) | price>30W + rising (gate) | price>30W + rising (gate) | — | — |
| **10W vs 30W SMA** | — | 10W>30W (gate) | — | — | — |
| **EMA pullback (10W/21W)** | — | — | low touches EMA (gate) | — | — |
| **SMA9 / SMA20 (daily)** | — | — | — | — | price>SMA20 (T1/T2); >SMA9 (FTF) |
| **Weekly resist / base break** | 8-wk close high (gate) | 8–20wk break or near-hi (gate) | — | — | — |
| **Weekly pattern (HH/HL, base)** | — | — | — | — | T1 gate; FTF uptrend |
| **Volume** | wk ≥1.2× + liq>200k | wk spike ≥1.5× +sc | rising vs prior wk (gate) | spike signal | >0.7×/>1.0× (gate) |
| **RS vs SPY** | 26-wk +sc | 26-wk + new-high +sc | 26-wk +sc | shown | 10-day RS status |
| **Reversal candle** | — | — | bullish wk candle (gate) | — | candlestick patterns (display) |
| **Earnings proximity** | exclude ≤14d (opt) | — | — | — | SKIP ≤7d / WARN ≤14d |
| **Sector ETF trend** | — | — | SPY>30W context | — | sector ETF MACD bull |
| **Score basis** | cross+RSI+ADX+MA+vol+RS | MA+RSI+base+vol+RS | MA+EMA+RSI+MACD+candle+vol | inherits + multi-signal rank | **no score** — tier assignment |
| **When / how to use** | breakout 15–45d | weekly ride 20–60d | buy-the-dip 10–30d | confluence dashboard | structured watch-list (admin) |
| **Why good** | multi-timeframe confirm | catches trends early | best entry price | ranks 2+ scanner hits | 4 tiers + 18-cond FTF |
| **Why weak** | many gates → sparse | enters mid-trend | fails if trend broke | only as good as members | complex; admin; no score |
""")

    # ── Group 3 ──────────────────────────────────────────────────
    _summary_header("Group 3 — Options Income & Directional Scanners")
    st.markdown("""
| Technical | 📦 Covered Calls | 💰 Cash-Sec. Puts | 🧨 LEAPS | 📈 ETF Options | ⚡ 3× ETF Options | 📅 Dividend + CC |
|---|---|---|---|---|---|---|
| **Underlying universe** | stocks / ETFs | stocks / ETFs | stocks / ETFs | 15 liquid ETFs | 13 leveraged ETFs | div large caps |
| **Trend (SMA50)** | near-resist heuristic | price>50 = bullish +sc | price>50>200 (gate) | — | — | — |
| **Delta** | 0.15–0.25 (gate) | 0.15–0.30 (gate) | 0.60–0.75 ITM (gate) | 0.15–0.30 (~0.22) | ~0.20 OTM | ATM/slightly OTM |
| **IV / IV Rank** | IV rank +sc | IV rank ≥min (gate) | IV rank ≤max (gate) | IV rank ≥min (gate) | IV rank ≥min (gate) | IV shown |
| **Premium %** | ≥ yield min (gate) | ≥% of strike (gate) | — (cost focus) | ≥% (gate) | ≥% of strike (gate) | total income % (gate) |
| **DTE** | 1–20 (gate) | 1–35 (gate) | ≥300 (gate) | 1–20 (gate) | 7–30 (gate) | ex-div→+28 |
| **Bid/Ask spread** | mid-price | ≤max % (gate) | mid-price | liquidity score | ≤max +sc | spread +sc |
| **Annualized return** | shown | shown | — | shown | shown | "if called" P&L |
| **Resistance (20D high)** | within 5% +sc | — | — | — | — | — |
| **ATR / volatility** | — | — | — | — | risk flags (>5/8%) | — |
| **Ex-dividend date** | — | — | — | — | — | 1–N days out (gate) |
| **Leverage / breakeven** | upside cap, P(assign) | BE=K−prem | leverage, BE=K+prem | — | BE=K−prem | never-lose-if-called |
| **Score basis** | delta+prem+resist+IV+DTE | IV+delta+prem+spread+trend | trend+RS+RSI+MACD+IV+delta | liquidity (spread+vol+IV) | IV+prem+spread+prem/risk | income+days+called-P&L |
| **When / how to use** | income on owned shares | get paid to buy lower | leveraged long (low IV) | premium on liquid ETFs | high-octane premium | capture dividend safely |
| **Why good** | steady yield | enter at discount | stock-like, less capital | tight spreads | huge premiums | "never lose if called" |
| **Why weak** | caps upside if called | assignment risk | capital tied long | lower premium | volatility decay; risk | tiny edge; data-dependent |
""")

    # ── Group 4 ──────────────────────────────────────────────────
    _summary_header("Group 4 — ETF Trend, Sector & Dividend Income")
    st.markdown("""
| Technical | 📊 ETF Trends | ⚡ 3× Leveraged ETF | 📊 Sector Rotation | 💵 Dividend Hacker |
|---|---|---|---|---|
| **Universe** | broad ETF list | 17 bull/bear 3× ETFs | 11 SPDR sectors + macro | ~150 div stocks/ETFs |
| **Price (SMA20)** | — | price>20 +sc | vs SMA20 shown | — |
| **Price (SMA50)** | price>50 (gate) | price>50 +sc | above/below = in/out | — |
| **Price (SMA200)** | +sc (50>200) | — | SPY context | — |
| **EMA9** | — | — | ≤3% = entry zone | — |
| **RSI** | 50–70 (gate) | 45–75 (gate) | 45–65 ideal | — |
| **MACD** | hist>0 +sc | hist>0 +sc | — | — |
| **Volume ratio** | ≥1.3 flow signal | ≥mult (gate) | >1.2× = accumulation | min avg vol filter |
| **ATR / expansion** | shown | warn (>3/5%) +sc | — | — |
| **RS vs SPY** | ≥1.02 (gate) | — | 3-mo ratio + trend (core) | — |
| **Returns (1M/3M)** | — | — | shown | — |
| **Dividend yield** | — | — | — | range filter (gate) |
| **Ex-div date** | — | — | — | within N weeks (gate) |
| **Frequency / consistency** | — | — | — | freq + payout consistency |
| **Direction (bull/bear)** | — | selectable filter | rotate in/out | — |
| **Score basis** | trend+RSI+RS+MACD+vol | intensity+RSI+MACD+vol+ATR | sorted by RS (+ trade-idea) | sort: yield/cap/consistency |
| **When / how to use** | find leading sectors | short-term bursts | where money rotates | plan ex-div income |
| **Why good** | sector-leadership view | high reward in trends | top-down regime read | reliable 6-source ex-div |
| **Why weak** | broad, not single-name | volatility decay | macro, not exact entry | drops ~div on ex-day |
""")

    _summary_header("Cross-cutting notes")
    st.markdown("""
- **Shared core engine:** almost every scanner reuses `calc_sma / calc_ema / calc_rsi / calc_macd / calc_atr` from `utils.py`; options scanners add `approx_iv_rank` and `annualized_return`.
- **Scoring convention:** stock/ETF scanners normalize to **0–100** and sort descending. **Sector Rotation** sorts by RS; **MTPA** uses tier assignment (no 0–100 score).
- **Hard-gate vs scored:** a scanner can *require* an indicator (gate) or merely *reward* it (`+sc`). Multi-Factor makes 7 indicators hard gates; Momentum gates 4 and scores the rest.
- **Single-scanner indicators:** Bollinger/Keltner squeeze → **Squeeze** · OBV → **HVB** · ADX → **Trend Align / MTPA-FTF** · candlesticks → **MTPA** · ex-dividend logic → **Dividend Hacker / Dividend+CC** · P/E·P/B·ROE·D/E·FCF → **Value** · Rev/EPS growth → **Growth**.
""")


# ── Render: Summary — Power Ranking ───────────────────────────
# Highest → lowest signal power, with strength / use / location / power-ups.

def _render_summary_ranking():
    st.markdown(
        f'<div style="border-left:4px solid {GOLD};padding:10px 16px;'
        f'background:linear-gradient(90deg,{GOLD}18,{BG_PANEL});border-radius:0 8px 8px 0;'
        f'margin-bottom:12px"><span style="color:{TEXT_PRIMARY};font-size:13px;line-height:1.6">'
        f'Scanners ranked by <b>signal power</b> — how reliably the signal precedes a real move. '
        f'Directional scanners are judged on edge; income/options scanners (⚙️) are judged on '
        f'their own purpose and sit lower because they don\'t generate directional edge themselves.'
        f'</span></div>',
        unsafe_allow_html=True,
    )

    st.markdown("""
### 🥇 1. Golden Scan — Multi-Signal tickers
- **Strength:** The most powerful view in the app. Runs 6 scanners and surfaces tickers confirmed by **2+ independent scanners** across daily *and* weekly timeframes. Confluence = highest probability.
- **When:** Your weekly starting point — find where multiple methods agree.
- **How:** Read the **⭐ Multi-Signal** expander first; ignore single-scanner hits unless score ≥ 80.
- **Location:** **Stocks → Golden Scan → ⭐ Multi-Signal Tickers**
- **Power-ups:** (1) Weight ranking by *scanner conviction priority*, not just raw count. (2) Add a market-regime gate — flag all longs when SPY is below its 200-SMA.

### 🥈 2. MTPA — Table 1 (PRIME) + First Things First
- **Strength:** Strictest structural filter: weekly pattern + not-extended + daily RSI/MACD + volume + SMA20 + MACD-near-zero + earnings-clear. FTF layers **18 conditions** incl. ADX and no-bearish-divergence.
- **When:** When you want a small, hand-pickable watch-list of textbook setups.
- **How:** Table 1 = buy list, Table 2 (STRONG) = on-deck, Table 3 (BUILDING) = early. FTF rows are most vetted.
- **Location:** **Admin → MTPA Scanner** (Tables 1/2/3/4); FTF also at **Admin → Strategies → FTF tab**
- **Power-ups:** (1) Make **RS vs SPY** and **sector-trending** hard gates for Table 1 (computed but not enforced). (2) Add a 0–100 score so PRIME rows can be ranked.

### 🥉 3. Multi-Factor Breakout
- **Strength:** 7 hard gates must *all* agree (trend, RSI, MACD, volume, ATR-expansion, near-20D-high, RS). Shows "X/7" conviction. Rare but high-quality.
- **When:** Strong/neutral market, only the cleanest breakouts.
- **How:** Filter to **7/7 conditions**; size up only those.
- **Location:** **Stocks → Golden Scan** (runs as the "MF" engine; per-scanner expander)
- **Power-ups:** (1) Add **weekly MACD** confirmation (daily-only today). (2) Add an **ADX > 20** gate.

### 4. Trend Continuation (weekly)
- **Strength:** Catches institutional momentum early — price > rising 30W SMA, 10W > 30W, weekly RSI 60–75, base breakout + RS new highs.
- **When:** Holding 20–60 days; riding established trends.
- **How:** Prefer rows with **Consol Break ✅ + RS New Hi ✅**.
- **Location:** **Stocks → Golden Scan** ("TC" expander)
- **Power-ups:** (1) Add a **daily entry trigger** so weekly signals don't enter late. (2) Add an **ADX** strength filter.

### 5. Trend Stack
- **Strength:** Full MA alignment (price > EMA20 > SMA50 > SMA200) with the 200-SMA sloping up — the cleanest "everything stacked" trend.
- **When:** Trend-following entries near the 20-day high.
- **How:** Take **Stack = ✅ Full** with RS > 1.10.
- **Location:** **Stocks → Golden Scan** ("TS" expander)
- **Power-ups:** (1) Require **volume trending up** on the breakout bar. (2) Output an ATR-based stop suggestion.

### 6. Trend Alignment (daily + weekly)
- **Strength:** Multi-timeframe — fresh daily MACD cross + RSI 55–78 + **ADX > 18** + price breaking weekly resistance above a rising 30W MA + liquidity floor.
- **When:** Breakout entries, 15–45 day holds.
- **How:** Favor **ADX ≥ 30** with weekly break confirmed.
- **Location:** **Stocks → Golden Scan** ("TA" expander)
- **Power-ups:** (1) Add **weekly MACD** alignment. (2) Raise the liquidity floor for cleaner fills.

### 7. Momentum Reset Bounce (weekly)
- **Strength:** Best *entry price* in a strong trend — buys the pullback to the 10W/21W EMA with RSI resetting (48–62) and turning up, plus a bullish reversal candle and SPY-bullish context.
- **When:** Adding to / initiating in trends that just dipped.
- **How:** Prefer **10W EMA touch + MACD → +**.
- **Location:** **Stocks → Golden Scan** ("MRS" expander)
- **Power-ups:** (1) Require a **daily confirmation trigger**. (2) Gate on sector "rotating IN."

### 8. Sector Rotation
- **Strength:** Top-down regime read — ranks 11 SPDR sectors by RS vs SPY with rotation in/out + ready-made LEAP/CSP trade ideas. Tells you *which pond to fish in*.
- **When:** Start-of-week macro context; pairs with every stock scanner.
- **How:** Take the top 3 sectors (improving RS, RSI < 68) and scan stocks within them.
- **Location:** **Admin → Strategies → Sector Rotation tab**
- **Power-ups:** (1) Add a **breadth metric** (% sectors above SMA50). (2) Auto-feed top sectors' constituents into stock scans.

### 9. MACD Power Cross
- **Strength:** Earliest momentum-ignition signal, and one of only two scanners with a **built-in backtest** (win-rate/avg-return).
- **When:** Catching moves at the start; aggressive entries.
- **How:** Cross-check the backtest card before trusting the signal.
- **Location:** **Stocks → Golden Scan** (feeds "MACDd" signal); standalone engine in Tech Hackers
- **Power-ups:** (1) Add an **RS-vs-SPY** gate (has none today). (2) Require price > 200-SMA.

### 10. High-Volume Breakout (HVB)
- **Strength:** Tracks the institutional footprint — break of 20/50D high on ≥2× volume + OBV + strong close. Also backtested.
- **When:** Momentum/breakout trading on volume surges.
- **How:** Prefer **Breaks 50D ✅ + Vol ≥ 3× + OBV rising**.
- **Location:** **Stocks → Golden Scan**; standalone engine in Tech Hackers
- **Power-ups:** (1) Add **2-day follow-through** confirmation. (2) Layer float/short-interest context.

### 11. Momentum (daily)
- **Strength:** Solid, well-filtered baseline — bull trend, RSI 55–68, MACD rising, volume-confirmed, over-extension guard.
- **When:** General medium-swing momentum, 10–30 days.
- **Location:** **Stocks → Golden Scan** ("M" expander)
- **Power-ups:** (1) Add **weekly trend confirmation**. (2) Reward **RS at new highs**.

### 12. Volatility Squeeze
- **Strength:** Times coiled-spring setups (Bollinger inside Keltner) *before* expansion — great timing tool.
- **When:** Anticipating a big move when direction is unclear.
- **How:** Wait for **Firing! 🔥** (price breaking upper BB) to confirm direction.
- **Location:** Standalone engine in Tech Hackers (surfaced via Golden Scan's BB-squeeze icon)
- **Power-ups:** (1) Add a **directional bias gate** — only fire long when MACD + RS bullish. (2) Output an expected-move / position-size estimate.

### 13. Growth
- **Strength:** Pairs fundamentals (rev/EPS acceleration) with technical confirmation — durable multi-month plays.
- **When:** 30–180 day holds in growth names.
- **Location:** **Stocks → Golden Scan** (optional "G" — checkbox, slower)
- **Power-ups:** (1) Reward **RS new highs**. (2) Add earnings-estimate-revision trend to avoid decelerating names.

### 14. 3× Leveraged ETF Momentum
- **Strength:** Highest reward-per-day when a trend is clean; built-in volatility warnings.
- **When:** *Short-term only* directional bursts.
- **How:** Take strong intensity scores in the trend direction; never hold through chop.
- **Location:** **Stocks → 3× Leveraged ETFs**
- **Power-ups:** (1) Gate on the **underlying index trend + VIX regime**. (2) Enforce a hard max-hold reminder.

### 15. Value
- **Strength:** Finds cheap quality with a trap-screen (debt/ROE/FCF). Counter-cyclical diversifier.
- **When:** Mean-reversion / rotation into value.
- **Location:** Standalone engine (logic in `value_scanner`)
- **Power-ups:** (1) Add a **catalyst / earnings-revision** filter. (2) Require RSI bottoming so you don't buy a falling knife.

---

### ⚙️ Execution / income tools (powerful for their job, not directional edge)
- **CSP — Stocks/ETFs** → *Options → CSP*: get paid to buy lower. **Power-up:** compute *true* IV Rank from 52-week IV history (today it's `approx_iv_rank` from a single IV) + earnings-inside-DTE filter.
- **LEAPS — Stocks/ETFs** → *Options → LEAPS*: leveraged long-term, less capital. **Power-up:** rank by underlying RS/trend strength.
- **3× ETF Options** → *Options → 3× ETF Options*: huge premium from high IV (small size only). **Power-up:** gate on underlying-index trend.
- **Dividend + CC Capture** → *Dividend → Dividend + CC Capture*: engineered "never lose if called." **Power-up:** rank by live assignment probability (delta).
- **Dividend Hacker** → *Dividend → Upcoming Dividends*: ex-div income calendar (6-source waterfall). **Power-up:** add post-ex-div price-recovery history to estimate true capture yield.
- **QQQ/TQQQ & CSP Strategy** → *Admin → Strategies*: rule-based playbooks rather than scanners.

---

> **The app's real edge is confluence:** use **Sector Rotation** (#8) to pick the sector → **Golden Scan Multi-Signal** (#1) or **MTPA PRIME** (#2) to pick the stock → the options tools to choose the instrument.
""")


def render():
    section_header("🔧", "Tech Details",
                   "Summary · Scanner guide · Universe browser · Scanner rankings & action playbook · Stock Analysis methodology")

    (tab_sum1, tab_sum2, tab1, tab2, tab3, tab4, tab5, tab6, tab7) = st.tabs([
        "📋 Summary — Matrix",
        "🏆 Summary — Power Ranking",
        "📊 Scanner Tech & Rankings",
        "📖 Scanner Guide",
        "🗃️ Stock Universe",
        "🔬 Stock Analysis",
        "📺 Trading View",
        "📊 ToS-Chart",
        "📊 MTPA Reference",
    ])

    with tab_sum1:
        _render_summary_matrix()

    with tab_sum2:
        _render_summary_ranking()

    with tab1:
        _render_scanner_tech()

    with tab2:
        _render_guide()

    with tab3:
        _render_universe()

    with tab4:
        _render_stock_analysis_methodology()

    with tab5:
        _render_trading_view()

    with tab6:
        _render_tos_chart()

    with tab7:
        _render_mtpa_reference()
