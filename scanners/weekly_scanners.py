# scanners/weekly_scanners.py
# ─────────────────────────────────────────────────────────────────
# Three weekly-chart setups used inside Golden Scan:
#
#   Setup 1 — Trend Alignment     : Daily MACD cross + weekly MA + ADX
#   Setup 2 — Trend Continuation  : Institutional momentum on weekly chart
#   Setup 3 — Momentum Reset Bounce: Pullback-to-EMA re-entry on weekly chart
#
# Weekly data is fetched via yfinance (interval="1wk") and cached at
# both the Streamlit-session level (@st.cache_data) and a module-level
# dict so headless / GitHub-Actions runs never re-fetch the same ticker
# across multiple scanners in a single process.
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *
from utils import calc_ema, calc_sma, calc_rsi

# ── Process-level weekly-data cache (survives across scanner calls) ──
_WK_CACHE: dict[str, pd.DataFrame] = {}


# ══════════════════════════════════════════════════════════════════
# 1. DATA HELPERS
# ══════════════════════════════════════════════════════════════════

@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_weekly_raw(ticker: str, years: int) -> pd.DataFrame:
    """yfinance weekly bars — Streamlit-session cached."""
    try:
        import yfinance as yf
        df = yf.download(ticker, period=f"{years}y", interval="1wk",
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df.dropna(subset=["Close"])
    except Exception:
        return pd.DataFrame()


def _get_weekly(ticker: str, years: int = 3) -> pd.DataFrame:
    """Process-level cache → Streamlit cache.  Never fetches twice per run."""
    key = f"{ticker}_{years}"
    if key not in _WK_CACHE:
        _WK_CACHE[key] = _fetch_weekly_raw(ticker, years)
    return _WK_CACHE[key]


def _get_weekly_spy() -> pd.DataFrame:
    return _get_weekly("SPY", years=3)


def clear_weekly_cache():
    """Call between runs if you want fresh data."""
    _WK_CACHE.clear()


def prefetch_weekly(tickers: list, years: int = 3) -> int:
    """
    Batch-download weekly bars for all tickers in ONE yf.download() call and
    populate _WK_CACHE.  Turns 200 sequential weekly API calls → 1 bulk call.

    Called from combined_scanner.run_combined() before the weekly scanners run.
    Already-cached tickers are skipped automatically.

    Returns the number of tickers successfully cached.
    """
    import yfinance as yf

    missing = [t for t in tickers if f"{t}_{years}" not in _WK_CACHE]
    if not missing:
        return 0

    try:
        raw = yf.download(
            missing,
            period=f"{years}y",
            interval="1wk",
            auto_adjust=True,
            progress=False,
            group_by="ticker",
        )
    except Exception:
        return 0

    if raw is None or raw.empty:
        return 0

    filled = 0
    for ticker in missing:
        cache_key = f"{ticker}_{years}"
        if cache_key in _WK_CACHE:
            continue
        try:
            if len(missing) == 1:
                df = raw.copy()
            else:
                if ticker not in raw.columns.get_level_values(0):
                    continue
                df = raw[ticker].copy()

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna(subset=["Close"])
            if df.empty:
                continue

            _WK_CACHE[cache_key] = df
            filled += 1
        except Exception:
            continue

    return filled


# ══════════════════════════════════════════════════════════════════
# 2. INDICATOR HELPERS
# ══════════════════════════════════════════════════════════════════

def calc_adx(df: pd.DataFrame, period: int = 14) -> float:
    """
    Average Directional Index — measures trend STRENGTH (not direction).
    > 20 = trend present.  > 30 = strong trend.
    Uses Wilder's EWM smoothing (alpha = 1/period).
    """
    try:
        hi    = df["High"].squeeze()
        lo    = df["Low"].squeeze()
        cl    = df["Close"].squeeze()
        if len(cl) < period * 2 + 5:
            return 0.0

        prev_cl = cl.shift(1)
        tr = pd.concat([
            hi - lo,
            (hi - prev_cl).abs(),
            (lo - prev_cl).abs(),
        ], axis=1).max(axis=1)

        up   = hi - hi.shift(1)
        dn   = lo.shift(1) - lo
        dm_p = up.where((up > dn) & (up > 0), 0.0)
        dm_m = dn.where((dn > up) & (dn > 0), 0.0)

        a = 1.0 / period
        atr_w  = tr.ewm(alpha=a, adjust=False).mean()
        dmp_w  = dm_p.ewm(alpha=a, adjust=False).mean()
        dmm_w  = dm_m.ewm(alpha=a, adjust=False).mean()

        di_p  = 100 * dmp_w / atr_w.replace(0, np.nan)
        di_m  = 100 * dmm_w / atr_w.replace(0, np.nan)
        dx    = 100 * (di_p - di_m).abs() / (di_p + di_m).replace(0, np.nan)
        adx   = dx.ewm(alpha=a, adjust=False).mean().dropna()

        return round(float(adx.iloc[-1]), 1) if not adx.empty else 0.0
    except Exception:
        return 0.0


def _ma_rising(series: pd.Series, lookback: int = 4) -> bool:
    """True if MA is higher than it was `lookback` bars ago."""
    try:
        return len(series) > lookback and float(series.iloc[-1]) > float(series.iloc[-1 - lookback])
    except Exception:
        return False


def _weekly_rsi(close_wk: pd.Series) -> float:
    return calc_rsi(close_wk, period=14)


def _weekly_macd_hist(close_wk: pd.Series) -> tuple[float, float]:
    """Returns (hist_prev, hist_current) for weekly MACD."""
    try:
        ema12 = calc_ema(close_wk, 12)
        ema26 = calc_ema(close_wk, 26)
        macd  = ema12 - ema26
        sig   = calc_ema(macd, 9)
        hist  = macd - sig
        if len(hist.dropna()) < 2:
            return 0.0, 0.0
        return float(hist.iloc[-2]), float(hist.iloc[-1])
    except Exception:
        return 0.0, 0.0


def _weekly_vol_ratio(df_wk: pd.DataFrame, lookback: int = 20) -> float:
    try:
        vol = df_wk["Volume"].squeeze()
        avg = float(vol.iloc[-lookback - 1:-1].mean())
        return round(float(vol.iloc[-1]) / avg, 2) if avg > 0 else 0.0
    except Exception:
        return 0.0


def _weekly_rs(close_wk: pd.Series, spy_close: pd.Series,
               lookback: int = 26) -> float:
    """26-week return ratio: ticker vs SPY.  > 1.0 = outperforming."""
    try:
        n = min(len(close_wk), len(spy_close))
        if n < lookback + 1:
            return 1.0
        t = float(close_wk.iloc[-1] / close_wk.iloc[-lookback])
        s = float(spy_close.iloc[-1] / spy_close.iloc[-lookback])
        return round(t / s, 3) if s > 0 else 1.0
    except Exception:
        return 1.0


def _rs_at_new_high(close_wk: pd.Series, spy_close: pd.Series,
                    lookback: int = 26, window: int = 26) -> bool:
    """True if current RS ratio is at or near its highest level in last `window` bars."""
    try:
        n  = min(len(close_wk), len(spy_close))
        rs_list = []
        for i in range(lookback, n):
            t = close_wk.iloc[i] / close_wk.iloc[i - lookback]
            s = spy_close.iloc[i]  / spy_close.iloc[i - lookback]
            rs_list.append(t / s if s > 0 else 1.0)
        if len(rs_list) < window:
            return False
        recent = rs_list[-window:]
        return recent[-1] >= max(recent) * 0.97
    except Exception:
        return False


def _price_breaks_weekly_resist(df_wk: pd.DataFrame, weeks: int = 8) -> bool:
    """Current close > highest close of prior `weeks` weekly bars."""
    try:
        cl = df_wk["Close"].squeeze()
        if len(cl) < weeks + 2:
            return False
        return float(cl.iloc[-1]) > float(cl.iloc[-weeks - 1:-1].max())
    except Exception:
        return False


def _consolidation_breakout(df_wk: pd.DataFrame,
                             min_wk: int = 8, max_wk: int = 20,
                             max_range_pct: float = 0.15) -> bool:
    """
    8–20 week base (range ≤ max_range_pct%) followed by current close
    breaking above the base high.
    """
    try:
        cl = df_wk["Close"].squeeze()
        if len(cl) < max_wk + 2:
            return False
        window = cl.iloc[-max_wk - 1:-1]
        hi = float(window.max())
        lo = float(window.min())
        if lo <= 0 or (hi - lo) / lo > max_range_pct:
            return False
        return float(cl.iloc[-1]) > hi
    except Exception:
        return False


def _close_near_weekly_high(df_wk: pd.DataFrame, pct: float = 0.04) -> bool:
    """Weekly close ≥ (1 – pct) × weekly high."""
    try:
        cl = float(df_wk["Close"].iloc[-1])
        hi = float(df_wk["High"].iloc[-1])
        return cl >= hi * (1 - pct)
    except Exception:
        return False


def _pullback_to_ema(df_wk: pd.DataFrame,
                     ema10: pd.Series, ema21: pd.Series,
                     tol: float = 0.04) -> tuple[bool, bool]:
    """
    Returns (touch_10, touch_21).
    "Touch" = weekly LOW came within tol% of the EMA level
    AND weekly CLOSE is still above or at the EMA (not fallen through).
    """
    try:
        cl  = float(df_wk["Close"].iloc[-1])
        lo  = float(df_wk["Low"].iloc[-1])
        e10 = float(ema10.iloc[-1])
        e21 = float(ema21.iloc[-1])
        t10 = (lo <= e10 * (1 + tol)) and (cl >= e10 * (1 - tol))
        t21 = (lo <= e21 * (1 + tol)) and (cl >= e21 * (1 - tol))
        return t10, t21
    except Exception:
        return False, False


def _bullish_reversal_candle(df_wk: pd.DataFrame) -> bool:
    """
    Weekly bullish reversal: close > open AND close in upper 60% of the week's range.
    """
    try:
        o = float(df_wk["Open"].iloc[-1])
        c = float(df_wk["Close"].iloc[-1])
        h = float(df_wk["High"].iloc[-1])
        l = float(df_wk["Low"].iloc[-1])
        if h == l:
            return False
        return (c > o) and ((c - l) / (h - l) >= 0.60)
    except Exception:
        return False


def _earnings_within(ticker: str, days: int = 14) -> bool:
    """True if next earnings date is within `days` from today."""
    try:
        from data_loader import get_info
        info = get_info(ticker)
        raw  = info.get("earningsTimestamp") or info.get("nextEarningsDate")
        if not raw:
            return False
        if isinstance(raw, (int, float)):
            earn = datetime.utcfromtimestamp(int(raw)).date()
        else:
            earn = datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
        return 0 <= (earn - datetime.utcnow().date()).days <= days
    except Exception:
        return False  # safe default: don't skip if we can't check


# ══════════════════════════════════════════════════════════════════
# SETUP 1 — TREND ALIGNMENT
# ══════════════════════════════════════════════════════════════════

def scan_trend_alignment(tickers: list,
                          price_min: float = 5.0,
                          price_max: float = 5000.0,
                          skip_earnings: bool = True,
                          status_ph=None) -> pd.DataFrame:
    """
    All conditions required:
      • Daily MACD line crosses above signal (histogram −→ +, fresh cross)
      • Daily RSI 55–70 (momentum sweet spot, not extended)
      • ADX > 20 on daily chart (confirmed trend strength)
      • Price breaks weekly resistance (8-week closing high)
      • Volume expansion on breakout week (≥ 1.2× avg)
      • Price above RISING 30-week SMA (no declining trend)
      • Minimum daily average volume > 200k (liquidity)
      • No earnings within 14 days (optional)
    Avoid: RSI > 78, declining 30-week MA, low-liquidity stocks.
    """
    from data_loader import get_price_history

    results   = []
    spy_wk    = _get_weekly_spy()
    spy_close = spy_wk["Close"].squeeze() if not spy_wk.empty else pd.Series()

    for ticker in tickers:
        if status_ph:
            status_ph.markdown(
                f'<div style="color:{TEXT_MUTED};font-size:12px;margin:2px 0">'
                f'Trend Alignment · {ticker}…</div>',
                unsafe_allow_html=True,
            )
        try:
            # ── Daily data ────────────────────────────────────────
            df_d   = get_price_history(ticker, period="1y")
            if df_d.empty or len(df_d) < 60:
                continue
            close_d = df_d["Close"].squeeze()
            vol_d   = df_d["Volume"].squeeze()
            price   = float(close_d.iloc[-1])
            if not (price_min <= price <= price_max):
                continue

            # Liquidity gate — skip very thinly traded stocks
            avg_vol_d = float(vol_d.iloc[-21:-1].mean()) if len(vol_d) > 21 else float(vol_d.mean())
            if avg_vol_d < 200_000:
                continue

            # Daily MACD fresh cross: histogram ≤ 0 → > 0
            ema12 = calc_ema(close_d, 12)
            ema26 = calc_ema(close_d, 26)
            macd_line = ema12 - ema26
            sig_line  = calc_ema(macd_line, 9)
            hist_d    = macd_line - sig_line
            if not (float(hist_d.iloc[-2]) <= 0 and float(hist_d.iloc[-1]) > 0):
                continue

            # Daily RSI 55–70; hard avoid above 78
            rsi_d = calc_rsi(close_d)
            if not (55 <= rsi_d <= 78):
                continue

            # ADX > 20 (daily)
            adx = calc_adx(df_d, period=14)
            if adx < 20:
                continue

            # ── Weekly data ───────────────────────────────────────
            df_wk = _get_weekly(ticker, years=2)
            if df_wk.empty or len(df_wk) < 35:
                continue
            close_wk = df_wk["Close"].squeeze()

            # Price above RISING 30-week SMA
            ma30w = calc_sma(close_wk, 30)
            if price < float(ma30w.iloc[-1]):
                continue
            if not _ma_rising(ma30w, lookback=4):
                continue                              # declining 30W MA → avoid

            # Weekly resistance break (8-week closing high)
            if not _price_breaks_weekly_resist(df_wk, weeks=8):
                continue

            # Earnings safety (optional — don't block if check fails)
            if skip_earnings and _earnings_within(ticker, days=14):
                continue

            # ── Scoring ───────────────────────────────────────────
            wk_vol_ratio = _weekly_vol_ratio(df_wk, lookback=20)
            rs           = _weekly_rs(close_wk, spy_close, lookback=26)

            score = 0
            score += 25                                     # fresh MACD cross (required)
            score += 15 if 55 <= rsi_d <= 65 else 8        # RSI ideal range
            score += 15 if adx >= 30 else (10 if adx >= 25 else 5)
            score += 15                                     # above rising 30W MA (required)
            score += 10 if wk_vol_ratio >= 1.5 else (6 if wk_vol_ratio >= 1.2 else 2)
            score += 10 if rs >= 1.10 else (6 if rs >= 1.0 else 2)
            score += 10                                     # weekly resistance break (required)
            score = min(score, 100)

            prev = float(close_d.iloc[-2])
            chg  = (price - prev) / prev * 100

            results.append({
                "Ticker":      ticker,
                "Price":       round(price, 2),
                "Change %":    round(chg, 2),
                "RSI":         round(rsi_d, 1),
                "ADX":         round(adx, 1),
                "Vol Ratio":   wk_vol_ratio,
                "RS vs SPY":   rs,
                ">30W MA":     "✅",
                "Wk Break":    "✅",
                "MACD Cross":  "✅",
                "Score":       score,
            })
        except Exception:
            continue

    df_out = pd.DataFrame(results)
    if not df_out.empty:
        df_out = df_out.sort_values("Score", ascending=False).reset_index(drop=True)
    return df_out


# ══════════════════════════════════════════════════════════════════
# SETUP 2 — TREND CONTINUATION
# ══════════════════════════════════════════════════════════════════

def scan_trend_continuation(tickers: list,
                             price_min: float = 5.0,
                             price_max: float = 5000.0,
                             status_ph=None) -> pd.DataFrame:
    """
    Weekly conditions — catching institutional momentum early in a longer uptrend:
      • Price above RISING 30-week SMA
      • 10-week SMA > 30-week SMA  (short-term MA above long-term)
      • Weekly RSI 60–75
      • Weekly close near candle highs (strong weekly close, ≥ 96% of week's high)
      • Breakout from 8–20 week consolidation (range ≤ 15%)
      • Volume spike ≥ 1.5× weekly average on breakout week
      • Relative Strength vs SPY at or near 26-week highs
    Minimum: consolidation breakout OR close near high must be true.
    """
    results   = []
    spy_wk    = _get_weekly_spy()
    spy_close = spy_wk["Close"].squeeze() if not spy_wk.empty else pd.Series()

    for ticker in tickers:
        if status_ph:
            status_ph.markdown(
                f'<div style="color:{TEXT_MUTED};font-size:12px;margin:2px 0">'
                f'Trend Continuation · {ticker}…</div>',
                unsafe_allow_html=True,
            )
        try:
            df_wk = _get_weekly(ticker, years=3)
            if df_wk.empty or len(df_wk) < 35:
                continue
            close_wk = df_wk["Close"].squeeze()
            price    = float(close_wk.iloc[-1])
            if not (price_min <= price <= price_max):
                continue

            # 30-week SMA: price above it AND rising
            ma30w = calc_sma(close_wk, 30)
            if price < float(ma30w.iloc[-1]):
                continue
            if not _ma_rising(ma30w, lookback=4):
                continue

            # 10-week SMA > 30-week SMA
            ma10w = calc_sma(close_wk, 10)
            if float(ma10w.iloc[-1]) <= float(ma30w.iloc[-1]):
                continue

            # Weekly RSI 60–75
            rsi_wk = _weekly_rsi(close_wk)
            if not (60 <= rsi_wk <= 75):
                continue

            # Ancillary signals
            close_near_hi  = _close_near_weekly_high(df_wk, pct=0.04)
            consol_break   = _consolidation_breakout(df_wk, min_wk=8, max_wk=20, max_range_pct=0.15)
            wk_vol_ratio   = _weekly_vol_ratio(df_wk, lookback=20)
            vol_spike      = wk_vol_ratio >= 1.5
            rs             = _weekly_rs(close_wk, spy_close, lookback=26)
            rs_new_hi      = _rs_at_new_high(close_wk, spy_close, lookback=26, window=26)

            # Minimum: at least one setup condition
            if not (consol_break or close_near_hi):
                continue

            # ── Scoring ───────────────────────────────────────────
            score = 0
            score += 20                                         # above rising 30W MA + 10W>30W (required)
            score += 15 if 62 <= rsi_wk <= 72 else 8           # RSI ideal zone
            score += 20 if consol_break else 0
            score += 10 if close_near_hi else 0
            score += 15 if vol_spike else (8 if wk_vol_ratio >= 1.2 else 2)
            score += 15 if rs_new_hi else (8 if rs >= 1.05 else 2)
            score += 5  if rs >= 1.10 else 0
            score = min(score, 100)

            prev = float(close_wk.iloc[-2]) if len(close_wk) > 1 else price
            chg  = (price - prev) / prev * 100

            results.append({
                "Ticker":       ticker,
                "Price":        round(price, 2),
                "Change %":     round(chg, 2),
                "RSI":          round(rsi_wk, 1),
                "10W SMA":      round(float(ma10w.iloc[-1]), 2),
                "30W SMA":      round(float(ma30w.iloc[-1]), 2),
                "Vol Ratio":    wk_vol_ratio,
                "RS vs SPY":    rs,
                "Consol Break": "✅" if consol_break else "—",
                "Close @ Hi":   "✅" if close_near_hi else "—",
                "RS New Hi":    "✅" if rs_new_hi else "—",
                "Score":        score,
            })
        except Exception:
            continue

    df_out = pd.DataFrame(results)
    if not df_out.empty:
        df_out = df_out.sort_values("Score", ascending=False).reset_index(drop=True)
    return df_out


# ══════════════════════════════════════════════════════════════════
# SETUP 3 — MOMENTUM RESET BOUNCE
# ══════════════════════════════════════════════════════════════════

def scan_momentum_reset(tickers: list,
                         price_min: float = 5.0,
                         price_max: float = 5000.0,
                         status_ph=None) -> pd.DataFrame:
    """
    Weekly re-entry after a healthy pullback in a strong uptrend:
      • Long-term uptrend intact: price above RISING 30-week SMA
      • Pulled back to 10-week EMA or 21-week EMA (weekly low touched EMA)
      • Weekly RSI cooled to 48–62 (was higher, now resetting)
      • RSI turning upward vs 3 weeks ago
      • Weekly MACD histogram turns positive (−→ +)  OR is freshly positive
      • Bullish reversal candle on current weekly bar
      • Volume increases vs prior week on the rebound bar
      • Market context: SPY above its 30-week SMA
    Minimum: pullback to one of the EMAs is required.
    """
    results   = []
    spy_wk    = _get_weekly_spy()
    spy_close = spy_wk["Close"].squeeze() if not spy_wk.empty else pd.Series()

    # Market context once
    market_bullish = False
    if not spy_wk.empty and len(spy_wk) >= 32:
        spy_ma30       = calc_sma(spy_close, 30)
        market_bullish = float(spy_close.iloc[-1]) > float(spy_ma30.iloc[-1])

    for ticker in tickers:
        if status_ph:
            status_ph.markdown(
                f'<div style="color:{TEXT_MUTED};font-size:12px;margin:2px 0">'
                f'Momentum Reset · {ticker}…</div>',
                unsafe_allow_html=True,
            )
        try:
            df_wk = _get_weekly(ticker, years=3)
            if df_wk.empty or len(df_wk) < 35:
                continue
            close_wk = df_wk["Close"].squeeze()
            price    = float(close_wk.iloc[-1])
            if not (price_min <= price <= price_max):
                continue

            # Long-term uptrend: price above RISING 30-week SMA
            ma30w = calc_sma(close_wk, 30)
            if price < float(ma30w.iloc[-1]):
                continue
            if not _ma_rising(ma30w, lookback=4):
                continue

            # 10-week EMA and 21-week EMA
            ema10w = calc_ema(close_wk, 10)
            ema21w = calc_ema(close_wk, 21)

            # Pullback to either EMA (required)
            touch_10, touch_21 = _pullback_to_ema(df_wk, ema10w, ema21w, tol=0.04)
            if not (touch_10 or touch_21):
                continue

            # Weekly RSI cooled to 48–62
            rsi_wk = _weekly_rsi(close_wk)
            if not (48 <= rsi_wk <= 62):
                continue

            # RSI turning up vs 3 weeks ago
            rsi_3w = calc_rsi(close_wk.iloc[:-3], period=14) if len(close_wk) > 17 else rsi_wk
            rsi_rising = rsi_wk > rsi_3w

            # Weekly MACD histogram status
            hist_prev, hist_curr = _weekly_macd_hist(close_wk)
            macd_turning  = hist_prev < 0 and hist_curr >= 0     # freshly crossed zero
            macd_positive = hist_curr > 0

            # Need at least MACD turning positive or already positive
            if not (macd_turning or macd_positive):
                continue

            # Reversal candle + volume
            reversal_candle = _bullish_reversal_candle(df_wk)
            vol             = df_wk["Volume"].squeeze()
            vol_increasing  = float(vol.iloc[-1]) > float(vol.iloc[-2]) if len(vol) >= 2 else False
            wk_vol_ratio    = _weekly_vol_ratio(df_wk, lookback=20)
            rs              = _weekly_rs(close_wk, spy_close, lookback=26)

            # Which EMA it bounced off
            if touch_10 and touch_21:
                bounce_label = "10W+21W"
            elif touch_10:
                bounce_label = "10W EMA"
            else:
                bounce_label = "21W EMA"

            # ── Scoring ───────────────────────────────────────────
            score = 0
            score += 20                                     # above rising 30W MA (required)
            score += 15 if touch_10 else 10                 # 10W touch = tighter, stronger
            score += 15 if rsi_rising else 5
            score += 15 if macd_turning else (8 if macd_positive else 0)
            score += 10 if reversal_candle else 0
            score += 10 if vol_increasing else 0
            score +=  8 if market_bullish else 0
            score +=  7 if rs >= 1.0 else 0
            score = min(score, 100)

            prev = float(close_wk.iloc[-2]) if len(close_wk) > 1 else price
            chg  = (price - prev) / prev * 100

            results.append({
                "Ticker":      ticker,
                "Price":       round(price, 2),
                "Change %":    round(chg, 2),
                "RSI":         round(rsi_wk, 1),
                "Bounce EMA":  bounce_label,
                "10W EMA":     round(float(ema10w.iloc[-1]), 2),
                "21W EMA":     round(float(ema21w.iloc[-1]), 2),
                "Vol Ratio":   wk_vol_ratio,
                "RS vs SPY":   rs,
                "MACD → +":   "✅" if macd_turning else "—",
                "Reversal":    "✅" if reversal_candle else "—",
                "Vol Up":      "✅" if vol_increasing else "—",
                "Score":       score,
            })
        except Exception:
            continue

    df_out = pd.DataFrame(results)
    if not df_out.empty:
        df_out = df_out.sort_values("Score", ascending=False).reset_index(drop=True)
    return df_out
