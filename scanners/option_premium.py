# scanners/option_premium.py — is an option premium actually RICH, or is the
# ticker just permanently volatile?
#
# Every options scanner in this repo answered that with utils.approx_iv_rank(),
# which maps IV onto a fixed 10-80% scale identical for every ticker:
#
#     rank = (iv - 0.10) / (0.80 - 0.10) * 100
#
# That is not an IV rank. It has no idea what NORMAL looks like for the ticker
# in front of it, so it scores SOXL 71 on a dead-calm day and pins every 3x ETF
# at 100 during any real volatility. What it actually measures is "is this a
# volatile ticker" — which, for a list of leveraged ETFs, is always yes. It
# ranks the universe in essentially the same order every single day.
#
# Richness is a comparison against the ticker's OWN normal, and there are two
# honest ways to make it:
#
#   1. IV vs REALIZED volatility (the variance risk premium). Needs nothing
#      stored: compare what options are charging against what the underlying
#      has actually delivered over the same horizon. A ratio near 1.0 means
#      options are priced about right; 1.3+ means the market is charging well
#      over the recent damage. This works from the first run.
#
#   2. IV vs its OWN past IV (a true IV rank/percentile). Strictly better, but
#      it needs history nobody was storing — see scanners/iv_history.py, which
#      accumulates it daily. Until enough sessions exist, callers fall back to
#      (1) and say so rather than quietly reporting a made-up number.
#
# Nothing here fetches a strike or an expiry for display. Both are needed to
# read a premium off the chain, but the output is deliberately ticker-level:
# which ticker is paying unusually well right now, not which contract.

from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pandas as pd

# Trading days per year, for annualising a realised-volatility figure so it is
# directly comparable with an implied-volatility quote (which is annualised).
TRADING_DAYS = 252

# Default realised-vol lookback. 20 sessions ~ one month, roughly matching the
# horizon of the near-dated contracts a premium seller actually writes.
RV_WINDOW = 20

# IV/RV thresholds. Options normally price a little above realised vol -- that
# spread is the seller's edge and exists in calm markets too -- so "rich" has
# to mean well above 1.0, not merely above it.
IV_RV_RICH = 1.30
IV_RV_FAIR = 1.10

# A "falling day" measured in the ticker's own daily range rather than a flat
# percentage: -3% is ordinary for SOXL and a rout for SPY.
DROP_ATR_NOTABLE = 1.0
DROP_ATR_SHARP = 1.75

# How far below its 50-day average counts as an established downtrend rather
# than ordinary chop. Sitting a fraction under the line is normal and vetoing
# it would throw away most sane candidates; sitting well under it is a
# different animal, and no premium compensates for writing puts into one.
KNIFE_SMA_PCT = -5.0


def realized_vol(close: pd.Series, days: int = RV_WINDOW) -> float:
    """Annualised realised volatility from daily closes, as a decimal (0.42).

    Log returns, sample stdev, scaled by sqrt(252) so the result is on the
    same footing as an implied-volatility quote. Returns 0.0 rather than
    raising when there is not enough data — callers treat 0 as "unknown" and
    fall back rather than dividing by it.
    """
    try:
        c = pd.Series(close).dropna().astype(float)
        if len(c) < days + 1:
            return 0.0
        rets = np.log(c / c.shift(1)).dropna().iloc[-days:]
        if len(rets) < 2:
            return 0.0
        sd = float(rets.std(ddof=1))
        if not math.isfinite(sd):
            return 0.0
        return round(sd * math.sqrt(TRADING_DAYS), 4)
    except Exception:
        return 0.0


def iv_rv_ratio(iv: float, rv: float) -> float | None:
    """How much more is the option charging than the stock has delivered?

    1.00 = options priced at the recent realised move. Above ~1.3 the market
    is charging well over recent damage, which is the condition worth selling
    into. None when realised vol is unknown, so a missing input never
    masquerades as a fair-priced 1.0.
    """
    try:
        if not iv or not rv or rv <= 0:
            return None
        return round(float(iv) / float(rv), 3)
    except Exception:
        return None


def atr_move(df: pd.DataFrame, period: int = 14) -> tuple[float, float]:
    """(today's % change, that change measured in ATR units).

    The second number is the one that travels across tickers: -2.1 ATRs is an
    unusual day for anything, while -3% is a Tuesday for SOXL and a crisis
    for SPY. Sign is preserved, so a fall is negative.
    """
    try:
        if df is None or df.empty or len(df) < period + 2:
            return 0.0, 0.0
        close = df["Close"].astype(float)
        prev, last = float(close.iloc[-2]), float(close.iloc[-1])
        chg_pct = (last / prev - 1) * 100 if prev else 0.0

        high, low = df["High"].astype(float), df["Low"].astype(float)
        tr = pd.concat([high - low,
                        (high - close.shift()).abs(),
                        (low - close.shift()).abs()], axis=1).max(axis=1)
        atr = float(tr.rolling(period).mean().iloc[-1])
        if not atr or not math.isfinite(atr) or atr <= 0:
            return round(chg_pct, 2), 0.0
        return round(chg_pct, 2), round((last - prev) / atr, 2)
    except Exception:
        return 0.0, 0.0


def _nearest(df: pd.DataFrame, col: str, target: float) -> pd.Series | None:
    try:
        d = df.dropna(subset=[col])
        if d.empty:
            return None
        return d.iloc[(d[col].astype(float) - target).abs().argsort().iloc[0]]
    except Exception:
        return None


def chain_snapshot(puts: pd.DataFrame, spot: float, dte: int,
                   otm_pct: float = 0.12) -> dict:
    """Reduce one put chain to the few numbers that describe its richness.

    Two IV readings, because they answer different questions:
      * at-the-money IV is the stable reference the IV/RV comparison needs;
      * the out-of-the-money put IV is what a cash-secured put seller is
        actually paid, and on a falling day it is bid up far more than ATM.

    Returns a dict with no strike or expiry in it. Both were used to compute
    these figures; neither is part of the answer, which is about the TICKER.
    """
    out = {"iv_atm": None, "iv_otm": None, "prem_pct": None, "ann_pct": None,
           "spread_pct": None, "open_interest": None, "skew": None}
    if puts is None or puts.empty or spot <= 0:
        return out

    p = puts.copy()
    for c in ("strike", "impliedVolatility", "bid", "ask", "lastPrice", "openInterest"):
        if c in p.columns:
            p[c] = pd.to_numeric(p[c], errors="coerce")
    if "strike" not in p.columns:
        return out

    atm = _nearest(p, "strike", spot)
    if atm is not None and pd.notna(atm.get("impliedVolatility")):
        out["iv_atm"] = round(float(atm["impliedVolatility"]), 4)

    target = spot * (1 - otm_pct)
    otm = _nearest(p, "strike", target)
    if otm is None:
        return out

    if pd.notna(otm.get("impliedVolatility")):
        out["iv_otm"] = round(float(otm["impliedVolatility"]), 4)
    if out["iv_atm"] and out["iv_otm"]:
        # Put skew: how much more the downside is bid than at-the-money. It
        # spikes when people are paying up for protection, which is exactly
        # the moment a seller is being paid best.
        out["skew"] = round(out["iv_otm"] - out["iv_atm"], 4)

    bid = float(otm.get("bid") or 0)
    ask = float(otm.get("ask") or 0)
    mid = (bid + ask) / 2 if (bid > 0 and ask > 0) else float(otm.get("lastPrice") or 0)
    strike = float(otm["strike"])
    if mid > 0 and strike > 0:
        out["prem_pct"] = round(mid / strike * 100, 2)
        if dte and dte > 0:
            out["ann_pct"] = round(mid / strike * (365 / dte) * 100, 1)
        if ask > 0 and bid > 0 and mid > 0:
            out["spread_pct"] = round((ask - bid) / mid * 100, 1)
    if pd.notna(otm.get("openInterest")):
        out["open_interest"] = int(otm["openInterest"])
    return out


def pick_expiry(expiries: list[str], dte_min: int = 21, dte_max: int = 45,
                today: datetime | None = None) -> tuple[str | None, int]:
    """First expiry inside the window, and its DTE.

    Used to read a representative premium, not to recommend a contract. The
    default 21-45 day window is where a premium seller's theta is best paid
    relative to gamma risk; it is a measurement horizon, nothing more.
    """
    today = today or datetime.now()
    best = (None, 0)
    for e in expiries or []:
        try:
            dte = (datetime.strptime(e, "%Y-%m-%d") - today).days
        except Exception:
            continue
        if dte_min <= dte <= dte_max:
            return e, dte
        # Remember the closest thing outside the window as a fallback.
        if best[0] is None and dte > 0:
            best = (e, dte)
    return best


# Anchors mapping IV/RV onto the 0-100 scale the existing scanners already
# speak, so premium_rank() is a drop-in for approx_iv_rank. Options normally
# carry a small premium over realised vol even in calm markets, which is why
# 1.00x maps to 30 rather than 50: fairly priced is not "unusually high".
_RATIO_ANCHORS = [0.80, 1.00, IV_RV_FAIR, IV_RV_RICH, 1.60]
_RANK_ANCHORS = [0.0, 30.0, 45.0, 70.0, 100.0]


def premium_rank(iv: float, rv: float, stored_rank: float | None = None) -> dict:
    """A real 0-100 answer to "how expensive is this option FOR THIS TICKER".

    Drop-in for utils.approx_iv_rank, which every options scanner used and
    which is not a rank at all — a fixed 10-80% IV scale identical for every
    ticker. Its practical effect was to turn the scanners' "IV Rank" sliders
    into hard IV floors and ceilings: a Min IV Rank of 25 means "IV >= 27.5%",
    which permanently excludes AAPL, SPY, KO and JNJ from the CSP scan however
    expensive their options become, while a Max IV Rank of 35 means
    "IV <= 34.5%" and permanently excludes NVDA, TSLA and the semis from the
    LEAPS scan however cheap theirs become.

    Two sources, best first:
      "history"  the ticker's own stored IV range (see scanners/iv_history)
                 — the real thing, once enough sessions exist;
      "realised" IV against realised volatility, mapped onto the same 0-100
                 scale — available immediately, and still a comparison against
                 the ticker's own behaviour rather than a universal constant.

    Known limit of the "realised" source: IV/RV still carries a per-asset
    baseline, just a far smaller one than raw IV. Index options run a
    persistent variance risk premium — SPY sits around 1.2-1.4x even in calm
    markets — while single stocks run lower, so a fixed cross-ticker threshold
    is generous to indices and harsh on stocks. That is why the daily snapshot
    records iv_rv as well as iv_atm: once history matures,
    iv_history.best_rank() ranks the RATIO against its own past and the
    baseline cancels out entirely. Until then, compare like with like —
    indices against indices, stocks against stocks.

    Returns {rank, source, iv_rv}. rank is None only when neither is
    computable, so callers can skip rather than assume.
    """
    ratio = iv_rv_ratio(iv, rv)
    if stored_rank is not None:
        return {"rank": float(stored_rank), "source": "history", "iv_rv": ratio}
    if ratio is None:
        return {"rank": None, "source": "none", "iv_rv": None}
    rank = float(np.interp(ratio, _RATIO_ANCHORS, _RANK_ANCHORS))
    return {"rank": round(max(0.0, min(100.0, rank)), 1),
            "source": "realised", "iv_rv": ratio}


def assess(iv: float, rv: float, drop_atr: float, iv_rank: float | None,
           spread_pct: float | None, sma50_pct: float | None,
           rsi: float | None = None) -> dict:
    """Turn the measurements into a verdict with its reasons attached.

    Deliberately conservative on two fronts. Rich premium is necessary but
    never sufficient: premium is richest precisely when something is going
    wrong, so a ticker in free-fall is excluded no matter what it pays. And a
    wide spread quietly eats the edge, so it caps the verdict rather than
    merely docking points.
    """
    ratio = iv_rv_ratio(iv, rv)
    reasons: list[str] = []

    if ratio is None:
        return {"verdict": "No data", "score": 0, "iv_rv": None,
                "reasons": ["not enough data to judge richness"]}

    score = 0
    if ratio >= IV_RV_RICH:
        score += 40
        reasons.append(f"options charging {ratio:.2f}× recent realised moves")
    elif ratio >= IV_RV_FAIR:
        score += 20
        reasons.append(f"premium mildly above realised ({ratio:.2f}×)")
    else:
        reasons.append(f"premium is not rich ({ratio:.2f}× realised)")

    # A true rank when history allows it; silent when it does not, rather
    # than substituting a fabricated one.
    if iv_rank is not None:
        if iv_rank >= 70:
            score += 25
            reasons.append(f"IV in the top {100 - iv_rank:.0f}% of its own year")
        elif iv_rank >= 50:
            score += 12
            reasons.append(f"IV above its own median (rank {iv_rank:.0f})")
        else:
            reasons.append(f"IV below its own median (rank {iv_rank:.0f})")

    if drop_atr <= -DROP_ATR_SHARP:
        score += 25
        reasons.append(f"sharp drop today ({drop_atr:.1f} ATRs)")
    elif drop_atr <= -DROP_ATR_NOTABLE:
        score += 15
        reasons.append(f"down {abs(drop_atr):.1f} ATRs today")

    if spread_pct is not None:
        if spread_pct <= 5:
            score += 10
        elif spread_pct > 15:
            reasons.append(f"wide spread ({spread_pct:.0f}%) eats the edge")

    below = sma50_pct is not None and sma50_pct < 0
    deep_below = sma50_pct is not None and sma50_pct <= KNIFE_SMA_PCT
    if sma50_pct is None:
        pass
    elif deep_below:
        reasons.append(f"{abs(sma50_pct):.0f}% below its 50-day — established downtrend")
    elif below:
        reasons.append(f"{abs(sma50_pct):.1f}% under its 50-day")
    else:
        reasons.append("still above its 50-day average")

    score = max(0, min(score, 100))

    # Verdict. Structure over arithmetic: these are veto conditions, not
    # penalties to be outweighed by a big enough premium.
    # Two ways to be a knife, and requiring both was the bug: a ticker 11%
    # under its 50-day and grinding lower is a knife whether or not TODAY was
    # dramatic. The trend is the risk; the single bad bar is just the day you
    # happened to look.
    if below and (drop_atr <= -DROP_ATR_SHARP or deep_below):
        verdict = "Avoid — knife"
    elif spread_pct is not None and spread_pct > 15:
        verdict = "Illiquid"
    elif ratio >= IV_RV_RICH and drop_atr <= -DROP_ATR_NOTABLE and not below:
        verdict = "Prime CSP"
    elif ratio >= IV_RV_RICH:
        verdict = "Rich premium"
    elif ratio >= IV_RV_FAIR:
        verdict = "Fair"
    else:
        verdict = "Thin"

    return {"verdict": verdict, "score": score, "iv_rv": ratio, "reasons": reasons}
