"""
scanners/ma400_scanner.py — 400-Day MA Buy-Zone Scanner

Scans a curated QUALITY universe (long-term-holdable stocks + broad/sector
ETFs — no leveraged or volatility products) for names trading close to or
below their 400-day simple moving average.

The 400-day MA is a classic "generational entry" line for quality compounders:
great businesses rarely trade below it, and when they do it has historically
marked deep-value accumulation zones.

Output columns per ticker:
  % vs 400MA (sorted deepest-below first) · D/W RSI · D/W MACD>0 ·
  D/W MACD crossover · trend state (golden/death cross) · 52-week drawdown ·
  sentiment · Dip Score /10 · warning flags
"""

import numpy as np
import pandas as pd
import yfinance as yf
import time, random

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    MTPA_200, SP500_SAMPLE, FTF_UNIVERSE,
    OPTIONS_ETF_UNIVERSE, ETF_UNIVERSE,
)
from data_loader import get_price_history
from utils import calc_ema, calc_sma, calc_rsi

# ── Universe ───────────────────────────────────────────────────────────────────
# Leveraged / inverse / volatility products — never "quality long-term holds".
_EXCLUDE_NOT_LONG_TERM = {
    # 3x / leveraged ETFs
    "TQQQ", "SOXL", "TECL", "CURE", "NAIL", "UPRO", "SPXL", "TNA",
    "FNGU", "LABU", "FAS", "UDOW", "DPST", "HIBL", "NUGT", "WEBL",
    "BULZ", "NVDL", "3TSL", "SQQQ", "SOXS", "SPXS", "TECS", "FNGD",
    "LABD", "WEBS", "FAZ", "TZA", "SDOW", "DFEN", "ERX", "URTY",
    "WANT", "MIDU", "INDL",
    # Volatility products (decay vehicles)
    "UVXY", "VXX",
    # Commodity futures ETFs (contango decay — not buy-and-hold)
    "USO", "UNG",
    # Structurally challenged / declining businesses
    "WBA", "F", "T", "VZ", "MO", "PM", "WBD", "FOXA", "NWSA",
    "INTC", "BEN", "IVZ", "VTRS", "AAL", "CCL", "NCLH", "LYFT",
}


def quality_universe() -> list[str]:
    """MTPA-200 quality list minus anything not worth holding long term."""
    return [t for t in MTPA_200 if t not in _EXCLUDE_NOT_LONG_TERM]


def sp500_universe() -> list[str]:
    return [t for t in SP500_SAMPLE if t not in _EXCLUDE_NOT_LONG_TERM]


def full_universe() -> list[str]:
    return [t for t in FTF_UNIVERSE if t not in _EXCLUDE_NOT_LONG_TERM]


# ── Thresholds ─────────────────────────────────────────────────────────────────
MA_LEN          = 400        # the star of the show
PRICE_MIN       = 10.0       # penny-ish names are not "quality"
AVG_VOL_MIN     = 500_000    # liquidity floor
KNIFE_DROP_PCT  = 8.0        # single-day drop > 8% in last 10 sessions = knife
DEEP_BREAK_PCT  = 25.0       # > 25% below 400MA = likely broken story
FRESH_X_DAILY   = 10         # "fresh" daily MACD cross = within 10 bars
FRESH_X_WEEKLY  = 4          # "fresh" weekly MACD cross = within 4 bars

# 400MA slope — a dip below a RISING long-term MA is a pullback in an uptrend;
# below a FALLING MA it is just a downtrend.
MA_SLOPE_BARS     = 40       # measure MA change over ~2 months of bars
MA_SLOPE_FLAT_TOL = -0.5     # ≥ −0.5% over 40 bars still counts as "flat"

# Fundamentals quality gate (Quality Score /6)
QUALITY_ROE_MIN    = 0.15    # return on equity ≥ 15%
QUALITY_MARGIN_MIN = 0.10    # operating margin ≥ 10%
QUALITY_DE_MAX     = 150.0   # debt/equity ≤ 1.5x (yfinance reports percent)
QUALITY_MCAP_MIN   = 10e9    # market cap ≥ $10B

# Tickers we already know are funds — skip the fundamentals fetch entirely
_KNOWN_ETFS = set(OPTIONS_ETF_UNIVERSE) | set(ETF_UNIVERSE) | {
    "MDY", "RSP", "XLC", "XLB", "XLRE", "XBI", "IEF", "EFA", "VEA",
}

# Process-level fundamentals cache — .info is one HTTP call per ticker
_FUND_CACHE: dict[str, dict] = {}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _macd_state(close: pd.Series, fresh_bars: int) -> dict:
    """MACD line/signal/hist state + fresh-crossover detection."""
    out = {"macd": np.nan, "macd_pos": False, "above_sig": False,
           "hist": np.nan, "hist_rising": False, "fresh_cross": False}
    try:
        macd_l = calc_ema(close, 12) - calc_ema(close, 26)
        sig_l  = calc_ema(macd_l, 9)
        hist_l = (macd_l - sig_l).dropna()
        m, s   = macd_l.dropna(), sig_l.dropna()
        if len(m) < 3 or len(hist_l) < 3:
            return out
        out["macd"]        = float(m.iloc[-1])
        out["macd_pos"]    = float(m.iloc[-1]) > 0
        out["above_sig"]   = float(m.iloc[-1]) > float(s.iloc[-1])
        out["hist"]        = float(hist_l.iloc[-1])
        out["hist_rising"] = float(hist_l.iloc[-1]) > float(hist_l.iloc[-2])
        n = min(fresh_bars, len(m) - 1, len(s) - 1)
        for k in range(1, n + 1):
            if (float(m.iloc[-k]) > float(s.iloc[-k])
                    and float(m.iloc[-k - 1]) <= float(s.iloc[-k - 1])):
                out["fresh_cross"] = True
                break
    except Exception:
        pass
    return out


def _fundamentals(ticker: str) -> dict:
    """
    Business-quality check via yfinance .info (cached per process).

    Quality Score /6:
      ROE ≥ 15% · Operating margin ≥ 10% · FCF > 0 ·
      D/E ≤ 1.5 · Revenue growth > 0 · Market cap ≥ $10B

    Returns {"q": int|None, "detail": str, "mcap_b": float|None, "is_fund": bool}
    q is None for ETFs/funds (N/A) or when no data came back.
    """
    if ticker in _FUND_CACHE:
        return _FUND_CACHE[ticker]

    out = {"q": None, "detail": "", "mcap_b": None, "is_fund": False}
    if ticker in _KNOWN_ETFS:
        out.update(is_fund=True, detail="ETF/fund — fundamentals N/A")
        _FUND_CACHE[ticker] = out
        return out

    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        info = {}

    if str(info.get("quoteType", "")).upper() in ("ETF", "MUTUALFUND", "INDEX"):
        out.update(is_fund=True, detail="ETF/fund — fundamentals N/A")
        _FUND_CACHE[ticker] = out
        return out

    roe  = info.get("returnOnEquity")
    marg = info.get("operatingMargins")
    fcf  = info.get("freeCashflow")
    de   = info.get("debtToEquity")        # yfinance reports percent: 150 = 1.5x
    rg   = info.get("revenueGrowth")
    mcap = info.get("marketCap")

    checks = [
        ("ROE≥15%",   None if roe  is None else bool(roe  >= QUALITY_ROE_MIN),
         "?" if roe  is None else f"{roe*100:.0f}%"),
        ("Marg≥10%",  None if marg is None else bool(marg >= QUALITY_MARGIN_MIN),
         "?" if marg is None else f"{marg*100:.0f}%"),
        ("FCF>0",     None if fcf  is None else bool(fcf > 0),
         "?" if fcf  is None else f"${fcf/1e9:.1f}B"),
        ("D/E≤1.5",   None if de   is None else bool(de <= QUALITY_DE_MAX),
         "?" if de   is None else f"{de/100:.2f}"),
        ("RevGr>0",   None if rg   is None else bool(rg > 0),
         "?" if rg   is None else f"{rg*100:+.0f}%"),
        ("MCap≥$10B", None if mcap is None else bool(mcap >= QUALITY_MCAP_MIN),
         "?" if mcap is None else f"${mcap/1e9:.0f}B"),
    ]

    if all(ok is None for _, ok, _ in checks):
        out["detail"] = "Fundamentals unavailable"
        _FUND_CACHE[ticker] = out
        return out

    out["q"] = int(sum(1 for _, ok, _ in checks if ok is True))
    out["detail"] = " · ".join(
        f"{name} {val} {'✓' if ok else '✗' if ok is False else '?'}"
        for name, ok, val in checks
    )
    out["mcap_b"] = round(mcap / 1e9, 1) if mcap else None
    _FUND_CACHE[ticker] = out
    return out


def _sentiment(score: int, stabilizing: bool) -> str:
    if score >= 7:
        return "🟢 Accumulate"
    if score >= 4:
        return "🟡 Stabilizing" if stabilizing else "🟡 Watch"
    return "🔴 Falling"


# ── Main scan ──────────────────────────────────────────────────────────────────

def scan_ma400(
    tickers: list[str],
    near_pct: float = 10.0,
    only_below: bool = False,
    require_ma_rising: bool = True,
    fundamentals: bool = True,
    status_fn=None,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Scan `tickers` for price close-to/below the 400-day SMA.

    near_pct          : include stocks up to this % ABOVE the 400MA
    only_below        : include only stocks strictly below the 400MA
    require_ma_rising : drop names whose 400MA itself is falling
                        (dip-in-uptrend only, no downtrends)
    fundamentals      : fetch business-quality data (Quality Score /6) for
                        zone-passers only — adds ~1s per surviving ticker

    Returns (results_df sorted deepest-below-first, skipped_tickers).
    """
    rows:    list[dict] = []
    skipped: list[str]  = []

    for i, ticker in enumerate(tickers):
        if status_fn:
            status_fn(i, len(tickers), ticker)

        # ── Daily history (400MA needs ~19 months of bars) ────────────────────
        try:
            df = get_price_history(ticker, period="2y")
            if df is None or df.empty:
                skipped.append(ticker)
                continue
            close = df["Close"].squeeze().dropna()
            if len(close) < MA_LEN:
                skipped.append(ticker)          # too young for a 400d MA
                continue
        except Exception:
            skipped.append(ticker)
            continue

        try:
            vol   = df["Volume"].squeeze()
            price = float(close.iloc[-1])
            prev  = float(close.iloc[-2])
            chg   = round((price - prev) / prev * 100, 2)
        except Exception:
            skipped.append(ticker)
            continue

        # ── Quality guards ────────────────────────────────────────────────────
        if price < PRICE_MIN:
            continue
        try:
            avg_vol = float(vol.iloc[-20:].mean())
        except Exception:
            avg_vol = 0.0
        if avg_vol < AVG_VOL_MIN:
            continue

        # ── 400-day MA and distance ───────────────────────────────────────────
        ma_ser  = close.rolling(MA_LEN).mean().dropna()
        ma400_v = float(ma_ser.iloc[-1]) if len(ma_ser) else np.nan
        if not np.isfinite(ma400_v) or ma400_v <= 0:
            skipped.append(ticker)
            continue
        pct_vs = (price - ma400_v) / ma400_v * 100

        # The zone filter — keep only names at/below (or just above) the line
        if only_below and pct_vs >= 0:
            continue
        if pct_vs > near_pct:
            continue

        # ── 400MA slope — dip in an uptrend vs plain downtrend ────────────────
        if len(ma_ser) > MA_SLOPE_BARS:
            ma_slope = (ma400_v / float(ma_ser.iloc[-1 - MA_SLOPE_BARS]) - 1) * 100
        else:
            ma_slope = 0.0
        ma_rising = ma_slope >= MA_SLOPE_FLAT_TOL
        if require_ma_rising and not ma_rising:
            continue

        # ── Daily indicators ─────────────────────────────────────────────────
        d_rsi = float(calc_rsi(close))
        d_macd = _macd_state(close, FRESH_X_DAILY)

        try:
            ema9_v = float(calc_ema(close, 9).iloc[-1])
        except Exception:
            ema9_v = price
        stabilizing = price > ema9_v

        try:
            sma50_v  = float(calc_sma(close, 50).dropna().iloc[-1])
            sma200_v = float(calc_sma(close, 200).dropna().iloc[-1])
            golden   = sma50_v > sma200_v
        except Exception:
            sma50_v = sma200_v = 0.0
            golden  = True

        # 52-week stats
        try:
            yr        = close.iloc[-252:]
            hi52, lo52 = float(yr.max()), float(yr.min())
            dd_52w    = (price - hi52) / hi52 * 100 if hi52 > 0 else 0.0
            range_pos = (price - lo52) / (hi52 - lo52) * 100 if hi52 > lo52 else 50.0
        except Exception:
            hi52 = lo52 = price
            dd_52w, range_pos = 0.0, 50.0

        # Falling knife: any drop > 8% in last 10 sessions
        try:
            knife = bool((close.pct_change().iloc[-10:] * 100 < -KNIFE_DROP_PCT).any())
        except Exception:
            knife = False

        # Capitulation / distribution volume: 5d avg vol > 2x 60d avg while down
        try:
            v5, v60 = float(vol.iloc[-5:].mean()), float(vol.iloc[-60:].mean())
            ret5    = (price / float(close.iloc[-6]) - 1) * 100
            heavy_selling = v60 > 0 and v5 > 2.0 * v60 and ret5 < 0
        except Exception:
            heavy_selling = False

        # ── Weekly indicators ─────────────────────────────────────────────────
        w_rsi, w_rsi_prev = np.nan, np.nan
        w_macd = {"macd_pos": False, "above_sig": False,
                  "hist_rising": False, "fresh_cross": False}
        try:
            wk = get_price_history(ticker, period="2y", interval="1wk")
            if wk is not None and not wk.empty and len(wk) >= 30:
                wk_close = wk["Close"].squeeze().dropna()
                w_rsi    = float(calc_rsi(wk_close))
                if len(wk_close) >= 5:
                    w_rsi_prev = float(calc_rsi(wk_close.iloc[:-4]))
                w_macd = _macd_state(wk_close, FRESH_X_WEEKLY)
        except Exception:
            pass
        w_rsi_rising = (not np.isnan(w_rsi) and not np.isnan(w_rsi_prev)
                        and w_rsi > w_rsi_prev)

        # ── Dip Score /10 — is this dip buyable NOW? ─────────────────────────
        score = int(sum([
            pct_vs <= 2.0,                                    # 1. at/below the line (≤2% above)
            (not np.isnan(w_rsi)) and w_rsi <= 50,           # 2. weekly pullback confirmed
            (not np.isnan(w_rsi)) and w_rsi >= 30,           # 3. ...but not collapsing
            d_rsi >= 30,                                      # 4. daily selling exhausted
            d_macd["hist_rising"],                            # 5. daily momentum turning up
            d_macd["fresh_cross"] or d_macd["above_sig"],     # 6. daily MACD bullish
            w_macd["above_sig"] or w_macd["hist_rising"],     # 7. weekly momentum improving
            stabilizing,                                      # 8. price back above EMA9
            dd_52w <= -15.0,                                  # 9. meaningful discount vs 52w high
            not knife and not heavy_selling,                  # 10. no active knife/capitulation
        ]))

        # ── Fundamentals quality gate (zone-passers only — keeps scan fast) ──
        q_score, q_detail, mcap_b, is_fund = None, "", None, False
        if fundamentals:
            f = _fundamentals(ticker)
            q_score, q_detail = f["q"], f["detail"]
            mcap_b, is_fund   = f["mcap_b"], f["is_fund"]

        # ── Flags ─────────────────────────────────────────────────────────────
        flags = []
        if not ma_rising:
            flags.append(f"📉 Falling 400MA ({ma_slope:+.1f}%/40d)")
        if fundamentals and q_score is not None and q_score <= 2:
            flags.append(f"🏭 Weak fundamentals ({q_score}/6)")
        if fundamentals and q_score is None and not is_fund:
            flags.append("❔ Fundamentals unavailable")
        if knife:
            flags.append("🔪 Falling knife (>8% day drop)")
        if heavy_selling:
            flags.append("📛 Heavy sell volume")
        if not golden and sma200_v > 0:
            flags.append("💀 Death cross (50<200)")
        if pct_vs < -DEEP_BREAK_PCT:
            flags.append(f"🕳️ Deep break ({pct_vs:.0f}% below)")
        if range_pos <= 5:
            flags.append("🩸 At 52-week low")
        if not np.isnan(w_rsi) and w_rsi < 30:
            flags.append(f"⚠️ W-RSI oversold ({w_rsi:.0f})")
        if d_rsi < 25:
            flags.append(f"⚠️ D-RSI extreme ({d_rsi:.0f})")
        if d_macd["fresh_cross"]:
            flags.append("✨ Fresh daily MACD cross")
        if w_macd["fresh_cross"]:
            flags.append("🌟 Fresh WEEKLY MACD cross")

        rows.append({
            "Ticker":      ticker,
            "Price":       round(price, 2),
            "Chg%":        chg,
            "400MA":       round(ma400_v, 2),
            "MA Slope%":   round(ma_slope, 2),
            "% vs 400MA":  round(pct_vs, 1),
            "52w DD%":     round(dd_52w, 1),
            "52w Pos":     round(range_pos, 0),
            "D-RSI":       round(d_rsi, 1),
            "W-RSI":       round(w_rsi, 1) if not np.isnan(w_rsi) else None,
            "W-RSI ↗":     w_rsi_rising,
            "MACD>0 D":    d_macd["macd_pos"],
            "MACD>0 W":    w_macd["macd_pos"],
            "X-over D":    ("Fresh ↑" if d_macd["fresh_cross"]
                            else "Above" if d_macd["above_sig"] else "Below"),
            "X-over W":    ("Fresh ↑" if w_macd["fresh_cross"]
                            else "Above" if w_macd["above_sig"] else "Below"),
            "Hist↗ D":     d_macd["hist_rising"],
            "Trend":       "Golden" if golden else "Death",
            "Stabilizing": stabilizing,
            "Sentiment":   _sentiment(score, stabilizing),
            "Score":       score,
            "Q":           q_score,
            "Q Detail":    q_detail,
            "MCap $B":     mcap_b,
            "Is Fund":     is_fund,
            "Flags":       " · ".join(flags) if flags else "—",
        })

        time.sleep(0.05 + random.uniform(0, 0.05))   # light throttle

    df_out = pd.DataFrame(rows)
    if not df_out.empty:
        # Deepest below the 400MA on top
        df_out = df_out.sort_values("% vs 400MA").reset_index(drop=True)
    return df_out, skipped
