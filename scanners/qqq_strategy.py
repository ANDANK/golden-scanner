"""
QQQ / TQQQ Rules-Based Strategy Engine
Weight-of-Evidence scoring — 7 indicators, threshold +4 (in-season) / +5 (off-season).
"""

import datetime as _dt

import numpy as np
import pandas as pd
import yfinance as yf

# ── Constants ─────────────────────────────────────────────────────────────────
VERSION               = "1.0"
MAX_SCORE             = 7
THRESHOLD_IN_SEASON   = 4
THRESHOLD_OFF_SEASON  = 5
VIX_LIMIT             = 31
MACD_SLOPE_DAYS       = 3          # MACD slope measured over 3 days
_OFF_MONTHS           = {7, 8, 9, 10}   # July–October = out-of-season

# ── Data helpers ──────────────────────────────────────────────────────────────

def _fetch(ticker: str, period: str = "2y") -> pd.DataFrame:
    """Download daily OHLCV; return lowercase-column DataFrame."""
    raw = yf.download(ticker, period=period, interval="1d",
                      progress=False, auto_adjust=True)
    if raw.empty:
        return pd.DataFrame()
    # yfinance may return MultiIndex columns when auto_adjust=True
    if isinstance(raw.columns, pd.MultiIndex):
        raw = raw.xs(ticker, axis=1, level=1) if ticker in raw.columns.get_level_values(1) \
              else raw.droplevel(1, axis=1)
    raw.columns = [c.lower() for c in raw.columns]
    df = raw[["open", "high", "low", "close", "volume"]].dropna()
    df.index = pd.to_datetime(df.index)
    return df


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def _atr(df: pd.DataFrame, n: int = 20) -> pd.Series:
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"]  - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=n - 1, adjust=False).mean()


def _macd(s: pd.Series, fast=12, slow=26, sig=9):
    line   = _ema(s, fast) - _ema(s, slow)
    signal = _ema(line, sig)
    return line, signal


def _rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d     = s.diff()
    gain  = d.clip(lower=0).ewm(com=n - 1, adjust=False).mean()
    loss  = (-d.clip(upper=0)).ewm(com=n - 1, adjust=False).mean()
    return 100 - 100 / (1 + gain / loss.replace(0, np.nan))


def _keltner(df: pd.DataFrame, ema_n=20, atr_n=20, mult=2.0):
    mid   = _ema(df["close"], ema_n)
    band  = mult * _atr(df, atr_n)
    return mid, mid + band, mid - band


# ── Candlestick pattern detection ────────────────────────────────────────────

_BULLISH_PATTERNS: list[str] = [
    "Hammer",
    "Inverted Hammer",
    "Bullish Engulfing",
    "Piercing Line",
    "Bullish Harami",
    "Morning Star",
    "Three White Soldiers",
    "Dragonfly Doji",
]

_BEARISH_PATTERNS: list[str] = [
    "Shooting Star",
    "Bearish Engulfing",
    "Evening Star",
    "Dark Cloud Cover",
    "Hanging Man",
    "Three Black Crows",
    "Gravestone Doji",
]


def _candle_score(df: pd.DataFrame) -> tuple[int, str]:
    """Return (+1/'pattern name'), (-1/'pattern name'), or (0,'None')."""
    if len(df) < 3:
        return 0, "Not enough data"

    o0, h0, l0, c0 = (df["open"].iloc[-1], df["high"].iloc[-1],
                       df["low"].iloc[-1],  df["close"].iloc[-1])
    o1, h1, l1, c1 = (df["open"].iloc[-2], df["high"].iloc[-2],
                       df["low"].iloc[-2],  df["close"].iloc[-2])
    o2, h2, l2, c2 = (df["open"].iloc[-3], df["high"].iloc[-3],
                       df["low"].iloc[-3],  df["close"].iloc[-3])

    body0  = abs(c0 - o0)
    body1  = abs(c1 - o1)
    body2  = abs(c2 - o2)
    rng0   = max(h0 - l0, 1e-6)
    rng1   = max(h1 - l1, 1e-6)
    us0    = h0 - max(o0, c0)   # upper shadow today
    ls0    = min(o0, c0) - l0   # lower shadow today
    us1    = h1 - max(o1, c1)
    ls1    = min(o1, c1) - l1

    # ── Bullish ──────────────────────────────────────────────────────────────

    # Hammer: long lower shadow ≥ 2× body, tiny upper shadow, close in upper half
    if (body0 > 0 and ls0 >= 2 * body0
            and us0 <= 0.3 * body0
            and (c0 - l0) / rng0 >= 0.5):
        # Distinguish Hanging Man (bearish) by prior trend
        if c1 < o1:   # prior candle bearish → Hammer
            return 1, "Hammer"
        elif c1 > o1:  # prior candle bullish → Hanging Man
            return -1, "Hanging Man"

    # Inverted Hammer (at bottom after red candle)
    if (body0 > 0 and us0 >= 2 * body0
            and ls0 <= 0.3 * body0
            and c1 < o1):
        return 1, "Inverted Hammer"

    # Bullish Engulfing: today green, yesterday red, today's body wraps yesterday's
    if (c0 > o0 and c1 < o1
            and o0 <= c1 and c0 >= o1):
        return 1, "Bullish Engulfing"

    # Piercing Line: red yesterday, gap-lower open today, close above prior midpoint
    prior_mid = (o1 + c1) / 2
    if (c1 < o1 and c0 > o0
            and o0 < l1
            and c0 > prior_mid and c0 < o1):
        return 1, "Piercing Line"

    # Bullish Harami: small green body inside prior large red body
    if (c1 < o1 and c0 > o0
            and o0 >= c1 and c0 <= o1
            and body0 <= 0.5 * body1):
        return 1, "Bullish Harami"

    # Morning Star: big red → small body/doji → big green closing above mid of candle 1
    if (c2 < o2 and body1 <= 0.3 * rng1
            and c0 > o0
            and c0 > (o2 + c2) / 2
            and body2 > 0.5 * body0):
        return 1, "Morning Star"

    # Three White Soldiers: 3 consecutive green candles, higher closes & opens
    if (c0 > o0 and c1 > o1 and c2 > o2
            and c0 > c1 > c2
            and o0 > o1 > o2
            and ls0 <= 0.2 * body0):
        return 1, "Three White Soldiers"

    # Dragonfly Doji: tiny body near high, very long lower shadow
    if (body0 <= 0.05 * rng0
            and ls0 >= 0.7 * rng0):
        return 1, "Dragonfly Doji"

    # ── Bearish ──────────────────────────────────────────────────────────────

    # Shooting Star: long upper shadow ≥ 2× body, small lower shadow, at top after green
    if (body0 > 0 and us0 >= 2 * body0
            and ls0 <= 0.3 * body0
            and c1 > o1):
        return -1, "Shooting Star"

    # Bearish Engulfing: today red, yesterday green, today's body wraps yesterday's
    if (c0 < o0 and c1 > o1
            and o0 >= c1 and c0 <= o1):
        return -1, "Bearish Engulfing"

    # Evening Star: big green → small doji → big red closing below mid of candle 1
    if (c2 > o2 and body1 <= 0.3 * rng1
            and c0 < o0
            and c0 < (o2 + c2) / 2):
        return -1, "Evening Star"

    # Dark Cloud Cover: green yesterday, gap-higher open today, close below prior midpoint
    prior_mid1 = (o1 + c1) / 2
    if (c1 > o1 and c0 < o0
            and o0 > h1
            and c0 < prior_mid1 and c0 > o1):
        return -1, "Dark Cloud Cover"

    # Three Black Crows: 3 consecutive red candles, lower closes & opens
    if (c0 < o0 and c1 < o1 and c2 < o2
            and c0 < c1 < c2):
        return -1, "Three Black Crows"

    # Gravestone Doji: tiny body near low, very long upper shadow
    if (body0 <= 0.05 * rng0
            and us0 >= 0.7 * rng0):
        return -1, "Gravestone Doji"

    return 0, "None"


# ── Higher High / Higher Low detection ───────────────────────────────────────

def _hh_hl(df: pd.DataFrame, lookback: int = 30) -> tuple[bool, float]:
    """
    Detect HH+HL swing structure in last *lookback* bars.
    Returns (is_uptrend, last_hl_price) for stop placement.
    """
    sub   = df.tail(lookback)
    highs = sub["high"].values
    lows  = sub["low"].values

    sh, sl = [], []
    for i in range(2, len(highs) - 2):
        if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
            sh.append(highs[i])
        if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
            sl.append(lows[i])

    is_up = (
        len(sh) >= 2 and sh[-1] > sh[-2] and   # Higher High
        len(sl) >= 2 and sl[-1] > sl[-2]        # Higher Low
    )
    last_hl = float(sl[-1]) if sl else float(df["low"].tail(10).min())
    return is_up, last_hl


# ── Season & VIX ─────────────────────────────────────────────────────────────

def _in_season() -> bool:
    return _dt.date.today().month not in _OFF_MONTHS


def _get_vix() -> float | None:
    try:
        v = yf.Ticker("^VIX").history(period="5d", interval="1d")
        return float(v["Close"].iloc[-1])
    except Exception:
        return None


# ── Signal label ─────────────────────────────────────────────────────────────

def _signal_label(score: int, threshold: int, overbought: bool,
                  below_200: bool) -> tuple[str, str]:
    """Return (label, color)."""
    if below_200:
        return "⛔  EXIT — Trend Break (price < SMA 200)", "red"
    if overbought and score >= threshold:
        return "⏸️  WAIT — Overbought (no new longs)", "orange"
    if score >= 6:
        return "💪  STRONG BUY / ADD MORE", "green"
    if score == 5:
        return "✅  BUY", "green"
    if score == threshold:        # 4 in-season or 5 off-season
        return "🟡  BUY — Borderline", "green"
    if score == 3:
        return "👀  WATCH — Approaching Threshold", "orange"
    if score in (1, 2):
        return "✂️  TRIM / REDUCE", "orange"
    return "🔴  EXIT / CASH", "red"


# ── Main evaluation ───────────────────────────────────────────────────────────

def evaluate(ticker: str) -> dict:
    """
    Full weight-of-evidence evaluation for *ticker*.
    Returns a dict with scores, details, signal, confidence, and stop level.
    """
    df = _fetch(ticker)
    if len(df) < 250:
        return {"error": f"Not enough price history for {ticker}. Need ≥250 bars."}

    close = df["close"]

    # ── Compute indicators ────────────────────────────────────────────────────
    sma200      = _sma(close, 200)
    sma50       = _sma(close, 50)
    macd_line, sig_line = _macd(close)
    rsi         = _rsi(close)
    kelt_mid, kelt_up, kelt_dn = _keltner(df)
    candle_val, candle_name = _candle_score(df)
    vix         = _get_vix()
    is_up, last_hl = _hh_hl(df)
    season      = _in_season()
    threshold   = THRESHOLD_IN_SEASON if season else THRESHOLD_OFF_SEASON

    # ── Latest values ─────────────────────────────────────────────────────────
    px        = float(close.iloc[-1])
    sma200v   = float(sma200.iloc[-1])
    sma50_now = float(sma50.iloc[-1])
    sma50_3d  = float(sma50.iloc[-1 - MACD_SLOPE_DAYS])
    macd_now  = float(macd_line.iloc[-1])
    macd_3d   = float(macd_line.iloc[-1 - MACD_SLOPE_DAYS])
    sig_now   = float(sig_line.iloc[-1])
    rsi_val   = float(rsi.iloc[-1])
    km        = float(kelt_mid.iloc[-1])
    ku        = float(kelt_up.iloc[-1])

    # ── Score each indicator ──────────────────────────────────────────────────
    scores  = {}
    details = {}

    # 1 · Price vs SMA 200
    if px > sma200v:
        scores["price_sma200"] = 1
        details["price_sma200"] = (
            "indicator", 1,
            f"Price ${px:,.2f} > SMA200 ${sma200v:,.2f}",
        )
    else:
        scores["price_sma200"] = -1
        details["price_sma200"] = (
            "indicator", -1,
            f"Price ${px:,.2f} < SMA200 ${sma200v:,.2f}  ← hard exit trigger",
        )

    # 2 · SMA 50 slope (3-day)
    if sma50_now > sma50_3d:
        scores["sma50"] = 1
        details["sma50"] = (
            "indicator", 1,
            f"SMA50 rising  {sma50_3d:,.2f} → {sma50_now:,.2f}",
        )
    else:
        scores["sma50"] = -1
        details["sma50"] = (
            "indicator", -1,
            f"SMA50 falling  {sma50_3d:,.2f} → {sma50_now:,.2f}",
        )

    # 3 · MACD: slope rising (3-day) AND above signal line
    macd_slope_up  = macd_now > macd_3d
    macd_above_sig = macd_now > sig_now
    if macd_slope_up and macd_above_sig:
        scores["macd"] = 1
        details["macd"] = (
            "indicator", 1,
            f"MACD slope ↑ & above signal  (MACD {macd_now:.4f} > sig {sig_now:.4f})",
        )
    elif not macd_slope_up and not macd_above_sig:
        scores["macd"] = -1
        details["macd"] = (
            "indicator", -1,
            f"MACD slope ↓ & below signal  (MACD {macd_now:.4f} < sig {sig_now:.4f})",
        )
    else:
        scores["macd"] = 0
        details["macd"] = (
            "indicator", 0,
            f"MACD mixed  slope {'↑' if macd_slope_up else '↓'},  "
            f"{'above' if macd_above_sig else 'below'} signal",
        )

    # 4 · RSI (14)
    if 50 <= rsi_val < 70:
        scores["rsi"] = 1
        details["rsi"] = ("indicator", 1, f"RSI {rsi_val:.1f}  (bullish zone 50–70)")
    elif rsi_val < 50:
        scores["rsi"] = -1
        details["rsi"] = ("indicator", -1, f"RSI {rsi_val:.1f}  (below 50 — bearish)")
    else:
        scores["rsi"] = 0
        details["rsi"] = ("indicator", 0, f"RSI {rsi_val:.1f}  (≥ 70 overbought — no new longs)")

    # 5 · Keltner location
    if km < px < ku:
        scores["keltner"] = 1
        details["keltner"] = (
            "indicator", 1,
            f"Price ${px:,.2f} between mid ${km:,.2f} and upper ${ku:,.2f}",
        )
    elif px <= km:
        scores["keltner"] = -1
        details["keltner"] = (
            "indicator", -1,
            f"Price ${px:,.2f} below Keltner midline ${km:,.2f}",
        )
    else:
        scores["keltner"] = 0
        details["keltner"] = (
            "indicator", 0,
            f"Price ${px:,.2f} at/above upper band ${ku:,.2f} — extended",
        )

    # 6 · VIX
    if vix is None:
        scores["vix"] = 0
        details["vix"] = ("indicator", 0, "VIX unavailable")
    elif vix < VIX_LIMIT:
        scores["vix"] = 1
        details["vix"] = ("indicator", 1, f"VIX {vix:.1f}  < {VIX_LIMIT}  (calm market)")
    else:
        scores["vix"] = -1
        details["vix"] = ("indicator", -1, f"VIX {vix:.1f}  ≥ {VIX_LIMIT}  (high volatility — avoid new longs)")

    # 7 · Candlestick pattern
    if candle_val == 1:
        scores["candle"] = 1
        details["candle"] = ("indicator", 1, f"Bullish pattern: {candle_name}")
    elif candle_val == -1:
        scores["candle"] = -1
        details["candle"] = ("indicator", -1, f"Bearish pattern: {candle_name}")
    else:
        scores["candle"] = 0
        details["candle"] = ("indicator", 0, "No significant candlestick pattern")

    # ── Totals & signal ───────────────────────────────────────────────────────
    total      = sum(scores.values())
    confidence = max(0, round(total / MAX_SCORE * 100))
    overbought = rsi_val >= 70 or px >= ku
    below_200  = px < sma200v
    signal, sig_color = _signal_label(total, threshold, overbought, below_200)

    # ── Swing-structure stop ──────────────────────────────────────────────────
    stop_note = (
        f"${last_hl:,.2f}  (last Higher Low)"
        if is_up else
        f"${last_hl:,.2f}  (recent 10-day low — no HH/HL confirmed yet)"
    )

    return {
        "ticker":      ticker,
        "price":       px,
        "total":       total,
        "max":         MAX_SCORE,
        "confidence":  confidence,
        "signal":      signal,
        "sig_color":   sig_color,
        "threshold":   threshold,
        "in_season":   season,
        "overbought":  overbought,
        "below_200":   below_200,
        "scores":      scores,
        "details":     details,
        "is_hh_hl":    is_up,
        "stop":        stop_note,
        "vix":         vix,
        "candle_name": candle_name,
        "sma200":      sma200v,
        "rsi":         rsi_val,
        "kelt_up":     ku,
        "kelt_mid":    km,
    }


# ── Pullback Entry Signal — 6-condition green heart check ─────────────────────

_PULLBACK_ZONE_PCT = 3.0    # price within 3% above EMA20 or SMA50 = "at the MA"
_MACD_SLOPE_W_DAYS = 2      # weekly MACD slope measured over 2 weekly bars

def check_pullback_entry(ticker: str) -> dict:
    """
    Evaluate 6 conditions for the TQQQ pullback-entry setup:

    Weekly (trend filter — must pass all 3 first):
      W1  Price > 20-week EMA
      W2  Weekly MACD slope rising (MACD line higher than 2 bars ago)
      W3  Weekly RSI > 50

    Daily (entry timing — all 3 must also pass):
      D1  Price pulled back to 20-day EMA or 50-day SMA
           (within PULLBACK_ZONE_PCT % above the MA — i.e. at/near the level)
      D2  Daily MACD slope rising (MACD line higher than MACD_SLOPE_DAYS bars ago)
      D3  Daily RSI > 45

    Returns dict with:
      signal   (bool)  — True if all 6 pass
      w_pass   (bool)  — True if weekly block passes
      d_pass   (bool)  — True if daily block passes
      conditions (list of dicts)  — label, passed, detail for each condition
    """
    conditions = []

    # ── Daily data (already fetched by evaluate(); re-fetch here for independence) ──
    df_d = _fetch(ticker, period="1y")
    if df_d.empty or len(df_d) < 60:
        return {"signal": False, "w_pass": False, "d_pass": False,
                "conditions": [], "error": "Insufficient daily data"}

    close_d = df_d["close"]
    px      = float(close_d.iloc[-1])

    ema20_d  = _ema(close_d, 20)
    sma50_d  = _sma(close_d, 50)
    macd_d, _ = _macd(close_d)
    rsi_d    = _rsi(close_d)

    ema20_d_v = float(ema20_d.iloc[-1])
    sma50_d_v = float(sma50_d.dropna().iloc[-1])
    macd_d_now = float(macd_d.iloc[-1])
    macd_d_prev= float(macd_d.iloc[-1 - MACD_SLOPE_DAYS])
    rsi_d_v   = float(rsi_d.dropna().iloc[-1])

    # D1 — Pullback to EMA20 or SMA50 (price within PULLBACK_ZONE_PCT % above)
    near_ema20 = ema20_d_v > 0 and 0 <= (px - ema20_d_v) / ema20_d_v * 100 <= _PULLBACK_ZONE_PCT
    near_sma50 = sma50_d_v > 0 and 0 <= (px - sma50_d_v) / sma50_d_v * 100 <= _PULLBACK_ZONE_PCT
    d1 = near_ema20 or near_sma50
    _d1_which  = ("EMA20" if near_ema20 else "") + (" & SMA50" if (near_ema20 and near_sma50) else ("SMA50" if near_sma50 else ""))
    conditions.append({
        "key": "D1", "label": "Daily: Pullback to EMA20 or SMA50",
        "passed": d1,
        "detail": (f"Price ${px:.2f} within {_PULLBACK_ZONE_PCT}% of {_d1_which}"
                   if d1 else f"Price ${px:.2f} not near EMA20 ${ema20_d_v:.2f} or SMA50 ${sma50_d_v:.2f}"),
    })

    # D2 — Daily MACD slope rising
    d2 = macd_d_now > macd_d_prev
    conditions.append({
        "key": "D2", "label": "Daily: MACD slope rising",
        "passed": d2,
        "detail": f"MACD {macd_d_prev:.4f} → {macd_d_now:.4f} {'↑' if d2 else '↓'}",
    })

    # D3 — Daily RSI > 45 (pullback-friendly: RSI 45–49 is a valid dip in an uptrend)
    d3 = rsi_d_v > 45
    conditions.append({
        "key": "D3", "label": "Daily: RSI > 45",
        "passed": d3,
        "detail": f"RSI {rsi_d_v:.1f}",
    })

    # ── Weekly data ──────────────────────────────────────────────────────────────
    try:
        raw_w = yf.download(ticker, period="3y", interval="1wk",
                            progress=False, auto_adjust=True)
        if raw_w.empty or len(raw_w) < 30:
            raise ValueError("Not enough weekly bars")
        if isinstance(raw_w.columns, pd.MultiIndex):
            raw_w = raw_w.xs(ticker, axis=1, level=1) \
                    if ticker in raw_w.columns.get_level_values(1) \
                    else raw_w.droplevel(1, axis=1)
        raw_w.columns = [c.lower() for c in raw_w.columns]
        close_w = raw_w["close"].dropna()

        ema20_w   = _ema(close_w, 20)
        macd_w, _ = _macd(close_w)
        rsi_w     = _rsi(close_w)

        px_w        = float(close_w.iloc[-1])
        ema20_w_v   = float(ema20_w.dropna().iloc[-1])
        macd_w_now  = float(macd_w.dropna().iloc[-1])
        macd_w_prev = float(macd_w.dropna().iloc[-1 - _MACD_SLOPE_W_DAYS])
        rsi_w_v     = float(rsi_w.dropna().iloc[-1])
        weekly_ok   = True
    except Exception as exc:
        weekly_ok   = False
        ema20_w_v = macd_w_now = macd_w_prev = rsi_w_v = 0.0
        px_w = px

    # W1 — Price > 20-week EMA
    w1 = weekly_ok and px_w > ema20_w_v
    conditions.append({
        "key": "W1", "label": "Weekly: Price > 20-week EMA",
        "passed": w1,
        "detail": (f"Price ${px_w:.2f} > EMA20w ${ema20_w_v:.2f}"
                   if w1 else f"Price ${px_w:.2f} ≤ EMA20w ${ema20_w_v:.2f}"),
    })

    # W2 — Weekly MACD slope rising
    w2 = weekly_ok and macd_w_now > macd_w_prev
    conditions.append({
        "key": "W2", "label": "Weekly: MACD slope rising",
        "passed": w2,
        "detail": (f"MACD {macd_w_prev:.4f} → {macd_w_now:.4f} ↑"
                   if w2 else f"MACD {macd_w_prev:.4f} → {macd_w_now:.4f} ↓"),
    })

    # W3 — Weekly RSI > 50
    w3 = weekly_ok and rsi_w_v > 50
    conditions.append({
        "key": "W3", "label": "Weekly: RSI > 50",
        "passed": w3,
        "detail": f"Weekly RSI {rsi_w_v:.1f}",
    })

    d_pass = d1 and d2 and d3
    w_pass = w1 and w2 and w3
    return {
        "signal":     d_pass and w_pass,
        "w_pass":     w_pass,
        "d_pass":     d_pass,
        "conditions": conditions,   # order: D1 D2 D3 W1 W2 W3
    }


# ── Indicator display labels ──────────────────────────────────────────────────

INDICATOR_LABELS = {
    "price_sma200": "1 · Price vs SMA 200",
    "sma50":        "2 · SMA 50 Slope (3-day)",
    "macd":         "3 · MACD Slope + vs Signal",
    "rsi":          "4 · RSI (14)",
    "keltner":      "5 · Keltner Location",
    "vix":          "6 · VIX < 31",
    "candle":       "7 · Candlestick Pattern",
}
