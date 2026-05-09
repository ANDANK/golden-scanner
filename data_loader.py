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


# ── Cached Data Fetchers ───────────────────────────────────────

def _fetch_price_history(ticker: str, period: str, interval: str) -> pd.DataFrame:
    df = yf.download(ticker, period=period, interval=interval,
                     progress=False, auto_adjust=True)
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_price_history(ticker: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
    """Fetch OHLCV history with retry + stale-cache fallback."""
    result, _ = _resilient(_fetch_price_history, ticker, period, interval,
                           key=("price_history", ticker, period, interval))
    return result if isinstance(result, pd.DataFrame) else pd.DataFrame()


def _fetch_info(ticker: str) -> dict:
    info = yf.Ticker(ticker).info
    return info if info else {}


@st.cache_data(ttl=300, show_spinner=False)
def get_info(ticker: str) -> dict:
    """Fetch fundamental info with retry + stale-cache fallback."""
    result, _ = _resilient(_fetch_info, ticker, key=("info", ticker))
    return result if isinstance(result, dict) else {}


def _fetch_options_chain(ticker: str, expiry: Optional[str]) -> Tuple[pd.DataFrame, pd.DataFrame, List[str]]:
    t = yf.Ticker(ticker)
    dates = t.options
    if not dates:
        return pd.DataFrame(), pd.DataFrame(), []
    target = expiry if expiry in dates else dates[0]
    chain = t.option_chain(target)
    return chain.calls, chain.puts, list(dates)


@st.cache_data(ttl=600, show_spinner=False)
def get_options_chain(ticker: str, expiry: Optional[str] = None) -> Tuple[pd.DataFrame, pd.DataFrame, List[str]]:
    """Fetch options chain with retry + stale-cache fallback. Returns (calls, puts, expiry_dates)."""
    result, _ = _resilient(_fetch_options_chain, ticker, expiry,
                           key=("options_chain", ticker, expiry))
    if isinstance(result, tuple) and len(result) == 3:
        return result
    return pd.DataFrame(), pd.DataFrame(), []


@st.cache_data(ttl=300, show_spinner=False)
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
