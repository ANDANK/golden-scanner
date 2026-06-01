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
    base = list(dict.fromkeys(SP500_SAMPLE[:100] + OPTIONS_ETF_UNIVERSE))
    return base

# ── Filters (hard gates — stock excluded if it fails) ─────────────────────────
PRICE_MIN       = 15.0
AVG_VOL_MIN     = 300_000
BETA_MAX        = 1.5
EARNINGS_DAYS   = 14
RSI_LO          = 35
RSI_HI          = 68
ADX_MAX         = 30
GAP_MAX_PCT     = 7.0       # max single-day move allowed in last 20 sessions
NEAR_HIGH_PCT   = 7.0       # price must be within X% of 20-day high
EMA9_SLOPE_MIN  = -0.05     # EMA9 slope (% change over 3 days) — allow slightly negative

# ── IV thresholds (display / flag, not filter) ────────────────────────────────
IVR_GOOD        = 30        # VR ≥ this = premium elevated
IVP_GOOD        = 40        # VP ≥ this = historically rich

# ── Helpers ────────────────────────────────────────────────────────────────────

def _adx(df: pd.DataFrame, period: int = 14) -> float:
    """14-period ADX from OHLC DataFrame with Close/High/Low columns."""
    try:
        hi = df["High"].squeeze()
        lo = df["Low"].squeeze()
        cl = df["Close"].squeeze()
        if len(cl) < period + 5:
            return np.nan
        prev_cl = cl.shift(1)
        tr = pd.concat([
            hi - lo,
            (hi - prev_cl).abs(),
            (lo - prev_cl).abs(),
        ], axis=1).max(axis=1)
        atr = tr.ewm(com=period - 1, adjust=False).mean()

        up   = hi.diff()
        down = -lo.diff()
        pdm  = up.where((up > down) & (up > 0), 0.0)
        ndm  = down.where((down > up) & (down > 0), 0.0)
        pdi  = 100 * pdm.ewm(com=period - 1, adjust=False).mean() / atr.replace(0, np.nan)
        ndi  = 100 * ndm.ewm(com=period - 1, adjust=False).mean() / atr.replace(0, np.nan)
        dx   = (100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)).fillna(0)
        adx_s = dx.ewm(com=period - 1, adjust=False).mean()
        return float(adx_s.dropna().iloc[-1])
    except Exception:
        return np.nan


def _hv_metrics(close: pd.Series) -> dict:
    """
    Compute realized-vol metrics used as IV proxy:
      hv30  : annualised 30-day realized vol (current)
      hv60  : annualised 60-day realized vol (trend reference)
      vr    : vol rank — where hv30 sits in its 252-day range (0-100)
      vp    : vol percentile — % of past year where hv30 was below current
      expanding : True if hv30 > hv60 (vol expanding)
    """
    if len(close) < 65:
        return {"hv30": np.nan, "hv60": np.nan, "vr": np.nan,
                "vp": np.nan, "expanding": False}
    rets   = close.pct_change().dropna()
    hv30   = float(rets.rolling(30).std().dropna().iloc[-1]) * (252 ** 0.5) * 100
    hv60   = float(rets.rolling(60).std().dropna().iloc[-1]) * (252 ** 0.5) * 100

    # rolling HV30 series for rank / percentile
    hv_series = (rets.rolling(30).std().dropna() * (252 ** 0.5) * 100)
    hv_series = hv_series.iloc[-252:] if len(hv_series) >= 252 else hv_series
    hi, lo    = float(hv_series.max()), float(hv_series.min())
    vr = round((hv30 - lo) / (hi - lo) * 100, 1) if hi > lo else 50.0
    vp = round((hv_series < hv30).sum() / len(hv_series) * 100, 1)
    return {
        "hv30":      round(hv30, 1),
        "hv60":      round(hv60, 1),
        "vr":        round(vr, 1),
        "vp":        round(vp, 1),
        "expanding": hv30 > hv60,
    }


def _beta(close: pd.Series, spy_close: pd.Series) -> float:
    """Rolling 1-year beta vs SPY."""
    try:
        ret    = close.pct_change().dropna()
        spy_r  = spy_close.pct_change().dropna()
        idx    = ret.index.intersection(spy_r.index)[-252:]
        if len(idx) < 60:
            return np.nan
        r, s   = ret.loc[idx], spy_r.loc[idx]
        cov    = float(np.cov(r, s)[0, 1])
        var    = float(np.var(s, ddof=1))
        return round(cov / var, 2) if var > 0 else np.nan
    except Exception:
        return np.nan


def _earnings_days(ticker: str) -> int | None:
    """Return days to next earnings, or None if unknown/unavailable."""
    try:
        t   = yf.Ticker(ticker)
        cal = t.calendar
        if cal is None or cal.empty:
            return None
        # calendar columns vary by yfinance version
        for col in ("Earnings Date", "earningsDate"):
            if col in cal.columns:
                dates = pd.to_datetime(cal[col].dropna().values)
                if len(dates) == 0:
                    return None
                nearest = min(dates, key=lambda d: abs((d - pd.Timestamp.now()).days))
                return max(0, (nearest - pd.Timestamp.now()).days)
        return None
    except Exception:
        return None


def _spy_gate(spy_close: pd.Series) -> bool:
    """Return True if SPY is above its 20-day EMA."""
    ema20 = calc_ema(spy_close, 20)
    return float(spy_close.iloc[-1]) > float(ema20.iloc[-1])


# ── Main scanner ───────────────────────────────────────────────────────────────

def scan_csp_strategy(
    tickers: list[str],
    status_fn=None,        # callable(i, n, ticker) for progress updates
) -> tuple[pd.DataFrame, bool, str]:
    """
    Scan tickers and return (results_df, spy_gate_ok, spy_note).
    results_df contains all stocks that pass the hard filters, sorted by Score desc.
    """
    # ── SPY gate ──────────────────────────────────────────────────
    spy_df      = get_price_history("SPY", period="3mo")
    spy_close   = spy_df["Close"].squeeze() if not spy_df.empty else pd.Series(dtype=float)
    spy_gate_ok = _spy_gate(spy_close) if len(spy_close) > 20 else True
    ema20_spy   = float(calc_ema(spy_close, 20).iloc[-1]) if len(spy_close) > 20 else 0
    spy_price   = float(spy_close.iloc[-1]) if len(spy_close) else 0
    spy_note    = (
        f"SPY ${spy_price:.2f} > EMA20 ${ema20_spy:.2f} ✅ Green light"
        if spy_gate_ok else
        f"⚠️ SPY ${spy_price:.2f} < EMA20 ${ema20_spy:.2f} — Market regime caution"
    )

    rows = []
    n    = len(tickers)

    for i, ticker in enumerate(tickers):
        if status_fn:
            status_fn(i, n, ticker)

        try:
            # ── Price history (6 mo → ~126 bars, enough for all indicators) ──
            df = get_price_history(ticker, period="1y")
            if df is None or df.empty or len(df) < 60:
                continue

            close  = df["Close"].squeeze()
            hi_col = df["High"].squeeze()
            lo_col = df["Low"].squeeze()
            vol    = df["Volume"].squeeze()
            price  = float(close.iloc[-1])
            prev   = float(close.iloc[-2]) if len(close) > 1 else price
            chg    = round((price - prev) / prev * 100, 2)

            # ── 1. Eligibility gates ───────────────────────────────
            if price < PRICE_MIN:
                continue

            avg_vol = float(vol.iloc[-20:].mean()) if len(vol) >= 20 else float(vol.mean())
            if avg_vol < AVG_VOL_MIN:
                continue

            beta_v = _beta(close, spy_close)
            if not np.isnan(beta_v) and beta_v > BETA_MAX:
                continue

            # ── Earnings check (non-blocking — unknown = allowed) ──
            earn_days = _earnings_days(ticker)
            if earn_days is not None and earn_days < EARNINGS_DAYS:
                continue

            # ── Indicators ─────────────────────────────────────────
            ema9    = calc_ema(close, 9)
            ema9_v  = float(ema9.iloc[-1])
            ema9_3d = float(ema9.iloc[-4]) if len(ema9) >= 4 else ema9_v
            ema9_slope_pct = (ema9_v - ema9_3d) / ema9_3d * 100 if ema9_3d > 0 else 0.0

            sma20_v  = float(calc_sma(close, 20).iloc[-1])
            rsi_v    = float(calc_rsi(close).dropna().iloc[-1])

            adx_v = _adx(df)

            # ── 2. Trend & momentum filters ────────────────────────
            if price <= ema9_v:                        # must be above EMA9
                continue
            if ema9_slope_pct < EMA9_SLOPE_MIN:        # EMA9 rolling over
                continue
            if not (RSI_LO <= rsi_v <= RSI_HI):
                continue
            if not np.isnan(adx_v) and adx_v > ADX_MAX:
                continue

            # ── 3. Gap & consistency ───────────────────────────────
            if len(close) >= 21:
                moves_20 = (close.pct_change().abs().iloc[-20:] * 100)
                if float(moves_20.max()) > GAP_MAX_PCT:
                    continue
            high_20d = float(close.iloc[-20:].max()) if len(close) >= 20 else price
            if (high_20d - price) / high_20d * 100 > NEAR_HIGH_PCT:
                continue

            # ── IV environment (realized vol proxies) ──────────────
            iv_m = _hv_metrics(close)

            # ── MACD (informational) ───────────────────────────────
            ema12   = calc_ema(close, 12)
            ema26   = calc_ema(close, 26)
            macd_l  = ema12 - ema26
            sig_l   = calc_ema(macd_l, 9)
            hist_l  = macd_l - sig_l
            macd_cross = float(macd_l.iloc[-1]) > float(sig_l.iloc[-1])
            hist_pos   = float(hist_l.iloc[-1]) > 0

            # ── Score (conditions favouring CSP entry) ─────────────
            score_items = [
                spy_gate_ok,
                iv_m["vr"] >= IVR_GOOD    if not np.isnan(iv_m["vr"]) else False,
                iv_m["vp"] >= IVP_GOOD    if not np.isnan(iv_m["vp"]) else False,
                iv_m["expanding"],
                price > ema9_v,
                ema9_slope_pct >= 0,
                50 <= rsi_v <= RSI_HI,    # bonus for golden RSI zone
                not np.isnan(adx_v) and adx_v < 20,  # very stable = best for CSP
                macd_cross,
                hist_pos,
            ]
            score = sum(score_items)

            # ── Flags ──────────────────────────────────────────────
            flags = []
            if earn_days is None:
                flags.append("Earnings unknown")
            elif earn_days <= 21:
                flags.append(f"Earnings in {earn_days}d")
            if iv_m["vr"] < IVR_GOOD and not np.isnan(iv_m["vr"]):
                flags.append(f"Low Vol Rank ({iv_m['vr']:.0f})")
            if rsi_v > 60:
                flags.append(f"RSI elevated ({rsi_v:.0f})")
            if np.isnan(beta_v):
                flags.append("Beta unavailable")
            elif beta_v > 1.2:
                flags.append(f"High Beta ({beta_v:.1f})")
            if not iv_m["expanding"]:
                flags.append("Vol contracting")
            if not macd_cross:
                flags.append("MACD below signal")

            rows.append({
                "Ticker":       ticker,
                "Price":        round(price, 2),
                "Chg%":         chg,
                "Avg Vol":      round(avg_vol / 1_000, 0),   # in K
                "Beta":         beta_v if not np.isnan(beta_v) else None,
                # IV Environment
                "HV30%":        iv_m["hv30"],
                "Vol Rank":     iv_m["vr"],
                "Vol Pctile":   iv_m["vp"],
                "IV Trend":     "Expanding ↑" if iv_m["expanding"] else "Contracting ↓",
                # Trend & Momentum
                "EMA9":         "✅ Above" if price > ema9_v else "❌ Below",
                "EMA9 Slope":   round(ema9_slope_pct, 2),
                "RSI":          round(rsi_v, 1),
                "ADX":          round(adx_v, 1) if not np.isnan(adx_v) else None,
                # MACD (informational)
                "MACD Cross":   "✅" if macd_cross else "❌",
                "Hist > 0":     "✅" if hist_pos else "❌",
                # Sort & notes
                "Score":        score,
                "Flags":        " · ".join(flags) if flags else "—",
            })

        except Exception:
            continue

        # Light throttle to avoid yfinance hammering
        time.sleep(0.3 + random.uniform(0, 0.2))

    df_out = pd.DataFrame(rows)
    if not df_out.empty:
        df_out = df_out.sort_values("Score", ascending=False).reset_index(drop=True)

    return df_out, spy_gate_ok, spy_note
