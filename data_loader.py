# data_loader.py — YFinance integration with smart caching

import yfinance as yf
import pandas as pd
import numpy as np
import streamlit as st
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Callable, Any
import warnings
warnings.filterwarnings("ignore")

try:
    import requests_cache
    # In-memory cache — avoids re-hitting Yahoo Finance for the same ticker
    # within the same Streamlit session. 5-min TTL matches our st.cache_data TTL.
    YF_SESSION = requests_cache.CachedSession(
        "gs_yf_cache",
        backend="memory",
        expire_after=300,
    )
except ImportError:
    import requests
    YF_SESSION = requests.Session()

# Browser-like headers prevent Yahoo Finance from rate-limiting cloud IPs.
# Import this in any scanner that calls yf.Ticker() directly.
YF_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
})


# ── Resilience: retry + stale-cache fallback ───────────────────
# In-memory last-good store, keyed by (function, args). Survives across reruns
# within a single Streamlit session via st.session_state.

def _stale_store() -> dict:
    """Lazy-init the stale-cache store inside session_state."""
    if "_gs_stale_cache" not in st.session_state:
        st.session_state["_gs_stale_cache"] = {}
    return st.session_state["_gs_stale_cache"]


def _resilient(fn: Callable[..., Any], *args, key: tuple, attempts: int = 3,
               base_delay: float = 0.4, **kwargs) -> Tuple[Any, str]:
    """
    Run fn with exponential backoff. If all attempts fail OR return an empty
    result, fall back to the last-good cached value for this key.

    Returns (value, status) where status ∈ {"fresh", "stale", "miss"}.
    """
    store = _stale_store()
    last_exc = None
    for attempt in range(attempts):
        try:
            result = fn(*args, **kwargs)
            # Treat empty DataFrame / empty dict / empty tuple as soft failure
            is_empty = (
                (isinstance(result, pd.DataFrame) and result.empty) or
                (isinstance(result, dict) and not result) or
                (isinstance(result, tuple) and all(
                    (isinstance(x, pd.DataFrame) and x.empty) or
                    (isinstance(x, list) and not x) for x in result
                ))
            )
            if not is_empty:
                store[key] = result
                return result, "fresh"
            # Empty: try once more before falling back
            if attempt < attempts - 1:
                time.sleep(base_delay * (2 ** attempt))
                continue
        except Exception as e:
            last_exc = e
            if attempt < attempts - 1:
                time.sleep(base_delay * (2 ** attempt))
                continue
    # Exhausted retries: serve stale if available
    if key in store:
        return store[key], "stale"
    return None, "miss"


# ── Process-level cache (survives st.cache_data no-op in headless mode) ───
# Keyed by (ticker, period, interval) → DataFrame.
# In the Streamlit app @st.cache_data is the primary cache; this dict acts as
# a secondary guard so that if cache_data is bypassed (headless / mocked) each
# ticker is still only downloaded once per Python process — even when multiple
# scanners ask for the same data in the same run.
_PROC_PRICE_CACHE: dict = {}
_PROC_INFO_CACHE:  dict = {}


def prefetch_tickers(tickers: List[str], period: str = "6mo", interval: str = "1d") -> int:
    """
    Batch-download OHLCV data for all tickers in ONE yf.download() call and
    populate _PROC_PRICE_CACHE.  This turns 200 sequential API calls into a
    single bulk request and is the primary speed optimisation for Golden Scan.

    Returns the number of tickers successfully cached.

    Call this before running any scanner that uses get_price_history():
        prefetch_tickers(tickers, "6mo",  "1d")   # daily scanners
        prefetch_tickers(tickers, "1y",   "1d")   # _estimate_upside
        prefetch_tickers(tickers, "2y",   "1wk")  # weekly scanners

    Already-cached tickers (in _PROC_PRICE_CACHE) are skipped so a second
    call for the same (period, interval) is a no-op.
    """
    missing = [t for t in tickers if (t, period, interval) not in _PROC_PRICE_CACHE]
    if not missing:
        return 0

    try:
        raw = yf.download(
            missing, period=period, interval=interval,
            progress=False, auto_adjust=True,
            group_by="ticker",
        )
    except Exception:
        return 0

    if raw is None or raw.empty:
        return 0

    filled = 0
    for ticker in missing:
        _key = (ticker, period, interval)
        if _key in _PROC_PRICE_CACHE:
            continue
        try:
            if len(missing) == 1:
                df = raw.copy()
            else:
                if ticker not in raw.columns.get_level_values(0):
                    continue
                df = raw[ticker].copy()

            # Drop all-NaN rows and ensure standard column names
            df = df.dropna(how="all")
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if df.empty:
                continue

            _PROC_PRICE_CACHE[_key] = df
            filled += 1
        except Exception:
            continue

    return filled


# ── Cached Data Fetchers ───────────────────────────────────────

def _fetch_price_history(ticker: str, period: str, interval: str) -> pd.DataFrame:
    df = yf.download(ticker, period=period, interval=interval,
                     progress=False, auto_adjust=True)
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


@st.cache_data(ttl=7200, show_spinner=False)   # 2 h — stock OHLCV rarely changes intraday
def get_price_history(ticker: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
    """Fetch OHLCV history with retry + stale-cache fallback.

    Two-level cache:
      1. @st.cache_data  — Streamlit app (primary, TTL 2 h)
      2. _PROC_PRICE_CACHE — process dict (headless mode guard; no TTL,
         scoped to one scanner run so staleness is not a concern)
    """
    _key = (ticker, period, interval)
    if _key in _PROC_PRICE_CACHE:
        return _PROC_PRICE_CACHE[_key].copy()

    result, _ = _resilient(_fetch_price_history, ticker, period, interval,
                           key=("price_history", ticker, period, interval))
    if not isinstance(result, pd.DataFrame) or result.empty:
        _log_api_warn("YFinance price history", ticker, f"period={period}")
        return pd.DataFrame()

    _PROC_PRICE_CACHE[_key] = result
    return result


def _fetch_info_from_download(ticker: str) -> dict:
    """
    Build a minimal info dict from yf.download() + actions=True.
    Uses the V8 chart API — no crumb needed, works on cloud IPs.
    Used as fallback when Ticker.info is blocked.
    """
    df = yf.download(ticker, period="2y", interval="1d",
                     progress=False, auto_adjust=True, actions=True,
                     multi_level_index=False)
    if df is None or df.empty:
        return {}
    close = df["Close"].dropna()
    price = float(close.iloc[-1]) if len(close) else 0.0
    if price <= 0:
        return {}

    divs = df["Dividends"].dropna() if "Dividends" in df.columns else pd.Series(dtype=float)
    divs = divs[divs > 0]
    result: dict = {"currentPrice": price, "regularMarketPrice": price,
                    "sector": "Unknown", "dividendYield": 0.0,
                    "dividendRate": 0.0, "lastDividendValue": 0.0}
    if not divs.empty:
        last_div   = float(divs.iloc[-1])
        last_date  = divs.index[-1]
        freq_days  = int((divs.index[-1] - divs.index[-2]).days) if len(divs) >= 2 else 91
        freq_days  = max(25, min(freq_days, 200))
        annual_div = last_div * (365 / freq_days)
        next_ex    = last_date + pd.Timedelta(days=freq_days)
        result.update({
            "lastDividendValue": last_div,
            "dividendRate":      round(annual_div, 4),
            "dividendYield":     annual_div / price,
            "exDividendDate":    int(pd.Timestamp(next_ex).timestamp()),
        })
    return result


def _fetch_info(ticker: str) -> dict:
    # Try Ticker.info first (requires crumb — works locally, may be blocked on cloud)
    try:
        info = yf.Ticker(ticker, session=YF_SESSION).info
        if info and len(info) > 10:   # real info has 50+ keys; empty fallback has ~5
            return info
    except Exception:
        pass
    # Fallback: build from download — always works
    return _fetch_info_from_download(ticker)


@st.cache_data(ttl=7200, show_spinner=False)   # 2 h — fundamentals are daily data
def get_info(ticker: str) -> dict:
    """Fetch fundamental info with retry + stale-cache fallback.

    Same two-level cache as get_price_history: @st.cache_data for the app,
    _PROC_INFO_CACHE for headless runs where cache_data is a no-op.
    """
    if ticker in _PROC_INFO_CACHE:
        return dict(_PROC_INFO_CACHE[ticker])   # shallow copy

    result, _ = _resilient(_fetch_info, ticker, key=("info", ticker))
    if not isinstance(result, dict) or not result:
        _log_api_warn("YFinance fundamentals", ticker)
        return {}

    _PROC_INFO_CACHE[ticker] = result
    return result


# ── Global API warning store ───────────────────────────────────
_API_WARN_KEY = "_gs_api_warnings"

def _log_api_warn(source: str, ticker: str, detail: str = "") -> None:
    """Record an API fetch issue to session_state for deferred display."""
    import streamlit as _st
    _st.session_state.setdefault(_API_WARN_KEY, []).append(
        {"source": source, "ticker": ticker, "detail": detail}
    )

def show_api_warnings() -> None:
    """
    Display all collected API warnings as a single st.warning() block.
    Call once per scanner render() after the scan completes.
    Clears the store after display so warnings don't accumulate across reruns.
    """
    import streamlit as _st
    warns = _st.session_state.pop(_API_WARN_KEY, [])
    if not warns:
        return
    sources  = sorted(set(w["source"]  for w in warns))
    tickers  = sorted(set(w["ticker"]  for w in warns if w["ticker"]))
    count    = len(warns)
    tk_list  = ", ".join(tickers[:8]) + ("…" if len(tickers) > 8 else "")
    src_list = ", ".join(sources)
    _st.warning(
        f"**{count} API fetch issue(s)** from {src_list}. "
        f"Affected tickers: {tk_list or 'unknown'}. "
        f"Yahoo Finance may be throttling — try reducing Universe Size or retrying in 30 s.",
        icon="⚠️",
    )


# ── Options error store (non-cached, lives in session_state) ──
_OPT_ERR_KEY = "_gs_opt_errors"

def _log_opt_err(ticker: str, msg: str) -> None:
    st.session_state.setdefault(_OPT_ERR_KEY, {})[ticker] = msg

def get_options_error(ticker: str) -> str:
    """Return the last recorded options-fetch error for a ticker (empty string = none)."""
    return st.session_state.get(_OPT_ERR_KEY, {}).get(ticker, "")


def _make_options_ticker(ticker: str) -> "yf.Ticker":
    """
    Create a yf.Ticker using a curl_cffi session with Chrome impersonation.
    - impersonate="chrome" mimics real browser TLS fingerprint → bypasses
      Yahoo Finance bot detection and rate limiting
    - verify=False avoids SSL bundle issues on Windows/some cloud envs
    Falls back to no-session (yfinance internal curl_cffi) if import fails.
    """
    try:
        from curl_cffi import requests as curl_req
        session = curl_req.Session(verify=False, impersonate="chrome")
        return yf.Ticker(ticker, session=session)
    except Exception:
        return yf.Ticker(ticker)   # fallback: let yfinance manage curl_cffi


def _is_rate_limit(exc: Exception) -> bool:
    """Return True if the exception looks like a Yahoo rate-limit error."""
    name = type(exc).__name__
    msg  = str(exc).lower()
    return (
        "ratelimit" in name.lower() or
        "too many" in msg or
        "rate limit" in msg or
        "429" in msg
    )


def _fetch_options_chain(ticker: str, expiry: Optional[str]) -> Tuple[pd.DataFrame, pd.DataFrame, List[str]]:
    """
    Fetch options chain using curl_cffi with Chrome impersonation to avoid
    Yahoo Finance rate limiting and bot detection.

    Key optimisation: when expiry=None (dates-only call), we ONLY fetch
    the expiry list — no chain download — halving the number of API calls.
    The chain is fetched only when a specific expiry string is supplied.

    Three attempts with rate-limit-aware back-off:
      attempt 0 → immediate
      attempt 1 → 20 s pause (YFRateLimitError needs a real break)
      attempt 2 → 40 s pause
    """
    import random
    errors: List[str] = []

    for attempt in range(3):
        try:
            if attempt > 0:
                # Rate-limit errors need a genuine pause, not just 1-2 s
                delay = 20.0 * attempt + random.uniform(0, 5)
                time.sleep(delay)

            t = _make_options_ticker(ticker)

            # ── Step 1: fetch expiry dates ────────────────────────────
            try:
                dates = list(t.options or [])
            except Exception as e:
                errors.append(f"dates:{type(e).__name__}:{str(e)[:80]}")
                if _is_rate_limit(e):
                    # Signal to the scan loop that a global pause may help
                    st.session_state["_rl_hit"] = time.time()
                continue

            if not dates:
                errors.append("no_expiry_dates")
                continue

            # ── Dates-only mode (expiry=None): return early, no chain ─
            if expiry is None:
                st.session_state.get(_OPT_ERR_KEY, {}).pop(ticker, None)
                return pd.DataFrame(), pd.DataFrame(), dates

            # ── Step 2: fetch chain for the requested expiry ──────────
            target = expiry if expiry in dates else dates[0]
            try:
                chain = t.option_chain(target)
            except Exception as e:
                errors.append(f"chain:{type(e).__name__}:{str(e)[:80]}")
                if _is_rate_limit(e):
                    st.session_state["_rl_hit"] = time.time()
                continue

            calls = getattr(chain, "calls", pd.DataFrame())
            puts  = getattr(chain, "puts",  pd.DataFrame())

            if calls.empty and puts.empty:
                errors.append(f"empty_chain@{target}")
                continue

            st.session_state.get(_OPT_ERR_KEY, {}).pop(ticker, None)
            return calls, puts, dates

        except Exception as e:
            errors.append(f"outer:{type(e).__name__}:{str(e)[:80]}")
            if _is_rate_limit(e):
                st.session_state["_rl_hit"] = time.time()

    _log_opt_err(ticker, " | ".join(errors) if errors else "unknown")
    return pd.DataFrame(), pd.DataFrame(), []


@st.cache_data(ttl=14400, show_spinner=False)  # 4 h — options chains are slow/expensive to fetch
def get_options_chain(ticker: str, expiry: Optional[str] = None) -> Tuple[pd.DataFrame, pd.DataFrame, List[str]]:
    """Fetch options chain with retry + stale-cache fallback. Returns (calls, puts, expiry_dates)."""
    result, _ = _resilient(_fetch_options_chain, ticker, expiry,
                           key=("options_chain", ticker, expiry))
    if isinstance(result, tuple) and len(result) == 3:
        return result
    return pd.DataFrame(), pd.DataFrame(), []


@st.cache_data(ttl=60, show_spinner=False)
def get_prepost_price(ticker: str) -> dict:
    """
    Fetch the most recent available price, including extended hours.
    Returns {"price": float, "reg_close": float, "change_pct": float, "session": str}
    or {} on failure.
    """
    try:
        df = yf.download(ticker, period="1d", interval="1m",
                         progress=False, prepost=True, auto_adjust=True)
        if df is None or df.empty:
            return {}
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        close = df["Close"].dropna()
        if close.empty:
            return {}

        last_price = float(close.iloc[-1])
        # Regular-hours close: last bar at or before 16:00 local
        reg_bars = close[close.index.time <= pd.Timestamp("16:00").time()]
        reg_close = float(reg_bars.iloc[-1]) if not reg_bars.empty else last_price
        change_pct = (last_price - reg_close) / reg_close * 100 if reg_close else 0.0

        import datetime as _dt
        hour = _dt.datetime.now().hour + _dt.datetime.now().minute / 60
        if hour < 9.5:
            session = "Pre-Market"
        elif hour >= 16.0:
            session = "After-Hours"
        else:
            session = "Regular"

        return {
            "price":      round(last_price, 2),
            "reg_close":  round(reg_close, 2),
            "change_pct": round(change_pct, 2),
            "session":    session,
        }
    except Exception:
        return {}


@st.cache_data(ttl=3600, show_spinner=False)   # 1 h — batch quotes for dashboard/watchlist
def get_batch_quotes(tickers: List[str]) -> pd.DataFrame:
    """Fetch current quotes for a list of tickers efficiently."""
    try:
        raw = yf.download(
            tickers, period="5d", interval="1d",
            progress=False, auto_adjust=True, group_by="ticker"
        )
        if raw.empty:
            return pd.DataFrame()

        records = []
        for tk in tickers:
            try:
                if len(tickers) == 1:
                    df = raw
                else:
                    df = raw[tk] if tk in raw.columns.get_level_values(0) else pd.DataFrame()

                if df.empty or len(df) < 2:
                    continue

                close = df["Close"].dropna()
                volume = df["Volume"].dropna()

                if len(close) < 2:
                    continue

                prev = float(close.iloc[-2])
                curr = float(close.iloc[-1])
                chg_pct = ((curr - prev) / prev * 100) if prev else 0
                avg_vol = float(volume.iloc[:-1].mean()) if len(volume) > 1 else float(volume.iloc[-1])
                curr_vol = float(volume.iloc[-1])

                records.append({
                    "Ticker": tk,
                    "Price": round(curr, 2),
                    "Change %": round(chg_pct, 2),
                    "Volume": int(curr_vol),
                    "Avg Volume": int(avg_vol),
                    "Vol Ratio": round(curr_vol / avg_vol, 2) if avg_vol else 0,
                })
            except Exception:
                continue

        return pd.DataFrame(records)
    except Exception:
        return pd.DataFrame()


# ── Options helpers (shared by CSP / CC / LEAPS / ETF Options) ─

def find_best_expiry(expiries: List[str], dte_min: int, dte_max: int,
                     fallback: bool = True) -> Optional[Tuple[str, int]]:
    """
    Pick the first expiry whose DTE falls in [dte_min, dte_max].
    If none and fallback=True, return the first positive-DTE expiry.
    Returns (expiry_str, dte) or None.
    """
    today = datetime.now()
    in_range = None
    first_positive = None
    for exp in expiries:
        try:
            dte = (datetime.strptime(exp, "%Y-%m-%d") - today).days
        except Exception:
            continue
        if dte <= 0:
            continue
        if first_positive is None:
            first_positive = (exp, dte)
        if dte_min <= dte <= dte_max and in_range is None:
            in_range = (exp, dte)
            break
    if in_range is not None:
        return in_range
    return first_positive if fallback else None


def pick_strike(chain: pd.DataFrame, price: float, scanner_type: str,
                config: dict) -> Optional[pd.Series]:
    """
    Pick the best strike from an options chain using config rules from
    OPTIONS_STRIKE_RANGES[scanner_type]. `config` is the strike_range dict
    (passed in to avoid coupling this module to config.py).

    Returns the chosen row as a pd.Series, or None if no candidate exists.
    """
    if chain is None or chain.empty or price <= 0:
        return None

    min_strike = price * config["min_pct"]
    max_strike = price * config["max_pct"]
    target_delta = config["target_delta"]
    fallback_pct = config["fallback_pct"]
    delta_floor = config.get("delta_floor", 0.05)
    delta_ceiling = config.get("delta_ceiling", 0.95)

    # Strike-window filter
    candidates = chain[
        (chain["strike"] >= min_strike) & (chain["strike"] <= max_strike)
    ].copy()
    if candidates.empty:
        return None

    # Use real delta if column has any non-zero values
    use_delta = False
    if "delta" in candidates.columns:
        valid = candidates["delta"].dropna()
        if len(valid) > 0 and valid.abs().max() > 0.01:
            use_delta = True

    if use_delta:
        candidates = candidates.assign(_delta_abs=candidates["delta"].abs())
        candidates = candidates[
            (candidates["_delta_abs"] >= delta_floor) &
            (candidates["_delta_abs"] <= delta_ceiling)
        ]
        if candidates.empty:
            return None
        candidates = candidates.assign(
            _dist=(candidates["_delta_abs"] - target_delta).abs()
        ).sort_values("_dist")
    else:
        # Strike-distance fallback when delta data is missing
        target_strike = price * fallback_pct
        candidates = candidates.assign(
            _dist=(candidates["strike"] - target_strike).abs()
        ).sort_values("_dist")

    return candidates.iloc[0]


@st.cache_data(ttl=60, show_spinner=False)
def get_market_overview() -> dict:
    """Fetch broad market indicators."""
    indices = {"S&P 500": "^GSPC", "NASDAQ": "^IXIC", "DOW": "^DJI",
               "VIX": "^VIX", "Gold": "GC=F", "10Y Yield": "^TNX"}
    result = {}
    for name, sym in indices.items():
        try:
            df = yf.download(sym, period="2d", interval="1d",
                             progress=False, auto_adjust=True)
            if df.empty or len(df) < 2:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            close = df["Close"].dropna()
            if len(close) < 2:
                continue
            curr = float(close.iloc[-1])
            prev = float(close.iloc[-2])
            chg = (curr - prev) / prev * 100
            result[name] = {"value": round(curr, 2), "change": round(chg, 2)}
        except Exception:
            continue
    return result
