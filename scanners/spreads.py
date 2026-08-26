# scanners/spreads.py — 0DTE credit spreads anchored on the morning range
#
# THE SETUP
#   Mark the session's High and Low from 09:30 to 12:00 ET. Where the price
#   sits inside that range AT NOON decides the side:
#
#     noon in the UPPER part  -> PUT credit spread, short strike below the
#                                morning LOW
#     noon BELOW the midpoint -> CALL credit spread, short strike above the
#                                morning HIGH
#
#   The trade is held to the close, so what matters is whether the session
#   CLOSES through the short strike, not whether it touches it intraday.
#
# WHY THE PUT SIDE IS GATED AT 70% AND THE CALL SIDE IS NOT
#   Measured over 59 sessions of 5-minute bars (2026-06-02 → 2026-08-25,
#   QQQ + SPY), the put side is not one state. Splitting at the midpoint
#   pools a zone that essentially never breached with one that breached a
#   third of the time:
#
#     noon >= 70%    1 breach / 43 sessions   2.3%
#     noon 60-70%    4 breaches / 13          30.8%
#     noon 50-60%    2 breaches / 8           25.0%
#
#   So >= 70% is the trade, 60-70% is shown with the real number attached
#   because it was explicitly asked for, and 50-60% is not offered at all.
#
#   The call side has no such split -- it is uniformly safe across the whole
#   lower half (QQQ 1/26, SPY 1/28, ~3.7%), so it takes a single zone.
#
# WHAT THESE NUMBERS ARE NOT
#   43 sessions with one breach means "under roughly 12% with 95%
#   confidence", not zero. One quiet market regime (mean morning range 1.35%
#   QQQ / 0.74% SPY). Premiums are Yahoo mid-quotes, delayed ~15 minutes,
#   which on 0DTE is a real difference -- they size a trade, they do not
#   fill one.

from __future__ import annotations

import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import pytz
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    GOLD, BG_PANEL, BG_CARD, BORDER_COLOR, TEXT_PRIMARY, TEXT_MUTED,
    ACCENT_GREEN, ACCENT_RED, ACCENT_BLUE,
)

ET = pytz.timezone("US/Eastern")

# Underlyings. SPX is quoted from ^SPX where Yahoo serves it; where it does
# not, SPY x10 stands in and the card says so rather than implying the
# strikes came from the index chain.
TICKERS = [
    {"key": "QQQ", "spot_symbol": "QQQ", "chain_symbol": "QQQ",
     "label": "QQQ", "scale": 1.0},
    {"key": "SPX", "spot_symbol": "^SPX", "chain_symbol": "^SPX",
     "label": "SPX", "scale": 1.0,
     "fallback": {"spot_symbol": "SPY", "chain_symbol": "SPY", "scale": 10.0}},
]

MORNING_START_MIN = 9 * 60 + 30
NOON_MIN = 12 * 60
# The scan only means anything near noon: run it at 15:00 and the morning
# range is stale while gamma has completely changed.
VALID_FROM_MIN = 11 * 60 + 45
VALID_TO_MIN = 13 * 60 + 30

PUT_GREEN_MIN = 70.0
PUT_AMBER_MIN = 60.0
CALL_MAX = 50.0

# Historical breach rate per zone, from data/noon_reversal/latest.json.
# Carried here so the card can state the number beside the badge instead of
# a vague "risky" — see the module header for the full table.
ZONES = {
    "put_green": {"label": "PUT credit spread", "colour": ACCENT_GREEN,
                  "breach": "1 breach / 43 sessions · 2.3%",
                  "note": "Noon closed decisively in the upper range. This is the zone the study supports."},
    "put_amber": {"label": "PUT credit spread — CAUTION", "colour": GOLD,
                  "breach": "4 breaches / 13 sessions · 30.8%",
                  "note": "Marginal zone. Historically breached the morning low almost a third of the time — "
                          "on a 3:1 spread that is not a small tail. Shown because you asked for it."},
    "put_block": {"label": "NO TRADE", "colour": ACCENT_RED,
                  "breach": "2 breaches / 8 sessions · 25.0%",
                  "note": "Noon barely above the midpoint. Not offered — the study found no safe put "
                          "structure here."},
    "call": {"label": "CALL credit spread", "colour": ACCENT_BLUE,
             "breach": "2 breaches / 54 sessions · 3.7%",
             "note": "Noon below the midpoint. The call side showed no dangerous sub-band — it is "
                     "uniformly safe across the whole lower half."},
}


def now_et() -> datetime:
    return datetime.now(ET)


def _minutes(ts) -> int:
    return int(ts.hour) * 60 + int(ts.minute)


def morning_state(spot_symbol: str, scale: float = 1.0) -> dict | None:
    """Today's morning range, the noon print, and where noon sits in it."""
    from data_loader import get_price_history

    df = get_price_history(spot_symbol, period="2d", interval="5m")
    if df is None or df.empty or "Close" not in df:
        return None
    idx = pd.DatetimeIndex(df.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx
    df = df.set_axis(idx.tz_convert(ET)).dropna(subset=["Close"])

    today = now_et().date()
    day = df[[d.date() == today for d in df.index]]
    if day.empty:
        return None

    mins = np.array([_minutes(t) for t in day.index])
    morning = day[(mins >= MORNING_START_MIN) & (mins < NOON_MIN)]
    if len(morning) < 6:
        return None

    hi = float(morning["High"].max()) * scale
    lo = float(morning["Low"].min()) * scale
    if not np.isfinite(hi) or not np.isfinite(lo) or hi <= lo:
        return None

    noon_px = float(morning["Close"].iloc[-1]) * scale
    spot = float(day["Close"].iloc[-1]) * scale
    last_min = int(mins.max())

    return {
        "high": hi, "low": lo, "mid": (hi + lo) / 2.0,
        "noon": noon_px, "spot": spot,
        "pos_pct": (noon_px - lo) / (hi - lo) * 100.0,
        "range_pct": (hi - lo) / lo * 100.0,
        # True while the 12:00 bar has not printed: the range can still widen,
        # so the position reading is provisional rather than final.
        "morning_complete": last_min >= NOON_MIN - 5,
    }


def zone_for(pos_pct: float) -> str:
    if pos_pct >= PUT_GREEN_MIN:
        return "put_green"
    if pos_pct >= PUT_AMBER_MIN:
        return "put_amber"
    if pos_pct >= CALL_MAX:
        return "put_block"
    return "call"


# ══════════════════════════════════════════════════════════════════════════
# SPREAD CONSTRUCTION
# ══════════════════════════════════════════════════════════════════════════

def _mid(bid, ask, last) -> float | None:
    """Mid of the quote, falling back to last only when a side is missing.

    A zero bid is real information on 0DTE (nobody wants it), so it is not
    treated as missing — but a spread priced off a 0x0 quote is fiction, and
    those are dropped by the caller.
    """
    try:
        b = float(bid) if bid is not None and np.isfinite(float(bid)) else None
        a = float(ask) if ask is not None and np.isfinite(float(ask)) else None
    except (TypeError, ValueError):
        b = a = None
    if b is not None and a is not None and a > 0:
        return (b + a) / 2.0
    for v in (a, b, last):
        try:
            f = float(v)
            if np.isfinite(f) and f > 0:
                return f
        except (TypeError, ValueError):
            continue
    return None


def todays_chain(chain_symbol: str) -> tuple[pd.DataFrame, pd.DataFrame, str] | None:
    """Today's 0DTE option chain (puts, calls, expiry). None if there isn't one."""
    import yfinance as yf

    try:
        tk = yf.Ticker(chain_symbol)
        expiries = list(tk.options or [])
    except Exception:
        return None
    if not expiries:
        return None

    today = now_et().date().isoformat()
    if today not in expiries:
        return None
    try:
        ch = tk.option_chain(today)
    except Exception:
        return None
    puts, calls = ch.puts, ch.calls
    if puts is None or calls is None or puts.empty or calls.empty:
        return None
    return puts, calls, today


def _leg_price(df: pd.DataFrame, strike: float) -> float | None:
    row = df[np.isclose(df["strike"], strike)]
    if row.empty:
        return None
    r = row.iloc[0]
    return _mid(r.get("bid"), r.get("ask"), r.get("lastPrice"))


def build_spreads(side: str, chain: pd.DataFrame, anchor: float, spot: float,
                  scale: float = 1.0, max_candidates: int = 3) -> list[dict]:
    """Candidate vertical credit spreads anchored on the morning range.

    `anchor` is the morning LOW for puts (short strike at or below it) and the
    morning HIGH for calls (short strike at or above it). Widths come from the
    chain's own strike spacing rather than an assumption, so QQQ's $1 grid and
    SPX's $5 grid both work without special-casing.

    No target ratio is imposed. Forcing a 1:3 would silently walk the short
    strike to wherever that ratio lives, which is not necessarily a strike the
    study ever validated — the whole point is that the strike is anchored to
    the morning range and the ratio is an OUTCOME to read, not an input.
    """
    if chain is None or chain.empty:
        return []
    strikes = np.sort(np.unique(chain["strike"].to_numpy(dtype=float))) * scale
    if len(strikes) < 3:
        return []
    step = float(np.median(np.diff(strikes))) or 1.0

    if side == "put":
        shorts = strikes[strikes <= anchor][::-1][:max_candidates]
    else:
        shorts = strikes[strikes >= anchor][:max_candidates]
    if not len(shorts):
        return []

    out = []
    for short_k in shorts:
        for width_mult in (1, 2, 4):
            width = step * width_mult
            long_k = short_k - width if side == "put" else short_k + width
            if long_k not in set(np.round(strikes, 6)) and not np.any(np.isclose(strikes, long_k)):
                continue
            s_px = _leg_price(chain, short_k / scale)
            l_px = _leg_price(chain, long_k / scale)
            if s_px is None or l_px is None:
                continue
            credit = (s_px - l_px) * scale
            # A credit at or below zero is not a credit spread, and one at or
            # above the width is a mispriced or stale quote, not free money.
            if credit <= 0 or credit >= width:
                continue
            max_profit = credit * 100.0
            max_loss = (width - credit) * 100.0
            breakeven = short_k - credit if side == "put" else short_k + credit
            cushion = ((spot - short_k) / spot * 100.0 if side == "put"
                       else (short_k - spot) / spot * 100.0)
            out.append({
                "side": side, "short": short_k, "long": long_k, "width": width,
                "credit": credit, "max_profit": max_profit, "max_loss": max_loss,
                "rr": max_loss / max_profit if max_profit else None,
                "credit_pct_width": credit / width * 100.0,
                "breakeven": breakeven, "cushion_pct": cushion,
            })
    # Widest cushion first, then the better ratio — the strike is the decision
    # the study speaks to; the ratio only breaks ties between equal strikes.
    out.sort(key=lambda x: (-x["cushion_pct"], x["rr"] if x["rr"] else 9e9))
    return out[:6]


# ══════════════════════════════════════════════════════════════════════════
# PRESENTATION
# ══════════════════════════════════════════════════════════════════════════
# Plain HTML throughout, like the rest of this app's tables: st.dataframe
# paints to a canvas and, when it fails to lay out, leaves a blank box with
# no error to explain it.

def _rgba(hex_colour: str, alpha: float) -> str:
    h = hex_colour.lstrip("#")
    return f"rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{alpha})"


def range_bar_html(st_: dict, zone: str) -> str:
    """The morning range as a bar, with the noon print marked on it.

    The single most useful thing on this tab: the decision is "where in the
    range did noon land", and a number between 0 and 100 is far harder to
    feel than a marker sitting in a shaded band.
    """
    pos = max(0.0, min(100.0, st_["pos_pct"]))
    colour = ZONES[zone]["colour"]
    # Bands drawn at the real thresholds so the gate is visible, not implied.
    bands = (
        f'<div style="position:absolute;left:0;width:50%;top:0;bottom:0;'
        f'background:{_rgba(ACCENT_BLUE,0.16)}"></div>'
        f'<div style="position:absolute;left:50%;width:10%;top:0;bottom:0;'
        f'background:{_rgba(ACCENT_RED,0.18)}"></div>'
        f'<div style="position:absolute;left:60%;width:10%;top:0;bottom:0;'
        f'background:{_rgba(GOLD,0.18)}"></div>'
        f'<div style="position:absolute;left:70%;width:30%;top:0;bottom:0;'
        f'background:{_rgba(ACCENT_GREEN,0.18)}"></div>'
    )
    ticks = "".join(
        f'<div style="position:absolute;left:{x}%;top:-3px;bottom:-3px;width:1px;'
        f'background:{TEXT_MUTED}66"></div>' for x in (50, 60, 70)
    )
    marker = (
        f'<div style="position:absolute;left:{pos:.1f}%;top:-7px;bottom:-7px;width:3px;'
        f'background:{colour};box-shadow:0 0 6px {_rgba(colour,0.9)};border-radius:2px"></div>'
        f'<div style="position:absolute;left:{pos:.1f}%;top:-26px;transform:translateX(-50%);'
        f'color:{colour};font-size:11px;font-weight:800;white-space:nowrap">'
        f'noon {st_["pos_pct"]:.0f}%</div>'
    )
    return (
        f'<div style="margin:26px 0 6px 0">'
        f'<div style="position:relative;height:22px;background:{BG_CARD};'
        f'border:1px solid {BORDER_COLOR};border-radius:5px">{bands}{ticks}{marker}</div>'
        f'<div style="display:flex;justify-content:space-between;margin-top:4px;'
        f'color:{TEXT_MUTED};font-size:10px">'
        f'<span>LOW {st_["low"]:,.2f}</span>'
        f'<span style="color:{TEXT_MUTED}">50 · 60 · 70 gates</span>'
        f'<span>HIGH {st_["high"]:,.2f}</span></div></div>'
    )


def spread_card_html(sp: dict, best: bool) -> str:
    """One candidate spread. Credit and risk given per contract, in dollars."""
    side_lbl = "PUT credit" if sp["side"] == "put" else "CALL credit"
    edge = ACCENT_GREEN if best else BORDER_COLOR
    rr = sp["rr"]
    rr_txt = "—" if rr is None else f"1 : {rr:.1f}"
    # A ratio worse than 1:5 means the credit is thin for the width — not
    # wrong, but worth seeing at a glance rather than computing in your head.
    rr_col = ACCENT_GREEN if (rr and rr <= 3.5) else GOLD if (rr and rr <= 5) else ACCENT_RED
    rows = [
        ("Short", f'{sp["short"]:,.2f}', TEXT_PRIMARY),
        ("Long", f'{sp["long"]:,.2f}', TEXT_MUTED),
        ("Width", f'{sp["width"]:,.2f}', TEXT_MUTED),
        ("Credit", f'${sp["credit"]:,.2f}', ACCENT_GREEN),
        ("Max profit", f'${sp["max_profit"]:,.0f}', ACCENT_GREEN),
        ("Max loss", f'-${sp["max_loss"]:,.0f}', ACCENT_RED),
        ("Risk : Reward", rr_txt, rr_col),
        ("Credit / width", f'{sp["credit_pct_width"]:.0f}%', TEXT_MUTED),
        ("Breakeven", f'{sp["breakeven"]:,.2f}', TEXT_PRIMARY),
        ("Cushion from spot", f'{sp["cushion_pct"]:+.2f}%', ACCENT_BLUE),
    ]
    body = "".join(
        f'<div style="display:flex;justify-content:space-between;padding:3px 0;'
        f'border-bottom:1px solid rgba(255,255,255,.04)">'
        f'<span style="color:{TEXT_MUTED};font-size:10.5px">{k}</span>'
        f'<span style="color:{c};font-size:11.5px;font-weight:700;'
        f'font-family:\'DM Mono\',monospace">{v}</span></div>'
        for k, v, c in rows
    )
    tag = (f'<div style="color:{ACCENT_GREEN};font-size:9px;font-weight:800;'
           f'letter-spacing:.08em;margin-bottom:4px">WIDEST CUSHION</div>' if best else
           f'<div style="height:15px"></div>')
    return (
        f'<div style="flex:1;min-width:210px;background:{BG_PANEL};border:1px solid {edge};'
        f'border-radius:10px;padding:11px 13px">{tag}'
        f'<div style="color:{TEXT_PRIMARY};font-size:13px;font-weight:800;margin-bottom:6px">'
        f'{side_lbl} {sp["short"]:,.0f}/{sp["long"]:,.0f}</div>{body}</div>'
    )


def _scan_one(cfg: dict) -> dict:
    """Everything the card needs for one underlying, or the reason it can't."""
    src, note = cfg, None
    state = morning_state(cfg["spot_symbol"], cfg.get("scale", 1.0))
    chain = todays_chain(cfg["chain_symbol"]) if state else None

    # SPX falls back to SPY x10 only when the index chain genuinely isn't
    # there — and the card says so, rather than implying index strikes.
    if (state is None or chain is None) and cfg.get("fallback"):
        fb = cfg["fallback"]
        fb_state = morning_state(fb["spot_symbol"], fb["scale"])
        fb_chain = todays_chain(fb["chain_symbol"])
        if fb_state and fb_chain:
            src = {**cfg, **fb}
            state, chain, note = fb_state, fb_chain, (
                f'Quoted from {fb["chain_symbol"]} × {fb["scale"]:.0f} — Yahoo served no '
                f'{cfg["chain_symbol"]} chain for today. Strikes are the ETF grid scaled up, '
                f'not real index strikes.')

    if state is None:
        return {"key": cfg["key"], "label": cfg["label"],
                "error": "No intraday bars for today yet."}
    if chain is None:
        return {"key": cfg["key"], "label": cfg["label"], "state": state,
                "error": "No 0DTE chain available for today."}

    puts, calls, expiry = chain
    zone = zone_for(state["pos_pct"])
    spreads = []
    if zone in ("put_green", "put_amber"):
        spreads = build_spreads("put", puts, state["low"], state["spot"], src.get("scale", 1.0))
    elif zone == "call":
        spreads = build_spreads("call", calls, state["high"], state["spot"], src.get("scale", 1.0))

    return {"key": cfg["key"], "label": cfg["label"], "state": state,
            "zone": zone, "spreads": spreads, "expiry": expiry, "note": note}


def render():
    """The 💵 Spreads tab."""
    now = now_et()
    mins = _minutes(now)

    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11.5px;line-height:1.6;margin-bottom:8px">'
        f'0DTE credit spreads anchored on the <b style="color:{GOLD}">09:30–12:00 ET</b> range. '
        f'Where price sits in that range at noon picks the side: upper range → '
        f'<b style="color:{ACCENT_GREEN}">PUT credit spread</b> below the morning low, '
        f'below the midpoint → <b style="color:{ACCENT_BLUE}">CALL credit spread</b> above the '
        f'morning high. Held to the close, so only the closing print matters.<br>'
        f'The put side is gated at <b>70%</b>: over 59 sessions the ≥70% zone breached '
        f'<b style="color:{ACCENT_GREEN}">1 time in 43</b>, while 60–70% breached '
        f'<b style="color:{GOLD}">4 in 13</b> and 50–60% <b style="color:{ACCENT_RED}">2 in 8</b>. '
        f'No target ratio is imposed — the strike is anchored to the range and the '
        f'<b>Risk : Reward</b> is an outcome to read.</div>',
        unsafe_allow_html=True,
    )

    # The scan is only meaningful near noon. It still runs — but it will not
    # look authoritative at 15:30 when the morning range is four hours stale.
    if not (VALID_FROM_MIN <= mins <= VALID_TO_MIN):
        st.warning(
            f"It is **{now.strftime('%H:%M')} ET**. This setup is designed to be read "
            f"between **11:45 and 13:30 ET** — outside that window the morning range is "
            f"stale and 0DTE gamma is a different animal. You can still scan; treat it as "
            f"a look, not a signal."
        )

    if st.button("▶ Scan now", type="primary", key="spreads_run", use_container_width=True):
        with st.spinner("Reading the morning range and today's 0DTE chains…"):
            try:
                st.session_state["spreads_cards"] = [_scan_one(c) for c in TICKERS]
                st.session_state["spreads_ts"] = now_et().strftime("%b %d · %H:%M:%S ET")
            except Exception as e:
                st.error(f"Scan failed: {e}")

    cards = st.session_state.get("spreads_cards")
    if cards is None:
        st.markdown(
            f'<div style="border:1px dashed {BORDER_COLOR};border-radius:10px;padding:34px;'
            f'text-align:center;color:{TEXT_MUTED}">Press <b style="color:{GOLD}">▶ Scan now</b>. '
            f'Re-run it as often as you like — nothing is scheduled and nothing is cached '
            f'between presses.</div>', unsafe_allow_html=True)
        return

    st.caption(f"Scanned {st.session_state.get('spreads_ts','')} · premiums are Yahoo mid-quotes, "
               f"delayed ~15 min — indicative sizing, not fills")

    for c in cards:
        st.markdown(
            f'<div style="margin-top:14px;color:{TEXT_PRIMARY};font-size:17px;font-weight:800">'
            f'{c["label"]}</div>', unsafe_allow_html=True)

        if c.get("error") and not c.get("state"):
            st.info(c["error"])
            continue

        s, zone = c["state"], c.get("zone")
        z = ZONES.get(zone, {})
        head = (f'spot <b style="color:{TEXT_PRIMARY}">{s["spot"]:,.2f}</b> · '
                f'morning range <b style="color:{TEXT_PRIMARY}">{s["range_pct"]:.2f}%</b> · '
                f'noon <b style="color:{TEXT_PRIMARY}">{s["noon"]:,.2f}</b>')
        if not s["morning_complete"]:
            head += (f' · <b style="color:{GOLD}">provisional — the 12:00 bar has not printed, '
                     f'the range can still widen</b>')
        st.markdown(f'<div style="color:{TEXT_MUTED};font-size:11px">{head}</div>',
                    unsafe_allow_html=True)
        st.markdown(range_bar_html(s, zone), unsafe_allow_html=True)

        st.markdown(
            f'<div style="background:{_rgba(z.get("colour", TEXT_MUTED), 0.10)};'
            f'border-left:3px solid {z.get("colour", TEXT_MUTED)};border-radius:0 8px 8px 0;'
            f'padding:9px 12px;margin-bottom:8px">'
            f'<span style="color:{z.get("colour", TEXT_MUTED)};font-size:13px;font-weight:800">'
            f'{z.get("label","")}</span>'
            f'<span style="color:{TEXT_MUTED};font-size:10.5px;margin-left:10px">'
            f'historical breach {z.get("breach","")}</span>'
            f'<div style="color:{TEXT_MUTED};font-size:11px;margin-top:3px">{z.get("note","")}</div>'
            f'</div>', unsafe_allow_html=True)

        if c.get("note"):
            st.caption(f'⚠️ {c["note"]}')
        if c.get("error"):
            st.info(c["error"])
            continue
        if zone == "put_block":
            continue
        if not c["spreads"]:
            st.info("No spread with a positive credit priced on today's chain at these strikes.")
            continue

        st.markdown(
            '<div style="display:flex;gap:8px;flex-wrap:wrap">'
            + "".join(spread_card_html(sp, i == 0) for i, sp in enumerate(c["spreads"][:3]))
            + "</div>", unsafe_allow_html=True)

        if len(c["spreads"]) > 3:
            with st.expander(f'{len(c["spreads"]) - 3} more strike/width combination(s)'):
                st.markdown(
                    '<div style="display:flex;gap:8px;flex-wrap:wrap">'
                    + "".join(spread_card_html(sp, False) for sp in c["spreads"][3:])
                    + "</div>", unsafe_allow_html=True)

    st.markdown(
        f'<div style="background:#1a1410;border:1px solid rgba(240,112,74,0.18);'
        f'border-radius:10px;padding:11px 13px;font-size:11px;color:#c9a99a;'
        f'line-height:1.6;margin-top:16px">'
        f'<b style="color:#f0704a">Read before sizing.</b> The breach rates come from '
        f'59 sessions in one quiet regime (mean morning range 1.35% QQQ / 0.74% SPY). '
        f'“1 in 43” means under roughly 12% with 95% confidence, not zero. Premiums are '
        f'delayed mid-quotes — on 0DTE the real spread can differ materially. Max loss '
        f'assumes the position is held to expiry with no adjustment.</div>',
        unsafe_allow_html=True)
