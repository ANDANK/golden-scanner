# scanners/combo_lab.py — which indicator, or which combination of them,
# actually works?
#
# THE QUESTION
#   Take MACD, RSI, EMA structure, ADX and volume. Split each into the states
#   a trader would actually distinguish. Test every cross-combination of those
#   states — and each state alone as a baseline — across ~500 names, on daily
#   and weekly bars, over two NON-OVERLAPPING periods. Then ask which ones
#   survive all four.
#
# FOUR DESIGN DECISIONS, AND WHY
#
# 1. EXIT IS A FIXED HOLDING PERIOD (10 and 20 bars, both reported).
#    Every combination exits identically, so a difference in the results is
#    attributable to the ENTRY signal and nothing else. An ATR stop or an
#    indicator-based exit would let a weak entry rank well because its exit
#    happened to manage the trade, which is not the question being asked.
#
# 2. CROSSOVERS USE A RECENCY WINDOW, NOT THE SAME BAR.
#    A (MACD cross) and C (EMA20/50 cross) are both EVENTS. Demanding both on
#    the same bar is close to impossible — on weekly bars over one year most
#    A+C cells would report N=0 and the whole table would be unrankable. So a
#    crossover condition reads "crossed within the last CROSS_WINDOW bars",
#    with the classification (above/below zero, price position) evaluated
#    where the spec implies: the zero-line test at the CROSS bar, because it
#    describes the cross; the price-position test at the SIGNAL bar, because
#    it describes where price is when you would act.
#
# 3. INDICATORS ARE THIS REPO'S OWN, NOT A LIBRARY.
#    The MACD, RSI and ADX here are lifted from fast_score.py and
#    first_things_first.py. That means the backtest measures exactly what the
#    live scanners measure — a library's ADX differs enough in its smoothing
#    that "validated in the backtest" would not describe the tab. It also
#    avoids adding a dependency to a repo where every push deploys.
#
# 4. THE TWO LOOKBACKS ARE DISJOINT.
#    A one-year window sitting inside a three-year window shares its trades
#    with it, so "confirmed in both" is partly just the same trades counted
#    twice. Here the windows are the RECENT 1 YEAR and the 2 YEARS BEFORE IT,
#    which share nothing. Agreement across them is then evidence.
#
# WHAT THIS CANNOT TELL YOU
#   The universe is today's list, so names that were delisted or acquired are
#   absent — the survivors are over-represented, which flatters every result
#   equally. Entries fill at the next bar's open with no slippage or
#   commission. And 191 combinations tested at once is 191 chances for one to
#   look good by luck: at a 5% threshold roughly 10 should print "significant"
#   with no edge at all. That is why the headline table ranks by CONSISTENCY
#   across four independent windows rather than by any single number.

from __future__ import annotations

import itertools
import os
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BENCHMARK = "SPY"

# How recently a crossover must have happened for the condition to hold.
# Daily gets a full trading week, weekly gets three bars — roughly the same
# span of market time, and enough that a signal is not lost to a one-bar
# timing difference between two indicators that turn at slightly different
# speeds.
CROSS_WINDOW = {"daily": 5, "weekly": 3}

# Holding periods, in bars of whichever timeframe is being tested.
HOLDS = {"daily": (10, 20), "weekly": (4, 8)}

# Below this a combination is reported but never ranked. 30 trades is not a
# lot; it is the point below which a win rate is essentially unreadable.
MIN_TRADES = 30

VOL_MULT = 1.2          # V1: volume >= 1.2x its 20-bar average
VOL_LOOKBACK = 20

ADX_MIN, ADX_MAX = 20.0, 50.0


# ══════════════════════════════════════════════════════════════════════════
# INDICATORS — the repo's own, so the backtest measures what the tabs show
# ══════════════════════════════════════════════════════════════════════════

def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """(line, signal, histogram) — identical to fast_score._macd."""
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig, line - sig


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI — identical to fast_score._rsi.

    Wilder smoothing (alpha = 1/period), not a simple mean: a simple mean
    reads several points hot near turns, which would shift every band
    boundary in section B.
    """
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return (100.0 - 100.0 / (1.0 + rs)).fillna(100.0)


def adx(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = 14) -> pd.Series:
    """Wilder's ADX — identical to first_things_first._adx_series."""
    prev_cl = close.shift(1)
    tr = pd.concat([high - low, (high - prev_cl).abs(),
                    (low - prev_cl).abs()], axis=1).max(axis=1)
    atr = tr.ewm(com=period - 1, adjust=False).mean()
    up, down = high.diff(), -low.diff()
    pdm = up.where((up > down) & (up > 0), 0.0)
    ndm = down.where((down > up) & (down > 0), 0.0)
    safe = atr.replace(0, np.nan)
    pdi = 100 * pdm.ewm(com=period - 1, adjust=False).mean() / safe
    ndi = 100 * ndm.ewm(com=period - 1, adjust=False).mean() / safe
    denom = (pdi + ndi).replace(0, np.nan)
    dx = (100 * (pdi - ndi).abs() / denom).fillna(0)
    return dx.ewm(com=period - 1, adjust=False).mean()


def _crossed_up_within(fast_s: pd.Series, slow_s: pd.Series,
                       window: int) -> tuple[pd.Series, pd.Series]:
    """(happened, value_at_cross) for a fast-over-slow cross in `window` bars.

    Returns the crossing bar's own index position too, so a condition that
    describes the CROSS (like "MACD was above zero when it crossed") can be
    evaluated where it belongs rather than at the signal bar, where the line
    may since have moved to the other side of zero.
    """
    above = fast_s > slow_s
    cross = above & ~above.shift(1, fill_value=False)
    # Position of the most recent cross at or before each bar.
    idx = pd.Series(np.arange(len(fast_s)), index=fast_s.index)
    last_cross = idx.where(cross).ffill()
    recent = (idx - last_cross) < window
    return recent.fillna(False), last_cross


def indicator_frame(df: pd.DataFrame, timeframe: str) -> pd.DataFrame | None:
    """OHLCV in, one row per bar with every condition as a boolean column.

    Every column is computed from data at or before its own bar. Nothing here
    peeks forward; the only forward-looking values in this module are the
    trade returns, which are built separately in forward_returns().
    """
    need = {"Open", "High", "Low", "Close", "Volume"}
    if df is None or df.empty or not need.issubset(df.columns):
        return None
    df = df.dropna(subset=["Open", "High", "Low", "Close"]).copy()
    if len(df) < 120:
        return None

    close, high, low = df["Close"], df["High"], df["Low"]
    vol = df["Volume"].fillna(0.0)
    win = CROSS_WINDOW[timeframe]

    m_line, m_sig, _ = macd(close)
    m_recent, m_at = _crossed_up_within(m_line, m_sig, win)
    # The zero-line test belongs to the CROSS, not to today: a line that
    # crossed below zero and has since climbed through it is still an A2
    # signal, because A2 describes the crossover that occurred.
    pos = np.arange(len(df))
    at = m_at.to_numpy()
    safe_at = np.where(np.isnan(at), 0, at).astype(int)
    macd_at_cross = m_line.to_numpy()[safe_at]
    macd_at_cross = np.where(np.isnan(at), np.nan, macd_at_cross)

    e20, e50 = ema(close, 20), ema(close, 50)
    e_recent, _ = _crossed_up_within(e20, e50, win)

    r = rsi(close)
    a = adx(high, low, close)
    vol_avg = vol.rolling(VOL_LOOKBACK, min_periods=VOL_LOOKBACK).mean()

    out = pd.DataFrame(index=df.index)
    out["open"] = df["Open"].to_numpy()
    out["close"] = close.to_numpy()

    # A — MACD crossover, split by where the line sat when it crossed.
    out["A1"] = m_recent.to_numpy() & (macd_at_cross > 0)
    out["A2"] = m_recent.to_numpy() & (macd_at_cross <= 0)

    # B — RSI band at the signal bar. Note that RSI < 30 falls in NO band:
    # the spec names three bands starting at 30, so a washed-out reading is
    # deliberately not a B signal rather than being folded into B1.
    out["B1"] = (r >= 30) & (r < 45)
    out["B2"] = (r >= 45) & (r < 60)
    out["B3"] = r >= 60

    # C — EMA20/50 golden cross, split by where price sits when you act.
    #
    # Expect C2 to be RARE and to sit under the low-N flag on most runs. At a
    # crossover EMA20 and EMA50 are by definition equal, so within a few bars
    # of it the "pullback zone" between them is a sliver price is seldom
    # inside. That is a property of combining "recently crossed" with "between
    # the two lines", not a data problem — and it is reported rather than
    # patched, because widening the band to manufacture signals would be
    # inventing a condition nobody asked to test.
    c_close, c20, c50 = close.to_numpy(), e20.to_numpy(), e50.to_numpy()
    out["C1"] = e_recent.to_numpy() & (c_close > c20)
    out["C3"] = e_recent.to_numpy() & (c_close < c50)
    out["C2"] = e_recent.to_numpy() & ~out["C1"].to_numpy() & ~out["C3"].to_numpy()

    # D — trending but not exhausted.
    out["D1"] = (a >= ADX_MIN) & (a <= ADX_MAX)

    # V — volume confirmation, kept as its own testable factor rather than
    # switched on everywhere, so the results say whether it actually helps.
    #
    # Expect weekly V1 to fire far less often than daily. A weekly bar's
    # volume is a five-day SUM, which is much smoother than a single day's,
    # so clearing 1.2x its own average is a higher bar. The multiplier is
    # deliberately the same on both timeframes anyway: tuning it per
    # timeframe to equalise the counts would be fitting the threshold to the
    # sample size rather than measuring anything.
    out["V1"] = (vol >= VOL_MULT * vol_avg) & vol_avg.notna() & (vol_avg > 0)

    for c in FACTOR_STATES:
        out[c] = out[c].fillna(False).astype(bool)
    return out


# ══════════════════════════════════════════════════════════════════════════
# COMBINATION ENGINE
# ══════════════════════════════════════════════════════════════════════════

# None means "this factor is not constrained", which is what makes singles
# and full combinations fall out of the same product rather than needing a
# separate code path.
FACTORS = {
    "A": (None, "A1", "A2"),
    "B": (None, "B1", "B2", "B3"),
    "C": (None, "C1", "C2", "C3"),
    "D": (None, "D1"),
    "V": (None, "V1"),
}
FACTOR_STATES = [s for states in FACTORS.values() for s in states if s]


def all_combinations() -> list[tuple[str, ...]]:
    """Every cross-combination, singles included, unconstrained excluded.

    3 x 4 x 4 x 2 x 2 = 192 products; dropping the all-unconstrained one
    leaves 191. "A1" alone is simply the product where B, C, D and V are
    unconstrained, so single-factor baselines are generated by the same
    itertools.product as the five-factor combinations and cannot drift from
    them.
    """
    combos = []
    for picks in itertools.product(*FACTORS.values()):
        chosen = tuple(p for p in picks if p)
        if chosen:
            combos.append(chosen)
    return combos


def label(combo: tuple[str, ...]) -> str:
    return "+".join(combo)


# ══════════════════════════════════════════════════════════════════════════
# BACKTEST
# ══════════════════════════════════════════════════════════════════════════

def forward_returns(frame: pd.DataFrame, hold: int) -> np.ndarray:
    """Return from the NEXT bar's open to the open `hold` bars later.

    Entry on the next open, not this bar's close, is what makes the signal
    tradeable: the condition is only known once the bar has closed. NaN where
    the trade would run past the end of the data, so an unfinished trade is
    dropped rather than silently truncated at the last price.
    """
    o = frame["open"].to_numpy(dtype=float)
    n = len(o)
    entry = np.full(n, np.nan)
    exit_ = np.full(n, np.nan)
    entry[: n - 1] = o[1:]
    if n > hold + 1:
        exit_[: n - hold - 1] = o[hold + 1:]
    with np.errstate(invalid="ignore", divide="ignore"):
        return (exit_ - entry) / entry


def _mask_for(frame: pd.DataFrame, combo: tuple[str, ...]) -> np.ndarray:
    m = np.ones(len(frame), dtype=bool)
    for state in combo:
        m &= frame[state].to_numpy()
    return m


def run_window(frames: dict[str, pd.DataFrame], bench: pd.DataFrame | None,
               start, end, hold: int,
               combos: list[tuple[str, ...]] | None = None,
               progress_cb=None) -> pd.DataFrame:
    """Every combination over one (timeframe, period, hold) cell.

    Indicators are computed over the FULL history and only the signal bars
    are restricted to [start, end] — an indicator needs its warmup, and
    warmup drawn from before the window is not look-ahead, it is the past.
    """
    combos = combos or all_combinations()

    # Benchmark return over the same span, so a combo is measured against
    # "did the market just go up" rather than against zero.
    bench_fwd = None
    if bench is not None and not bench.empty:
        bf = forward_returns(bench, hold)
        bench_fwd = pd.Series(bf, index=bench.index)

    per_combo: dict[str, list] = {label(c): [] for c in combos}
    n_tickers = 0

    for i, (ticker, frame) in enumerate(frames.items()):
        if frame is None or frame.empty:
            continue
        in_window = (frame.index >= start) & (frame.index <= end)
        if not in_window.any():
            continue
        n_tickers += 1
        fwd = forward_returns(frame, hold)
        usable = in_window & np.isfinite(fwd)
        if not usable.any():
            continue

        if bench_fwd is not None:
            bm = bench_fwd.reindex(frame.index).to_numpy()
        else:
            bm = np.zeros(len(frame))
        dates = frame.index.values.astype("datetime64[ns]").astype(np.int64).astype(float)

        for combo in combos:
            sel = _mask_for(frame, combo) & usable
            if not sel.any():
                continue
            # Third column is the entry DATE as an ordinal, not the bar's
            # position within this ticker: the drawdown curve is built across
            # every ticker at once, and positions would interleave unrelated
            # calendars into a meaningless sequence.
            per_combo[label(combo)].append(
                np.column_stack([fwd[sel], bm[sel], dates[sel]]))
        if progress_cb and i % 25 == 0:
            progress_cb(i, len(frames))

    rows = []
    for combo in combos:
        lab = label(combo)
        chunks = per_combo[lab]
        rows.append(_summarise(lab, combo, chunks, hold, n_tickers))
    return pd.DataFrame(rows)


def _summarise(lab: str, combo: tuple[str, ...], chunks: list,
               hold: int, n_tickers: int) -> dict:
    base = {
        "combo": lab,
        "n_factors": len(combo),
        "hold": hold,
        "tickers": n_tickers,
        "trades": 0,
        "win_rate": np.nan,
        "avg_return": np.nan,
        "median_return": np.nan,
        "avg_excess": np.nan,
        "total_return": np.nan,
        "max_drawdown": np.nan,
        "sharpe": np.nan,
        "sortino": np.nan,
        "avg_hold": float(hold),
        "t_stat": np.nan,
        "low_n": True,
    }
    if not chunks:
        return base

    data = np.vstack(chunks)
    ret, bmk = data[:, 0], data[:, 1]
    excess = ret - np.nan_to_num(bmk)
    n = len(ret)

    # Sharpe and Sortino are computed on the TRADE distribution and then
    # annualised by how often the signal actually fires, rather than on a
    # daily equity curve. With overlapping equal-weight signals there is no
    # single well-defined equity curve, and inventing one would make the
    # ratio depend on a position-sizing choice this study never makes.
    sd = float(np.std(ret, ddof=1)) if n > 1 else np.nan
    downside = ret[ret < 0]
    dsd = float(np.std(downside, ddof=1)) if len(downside) > 1 else np.nan
    per_year = 252.0 / hold          # daily-bar convention; weekly rescaled
    scale = np.sqrt(per_year)

    # Equity curve of the trades in DATE order, equal weight, no compounding
    # across overlaps — enough to read a drawdown from, and honest about
    # being a trade-sequence curve rather than a portfolio.
    #
    # The running peak must INCLUDE the current point. Excluding it lets the
    # first trade's own gain come back as a positive "drawdown", which is not
    # a thing; a drawdown is bounded above by zero by definition.
    order = np.argsort(data[:, 2], kind="stable")
    curve = np.cumsum(ret[order])
    peak = np.maximum.accumulate(np.concatenate([[0.0], curve]))[1:]
    dd = float(np.min(curve - peak)) if n else np.nan

    base.update({
        "trades": int(n),
        "win_rate": float((ret > 0).mean() * 100),
        "avg_return": float(ret.mean() * 100),
        "median_return": float(np.median(ret) * 100),
        "avg_excess": float(excess.mean() * 100),
        "total_return": float(ret.sum() * 100),
        "max_drawdown": float(dd * 100),
        "sharpe": float(ret.mean() / sd * scale) if sd and sd > 0 else np.nan,
        "sortino": float(ret.mean() / dsd * scale) if dsd and dsd > 0 else np.nan,
        "t_stat": float(excess.mean() / (np.std(excess, ddof=1) / np.sqrt(n)))
        if n > 1 and np.std(excess, ddof=1) > 0 else np.nan,
        "low_n": bool(n < MIN_TRADES),
    })
    return base


# ══════════════════════════════════════════════════════════════════════════
# THE HEADLINE: what survives every window
# ══════════════════════════════════════════════════════════════════════════

def consensus(tables: dict[str, pd.DataFrame],
              metric: str = "avg_excess") -> pd.DataFrame:
    """One row per combination, one column per (timeframe x period) cell.

    This is the table that answers the actual question. Four separate ranked
    tables invite reading the top of one of them, which is exactly how a
    combination that worked in a single window gets mistaken for one that
    works. Ranking by how many INDEPENDENT windows a combination held up in —
    and only then by size of edge — makes the fragile ones sort themselves to
    the bottom without anyone having to cross-reference four pages.
    """
    if not tables:
        return pd.DataFrame()
    keys = list(tables)
    merged = None
    for key, tbl in tables.items():
        cols = tbl[["combo", "n_factors", metric, "trades", "win_rate"]].copy()
        cols.columns = ["combo", "n_factors", f"{key}_edge",
                        f"{key}_n", f"{key}_win"]
        merged = cols if merged is None else merged.merge(
            cols.drop(columns=["n_factors"]), on="combo", how="outer")

    edge_cols = [f"{k}_edge" for k in keys]
    n_cols = [f"{k}_n" for k in keys]

    edges = merged[edge_cols].to_numpy(dtype=float)
    ns = merged[n_cols].to_numpy(dtype=float)
    enough = ns >= MIN_TRADES
    positive = (edges > 0) & enough

    merged["windows_tested"] = enough.sum(axis=1)
    merged["windows_positive"] = positive.sum(axis=1)
    # Mean edge over the windows that actually had a sample. A window with
    # nine trades contributes nothing rather than dragging the average
    # around with noise.
    # An all-NaN row is the CORRECT answer for a combination that never
    # reached an adequate sample in any window, so numpy's warning about it
    # is noise that would bury real warnings in the job log.
    masked = np.where(enough, edges, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        merged["mean_edge"] = np.nanmean(masked, axis=1)
        merged["worst_edge"] = np.nanmin(masked, axis=1)
        merged["min_n"] = np.where(
            enough.any(axis=1),
            np.nanmin(np.where(enough, ns, np.nan), axis=1), 0)

    # A combination only counts as consistent if it was measurable in EVERY
    # window. Two-out-of-two is not the same evidence as four-out-of-four and
    # must not sort as though it were.
    merged["verdict"] = np.select(
        [
            (merged["windows_tested"] == len(keys)) & (merged["windows_positive"] == len(keys)),
            (merged["windows_tested"] == len(keys)) & (merged["windows_positive"] >= len(keys) - 1),
            merged["windows_tested"] < len(keys),
        ],
        ["Holds everywhere", "Mostly holds", "Not enough data"],
        default="Inconsistent",
    )
    order = {"Holds everywhere": 0, "Mostly holds": 1,
             "Inconsistent": 2, "Not enough data": 3}
    merged["_rank"] = merged["verdict"].map(order)
    return merged.sort_values(
        ["_rank", "mean_edge"], ascending=[True, False]).drop(columns=["_rank"])


def rank_table(tbl: pd.DataFrame, by: str = "avg_excess") -> pd.DataFrame:
    """One window's table, adequately-sampled combinations first.

    Low-N rows are kept — a combination that fired eight times is a finding
    about the combination — but they sort below everything rankable so a
    100% win rate on three trades cannot head the page.
    """
    if tbl is None or tbl.empty:
        return pd.DataFrame()
    out = tbl.copy()
    out["_lowN"] = out["low_n"].astype(int)
    return out.sort_values(["_lowN", by], ascending=[True, False]).drop(
        columns=["_lowN"])
