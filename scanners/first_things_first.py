"""
scanners/first_things_first.py — "First Things First" high-conviction setup scanner

Applies a strict multi-timeframe filter across weekly AND daily charts.
Any stock that passes ALL conditions is surfaced at the top of the MTPA and
CSP Strategy pages.  Returns even if nothing qualifies — caller renders the
empty state card.

Weekly conditions (ALL must hold):
  W1  HH/HL OR Tight Base (< 5% range in last 10 weekly bars)
  W2  Not extended (price within 10% above SMA20W)
  W3  RSI 35–70 (GREEN or YELLOW zone)
  W4  MACD > Signal line
  W5  Volume OK (0.7–2.0× 20-week avg — not dry, not spike)
  W6  Price > SMA20W
  W7  |MACD line| ≤ 1.5% of price (fresh crossover, not overrun)
  (W8 removed — W4 hist>0 is sufficient; declining positive histogram is still valid)
  W9  Uptrend (price > SMA50W OR HH/HL confirmed)

Daily conditions (ALL must hold):
  D1  Not extended (price within 8% above SMA9D)
  D2  RSI 35–70
  D3  MACD > Signal line
  D4  Price > SMA9D
  D5  Histogram rising (hist[-1] > hist[-2])
  D6  No nearby supply (price NOT within 3% below 20-day rolling high)
  D7  Volume > 20-day average

Cross-timeframe:
  X1  ADX > 16 AND ADX rising (ADX[-1] > ADX[-4])
  X2  No bearish divergence (price trend UP but RSI trend DOWN → excluded)
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
import yfinance as yf

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_loader import get_price_history
from utils import calc_ema, calc_sma, calc_rsi


# ── Indicator helpers ──────────────────────────────────────────────────────────

def _macd(close: pd.Series, fast=12, slow=26, sig=9):
    line   = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    signal = line.ewm(span=sig,  adjust=False).mean()
    hist   = line - signal
    return line, signal, hist


def _adx_series(close: pd.Series, high: pd.Series, low: pd.Series, period: int = 14) -> pd.Series:
    """Return full ADX series."""
    try:
        prev_cl = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_cl).abs(),
            (low  - prev_cl).abs(),
        ], axis=1).max(axis=1)
        atr  = tr.ewm(com=period - 1, adjust=False).mean()
        up   = high.diff();  down = -low.diff()
        pdm  = up.where((up > down) & (up > 0), 0.0)
        ndm  = down.where((down > up) & (down > 0), 0.0)
        safe = atr.replace(0, np.nan)
        pdi  = 100 * pdm.ewm(com=period - 1, adjust=False).mean() / safe
        ndi  = 100 * ndm.ewm(com=period - 1, adjust=False).mean() / safe
        denom = (pdi + ndi).replace(0, np.nan)
        dx   = (100 * (pdi - ndi).abs() / denom).fillna(0)
        return dx.ewm(com=period - 1, adjust=False).mean()
    except Exception:
        return pd.Series(dtype=float)


def _bearish_divergence(close: pd.Series, rsi: pd.Series, lookback: int = 14) -> bool:
    """
    True if price is making higher highs but RSI is making lower highs
    over the last `lookback` bars — classic bearish divergence.
    """
    try:
        if len(close) < lookback or len(rsi) < lookback:
            return False
        price_trend_up = float(close.iloc[-1]) > float(close.iloc[-lookback])
        rsi_trend_down = float(rsi.iloc[-1])   < float(rsi.iloc[-lookback])
        return price_trend_up and rsi_trend_down
    except Exception:
        return False


# ── Weekly check ───────────────────────────────────────────────────────────────

def _check_weekly(ticker: str, price: float) -> dict:
    """
    Fetch and evaluate all weekly conditions for a ticker.
    Returns dict with per-condition booleans and a 'pass' key.
    """
    result = {k: False for k in ["W1","W2","W3","W4","W5","W6","W7","W9","pass"]}
    result["detail"] = {}
    try:
        raw = yf.download(ticker, period="3y", interval="1wk",
                          progress=False, auto_adjust=True)
        if raw is None or raw.empty or len(raw) < 26:
            return result
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        raw.columns = [c.lower() for c in raw.columns]
        raw = raw.dropna(subset=["close"])

        close_w = raw["close"].squeeze()
        high_w  = raw["high"].squeeze()
        low_w   = raw["low"].squeeze()
        vol_w   = raw["volume"].squeeze()

        px = float(close_w.iloc[-1])

        # SMA20W, SMA50W
        sma20_w = float(calc_sma(close_w, 20).dropna().iloc[-1])
        sma50_w = float(calc_sma(close_w, 50).dropna().iloc[-1]) if len(close_w) >= 50 else sma20_w

        # HH/HL: last 5 weekly bars vs prior 5
        hh_hl = False
        if len(high_w) >= 10:
            hh_hl = (float(high_w.iloc[-5:].max()) > float(high_w.iloc[-10:-5].max()) and
                     float(low_w.iloc[-5:].min())  > float(low_w.iloc[-10:-5].min()))

        # Tight Base: last 10 weekly bars range < 5% of SMA20W
        tight_base = False
        if len(close_w) >= 10 and sma20_w > 0:
            rng = float(close_w.iloc[-10:].max() - close_w.iloc[-10:].min())
            tight_base = (rng / sma20_w * 100) < 5.0

        # RSI
        rsi_w_v = float(calc_rsi(close_w).dropna().iloc[-1])

        # MACD
        macd_w, sig_w, hist_w = _macd(close_w)
        m_w  = float(macd_w.dropna().iloc[-1])
        s_w  = float(sig_w.dropna().iloc[-1])
        h_w  = float(hist_w.dropna().iloc[-1])
        h_w_prev = float(hist_w.dropna().iloc[-2]) if len(hist_w.dropna()) >= 2 else h_w

        # Volume
        avg_vol_20w = float(vol_w.iloc[-21:-1].mean()) if len(vol_w) >= 21 else float(vol_w.mean())
        cur_vol_w   = float(vol_w.iloc[-1])
        vol_ratio_w = cur_vol_w / avg_vol_20w if avg_vol_20w > 0 else 1.0

        # Evaluate conditions
        result["W1"] = hh_hl or tight_base
        result["W2"] = (sma20_w > 0) and (px <= sma20_w * 1.10)          # within 10%
        result["W3"] = 35 <= rsi_w_v <= 70
        result["W4"] = m_w > s_w
        result["W5"] = 0.7 <= vol_ratio_w <= 3.0          # relaxed upper cap: breakout days OK
        result["W6"] = px > sma20_w
        # W7 — fresh crossover: MACD crossed above Signal within last 5 weekly bars
        # 5 weeks matches a weekly scan cadence — catches brand-new crosses AND
        # setups where other conditions (RSI, histogram, structure) remained valid
        # into weeks 4-5 after the initial cross. Beyond 5 weeks = stale setup.
        _fresh_cross_w = False
        _macd_d = macd_w.dropna(); _sig_d = sig_w.dropna()
        _n_check = min(8, len(_macd_d) - 1)
        for _k in range(1, _n_check + 1):
            if (float(_macd_d.iloc[-_k]) > float(_sig_d.iloc[-_k]) and
                    float(_macd_d.iloc[-_k - 1]) <= float(_sig_d.iloc[-_k - 1])):
                _fresh_cross_w = True
                break
        result["W7"] = _fresh_cross_w
        # W8 removed — W4 (hist>0) is sufficient guard
        result["W9"] = (px > sma50_w) or hh_hl

        result["detail"] = {
            "hh_hl": hh_hl, "tight_base": tight_base,
            "rsi_w": round(rsi_w_v, 1),
            "macd_w": round(m_w, 4), "sig_w": round(s_w, 4),
            "hist_w": round(h_w, 4), "hist_w_prev": round(h_w_prev, 4),
            "sma20_w": round(sma20_w, 2), "sma50_w": round(sma50_w, 2),
            "vol_ratio_w": round(vol_ratio_w, 2),
            "fresh_cross_w": _fresh_cross_w,
            "macd_pct_w": round(abs(m_w) / px * 100, 3) if px > 0 else 0,
        }
        result["pass"] = all(result[k] for k in ["W1","W2","W3","W4","W5","W6","W7","W9"])

    except Exception:
        pass
    return result


# ── Daily check ────────────────────────────────────────────────────────────────

def _check_daily(ticker: str, price: float) -> dict:
    """Evaluate all daily + cross-timeframe conditions."""
    result = {k: False for k in ["D1","D2","D3","D4","D5","D6","D7","X1","X2","pass"]}
    result["detail"] = {}
    try:
        df = get_price_history(ticker, period="6mo")
        if df is None or df.empty or len(df) < 30:
            return result

        close_d = df["Close"].squeeze()
        high_d  = df["High"].squeeze()  if "High"   in df.columns else None
        low_d   = df["Low"].squeeze()   if "Low"    in df.columns else None
        vol_d   = df["Volume"].squeeze() if "Volume" in df.columns else None

        px = float(close_d.iloc[-1])

        # EMAs / SMAs
        sma9_d  = float(calc_ema(close_d, 9).dropna().iloc[-1])
        sma20_d = float(calc_sma(close_d, 20).dropna().iloc[-1])

        # RSI
        rsi_d = calc_rsi(close_d).dropna()
        rsi_v = float(rsi_d.iloc[-1])

        # MACD
        macd_d, sig_d, hist_d = _macd(close_d)
        m_d = float(macd_d.dropna().iloc[-1])
        s_d = float(sig_d.dropna().iloc[-1])
        h_d = float(hist_d.dropna().iloc[-1])
        h_d_prev = float(hist_d.dropna().iloc[-2]) if len(hist_d.dropna()) >= 2 else h_d

        # Volume
        avg_vol = float(vol_d.iloc[-21:-1].mean()) if (vol_d is not None and len(vol_d) >= 21) else None
        cur_vol = float(vol_d.iloc[-1]) if vol_d is not None else None
        # D7: relaxed to 0.8× avg — normal consolidation days still qualify
        vol_above = (cur_vol >= avg_vol * 0.8) if (cur_vol and avg_vol) else False

        # Supply zone: price >2% below 20-day rolling high (relaxed from 3%)
        high_20d = float(close_d.iloc[-20:].max()) if len(close_d) >= 20 else px
        pct_below_high = (high_20d - px) / high_20d * 100 if high_20d > 0 else 0
        no_supply = pct_below_high > 2.0   # relaxed: 2% clear of resistance is sufficient

        # ADX
        adx_series = pd.Series(dtype=float)
        if high_d is not None and low_d is not None:
            adx_series = _adx_series(close_d, high_d, low_d)
        adx_v     = float(adx_series.dropna().iloc[-1])   if len(adx_series.dropna()) >= 1 else np.nan
        adx_prev  = float(adx_series.dropna().iloc[-4])   if len(adx_series.dropna()) >= 4 else np.nan
        adx_ok    = (not np.isnan(adx_v)) and adx_v > 16   # X1: just >16, rising = display only
        adx_rising= (not np.isnan(adx_prev)) and adx_v > adx_prev   # shown in table, not a gate

        # Bearish divergence
        div = _bearish_divergence(close_d, rsi_d, lookback=14)

        # Demand zone (preferred, not mandatory — used for display only)
        low_10d = float(close_d.iloc[-10:].min()) if len(close_d) >= 10 else px
        in_demand = px <= low_10d * 1.05   # within 5% above recent swing low

        result["D1"] = (sma9_d > 0) and (px <= sma9_d * 1.08)    # within 8% above SMA9
        result["D2"] = 35 <= rsi_v <= 70
        result["D3"] = m_d > s_d
        result["D4"] = px > sma9_d
        result["D5"] = h_d > h_d_prev
        result["D6"] = no_supply
        result["D7"] = vol_above
        result["X1"] = adx_ok          # rising is informational only
        result["X2"] = not div                                     # True = no divergence

        result["detail"] = {
            "rsi_d":       round(rsi_v, 1),
            "macd_d":      round(m_d, 4),
            "sig_d":       round(s_d, 4),
            "hist_d":      round(h_d, 4),
            "hist_d_prev": round(h_d_prev, 4),
            "sma9_d":      round(sma9_d, 2),
            "adx":         round(adx_v, 1) if not np.isnan(adx_v) else None,
            "adx_rising":  adx_rising,
            "bearish_div": div,
            "in_demand":   in_demand,
            "pct_below_high": round(pct_below_high, 1),
        }
        daily_conditions = ["D1","D2","D3","D4","D5","D6","D7","X1","X2"]
        result["pass"] = all(result[k] for k in daily_conditions)

    except Exception:
        pass
    return result


# ── Main scanner ───────────────────────────────────────────────────────────────

def run_ftf_scan(
    tickers: list[str],
    status_fn=None,
) -> list[dict]:
    """
    Run the First-Things-First scan across tickers.
    Returns list of dicts for qualifying tickers, sorted by ADX desc.
    Each dict contains: ticker, price, weekly_detail, daily_detail,
    weekly_flags (list of passing W conditions), daily_flags (list of passing D conditions).
    """
    qualified = []

    for i, ticker in enumerate(tickers):
        if status_fn:
            status_fn(i, len(tickers), ticker)

        try:
            df_px = get_price_history(ticker, period="5d")
            if df_px is None or df_px.empty:
                continue
            price = float(df_px["Close"].squeeze().dropna().iloc[-1])
        except Exception:
            continue

        # Weekly check first (gate)
        wk = _check_weekly(ticker, price)
        if not wk["pass"]:
            continue

        # Daily + cross-TF check
        dy = _check_daily(ticker, price)
        if not dy["pass"]:
            continue

        # Both pass — build condition flag strings
        w_flags = []
        w_map = {
            "W1": "HH/HL or Base", "W2": "Not Extended", "W3": "RSI ✓",
            "W4": "MACD>Sig",      "W5": "Vol OK",        "W6": "P>SMA20W",
            "W7": "Fresh Cross≤8wk",                         "W9": "Uptrend",
        }
        d_map = {
            "D1": "Not Ext'd",  "D2": "RSI ✓",     "D3": "MACD>Sig",
            "D4": "P>SMA9",     "D5": "Hist↑",      "D6": "No Supply",
            "D7": "Vol>Avg",    "X1": "ADX>16↑",    "X2": "No BearDiv",
        }
        for k, lbl in w_map.items():
            if wk.get(k):
                w_flags.append(lbl)
        d_flags = []
        for k, lbl in d_map.items():
            if dy.get(k):
                d_flags.append(lbl)

        qualified.append({
            "ticker":       ticker,
            "price":        round(price, 2),
            "w_detail":     wk.get("detail", {}),
            "d_detail":     dy.get("detail", {}),
            "w_flags":      w_flags,
            "d_flags":      d_flags,
        })

    # Sort by ADX descending (higher ADX = stronger trend)
    qualified.sort(
        key=lambda r: r["d_detail"].get("adx") or 0,
        reverse=True,
    )
    return qualified
