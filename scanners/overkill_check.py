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

from config import (
    GOLD, BG_DARK, BG_PANEL, ACCENT_BLUE, ACCENT_GREEN, ACCENT_RED,
    TEXT_PRIMARY, TEXT_MUTED, BORDER_COLOR,
    FTF_UNIVERSE, MTPA_200, SP500_SAMPLE,
)
from utils import calc_ema, calc_sma
from data_loader import get_price_history, prefetch_tickers

PURPLE = "#A78BFA"

# ── WaveTrend params (LazyBear's public "WaveTrend Oscillator" formula) ────
WT_CHANNEL_LEN = 9
WT_AVG_LEN     = 12
WT_MA_LEN      = 3
WT_OB_LEVEL    = 53      # dots need the cross to land beyond this
WT_OS_LEVEL    = -53

MA_LEN            = 400   # "he leans on the 400 MA a lot"
VP_LOOKBACK_DAYS  = 504   # ~2y of daily bars behind the volume profile
VP_BINS           = 24
CONFLUENCE_TOL    = 0.02  # 2% of price counts as "at" a level
MAX_TICKERS       = 30

# ── Universe scan (screener mode) ────────────────────────────────────────────
_SCAN_UNIVERSE_CHOICES = {
    "FTF Universe (~480 · full S&P 500 + ETFs)": FTF_UNIVERSE,
    "MTPA 200 (stock-heavy)": MTPA_200,
    "S&P 500 sample (200)": SP500_SAMPLE[:200],
}
DEFAULT_WEEKLY_FRESH_BARS  = 4   # "fresh" weekly dot = within the last N weekly bars
DEFAULT_MONTHLY_FRESH_BARS = 2   # "fresh" monthly dot = within the last N monthly bars

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


def _last_dot(df: pd.DataFrame, dots: pd.DataFrame | None, ma_series: pd.Series | None,
              vp: dict | None) -> dict | None:
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
                hits=_level_hits(price, vp, ma_val), bars_ago=int(bars_ago))


def _last_green_dot(df: pd.DataFrame, dots: pd.DataFrame | None, ma_series: pd.Series | None,
                     vp: dict | None) -> dict | None:
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
                hits=_level_hits(price, vp, ma_val), bars_ago=int(bars_ago))


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

        daily = get_price_history(ticker, period="2y", interval="1d")
        if daily is not None and not daily.empty:
            daily = daily.dropna(subset=["Open", "High", "Low", "Close"])
        vp = _volume_profile(daily) if daily is not None and not daily.empty else None

        weekly_close = weekly["Close"].squeeze()
        ma400_w = calc_sma(weekly_close, MA_LEN)
        wt1_w, wt2_w = _wavetrend(weekly)
        dots_w = _wt_dots(wt1_w, wt2_w)
        rsi_w = float(_rsi(weekly_close).iloc[-1])

        result = dict(
            ticker=ticker, weekly=weekly, monthly=None, vp=vp,
            wt1_w=wt1_w, wt2_w=wt2_w, dots_w=dots_w, ma400_w=ma400_w,
            wt1_m=None, wt2_m=None, dots_m=None, ma400_m=None,
            rsi_w=rsi_w, rsi_m=None,
            price_now=float(weekly_close.iloc[-1]),
        )

        if monthly is not None and len(monthly) >= 20:
            monthly_close = monthly["Close"].squeeze()
            ma400_m = calc_sma(monthly_close, MA_LEN)
            wt1_m, wt2_m = _wavetrend(monthly)
            dots_m = _wt_dots(wt1_m, wt2_m)
            result.update(monthly=monthly, wt1_m=wt1_m, wt2_m=wt2_m, dots_m=dots_m, ma400_m=ma400_m,
                         rsi_m=float(_rsi(monthly_close).iloc[-1]))

        result["last_w"] = _last_dot(weekly, dots_w, ma400_w, vp)
        result["last_m"] = (_last_dot(monthly, result["dots_m"], result["ma400_m"], vp)
                             if result.get("dots_m") is not None else None)
        return result
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def _analyze_ticker_green_only(ticker: str) -> dict:
    """Full per-ticker profile (for the chart + confluence columns), but with
    last_w/last_m overridden to the most recent GREEN dot specifically —
    used by the Universe Scan table so a ticker's more-recent red dot never
    hides the green dot that got it onto the screener."""
    r = _analyze_ticker(ticker)
    if "error" in r:
        return r
    r["last_w"] = _last_green_dot(r["weekly"], r["dots_w"], r["ma400_w"], r["vp"])
    r["last_m"] = (_last_green_dot(r["monthly"], r["dots_m"], r["ma400_m"], r["vp"])
                   if r.get("dots_m") is not None else None)
    return r


def _scan_universe(universe: list[str], weekly_fresh: int, monthly_fresh: int,
                   progress_cb=None) -> list[dict]:
    """Phase 1 of the Universe Scan — cheap pass (weekly + monthly WaveTrend
    only, no daily/Volume-Profile fetch) over the whole universe to find
    tickers with a green dot inside the fresh-lookback window on either
    timeframe (OR). Returns candidates sorted weekly-fresh-first (then by
    weekly dot recency), monthly-only matches after (then by monthly dot
    recency) — matching 'sort the table by weekly green dots'.
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
            dots_w = _wt_dots(*_wavetrend(weekly))
            gw = _last_green_dot(weekly, dots_w, None, None)
            fresh_w = gw is not None and gw["bars_ago"] < weekly_fresh

            gm = None
            fresh_m = False
            monthly = get_price_history(ticker, period="max", interval="1mo")
            if monthly is not None and not monthly.empty:
                monthly = monthly.dropna(subset=["Open", "High", "Low", "Close"])
                if len(monthly) >= 20:
                    dots_m = _wt_dots(*_wavetrend(monthly))
                    gm = _last_green_dot(monthly, dots_m, None, None)
                    fresh_m = gm is not None and gm["bars_ago"] < monthly_fresh

            if fresh_w or fresh_m:
                candidates.append(dict(
                    ticker=ticker, fresh_w=fresh_w, fresh_m=fresh_m,
                    gw_date=gw["date"] if gw else "", gm_date=gm["date"] if gm else "",
                ))
        except Exception:
            continue

    weekly_first = sorted([c for c in candidates if c["fresh_w"]],
                          key=lambda c: c["gw_date"], reverse=True)
    monthly_only = sorted([c for c in candidates if not c["fresh_w"] and c["fresh_m"]],
                          key=lambda c: c["gm_date"], reverse=True)
    return weekly_first + monthly_only


def _vp_position(price: float | None, vp: dict | None) -> tuple[str, str]:
    """Directional read of CURRENT price vs the Volume Profile — this is the
    'which tickers are likely to move up' heuristic: room-to-run toward the
    magnetic POC/VAH levels, not a prediction. Purely technical, not advice."""
    if price is None or vp is None or not np.isfinite(price):
        return "— no VP data", TEXT_MUTED
    poc, val, vah = vp["poc"], vp["val"], vp["vah"]
    tol = price * CONFLUENCE_TOL
    if price < val:
        return f"🔻 Below VAL (${val:.2f})", ACCENT_RED
    if abs(price - poc) <= tol:
        return f"⚖️ At POC (${poc:.2f})", GOLD
    if price < poc:
        return f"🚀 Upside to POC (${poc:.2f})", ACCENT_GREEN
    if price <= vah:
        return f"➡️ Room to VAH (${vah:.2f})", ACCENT_BLUE
    return f"⚠️ Above VAH (${vah:.2f})", GOLD


def _verdict_cell(last: dict | None, price_now: float | None, vp: dict | None) -> str:
    bias_text, bias_color = _vp_position(price_now, vp)
    if last is None:
        conv_text, conv_color = "no recent dot", TEXT_MUTED
    elif last["hits"]:
        conv_text = f'🔥 {last["color"]} dot @ ' + "/".join(last["hits"])
        conv_color = ACCENT_GREEN if last["color"] == "Green" else ACCENT_RED
    else:
        conv_text, conv_color = "⚠️ isolated dot — chop risk", GOLD
    return (
        f'<div style="color:{bias_color};font-weight:700;font-size:11px;white-space:normal">{bias_text}</div>'
        f'<div style="color:{conv_color};font-size:9.5px;margin-top:2px;white-space:normal">{conv_text}</div>'
    )


# ── Chart ────────────────────────────────────────────────────────────────────
def _build_chart(result: dict, timeframe: str):
    if timeframe == "Monthly":
        df, wt1, wt2, dots, ma_series = (result.get("monthly"), result.get("wt1_m"),
                                          result.get("wt2_m"), result.get("dots_m"),
                                          result.get("ma400_m"))
    else:
        df, wt1, wt2, dots, ma_series = (result["weekly"], result["wt1_w"], result["wt2_w"],
                                          result["dots_w"], result["ma400_w"])
    if df is None or df.empty or wt1 is None:
        return None

    n = min(260, len(df))
    view = df.iloc[-n:]
    xs = view.index
    wt1_v, wt2_v = wt1.iloc[-n:], wt2.iloc[-n:]
    dots_v = dots.iloc[-n:]
    ma_v = ma_series.iloc[-n:] if ma_series is not None else None
    vp = result.get("vp")
    ticker = result["ticker"]

    macd_ln, sig_ln, hist_s = _macd(df["Close"].squeeze())
    macd_ln, sig_ln, hist_s = macd_ln.iloc[-n:], sig_ln.iloc[-n:], hist_s.iloc[-n:]

    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.04,
                        row_heights=[0.5, 0.26, 0.24])

    fig.add_trace(go.Candlestick(
        x=xs, open=view["Open"].squeeze(), high=view["High"].squeeze(),
        low=view["Low"].squeeze(), close=view["Close"].squeeze(),
        increasing_line_color=ACCENT_GREEN, decreasing_line_color=ACCENT_RED,
        increasing_fillcolor=_rgba(ACCENT_GREEN, 0.6), decreasing_fillcolor=_rgba(ACCENT_RED, 0.6),
        name=ticker,
    ), row=1, col=1)

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
        for lvl in vp["hvn"]:
            fig.add_hline(y=lvl, line=dict(color=_rgba(GOLD, 0.45), width=0.7, dash="dot"), row=1, col=1)
        for lvl in vp["lvn"]:
            fig.add_hline(y=lvl, line=dict(color=_rgba(TEXT_MUTED, 0.55), width=0.6, dash="dot"), row=1, col=1)

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

    fig.update_layout(
        paper_bgcolor=BG_DARK, plot_bgcolor=BG_PANEL,
        font=dict(color=TEXT_PRIMARY, family="Inter, sans-serif", size=11),
        height=760, margin=dict(l=10, r=60, t=34, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                   bgcolor="rgba(0,0,0,0)", font=dict(size=10)),
        xaxis_rangeslider_visible=False, hovermode="x unified",
        title=dict(text=f"{ticker} — {timeframe}", font=dict(size=13, color=GOLD), x=0.01, y=0.99),
    )
    for i in (1, 2, 3):
        fig.update_xaxes(gridcolor=BORDER_COLOR, row=i, col=1, showgrid=True)
        fig.update_yaxes(gridcolor=BORDER_COLOR, row=i, col=1, showgrid=True)
    fig.update_yaxes(title_text="Price", row=1, col=1, title_font=dict(size=10, color=TEXT_MUTED))
    fig.update_yaxes(title_text="WaveTrend", row=2, col=1, title_font=dict(size=10, color=TEXT_MUTED))
    fig.update_yaxes(title_text="MACD", row=3, col=1, title_font=dict(size=10, color=TEXT_MUTED))
    return fig


# ── Ticker table (checkbox-select, scrollable) ──────────────────────────────
_TH = (f"color:{TEXT_MUTED};font-size:9px;font-weight:700;text-transform:uppercase;"
       f"letter-spacing:0.6px;padding:6px 10px;text-align:left;white-space:nowrap;"
       f"border-bottom:1.5px solid {BORDER_COLOR}")
_TABLE_RATIOS  = [0.32, 0.5, 1.05, 1.05, 0.62, 1.7]
_TABLE_HEADERS = ["", "Ticker", "Weekly Dot", "Monthly Dot", "RSI", "Verdict"]
_ROW_HEIGHT_PX = 83   # calibrated against the Best Scanners table (~83px/row)


def _dot_compact(last: dict | None) -> str:
    if last is None:
        return f'<span style="color:{TEXT_MUTED}">—</span>'
    color = ACCENT_GREEN if last["color"] == "Green" else ACCENT_RED
    icon = "🟢" if last["color"] == "Green" else "🔴"
    return (f'<span style="color:{color};font-weight:600">{icon} {last["date"]}</span><br>'
            f'<span style="color:{TEXT_MUTED};font-size:10px">${last["price"]:.2f} '
            f'· {last["bars_ago"]}b ago</span>')


def _rsi_cell(rsi_w: float | None, rsi_m: float | None) -> str:
    w = f"{rsi_w:.0f}" if rsi_w is not None and np.isfinite(rsi_w) else "—"
    m = f"{rsi_m:.0f}" if rsi_m is not None and np.isfinite(rsi_m) else "—"
    return f"W {w} / M {m}"


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


def _render_ticker_table(results: list[dict], key_prefix: str) -> str | None:
    """Scrollable table (~7 rows) with a per-row single-select checkbox that
    drives which ticker's chart renders below. Uses real Streamlit widgets
    (not raw HTML) so the checkbox can call back into Python, wrapped in
    st.container(height=...) — the native way to get a real scrollable area
    around widgets (raw HTML can't wrap elements rendered across separate
    st.columns calls). Header is rendered outside the container so it stays
    fixed while the rows scroll."""
    ok = [r for r in results if "error" not in r]
    bad = [r for r in results if "error" in r]
    if bad:
        st.warning("Couldn't analyze: " + ", ".join(f'{r["ticker"]} ({r["error"]})' for r in bad))
    if not ok:
        st.info("No tickers returned usable data.")
        return None

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

    height = min(max(len(ok), 1), 7) * _ROW_HEIGHT_PX + 10
    with st.container(height=height):
        for r in ok:
            ticker = r["ticker"]
            lw, lm = r.get("last_w"), r.get("last_m")
            cols = st.columns(_TABLE_RATIOS)
            cols[0].checkbox("select", key=f"{key_prefix}_chk_{ticker}", label_visibility="collapsed",
                             on_change=_select_ticker_cb, args=(ticker, all_tickers, key_prefix))
            tk_style = f"color:{GOLD};font-weight:700" + (";text-decoration:underline" if ticker == selected else "")
            cols[1].markdown(f'<span style="{tk_style}">{ticker}</span>', unsafe_allow_html=True)
            cols[2].markdown(_dot_compact(lw), unsafe_allow_html=True)
            cols[3].markdown(_dot_compact(lm), unsafe_allow_html=True)
            cols[4].markdown(_rsi_cell(r.get("rsi_w"), r.get("rsi_m")))
            cols[5].markdown(_verdict_cell(lw or lm, r.get("price_now"), r.get("vp")), unsafe_allow_html=True)

    return st.session_state.get(sel_key, selected)


# ══════════════════════════════════════════════════════════════════════════════
# SHARED RESULTS SECTION (table + chart) — used by both modes
# ══════════════════════════════════════════════════════════════════════════════

def _render_results_section(results: list[dict], key_prefix: str) -> None:
    sel_ticker = _render_ticker_table(results, key_prefix)
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
            f"Volume Profile (trailing ~2y daily, approximated) — "
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

def _render_scan_mode():
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11.5px;line-height:1.6;margin-bottom:8px">'
        f'Scans the whole universe for tickers with a <b style="color:{ACCENT_GREEN}">🟢 fresh green '
        f'dot</b> on the Weekly <i>or</i> Monthly chart — only matching tickers are listed (not all '
        f'~480). "Fresh" = the dot printed within the lookback below; tighten it for only-this-week '
        f'signals, loosen it to catch dots that are still developing.</div>',
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns([2.2, 1, 1])
    with c1:
        uni_label = st.selectbox("Universe", list(_SCAN_UNIVERSE_CHOICES.keys()), key="overkill_scan_uni")
    with c2:
        weekly_fresh = st.number_input("Weekly lookback (bars)", min_value=1, max_value=20,
                                       value=DEFAULT_WEEKLY_FRESH_BARS, key="overkill_scan_wf")
    with c3:
        monthly_fresh = st.number_input("Monthly lookback (bars)", min_value=1, max_value=12,
                                        value=DEFAULT_MONTHLY_FRESH_BARS, key="overkill_scan_mf")

    run_scan = st.button("▶ Scan Universe", type="primary", key="overkill_scan_run")

    if run_scan:
        universe = _SCAN_UNIVERSE_CHOICES[uni_label]
        prog = st.progress(0.0, text="Scanning for fresh green dots…")

        def _cb(i, total, ticker):
            prog.progress(min((i + 1) / total, 1.0), text=f"Scanning {ticker} ({i+1}/{total})…")

        candidates = _scan_universe(universe, int(weekly_fresh), int(monthly_fresh), progress_cb=_cb)
        prog.empty()

        if not candidates:
            st.session_state.pop("overkill_scan_results", None)
            st.info("No tickers currently show a fresh green dot within the chosen lookback — "
                    "try widening the lookback windows above.")
        else:
            prefetch_tickers([c["ticker"] for c in candidates], "2y", "1d")
            with st.spinner(f"Building full profile (Volume Profile + confluence) for "
                            f"{len(candidates)} matching ticker(s)…"):
                results = [_analyze_ticker_green_only(c["ticker"]) for c in candidates]
            st.session_state["overkill_scan_results"] = results
            st.session_state["overkill_scan_ts"] = pd.Timestamp.now().strftime("%b %d %Y · %I:%M %p")
            st.session_state.pop("overkill_scan_selected_ticker", None)

    results = st.session_state.get("overkill_scan_results")
    if not results:
        st.markdown(
            f'<div style="border:1px dashed {BORDER_COLOR};border-radius:10px;padding:36px;'
            f'text-align:center;color:{TEXT_MUTED}">Press <b style="color:{GOLD}">▶ Scan Universe</b> '
            f'to find tickers with a fresh green dot right now.</div>',
            unsafe_allow_html=True,
        )
        return

    ok = [r for r in results if "error" not in r]
    st.caption(f"Scanned {st.session_state.get('overkill_scan_ts','')} · "
              f"{len(ok)} ticker(s) with a fresh green dot (sorted: weekly dots first, most recent)")
    _render_results_section(results, key_prefix="overkill_scan")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN RENDER
# ══════════════════════════════════════════════════════════════════════════════

def render():
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:12px;line-height:1.7;margin-bottom:10px">'
        f'Approximates Overkill Trading\'s <b>WaveTrend dot + Volume Profile confluence</b> setup. '
        f'<b style="color:{ACCENT_GREEN}">🟢 Green Dot</b> = bullish WaveTrend cross while oversold · '
        f'<b style="color:{ACCENT_RED}">🔴 Red Dot</b> = bearish cross while overbought. The '
        f'<b>Verdict</b> column combines two reads: where <i>today\'s</i> price sits vs. the Volume '
        f'Profile (room up to POC/VAH = upside bias, below VAL = downside risk) and whether the '
        f'qualifying dot itself printed at a key level or in isolation (his "Golden Rule" — an '
        f'isolated dot is chop risk). MACD crossover is shown on the chart. <b>Note:</b> dots come from '
        f'the public WaveTrend formula his tool is built on (not his exact proprietary script), the '
        f'{MA_LEN}-period MA is an expanding average until enough bars exist, and the Volume Profile is '
        f'approximated from daily volume (yfinance has no true volume-at-price feed) — treat all three '
        f'as close estimates, not certainty.</div>',
        unsafe_allow_html=True,
    )

    mode = st.radio("Mode", ["🔤 Manual Ticker(s)", "🌐 Scan Universe"], horizontal=True,
                    key="overkill_check_mode", label_visibility="collapsed")

    if mode == "🌐 Scan Universe":
        _render_scan_mode()
    else:
        _render_manual_mode()
