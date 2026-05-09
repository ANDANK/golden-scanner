# pages/home.py — Market Overview + Strategy Dashboard

from __future__ import annotations
import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import *
from utils import section_header, calc_sma, calc_ema, calc_rsi, calc_macd, calc_atr
from data_loader import get_price_history, get_market_overview, get_batch_quotes


# ── Colour helpers ───────────────────────────────────────────────

def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _sig(signal: str) -> str:
    if signal == "BUY":    color, bg = ACCENT_GREEN, _rgba(ACCENT_GREEN, 0.15)
    elif signal == "SELL": color, bg = ACCENT_RED,   _rgba(ACCENT_RED,   0.15)
    elif signal == "HOLD": color, bg = "#FBBF24",    _rgba("#FBBF24",    0.15)
    else:                  color, bg = TEXT_MUTED,   _rgba("#6B7280",    0.12)
    s = (f"background:{bg};color:{color};border:1px solid {color}66;"
         f"padding:3px 10px;border-radius:4px;font-size:11px;font-weight:700;"
         f"letter-spacing:0.5px;white-space:nowrap")
    return f'<span style="{s}">{signal}</span>'


def _score_bar(score: int) -> str:
    color = ACCENT_GREEN if score >= 70 else ("#FBBF24" if score >= 50 else ACCENT_RED)
    bar_s  = f"background:rgba(107,114,128,0.2);border-radius:3px;height:5px;width:100%;margin:3px 0"
    fill_s = f"background:{color};height:5px;border-radius:3px;width:{min(score, 100)}%"
    return (f'<div style="{bar_s}"><div style="{fill_s}"></div></div>'
            f'<span style="color:{color};font-size:11px;font-weight:700">{score}/100</span>')


def _strategy_table(strategies: list) -> str:
    sep = f"border-bottom:1px solid {_rgba(BORDER_COLOR, 0.6)}"
    hdr = (f"background:{BG_PANEL};color:{GOLD};font-size:10px;font-weight:600;"
           f"text-transform:uppercase;letter-spacing:0.8px;padding:8px 12px;{sep}")
    header = (
        f'<tr>'
        f'<th style="{hdr};text-align:center;width:36px">#</th>'
        f'<th style="{hdr}">Strategy</th>'
        f'<th style="{hdr};text-align:center;width:80px">Signal</th>'
        f'<th style="{hdr};width:130px">Score</th>'
        f'<th class="gs-note-col" style="{hdr}">Current Reading</th>'
        f'</tr>'
    )
    rows = []
    for i, s in enumerate(strategies):
        bg = BG_CARD if i % 2 == 0 else BG_PANEL
        rank_s  = f"background:{bg};color:{TEXT_MUTED};font-size:13px;font-weight:600;padding:10px 12px;{sep};text-align:center;vertical-align:middle"
        name_s  = f"background:{bg};padding:10px 12px;{sep};vertical-align:middle"
        sig_s   = f"background:{bg};padding:10px 12px;{sep};text-align:center;vertical-align:middle"
        score_s = f"background:{bg};padding:10px 12px;{sep};vertical-align:middle"
        note_s  = f"background:{bg};color:{TEXT_MUTED};font-size:12px;padding:10px 12px;{sep};vertical-align:middle"
        name_html = (f'<div style="color:{TEXT_PRIMARY};font-size:13px;font-weight:600;margin-bottom:2px">{s["name"]}</div>'
                     f'<div style="color:{TEXT_MUTED};font-size:11px">{s["description"]}</div>')
        rows.append(
            f'<tr>'
            f'<td style="{rank_s}">#{s["rank"]}</td>'
            f'<td style="{name_s}">{name_html}</td>'
            f'<td style="{sig_s}">{_sig(s["signal"])}</td>'
            f'<td style="{score_s}">{_score_bar(s["score"])}</td>'
            f'<td class="gs-note-col" style="{note_s}">{s["note"]}</td>'
            f'</tr>'
        )
    wrap_s = f"overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid {BORDER_COLOR};border-radius:8px;margin-top:8px"
    tbl_s  = "width:100%;border-collapse:collapse;font-family:'Inter',sans-serif"
    mobile_css = "<style>@media(max-width:600px){.gs-note-col{display:none!important}}</style>"
    return f'{mobile_css}<div style="{wrap_s}"><table style="{tbl_s}"><thead>{header}</thead><tbody>{"".join(rows)}</tbody></table></div>'


# ── Indicator fetching ───────────────────────────────────────────

def _get_ind(ticker: str) -> dict:
    try:
        df = get_price_history(ticker, period="1y")
        if df is None or df.empty or len(df) < 50:
            return {}
        close = df["Close"].squeeze()
        n = len(close)
        price  = float(close.iloc[-1])
        prev   = float(close.iloc[-2]) if n > 1 else price
        chg    = (price - prev) / prev * 100

        sma200 = float(calc_sma(close, 200).iloc[-1])
        sma50  = float(calc_sma(close, 50).iloc[-1])
        ema9   = float(calc_ema(close, 9).iloc[-1])
        ema21  = float(calc_ema(close, 21).iloc[-1])
        ema50  = float(calc_ema(close, 50).iloc[-1])

        rsi14      = calc_rsi(close, 14)
        rsi2       = calc_rsi(close, 2)
        _, _, mhist = calc_macd(close)
        atr_pct    = calc_atr(df) if "High" in df.columns else 0.0

        vol_ratio = 1.0
        if "Volume" in df.columns:
            vol = df["Volume"].squeeze()
            avg = float(vol.iloc[-21:-1].mean()) if n > 21 else float(vol.mean())
            vol_ratio = float(vol.iloc[-1]) / avg if avg > 0 else 1.0

        high5 = float(df["High"].iloc[-5:].max()) if "High" in df.columns and n >= 5 else price

        return {
            "price": price, "chg": chg,
            "sma200": sma200, "sma50": sma50,
            "ema9": ema9, "ema21": ema21, "ema50": ema50,
            "rsi14": rsi14, "rsi2": rsi2,
            "macd_hist": mhist,
            "atr_pct": atr_pct, "vol_ratio": vol_ratio, "high5": high5,
        }
    except Exception:
        return {}


# ── Strategy scoring — TQQQ ──────────────────────────────────────

def _tqqq_strategies(qqq: dict, tqqq: dict, vix: dict) -> list:
    st_list = []
    vix_lvl = float(vix.get("price", 20)) if vix else 20.0

    # 1. 200 SMA Trend
    if qqq:
        pct = (qqq["price"] - qqq["sma200"]) / qqq["sma200"] * 100
        if pct > 4:
            sig, score = "BUY",  min(100, 60 + int(pct * 3))
            note = f"QQQ {pct:+.1f}% above 200 SMA — bull regime confirmed"
        elif pct < -1:
            sig, score = "SELL", max(5, 50 + int(pct * 3))
            note = f"QQQ {pct:+.1f}% below 200 SMA — bear regime, exit TQQQ"
        else:
            sig, score = "HOLD", 48
            note = f"QQQ {pct:+.1f}% from 200 SMA — borderline, wait for clear signal"
    else:
        sig, score, note = "WATCH", 30, "Data unavailable"
    st_list.append({"name": "200 SMA Trend", "description": "QQQ >4% above 200 SMA = BUY · Below -1% = SELL", "signal": sig, "score": score, "note": note})

    # 2. EMA Momentum Swing
    if tqqq:
        c1 = tqqq["ema9"] > tqqq["ema21"]
        c2 = tqqq["rsi14"] > 50
        c3 = tqqq["macd_hist"] > 0
        met = int(c1) + int(c2) + int(c3)
        if met == 3:
            sig, score = "BUY", 88
            note = f"All 3 confirmed — EMA9>EMA21 · RSI {tqqq['rsi14']:.0f} · MACD bull"
        elif met == 2:
            miss = [label for cond, label in [(c1, "EMA cross"), (c2, f"RSI>50 ({tqqq['rsi14']:.0f})"), (c3, "MACD bull")] if not cond]
            sig, score = "HOLD", 55
            note = f"2/3 conditions met · Missing: {', '.join(miss)}"
        else:
            sig, score = "SELL", 22
            note = f"EMA9 {'>' if c1 else '<'} EMA21 · RSI {tqqq['rsi14']:.0f} · MACD {'▲' if c3 else '▼'}"
    else:
        sig, score, note = "WATCH", 30, "Data unavailable"
    st_list.append({"name": "EMA Momentum Swing", "description": "EMA9 > EMA21 + RSI > 50 + MACD bullish — all 3 required", "signal": sig, "score": score, "note": note})

    # 3. RSI Oversold Bounce
    if tqqq:
        r2, r14 = tqqq["rsi2"], tqqq["rsi14"]
        if r2 < 10 or r14 < 30:
            sig, score = "BUY", 85
            note = f"RSI(2)={r2:.0f} · RSI(14)={r14:.0f} — extreme oversold, load TQQQ"
        elif r2 > 90 or r14 > 72:
            sig, score = "SELL", 18
            note = f"RSI(2)={r2:.0f} · RSI(14)={r14:.0f} — overbought, reduce exposure"
        elif r14 < 45:
            sig, score = "HOLD", 62
            note = f"RSI(2)={r2:.0f} · RSI(14)={r14:.0f} — approaching oversold, watch"
        else:
            sig, score = "HOLD", 42
            note = f"RSI(2)={r2:.0f} · RSI(14)={r14:.0f} — neutral zone, no bounce signal yet"
    else:
        sig, score, note = "WATCH", 30, "Data unavailable"
    st_list.append({"name": "RSI Oversold Bounce", "description": "RSI(2) < 10 or RSI(14) < 30 = load TQQQ · RSI(2) > 90 = trim", "signal": sig, "score": score, "note": note})

    # 4. DCA + Profit Taking
    if qqq:
        above50 = qqq["price"] > qqq["sma50"]
        r14 = qqq["rsi14"]
        if above50 and r14 < 65:
            sig, score = "BUY", 78
            note = f"QQQ above SMA50 · RSI {r14:.0f} — DCA into TQQQ is active"
        elif above50 and r14 >= 65:
            sig, score = "HOLD", 55
            note = f"QQQ above SMA50 but RSI {r14:.0f} extended — trim 20–25%"
        else:
            sig, score = "HOLD", 32
            note = f"QQQ below SMA50 · RSI {r14:.0f} — pause DCA, wait for reclaim"
    else:
        sig, score, note = "WATCH", 30, "Data unavailable"
    st_list.append({"name": "DCA + Profit Taking", "description": "QQQ > 50 SMA = DCA active · RSI > 65 = trim partial profits", "signal": sig, "score": score, "note": note})

    # 5. Risk-On / Risk-Off
    if qqq:
        above200 = qqq["price"] > qqq["sma200"]
        pct_from = (qqq["price"] - qqq["sma200"]) / qqq["sma200"] * 100
        if above200 and vix_lvl < 25:
            sig, score = "BUY", 90
            note = f"QQQ above 200 SMA · VIX {vix_lvl:.1f} — risk-on, full TQQQ allocation"
        elif above200 and vix_lvl < 30:
            sig, score = "HOLD", 55
            note = f"QQQ above 200 SMA · VIX {vix_lvl:.1f} elevated — reduce size 50%"
        elif not above200 and vix_lvl > 30:
            sig, score = "SELL", 8
            note = f"QQQ below 200 SMA · VIX {vix_lvl:.1f} spiked — risk-off, exit TQQQ"
        else:
            sig, score = "HOLD", 40
            note = f"QQQ {pct_from:+.1f}% from 200 SMA · VIX {vix_lvl:.1f} — mixed signals"
    else:
        sig, score, note = "WATCH", 30, "Data unavailable"
    st_list.append({"name": "Risk-On / Risk-Off", "description": "QQQ > 200 SMA + VIX < 25 = all-in · VIX > 30 = exit TQQQ", "signal": sig, "score": score, "note": note})

    st_list.sort(key=lambda x: -x["score"])
    for i, s in enumerate(st_list):
        s["rank"] = i + 1
    return st_list


# ── Strategy scoring — SPY ───────────────────────────────────────

def _spy_strategies(spy: dict) -> list:
    st_list = []

    # 1. 50 EMA Pullback
    if spy:
        pct = (spy["price"] - spy["ema50"]) / spy["ema50"] * 100
        r14 = spy["rsi14"]
        if -2.5 <= pct <= 2.0 and 38 <= r14 <= 55:
            sig, score = "BUY", 88
            note = f"SPY {pct:+.1f}% from EMA50 · RSI {r14:.0f} — textbook pullback entry"
        elif spy["price"] > spy["ema50"] and r14 < 65:
            sig, score = "HOLD", 58
            note = f"SPY above EMA50 · RSI {r14:.0f} — trending, wait for pullback"
        elif spy["price"] < spy["ema50"]:
            sig, score = "SELL", 22
            note = f"SPY below EMA50 — wait for reclaim before entering"
        else:
            sig, score = "HOLD", 42
            note = f"SPY {pct:+.1f}% from EMA50 · RSI {r14:.0f}"
    else:
        sig, score, note = "WATCH", 30, "Data unavailable"
    st_list.append({"name": "50 EMA Pullback", "description": "SPY within 2.5% of EMA50 + RSI 38–55 = buy the dip", "signal": sig, "score": score, "note": note})

    # 2. Opening Range Breakout (proxy: 5-day high + volume)
    if spy:
        pct5d = (spy["price"] - spy["high5"]) / spy["high5"] * 100
        vr = spy["vol_ratio"]
        if pct5d >= -0.3 and vr > 1.2:
            sig, score = "BUY", 78
            note = f"SPY at/near 5-day high · Vol {vr:.1f}× — momentum breakout signal"
        elif pct5d >= -0.3:
            sig, score = "HOLD", 52
            note = f"At 5-day high · Vol {vr:.1f}× low — needs volume confirmation"
        else:
            sig, score = "HOLD", 38
            note = f"SPY {pct5d:.1f}% from 5-day high — no breakout yet"
    else:
        sig, score, note = "WATCH", 30, "Data unavailable"
    st_list.append({"name": "Opening Range Breakout", "description": "Price at/above 5-day high + volume confirms momentum", "signal": sig, "score": score, "note": note})

    # 3. VWAP Trend Continuation (EMA proxy)
    if spy:
        trend_up = spy["ema9"] > spy["ema21"]
        vr, r14 = spy["vol_ratio"], spy["rsi14"]
        if trend_up and vr > 1.1 and r14 > 50:
            sig, score = "BUY", 76
            note = f"EMA9 > EMA21 · RSI {r14:.0f} · Vol {vr:.1f}× — trend continuation"
        elif trend_up and r14 > 50:
            sig, score = "HOLD", 55
            note = f"Uptrend intact · RSI {r14:.0f} · Vol {vr:.1f}× light — low conviction"
        elif trend_up:
            sig, score = "HOLD", 44
            note = f"EMA cross bullish · RSI {r14:.0f} weak — wait for RSI > 50"
        else:
            sig, score = "SELL", 25
            note = f"EMA9 < EMA21 · RSI {r14:.0f} — downtrend, avoid longs"
    else:
        sig, score, note = "WATCH", 30, "Data unavailable"
    st_list.append({"name": "VWAP Trend Continuation", "description": "EMA9 > EMA21 + RSI > 50 + volume above average", "signal": sig, "score": score, "note": note})

    # 4. RSI + MA Mean Reversion
    if spy:
        r14 = spy["rsi14"]
        above200 = spy["price"] > spy["sma200"]
        if r14 < 38 and above200:
            sig, score = "BUY", 90
            note = f"RSI {r14:.0f} oversold in uptrend — strong mean reversion buy"
        elif r14 > 72:
            sig, score = "SELL", 20
            note = f"RSI {r14:.0f} overbought — trim positions, take profits"
        elif 38 <= r14 <= 60 and above200:
            sig, score = "HOLD", 58
            note = f"RSI {r14:.0f} neutral · above 200 SMA — hold, wait for edge"
        else:
            sig, score = "HOLD", 35
            note = f"RSI {r14:.0f} · {'above' if above200 else 'below'} 200 SMA"
    else:
        sig, score, note = "WATCH", 30, "Data unavailable"
    st_list.append({"name": "RSI + MA Mean Reversion", "description": "RSI < 38 + above 200 SMA = oversold bounce · RSI > 72 = sell", "signal": sig, "score": score, "note": note})

    # 5. 200 SMA Regime Filter
    if spy:
        pct = (spy["price"] - spy["sma200"]) / spy["sma200"] * 100
        bull_macd = spy["macd_hist"] > 0
        if pct > 0 and bull_macd:
            sig, score = "BUY",  min(95, 65 + int(pct * 3))
            note = f"SPY {pct:+.1f}% above 200 SMA · MACD bull — strong bull regime"
        elif pct > 0:
            sig, score = "HOLD", min(72, 55 + int(pct * 2))
            note = f"SPY {pct:+.1f}% above 200 SMA · MACD bearish — regime intact but weakening"
        elif pct > -5:
            sig, score = "SELL", 35
            note = f"SPY {pct:+.1f}% below 200 SMA — regime broken, be defensive"
        else:
            sig, score = "SELL", max(5, 45 + int(pct * 2))
            note = f"SPY {pct:+.1f}% below 200 SMA — bear regime, cash/hedge"
    else:
        sig, score, note = "WATCH", 30, "Data unavailable"
    st_list.append({"name": "200 SMA Regime Filter", "description": "Above 200 SMA = bull bias · Below = defensive / cash", "signal": sig, "score": score, "note": note})

    st_list.sort(key=lambda x: -x["score"])
    for i, s in enumerate(st_list):
        s["rank"] = i + 1
    return st_list


# ── Strategy scoring — TSLA Options ─────────────────────────────

def _tsla_strategies(tsla: dict, vix: dict) -> list:
    st_list = []
    vix_lvl = float(vix.get("price", 20)) if vix else 20.0

    if not tsla:
        for name, desc in [
            ("Low-Delta Covered Calls", "Delta 0.10–0.20 · 2–6 weeks · sell into RSI 55–72"),
            ("Protective Collar",       "Buy OTM put + sell OTM call · hedge large TSLA position"),
            ("Cash-Secured Put",        "Sell OTM put · RSI 30–50 + above 200 SMA = sweet spot"),
            ("Diagonal Call Spread",    "LEAP call + short near-term call · mild uptrend play"),
            ("Trend Cash-on-Dip",       "RSI 40–60 + above 200 SMA = high-probability entry"),
        ]:
            st_list.append({"name": name, "description": desc, "signal": "WATCH", "score": 30, "note": "Data unavailable"})
        for i, s in enumerate(st_list):
            s["rank"] = i + 1
        return st_list

    r14      = tsla["rsi14"]
    above200 = tsla["price"] > tsla["sma200"]
    above50  = tsla["price"] > tsla["sma50"]
    iv_elev  = tsla["atr_pct"] > 3.0

    # 1. Low-Delta Covered Calls
    if above50 and 55 <= r14 <= 72 and iv_elev:
        sig, score = "BUY", 85
        note = f"RSI {r14:.0f} · ATR {tsla['atr_pct']:.1f}% · above SMA50 — ideal call selling setup"
    elif above50 and r14 > 72:
        sig, score = "BUY", 78
        note = f"RSI {r14:.0f} extended — great time to sell OTM calls (delta 0.10–0.20)"
    elif above50 and iv_elev:
        sig, score = "HOLD", 55
        note = f"Above SMA50 · RSI {r14:.0f} · IV ok — calls viable, wait for RSI 55+"
    elif above50:
        sig, score = "HOLD", 40
        note = f"Above SMA50 · ATR {tsla['atr_pct']:.1f}% low — premiums may be thin"
    else:
        sig, score = "SELL", 18
        note = f"TSLA below SMA50 — risky to sell calls, stock can continue lower"
    st_list.append({"name": "Low-Delta Covered Calls", "description": "Delta 0.10–0.20 · 2–6 weeks · sell at RSI 55–72", "signal": sig, "score": score, "note": note})

    # 2. Protective Collar
    if (vix_lvl > 25 or r14 > 68) and above200:
        sig, score = "BUY", 78
        note = f"VIX {vix_lvl:.1f} · RSI {r14:.0f} · above 200 SMA — collar your TSLA gains now"
    elif above200 and 50 < r14 <= 68:
        sig, score = "HOLD", 48
        note = f"TSLA trending · RSI {r14:.0f} — collar limits upside unnecessarily"
    elif not above200:
        sig, score = "HOLD", 45
        note = f"Below 200 SMA — collar valid to protect existing position"
    else:
        sig, score = "HOLD", 35
        note = f"Low vol + low RSI — collar cost may outweigh benefit"
    st_list.append({"name": "Protective Collar", "description": "Buy OTM put + sell OTM call · hedge large TSLA position", "signal": sig, "score": score, "note": note})

    # 3. Cash-Secured Put
    if above200 and 30 <= r14 <= 50:
        sig, score = "BUY", 88
        note = f"RSI {r14:.0f} · above 200 SMA — sweet spot for selling puts"
    elif above200 and r14 < 30:
        sig, score = "BUY", 75
        note = f"RSI {r14:.0f} deeply oversold · above 200 SMA — aggressive CSP entry"
    elif above200 and r14 > 65:
        sig, score = "HOLD", 42
        note = f"RSI {r14:.0f} extended — wait for pullback before selling puts"
    elif above200:
        sig, score = "HOLD", 55
        note = f"RSI {r14:.0f} neutral · above 200 SMA — CSP ok with wider OTM strikes"
    else:
        sig, score = "SELL", 18
        note = f"Below 200 SMA — assignment risk at unfavorable price level"
    st_list.append({"name": "Cash-Secured Put", "description": "Sell OTM put · RSI 30–50 + above 200 SMA = sweet spot", "signal": sig, "score": score, "note": note})

    # 4. Diagonal Call Spread
    mild_up = above50 and tsla["ema9"] > tsla["ema21"]
    if mild_up and 45 <= r14 <= 65:
        sig, score = "BUY", 80
        note = f"Mild uptrend · RSI {r14:.0f} — ideal diagonal spread conditions"
    elif mild_up and r14 > 65:
        sig, score = "HOLD", 55
        note = f"Uptrend extended RSI {r14:.0f} — widen strikes, manage carefully"
    elif above200 and not above50:
        sig, score = "HOLD", 42
        note = f"Consolidating · above 200 SMA — diagonal viable at lower conviction"
    else:
        sig, score = "SELL", 20
        note = f"Downtrend — LEAP value at risk, avoid diagonals"
    st_list.append({"name": "Diagonal Call Spread", "description": "LEAP call + short near-term call · best in mild uptrend", "signal": sig, "score": score, "note": note})

    # 5. Trend Cash-on-Dip
    if above200 and 40 <= r14 <= 60:
        sig, score = "BUY", 85
        note = f"RSI {r14:.0f} sweet zone · above 200 SMA — high-probability dip entry"
    elif above200 and r14 < 40:
        sig, score = "BUY", 70
        note = f"RSI {r14:.0f} approaching oversold · above 200 SMA — scale in carefully"
    elif above200 and r14 > 60:
        sig, score = "HOLD", 48
        note = f"RSI {r14:.0f} elevated — wait for dip to 40–60 zone"
    else:
        sig, score = "SELL", 15
        note = f"Below 200 SMA — not a dip, trend is broken. Wait for reclaim."
    st_list.append({"name": "Trend Cash-on-Dip", "description": "RSI 40–60 + above 200 SMA = high-probability entry", "signal": sig, "score": score, "note": note})

    st_list.sort(key=lambda x: -x["score"])
    for i, s in enumerate(st_list):
        s["rank"] = i + 1
    return st_list


# ── Strategy scoring — Common ────────────────────────────────────

def _common_strategies(all_data: dict) -> list:
    st_list = []
    instruments = ["SPY", "QQQ", "TSLA", "NVDA", "AAPL", "AMZN", "META"]

    cfg_list = [
        ("Cash-Secured Put (CSP)",  "Sell OTM put · needs IV elevation + bullish-neutral underlying",  "csp"),
        ("Covered Call (CC)",       "Sell OTM call against shares · income in sideways + elevated IV",  "cc"),
        ("Wheel Strategy",          "CSP → CC cycle · needs premium-rich, range-bound stock",           "wheel"),
        ("Naked Put",               "Uncovered short put · higher premium · requires margin · higher risk", "naked"),
    ]

    for name, desc, key in cfg_list:
        best_tkr, best_score, best_note = "", 0, ""
        for tkr in instruments:
            d = all_data.get(tkr, {})
            if not d:
                continue
            r14 = d["rsi14"]
            above200 = d["price"] > d["sma200"]
            above50  = d["price"] > d["sma50"]
            iv_ok    = d["atr_pct"] > 2.0

            if key == "csp":
                if above200 and 28 <= r14 <= 52 and iv_ok: s = 90
                elif above200 and iv_ok:                    s = 65
                elif above200:                              s = 45
                else:                                       s = 20
            elif key == "cc":
                if above50 and r14 >= 55 and iv_ok: s = 88
                elif above50 and iv_ok:             s = 62
                elif above50:                       s = 40
                else:                               s = 15
            elif key == "wheel":
                if above200 and 32 <= r14 <= 60 and iv_ok: s = 85
                elif above200 and iv_ok:                    s = 60
                elif above200:                              s = 38
                else:                                       s = 18
            else:  # naked
                if above200 and r14 < 42 and iv_ok: s = 75
                elif above200 and iv_ok:             s = 50
                elif above200:                       s = 35
                else:                                s = 12

            if s > best_score:
                best_score = s
                best_tkr   = tkr
                best_note  = (f"Best on {tkr} — RSI {d['rsi14']:.0f} · ATR {d['atr_pct']:.1f}% · "
                              f"{'above' if above200 else 'below'} 200 SMA")

        if not best_tkr:
            sig, best_score, best_note = "WATCH", 25, "No qualifying instruments found"
        elif best_score >= 75:
            sig = "BUY"
        elif best_score >= 50:
            sig = "HOLD"
        else:
            sig = "SELL"

        st_list.append({"name": name, "description": desc, "signal": sig, "score": best_score, "note": best_note})

    st_list.sort(key=lambda x: -x["score"])
    for i, s in enumerate(st_list):
        s["rank"] = i + 1
    return st_list


# ── Main render ──────────────────────────────────────────────────

def render():
    now_et = datetime.now(pytz.timezone("US/Eastern")).strftime("%A %b %d %Y  %I:%M %p ET")
    section_header("🏠", "Market Overview", f"Strategy Dashboard · {now_et}")

    col_r, col_b = st.columns([6, 1])
    with col_b:
        if st.button("🔄 Refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    # ── Market Indices ──────────────────────────────────────────
    st.markdown(f'<div style="color:{TEXT_MUTED};font-size:11px;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:10px">Major Indices</div>', unsafe_allow_html=True)
    with st.spinner("Fetching market data…"):
        market = get_market_overview()

    if market:
        icons = {"S&P 500": "📈", "NASDAQ": "💹", "DOW": "🏦", "VIX": "⚡", "Gold": "🥇", "10Y Yield": "💵"}
        cards_html = []
        for name, data in market.items():
            val, chg = data["value"], data["change"]
            color = ACCENT_GREEN if chg >= 0 else ACCENT_RED
            sign = "+" if chg >= 0 else ""
            card_s = (f"background:{BG_CARD};border:1px solid {BORDER_COLOR};"
                      f"border-top:3px solid {color};border-radius:6px;"
                      f"padding:10px 14px;flex:1 1 120px")
            cards_html.append(
                f'<div style="{card_s}">'
                f'<div style="display:flex;align-items:center;gap:5px;margin-bottom:4px">'
                f'<span style="font-size:14px">{icons.get(name, "📊")}</span>'
                f'<span style="color:{TEXT_MUTED};font-size:9px;letter-spacing:1.2px;text-transform:uppercase">{name}</span>'
                f'</div>'
                f'<div style="color:{TEXT_PRIMARY};font-family:\'DM Mono\',monospace;font-size:15px;font-weight:700;line-height:1.2">{val:,.2f}</div>'
                f'<div style="color:{color};font-size:12px;font-weight:600;margin-top:2px">{sign}{chg:.2f}%</div>'
                f'</div>'
            )
        st.markdown(
            f'<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:4px">{"".join(cards_html)}</div>',
            unsafe_allow_html=True,
        )

    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11px;margin-top:4px;margin-bottom:16px">⚠️ Market data may be delayed up to 15 minutes.</div>',
        unsafe_allow_html=True,
    )

    # ── Strategy Analysis ───────────────────────────────────────
    st.markdown(f'<div style="color:{GOLD};font-size:13px;font-weight:700;letter-spacing:1px;text-transform:uppercase;margin-bottom:4px">Strategy Signals — Live</div>', unsafe_allow_html=True)
    st.markdown(f'<div style="color:{TEXT_MUTED};font-size:12px;margin-bottom:12px">Ranked by current conditions · 🟢 BUY · 🔴 SELL · 🟡 HOLD</div>', unsafe_allow_html=True)

    with st.spinner("Computing strategy signals…"):
        qqq_d   = _get_ind("QQQ")
        tqqq_d  = _get_ind("TQQQ")
        spy_d   = _get_ind("SPY")
        tsla_d  = _get_ind("TSLA")
        vix_d   = _get_ind("^VIX")
        all_inst = {
            "SPY":  spy_d,
            "QQQ":  qqq_d,
            "TSLA": tsla_d,
            "NVDA": _get_ind("NVDA"),
            "AAPL": _get_ind("AAPL"),
            "AMZN": _get_ind("AMZN"),
            "META": _get_ind("META"),
        }

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📈  QQQ Strategies",
        "📊  SPY Strategies",
        "⚡  TSLA Options",
        "🔄  Common Strategies",
        "📱  Social Trends",
    ])

    with tab1:
        desc_s = f"color:{TEXT_MUTED};font-size:12px;padding:8px 0 4px 0"
        st.markdown(
            f'<div style="{desc_s}">5 QQQ strategies scored on live QQQ and VIX readings. '
            f'<b style="color:{TEXT_PRIMARY}">QQQ</b> is the regime signal; '
            f'<b style="color:{TEXT_PRIMARY}">TQQQ</b> is the trading vehicle.</div>',
            unsafe_allow_html=True,
        )
        st.markdown(_strategy_table(_tqqq_strategies(qqq_d, tqqq_d, vix_d)), unsafe_allow_html=True)

    with tab2:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:12px;padding:8px 0 4px 0">'
            f'5 SPY strategies scored on current price action, moving averages, RSI and volume.</div>',
            unsafe_allow_html=True,
        )
        st.markdown(_strategy_table(_spy_strategies(spy_d)), unsafe_allow_html=True)

    with tab3:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:12px;padding:8px 0 4px 0">'
            f'5 TSLA options strategies scored on price, RSI and implied volatility proxy (ATR). '
            f'<b style="color:{ACCENT_RED}">TSLA is highly volatile — size accordingly.</b></div>',
            unsafe_allow_html=True,
        )
        st.markdown(_strategy_table(_tsla_strategies(tsla_d, vix_d)), unsafe_allow_html=True)

    with tab4:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:12px;padding:8px 0 4px 0">'
            f'CSP, Covered Call, Wheel and Naked Put ranked by best-fit instrument across '
            f'SPY, QQQ, TSLA, NVDA, AAPL, AMZN, META right now.</div>',
            unsafe_allow_html=True,
        )
        st.markdown(_strategy_table(_common_strategies(all_inst)), unsafe_allow_html=True)

    with tab5:
        from scanners.social_trends import render_social_trends
        render_social_trends()

    # ── Disclaimer ──────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    disc_s = (f"background:{BG_PANEL};border:1px solid {BORDER_COLOR};"
              f"border-radius:6px;padding:12px 16px;color:{TEXT_MUTED};font-size:11px;text-align:center")
    st.markdown(
        f'<div style="{disc_s}">⚠️ <b>Disclaimer:</b> Golden Scanner is for educational and research purposes only. '
        f'Signals are based on technical indicators and do not constitute financial advice. '
        f'Always conduct your own due diligence before trading.</div>',
        unsafe_allow_html=True,
    )
