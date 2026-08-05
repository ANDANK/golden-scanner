# scanners/home.py — Market Overview (rewritten 2026-07-23)
#
# Layout:
#   ┌─ Market-regime header (Risk-On/Mixed/Off · indices · breadth) ─┐
#   ├─ Tab 1  🎯 Best Scanners  — the 6 keeper scanners over a universe
#   ├─ Tab 2  📺 OverKill Shorts — curated watch-list from the YouTube shorts
#   ├─ Tab 3  🔄 Sector Rotation — RRG-style flows (preserved from the old page)
#   └─ Tab 4  🔍 Overkill Check — WaveTrend dot + Volume Profile confluence
#             scan on any user-entered ticker(s) (see scanners/overkill_check.py)
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

_LABELS = ["1Mom", "2TC", "3MF", "4TS", "5RB", "6Prime", "7Square", "8Cross"]

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
    a plain-language verdict plus the numbers behind it; 'Too New' means
    nothing on the shortlist matched -- not a bad sign, just unconfirmed.

    A ticker can match several shortlist combos at once (e.g. matching both
    1Mom+8Cross and a smaller-sample triple that happens to have a bigger raw
    number) -- confidence tier wins first, score only breaks ties within the
    same tier, so a flashier thin-sample number never outranks a validated
    high-confidence one. (Not "first match wins" by list order -- checked and
    fixed after a test caught exactly this ordering bug.)"""
    label_set = frozenset(labels)
    matches = [entry for entry in _EDGE_SHORTLIST if entry[0] <= label_set]
    if not matches:
        return dict(verdict="Too New", confidence=None, score=None, n=None,
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
    "FTF Universe (~480 · full S&P 500 + ETFs)": "FTF",
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
                rows.append(snap)
        except Exception:
            continue
    prog.empty()

    df_out = pd.DataFrame(rows)
    if not df_out.empty:
        # Strong Setup first, then Mixed Signal, then Too New; within a tier,
        # higher edge score first. Replaces the old _count-based sort now that
        # raw scanner count is known not to be a reliable ranker (see the
        # cross-run analysis -- it doesn't move monotonically either way).
        verdict_rank = {"Strong Setup": 2, "Mixed Signal": 1, "Too New": 0}
        df_out["_verdict_rank"] = df_out["_verdict"].map(verdict_rank)
        df_out = df_out.sort_values(
            ["_verdict_rank", "_edge_score"], ascending=[False, False], na_position="last"
        ).drop(columns="_verdict_rank").reset_index(drop=True)
    return df_out


_SORT_COLUMNS = {
    # Both options rank by Verdict tier first (Strong Setup > Mixed Signal > Too New),
    # then by Edge Score within a tier -- a thin-sample combo's flashy score can no
    # longer outrank a well-validated one just because "Edge Score" was picked.
    "Verdict": ["_verdict_rank_n", "_edge_score_n"],
    "Edge Score": ["_verdict_rank_n", "_edge_score_n"],
    "Ticker": "Ticker",
    "Price": "Price",
    "Chg %": "Chg %",
    "RSI D": "RSI D",
    "Vol×": "Vol×",
    "RS·SPY": "RS·SPY",
}

_VERDICT_COLOR = {"Strong Setup": ACCENT_GREEN, "Mixed Signal": GOLD, "Too New": TEXT_MUTED}
_VERDICT_RANK = {"Strong Setup": 2, "Mixed Signal": 1, "Too New": 0}


def _hold_range_text(hold_range) -> str:
    if not hold_range or (isinstance(hold_range, float) and pd.isna(hold_range)):
        return "—"
    lo, hi = hold_range
    return f"{lo}-{hi}d"


_ROW_COL_RATIOS = [0.35, 0.85, 0.55, 0.5, 0.55, 0.5, 1.4, 0.7, 0.9, 0.6, 0.8, 1.1]
_ROW_HEADERS = ["", "Verdict", "Hold", "Ticker", "Price", "Chg %", "Scanners", "RSI W/D",
                "MACD", ">SMA 9/20", "Vol× / RS", "Flags"]


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
        "Hold": df["_hold_range"].apply(_hold_range_text),
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
            v_color = _VERDICT_COLOR.get(r["Verdict"], TEXT_MUTED)
            cols[1].markdown(f'<span style="color:{v_color};font-weight:600;font-size:11.5px">{r["Verdict"]}</span>',
                             unsafe_allow_html=True)
            cols[2].markdown(f'<span style="color:{TEXT_MUTED};font-size:11.5px">{r["Hold"]}</span>',
                             unsafe_allow_html=True)
            cols[3].markdown(f'<span style="{tk_style}">{ticker}</span>', unsafe_allow_html=True)
            cols[4].markdown(f'${r["Price"]:,.2f}')
            cols[5].markdown(_chg_html(r["Chg %"]), unsafe_allow_html=True)
            cols[6].markdown(f'<span style="font-size:11.5px">{r["Scanners"]}</span>', unsafe_allow_html=True)
            cols[7].markdown(f'W{r["RSI W"]:.0f} / D{r["RSI D"]:.0f}')
            cols[8].markdown(f'{_b(r["MACD>Sig"])} {r["MACD Zone"]}')
            cols[9].markdown(f'{_b(r[">SMA9"])} / {_b(r[">SMA20"])}')
            cols[10].markdown(f'{r["Vol×"]:.2f}x / {r["RS·SPY"]:.2f}')
            cols[11].markdown(f'<span style="color:{TEXT_MUTED};font-size:11px">{r["Flags"] or "—"}</span>',
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


_EDGE_LEGEND = [
    ("Strong Setup", ACCENT_GREEN,
     "This exact scanner combination has clearly beaten the market historically, "
     "backed by a large number of past examples."),
    ("Mixed Signal", GOLD,
     "Some historical edge, but backed by fewer past examples — worth a look, not a first pick."),
    ("Too New", TEXT_MUTED,
     "We haven't seen this exact combination often enough yet to say whether it works."),
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


def _render_best_scan_mode():
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:12px;line-height:1.7;margin-bottom:10px">'
        f'The six keeper scanners plus two early-signal add-ons (<b>7Square</b> · <b>8Cross</b>) '
        f'run over one universe and merge into a single table. The <b>Scanners</b> column lists '
        f'every scanner that flagged the ticker — <b style="color:{ACCENT_GREEN}">2+ = confluence</b> '
        f'(sorted first). <b>8Cross·W</b> = the EMA20/50 cross also shows on the weekly.</div>',
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

    if clear:
        st.session_state.pop("home_best_df", None)
        st.session_state.pop("home_best_ts", None)
        st.rerun()

    if run:
        universe = _resolve_universe(_UNIVERSE_CHOICES[uni_label])
        st.info(f"Scanning {len(universe)} tickers across 6 scanners — this takes a few minutes.")
        df = _run_best_scanners(universe)
        st.session_state["home_best_df"] = df
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
        exp = df.drop(columns=["_count", "x8_weekly"], errors="ignore").copy()
        exp["Flags"] = exp["Flags"].apply(lambda x: "; ".join(x) if isinstance(x, list) else x)
        st.download_button("⬇ CSV", exp.to_csv(index=False), "best_scanners.csv",
                           "text/csv", use_container_width=True, key="home_best_csv")

    selected_ticker = _render_best_table(df)
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


def _trigger_overkill_workflow() -> tuple:
    """POST a workflow_dispatch event. Returns (ok, message)."""
    token = _get_github_token()
    if not token:
        return False, ("No GitHub token configured. Add **GITHUB_TOKEN** (a PAT with `actions:write` "
                        "or `repo` scope on this repo) to your Streamlit secrets to enable this button.")
    url = (f"https://api.github.com/repos/{_GH_OWNER}/{_GH_REPO}/actions/workflows/"
           f"{_GH_WORKFLOW_FILE}/dispatches")
    try:
        r = requests.post(url, headers=_gh_headers(token), json={"ref": "main"}, timeout=15)
    except Exception as e:
        return False, f"Request failed: {e}"
    if r.status_code == 204:
        return True, "Triggered — the run usually finishes in a minute or two. Use *Check status* below."
    if r.status_code == 401:
        return False, "GitHub rejected the token (401) — GITHUB_TOKEN may be invalid or expired."
    if r.status_code == 404:
        return False, "Workflow or repo not found (404) — check the token has access to this repo."
    return False, f"GitHub API error {r.status_code}: {r.text[:200]}"


def _latest_overkill_run():
    """Fetch the most recent run of the refresh workflow, or None on failure."""
    token = _get_github_token()
    if not token:
        return None
    url = (f"https://api.github.com/repos/{_GH_OWNER}/{_GH_REPO}/actions/workflows/"
           f"{_GH_WORKFLOW_FILE}/runs")
    try:
        r = requests.get(url, headers=_gh_headers(token), params={"per_page": 1}, timeout=15)
        r.raise_for_status()
        runs = r.json().get("workflow_runs", [])
        return runs[0] if runs else None
    except Exception:
        return None


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


def _render_overkill_trigger():
    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("🔄 Refresh Now", key="overkill_trigger_btn",
                      help="Runs the GitHub Action that pulls new Shorts, right from here"):
            with st.spinner("Triggering GitHub Action…"):
                ok, msg = _trigger_overkill_workflow()
            (st.success if ok else st.error)(msg)
    with c2:
        if st.button("Check latest run status", key="overkill_status_btn"):
            with st.spinner("Checking…"):
                run = _latest_overkill_run()
            if run is None:
                st.info("Couldn't fetch run status — check GITHUB_TOKEN in secrets.")
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

    # Always-visible debug so token problems are self-diagnosable without asking Claude
    token = _get_github_token()
    with st.expander("🔧 Debug — GitHub token status", expanded=not token):
        if token:
            preview = token[:12] + "…" if len(token) > 12 else token
            st.markdown(f"**Token read:** `{preview}` (length {len(token)})")
            st.caption("If buttons still error with 401, the token is invalid/expired — regenerate it. "
                       "If 404, its repo access or Actions permission isn't set on golden-scanner.")
        else:
            st.markdown("**Token read:** *(not found)* — `st.secrets[\"GITHUB_TOKEN\"]` returned nothing.")
            st.caption("On Streamlit Cloud: Settings → Secrets must contain a top-level line "
                       "`GITHUB_TOKEN = \"github_pat_...\"` (exact key name, not nested under a section). "
                       "After saving, the app should auto-reboot — if this still shows 'not found' after "
                       "a minute, use 'Reboot app' from the Cloud menu to force it.")


def _render_overkill_pending():
    """Semi-auto model: the GitHub Action only detects new Shorts (via the
    official YouTube API — reliable) and lists them here. Pulling transcripts
    and extracting picks is done on request in a Claude session, since
    yt-dlp gets blocked wholesale by YouTube's bot-check from GitHub Actions'
    shared IPs ('Sign in to confirm you're not a bot' — IP-reputation based,
    not fixable by spoofing a different yt-dlp client)."""
    path = os.path.join(DATA_DIR, "overkill_pending.json")
    try:
        with open(path, encoding="utf-8") as f:
            pending_data = json.load(f)
    except Exception:
        return
    pending = pending_data.get("pending", [])
    if not pending:
        return
    items = "".join(
        f'<li style="margin-bottom:4px"><a href="{p.get("url","")}" target="_blank" '
        f'style="color:{TEXT_PRIMARY}">{p.get("title","")}</a> '
        f'<span style="color:{TEXT_MUTED};font-size:10px">· {p.get("date","")}</span></li>'
        for p in pending
    )
    st.markdown(
        f'<div style="background:{_rgba(GOLD, 0.08)};border:1px solid {GOLD}44;border-radius:10px;'
        f'padding:12px 16px;margin:4px 0 14px">'
        f'<div style="color:{GOLD};font-size:12px;font-weight:700;margin-bottom:6px">'
        f'🕒 {len(pending)} new Short(s) detected, not yet analyzed</div>'
        f'<ul style="margin:0;padding-left:18px;font-size:12px">{items}</ul>'
        f'<div style="color:{TEXT_MUTED};font-size:10.5px;margin-top:8px">'
        f'Ask Claude to pull picks for these — automatic extraction is blocked by '
        f'YouTube\'s bot-check on GitHub Actions.</div></div>',
        unsafe_allow_html=True,
    )


def _render_overkill_tab():
    path = os.path.join(DATA_DIR, "overkill_shorts.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        st.info("No OverKill Shorts summary stored yet.")
        return

    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:12px;line-height:1.7;margin-bottom:10px">'
        f'Latest stock picks from <b>{data.get("channel","@overkilltrading")}</b> Shorts '
        f'(crypto skipped). <b>Dot</b> = his wave-indicator call <i>as stated in the video</i> '
        f'(🟢 Green = buy · 🔴 Red = sell/trim · — = not formed). '
        f'Updated <b>{data.get("updated","")}</b> · not financial advice.</div>',
        unsafe_allow_html=True,
    )

    _render_overkill_trigger()
    _render_overkill_pending()

    def _bias_html(b):
        col = ACCENT_GREEN if b == "Bullish" else ACCENT_RED if b == "Bearish" else TEXT_MUTED
        return f'<span style="color:{col};font-weight:700;font-size:11px">{b}</span>'

    def _dot_html(d):
        if d == "Green":
            return '<span style="color:#34D399;font-size:13px">🟢 Green</span>'
        if d == "Red":
            return '<span style="color:#F87171;font-size:13px">🔴 Red</span>'
        return f'<span style="color:{TEXT_MUTED};font-size:11px">— none</span>'

    flat = []
    for vid in data.get("videos", []):
        for p in vid.get("picks", []):
            row = dict(p)
            row["date"]  = vid.get("date", "")
            row["video"] = vid.get("title", "")
            row["url"]   = vid.get("url", "")
            flat.append(row)
    flat.sort(key=lambda r: (r.get("date", ""), r.get("ticker", "")), reverse=True)

    hdr = "".join(f'<th style="{_TH}">{h}</th>' for h in ["Date", "Ticker", "Bias", "Dot", "Notes"])
    rows = ""
    for r in flat:
        url = r.get("url", "")
        if url:
            date_cell = ('<a href="' + url + '" target="_blank" title="' + str(r.get("video", "")) +
                         '" style="color:' + TEXT_MUTED + ';text-decoration:none;font-size:10px">' +
                         str(r.get("date", "")) + ' ↗</a>')
        else:
            date_cell = f'<span style="color:{TEXT_MUTED};font-size:10px">' + str(r.get("date", "")) + '</span>'
        rows += (
            "<tr>"
            + f'<td style="{_TD}">' + date_cell + "</td>"
            + f'<td style="{_TD}">' + _mono(str(r.get("ticker", "")), GOLD, 13, True) + "</td>"
            + f'<td style="{_TD}">' + _bias_html(r.get("bias", "Neutral")) + "</td>"
            + f'<td style="{_TD}">' + _dot_html(r.get("dot", "None")) + "</td>"
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
    st.caption("One row per pick across all captured days. New-video detection runs twice daily "
               "(~8am/7pm CT) via GitHub Actions — pending ones needing analysis show above. "
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
            quad = ("Leading" if rs63 >= 1 and rs21 >= 1 else
                    "Weakening" if rs63 >= 1 else
                    "Improving" if rs21 >= 1 else "Lagging")
            rows.append({"tkr": tkr, "name": name, "rs63": rs63, "rs21": rs21,
                         "flow": round(flow, 2), "quad": quad,
                         "ret1m": round((float(close.iloc[-1]) / float(close.iloc[-21]) - 1) * 100, 1)
                                  if len(close) >= 21 else 0.0})
        except Exception:
            continue
    return rows


def _render_sectors():
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
    GRID = "grid-template-columns:132px 132px 50px 24px 58px 62px"

    bar_rows = ""
    for r in ranked:
        col = q_col.get(r["quad"], TEXT_MUTED)
        dev = r["rs63"] - 1.0
        w = min(abs(dev) / max_dev * 58, 58)
        left = 62 if dev >= 0 else 62 - w
        bar = (f'<div style="position:absolute;left:{left:.0f}px;top:0;bottom:0;'
               f'width:{max(w,1):.0f}px;background:{col};border-radius:3px;opacity:0.9"></div>')
        mom = r["rs21"] - r["rs63"]
        if mom > 0.005:
            m_arrow, m_col = "▲", ACCENT_GREEN
        elif mom < -0.005:
            m_arrow, m_col = "▼", ACCENT_RED
        else:
            m_arrow, m_col = "▬", TEXT_MUTED
        ret = r["ret1m"]; ret_col = ACCENT_GREEN if ret >= 0 else ACCENT_RED
        if r["flow"] >= 1.15:
            flow_badge = f'<span style="color:{GOLD};font-size:10px;font-weight:700">💰{r["flow"]:.1f}x</span>'
        else:
            flow_badge = f'<span style="color:{TEXT_MUTED};font-size:10px">{r["flow"]:.1f}x</span>'
        name = str(r["name"])[:12]
        bar_rows += (
            f'<div style="display:grid;{GRID};align-items:center;gap:6px;padding:3px 0;'
            f'border-bottom:1px solid #2A2A3A22">'
            + f'<span style="color:{col};font-family:\'DM Mono\',monospace;font-size:11px;'
            + f'font-weight:700">' + q_ic.get(r["quad"], "") + " " + str(r["tkr"])
            + f'<span style="color:{TEXT_MUTED};font-weight:400"> ' + name + "</span></span>"
            + f'<div style="position:relative;height:12px;background:#2A2A3A33;border-radius:3px">'
            + f'<div style="position:absolute;left:62px;top:-2px;bottom:-2px;width:1px;'
            + f'background:{TEXT_MUTED}66"></div>' + bar + "</div>"
            + f'<span style="color:{col};font-family:\'DM Mono\',monospace;font-size:11px;'
            + f'font-weight:700">' + "{:.3f}".format(r["rs63"]) + "</span>"
            + f'<span style="color:{m_col};font-size:11px">' + m_arrow + "</span>"
            + f'<span style="color:{ret_col};font-family:\'DM Mono\',monospace;font-size:11px">'
            + "{:+.1f}%".format(ret) + "</span>"
            + flow_badge + "</div>"
        )

    header = (f'<div style="display:grid;{GRID};gap:6px;padding:0 0 4px;color:{TEXT_MUTED};'
              f'font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px">'
              f'<span>Sector</span><span>RS vs SPY 63d</span><span>RS</span><span>Mom</span>'
              f'<span>1M</span><span>Flow</span></div>')

    buys  = [r for r in ranked if r["quad"] in ("Leading", "Improving")][:4]
    sells = sorted([r for r in ranked if r["quad"] in ("Lagging", "Weakening")],
                   key=lambda r: r["rs63"])[:4]
    buy_chips  = " ".join(_chip(r["tkr"] + " " + r["name"], ACCENT_GREEN) for r in buys) or "—"
    sell_chips = " ".join(_chip(r["tkr"] + " " + r["name"], ACCENT_RED) for r in sells) or "—"
    summary = (
        f'<div style="margin-top:10px;display:flex;flex-direction:column;gap:6px">'
        f'<div style="font-size:11px"><span style="color:{ACCENT_GREEN};font-weight:800">'
        f'💰 FOCUS: </span>{buy_chips}</div>'
        f'<div style="font-size:11px"><span style="color:{ACCENT_RED};font-weight:800">'
        f'🚪 AVOID: </span>{sell_chips}</div></div>'
        f'<div style="color:{TEXT_MUTED};font-size:9px;margin-top:8px">Bars diverge from the '
        f'center line (= SPY): green/blue = leading/improving · gold/red = weakening/lagging. '
        f'▲ = momentum accelerating (21d RS &gt; 63d) · 💰 = dollar-volume surge ≥1.15×. '
        f'Flows show up in price × volume before headlines.</div>'
    )

    st.markdown(_card("Sector Rotation — follow the big money", "🔄", MINT,
                      header + bar_rows + summary), unsafe_allow_html=True)


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

    # "📺 Over Kill" (curated YouTube-Shorts watchlist, with its Refresh/Check-
    # latest-run-status buttons) is hidden per request — code kept intact
    # (_render_overkill_tab below) in case it's wanted back; just re-add its
    # label + a `with` block below to restore it.
    tab1, tab3, tab4 = st.tabs(
        ["🎯  Best Scanners", "🔄  Sector Rotation", "🔍  OverKill"]
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

    st.markdown(
        f'<div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};'
        f'border-radius:6px;padding:10px 16px;color:{TEXT_MUTED};font-size:10px;'
        f'text-align:center;margin-top:6px">⚠️ <b>Disclaimer:</b> Golden Scanner is for '
        f'educational and research purposes only. Signals are technical readings, not '
        f'financial advice. Do your own due diligence.</div>',
        unsafe_allow_html=True,
    )
