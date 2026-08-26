# scanners/fast_score.py — Fast Score scanner (Market Overview → ⚡ Fast Score tab)
#
# WHAT IT LOOKS FOR
# -----------------
# A liquid large cap in a confirmed multi-year uptrend that is *still*
# accelerating, which has pulled back to touch its long-term weekly moving
# average on QUIET volume without breaking it, and whose weekly MACD is
# turning back up. Everything is computed on WEEKLY bars — there is no daily
# input anywhere in this file.
#
# The three tiers are one signal at three ages, not three quality grades:
#   Early / Pre-Cross  weekly MACD still below signal, but closing the gap
#   Fresh Setups       MACD crossed up within the last FRESH_CROSS_WKS weeks
#   Further Along      MACD crossed up longer ago; the bounce is underway
#
# HARD GATES (a ticker fails the scan if any one of these fails)
#   1. 52-week regression slope >= MIN_SLOPE_52W    long trend up
#   2. 26-week regression slope > 0                 medium trend up
#   3. slope ratio (26w/52w)   >= MIN_SLOPE_RATIO   trend not decaying
#   4. a valid touch of the 50-week SMA in the last TOUCH_LOOKBACK_WKS weeks,
#      at a depth inside [TOUCH_MIN_PCT, TOUCH_MAX_PCT], and the line has HELD
#      every week since (no weekly close more than |TOUCH_MIN_PCT| below it)
#   5. 3-week change in the MACD gap > 0 AND >= MIN_MACD_DELTA_PCT of price
#   6. volume ratio <= MAX_VOL_RATIO                pullback happened quietly
#   7. >= MIN_WEEKLY_BARS of weekly history         200W SMA needs ~4 years
#   8. close >= MIN_PRICE
#   9. a FALLING 200-week SMA is only allowed within MAX_DIST_IF_LT_FALLING
#      of it — buying the base of a recovery, not the back half of a bounce
#  10. close within MAX_EXT_50W of the 50-week SMA  pullback entry still open
#  11. weekly RSI(14) <= MAX_RSI                    not already overbought
#  12. weekly MFI(14) <= MAX_MFI                    not in the take-profit zone
#
# WHY THE SLOPE RATIO CLUSTERS NEAR 0.50
#   Both slopes are the total rise of a least-squares regression line across
#   their window, as a % of that line's starting value. A perfectly steady
#   trend therefore covers half as much ground in half the time, so ratio
#   ~0.50 == steady, >0.50 == accelerating, <0.50 == decaying. That is the
#   whole reason the ratio is a gate rather than a display column.
#
# FAST SCORE (0-15)
#   Five components, 0-3 points each — see _score_row(). It ranks the
#   survivors, it does not filter them: everything in the table already
#   passed all twelve gates above. MACD delta is SCORED as a % of price but
#   DISPLAYED raw, because a $2,000 stock and a $50 stock produce MACD
#   values two orders of magnitude apart and a raw threshold would just be
#   a price filter wearing a momentum costume.
#
# Consumed by:
#   scanners/home.py                     the ⚡ Fast Score tab
#   scripts/headless_fast_score_scan.py  the weekly Friday-evening email

from __future__ import annotations

import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    FTF_UNIVERSE, MTPA_200, SP500_SAMPLE,
    GOLD, BG_PANEL, BG_CARD, BORDER_COLOR, TEXT_PRIMARY, TEXT_MUTED,
    ACCENT_GREEN, ACCENT_RED,
)
from data_loader import get_price_history, prefetch_tickers

# ── Tunables ───────────────────────────────────────────────────────────────
MIN_SLOPE_52W     = 5.0    # %   long-term regression must rise at least this much
MIN_SLOPE_26W     = 0.0    # %   medium-term regression must be positive
MIN_SLOPE_RATIO   = 0.25   #     26w rise / 52w rise
TOUCH_LOOKBACK_WKS = 52    #     how far back a qualifying touch may be
TOUCH_MIN_PCT     = -2.0   # %   deepest allowed break below the 50w SMA
TOUCH_MAX_PCT     = 8.0    # %   furthest above the 50w SMA that still counts
MAX_VOL_RATIO     = 1.10   # x   4w avg volume / 26w avg volume
# The 3-week MACD improvement must be big enough to mean something. A bare
# "> 0" test passes a name whose MACD gap improved by 0.00002 -- on a smooth
# trend the gap approaches its steady state from below, so the delta is
# positive but economically nil. Expressed as % of price so a $2,000 stock
# and a $50 stock face the same bar; 0.02% sits just under the smallest
# genuine reading observed on a real scan (+0.16 on a $382 close = 0.042%).
MIN_MACD_DELTA_PCT = 0.02  # %   of price
FRESH_CROSS_WKS   = 8      #     MACD cross this recent == "Fresh Setups"
# Slope-ratio scoring band. ~0.50 is a steady trend, so 0.60-2.00 is
# "accelerating and still measured against a meaningful 52-week base".
# Past RATIO_UNSTABLE the denominator is so small the ratio says more about
# the base being flat than about the trend being strong.
RATIO_BEST_LO     = 0.60
RATIO_BEST_HI     = 2.00
RATIO_UNSTABLE    = 5.00
# Exhaustion gates. The scanner previously had NO concept of whether the
# opportunity was still available: it confirmed the setup had HAPPENED
# (trend up, line touched, MACD turned) and never asked whether the move
# was already spent. That is how a name printing RSI 69.8 / MFI 70.8 --
# "Overbought / Take Profit" on the very panel used to vet these -- reached
# the top of the table. Thresholds match that panel's own bands.
MAX_RSI           = 68.0   #     weekly RSI(14) above this = overbought
MAX_MFI           = 70.0   #     weekly MFI(14) above this = take-profit zone
RSI_BUY_LO        = 45.0   #     the panel's "Buy Zone" band
RSI_BUY_HI        = 65.0
# The setup is "price pulled back TO the 50-week line". Once price has run
# far above it again the pullback entry is gone, however good the trend is.
MAX_EXT_50W       = 25.0   # %   current close above the 50-week SMA
# "Confirmed multi-year uptrend" was asserted in this file's own description
# while nothing in the code ever looked further back than 52 weeks. A stock
# that collapsed and is bouncing passes every 52-week test yet has a 200-week
# average still FALLING -- that is a rally inside a long-term downtrend.
#
# Rejecting every falling-200w name outright would also throw out the early
# crash-recovery setups this scanner is best at (the reference scan's 15/15
# was one). The distinction that separates them is not the falling average,
# it is WHERE you are buying against it: right at the base is the setup,
# 40% above it is the back half of a dead-cat bounce.
LT_SLOPE_WINDOW_WKS = 26   #     window for measuring the 200-week SMA's slope
MAX_DIST_IF_LT_FALLING = 15.0  # % above a FALLING 200-week SMA still allowed
# How far the bounce off the touch low may already have run before the
# "room left" component stops paying out.
BOUNCE_SPENT_PCT  = 50.0   # %
MIN_WEEKLY_BARS   = 200    #     enough history for a 200-week SMA
MIN_PRICE         = 5.0    # $

TREND_SMA_WKS = 50         # the "golden line" price pulls back to
LONG_SMA_WKS  = 200        # the 200-week SMA used for the stretch column
FETCH_PERIOD  = "10y"
FETCH_INTERVAL = "1wk"
PREFETCH_CHUNK = 120       # yfinance bulk-download batch size

TIER_EARLY   = "Early"
TIER_FRESH   = "Fresh"
TIER_FURTHER = "Further Along"

# Tier order used for tie-breaks: an earlier entry has more of the move left,
# so at equal score the less-advanced setup ranks first.
_TIER_RANK = {TIER_EARLY: 0, TIER_FRESH: 1, TIER_FURTHER: 2}
_TIER_COLOR = {TIER_EARLY: "#F5C842", TIER_FRESH: "#34D399", TIER_FURTHER: "#60A5FA"}
_TIER_LABEL = {TIER_EARLY: "Early", TIER_FRESH: "Fresh", TIER_FURTHER: "Further Along"}

UNIVERSE_CHOICES = {
    "FTF Universe (~500 · full S&P 500)": "FTF",
    "MTPA 200 (stock-heavy)": "MTPA",
    "S&P 500 sample (360)": "SP500",
}

# Funds are excluded by default: a 200-week trend/pullback read on a 3x
# leveraged ETF measures the decay of the wrapper, not the trend of anything
# investable, and the sector column would be meaningless for all of them.
_FUND_TICKERS = {
    "SPY","QQQ","IWM","DIA","VTI","VOO","MDY","RSP","UVXY","VXX",
    "GLD","SLV","TLT","IEF","HYG","LQD","USO","UNG","GDX","GDXJ",
    "XLK","XLF","XLE","XLV","XLI","XLU","XLP","XLY","XLC","XLB","XLRE","XBI",
    "SOXX","SMH","ARKK","IBB","EEM","FXI","EWZ","KWEB","VNQ","EFA",
    "VWO","AGG","BND","XRT","KRE","IAT","ARKW","IYR","MUB","VCIT","VCSH",
    "TQQQ","SOXL","TECL","CURE","NAIL","UPRO","SPXL","TNA","FNGU","LABU",
    "FAS","UDOW","DPST","HIBL","NUGT","WEBL","NVDL","3TSL","DFEN","ERX",
    "URTY","WANT","MIDU","INDL","BULZ",
    "SQQQ","SOXS","SPXS","TECS","FNGD","LABD","WEBS","FAZ","TZA","SDOW",
}


# ── Fast Score universe extension ─────────────────────────────────────────
# FTF_UNIVERSE is S&P 500-shaped, and this setup's best candidates are
# precisely the liquid large caps that sit OUTSIDE that index: the high-beta
# names that fall hard and recover, which is what puts a stock back at its
# 200-week line while it is ripping 15%+ in three weeks. Six such names were
# missing outright (COIN, MSTR, MELI, ALNY, ULTA, PDD) and they were four of
# the top seven on the reference scan -- COIN scored 15/15 there.
#
# Added here rather than in config.FTF_UNIVERSE on purpose: that list is
# shared with First Things First and Best Scanners, and silently changing
# what those scan is a side effect nobody asked for.
#
# Names that IPO'd too recently are self-filtering -- MIN_WEEKLY_BARS needs
# ~4 years of history for the 200-week SMA, so they are simply skipped.
_EXTRA_TICKERS = [
    # the six the reference scan had and FTF does not
    "COIN", "MSTR", "MELI", "ALNY", "ULTA", "PDD",
    # same character: liquid, optionable, high-beta, non-S&P or recent adds
    "SHOP", "SE", "NU", "SPOT", "TTD", "DASH", "SNAP", "PINS", "RBLX",
    "HOOD", "SOFI", "AFRM", "U", "ZM", "TWLO", "DOCU", "OKTA", "CVNA",
    "CHWY", "DKNG", "W", "ROKU", "BABA", "JD", "NTES", "BIDU", "RIVN",
    "LCID", "SMCI", "IONQ", "ZETA", "TOST", "GTLB", "S", "ESTC",
]


# Dual share classes are one company producing two near-identical rows that
# push a genuinely different name off the table (GOOG and GOOGL landed at
# ranks 22 and 23 of the same scan with metrics matching to two decimals).
# Collapsed AFTER scoring rather than dropped from the universe, so whichever
# class actually scores better is the one kept.
_SHARE_CLASS_GROUPS = {
    "GOOG": "GOOGL", "GOOGL": "GOOGL",
    "FOX": "FOXA", "FOXA": "FOXA",
    "NWS": "NWSA", "NWSA": "NWSA",
    "UA": "UAA", "UAA": "UAA",
}


def universe_for(kind: str, include_funds: bool = False,
                 include_extras: bool = True) -> list[str]:
    """Resolve a universe name to a de-duplicated ticker list.

    include_extras appends _EXTRA_TICKERS (see above) — on by default,
    because without them the scan cannot see the cohort this setup is
    best at finding.
    """
    base = {"FTF": FTF_UNIVERSE, "MTPA": MTPA_200, "SP500": SP500_SAMPLE}.get(
        (kind or "FTF").upper(), FTF_UNIVERSE
    )
    out = list(base) + (list(_EXTRA_TICKERS) if include_extras else [])
    out = list(dict.fromkeys(out))
    if not include_funds:
        out = [t for t in out if t not in _FUND_TICKERS]
    return out


# ── Sector labels ──────────────────────────────────────────────────────────
# Deliberately NOT the 11 GICS sectors: "Technology" lumps a fab-equipment
# maker in with a seat-licence SaaS business, and those two trade nothing
# alike. These are the trading-desk buckets the setup actually clusters in.
_SECTOR_GROUPS = {
    "Mega Tech": [
        "AAPL","MSFT","NVDA","AMZN","GOOGL","GOOG","META","AVGO","TSLA","NFLX",
        "ORCL","CSCO","IBM","ANET","MSTR","PLTR","APP","UBER","LYFT",
        "SHOP","SPOT","SNAP","PINS","RBLX","ROKU","U","ZM","BIDU",
    ],
    "Semis": [
        "AMD","AMAT","ADI","TXN","QCOM","MCHP","SWKS","KEYS","TER","MPWR",
        "LRCX","KLAC","MRVL","MU","ON","NXPI","STX","WDC","NTAP","TEL",
        "APH","GLW","INTC","SMCI",
    ],
    "SaaS": [
        "CRM","ADBE","INTU","NOW","PANW","CRWD","FTNT","NET","ZS","WDAY",
        "SNOW","DDOG","MDB","OKTA","CDNS","SNPS","ADSK","TEAM","VRSN","AKAM",
        "CTSH","IT","PAYC","BR","EFX","SAIC","LDOS","BAH","CACI","ANSS","PTC",
        "ADP","PAYX","FIS","FI","ACN","EPAM","DXC","CDW","ZBRA","FFIV","JNPR",
        "HPE","HPQ","CSGP","VRSK","TRMB","ROP",
        "TTD","TWLO","DOCU","GTLB","S","ESTC","ZETA","IONQ",
    ],
    "Biotech": [
        "LLY","MRK","ABBV","PFE","BMY","AMGN","GILD","REGN","VRTX","MRNA",
        "BIIB","JNJ","UNH","CVS","WBA","MCK","CAH","COR","MOH","HUM","ELV",
        "CI","DVA","LH","DGX","RVTY","OGN","TMO","ABT","ISRG","EW","SYK",
        "BSX","MDT","DHR","ZTS","IDXX","IQV","VEEV","DXCM","RMD","ALGN",
        "HCA","HOLX","STE","PODD","GEHC","MTD","WAT","A","ILMN","BIO",
        "VTRS","TFX","ZBH","HSIC","PDCO","ALNY","CNC",
    ],
    "Finance": [
        "BRK-B","JPM","BAC","WFC","C","GS","MS","USB","PNC","TFC","COF",
        "ZION","CFG","FITB","KEY","HBAN","AIG","PRU","MET","AFL","ALL",
        "TRV","CB","PGR","MCO","HIG","UNM","GL","RE","WTW","BX","KKR",
        "SCHW","AXP","SPGI","ICE","CME","NDAQ","BK","STT","NTRS","AMP",
        "TROW","RJF","BEN","RF","WRB","CINF","FAF","FHN","IVZ","CBOE",
        "MKTX","VOYA","BLK","AON","MMC","V","MA","COIN",
        "NU","HOOD","SOFI","AFRM",
    ],
    "Retail": [
        "WMT","COST","HD","LOW","TJX","ROST","MCD","NKE","SBUX","BKNG",
        "ABNB","MAR","HLT","LULU","AZO","ORLY","TSCO","BBY","KMX","ETSY",
        "RL","TPR","DIS","CMCSA","CHTR","RDDT","WBD","FOXA","NWSA","TMUS",
        "VZ","T","MGM","LVS","WYNN","CZR","MAT","RCL","CCL","NCLH",
        "MELI","PDD","ULTA","DG","DLTR","KR","SYY","DPZ","YUM","MNST",
        "SE","BABA","JD","NTES","CVNA","CHWY","W","DKNG","TOST","DASH",
    ],
    "Staples": [
        "PG","KO","PEP","MDLZ","STZ","MO","PM","EL","CL","KMB","GIS",
        "HSY","MKC","HRL","SJM","CPB","CAG","TAP","ADM","CHD","CLX",
    ],
    "Industrials": [
        "GE","BA","RTX","LMT","GD","NOC","LHX","TDG","HWM","AXON","TDY",
        "CW","CAT","DE","HON","EMR","ETN","ITW","PH","ROK","IR","GNRC",
        "TT","NDSN","AOS","MAS","PNR","XYL","MMM","FAST","GWW","URI",
        "CMI","CARR","OTIS","PCAR","CTAS","VLTO","IEX","RRX","ALLE",
        "UNP","CSX","NSC","UPS","FDX","UAL","DAL","LUV","AAL","ODFL",
        "JBHT","EXPD","WM","RSG","CPRT","F","GM","APTV","BWA","GPC","LKQ",
        "RIVN","LCID",
    ],
    "Energy": [
        "XOM","CVX","COP","OXY","EOG","SLB","HAL","BKR","MRO","DVN",
        "FANG","APA","CTRA","PSX","MPC","VLO","KMI","WMB","OKE","CEG",
    ],
    "Utilities": [
        "NEE","DUK","SO","D","AEP","EXC","SRE","PEG","XEL","WEC","ES",
        "DTE","ETR","PPL","FE","CMS","AES","NRG","ED","EIX","NI","LNT",
        "EVRG","AWK","VST",
    ],
    "Metals": [
        "LIN","ECL","SHW","APD","DD","DOW","NEM","FCX","NUE","ALB",
        "VMC","MLM","STLD","RS","PKG","IP","AVY","CCK","BALL","OLN",
        "SEE","SON","SW",
    ],
    "Homebuilders": ["DHI","LEN","PHM","NVR","TOL"],
    "REITs": [
        "AMT","EQIX","CCI","PSA","PLD","AVB","EQR","WELL","VTR","O",
        "DLR","IRM","SBAC","EXR","ARE","BXP","KIM","REG","SPG","WPC",
        "EGP","CPT","UDR","NNN","CUBE",
    ],
}

_SECTOR_MAP: dict[str, str] = {}
for _sector, _tickers in _SECTOR_GROUPS.items():
    for _t in _tickers:
        _SECTOR_MAP.setdefault(_t, _sector)


def sector_of(ticker: str) -> str:
    if ticker in _FUND_TICKERS:
        return "ETF"
    return _SECTOR_MAP.get(ticker, "Other")


# ══════════════════════════════════════════════════════════════════════════
# METRICS
# ══════════════════════════════════════════════════════════════════════════

def _regression_rise_pct(series: pd.Series) -> float | None:
    """Total rise of a least-squares line through `series`, as % of its start.

    Using the fitted line's endpoints rather than the raw first/last closes
    is what makes this robust: a single spike in the first or last week can
    swing a raw point-to-point change by 20%+ while barely moving the fit.
    """
    vals = pd.to_numeric(series, errors="coerce").dropna().to_numpy(dtype=float)
    n = len(vals)
    if n < 8:
        return None
    x = np.arange(n, dtype=float)
    slope, intercept = np.polyfit(x, vals, 1)
    start = intercept
    end = intercept + slope * (n - 1)
    if not np.isfinite(start) or not np.isfinite(end) or start <= 0:
        return None
    return float((end - start) / start * 100.0)


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Standard MACD on weekly closes. Returns (macd_line, signal_line, gap)."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line, macd_line - signal_line


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI on weekly closes.

    Wilder smoothing (alpha = 1/period), not a simple mean — a simple mean
    reads several points hot near turns and would defeat the whole purpose
    of an exhaustion gate.
    """
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return (100.0 - 100.0 / (1.0 + rs)).fillna(100.0)


def _mfi(high: pd.Series, low: pd.Series, close: pd.Series,
         volume: pd.Series, period: int = 14) -> pd.Series:
    """Money Flow Index — RSI weighted by volume, on the typical price.

    Volume-weighted is the point: it separates a rally the money is still
    entering from one running on fumes, which a price-only oscillator
    cannot see.
    """
    typical = (high + low + close) / 3.0
    raw_flow = typical * volume
    direction = typical.diff()
    pos = raw_flow.where(direction > 0, 0.0).rolling(period).sum()
    neg = raw_flow.where(direction < 0, 0.0).rolling(period).sum()
    ratio = pos / neg.replace(0.0, np.nan)
    return (100.0 - 100.0 / (1.0 + ratio)).fillna(50.0)


def _weeks_since_cross_up(gap: pd.Series) -> int | None:
    """Weeks since the gap last crossed from <=0 to >0. None if never / still below."""
    g = gap.to_numpy(dtype=float)
    n = len(g)
    if n < 2 or g[-1] <= 0:
        return None
    for i in range(n - 1, 0, -1):
        if g[i] > 0 >= g[i - 1]:
            return int(n - 1 - i)
    return int(n - 1)          # positive for the entire visible history


def _find_touch(low: pd.Series, close: pd.Series, sma: pd.Series) -> dict | None:
    """Most recent qualifying pullback to the 50-week SMA, if the line held.

    A "touch" is a week whose LOW came inside [TOUCH_MIN_PCT, TOUCH_MAX_PCT]
    of the SMA. The most recent such week wins. The setup is then void if any
    week AFTER it closed more than |TOUCH_MIN_PCT| below the line — that is
    a break of the trend, not a bounce off it, and without this check a stock
    that touched, broke down, and merely bounced off a lower low would score
    as a textbook pullback.
    """
    n = len(close)
    start = max(0, n - TOUCH_LOOKBACK_WKS)
    depth_low = (low - sma) / sma * 100.0
    depth_close = (close - sma) / sma * 100.0

    for i in range(n - 1, start - 1, -1):
        d = depth_low.iloc[i]
        if not np.isfinite(d) or not (TOUCH_MIN_PCT <= d <= TOUCH_MAX_PCT):
            continue
        after = depth_close.iloc[i + 1:]
        if len(after) and float(after.min()) < TOUCH_MIN_PCT:
            return None                     # line broke after the touch
        touch_low = float(low.iloc[i])
        if touch_low <= 0:
            return None
        return {
            "touch_pct": float(d),
            "wks_since_touch": int(n - 1 - i),
            "bounce_pct": float((close.iloc[-1] - touch_low) / touch_low * 100.0),
        }
    return None


def _score_row(r: dict) -> tuple[int, dict]:
    """Fast Score, 0-15. Five components, 0-3 each. Returns (total, per-part)."""
    parts = {}

    # 15% was too high a bar for 3 points: on a real scan only 3 of 25 rows
    # cleared it, and NONE of those 3 were also near the 200-week line, so a
    # 14 or 15 overall was not merely rare but arithmetically unreachable.
    a = r["accel_3w"]
    parts["accel"] = 3 if a >= 12 else 2 if a >= 5 else 1 if a >= 0 else 0
    # ...but a three-week rip is exactly what pushes RSI toward overbought,
    # so paying full marks for the move while charging nothing for the
    # extension it created let the score reward its own worst entries. Once
    # RSI leaves the buy band the acceleration is history, not opportunity.
    if r.get("rsi") is not None and r["rsi"] > RSI_BUY_HI:
        parts["accel"] = min(parts["accel"], 1)

    # Normalised by price — see the module header for why.
    m = r["macd_delta_3w"] / r["close"] * 100.0 if r["close"] else 0.0
    parts["macd"] = 3 if m >= 1.0 else 2 if m >= 0.5 else 1 if m >= 0.15 else 0

    # BANDED, not "higher is better". The ratio is 26w rise / 52w rise, so a
    # huge value means the 52-week DENOMINATOR was near zero, not that the
    # trend is exceptional -- a name that went nowhere for six months then
    # ripped prints 18.52 and is a noisier read than a clean 1.0, yet the old
    # ">= 0.60 -> 3" rule handed both the same maximum. On a real 25-row scan
    # that gave 20 of 25 rows the max, so the component ranked nothing.
    sr = r["slope_ratio"]
    if RATIO_BEST_LO <= sr <= RATIO_BEST_HI:
        parts["ratio"] = 3
    elif 0.45 <= sr < RATIO_BEST_LO or RATIO_BEST_HI < sr <= 3.00:
        parts["ratio"] = 2
    elif 0.30 <= sr < 0.45 or 3.00 < sr <= RATIO_UNSTABLE:
        parts["ratio"] = 1
    else:
        parts["ratio"] = 0

    # Closer to (or below) the 200-week line scores best: that is where the
    # asymmetry lives. Far above it the move is mostly already paid out.
    # Widened alongside accel for the same reason: in a bull market a quality
    # name sits 40-100% above its 200-week SMA, so a 25% cut-off for 3 points
    # was scoring "has not moved in four years" rather than "has room left".
    d = r["dist_200w"]
    if d < -30:
        parts["dist200"] = 1
    elif d <= 35:
        parts["dist200"] = 3
    elif d <= 75:
        parts["dist200"] = 2
    elif d <= 140:
        parts["dist200"] = 1
    else:
        parts["dist200"] = 0
    # This component is "how much room is left", and the 200-week distance
    # only tells half of that story. bounce_pct -- how far price has ALREADY
    # travelled from the touch low -- was being computed, stored and shown
    # while contributing nothing. A name up 55% off its low has spent the
    # move this scanner exists to catch early, whatever its 200w distance
    # says, so it can no longer claim full marks for having room.
    b = r.get("bounce_pct")
    if b is not None and b > BOUNCE_SPENT_PCT:
        parts["dist200"] = min(parts["dist200"], 1)

    v = r["vol_ratio"]
    parts["vol"] = 3 if v <= 0.90 else 2 if v <= 1.00 else 1 if v <= 1.10 else 0

    return int(sum(parts.values())), parts


def evaluate_ticker(ticker: str, weekly: pd.DataFrame) -> dict | None:
    """Run every gate against one ticker's weekly bars. None == did not qualify."""
    if weekly is None or weekly.empty:
        return None
    need = {"Close", "High", "Low", "Volume"}
    if not need.issubset(set(weekly.columns)):
        return None

    df = weekly.dropna(subset=["Close"]).copy()

    # Drop the in-progress week. Every gate here is defined on settled bars,
    # and a Wednesday-afternoon partial week would flip MACD gaps and volume
    # ratios back and forth between runs on data that is not final yet.
    if len(df) and _is_partial_week(df.index[-1]):
        df = df.iloc[:-1]

    if len(df) < MIN_WEEKLY_BARS:
        return None

    close = pd.to_numeric(df["Close"], errors="coerce")
    high = pd.to_numeric(df["High"], errors="coerce")
    low = pd.to_numeric(df["Low"], errors="coerce")
    volume = pd.to_numeric(df["Volume"], errors="coerce")
    if close.isna().any():
        close = close.ffill()
        low = low.fillna(close)
        high = high.fillna(close)
    px = float(close.iloc[-1])
    if not np.isfinite(px) or px < MIN_PRICE:
        return None

    # 1-3 · trend gates
    slope_52 = _regression_rise_pct(close.iloc[-52:])
    slope_26 = _regression_rise_pct(close.iloc[-26:])
    if slope_52 is None or slope_26 is None:
        return None
    if slope_52 < MIN_SLOPE_52W or slope_26 <= MIN_SLOPE_26W:
        return None
    ratio = slope_26 / slope_52
    if ratio < MIN_SLOPE_RATIO:
        return None

    # 4 · pullback to the 50-week line, and the line held
    sma_trend = close.rolling(TREND_SMA_WKS).mean()
    if not np.isfinite(sma_trend.iloc[-1]):
        return None
    touch = _find_touch(low, close, sma_trend)
    if touch is None:
        return None

    # 5 · weekly MACD improving over 3 weeks
    macd_line, signal_line, gap = _macd(close)
    if len(gap) < 4:
        return None
    macd_gap = float(gap.iloc[-1])
    macd_delta_3w = float(gap.iloc[-1] - gap.iloc[-4])
    if macd_delta_3w <= 0:
        return None
    if macd_delta_3w / px * 100.0 < MIN_MACD_DELTA_PCT:
        return None

    # 6 · the pullback happened on quiet volume
    v4 = float(volume.iloc[-4:].mean())
    v26 = float(volume.iloc[-26:].mean())
    if not np.isfinite(v4) or not np.isfinite(v26) or v26 <= 0:
        return None
    vol_ratio = v4 / v26
    if vol_ratio > MAX_VOL_RATIO:
        return None

    sma_200 = close.rolling(LONG_SMA_WKS).mean().iloc[-1]
    if not np.isfinite(sma_200) or sma_200 <= 0:
        return None

    # 7 · long-term trend direction. A falling 200-week average is only
    # acceptable if price is still down at the base of the recovery.
    sma_200_series = close.rolling(LONG_SMA_WKS).mean()
    dist_200w = float((px - sma_200) / sma_200 * 100.0)
    lt_prev = sma_200_series.iloc[-1 - LT_SLOPE_WINDOW_WKS] \
        if len(sma_200_series) > LT_SLOPE_WINDOW_WKS else np.nan
    lt_slope = (float((sma_200 - lt_prev) / lt_prev * 100.0)
                if np.isfinite(lt_prev) and lt_prev > 0 else 0.0)
    if lt_slope < 0 and dist_200w > MAX_DIST_IF_LT_FALLING:
        return None

    # 8 · the pullback entry must still be on the table. Price back up 25%+
    # above the 50-week line is a trend continuation, not a pullback.
    ext_50w = float((px - sma_trend.iloc[-1]) / sma_trend.iloc[-1] * 100.0)
    if ext_50w > MAX_EXT_50W:
        return None

    # 9 · exhaustion. Both are read on the same weekly bars as everything
    # else, so they answer "is the move already spent" for this timeframe.
    rsi = float(_rsi(close).iloc[-1])
    mfi = float(_mfi(high, low, close, volume).iloc[-1])
    if not np.isfinite(rsi) or rsi > MAX_RSI:
        return None
    if np.isfinite(mfi) and mfi > MAX_MFI:
        return None

    wks_since_cross = _weeks_since_cross_up(gap)
    if macd_gap < 0:
        tier = TIER_EARLY
    elif wks_since_cross is not None and wks_since_cross <= FRESH_CROSS_WKS:
        tier = TIER_FRESH
    else:
        tier = TIER_FURTHER

    prev = float(close.iloc[-4])
    row = {
        "ticker": ticker,
        "sector": sector_of(ticker),
        "tier": tier,
        "close": px,
        "slope_52w": float(slope_52),
        "slope_26w": float(slope_26),
        "slope_ratio": float(ratio),
        "touch_pct": touch["touch_pct"],
        "bounce_pct": touch["bounce_pct"],
        "wks_since_touch": touch["wks_since_touch"],
        "macd_gap": macd_gap,
        "macd_delta_3w": macd_delta_3w,
        "wks_since_cross": wks_since_cross,
        "accel_3w": float((px - prev) / prev * 100.0) if prev > 0 else 0.0,
        "dist_200w": dist_200w,
        "lt_slope_200w": lt_slope,
        "vol_ratio": float(vol_ratio),
        "ext_50w": ext_50w,
        "rsi": rsi,
        "mfi": mfi,
    }
    row["score"], row["score_parts"] = _score_row(row)
    return row


def _is_partial_week(ts) -> bool:
    """True if `ts` labels a week whose trading has not finished yet.

    The naive rule ("less than 5 days old") silently broke the Friday-evening
    email: yfinance labels a weekly bar with the Monday that starts it, so on
    Friday the bar is 4 days old and got thrown away as unsettled -- meaning
    the weekly email always reported the PREVIOUS week's data, a full week
    stale, which is the one thing that schedule exists to avoid.

    A week is finished once its Friday close has happened. 21:00 UTC covers
    16:00 ET in both EST (21:00 UTC) and EDT (20:00 UTC), so the cutoff is
    DST-safe. The bar is normalised to its own Monday first, because a
    holiday-shortened week can be labelled with a Tuesday.
    """
    try:
        bar = pd.Timestamp(ts)
        bar = (bar.tz_convert(None) if bar.tzinfo else bar).normalize()
    except Exception:
        return False
    now = pd.Timestamp.utcnow()
    now = (now.tz_convert(None) if now.tzinfo else now)

    week_monday = bar - pd.Timedelta(days=int(bar.weekday()))
    week_friday = week_monday + pd.Timedelta(days=4)
    today = now.normalize()

    if today > week_friday:
        return False                      # weekend or later: week is over
    if today < week_friday:
        return True                       # Mon-Thu: still trading
    return now.hour < 21                  # Friday: settled only after the close


def run_fast_score_scan(universe: list[str], progress_cb=None) -> pd.DataFrame:
    """Scan `universe` and return qualifying rows, ranked.

    Ranking: Fast Score descending, then tier (earlier setups first at equal
    score — more of the move is still ahead), then slope ratio.
    """
    tickers = list(dict.fromkeys(universe))
    total = len(tickers)

    for i in range(0, total, PREFETCH_CHUNK):
        chunk = tickers[i:i + PREFETCH_CHUNK]
        if progress_cb:
            progress_cb(i, total, f"Downloading weekly bars ({i + len(chunk)}/{total})…")
        try:
            prefetch_tickers(chunk, FETCH_PERIOD, FETCH_INTERVAL)
        except Exception:
            pass                     # per-ticker fallback below still works

    rows = []
    for i, t in enumerate(tickers):
        if progress_cb:
            progress_cb(i, total, f"Scanning {t} ({i + 1}/{total})…")
        try:
            weekly = get_price_history(t, FETCH_PERIOD, FETCH_INTERVAL)
            row = evaluate_ticker(t, weekly)
            if row:
                rows.append(row)
        except Exception:
            continue

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["_tier_rank"] = df["tier"].map(_TIER_RANK).fillna(9)
    df = (df.sort_values(["score", "_tier_rank", "slope_ratio"],
                         ascending=[False, True, False])
            .drop(columns="_tier_rank")
            .reset_index(drop=True))
    # Keep only the best-scoring class of each dual-class company. Sorting
    # happens first so "first" is "best", not "alphabetically luckiest".
    df["_class_group"] = df["ticker"].map(lambda t: _SHARE_CLASS_GROUPS.get(t, t))
    df = (df.drop_duplicates(subset="_class_group", keep="first")
            .drop(columns="_class_group")
            .reset_index(drop=True))
    df.insert(0, "rank", range(1, len(df) + 1))
    return df


# ══════════════════════════════════════════════════════════════════════════
# PRESENTATION
# ══════════════════════════════════════════════════════════════════════════
# Column identity colors. Each metric keeps ONE hue wherever it appears so the
# eye learns "purple == MACD" and can scan down a column without re-reading
# the header. Sign is carried by the +/- and by the desirability rules below,
# not by recoloring the whole column.
_C_ACCEL = "#7DA9FF"
_C_MACD  = "#C084FC"
_C_RATIO = "#FBBF24"
_C_DIST  = "#34D399"
_C_VOL   = "#22D3EE"
_C_NEG   = "#F87171"
_C_RANK  = "#4ADE80"

SCORE_GREEN_MIN = 9        # score at/above this gets the green badge


def _fmt_pct(v: float) -> str:
    return f"{v:+.1f}%"


def _accel_color(v: float) -> str:
    return _C_ACCEL if v >= 0 else _C_NEG


def _dist_color(v: float) -> str:
    """200W distance is colored by DESIRABILITY, not by sign.

    Below the 200-week line is where this setup has the most room, so a
    negative reading is green — the same green a near-the-line positive gets.
    Only a badly extended name (>120% above) is called out in red.
    """
    if v > 120:
        return _C_NEG
    if v > 60:
        return _C_RATIO
    return _C_DIST


def _vol_color(v: float) -> str:
    return _C_VOL if v <= 1.0 else _C_RATIO


def _score_colors(score: int) -> tuple[str, str]:
    """(background, text) for the Fast Score badge."""
    if score >= 12:
        return "#15803D", "#FFFFFF"
    if score >= SCORE_GREEN_MIN:
        return "#16A34A", "#FFFFFF"
    if score >= 6:
        return "#D97706", "#FFFFFF"
    return "#7C2D12", "#FED7AA"


def _metric_cell(label: str, value: str, color: str) -> str:
    return (
        f'<div style="min-width:78px;text-align:center">'
        f'<div style="color:{TEXT_MUTED};font-size:9px;font-weight:800;'
        f'letter-spacing:.08em;text-transform:uppercase;margin-bottom:3px">{label}</div>'
        f'<div style="color:{color};font-size:15px;font-weight:800">{value}</div>'
        f'</div>'
    )


def app_table_html(df: pd.DataFrame) -> str:
    """The single colorful ranked table shown in the Streamlit tab."""
    if df is None or df.empty:
        return ""

    header = (
        f'<div style="display:flex;align-items:center;gap:10px;padding:0 14px 8px 14px">'
        f'<div style="width:26px;color:{TEXT_MUTED};font-size:9px;font-weight:800;'
        f'letter-spacing:.08em">#</div>'
        f'<div style="flex:1;color:{TEXT_MUTED};font-size:9px;font-weight:800;'
        f'letter-spacing:.08em">TICKER / SECTOR / TIER</div>'
        + "".join(
            f'<div style="min-width:78px;text-align:center;color:{TEXT_MUTED};'
            f'font-size:9px;font-weight:800;letter-spacing:.08em">{lbl}</div>'
            for lbl in ("3W ACCEL", "MACD Δ3W", "SLOPE RATIO", "200W DIST", "VOL RATIO")
        )
        + f'<div style="min-width:74px;text-align:center;color:{TEXT_MUTED};'
          f'font-size:9px;font-weight:800;letter-spacing:.08em">FAST SCORE</div>'
        + "</div>"
    )

    rows = []
    for _, r in df.iterrows():
        tier = str(r["tier"])
        tier_color = _TIER_COLOR.get(tier, TEXT_MUTED)
        bg, fg = _score_colors(int(r["score"]))
        rows.append(
            f'<div style="display:flex;align-items:center;gap:10px;background:{BG_CARD};'
            f'border:1px solid {BORDER_COLOR};border-radius:10px;padding:10px 14px;margin-bottom:6px">'
            f'<div style="width:26px;color:{_C_RANK};font-size:15px;font-weight:800">{int(r["rank"])}</div>'
            f'<div style="flex:1;min-width:0">'
            f'<span style="color:{TEXT_PRIMARY};font-size:22px;font-weight:800;'
            f'letter-spacing:-.02em">{r["ticker"]}</span>'
            f'<span style="color:{TEXT_MUTED};font-size:12px;margin-left:8px">{r["sector"]}</span>'
            f'<span style="color:{tier_color};font-size:12px;font-weight:700;margin-left:8px">'
            f'{_TIER_LABEL.get(tier, tier)}</span>'
            f'</div>'
            + _metric_cell("3W", _fmt_pct(r["accel_3w"]), _accel_color(r["accel_3w"]))
            + _metric_cell("MACD", f'{r["macd_delta_3w"]:+.2f}', _C_MACD)
            + _metric_cell("RATIO", f'{r["slope_ratio"]:.2f}', _C_RATIO)
            + _metric_cell("200W", _fmt_pct(r["dist_200w"]), _dist_color(r["dist_200w"]))
            + _metric_cell("VOL", f'{r["vol_ratio"]:.2f}x', _vol_color(r["vol_ratio"]))
            + f'<div style="min-width:74px;text-align:center">'
              f'<div style="background:{bg};color:{fg};border-radius:8px;padding:8px 0;'
              f'font-size:19px;font-weight:800">{int(r["score"])}/15</div></div>'
            + "</div>"
        )

    return (
        f'<div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};'
        f'border-radius:12px;padding:12px 6px 6px 6px">{header}'
        f'<div style="padding:0 6px">{"".join(rows)}</div></div>'
    )


def email_table_html(df: pd.DataFrame, max_rows: int = 25) -> str:
    """Same ranked table as real <table> markup, for the weekly email.

    Built from <table>/<tr>/<td> rather than flexbox on purpose — Outlook
    desktop supports neither flex nor grid, and a flex version of this table
    collapses into one vertical stack there. Same reason the Best Scanners
    email is table-based (see scripts/headless_best_scanners_scan.py).
    """
    if df is None or df.empty:
        return ""

    head_cells = "".join(
        f'<td style="color:#6B7280;font-size:9px;font-weight:800;letter-spacing:.08em;'
        f'padding:0 6px 8px 6px;text-align:{"left" if i < 2 else "center"}">{lbl}</td>'
        for i, lbl in enumerate(
            ["#", "TICKER / SECTOR / TIER", "3W ACCEL", "MACD Δ3W",
             "SLOPE RATIO", "200W DIST", "VOL RATIO", "FAST SCORE"]
        )
    )

    body = []
    for _, r in df.head(max_rows).iterrows():
        tier = str(r["tier"])
        tier_color = _TIER_COLOR.get(tier, "#6B7280")
        bg, fg = _score_colors(int(r["score"]))
        cells = [
            f'<td style="padding:10px 6px;background:#111118;border-radius:8px 0 0 8px;'
            f'color:{_C_RANK};font-size:14px;font-weight:800">{int(r["rank"])}</td>',
            f'<td style="padding:10px 6px;background:#111118;white-space:nowrap">'
            f'<span style="color:#F1F1F1;font-size:18px;font-weight:800">{r["ticker"]}</span>'
            f'<span style="color:#6B7280;font-size:11px">&nbsp;{r["sector"]}</span><br>'
            f'<span style="color:{tier_color};font-size:11px;font-weight:700">'
            f'{_TIER_LABEL.get(tier, tier)}</span></td>',
        ]
        for value, color in (
            (_fmt_pct(r["accel_3w"]), _accel_color(r["accel_3w"])),
            (f'{r["macd_delta_3w"]:+.2f}', _C_MACD),
            (f'{r["slope_ratio"]:.2f}', _C_RATIO),
            (_fmt_pct(r["dist_200w"]), _dist_color(r["dist_200w"])),
            (f'{r["vol_ratio"]:.2f}x', _vol_color(r["vol_ratio"])),
        ):
            cells.append(
                f'<td style="padding:10px 6px;background:#111118;text-align:center;'
                f'color:{color};font-size:14px;font-weight:800;white-space:nowrap">{value}</td>'
            )
        cells.append(
            f'<td style="padding:10px 8px;background:#111118;border-radius:0 8px 8px 0;'
            f'text-align:center"><span style="background:{bg};color:{fg};border-radius:6px;'
            f'padding:6px 10px;font-size:15px;font-weight:800;display:inline-block">'
            f'{int(r["score"])}/15</span></td>'
        )
        body.append(f'<tr>{"".join(cells)}</tr>')
        body.append('<tr><td colspan="8" style="height:6px;line-height:6px">&nbsp;</td></tr>')

    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;border-collapse:separate;border-spacing:0">'
        f'<tr>{head_cells}</tr>{"".join(body)}</table>'
    )


# ══════════════════════════════════════════════════════════════════════════
# STREAMLIT TAB
# ══════════════════════════════════════════════════════════════════════════

_SS_ROWS = "fast_score_rows"
_SS_TS   = "fast_score_ts"
_SS_UNI  = "fast_score_uni_n"


def _explainer() -> str:
    return (
        f'<div style="color:{TEXT_MUTED};font-size:11.5px;line-height:1.6;margin-bottom:10px">'
        f'Finds a liquid large cap in a confirmed multi-year uptrend that is <b>still accelerating</b>, '
        f'which has pulled back to touch its <b style="color:{GOLD}">50-week moving average</b> on '
        f'<b>quiet volume</b> without breaking it, and whose <b style="color:{_C_MACD}">weekly MACD</b> '
        f'is turning back up. Everything is computed on weekly bars, and the in-progress week is dropped '
        f'— only settled bars count.<br>'
        f'The three tiers are one signal at three ages, not three quality grades: '
        f'<b style="color:{_TIER_COLOR[TIER_EARLY]}">Early</b> = MACD still below signal but closing the gap · '
        f'<b style="color:{_TIER_COLOR[TIER_FRESH]}">Fresh</b> = crossed up within {FRESH_CROSS_WKS} weeks · '
        f'<b style="color:{_TIER_COLOR[TIER_FURTHER]}">Further Along</b> = crossed earlier, bounce underway.<br>'
        f'<b style="color:{TEXT_PRIMARY}">Fast Score</b> ranks the survivors 0–15 (five components, 0–3 each: '
        f'3-week acceleration, MACD improvement, slope ratio, room above the 200-week line, and how quiet the '
        f'volume is). It does not filter — everything in the table already passed all twelve gates.</div>'
    )


def render():
    """The ⚡ Fast Score tab inside Market Overview."""
    st.markdown(_explainer(), unsafe_allow_html=True)

    c1, c2, c3 = st.columns([2.4, 1.4, 1])
    with c1:
        uni_label = st.selectbox("Universe", list(UNIVERSE_CHOICES.keys()),
                                 key="fast_score_uni")
    with c2:
        tier_sel = st.multiselect(
            "Tiers", [TIER_EARLY, TIER_FRESH, TIER_FURTHER],
            default=[TIER_EARLY, TIER_FRESH, TIER_FURTHER],
            key="fast_score_tiers",
        )
    with c3:
        min_score = st.number_input("Min score", min_value=0, max_value=15, value=0,
                                    key="fast_score_min")

    run = st.button("▶ Run Scan", type="primary", key="fast_score_run",
                    use_container_width=True)

    if run:
        universe = universe_for(UNIVERSE_CHOICES[uni_label])
        prog = st.progress(0.0, text="Starting…")

        def _cb(i, total, msg):
            prog.progress(min((i + 1) / max(total, 1), 1.0), text=msg)

        with st.spinner(f"Scanning {len(universe)} symbols on weekly bars…"):
            df = run_fast_score_scan(universe, progress_cb=_cb)
        prog.empty()

        st.session_state[_SS_ROWS] = df.to_dict("records") if not df.empty else []
        st.session_state[_SS_TS] = datetime.now().strftime("%b %d %Y · %I:%M %p")
        st.session_state[_SS_UNI] = len(universe)

    rows = st.session_state.get(_SS_ROWS)
    if rows is None:
        st.markdown(
            f'<div style="border:1px dashed {BORDER_COLOR};border-radius:10px;padding:36px;'
            f'text-align:center;color:{TEXT_MUTED}">Press <b style="color:{GOLD}">▶ Run Scan</b> '
            f'to find setups right now. A full ~500-symbol run pulls 10 years of weekly bars '
            f'and takes a couple of minutes.</div>',
            unsafe_allow_html=True,
        )
        return

    df = pd.DataFrame(rows)
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11px;margin:6px 0 8px 0">'
        f'Run: <b style="color:{TEXT_PRIMARY}">{st.session_state.get(_SS_TS, "")}</b>'
        f'&nbsp;&nbsp;|&nbsp;&nbsp;Universe: '
        f'<b style="color:{TEXT_PRIMARY}">{st.session_state.get(_SS_UNI, 0)} symbols</b>'
        f'&nbsp;&nbsp;|&nbsp;&nbsp;Qualified: '
        f'<b style="color:{GOLD}">{len(df)}</b></div>',
        unsafe_allow_html=True,
    )

    if df.empty:
        st.info("Nothing qualified on the last run — every candidate failed at least one of "
                "the twelve gates. That is a normal reading in a market with no orderly "
                "pullbacks, not an error.")
        return

    view = df[df["tier"].isin(tier_sel or [TIER_EARLY, TIER_FRESH, TIER_FURTHER])]
    view = view[view["score"] >= int(min_score)]
    if view.empty:
        st.info("No rows match the current tier / min-score filter — widen it above. "
                f"The unfiltered scan found {len(df)} setup(s).")
        return

    counts = df["tier"].value_counts()
    chips = "".join(
        f'<span style="background:{_rgba_hex(_TIER_COLOR[t], 0.14)};color:{_TIER_COLOR[t]};'
        f'border-radius:999px;padding:3px 12px;font-size:11px;font-weight:800;margin-right:6px">'
        f'{_TIER_LABEL[t]} · {int(counts.get(t, 0))}</span>'
        for t in (TIER_EARLY, TIER_FRESH, TIER_FURTHER)
    )
    st.markdown(f'<div style="margin-bottom:10px">{chips}</div>', unsafe_allow_html=True)

    st.markdown(app_table_html(view), unsafe_allow_html=True)

    # Results cached in session_state from a run made before a column existed
    # would raise KeyError here and take the whole tab down with it, which is
    # exactly what happens after a deploy adds gates. Select what is present.
    _detail_cols = [c for c in (
            "rank", "ticker", "sector", "tier", "close", "rsi", "mfi", "ext_50w",
            "lt_slope_200w", "slope_52w", "slope_26w", "slope_ratio", "touch_pct",
            "bounce_pct", "wks_since_touch", "macd_gap", "macd_delta_3w",
            "accel_3w", "dist_200w", "vol_ratio", "score",
        ) if c in view.columns]
    _missing = [c for c in ("rsi", "mfi", "ext_50w") if c not in view.columns]
    with st.expander("Full detail — the gate columns behind each row", expanded=True):
        if _missing:
            st.warning(
                f"These results predate the {', '.join(_missing)} column(s) — "
                f"press ▶ Run Scan to refresh and see every gate."
            )
        detail = view[_detail_cols].round(2).rename(columns={
            "rsi": "RSI", "mfi": "MFI", "ext_50w": "Above 50w %",
            "lt_slope_200w": "200W Trend %",
            "rank": "#", "ticker": "Sym", "sector": "Sector", "tier": "Tier",
            "close": "Close", "slope_52w": "52wk Slope %", "slope_26w": "26wk Slope %",
            "slope_ratio": "Slope Ratio", "touch_pct": "Touch %", "bounce_pct": "Bounce %",
            "wks_since_touch": "Wks Since Touch", "macd_gap": "MACD Gap",
            "macd_delta_3w": "MACD Δ3W", "accel_3w": "3W Accel %",
            "dist_200w": "200W Dist %", "vol_ratio": "Vol Ratio", "score": "Score",
        })
        st.dataframe(detail, use_container_width=True, hide_index=True)

    st.download_button(
        "⬇ Download CSV", view.to_csv(index=False).encode(),
        file_name=f"fast_score_{datetime.now().strftime('%Y-%m-%d')}.csv",
        mime="text/csv", key="fast_score_dl",
    )


def _rgba_hex(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{alpha})"
