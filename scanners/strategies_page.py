"""
scanners/strategies_page.py — Strategies hub
Two tabs: QQQ/TQQQ Strategy · CSP Strategy
"""

import streamlit as st
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    GOLD, GOLD_DARK, BG_CARD, BG_PANEL, BG_DARK,
    ACCENT_GREEN, ACCENT_RED, ACCENT_BLUE,
    TEXT_PRIMARY, TEXT_MUTED, BORDER_COLOR,
)
from utils import section_header

# ── Tab CSS (reuse the green tab style) ───────────────────────────────────────
_TAB_CSS = f"""
<style>
div[data-testid="stTabs"] > div:first-child {{
    gap:0 !important;
    border-bottom:2px solid {ACCENT_GREEN}55 !important;
}}
div[data-testid="stTabs"] > div:first-child > button {{
    flex:1 1 0 !important; justify-content:center !important;
    font-size:14px !important; font-weight:600 !important;
    padding:14px 0 !important; border-radius:0 !important;
    background:transparent !important; color:{TEXT_MUTED} !important;
    border-bottom:3px solid transparent !important;
}}
div[data-testid="stTabs"] > div:first-child > button:hover {{
    background:{ACCENT_GREEN}12 !important; color:{ACCENT_GREEN} !important;
}}
div[data-testid="stTabs"] > div:first-child > button[aria-selected="true"] {{
    background:{ACCENT_GREEN}18 !important; color:{ACCENT_GREEN} !important;
    border-bottom:3px solid {ACCENT_GREEN} !important; font-weight:700 !important;
}}
</style>
"""


# ══════════════════════════════════════════════════════════════════════════════
# CSP STRATEGY TABLE RENDERER
# ══════════════════════════════════════════════════════════════════════════════

def _iv_badge(val, threshold, label):
    """Color badge for IV metrics."""
    if val is None or (isinstance(val, float) and val != val):
        return f'<span style="color:{TEXT_MUTED}">—</span>'
    ok  = val >= threshold
    col = ACCENT_GREEN if ok else TEXT_MUTED
    return (
        f'<span style="background:{col}18;color:{col};border:1px solid {col}44;'
        f'font-size:10px;font-weight:700;padding:1px 7px;border-radius:12px">'
        f'{label} {val:.0f}</span>'
    )


def _rsi_badge(rsi):
    if rsi is None:
        return f'<span style="color:{TEXT_MUTED}">—</span>'
    col = (ACCENT_GREEN if 50 <= rsi <= 65 else
           GOLD if 35 <= rsi < 50 or 65 < rsi <= 68 else ACCENT_RED)
    return (
        f'<span style="color:{col};font-family:\'DM Mono\',monospace;'
        f'font-weight:700">{rsi:.1f}</span>'
    )


def _adx_badge(adx):
    if adx is None:
        return f'<span style="color:{TEXT_MUTED}">—</span>'
    col = (ACCENT_GREEN if adx < 20 else
           GOLD if adx < 30 else ACCENT_RED)
    return (
        f'<span style="color:{col};font-family:\'DM Mono\',monospace;'
        f'font-weight:700">{adx:.1f}</span>'
    )


def _slope_badge(slope):
    col  = ACCENT_GREEN if slope >= 0 else GOLD if slope >= -0.05 else ACCENT_RED
    sign = "+" if slope >= 0 else ""
    return (
        f'<span style="color:{col};font-family:\'DM Mono\',monospace;'
        f'font-size:11px">{sign}{slope:.2f}%</span>'
    )


def _render_csp_table(df: pd.DataFrame):
    G  = ACCENT_GREEN
    GL = GOLD
    BL = ACCENT_BLUE

    # ── Column header groups ───────────────────────────────────────────────────
    header_groups = (
        f'<div style="display:grid;grid-template-columns:'
        f'120px 90px 70px 200px 200px 120px 60px 1fr;'
        f'gap:0;margin-bottom:0">'
        f'<div style="background:{BG_PANEL};padding:5px 12px;font-size:9px;'
        f'color:{TEXT_MUTED};font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.8px;border-bottom:1px solid {GL}33">Ticker</div>'
        f'<div style="background:{BG_PANEL};padding:5px 12px;font-size:9px;'
        f'color:{TEXT_MUTED};font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.8px;border-bottom:1px solid {GL}33">Price</div>'
        f'<div style="background:{BG_PANEL};padding:5px 12px;font-size:9px;'
        f'color:{TEXT_MUTED};font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.8px;border-bottom:1px solid {GL}33">Chg%</div>'
        f'<div style="background:#60A5FA18;padding:5px 12px;font-size:9px;'
        f'color:{BL};font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.8px;border-bottom:2px solid {BL}55">IV Environment</div>'
        f'<div style="background:#22C55E18;padding:5px 12px;font-size:9px;'
        f'color:{G};font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.8px;border-bottom:2px solid {G}55">Trend &amp; Momentum</div>'
        f'<div style="background:#A78BFA18;padding:5px 12px;font-size:9px;'
        f'color:#A78BFA;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.8px;border-bottom:2px solid #A78BFA55">MACD (info)</div>'
        f'<div style="background:{GL}18;padding:5px 12px;font-size:9px;'
        f'color:{GL};font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.8px;border-bottom:2px solid {GL}55">Score</div>'
        f'<div style="background:#F47218;padding:5px 12px;font-size:9px;'
        f'color:#F97316;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.8px;border-bottom:2px solid #F9731655">Flags</div>'
        f'</div>'
    )

    # Column headers (sub-row)
    _HD = (f'background:{BG_PANEL};color:{TEXT_MUTED};font-size:9px;font-weight:600;'
           f'text-transform:uppercase;letter-spacing:0.6px;padding:6px 12px;'
           f'border-bottom:2px solid {GL}22;white-space:nowrap')
    hdr = "".join(
        f'<th style="{_HD};text-align:left">{c}</th>'
        for c in [
            "Ticker", "Price", "Chg%",
            "HV30%", "Vol Rank", "Vol Pctile", "IV Trend",
            "EMA9", "Slope", "RSI", "ADX",
            "Cross", "Hist",
            "Pullback",
            "Score", "Flags",
        ]
    )

    rows_html = ""
    for i, (_, row) in enumerate(df.iterrows()):
        bg  = BG_CARD if i % 2 == 0 else BG_PANEL
        chg = row["Chg%"]
        chg_col = ACCENT_GREEN if chg >= 0 else ACCENT_RED
        sc  = int(row["Score"])
        sc_col = (ACCENT_GREEN if sc >= 7 else
                  GOLD if sc >= 5 else
                  TEXT_MUTED)
        iv_trend_col = ACCENT_GREEN if "Expan" in str(row["IV Trend"]) else ACCENT_RED

        # Vol Rank badge
        vr = row["Vol Rank"]
        vr_col = (ACCENT_GREEN if (not pd.isna(vr) and vr >= 30) else TEXT_MUTED)
        vr_html = (f'<span style="color:{vr_col};font-weight:700">{vr:.0f}</span>'
                   if not pd.isna(vr) else f'<span style="color:{TEXT_MUTED}">—</span>')

        vp = row["Vol Pctile"]
        vp_col = ACCENT_GREEN if (not pd.isna(vp) and vp >= 40) else TEXT_MUTED
        vp_html = (f'<span style="color:{vp_col};font-weight:700">{vp:.0f}</span>'
                   if not pd.isna(vp) else f'<span style="color:{TEXT_MUTED}">—</span>')

        flags = str(row["Flags"])
        flag_col = "#F97316" if flags != "—" else TEXT_MUTED

        rows_html += (
            f'<tr style="background:{bg}">'
            # Ticker
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22;white-space:nowrap">'
            f'<span style="color:{GL};font-family:\'DM Mono\',monospace;font-weight:700;font-size:13px">'
            f'{row["Ticker"]}</span></td>'
            # Price
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22">'
            f'<span style="color:{TEXT_PRIMARY};font-family:\'DM Mono\',monospace">'
            f'${row["Price"]:.2f}</span></td>'
            # Chg%
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22">'
            f'<span style="color:{chg_col};font-family:\'DM Mono\',monospace">'
            f'{chg:+.2f}%</span></td>'
            # IV Environment
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22;'
            f'border-left:1px solid #60A5FA33">'
            f'<span style="color:{ACCENT_BLUE};font-weight:700">'
            f'{row["HV30%"]:.1f}%</span></td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22">'
            f'{vr_html}</td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22">'
            f'{vp_html}</td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22">'
            f'<span style="color:{iv_trend_col};font-size:11px">{row["IV Trend"]}</span></td>'
            # Trend & Momentum
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22;'
            f'border-left:1px solid {ACCENT_GREEN}33">'
            f'<span style="color:{ACCENT_GREEN};font-size:11px">{row["EMA9"]}</span></td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22">'
            f'{_slope_badge(row["EMA9 Slope"])}</td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22">'
            f'{_rsi_badge(row["RSI"])}</td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22">'
            f'{_adx_badge(row["ADX"])}</td>'
            # MACD
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22;'
            f'border-left:1px solid #A78BFA33;font-size:14px;text-align:center">'
            f'{row["MACD Cross"]}</td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22;'
            f'font-size:14px;text-align:center">{row["Hist > 0"]}</td>'
            # Pullback
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22;'
            f'border-left:1px solid #34D39933;white-space:nowrap">'
            f'<span style="color:{"#34D399" if "↘" in str(row.get("Pullback","")) and "low vol" in str(row.get("Pullback","")) else (GOLD if "↘" in str(row.get("Pullback","")) else TEXT_MUTED)};'
            f'font-size:11px">{row.get("Pullback", "—")}</span></td>'
            # Score
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22;'
            f'border-left:1px solid {GL}33;text-align:center">'
            f'<span style="color:{sc_col};font-weight:800;font-size:13px">{sc}</span>'
            f'<span style="color:{TEXT_MUTED};font-size:9px">/11</span></td>'
            # Flags
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22;'
            f'border-left:1px solid #F9731633;font-size:10px;color:{flag_col}">'
            f'{flags}</td>'
            f'</tr>'
        )

    st.markdown(
        f'<div style="overflow-x:auto;border:1px solid {BORDER_COLOR};border-radius:10px">'
        f'<table style="width:100%;border-collapse:collapse;font-family:\'Inter\',sans-serif">'
        f'<thead><tr>{hdr}</tr></thead>'
        f'<tbody>{rows_html}</tbody>'
        f'</table></div>',
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# CSP STRATEGY TAB
# ══════════════════════════════════════════════════════════════════════════════

def _render_csp_strategy():
    from scanners.csp_strategy import scan_csp_strategy, default_universe
    from config import SP500_SAMPLE, OPTIONS_ETF_UNIVERSE

    st.markdown(
        f'<div style="background:linear-gradient(135deg,{BG_CARD},{BG_PANEL});'
        f'border:1px solid {GOLD}44;border-radius:12px;padding:18px 24px;margin-bottom:16px">'
        f'<div style="color:{GOLD};font-size:15px;font-weight:700;margin-bottom:6px">'
        f'💰 CSP Strategy Screener</div>'
        f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.7">'
        f'Filters stocks for optimal Cash-Secured Put entry — no options data needed. '
        f'IV metrics use <b>realized-volatility history</b> (HV30) as a proxy. '
        f'Sort: highest-conviction setups first (Score /10).</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Filter legend ──────────────────────────────────────────────────────────
    with st.expander("📋 Filter Logic & Strategy Guide", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Hard filters (stock excluded if fails)**")
            st.markdown(
                "- Avg Volume > 300K\n"
                "- Beta < 1.5\n"
                "- Price > EMA9\n"
                "- EMA9 slope flat or rising (≥ −0.05%)\n"
                "- RSI 35–68\n"
                "- No single-day move > 7% in last 20 sessions\n"
                "- Price within 7% of 20-day high\n\n"
                "**Score /10** — sum of 10 positive conditions:\n"
                "1. SPY > EMA20 (market gate)\n"
                "2. Vol Rank ≥ 40 (elevated premium)\n"
                "3. Vol Pctile ≥ 45 (historically rich vol)\n"
                "4. Price > EMA9\n"
                "5. EMA9 slope ≥ 0\n"
                "6. RSI 50–68\n"
                "7. MACD line > signal\n"
                "8. MACD histogram > 0\n"
                "9. Pullback in uptrend (dip on low vol)\n"
                "10. IV contracting **AND** ADX ≥ 25 (combined)"
            )
        with c2:
            st.markdown("**Column guide**")
            st.markdown(
                "- **HV30%** — 30-day realized vol annualized (IV proxy). Higher = richer premium available\n"
                "- **Vol Rank** — where HV30 sits in its 52-week range (0–100). ≥ 40 = elevated\n"
                "- **Vol Pctile** — % of past year where vol was *lower* than today. ≥ 45 = historically rich\n"
                "- **IV Trend** — HV30 vs HV60. **Contracting ↓** = IV falling (ideal for put sellers — IV crush works for you). Expanding ↑ = IV rising\n"
                "- **EMA9 Slope** — 3-day % rate of change. Near 0 = consolidating (good CSP entry). Steeply positive = chasing\n"
                "- **RSI** — 45–60 sweet spot for CSP. > 62 flagged as elevated\n"
                "- **ADX** — trend strength. ≥ 25 = strong confirmed uptrend. < 20 = flagged as weak\n"
                "- **MACD Cross / Hist** — informational momentum confirmation. Both ✅ = clean trend\n"
                "- **Pullback** — ↘ X% · low vol = quiet dip in uptrend (+1 bonus). 'Uptrend · flat/rising' = trend intact but no dip yet — wait\n"
                "- **Flags** — passed all hard filters but worth noting (high beta, weak ADX, expanding vol, etc.)\n"
                "- **Score** — ≥ 8 = high conviction, 6–7 = moderate, < 6 = speculative"
            )

        st.markdown("---")
        st.markdown("**When to sell a CSP vs buy a LEAP on stocks from this list**")
        tip1, tip2 = st.columns(2)
        with tip1:
            st.markdown(
                "**💰 Sell a CSP when:**\n"
                "- IV Trend = **Contracting ↓** — IV falling after you sell means IV crush profits the seller\n"
                "- Vol Rank ≥ 40 and Vol Pctile ≥ 45 — premium is rich relative to history\n"
                "- ADX ≥ 25 — confirmed uptrend; direction is your friend\n"
                "- Pullback column shows **↘ % · low vol** — quiet dip = better strike, lower breakeven\n"
                "- RSI 45–62 — healthy momentum, not overbought\n"
                "- Score ≥ 7/10, SPY gate ✅\n\n"
                "*Sell an OTM put (delta 0.15–0.30), collect premium, let IV crush + time decay work. "
                "Close at 50% profit or before earnings.*"
            )
        with tip2:
            st.markdown(
                "**🚀 Buy a LEAP instead when:**\n"
                "- IV Trend = **Expanding ↑** OR Vol Rank < 30 — IV still low, buy before it rises\n"
                "- Stock just broke out of consolidation or confirmed a new uptrend\n"
                "- ADX ≥ 25 **and** MACD Cross ✅ **and** Hist > 0 ✅ — strong directional momentum\n"
                "- RSI 55–68 — strong move underway, not yet extended\n"
                "- Multi-month bullish thesis (earnings catalyst, sector rotation, breakout)\n"
                "- Score ≥ 8/10 with all trend signals aligned\n\n"
                "*Buy a deep ITM call (delta 0.70–0.85, 6–12 month expiry) for leveraged upside "
                "with defined risk and no assignment obligation.*"
            )
        st.markdown(
            "> **Key rule:** High IV + Falling → **Sell** (CSP). &nbsp; Low IV + Rising → **Buy** (LEAP). "
            "A stock with Vol Rank ≥ 40 and IV Trend = Contracting ↓ is a CSP candidate. "
            "The same stock a month earlier — Vol Rank < 30, IV Trend = Expanding ↑ — was a LEAP candidate.",
            unsafe_allow_html=False,
        )

    # ── Controls ───────────────────────────────────────────────────────────────
    ctrl_col, uni_col, run_col = st.columns([2, 2, 1])
    with ctrl_col:
        max_tickers = st.slider("Universe size", 30, 250, 100, 10,
                                key="csp_strat_n",
                                help="Number of top SP500 + ETF tickers to screen")
    with uni_col:
        include_etf = st.checkbox("Include options ETFs", value=True, key="csp_strat_etf")
    with run_col:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        run_btn = st.button("▶ Run Screener", type="primary",
                            use_container_width=True, key="csp_strat_run")

    if run_btn:
        universe = list(dict.fromkeys(
            SP500_SAMPLE[:max_tickers] +
            (OPTIONS_ETF_UNIVERSE if include_etf else [])
        ))

        prog_ph  = st.progress(0, text="Starting…")
        stat_ph  = st.empty()

        def _status(i, n, tk):
            prog_ph.progress((i + 1) / n, text=f"Scanning {tk} ({i+1}/{n})")
            stat_ph.markdown(
                f'<div style="color:{TEXT_MUTED};font-size:11px">🔍 {tk}</div>',
                unsafe_allow_html=True,
            )

        df_out, spy_ok, spy_note = scan_csp_strategy(universe, status_fn=_status)

        prog_ph.empty()
        stat_ph.empty()

        st.session_state["csp_strat_df"]      = df_out
        st.session_state["csp_strat_spy_ok"]  = spy_ok
        st.session_state["csp_strat_spy_note"]= spy_note
        st.session_state["csp_strat_ts"]      = pd.Timestamp.now().strftime("%b %d %Y  %I:%M %p")
        st.rerun()

    # ── Results ────────────────────────────────────────────────────────────────
    if "csp_strat_df" not in st.session_state:
        st.markdown(
            f'<div style="border:1px dashed {BORDER_COLOR};border-radius:10px;'
            f'padding:40px;text-align:center;color:{TEXT_MUTED};margin-top:12px">'
            f'Press <b style="color:{GOLD}">▶ Run Screener</b> to scan stocks</div>',
            unsafe_allow_html=True,
        )
        return

    df_out   = st.session_state["csp_strat_df"]
    spy_ok   = st.session_state["csp_strat_spy_ok"]
    spy_note = st.session_state["csp_strat_spy_note"]
    ts       = st.session_state.get("csp_strat_ts", "")

    # SPY gate banner
    if spy_ok:
        st.success(f"✅ {spy_note}")
    else:
        st.warning(f"{spy_note} — Proceed with smaller size / tighter strikes")

    if df_out.empty:
        st.info("No stocks passed all filters. Try a larger universe or check market conditions.")
        return

    # Summary strip
    n_hi = int((df_out["Score"] >= 8).sum())
    n_md = int(((df_out["Score"] >= 6) & (df_out["Score"] < 8)).sum())
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:20px;flex-wrap:wrap;'
        f'background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:8px;'
        f'padding:10px 16px;margin:10px 0">'
        f'<span style="color:{TEXT_MUTED};font-size:11px">Found '
        f'<b style="color:{GOLD}">{len(df_out)}</b> stocks passing all filters</span>'
        f'<span style="color:{ACCENT_GREEN};font-size:11px;font-weight:600">'
        f'⭐ {n_hi} high conviction (≥8/10)</span>'
        f'<span style="color:{GOLD};font-size:11px;font-weight:600">'
        f'🟡 {n_md} moderate (6–7/10)</span>'
        f'<span style="color:{TEXT_MUTED};font-size:10px;margin-left:auto">'
        f'Scanned {ts}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Column legend
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:10px;line-height:1.8;'
        f'margin-bottom:8px">'
        f'<b style="color:{ACCENT_BLUE}">IV Environment</b>: HV30% = 30-day realized vol (proxy for IV) · '
        f'Vol Rank ≥ 40 = premium elevated · Vol Pctile ≥ 45 = historically rich &nbsp;|&nbsp; '
        f'<b style="color:{ACCENT_GREEN}">Trend</b>: EMA9 · Slope (3-day %) · RSI · ADX &nbsp;|&nbsp; '
        f'<b style="color:#A78BFA">MACD</b>: informational only — not a filter &nbsp;|&nbsp; '
        f'<b style="color:#34D399">Pullback</b>: ↘ % · low vol = +1 bonus (uptrend dip on quiet volume)</div>',
        unsafe_allow_html=True,
    )

    _render_csp_table(df_out)

    # Download
    st.download_button(
        "⬇ Export CSV", df_out.to_csv(index=False),
        "csp_strategy_scan.csv", "text/csv",
        use_container_width=False, key="csp_strat_dl",
    )


# ══════════════════════════════════════════════════════════════════════════════
# MAIN RENDER
# ══════════════════════════════════════════════════════════════════════════════

def render():
    section_header("♟️", "Strategies",
                   "QQQ / TQQQ weight-of-evidence · CSP stock screener")

    st.markdown(_TAB_CSS, unsafe_allow_html=True)

    tab_qqq, tab_csp = st.tabs([
        "♟️  QQQ / TQQQ Strategy",
        "💰  CSP Strategy",
    ])

    with tab_qqq:
        from scanners.qqq_strategy_page import render as _qqq_render
        # Strip the section_header call since we already have one above
        _qqq_render(_skip_header=True)

    with tab_csp:
        _render_csp_strategy()
