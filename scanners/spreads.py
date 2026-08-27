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
# COVERAGE — TWO TABLES
#   Daily expiries (QQQ, SPX, IWM) list an expiry every weekday, so the setup
#   is available every session. QQQ and SPX are the only names the breach
#   study actually measured and they lead that table.
#
#   Non-daily expiries (SMH, GLD, TQQQ, SOXL, NVDA, AVGO, TSLA, META, GOOGL,
#   MSFT) are only a 0DTE trade on their own expiry days. They are a separate
#   table rather than a footnote because on any other day there is no trade
#   here at all — a later expiry has an overnight session inside it, which is
#   precisely what this setup assumes away, so it is never substituted.
#
#   Every name outside QQQ and SPX is badged UNVALIDATED. The chain is always
#   asked; nothing here assumes an expiry exists.
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
from scanners import range_history as rh

ET = pytz.timezone("US/Eastern")

# Underlyings. The list, the descriptions and the validated/cadence flags
# live in scanners/range_history.py, because the accumulator that is
# building the evidence and the tab that trades on it must never disagree
# about which tickers are in scope or which have been measured. This module
# layers on only what is specific to pricing an option: the chain symbol,
# any scaling, and the SPX fallback.
#
# `validated` is the honest part. The 70% gate and every breach rate on this
# tab were measured on QQQ and SPY over 59 sessions — nothing else. Every
# other row carries an UNVALIDATED badge: the thresholds are transplanted,
# not confirmed.
#
# `cadence` decides which of the two tables a ticker appears in. It is a
# declared expectation, never a gate — todays_chain() always asks the chain
# what expiries actually exist, so a ticker that is not 0DTE today reports
# that as a reason rather than being quietly dropped or wrongly included.

# Pricing overrides, keyed by ticker. Everything else comes from the shared
# universe. SPX is quoted from ^SPX where Yahoo serves it; where it does
# not, SPY x10 stands in and the row says so rather than implying the
# strikes came from the index chain.
_OPTION_OVERRIDES = {
    "SPX": {"spot_symbol": "^SPX", "chain_symbol": "^SPX",
            "fallback": {"spot_symbol": "SPY", "chain_symbol": "SPY", "scale": 10.0}},
}


def _build_tickers() -> list[dict]:
    out = []
    for t in rh.UNIVERSE:
        cfg = {"key": t["key"], "label": t["label"], "desc": t["desc"],
               "validated": t["validated"], "cadence": t["cadence"],
               "hint": t["hint"], "group": t["group"],
               "spot_symbol": t["key"], "chain_symbol": t["key"], "scale": 1.0,
               "daily": t["cadence"] == rh.CADENCE_DAILY}
        cfg.update(_OPTION_OVERRIDES.get(t["key"], {}))
        out.append(cfg)
    return out


TICKERS = _build_tickers()
BY_KEY_CFG = {t["key"]: t for t in TICKERS}

# The two tables. Daily-expiry names are the ones this setup was built for;
# everything else only becomes a 0DTE trade on its own expiry days, which is
# a different enough situation to deserve its own table rather than a footnote.
TABLES = [
    {"cadence": rh.CADENCE_DAILY, "title": "Daily expiries",
     "blurb": "Lists an expiry every weekday, so the setup is available every "
              "session. QQQ and SPX are the two the breach study measured."},
    {"cadence": rh.CADENCE_NON_DAILY, "title": "Non-daily expiries",
     "blurb": "Only a 0DTE trade on its own expiry days. On every other day the "
              "row says so and offers nothing — a later expiry is a different "
              "trade, with an overnight session inside it, and is never "
              "substituted."},
]

MORNING_START_MIN = 9 * 60 + 30
NOON_MIN = 12 * 60
# The scan only means anything near noon: run it at 15:00 and the morning
# range is stale while gamma has completely changed.
VALID_FROM_MIN = 11 * 60 + 45
VALID_TO_MIN = 13 * 60 + 30

# Worst risk:reward worth showing. At 1:25 you are risking $25 to make $1 —
# a 4% return on risk, which needs a ~96% win rate merely to break even
# before costs. The measured breach rates are good, but not good enough to
# survive a ratio that thin, and a candidate that far out is really telling
# you the credit does not reach the strike the study validated.
MAX_RR = 25.0

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


def todays_chain(chain_symbol: str):
    """Today's 0DTE chain as (puts, calls, expiry), or (None, reason).

    Returns the REASON rather than a bare None. The first live run reported
    only "No 0DTE chain available for today", which could equally have meant
    a network failure, an empty expiry list, or today genuinely not being an
    expiry — three problems with three different fixes and no way to tell
    them apart.
    """
    import yfinance as yf

    try:
        tk = yf.Ticker(chain_symbol)
        expiries = list(tk.options or [])
    except Exception as e:
        return None, f"could not read the expiry list for {chain_symbol} ({type(e).__name__}: {e})"
    if not expiries:
        return None, f"Yahoo returned no expiries at all for {chain_symbol}"

    today = now_et().date().isoformat()
    if today not in expiries:
        nearest = min(expiries)
        return None, (f"{chain_symbol} has no expiry dated {today} — nearest is {nearest}. "
                      f"This is a 0DTE setup, so a later expiry is a different trade and is "
                      f"deliberately not substituted.")
    try:
        ch = tk.option_chain(today)
    except Exception as e:
        return None, f"expiry {today} listed but the chain would not load ({type(e).__name__}: {e})"
    puts, calls = ch.puts, ch.calls
    if puts is None or calls is None or puts.empty or calls.empty:
        return None, f"the {today} chain for {chain_symbol} came back empty"
    return (puts, calls, today), None


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
            rr = max_loss / max_profit if max_profit else None
            # Anything worse than MAX_RR is not a trade-off, it is a bad
            # trade wearing a high win rate.
            if rr is None or rr > MAX_RR:
                continue
            breakeven = short_k - credit if side == "put" else short_k + credit
            cushion = ((spot - short_k) / spot * 100.0 if side == "put"
                       else (short_k - spot) / spot * 100.0)
            out.append({
                "side": side, "short": short_k, "long": long_k, "width": width,
                "credit": credit, "max_profit": max_profit, "max_loss": max_loss,
                "rr": rr,
                # Return on risk: what you make as a % of what you put up.
                # 1:3 is 33%, 1:25 is 4%. The ratio and this are the same
                # fact, but this is the one that compares across widths and
                # across underlyings.
                "ror_pct": max_profit / max_loss * 100.0 if max_loss else None,
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
#
# ONE table for every underlying, not a card per name. Cards made you compare
# ratios by scrolling; a single grid with a banner row per underlying lets the
# eye run straight down the R:R column across all of them.

def _rgba(hex_colour: str, alpha: float) -> str:
    h = hex_colour.lstrip("#")
    return f"rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{alpha})"


# ── The premium icon ──────────────────────────────────────────────────────
# A money-bag rather than a bare "$", because the dollar sign is already
# doing work in every credit and P/L cell and would not read as a rank.
# Tiers are relative to the BEST credit on that underlying, never across
# underlyings: SPX credits are ~10x QQQ's for arithmetic reasons that say
# nothing about which is the richer premium.
MONEY_TIERS = ((0.90, "\U0001F4B0\U0001F4B0\U0001F4B0"),
               (0.75, "\U0001F4B0\U0001F4B0"),
               (0.55, "\U0001F4B0"))


def premium_icons(credit: float, best_credit: float) -> str:
    """Money bags scaled to how close this credit is to the fattest one."""
    if not best_credit or best_credit <= 0 or credit is None or credit <= 0:
        return ""
    frac = credit / best_credit
    for cutoff, icons in MONEY_TIERS:
        if frac >= cutoff:
            return icons
    return ""


def _rr_colour(rr: float | None) -> str:
    """Green to 1:3.5, gold to 1:5, red beyond — the same scale as before."""
    if rr is None:
        return TEXT_MUTED
    return ACCENT_GREEN if rr <= 3.5 else GOLD if rr <= 5 else ACCENT_RED


TABLE_COLS = [
    ("", "left"), ("Spread", "left"), ("Width", "right"), ("Credit", "right"),
    ("Max profit", "right"), ("Max loss", "right"), ("R : R", "right"),
    ("Return<br>on risk", "right"), ("Credit<br>/ width", "right"),
    ("Breakeven", "right"), ("Cushion", "right"),
]

_TD = ("padding:5px 9px;font-size:11.5px;font-family:'DM Mono',monospace;"
       "border-bottom:1px solid rgba(255,255,255,.045)")


def _cell(v, colour=TEXT_PRIMARY, align="right", weight=700, extra="") -> str:
    return (f'<td style="{_TD};text-align:{align};color:{colour};'
            f'font-weight:{weight};{extra}">{v}</td>')


def spread_row_html(sp: dict, best_credit: float, is_best_rr: bool) -> str:
    """One candidate spread as a table row."""
    rr = sp["rr"]
    rr_col = _rr_colour(rr)
    icons = premium_icons(sp["credit"], best_credit)
    side_col = ACCENT_GREEN if sp["side"] == "put" else ACCENT_BLUE
    side_lbl = "PUT" if sp["side"] == "put" else "CALL"
    # The best-ratio row is the one the table is sorted to put first; mark it
    # so it stays identifiable after the eye has moved down the page.
    mark = (f'<span style="color:{GOLD};font-weight:900">\u2605</span>' if is_best_rr
            else '<span style="opacity:.25">\u00b7</span>')
    tint = f"background:{_rgba(GOLD, 0.05)};" if is_best_rr else ""
    return (
        f'<tr style="{tint}">'
        + _cell(f'{mark} <span style="font-size:12px">{icons}</span>',
                TEXT_MUTED, "left", 700)
        + _cell(f'<span style="color:{side_col};font-weight:800">{side_lbl}</span> '
                f'{sp["short"]:,.2f} / {sp["long"]:,.2f}', TEXT_PRIMARY, "left")
        + _cell(f'{sp["width"]:,.2f}', TEXT_MUTED)
        + _cell(f'${sp["credit"]:,.2f}', ACCENT_GREEN)
        + _cell(f'${sp["max_profit"]:,.0f}', ACCENT_GREEN)
        + _cell(f'-${sp["max_loss"]:,.0f}', ACCENT_RED)
        + _cell("\u2014" if rr is None else f'1 : {rr:.1f}', rr_col, "right", 800)
        + _cell("\u2014" if sp.get("ror_pct") is None else f'{sp["ror_pct"]:.1f}%', rr_col)
        + _cell(f'{sp["credit_pct_width"]:.0f}%', TEXT_MUTED)
        + _cell(f'{sp["breakeven"]:,.2f}', TEXT_PRIMARY)
        + _cell(f'{sp["cushion_pct"]:+.2f}%', ACCENT_BLUE)
        + '</tr>'
    )


def _group_header_html(c: dict) -> str:
    """The banner row that opens one underlying's block inside the table."""
    ncols = len(TABLE_COLS)
    s, zone = c.get("state"), c.get("zone")
    z = ZONES.get(zone, {})
    colour = z.get("colour", TEXT_MUTED)

    badges = ""
    if not c.get("validated", True):
        badges += (f'<span style="background:{_rgba(ACCENT_RED,0.14)};color:{ACCENT_RED};'
                   f'font-size:8.5px;font-weight:800;letter-spacing:.06em;padding:2px 6px;'
                   f'border-radius:4px;margin-left:8px" '
                   f'title="The 70% gate and the breach rates were measured on QQQ and SPY '
                   f'only. On this underlying they are transplanted, not confirmed.">'
                   f'UNVALIDATED</span>')
    if not s:
        return (f'<tr><td colspan="{ncols}" style="padding:14px 10px 6px 10px;'
                f'border-top:2px solid {BORDER_COLOR}">'
                f'<span style="color:{TEXT_PRIMARY};font-size:15px;font-weight:800">'
                f'{c["label"]}</span>'
                f'<span style="color:{TEXT_MUTED};font-size:10.5px;margin-left:8px">'
                f'{c.get("desc","")}</span>{badges}</td></tr>')

    prov = ("" if s["morning_complete"] else
            f' · <b style="color:{GOLD}">provisional</b>')
    # A compact range bar inline in the header: the noon position is the whole
    # decision, and a number between 0 and 100 is harder to feel than a mark.
    pos = max(0.0, min(100.0, s["pos_pct"]))
    bar = (
        f'<span style="display:inline-block;position:relative;width:150px;height:9px;'
        f'background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:3px;'
        f'vertical-align:middle;margin:0 8px">'
        f'<span style="position:absolute;left:0;width:50%;top:0;bottom:0;'
        f'background:{_rgba(ACCENT_BLUE,0.20)}"></span>'
        f'<span style="position:absolute;left:50%;width:10%;top:0;bottom:0;'
        f'background:{_rgba(ACCENT_RED,0.22)}"></span>'
        f'<span style="position:absolute;left:60%;width:10%;top:0;bottom:0;'
        f'background:{_rgba(GOLD,0.22)}"></span>'
        f'<span style="position:absolute;left:70%;width:30%;top:0;bottom:0;'
        f'background:{_rgba(ACCENT_GREEN,0.22)}"></span>'
        f'<span style="position:absolute;left:{pos:.1f}%;top:-3px;bottom:-3px;width:3px;'
        f'background:{colour};border-radius:2px"></span></span>'
    )
    return (
        f'<tr><td colspan="{ncols}" style="padding:15px 10px 7px 10px;'
        f'border-top:2px solid {BORDER_COLOR}">'
        f'<span style="color:{TEXT_PRIMARY};font-size:15px;font-weight:800">{c["label"]}</span>'
        f'<span style="color:{TEXT_MUTED};font-size:10.5px;margin-left:8px">'
        f'{c.get("desc","")}</span>{badges}'
        f'<span style="background:{_rgba(colour,0.13)};color:{colour};font-size:9.5px;'
        f'font-weight:800;letter-spacing:.05em;padding:2px 7px;border-radius:4px;'
        f'margin-left:10px">{z.get("label","")}</span>'
        f'<div style="color:{TEXT_MUTED};font-size:10.5px;margin-top:5px">'
        f'spot <b style="color:{TEXT_PRIMARY}">{s["spot"]:,.2f}</b> · '
        f'range <b style="color:{TEXT_PRIMARY}">{s["range_pct"]:.2f}%</b> '
        f'({s["low"]:,.2f}\u2013{s["high"]:,.2f}){prov}{bar}'
        f'noon <b style="color:{colour}">{s["pos_pct"]:.0f}%</b> · '
        f'historically {z.get("breach","")}</div></td></tr>'
    )


def _message_row_html(text: str, colour=TEXT_MUTED) -> str:
    return (f'<tr><td colspan="{len(TABLE_COLS)}" style="padding:7px 12px;'
            f'font-size:11px;color:{colour};line-height:1.55;'
            f'border-bottom:1px solid rgba(255,255,255,.045)">{text}</td></tr>')


def spreads_table_html(cards: list[dict]) -> str:
    """Every underlying in ONE table, each block sorted best-ratio-first.

    Two orderings are at work and they are deliberately different:

      * build_spreads() SELECTS candidates widest-cushion-first, because the
        strike is what the breach study speaks to. That choice is unchanged.
      * this table DISPLAYS them best-R:R-first, because once the strikes are
        all anchored the ratio is what separates them.

    So the set you see is still chosen by cushion; only the order is by ratio.
    """
    head = "".join(
        f'<th style="padding:7px 9px;text-align:{a};color:{TEXT_MUTED};font-size:9.5px;'
        f'font-weight:800;letter-spacing:.06em;text-transform:uppercase;'
        f'border-bottom:1px solid {BORDER_COLOR};white-space:nowrap">{h}</th>'
        for h, a in TABLE_COLS
    )
    body = []
    for c in cards:
        body.append(_group_header_html(c))
        zone = c.get("zone")

        if c.get("error") and not c.get("state"):
            body.append(_message_row_html(c["error"]))
            continue
        if c.get("note"):
            body.append(_message_row_html(f'\u26a0\ufe0f {c["note"]}', GOLD))
        if c.get("error"):
            z = ZONES.get(zone, {})
            if c.get("anchor_only") is not None and zone != "put_block":
                lvl = "morning low" if str(zone).startswith("put") else "morning high"
                body.append(_message_row_html(
                    f'{c["error"]}<br>The read still stands: <b style="color:'
                    f'{z.get("colour", TEXT_MUTED)}">{z.get("label","")}</b> with the short '
                    f'strike at or beyond the {lvl} of <b>{c["anchor_only"]:,.2f}</b>. '
                    f'Only the strikes and premiums are missing.'))
            else:
                body.append(_message_row_html(c["error"]))
            continue
        if zone == "put_block":
            body.append(_message_row_html(ZONES["put_block"]["note"], ACCENT_RED))
            continue
        if not c.get("spreads"):
            body.append(_message_row_html(
                f'Nothing priced. Either no spread showed a positive credit at these '
                f'strikes, or every candidate came out worse than <b>1 : {MAX_RR:.0f}</b> '
                f'and was dropped \u2014 itself a read: the credit at the level the study '
                f'validated is too thin to be worth the risk today.'))
            continue

        rows = sorted(c["spreads"], key=lambda x: (x["rr"] if x["rr"] else 9e9))
        best_credit = max(x["credit"] for x in rows)
        body += [spread_row_html(sp, best_credit, i == 0) for i, sp in enumerate(rows)]

    return (
        f'<div style="overflow-x:auto">'
        f'<table style="width:100%;border-collapse:collapse;background:{BG_PANEL};'
        f'border:1px solid {BORDER_COLOR};border-radius:10px">'
        f'<thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
    )


def _scan_one(cfg: dict) -> dict:
    """Everything the card needs for one underlying, or the reason it can't.

    The ZONE is always set whenever there is a morning range, because it is a
    property of that range alone and owes nothing to the option chain. The
    first live run returned a card carrying a state but no zone, and the
    renderer then looked up ZONES[None] and died with a KeyError whose string
    is the word "None" — a crash reported as a message that says nothing.
    Losing the chain should cost you the strikes, not the read.
    """
    src, note = cfg, None
    state = morning_state(cfg["spot_symbol"], cfg.get("scale", 1.0))
    chain, reason = (todays_chain(cfg["chain_symbol"]) if state else (None, "no morning range"))

    # SPX falls back to SPY x10 only when the index chain genuinely isn't
    # there — and the card says so, rather than implying index strikes.
    if (state is None or chain is None) and cfg.get("fallback"):
        fb = cfg["fallback"]
        fb_state = morning_state(fb["spot_symbol"], fb["scale"])
        fb_chain, fb_reason = todays_chain(fb["chain_symbol"])
        if fb_state and fb_chain:
            src = {**cfg, **fb}
            state, chain, reason = fb_state, fb_chain, None
            note = (f'Quoted from {fb["chain_symbol"]} × {fb["scale"]:.0f} — no '
                    f'{cfg["chain_symbol"]} chain today. Strikes are the ETF grid scaled up, '
                    f'not real index strikes.')

    # Display metadata rides along on every return shape, so a row that
    # fails still shows its name, its description and — critically — its
    # UNVALIDATED badge rather than silently losing the caveat.
    meta = {"key": cfg["key"], "label": cfg["label"],
            "desc": cfg.get("desc", ""), "validated": cfg.get("validated", True)}

    if state is None:
        why = ("No intraday bars for today yet." if cfg.get("daily", True) else
               f'No intraday bars for today yet. ({cfg["label"]} does not list an '
               f'expiry every weekday, so it is only a 0DTE name on its expiry days.)')
        return {**meta, "error": why}

    zone = zone_for(state["pos_pct"])
    base = {**meta, "state": state, "zone": zone, "note": note, "spreads": []}

    if chain is None:
        # The range, the zone and the anchor level are all still worth showing.
        anchor = state["low"] if zone.startswith("put") else state["high"]
        return {**base,
                "error": f"No 0DTE chain — {reason}",
                "anchor_only": anchor}

    puts, calls, expiry = chain
    spreads = []
    if zone in ("put_green", "put_amber"):
        spreads = build_spreads("put", puts, state["low"], state["spot"], src.get("scale", 1.0))
    elif zone == "call":
        spreads = build_spreads("call", calls, state["high"], state["spot"], src.get("scale", 1.0))
    return {**base, "spreads": spreads, "expiry": expiry}


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
        f'<b>Risk : Reward</b> is an outcome to read — capped at <b>1 : {MAX_RR:.0f}</b>, '
        f'below which the credit is too thin to justify the risk whatever the win rate.<br>'
        f'<b style="color:{TEXT_PRIMARY}">Two tables.</b> '
        f'<b style="color:{TEXT_PRIMARY}">Daily expiries</b> (QQQ, SPX, IWM) list an expiry '
        f'every weekday, so the setup is available every session. '
        f'<b style="color:{TEXT_PRIMARY}">Non-daily expiries</b> (SMH, GLD, TQQQ, SOXL, NVDA, '
        f'AVGO, TSLA, META, GOOGL, MSFT) are only a 0DTE trade on their own expiry days — on '
        f'any other day the row says so and offers nothing, because a later expiry has an '
        f'overnight session inside it and that is exactly what this setup assumes away.<br>'
        f'Everything except QQQ and SPX is badged <b style="color:{ACCENT_RED}">UNVALIDATED</b>: '
        f'the gate is transplanted to it, never measured on it. '
        f'<span style="color:{GOLD}">The accumulator is now recording every session so those '
        f'badges can eventually come off — see scanners/range_history.py.</span></div>',
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
        with st.spinner(f"Reading the morning range and today's chains for {len(TICKERS)} underlyings…"):
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

    by_key = {c["key"]: c for c in cards}
    for spec in TABLES:
        group = [by_key[t["key"]] for t in TICKERS
                 if t["cadence"] == spec["cadence"] and t["key"] in by_key]
        if not group:
            continue
        st.markdown(
            f'<div style="margin:18px 0 6px 0">'
            f'<span style="color:{TEXT_PRIMARY};font-size:14px;font-weight:800;'
            f'letter-spacing:.02em">{spec["title"]}</span>'
            f'<span style="color:{TEXT_MUTED};font-size:10.5px;margin-left:10px">'
            f'{spec["blurb"]}</span></div>',
            unsafe_allow_html=True)
        st.markdown(spreads_table_html(group), unsafe_allow_html=True)

    st.markdown(
        f'<div style="display:flex;flex-wrap:wrap;gap:16px;margin-top:8px;'
        f'color:{TEXT_MUTED};font-size:10.5px">'
        f'<span><b style="color:{GOLD}">\u2605</b> best risk\u2009:\u2009reward in that block '
        f'(the sort key)</span>'
        f'<span>\U0001F4B0 richest premiums for that underlying '
        f'\u2014 \U0001F4B0\U0001F4B0\U0001F4B0 \u2265 90% of its best credit, '
        f'\U0001F4B0\U0001F4B0 \u2265 75%, \U0001F4B0 \u2265 55%</span>'
        f'<span><b style="color:{ACCENT_RED}">UNVALIDATED</b> the 70% gate was measured on '
        f'QQQ and SPY only</span>'
        f'<span>Cushion = distance from spot to the short strike</span></div>',
        unsafe_allow_html=True)

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
