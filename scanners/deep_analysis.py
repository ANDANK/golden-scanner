# scanners/deep_analysis.py — Multi-Ticker Deep Technical Analysis Panel
# 9 indicator modules · Daily + Weekly · Composite scores · Interactive chart
# Up to 25 tickers, full-color coded output with hover tooltips.

from __future__ import annotations

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import *
from utils import calc_sma, calc_ema, calc_rsi, calc_atr, atr_expanding, calc_relative_strength, section_header
from data_loader import get_price_history, get_info


# ── Sector → ETF mapping ───────────────────────────────────────
SECTOR_ETF = {
    "Technology":             "XLK",
    "Healthcare":             "XLV",
    "Financial Services":     "XLF",
    "Financials":             "XLF",
    "Energy":                 "XLE",
    "Consumer Cyclical":      "XLY",
    "Consumer Defensive":     "XLP",
    "Industrials":            "XLI",
    "Utilities":              "XLU",
    "Real Estate":            "XLRE",
    "Basic Materials":        "XLB",
    "Materials":              "XLB",
    "Communication Services": "XLC",
}

YELLOW = "#FBBF24"


# ══════════════════════════════════════════════════════════════
# INDICATOR HELPERS
# ══════════════════════════════════════════════════════════════

def _bb(close: pd.Series, period: int = 20, std_mult: float = 2.0):
    """Bollinger Bands → (upper, mid, lower, width_pct)."""
    mid   = calc_sma(close, period)
    sigma = close.rolling(period, min_periods=1).std()
    upper = mid + std_mult * sigma
    lower = mid - std_mult * sigma
    width = ((upper - lower) / mid.replace(0, np.nan) * 100).fillna(0)
    return upper, mid, lower, width


def _obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    return (np.sign(close.diff().fillna(0)) * volume).cumsum()


def _mfi(df: pd.DataFrame, period: int = 14) -> float:
    """Money Flow Index (0–100)."""
    try:
        tp  = (df["High"].squeeze() + df["Low"].squeeze() + df["Close"].squeeze()) / 3
        mf  = tp * df["Volume"].squeeze()
        pos = mf.where(tp > tp.shift(1), 0).rolling(period).sum()
        neg = mf.where(tp < tp.shift(1), 0).rolling(period).sum()
        mfr = pos / neg.replace(0, np.nan)
        return float((100 - 100 / (1 + mfr)).dropna().iloc[-1])
    except Exception:
        return 50.0


def _rgba(hex_color: str, alpha: float) -> str:
    """Convert #RRGGBB to rgba() — Plotly rejects 8-digit hex with alpha byte."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _slope_pct(series: pd.Series, lookback: int = 10) -> float:
    s = series.dropna()
    if len(s) < lookback + 1 or float(s.iloc[-1 - lookback]) == 0:
        return 0.0
    return float((s.iloc[-1] - s.iloc[-1 - lookback]) / abs(s.iloc[-1 - lookback]) * 100)


def _macd_series(close: pd.Series):
    """Full MACD line, signal, histogram series."""
    ema12 = calc_ema(close, 12)
    ema26 = calc_ema(close, 26)
    macd  = ema12 - ema26
    sig   = calc_ema(macd, 9)
    hist  = macd - sig
    return macd, sig, hist


def _rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
    """Full RSI series using Wilder's smoothing."""
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


# ══════════════════════════════════════════════════════════════
# HTML / BADGE HELPERS
# ══════════════════════════════════════════════════════════════

def _lvl_color(level: str) -> tuple:
    """(fg, bg) for badge level."""
    return {
        "bull":    (ACCENT_GREEN, f"{ACCENT_GREEN}1A"),
        "bear":    (ACCENT_RED,   f"{ACCENT_RED}1A"),
        "warn":    (YELLOW,       f"{YELLOW}1A"),
        "neutral": (TEXT_MUTED,   f"{BORDER_COLOR}44"),
    }.get(level, (TEXT_MUTED, f"{BORDER_COLOR}44"))


def _badge(text: str, level: str) -> str:
    fg, bg = _lvl_color(level)
    return (
        f'<span style="background:{bg};color:{fg};border:1px solid {fg}66;'
        f'padding:2px 9px;border-radius:4px;font-size:12px;font-weight:700;'
        f'white-space:nowrap;display:inline-block">{text}</span>'
    )


def _tip(text: str) -> str:
    """Escape tooltip text for HTML attribute."""
    return text.replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


# Column header colors for Daily / Weekly
_DAILY_HDR  = "#3B82F6"    # blue
_WEEKLY_HDR = "#A78BFA"    # purple
# Row separator — rgba avoids 8-digit hex which some renderers reject
_SEP = "rgba(255,255,255,0.06)"
_DAILY_BG  = "rgba(59,130,246,0.08)"
_WEEKLY_BG = "rgba(167,139,250,0.08)"


def _row(label: str, d_val: str, w_val: str, d_lvl: str, w_lvl: str, tooltip: str = "") -> str:
    tip = f'title="{_tip(tooltip)}"' if tooltip else ""
    lbl_s = f"color:{TEXT_MUTED};font-size:12px;padding:7px 10px;white-space:nowrap;border-bottom:1px solid {_SEP}"
    d_s   = f"padding:7px 10px;background:{_DAILY_BG};border-bottom:1px solid {_SEP}"
    w_s   = f"padding:7px 10px;background:{_WEEKLY_BG};border-bottom:1px solid {_SEP}"
    return (f'<tr><td style="{lbl_s}" {tip}>{label}</td>'
            f'<td style="{d_s}">{_badge(d_val, d_lvl)}</td>'
            f'<td style="{w_s}">{_badge(w_val, w_lvl)}</td></tr>')


def _srow(label: str, val: str, level: str, tooltip: str = "") -> str:
    tip = f'title="{_tip(tooltip)}"' if tooltip else ""
    lbl_s = f"color:{TEXT_MUTED};font-size:12px;padding:7px 10px;white-space:nowrap;border-bottom:1px solid {_SEP}"
    val_s = f"padding:7px 10px;border-bottom:1px solid {_SEP}"
    return (f'<tr><td style="{lbl_s}" {tip}>{label}</td>'
            f'<td colspan="2" style="{val_s}">{_badge(val, level)}</td></tr>')


def _html_row(content_html: str) -> str:
    return f'<tr><td colspan="3" style="padding:6px 10px">{content_html}</td></tr>'


def _section(title: str, icon: str, rows_html: str, dual_timeframe: bool = True) -> str:
    if dual_timeframe:
        col_headers = (
            f'<tr>'
            f'<td style="padding:5px 10px;width:42%"></td>'
            f'<td style="padding:5px 10px;background:{_DAILY_BG};border-bottom:2px solid {_DAILY_HDR}">'
            f'<span style="color:{_DAILY_HDR};font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1.2px">&#128197; Daily</span></td>'
            f'<td style="padding:5px 10px;background:{_WEEKLY_BG};border-bottom:2px solid {_WEEKLY_HDR}">'
            f'<span style="color:{_WEEKLY_HDR};font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1.2px">&#128198; Weekly</span></td>'
            f'</tr>'
        )
    else:
        col_headers = ""

    wrap_s  = f"background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:8px;margin-bottom:12px;overflow:hidden"
    hdr_s   = f"background:{BG_PANEL};padding:9px 14px;border-bottom:1px solid {BORDER_COLOR}"
    title_s = f"color:{GOLD};font-size:13px;font-weight:700"
    return (
        f'<div style="{wrap_s}">'
        f'<div style="{hdr_s}"><span style="{title_s}">{icon} {title}</span></div>'
        f'<table style="width:100%;border-collapse:collapse">{col_headers}{rows_html}</table>'
        f'</div>'
    )


# ══════════════════════════════════════════════════════════════
# VISUAL COMPONENTS
# ══════════════════════════════════════════════════════════════

def _score_ring(label: str, score: int, color: str) -> str:
    score = int(max(0, min(100, score)))
    circ  = 213.628   # 2 * pi * 34
    dash  = score * circ / 100
    return f"""
<div style="text-align:center;padding:14px 8px">
  <div style="position:relative;width:84px;height:84px;margin:0 auto">
    <svg width="84" height="84" viewBox="0 0 84 84">
      <circle cx="42" cy="42" r="34" fill="none" stroke="{BORDER_COLOR}" stroke-width="7"/>
      <circle cx="42" cy="42" r="34" fill="none" stroke="{color}" stroke-width="7"
        stroke-dasharray="{dash:.1f} {circ:.1f}"
        stroke-dashoffset="53.4" stroke-linecap="round"
        style="transition:stroke-dasharray 0.5s ease"/>
    </svg>
    <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
                color:{color};font-size:20px;font-weight:800;
                font-family:'Cormorant Garamond',serif;line-height:1">{score}</div>
  </div>
  <div style="color:{TEXT_MUTED};font-size:10px;text-transform:uppercase;
              letter-spacing:1px;margin-top:8px;line-height:1.3">{label}</div>
</div>"""


def _rsi_gauge(rsi: float) -> str:
    """Visual zone bar for RSI."""
    rsi   = max(0.0, min(100.0, rsi))
    zones = [
        (0,  30,  ACCENT_RED,   "Oversold"),
        (30, 55,  TEXT_MUTED,   "Neutral"),
        (55, 68,  ACCENT_GREEN, "Momentum Zone ✅"),
        (68, 70,  YELLOW,       "Hot"),
        (70, 100, ACCENT_RED,   "Overbought"),
    ]
    label = "Neutral"; color = TEXT_MUTED
    for lo, hi, c, lbl in zones:
        if lo <= rsi < hi:
            label = lbl; color = c; break
    if rsi >= 100:
        label = "Overbought"; color = ACCENT_RED

    markers = ""
    for pct in (30, 55, 68, 70):
        markers += f'<div style="position:absolute;left:{pct}%;top:0;height:100%;width:1px;background:{BORDER_COLOR}88;z-index:2"></div>'

    return f"""
<div style="margin:2px 0 8px">
  <div style="position:relative;background:#1a1a2a;border-radius:4px;height:12px;width:100%">
    {markers}
    <div style="background:{color};height:12px;border-radius:4px;
                width:{rsi:.1f}%;position:relative;z-index:1;
                transition:width 0.4s ease"></div>
  </div>
  <div style="display:flex;justify-content:space-between;font-size:9px;
              color:{TEXT_MUTED};margin-top:3px">
    <span>0</span><span>30</span><span style="margin-left:14px">55</span>
    <span>68 70</span><span>100</span>
  </div>
  <div style="color:{color};font-weight:700;font-size:13px;margin-top:4px">
    {rsi:.1f} — {label}
  </div>
</div>"""


def _pct_b_bar(pct_b: float, lo: float, mid: float, hi: float) -> str:
    pct_b = max(0, min(100, pct_b))
    return f"""
<div style="margin:4px 0 2px">
  <div style="position:relative;background:#1a1a2a;border-radius:4px;height:8px">
    <div style="position:absolute;left:50%;top:0;height:100%;width:1px;background:{BORDER_COLOR}88"></div>
    <div style="background:#A78BFA;height:8px;border-radius:4px;
                width:{pct_b:.0f}%;transition:width 0.4s ease"></div>
  </div>
  <div style="display:flex;justify-content:space-between;font-size:9px;
              color:{TEXT_MUTED};margin-top:2px">
    <span>Lower ${lo:.1f}</span>
    <span>Mid ${mid:.1f}</span>
    <span>Upper ${hi:.1f}</span>
  </div>
</div>"""


def _mini_weekly_chart(df_w: pd.DataFrame, ticker: str) -> go.Figure:
    close = df_w["Close"].squeeze().dropna().iloc[-52:]
    color = ACCENT_GREEN if float(close.iloc[-1]) >= float(close.iloc[0]) else ACCENT_RED
    fig = go.Figure(go.Scatter(
        x=list(range(len(close))),
        y=close.values,
        mode="lines",
        line=dict(color=color, width=1.5),
        fill="tozeroy",
        fillcolor=_rgba(color, 0.09),
    ))
    fig.update_layout(
        paper_bgcolor=BG_CARD, plot_bgcolor=BG_PANEL,
        height=90, margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        showlegend=False,
    )
    return fig


# ══════════════════════════════════════════════════════════════
# MAIN ANALYSIS COMPUTATION
# ══════════════════════════════════════════════════════════════

def compute_analysis(ticker: str) -> dict | None:
    try:
        df_d = get_price_history(ticker, period="6mo",  interval="1d")
        df_w = get_price_history(ticker, period="2y",   interval="1wk")
        info = get_info(ticker)

        if df_d is None or df_d.empty or len(df_d) < 30:
            return None

        for df in [df_d, df_w]:
            if df is not None and isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

        close_d = df_d["Close"].squeeze()
        vol_d   = df_d["Volume"].squeeze()
        close_w = df_w["Close"].squeeze() if (df_w is not None and not df_w.empty) else pd.Series()

        price   = float(close_d.iloc[-1])
        prev    = float(close_d.iloc[-2]) if len(close_d) > 1 else price
        chg_pct = (price - prev) / prev * 100 if prev else 0.0
        name    = info.get("shortName") or info.get("longName") or ticker
        sector  = info.get("sector", "")

        # ── Moving Averages ──────────────────────────────────────
        ema20  = calc_ema(close_d, 20)
        sma50  = calc_sma(close_d, 50)
        sma200 = calc_sma(close_d, 200) if len(close_d) >= 200 else pd.Series()

        ema20_v  = float(ema20.iloc[-1])
        sma50_v  = float(sma50.iloc[-1])
        sma200_v = float(sma200.iloc[-1]) if not sma200.empty else None

        above_ema20     = price > ema20_v
        above_sma50     = price > sma50_v
        above_sma200    = (price > sma200_v) if sma200_v else False
        ema20_above_50  = ema20_v > sma50_v
        sma50_above_200 = (sma50_v > sma200_v) if sma200_v else False

        full_stack = above_ema20 and ema20_above_50 and above_sma50 and above_sma200 and sma50_above_200
        partial    = above_sma50 and not full_stack
        trend_level = "bull" if full_stack else ("warn" if partial else "bear")
        trend_dir   = "Uptrend" if above_sma50 else "Downtrend"

        slope_200 = _slope_pct(sma200, 10) if not sma200.empty else 0.0
        slope_50  = _slope_pct(sma50,  10)

        def _arrow(v): return "↗" if v > 0.05 else ("↘" if v < -0.05 else "→")

        # ── MACD (Daily) ─────────────────────────────────────────
        macd_d, sig_d, hist_d = _macd_series(close_d)
        m_d = float(macd_d.iloc[-1]); s_d = float(sig_d.iloc[-1]); h_d = float(hist_d.iloc[-1])
        cross_d    = m_d > s_d
        hist_pos_d = h_d > 0
        slope_macd = float(macd_d.iloc[-1]) - float(macd_d.iloc[-3]) if len(macd_d) >= 3 else 0.0

        # ── MACD (Weekly) ────────────────────────────────────────
        m_w = s_w = h_w = 0.0
        cross_w = hist_pos_w = False
        if len(close_w) >= 26:
            macd_w, sig_w, hist_w_s = _macd_series(close_w)
            m_w = float(macd_w.iloc[-1]); s_w = float(sig_w.iloc[-1]); h_w = float(hist_w_s.iloc[-1])
            cross_w    = m_w > s_w
            hist_pos_w = h_w > 0

        # ── RSI ──────────────────────────────────────────────────
        rsi_d = calc_rsi(close_d)
        rsi_w = calc_rsi(close_w) if len(close_w) >= 15 else 50.0

        def rsi_level(r):
            return "bull" if 55 <= r <= 70 else ("bear" if r < 30 or r > 70 else "warn" if r > 68 else "neutral")

        # ── Volume & OBV & MFI ───────────────────────────────────
        avg_vol = float(vol_d.iloc[:-1].rolling(20).mean().dropna().iloc[-1]) if len(vol_d) > 20 else float(vol_d.mean())
        curr_vol = float(vol_d.iloc[-1])
        vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 1.0
        vol_spike = vol_ratio >= 1.5

        obv_s     = _obv(close_d, vol_d)
        obv_slope = _slope_pct(obv_s, 5)
        obv_bull  = obv_slope > 0
        mfi       = _mfi(df_d)

        # ── Bollinger Bands ──────────────────────────────────────
        bb_up, bb_mid, bb_lo, bb_wid = _bb(close_d)
        bb_up_v  = float(bb_up.iloc[-1])
        bb_lo_v  = float(bb_lo.iloc[-1])
        bb_mid_v = float(bb_mid.iloc[-1])
        bb_w_v   = float(bb_wid.iloc[-1])

        ww = bb_wid.dropna()
        bb_squeeze   = len(ww) >= 20 and bb_w_v <= float(ww.iloc[-20:].quantile(0.15))
        above_upper  = price > bb_up_v
        below_lower  = price < bb_lo_v
        pct_b        = (price - bb_lo_v) / (bb_up_v - bb_lo_v) * 100 if (bb_up_v != bb_lo_v) else 50.0

        # ── Breakout ─────────────────────────────────────────────
        high_20 = float(close_d.iloc[-20:].max()) if len(close_d) >= 20 else price
        high_50 = float(close_d.iloc[-50:].max()) if len(close_d) >= 50 else price
        near_20h = price >= high_20 * 0.98
        new_20h  = price >= high_20
        new_50h  = price >= high_50

        if new_20h and vol_spike:
            brk_label = "Breakout Confirmed 🚀"; brk_level = "bull"
        elif near_20h:
            brk_label = "Potential Breakout ⚡"; brk_level = "warn"
        else:
            brk_label = "No Breakout"; brk_level = "neutral"

        # ── Short Squeeze ────────────────────────────────────────
        short_pct   = (info.get("shortPercentOfFloat") or 0) * 100
        short_ratio = info.get("shortRatio") or 0.0

        if short_pct >= 15 or short_ratio >= 7:
            sq_label = "High Squeeze Potential 🔥"; sq_level = "bull"
        elif short_pct >= 8 or short_ratio >= 4:
            sq_label = "Moderate Squeeze";          sq_level = "warn"
        else:
            sq_label = "Low Squeeze Risk";          sq_level = "neutral"

        # ── ATR & Volatility ─────────────────────────────────────
        atr_pct  = calc_atr(df_d)
        atr_exp  = atr_expanding(df_d)
        atr_label = "Expanding ⚡" if atr_exp else "Contracting"
        atr_level = "warn" if atr_exp else "neutral"

        # ── Relative Strength ────────────────────────────────────
        spy_df    = get_price_history("SPY", period="6mo")
        spy_close = spy_df["Close"].squeeze() if (spy_df is not None and not spy_df.empty) else pd.Series()
        rs_spy    = calc_relative_strength(close_d, spy_close) if not spy_close.empty else 1.0

        sector_etf = SECTOR_ETF.get(sector, "")
        rs_sector  = 1.0
        if sector_etf:
            etf_df    = get_price_history(sector_etf, period="6mo")
            etf_close = etf_df["Close"].squeeze() if (etf_df is not None and not etf_df.empty) else pd.Series()
            rs_sector = calc_relative_strength(close_d, etf_close) if not etf_close.empty else 1.0

        def rs_level(r): return "bull" if r >= 1.05 else ("bear" if r < 0.95 else "neutral")
        def rs_label(r): return f"{'Strong ↑' if r >= 1.05 else ('Weak ↓' if r < 0.95 else 'Neutral →')} {r:.3f}×"

        # ── Composite Scores ─────────────────────────────────────
        # Momentum (0–100)
        mom = 0
        if hist_pos_d:                   mom += 20
        if cross_d:                      mom += 15
        if hist_pos_w:                   mom += 10
        if cross_w:                      mom += 8
        if 55 <= rsi_d <= 68:            mom += 25
        elif 50 <= rsi_d < 55 or 68 < rsi_d <= 72: mom += 12
        if vol_spike:                    mom += 12
        if obv_bull:                     mom += 10
        momentum_score = min(100, mom)

        # Trend Strength (0–100)
        trd = 0
        if above_ema20:       trd += 14
        if ema20_above_50:    trd += 14
        if above_sma50:       trd += 14
        if above_sma200:      trd += 20
        if sma50_above_200:   trd += 14
        if slope_200 > 0:     trd += 12
        if slope_50  > 0:     trd += 12
        trend_score = min(100, trd)

        # Buy Pressure (0–100)
        bp = 0
        if vol_spike:         bp += 20
        if obv_bull:          bp += 15
        if mfi > 60:          bp += 15
        elif mfi > 50:        bp += 8
        if new_20h:           bp += 20
        elif near_20h:        bp += 10
        if rs_spy >= 1.05:    bp += 15
        if hist_pos_d:        bp += 15
        buy_pressure_score = min(100, bp)

        # ── Consolidated Signal ──────────────────────────────────
        raw_composite = (momentum_score * 0.35 + trend_score * 0.35 + buy_pressure_score * 0.30)
        bias = 0
        if full_stack:              bias += 8
        elif not above_sma50:       bias -= 10
        if cross_d and hist_pos_d:  bias += 5
        elif not cross_d:           bias -= 5
        if 55 <= rsi_d <= 68:       bias += 5
        elif rsi_d > 75:            bias -= 8
        elif rsi_d < 30:            bias -= 4
        if rs_spy >= 1.05:          bias += 4
        elif rs_spy < 0.92:         bias -= 4
        composite = int(round(max(0, min(100, raw_composite + bias))))

        if composite >= 60:
            signal, signal_pct, signal_color = "BUY",     composite,           ACCENT_GREEN
        elif composite <= 40:
            signal, signal_pct, signal_color = "SELL",    100 - composite,     ACCENT_RED
        else:
            signal, signal_pct, signal_color = "NEUTRAL", composite,           YELLOW

        return dict(
            ticker=ticker, name=name, sector=sector, sector_etf=sector_etf,
            price=price, chg_pct=chg_pct,
            trend_level=trend_level, trend_dir=trend_dir,
            full_stack=full_stack, partial=partial,
            ema20_v=ema20_v, sma50_v=sma50_v, sma200_v=sma200_v,
            above_ema20=above_ema20, above_sma50=above_sma50, above_sma200=above_sma200,
            ema20_above_50=ema20_above_50, sma50_above_200=sma50_above_200,
            slope_50=slope_50, slope_200=slope_200, _arrow=_arrow,
            m_d=m_d, s_d=s_d, h_d=h_d, cross_d=cross_d, hist_pos_d=hist_pos_d, slope_macd=slope_macd,
            m_w=m_w, s_w=s_w, h_w=h_w, cross_w=cross_w, hist_pos_w=hist_pos_w,
            rsi_d=rsi_d, rsi_w=rsi_w, rsi_level_d=rsi_level(rsi_d), rsi_level_w=rsi_level(rsi_w),
            vol_ratio=vol_ratio, vol_spike=vol_spike, obv_bull=obv_bull, obv_slope=obv_slope, mfi=mfi,
            bb_up_v=bb_up_v, bb_lo_v=bb_lo_v, bb_mid_v=bb_mid_v, bb_w_v=bb_w_v,
            bb_squeeze=bb_squeeze, above_upper=above_upper, below_lower=below_lower, pct_b=pct_b,
            brk_label=brk_label, brk_level=brk_level,
            near_20h=near_20h, new_20h=new_20h, new_50h=new_50h,
            short_pct=short_pct, short_ratio=short_ratio, sq_label=sq_label, sq_level=sq_level,
            atr_pct=atr_pct, atr_exp=atr_exp, atr_label=atr_label, atr_level=atr_level,
            rs_spy=rs_spy, rs_sector=rs_sector,
            rs_spy_level=rs_level(rs_spy),   rs_spy_label=rs_label(rs_spy),
            rs_sec_level=rs_level(rs_sector), rs_sec_label=rs_label(rs_sector),
            momentum_score=momentum_score, trend_score=trend_score, buy_pressure_score=buy_pressure_score,
            signal=signal, signal_pct=signal_pct, signal_color=signal_color,
            df_d=df_d, df_w=df_w,
        )
    except Exception as e:
        st.error(f"Error computing analysis for **{ticker}**: {e}")
        return None


# ══════════════════════════════════════════════════════════════
# PLOTLY CHART
# ══════════════════════════════════════════════════════════════

def _build_chart(a: dict) -> go.Figure:
    df_d  = a["df_d"]
    close = df_d["Close"].squeeze()
    vol   = df_d["Volume"].squeeze()
    n     = min(120, len(close))    # show up to 120 days

    ema20  = calc_ema(close, 20)
    sma50  = calc_sma(close, 50)
    sma200 = calc_sma(close, 200)
    bb_up, bb_mid, bb_lo, _ = _bb(close)
    macd_ln, sig_ln, hist_s  = _macd_series(close)
    rsi_s  = _rsi_series(close)
    avg_v  = vol.rolling(20).mean()

    xs = df_d.index[-n:]

    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.025,
        row_heights=[0.50, 0.14, 0.18, 0.18],
    )

    # ── Row 1: Price + Bollinger + MAs ─────────────────────────
    # BB fill
    x_fill = list(xs) + list(xs[::-1])
    y_fill = list(bb_up.iloc[-n:]) + list(bb_lo.iloc[-n:][::-1])
    fig.add_trace(go.Scatter(
        x=x_fill, y=y_fill,
        fill="toself", fillcolor=_rgba(ACCENT_BLUE, 0.07),
        line=dict(color="rgba(0,0,0,0)"), showlegend=False, hoverinfo="skip",
    ), row=1, col=1)
    # BB lines
    for band, dash_style, label in [
        (bb_up,  "dot", "BB Upper"),
        (bb_mid, "solid", "BB Mid"),
        (bb_lo,  "dot", "BB Lower"),
    ]:
        fig.add_trace(go.Scatter(
            x=xs, y=band.iloc[-n:],
            line=dict(color=ACCENT_BLUE, width=0.8, dash=dash_style),
            name=label, showlegend=True, legendgroup="bb",
        ), row=1, col=1)
    # Candlestick
    fig.add_trace(go.Candlestick(
        x=xs,
        open=df_d["Open"].squeeze().iloc[-n:],
        high=df_d["High"].squeeze().iloc[-n:],
        low=df_d["Low"].squeeze().iloc[-n:],
        close=close.iloc[-n:],
        increasing_line_color=ACCENT_GREEN, decreasing_line_color=ACCENT_RED,
        increasing_fillcolor=_rgba(ACCENT_GREEN, 0.6), decreasing_fillcolor=_rgba(ACCENT_RED, 0.6),
        name=a["ticker"],
    ), row=1, col=1)
    # MAs
    for series, color, lbl, w in [
        (ema20,  GOLD,      "EMA 20",  1.5),
        (sma50,  "#A78BFA", "SMA 50",  1.5),
        (sma200, "#FB923C", "SMA 200", 1.5),
    ]:
        if not series.dropna().empty:
            fig.add_trace(go.Scatter(
                x=xs, y=series.iloc[-n:],
                line=dict(color=color, width=w), name=lbl,
            ), row=1, col=1)

    # ── Row 2: Volume ───────────────────────────────────────────
    bar_colors = [
        ACCENT_GREEN if c >= o else ACCENT_RED
        for c, o in zip(close.iloc[-n:], df_d["Open"].squeeze().iloc[-n:])
    ]
    fig.add_trace(go.Bar(
        x=xs, y=vol.iloc[-n:], marker_color=bar_colors,
        name="Volume", showlegend=False, opacity=0.75,
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=xs, y=avg_v.iloc[-n:],
        line=dict(color=GOLD, width=1.2, dash="dot"), name="Avg Vol",
    ), row=2, col=1)

    # ── Row 3: MACD ─────────────────────────────────────────────
    hist_colors = [ACCENT_GREEN if v >= 0 else ACCENT_RED for v in hist_s.iloc[-n:]]
    fig.add_trace(go.Bar(
        x=xs, y=hist_s.iloc[-n:], marker_color=hist_colors,
        name="MACD Hist", showlegend=False, opacity=0.85,
    ), row=3, col=1)
    fig.add_trace(go.Scatter(
        x=xs, y=macd_ln.iloc[-n:],
        line=dict(color=ACCENT_BLUE, width=1.4), name="MACD",
    ), row=3, col=1)
    fig.add_trace(go.Scatter(
        x=xs, y=sig_ln.iloc[-n:],
        line=dict(color=YELLOW, width=1.2), name="Signal",
    ), row=3, col=1)
    fig.add_hline(y=0, line=dict(color=BORDER_COLOR, width=0.8, dash="dot"), row=3, col=1)

    # ── Row 4: RSI ──────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=xs, y=rsi_s.iloc[-n:],
        line=dict(color="#A78BFA", width=1.5), name="RSI",
        fill="tozeroy", fillcolor=_rgba("#A78BFA", 0.08),
    ), row=4, col=1)
    for lvl, clr in [(30, ACCENT_RED), (55, _rgba(TEXT_MUTED, 0.53)), (68, ACCENT_GREEN), (70, YELLOW)]:
        fig.add_hline(y=lvl, line=dict(color=clr, width=0.7, dash="dot"), row=4, col=1)

    fig.update_layout(
        paper_bgcolor=BG_DARK, plot_bgcolor=BG_PANEL,
        font=dict(color=TEXT_PRIMARY, family="Inter, sans-serif", size=11),
        height=640,
        margin=dict(l=10, r=10, t=12, b=10),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.01, x=0,
            bgcolor="rgba(0,0,0,0)", font=dict(size=10), itemsizing="constant",
        ),
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
    )
    for i in range(1, 5):
        fig.update_xaxes(gridcolor=BORDER_COLOR, row=i, col=1, showgrid=True)
        fig.update_yaxes(gridcolor=BORDER_COLOR, row=i, col=1, showgrid=True)
    fig.update_yaxes(title_text="Price", row=1, col=1, title_font=dict(size=10, color=TEXT_MUTED))
    fig.update_yaxes(title_text="Vol",   row=2, col=1, title_font=dict(size=10, color=TEXT_MUTED))
    fig.update_yaxes(title_text="MACD",  row=3, col=1, title_font=dict(size=10, color=TEXT_MUTED))
    fig.update_yaxes(title_text="RSI",   row=4, col=1, title_font=dict(size=10, color=TEXT_MUTED),
                     range=[0, 100])
    return fig


# ══════════════════════════════════════════════════════════════
# PER-TICKER PANEL RENDERER
# ══════════════════════════════════════════════════════════════

def render_ticker_panel(a: dict):
    ticker  = a["ticker"]
    chg_col = ACCENT_GREEN if a["chg_pct"] >= 0 else ACCENT_RED
    trend_c = {"bull": ACCENT_GREEN, "warn": YELLOW, "bear": ACCENT_RED}.get(a["trend_level"], TEXT_MUTED)
    arrow_fn = a["_arrow"]

    # ── Header Card ────────────────────────────────────────────
    weekly_spark_col, header_col = st.columns([1, 3])

    with header_col:
        sma200_str = f"${a['sma200_v']:.2f}" if a["sma200_v"] else "—"
        trend_lbl  = "Strong Uptrend ✅" if a["full_stack"] else ("Moderate Trend ⚠️" if a["partial"] else "Downtrend ❌")
        sig        = a["signal"]
        sig_pct    = a["signal_pct"]
        sig_color  = a["signal_color"]
        sig_icon   = "▲" if sig == "BUY" else ("▼" if sig == "SELL" else "◆")
        arrow_ud   = "▲" if a["chg_pct"] >= 0 else "▼"
        above_e20c = ACCENT_GREEN if a["above_ema20"] else ACCENT_RED
        above_s50c = ACCENT_GREEN if a["above_sma50"] else ACCENT_RED
        above_s200c = (ACCENT_GREEN if a["above_sma200"] else (TEXT_MUTED if not a["sma200_v"] else ACCENT_RED))
        st.markdown(
            f'<div style="background:linear-gradient(135deg,{BG_CARD} 0%,{BG_PANEL} 100%);'
            f'border:1px solid {BORDER_COLOR};border-left:5px solid {sig_color};'
            f'border-radius:10px;padding:18px 24px;margin-bottom:0">'
            f'<div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:12px;align-items:flex-start">'
            f'<div>'
            f'<div style="color:{GOLD};font-size:34px;font-family:\'Cormorant Garamond\',serif;'
            f'font-weight:700;letter-spacing:2px;line-height:1">{ticker}</div>'
            f'<div style="color:{TEXT_PRIMARY};font-size:14px;margin-top:4px">{a["name"]}</div>'
            f'<div style="color:{TEXT_MUTED};font-size:11px">{a["sector"]}</div>'
            f'</div>'
            f'<div style="display:flex;flex-direction:column;align-items:flex-end;gap:6px">'
            f'<div style="color:{TEXT_PRIMARY};font-size:30px;font-family:\'Cormorant Garamond\',serif;font-weight:700;line-height:1">'
            f'${a["price"]:.2f}</div>'
            f'<div style="color:{chg_col};font-size:15px;font-weight:600">{arrow_ud} {a["chg_pct"]:+.2f}%</div>'
            f'<div style="background:{sig_color}22;border:2px solid {sig_color};border-radius:8px;'
            f'padding:6px 18px;text-align:center;min-width:110px">'
            f'<div style="color:{sig_color};font-size:11px;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:1.5px">{sig_icon} {sig}</div>'
            f'<div style="color:{sig_color};font-size:26px;font-weight:800;line-height:1.1">{sig_pct}%</div>'
            f'<div style="color:{sig_color}99;font-size:9px;text-transform:uppercase;letter-spacing:0.8px">confidence</div>'
            f'</div>'
            f'</div>'
            f'</div>'
            f'<div style="margin-top:12px;display:flex;flex-wrap:wrap;gap:8px;align-items:center">'
            f'{_badge(trend_lbl, a["trend_level"])}'
            f'<span style="color:{TEXT_MUTED};font-size:12px">'
            f'EMA20 <b style="color:{above_e20c}">${a["ema20_v"]:.2f}</b>'
            f'&nbsp;&middot;&nbsp; SMA50 <b style="color:{above_s50c}">${a["sma50_v"]:.2f}</b>'
            f'&nbsp;&middot;&nbsp; SMA200 <b style="color:{above_s200c}">{sma200_str}</b>'
            f'</span>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    with weekly_spark_col:
        st.markdown(f"""
<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:10px;
            padding:10px 12px;height:100%">
  <div style="color:{TEXT_MUTED};font-size:10px;text-transform:uppercase;
              letter-spacing:1px;margin-bottom:4px">52-Week Weekly</div>
""", unsafe_allow_html=True)
        if a["df_w"] is not None and not a["df_w"].empty and len(a["df_w"]) >= 4:
            st.plotly_chart(_mini_weekly_chart(a["df_w"], ticker), width='stretch')
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    # ── Composite Score Rings ───────────────────────────────────
    def _score_color(s): return ACCENT_GREEN if s >= 70 else (GOLD if s >= 50 else ACCENT_RED)

    s1, s2, s3 = st.columns(3)
    for col, label, score_key in [
        (s1, "Momentum",      "momentum_score"),
        (s2, "Trend Strength","trend_score"),
        (s3, "Buy Pressure",  "buy_pressure_score"),
    ]:
        sc = a[score_key]
        with col:
            st.markdown(f"""
<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:8px">
  {_score_ring(label, sc, _score_color(sc))}
</div>""", unsafe_allow_html=True)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    # ── Left / Right indicator columns ─────────────────────────
    left, right = st.columns(2)

    # ════ LEFT COLUMN ═══════════════════════════════════════════
    with left:

        # 1. Moving Average Trend ──────────────────────────────
        s200_lbl = f"{arrow_fn(a['slope_200'])} {a['slope_200']:+.2f}% /10d"
        s50_lbl  = f"{arrow_fn(a['slope_50'])} {a['slope_50']:+.2f}% /10d"
        sma200_txt = f"${a['sma200_v']:.2f}" if a["sma200_v"] else "N/A"
        rows = (
            _srow("Trend Stack Alignment",
                  "Full Stack ✅" if a["full_stack"] else ("Partial ⚠️" if a["partial"] else "Broken ❌"),
                  a["trend_level"],
                  "Full Stack = Price > EMA20 > SMA50 > SMA200. All 4 conditions must hold for strong uptrend.")
            + _srow(f"Price ${a['price']:.2f} vs EMA20 ${a['ema20_v']:.2f}",
                    "Above ✅" if a["above_ema20"] else "Below ❌",
                    "bull" if a["above_ema20"] else "bear",
                    "Price above EMA20 confirms short-term momentum. Ideal entry when price bounces off EMA20.")
            + _srow(f"EMA20 ${a['ema20_v']:.2f} vs SMA50 ${a['sma50_v']:.2f}",
                    "Above ✅" if a["ema20_above_50"] else "Below ❌",
                    "bull" if a["ema20_above_50"] else "bear",
                    "EMA20 above SMA50 = momentum aligned with medium-term trend. Bullish structure.")
            + _srow(f"SMA50 vs SMA200 {sma200_txt}",
                    "Golden Cross ✅" if a["sma50_above_200"] else ("N/A" if not a["sma200_v"] else "Death Cross ❌"),
                    "bull" if a["sma50_above_200"] else ("neutral" if not a["sma200_v"] else "bear"),
                    "SMA50 > SMA200 = Golden Cross (long-term bullish). SMA50 < SMA200 = Death Cross (bearish).")
            + _srow(f"200 SMA Slope (10 bars)",
                    s200_lbl,
                    "bull" if a["slope_200"] > 0 else "bear",
                    "Rising 200 SMA slope = long-term uptrend is healthy. Flat/falling = caution on longs.")
            + _srow(f"50 SMA Slope (10 bars)",
                    s50_lbl,
                    "bull" if a["slope_50"] > 0 else "bear",
                    "Rising 50 SMA = medium-term trend intact. Sell signals are weaker in a rising-50-SMA environment.")
        )
        st.markdown(_section("Moving Average Trend", "📈", rows, dual_timeframe=False), unsafe_allow_html=True)

        # 2. MACD ─────────────────────────────────────────────
        macd_slope_lbl = f"{'Rising ↗' if a['slope_macd'] > 0 else 'Falling ↘'} {a['slope_macd']:+.4f}"
        rows = (
            _row("Line vs Signal (Cross)",
                 "Bull Cross ✅" if a["cross_d"] else "Bear Cross ❌",
                 "Bull Cross ✅" if a["cross_w"] else "Bear Cross ❌",
                 "bull" if a["cross_d"] else "bear",
                 "bull" if a["cross_w"] else "bear",
                 "MACD line crossing above signal = bullish. Buy zone starts. Cross below = sell signal.")
            + _row("Histogram",
                   f"{'▲ Positive' if a['hist_pos_d'] else '▼ Negative'} {a['h_d']:+.4f}",
                   f"{'▲ Positive' if a['hist_pos_w'] else '▼ Negative'} {a['h_w']:+.4f}",
                   "bull" if a["hist_pos_d"] else "bear",
                   "bull" if a["hist_pos_w"] else "bear",
                   "Positive histogram = MACD diverging above signal (momentum building). Negative = fading.")
            + _row("MACD / Signal / Hist",
                   f"{a['m_d']:+.3f} / {a['s_d']:+.3f} / {a['h_d']:+.3f}",
                   f"{a['m_w']:+.3f} / {a['s_w']:+.3f} / {a['h_w']:+.3f}",
                   "bull" if a["hist_pos_d"] else "bear",
                   "bull" if a["hist_pos_w"] else "bear",
                   "Raw MACD values. Positive MACD line = above zero line (bullish regime).")
            + _srow("MACD Slope (Daily 3-bar)",
                    macd_slope_lbl,
                    "bull" if a["slope_macd"] > 0 else "bear",
                    "Rising MACD slope = momentum accelerating. Falling while positive = momentum decelerating.")
        )
        st.markdown(_section("MACD", "📡", rows, dual_timeframe=True), unsafe_allow_html=True)

        # 3. RSI with Visual Gauge ────────────────────────────
        rsi_html = f"""
<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:8px;
            margin-bottom:12px;overflow:hidden">
  <div style="background:{BG_PANEL};padding:9px 14px;border-bottom:1px solid {BORDER_COLOR}">
    <span style="color:{GOLD};font-size:13px;font-weight:700"
          title="RSI ranges: Below 30 = Oversold (potential reversal buy). 30-55 = Neutral. 55-68 = Momentum Zone (ideal entry). 68-70 = Hot (reduce size). Above 70 = Overbought (caution/take profit).">
      💪 RSI (Relative Strength Index)
    </span>
    <span style="color:{TEXT_MUTED};font-size:10px;float:right;margin-top:2px">Daily &nbsp;·&nbsp; Weekly</span>
  </div>
  <div style="padding:12px 14px">
    <div style="color:{TEXT_MUTED};font-size:10px;text-transform:uppercase;letter-spacing:0.8px;margin-bottom:4px">📅 Daily</div>
    {_rsi_gauge(a['rsi_d'])}
    <div style="border-top:1px solid {BORDER_COLOR};margin:10px 0 8px"></div>
    <div style="color:{TEXT_MUTED};font-size:10px;text-transform:uppercase;letter-spacing:0.8px;margin-bottom:4px">📆 Weekly</div>
    {_rsi_gauge(a['rsi_w'])}
    <div style="margin-top:10px;color:{TEXT_MUTED};font-size:10px;line-height:1.7">
      Zone guide:
      <span style="color:{ACCENT_RED}">&lt;30 Oversold</span> ·
      <span style="color:{TEXT_MUTED}">30–55 Neutral</span> ·
      <span style="color:{ACCENT_GREEN}">55–68 Momentum ✅</span> ·
      <span style="color:{YELLOW}">68–70 Hot</span> ·
      <span style="color:{ACCENT_RED}">&gt;70 Overbought</span>
    </div>
  </div>
</div>"""
        st.markdown(rsi_html, unsafe_allow_html=True)

    # ════ RIGHT COLUMN ═══════════════════════════════════════════
    with right:

        # 4. Volume + OBV + MFI ──────────────────────────────
        vol_lbl  = f"{a['vol_ratio']:.2f}× {'🔥 Spike' if a['vol_spike'] else 'avg'}"
        vol_lvl  = "bull" if a["vol_spike"] else "neutral"
        obv_lbl  = f"{'Rising ↗' if a['obv_bull'] else 'Falling ↘'} ({a['obv_slope']:+.1f}%)"
        obv_lvl  = "bull" if a["obv_bull"] else "bear"
        mfi_lvl  = "bull" if a["mfi"] > 60 else ("bear" if a["mfi"] < 40 else "neutral")
        mfi_lbl  = f"{a['mfi']:.0f} — {'Buy Pressure' if a['mfi'] > 60 else ('Sell Pressure' if a['mfi'] < 40 else 'Neutral')}"
        rows = (
            _srow("Volume vs 20-Day Avg",
                  vol_lbl, vol_lvl,
                  "Volume >= 1.5x avg = Spike (strong conviction). Below 1x = weak move, treat with caution.")
            + _srow("OBV Direction (5-bar)",
                    obv_lbl, obv_lvl,
                    "On-Balance Volume rising = institutional accumulation (bullish). Falling = distribution. Divergence from price is key.")
            + _srow("Money Flow Index (MFI)",
                    mfi_lbl, mfi_lvl,
                    "MFI >60 = money flowing in (buy pressure). MFI <40 = money leaving (sell pressure). Range 0-100. Cross of 50 is signal.")
        )
        st.markdown(_section("Volume Analysis", "🌊", rows, dual_timeframe=False), unsafe_allow_html=True)

        # 5. Bollinger Bands ──────────────────────────────────
        bb_pos_lbl = ("Above Upper ⚡" if a["above_upper"] else
                      ("Below Lower 💀" if a["below_lower"] else "Inside Bands"))
        bb_pos_lvl = "warn" if a["above_upper"] else ("bear" if a["below_lower"] else "neutral")
        pct_b_lbl  = f"{a['pct_b']:.0f}% of band"
        pct_b_lvl  = "bull" if a["pct_b"] > 65 else ("bear" if a["pct_b"] < 35 else "neutral")
        bw_lbl     = f"{a['bb_w_v']:.1f}% width"
        sq_lbl     = "Squeeze ⚡ (breakout imminent)" if a["bb_squeeze"] else "Normal range"
        sq_lvl     = "warn" if a["bb_squeeze"] else "neutral"
        rows = (
            _srow("Price vs Bands",
                  bb_pos_lbl, bb_pos_lvl,
                  "Above upper band = overbought extension or breakout. Below lower = oversold. Inside = normal range.")
            + _srow("%B (Position in Band)",
                    pct_b_lbl, pct_b_lvl,
                    "%B = 0% means price at lower band, 100% = upper band. >80% = upper zone (overbought/breakout). <20% = lower zone.")
            + _srow("Band Width",
                    bw_lbl, "warn" if a["bb_squeeze"] else "neutral",
                    "Narrowing bandwidth = volatility compression (quiet before storm). Wide = expansion after breakout.")
            + _srow("Squeeze Condition",
                    sq_lbl, sq_lvl,
                    "Bollinger Band Squeeze: bands narrow to 20-day low. Precedes high-volatility directional move. Direction unknown.")
            + _html_row(_pct_b_bar(a["pct_b"], a["bb_lo_v"], a["bb_mid_v"], a["bb_up_v"]))
        )
        st.markdown(_section("Bollinger Bands", "🌀", rows, dual_timeframe=False), unsafe_allow_html=True)

        # 6. Breakout Conditions ──────────────────────────────
        rows = (
            _srow("Breakout Status",
                  a["brk_label"], a["brk_level"],
                  "Confirmed: new 20-day high + volume spike. Potential: within 2% of high. Volume confirmation is critical.")
            + _srow("New 20-Day High",
                    "Yes ✅" if a["new_20h"] else "No",
                    "bull" if a["new_20h"] else "neutral",
                    "Price at or above 20-day closing high = swing breakout candidate. Watch for follow-through next session.")
            + _srow("Within 2% of 20D High",
                    "Yes ⚡" if a["near_20h"] else "No",
                    "warn" if (a["near_20h"] and not a["new_20h"]) else ("bull" if a["new_20h"] else "neutral"),
                    "Price within 2% of 20-day high = approaching potential breakout. Set alerts near this level.")
            + _srow("New 50-Day High",
                    "Yes ✅" if a["new_50h"] else "No",
                    "bull" if a["new_50h"] else "neutral",
                    "New 50-day high = confirmed medium-term breakout. Higher base of support established.")
            + _srow("Volume Confirmation",
                    "Confirmed 🔥" if a["vol_spike"] else "Not Confirmed",
                    "bull" if a["vol_spike"] else "neutral",
                    "Volume >= 1.5x avg is required to trust a breakout. Low-volume breakouts fail 60%+ of the time.")
        )
        st.markdown(_section("Breakout Conditions", "🚀", rows, dual_timeframe=False), unsafe_allow_html=True)

    # ── Full-width bottom row ────────────────────────────────────
    b1, b2, b3 = st.columns(3)

    with b1:
        # 7. Short Squeeze ────────────────────────────────────
        sp_lbl = f"{a['short_pct']:.1f}% of float" if a["short_pct"] > 0 else "N/A"
        sr_lbl = f"{a['short_ratio']:.1f} days" if a["short_ratio"] > 0 else "N/A"
        sp_lvl = "warn" if a["short_pct"] >= 8 else "neutral"
        sr_lvl = "warn" if a["short_ratio"] >= 4 else "neutral"
        rows = (
            _srow("Squeeze Potential",
                  a["sq_label"], a["sq_level"],
                  "High: Short% >15% float OR days-to-cover >7. As price rises, shorts must cover = accelerating squeeze rally.")
            + _srow("Short % of Float",
                    sp_lbl, sp_lvl,
                    "Short interest >10% float = meaningful squeeze fuel. >20% = extreme. Combined with rising price = squeeze risk.")
            + _srow("Days to Cover",
                    sr_lbl, sr_lvl,
                    "Days-to-cover = short interest / avg daily volume. >5 days = high squeeze risk. Shorts trapped if price rises fast.")
        )
        st.markdown(_section("Short Squeeze", "🔥", rows, dual_timeframe=False), unsafe_allow_html=True)

    with b2:
        # 8. ATR & Volatility ─────────────────────────────────
        atr_size_lvl = "warn" if a["atr_pct"] > 3.0 else "neutral"
        rows = (
            _srow("ATR Status",
                  a["atr_label"], a["atr_level"],
                  "ATR Expanding = volatility increasing (bigger daily swings). Contracting = quieting down, possible squeeze setup.")
            + _srow("ATR % of Price",
                    f"{a['atr_pct']:.2f}% daily range",
                    atr_size_lvl,
                    "ATR% >3% = high-volatility instrument (wider stops needed). <1% = low-vol (tight stops possible). Position size accordingly.")
            + _srow("Volatility Regime",
                    "Expansion ⚡" if a["atr_exp"] else "Contraction",
                    "warn" if a["atr_exp"] else "neutral",
                    "Volatility expansion follows breakouts and earnings. Contraction precedes compression. Trade breakouts on expansion.")
        )
        st.markdown(_section("ATR & Volatility", "⚡", rows, dual_timeframe=False), unsafe_allow_html=True)

    with b3:
        # 9. Relative Strength ────────────────────────────────
        rows = (
            _srow("RS vs SPY (S&P 500)",
                  a["rs_spy_label"], a["rs_spy_level"],
                  "RS >1.05 = outperforming SPY over 63 days. Focus on stocks leading the market. RS <0.95 = laggard, avoid.")
            + _srow(f"RS vs {a['sector_etf'] or 'Sector ETF'}",
                    a["rs_sec_label"], a["rs_sec_level"],
                    "RS vs sector ETF isolates stock-specific alpha. Strong RS vs sector = true leader. Combine with SPY RS for top picks.")
        )
        st.markdown(_section("Relative Strength vs Benchmark", "🏆", rows, dual_timeframe=False), unsafe_allow_html=True)

    # ── Main Interactive Chart ───────────────────────────────────
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11px;margin:8px 0 4px">'
        f'📊 Last 120 days — Candlestick · Bollinger Bands · EMA20 / SMA50 / SMA200 '
        f'· Volume · MACD · RSI with zone lines</div>',
        unsafe_allow_html=True,
    )
    with st.spinner(f"Rendering chart for {ticker}…"):
        st.plotly_chart(_build_chart(a), width='stretch')

    # ── Ticker divider ──────────────────────────────────────────
    st.markdown(
        f'<div style="height:2px;background:linear-gradient(90deg,transparent,{GOLD}55,transparent);'
        f'margin:28px 0 32px"></div>',
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════
# SUMMARY TABLE — all tickers at a glance
# ══════════════════════════════════════════════════════════════

def _render_summary_table(analyses: list):
    """Compact at-a-glance table shown ABOVE per-ticker detail panels."""
    if not analyses:
        return

    def _score_bar(score: int) -> str:
        color = ACCENT_GREEN if score >= 70 else (GOLD if score >= 50 else ACCENT_RED)
        bar_w = int(score * 44 / 100)
        return (
            f'<div style="display:flex;align-items:center;gap:5px">'
            f'<div style="background:#1a1a2a;border-radius:2px;height:5px;width:44px">'
            f'<div style="background:{color};height:5px;border-radius:2px;width:{bar_w}px"></div>'
            f'</div>'
            f'<span style="color:{color};font-size:11px;font-weight:700">{score}</span>'
            f'</div>'
        )

    rows_html = []
    for a in analyses:
        sig       = a["signal"]
        sig_pct   = a["signal_pct"]
        sig_color = a["signal_color"]
        circle    = "🟢" if sig == "BUY" else ("🔴" if sig == "SELL" else "🟡")

        # Weekly MACD
        macd_w_color = ACCENT_GREEN if a["cross_w"] else ACCENT_RED
        macd_w_label = "Bull ✅" if a["cross_w"] else "Bear ❌"
        macd_w_vals  = f"{a['m_w']:+.3f} / {a['s_w']:+.3f}"

        # RSI colors
        def _rsi_color(r):
            return ACCENT_GREEN if 55 <= r <= 68 else (ACCENT_RED if r > 70 or r < 30 else YELLOW)

        rsi_d_c = _rsi_color(a["rsi_d"])
        rsi_w_c = _rsi_color(a["rsi_w"])

        # Trend label
        trend_color = (ACCENT_GREEN if a["trend_level"] == "bull"
                       else (YELLOW if a["trend_level"] == "warn" else ACCENT_RED))
        trend_lbl   = "Full Stack" if a["full_stack"] else ("Partial" if a["partial"] else "Weak")

        # Volume & RS
        vol_color = ACCENT_GREEN if a["vol_spike"] else TEXT_MUTED
        vol_lbl   = f"{a['vol_ratio']:.1f}×{'🔥' if a['vol_spike'] else ''}"
        rs_color  = (ACCENT_GREEN if a["rs_spy"] >= 1.05
                     else (ACCENT_RED if a["rs_spy"] < 0.95 else TEXT_MUTED))
        rs_lbl    = f"RS {a['rs_spy']:.3f}×"

        chg_c = ACCENT_GREEN if a["chg_pct"] >= 0 else ACCENT_RED
        td    = f"padding:9px 10px;border-bottom:1px solid {BORDER_COLOR}22;vertical-align:middle"

        rows_html.append(f"""<tr>
          <td style="{td};font-size:18px;text-align:center;width:32px">{circle}</td>
          <td style="{td}">
            <div style="color:{GOLD};font-size:14px;font-weight:800;font-family:'DM Mono',monospace;letter-spacing:1px">{a['ticker']}</div>
            <div style="color:{TEXT_MUTED};font-size:10px;margin-top:1px">${a['price']:.2f}
              <span style="color:{chg_c}">&nbsp;{a['chg_pct']:+.1f}%</span></div>
          </td>
          <td style="{td}">
            <div style="background:{sig_color}22;border:1px solid {sig_color}55;border-radius:6px;
                        padding:5px 10px;text-align:center;min-width:72px">
              <div style="color:{sig_color};font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.8px">{sig}</div>
              <div style="color:{sig_color};font-size:17px;font-weight:800;line-height:1.1">{sig_pct}%</div>
            </div>
          </td>
          <td style="{td}">
            <div style="color:{macd_w_color};font-size:11px;font-weight:600">{macd_w_label}</div>
            <div style="color:{TEXT_MUTED};font-size:10px;font-family:'DM Mono',monospace;margin-top:2px">{macd_w_vals}</div>
          </td>
          <td style="{td}">
            <div style="color:{rsi_d_c};font-size:11px;font-weight:600">D:&nbsp;{a['rsi_d']:.0f}</div>
            <div style="color:{rsi_w_c};font-size:11px;font-weight:600;margin-top:3px">W:&nbsp;{a['rsi_w']:.0f}</div>
          </td>
          <td style="{td}">
            <div style="color:{trend_color};font-size:11px;font-weight:600;margin-bottom:4px">{trend_lbl}</div>
            {_score_bar(a['trend_score'])}
          </td>
          <td style="{td}">{_score_bar(a['momentum_score'])}</td>
          <td style="{td}">{_score_bar(a['buy_pressure_score'])}</td>
          <td style="{td}">
            <div style="color:{vol_color};font-size:11px;font-weight:600">{vol_lbl}</div>
            <div style="color:{rs_color};font-size:10px;margin-top:3px">{rs_lbl}</div>
          </td>
        </tr>""")

    th = (f"padding:8px 10px;color:{TEXT_MUTED};font-size:10px;font-weight:700;"
          f"text-transform:uppercase;letter-spacing:.8px;background:{BG_PANEL};"
          f"border-bottom:2px solid {GOLD}44;white-space:nowrap")
    headers = ["", "Ticker", "Signal / Conf", "Weekly MACD", "RSI D/W",
               "Trend Strength", "Momentum", "Buy Pressure", "Vol / RS"]
    hdr_html = "".join(f'<th style="{th}">{h}</th>' for h in headers)

    st.markdown(
        f'<div style="background:{BG_PANEL};border:1px solid {GOLD}44;border-radius:10px;'
        f'margin-bottom:28px;overflow:hidden">'
        f'<div style="background:{BG_CARD};padding:11px 18px;border-bottom:1px solid {BORDER_COLOR};'
        f'display:flex;align-items:center;justify-content:space-between">'
        f'<span style="color:{GOLD};font-size:13px;font-weight:700">📊 Summary — All Tickers at a Glance</span>'
        f'<span style="color:{TEXT_MUTED};font-size:11px">'
        f'🟢&thinsp;Buy &nbsp;·&nbsp; 🟡&thinsp;Neutral &nbsp;·&nbsp; 🔴&thinsp;Sell</span>'
        f'</div>'
        f'<div style="overflow-x:auto">'
        f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
        f'<thead><tr>{hdr_html}</tr></thead>'
        f'<tbody>{"".join(rows_html)}</tbody>'
        f'</table></div></div>',
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════
# MAIN RENDER
# ══════════════════════════════════════════════════════════════

def render():
    section_header(
        "🔬", "Stock Analysis",
        "Multi-ticker · Daily + Weekly · 9 indicator modules · Composite scores · Interactive chart",
    )

    # ── Ticker input — prominent, in main content area ──────────
    st.markdown(f"""
<div style="background:{BG_PANEL};border:1px solid {GOLD}44;border-radius:10px;
            padding:18px 24px;margin-bottom:20px">
  <div style="color:{GOLD};font-size:12px;font-weight:700;text-transform:uppercase;
              letter-spacing:1.2px;margin-bottom:10px">🔬 Enter Tickers to Analyze</div>
  <div style="color:{TEXT_MUTED};font-size:12px;margin-bottom:10px">
    Type 1–25 stock symbols separated by commas, then click <b style="color:{TEXT_PRIMARY}">▶ Analyze</b>.
    Example: <span style="color:{GOLD};font-family:'DM Mono',monospace">AAPL, MSFT, NVDA, TSLA, META</span>
  </div>
</div>""", unsafe_allow_html=True)

    col_input, col_run, col_clr = st.columns([4, 1, 1])
    with col_input:
        ticker_input = st.text_input(
            "Tickers",
            value="AAPL",
            placeholder="e.g. AAPL, MSFT, NVDA, TSLA, META, GOOGL, AMZN …",
            label_visibility="collapsed",
        )
    with col_run:
        run = st.button("▶ Analyze", use_container_width=True)
    with col_clr:
        if st.button("🔄 Clear Cache", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    import re
    raw     = [t.upper() for t in re.split(r"[\s,;]+", ticker_input.strip()) if t.strip()]
    tickers = raw[:25]

    if len(raw) > 25:
        st.warning(f"Only the first 25 tickers will be analyzed. Dropped: {', '.join(raw[25:])}")

    if not tickers:
        st.info("Enter 1–5 ticker symbols above and click **▶ Analyze**.")
        return

    if not run:
        # Landing card ─────────────────────────────────────────
        features = [
            ("&#128200;", "Trend Stack",        "Price &gt; EMA20 &gt; SMA50 &gt; SMA200 &middot; Slope analysis"),
            ("&#128225;", "MACD",               "Daily + Weekly &middot; Cross &middot; Histogram &middot; Slope"),
            ("&#128170;", "RSI Gauge",           "Visual zone bar &middot; Daily + Weekly &middot; All 5 zones"),
            ("&#127754;", "Volume &amp; OBV",    "Volume spike &middot; OBV direction &middot; Money Flow Index"),
            ("&#127744;", "Bollinger Bands",     "Squeeze &middot; %B &middot; Band width &middot; Breakout detection"),
            ("&#128640;", "Breakouts",           "20/50-day high &middot; Volume-confirmed &middot; Near-zone"),
            ("&#128293;", "Short Squeeze",       "Short% float &middot; Days to cover &middot; Squeeze rating"),
            ("&#9889;",   "ATR &amp; Vol",       "ATR% &middot; Expanding / Contracting &middot; Volatility regime"),
            ("&#127942;", "Relative Strength",   "RS vs SPY &middot; RS vs Sector ETF &middot; Leader or laggard"),
        ]

        def _feat_card(ic, ti, de):
            return (
                f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};'
                f'border-radius:8px;padding:14px 16px">'
                f'<div style="font-size:20px;margin-bottom:6px">{ic}</div>'
                f'<div style="color:{GOLD};font-size:12px;font-weight:700;margin-bottom:4px">{ti}</div>'
                f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.5">{de}</div>'
                f'</div>'
            )

        cards_html = "".join(_feat_card(ic, ti, de) for ic, ti, de in features)
        st.markdown(
            f'<div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:12px;'
            f'padding:40px;text-align:center;margin-top:8px">'
            f'<div style="font-size:52px;margin-bottom:16px">&#128302;</div>'
            f'<div style="font-size:24px;color:{GOLD};font-family:\'Cormorant Garamond\',serif;margin-bottom:10px">'
            f'Deep Technical Analysis Panel</div>'
            f'<div style="color:{TEXT_MUTED};font-size:14px;max-width:580px;margin:0 auto 28px;line-height:1.8">'
            f'Enter up to <b style="color:{TEXT_PRIMARY}">25 tickers</b> above and click '
            f'<b style="color:{TEXT_PRIMARY}">&#9658; Analyze</b>. '
            f'Each ticker gets a full multi-color, dual-timeframe technical report '
            f'with hover tooltips, composite scores, and an interactive chart.</div>'
            f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;'
            f'max-width:760px;margin:0 auto;text-align:left">{cards_html}</div>'
            f'<div style="margin-top:24px;display:flex;justify-content:center;gap:20px;flex-wrap:wrap">'
            f'{_badge("Green = Bullish","bull")}'
            f'{_badge("Yellow = Neutral / Watch","warn")}'
            f'{_badge("Red = Bearish","bear")}'
            f'</div></div>',
            unsafe_allow_html=True,
        )
        return

    # Ticker pill bar (shown when running)
    st.markdown(f"""
<div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:8px;
            padding:10px 18px;margin-bottom:20px;display:flex;align-items:center;
            gap:12px;flex-wrap:wrap">
  <span style="color:{TEXT_MUTED};font-size:12px">Analyzing:</span>
  {''.join(
    f'<span style="background:{BG_CARD};border:1px solid {GOLD}55;color:{GOLD};'
    f'padding:4px 14px;border-radius:4px;font-family:\'DM Mono\',monospace;font-weight:700;font-size:13px">{t}</span>'
    for t in tickers
  )}
  <span style="color:{TEXT_MUTED};font-size:11px;margin-left:auto">
    Data via YFinance · Daily + Weekly timeframes
  </span>
</div>""", unsafe_allow_html=True)

    # Run analysis ──────────────────────────────────────────────
    analyses = []
    with st.spinner(f"Fetching data for {', '.join(tickers)}…"):
        for tk in tickers:
            result = compute_analysis(tk)
            if result:
                analyses.append(result)

    if not analyses:
        st.error("No valid data returned. Check ticker symbols and try again.")
        return

    # ── Summary table (top) ─────────────────────────────────────
    _render_summary_table(analyses)

    # ── Per-ticker detail panels ────────────────────────────────
    for a in analyses:
        render_ticker_panel(a)
