"""
Golden Scanner — QQQ / TQQQ Strategy Page
Renders the weight-of-evidence dashboard using GoldenScanner's dark theme.
"""

import datetime as _dt
import streamlit as st

from config import (
    GOLD, GOLD_DARK, BG_CARD, BG_PANEL, BG_DARK,
    ACCENT_GREEN, ACCENT_RED, ACCENT_BLUE,
    TEXT_PRIMARY, TEXT_MUTED, BORDER_COLOR,
)
from scanners.qqq_strategy import (
    evaluate,
    check_pullback_entry,
    INDICATOR_LABELS,
    THRESHOLD_IN_SEASON,
    THRESHOLD_OFF_SEASON,
    MAX_SCORE,
    _BULLISH_PATTERNS,
    _BEARISH_PATTERNS,
    _in_season,
)

# ── Theme helpers ─────────────────────────────────────────────────────────────

def _badge(text: str, bg: str, fg: str) -> str:
    return (
        f'<span style="background:{bg};color:{fg};font-size:11px;font-weight:700;'
        f'letter-spacing:1px;padding:3px 10px;border-radius:20px;'
        f'text-transform:uppercase">{text}</span>'
    )

def _card(content_html: str, border_color: str = BORDER_COLOR) -> str:
    return (
        f'<div style="background:{BG_CARD};border:1px solid {border_color};'
        f'border-radius:10px;padding:16px 20px;margin-bottom:12px">'
        f'{content_html}</div>'
    )

_SIG_THEME = {
    "green":  (ACCENT_GREEN,  "#052e16", "#dcfce7"),
    "orange": ("#F59E0B",     "#451a03", "#fef3c7"),
    "red":    (ACCENT_RED,    "#450a0a", "#fee2e2"),
}


def _render_pullback_card(pb: dict):
    """Render the 6-condition pullback entry checklist below the main panel."""
    if not pb or "error" in pb:
        return

    G  = ACCENT_GREEN
    all_pass = pb["signal"]
    w_pass   = pb["w_pass"]
    d_pass   = pb["d_pass"]

    # Section label
    heart = "💚" if all_pass else ("🟡" if (w_pass or d_pass) else "⬜")
    st.markdown(
        f'<div style="color:{ACCENT_BLUE};font-size:11px;font-weight:700;'
        f'letter-spacing:1.5px;text-transform:uppercase;margin:14px 0 6px">'
        f'{heart} Pullback Entry Signal</div>',
        unsafe_allow_html=True,
    )

    conds = pb.get("conditions", [])
    # Show weekly (W1/W2/W3) then daily (D1/D2/D3) in readable order
    ordered = (
        [c for c in conds if c["key"].startswith("W")]
        + [c for c in conds if c["key"].startswith("D")]
    )

    rows_html = ""
    for c in ordered:
        icon = "✅" if c["passed"] else "❌"
        col  = G if c["passed"] else ACCENT_RED
        rows_html += (
            f'<div style="display:flex;align-items:flex-start;gap:8px;'
            f'padding:5px 10px;border-radius:6px;margin-bottom:3px;'
            f'background:{BG_PANEL};border:1px solid {BORDER_COLOR}">'
            f'<span style="font-size:13px;min-width:18px">{icon}</span>'
            f'<span style="flex:1;font-size:11px;color:{GOLD};font-weight:600">'
            f'{c["label"]}</span>'
            f'<span style="font-size:10px;color:{col};font-family:monospace;'
            f'white-space:nowrap">{c["detail"]}</span>'
            f'</div>'
        )

    verdict_bg  = f"{G}18" if all_pass else (f"#FBBF2418" if (w_pass or d_pass) else f"{ACCENT_RED}12")
    verdict_bdr = G if all_pass else ("#FBBF24" if (w_pass or d_pass) else ACCENT_RED)
    verdict_txt = (
        "All 6 conditions met — pullback entry confirmed 💚" if all_pass else
        ("Weekly confirmed ✅ — waiting for daily pullback" if w_pass else
         ("Daily setup ready — waiting for weekly confirmation" if d_pass else
          "Setup not ready — conditions not met"))
    )
    verdict_col = G if all_pass else ("#FBBF24" if (w_pass or d_pass) else ACCENT_RED)

    st.markdown(
        f'{rows_html}'
        f'<div style="margin-top:6px;background:{verdict_bg};border:1px solid {verdict_bdr}44;'
        f'border-left:3px solid {verdict_bdr};border-radius:6px;padding:8px 12px;'
        f'font-size:11px;font-weight:600;color:{verdict_col}">{verdict_txt}</div>',
        unsafe_allow_html=True,
    )


# ── Panel renderer (one ticker) ───────────────────────────────────────────────

def _render_panel(r: dict):
    if "error" in r:
        st.error(r["error"])
        return

    ticker     = r["ticker"]
    total      = r["total"]
    max_s      = r["max"]
    confidence = r["confidence"]
    signal     = r["signal"]
    sig_color  = r["sig_color"]
    threshold  = r["threshold"]

    accent, dark_fg, light_bg = _SIG_THEME.get(sig_color, _SIG_THEME["orange"])

    # ── Signal card ───────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="background:linear-gradient(135deg,{dark_fg},{BG_CARD});'
        f'border:1.5px solid {accent}55;border-left:4px solid {accent};'
        f'border-radius:10px;padding:16px 20px;margin-bottom:14px">'
        f'<div style="font-size:20px;font-weight:800;color:{accent}">{signal}</div>'
        f'<div style="margin-top:8px;display:flex;gap:20px;flex-wrap:wrap">'
        f'<span style="color:{TEXT_MUTED};font-size:12px">Score &nbsp;'
        f'<span style="color:{accent};font-weight:700;font-size:16px">{total}/{max_s}</span></span>'
        f'<span style="color:{TEXT_MUTED};font-size:12px">Confidence &nbsp;'
        f'<span style="color:{accent};font-weight:700;font-size:16px">{confidence}%</span></span>'
        f'<span style="color:{TEXT_MUTED};font-size:12px">Threshold &nbsp;'
        f'<span style="color:{TEXT_PRIMARY};font-weight:600">+{threshold}</span></span>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    # Confidence bar
    bar_pct = confidence / 100
    st.markdown(
        f'<div style="background:{BG_PANEL};border-radius:6px;height:8px;margin-bottom:14px;overflow:hidden">'
        f'<div style="width:{confidence}%;height:100%;background:linear-gradient(90deg,{GOLD_DARK},{accent});border-radius:6px;'
        f'transition:width 0.4s ease"></div></div>',
        unsafe_allow_html=True,
    )

    # ── Price metrics ─────────────────────────────────────────────────────────
    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("Price",   f"${r['price']:,.2f}")
    mc2.metric("SMA 200", f"${r['sma200']:,.2f}",
               delta="above" if r["price"] > r["sma200"] else "⚠ BELOW")
    mc3.metric("RSI 14",  f"{r['rsi']:.1f}",
               delta="overbought" if r["overbought"] else None)

    # ── Context row ───────────────────────────────────────────────────────────
    season_html = (
        f'<span style="color:{ACCENT_GREEN}">✅ In-Season (Nov–Jun)</span>'
        if r["in_season"] else
        f'<span style="color:#F59E0B">⚠️ Off-Season (Jul–Oct) — threshold +{THRESHOLD_OFF_SEASON}</span>'
    )
    hh_html = (
        f'<span style="color:{ACCENT_GREEN}">✅ HH+HL confirmed</span>'
        if r["is_hh_hl"] else
        f'<span style="color:{TEXT_MUTED}">❌ No HH+HL yet</span>'
    )
    ob_html = (
        f'<span style="color:{ACCENT_RED}">⚠️ Overbought — no new longs</span>'
        if r["overbought"] else
        f'<span style="color:{ACCENT_GREEN}">✅ Not Overbought</span>'
    )
    st.markdown(
        f'<div style="font-size:12px;line-height:2;margin-bottom:12px">'
        f'{season_html} &nbsp;·&nbsp; {hh_html} &nbsp;·&nbsp; {ob_html}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Checklist ─────────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="color:{GOLD};font-size:11px;font-weight:700;'
        f'letter-spacing:1.5px;text-transform:uppercase;margin-bottom:8px">'
        f'Indicator Checklist</div>',
        unsafe_allow_html=True,
    )

    for key, label in INDICATOR_LABELS.items():
        _, sc, desc = r["details"][key]
        if sc == 1:
            icon, col, pts = "✅", ACCENT_GREEN, "+1"
        elif sc == -1:
            icon, col, pts = "❌", ACCENT_RED,   "−1"
        else:
            icon, col, pts = "⬜", TEXT_MUTED,   " 0"

        st.markdown(
            f'<div style="display:flex;align-items:flex-start;gap:8px;'
            f'padding:5px 10px;border-radius:6px;margin-bottom:3px;'
            f'background:{BG_PANEL};border:1px solid {BORDER_COLOR}">'
            f'<span style="font-size:14px;min-width:18px">{icon}</span>'
            f'<span style="flex:1;font-size:12px;color:{TEXT_PRIMARY}">'
            f'<span style="font-weight:600">{label}</span>'
            f'<span style="color:{TEXT_MUTED}"> — {desc}</span>'
            f'</span>'
            f'<span style="font-family:monospace;font-size:12px;font-weight:700;'
            f'color:{col};min-width:24px;text-align:right">{pts}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── Stop level ────────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="margin-top:10px;background:{BG_PANEL};border:1px solid {BORDER_COLOR};'
        f'border-left:3px solid {GOLD};border-radius:6px;padding:10px 14px;font-size:12px">'
        f'<span style="color:{GOLD};font-weight:700">📍 Suggested Stop:</span>'
        f'&nbsp;<span style="color:{TEXT_PRIMARY}">{r["stop"]}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    if r.get("vix") is not None:
        st.caption(f"VIX: {r['vix']:.1f}")


# ── Main render ───────────────────────────────────────────────────────────────

def render(_skip_header: bool = False):
    from config import GOLD, TEXT_MUTED, BG_CARD, BORDER_COLOR

    if not _skip_header:
        # Page header (shown when rendered standalone, not inside strategies_page tabs)
        st.markdown(
            f'<div style="margin-bottom:6px">'
            f'<span style="font-family:\'Cormorant Garamond\',serif;font-size:28px;'
            f'font-weight:700;color:{GOLD};letter-spacing:2px">♟️ QQQ / TQQQ Strategy</span>'
            f'</div>'
            f'<div style="color:{TEXT_MUTED};font-size:12px;margin-bottom:16px">'
            f'Weight-of-Evidence · 7 Indicators · Threshold +{THRESHOLD_IN_SEASON} (in-season) '
            f'/ +{THRESHOLD_OFF_SEASON} (off-season) · Data via yfinance (EOD)</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div style="height:1px;background:linear-gradient(90deg,{GOLD}44,transparent);'
            f'margin-bottom:20px"></div>',
            unsafe_allow_html=True,
        )

    # ── Strategy Rules Reference ──────────────────────────────────────────────
    with st.expander("📋 Strategy Rules Reference", expanded=False):
        rc1, rc2 = st.columns(2)
        with rc1:
            st.markdown(f"**Indicator Scoring**")
            st.markdown(
                "| # | Indicator | +1 | 0 | −1 |\n"
                "|---|-----------|-----|---|----|\n"
                "| 1 | Price vs SMA 200 | Price > SMA200 | — | Price < SMA200 |\n"
                "| 2 | SMA 50 Slope (3-day) | Rising | — | Falling |\n"
                "| 3 | MACD Slope + Signal | Slope ↑ & above signal | Mixed | Slope ↓ & below |\n"
                "| 4 | RSI 14 | 50–69 | ≥ 70 (OB) | < 50 |\n"
                "| 5 | Keltner Location | Mid < Price < Upper | At/above upper | ≤ mid |\n"
                "| 6 | VIX | < 31 | N/A | ≥ 31 |\n"
                "| 7 | Candlestick | Bullish pattern | None | Bearish pattern |"
            )
            st.markdown(
                f"**Thresholds:** In-season (Nov–Jun): **≥ +{THRESHOLD_IN_SEASON}**  ·  "
                f"Off-season (Jul–Oct): **≥ +{THRESHOLD_OFF_SEASON}**"
            )
        with rc2:
            bp_col, bap_col = st.columns(2)
            with bp_col:
                st.markdown("**✅ Bullish Patterns**")
                for p in _BULLISH_PATTERNS:
                    st.markdown(f"- {p}")
            with bap_col:
                st.markdown("**❌ Bearish Patterns**")
                for p in _BEARISH_PATTERNS:
                    st.markdown(f"- {p}")

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── Run button ────────────────────────────────────────────────────────────
    run_col, ts_col = st.columns([1, 3])
    with run_col:
        run_btn = st.button("🔍  Run Analysis", type="primary",
                            key="gs_strat_run", use_container_width=True)
    with ts_col:
        if "gs_strat_last_run" in st.session_state:
            st.markdown(
                f'<div style="color:{TEXT_MUTED};font-size:12px;padding-top:10px">'
                f'Last run: {st.session_state["gs_strat_last_run"]}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div style="color:{TEXT_MUTED};font-size:12px;padding-top:10px">'
                f'Press Run Analysis to fetch live data and evaluate signals.</div>',
                unsafe_allow_html=True,
            )

    if run_btn:
        with st.spinner("Fetching QQQ and TQQQ data from Yahoo Finance…"):
            r_qqq   = evaluate("QQQ")
            r_tqqq  = evaluate("TQQQ")
            pb_qqq  = check_pullback_entry("QQQ")
            pb_tqqq = check_pullback_entry("TQQQ")
        st.session_state["gs_strat_qqq"]      = r_qqq
        st.session_state["gs_strat_tqqq"]     = r_tqqq
        st.session_state["gs_strat_pb_qqq"]   = pb_qqq
        st.session_state["gs_strat_pb_tqqq"]  = pb_tqqq
        st.session_state["gs_strat_last_run"] = _dt.datetime.now().strftime("%b %d %Y  %I:%M %p")
        st.rerun()

    # ── Results ───────────────────────────────────────────────────────────────
    if "gs_strat_qqq" in st.session_state:
        r_qqq   = st.session_state["gs_strat_qqq"]
        r_tqqq  = st.session_state["gs_strat_tqqq"]
        pb_qqq  = st.session_state.get("gs_strat_pb_qqq",  {})
        pb_tqqq = st.session_state.get("gs_strat_pb_tqqq", {})

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        col_qqq, col_tqqq = st.columns(2)

        with col_qqq:
            _heart_qqq = " 💚" if pb_qqq.get("signal") else ""
            st.markdown(
                f'<div style="font-family:\'Cormorant Garamond\',serif;font-size:22px;'
                f'font-weight:700;color:{GOLD};margin-bottom:4px">QQQ{_heart_qqq}</div>'
                f'<div style="color:{TEXT_MUTED};font-size:11px;margin-bottom:12px">'
                f'Nasdaq 100 ETF · 1× leverage</div>',
                unsafe_allow_html=True,
            )
            _render_panel(r_qqq)
            _render_pullback_card(pb_qqq)

        with col_tqqq:
            _heart_tqqq = " 💚" if pb_tqqq.get("signal") else ""
            st.markdown(
                f'<div style="font-family:\'Cormorant Garamond\',serif;font-size:22px;'
                f'font-weight:700;color:{GOLD};margin-bottom:4px">TQQQ{_heart_tqqq}</div>'
                f'<div style="color:{TEXT_MUTED};font-size:11px;margin-bottom:12px">'
                f'Nasdaq 100 ETF · 3× leverage · same rules</div>',
                unsafe_allow_html=True,
            )
            _render_panel(r_tqqq)
            _render_pullback_card(pb_tqqq)

    else:
        st.markdown(
            f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};'
            f'border-radius:10px;padding:40px;text-align:center;color:{TEXT_MUTED}">'
            f'Press <strong style="color:{GOLD}">Run Analysis</strong> to generate today\'s signal.'
            f'</div>',
            unsafe_allow_html=True,
        )
