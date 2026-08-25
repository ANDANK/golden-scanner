# scanners/home.py — Market Overview (rewritten 2026-07-23)
#
# Layout:
#   ┌─ Market-regime header (Risk-On/Mixed/Off · indices · breadth) ─┐
#   ├─ Tab 1  🎯 Best Scanners  — the 6 keeper scanners over a universe
#   ├─ Tab 2  🔄 Sector Rotation — RRG-style flows (preserved from the old page)
#   ├─ Tab 3  🔍 Overkill Check — WaveTrend dot + Volume Profile confluence
#   │         scan on any user-entered ticker(s) (see scanners/overkill_check.py)
#   ├─ Tab 4  📺 OverKill Shorts — watch-list auto-extracted from the YouTube
#   │         shorts (data/overkill_shorts.json, refreshed twice daily by
#   │         scripts/overkill_shorts_scan.py — see .github/workflows/refresh_overkill.yml)
#   ├─ Tab 5  📊 Shorts Perf — how those auto-extracted picks actually did,
#   │         scored from the price captured on the day of each call
#   │         (see scanners/overkill_shorts_perf.py)
#   └─ Tab 6  🎯 Shorts Backtest — performance of a HAND-CURATED list of
#             OverKill scanner alerts (Golden Dot / Weekly / Monthly / Daily).
#             Despite sitting next to Shorts Perf this reads a completely
#             different source — see scanners/overkill_performance.py. Moved
#             here from the Admin-only nav, now visible to all users.
#
# The Fear & Greed gauge and the whole sidebar live in app.py — untouched here.
# Backup of the previous command-center page: scanners/home_backup_2026-07-23.py

from __future__ import annotations
import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json, os, sys
from datetime import datetime
import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import *
from utils import section_header, calc_sma
from data_loader import get_price_history, get_market_overview, prefetch_tickers
from scanners import overkill_check
from scanners import overkill_performance
from scanners import overkill_shorts_perf
from scanners import scan_history
from scanners.ui_tables import sortable_table_html

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

ORANGE = "#F97316"
PURPLE = "#A78BFA"
MINT   = "#34D399"


# ══════════════════════════════════════════════════════════════════════════════
# SMALL HTML HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{alpha})"


def _chip(text: str, color: str, bg_alpha: float = 0.12) -> str:
    return (f'<span style="background:{_rgba(color, bg_alpha)};color:{color};'
            f'border:1px solid {color}44;font-size:10px;font-weight:700;'
            f'padding:2px 9px;border-radius:12px;white-space:nowrap">{text}</span>')


def _card(title: str, icon: str, color: str, body_html: str,
          subtitle: str = "", max_height: int = 0) -> str:
    scroll = (f"max-height:{max_height}px;overflow-y:auto;" if max_height else "")
    return (
        f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};'
        f'border-radius:14px;overflow:hidden;margin-bottom:14px">'
        f'<div style="background:linear-gradient(90deg,{_rgba(color,0.22)},{_rgba(color,0.04)});'
        f'border-bottom:2px solid {color}55;padding:10px 16px;'
        f'display:flex;align-items:baseline;gap:10px">'
        f'<span style="font-size:16px">{icon}</span>'
        f'<span style="color:{color};font-size:13px;font-weight:800;'
        f'letter-spacing:0.6px;text-transform:uppercase">{title}</span>'
        + (f'<span style="color:{TEXT_MUTED};font-size:10px;margin-left:auto">{subtitle}</span>'
           if subtitle else '')
        + f'</div>'
        f'<div style="padding:10px 12px;{scroll}">{body_html}</div>'
        f'</div>'
    )


_TD = "padding:7px 10px;border-bottom:1px solid #2A2A3A33;vertical-align:middle;white-space:nowrap"
_TH = (f"color:{TEXT_MUTED};font-size:9px;font-weight:700;text-transform:uppercase;"
       f"letter-spacing:0.6px;padding:6px 10px;text-align:left;white-space:nowrap;"
       f"border-bottom:1.5px solid #2A2A3A66;position:sticky;top:0;background:{BG_PANEL}")


def _mono(v: str, color: str = TEXT_PRIMARY, size: int = 12, bold: bool = False) -> str:
    w = "700" if bold else "500"
    return (f'<span style="color:{color};font-family:\'DM Mono\',monospace;'
            f'font-size:{size}px;font-weight:{w}">{v}</span>')




# ══════════════════════════════════════════════════════════════════════════════
# MARKET-REGIME HEADER  (kept from the original command center)
# ══════════════════════════════════════════════════════════════════════════════

_SECTOR_ETFS = ["XLK","XLF","XLV","XLI","XLE","XLY","XLP","XLC","XLB","XLRE","XLU"]


@st.cache_data(ttl=1800, show_spinner=False)
def _regime_data() -> dict:
    """SPY/QQQ trend, VIX, and sector breadth. Cached 30 min."""
    out = {"ok": False}
    try:
        spy = get_price_history("SPY", period="1y")["Close"].squeeze()
        qqq = get_price_history("QQQ", period="1y")["Close"].squeeze()
        out["spy_v200"] = (float(spy.iloc[-1]) / float(calc_sma(spy, 200).iloc[-1]) - 1) * 100
        out["qqq_v200"] = (float(qqq.iloc[-1]) / float(calc_sma(qqq, 200).iloc[-1]) - 1) * 100
        out["spy_chg"]  = (float(spy.iloc[-1]) / float(spy.iloc[-2]) - 1) * 100
        out["qqq_chg"]  = (float(qqq.iloc[-1]) / float(qqq.iloc[-2]) - 1) * 100
        out["ok"] = True
    except Exception:
        return out
    try:
        vix = get_price_history("^VIX", period="3mo")["Close"].squeeze()
        out["vix"] = float(vix.iloc[-1])
    except Exception:
        out["vix"] = 20.0
    above = total = 0
    for t in _SECTOR_ETFS:
        try:
            c = get_price_history(t, period="1y")["Close"].squeeze()
            total += 1
            if float(c.iloc[-1]) > float(calc_sma(c, 50).iloc[-1]):
                above += 1
        except Exception:
            continue
    out["breadth"] = round(above / total * 100) if total else 50
    return out


def _render_regime_bar():
    d = _regime_data()
    try:
        mkt = get_market_overview()
    except Exception:
        mkt = {}

    if not d.get("ok"):
        st.warning("Market data unavailable right now — the tabs below still work.")
        return

    vix, breadth = d["vix"], d["breadth"]
    risk_on  = d["spy_v200"] > 0 and d["qqq_v200"] > 0 and vix < 22 and breadth >= 55
    risk_off = d["spy_v200"] < 0 or vix > 30 or breadth < 30
    if risk_on:
        verdict, v_col, v_note = "🟢 RISK-ON", ACCENT_GREEN, "full size OK"
    elif risk_off:
        verdict, v_col, v_note = "🔴 RISK-OFF", ACCENT_RED, "defense — small size, tight stops"
    else:
        verdict, v_col, v_note = "🟡 MIXED", GOLD, "half size, be selective"

    def _mini(label, val, chg=None, col=None):
        c = col or (ACCENT_GREEN if (chg or 0) >= 0 else ACCENT_RED)
        chg_s = (f'<span style="color:{c};font-size:10px;font-weight:700"> {chg:+.2f}%</span>'
                 if chg is not None else '')
        return (f'<span style="white-space:nowrap"><span style="color:{TEXT_MUTED};'
                f'font-size:10px">{label}</span> '
                f'<span style="color:{TEXT_PRIMARY};font-family:\'DM Mono\',monospace;'
                f'font-size:12px;font-weight:700">{val}</span>{chg_s}</span>')

    chips = [
        _mini("SPY vs 200MA", f'{d["spy_v200"]:+.1f}%', d["spy_chg"]),
        _mini("QQQ vs 200MA", f'{d["qqq_v200"]:+.1f}%', d["qqq_chg"]),
        _mini("VIX", f"{vix:.1f}", col=(ACCENT_GREEN if vix < 20 else GOLD if vix < 28 else ACCENT_RED)),
        _mini("Breadth", f"{breadth}%",
              col=(ACCENT_GREEN if breadth >= 55 else GOLD if breadth >= 35 else ACCENT_RED)),
    ]
    for name, key in [("Gold", "Gold"), ("10Y", "10Y Yield")]:
        if key in mkt:
            chips.append(_mini(name, f'{mkt[key]["value"]:,.1f}', mkt[key]["change"]))

    st.markdown(
        f'<div style="background:linear-gradient(90deg,{_rgba(v_col,0.16)},{BG_CARD} 55%);'
        f'border:1px solid {v_col}55;border-radius:14px;padding:12px 18px;'
        f'display:flex;align-items:center;gap:22px;flex-wrap:wrap;margin-bottom:14px">'
        f'<span style="color:{v_col};font-size:17px;font-weight:900;letter-spacing:1px">{verdict}</span>'
        f'<span style="color:{TEXT_MUTED};font-size:11px;font-style:italic">{v_note}</span>'
        + "".join(chips)
        + f'</div>',
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — BEST SCANNERS  (the 6 keepers, one merged table)
# ══════════════════════════════════════════════════════════════════════════════
#
# Self-contained engine: one prefetch of 2-yr daily bars, weekly resampled
# in-memory, then each ticker is tested against all six scanners at the latest
# bar. Logic mirrors the app's own engines (validated against them).

_LABELS = ["1Mom", "2TC", "3MF", "4TS", "5RB", "6Prime", "7Square", "8Cross", "9TA"]

_SCANNER_NOTES = [
    ("1Mom",   "MACD Momentum (MTPA Table 4)", "Weekly + Daily",
     "Weekly MACD line >0 + histogram >0 and rising, AND daily MACD line >0 + histogram >0. Momentum confirmed on both timeframes."),
    ("2TC",    "Trend Continuation", "Weekly",
     "Price > rising 30-wk SMA · 10-wk SMA > 30-wk SMA · weekly RSI 60–75 · base breakout or close near weekly high · weekly volume ≥1.5×. Hold 20–60d."),
    ("3MF",    "Multi-Factor", "Daily",
     "Price > 50-SMA > 200-SMA · RSI 50–72 · MACD hist >0 · vol ≥1.1× · ATR expanding · within 2% of 20-day high · RS ≥1.0. Hold 10–30d."),
    ("4TS",    "Trend Stack", "Daily",
     "Price > EMA20 > SMA50 > SMA200 (200 rising) · RSI 55–70 · within 3% of 20-day high · vol ≥1.3× · RS ≥1.03. Hold 20–60d."),
    ("5RB",    "Reset Bounce", "Weekly",
     "Price > rising 30-wk SMA · pulled back to the 10/21-wk EMA · weekly RSI 48–62 and rising · weekly MACD turning up · reversal candle or rising volume. Hold 10–30d."),
    ("6Prime", "PRIME (MTPA Table 1)", "Weekly + Daily",
     "Weekly HH/HL or tight base · not extended · daily RSI GREEN/YELLOW · MACD > signal · vol >0.7× · price > SMA20 · |MACD| ≤1% of price (fresh cross)."),
    ("7Square", "MACD Bull ×0 — the TradingView 'green square'", "Daily · watch",
     "Fresh MACD cross above signal while the MACD line is near zero (|MACD| ≤0.5% of price), price > SMA200. Early/aggressive — weak on its own in testing, treat as a watch, not a signal."),
    ("8Cross", "EMA20 × EMA50 cross", "Daily · ·W = weekly too",
     "EMA20 crossed above EMA50 in the last ~6 bars, or is within 1% and closing in (price > SMA200). A ·W suffix means the WEEKLY EMA20/50 is also crossing or about to — higher-timeframe confirmation."),
    ("9TA", "Trend Alignment (folded in from Golden Scan)", "Daily + Weekly",
     "Fresh daily MACD cross (last 3 bars) · daily RSI 55–78 · daily ADX >18 · breaks the 8-week resistance on ≥1.2× weekly volume · above a rising 30-week SMA · liquid (>200k avg vol). Quick swing, hold 10–30d."),
]

# Star rating — flags rare, high-conviction label combos. A combo matches if the
# ticker's labels are a SUPERSET of the required set; rules are checked highest
# tier first, so a ticker matching more than one tier gets the best one.
#
# 2*/3* swapped 2026-07-29 based on 5 independent headless backtests (FTF/
# MTPA/SP500 universes, 2-5yr lookbacks, 10-45 day holds -- see
# scripts/headless_best_scanners_backtest.py): the 6Prime-based combos
# (originally 3*) underperformed the {1Mom,2TC,3MF}/{1Mom,5RB} combos
# (originally 2*) on avg excess return vs SPY in all 5 runs, no exceptions.
_STAR_RULES = [
    (frozenset({"1Mom", "4TS", "3MF"}), 4),
    (frozenset({"1Mom", "2TC", "3MF"}), 3),
    (frozenset({"1Mom", "5RB"}), 3),
    (frozenset({"4TS", "6Prime"}), 2),
    (frozenset({"1Mom", "6Prime"}), 2),
    (frozenset({"4TS", "3MF"}), 1),
    (frozenset({"2TC", "5RB"}), 1),
    (frozenset({"2TC", "1Mom"}), 1),
]


def _star_rating(labels: list) -> int:
    label_set = set(labels)
    for required, stars in _STAR_RULES:
        if required <= label_set:
            return stars
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# EDGE SCORE — replaces _STAR_RULES as what Run Scan / the email actually
# display. _STAR_RULES/_star_rating stay in place unchanged (the Backtest mode
# still validates them, and nothing here depends on removing them) — this is
# a parallel, better-evidenced system for the live-facing views specifically.
#
# _EDGE_SHORTLIST is hand-curated from 8 headless full-analysis backtests
# (FTF/MTPA/SP500 universes, 2-10yr lookbacks, 10-90d holds, run 2026-07-29 —
# see scripts/headless_best_scanners_full_analysis.py). Each entry:
#   (combo, avg_excess_pct, n, (min_hold_days, max_hold_days))
# hold_range reflects ACTUAL evidence, not a guess: several combos that look
# great at 10-30d were CONFIRMED NEGATIVE at 60d in the same backtests (see
# comments below) and are capped there rather than extrapolated.
#
# Confidence is bucketed by sample size alone (n >= 1000 -> high, >= 200 ->
# medium) since these runs only captured the mean excess return per combo,
# not its spread -- a proper standard-error-based score needs
# _aggregate_full_analysis to also track std_rel (added below) and a fresh
# batch of runs. Until then this is the honest, evidence-backed interim.
_EDGE_SHORTLIST = [
    # positive across the FULL 10-90 day range actually tested
    (frozenset({"1Mom", "8Cross"}), 0.95, 9780, (10, 90)),
    (frozenset({"3MF", "8Cross"}), 0.83, 3867, (10, 90)),
    # positive through 60d; no 90d evidence either way yet
    (frozenset({"1Mom", "5RB", "8Cross"}), 0.97, 3878, (10, 60)),
    # strong at 10-30d but CONFIRMED NEGATIVE at 60d in the FTF/5y/60d run --
    # capped here on purpose, not extrapolated past what the data showed
    (frozenset({"5RB", "8Cross"}), 0.57, 6325, (10, 30)),
    (frozenset({"3MF", "5RB"}), 0.55, 3613, (10, 30)),
    (frozenset({"1Mom", "3MF", "8Cross"}), 0.57, 1310, (10, 30)),
    (frozenset({"6Prime", "7Square", "8Cross"}), 0.47, 2978, (10, 30)),
    (frozenset({"7Square", "8Cross"}), 0.43, 10416, (10, 30)),
    # medium-confidence (200-999 samples) -- promising, thinner evidence
    (frozenset({"3MF", "5RB", "8Cross"}), 1.59, 577, (10, 30)),
    (frozenset({"3MF", "4TS", "8Cross"}), 1.26, 383, (10, 30)),
    (frozenset({"3MF", "6Prime", "8Cross"}), 1.10, 214, (10, 30)),
]

_EDGE_MIN_N_HIGH = 1000
_EDGE_MIN_N_MEDIUM = 200


def _edge_verdict(labels: list) -> dict:
    """Finds the best-matching shortlist combo for a ticker's CURRENT matched
    labels (same 'is a subset of what fired' logic as _star_rating). Returns
    a plain-language verdict plus the numbers behind it.

    'Untested combo' means nothing on the shortlist matched -- and note it
    describes the SIGNAL COMBINATION, not the ticker. Eight labels give 255
    possible combinations and only 11 have been backtested with enough
    samples to measure, so most combinations simply have no evidence either
    way. It is not a judgement that the setup is weak, and it says nothing
    about how long the ticker has been on the list. (It used to be called
    'Too New', which read as a statement about the stock's age and caused
    exactly that confusion.)

    A ticker can match several shortlist combos at once (e.g. matching both
    1Mom+8Cross and a smaller-sample triple that happens to have a bigger raw
    number) -- confidence tier wins first, score only breaks ties within the
    same tier, so a flashier thin-sample number never outranks a validated
    high-confidence one. (Not "first match wins" by list order -- checked and
    fixed after a test caught exactly this ordering bug.)"""
    label_set = frozenset(labels)
    matches = [entry for entry in _EDGE_SHORTLIST if entry[0] <= label_set]
    if not matches:
        return dict(verdict="Untested combo", confidence=None, score=None, n=None,
                   hold_range=None, combo=None)
    combo, score, n, hold_range = max(
        matches, key=lambda e: (e[2] >= _EDGE_MIN_N_HIGH, e[1])
    )
    confidence = "high" if n >= _EDGE_MIN_N_HIGH else "medium"
    verdict = "Strong Setup" if confidence == "high" else "Mixed Signal"
    return dict(
        verdict=verdict, confidence=confidence, score=score, n=n,
        hold_range=hold_range,
        combo="+".join(sorted(combo, key=_LABELS.index)),
    )


_UNIVERSE_CHOICES = {
    "FTF Universe (~500 · full S&P 500 + ETFs)": "FTF",
    "MTPA 200 (stock-heavy)": "MTPA",
    "S&P 500 sample (200)": "SP500",
}


def _ema(s, n): return s.ewm(span=n, adjust=False).mean()
def _sma(s, n): return s.rolling(n, min_periods=1).mean()


def _rsi(s, n=14):
    d = s.diff()
    g = d.clip(lower=0); l = (-d.clip(upper=0))
    ag = g.ewm(alpha=1/n, adjust=False).mean(); al = l.ewm(alpha=1/n, adjust=False).mean()
    return (100 - 100 / (1 + ag / al.replace(0, np.nan))).fillna(50)


def _macd(s):
    m = _ema(s, 12) - _ema(s, 26); sig = _ema(m, 9)
    return m, sig, m - sig


def _evaluate(df: pd.DataFrame, spy_close: pd.Series) -> dict | None:
    """Return {labels, snapshot} if any of the 6 scanners fire on the last bar, else None."""
    try:
        if isinstance(df.columns, pd.MultiIndex):
            df = df.copy(); df.columns = df.columns.get_level_values(0)
        # Drop today's still-forming bar during market hours — its partial volume
        # and price would otherwise suppress the volume-gated and weekly scanners.
        try:
            now_et = datetime.now(pytz.timezone("US/Eastern"))
            if (pd.Timestamp(df.index[-1]).date() == now_et.date()
                    and now_et.weekday() < 5 and now_et.hour < 16):
                df = df.iloc[:-1]
        except Exception:
            pass
        c = df["Close"].dropna()
        if len(c) < 210:
            return None
        h, l, v = df["High"], df["Low"], df["Volume"]
        px = float(c.iloc[-1])

        sma9, sma20, sma50 = _sma(c, 9), _sma(c, 20), _sma(c, 50)
        sma200, ema20, ema50d = _sma(c, 200), _ema(c, 20), _ema(c, 50)
        macd, sig, hist = _macd(c)
        rsi = _rsi(c)
        volr = float((v / v.shift(1).rolling(20).mean()).iloc[-1])
        atr_tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        atr = atr_tr.rolling(14).mean()
        atr_exp = float(atr.iloc[-1]) > float(atr.rolling(20).mean().iloc[-1])
        r20max = float(c.rolling(20).max().iloc[-1])
        within2 = px >= r20max * 0.98
        within3 = px >= r20max * 0.97
        is20h = px >= r20max
        s200_rise = float(sma200.iloc[-1]) > float(sma200.iloc[-11])
        sp = spy_close.reindex(c.index).ffill()
        try:
            rs = (float((c.iloc[-1] / c.iloc[-64]) / (sp.iloc[-1] / sp.iloc[-64]))
                  if len(c) >= 64 and pd.notna(sp.iloc[-1]) and pd.notna(sp.iloc[-64]) else 1.0)
        except Exception:
            rs = 1.0
        macd_v, hist_v = float(macd.iloc[-1]), float(hist.iloc[-1])
        rsi_d = float(rsi.iloc[-1])

        # ── Weekly resample ──
        wk = df.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min",
                                       "Close": "last", "Volume": "sum"}).dropna(subset=["Close"])
        if len(wk) < 34:
            return None
        wc, wh, wl, wo, wv = wk["Close"], wk["High"], wk["Low"], wk["Open"], wk["Volume"]
        wsma30, wsma10 = _sma(wc, 30), _sma(wc, 10)
        wema10, wema21, wema20, wema50 = _ema(wc, 10), _ema(wc, 21), _ema(wc, 20), _ema(wc, 50)
        wrsi = _rsi(wc)
        wmacd, wsig, whist = _macd(wc)
        wpx = float(wc.iloc[-1])
        w30 = float(wsma30.iloc[-1]); w30_rise = w30 > float(wsma30.iloc[-5])
        w10_30 = float(wsma10.iloc[-1]) > w30
        w_ext = wpx > float(wema20.iloc[-1]) * 1.10
        wrsi_v = float(wrsi.iloc[-1])
        whist_v = float(whist.iloc[-1]); whist_p = float(whist.iloc[-2])
        wmacd_v = float(wmacd.iloc[-1])
        # patterns
        hh6 = all(float(wh.iloc[-i]) > float(wh.iloc[-i-1]) for i in range(1, 6))
        ll6 = all(float(wl.iloc[-i]) > float(wl.iloc[-i-1]) for i in range(1, 6))
        watr = (wh - wl) / wc * 100
        tight5 = float(watr.iloc[-5:].mean()) < 4.5
        pattern = (hh6 and ll6) or tight5
        res8 = wpx > float(wc.iloc[-9:-1].max())
        w20 = wc.iloc[-21:-1]
        consol = wpx > float(w20.max()) and (float(w20.max()) - float(w20.min())) / float(w20.min()) <= 0.15 if len(w20) else False
        near_hi = wpx >= float(wh.iloc[-1]) * 0.96
        e10, e21 = float(wema10.iloc[-1]), float(wema21.iloc[-1])
        t10 = float(wl.iloc[-1]) <= e10 * 1.025 and wpx >= e10 * 0.975
        t21 = float(wl.iloc[-1]) <= e21 * 1.025 and wpx >= e21 * 0.975
        rsi_reset = 48 <= wrsi_v <= 62 and wrsi_v > float(wrsi.iloc[-4])
        macd_turn = (whist_p < 0 and whist_v >= 0) or (whist_v > 0)
        rev = wpx > float(wo.iloc[-1]) and (float(wh.iloc[-1]) - float(wl.iloc[-1])) > 0 and \
            (wpx - float(wl.iloc[-1])) / (float(wh.iloc[-1]) - float(wl.iloc[-1])) >= 0.6
        volup = float(wv.iloc[-1]) > float(wv.iloc[-2])
        wvolr = float(wv.iloc[-1]) / float(wv.iloc[-21:-1].mean()) if len(wv) >= 21 else 1.0
        macdmom_w = wmacd_v > 0 and whist_v > 0 and whist_v > whist_p

        # ── daily helpers for gates ──
        c_sma50, c_sma200 = float(sma50.iloc[-1]), float(sma200.iloc[-1])
        c_ema20, c_sma20, c_sma9 = float(ema20.iloc[-1]), float(sma20.iloc[-1]), float(sma9.iloc[-1])
        c_ema50d = float(ema50d.iloc[-1])
        rsi_rise3 = rsi_d > float(rsi.iloc[-4])
        gy = (50 <= rsi_d <= 70 and rsi_rise3) or (40 <= rsi_d < 50 and rsi_rise3)

        # ── ADX(14) + daily MACD fresh cross + liquidity (for 9TA Trend Align) ──
        _up = h.diff(); _dn = -l.diff()
        _plus_dm = _up.where((_up > _dn) & (_up > 0), 0.0)
        _minus_dm = _dn.where((_dn > _up) & (_dn > 0), 0.0)
        _pdi = 100 * (_plus_dm.rolling(14).mean() / atr)
        _mdi = 100 * (_minus_dm.rolling(14).mean() / atr)
        _dx = 100 * (_pdi - _mdi).abs() / (_pdi + _mdi).replace(0, np.nan)
        _adx = float(_dx.rolling(14).mean().iloc[-1])
        adx_v = _adx if pd.notna(_adx) else 0.0
        fresh_cross3 = (
            (float(hist.iloc[-2]) <= 0 and hist_v > 0)
            or (float(hist.iloc[-3]) <= 0 and float(hist.iloc[-2]) > 0)
            or (float(hist.iloc[-4]) <= 0 and float(hist.iloc[-3]) > 0)
        )
        avg_dvol = float(v.iloc[-21:-1].mean()) if len(v) > 21 else float(v.mean())

        # ── the 6 scanners ──
        labels = []
        if macdmom_w and macd_v > 0 and hist_v > 0:
            labels.append("1Mom")
        if (wpx > w30 and w30_rise and w10_30 and 60 <= wrsi_v <= 75
                and (consol or near_hi) and wvolr >= 1.5):
            labels.append("2TC")
        if (px > c_sma50 > c_sma200 and 50 <= rsi_d <= 72 and hist_v > 0
                and volr >= 1.1 and atr_exp and within2 and rs >= 1.0):
            labels.append("3MF")
        if (px > c_ema20 > c_sma50 > c_sma200 and s200_rise and 55 <= rsi_d <= 70
                and within3 and volr >= 1.3 and rs >= 1.03):
            labels.append("4TS")
        if (wpx > w30 and w30_rise and (t10 or t21) and rsi_reset
                and macd_turn and (rev or volup)):
            labels.append("5RB")
        if (pattern and not w_ext and gy and hist_v > 0 and volr > 0.7
                and px > c_sma20 and abs(macd_v) <= px * 0.01):
            labels.append("6Prime")

        # 7Square — MACD bull cross above signal near zero (TradingView "green square")
        cross_recent = hist_v > 0 and float(hist.iloc[-4:-1].min()) <= 0
        if cross_recent and abs(macd_v) <= px * 0.005 and px > c_sma200:
            labels.append("7Square")

        # 8Cross — daily EMA20 crossing above EMA50 (crossed in last ~6 bars OR about to);
        # x8_weekly flags the same event on the weekly EMA20/50 (shown as ·W).
        diffD = ema20 - ema50d
        d_now = float(diffD.iloc[-1])
        crossedD = d_now > 0 and float(diffD.iloc[-7:-1].min()) <= 0
        aboutD = (d_now < 0 and c_ema50d > 0 and abs(d_now) / c_ema50d <= 0.01
                  and d_now > float(diffD.iloc[-4]))
        diffW = wema20 - wema50
        w_now = float(diffW.iloc[-1]); w_e50 = float(wema50.iloc[-1])
        crossedW = w_now > 0 and float(diffW.iloc[-4:-1].min()) <= 0
        aboutW = (w_now < 0 and w_e50 > 0 and abs(w_now) / w_e50 <= 0.01
                  and w_now > float(diffW.iloc[-3]))
        x8_weekly = crossedW or aboutW
        if (crossedD or aboutD) and px > c_sma200:
            labels.append("8Cross")

        # 9TA — Trend Alignment, folded in from Golden Scan. Fresh daily MACD cross
        # + daily RSI 55-78 + daily ADX>18 + 8-week resistance break on ≥1.2× weekly
        # volume + above a rising 30-week SMA + liquidity.
        if (fresh_cross3 and 55 <= rsi_d <= 78 and adx_v > 18
                and res8 and wvolr >= 1.2 and wpx > w30 and w30_rise
                and avg_dvol > 200_000):
            labels.append("9TA")

        if not labels:
            return None

        zone = ("Positive" if macd_v > px * 0.005 else
                "Negative" if macd_v < -px * 0.005 else "Near Zero")
        flags = []
        if px >= float(c.max()) * 0.97: flags.append("Near 52W Hi")
        if volr >= 1.5:                 flags.append("Vol Spike")
        _wema20v = float(wema20.iloc[-1])
        ext_pct_w = (wpx / _wema20v - 1) * 100 if _wema20v > 0 else 0.0
        if ext_pct_w > 5:               flags.append(f"Ext +{ext_pct_w:.0f}%")
        if is20h:                       flags.append("20D High")

        chg = (px / float(c.iloc[-2]) - 1) * 100
        return {
            "labels": labels,
            "snap": {
                "Ticker": None, "Price": round(px, 2), "Chg": round(chg, 2),
                "RSI_W": round(wrsi_v, 0), "RSI_D": round(rsi_d, 0),
                "MACD>Sig": hist_v > 0, "MACD Zone": zone,
                ">SMA9": px > c_sma9, ">SMA20": px > c_sma20,
                "Vol Ratio": round(volr, 2), "RS vs SPY": round(rs, 3),
                "Flags": flags, "x8_weekly": bool(x8_weekly),
                "atr_val": round(float(atr.iloc[-1]), 4),
            },
        }
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def _resolve_universe(kind: str) -> list:
    if kind == "MTPA":
        return list(MTPA_200)
    if kind == "SP500":
        return list(SP500_SAMPLE[:200])
    try:
        return list(FTF_UNIVERSE)
    except Exception:
        return list(SP500_SAMPLE)


def _run_best_scanners(universe: list) -> pd.DataFrame:
    """Run all 6 keepers over the universe. Returns one row per flagged ticker."""
    prog = st.progress(0.0, text="Prefetching 2-yr daily bars…")
    prefetch_tickers(universe + ["SPY"], "2y", "1d")
    try:
        spy_close = get_price_history("SPY", period="2y")["Close"].squeeze()
    except Exception:
        spy_close = pd.Series(dtype=float)

    rows = []
    n = len(universe)
    for i, t in enumerate(universe):
        if i % 5 == 0 or i == n - 1:
            prog.progress((i + 1) / n, text=f"Scanning {t} ({i+1}/{n})")
        try:
            df = get_price_history(t, period="2y")
            if df is None or df.empty:
                continue
            res = _evaluate(df, spy_close)
            if res:
                snap = res["snap"]; snap["Ticker"] = t
                scan_s = " · ".join(sorted(res["labels"], key=lambda x: _LABELS.index(x)))
                if snap.get("x8_weekly") and "8Cross" in res["labels"]:
                    scan_s = scan_s.replace("8Cross", "8Cross·W")
                snap["Scanners"] = scan_s
                snap["_count"] = len(res["labels"])
                snap["_stars"] = _star_rating(res["labels"])
                edge = _edge_verdict(res["labels"])
                snap["_verdict"] = edge["verdict"]
                snap["_confidence"] = edge["confidence"]
                snap["_edge_score"] = edge["score"]
                snap["_edge_n"] = edge["n"]
                snap["_hold_range"] = edge["hold_range"]
                snap["_combo"] = edge["combo"]
                # Holding horizon (Quick vs Long) + ATR risk plan, scaled by horizon.
                hz, hlo, hhi = _horizon_of(res["labels"], edge["hold_range"])
                snap["_horizon"] = hz
                snap["_hold_lo"] = hlo
                snap["_hold_hi"] = hhi
                snap["_plan"] = _risk_plan(snap["Price"], snap.get("atr_val"), hz)
                rows.append(snap)
        except Exception:
            continue
    prog.empty()

    df_out = pd.DataFrame(rows)
    if not df_out.empty:
        # Strong Setup first, then Mixed Signal, then Untested combo; within a tier,
        # higher edge score first. Replaces the old _count-based sort now that
        # raw scanner count is known not to be a reliable ranker (see the
        # cross-run analysis -- it doesn't move monotonically either way).
        verdict_rank = {"Strong Setup": 2, "Mixed Signal": 1, "Untested combo": 0}
        df_out["_verdict_rank"] = df_out["_verdict"].map(verdict_rank)
        df_out = df_out.sort_values(
            ["_verdict_rank", "_edge_score"], ascending=[False, False], na_position="last"
        ).drop(columns="_verdict_rank").reset_index(drop=True)
    return df_out


def _annotate_history(df: pd.DataFrame, tag: str) -> pd.DataFrame:
    """Read-only: tags each row with _is_new / _first_found from the stored
    scan-history JSON (data/best_scanners/*.json, written once daily by the
    Best Scanners email GitHub Action) and re-sorts tier -> New -> Edge
    Score. The interactive app never writes its own snapshot -- only the
    once-daily automated run does -- so "New" means the same thing here as
    it does in the email. Stamps the US/Eastern MARKET day, not UTC: the email
    action runs in the morning (ET date == UTC date then, so the stored history
    still lines up), whereas an evening interactive run in UTC rolls a day ahead
    and would show tomorrow's date on today's fresh picks."""
    if df.empty:
        return df
    today = datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")
    today_rows = [{"ticker": t} for t in df["Ticker"]]
    history = scan_history.annotate_new_and_first_found("best_scanners", tag, today, today_rows)
    df = df.copy()
    df["_is_new"] = df["Ticker"].map(lambda t: history.get(t, {}).get("is_new", True))
    df["_first_found"] = df["Ticker"].map(lambda t: history.get(t, {}).get("first_found", today))
    verdict_rank = {"Strong Setup": 2, "Mixed Signal": 1, "Untested combo": 0}
    df["_verdict_rank"] = df["_verdict"].map(verdict_rank)
    df = df.sort_values(
        ["_verdict_rank", "_is_new", "_edge_score"], ascending=[False, False, False], na_position="last"
    ).drop(columns="_verdict_rank").reset_index(drop=True)
    return df


_SORT_COLUMNS = {
    # All three keys rank by Verdict tier first (Strong Setup > Mixed Signal > Untested combo),
    # New tickers next within a tier, then Edge Score -- a thin-sample combo's flashy
    # score can no longer outrank a well-validated one just because "Edge Score" was
    # picked, and a fresh signal always rises above a day-5 repeat in the same tier.
    "Verdict": ["_verdict_rank_n", "_is_new", "_edge_score_n"],
    "Edge Score": ["_verdict_rank_n", "_is_new", "_edge_score_n"],
    "Ticker": "Ticker",
    "Price": "Price",
    "Chg %": "Chg %",
    "RSI D": "RSI D",
    "Vol×": "Vol×",
    "RS·SPY": "RS·SPY",
}

_VERDICT_COLOR = {"Strong Setup": ACCENT_GREEN, "Mixed Signal": GOLD, "Untested combo": TEXT_MUTED}
_VERDICT_RANK = {"Strong Setup": 2, "Mixed Signal": 1, "Untested combo": 0}


def _hold_range_text(hold_range) -> str:
    if not hold_range or (isinstance(hold_range, float) and pd.isna(hold_range)):
        return "—"
    lo, hi = hold_range
    return f"{lo}-{hi}d"


def _fmt_found_date(date_str) -> str:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%b %d")
    except Exception:
        return date_str or "—"


# ── Holding-horizon (Quick wins vs Long runs) + ATR risk framing ─────────────
# Per-scanner nominal hold windows (trading days), used when no backtested combo
# hold applies (Untested combos) so every pick still gets a horizon. Values match
# the per-scanner notes above and combined_scanner's SCANNER_META.
_SCANNER_HOLD = {
    "1Mom": (10, 30), "2TC": (20, 60), "3MF": (10, 30), "4TS": (20, 60),
    "5RB": (10, 30), "6Prime": (20, 60), "7Square": (10, 30), "8Cross": (10, 30),
    "9TA": (10, 30),
}
_QUICK_MAX_DAYS = 30   # effective max hold <= this = quick-win swing; longer = long run


def _effective_hold(labels, hold_range):
    """Backtested combo hold wins; otherwise span the firing scanners' windows."""
    if hold_range and not (isinstance(hold_range, float) and pd.isna(hold_range)):
        return int(hold_range[0]), int(hold_range[1])
    los = [_SCANNER_HOLD[x][0] for x in labels if x in _SCANNER_HOLD]
    his = [_SCANNER_HOLD[x][1] for x in labels if x in _SCANNER_HOLD]
    return (min(los), max(his)) if his else (10, 30)


def _horizon_of(labels, hold_range):
    """('Quick'|'Long', lo, hi) — Quick when the effective max hold is <= 30d."""
    lo, hi = _effective_hold(labels, hold_range)
    return ("Quick" if hi <= _QUICK_MAX_DAYS else "Long"), lo, hi


# ATR stop/target multiples scaled by horizon. Reward:risk is a fixed 2:1 either
# way; long runs simply get wider absolute stops/targets to fit their bigger move.
_RISK_MULT = {"Quick": (1.5, 3.0), "Long": (2.5, 5.0)}


def _risk_plan(px, atr, horizon):
    """Entry/stop/target/RR/risk% from ATR, or None if inputs are unusable."""
    try:
        px = float(px); atr = float(atr)
    except (TypeError, ValueError):
        return None
    if not (px > 0 and atr > 0):
        return None
    ks, kt = _RISK_MULT.get(horizon, (2.0, 4.0))
    stop = px - ks * atr
    if stop <= 0:
        return None
    return {"entry": round(px, 2), "stop": round(stop, 2), "target": round(px + kt * atr, 2),
            "rr": round(kt / ks, 1), "risk_pct": round((px - stop) / px * 100, 1)}


def _horizon_badge(horizon, lo, hi):
    return f'{"⚡" if horizon == "Quick" else "🐢"} {lo}-{hi}d'


def _plan_text(plan):
    if not isinstance(plan, dict):
        return "—"
    return (f'<span style="color:{ACCENT_RED}">⛔${plan["stop"]:,.2f}</span> '
            f'<span style="color:{ACCENT_GREEN}">🎯${plan["target"]:,.2f}</span> '
            f'<span style="color:{TEXT_MUTED};font-size:10px">R{plan["rr"]:.0f}·−{plan["risk_pct"]:.1f}%</span>')


_ROW_COL_RATIOS = [0.35, 0.85, 0.6, 0.55, 0.55, 0.5, 0.55, 0.5, 1.4, 0.7, 0.9, 0.6, 0.8, 1.15]
_ROW_HEADERS = ["", "Verdict", "Horizon", "Date", "Ticker", "Price", "Chg %", "Scanners", "RSI W/D",
                "MACD", ">SMA 9/20", "Vol× / RS", "Flags", "Stop→Tgt"]


def _select_ticker_cb(ticker: str, all_tickers: list):
    """on_change for a row checkbox — enforces single-selection: checking one
    unchecks the rest; unchecking the active one is ignored (always exactly
    one ticker selected, since the chart needs one)."""
    key = f"home_best_chk_{ticker}"
    if st.session_state.get(key):
        for t in all_tickers:
            if t != ticker:
                st.session_state[f"home_best_chk_{t}"] = False
        st.session_state["home_best_selected_ticker"] = ticker
    elif st.session_state.get("home_best_selected_ticker") == ticker:
        st.session_state[key] = True


def _render_best_table(df: pd.DataFrame):
    """Sortable table with a per-row checkbox (leftmost column, single-select)
    that picks which ticker charts below.

    Streamlit's interactive st.dataframe grid renders on an HTML5 canvas;
    on this app's Streamlit Cloud deployment that canvas never paints
    (confirmed: double-clicking a cell still opens the real value in an
    editor, so data/interaction work — only the paint step doesn't,
    consistently across browsers). A raw HTML checkbox has the same
    problem in reverse (paints fine, but can't call back into Python), so
    each row is rendered as real Streamlit widgets (checkbox + markdown)
    laid out via st.columns — the only combination that's both interactive
    and guaranteed to render here. Trade-off: no fixed-height scroll
    container (native widgets can't be wrapped in one across separate
    st.markdown calls), so the table now grows with the page instead of
    scrolling internally.
    """
    view = pd.DataFrame({
        "Verdict": df["_verdict"].astype(str),
        "_verdict_rank_n": df["_verdict"].map(_VERDICT_RANK).fillna(0),
        "Horizon": df.apply(lambda r: _horizon_badge(r.get("_horizon", "Long"),
                            r.get("_hold_lo", 10), r.get("_hold_hi", 30)), axis=1)
                   if "_horizon" in df.columns else pd.Series(["—"] * len(df)),
        "_horizon": df["_horizon"].astype(str) if "_horizon" in df.columns
                    else pd.Series(["Long"] * len(df)),
        "Trade": df["_plan"].apply(_plan_text) if "_plan" in df.columns
                 else pd.Series(["—"] * len(df)),
        "Date": df["_first_found"].apply(_fmt_found_date) if "_first_found" in df.columns
                else pd.Series(["—"] * len(df)),
        "_is_new": df["_is_new"].fillna(False).astype(bool) if "_is_new" in df.columns
                   else pd.Series([False] * len(df)),
        "_edge_score_n": pd.to_numeric(df["_edge_score"], errors="coerce").fillna(-999),
        "Ticker": df["Ticker"].astype(str),
        "Price": pd.to_numeric(df["Price"], errors="coerce"),
        "Chg %": pd.to_numeric(df["Chg"], errors="coerce"),
        "Scanners": df["Scanners"].astype(str),
        "RSI W": pd.to_numeric(df["RSI_W"], errors="coerce"),
        "RSI D": pd.to_numeric(df["RSI_D"], errors="coerce"),
        "MACD>Sig": df["MACD>Sig"].fillna(False).astype(bool),
        "MACD Zone": df["MACD Zone"].astype(str),
        ">SMA9": df[">SMA9"].fillna(False).astype(bool),
        ">SMA20": df[">SMA20"].fillna(False).astype(bool),
        "Vol×": pd.to_numeric(df["Vol Ratio"], errors="coerce"),
        "RS·SPY": pd.to_numeric(df["RS vs SPY"], errors="coerce"),
        "Flags": df["Flags"].apply(lambda x: "; ".join(x) if isinstance(x, list) else (x or "")),
    }).reset_index(drop=True)
    # A NaN gap in the underlying price data (same root cause as the earlier chart
    # bug) can otherwise leave a row with no usable Price — drop those defensively.
    view = view.dropna(subset=["Price"]).reset_index(drop=True)
    if view.empty:
        st.info("No rows to show.")
        return None

    # Quality gate — default to validated setups (Strong + Mixed), the same
    # filter the daily email uses. Without it, a single broad scanner (mostly
    # lone 1Mom on an up day) floods the table with dozens of "Untested combo"
    # single-scanner hits that have no backtested edge.
    n_untested = int((view["Verdict"] == "Untested combo").sum())
    qual = st.radio(
        "Quality", ["⭐ Validated only (Strong + Mixed)", "All (incl. Untested)"],
        horizontal=True, key="home_best_qual",
        help="Validated = combos with a backtested edge, the same set the daily email "
             "sends. 'All' adds single-scanner Untested hits (often extended momentum names).",
    )
    if qual.startswith("⭐"):
        view = view[view["Verdict"] != "Untested combo"].reset_index(drop=True)
        if n_untested:
            st.caption(f"Hiding {n_untested} Untested-combo single-scanner hit(s) — "
                       f"switch to “All” to see them.")
        if view.empty:
            st.info("No validated (Strong/Mixed) setups right now — switch to “All” "
                    "to see single-scanner hits.")
            return None

    # Quick wins vs Long runs — a distinct split by holding horizon.
    hz_filter = st.radio(
        "Horizon", ["All", "⚡ Quick wins (≤30d)", "🐢 Long runs (>30d)"],
        horizontal=True, key="home_best_hz",
        help="Quick = swing setups that historically played out in ≤30 trading days; "
             "Long = trend/position setups that need 30d+ to work.",
    )
    if hz_filter.startswith("⚡"):
        view = view[view["_horizon"] == "Quick"].reset_index(drop=True)
    elif hz_filter.startswith("🐢"):
        view = view[view["_horizon"] == "Long"].reset_index(drop=True)
    if view.empty:
        st.info("No picks in that horizon right now.")
        return None

    c1, c2 = st.columns([1.3, 0.7])
    with c1:
        sort_label = st.selectbox("Sort by", list(_SORT_COLUMNS.keys()), index=0, key="home_best_sort_col")
    with c2:
        descending = st.selectbox("Order", ["↓ High-Low", "↑ Low-High"], index=0, key="home_best_sort_dir") \
            .startswith("↓")
    view = view.sort_values(_SORT_COLUMNS[sort_label], ascending=not descending).reset_index(drop=True)

    all_tickers = view["Ticker"].tolist()
    selected = st.session_state.get("home_best_selected_ticker")
    if selected not in all_tickers:
        selected = all_tickers[0]
        st.session_state["home_best_selected_ticker"] = selected
    for t in all_tickers:
        st.session_state.setdefault(f"home_best_chk_{t}", t == selected)

    def _chg_html(v):
        col = ACCENT_GREEN if v >= 0 else ACCENT_RED
        return f'<span style="color:{col}">{v:+.1f}%</span>'

    def _b(v):
        return "✅" if v else "—"

    hdr_cols = st.columns(_ROW_COL_RATIOS)
    for c, label in zip(hdr_cols, _ROW_HEADERS):
        c.markdown(f'<div style="{_TH}">{label}</div>', unsafe_allow_html=True)

    # st.container(height=...) gives native widgets (checkboxes included) a real
    # scrollable area — ~6-7 rows visible, header stays fixed above since it's
    # rendered outside this container.
    with st.container(height=500):
        for _, r in view.iterrows():
            ticker = r["Ticker"]
            cols = st.columns(_ROW_COL_RATIOS)
            cols[0].checkbox("select", key=f"home_best_chk_{ticker}", label_visibility="collapsed",
                             on_change=_select_ticker_cb, args=(ticker, all_tickers))
            tk_style = f"color:{GOLD};font-weight:700" + (";text-decoration:underline" if ticker == selected else "")
            new_badge = ' <span title="New in the last 7 scan-days" style="font-size:10px">🆕</span>' \
                if r["_is_new"] else ""
            v_color = _VERDICT_COLOR.get(r["Verdict"], TEXT_MUTED)
            cols[1].markdown(f'<span style="color:{v_color};font-weight:600;font-size:11.5px">{r["Verdict"]}</span>',
                             unsafe_allow_html=True)
            cols[2].markdown(f'<span style="font-size:11.5px">{r["Horizon"]}</span>',
                             unsafe_allow_html=True)
            cols[3].markdown(f'<span style="color:{TEXT_MUTED};font-size:11px">{r["Date"]}</span>',
                             unsafe_allow_html=True)
            cols[4].markdown(f'<span style="{tk_style}">{ticker}</span>{new_badge}', unsafe_allow_html=True)
            cols[5].markdown(f'${r["Price"]:,.2f}')
            cols[6].markdown(_chg_html(r["Chg %"]), unsafe_allow_html=True)
            cols[7].markdown(f'<span style="font-size:11.5px">{r["Scanners"]}</span>', unsafe_allow_html=True)
            cols[8].markdown(f'W{r["RSI W"]:.0f} / D{r["RSI D"]:.0f}')
            cols[9].markdown(f'{_b(r["MACD>Sig"])} {r["MACD Zone"]}')
            cols[10].markdown(f'{_b(r[">SMA9"])} / {_b(r[">SMA20"])}')
            cols[11].markdown(f'{r["Vol×"]:.2f}x / {r["RS·SPY"]:.2f}')
            cols[12].markdown(f'<span style="color:{TEXT_MUTED};font-size:11px">{r["Flags"] or "—"}</span>',
                              unsafe_allow_html=True)
            cols[13].markdown(f'<span style="font-size:10.5px">{r["Trade"]}</span>',
                              unsafe_allow_html=True)

    return st.session_state.get("home_best_selected_ticker", selected)


def _pivot_levels(df: pd.DataFrame, order: int = 8, min_touches: int = 2,
                  cluster_pct: float = 0.015, max_levels: int = 2):
    """Support/resistance from CLUSTERED swing highs/lows on the daily chart —
    a level only counts as 'strong' if price reversed near it at least
    `min_touches` times, within `cluster_pct` of each other. A single
    isolated swing point no longer qualifies on its own (that was the old
    behavior, and why levels looked cluttered/arbitrary). Pass the full
    fetched history (not just the visible chart window) so an older but
    still-relevant level isn't missed just because it's off-screen."""
    high, low, close = df["High"].squeeze(), df["Low"].squeeze(), df["Close"].squeeze()
    win = 2 * order + 1
    roll_max = high.rolling(win, center=True, min_periods=win).max()
    roll_min = low.rolling(win, center=True, min_periods=win).min()
    piv_hi = sorted(float(p) for p in high[high == roll_max].round(2).tolist())
    piv_lo = sorted(float(p) for p in low[low == roll_min].round(2).tolist())

    def _cluster(pivots):
        if not pivots:
            return []
        groups, current = [], [pivots[0]]
        for p in pivots[1:]:
            if abs(p - current[-1]) / current[-1] <= cluster_pct:
                current.append(p)
            else:
                groups.append(current)
                current = [p]
        groups.append(current)
        return [sum(g) / len(g) for g in groups if len(g) >= min_touches]

    strong_hi, strong_lo = _cluster(piv_hi), _cluster(piv_lo)
    last = float(close.iloc[-1])
    resistance = sorted(p for p in strong_hi if p > last)[:max_levels]
    support = sorted((p for p in strong_lo if p < last), reverse=True)[:max_levels]
    return support, resistance


def _build_scanner_chart(ticker: str):
    """Daily candlestick + EMA20/SMA50/SMA200 + support/resistance, MACD, RSI."""
    df = get_price_history(ticker, period="2y")
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy(); df.columns = df.columns.get_level_values(0)
    # Drop any bar with a gap in OHLC (yfinance occasionally returns NaN closes) —
    # a NaN mid-series otherwise breaks Plotly's SVG path for the candlesticks/MACD bars.
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    if df.empty:
        return None
    close = df["Close"].squeeze()
    if len(close) < 30:
        return None

    n = min(180, len(df))
    view = df.iloc[-n:]
    close_v = close.iloc[-n:]
    xs = view.index

    ema20  = _ema(close, 20).iloc[-n:]
    sma50  = _sma(close, 50).iloc[-n:]
    sma200 = _sma(close, 200).iloc[-n:]
    macd_ln, sig_ln, hist_s = _macd(close)
    macd_ln, sig_ln, hist_s = macd_ln.iloc[-n:], sig_ln.iloc[-n:], hist_s.iloc[-n:]
    rsi_s = _rsi(close).iloc[-n:]
    support, resistance = _pivot_levels(df)   # full 2y history, not just the visible window

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03,
        row_heights=[0.55, 0.22, 0.23],
    )

    fig.add_trace(go.Candlestick(
        x=xs, open=view["Open"].squeeze(), high=view["High"].squeeze(),
        low=view["Low"].squeeze(), close=close_v,
        increasing_line_color=ACCENT_GREEN, decreasing_line_color=ACCENT_RED,
        increasing_fillcolor=_rgba(ACCENT_GREEN, 0.6), decreasing_fillcolor=_rgba(ACCENT_RED, 0.6),
        name=ticker,
    ), row=1, col=1)

    for series, color, label, width in [(ema20, "#22D3EE", "EMA 20", 1.4),
                                         (sma50, ACCENT_GREEN, "SMA 50", 1.4),
                                         (sma200, ACCENT_RED, "SMA 200", 2.6)]:
        if not series.dropna().empty:
            fig.add_trace(go.Scatter(x=xs, y=series, line=dict(color=color, width=width), name=label),
                          row=1, col=1)

    for lvl in resistance:
        fig.add_hline(y=lvl, line=dict(color=ACCENT_RED, width=1, dash="dash"),
                      annotation_text=f"R {lvl:.2f}", annotation_position="right",
                      annotation_font=dict(size=9, color=ACCENT_RED), row=1, col=1)
    for lvl in support:
        fig.add_hline(y=lvl, line=dict(color=ACCENT_GREEN, width=1, dash="dash"),
                      annotation_text=f"S {lvl:.2f}", annotation_position="right",
                      annotation_font=dict(size=9, color=ACCENT_GREEN), row=1, col=1)

    hist_colors = [ACCENT_GREEN if v >= 0 else ACCENT_RED for v in hist_s]
    fig.add_trace(go.Bar(x=xs, y=hist_s, marker_color=hist_colors, name="MACD Hist",
                         showlegend=False, opacity=0.85), row=2, col=1)
    fig.add_trace(go.Scatter(x=xs, y=macd_ln, line=dict(color=ACCENT_GREEN, width=1.3), name="MACD"),
                  row=2, col=1)
    fig.add_trace(go.Scatter(x=xs, y=sig_ln, line=dict(color=ACCENT_RED, width=1.1), name="Signal"),
                  row=2, col=1)
    fig.add_hline(y=0, line=dict(color=BORDER_COLOR, width=0.8, dash="dot"), row=2, col=1)

    fig.add_trace(go.Scatter(x=xs, y=rsi_s, line=dict(color="#A78BFA", width=1.5), name="RSI",
                             fill="tozeroy", fillcolor=_rgba("#A78BFA", 0.08)), row=3, col=1)
    for lvl, clr in [(30, ACCENT_RED), (50, _rgba(TEXT_MUTED, 0.5)), (70, ACCENT_GREEN)]:
        fig.add_hline(y=lvl, line=dict(color=clr, width=0.7, dash="dot"), row=3, col=1)

    fig.update_layout(
        paper_bgcolor=BG_DARK, plot_bgcolor=BG_PANEL,
        font=dict(color=TEXT_PRIMARY, family="Inter, sans-serif", size=11),
        height=560, margin=dict(l=10, r=55, t=34, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    bgcolor="rgba(0,0,0,0)", font=dict(size=10)),
        xaxis_rangeslider_visible=False, hovermode="x unified",
        title=dict(text=f"{ticker} — Daily", font=dict(size=13, color=GOLD), x=0.01, y=0.99),
    )
    for i in range(1, 4):
        fig.update_xaxes(gridcolor=BORDER_COLOR, row=i, col=1, showgrid=True)
        fig.update_yaxes(gridcolor=BORDER_COLOR, row=i, col=1, showgrid=True)
    fig.update_yaxes(title_text="Price", row=1, col=1, title_font=dict(size=10, color=TEXT_MUTED))
    fig.update_yaxes(title_text="MACD",  row=2, col=1, title_font=dict(size=10, color=TEXT_MUTED))
    fig.update_yaxes(title_text="RSI",   row=3, col=1, title_font=dict(size=10, color=TEXT_MUTED),
                     range=[0, 100])
    return fig


def _render_scanner_chart_section(ticker):
    st.markdown(
        f'<div style="margin-top:18px;color:{TEXT_MUTED};font-size:11px;letter-spacing:.08em;'
        f'text-transform:uppercase">Chart{f" — {ticker}" if ticker else ""}'
        f'<span style="font-weight:400;text-transform:none"> (click a row above to change)</span></div>',
        unsafe_allow_html=True,
    )
    if not ticker:
        st.info("Select a ticker in the table above to see its chart.")
        return
    with st.spinner(f"Loading {ticker} chart…"):
        fig = _build_scanner_chart(ticker)
    if fig is None:
        st.warning(f"Couldn't load chart data for {ticker}.")
        return
    st.plotly_chart(fig, use_container_width=True, key=f"home_best_chart_{ticker}")


def _render_track_record_table(df: pd.DataFrame, tag: str):
    st.markdown(
        f'<div style="margin-top:22px;color:{TEXT_MUTED};font-size:11px;letter-spacing:.06em;'
        f'text-transform:uppercase;font-weight:700">Track Record — last 90 days</div>',
        unsafe_allow_html=True,
    )
    if df.empty:
        st.caption("No qualifying tickers to build a track record from yet.")
        return

    today = datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")
    today_rows = [
        {"ticker": r["Ticker"], "price": r["Price"], "verdict": r["_verdict"], "scanners": r.get("Scanners")}
        for _, r in df.iterrows() if pd.notna(r["Price"])
    ]
    with st.spinner("Building track record — fetching current prices…"):
        track_rows = scan_history.track_record("best_scanners", tag, today, today_rows)
    if not track_rows:
        st.caption("No track record yet — check back after a few more days of runs.")
        return

    columns = [
        {"label": "Ticker", "type": "str"}, {"label": "Verdict", "type": "str"},
        {"label": "Scanners", "type": "str"}, {"label": "First Found", "type": "str"},
        {"label": "First Price", "type": "num"}, {"label": "Now", "type": "num"},
        {"label": "Perf", "type": "num"}, {"label": "High", "type": "num"},
        {"label": "% High", "type": "num"}, {"label": "Low", "type": "num"},
        {"label": "% Low", "type": "num"},
    ]
    def _pct_color(v):
        """Green above zero, red below, muted when there's no value. Used for
        every percentage in this table so none of them can be coloured by
        which column it sits in."""
        return TEXT_MUTED if v is None else (ACCENT_GREEN if v >= 0 else ACCENT_RED)

    table_rows = []
    for r in track_rows:
        pct = r.get("pct")
        pct_color = _pct_color(pct)
        pct_txt = "—" if pct is None else f"{pct:+.1f}%"
        cur_txt = "—" if r.get("current_price") is None else f"${r['current_price']:,.2f}"
        v_color = _VERDICT_COLOR.get(r.get("verdict"), TEXT_MUTED)
        high, low = r.get("high"), r.get("low")
        high_pct, low_pct = r.get("high_pct"), r.get("low_pct")
        high_txt = "—" if high is None else f"${high:,.2f}"
        low_txt = "—" if low is None else f"${low:,.2f}"
        high_pct_txt = "—" if high_pct is None else f"{high_pct:+.1f}%"
        low_pct_txt = "—" if low_pct is None else f"{low_pct:+.1f}%"
        # Colour by SIGN, not by column. % High was hardcoded green, but it
        # goes negative whenever the stock never traded above the entry price
        # since it was found -- so a losing position showed "-3.3%" in green,
        # which reads as good news at a glance. % Low can likewise be positive
        # when a name only ever traded up.
        high_pct_color = _pct_color(high_pct)
        low_pct_color = _pct_color(low_pct)
        table_rows.append([
            (f'<span style="font-weight:700;color:{GOLD}">{r["ticker"]}</span>', r["ticker"]),
            (f'<span style="color:{v_color};font-weight:600">{r.get("verdict") or "—"}</span>', r.get("verdict") or ""),
            (f'<span style="color:{TEXT_MUTED};font-size:11px">{r.get("scanners") or "—"}</span>', r.get("scanners") or ""),
            (f'<span style="color:{TEXT_MUTED};font-size:11px">{_fmt_found_date(r["first_found"])}</span>', r["first_found"]),
            (f'${r["first_price"]:,.2f}', r["first_price"]),
            (cur_txt, r.get("current_price") if r.get("current_price") is not None else ""),
            (f'<span style="font-weight:700;color:{pct_color}">{pct_txt}</span>', pct if pct is not None else ""),
            (high_txt, high if high is not None else ""),
            (f'<span style="color:{high_pct_color}">{high_pct_txt}</span>', high_pct if high_pct is not None else ""),
            (low_txt, low if low is not None else ""),
            (f'<span style="color:{low_pct_color}">{low_pct_txt}</span>', low_pct if low_pct is not None else ""),
        ])
    # Imported here, not at module top-level: headless mode (the GitHub Actions
    # email scripts) mocks `streamlit` in sys.modules without a real streamlit
    # install, and this submodule import fails against that mock -- but headless
    # mode never calls this render function, so a lazy import avoids the issue
    # entirely without needing to extend the mock.
    import streamlit.components.v1 as components
    components.html(
        sortable_table_html(columns, table_rows, default_sort_idx=6, default_desc=True),
        height=440, scrolling=False,
    )


_EDGE_LEGEND = [
    ("Strong Setup", ACCENT_GREEN,
     "This exact scanner combination has clearly beaten the market historically, "
     "backed by a large number of past examples."),
    ("Mixed Signal", GOLD,
     "Some historical edge, but backed by fewer past examples — worth a look, not a first pick."),
    ("Untested combo", TEXT_MUTED,
     "This combination of scanners has never been backtested with enough samples to "
     "measure — so there is no evidence either way. It says nothing about the ticker "
     "itself, and is not a sign the setup is weak."),
]


def _render_edge_legend():
    rows = "".join(
        f'<tr><td style="{_TD};color:{color};font-weight:600;white-space:nowrap">{label}</td>'
        f'<td style="{_TD};color:{TEXT_MUTED};font-size:11px">{desc}</td></tr>'
        for label, color, desc in _EDGE_LEGEND
    )
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11px;margin:14px 0 4px">'
        f'Verdict (next to Ticker) — based on how this exact scanner combination performed '
        f'historically, not a prediction. "Hold" is the range of hold lengths that combination '
        f'was actually tested at:</div>'
        f'<div style="border:1px solid {BORDER_COLOR};border-radius:10px;overflow:hidden">'
        f'<table style="width:100%;border-collapse:collapse">'
        f'<tbody>{rows}</tbody></table></div>',
        unsafe_allow_html=True,
    )


def _render_scanner_notes():
    items = "".join(
        f'<tr><td style="{_TD}">{_chip(lbl, GOLD, 0.12)}</td>'
        f'<td style="{_TD};white-space:normal"><b style="color:{TEXT_PRIMARY}">{name}</b> '
        f'<span style="color:{ACCENT_BLUE};font-size:9px">· {tf}</span></td>'
        f'<td style="{_TD};white-space:normal;color:{TEXT_MUTED};font-size:11px">{desc}</td></tr>'
        for lbl, name, tf, desc in _SCANNER_NOTES
    )
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11px;margin:14px 0 4px">What each scanner means:</div>'
        f'<div style="border:1px solid {BORDER_COLOR};border-radius:10px;overflow:hidden">'
        f'<table style="width:100%;border-collapse:collapse">'
        f'<tbody>{items}</tbody></table></div>',
        unsafe_allow_html=True,
    )


def _upload_best_to_sheet(df: pd.DataFrame):
    from scanners.gsheet_helper import export_tables, gsheets_configured
    if not gsheets_configured():
        st.warning("Google Sheets not connected — add `[gsheets]` credentials in Secrets to enable upload.")
        return
    cols = ["Ticker", "Price", "Chg", "Scanners", "RSI_W", "RSI_D", "MACD>Sig",
            "MACD Zone", ">SMA9", ">SMA20", "Vol Ratio", "RS vs SPY", "Flags"]
    vals = [[("; ".join(r["Flags"]) if c == "Flags" else
             ("✅" if r[c] else "❌") if c in (">SMA9", ">SMA20", "MACD>Sig") else r[c])
             for c in cols] for _, r in df.iterrows()]
    meta = [f"Best Scanners  {datetime.now():%Y-%m-%d %H:%M}", f"Tickers: {len(df)}",
            "Scanners: 1Mom · 2TC · 3MF · 4TS · 5RB · 6Prime"]
    with st.spinner("Uploading to Google Sheets…"):
        ok, msg = export_tables("HomeBest", [("BEST SCANNERS", cols, vals)], meta_cells=meta)
    (st.success if ok else st.error)(msg)


def _apply_growth_overlay(df: pd.DataFrame) -> pd.DataFrame:
    """Optional fundamentals overlay (folded in from Golden Scan's Growth scanner):
    tag firing tickers whose YoY revenue growth >=10% AND EPS growth >=8% with a
    '💹 Growth' flag. Runs only on the already-flagged rows (dozens of get_info
    calls, not the whole universe) and fails soft — a blocked/missing fundamentals
    lookup just means no flag, never an error. It does not change the ranking or
    horizon; growth is a confirmation, not a timing signal."""
    from data_loader import get_info
    if df.empty:
        return df
    new_flags = []
    prog = st.progress(0.0, text="Growth overlay (fundamentals)…")
    n = len(df)
    for i, (_, r) in enumerate(df.iterrows()):
        prog.progress((i + 1) / n)
        ok = False
        try:
            info = get_info(r["Ticker"]) or {}
            rev = (info.get("revenueGrowth") or 0) * 100
            eps = (info.get("earningsGrowth") or 0) * 100
            ok = rev >= 10 and eps >= 8
        except Exception:
            ok = False
        fl = r.get("Flags")
        fl = list(fl) if isinstance(fl, list) else ([] if not fl else [str(fl)])
        if ok and "💹 Growth" not in fl:
            fl = fl + ["💹 Growth"]
        new_flags.append(fl)
    prog.empty()
    df = df.copy()
    df["Flags"] = new_flags
    return df


def _render_best_scan_mode():
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:12px;line-height:1.7;margin-bottom:10px">'
        f'The six keeper scanners plus three add-ons (<b>7Square</b> · <b>8Cross</b> · '
        f'<b>9TA</b> Trend Align) run over one universe and merge into a single table. The '
        f'<b>Scanners</b> column lists every scanner that flagged the ticker — '
        f'<b style="color:{ACCENT_GREEN}">2+ = confluence</b> (sorted first). '
        f'<b>Horizon</b> splits <b>⚡ quick swings</b> from <b>🐢 long runs</b>; '
        f'<b>Stop→Tgt</b> is an ATR-based plan scaled to that horizon (2:1 reward:risk).</div>',
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns([2.4, 1, 1])
    with c1:
        uni_label = st.selectbox("Universe", list(_UNIVERSE_CHOICES.keys()), index=0, key="home_best_uni")
    with c2:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        run = st.button("▶ Run Scan", type="primary", use_container_width=True, key="home_best_run")
    with c3:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        clear = st.button("🔄 Clear", use_container_width=True, key="home_best_clear")
    inc_growth = st.checkbox(
        "➕ Growth overlay — also require strong fundamentals (rev ≥10% & EPS ≥8% YoY); adds a 💹 flag",
        value=False, key="home_best_growth",
        help="Folded in from Golden Scan. Slower — fetches fundamentals for flagged tickers only.",
    )

    if clear:
        st.session_state.pop("home_best_df", None)
        st.session_state.pop("home_best_ts", None)
        st.rerun()

    if run:
        universe = _resolve_universe(_UNIVERSE_CHOICES[uni_label])
        st.info(f"Scanning {len(universe)} tickers across 9 scanners — this takes a few minutes.")
        df = _run_best_scanners(universe)
        df = _annotate_history(df, _UNIVERSE_CHOICES[uni_label])
        if inc_growth:
            df = _apply_growth_overlay(df)
        st.session_state["home_best_df"] = df
        st.session_state["home_best_uni_tag"] = _UNIVERSE_CHOICES[uni_label]
        st.session_state["home_best_ts"] = datetime.now().strftime("%b %d %Y · %I:%M %p")
        st.rerun()

    df = st.session_state.get("home_best_df")
    if df is None:
        st.markdown(
            f'<div style="border:1px dashed {BORDER_COLOR};border-radius:10px;padding:36px;'
            f'text-align:center;color:{TEXT_MUTED}">Press <b style="color:{GOLD}">▶ Run Scan</b> '
            f'to score the universe against all six scanners.</div>',
            unsafe_allow_html=True,
        )
        return
    if df.empty:
        st.info("No tickers passed any of the six scanners in this universe right now.")
        return

    ts = st.session_state.get("home_best_ts", "")
    n_multi = int((df["_count"] >= 2).sum())
    st.markdown(
        f'<div style="display:flex;gap:20px;flex-wrap:wrap;background:{BG_CARD};'
        f'border:1px solid {BORDER_COLOR};border-radius:8px;padding:9px 16px;margin:4px 0 10px">'
        f'<span style="color:{TEXT_MUTED};font-size:11px">Found <b style="color:{GOLD}">{len(df)}</b> tickers</span>'
        f'<span style="color:{ACCENT_GREEN};font-size:11px;font-weight:700">⭐ {n_multi} multi-signal (2+)</span>'
        f'<span style="color:{TEXT_MUTED};font-size:10px;margin-left:auto">Scanned {ts}</span></div>',
        unsafe_allow_html=True,
    )

    up_col, dl_col, _ = st.columns([1.4, 1, 3])
    with up_col:
        if st.button("📤 Upload to Google Sheet", use_container_width=True, key="home_best_upload"):
            _upload_best_to_sheet(df)
    with dl_col:
        exp = df.drop(columns=["_count", "x8_weekly", "_labels", "_plan",
                               "_horizon", "_hold_lo", "_hold_hi", "atr_val"],
                      errors="ignore").copy()
        exp["Flags"] = exp["Flags"].apply(lambda x: "; ".join(x) if isinstance(x, list) else x)
        st.download_button("⬇ CSV", exp.to_csv(index=False), "best_scanners.csv",
                           "text/csv", use_container_width=True, key="home_best_csv")

    selected_ticker = _render_best_table(df)
    _render_track_record_table(df, st.session_state.get("home_best_uni_tag", "FTF"))
    _render_scanner_chart_section(selected_ticker)
    _render_edge_legend()
    _render_scanner_notes()


# ══════════════════════════════════════════════════════════════════════════════
# BEST SCANNERS BACKTEST — validates the ★ combo rules against real outcomes
# ══════════════════════════════════════════════════════════════════════════════
#
# Reuses _evaluate()/_star_rating() UNCHANGED — guarantees the backtest tests
# the EXACT same signal definitions as the live scanner, no risk of a
# reimplementation quietly drifting out of sync. Each historical day gets a
# BOUNDED trailing window (260 daily bars — comfortably over _evaluate()'s
# own 210-day/34-week minimums) instead of the full expanding history, so
# per-call cost stays roughly constant instead of growing with position —
# makes a multi-year, multi-hundred-ticker walk-forward backtest tractable.
#
# A "signal" is the ONSET of a star tier — the day its value first differs
# from the prior day's (including from "unflagged"), not every day it
# persists — otherwise a single multi-month uptrend in one stock would
# dominate a tier's stats. "Win" = forward return over the hold period
# beats SPY's return over the same window (relative strength — matches the
# RS-gated spirit already built into 3MF/4TS), not just "did it go up".

BS_BT_WARMUP_BARS    = 260   # trailing daily bars fed to _evaluate() each call
BS_BT_LOOKBACK_YEARS = 5
BS_BT_HOLD_DAYS      = 90

# yfinance's period param only accepts a fixed preset list (1y/2y/5y/10y/max
# for year-scale requests) — anything else (e.g. "7y") gets rejected by
# Yahoo's API and silently comes back empty. Map the requested buffer to the
# smallest preset that covers it instead of building an arbitrary "Ny" string.
def _yf_period_for_years(years: int) -> str:
    for cap, period in ((1, "1y"), (2, "2y"), (5, "5y"), (10, "10y")):
        if years <= cap:
            return period
    return "max"


def _bt_forward_outcome(closes: pd.Series, spy_aligned: pd.Series, entry_pos: int,
                        hold_days: int) -> dict | None:
    """Forward return vs SPY over `hold_days` trading days from `entry_pos`
    (an integer position into `closes`/`spy_aligned`). None if there isn't
    enough forward data yet (event too close to the end of history)."""
    exit_pos = entry_pos + hold_days
    if exit_pos >= len(closes):
        return None
    entry_px, exit_px = float(closes.iloc[entry_pos]), float(closes.iloc[exit_pos])
    spy_entry, spy_exit = float(spy_aligned.iloc[entry_pos]), float(spy_aligned.iloc[exit_pos])
    if entry_px <= 0 or spy_entry <= 0 or pd.isna(spy_entry) or pd.isna(spy_exit):
        return None
    stock_ret = exit_px / entry_px - 1
    spy_ret = spy_exit / spy_entry - 1
    return dict(stock_ret=stock_ret, spy_ret=spy_ret, rel_ret=stock_ret - spy_ret,
               win=stock_ret > spy_ret)


def _backtest_ticker_best_scanners(ticker: str, lookback_years: int, hold_days: int,
                                   since: pd.Timestamp) -> tuple[list[dict], str]:
    """Walks `ticker`'s daily history day-by-day from `since` onward, calling
    the live _evaluate()/_star_rating() on a bounded trailing window at each
    point, and records one outcome per star-tier ONSET. Returns (records,
    reason) — reason explains an empty result (no_daily_data / no_spy_data /
    insufficient_history / no_onsets / error:<Type>:<msg>) so a zero-record
    run can be diagnosed from the UI instead of failing silently."""
    records: list[dict] = []
    try:
        period = _yf_period_for_years(lookback_years + 2)
        daily = get_price_history(ticker, period=period, interval="1d")
        spy = get_price_history("SPY", period=period, interval="1d")
        if daily is None or daily.empty:
            return records, "no_daily_data"
        if spy is None or spy.empty:
            return records, "no_spy_data"
        daily = daily.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
        if len(daily) < BS_BT_WARMUP_BARS + 20:
            return records, "insufficient_history"
        spy_aligned = spy["Close"].squeeze().reindex(daily.index).ffill()
        closes = daily["Close"].squeeze()

        # searchsorted() requires matching datetime64 units under pandas 3.x
        # (unlike comparison operators, which auto-widen) -- daily.index comes
        # back from yfinance at whatever resolution it/pandas picked (e.g. 's'),
        # while `since` is built from Timestamp.now() at pandas's own default
        # ('us'). Snap since to the index's unit or this raises "Cannot
        # losslessly convert units" for every single ticker.
        since_matched = since.as_unit(daily.index.unit)
        start_i = max(BS_BT_WARMUP_BARS - 1, int(daily.index.searchsorted(since_matched)))
        prev_state = None
        for i in range(start_i, len(daily)):
            window = daily.iloc[i - BS_BT_WARMUP_BARS + 1: i + 1]
            spy_window = spy_aligned.iloc[i - BS_BT_WARMUP_BARS + 1: i + 1]
            res = _evaluate(window, spy_window)
            cur_state = _star_rating(res["labels"]) if res else None
            if cur_state is not None and cur_state != prev_state:
                outcome = _bt_forward_outcome(closes, spy_aligned, i, hold_days)
                if outcome is not None:
                    records.append(dict(
                        ticker=ticker, date=daily.index[i].date().isoformat(),
                        stars=cur_state, **outcome,
                    ))
            prev_state = cur_state
        return records, ("ok" if records else "no_onsets")
    except Exception as e:
        return records, f"error:{type(e).__name__}:{e}"


def _run_best_scanners_backtest(universe: list, lookback_years: int, hold_days: int,
                                progress_cb=None) -> tuple[list[dict], dict]:
    # Sequential on purpose -- this app runs on Streamlit Community Cloud's
    # free tier, which throttles CPU when usage stays too high for too long.
    # A thread pool here concentrates CPU load (more of it at once) rather
    # than reducing total work, which tripped that throttle faster, not
    # slower. Reducing actual CPU cost (e.g. vectorizing the indicator math)
    # is the real fix if the full universe/lookback needs to fit reliably;
    # see the ticket flagged for that.
    from collections import Counter
    prefetch_tickers(list(universe) + ["SPY"], _yf_period_for_years(lookback_years + 2), "1d")
    since = pd.Timestamp.now() - pd.DateOffset(years=lookback_years)
    all_records: list[dict] = []
    reasons: Counter = Counter()
    total = len(universe)
    for i, ticker in enumerate(universe):
        if progress_cb and (i % 5 == 0 or i == total - 1):
            progress_cb(i, total, ticker)
        recs, reason = _backtest_ticker_best_scanners(ticker, lookback_years, hold_days, since)
        all_records.extend(recs)
        reasons[reason] += 1
    return all_records, dict(reasons)


def _aggregate_best_scanners_backtest(records: list[dict]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    rows = []
    for stars, grp in df.groupby("stars"):
        n = len(grp)
        wins = int(grp["win"].sum())
        rows.append(dict(
            stars=int(stars), n=n, wins=wins,
            win_rate=(wins / n * 100) if n else float("nan"),
            avg_rel=float(grp["rel_ret"].mean()) * 100,
            avg_stock=float(grp["stock_ret"].mean()) * 100,
        ))
    return pd.DataFrame(rows).sort_values("stars", ascending=False).reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════════
# FULL ANALYSIS BACKTEST — is the * combo system actually better than raw
# scanner count, and are the hardcoded _STAR_RULES combos actually the best
# ones? Same walk-forward as _backtest_ticker_best_scanners (identical fetch,
# identical bounded-window _evaluate() call each day), but instead of only
# tracking the star tier, tracks THREE dimensions per day from the same
# already-computed label set: star tier (unchanged), raw scanner count, and
# membership of every 1-3-label combo (singles cover "which one scanner is
# best", pairs+triples cover "which combo works best" beyond just the ones
# _STAR_RULES happens to hardcode). One record per (ticker, date, dimension,
# tier) onset. Reuses _bt_forward_outcome() unchanged.
# ══════════════════════════════════════════════════════════════════════════════

from itertools import combinations as _combinations

_COMBO_UNIVERSE: list[tuple[frozenset, str]] = [
    (frozenset(combo), "+".join(combo))
    for size in (1, 2, 3)
    for combo in _combinations(_LABELS, size)
]   # 8 singles + 28 pairs + 56 triples = 92


def _backtest_ticker_full_analysis(ticker: str, lookback_years: int, hold_days: int,
                                   since: pd.Timestamp) -> tuple[list[dict], str]:
    records: list[dict] = []
    try:
        period = _yf_period_for_years(lookback_years + 2)
        daily = get_price_history(ticker, period=period, interval="1d")
        spy = get_price_history("SPY", period=period, interval="1d")
        if daily is None or daily.empty:
            return records, "no_daily_data"
        if spy is None or spy.empty:
            return records, "no_spy_data"
        daily = daily.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
        if len(daily) < BS_BT_WARMUP_BARS + 20:
            return records, "insufficient_history"
        spy_aligned = spy["Close"].squeeze().reindex(daily.index).ffill()
        closes = daily["Close"].squeeze()

        since_matched = since.as_unit(daily.index.unit)
        start_i = max(BS_BT_WARMUP_BARS - 1, int(daily.index.searchsorted(since_matched)))

        prev_star = None
        prev_count = None
        prev_combo_in = {key: False for _, key in _COMBO_UNIVERSE}

        for i in range(start_i, len(daily)):
            window = daily.iloc[i - BS_BT_WARMUP_BARS + 1: i + 1]
            spy_window = spy_aligned.iloc[i - BS_BT_WARMUP_BARS + 1: i + 1]
            res = _evaluate(window, spy_window)
            label_set = frozenset(res["labels"]) if res else frozenset()
            cur_star = _star_rating(res["labels"]) if res else None
            cur_count = len(label_set)

            events: list[tuple[str, str]] = []
            if cur_star is not None and cur_star != prev_star:
                events.append(("star", str(cur_star)))
            if cur_count >= 1 and cur_count != prev_count:
                events.append(("count", str(cur_count)))
            for combo, key in _COMBO_UNIVERSE:
                now_in = combo <= label_set
                if now_in and not prev_combo_in[key]:
                    events.append(("combo", key))
                prev_combo_in[key] = now_in

            if events:
                outcome = _bt_forward_outcome(closes, spy_aligned, i, hold_days)
                if outcome is not None:
                    date_str = daily.index[i].date().isoformat()
                    for dim, tier in events:
                        records.append(dict(ticker=ticker, date=date_str,
                                            dimension=dim, tier=tier, **outcome))

            prev_star = cur_star
            prev_count = cur_count

        return records, ("ok" if records else "no_onsets")
    except Exception as e:
        return records, f"error:{type(e).__name__}:{e}"


def _run_full_analysis_backtest(universe: list, lookback_years: int, hold_days: int,
                                progress_cb=None) -> tuple[list[dict], dict]:
    from collections import Counter
    prefetch_tickers(list(universe) + ["SPY"], _yf_period_for_years(lookback_years + 2), "1d")
    since = pd.Timestamp.now() - pd.DateOffset(years=lookback_years)
    all_records: list[dict] = []
    reasons: Counter = Counter()
    total = len(universe)
    for i, ticker in enumerate(universe):
        if progress_cb and (i % 5 == 0 or i == total - 1):
            progress_cb(i, total, ticker)
        recs, reason = _backtest_ticker_full_analysis(ticker, lookback_years, hold_days, since)
        all_records.extend(recs)
        reasons[reason] += 1
    return all_records, dict(reasons)


def _aggregate_full_analysis(records: list[dict], min_n: int = 30) -> pd.DataFrame:
    """Groups by (dimension, tier). `ranked` marks whether a row has enough
    onset events (>= min_n) for its win rate / excess return to be trusted.

    Also computes std_rel/standard_error/lower_bound_score -- a proper
    confidence-adjusted score (avg_rel discounted by its own standard error,
    Z=1.5), not just the sample-size-bucketed high/medium/low confidence
    _EDGE_SHORTLIST currently uses. That shortlist predates this addition (it
    was hand-built from runs that only captured the mean, not the spread);
    once a fresh batch of full-analysis runs is collected with this in
    place, the shortlist can be rebuilt from lower_bound_score directly
    instead of the N-threshold approximation."""
    if not records:
        return pd.DataFrame()
    Z = 1.5
    df = pd.DataFrame(records)
    rows = []
    for (dim, tier), grp in df.groupby(["dimension", "tier"]):
        n = len(grp)
        wins = int(grp["win"].sum())
        avg_rel = float(grp["rel_ret"].mean()) * 100
        std_rel = float(grp["rel_ret"].std()) * 100 if n > 1 else float("nan")
        se = std_rel / (n ** 0.5) if n > 1 else float("nan")
        rows.append(dict(
            dimension=dim, tier=tier, n=n, wins=wins,
            win_rate=(wins / n * 100) if n else float("nan"),
            avg_rel=avg_rel,
            avg_stock=float(grp["stock_ret"].mean()) * 100,
            std_rel=std_rel,
            standard_error=se,
            lower_bound_score=(avg_rel - Z * se) if n > 1 else float("nan"),
            ranked=n >= min_n,
        ))
    return pd.DataFrame(rows)


_BS_BT_TD = f"padding:7px 10px;border-bottom:1px solid {BORDER_COLOR};vertical-align:middle;white-space:nowrap"


def _render_best_scanners_backtest_table(agg: pd.DataFrame) -> None:
    if agg.empty:
        st.info("No historical signals found to backtest in this window.")
        return
    cols = ["★", "Signals Tested", "Win Rate (beats SPY)", "Avg Excess Return", "Avg Stock Return"]
    thead = "".join(f'<th style="{_TH}">{c}</th>' for c in cols)
    body = ""
    for _, r in agg.iterrows():
        wr = r["win_rate"]
        if pd.isna(wr):
            wr_str, wr_color = "—", TEXT_MUTED
        else:
            wr_str = f"{wr:.0f}%"
            wr_color = ACCENT_GREEN if wr >= 55 else (GOLD if wr >= 45 else ACCENT_RED)
        rel = r["avg_rel"]; rel_color = ACCENT_GREEN if rel >= 0 else ACCENT_RED
        stock = r["avg_stock"]; stock_color = ACCENT_GREEN if stock >= 0 else ACCENT_RED
        stars_label = "★" * int(r["stars"]) if r["stars"] > 0 else "— (0)"
        body += (
            "<tr>"
            f'<td style="{_BS_BT_TD};color:{GOLD};font-size:13px">{stars_label}</td>'
            f'<td style="{_BS_BT_TD}">{int(r["n"])}</td>'
            f'<td style="{_BS_BT_TD};color:{wr_color};font-weight:700">{wr_str}</td>'
            f'<td style="{_BS_BT_TD};color:{rel_color}">{rel:+.1f}%</td>'
            f'<td style="{_BS_BT_TD};color:{stock_color}">{stock:+.1f}%</td>'
            "</tr>"
        )
    st.markdown(
        f'<div style="overflow-x:auto;border:1px solid {BORDER_COLOR};border-radius:10px">'
        f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
        f'<thead><tr>{thead}</tr></thead><tbody>{body}</tbody></table></div>',
        unsafe_allow_html=True,
    )


_BS_BT_BUILD_TAG = "bt-build-2026-07-28-sequential2"   # bump whenever this function's logic changes


def _render_best_scanners_backtest_mode():
    st.caption(f"engine: {_BS_BT_BUILD_TAG}")
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11.5px;line-height:1.6;margin-bottom:8px">'
        f'Tests every historical ★ combo signal against real outcomes. Unlike OverKill, Best Scanners '
        f'has no stated TP/SL — a "win" here means the stock\'s forward return over the hold period '
        f'<b>beat SPY\'s</b> return over the same window, not just "went up" (so a rising-tide bull '
        f'market doesn\'t inflate every tier equally). Each row is the first day a ticker newly '
        f'entered that ★ tier, not every day it stayed there. Runs the exact same _evaluate()/'
        f'_star_rating() logic as Run Scan — no separate reimplementation to drift out of sync.</div>',
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns([2.2, 1, 1])
    with c1:
        uni_label = st.selectbox("Universe", list(_UNIVERSE_CHOICES.keys()), index=0, key="home_bsbt_uni")
    with c2:
        lookback_years = st.number_input("Lookback (years)", min_value=1, max_value=10,
                                         value=BS_BT_LOOKBACK_YEARS, key="home_bsbt_years")
    with c3:
        hold_days = st.number_input("Max hold (trading days)", min_value=10, max_value=250,
                                    value=BS_BT_HOLD_DAYS, key="home_bsbt_hold")

    run_bt = st.button("▶ Run Backtest", type="primary", key="home_bsbt_run")

    if run_bt:
        universe = _resolve_universe(_UNIVERSE_CHOICES[uni_label])
        prog = st.progress(0.0, text="Backtesting historical scanner signals…")

        def _cb(i, total, ticker):
            prog.progress(min((i + 1) / total, 1.0), text=f"Backtesting {ticker} ({i+1}/{total})…")

        records, reasons = _run_best_scanners_backtest(universe, int(lookback_years), int(hold_days), progress_cb=_cb)
        prog.empty()

        st.session_state["home_bsbt_records"] = records
        st.session_state["home_bsbt_reasons"] = reasons
        st.session_state["home_bsbt_ts"] = datetime.now().strftime("%b %d %Y · %I:%M %p")
        if not records:
            st.info("No historical ★ signals found in this window — try a longer lookback or a bigger universe.")

    records = st.session_state.get("home_bsbt_records")
    if not records:
        reasons = st.session_state.get("home_bsbt_reasons")
        if reasons:
            _LABEL = {
                "no_daily_data": "no daily data returned",
                "no_spy_data": "no SPY data returned",
                "insufficient_history": "insufficient history (<280 daily bars)",
                "no_onsets": "data fetched fine, but no ★-tier onset in this window",
                "ok": "found signal(s)",
            }
            parts = []
            for reason, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
                label = _LABEL.get(reason) or (reason if not reason.startswith("error:") else reason)
                parts.append(f"{n} × {label}")
            st.caption("Diagnostics — " + " · ".join(parts))
        st.markdown(
            f'<div style="border:1px dashed {BORDER_COLOR};border-radius:10px;padding:36px;'
            f'text-align:center;color:{TEXT_MUTED}">Press <b style="color:{GOLD}">▶ Run Backtest</b> '
            f'to validate the ★ combo rules against historical outcomes. This scans every ticker in '
            f'the chosen universe day-by-day and can take a while — far more work per ticker than '
            f'Run Scan.</div>',
            unsafe_allow_html=True,
        )
        return

    greens = sum(1 for r in records if r["win"])
    st.caption(
        f"Backtested {st.session_state.get('home_bsbt_ts','')} · {len(records)} historical signals "
        f"({greens} beat SPY, {len(records)-greens} didn't)"
    )
    agg = _aggregate_best_scanners_backtest(records)
    _render_best_scanners_backtest_table(agg)


def _render_best_scanners_tab():
    mode = st.radio("Mode", ["▶ Run Scan", "📊 Backtest"], horizontal=True, key="home_best_mode",
                    label_visibility="collapsed")
    if mode == "📊 Backtest":
        _render_best_scanners_backtest_mode()
    else:
        _render_best_scan_mode()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — OVERKILL SHORTS  (curated watch-list, refreshed on request)
# ══════════════════════════════════════════════════════════════════════════════

_GH_OWNER = "ANDANK"
_GH_REPO = "golden-scanner"
_GH_WORKFLOW_FILE = "refresh_overkill.yml"


def _get_github_token() -> str:
    """Read a GitHub PAT (repo/actions:write scope) from Streamlit secrets."""
    try:
        return str(st.secrets["GITHUB_TOKEN"]).strip()
    except (KeyError, FileNotFoundError):
        pass
    except Exception:
        try:
            val = st.secrets.get("GITHUB_TOKEN")
            if val:
                return str(val).strip()
        except Exception:
            pass
    return ""


def _gh_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _trigger_overkill_workflow(handles: list[str] | None = None) -> tuple:
    """POST a workflow_dispatch event. Returns (ok, message).

    `handles` narrows the scan to those channels. Passing every channel (or
    none) sends an empty input, which the script reads as "scan everything" --
    so the default behaviour and every scheduled run are untouched."""
    token = _get_github_token()
    if not token:
        return False, ("No GitHub token configured. Add **GITHUB_TOKEN** (a PAT with `actions:write` "
                        "or `repo` scope on this repo) to your Streamlit secrets to enable this button.")
    url = (f"https://api.github.com/repos/{_GH_OWNER}/{_GH_REPO}/actions/workflows/"
           f"{_GH_WORKFLOW_FILE}/dispatches")
    payload = {"ref": "main", "inputs": {"channels": ",".join(handles or [])}}
    try:
        r = requests.post(url, headers=_gh_headers(token), json=payload, timeout=15)
    except Exception as e:
        return False, f"Request failed: {e}"
    if r.status_code == 204:
        scope = (f"{len(handles)} channel(s)" if handles else "all channels")
        return True, (f"Triggered for {scope} — the run usually finishes in a minute or two. "
                      f"Use *Check status* below.")
    if r.status_code == 401:
        return False, "GitHub rejected the token (401) — GITHUB_TOKEN may be invalid or expired."
    if r.status_code == 404:
        return False, "Workflow or repo not found (404) — check the token has access to this repo."
    return False, f"GitHub API error {r.status_code}: {r.text[:200]}"


def _latest_overkill_run():
    """Most recent run of the refresh workflow, as (run, error_message).

    Returns the specific reason rather than a bare None. The previous version
    swallowed every failure into `return None` and the caller then blamed the
    token for all of them -- so an expired token, a permissions gap, a renamed
    workflow file and a network blip all produced the identical "check
    GITHUB_TOKEN" message. Three of those four are not the token, and the
    message sent you looking in the wrong place."""
    token = _get_github_token()
    if not token:
        return None, ("No **GITHUB_TOKEN** in Streamlit secrets. Add it as a top-level line: "
                      "`GITHUB_TOKEN = \"github_pat_...\"`")
    url = (f"https://api.github.com/repos/{_GH_OWNER}/{_GH_REPO}/actions/workflows/"
           f"{_GH_WORKFLOW_FILE}/runs")
    try:
        r = requests.get(url, headers=_gh_headers(token), params={"per_page": 1}, timeout=15)
        if r.status_code == 401:
            return None, ("GitHub rejected the token (**401**) — it has expired or been revoked. "
                          "Regenerate the PAT and update the Streamlit secret.")
        if r.status_code == 403:
            return None, ("Token authenticated but lacks permission (**403**) — it needs "
                          "`Actions: Read and write` on this repo. Read-only shows this on the "
                          "Refresh button while status still loads.")
        if r.status_code == 404:
            return None, (f"`{_GH_WORKFLOW_FILE}` not found (**404**) — either the token can't see "
                          f"`{_GH_OWNER}/{_GH_REPO}`, or the workflow file was renamed.")
        r.raise_for_status()
        runs = r.json().get("workflow_runs", [])
        if not runs:
            return None, "No runs recorded for this workflow yet."
        return runs[0], None
    except requests.Timeout:
        return None, "GitHub timed out. Try again in a moment."
    except Exception as e:
        return None, f"Couldn't reach GitHub: {e}"


def _to_ct(iso_utc: str) -> str:
    """Format a GitHub UTC timestamp (e.g. 2026-07-24T14:39:12Z) as US/Central."""
    if not iso_utc:
        return "?"
    try:
        dt = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ")
        dt = pytz.utc.localize(dt).astimezone(pytz.timezone("US/Central"))
        return dt.strftime("%Y-%m-%d %I:%M %p %Z")
    except Exception:
        return iso_utc


def _job_log_tail(run_id: int, lines: int = 150) -> str:
    """Return the tail of a run's job log — the failed job if any, else the first job."""
    token = _get_github_token()
    if not token:
        return ""
    try:
        jr = requests.get(
            f"https://api.github.com/repos/{_GH_OWNER}/{_GH_REPO}/actions/runs/{run_id}/jobs",
            headers=_gh_headers(token), timeout=15,
        )
        jr.raise_for_status()
        jobs = jr.json().get("jobs", [])
        if not jobs:
            return "(no jobs found on this run)"
        job = next((j for j in jobs if j.get("conclusion") == "failure"), jobs[0])
        lr = requests.get(
            f"https://api.github.com/repos/{_GH_OWNER}/{_GH_REPO}/actions/jobs/{job['id']}/logs",
            headers=_gh_headers(token), timeout=20,
        )
        lr.raise_for_status()
        log_lines = lr.text.splitlines()
        return "\n".join(log_lines[-lines:])
    except Exception as e:
        return f"(couldn't fetch logs: {e})"


def _render_overkill_trigger(handles: list[str] | None = None):
    """`handles` comes from the channel filter above the table, so Refresh Now
    scans exactly what you're looking at. Selecting every channel (the default)
    passes nothing and scans them all."""
    c1, c2 = st.columns([1, 1])
    with c1:
        scoped = bool(handles)
        label = f"🔄 Refresh {len(handles)} channel(s)" if scoped else "🔄 Refresh Now"
        if st.button(label, key="overkill_trigger_btn",
                     help=("Runs the GitHub Action for just the channels selected above — "
                           "the whole per-run fetch budget goes to them, so one channel's "
                           "backlog drains far faster."
                           if scoped else
                           "Runs the GitHub Action across every watched channel.")):
            with st.spinner("Triggering GitHub Action…"):
                ok, msg = _trigger_overkill_workflow(handles)
            (st.success if ok else st.error)(msg)
    with c2:
        if st.button("Check latest run status", key="overkill_status_btn"):
            with st.spinner("Checking…"):
                run, err = _latest_overkill_run()
            if run is None:
                st.warning(f"Couldn't fetch run status — {err}")
            else:
                label = run.get("conclusion") or run.get("status") or "unknown"
                icon = {"success": "✅", "failure": "❌", "in_progress": "⏳",
                        "queued": "⏳", "cancelled": "🚫"}.get(label, "ℹ️")
                st.info(f"{icon} Latest run: **{label}** · started "
                        f"{_to_ct(run.get('run_started_at', ''))}")
                with st.spinner("Fetching run log…"):
                    tail = _job_log_tail(run["id"])
                with st.expander("🪵 Run log (last 150 lines)", expanded=(label == "failure")):
                    st.code(tail or "(empty log)", language="text")
                    st.caption("On a successful run with no new videos in the table, this log shows exactly "
                               "which candidate videos were checked and why each was skipped (crypto, no "
                               "transcript yet, or no picks extracted).")

    # The "Debug — GitHub token status" expander that used to sit here was
    # removed once the token was confirmed working -- it was permanent UI for a
    # one-time setup problem. If the Refresh/status buttons ever start erroring:
    # 401 means the token is invalid or expired (regenerate it), 404 means its
    # repo access or Actions permission isn't set on golden-scanner, and "not
    # found" means st.secrets["GITHUB_TOKEN"] is missing or nested under a
    # section instead of being a top-level line in Streamlit Cloud's Secrets.


def _render_overkill_pending():
    """Videos not yet in the table, split by WHY.

    These are two unrelated situations and were previously shown as one list
    headed "couldn't be auto-analyzed". After the jump to seven channels that
    read as "92 Shorts couldn't be auto-analyzed" when in fact nearly all of
    them were simply queued behind the per-run cap and would be picked up over
    the following days. Queued is the healthy state of a backlog draining; only
    `failed` means a transcript genuinely couldn't be fetched."""
    path = os.path.join(DATA_DIR, "overkill_pending.json")
    try:
        with open(path, encoding="utf-8") as f:
            pending_data = json.load(f)
    except Exception:
        return
    pending = pending_data.get("pending", [])
    if not pending:
        return

    # Entries written before this split carried no reason. Treat them as
    # queued: that's the overwhelmingly common case, and it errs toward the
    # calmer reading rather than crying failure over a healthy backlog.
    failed = [p for p in pending if p.get("reason") == "failed"]
    queued = [p for p in pending if p.get("reason") != "failed"]

    def _items(rows):
        return "".join(
            f'<li style="margin-bottom:4px"><a href="{p.get("url","")}" target="_blank" '
            f'style="color:{TEXT_PRIMARY}">{p.get("title","")}</a> '
            f'<span style="color:{TEXT_MUTED};font-size:10px">· {p.get("date","")}'
            + (f' · {p["channel_name"]}' if p.get("channel_name") else "")
            + '</span></li>'
            for p in rows)

    if failed:
        st.markdown(
            f'<div style="background:{_rgba(GOLD, 0.08)};border:1px solid {GOLD}44;'
            f'border-radius:10px;padding:12px 16px;margin:4px 0 10px">'
            f'<div style="color:{GOLD};font-size:12px;font-weight:700;margin-bottom:6px">'
            f'⚠️ {len(failed)} Short(s) couldn\'t be analysed</div>'
            f'<ul style="margin:0;padding-left:18px;font-size:12px">{_items(failed)}</ul>'
            f'<div style="color:{TEXT_MUTED};font-size:10.5px;margin-top:8px">'
            f'Transcript unavailable — captions off, or the fetch was blocked. '
            f'These are retried on later runs.</div></div>',
            unsafe_allow_html=True,
        )

    if queued:
        with st.expander(f"🕒 {len(queued)} Short(s) queued for upcoming runs", expanded=False):
            st.caption(
                "Waiting their turn behind the per-run fetch cap, not a problem. The cap "
                "keeps request volume low enough to avoid the YouTube rate limit, so a "
                "backlog drains over several days. Nothing to do."
            )
            st.markdown(f'<ul style="margin:0;padding-left:18px;font-size:12px">'
                        f'{_items(queued[:40])}</ul>'
                        + (f'<div style="color:{TEXT_MUTED};font-size:10.5px;margin-top:6px">'
                           f'…and {len(queued) - 40} more.</div>' if len(queued) > 40 else ""),
                        unsafe_allow_html=True)


def _render_recent_ticker_line(flat: list[dict]):
    """Comma-separated tickers from the two most recent posting dates, ready to
    copy into the OverKill tab to pull the charts.

    Two most recent DATES PRESENT, not the last two calendar days: the channel
    doesn't post every day, so a calendar window would come up empty after a
    quiet stretch, which is exactly when you'd still want the latest names.
    Deduped, newest date first, order preserved within a date."""
    dates = sorted({r.get("date", "") for r in flat if r.get("date")}, reverse=True)[:2]
    if not dates:
        return
    seen, tickers = set(), []
    for r in flat:                                    # already sorted newest-first
        t = (r.get("ticker") or "").upper()
        if r.get("date") in dates and t and t not in seen:
            seen.add(t)
            tickers.append(t)
    if not tickers:
        return
    joined = ", ".join(tickers)
    st.markdown(
        f'<div style="color:{GOLD};font-size:10px;font-weight:700;'
        f'text-transform:uppercase;letter-spacing:0.5px;margin-bottom:2px">'
        f'Last 2 posting days ({" · ".join(dates)}) — {len(tickers)} ticker(s)</div>',
        unsafe_allow_html=True,
    )
    # st.code rather than a styled div: it ships Streamlit's own copy-to-
    # clipboard button, which beats hand-rolling one. A custom button would
    # have to run navigator.clipboard inside a components.html iframe, where
    # clipboard writes are commonly blocked by permissions policy -- a button
    # that silently fails to copy is worse than no button. Trades the gold box
    # for a control that reliably works.
    st.code(joined, language=None)
    st.caption("Copy with the button above, then paste into the OverKill tab to chart these.")


def _render_overkill_tab():
    path = os.path.join(DATA_DIR, "overkill_shorts.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        st.info("No OverKill Shorts summary stored yet.")
        return

    n_ch = len(data.get("channels", [])) or 1
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:12px;line-height:1.7;margin-bottom:10px">'
        f'Stock calls and takeaways auto-extracted from the captions of finance Shorts '
        f'across <b>{n_ch} channel(s)</b> (crypto skipped). <b>Bias</b> is the direction '
        f'stated in the video — rows with no ticker are general takeaways (a rate call, a '
        f'tax rule, a market view) rather than trade ideas. '
        f'Updated <b>{data.get("updated","")}</b> · not financial advice.</div>',
        unsafe_allow_html=True,
    )

    def _bias_html(b):
        col = ACCENT_GREEN if b == "Bullish" else ACCENT_RED if b == "Bearish" else TEXT_MUTED
        return f'<span style="color:{col};font-weight:700;font-size:11px">{b}</span>'

    flat = []
    for vid in data.get("videos", []):
        for p in vid.get("picks", []):
            row = dict(p)
            row["date"]    = vid.get("date", "")
            row["video"]   = vid.get("title", "")
            row["url"]     = vid.get("url", "")
            row["channel"] = vid.get("channel_name") or "OverKill"
            flat.append(row)
    flat.sort(key=lambda r: (r.get("date", ""), r.get("ticker", "")), reverse=True)

    # Filters sit at the very top, above the refresh controls and the pending
    # list: with seven channels the feed is long, and the two questions you
    # arrive with are "what did X say" and "just show me the tickers".
    names = sorted({r["channel"] for r in flat})
    # Defaults to OverKill alone rather than everything: it's the channel with
    # the real history and the one worth seeing first, and because this
    # selection also scopes Refresh Now, defaulting to all seven would make
    # every casual refresh a seven-channel fetch. Widen the selection
    # deliberately when you want more.
    default_sel = [n for n in names if n == "OverKill"] or names
    fc, ft = st.columns([3, 2])
    with fc:
        picked = st.multiselect("Channels", names, default=default_sel,
                                key="yt_shorts_channels",
                                help="Filters the table AND scopes the Refresh button — "
                                     "only the channels selected here get scanned.")
    with ft:
        only_tickers = st.checkbox("Ticker calls only", value=False,
                                   key="yt_shorts_only_tickers",
                                   help="Hide general takeaways that have no ticker attached.")
    if picked:
        flat = [r for r in flat if r["channel"] in picked]
    if only_tickers:
        flat = [r for r in flat if r.get("ticker")]
    st.caption(f"Showing {len(flat)} row(s) from {len(picked) or len(names)} of "
               f"{len(names)} channel(s).")

    # Map the display names back to handles for the refresh call. Only pass
    # them when the selection is an actual subset -- "everything selected" and
    # "nothing selected" both mean scan all, and sending the full list would
    # just be a noisier way of saying the same thing.
    from scripts.yt_channels import CHANNELS as _ALL_CHANNELS
    name_to_handle = {c["name"]: c["handle"] for c in _ALL_CHANNELS}
    subset = (sorted({name_to_handle[n] for n in picked if n in name_to_handle})
              if picked and len(picked) < len(names) else None)

    _render_overkill_trigger(subset)
    _render_overkill_pending()
    _render_recent_ticker_line(flat)

    # "Dot" used to sit between Bias and Notes. It was set as
    # `dot = "Green" if bias == "Bullish" else "Red"` -- a recolouring of Bias
    # with no information of its own, and meaningless for channels that don't
    # trade a dot indicator. Its column now carries the source Channel.
    hdr = "".join(f'<th style="{_TH}">{h}</th>'
                  for h in ["Date", "Channel", "Ticker", "Bias", "Notes"])
    rows = ""
    for r in flat:
        url = r.get("url", "")
        if url:
            date_cell = ('<a href="' + url + '" target="_blank" title="' + str(r.get("video", "")) +
                         '" style="color:' + TEXT_MUTED + ';text-decoration:none;font-size:10px">' +
                         str(r.get("date", "")) + ' ↗</a>')
        else:
            date_cell = f'<span style="color:{TEXT_MUTED};font-size:10px">' + str(r.get("date", "")) + '</span>'
        ticker = str(r.get("ticker", ""))
        ticker_cell = (_mono(ticker, GOLD, 13, True) if ticker else
                       f'<span style="color:{TEXT_MUTED};font-size:10px">general</span>')
        rows += (
            "<tr>"
            + f'<td style="{_TD}">' + date_cell + "</td>"
            + f'<td style="{_TD};color:{ACCENT_BLUE};font-size:11px;font-weight:600;white-space:nowrap">'
            + str(r.get("channel", "")) + "</td>"
            + f'<td style="{_TD}">' + ticker_cell + "</td>"
            + f'<td style="{_TD}">' + _bias_html(r.get("bias", "Neutral")) + "</td>"
            + f'<td style="{_TD};white-space:normal;color:{TEXT_PRIMARY};font-size:11px;line-height:1.5">'
            + str(r.get("notes", "")) + "</td>"
            + "</tr>"
        )
    st.markdown(
        f'<div style="overflow-x:auto;border:1px solid {BORDER_COLOR};border-radius:10px;max-height:640px">'
        f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
        f'<thead><tr>{hdr}</tr></thead><tbody>{rows}</tbody></table></div>',
        unsafe_allow_html=True,
    )
    st.caption("One row per pick across all captured days. Detection + auto-extraction (Claude reads "
               "the transcript) runs once daily (~7am CT) via GitHub Actions. Any video where the "
               "transcript couldn't be fetched shows pending above instead of being silently dropped. "
               "Hit “Refresh Now” to check for new Shorts on demand.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — SECTOR ROTATION  (preserved from the original page)
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=1800, show_spinner=False)
def _sector_flows() -> list[dict]:
    from scanners.sector_rotation import SECTORS
    try:
        spy = get_price_history("SPY", period="1y")["Close"].squeeze()
    except Exception:
        return []

    def _ratio(c, b, n):
        try:
            return (float(c.iloc[-1]) / float(c.iloc[-n])) / (float(b.iloc[-1]) / float(b.iloc[-n]))
        except Exception:
            return 1.0

    rows = []
    for tkr, name in SECTORS:
        try:
            df = get_price_history(tkr, period="1y")
            close = df["Close"].squeeze()
            vol   = df["Volume"].squeeze()
            if len(close) < 70:
                continue
            rs63 = _ratio(close, spy, 63)
            rs21 = _ratio(close, spy, 21)
            dvol = (close * vol).dropna()
            flow = float(dvol.iloc[-5:].mean()) / float(dvol.iloc[-63:].mean()) if len(dvol) >= 63 else 1.0
            # Dead-band so a sector sitting flat against SPY isn't promoted into a
            # strength quadrant on a knife-edge. Validated on 2026-08-24 close data:
            # XLK (rs21=1.000, rank #13, flat vs SPY) was reading "Improving — money
            # arriving" purely because rs21 cleared 1.0 by +0.0%, directly
            # contradicting the (correct) outlook card's "Flat/Weakening". Requiring
            # a real >0.25% edge to count as "up" demotes only genuinely-flat sectors
            # (only XLK & QQQ on that day); every sector with an actual edge
            # (XLY +3.3%, XLC +1.0%) is unchanged.
            _band = 0.0025
            up63, up21 = rs63 >= 1 + _band, rs21 >= 1 + _band
            quad = ("Leading" if up63 and up21 else
                    "Weakening" if up63 else
                    "Improving" if up21 else "Lagging")
            rows.append({"tkr": tkr, "name": name, "rs63": rs63, "rs21": rs21,
                         "flow": round(flow, 2), "quad": quad,
                         "ret1m": round((float(close.iloc[-1]) / float(close.iloc[-21]) - 1) * 100, 1)
                                  if len(close) >= 21 else 0.0})
        except Exception:
            continue
    return rows


# Hand-curated candidate pool per real GICS sector ETF (~15 well-known,
# liquid names each) -- there's no sector-constituent data source in this
# codebase, so this is a reasonable stand-in universe to rank within.
# QQQ/IWM/GLD/TLT are intentionally excluded: they aren't a sector basket
# of stocks (GLD is bullion, TLT is bonds), so they get no leaders list.
_SECTOR_CANDIDATES = {
    "XLK":  ["AAPL","MSFT","NVDA","AVGO","ORCL","CRM","ADBE","AMD","CSCO","ACN","QCOM","TXN","INTU","IBM","NOW"],
    "XLF":  ["BRK-B","JPM","V","MA","BAC","WFC","GS","MS","SPGI","AXP","C","SCHW","BLK","PGR","MMC"],
    "XLV":  ["LLY","UNH","JNJ","ABBV","MRK","TMO","ABT","PFE","DHR","AMGN","ISRG","BMY","GILD","CVS","MDT"],
    "XLI":  ["GE","CAT","RTX","UNP","HON","UPS","BA","DE","LMT","ETN","ADP","GD","MMM","WM","NOC"],
    "XLE":  ["XOM","CVX","COP","EOG","SLB","MPC","PSX","WMB","OXY","VLO","KMI","HES","BKR","OKE","TRGP"],
    "XLY":  ["AMZN","TSLA","HD","MCD","NKE","LOW","BKNG","TJX","SBUX","CMG","MAR","ORLY","AZO","ROST","YUM"],
    "XLP":  ["PG","KO","PEP","COST","WMT","PM","MDLZ","MO","CL","TGT","KMB","GIS","STZ","KDP","SYY"],
    "XLC":  ["GOOGL","META","NFLX","DIS","CMCSA","TMUS","VZ","T","CHTR","EA","WBD","OMC","TTWO","MTCH","PARA"],
    "XLB":  ["LIN","SHW","FCX","ECL","APD","NEM","DOW","DD","NUE","VMC","MLM","PPG","ALB","IFF","CTVA"],
    "XLRE": ["PLD","AMT","EQIX","PSA","WELL","SPG","O","DLR","CCI","CBRE","AVB","EQR","VTR","EXR","INVH"],
    "XLU":  ["NEE","SO","DUK","CEG","AEP","SRE","D","EXC","XEL","ED","WEC","PEG","ES","AWK","DTE"],
}


@st.cache_data(ttl=14400, show_spinner=False)   # 4h -- "which names lead the sector" moves
def _sector_leaders() -> dict:                  # slower than the live RS quadrant, no need to refresh every 30 min
    """For each real GICS sector ETF, up to 10 candidate tickers currently
    beating THAT SECTOR'S OWN ETF (63d RS vs the ETF, not vs SPY -- a
    different question than the sector-vs-market table: "which names are
    leading the sector" rather than "is the sector leading the market").

    Returns {etf: [(ticker, extended), ...]} ranked purely by RS, strongest
    first. `extended` (RSI>68 or >6% above EMA9 -- the same threshold
    scanners/sector_rotation.py uses for its own trade ideas) is passed
    through for display rather than used to reorder; see the note below."""
    all_tickers = sorted({t for cands in _SECTOR_CANDIDATES.values() for t in cands}
                         | set(_SECTOR_CANDIDATES.keys()))
    prefetch_tickers(all_tickers, "6mo", "1d")

    out = {}
    for etf, candidates in _SECTOR_CANDIDATES.items():
        try:
            etf_close = get_price_history(etf, period="6mo")["Close"].squeeze()
        except Exception:
            out[etf] = []
            continue
        scored = []
        for t in candidates:
            try:
                close = get_price_history(t, period="6mo")["Close"].squeeze()
                n = min(len(close), len(etf_close), 63)
                if n < 63:
                    continue
                rs = ((float(close.iloc[-1]) / float(close.iloc[-n]))
                      / (float(etf_close.iloc[-1]) / float(etf_close.iloc[-n])))
                rsi_now = float(_rsi(close).iloc[-1])
                ema9_now = float(_ema(close, 9).iloc[-1])
                pct_above_ema9 = (float(close.iloc[-1]) / ema9_now - 1) * 100 if ema9_now else 0.0
                extended = rsi_now > 68 or pct_above_ema9 > 6
                scored.append((t, rs, extended))
            except Exception:
                continue
        # Pure RS ranking -- strongest first, extended or not. The previous
        # ordering placed every non-extended name ahead of every extended one,
        # which reads like a mild preference but measured out as total
        # exclusion: clean counts run 11-15 per sector, always at or above the
        # 10-name cap, so no extended name EVER surfaced -- 15 of them were
        # invisible across the table, including MSFT/ORCL/INTU/ACN in Tech.
        # They're extended *because* they're leading, so a column headed
        # "Leaders" was systematically hiding the leaders. Rank on merit now
        # and pass `extended` through for the caller to mark, keeping
        # leadership and entry quality as the two separate questions they are.
        scored.sort(key=lambda x: -x[1])
        out[etf] = [(t, ext) for t, _rs, ext in scored[:10]]
    return out


# Position-only vocabulary. Card 1 (this standings table) says WHERE a sector
# stands now; the "Where is the money heading?" card above owns the trajectory
# verb. The old text bolted a second momentum verb onto the position
# ("Leading but Decelerating"), which fought the card above word-for-word for
# the same sector -- the reported XLV contradiction. Backtesting that arrow
# (2005-2017, 9 SPDR sectors) found it near-noise for forward relative return,
# so the position label loses nothing by dropping it. One axis per card means
# the two can never disagree on momentum, because only one of them speaks it.
_SIGNAL_TEXT = {
    "Leading":   "Leading — money is here now",
    "Improving": "Improving — money arriving",
    "Weakening": "Weakening — money thinning",
    "Lagging":   "Lagging — money elsewhere",
}


def _plain_signal(quad: str) -> str:
    """Position-only label for the standings card. Whether the lead is still
    growing is answered by the trajectory card above, not here -- one axis per
    card so the two never use competing momentum words for one sector."""
    return _SIGNAL_TEXT.get(quad, _SIGNAL_TEXT["Lagging"])


def _render_sectors():
    # Forward-looking card FIRST. The ranking below it answers "where has
    # money been" -- a 63-day verdict, structurally late -- and that is the
    # question a reader asks second, not first.
    try:
        _render_sector_outlook()
    except Exception as e:
        st.caption(f"Sector outlook unavailable: {e}")

    rows = _sector_flows()
    if not rows:
        st.markdown(_card("Sector Rotation", "🔄", MINT,
                          f'<div style="color:{TEXT_MUTED};padding:20px">Sector data unavailable.</div>'),
                    unsafe_allow_html=True)
        return

    q_col = {"Leading": ACCENT_GREEN, "Improving": ACCENT_BLUE, "Weakening": GOLD, "Lagging": ACCENT_RED}
    q_ic  = {"Leading": "💰", "Improving": "📈", "Weakening": "⚠️", "Lagging": "🚪"}

    ranked = sorted(rows, key=lambda r: -r["rs63"])
    max_dev = max((abs(r["rs63"] - 1) for r in ranked), default=0.01) or 0.01
    GRID = "grid-template-columns:132px 100px 48px 76px 70px 72px 60px 152px 356px"
    leaders_by_etf = _sector_leaders()

    # Momentum as a readable percentage rather than a bare ratio difference:
    # "-3.1%" says how far last month's edge ran behind the 3-month pace,
    # where "-0.0306" says nothing to a reader. The ratio and difference forms
    # were checked against live data and classify all 15 rows identically, so
    # this is purely a units change. Computed up here because the FOCUS chips
    # rank on it too.
    for r in ranked:
        r["mom_pct"] = (r["rs21"] / r["rs63"] ** (21 / 63) - 1) * 100
        # rs21 drives the quadrant but was never displayed anywhere -- shown
        # now as the "vs SPY" line. Ratio-excess rather than a plain
        # percentage-point subtraction, to stay consistent with the RS column
        # and the quadrant; measured max divergence between the two is 0.24pp.
        r["vs_spy"] = (r["rs21"] - 1) * 100

    bar_rows = ""
    for r in ranked:
        col = q_col.get(r["quad"], TEXT_MUTED)
        dev = r["rs63"] - 1.0
        w = min(abs(dev) / max_dev * 46, 46)
        left = 48 if dev >= 0 else 48 - w
        bar = (f'<div style="position:absolute;left:{left:.0f}px;top:0;bottom:0;'
               f'width:{max(w,1):.0f}px;background:{col};border-radius:3px;opacity:0.9"></div>')
        # rs21 and rs63 are CUMULATIVE ratios over different horizons, so
        # subtracting them raw isn't an acceleration measure -- three months of
        # compounding beats one month of it even at a perfectly constant rate,
        # so every RS>1 sector reads "decelerating" and every RS<1 one reads
        # "accelerating". Measured against live data, the raw difference
        # correlates -0.85 with (rs63-1): the arrow was mostly restating the RS
        # column. Taking the geometric mean per 21-day block puts both on the
        # same footing -- last month's edge vs the average monthly edge over
        # three months -- which drops that correlation to -0.39 (the remainder
        # is real: sectors that have run hard do tend to cool off).
        mom_pct = r["mom_pct"]
        if mom_pct > 0.5:
            m_arrow, m_col = "▲", ACCENT_GREEN
        elif mom_pct < -0.5:
            m_arrow, m_col = "▼", ACCENT_RED
        else:
            m_arrow, m_col = "▬", TEXT_MUTED
        mom_cell = (f'<span style="color:{m_col};font-family:\'DM Mono\',monospace;'
                    f'font-size:11px;font-weight:600">{m_arrow} {mom_pct:+.1f}%</span>')

        # Absolute return and market-relative return as SEPARATE columns, not
        # stacked in one cell. Same two numbers either way, but stacking made
        # every row double-height (15 rows of it) and left the relative figure
        # unreadable down the column, which is exactly how you'd want to scan
        # it. The absolute number alone was the page's biggest source of
        # confusion -- a sector can be up 6% and still be losing ground when
        # SPY is up more, which is what every other column here measures.
        ret = r["ret1m"]; ret_col = ACCENT_GREEN if ret >= 0 else ACCENT_RED
        vs_col = ACCENT_GREEN if r["vs_spy"] >= 0 else ACCENT_RED
        ret_cell = (f'<span style="color:{ret_col};font-family:\'DM Mono\',monospace;'
                    f'font-size:11px;font-weight:600">{ret:+.1f}%</span>')
        vs_cell = (f'<span style="color:{vs_col};font-family:\'DM Mono\',monospace;'
                   f'font-size:11px;font-weight:600">{r["vs_spy"]:+.1f}%</span>')

        if r["flow"] >= 1.15:
            flow_badge = f'<span style="color:{GOLD};font-size:10px;font-weight:700">💰{r["flow"]:.1f}x</span>'
        else:
            flow_badge = f'<span style="color:{TEXT_MUTED};font-size:10px">{r["flow"]:.1f}x</span>'
        name = str(r["name"])[:12]
        signal_txt = _plain_signal(r["quad"])
        signal_cell = f'<span style="color:{col};font-size:11px;font-weight:600">{signal_txt}</span>'

        # Three states, ranked strictly by RS either way:
        #   gold + °  extended -- leading, but not an easy entry
        #   green     the strongest name that ISN'T extended (best entry)
        #   white     everything else
        # Whole sectors can run extended at the top (XLE opens MPC°/VLO°/PSX°),
        # and that is real information worth keeping -- but it buried the
        # answer to "so what do I actually buy". Colour answers both at once
        # without a second list or another column. Extended keeps its degree
        # mark so the distinction survives greyscale and colour-blindness;
        # green is positional (always exactly one per sector) so it stays
        # readable from ordering alone.
        leader_pairs = leaders_by_etf.get(r["tkr"], [])
        first_clean = next((i for i, (_t, ext) in enumerate(leader_pairs) if not ext), None)
        leaders_cell = (f'<span style="font-family:\'DM Mono\',monospace;'
                        f'font-size:10.5px;white-space:nowrap">'
                        + ", ".join(
                            f'<span style="color:{GOLD}">{t}°</span>' if ext
                            else f'<span style="color:{ACCENT_GREEN};font-weight:700">{t}</span>'
                            if i == first_clean
                            else f'<span style="color:{TEXT_PRIMARY}">{t}</span>'
                            for i, (t, ext) in enumerate(leader_pairs))
                        + "</span>") if leader_pairs else \
                       f'<span style="color:{TEXT_MUTED};font-size:11px">—</span>'
        bar_rows += (
            f'<div style="display:grid;{GRID};align-items:center;gap:6px;padding:3px 0;'
            f'border-bottom:1px solid #2A2A3A22">'
            + f'<span style="color:{col};font-family:\'DM Mono\',monospace;font-size:11px;'
            + f'font-weight:700">' + q_ic.get(r["quad"], "") + " " + str(r["tkr"])
            + f'<span style="color:{TEXT_MUTED};font-weight:400"> ' + name + "</span></span>"
            + f'<div style="position:relative;height:12px;background:#2A2A3A33;border-radius:3px">'
            + f'<div style="position:absolute;left:48px;top:-2px;bottom:-2px;width:1px;'
            + f'background:{TEXT_MUTED}66"></div>' + bar + "</div>"
            + f'<span style="color:{col};font-family:\'DM Mono\',monospace;font-size:11px;'
            + f'font-weight:700">' + "{:.3f}".format(r["rs63"]) + "</span>"
            + mom_cell + ret_cell + vs_cell
            + flow_badge + signal_cell + leaders_cell + "</div>"
        )

    header = (f'<div style="display:grid;{GRID};gap:6px;padding:0 0 4px;color:{TEXT_MUTED};'
              f'font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px">'
              f'<span>Sector</span><span>3-Mo vs SPY</span><span>RS 63d</span>'
              f'<span>Momentum</span><span>1-Mo Return</span><span>1-Mo vs SPY</span>'
              f'<span>Activity</span>'
              f'<span>Position (now)</span><span>Sector Leaders (° = extended)</span></div>')

    # Leaders and emerging names are two different trades, so they get two
    # different chip rows. Previously both shared one list ranked by RS63,
    # which structurally buried the emerging ones -- an early-rotation sector
    # is defined by having a LOW RS63, so ranking that group by RS63 promotes
    # whichever is closest to already-leading and drops the sharpest turns.
    # GLD is the live example: strongest momentum on the board and the only
    # elevated Activity reading, yet absent from the old FOCUS chips entirely.
    core  = [r for r in ranked if r["quad"] == "Leading"][:4]
    early = sorted([r for r in ranked if r["quad"] == "Improving"],
                   key=lambda r: -r["mom_pct"])[:4]
    sells = sorted([r for r in ranked if r["quad"] in ("Lagging", "Weakening")],
                   key=lambda r: r["rs63"])[:4]
    core_chips  = " ".join(_chip(r["tkr"] + " " + r["name"], ACCENT_GREEN) for r in core) or "—"
    early_chips = " ".join(_chip(r["tkr"] + " " + r["name"], ACCENT_BLUE) for r in early) or "—"
    sell_chips  = " ".join(_chip(r["tkr"] + " " + r["name"], ACCENT_RED) for r in sells) or "—"
    summary = (
        f'<div style="margin-top:10px;display:flex;flex-direction:column;gap:6px">'
        f'<div style="font-size:11px"><span style="color:{ACCENT_GREEN};font-weight:800">'
        f'💰 CORE LEADERS: </span>{core_chips}'
        f'<span style="color:{TEXT_MUTED};font-size:9px"> &nbsp;already strong and still ahead</span></div>'
        f'<div style="font-size:11px"><span style="color:{ACCENT_BLUE};font-weight:800">'
        f'📈 EARLY ROTATION: </span>{early_chips}'
        f'<span style="color:{TEXT_MUTED};font-size:9px"> &nbsp;still behind, but turning up fastest</span></div>'
        f'<div style="font-size:11px"><span style="color:{ACCENT_RED};font-weight:800">'
        f'🚪 AVOID: </span>{sell_chips}'
        f'<span style="color:{TEXT_MUTED};font-size:9px"> &nbsp;weakest relative strength</span></div></div>'
        f'<div style="color:{TEXT_MUTED};font-size:9px;margin-top:8px;line-height:1.5">'
        f'<b style="color:{TEXT_PRIMARY}">This card is POSITION — where each sector stands now (63-day rank). '
        f'Whether that standing is still improving is the “Where is the money heading?” card above; '
        f'a sector can lead here yet be strengthening (or cooling) there — two lenses, not a contradiction.</b><br>'
        f'<b>3-Mo vs SPY</b> — bar diverges from the centre line (= SPY): green/blue = '
        f'leading/improving · gold/red = weakening/lagging. <b>RS 63d</b> is that same figure '
        f'as a ratio (1.10 = beat SPY by ~10% over three months). '
        f'<b>Momentum</b> compares the last month\'s edge over SPY against its own 3-month '
        f'average pace, so ▲ means genuinely picking up speed, not merely still winning. '
        f'<b>1-Mo Return</b> is the sector\'s own move; <b>1-Mo vs SPY</b> is that same '
        f'month measured against the market — a sector can rise and still lose ground '
        f'when SPY rises more, which is what the rest of this table is measuring. '
        f'<b>Activity</b> is 5-day vs 63-day dollar volume (💰 ≥1.15×): it measures how much '
        f'is trading, <b>not</b> whether that is buying or selling. '
        f'<b>Leaders</b> = up to 10 names beating THAT SECTOR\'S own ETF (not just SPY), '
        f'strongest first; <span style="color:{GOLD}">gold°</span> = already extended '
        f'(RSI&gt;68 or &gt;6% above EMA9), i.e. leading but not an easy entry, and '
        f'<span style="color:{ACCENT_GREEN};font-weight:700">green</span> = the strongest '
        f'name that isn\'t extended — the pick when the top of a sector has run away. '
        f'Leaders update every 4h, the rest every 30 min. '
        f'QQQ/IWM/GLD/TLT have no leaders list (not a stock sector).</div>'
    )

    st.markdown(_card("Sector Standings — where the money is now", "🔄", MINT,
                      header + bar_rows + summary), unsafe_allow_html=True)

    # ── Freshness, history and validation ─────────────────────────────────
    # Everything above is computed off the LAST bar, and during market hours
    # that bar is still forming -- so the table legitimately moves between
    # refreshes (and _sector_flows caches for 30 min on top, which makes the
    # movement arrive in jumps rather than smoothly). Say which of the two is
    # happening, then offer the history that tells signal from noise.
    _render_sector_tracking(ranked)


def _render_sector_outlook():
    """Momentum-of-relative-strength view, rendered above the ranking card.

    Shares _sector_history_cached with the tracking panels below, so the two
    are computed from one series and cannot disagree.
    """
    from scanners.sector_outlook import render_outlook
    from scanners.sector_rotation import SECTORS, _sector_history_cached

    try:
        spy = get_price_history("SPY", period="1y")
        if spy is None or spy.empty:
            return
        as_of = pd.Timestamp(spy["Close"].squeeze().index[-1]).strftime("%Y-%m-%d")
    except Exception:
        return

    hist = _sector_history_cached(as_of=as_of)
    if hist is None or hist.empty:
        return
    render_outlook(hist, SECTORS)


def _render_sector_tracking(ranked: list[dict]):
    """Freshness label + Rotation History + independent validation, shared
    with the Strategies page's Sector Rotation tab.

    The panels live in scanners/sector_rotation.py so both pages show the
    same history rather than two implementations that can disagree. They key
    off the ticker list only, so the fact that this tab ranks by its own
    rs63/quadrant maths and that one by RS-vs-SPY does not matter -- both are
    the 63-day ratio against SPY, and the history is rebuilt from prices
    either way.
    """
    from scanners.sector_rotation import (
        _is_live_bar, _render_history_panel, _render_validation_panel,
        _sector_history_cached,
    )

    try:
        spy = get_price_history("SPY", period="1y")
        spy_close = spy["Close"].squeeze() if spy is not None and not spy.empty else None
        if spy_close is None or spy_close.empty:
            return
        live = _is_live_bar(spy_close)
        as_of = pd.Timestamp(spy_close.index[-1]).strftime("%Y-%m-%d")
    except Exception:
        return

    col = GOLD if live else ACCENT_GREEN
    lbl = ("⚡ LIVE BAR — today's session is still open, so these numbers move "
           "with the tape") if live else \
          "✓ Settled close — these numbers are fixed until the next session"
    st.markdown(
        f'<div style="background:{col}12;border-left:3px solid {col};'
        f'padding:6px 12px;border-radius:0 6px 6px 0;margin:10px 0 12px;'
        f'color:{TEXT_MUTED};font-size:11px">'
        f'<b style="color:{col}">{lbl}</b> · last bar {as_of}</div>',
        unsafe_allow_html=True,
    )

    try:
        hist = _sector_history_cached(as_of=as_of)
        order = pd.DataFrame([{"Ticker": r["tkr"], "Sector": r["name"]} for r in ranked])
        # Quadrant vocabulary, not trade actions: the card directly above
        # already labels these sectors Leading/Improving/Weakening/Lagging,
        # and two names for one state on one screen confuses more than it
        # informs.
        _render_history_panel(order, hist, label_col="Quadrant")
        _render_validation_panel(order, key_prefix="home_sr")
    except Exception as e:
        st.caption(f"Rotation history unavailable: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN RENDER
# ══════════════════════════════════════════════════════════════════════════════

def render():
    now_et = datetime.now(pytz.timezone("US/Eastern")).strftime("%A %b %d %Y · %I:%M %p ET")
    section_header("🏠", "Market Overview", f"Command Center · {now_et}")

    _, col_btn = st.columns([6, 1])
    with col_btn:
        if st.button("🔄 Refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    with st.spinner("Reading market regime…"):
        try:
            _render_regime_bar()
        except Exception:
            st.warning("Regime bar unavailable.")

    # "Shorts Perf" and "Shorts Backtest" are deliberately different things:
    # Perf scores the picks auto-extracted from the videos, Backtest scores a
    # hand-curated list of OverKill scanner alerts (Golden Dot / Weekly /
    # Monthly / Daily) that has no connection to the Shorts feed.
    tab1, tab3, tab4, tab2, tab6, tab5 = st.tabs(
        ["🎯  Best Scanners", "🔄  Sector Rotation", "🔍  OverKill",
         "📺  YouTube Shorts", "📊  Shorts Perf", "🎯  Shorts Backtest"]
    )

    with tab1:
        try:
            _render_best_scanners_tab()
        except Exception as e:
            st.error(f"Best-scanners tab error: {e}")

    with tab3:
        with st.spinner("Computing sector flows…"):
            try:
                _render_sectors()
            except Exception:
                st.warning("Sector rotation unavailable.")

    with tab4:
        try:
            overkill_check.render()
        except Exception as e:
            st.error(f"Overkill Check tab error: {e}")

    with tab2:
        try:
            _render_overkill_tab()
        except Exception as e:
            st.error(f"OverKill Shorts tab error: {e}")

    with tab6:
        try:
            overkill_shorts_perf.render()
        except Exception as e:
            st.error(f"Shorts Perf tab error: {e}")

    with tab5:
        try:
            overkill_performance.render()
        except Exception as e:
            st.error(f"Shorts Backtest tab error: {e}")

    st.markdown(
        f'<div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};'
        f'border-radius:6px;padding:10px 16px;color:{TEXT_MUTED};font-size:10px;'
        f'text-align:center;margin-top:6px">⚠️ <b>Disclaimer:</b> Golden Scanner is for '
        f'educational and research purposes only. Signals are technical readings, not '
        f'financial advice. Do your own due diligence.</div>',
        unsafe_allow_html=True,
    )
