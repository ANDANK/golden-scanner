# scanners/overkill_check.py — "OverKill" tab (Market Overview)
#
# Approximates Overkill Trading's WaveTrend-dot + Volume-Profile confluence
# setup on any user-supplied ticker(s), or scans a whole universe for them:
#
#   - WaveTrend oscillator (LazyBear's public formula — the same base engine
#     most "money-flow dot" indicators are built on) computed on Weekly bars
#     (and Monthly, when there's enough history). A dot only counts when the
#     wt1/wt2 cross lands inside the overbought/oversold zone, matching
#     "Green Dot in oversold territory" / "Red Dot in overbought territory".
#   - Volume Profile (POC / VAH / VAL / HVN / LVN) approximated from trailing
#     daily Close/High/Low/Volume, since yfinance has no true volume-at-price
#     feed — each day's volume is spread across the price bins its High-Low
#     range touches.
#   - 400-period MA overlay (he leans on this a lot) — plotted as an expanding
#     average from whatever bars exist so it appears for every ticker (young
#     names like PLTR won't have a true 400-bar average for a few more years,
#     but the line still renders and converges over time).
#   - Verdict column combines two reads: (1) does the current price sit at a
#     Volume-Profile level with room to run (POC/VAH/VAL positioning), and
#     (2) did the qualifying dot itself print at a key level or in isolation
#     (his "Golden Rule" — an isolated dot elsewhere is chop risk).
#
# This is a best-effort open-source approximation of a paid/proprietary
# indicator — dot timing should track his tool closely but won't be
# pixel-identical, and the Volume Profile is a daily-bar approximation,
# not tick-level volume-at-price data.

from __future__ import annotations
import sys, os, re
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scanners import scan_history
from scanners.ui_tables import sortable_table_html
from config import (
    GOLD, BG_DARK, BG_PANEL, ACCENT_BLUE, ACCENT_GREEN, ACCENT_RED,
    TEXT_PRIMARY, TEXT_MUTED, BORDER_COLOR,
    FTF_UNIVERSE, MTPA_200, SP500_SAMPLE,
)
from utils import calc_ema, calc_sma
from data_loader import get_price_history, prefetch_tickers

PURPLE = "#A78BFA"
SMA9_COLOR  = "#FACC15"  # yellow
SMA20_COLOR = "#22D3EE"  # aqua
SMA50_COLOR = "#F97316"  # orange — aqua's taken by SMA20, needs its own distinct color

# ── WaveTrend params (LazyBear's public "WaveTrend Oscillator" formula) ────
WT_CHANNEL_LEN = 9
WT_AVG_LEN     = 12
WT_MA_LEN      = 3
WT_OB_LEVEL    = 53      # dots need the cross to land beyond this
WT_OS_LEVEL    = -53

MA_LEN            = 400   # "he leans on the 400 MA a lot"
VP_LOOKBACK_DAYS  = 1260  # ~5y of daily bars behind the volume profile — spans
                         # multiple market cycles instead of just whichever
                         # regime happened to fall in a shorter trailing window
VP_FETCH_PERIOD   = "5y"  # daily fetch period must cover VP_LOOKBACK_DAYS
VP_BINS           = 24
CONFLUENCE_TOL    = 0.02  # 2% of price counts as "at" a level
MAX_TICKERS       = 30

# Money Flow Index — soft confirmation layer for dots (volume-weighted RSI).
# Doesn't filter anything out; a dot just gets a 💰 badge next to the ticker
# when MF agrees (oversold for a green dot, overbought for a red dot).
MFI_PERIOD    = 14
MFI_OS_LEVEL  = 20
MFI_OB_LEVEL  = 80

# ── Universe scan (screener mode) ────────────────────────────────────────────
_SCAN_UNIVERSE_CHOICES = {
    "FTF Universe (~480 · full S&P 500 + ETFs)": FTF_UNIVERSE,
    "MTPA 200 (stock-heavy)": MTPA_200,
    "S&P 500 sample (200)": SP500_SAMPLE[:200],
}
DEFAULT_WEEKLY_FRESH_BARS  = 6   # "fresh" weekly dot = within the last N weekly bars
DEFAULT_MONTHLY_FRESH_BARS = 3   # "fresh" monthly dot = within the last N monthly bars
# Relaxed from 4/2 (2026-07) — a WT dot is already a strict event (WT2 <= -53
# at the cross), so a narrow recency window on top of that was crushing the
# fresh-tier counts in Scan Universe. Widening the window doesn't touch the
# dot definition, Volume Profile, or star tiers, so backtest results already
# gathered against those still hold — this only changes which of the SAME
# dots count as "recent enough" to surface. Still user-adjustable per run
# (1-20 weekly / 1-12 monthly) regardless of this default.

_DEFAULT_MANUAL_TICKERS = (
    "TSLA, MU, AAPL, MSFT, AMZN, SOXL, TQQQ, QQQ, PLTR, ASTS, CRWV, NVDA, "
    "TTD, CVS, AXON, INTC, AVAV, OKTA, ZS, QCOM, META, RBLX, AMD, MCD"
)


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{alpha})"


def _split_tickers(raw: str) -> list[str]:
    """Comma AND/OR whitespace separated — 'AAPL, MSFT TSLA,QQQ' all work."""
    return [t.upper() for t in re.split(r"[,\s]+", raw.strip()) if t]


# ── WaveTrend ────────────────────────────────────────────────────────────────
def _wavetrend(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    hlc3 = (df["High"].squeeze() + df["Low"].squeeze() + df["Close"].squeeze()) / 3.0
    esa = calc_ema(hlc3, WT_CHANNEL_LEN)
    d = calc_ema((hlc3 - esa).abs(), WT_CHANNEL_LEN).replace(0, np.nan)
    ci = (hlc3 - esa) / (0.015 * d)
    wt1 = calc_ema(ci, WT_AVG_LEN)
    wt2 = wt1.rolling(WT_MA_LEN, min_periods=1).mean()
    return wt1, wt2


def _wt_dots(wt1: pd.Series, wt2: pd.Series) -> pd.DataFrame:
    """Green/red dot at every wt1/wt2 cross that lands beyond the OB/OS zone."""
    cross_up = (wt1 > wt2) & (wt1.shift(1) <= wt2.shift(1))
    cross_dn = (wt1 < wt2) & (wt1.shift(1) >= wt2.shift(1))
    out = pd.DataFrame(index=wt1.index)
    out["green"] = (cross_up & (wt2 <= WT_OS_LEVEL)).fillna(False)
    out["red"]   = (cross_dn & (wt2 >= WT_OB_LEVEL)).fillna(False)
    return out


# ── Divergence — "light/liberal" by design: a small pivot_order (2) means a
# bar only has to be the local extreme within +/-2 bars to count, and only the
# two MOST RECENT pivots need to disagree with price — no requirement that
# the divergence be large or that a whole pattern of swings lines up. This
# catches a reversal warning early, before WT1/WT2 even cross into a dot.
DIVERGENCE_PIVOT_ORDER = 2
DIVERGENCE_LOOKBACK_WEEKLY  = 26   # ~6 months of weekly bars
DIVERGENCE_LOOKBACK_MONTHLY = 12   # ~1 year of monthly bars


def _pivot_lows(series: pd.Series, order: int) -> list:
    win = 2 * order + 1
    roll_min = series.rolling(win, center=True, min_periods=win).min()
    return list(series.index[series == roll_min])


def _pivot_highs(series: pd.Series, order: int) -> list:
    win = 2 * order + 1
    roll_max = series.rolling(win, center=True, min_periods=win).max()
    return list(series.index[series == roll_max])


def _detect_divergence(df: pd.DataFrame, wt1: pd.Series, lookback_bars: int,
                       order: int = DIVERGENCE_PIVOT_ORDER) -> str | None:
    """'bullish' if price's two most recent swing lows (within `lookback_bars`)
    make a LOWER low while WT1 makes a HIGHER low at those same two points;
    'bearish' for the mirror-image swing-high case. None otherwise. Pivots
    are found over the FULL series (so the rolling window isn't distorted by
    truncation) then filtered down to the recent window."""
    close = df["Close"].squeeze()
    if len(close) < order * 2 + 3:
        return None
    since_ts = close.index[max(0, len(close) - lookback_bars)]

    lows = [t for t in _pivot_lows(close, order) if t >= since_ts]
    if len(lows) >= 2:
        t1, t2 = lows[-2], lows[-1]
        if close.loc[t2] < close.loc[t1] and wt1.loc[t2] > wt1.loc[t1]:
            return "bullish"

    highs = [t for t in _pivot_highs(close, order) if t >= since_ts]
    if len(highs) >= 2:
        t1, t2 = highs[-2], highs[-1]
        if close.loc[t2] > close.loc[t1] and wt1.loc[t2] < wt1.loc[t1]:
            return "bearish"

    return None


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's-smoothed RSI, full series (utils.calc_rsi only returns the
    latest scalar, which isn't enough to also plot/chart it if ever needed)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta.clip(upper=0))
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def _macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    macd_line = calc_ema(close, 12) - calc_ema(close, 26)
    signal_line = calc_ema(macd_line, 9)
    return macd_line, signal_line, macd_line - signal_line


def _mfi(df: pd.DataFrame, period: int = MFI_PERIOD) -> pd.Series:
    """Money Flow Index — the standard public volume-weighted RSI. Used only
    as a soft confirmation flag on dots (never a filter)."""
    tp = (df["High"].squeeze() + df["Low"].squeeze() + df["Close"].squeeze()) / 3.0
    raw_mf = tp * df["Volume"].squeeze()
    tp_diff = tp.diff()
    pos_mf = raw_mf.where(tp_diff > 0, 0.0).rolling(period, min_periods=1).sum()
    neg_mf = raw_mf.where(tp_diff < 0, 0.0).rolling(period, min_periods=1).sum()
    mfr = pos_mf / neg_mf.replace(0, np.nan)
    return (100 - 100 / (1 + mfr)).fillna(50)


# ── Volume Profile (approximated from daily bars) ───────────────────────────
def _volume_profile(daily: pd.DataFrame, bins: int = VP_BINS) -> dict | None:
    df = daily.tail(VP_LOOKBACK_DAYS).dropna(subset=["High", "Low", "Volume"])
    if len(df) < 20:
        return None
    lo, hi = float(df["Low"].min()), float(df["High"].max())
    if not (hi > lo):
        return None

    edges = np.linspace(lo, hi, bins + 1)
    vols = np.zeros(bins)
    for h, l, v in zip(df["High"].to_numpy(), df["Low"].to_numpy(), df["Volume"].to_numpy()):
        if v <= 0 or not (h > l):
            continue
        i0 = min(max(int(np.searchsorted(edges, l, side="right") - 1), 0), bins - 1)
        i1 = min(max(int(np.searchsorted(edges, h, side="right") - 1), 0), bins - 1)
        if i0 == i1:
            vols[i0] += v
            continue
        span = h - l
        for i in range(i0, i1 + 1):
            overlap = max(0.0, min(h, edges[i + 1]) - max(l, edges[i]))
            vols[i] += v * (overlap / span)

    total = vols.sum()
    if total <= 0:
        return None

    poc_i = int(np.argmax(vols))
    lo_i = hi_i = poc_i
    covered = vols[poc_i]
    while covered < 0.70 * total and (lo_i > 0 or hi_i < bins - 1):
        left  = vols[lo_i - 1] if lo_i > 0 else -1.0
        right = vols[hi_i + 1] if hi_i < bins - 1 else -1.0
        if right >= left:
            hi_i += 1
            covered += vols[hi_i]
        else:
            lo_i -= 1
            covered += vols[lo_i]

    mids = (edges[:-1] + edges[1:]) / 2
    hvn, lvn = [], []
    for i in range(bins):
        left  = vols[i - 1] if i > 0 else 0.0
        right = vols[i + 1] if i < bins - 1 else 0.0
        if vols[i] > 0 and vols[i] >= left and vols[i] >= right:
            hvn.append((float(mids[i]), float(vols[i])))
        if vols[i] <= left and vols[i] <= right:
            lvn.append((float(mids[i]), float(vols[i])))
    hvn.sort(key=lambda x: -x[1])
    lvn.sort(key=lambda x: x[1])

    return dict(
        edges=edges, vols=vols, mids=mids,
        poc=float(mids[poc_i]), val=float(edges[lo_i]), vah=float(edges[hi_i + 1]),
        hvn=[p for p, _ in hvn[:5]], lvn=[p for p, _ in lvn[:5]],
        lo=lo, hi=hi,
    )


def _level_hits(price: float | None, vp: dict | None, ma_val: float | None) -> list[str]:
    if price is None or not np.isfinite(price):
        return []
    tol = abs(price) * CONFLUENCE_TOL
    hits = []
    if vp:
        if abs(price - vp["poc"]) <= tol:
            hits.append("POC")
        if abs(price - vp["val"]) <= tol:
            hits.append("VAL")
        if abs(price - vp["vah"]) <= tol:
            hits.append("VAH")
        if any(abs(price - h) <= tol for h in vp["hvn"]):
            hits.append("HVN")
    if ma_val is not None and np.isfinite(ma_val) and abs(price - ma_val) <= tol:
        hits.append(f"{MA_LEN}MA")
    return hits


def _mf_confirmed(color: str, ts, mfi_series: pd.Series | None) -> bool:
    if mfi_series is None or ts not in mfi_series.index or pd.isna(mfi_series.loc[ts]):
        return False
    val = float(mfi_series.loc[ts])
    return val <= MFI_OS_LEVEL if color == "Green" else val >= MFI_OB_LEVEL


def _last_dot(df: pd.DataFrame, dots: pd.DataFrame | None, ma_series: pd.Series | None,
              vp: dict | None, mfi_series: pd.Series | None = None) -> dict | None:
    if dots is None:
        return None
    greens = df.index[dots["green"].to_numpy()]
    reds   = df.index[dots["red"].to_numpy()]
    cands = [(ts, "Green") for ts in greens] + [(ts, "Red") for ts in reds]
    if not cands:
        return None
    ts, color = max(cands, key=lambda t: t[0])
    bar = df.loc[ts]
    price = float(bar["Low"]) if color == "Green" else float(bar["High"])
    ma_val = None
    if ma_series is not None and ts in ma_series.index and pd.notna(ma_series.loc[ts]):
        ma_val = float(ma_series.loc[ts])
    bars_ago = len(df.index) - 1 - df.index.get_loc(ts)
    return dict(date=pd.Timestamp(ts).date().isoformat(), color=color, price=price,
                hits=_level_hits(price, vp, ma_val), bars_ago=int(bars_ago),
                mf_confirmed=_mf_confirmed(color, ts, mfi_series))


def _last_green_dot(df: pd.DataFrame, dots: pd.DataFrame | None, ma_series: pd.Series | None,
                     vp: dict | None, mfi_series: pd.Series | None = None) -> dict | None:
    """Same as _last_dot but green-only — used by the Universe Scan, which is
    a long-side (green dot) screener and shouldn't have a more-recent red dot
    on the same ticker shadow out the green one that qualified it."""
    if dots is None:
        return None
    idx = df.index[dots["green"].to_numpy()]
    if len(idx) == 0:
        return None
    ts = idx[-1]
    bar = df.loc[ts]
    price = float(bar["Low"])
    ma_val = None
    if ma_series is not None and ts in ma_series.index and pd.notna(ma_series.loc[ts]):
        ma_val = float(ma_series.loc[ts])
    bars_ago = len(df.index) - 1 - df.index.get_loc(ts)
    return dict(date=pd.Timestamp(ts).date().isoformat(), color="Green", price=price,
                hits=_level_hits(price, vp, ma_val), bars_ago=int(bars_ago),
                mf_confirmed=_mf_confirmed("Green", ts, mfi_series))


def _last_red_dot(df: pd.DataFrame, dots: pd.DataFrame | None, ma_series: pd.Series | None,
                  vp: dict | None, mfi_series: pd.Series | None = None) -> dict | None:
    """Red-only mirror of _last_green_dot — short-side screener."""
    if dots is None:
        return None
    idx = df.index[dots["red"].to_numpy()]
    if len(idx) == 0:
        return None
    ts = idx[-1]
    bar = df.loc[ts]
    price = float(bar["High"])
    ma_val = None
    if ma_series is not None and ts in ma_series.index and pd.notna(ma_series.loc[ts]):
        ma_val = float(ma_series.loc[ts])
    bars_ago = len(df.index) - 1 - df.index.get_loc(ts)
    return dict(date=pd.Timestamp(ts).date().isoformat(), color="Red", price=price,
                hits=_level_hits(price, vp, ma_val), bars_ago=int(bars_ago),
                mf_confirmed=_mf_confirmed("Red", ts, mfi_series))


# ── Per-ticker analysis ──────────────────────────────────────────────────────
def _analyze_ticker(ticker: str) -> dict:
    ticker = ticker.strip().upper()
    try:
        weekly = get_price_history(ticker, period="max", interval="1wk")
        if weekly is None or weekly.empty:
            return {"ticker": ticker, "error": "no weekly data returned"}
        weekly = weekly.dropna(subset=["Open", "High", "Low", "Close"])
        if len(weekly) < 30:
            return {"ticker": ticker, "error": "not enough weekly history"}

        monthly = get_price_history(ticker, period="max", interval="1mo")
        if monthly is not None and not monthly.empty:
            monthly = monthly.dropna(subset=["Open", "High", "Low", "Close"])

        daily = get_price_history(ticker, period=VP_FETCH_PERIOD, interval="1d")
        if daily is not None and not daily.empty:
            daily = daily.dropna(subset=["Open", "High", "Low", "Close"])
        vp = _volume_profile(daily) if daily is not None and not daily.empty else None

        try:
            spy_close = get_price_history("SPY", period=VP_FETCH_PERIOD, interval="1d")["Close"].squeeze()
        except Exception:
            spy_close = pd.Series(dtype=float)
        scanners, stars = _run_best_scanner(daily, spy_close)

        weekly_close = weekly["Close"].squeeze()
        ma400_w = calc_sma(weekly_close, MA_LEN)
        sma9_w = calc_sma(weekly_close, 9)
        sma20_w = calc_sma(weekly_close, 20)
        sma50_w = calc_sma(weekly_close, 50)
        wt1_w, wt2_w = _wavetrend(weekly)
        dots_w = _wt_dots(wt1_w, wt2_w)
        rsi_w = float(_rsi(weekly_close).iloc[-1])
        mfi_w = _mfi(weekly)
        div_w = _detect_divergence(weekly, wt1_w, DIVERGENCE_LOOKBACK_WEEKLY)

        result = dict(
            ticker=ticker, weekly=weekly, monthly=None, daily=daily, vp=vp,
            wt1_w=wt1_w, wt2_w=wt2_w, dots_w=dots_w, ma400_w=ma400_w,
            sma9_w=sma9_w, sma20_w=sma20_w, sma50_w=sma50_w,
            wt1_m=None, wt2_m=None, dots_m=None, ma400_m=None,
            sma9_m=None, sma20_m=None, sma50_m=None,
            rsi_w=rsi_w, rsi_m=None, mfi_w=mfi_w, mfi_m=None, div_w=div_w, div_m=None,
            price_now=float(weekly_close.iloc[-1]),
            scanners=scanners, stars=stars,
        )

        if monthly is not None and len(monthly) >= 20:
            monthly_close = monthly["Close"].squeeze()
            ma400_m = calc_sma(monthly_close, MA_LEN)
            sma9_m = calc_sma(monthly_close, 9)
            sma20_m = calc_sma(monthly_close, 20)
            sma50_m = calc_sma(monthly_close, 50)
            wt1_m, wt2_m = _wavetrend(monthly)
            dots_m = _wt_dots(wt1_m, wt2_m)
            result.update(monthly=monthly, wt1_m=wt1_m, wt2_m=wt2_m, dots_m=dots_m, ma400_m=ma400_m,
                         sma9_m=sma9_m, sma20_m=sma20_m, sma50_m=sma50_m,
                         rsi_m=float(_rsi(monthly_close).iloc[-1]), mfi_m=_mfi(monthly),
                         div_m=_detect_divergence(monthly, wt1_m, DIVERGENCE_LOOKBACK_MONTHLY))

        result["last_w"] = _last_dot(weekly, dots_w, ma400_w, vp, mfi_w)
        result["last_m"] = (_last_dot(monthly, result["dots_m"], result["ma400_m"], vp, result["mfi_m"])
                             if result.get("dots_m") is not None else None)
        if result["last_w"] is not None:
            result["last_w"]["daily_confirmed"] = _daily_confirm(daily, result["last_w"]["color"])
        if result["last_m"] is not None:
            result["last_m"]["daily_confirmed"] = _daily_confirm(daily, result["last_m"]["color"])
        return result
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def _color_variant(base: dict, color: str) -> dict:
    """Shallow-derive a color-specific view of a full _analyze_ticker result
    (from the SAME already-fetched data — no extra network/compute), with
    last_w/last_m overridden to the most recent dot of just that color, so a
    ticker's more-recent opposite-color dot never shadows the one that
    qualified this particular row."""
    v = dict(base)
    dot_fn = _last_green_dot if color == "Green" else _last_red_dot
    v["last_w"] = dot_fn(base["weekly"], base["dots_w"], base["ma400_w"], base["vp"], base["mfi_w"])
    v["last_m"] = (dot_fn(base["monthly"], base["dots_m"], base["ma400_m"], base["vp"], base["mfi_m"])
                  if base.get("dots_m") is not None else None)
    if v["last_w"] is not None:
        v["last_w"]["daily_confirmed"] = _daily_confirm(base.get("daily"), color)
    if v["last_m"] is not None:
        v["last_m"]["daily_confirmed"] = _daily_confirm(base.get("daily"), color)
    return v


def _scan_universe(universe: list[str], weekly_fresh: int, monthly_fresh: int,
                   progress_cb=None) -> list[dict]:
    """Phase 1 of the Universe Scan — cheap pass (weekly + monthly WaveTrend
    only, no daily/Volume-Profile fetch) over the whole universe.

    Qualification is WEEKLY-ONLY now, and uses _last_dot (the single most
    recent dot of EITHER color, not a color-specific lookup): a ticker
    qualifies as green only if its single most recent weekly dot is green
    AND fresh. This fixes two things at once:
      1. A fresh MONTHLY dot could previously admit a ticker whose WEEKLY
         dot was long stale (e.g. 27 bars ago) — confusing, since the table
         displays weekly-first. Monthly no longer gates admission at all.
      2. A stale-but-still-in-window green dot could previously qualify a
         ticker even after a MORE RECENT red dot had since printed on the
         same weekly series — i.e. the picture had already flipped bearish.
         Using _last_dot (max-by-date across both colors) makes that
         impossible: if a red dot is more recent, _last_dot returns red,
         so the earlier green dot can no longer qualify the ticker.
    Monthly is still computed (for the Monthly Dot column + the 🎯
    dual-timeframe badge, also using _last_dot for the same supersession
    logic) but plays no role in whether a ticker is included at all.
    """
    prefetch_tickers(universe, "max", "1wk")
    prefetch_tickers(universe, "max", "1mo")

    candidates = []
    total = len(universe)
    for i, ticker in enumerate(universe):
        if progress_cb and (i % 5 == 0 or i == total - 1):
            progress_cb(i, total, ticker)
        try:
            weekly = get_price_history(ticker, period="max", interval="1wk")
            if weekly is None or weekly.empty:
                continue
            weekly = weekly.dropna(subset=["Open", "High", "Low", "Close"])
            if len(weekly) < 30:
                continue
            wt1_w, wt2_w = _wavetrend(weekly)
            dots_w = _wt_dots(wt1_w, wt2_w)
            last_w = _last_dot(weekly, dots_w, None, None)
            fresh_w_green = last_w is not None and last_w["color"] == "Green" and last_w["bars_ago"] < weekly_fresh
            fresh_w_red   = last_w is not None and last_w["color"] == "Red"   and last_w["bars_ago"] < weekly_fresh

            fresh_m_green = fresh_m_red = False
            monthly = get_price_history(ticker, period="max", interval="1mo")
            if monthly is not None and not monthly.empty:
                monthly = monthly.dropna(subset=["Open", "High", "Low", "Close"])
                if len(monthly) >= 20:
                    wt1_m, wt2_m = _wavetrend(monthly)
                    dots_m = _wt_dots(wt1_m, wt2_m)
                    last_m = _last_dot(monthly, dots_m, None, None)
                    fresh_m_green = last_m is not None and last_m["color"] == "Green" and last_m["bars_ago"] < monthly_fresh
                    fresh_m_red   = last_m is not None and last_m["color"] == "Red"   and last_m["bars_ago"] < monthly_fresh

            has_green = fresh_w_green   # weekly-only gate — monthly no longer admits on its own
            has_red   = fresh_w_red
            if has_green or has_red:
                candidates.append(dict(
                    ticker=ticker, has_green=has_green, has_red=has_red,
                    both_fresh_green=fresh_w_green and fresh_m_green,
                    both_fresh_red=fresh_w_red and fresh_m_red,
                ))
        except Exception:
            continue

    return candidates


# ══════════════════════════════════════════════════════════════════════════════
# BACKTEST — validates the ★ system against real historical outcomes
# ══════════════════════════════════════════════════════════════════════════════
#
# For every historical dot in the lookback window: rebuild the Volume Profile
# using ONLY daily bars up to that dot's own date (no lookahead bias), compute
# what its ★ rating would have been at the time, then walk forward day-by-day
# to see whether price hit TP1 (POC), TP2 (VAH for a long / VAL for a short),
# or the stop (just past the nearest LVN) first — the strategy's own exits,
# not a substitute metric. Aggregating outcomes by ★ tier answers "does a
# 5★ dot actually win more than a 2★ one, historically?"

BACKTEST_LOOKBACK_YEARS = 5
BACKTEST_MAX_HOLD_DAYS  = 90     # ~4.5 months — a swing/position-trade horizon
BACKTEST_DAILY_PERIOD   = "10y"  # needs lookback + VP_LOOKBACK_DAYS of headroom
BACKTEST_SL_FALLBACK_PCT = 0.10  # used only if no LVN exists in the stop direction


def _enumerate_dots(df: pd.DataFrame, dots: pd.DataFrame, since: pd.Timestamp) -> list[dict]:
    """Every green/red dot on/after `since` — unlike _last_dot (most recent
    only), this returns the full history for backtesting."""
    out = []
    for ts in df.index[dots["green"].to_numpy()]:
        if ts >= since:
            out.append(dict(date=ts, color="Green", price=float(df.loc[ts, "Low"])))
    for ts in df.index[dots["red"].to_numpy()]:
        if ts >= since:
            out.append(dict(date=ts, color="Red", price=float(df.loc[ts, "High"])))
    out.sort(key=lambda d: d["date"])
    return out


def _historical_vp(daily: pd.DataFrame, as_of: pd.Timestamp) -> dict | None:
    """Volume Profile built only from bars up to `as_of` — the as-of-the-time
    reconstruction needed to backtest a historical dot without lookahead."""
    return _volume_profile(daily[daily.index <= as_of])


def _nearest_lvn(vp: dict, price: float, direction: str) -> float | None:
    """Nearest low-volume bin in `direction` ('below'/'above') from `price` —
    the strategy's own stop placement rule ('just past the LVN')."""
    mids, vols = vp["mids"], vp["vols"]
    positive = vols[vols > 0]
    if len(positive) == 0:
        return None
    threshold = float(np.median(positive)) * 0.4
    if direction == "below":
        cands = [m for m, v in zip(mids, vols) if m < price and v <= threshold]
        return max(cands) if cands else None
    cands = [m for m, v in zip(mids, vols) if m > price and v <= threshold]
    return min(cands) if cands else None


def _simulate_trade(daily: pd.DataFrame, entry_date: pd.Timestamp, color: str,
                    tp1: float, tp2: float, sl: float, max_hold_days: int) -> str:
    """Walks forward day-by-day (using daily High/Low) from the bar after
    `entry_date` for up to `max_hold_days`. Returns 'tp1', 'tp2', 'sl', or
    'expired'. A day that touches both a target and the stop is resolved in
    favor of the stop — the conservative assumption, since daily bars can't
    tell us which was actually touched first intraday."""
    future = daily[daily.index > entry_date].head(max_hold_days)
    for _, bar in future.iterrows():
        hi, lo = float(bar["High"]), float(bar["Low"])
        if color == "Green":
            if lo <= sl:
                return "sl"
            if hi >= tp2:
                return "tp2"
            if hi >= tp1:
                return "tp1"
        else:
            if hi >= sl:
                return "sl"
            if lo <= tp2:
                return "tp2"
            if lo <= tp1:
                return "tp1"
    return "expired"


def _backtest_ticker(ticker: str, lookback_years: int, max_hold_days: int) -> list[dict]:
    """Backtests every Weekly + Monthly dot for `ticker` over the trailing
    `lookback_years`. One record per dot tested."""
    records: list[dict] = []
    try:
        weekly  = get_price_history(ticker, period="max", interval="1wk")
        monthly = get_price_history(ticker, period="max", interval="1mo")
        daily   = get_price_history(ticker, period=BACKTEST_DAILY_PERIOD, interval="1d")
        if weekly is None or weekly.empty or daily is None or daily.empty:
            return records
        weekly = weekly.dropna(subset=["Open", "High", "Low", "Close"])
        daily  = daily.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
        if len(weekly) < 30 or len(daily) < 100:
            return records

        since = pd.Timestamp.now() - pd.DateOffset(years=lookback_years)

        for label, df in (("Weekly", weekly), ("Monthly", monthly)):
            if df is None or df.empty:
                continue
            df = df.dropna(subset=["Open", "High", "Low", "Close"])
            if len(df) < 20:
                continue
            wt1, wt2 = _wavetrend(df)
            dots = _wt_dots(wt1, wt2)
            mfi = _mfi(df)
            ma400 = calc_sma(df["Close"].squeeze(), MA_LEN)

            for d in _enumerate_dots(df, dots, since):
                ts, color, price = d["date"], d["color"], d["price"]
                vp = _historical_vp(daily, ts)
                if vp is None:
                    continue
                ma_val = float(ma400.loc[ts]) if ts in ma400.index and pd.notna(ma400.loc[ts]) else None
                hits = _level_hits(price, vp, ma_val)
                close_at_dot = float(df.loc[ts, "Close"])
                stars = _verdict_stars(dict(color=color, hits=hits), close_at_dot, vp)

                if color == "Green":
                    tp1, tp2, sl_dir = vp["poc"], vp["vah"], "below"
                else:
                    tp1, tp2, sl_dir = vp["poc"], vp["val"], "above"
                lvn = _nearest_lvn(vp, price, sl_dir)
                pad = (vp["vah"] - vp["val"]) * 0.02
                if lvn is not None:
                    sl = lvn - pad if color == "Green" else lvn + pad
                else:
                    sl = price * (1 - BACKTEST_SL_FALLBACK_PCT) if color == "Green" \
                        else price * (1 + BACKTEST_SL_FALLBACK_PCT)

                outcome = _simulate_trade(daily, ts, color, tp1, tp2, sl, max_hold_days)
                records.append(dict(
                    ticker=ticker, timeframe=label, date=ts.date().isoformat(),
                    color=color, stars=stars, confirmed=bool(hits), outcome=outcome,
                ))
    except Exception:
        pass
    return records


def _run_backtest(universe: list[str], lookback_years: int, max_hold_days: int,
                  progress_cb=None) -> list[dict]:
    prefetch_tickers(universe, "max", "1wk")
    prefetch_tickers(universe, "max", "1mo")
    prefetch_tickers(universe, BACKTEST_DAILY_PERIOD, "1d")

    all_records: list[dict] = []
    total = len(universe)
    for i, ticker in enumerate(universe):
        if progress_cb and (i % 5 == 0 or i == total - 1):
            progress_cb(i, total, ticker)
        all_records.extend(_backtest_ticker(ticker, lookback_years, max_hold_days))
    return all_records


def _aggregate_backtest(records: list[dict]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    rows = []
    for stars, grp in df.groupby("stars"):
        n = len(grp)
        tp1 = int((grp["outcome"] == "tp1").sum())
        tp2 = int((grp["outcome"] == "tp2").sum())
        sl  = int((grp["outcome"] == "sl").sum())
        exp = int((grp["outcome"] == "expired").sum())
        decided = tp1 + tp2 + sl
        win_rate = (tp1 + tp2) / decided * 100 if decided else float("nan")
        rows.append(dict(stars=int(stars), n=n, tp1=tp1, tp2=tp2, sl=sl, expired=exp,
                         win_rate=win_rate))
    return pd.DataFrame(rows).sort_values("stars", ascending=False).reset_index(drop=True)


def _vp_position(price: float | None, vp: dict | None, color: str | None = None) -> tuple[str, str]:
    """Directional read of CURRENT price vs the Volume Profile — mirrors
    _verdict_stars' pos thresholds (0 / 0.4 / 0.75) exactly, so the text and
    the star rating never contradict each other.

    Without a `color` (no dot to judge this against — e.g. before any dot
    has ever printed) the read stays neutral/descriptive only: no
    "good"/"bad" framing, since there's no direction to judge it against.
    With a color, phrasing matches what the backtest showed: for a Green/
    long dot, price already through fair value toward/past VAH is strength
    (trend continuation), while price that's broken back below VAL is the
    warning case. The mirror holds for a Red/short dot around VAL/VAH."""
    if price is None or vp is None or not np.isfinite(price):
        return "— no VP data", TEXT_MUTED
    poc, val, vah = vp["poc"], vp["val"], vp["vah"]
    tol = price * CONFLUENCE_TOL

    if color is None:
        if price < val:
            return f"Below VAL (${val:.2f})", TEXT_MUTED
        if abs(price - poc) <= tol:
            return f"⚖️ At POC (${poc:.2f})", GOLD
        if price < poc:
            return f"Between VAL and POC (${val:.2f}–${poc:.2f})", TEXT_MUTED
        if price <= vah:
            return f"Between POC and VAH (${poc:.2f}–${vah:.2f})", TEXT_MUTED
        return f"Above VAH (${vah:.2f})", TEXT_MUTED

    span = vah - val
    pos = (price - val) / span if color == "Green" else (vah - price) / span
    confirm_name, confirm_lvl = ("VAL", val) if color == "Green" else ("VAH", vah)
    far_name, far_lvl = ("VAH", vah) if color == "Green" else ("VAL", val)

    if pos < 0:
        return f"⚠️ Broke back through {confirm_name} (${confirm_lvl:.2f})", ACCENT_RED
    if abs(price - poc) <= tol:
        return f"⚖️ At POC (${poc:.2f})", GOLD
    if pos < 0.4:
        return f"🎯 Near {confirm_name} (${confirm_lvl:.2f}) — unproven", GOLD
    if pos < 0.75:
        return f"➡️ Through POC, toward {far_name} (${far_lvl:.2f})", ACCENT_BLUE
    return f"💪 Extended past {far_name} (${far_lvl:.2f}) — trend continuation", ACCENT_GREEN


def _run_best_scanner(daily: pd.DataFrame | None, spy_close: pd.Series) -> tuple[list[str], int]:
    """Runs the exact same 6-scanner (+7Square/8Cross) evaluation as the Best
    Scanners tab, reusing the daily bars already fetched here for the Volume
    Profile — no extra fetch. Lazy import of scanners.home to dodge the
    circular import (home.py imports this module at module load time; by the
    time this function is actually CALLED, home.py is already fully loaded)."""
    if daily is None or daily.empty:
        return [], 0
    from scanners.home import _evaluate, _star_rating, _LABELS
    res = _evaluate(daily, spy_close)
    if res is None:
        return [], 0
    labels = res["labels"]
    scan_s = sorted(labels, key=lambda x: _LABELS.index(x))
    if res["snap"].get("x8_weekly") and "8Cross" in labels:
        scan_s = ["8Cross·W" if s == "8Cross" else s for s in scan_s]
    return scan_s, _star_rating(labels)


def _verdict_stars(last: dict | None, price_now: float | None, vp: dict | None) -> int:
    """0-5 power rating for the Verdict.

    Within a confirmed dot, stars grade where price sits relative to the
    level it confirmed at — corrected against a real backtest (MTPA 200 /
    S&P 500 sample / FTF ~480, 25/30/45/90-day holds) which showed the
    original "reward = room still left toward the far edge" framing was
    backwards: it scored "price has since crashed through VAL" the SAME as
    "fresh dot right at VAL" (both were unboundedly >= max reward), which
    buried a huge number of broken-support dots in the top tier. It also
    treated "price already extended past VAH" as "no room left" (worst
    tier) when empirically that was the BEST-performing case (~100% win
    rate, zero stop-outs) — a green dot confirming during an already-proven
    uptrend is a trend-continuation trade, not a "too late" trade.

    A second backtest round (after that fix) then showed confirmed-then-
    BROKEN (2 below) winning far less often than an isolated dot (7-10% vs
    38-52%, consistent across both universes) — a dot that had real
    confluence and then got invalidated is a stronger negative signal than
    a dot that never had confluence at all, so 1 and 2 are ordered with
    broken-confirmation as the worst tier, below isolated.
      0 = no recent dot
      1 = confirmed, but price has since broken the opposite structural
          level (e.g. a green dot whose VAL support has since given way) —
          empirically the WORST tier, well below isolated
      2 = isolated dot (no confluence when it printed) — weak/uninformative,
          but empirically beats an actively-broken confirmation
      3 = confirmed, price still between the confirming level and fair
          value (POC) — the traditional "textbook entry", not yet proven
      4 = confirmed, price has moved through fair value toward the far edge
      5 = confirmed, price at or beyond the far edge — confirmed strength /
          trend continuation, empirically the strongest tier
    """
    if last is None:
        return 0
    if not last["hits"]:
        return 2
    if price_now is None or vp is None or not np.isfinite(price_now):
        return 3
    val, vah = vp["val"], vp["vah"]
    span = vah - val
    if span <= 0:
        return 3
    # pos: 0 = at the confirming level, 1 = at the far edge, >1 = past the far
    # edge (proven strength), <0 = broken back through the confirming level
    pos = (price_now - val) / span if last["color"] == "Green" else (vah - price_now) / span
    if pos < 0:
        return 1
    if pos < 0.4:
        return 3
    if pos < 0.75:
        return 4
    return 5


def _verdict_cell(last: dict | None, price_now: float | None, vp: dict | None) -> str:
    bias_text, bias_color = _vp_position(price_now, vp, last["color"] if last else None)
    stars = _verdict_stars(last, price_now, vp)
    star_prefix = f'<span style="color:{GOLD}">{"★" * stars}</span> ' if stars else ""
    if last is None:
        conv_text, conv_color = "no recent dot", TEXT_MUTED
    elif last["hits"]:
        conv_text = f'🔥 {last["color"]} dot @ ' + "/".join(last["hits"])
        conv_color = ACCENT_GREEN if last["color"] == "Green" else ACCENT_RED
    else:
        conv_text, conv_color = "⚠️ isolated dot — chop risk", GOLD
    return (
        f'<div style="color:{bias_color};font-weight:700;font-size:11px;white-space:normal">'
        f'{star_prefix}{bias_text}</div>'
        f'<div style="color:{conv_color};font-size:9.5px;margin-top:2px;white-space:normal">{conv_text}</div>'
    )


# ── Chart ────────────────────────────────────────────────────────────────────
def _build_chart(result: dict, timeframe: str):
    if timeframe == "Monthly":
        df, wt1, wt2, dots, ma_series, sma9_series, sma20_series, sma50_series = (
            result.get("monthly"), result.get("wt1_m"), result.get("wt2_m"),
            result.get("dots_m"), result.get("ma400_m"), result.get("sma9_m"),
            result.get("sma20_m"), result.get("sma50_m"),
        )
    else:
        df, wt1, wt2, dots, ma_series, sma9_series, sma20_series, sma50_series = (
            result["weekly"], result["wt1_w"], result["wt2_w"],
            result["dots_w"], result["ma400_w"], result.get("sma9_w"),
            result.get("sma20_w"), result.get("sma50_w"),
        )
    if df is None or df.empty or wt1 is None:
        return None

    n = min(260, len(df))
    view = df.iloc[-n:]
    xs = view.index
    wt1_v, wt2_v = wt1.iloc[-n:], wt2.iloc[-n:]
    dots_v = dots.iloc[-n:]
    ma_v = ma_series.iloc[-n:] if ma_series is not None else None
    sma9_v = sma9_series.iloc[-n:] if sma9_series is not None else None
    sma20_v = sma20_series.iloc[-n:] if sma20_series is not None else None
    sma50_v = sma50_series.iloc[-n:] if sma50_series is not None else None
    vp = result.get("vp")
    ticker = result["ticker"]

    macd_ln, sig_ln, hist_s = _macd(df["Close"].squeeze())
    macd_ln, sig_ln, hist_s = macd_ln.iloc[-n:], sig_ln.iloc[-n:], hist_s.iloc[-n:]

    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.035,
                        row_heights=[0.44, 0.22, 0.19, 0.15])

    fig.add_trace(go.Candlestick(
        x=xs, open=view["Open"].squeeze(), high=view["High"].squeeze(),
        low=view["Low"].squeeze(), close=view["Close"].squeeze(),
        increasing_line_color=ACCENT_GREEN, decreasing_line_color=ACCENT_RED,
        increasing_fillcolor=_rgba(ACCENT_GREEN, 0.6), decreasing_fillcolor=_rgba(ACCENT_RED, 0.6),
        name=ticker,
    ), row=1, col=1)

    for series_v, color, label in [(sma9_v, SMA9_COLOR, "9-period MA"),
                                   (sma20_v, SMA20_COLOR, "20-period MA"),
                                   (sma50_v, SMA50_COLOR, "50-period MA")]:
        if series_v is not None and not series_v.dropna().empty:
            fig.add_trace(go.Scatter(x=xs, y=series_v, line=dict(color=color, width=1.3),
                                     name=label), row=1, col=1)

    if ma_v is not None and not ma_v.dropna().empty:
        fig.add_trace(go.Scatter(x=xs, y=ma_v, line=dict(color=PURPLE, width=2.2),
                                 name=f"{MA_LEN}-period MA"), row=1, col=1)

    if vp:
        for lvl, label, color, dash, width in [
            (vp["poc"], "POC", GOLD, "solid", 1.5),
            (vp["vah"], "VAH", ACCENT_BLUE, "dash", 1.0),
            (vp["val"], "VAL", ACCENT_BLUE, "dash", 1.0),
        ]:
            fig.add_hline(y=lvl, line=dict(color=color, width=width, dash=dash),
                         annotation_text=label, annotation_position="right",
                         annotation_font=dict(size=9, color=color), row=1, col=1)
        # Chart shows only the top 2 of each (by volume) to stay readable now that
        # they're labeled — the confluence check (_level_hits) still checks all 5.
        for lvl in vp["hvn"][:2]:
            fig.add_hline(y=lvl, line=dict(color=_rgba(GOLD, 0.45), width=0.7, dash="dot"),
                         annotation_text="HVN", annotation_position="right",
                         annotation_font=dict(size=8, color=_rgba(GOLD, 0.7)), row=1, col=1)
        for lvl in vp["lvn"][:2]:
            fig.add_hline(y=lvl, line=dict(color=_rgba(TEXT_MUTED, 0.55), width=0.6, dash="dot"),
                         annotation_text="LVN", annotation_position="right",
                         annotation_font=dict(size=8, color=_rgba(TEXT_MUTED, 0.8)), row=1, col=1)

    # WaveTrend "cloud" — two-tone fill between wt1/wt2, green when wt1>=wt2, red otherwise
    bull = (wt1_v >= wt2_v)
    for mask, color in [(bull, ACCENT_GREEN), (~bull, ACCENT_RED)]:
        fig.add_trace(go.Scatter(x=xs, y=wt2_v.where(mask), line=dict(width=0),
                                 showlegend=False, hoverinfo="skip"), row=2, col=1)
        fig.add_trace(go.Scatter(x=xs, y=wt1_v.where(mask), line=dict(width=0),
                                 fill="tonexty", fillcolor=_rgba(color, 0.20),
                                 showlegend=False, hoverinfo="skip"), row=2, col=1)

    fig.add_trace(go.Scatter(x=xs, y=wt1_v, line=dict(color=ACCENT_BLUE, width=1.4), name="WT1"), row=2, col=1)
    fig.add_trace(go.Scatter(x=xs, y=wt2_v, line=dict(color=GOLD, width=1.1), name="WT2"), row=2, col=1)
    for lvl, clr in [(WT_OB_LEVEL, ACCENT_RED), (WT_OS_LEVEL, ACCENT_GREEN), (0, _rgba(TEXT_MUTED, 0.5))]:
        fig.add_hline(y=lvl, line=dict(color=clr, width=0.7, dash="dot"), row=2, col=1)

    g_idx = xs[dots_v["green"].to_numpy()]
    r_idx = xs[dots_v["red"].to_numpy()]
    if len(g_idx):
        fig.add_trace(go.Scatter(x=g_idx, y=wt1_v.loc[g_idx], mode="markers",
                                 marker=dict(color=ACCENT_GREEN, size=10, symbol="circle",
                                             line=dict(color="white", width=1)),
                                 name="Green Dot"), row=2, col=1)
    if len(r_idx):
        fig.add_trace(go.Scatter(x=r_idx, y=wt1_v.loc[r_idx], mode="markers",
                                 marker=dict(color=ACCENT_RED, size=10, symbol="circle",
                                             line=dict(color="white", width=1)),
                                 name="Red Dot"), row=2, col=1)

    # MACD crossover (chart only, per request — not a table column)
    hist_colors = [ACCENT_GREEN if v >= 0 else ACCENT_RED for v in hist_s]
    fig.add_trace(go.Bar(x=xs, y=hist_s, marker_color=hist_colors, name="MACD Hist",
                        showlegend=False, opacity=0.85), row=3, col=1)
    fig.add_trace(go.Scatter(x=xs, y=macd_ln, line=dict(color=ACCENT_BLUE, width=1.3), name="MACD"), row=3, col=1)
    fig.add_trace(go.Scatter(x=xs, y=sig_ln, line=dict(color=GOLD, width=1.1), name="Signal"), row=3, col=1)
    fig.add_hline(y=0, line=dict(color=BORDER_COLOR, width=0.8, dash="dot"), row=3, col=1)

    # Volume bars — colored by that bar's own candle direction
    close_v, open_v = view["Close"].squeeze(), view["Open"].squeeze()
    vol_colors = [ACCENT_GREEN if c >= o else ACCENT_RED for c, o in zip(close_v, open_v)]
    fig.add_trace(go.Bar(x=xs, y=view["Volume"].squeeze(), marker_color=vol_colors, name="Volume",
                        showlegend=False, opacity=0.7), row=4, col=1)

    fig.update_layout(
        paper_bgcolor=BG_DARK, plot_bgcolor=BG_PANEL,
        font=dict(color=TEXT_PRIMARY, family="Inter, sans-serif", size=11),
        height=880, margin=dict(l=10, r=60, t=34, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                   bgcolor="rgba(0,0,0,0)", font=dict(size=10)),
        xaxis_rangeslider_visible=False, hovermode="x unified",
        title=dict(text=f"{ticker} — {timeframe}", font=dict(size=13, color=GOLD), x=0.01, y=0.99),
    )
    for i in (1, 2, 3, 4):
        fig.update_xaxes(gridcolor=BORDER_COLOR, row=i, col=1, showgrid=True)
        fig.update_yaxes(gridcolor=BORDER_COLOR, row=i, col=1, showgrid=True)
    fig.update_yaxes(title_text="Price", row=1, col=1, title_font=dict(size=10, color=TEXT_MUTED))
    fig.update_yaxes(title_text="WaveTrend", row=2, col=1, title_font=dict(size=10, color=TEXT_MUTED))
    fig.update_yaxes(title_text="MACD", row=3, col=1, title_font=dict(size=10, color=TEXT_MUTED))
    fig.update_yaxes(title_text="Volume", row=4, col=1, title_font=dict(size=10, color=TEXT_MUTED))
    return fig


# ── Ticker table (checkbox-select, scrollable) ──────────────────────────────
_TH = (f"color:{TEXT_MUTED};font-size:9px;font-weight:700;text-transform:uppercase;"
       f"letter-spacing:0.6px;padding:6px 10px;text-align:left;white-space:nowrap;"
       f"border-bottom:1.5px solid {BORDER_COLOR}")
_TABLE_RATIOS  = [0.28, 0.45, 0.55, 0.95, 0.55, 0.95, 0.55, 0.62, 1.3, 1.55]
_TABLE_HEADERS = ["", "Ticker", "Price", "Weekly Dot", "Weekly Age", "Monthly Dot", "Monthly Age",
                  "RSI", "Scanners", "Verdict"]
_ROW_HEIGHT_PX = 83   # calibrated against the Best Scanners table (~83px/row)
_MAX_VISIBLE_ROWS = 6


def _dot_compact(last: dict | None, fresh_threshold: int | None = None) -> str:
    """`fresh_threshold`, when given (Scan Universe only), dims the cell when
    this dot is OLDER than the lookback that would make it 'fresh' — makes it
    visually obvious when a row only qualified via divergence (or the other
    timeframe), not this dot. Bars-ago lives in its own column now (see
    _dot_age), not stacked into this cell."""
    if last is None:
        return f'<span style="color:{TEXT_MUTED}">—</span>'
    is_stale = fresh_threshold is not None and last["bars_ago"] >= fresh_threshold
    color = TEXT_MUTED if is_stale else (ACCENT_GREEN if last["color"] == "Green" else ACCENT_RED)
    icon = "🟢" if last["color"] == "Green" else "🔴"
    return (f'<span style="color:{color};font-weight:600">{icon} {last["date"]}</span><br>'
            f'<span style="color:{TEXT_MUTED};font-size:10px">${last["price"]:.2f}</span>')


def _dot_age(last: dict | None, fresh_threshold: int | None = None) -> str:
    """The 'Nb ago' + stale note that used to be stacked inside _dot_compact,
    now its own column."""
    if last is None:
        return f'<span style="color:{TEXT_MUTED}">—</span>'
    is_stale = fresh_threshold is not None and last["bars_ago"] >= fresh_threshold
    stale_note = " · stale" if is_stale else ""
    return f'<span style="color:{TEXT_MUTED};font-size:11px">{last["bars_ago"]}b ago{stale_note}</span>'


def _mf_badge(last: dict | None) -> str:
    """Money Flow soft confirmation — a small badge next to the ticker when
    the qualifying dot's Money Flow Index agrees (oversold for green,
    overbought for red). Absence of the badge doesn't mean anything is
    wrong — it's confirmation-when-present, never a filter."""
    if not last or not last.get("mf_confirmed"):
        return ""
    color = ACCENT_GREEN if last["color"] == "Green" else ACCENT_RED
    return (f' <span title="Money Flow confirms this dot" '
            f'style="color:{color};font-size:10px">💰</span>')


def _divergence_badge(div_w: str | None, div_m: str | None) -> str:
    """Small badge next to the ticker when a bullish/bearish WaveTrend
    divergence is present on either timeframe — catches a reversal warning
    even before WT1/WT2 actually cross into a dot."""
    div = div_w or div_m
    if not div:
        return ""
    icon = "📈" if div == "bullish" else "📉"
    color = ACCENT_GREEN if div == "bullish" else ACCENT_RED
    label = f"{div.capitalize()} divergence"
    return f' <span title="{label}" style="color:{color};font-size:10px">{icon}</span>'


def _dual_tf_badge(both_fresh: bool) -> str:
    """Small badge when a ticker has a FRESH confirmation on both Weekly AND
    Monthly at once (each independently inside its own lookback window) —
    the strongest confluence available, used in Scan Universe to rank these
    tickers ahead of a weekly-only match."""
    if not both_fresh:
        return ""
    return (f' <span title="Fresh on both Weekly and Monthly" '
            f'style="color:{GOLD};font-size:10px">🎯</span>')


def _daily_confirm(daily: pd.DataFrame | None, color: str) -> bool:
    """Daily-timeframe confirmation for a weekly/monthly dot: True if EITHER
    (1) the daily MACD histogram is aligned with the dot's direction (Hist>0
    for Green, Hist<0 for Red — MACD line above/below its own signal line,
    a crossover STATE not a fresh-cross event, regardless of the MACD line's
    own position relative to zero), OR (2) the daily EMA20/50 relationship
    just crossed in that direction. (2) mirrors Best Scanners' own 8Cross
    label, which is bullish-only (crossedD = EMA20 crossed above EMA50) — the
    Red-dot case needs the bearish mirror computed here since no such label
    exists upstream. Non-gating, informational only, like the other badges."""
    if daily is None or daily.empty or len(daily) < 60:
        return False
    from scanners.home import _ema, _macd
    close = daily["Close"].squeeze()
    _, _, hist = _macd(close)
    hist_v = float(hist.iloc[-1])
    hist_ok = hist_v > 0 if color == "Green" else hist_v < 0

    diff = _ema(close, 20) - _ema(close, 50)
    d_now = float(diff.iloc[-1])
    if color == "Green":
        cross_ok = d_now > 0 and float(diff.iloc[-7:-1].min()) <= 0
    else:
        cross_ok = d_now < 0 and float(diff.iloc[-7:-1].max()) >= 0

    return hist_ok or cross_ok


def _daily_confirm_badge(confirmed: bool) -> str:
    """Heart badge next to the star rating when the daily chart confirms the
    dot's direction (see _daily_confirm) — non-gating, informational only."""
    if not confirmed:
        return ""
    return (f' <span title="Daily MACD/EMA confirms this dot\'s direction" '
            f'style="font-size:10px">❤️</span>')


def _price_cell(price: float | None) -> str:
    if price is None or not np.isfinite(price):
        return f'<span style="color:{TEXT_MUTED}">—</span>'
    return f'<span style="font-family:\'DM Mono\',monospace;color:{TEXT_PRIMARY}">${price:,.2f}</span>'


def _rsi_color(val: float | None) -> str:
    """Green when 50-70 (his 'healthy uptrend' zone), red otherwise."""
    if val is None or not np.isfinite(val):
        return TEXT_MUTED
    return ACCENT_GREEN if 50 <= val <= 70 else ACCENT_RED


def _rsi_cell(rsi_w: float | None, rsi_m: float | None) -> str:
    w = f"{rsi_w:.0f}" if rsi_w is not None and np.isfinite(rsi_w) else "—"
    m = f"{rsi_m:.0f}" if rsi_m is not None and np.isfinite(rsi_m) else "—"
    return (f'<span style="color:{_rsi_color(rsi_w)};font-weight:600">W {w}</span> / '
            f'<span style="color:{_rsi_color(rsi_m)};font-weight:600">M {m}</span>')


def _scanners_cell(scanners: list[str] | None, stars: int) -> str:
    # Daily-confirm heart moved next to the ticker (cols[1], alongside the
    # money-flow/divergence/dual-timeframe badges) -- next to the stars here
    # turned out too easy to miss buried among the star string and scanner list.
    if not scanners:
        return f'<span style="color:{GOLD};font-size:11px">no scanner match</span>'
    star_str = f'<span style="color:{GOLD}">{"★" * stars} </span>' if stars else ""
    return star_str + f'<span style="color:{TEXT_PRIMARY};font-size:10.5px">{" · ".join(scanners)}</span>'


def _stars_of(r: dict) -> int:
    last = r.get("last_w") or r.get("last_m")
    return _verdict_stars(last, r.get("price_now"), r.get("vp"))


# Each key returns a sortable value (or tuple, for a tiebreak) from a row dict.
# "Weekly Age"/"Monthly Age" use NEGATIVE bars_ago so "High-Low" (descending,
# the default) reads as "most recent first" -- matching the table's original
# fixed sort order (_sort_color_group) rather than a literal magnitude sort.
_SCAN_SORT_COLUMNS = {
    "Weekly Age":  lambda r: (-(r.get("last_w") or {}).get("bars_ago", float("inf")), _stars_of(r)),
    "Monthly Age": lambda r: (-(r.get("last_m") or {}).get("bars_ago", float("inf")), _stars_of(r)),
    "★ Stars":     lambda r: (_stars_of(r), -(r.get("last_w") or {}).get("bars_ago", float("inf"))),
    "Ticker":      lambda r: r["ticker"],
    "Price":       lambda r: r["price_now"] if r.get("price_now") is not None else float("-inf"),
    "RSI (Weekly)": lambda r: r["rsi_w"] if r.get("rsi_w") is not None else float("-inf"),
}


def _select_ticker_cb(ticker: str, all_tickers: list, key_prefix: str) -> None:
    """on_change for a row checkbox — single-selection: checking one unchecks
    the rest; unchecking the active one is ignored (exactly one selected)."""
    key = f"{key_prefix}_chk_{ticker}"
    sel_key = f"{key_prefix}_selected_ticker"
    if st.session_state.get(key):
        for t in all_tickers:
            if t != ticker:
                st.session_state[f"{key_prefix}_chk_{t}"] = False
        st.session_state[sel_key] = ticker
    elif st.session_state.get(sel_key) == ticker:
        st.session_state[key] = True


def _render_ticker_table(results: list[dict], key_prefix: str,
                         weekly_fresh: int | None = None, monthly_fresh: int | None = None) -> str | None:
    """Scrollable table (~6 rows) with a per-row single-select checkbox that
    drives which ticker's chart renders below. Uses real Streamlit widgets
    (not raw HTML) so the checkbox can call back into Python, wrapped in
    st.container(height=...) — the native way to get a real scrollable area
    around widgets (raw HTML can't wrap elements rendered across separate
    st.columns calls). Header is rendered outside the container so it stays
    fixed while the rows scroll.

    `weekly_fresh`/`monthly_fresh` (Scan Universe only) dim a dot's cell and
    mark it "stale" when it's outside that lookback — makes it obvious when
    a row only qualified via divergence or the other timeframe, not this
    dot (otherwise a stale-but-shown dot reads as if it were the reason the
    row is here)."""
    ok = [r for r in results if "error" not in r]
    bad = [r for r in results if "error" in r]
    if bad:
        st.warning("Couldn't analyze: " + ", ".join(f'{r["ticker"]} ({r["error"]})' for r in bad))
    if not ok:
        st.info("No tickers returned usable data.")
        return None

    sc1, sc2 = st.columns([1.3, 0.7])
    with sc1:
        sort_label = st.selectbox("Sort by", list(_SCAN_SORT_COLUMNS.keys()), index=0, key=f"{key_prefix}_sort_col")
    with sc2:
        descending = st.selectbox("Order", ["↓ High-Low", "↑ Low-High"], index=0, key=f"{key_prefix}_sort_dir") \
            .startswith("↓")
    ok = sorted(ok, key=_SCAN_SORT_COLUMNS[sort_label], reverse=descending)

    all_tickers = [r["ticker"] for r in ok]
    sel_key = f"{key_prefix}_selected_ticker"
    selected = st.session_state.get(sel_key)
    if selected not in all_tickers:
        selected = all_tickers[0]
        st.session_state[sel_key] = selected
    for t in all_tickers:
        st.session_state.setdefault(f"{key_prefix}_chk_{t}", t == selected)

    hdr_cols = st.columns(_TABLE_RATIOS)
    for c, label in zip(hdr_cols, _TABLE_HEADERS):
        c.markdown(f'<div style="{_TH}">{label}</div>', unsafe_allow_html=True)

    height = min(max(len(ok), 1), _MAX_VISIBLE_ROWS) * _ROW_HEIGHT_PX + 10
    with st.container(height=height):
        for r in ok:
            ticker = r["ticker"]
            lw, lm = r.get("last_w"), r.get("last_m")
            cols = st.columns(_TABLE_RATIOS)
            cols[0].checkbox("select", key=f"{key_prefix}_chk_{ticker}", label_visibility="collapsed",
                             on_change=_select_ticker_cb, args=(ticker, all_tickers, key_prefix))
            tk_style = f"color:{GOLD};font-weight:700" + (";text-decoration:underline" if ticker == selected else "")
            mf = _mf_badge(lw or lm)
            div = _divergence_badge(r.get("div_w"), r.get("div_m"))
            dual = _dual_tf_badge(r.get("both_fresh", False))
            heart = _daily_confirm_badge(bool((lw or lm or {}).get("daily_confirmed")))
            cols[1].markdown(f'<span style="{tk_style}">{ticker}</span>{mf}{div}{dual}{heart}',
                             unsafe_allow_html=True)
            cols[2].markdown(_price_cell(r.get("price_now")), unsafe_allow_html=True)
            cols[3].markdown(_dot_compact(lw, weekly_fresh), unsafe_allow_html=True)
            cols[4].markdown(_dot_age(lw, weekly_fresh), unsafe_allow_html=True)
            cols[5].markdown(_dot_compact(lm, monthly_fresh), unsafe_allow_html=True)
            cols[6].markdown(_dot_age(lm, monthly_fresh), unsafe_allow_html=True)
            cols[7].markdown(_rsi_cell(r.get("rsi_w"), r.get("rsi_m")), unsafe_allow_html=True)
            cols[8].markdown(_scanners_cell(r.get("scanners"), r.get("stars", 0)), unsafe_allow_html=True)
            cols[9].markdown(_verdict_cell(lw or lm, r.get("price_now"), r.get("vp")), unsafe_allow_html=True)

    return st.session_state.get(sel_key, selected)


# ══════════════════════════════════════════════════════════════════════════════
# SHARED RESULTS SECTION (table + chart) — used by both modes
# ══════════════════════════════════════════════════════════════════════════════

def _render_results_section(results: list[dict], key_prefix: str,
                            weekly_fresh: int | None = None, monthly_fresh: int | None = None) -> None:
    sel_ticker = _render_ticker_table(results, key_prefix, weekly_fresh, monthly_fresh)
    if sel_ticker is None:
        return

    ok = [r for r in results if "error" not in r]
    result = next(r for r in ok if r["ticker"] == sel_ticker)

    st.markdown(
        f'<div style="margin-top:18px;color:{TEXT_MUTED};font-size:11px;letter-spacing:.08em;'
        f'text-transform:uppercase">Chart — {sel_ticker} '
        f'<span style="font-weight:400;text-transform:none">(check a row above to change)</span></div>',
        unsafe_allow_html=True,
    )
    tf_options = ["Weekly"] + (["Monthly"] if result.get("wt1_m") is not None else [])
    tf = st.selectbox("Timeframe", tf_options, key=f"{key_prefix}_tf_sel_{sel_ticker}")

    with st.spinner(f"Building {sel_ticker} chart…"):
        fig = _build_chart(result, tf)
    if fig is None:
        st.warning("Not enough data to build this chart.")
    else:
        st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_chart_{sel_ticker}_{tf}")

    vp = result.get("vp")
    if vp:
        st.caption(
            f"Volume Profile (trailing ~5y daily, approximated) — "
            f"POC ${vp['poc']:.2f} · VAH ${vp['vah']:.2f} · VAL ${vp['val']:.2f} · "
            f"HVN {', '.join(f'${h:.2f}' for h in vp['hvn'][:3]) or '—'}"
        )
    else:
        st.caption("Volume Profile unavailable for this ticker (not enough daily history).")


# ══════════════════════════════════════════════════════════════════════════════
# MODE 1 — MANUAL TICKER(S)
# ══════════════════════════════════════════════════════════════════════════════

def _render_manual_mode():
    c1, c2 = st.columns([4, 1])
    with c1:
        raw = st.text_input("Ticker(s) — comma or space separated", key="overkill_check_input",
                            value=_DEFAULT_MANUAL_TICKERS,
                            placeholder="e.g. AAPL, MSFT NVDA COIN")
    with c2:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        run = st.button("▶ Check", type="primary", use_container_width=True, key="overkill_check_run")

    if run:
        tickers = _split_tickers(raw)[:MAX_TICKERS]
        if not tickers:
            st.warning("Enter at least one ticker.")
        else:
            with st.spinner(f"Analyzing {len(tickers)} ticker(s) — WaveTrend + Volume Profile…"):
                results = [_analyze_ticker(t) for t in tickers]
            st.session_state["overkill_check_results"] = results
            st.session_state["overkill_check_ts"] = pd.Timestamp.now().strftime("%b %d %Y · %I:%M %p")
            st.session_state.pop("overkill_check_selected_ticker", None)

    results = st.session_state.get("overkill_check_results")
    if not results:
        st.markdown(
            f'<div style="border:1px dashed {BORDER_COLOR};border-radius:10px;padding:36px;'
            f'text-align:center;color:{TEXT_MUTED}">Edit the ticker list above (optional) and press '
            f'<b style="color:{GOLD}">▶ Check</b> to scan for WaveTrend dots + Volume Profile confluence.</div>',
            unsafe_allow_html=True,
        )
        return

    st.caption(f"Checked {st.session_state.get('overkill_check_ts','')}")
    _render_results_section(results, key_prefix="overkill_check")


# ══════════════════════════════════════════════════════════════════════════════
# MODE 2 — UNIVERSE SCAN (green-dot screener)
# ══════════════════════════════════════════════════════════════════════════════

def _sort_color_group(results: list[dict]) -> list[dict]:
    """Weekly Age first (most recent dot on top), ★ as the tie-breaker within
    the same age. Uses last_w specifically (not last_w-or-last_m) since Scan
    Universe qualification is weekly-only already — every row here has a
    genuine weekly dot to sort by."""
    errored = [r for r in results if "error" in r]
    ok = [r for r in results if "error" not in r]

    def _key(r):
        last = r.get("last_w")
        bars_ago = last["bars_ago"] if last else float("inf")
        stars = _verdict_stars(last, r.get("price_now"), r.get("vp"))
        return (-bars_ago, stars)

    ok.sort(key=_key, reverse=True)
    return ok + errored


def _fmt_found_date(date_str) -> str:
    try:
        return pd.Timestamp(date_str).strftime("%b %d")
    except Exception:
        return date_str or "—"


def _render_track_record_table():
    """Read-only: every ticker the daily email has flagged (4-5★) in the
    last 6 months, with % performance since it was first flagged. Reads the
    same data/overkill/*.json history the email writes -- this page never
    writes its own snapshot (only the once-daily automated run does), and
    today_rows is passed as [] since Scan Universe here isn't star-filtered
    the way the email is, so it shouldn't add unfiltered tickers to the
    historical record."""
    st.markdown(
        f'<div style="margin-top:22px;color:{TEXT_MUTED};font-size:12px;font-weight:800;'
        f'text-transform:uppercase;letter-spacing:.06em">Track Record — last 6 months</div>'
        f'<div style="color:{TEXT_MUTED};font-size:11px;margin:4px 0 8px">'
        f'Every ticker the daily email has flagged in the last 6 months, with % performance '
        f'since it was first flagged.</div>',
        unsafe_allow_html=True,
    )
    today = pd.Timestamp.utcnow().strftime("%Y-%m-%d")
    with st.spinner("Building track record — fetching current prices…"):
        track_rows = scan_history.track_record("overkill", "default", today, [])
    if not track_rows:
        st.caption("No track record yet — check back after the daily email has run a few times.")
        return

    columns = [
        {"label": "Ticker", "type": "str"}, {"label": "★", "type": "num"},
        {"label": "Verdict", "type": "str"}, {"label": "Dot Date", "type": "str"},
        {"label": "Price @ Dot", "type": "num"}, {"label": "Now", "type": "num"},
        {"label": "Perf", "type": "num"},
    ]
    table_rows = []
    for r in track_rows:
        pct = r.get("pct")
        pct_color = TEXT_MUTED if pct is None else (ACCENT_GREEN if pct >= 0 else ACCENT_RED)
        pct_txt = "—" if pct is None else f"{pct:+.1f}%"
        cur_txt = "—" if r.get("current_price") is None else f"${r['current_price']:,.2f}"
        n_stars = int(r["stars"]) if r.get("stars") else 0
        stars_txt = "★" * n_stars if n_stars else "—"
        color = r.get("color")
        verdict_color = ACCENT_GREEN if color == "Green" else (ACCENT_RED if color == "Red" else TEXT_MUTED)
        table_rows.append([
            (f'<span style="font-weight:700;color:{GOLD}">{r["ticker"]}</span>', r["ticker"]),
            (f'<span style="color:{GOLD}">{stars_txt}</span>', n_stars),
            (f'<span style="color:{verdict_color};font-weight:700">{color or "—"}</span>', color or ""),
            (f'<span style="color:{TEXT_MUTED};font-size:11px">{_fmt_found_date(r["first_found"])}</span>', r["first_found"]),
            (f'${r["first_price"]:,.2f}', r["first_price"]),
            (cur_txt, r.get("current_price") if r.get("current_price") is not None else ""),
            (f'<span style="font-weight:700;color:{pct_color}">{pct_txt}</span>', pct if pct is not None else ""),
        ])
    # Imported here, not at module top-level: headless mode (the GitHub Actions
    # email script) mocks `streamlit` without a real install, and this submodule
    # import fails against that mock -- headless mode never calls this render
    # function, so a lazy import avoids the issue without extending the mock.
    import streamlit.components.v1 as components
    components.html(
        sortable_table_html(columns, table_rows, default_sort_idx=6, default_desc=True),
        height=440, scrolling=False,
    )


def _render_scan_mode():
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11.5px;line-height:1.6;margin-bottom:8px">'
        f'Scans the whole universe for tickers whose single most-recent <b>Weekly</b> dot is '
        f'<b style="color:{ACCENT_GREEN}">🟢 green</b> (long) or <b style="color:{ACCENT_RED}">🔴 red</b> '
        f'(short) AND fresh, shown as two separate sections below. Weekly-only and "most recent wins" '
        f'on purpose: if a more recent opposite-color dot has since printed, the earlier same-color one '
        f'no longer qualifies — the picture has changed. Monthly no longer admits a ticker on its own '
        f'(that let in tickers with a long-stale weekly dot); it still feeds the '
        f'<b style="color:{GOLD}">🎯</b> badge (both Weekly and Monthly independently fresh in the same '
        f'direction) and the Monthly Dot column. A <b style="color:{ACCENT_GREEN}">📈</b>/'
        f'<b style="color:{ACCENT_RED}">📉</b> badge shows divergence as bonus context on a qualifying '
        f'row, but can\'t bring in a ticker by itself. Each section sorts by ★ first, newest dot '
        f'breaking ties within the same star tier.</div>',
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns([2.2, 1, 1])
    with c1:
        uni_label = st.selectbox("Universe", list(_SCAN_UNIVERSE_CHOICES.keys()), key="overkill_scan_uni")
    with c2:
        weekly_fresh = st.number_input("Weekly lookback (bars)", min_value=1, max_value=20,
                                       value=DEFAULT_WEEKLY_FRESH_BARS, key="overkill_scan_wf")
    with c3:
        monthly_fresh = st.number_input("Monthly lookback (bars) — 🎯 badge only", min_value=1, max_value=12,
                                        value=DEFAULT_MONTHLY_FRESH_BARS, key="overkill_scan_mf")

    run_scan = st.button("▶ Scan Universe", type="primary", key="overkill_scan_run")

    if run_scan:
        universe = _SCAN_UNIVERSE_CHOICES[uni_label]
        prog = st.progress(0.0, text="Scanning for fresh dots…")

        def _cb(i, total, ticker):
            prog.progress(min((i + 1) / total, 1.0), text=f"Scanning {ticker} ({i+1}/{total})…")

        candidates = _scan_universe(universe, int(weekly_fresh), int(monthly_fresh), progress_cb=_cb)
        prog.empty()

        if not candidates:
            st.session_state.pop("overkill_scan_green_results", None)
            st.session_state.pop("overkill_scan_red_results", None)
            st.info("No tickers currently show a fresh dot within the chosen lookback — "
                    "try widening the lookback windows above.")
        else:
            prefetch_tickers([c["ticker"] for c in candidates], VP_FETCH_PERIOD, "1d")
            with st.spinner(f"Building full profile (Volume Profile + confluence) for "
                            f"{len(candidates)} matching ticker(s)…"):
                green_results, red_results = [], []
                for c in candidates:
                    base = _analyze_ticker(c["ticker"])
                    if "error" in base:
                        (green_results if c["has_green"] else red_results).append(base)
                        continue
                    if c["has_green"]:
                        g = _color_variant(base, "Green")
                        g["both_fresh"] = c["both_fresh_green"]
                        green_results.append(g)
                    if c["has_red"]:
                        rd = _color_variant(base, "Red")
                        rd["both_fresh"] = c["both_fresh_red"]
                        red_results.append(rd)

            st.session_state["overkill_scan_green_results"] = _sort_color_group(green_results)
            st.session_state["overkill_scan_red_results"] = _sort_color_group(red_results)
            st.session_state["overkill_scan_ts"] = pd.Timestamp.now().strftime("%b %d %Y · %I:%M %p")
            st.session_state.pop("overkill_scan_green_selected_ticker", None)
            st.session_state.pop("overkill_scan_red_selected_ticker", None)

    green_results = st.session_state.get("overkill_scan_green_results")
    red_results = st.session_state.get("overkill_scan_red_results")
    if not green_results and not red_results:
        st.markdown(
            f'<div style="border:1px dashed {BORDER_COLOR};border-radius:10px;padding:36px;'
            f'text-align:center;color:{TEXT_MUTED}">Press <b style="color:{GOLD}">▶ Scan Universe</b> '
            f'to find tickers with a fresh dot right now.</div>',
            unsafe_allow_html=True,
        )
        return

    st.caption(f"Scanned {st.session_state.get('overkill_scan_ts','')}")

    st.markdown(
        f'<div style="margin-top:6px;color:{ACCENT_GREEN};font-size:12px;font-weight:800;'
        f'text-transform:uppercase;letter-spacing:.06em">🟢 Green Dots — {len(green_results or [])} ticker(s)</div>',
        unsafe_allow_html=True,
    )
    if green_results:
        _render_results_section(green_results, key_prefix="overkill_scan_green",
                                weekly_fresh=int(weekly_fresh), monthly_fresh=int(monthly_fresh))
    else:
        st.info("No tickers with a fresh green dot right now.")

    st.markdown(f'<hr style="border-color:{BORDER_COLOR};margin:22px 0">', unsafe_allow_html=True)

    st.markdown(
        f'<div style="color:{ACCENT_RED};font-size:12px;font-weight:800;text-transform:uppercase;'
        f'letter-spacing:.06em">🔴 Red Dots — {len(red_results or [])} ticker(s)</div>',
        unsafe_allow_html=True,
    )
    if red_results:
        _render_results_section(red_results, key_prefix="overkill_scan_red",
                                weekly_fresh=int(weekly_fresh), monthly_fresh=int(monthly_fresh))
    else:
        st.info("No tickers with a fresh red dot right now.")

    st.markdown(f'<hr style="border-color:{BORDER_COLOR};margin:22px 0">', unsafe_allow_html=True)
    _render_track_record_table()


# ══════════════════════════════════════════════════════════════════════════════
# MODE 3 — BACKTEST (validates the ★ system against history)
# ══════════════════════════════════════════════════════════════════════════════

_BT_TD = f"padding:7px 10px;border-bottom:1px solid {BORDER_COLOR};vertical-align:middle;white-space:nowrap"


def _render_backtest_table(agg: pd.DataFrame) -> None:
    if agg.empty:
        st.info("No historical dots found to backtest in this window.")
        return
    cols = ["★", "Dots Tested", "Win Rate", "TP1 (POC)", "TP2 (VAH/VAL)", "Stopped Out", "Expired"]
    thead = "".join(f'<th style="{_TH}">{c}</th>' for c in cols)
    body = ""
    for _, r in agg.iterrows():
        wr = r["win_rate"]
        if np.isnan(wr):
            wr_str, wr_color = "—", TEXT_MUTED
        else:
            wr_str = f"{wr:.0f}%"
            wr_color = ACCENT_GREEN if wr >= 55 else (GOLD if wr >= 45 else ACCENT_RED)
        body += (
            "<tr>"
            f'<td style="{_BT_TD};color:{GOLD};font-size:13px">{"★" * int(r["stars"])}</td>'
            f'<td style="{_BT_TD}">{int(r["n"])}</td>'
            f'<td style="{_BT_TD};color:{wr_color};font-weight:700">{wr_str}</td>'
            f'<td style="{_BT_TD};color:{ACCENT_GREEN}">{int(r["tp1"])}</td>'
            f'<td style="{_BT_TD};color:{ACCENT_GREEN}">{int(r["tp2"])}</td>'
            f'<td style="{_BT_TD};color:{ACCENT_RED}">{int(r["sl"])}</td>'
            f'<td style="{_BT_TD};color:{TEXT_MUTED}">{int(r["expired"])}</td>'
            "</tr>"
        )
    st.markdown(
        f'<div style="overflow-x:auto;border:1px solid {BORDER_COLOR};border-radius:10px">'
        f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
        f'<thead><tr>{thead}</tr></thead><tbody>{body}</tbody></table></div>',
        unsafe_allow_html=True,
    )


def _render_backtest_mode():
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11.5px;line-height:1.6;margin-bottom:8px">'
        f'Tests every historical dot against the strategy\'s own exits — TP1 = POC, TP2 = VAH '
        f'(long) / VAL (short), stop just past the nearest LVN — walked forward day-by-day. The '
        f'Volume Profile for each dot is rebuilt using only data available <i>as of that dot\'s own '
        f'date</i> (no lookahead bias). Grouped by ★ to answer: does a 5★ dot actually win more than '
        f'a 2★ one, historically? <b>Caveats:</b> today\'s universe list applied backward in time '
        f'(survivorship bias — tickers that failed/delisted since aren\'t included), same-day '
        f'target-vs-stop ties resolved in favor of the stop (conservative), and a flat '
        f'{int(BACKTEST_SL_FALLBACK_PCT*100)}% stop used on the rare dot with no LVN in the right '
        f'direction. Watch the <b>Dots Tested</b> column — a tier with only a handful of dots isn\'t '
        f'statistically meaningful yet.</div>',
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns([2.2, 1, 1])
    with c1:
        uni_label = st.selectbox("Universe", list(_SCAN_UNIVERSE_CHOICES.keys()), index=1,
                                 key="overkill_bt_uni")
    with c2:
        lookback_years = st.number_input("Lookback (years)", min_value=1, max_value=10,
                                         value=BACKTEST_LOOKBACK_YEARS, key="overkill_bt_years")
    with c3:
        max_hold = st.number_input("Max hold (trading days)", min_value=10, max_value=250,
                                   value=BACKTEST_MAX_HOLD_DAYS, key="overkill_bt_hold")

    run_bt = st.button("▶ Run Backtest", type="primary", key="overkill_bt_run")

    if run_bt:
        universe = _SCAN_UNIVERSE_CHOICES[uni_label]
        prog = st.progress(0.0, text="Backtesting historical dots…")

        def _cb(i, total, ticker):
            prog.progress(min((i + 1) / total, 1.0), text=f"Backtesting {ticker} ({i+1}/{total})…")

        records = _run_backtest(universe, int(lookback_years), int(max_hold), progress_cb=_cb)
        prog.empty()

        st.session_state["overkill_bt_records"] = records
        st.session_state["overkill_bt_ts"] = pd.Timestamp.now().strftime("%b %d %Y · %I:%M %p")
        if not records:
            st.info("No historical dots found in this window — try a longer lookback or a bigger universe.")
            return

    records = st.session_state.get("overkill_bt_records")
    if not records:
        st.markdown(
            f'<div style="border:1px dashed {BORDER_COLOR};border-radius:10px;padding:36px;'
            f'text-align:center;color:{TEXT_MUTED}">Press <b style="color:{GOLD}">▶ Run Backtest</b> '
            f'to validate the ★ ratings against historical outcomes. This scans every ticker in the '
            f'chosen universe and can take a while — it\'s doing far more work per ticker than a '
            f'live scan.</div>',
            unsafe_allow_html=True,
        )
        return

    greens = sum(1 for r in records if r["color"] == "Green")
    reds = len(records) - greens
    weeklies = sum(1 for r in records if r["timeframe"] == "Weekly")
    st.caption(
        f"Backtested {st.session_state.get('overkill_bt_ts','')} · {len(records)} historical dots "
        f"({greens} green, {reds} red · {weeklies} weekly, {len(records)-weeklies} monthly)"
    )
    agg = _aggregate_backtest(records)
    _render_backtest_table(agg)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN RENDER
# ══════════════════════════════════════════════════════════════════════════════

def render():
    mode = st.radio("Mode", ["🔤 Manual Ticker(s)", "🌐 Scan Universe", "📊 Backtest"], horizontal=True,
                    index=1, key="overkill_check_mode", label_visibility="collapsed")

    if mode == "🌐 Scan Universe":
        _render_scan_mode()
    elif mode == "📊 Backtest":
        _render_backtest_mode()
    else:
        _render_manual_mode()

    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:14px;line-height:1.85;margin-top:28px;'
        f'padding-top:18px;border-top:1px solid {BORDER_COLOR}">'
        f'Approximates Overkill Trading\'s <b>WaveTrend dot + Volume Profile confluence</b> setup. '
        f'<b style="color:{ACCENT_GREEN}">🟢 Green Dot</b> = bullish WaveTrend cross while oversold · '
        f'<b style="color:{ACCENT_RED}">🔴 Red Dot</b> = bearish cross while overbought. '
        f'Four small badges can appear next to the ticker, all soft confirmation only — none of them '
        f'can bring in a ticker on their own, and their absence never disqualifies anything: '
        f'a 💰 means Money Flow Index agrees with that dot (oversold for green, overbought for red); '
        f'a <b style="color:{ACCENT_GREEN}">📈</b>/<b style="color:{ACCENT_RED}">📉</b> means price '
        f'and the WaveTrend line are diverging (e.g. price makes a lower low while the oscillator '
        f'makes a higher low) — a reversal warning shown as bonus context on a row that already has a '
        f'fresh dot; a <b style="color:{GOLD}">🎯</b> means Weekly <i>and</i> Monthly are both '
        f'independently fresh at the same time — the strongest confluence this system can show; and a '
        f'❤️ means the <b>daily</b> chart confirms the dot\'s direction — either the daily MACD '
        f'histogram is aligned (positive for green, negative for red) or the daily EMA20/50 '
        f'relationship just crossed that way. Unlike the other three, this last one is checked on '
        f'the daily bar specifically, so it can change day to day (even intraday, since it isn\'t '
        f'gated to only completed bars the way Best Scanners is) as the daily chart moves — read it '
        f'as "does today\'s daily action line up," not a permanent property of the dot. The '
        f'<b>Verdict</b> column combines two reads: where <i>today\'s</i> price sits vs. the Volume '
        f'Profile (room up to POC/VAH = upside bias, below VAL = downside risk) and whether the '
        f'qualifying dot itself printed at a key level or in isolation (his "Golden Rule" — an '
        f'isolated dot is chop risk). The <b style="color:{GOLD}">★</b> before it (1-5, blank = no dot) '
        f'ranks that combination, tuned against two real Backtest rounds (see that mode): already '
        f'through fair value toward/past the far edge (★★★★★–★★★★) reads as confirmed strength/trend '
        f'continuation, near the confirming level but not yet proven (★★★) is the textbook-but-'
        f'unconfirmed entry, an isolated dot with no confluence at all (★★) is weak but merely '
        f'uninformative, and a dot that WAS confirmed but has since broken back through that same '
        f'level (★) is the single worst tier — an active failure, empirically worse than never having '
        f'confluence to begin with. Both backtest rounds found the original design backwards (room-'
        f'based reward scoring, and isolated ranked above broken-confirmation) — validate any further '
        f'tuning the same way before trusting it. MACD crossover is shown on the chart. '
        f'<b>Note:</b> dots come from '
        f'the public WaveTrend formula his tool is built on (not his exact proprietary script), the '
        f'{MA_LEN}-period MA is an expanding average until enough bars exist, and the Volume Profile is '
        f'approximated from daily volume (yfinance has no true volume-at-price feed) — treat all three '
        f'as close estimates, not certainty.</div>',
        unsafe_allow_html=True,
    )
