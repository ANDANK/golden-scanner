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
# OPTIONS STRATEGY TABLE RENDERER
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
    col = (ACCENT_GREEN if adx >= 25 else
           GOLD if adx >= 20 else TEXT_MUTED)
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


def _suggest_badge(suggest: str) -> str:
    if suggest == "CSP":
        col, bg = GOLD, f"{GOLD}18"
        icon = "💰"
    elif suggest == "LEAP":
        col, bg = ACCENT_BLUE, f"{ACCENT_BLUE}18"
        icon = "🚀"
    else:
        col, bg = TEXT_MUTED, f"{TEXT_MUTED}12"
        icon = "👀"
    return (
        f'<span style="background:{bg};color:{col};border:1px solid {col}44;'
        f'font-size:10px;font-weight:700;padding:2px 9px;border-radius:12px;'
        f'white-space:nowrap">{icon} {suggest}</span>'
    )


def _render_options_table(df: pd.DataFrame):
    G  = ACCENT_GREEN
    GL = GOLD
    BL = ACCENT_BLUE

    # ── Column header groups ───────────────────────────────────────────────────
    _GH = "padding:5px 12px;font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px"
    header_groups = (
        f'<div style="display:grid;grid-template-columns:'
        f'120px 90px 70px 200px 250px 120px 130px 90px 60px 1fr;'
        f'gap:0;margin-bottom:0">'
        f'<div style="background:{BG_PANEL};{_GH};color:{TEXT_MUTED};border-bottom:1px solid {GL}33">Ticker</div>'
        f'<div style="background:{BG_PANEL};{_GH};color:{TEXT_MUTED};border-bottom:1px solid {GL}33">Price</div>'
        f'<div style="background:{BG_PANEL};{_GH};color:{TEXT_MUTED};border-bottom:1px solid {GL}33">Chg%</div>'
        f'<div style="background:{BL}12;{_GH};color:{BL};border-bottom:2px solid {BL}55">IV Environment</div>'
        f'<div style="background:{G}12;{_GH};color:{G};border-bottom:2px solid {G}55">Trend &amp; Momentum</div>'
        f'<div style="background:#A78BFA18;{_GH};color:#A78BFA;border-bottom:2px solid #A78BFA55">MACD (info)</div>'
        f'<div style="background:#34D39918;{_GH};color:#34D399;border-bottom:2px solid #34D39955">Pullback</div>'
        f'<div style="background:{GL}18;{_GH};color:{GL};border-bottom:2px solid {GL}55">Signal</div>'
        f'<div style="background:{GL}18;{_GH};color:{GL};border-bottom:2px solid {GL}55">Score</div>'
        f'<div style="background:#F9731612;{_GH};color:#F97316;border-bottom:2px solid #F9731655">Flags</div>'
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
            "EMA9", "Slope", "RSI", "ADX", "SMA200",
            "Cross", "Hist",
            "Pullback",
            "Suggest",
            "Score", "Flags",
        ]
    )

    rows_html = ""
    for i, (_, row) in enumerate(df.iterrows()):
        bg      = BG_CARD if i % 2 == 0 else BG_PANEL
        chg     = row["Chg%"]
        chg_col = ACCENT_GREEN if chg >= 0 else ACCENT_RED
        sc      = int(row["Score"])
        sc_col  = ACCENT_GREEN if sc >= 7 else GOLD if sc >= 5 else TEXT_MUTED

        # IV Trend: gold = contracting (good for CSP sellers), blue = expanding (good for LEAP buyers)
        iv_trend_str = str(row["IV Trend"])
        iv_trend_col = GOLD if "Contrac" in iv_trend_str else ACCENT_BLUE

        # Vol Rank / Vol Pctile — green if elevated enough for premium selling
        vr = row["Vol Rank"]
        vr_col  = ACCENT_GREEN if (not pd.isna(vr) and vr >= 40) else TEXT_MUTED
        vr_html = (f'<span style="color:{vr_col};font-weight:700">{vr:.0f}</span>'
                   if not pd.isna(vr) else f'<span style="color:{TEXT_MUTED}">—</span>')

        vp = row["Vol Pctile"]
        vp_col  = ACCENT_GREEN if (not pd.isna(vp) and vp >= 45) else TEXT_MUTED
        vp_html = (f'<span style="color:{vp_col};font-weight:700">{vp:.0f}</span>'
                   if not pd.isna(vp) else f'<span style="color:{TEXT_MUTED}">—</span>')

        # SMA200
        sma200_raw = row.get("SMA200", None)
        price_v    = row["Price"]
        if sma200_raw is not None and not pd.isna(sma200_raw):
            above_200  = price_v > float(sma200_raw)
            s200_col   = ACCENT_GREEN if above_200 else ACCENT_RED
            s200_html  = (f'<span style="color:{s200_col};font-size:10px">'
                          f'{"✅" if above_200 else "❌"} ${float(sma200_raw):.0f}</span>')
        else:
            s200_html = f'<span style="color:{TEXT_MUTED}">—</span>'

        flags    = str(row["Flags"])
        flag_col = "#F97316" if flags != "—" else TEXT_MUTED
        suggest  = str(row.get("Suggest", "Watch"))
        pb_str   = str(row.get("Pullback", "—"))
        pb_col   = ("#34D399" if "↘" in pb_str and "low vol" in pb_str
                    else GOLD if "↘" in pb_str else TEXT_MUTED)

        rows_html += (
            f'<tr style="background:{bg}">'
            # Ticker
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22;white-space:nowrap">'
            f'<span style="color:{GL};font-family:\'DM Mono\',monospace;font-weight:700;font-size:13px">'
            f'{row["Ticker"]}</span></td>'
            # Price
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22">'
            f'<span style="color:{TEXT_PRIMARY};font-family:\'DM Mono\',monospace">'
            f'${price_v:.2f}</span></td>'
            # Chg%
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22">'
            f'<span style="color:{chg_col};font-family:\'DM Mono\',monospace">'
            f'{chg:+.2f}%</span></td>'
            # IV Environment
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22;border-left:1px solid {BL}33">'
            f'<span style="color:{ACCENT_BLUE};font-weight:700">{row["HV30%"]:.1f}%</span></td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22">{vr_html}</td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22">{vp_html}</td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22">'
            f'<span style="color:{iv_trend_col};font-size:11px">{iv_trend_str}</span></td>'
            # Trend & Momentum
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22;border-left:1px solid {G}33">'
            f'<span style="color:{G};font-size:11px">{row["EMA9"]}</span></td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22">'
            f'{_slope_badge(row["EMA9 Slope"])}</td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22">'
            f'{_rsi_badge(row["RSI"])}</td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22">'
            f'{_adx_badge(row["ADX"])}</td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22">{s200_html}</td>'
            # MACD
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22;'
            f'border-left:1px solid #A78BFA33;font-size:14px;text-align:center">{row["MACD Cross"]}</td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22;'
            f'font-size:14px;text-align:center">{row["Hist > 0"]}</td>'
            # Pullback
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22;'
            f'border-left:1px solid #34D39933;white-space:nowrap">'
            f'<span style="color:{pb_col};font-size:11px">{pb_str}</span></td>'
            # Suggest
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22;'
            f'border-left:1px solid {GL}33;text-align:center">'
            f'{_suggest_badge(suggest)}</td>'
            # Score
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22;text-align:center">'
            f'<span style="color:{sc_col};font-weight:800;font-size:13px">{sc}</span>'
            f'<span style="color:{TEXT_MUTED};font-size:9px">/10</span></td>'
            # Flags
            f'<td style="padding:8px 12px;border-bottom:1px solid {BORDER_COLOR}22;'
            f'border-left:1px solid #F9731633;font-size:10px;color:{flag_col}">{flags}</td>'
            f'</tr>'
        )

    st.markdown(
        f'<div style="overflow-x:auto;border:1px solid {BORDER_COLOR};border-radius:10px">'
        f'<table style="width:100%;border-collapse:collapse;font-family:\'Inter\',sans-serif">'
        f'<thead>{header_groups}<tr>{hdr}</tr></thead>'
        f'<tbody>{rows_html}</tbody>'
        f'</table></div>',
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# OPTIONS STRATEGY TAB
# ══════════════════════════════════════════════════════════════════════════════

def _render_options_strategy():
    from scanners.csp_strategy import scan_csp_strategy, default_universe
    from config import SP500_SAMPLE, OPTIONS_ETF_UNIVERSE

    st.markdown(
        f'<div style="background:linear-gradient(135deg,{BG_CARD},{BG_PANEL});'
        f'border:1px solid {GOLD}44;border-radius:12px;padding:18px 24px;margin-bottom:16px">'
        f'<div style="color:{GOLD};font-size:15px;font-weight:700;margin-bottom:6px">'
        f'💰 Options Strategy Screener</div>'
        f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.7">'
        f'Screens stocks for <b>CSP</b> (sell put — high/falling IV) or <b>LEAP</b> (buy call — low/rising IV) entry. '
        f'No options chain needed — IV proxied from realized-volatility history (HV30). '
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
                "**💰 CSP Score /10** — scored when Suggest = CSP or Watch:\n"
                "1. SPY > EMA20\n"
                "2. Vol Rank ≥ 40\n"
                "3. Vol Pctile ≥ 45\n"
                "4. Price > EMA9\n"
                "5. EMA9 slope ≥ 0\n"
                "6. RSI 50–68\n"
                "7. MACD cross\n"
                "8. MACD hist > 0\n"
                "9. Pullback on low vol (+1 bonus)\n"
                "10. IV contracting AND ADX ≥ 25\n\n"
                "**🚀 LEAP Score /10** — scored when Suggest = LEAP:\n"
                "1. SPY > EMA20\n"
                "2. IV Trend = Expanding ↑\n"
                "3. Vol Rank < 30 (IV cheap)\n"
                "4. Price > SMA200\n"
                "5. Price > EMA9\n"
                "6. EMA9 slope ≥ 0\n"
                "7. RSI 55–68\n"
                "8. ADX ≥ 25\n"
                "9. MACD cross\n"
                "10. MACD hist > 0"
            )
        with c2:
            st.markdown("**Column guide**")
            st.markdown(
                "- **HV30%** — 30-day realized vol annualized (IV proxy). Higher = richer premium\n"
                "- **Vol Rank** — HV30 within its 52-week range (0–100). ≥ 40 = elevated (gold)\n"
                "- **Vol Pctile** — % of past year where vol was lower. ≥ 45 = historically rich\n"
                "- **IV Trend** — HV30 vs HV60. **Contracting ↓** (gold) = falling IV → ideal for CSP sellers. **Expanding ↑** (blue) = rising IV → ideal for LEAP buyers\n"
                "- **ADX** — trend strength. ≥ 25 (green) = confirmed uptrend. < 20 = trend too weak\n"
                "- **SMA200** — ✅ = price above 200-day MA (long-term uptrend intact — key for LEAPs)\n"
                "- **RSI** — 45–60 sweet spot. > 62 flagged elevated\n"
                "- **EMA9 Slope** — 3-day % change. Near 0 = consolidating (good CSP entry). Steep = chasing\n"
                "- **MACD Cross / Hist** — momentum confirmation. Both ✅ + ADX ≥ 25 = strong LEAP signal\n"
                "- **Pullback** — ↘ X% · low vol = quiet dip in uptrend (+1 score bonus) → ideal CSP entry timing\n"
                "- **Suggest** — 💰 CSP = sell put (high+falling IV). 🚀 LEAP = buy call (low/rising IV + momentum). 👀 Watch = wait\n"
                "- **Score** — ≥ 8 = high conviction, 6–7 = moderate, < 6 = speculative"
            )

        st.markdown("---")
        st.markdown("**💰 CSP vs 🚀 LEAP — when to use each**")
        tip1, tip2 = st.columns(2)
        with tip1:
            st.markdown(
                "**💰 Sell a CSP when:**\n"
                "- IV Trend = **Contracting ↓** — IV crush profits the seller after entry\n"
                "- Vol Rank ≥ 40 and Vol Pctile ≥ 45 — premium rich relative to history\n"
                "- ADX ≥ 25 — strong uptrend confirmed\n"
                "- Pullback column shows **↘ % · low vol** — quiet dip = better entry price\n"
                "- RSI 45–62 — healthy momentum, not overbought\n"
                "- Score ≥ 7/10, SPY gate ✅\n\n"
                "*Sell OTM put (delta 0.15–0.30), collect premium, close at 50% profit or before earnings.*"
            )
        with tip2:
            st.markdown(
                "**🚀 Buy a LEAP when:**\n"
                "- IV Trend = **Expanding ↑** OR Vol Rank < 30 — buy cheap before IV rises\n"
                "- Price above **SMA200** ✅ — long-term trend intact\n"
                "- ADX ≥ 25 **and** MACD Cross ✅ **and** Hist > 0 ✅ — strong momentum\n"
                "- RSI 55–68 — strong move underway, not yet extended\n"
                "- Multi-month thesis: earnings catalyst, breakout, sector rotation\n"
                "- Score ≥ 8/10 with all trend signals aligned\n\n"
                "*Buy deep ITM call (delta 0.70–0.85, 6–12 month expiry) — leveraged upside, defined risk, no assignment.*"
            )
        st.markdown(
            "> **Key rule:** High IV + Falling → **Sell** (CSP — pocket IV crush). "
            "Low IV + Rising → **Buy** (LEAP — ride IV expansion + price move). "
            "The **Suggest** column applies this automatically per row.",
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

        df_out, spy_ok, spy_note, ftf_rows = scan_csp_strategy(universe, status_fn=_status)

        prog_ph.empty()
        stat_ph.empty()

        st.session_state["csp_strat_df"]       = df_out
        st.session_state["csp_strat_spy_ok"]   = spy_ok
        st.session_state["csp_strat_spy_note"]  = spy_note
        st.session_state["csp_strat_ts"]        = pd.Timestamp.now().strftime("%b %d %Y  %I:%M %p")
        # FTF computed inline inside scan_csp_strategy — no separate scan pass
        st.session_state["csp_strat_ftf"]       = ftf_rows

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

    # ── First Things First ─────────────────────────────────────────────────────
    from scanners.mtpa_page import render_ftf_section
    render_ftf_section(st.session_state.get("csp_strat_ftf", []), context="csp")

    if df_out.empty:
        st.info("No stocks passed all filters. Try a larger universe or check market conditions.")
        return

    # Summary strip
    n_csp   = int((df_out.get("Suggest", "") == "CSP").sum())  if "Suggest" in df_out.columns else 0
    n_leap  = int((df_out.get("Suggest", "") == "LEAP").sum()) if "Suggest" in df_out.columns else 0
    n_watch = int((df_out.get("Suggest", "") == "Watch").sum())if "Suggest" in df_out.columns else 0
    n_hi    = int((df_out["Score"] >= 8).sum())
    n_md    = int(((df_out["Score"] >= 6) & (df_out["Score"] < 8)).sum())
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:20px;flex-wrap:wrap;'
        f'background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:8px;'
        f'padding:10px 16px;margin:10px 0">'
        f'<span style="color:{TEXT_MUTED};font-size:11px">Found '
        f'<b style="color:{GOLD}">{len(df_out)}</b> stocks</span>'
        f'<span style="color:{GOLD};font-size:11px;font-weight:600">💰 {n_csp} CSP</span>'
        f'<span style="color:{ACCENT_BLUE};font-size:11px;font-weight:600">🚀 {n_leap} LEAP</span>'
        f'<span style="color:{TEXT_MUTED};font-size:11px">👀 {n_watch} Watch</span>'
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
        f'<div style="color:{TEXT_MUTED};font-size:10px;line-height:1.8;margin-bottom:8px">'
        f'<b style="color:{ACCENT_BLUE}">IV Env</b>: Vol Rank ≥ 40 · Vol Pctile ≥ 45 = elevated premium &nbsp;|&nbsp; '
        f'<b style="color:{GOLD}">Contracting ↓</b> = IV falling (CSP) · '
        f'<b style="color:{ACCENT_BLUE}">Expanding ↑</b> = IV rising (LEAP) &nbsp;|&nbsp; '
        f'<b style="color:{ACCENT_GREEN}">Trend</b>: ADX ≥ 25 = confirmed · SMA200 ✅ = long-term trend &nbsp;|&nbsp; '
        f'<b style="color:#34D399">Pullback</b>: ↘ % · low vol = ideal CSP entry (+1 bonus) &nbsp;|&nbsp; '
        f'<b style="color:{GOLD}">Suggest</b>: 💰 CSP · 🚀 LEAP · 👀 Watch &nbsp;|&nbsp; '
        f'<b style="color:{GOLD}">Score /10</b>: CSP criteria for CSP/Watch rows · LEAP criteria for LEAP rows</div>',
        unsafe_allow_html=True,
    )

    _render_options_table(df_out)

    # ── Export row ────────────────────────────────────────────────────────────
    dl_col, gs_col, _ = st.columns([1, 1, 4])
    with dl_col:
        st.download_button(
            "⬇ Export CSV", df_out.to_csv(index=False),
            "options_strategy_scan.csv", "text/csv",
            use_container_width=True, key="csp_strat_dl",
        )
    with gs_col:
        from scanners.gsheet_helper import export_options_scan, gsheets_configured
        if gsheets_configured():
            if st.button("📤 Export to Google Sheets", use_container_width=True,
                         key="csp_strat_gs"):
                with st.spinner("Exporting to Google Sheets…"):
                    ok, msg = export_options_scan(
                        df_out,
                        spy_note=spy_note,
                    )
                if ok:
                    st.success(f"✅ {msg}")
                else:
                    st.error(f"❌ {msg}")
        else:
            st.button("📤 Export to Google Sheets", disabled=True,
                      help="Google Sheets not configured — add credentials in Streamlit Secrets",
                      use_container_width=True, key="csp_strat_gs_dis")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN RENDER
# ══════════════════════════════════════════════════════════════════════════════

# ── FTF extra ETFs not already in SP500_SAMPLE ────────────────────────────────
_FTF_EXTRA_ETFS = [
    "XLC", "NVDL", "3TSL",                    # comms sector + single-stock 3x
]


def _render_ftf_tab():
    """Standalone First Things First scanner — full SP500 + quality ETFs."""
    from config import FTF_UNIVERSE
    from scanners.first_things_first import run_ftf_scan
    from scanners.mtpa_page import render_ftf_section

    G  = ACCENT_GREEN
    GL = GOLD

    universe = FTF_UNIVERSE

    # ── Info banner ────────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="background:linear-gradient(135deg,{GL}10,{G}08);'
        f'border:1px solid {GL}44;border-radius:12px;padding:16px 22px;margin-bottom:14px">'
        f'<div style="color:{GL};font-size:14px;font-weight:700;margin-bottom:4px">'
        f'🎯 First Things First — Full Universe Scan</div>'
        f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.7">'
        f'Scans <b style="color:#fff">{len(universe)} tickers</b> '
        f'(full S&P 500 · liquid ETFs · sector ETFs · 3× leveraged ETFs) for stocks passing all '
        f'<b style="color:#fff">12 conditions</b> simultaneously across weekly + daily timeframes. '
        f'Expect a 5–8 minute runtime. Best run <b style="color:{GL}">30–60 min after market open</b> '
        f'when volume and histogram direction are established.</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Controls ───────────────────────────────────────────────────────────────
    run_col, clear_col, _ = st.columns([1, 1, 4])
    with run_col:
        run_btn = st.button("▶ Run FTF Scan", type="primary",
                            use_container_width=True, key="ftf_strat_run")
    with clear_col:
        if st.button("🔄 Clear", use_container_width=True, key="ftf_strat_clear"):
            st.session_state.pop("ftf_strat_rows", None)
            st.session_state.pop("ftf_strat_ts", None)
            st.rerun()

    if st.session_state.get("ftf_strat_ts"):
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:11px;margin-top:2px">'
            f'Last scan: {st.session_state["ftf_strat_ts"]}</div>',
            unsafe_allow_html=True,
        )

    # ── Run ────────────────────────────────────────────────────────────────────
    if run_btn:
        prog = st.progress(0, text="Starting FTF scan…")
        stat = st.empty()

        def _status(i, n, tk):
            prog.progress((i + 1) / n, text=f"Scanning {tk} ({i+1}/{n})")
            stat.markdown(
                f'<div style="color:{TEXT_MUTED};font-size:11px">🔍 {tk}</div>',
                unsafe_allow_html=True,
            )

        rows, diag = run_ftf_scan(universe, status_fn=_status)
        prog.empty(); stat.empty()

        st.session_state["ftf_strat_rows"] = rows
        st.session_state["ftf_strat_diag"] = diag
        st.session_state["ftf_strat_ts"]   = pd.Timestamp.now().strftime("%b %d %Y  %I:%M %p")
        st.rerun()

    # ── Results ────────────────────────────────────────────────────────────────
    if "ftf_strat_rows" not in st.session_state:
        st.markdown(
            f'<div style="border:1px dashed {BORDER_COLOR};border-radius:10px;'
            f'padding:40px;text-align:center;color:{TEXT_MUTED};margin-top:12px">'
            f'Press <b style="color:{GL}">▶ Run FTF Scan</b> to scan <b style="color:#fff">{len(universe)}</b> tickers'
            f'</div>',
            unsafe_allow_html=True,
        )
        return

    # ── Diagnostic funnel ─────────────────────────────────────────────────────
    diag = st.session_state.get("ftf_strat_diag", {})
    if diag:
        total  = diag.get("total", 0)
        dok    = diag.get("data_ok", total)
        wpass  = diag.get("weekly_pass", 0)
        dpass  = diag.get("daily_pass", 0)
        w_fails = diag.get("w_fails", {})
        d_fails = diag.get("d_fails", {})

        # Funnel chips
        st.markdown(
            f'<div style="display:flex;gap:10px;margin-bottom:8px;flex-wrap:wrap;align-items:center">'
            f'<span style="background:{TEXT_MUTED}18;color:{TEXT_MUTED};border:1px solid {TEXT_MUTED}33;'
            f'font-size:11px;font-weight:700;padding:4px 14px;border-radius:20px">🔎 Scanned {total}</span>'
            f'<span style="background:{TEXT_MUTED}18;color:{TEXT_MUTED};border:1px solid {TEXT_MUTED}33;'
            f'font-size:11px;font-weight:700;padding:4px 14px;border-radius:20px">📥 Data OK {dok}</span>'
            f'<span style="background:{GOLD}18;color:{GOLD};border:1px solid {GOLD}33;'
            f'font-size:11px;font-weight:700;padding:4px 14px;border-radius:20px">📅 Weekly pass {wpass}</span>'
            f'<span style="background:{ACCENT_GREEN}18;color:{ACCENT_GREEN};border:1px solid {ACCENT_GREEN}33;'
            f'font-size:11px;font-weight:700;padding:4px 14px;border-radius:20px">✅ Final pass {dpass}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # ── Always-visible breakdown (weekly + daily) ─────────────────────────
        w_errors = diag.get("w_errors", {})

        def _breakdown_table(fails: dict, labels: dict, n: int, color: str) -> str:
            if not fails or n == 0:
                return ""
            rows = "".join(
                f'<tr>'
                f'<td style="padding:5px 10px;color:{color};font-family:monospace;'
                f'font-weight:700;white-space:nowrap">{k}</td>'
                f'<td style="padding:5px 10px;color:#ddd;font-size:11px">{labels.get(k, k)}</td>'
                f'<td style="padding:5px 10px;font-weight:700;font-size:11px;white-space:nowrap;'
                f'color:{"#EF4444" if v > n*0.7 else ("#FBBF24" if v > n*0.3 else "#22C55E")}">'
                f'{v}/{n} ({v*100//n}%)</td>'
                f'</tr>'
                for k, v in sorted(fails.items(), key=lambda x: -x[1])
            )
            return (
                f'<table style="width:100%;border-collapse:collapse;font-size:11px">'
                f'<thead><tr>'
                f'<th style="padding:4px 10px;color:{TEXT_MUTED};text-align:left;font-size:10px">Cond</th>'
                f'<th style="padding:4px 10px;color:{TEXT_MUTED};text-align:left;font-size:10px">Description</th>'
                f'<th style="padding:4px 10px;color:{TEXT_MUTED};text-align:left;font-size:10px">Fail Rate ↓</th>'
                f'</tr></thead><tbody>{rows}</tbody></table>'
            )

        w_labels = {"W2":"Not Extended ≤15% above SMA20W","W3":"RSI 35–75 (weekly)",
                    "W4":"MACD > Signal (weekly)",
                    "W6":"Price > SMA20W","W9":"Uptrend (P>SMA50W or HH/HL)"}
        d_labels = {"D1":"Not Extended ≤8% above EMA9","D2":"RSI 35–70 (daily)",
                    "D3":"MACD > Signal (daily)","D4":"Price > EMA9",
                    "D6":"Volume > 20-day avg","X1":"ADX > 16","X2":"No Bearish Divergence"}

        with st.expander("🔬 Condition breakdown (always visible — expand for details)", expanded=(dpass == 0)):
            # Errors if any
            if w_errors:
                err_html = "".join(
                    f'<div style="color:{ACCENT_RED};font-size:10px;font-family:monospace;padding:1px 0">'
                    f'{t}: {e}</div>' for t, e in list(w_errors.items())[:5]
                )
                st.markdown(
                    f'<div style="background:{ACCENT_RED}0D;border:1px solid {ACCENT_RED}33;'
                    f'border-radius:6px;padding:8px 12px;margin-bottom:10px">'
                    f'<b style="color:{ACCENT_RED};font-size:11px">🐛 Exceptions in weekly check:</b><br>'
                    f'{err_html}</div>', unsafe_allow_html=True,
                )

            # Show weekly passers detail
            weekly_passers = diag.get("weekly_passers", [])
            if weekly_passers:
                rows_wp = "".join(
                    f'<tr>'
                    f'<td style="padding:4px 10px;color:{GOLD};font-family:monospace;font-weight:700">{p["ticker"]}</td>'
                    f'<td style="padding:4px 10px;color:#ddd">${p["price"]}</td>'
                    f'<td style="padding:4px 10px;color:#ddd">W-RSI {p["w_detail"].get("rsi_w","?")} · '
                    f'MACD {p["w_detail"].get("macd_w","?"):.4f}</td>'
                    f'<td style="padding:4px 10px;color:{ACCENT_RED};font-size:10px">'
                    f'Daily fail: {", ".join(p.get("d_flags_fail", []))}</td>'
                    f'</tr>'
                    for p in weekly_passers[:20]
                )
                st.markdown(
                    f'<div style="color:{GOLD};font-size:11px;font-weight:700;margin-bottom:4px">'
                    f'⭐ Weekly passers ({len(weekly_passers)}) — why they failed daily:</div>'
                    f'<div style="background:#0f172a;border-radius:6px;padding:4px;overflow-x:auto;margin-bottom:10px">'
                    f'<table style="width:100%;border-collapse:collapse;font-size:11px">'
                    f'<thead><tr>'
                    f'<th style="padding:4px 10px;color:{TEXT_MUTED};font-size:10px;text-align:left">Ticker</th>'
                    f'<th style="padding:4px 10px;color:{TEXT_MUTED};font-size:10px;text-align:left">Price</th>'
                    f'<th style="padding:4px 10px;color:{TEXT_MUTED};font-size:10px;text-align:left">Weekly values</th>'
                    f'<th style="padding:4px 10px;color:{TEXT_MUTED};font-size:10px;text-align:left">Failing daily conds</th>'
                    f'</tr></thead><tbody>{rows_wp}</tbody></table></div>',
                    unsafe_allow_html=True,
                )

            col_w, col_d = st.columns(2)
            with col_w:
                st.markdown(
                    f'<div style="color:{GOLD};font-size:11px;font-weight:700;margin-bottom:4px">'
                    f'📅 Weekly gate — {wpass}/{dok} passed</div>'
                    + f'<div style="background:#0f172a;border-radius:6px;padding:4px;overflow-x:auto">'
                    + _breakdown_table(w_fails, w_labels, dok, GOLD)
                    + '</div>',
                    unsafe_allow_html=True,
                )
            with col_d:
                st.markdown(
                    f'<div style="color:{ACCENT_GREEN};font-size:11px;font-weight:700;margin-bottom:4px">'
                    f'📊 Daily gate — {dpass}/{wpass} passed (of weekly passers)</div>'
                    + f'<div style="background:#0f172a;border-radius:6px;padding:4px;overflow-x:auto">'
                    + (_breakdown_table(d_fails, d_labels, wpass, ACCENT_GREEN) if wpass > 0
                       else f'<div style="color:{TEXT_MUTED};font-size:11px;padding:8px">No tickers reached daily gate</div>')
                    + '</div>',
                    unsafe_allow_html=True,
                )

    render_ftf_section(st.session_state["ftf_strat_rows"], context="ftf")

    # Export
    rows = st.session_state["ftf_strat_rows"]
    if rows:
        _df = pd.DataFrame([{
            "Ticker": r["ticker"], "Price": r["price"],
            "W-RSI": r["w_detail"].get("rsi_w"),
            "D-RSI": r["d_detail"].get("rsi_d"),
            "ADX":   r["d_detail"].get("adx"),
        } for r in rows])
        st.download_button("⬇ Export CSV", _df.to_csv(index=False),
                           "ftf_scan.csv", "text/csv", key="ftf_dl")


def render():
    section_header("♟️", "Strategies",
                   "QQQ / TQQQ weight-of-evidence · Options Strategy screener · First Things First")

    st.markdown(_TAB_CSS, unsafe_allow_html=True)

    tab_qqq, tab_opts, tab_ftf = st.tabs([
        "♟️  QQQ / TQQQ Strategy",
        "💰  Options Strategy",
        "🎯  First Things First",
    ])

    with tab_qqq:
        from scanners.qqq_strategy_page import render as _qqq_render
        _qqq_render(_skip_header=True)

    with tab_opts:
        _render_options_strategy()

    with tab_ftf:
        _render_ftf_tab()
