# scanners/mtpa_scanner.py — MTPA Scanner (Momentum Trend Price Action)
# ─────────────────────────────────────────────────────────────────────────────
# Admin-only scanner. No scoring. Pure filter + display.
# Evaluates each ticker across weekly structure, daily technicals, earnings
# proximity, candlestick patterns, relative strength, and sector ETF trend,
# then assigns tickers to Table 1 (PRIME), Table 2 (STRONG), or Table 3 (BUILDING).
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional

from config import SP500_SAMPLE
from utils import calc_ema, calc_rsi, calc_macd, calc_sma
from data_loader import get_price_history, get_info, prefetch_tickers


# ── Sector ETF mapping ────────────────────────────────────────────────────────
# Maps ticker sector string (from yfinance info) → SPDR sector ETF ticker.
# Matched via substring to handle variations like "Technology" / "Information Technology".
SECTOR_ETF_MAP = {
    "Technology":             "XLK",
    "Information Technology": "XLK",
    "Financials":             "XLF",
    "Financial Services":     "XLF",
    "Healthcare":             "XLV",
    "Health Care":            "XLV",
    "Energy":                 "XLE",
    "Consumer Discretionary": "XLY",
    "Consumer Staples":       "XLP",
    "Industrials":            "XLI",
    "Materials":              "XLB",
    "Utilities":              "XLU",
    "Real Estate":            "XLRE",
    "Communication":          "XLC",
    "Communication Services": "XLC",
}

# Pre-compute sector ETF MACD trend cache so we only fetch each sector ETF once.
_SECTOR_TREND_CACHE: dict[str, bool] = {}


def _get_sector_etf(sector: str) -> str:
    """Return the sector ETF ticker for a given sector string, or 'SPY' fallback."""
    for key, etf in SECTOR_ETF_MAP.items():
        if key.lower() in sector.lower():
            return etf
    return "SPY"


def _sector_is_trending(etf_ticker: str) -> bool:
    """True if sector ETF's MACD line > Signal line (bullish trend)."""
    global _SECTOR_TREND_CACHE
    if etf_ticker in _SECTOR_TREND_CACHE:
        return _SECTOR_TREND_CACHE[etf_ticker]
    try:
        df = get_price_history(etf_ticker, period="6mo")
        if df.empty or len(df) < 30:
            _SECTOR_TREND_CACHE[etf_ticker] = False
            return False
        close = df["Close"].squeeze()
        macd_line, signal_line, _, _ = calc_macd(close)
        trending = macd_line > signal_line
        _SECTOR_TREND_CACHE[etf_ticker] = bool(trending)
        return bool(trending)
    except Exception:
        _SECTOR_TREND_CACHE[etf_ticker] = False
        return False


# ── Weekly pattern detection ──────────────────────────────────────────────────

def _calc_weekly_pattern(wk_df: pd.DataFrame) -> str:
    """
    Classify the last 4–6 weekly bars as:
      "HH/HL"     — higher highs AND higher lows (uptrend structure)
      "Tight Base" — average weekly ATR% < 4.5% (consolidation)
      "Mixed"     — neither
    Uses the last 6 bars for the HH/HL check and last 5 for the tight-base check.
    """
    if wk_df.empty or len(wk_df) < 6:
        return "Mixed"

    bars = wk_df.iloc[-6:]
    highs = bars["High"].values
    lows  = bars["Low"].values

    # HH/HL: each bar must have a higher high and higher low than the one before
    hh = all(highs[i] > highs[i - 1] for i in range(1, len(highs)))
    hl = all(lows[i]  > lows[i - 1]  for i in range(1, len(lows)))

    if hh and hl:
        return "HH/HL"

    # Tight Base: average weekly ATR% (High - Low) / Close < 4.5%
    last5 = wk_df.iloc[-5:]
    atr_pcts = (last5["High"] - last5["Low"]) / last5["Close"].replace(0, np.nan) * 100
    avg_atr_pct = float(atr_pcts.mean())
    if avg_atr_pct < 4.5:
        return "Tight Base"

    return "Mixed"


def _calc_weekly_extended(wk_df: pd.DataFrame) -> bool:
    """True if weekly close > weekly EMA(20) * 1.10 (over-extended)."""
    if wk_df.empty or len(wk_df) < 20:
        return False
    close = wk_df["Close"].squeeze()
    ema20 = float(calc_ema(close, 20).iloc[-1])
    curr  = float(close.iloc[-1])
    return curr > ema20 * 1.10


# ── Candlestick pattern detection (last 3 daily bars) ─────────────────────────

def _detect_candle_patterns(df: pd.DataFrame) -> list[str]:
    """
    Scan the last 3 daily bars for bullish candlestick patterns.
    Returns a list of detected pattern names (empty list if none found).

    Patterns checked:
      Hammer, Bullish Engulfing, Morning Star, Piercing Line,
      Bullish Harami, Three White Soldiers, Dragonfly Doji,
      Inverted Hammer, Tweezer Bottom
    """
    patterns: list[str] = []
    if df.empty or len(df) < 3:
        return patterns

    # Use last 3 bars (indices -3, -2, -1)
    bars = df.iloc[-3:].copy()
    o = bars["Open"].values.astype(float)
    h = bars["High"].values.astype(float)
    l = bars["Low"].values.astype(float)
    c = bars["Close"].values.astype(float)

    def body(i):    return abs(c[i] - o[i])
    def is_bull(i): return c[i] > o[i]
    def is_bear(i): return c[i] < o[i]
    def upper_wick(i): return h[i] - max(c[i], o[i])
    def lower_wick(i): return min(c[i], o[i]) - l[i]

    # ── Bar -1 (most recent) single-bar patterns ──
    i = 2   # index 2 → last bar
    b = body(i)
    lw = lower_wick(i)
    uw = upper_wick(i)

    # Hammer: small body at top, lower shadow >= 2x body, minimal upper shadow
    if b > 0 and lw >= 2 * b and uw <= 0.3 * b:
        patterns.append("Hammer")

    # Inverted Hammer: small body at bottom, upper shadow >= 2x body
    if b > 0 and uw >= 2 * b and lw <= 0.3 * b:
        patterns.append("Inverted Hammer")

    # Dragonfly Doji: open ≈ close near the high, long lower shadow
    if b < (h[i] - l[i]) * 0.1 and lw >= (h[i] - l[i]) * 0.6:
        patterns.append("Dragonfly Doji")

    # ── Two-bar patterns (bars -2 and -1) ──
    if len(df) >= 2:
        p = 1   # previous bar (index 1 in slice)

        # Bullish Engulfing: prev red, current green body engulfs prev body
        if is_bear(p) and is_bull(i):
            if c[i] > o[p] and o[i] < c[p]:
                patterns.append("Bullish Engulfing")

        # Piercing Line: prev red, current opens below prev low, closes above prev midpoint
        prev_mid = (o[p] + c[p]) / 2
        if is_bear(p) and is_bull(i):
            if o[i] < l[p] and c[i] > prev_mid and c[i] < o[p]:
                patterns.append("Piercing Line")

        # Bullish Harami: small green candle inside prior large red candle
        if is_bear(p) and is_bull(i):
            if o[i] > c[p] and c[i] < o[p] and body(i) < body(p) * 0.5:
                patterns.append("Bullish Harami")

        # Tweezer Bottom: two candles with same/similar low (within 0.2%) after context
        if abs(l[i] - l[p]) / max(l[p], 1e-9) < 0.002:
            patterns.append("Tweezer Bottom")

    # ── Three-bar patterns (all three bars) ──
    if len(df) >= 3:
        pp = 0  # bar before previous (index 0 in slice)

        # Three White Soldiers: 3 consecutive green candles each closing higher
        if is_bull(pp) and is_bull(p) and is_bull(i):
            if c[i] > c[p] > c[pp]:
                patterns.append("Three White Soldiers")

        # Morning Star: down candle, small body, up candle closing above midpoint of first
        pp_mid = (o[pp] + c[pp]) / 2
        if (is_bear(pp) and
                body(p) < body(pp) * 0.35 and
                is_bull(i) and
                c[i] > pp_mid):
            patterns.append("Morning Star")

    return patterns


# ── Earnings proximity ────────────────────────────────────────────────────────

def _calc_earnings(info: dict) -> tuple[int, str]:
    """
    Returns (days_to_earnings, earnings_flag).
      days_to_earnings: integer days to next earnings, -1 if unknown
      earnings_flag:    "SKIP" ≤7d · "WARN" 8–14d · "OK" otherwise
    """
    raw = info.get("earningsTimestamp") or info.get("nextEarningsDate")
    if not raw:
        return -1, "OK"
    try:
        earn_date = (
            datetime.utcfromtimestamp(int(raw)).date()
            if isinstance(raw, (int, float))
            else datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
        )
        days_to = (earn_date - datetime.utcnow().date()).days
        if days_to < 0:
            return -1, "OK"   # earnings already passed
        if days_to <= 7:
            return days_to, "SKIP"
        if days_to <= 14:
            return days_to, "WARN"
        return days_to, "OK"
    except Exception:
        return -1, "OK"


# ── 10-day relative strength vs SPY ──────────────────────────────────────────

def _calc_rs_10d(close: pd.Series, spy_close: pd.Series) -> tuple[float, str, str]:
    """
    Compute 10-day relative strength vs SPY.
    Returns (rs_value, rs_status, rs_pct).
    """
    try:
        n = min(10, len(close) - 1, len(spy_close) - 1)
        if n < 2:
            return 1.0, "MATCH", "+0.0%"
        ticker_ret = float(close.iloc[-1]) / float(close.iloc[-(n + 1)]) if float(close.iloc[-(n + 1)]) else 1.0
        spy_ret    = float(spy_close.iloc[-1]) / float(spy_close.iloc[-(n + 1)]) if float(spy_close.iloc[-(n + 1)]) else 1.0
        rs_val = ticker_ret / spy_ret if spy_ret else 1.0
        diff_pct = (rs_val - 1.0) * 100
        pct_str  = f"+{diff_pct:.1f}%" if diff_pct >= 0 else f"{diff_pct:.1f}%"
        if rs_val > 1.02:
            status = "OUTPERFORM"
        elif rs_val >= 0.95:
            status = "MATCH"
        else:
            status = "UNDERPERFORM"
        return round(rs_val, 4), status, pct_str
    except Exception:
        return 1.0, "MATCH", "+0.0%"


# ── RSI classification ────────────────────────────────────────────────────────

def _rsi_status(close: pd.Series) -> tuple[float, str]:
    """Return (rsi_value, rsi_status). Uses last 3 bars to detect rising RSI."""
    rsi_now  = calc_rsi(close)
    rsi_prev = calc_rsi(close.iloc[:-2]) if len(close) > 3 else rsi_now
    rising = rsi_now > rsi_prev
    if 50 <= rsi_now <= 70 and rising:
        status = "GREEN"
    elif 40 <= rsi_now < 50 and rising:
        status = "YELLOW"
    else:
        status = "NEUTRAL"
    return round(rsi_now, 1), status


# ── Unusual flags ─────────────────────────────────────────────────────────────

def _build_flags(
    close: pd.Series,
    open_today: float,
    prev_close: float,
    volume_ratio: float,
    rs_value: float,
    weekly_extended: bool,
    earnings_flag: str,
) -> list[str]:
    """Return list of unusual flag strings for this ticker."""
    flags: list[str] = []
    price = float(close.iloc[-1])

    # Near 52W High: within 3% of 52-week high
    high_52w = float(close.rolling(252, min_periods=1).max().iloc[-1])
    if price >= high_52w * 0.97:
        flags.append("Near 52W High")

    # Volume Spike
    if volume_ratio >= 1.5:
        flags.append("Vol Spike")

    # Gap Up / Gap Down
    if prev_close > 0:
        if open_today > prev_close * 1.01:
            flags.append("Gap Up")
        elif open_today < prev_close * 0.99:
            flags.append("Gap Down")

    # RS Extreme
    if rs_value > 1.15 or rs_value < 0.80:
        flags.append("RS Extreme")

    # Extended (weekly)
    if weekly_extended:
        flags.append("Extended")

    # Earnings Soon
    if earnings_flag == "WARN":
        flags.append("Earnings Soon")

    return flags


# ── Table assignment ──────────────────────────────────────────────────────────

def _assign_table(r: dict) -> Optional[int]:
    """
    Returns 1, 2, 3, or None (doesn't qualify for any table).
    Priority: Table 1 > Table 2 > Table 3 (first match wins).
    """
    # Table 1 (PRIME): full alignment
    if (r["weekly_pattern"] in ("HH/HL", "Tight Base")
            and not r["weekly_extended"]
            and r["rsi_status"] in ("GREEN", "YELLOW")
            and r["macd_above_signal"]
            and r["volume_ok"]
            and r["price_above_sma20"]
            and r["macd_zone"] == "NEAR_ZERO"
            and r["earnings_flag"] != "SKIP"):
        return 1

    # Table 2 (STRONG): weekly clean + daily confirmed
    if (not r["weekly_extended"]
            and r["rsi_status"] in ("GREEN", "YELLOW")
            and r["macd_above_signal"]
            and r["price_above_sma9"]):
        return 2

    # Table 3 (BUILDING): daily signal only
    if r["rsi_status"] in ("GREEN", "YELLOW") and r["macd_above_signal"]:
        return 3

    return None


# ── Main scan function ────────────────────────────────────────────────────────

def run_mtpa_scan(
    tickers: Optional[list[str]] = None,
    progress_label=None,
    progress_bar=None,
) -> dict:
    """
    Run the MTPA scan over `tickers` (defaults to SP500_SAMPLE).

    Returns a dict with keys:
      table1       — list of result dicts (PRIME setups)
      table2       — list of result dicts (STRONG setups)
      table3       — list of result dicts (BUILDING setups)
      scan_time    — float seconds elapsed
      total_scanned — int
      total_matched — int
      failed        — list of tickers that raised exceptions
    """
    if tickers is None:
        tickers = SP500_SAMPLE

    t_start = datetime.now()

    # ── Clear per-run sector trend cache ──
    global _SECTOR_TREND_CACHE
    _SECTOR_TREND_CACHE = {}

    # ── Batch-prefetch daily data: tickers + SPY + all sector ETFs ──
    # Sector ETFs are included here so _sector_is_trending() (which calls
    # get_price_history(etf, period="6mo", interval="1d")) hits the process
    # cache instead of making individual network requests per sector.
    sector_etfs = list(set(SECTOR_ETF_MAP.values()))
    all_daily   = list(dict.fromkeys(tickers + ["SPY"] + sector_etfs))
    prefetch_tickers(all_daily, period="6mo", interval="1d")

    # ── Fetch SPY close for relative-strength calculation ─────────
    spy_df = get_price_history("SPY", period="6mo")
    spy_close = spy_df["Close"].squeeze() if not spy_df.empty else pd.Series(dtype=float)

    # ── Prefetch weekly bars for all tickers in one batch ─────────
    prefetch_tickers(tickers, period="2y", interval="1wk")

    table1: list[dict] = []
    table2: list[dict] = []
    table3: list[dict] = []
    failed: list[str]  = []

    n = len(tickers)

    for idx, ticker in enumerate(tickers):
        # Progress update
        if progress_label is not None:
            progress_label.markdown(
                f'<div style="color:#C9A84C;font-size:12px">'
                f'🔍 Scanning {idx + 1} of {n} — {ticker}</div>',
                unsafe_allow_html=True,
            )
        if progress_bar is not None:
            progress_bar.progress((idx + 1) / n)

        try:
            # ── Daily data ───────────────────────────────────────
            daily_df = get_price_history(ticker, period="6mo", interval="1d")
            if daily_df.empty or len(daily_df) < 30:
                continue

            # Squeeze MultiIndex columns if present
            if isinstance(daily_df.columns, pd.MultiIndex):
                daily_df.columns = daily_df.columns.get_level_values(0)

            close  = daily_df["Close"].squeeze()
            volume = daily_df["Volume"].squeeze()
            open_s = daily_df["Open"].squeeze()

            price      = float(close.iloc[-1])
            prev_close = float(close.iloc[-2]) if len(close) > 1 else price
            open_today = float(open_s.iloc[-1]) if not open_s.empty else price

            # ── Weekly data ──────────────────────────────────────
            wk_df = get_price_history(ticker, period="2y", interval="1wk")
            if isinstance(wk_df.columns, pd.MultiIndex):
                wk_df.columns = wk_df.columns.get_level_values(0)

            # ── Weekly indicators ────────────────────────────────
            weekly_pattern  = _calc_weekly_pattern(wk_df)
            weekly_extended = _calc_weekly_extended(wk_df) if not wk_df.empty else False

            # ── RSI ───────────────────────────────────────────────
            rsi_value, rsi_status = _rsi_status(close)

            # ── MACD ─────────────────────────────────────────────
            macd_line, signal_line, _, _ = calc_macd(close)
            macd_above_signal = bool(macd_line > signal_line)
            if macd_line > 3:
                macd_zone = "POSITIVE"
            elif macd_line < -3:
                macd_zone = "NEGATIVE"
            else:
                macd_zone = "NEAR_ZERO"

            # ── Volume ratio ─────────────────────────────────────
            avg_vol = float(
                volume.iloc[:-1].rolling(20).mean().dropna().iloc[-1]
            ) if len(volume) > 20 else float(volume.mean())
            curr_vol    = float(volume.iloc[-1])
            volume_ratio = curr_vol / avg_vol if avg_vol > 0 else 0.0
            volume_ok    = bool(1.0 < volume_ratio < 1.8)

            # ── SMA checks ────────────────────────────────────────
            sma9_ser  = calc_sma(close, 9)
            sma20_ser = calc_sma(close, 20)
            price_above_sma9  = bool(price > float(sma9_ser.iloc[-1]))
            price_above_sma20 = bool(price > float(sma20_ser.iloc[-1]))

            # ── Earnings ─────────────────────────────────────────
            info = get_info(ticker)
            days_to_earnings, earnings_flag = _calc_earnings(info)

            # ── Candlestick patterns ──────────────────────────────
            candle_patterns = _detect_candle_patterns(daily_df)

            # ── Relative Strength vs SPY (10-day) ────────────────
            rs_value, rs_status, rs_pct = _calc_rs_10d(close, spy_close)

            # ── Sector ETF ────────────────────────────────────────
            sector_raw = str(info.get("sector") or info.get("industry") or "")
            sector_etf     = _get_sector_etf(sector_raw)
            sector_trending = _sector_is_trending(sector_etf)

            # ── Unusual flags ─────────────────────────────────────
            flags = _build_flags(
                close, open_today, prev_close,
                volume_ratio, rs_value, weekly_extended, earnings_flag,
            )

            # ── Assemble result dict ──────────────────────────────
            result = {
                "ticker":            ticker,
                "price":             round(price, 2),
                # Weekly
                "weekly_pattern":    weekly_pattern,
                "weekly_extended":   weekly_extended,
                # Daily — RSI
                "rsi_value":         rsi_value,
                "rsi_status":        rsi_status,
                # Daily — MACD
                "macd_value":        round(macd_line, 3),
                "macd_signal":       round(signal_line, 3),
                "macd_above_signal": macd_above_signal,
                "macd_zone":         macd_zone,
                # Daily — Volume
                "volume_ratio":      round(volume_ratio, 2),
                "volume_ok":         volume_ok,
                # Daily — SMA
                "price_above_sma20": price_above_sma20,
                "price_above_sma9":  price_above_sma9,
                # Earnings
                "days_to_earnings":  days_to_earnings,
                "earnings_flag":     earnings_flag,
                # Candlestick
                "candle_patterns":   candle_patterns,
                # Relative strength
                "rs_value":          rs_value,
                "rs_status":         rs_status,
                "rs_pct":            rs_pct,
                # Sector
                "sector_etf":        sector_etf,
                "sector_trending":   sector_trending,
                # Flags
                "flags":             flags,
            }

            # ── Table assignment ──────────────────────────────────
            table_num = _assign_table(result)
            if table_num == 1:
                table1.append(result)
            elif table_num == 2:
                table2.append(result)
            elif table_num == 3:
                table3.append(result)

        except Exception as exc:
            failed.append(f"{ticker}: {type(exc).__name__}")
            continue

    elapsed = (datetime.now() - t_start).total_seconds()
    total_matched = len(table1) + len(table2) + len(table3)

    # Clear progress UI elements
    if progress_label is not None:
        progress_label.empty()
    if progress_bar is not None:
        progress_bar.empty()

    return {
        "table1":        table1,
        "table2":        table2,
        "table3":        table3,
        "scan_time":     elapsed,
        "total_scanned": len(tickers),
        "total_matched": total_matched,
        "failed":        failed,
    }
