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
]


# ── Universe builder ───────────────────────────────────────────

def _build_universe_df() -> pd.DataFrame:
    from scanners.deep_analysis import STANDARD_TICKERS
    ticker_map: dict[str, list] = {}

    def _add(tickers, label):
        for t in tickers:
            ticker_map.setdefault(t, [])
            if label not in ticker_map[t]:
                ticker_map[t].append(label)

    _add(SP500_SAMPLE[:200],   "Golden Scan (top 200)")
    _add(SP500_SAMPLE[200:],   "Golden Scan (extended)")
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
    c1, c2, c3 = st.columns(3)
    with c1: st.metric("📡 Scanners Available", str(len(SCANNERS)))
    with c2: st.metric("🗂️ Universe Size", f"{len(SP500_SAMPLE):,} tickers")
    with c3: st.metric("⚡ Options ETFs", f"{len(OPTIONS_ETF_UNIVERSE)} liquid ETFs")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:12px;margin-bottom:12px">'
        f'Click any scanner to expand its default parameters and technical criteria. '
        f'All filters are adjustable via the sidebar at run time.</div>',
        unsafe_allow_html=True,
    )

    groups = {
        "📊 Multi-Factor":       ["Golden Scan"],
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

    # ── Watchlist Analysis reference ────────────────────────────────────
    st.markdown(
        f'<div style="height:1px;background:linear-gradient(90deg,transparent,{GOLD}44,transparent);'
        f'margin:24px 0 20px"></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="color:{GOLD};font-size:13px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:1.2px;margin-bottom:14px">&#10022; Watchlist Analysis — How It Works</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:8px;'
        f'padding:16px 20px;margin-bottom:16px">'
        f'<div style="color:{TEXT_PRIMARY};font-size:13px;line-height:1.8;margin-bottom:12px">'
        f'The <b style="color:{GOLD}">✦ Watchlist Analysis</b> tab (inside Stock Analysis) runs the full '
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
        f'Run Watchlist Analysis each morning → filter by <b style="color:{TEXT_PRIMARY}">BUY + SETUP</b> → '
        f'sort by <b style="color:{TEXT_PRIMARY}">Confidence ↓</b> → '
        f'for SETUP tickers with D-MACD also turning Bull, open the '
        f'<b style="color:{GOLD}">Deep Analysis</b> tab for a full report.</div>',
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
        f'letter-spacing:1.2px;margin-bottom:14px">&#11044; Signal Circle Legend — Watchlist Analysis &amp; Deep Analysis</div>',
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
        f'every row in the Watchlist Analysis table and the Deep Analysis summary table.</div>',
        unsafe_allow_html=True,
    )


# ── Main render ────────────────────────────────────────────────

def render():
    section_header("🔧", "Tech Details",
                   "Scanner guide · Universe browser · Scanner rankings & action playbook · Stock Analysis methodology")

    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Scanner Tech & Rankings",
        "📖 Scanner Guide",
        "🗃️ Stock Universe",
        "🔬 Stock Analysis",
    ])

    with tab1:
        _render_scanner_tech()

    with tab2:
        _render_guide()

    with tab3:
        _render_universe()

    with tab4:
        _render_stock_analysis_methodology()
