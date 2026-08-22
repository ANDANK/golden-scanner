# scanners/sector_validate.py — cross-check the Sector Rotation table against
# an INDEPENDENT price source, and point at the standard published references.
#
# The rotation table is only as trustworthy as the Yahoo Finance bars behind
# it, and Yahoo's free endpoint is the single point of failure for every
# number on the page: one bad bar in SPY (the RS denominator) skews all 15
# rows at once, and a stale bar skews them silently. So the check that
# matters is not "does this number look plausible" but "does a second,
# unrelated data source agree".
#
# Stooq is used as that second source: free daily OHLC over plain CSV, no
# API key, no account, and it is not derived from Yahoo. Two caveats shape
# how the comparison is done:
#
#   * Stooq's US close is split-adjusted but NOT dividend-adjusted, while
#     data_loader fetches with auto_adjust=True (dividend-adjusted). Over 63
#     sessions that is worth roughly a quarter's yield -- ~0.2% on XLK, but
#     ~0.9% on XLU/XLP/XLRE. So OUR returns should read slightly HIGHER than
#     Stooq's, by about the sector's yield, and a difference in that
#     direction is agreement, not a discrepancy.
#   * The two feeds can be a session apart near the close. Everything below
#     is therefore compared on the LAST DATE BOTH SOURCES SHARE, never on
#     "the last row of each".
#
# What is actually checked, weakest assumption first:
#   1. Price level      — same close on the same date, to the cent.
#   2. Return windows   — 21 / 63-session % change over the same dates.
#   3. RS ranking       — Spearman correlation of the whole leaderboard
#                         recomputed from Stooq. This is the one that
#                         matters: the page is a ranking, so agreement on
#                         ORDER is the real test, and it is robust to the
#                         dividend-adjustment gap above.

from __future__ import annotations

import io
import time

import pandas as pd

# Stooq mirrors. The .com host blocks or rate-limits datacenter IPs (which is
# what a Streamlit Cloud dyno is), and answers with a 403 or a plain-text
# notice rather than an HTTP error, so both are tried before giving up.
STOOQ_HOSTS = ("https://stooq.com", "https://stooq.pl")
STOOQ_PATH = "/q/d/l/?s={sym}.us&i=d"

# Tolerances. Deliberately loose enough to absorb the dividend-adjustment
# gap and a one-session lag, tight enough that a genuinely stale or wrong
# bar cannot slip through.
PRICE_TOL_PCT  = 0.35   # same-date close: should be near-exact
RETURN_TOL_PCT = 1.25   # 21/63-session return, absorbing ~a quarter's yield
RANK_CORR_MIN  = 0.90   # Spearman floor for the leaderboard to count as confirmed

# The 11 GICS sector ETFs, i.e. the ones that actually partition the S&P 500.
# QQQ/IWM/GLD/TLT ride along in the rotation table for context but are not
# S&P components, so they are excluded from any check that treats the set as
# a decomposition of the index.
GICS_SECTORS = ("XLK", "XLF", "XLV", "XLI", "XLE", "XLY",
                "XLP", "XLC", "XLB", "XLRE", "XLU")


# ── Published references for eyeballing ────────────────────────────────────────
# Ordered by how directly each one answers "is this table right?". The first
# is authoritative for these specific funds; the rest are cross-checks and
# context.
SOURCES = [
    {
        "name":  "SPDR Sector Tracker (State Street)",
        "url":   "https://www.sectorspdrs.com/sectortracker",
        "check": "1M / 3M / YTD return for all 11 XL* funds",
        "note":  "The fund issuer's own numbers for the exact tickers this page "
                 "ranks — the authoritative source for the return columns. Total "
                 "return, so it should match our dividend-adjusted figures closely.",
    },
    {
        "name":  "StockCharts PerfChart / RRG",
        "url":   "https://stockcharts.com/freecharts/perf.php?XLK,XLF,XLV,XLI,XLE,XLY,XLP,XLC,XLB,XLRE,XLU&id=p&r=SPY",
        "check": "Relative strength vs SPY, and the rotation quadrants",
        "note":  "The direct analogue of our RS column: set the benchmark to SPY "
                 "and the ordering should match ours. Their Relative Rotation "
                 "Graph is the industry-standard version of this whole page.",
    },
    {
        "name":  "S&P Dow Jones Indices — S&P 500 GICS sectors",
        "url":   "https://www.spglobal.com/spdji/en/index-family/equity/us-equity/sp-sectors/",
        "check": "The underlying sector indices the XL* ETFs track",
        "note":  "Index-level truth. Small tracking difference vs the ETFs is "
                 "expected and normal — the ETF is the tradeable proxy.",
    },
    {
        "name":  "Finviz sector performance",
        "url":   "https://finviz.com/groups.ashx?g=sector&v=210&o=name",
        "check": "Sector ordering over 1W / 1M / 3M / YTD",
        "note":  "Cap-weighted from constituents rather than from the ETF, so "
                 "treat it as a sanity check on the ORDER, not the decimals.",
    },
    {
        "name":  "Fidelity business-cycle sector framework",
        "url":   "https://institutional.fidelity.com/advisors/insights/spotlights/business-cycle-update",
        "check": "Is the rotation we see consistent with the macro regime?",
        "note":  "Qualitative. Defensives (XLU/XLP/XLV) leading late-cycle and "
                 "cyclicals (XLI/XLF/XLY) leading early-cycle is the textbook "
                 "pattern our table should be reproducing.",
    },
    {
        "name":  "FRED — yield curve & real rates",
        "url":   "https://fred.stlouisfed.org/series/T10Y2Y",
        "check": "Context for the XLU / TLT / XLRE rows",
        "note":  "Rate-sensitive sectors move with the curve. If TLT and XLU "
                 "diverge sharply here while rates are flat, suspect the data "
                 "before the signal.",
    },
]


# ── Independent fetch ──────────────────────────────────────────────────────────

def fetch_stooq_daily(ticker: str, timeout: int = 15) -> pd.Series:
    """Daily closes from Stooq as a date-indexed Series (oldest first).

    Thin wrapper kept for callers that only want the data; use
    fetch_reference_daily() when the reason for a failure matters.
    """
    return fetch_reference_daily(ticker, timeout)[0]


def fetch_reference_daily(ticker: str, timeout: int = 15) -> tuple[pd.Series, str]:
    """(closes, reason) from the reference feed, trying each mirror in turn.

    The reason string exists because the previous version collapsed every
    failure mode into an empty Series, which left the panel guessing at the
    cause -- and guessing wrong: it blamed the host's outbound network on a
    box where yfinance works fine. HTTP 403, a rate-limit notice, an unknown
    symbol and a timeout are four different problems with four different
    fixes, so they are reported as four different strings.
    """
    import requests

    sym = ticker.lower().replace("-", ".")   # BRK-B → brk.b
    reasons = []
    for host in STOOQ_HOSTS:
        url = host + STOOQ_PATH.format(sym=sym)
        try:
            resp = requests.get(
                url,
                timeout=timeout,
                headers={
                    # Stooq serves datacenter IPs differently from browsers;
                    # a real UA and an explicit Accept get through more often.
                    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                                   "Chrome/124.0.0.0 Safari/537.36"),
                    "Accept": "text/csv,text/plain,*/*",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
        except Exception as e:
            reasons.append(f"{host}: {type(e).__name__}")
            continue

        if resp.status_code != 200:
            reasons.append(f"{host}: HTTP {resp.status_code}")
            continue

        text = resp.text or ""
        head = text.lstrip()
        if not head.lower().startswith("date,"):
            # Stooq answers a blocked or throttled request with a plain-text
            # notice and a 200, so the body is the only signal there is.
            snippet = " ".join(head.split())[:80] or "empty body"
            reasons.append(f"{host}: {snippet}")
            continue

        try:
            df = pd.read_csv(io.StringIO(text))
            if df.empty or "Close" not in df.columns:
                reasons.append(f"{host}: CSV had no Close column")
                continue
            out = pd.Series(df["Close"].values,
                            index=pd.to_datetime(df["Date"]).values,
                            dtype=float).dropna()
            if out.empty:
                reasons.append(f"{host}: CSV had no usable rows")
                continue
            return out.sort_index(), "ok"
        except Exception as e:
            reasons.append(f"{host}: parse {type(e).__name__}")

    return pd.Series(dtype=float), "; ".join(reasons) or "no response"


# ── Self-consistency checks (no external source needed) ────────────────────────

def _pct_over(s: pd.Series, bars: int):
    try:
        if s is None or len(s) <= bars:
            return None
        base = float(s.iloc[-(bars + 1)])
        return None if base == 0 else (float(s.iloc[-1]) / base - 1) * 100
    except Exception:
        return None


def self_checks(ours: dict, sectors: list[tuple[str, str]], bench: str = "SPY") -> list[dict]:
    """Checks that need no second provider, so they run even when the
    reference feed is unreachable.

    These catch the failure mode that actually bit this app before (see the
    note in data_loader.py about a NaN SPY bar poisoning every RS figure):
    a single bad or stale bar in one ticker. Each returns
    {name, status, detail} with status in {"pass", "warn", "fail"}.
    """
    out = []
    series = {t: _norm_index(s) for t, s in ours.items() if s is not None}
    series = {t: s for t, s in series.items() if not s.empty}

    if not series:
        return [{"name": "Price data present", "status": "fail",
                 "detail": "No price series were loaded at all."}]

    # 1. Every ticker in the table has data.
    expected = [t for t, _ in sectors] + [bench]
    missing = [t for t in expected if t not in series]
    out.append({
        "name": "All tickers loaded",
        "status": "pass" if not missing else "fail",
        "detail": (f"{len(expected)} of {len(expected)} present"
                   if not missing else f"missing: {', '.join(missing)}"),
    })

    # 2. Everything is on the same last bar. A ticker lagging the rest is
    #    stale data, and stale data in a RANKING silently mis-sorts the page.
    last_dates = {t: s.index.max() for t, s in series.items()}
    newest = max(last_dates.values())
    lagging = {t: d for t, d in last_dates.items() if (newest - d).days > 4}
    out.append({
        "name": "Bars are in step",
        "status": "pass" if not lagging else "warn",
        "detail": (f"all {len(series)} tickers end {pd.Timestamp(newest):%Y-%m-%d}"
                   if not lagging else
                   "behind: " + ", ".join(f"{t} ({pd.Timestamp(d):%Y-%m-%d})"
                                          for t, d in lagging.items())),
    })

    # 3. The benchmark's return must sit INSIDE the range of the 11 GICS
    #    sectors. SPY is a weighted average of them, and a weighted average
    #    cannot fall outside the range of its inputs -- so if it does, either
    #    SPY's bar or a sector's bar is wrong. No external data required;
    #    it is an arithmetic identity of the index construction.
    sec_rets = {t: _pct_over(series[t], 63) for t in GICS_SECTORS if t in series}
    sec_rets = {t: v for t, v in sec_rets.items() if v is not None}
    bench_ret = _pct_over(series.get(bench), 63)
    if len(sec_rets) >= 8 and bench_ret is not None:
        lo, hi = min(sec_rets.values()), max(sec_rets.values())
        inside = lo <= bench_ret <= hi
        out.append({
            "name": f"{bench} sits inside the sector range",
            "status": "pass" if inside else "fail",
            "detail": (f"{bench} {bench_ret:+.1f}% over 3M, sectors span "
                       f"{lo:+.1f}% to {hi:+.1f}%"
                       + ("" if inside else
                          " — impossible for an index against its own components, "
                          "so one of these bars is wrong")),
        })

    # 4. No single-session move big enough to mean an unadjusted split.
    wild = []
    for t, sr in series.items():
        try:
            mx = sr.iloc[-63:].pct_change().abs().max() * 100
            if mx > 25:
                wild.append(f"{t} ({mx:.0f}%)")
        except Exception:
            continue
    out.append({
        "name": "No split-sized jumps",
        "status": "pass" if not wild else "warn",
        "detail": ("no single-day move over 25% in the last 63 sessions"
                   if not wild else
                   "unusually large jumps: " + ", ".join(wild)
                   + " — check for an unadjusted split"),
    })

    # 5. No non-positive or missing closes feeding the maths.
    bad = [t for t, sr in series.items()
           if sr.iloc[-63:].isna().any() or (sr.iloc[-63:] <= 0).any()]
    out.append({
        "name": "Closes are clean",
        "status": "pass" if not bad else "fail",
        "detail": ("no NaN or non-positive closes in the last 63 sessions"
                   if not bad else "bad closes in: " + ", ".join(bad)),
    })

    return out


def _norm_index(s: pd.Series) -> pd.Series:
    """Normalise to naive midnight dates so two feeds can be joined."""
    if s is None or s.empty:
        return pd.Series(dtype=float)
    idx = pd.DatetimeIndex(pd.to_datetime(s.index))
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    out = pd.Series(s.values, index=idx.normalize(), dtype=float)
    return out[~out.index.duplicated(keep="last")].sort_index()


def _return_over(s: pd.Series, end_date, bars: int):
    """% change over `bars` sessions ending at end_date, or None."""
    try:
        s = s.loc[:end_date]
        if len(s) <= bars:
            return None
        base = float(s.iloc[-(bars + 1)])
        if base == 0:
            return None
        return (float(s.iloc[-1]) / base - 1) * 100
    except Exception:
        return None


def cross_check(ours: dict, sectors: list[tuple[str, str]],
                bench: str = "SPY", pause: float = 0.15,
                progress_fn=None) -> tuple[pd.DataFrame, dict]:
    """Compare our series against Stooq's for every sector ETF.

    ours      {ticker: our close Series} — SPY included, keyed by ticker.
    sectors   [(ticker, name), ...]
    Returns (per-ticker DataFrame, summary dict).
    """
    tickers = [t for t, _ in sectors if t in ours]
    names = dict(sectors)

    ref: dict[str, pd.Series] = {}
    reasons: dict[str, str] = {}
    to_fetch = tickers + ([bench] if bench in ours else [])
    for i, t in enumerate(to_fetch):
        if progress_fn:
            progress_fn(i, len(to_fetch), t)
        series, why = fetch_reference_daily(t)
        ref[t] = _norm_index(series)
        reasons[t] = why
        if pause:
            time.sleep(pause)

    reachable = sum(1 for v in ref.values() if not v.empty)
    if reachable == 0:
        # Report what the server actually said. The distinct reasons are
        # usually one or two strings repeated across every ticker, so
        # deduplicating them gives a short, actionable message instead of
        # sixteen copies of the same line.
        distinct = sorted({r for r in reasons.values() if r and r != "ok"})
        return pd.DataFrame(), {
            "status": "unreachable",
            "attempted": len(to_fetch),
            "reasons": distinct,
            "message": ("Reference feed (Stooq) returned no usable data for any of "
                        f"{len(to_fetch)} tickers."),
        }

    ours_n = {t: _norm_index(s) for t, s in ours.items()}

    # Benchmark leg for the independently recomputed RS.
    b_ours = ours_n.get(bench, pd.Series(dtype=float))
    b_ref = ref.get(bench, pd.Series(dtype=float))

    rows = []
    for t in tickers:
        o, r = ours_n.get(t, pd.Series(dtype=float)), ref.get(t, pd.Series(dtype=float))
        if o.empty or r.empty:
            rows.append({
                "Ticker": t, "Sector": names.get(t, ""), "Status": "No reference data",
                "Ours": None, "Reference": None, "Δ Price %": None,
                "Ours 3M %": None, "Ref 3M %": None, "Δ 3M pts": None,
                "Ours RS": None, "Ref RS": None, "As Of": "",
            })
            continue

        common = o.index.intersection(r.index)
        if len(common) < 70:
            rows.append({
                "Ticker": t, "Sector": names.get(t, ""), "Status": "Too little overlap",
                "Ours": None, "Reference": None, "Δ Price %": None,
                "Ours 3M %": None, "Ref 3M %": None, "Δ 3M pts": None,
                "Ours RS": None, "Ref RS": None, "As Of": "",
            })
            continue

        d = common.max()
        po, pr = float(o.loc[d]), float(r.loc[d])
        dprice = (po - pr) / pr * 100 if pr else None

        o3, r3 = _return_over(o, d, 63), _return_over(r, d, 63)
        d3 = (o3 - r3) if (o3 is not None and r3 is not None) else None

        # RS recomputed end-to-end from the reference feed, on the same dates.
        rs_ours = rs_ref = None
        if not b_ours.empty and not b_ref.empty:
            bo, br = _return_over(b_ours, d, 63), _return_over(b_ref, d, 63)
            if o3 is not None and bo is not None:
                rs_ours = round((1 + o3 / 100) / (1 + bo / 100), 4)
            if r3 is not None and br is not None:
                rs_ref = round((1 + r3 / 100) / (1 + br / 100), 4)

        if dprice is None:
            status = "No reference data"
        elif abs(dprice) > PRICE_TOL_PCT:
            status = "Price mismatch"
        elif d3 is not None and abs(d3) > RETURN_TOL_PCT:
            status = "Return drift"
        else:
            status = "Confirmed"

        rows.append({
            "Ticker":    t,
            "Sector":    names.get(t, ""),
            "Status":    status,
            "Ours":      round(po, 2),
            "Reference": round(pr, 2),
            "Δ Price %": round(dprice, 2) if dprice is not None else None,
            "Ours 3M %": round(o3, 1) if o3 is not None else None,
            "Ref 3M %":  round(r3, 1) if r3 is not None else None,
            "Δ 3M pts":  round(d3, 1) if d3 is not None else None,
            "Ours RS":   rs_ours,
            "Ref RS":    rs_ref,
            "As Of":     pd.Timestamp(d).strftime("%Y-%m-%d"),
        })

    df = pd.DataFrame(rows)

    # The headline test: does the reference source produce the SAME ordering?
    paired = df.dropna(subset=["Ours RS", "Ref RS"])
    corr = None
    if len(paired) >= 4:
        try:
            # Spearman = Pearson on the ranks, computed that way on purpose:
            # Series.corr(method="spearman") delegates to scipy, which is not
            # a dependency of this project, so it would raise here and leave
            # the headline check reading "n/a" forever with nothing to show
            # for it. Ranking first needs only pandas.
            corr = float(paired["Ours RS"].rank().corr(paired["Ref RS"].rank()))
        except Exception:
            corr = None

    top_match = None
    if len(paired) >= 3:
        ours_top = set(paired.nlargest(3, "Ours RS")["Ticker"])
        ref_top = set(paired.nlargest(3, "Ref RS")["Ticker"])
        top_match = len(ours_top & ref_top)

    confirmed = int((df["Status"] == "Confirmed").sum()) if not df.empty else 0
    summary = {
        "status":       "ok",
        "source":       "Stooq (independent daily OHLC)",
        "checked":      int(len(df)),
        "confirmed":    confirmed,
        "mismatched":   int(len(df)) - confirmed,
        "rank_corr":    round(corr, 3) if corr is not None else None,
        "rank_ok":      (corr is not None and corr >= RANK_CORR_MIN),
        "top3_overlap": top_match,
        "as_of":        df["As Of"].max() if not df.empty and df["As Of"].any() else "",
    }
    return df, summary
