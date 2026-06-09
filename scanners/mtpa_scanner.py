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

from config import SP500_SAMPLE, MTPA_200, INDIA_150
from utils import calc_ema, calc_rsi, calc_macd, calc_sma
from data_loader import get_price_history, get_info, prefetch_tickers
from scanners.first_things_first import _ftf_suggest


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

# India sector ETF mapping — NSE-listed ETFs, NIFTYBEES.NS as broad fallback
INDIA_SECTOR_ETF_MAP = {
    "Technology":             "ITBEES.NS",
    "Information Technology": "ITBEES.NS",
    "Financials":             "BANKBEES.NS",
    "Financial Services":     "BANKBEES.NS",
    "Healthcare":             "NIFTYBEES.NS",
    "Health Care":            "NIFTYBEES.NS",
    "Energy":                 "NIFTYBEES.NS",
    "Consumer Discretionary": "NIFTYBEES.NS",
    "Consumer Staples":       "NIFTYBEES.NS",
    "Industrials":            "NIFTYBEES.NS",
    "Materials":              "NIFTYBEES.NS",
    "Utilities":              "NIFTYBEES.NS",
    "Real Estate":            "NIFTYBEES.NS",
    "Communication":          "NIFTYBEES.NS",
    "Communication Services": "NIFTYBEES.NS",
}

# Pre-compute sector ETF MACD trend cache so we only fetch each sector ETF once.
_SECTOR_TREND_CACHE: dict[str, bool] = {}


def _get_sector_etf(sector: str, sector_map: dict = None, fallback: str = "SPY") -> str:
    """Return the sector ETF ticker for a given sector string, or fallback."""
    if sector_map is None:
        sector_map = SECTOR_ETF_MAP
    for key, etf in sector_map.items():
        if key.lower() in sector.lower():
            return etf
    return fallback


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
    # MACD "near zero" is price-normalised: |MACD line| ≤ 1% of price.
    # 1% on a $200 stock = ±$2 — roughly a 1-2 week window post-crossover
    # before momentum has run too far.  Works for any price tier.
    macd_near_zero = abs(r["macd_value"]) <= r["price"] * 0.01
    if (r["weekly_pattern"] in ("HH/HL", "Tight Base")
            and not r["weekly_extended"]
            and r["rsi_status"] in ("GREEN", "YELLOW")
            and r["macd_above_signal"]
            and r["volume_ok"]
            and r["price_above_sma20"]
            and macd_near_zero
            and r["earnings_flag"] != "SKIP"):
        return 1

    # Table 2 (STRONG): weekly clean + daily confirmed
    # SMA20 (upgraded from SMA9) — requires confirmed medium-term trend, not
    # just a short-term blip above the 9-day line.
    if (not r["weekly_extended"]
            and r["rsi_status"] in ("GREEN", "YELLOW")
            and r["macd_above_signal"]
            and r["price_above_sma20"]):
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
    market: str = "US",
) -> dict:
    """
    Run the MTPA scan over `tickers`.

    market: "US" (default — uses MTPA_200, SPY benchmark, SPDR sector ETFs)
            "IN" (India    — uses INDIA_150, NIFTYBEES.NS benchmark, NSE sector ETFs)

    Returns a dict with keys:
      table1          — list of result dicts (PRIME setups)
      table2          — list of result dicts (STRONG setups)
      table3          — list of result dicts (BUILDING setups)
      table4          — list of result dicts (MACD Momentum — independent)
      scan_time       — float seconds elapsed
      total_scanned   — int
      total_matched   — int
      failed          — list of tickers that raised exceptions
      market          — "US" or "IN"
      benchmark_label — "RS vs SPY" or "RS vs Nifty"
    """
    # ── Market-specific config ────────────────────────────────────
    if market == "IN":
        if tickers is None:
            tickers = INDIA_150
        active_sector_map = INDIA_SECTOR_ETF_MAP
        benchmark         = "NIFTYBEES.NS"
        benchmark_label   = "RS vs Nifty"
        sector_fallback   = "NIFTYBEES.NS"
    else:
        if tickers is None:
            tickers = MTPA_200
        active_sector_map = SECTOR_ETF_MAP
        benchmark         = "SPY"
        benchmark_label   = "RS vs SPY"
        sector_fallback   = "SPY"

    t_start = datetime.now()

    # ── Clear per-run sector trend cache ──
    global _SECTOR_TREND_CACHE
    _SECTOR_TREND_CACHE = {}

    # ── Batch-prefetch daily data: tickers + benchmark + all sector ETFs ──
    # Sector ETFs are included here so _sector_is_trending() (which calls
    # get_price_history(etf, period="6mo", interval="1d")) hits the process
    # cache instead of making individual network requests per sector.
    sector_etfs = list(set(active_sector_map.values()))
    all_daily   = list(dict.fromkeys(tickers + [benchmark] + sector_etfs))
    prefetch_tickers(all_daily, period="6mo", interval="1d")

    # ── Fetch benchmark close for relative-strength calculation ───
    bench_df  = get_price_history(benchmark, period="6mo")
    spy_close = bench_df["Close"].squeeze() if not bench_df.empty else pd.Series(dtype=float)

    # ── Prefetch weekly bars for all tickers in one batch ─────────
    prefetch_tickers(tickers, period="2y", interval="1wk")

    table1: list[dict] = []
    table2: list[dict] = []
    table3: list[dict] = []
    table4: list[dict] = []   # MACD Momentum — independent, no dedup
    table_ftf: list[dict] = []  # First Things First — all 18 conditions, zero extra API calls
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

            # ── Weekly MACD & RSI (used by Table 4) ──────────────
            # calc_macd needs ≥26 bars; weekly 2y gives ~104 bars.
            if not wk_df.empty and len(wk_df) >= 26:
                wk_close_s = wk_df["Close"].squeeze()
                wk_macd_line_val, _, wk_hist_val, wk_prev_hist_val = calc_macd(wk_close_s)
                wk_rsi_val  = calc_rsi(wk_close_s)
            else:
                wk_macd_line_val = wk_hist_val = wk_prev_hist_val = 0.0
                wk_rsi_val = 50.0

            wk_macd_line_pos  = bool(wk_macd_line_val > 0)
            wk_hist_pos       = bool(wk_hist_val > 0)
            wk_hist_rising    = bool(wk_hist_val > wk_prev_hist_val)

            # ── RSI ───────────────────────────────────────────────
            rsi_value, rsi_status = _rsi_status(close)

            # ── MACD ─────────────────────────────────────────────
            macd_line, signal_line, macd_hist_val, _ = calc_macd(close)
            macd_above_signal = bool(macd_line > signal_line)   # = hist > 0
            dly_macd_line_pos = bool(macd_line > 0)
            if macd_line > 3:
                macd_zone = "POSITIVE"
            elif macd_line < -3:
                macd_zone = "NEGATIVE"
            else:
                macd_zone = "NEAR_ZERO"

            # ── Volume ratio — use yesterday's completed bar (iloc[-2])
            # Today's bar is partial at open; iloc[-1] would fail every ticker early session.
            avg_vol = float(
                volume.iloc[:-1].rolling(20).mean().dropna().iloc[-1]
            ) if len(volume) > 20 else float(volume.mean())
            curr_vol    = float(volume.iloc[-2]) if len(volume) >= 2 else float(volume.iloc[-1])
            volume_ratio = curr_vol / avg_vol if avg_vol > 0 else 0.0
            volume_ok    = bool(volume_ratio > 0.7)

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
            sector_etf      = _get_sector_etf(sector_raw, active_sector_map, sector_fallback)
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
                "macd_hist":         round(macd_hist_val, 3),
                "macd_above_signal": macd_above_signal,
                "macd_zone":         macd_zone,
                # Weekly MACD (Table 4)
                "wk_macd_line":      round(wk_macd_line_val, 3),
                "wk_macd_hist":      round(wk_hist_val, 3),
                "wk_macd_hist_rising": wk_hist_rising,
                "wk_rsi_value":      round(wk_rsi_val, 1),
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

            # ── Table 1/2/3 assignment (dedup) ───────────────────
            table_num = _assign_table(result)
            if table_num == 1:
                table1.append(result)
            elif table_num == 2:
                table2.append(result)
            elif table_num == 3:
                table3.append(result)

            # ── Table 4 (MACD Momentum) — independent, no dedup ──
            # Weekly: Line>0 + Hist>0 + Hist rising
            # Daily:  Line>0 + Hist>0
            if (wk_macd_line_pos and wk_hist_pos and wk_hist_rising
                    and dly_macd_line_pos and macd_above_signal):
                table4.append(result)

            # ── First Things First — computed from already-fetched data ──────
            # Zero extra API calls — all series (close, wk_df, volume) are
            # already in memory from the MTPA scan above.
            try:
                # ── Weekly gaps ──────────────────────────────────────────────
                # W6: price > weekly SMA20 (distinct from daily sma20)
                wk_close_s2 = wk_df["Close"].squeeze() if not wk_df.empty else pd.Series(dtype=float)
                _sma20w = float(calc_sma(wk_close_s2, 20).dropna().iloc[-1]) if len(wk_close_s2) >= 20 else 0.0
                _sma50w = float(calc_sma(wk_close_s2, 50).dropna().iloc[-1]) if len(wk_close_s2) >= 50 else _sma20w
                _w6 = price > _sma20w if _sma20w > 0 else False

                # W7: fresh weekly MACD crossover within last 5 bars
                _wk_macd_full, _wk_sig_full, _, _ = calc_macd(wk_close_s2) if len(wk_close_s2) >= 26 else (pd.Series(dtype=float), pd.Series(dtype=float), None, None)
                _fresh_cross_w = False
                _n = min(5, max(0, len(_wk_macd_full) - 1))
                for _k in range(1, _n + 1):
                    if (float(_wk_macd_full.iloc[-_k]) > float(_wk_sig_full.iloc[-_k]) and
                            float(_wk_macd_full.iloc[-_k - 1]) <= float(_wk_sig_full.iloc[-_k - 1])):
                        _fresh_cross_w = True
                        break

                # W9: uptrend = weekly HH/HL OR price > weekly SMA50
                _w9 = (weekly_pattern == "HH/HL") or (price > _sma50w if _sma50w > 0 else False)

                # W2: not extended = price within 10% above weekly SMA20
                _w2 = (_sma20w > 0) and (price <= _sma20w * 1.10)

                # W5: weekly volume ratio (use daily as proxy — same direction)
                _w5 = 0.7 <= volume_ratio <= 3.0

                # ── Daily gaps ────────────────────────────────────────────────
                # D1: not extended — price within 8% above SMA9
                _sma9v = float(calc_sma(close, 9).dropna().iloc[-1]) if len(close) >= 9 else price
                _d1 = (_sma9v > 0) and (price <= _sma9v * 1.08)

                # D5: 2 consecutive rising histogram bars
                _dh_series = (calc_ema(close, 12) - calc_ema(close, 26))
                _dh_series = _dh_series - calc_ema(_dh_series, 9)
                _dh_clean  = _dh_series.dropna()
                _dh_now    = float(_dh_clean.iloc[-1]) if len(_dh_clean) >= 1 else 0.0
                _dh_prev   = float(_dh_clean.iloc[-2]) if len(_dh_clean) >= 2 else _dh_now
                _dh_prev2  = float(_dh_clean.iloc[-3]) if len(_dh_clean) >= 3 else _dh_prev
                _d5 = (_dh_now > _dh_prev) and (_dh_prev > _dh_prev2)

                # Supply zone — display only (not a gate)
                _high_20d = float(close.iloc[-20:].max()) if len(close) >= 20 else price
                _pct_below = (_high_20d - price) / _high_20d * 100 if _high_20d > 0 else 0

                # D6: volume > 20-day average (strict; replaces old supply zone check)
                _d6 = volume_ratio > 1.0
                # D7 removed — D6 now covers volume strictly

                # X1: ADX > 16 (compute from daily OHLC if available)
                _adx_ok = False
                try:
                    _hi = daily_df["High"].squeeze()
                    _lo = daily_df["Low"].squeeze()
                    _prev_cl = close.shift(1)
                    _tr = pd.concat([_hi - _lo, (_hi - _prev_cl).abs(), (_lo - _prev_cl).abs()], axis=1).max(axis=1)
                    _atr = _tr.ewm(com=13, adjust=False).mean()
                    _up = _hi.diff(); _dn = -_lo.diff()
                    _pdm = _up.where((_up > _dn) & (_up > 0), 0.0)
                    _ndm = _dn.where((_dn > _up) & (_dn > 0), 0.0)
                    _safe = _atr.replace(0, np.nan)
                    _pdi = 100 * _pdm.ewm(com=13, adjust=False).mean() / _safe
                    _ndi = 100 * _ndm.ewm(com=13, adjust=False).mean() / _safe
                    _dx = (100 * (_pdi - _ndi).abs() / (_pdi + _ndi).replace(0, np.nan)).fillna(0)
                    _adx_val = float(_dx.ewm(com=13, adjust=False).mean().dropna().iloc[-1])
                    _adx_ok = np.isfinite(_adx_val) and _adx_val > 16
                except Exception:
                    _adx_ok = True   # if ADX fails, don't gate on it

                # X2: no bearish divergence — rebuild RSI series (calc_rsi returns float)
                _delta_r  = close.diff().dropna()
                _gain_r   = _delta_r.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
                _loss_r   = (-_delta_r.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
                _rsi_ser  = (100 - 100 / (1 + _gain_r / _loss_r.replace(0, float("nan")))).fillna(50)
                _no_div   = True
                if len(_rsi_ser) >= 14 and len(close) >= 14:
                    _no_div = not (float(close.iloc[-1]) > float(close.iloc[-14]) and
                                   float(_rsi_ser.iloc[-1]) < float(_rsi_ser.iloc[-14]))

                # Zone metrics
                _pct_above_ema9   = round((price - _sma9v) / _sma9v * 100, 1) if _sma9v > 0 else 0
                _sma20d_v = float(calc_sma(close, 20).dropna().iloc[-1]) if len(close) >= 20 else price
                _pct_above_sma20d = round((price - _sma20d_v) / _sma20d_v * 100, 1) if _sma20d_v > 0 else 0
                # D6 relaxed: volume > 0.7× avg (not strict >1.0×)
                _d6_relaxed = volume_ratio > 0.7

                # ── FTF gate — current conditions (W1 W5 W7 removed; W2→15%, W3→75) ──
                _w2_curr = (_sma20w > 0) and (price <= _sma20w * 1.15)
                _ftf_pass = all([
                    _w2_curr,               # W2 not extended (≤15%)
                    35 <= wk_rsi_val <= 75, # W3 RSI (weekly, raised to 75)
                    wk_hist_pos,            # W4 MACD>Signal weekly
                    _w6,                    # W6 price > SMA20W
                    _w9,                    # W9 uptrend
                    _d1,                    # D1 not extended daily
                    35 <= rsi_value <= 70,  # D2
                    macd_above_signal,      # D3
                    price_above_sma9,       # D4
                    _d5,                    # D5: 2 consecutive rising hist bars
                    _adx_ok,                # X1
                    _no_div,                # X2
                ])

                if _ftf_pass:
                    _w_det = {
                        "rsi_w":      round(wk_rsi_val, 1),
                        "hist_w":     round(_dh_now, 4),
                        "hist_w_prev":round(_dh_prev, 4),
                        "hh_hl":      weekly_pattern == "HH/HL",
                        "sma20_w":    round(_sma20w, 2),
                        "sma50_w":    round(_sma50w, 2),
                        "macd_w":     0, "sig_w": 0,              # not separately tracked
                    }
                    _d_det = {
                        "rsi_d":           round(rsi_value, 1),
                        "hist_d":          round(_dh_now, 4),
                        "hist_d_prev":     round(_dh_prev, 4),
                        "hist_d_prev2":    round(_dh_prev2, 4),
                        "adx":             round(_adx_val, 1) if (_adx_ok and np.isfinite(_adx_val)) else None,
                        "adx_rising":      False,
                        "bearish_div":     not _no_div,
                        "in_demand":       price <= float(close.iloc[-10:].min()) * 1.05 if len(close) >= 10 else False,
                        "pct_below_high":  round(_pct_below, 1),
                        "pct_above_ema9":  _pct_above_ema9,
                        "pct_above_sma20d":_pct_above_sma20d,
                    }
                    table_ftf.append({
                        "ticker":   ticker,
                        "price":    round(price, 2),
                        "w_detail": _w_det,
                        "d_detail": _d_det,
                        "w_flags":  [],
                        "d_flags":  [],
                        "suggest":  _ftf_suggest(_w_det, _d_det),
                    })
            except Exception:
                pass   # FTF failure never blocks the main MTPA result

        except Exception as exc:
            failed.append(f"{ticker}: {type(exc).__name__}")
            continue

    elapsed = (datetime.now() - t_start).total_seconds()
    total_matched = len(table1) + len(table2) + len(table3)

    # ── Mark Table 4 rows that also appear in Tables 1–3 ─────────
    # Stores the table number (1/2/3) so the page can show the correct
    # coloured circle (🟢/🟡/🔵).  0 means not in any of the main tables.
    main_table_map: dict[str, int] = {}
    for r in table1:
        main_table_map[r["ticker"]] = 1
    for r in table2:
        main_table_map[r["ticker"]] = 2
    for r in table3:
        main_table_map[r["ticker"]] = 3
    for r in table4:
        r["in_main_tables"] = main_table_map.get(r["ticker"], 0)

    # Clear progress UI elements
    if progress_label is not None:
        progress_label.empty()
    if progress_bar is not None:
        progress_bar.empty()

    # Sort FTF by ADX descending (strongest trend first)
    table_ftf.sort(key=lambda r: r.get("d_detail", {}).get("adx") or 0, reverse=True)

    return {
        "table1":          table1,
        "table2":          table2,
        "table3":          table3,
        "table4":          table4,
        "table_ftf":       table_ftf,   # First Things First — 0 extra API calls
        "scan_time":       elapsed,
        "total_scanned":   len(tickers),
        "total_matched":   total_matched,
        "failed":          failed,
        "market":          market,
        "benchmark_label": benchmark_label,
    }
