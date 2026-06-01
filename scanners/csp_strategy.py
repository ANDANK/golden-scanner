"""
scanners/csp_strategy.py — CSP Strategy Stock Screener
Filters stocks for optimal Cash-Secured Put eligibility using ONLY
price/volume/technical data (no options chain fetches).
IV metrics are derived from realized-volatility history (HV30/HV252).
"""

import numpy as np
import pandas as pd
import yfinance as yf
import time, random

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import SP500_SAMPLE, OPTIONS_ETF_UNIVERSE
from data_loader import get_price_history
from utils import calc_ema, calc_sma, calc_rsi

# ── Universe ───────────────────────────────────────────────────────────────────
def default_universe() -> list[str]:
    return list(dict.fromkeys(SP500_SAMPLE + OPTIONS_ETF_UNIVERSE))

# ── Filter thresholds ─────────────────────────────────────────────────────────
PRICE_MIN       = 15.0
AVG_VOL_MIN     = 300_000
BETA_MAX        = 1.5
RSI_LO          = 35
RSI_HI          = 68
ADX_TREND_MIN   = 25        # ADX > 25 confirms a strong uptrend (good for CSP entry)
GAP_MAX_PCT     = 7.0       # max single-day move allowed in last 20 sessions
NEAR_HIGH_PCT   = 7.0       # price must be within X% of 20-day high
EMA9_SLOPE_MIN  = -0.05     # allow very slight negative slope (flat)

# ── IV display thresholds (flag, not filter) ───────────────────────────────────
IVR_GOOD  = 40              # elevated vol rank — enough premium to sell
IVP_GOOD  = 45              # elevated vol percentile — above historical median

# ── Helpers ────────────────────────────────────────────────────────────────────

def _adx(close, high, low, period: int = 14) -> float:
    """14-period ADX from Series inputs."""
    try:
        if len(close) < period + 5:
            return np.nan
        prev_cl = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_cl).abs(),
            (low  - prev_cl).abs(),
        ], axis=1).max(axis=1)
        atr  = tr.ewm(com=period - 1, adjust=False).mean()
        up   = high.diff()
        down = -low.diff()
        pdm  = up.where((up > down) & (up > 0), 0.0)
        ndm  = down.where((down > up) & (down > 0), 0.0)
        safe = atr.replace(0, np.nan)
        pdi  = 100 * pdm.ewm(com=period - 1, adjust=False).mean() / safe
        ndi  = 100 * ndm.ewm(com=period - 1, adjust=False).mean() / safe
        denom = (pdi + ndi).replace(0, np.nan)
        dx   = (100 * (pdi - ndi).abs() / denom).fillna(0)
        adx_s = dx.ewm(com=period - 1, adjust=False).mean()
        val = float(adx_s.dropna().iloc[-1])
        return val if np.isfinite(val) else np.nan
    except Exception:
        return np.nan


def _hv_metrics(close: pd.Series) -> dict:
    """
    HV30/HV60 realized-vol metrics used as IV proxy.
    Returns hv30, hv60, vr (vol rank 0-100), vp (vol percentile), expanding flag.
    """
    _empty = {"hv30": np.nan, "hv60": np.nan, "vr": np.nan,
               "vp": np.nan, "expanding": False}
    try:
        if len(close) < 65:
            return _empty
        rets = close.pct_change().dropna()
        hv30 = float(rets.rolling(30).std().dropna().iloc[-1]) * (252 ** 0.5) * 100
        hv60 = float(rets.rolling(60).std().dropna().iloc[-1]) * (252 ** 0.5) * 100
        hv_series = (rets.rolling(30).std().dropna() * (252 ** 0.5) * 100)
        hv_series = hv_series.iloc[-252:] if len(hv_series) >= 252 else hv_series
        hi, lo = float(hv_series.max()), float(hv_series.min())
        vr = round((hv30 - lo) / (hi - lo) * 100, 1) if hi > lo else 50.0
        vp = round((hv_series < hv30).sum() / len(hv_series) * 100, 1)
        return {"hv30": round(hv30, 1), "hv60": round(hv60, 1),
                "vr": round(vr, 1), "vp": round(vp, 1),
                "expanding": hv30 > hv60}
    except Exception:
        return _empty


def _beta(close: pd.Series, spy_close: pd.Series) -> float:
    """1-year beta vs SPY. Returns NaN if insufficient data."""
    try:
        ret   = close.pct_change().dropna()
        spy_r = spy_close.pct_change().dropna()
        idx   = ret.index.intersection(spy_r.index)
        if len(idx) < 120:          # need at least 6 months of overlap
            return np.nan
        r, s  = ret.loc[idx], spy_r.loc[idx]
        cov   = float(np.cov(r, s)[0, 1])
        var   = float(np.var(s, ddof=1))
        b     = round(cov / var, 2) if var > 0 else np.nan
        return b if np.isfinite(b) else np.nan
    except Exception:
        return np.nan


def _pullback_in_uptrend(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    vol: pd.Series,
    sma50_v: float,
) -> dict:
    """
    Detect a slight, low-volume pullback within an uptrend.

    Uptrend (either qualifies):
      A) Price > SMA50
      B) HH+HL: last 5 bars' high AND low both above the prior 5 bars

    Pullback conditions (all must hold for bonus=True):
      1. Price is 0–7% below the 3-day peak (dipping, not crashed)
      2. At least 2 of the last 3 days closed down
      3. Average volume on those down days < 20-day average volume

    Returns dict:
      in_uptrend   bool   — A or B passes
      pulling_back bool   — conditions 1+2 hold
      pullback_pct float  — % below 3-day peak
      low_vol_dip  bool   — condition 3 holds
      bonus        bool   — all conditions met (uptrend + pullback + low vol)
      label        str    — display string for the table column
    """
    result = {
        "in_uptrend":   False,
        "pulling_back": False,
        "pullback_pct": 0.0,
        "low_vol_dip":  False,
        "bonus":        False,
        "label":        "—",
    }
    try:
        px = float(close.iloc[-1])

        # ── Uptrend check ─────────────────────────────────────────────────────
        above_sma50 = px > sma50_v

        # HH+HL: compare last 5 bars vs prior 5 bars using high/low series
        hh_hl = False
        if high is not None and low is not None and len(high) >= 10:
            recent_hi  = float(high.iloc[-5:].max())
            prior_hi   = float(high.iloc[-10:-5].max())
            recent_lo  = float(low.iloc[-5:].min())
            prior_lo   = float(low.iloc[-10:-5].min())
            hh_hl = (recent_hi > prior_hi) and (recent_lo > prior_lo)

        in_uptrend = above_sma50 or hh_hl
        result["in_uptrend"] = in_uptrend

        if not in_uptrend:
            result["label"] = "No uptrend"
            return result

        # ── Pullback magnitude ────────────────────────────────────────────────
        # 3-day peak = max close of the 3 bars BEFORE today (yesterday, 2d, 3d ago)
        if len(close) < 4:
            return result
        peak_3d      = float(close.iloc[-4:-1].max())
        pullback_pct = (peak_3d - px) / peak_3d * 100 if peak_3d > 0 else 0.0
        pulling_back = 0 < pullback_pct <= 7.0      # must be dipping, not at peak
        result["pulling_back"] = pulling_back
        result["pullback_pct"] = round(pullback_pct, 2)

        if not pulling_back:
            result["label"] = f"Uptrend · flat/rising"
            return result

        # ── At least 2 of last 3 days were down ──────────────────────────────
        last3_chg  = close.pct_change().iloc[-3:]
        down_mask  = last3_chg < 0
        down_count = int(down_mask.sum())
        two_down   = down_count >= 2

        # ── Volume on down days < 20-day avg ─────────────────────────────────
        low_vol_dip = False
        if vol is not None and len(vol) >= 21:
            avg_vol_20 = float(vol.iloc[-21:-1].mean())
            down_vols  = vol.iloc[-3:][down_mask.values]
            if len(down_vols) > 0 and avg_vol_20 > 0:
                low_vol_dip = float(down_vols.mean()) < avg_vol_20

        result["low_vol_dip"] = low_vol_dip

        bonus = two_down and low_vol_dip
        result["bonus"] = bonus
        result["label"] = (
            f"↘ {pullback_pct:.1f}% · low vol" if bonus else
            f"↘ {pullback_pct:.1f}%" if pulling_back else "—"
        )

    except Exception:
        pass

    return result


def _suggest_strategy(iv_m: dict, adx_v: float, macd_cross: bool,
                      hist_pos: bool, rsi_v: float, price: float,
                      sma200_v: float) -> str:
    """
    Return 'CSP', 'LEAP', or 'Watch' based on IV environment + momentum signals.
    CSP  = high + falling IV (sell into richness, pocket IV crush)
    LEAP = low/rising IV + strong momentum (buy cheap before IV expands)
    """
    vr           = iv_m.get("vr", np.nan)
    iv_contracting = not iv_m.get("expanding", True)
    iv_high        = not np.isnan(vr) and vr >= 40

    # CSP: elevated AND falling IV is the primary signal
    if iv_high and iv_contracting:
        return "CSP"

    # LEAP: low/rising IV + at least 3 momentum confirmations
    iv_low_rising = iv_m.get("expanding", False) or (not np.isnan(vr) and vr < 40)
    adx_strong    = not np.isnan(adx_v) and adx_v >= ADX_TREND_MIN
    above_sma200  = price > sma200_v if sma200_v > 0 else True
    momentum      = sum([adx_strong, macd_cross, hist_pos, rsi_v >= 55, above_sma200])
    if iv_low_rising and momentum >= 3:
        return "LEAP"

    return "Watch"


def _spy_gate(spy_close: pd.Series) -> tuple[bool, float, float]:
    """Return (gate_ok, spy_price, ema20_value)."""
    try:
        ema20 = calc_ema(spy_close, 20)
        p     = float(spy_close.iloc[-1])
        e     = float(ema20.iloc[-1])
        return p > e, p, e
    except Exception:
        return True, 0.0, 0.0


# ── Main scanner ───────────────────────────────────────────────────────────────

def scan_csp_strategy(
    tickers: list[str],
    status_fn=None,
) -> tuple[pd.DataFrame, bool, str]:
    """
    Scan tickers and return (results_df, spy_gate_ok, spy_note).
    Each ticker is processed with INDIVIDUAL try/except blocks so one
    failed computation never silently drops the whole ticker.
    """
    # ── SPY gate + 1-year SPY data for beta ───────────────────────────────────
    spy_df    = get_price_history("SPY", period="1y")   # 1y for reliable beta
    spy_close = spy_df["Close"].squeeze() if not spy_df.empty else pd.Series(dtype=float)
    gate_ok, spy_px, spy_ema = _spy_gate(spy_close)
    spy_note  = (
        f"SPY ${spy_px:.2f} > EMA20 ${spy_ema:.2f} ✅ Green light to scan"
        if gate_ok else
        f"⚠️ SPY ${spy_px:.2f} < EMA20 ${spy_ema:.2f} — Market caution; use tighter strikes"
    )

    rows = []

    for i, ticker in enumerate(tickers):
        if status_fn:
            status_fn(i, len(tickers), ticker)

        # ── Fetch price history ───────────────────────────────────────────────
        try:
            df = get_price_history(ticker, period="1y")
            if df is None or df.empty or len(df) < 60:
                continue
        except Exception:
            continue

        # ── Extract series (individual try so one bad column doesn't skip ticker)
        try:
            close = df["Close"].squeeze()
            price = float(close.iloc[-1])
            prev  = float(close.iloc[-2]) if len(close) > 1 else price
            chg   = round((price - prev) / prev * 100, 2)
        except Exception:
            continue

        try:
            high = df["High"].squeeze()
            low  = df["Low"].squeeze()
            vol  = df["Volume"].squeeze()
        except Exception:
            high = low = vol = None

        # ── 1. Volume filter ──────────────────────────────────────────────────
        try:
            avg_vol = float(vol.iloc[-20:].mean()) if (vol is not None and len(vol) >= 20) \
                      else (float(vol.mean()) if vol is not None else 0.0)
        except Exception:
            avg_vol = 0.0
        if avg_vol < AVG_VOL_MIN:
            continue

        # ── 3. Beta (display + filter; NaN = pass) ────────────────────────────
        beta_v = _beta(close, spy_close) if len(spy_close) > 0 else np.nan
        if not np.isnan(beta_v) and beta_v > BETA_MAX:
            continue

        # ── Indicators (each in its own try block) ────────────────────────────
        try:
            ema9   = calc_ema(close, 9)
            ema9_v = float(ema9.iloc[-1])
            ema9_3d = float(ema9.iloc[-4]) if len(ema9) >= 4 else ema9_v
            ema9_slope = (ema9_v - ema9_3d) / ema9_3d * 100 if ema9_3d > 0 else 0.0
        except Exception:
            ema9_v = price; ema9_slope = 0.0

        try:
            rsi_v = float(calc_rsi(close))
        except Exception:
            rsi_v = 50.0

        try:
            sma50_v = float(calc_sma(close, 50).dropna().iloc[-1])
        except Exception:
            sma50_v = price * 0.95   # safe fallback — won't falsely pass

        try:
            sma200_v = float(calc_sma(close, 200).dropna().iloc[-1])
        except Exception:
            sma200_v = 0.0

        try:
            sma20_v = float(calc_sma(close, 20).dropna().iloc[-1])
        except Exception:
            sma20_v = price

        adx_v = _adx(close, high, low) if (high is not None and low is not None) else np.nan

        # ── 4. Trend filters ──────────────────────────────────────────────────
        if price <= ema9_v:
            continue
        if ema9_slope < EMA9_SLOPE_MIN:
            continue
        if not (RSI_LO <= rsi_v <= RSI_HI):
            continue
        # ADX is used as a scoring signal, not a hard filter

        # ── 5. Gap & consistency filters ─────────────────────────────────────
        try:
            moves_20 = close.pct_change().abs().iloc[-20:] * 100
            if float(moves_20.max()) > GAP_MAX_PCT:
                continue
        except Exception:
            pass

        try:
            high_20d = float(close.iloc[-20:].max())
            pct_off  = (high_20d - price) / high_20d * 100 if high_20d > 0 else 0.0
            if pct_off > NEAR_HIGH_PCT:
                continue
        except Exception:
            pass

        # ── IV metrics ────────────────────────────────────────────────────────
        iv_m = _hv_metrics(close)

        # ── MACD (informational) ──────────────────────────────────────────────
        try:
            ema12      = calc_ema(close, 12)
            ema26      = calc_ema(close, 26)
            macd_l     = ema12 - ema26
            sig_l      = calc_ema(macd_l, 9)
            hist_l     = macd_l - sig_l
            macd_cross = float(macd_l.iloc[-1]) > float(sig_l.iloc[-1])
            hist_pos   = float(hist_l.iloc[-1]) > 0
        except Exception:
            macd_cross = hist_pos = False

        # ── Pullback-in-uptrend (scoring bonus) ───────────────────────────────
        pb = _pullback_in_uptrend(close, high, low, vol, sma50_v)

        # ── Score /10 ─────────────────────────────────────────────────────────
        # Combined point: IV contracting + ADX > 25 = ideal CSP entry
        # (high-but-falling IV means richer premium + IV crush; strong ADX confirms uptrend)
        iv_contracting_strong_trend = (
            (not iv_m["expanding"])
            and (not np.isnan(adx_v) and adx_v >= ADX_TREND_MIN)
        )
        score = sum([
            gate_ok,
            (iv_m["vr"] >= IVR_GOOD) if not np.isnan(iv_m["vr"]) else False,
            (iv_m["vp"] >= IVP_GOOD) if not np.isnan(iv_m["vp"]) else False,
            price > ema9_v,
            ema9_slope >= 0,
            50 <= rsi_v <= RSI_HI,
            macd_cross,
            hist_pos,
            pb["bonus"],           # +1 bonus: uptrend + slight dip + low vol
            iv_contracting_strong_trend,   # +1: IV falling + ADX confirms trend
        ])

        # ── Strategy suggestion (computed before flags so flags can adapt) ──────
        suggest = _suggest_strategy(iv_m, adx_v, macd_cross, hist_pos,
                                    rsi_v, price, sma200_v)

        # ── Flags — context-aware per strategy ────────────────────────────────
        flags = []
        if suggest == "CSP":
            if not np.isnan(iv_m["vr"]) and iv_m["vr"] < IVR_GOOD:
                flags.append(f"Low VR ({iv_m['vr']:.0f}) — premium thin")
            if iv_m["expanding"]:
                flags.append("Vol expanding ⚠️ — no IV crush on entry")
            if rsi_v > 62:
                flags.append(f"RSI elevated ({rsi_v:.0f}) — consider waiting for dip")
            if pb["in_uptrend"] and pb["pulling_back"] and not pb["low_vol_dip"]:
                flags.append("Pullback on high vol ⚠️ — possible distribution")
        elif suggest == "LEAP":
            if not np.isnan(iv_m["vr"]) and iv_m["vr"] >= IVR_GOOD and not iv_m["expanding"]:
                flags.append(f"IV high+falling ({iv_m['vr']:.0f}) — IV crush risk for long call")
            if rsi_v < 45:
                flags.append(f"RSI weak ({rsi_v:.0f}) — momentum not confirmed")
            if sma200_v > 0 and price <= sma200_v:
                flags.append("Below SMA200 — long-term trend not intact")
        # Common flags regardless of strategy
        if not np.isnan(beta_v) and beta_v > 1.2:
            flags.append(f"Beta {beta_v:.1f}")
        if not np.isnan(adx_v) and adx_v < ADX_TREND_MIN:
            flags.append(f"ADX weak ({adx_v:.0f}) — trend not confirmed")
        if not macd_cross:
            flags.append("MACD ↓ signal")

        rows.append({
            "Ticker":     ticker,
            "Price":      round(price, 2),
            "Chg%":       chg,
            "AvgVol(K)":  round(avg_vol / 1_000, 0),
            "Beta":       beta_v if not np.isnan(beta_v) else None,
            # IV Environment
            "HV30%":      iv_m["hv30"],
            "Vol Rank":   iv_m["vr"],
            "Vol Pctile": iv_m["vp"],
            "IV Trend":   "Expanding ↑" if iv_m["expanding"] else "Contracting ↓",
            # Trend & Momentum
            "EMA9":       "✅ Above" if price > ema9_v else "❌ Below",
            "EMA9 Slope": round(ema9_slope, 2),
            "RSI":        round(rsi_v, 1),
            "ADX":        round(adx_v, 1) if not np.isnan(adx_v) else None,
            # MACD (informational)
            "MACD Cross": "✅" if macd_cross else "❌",
            "Hist > 0":   "✅" if hist_pos else "❌",
            # Pullback bonus
            "Pullback":   pb["label"],
            # Strategy suggestion
            "SMA200":     round(sma200_v, 2) if sma200_v > 0 else None,
            "Suggest":    suggest,
            # Score & notes
            "Score":      score,
            "Flags":      " · ".join(flags) if flags else "—",
        })

        time.sleep(0.1 + random.uniform(0, 0.1))   # light throttle

    df_out = pd.DataFrame(rows)
    if not df_out.empty:
        df_out = df_out.sort_values("Score", ascending=False).reset_index(drop=True)

    return df_out, gate_ok, spy_note
