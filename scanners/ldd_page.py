# scanners/ldd_page.py — LDD Signal Dashboard
"""
Ingests the paid Discord "LDD method" indicator alerts (Monthly / Weekly /
Daily), keeps a running per-ticker "latest known state" per timeframe, pulls
live technicals for every ticker ever pasted, and shows two INDEPENDENT
verdicts side by side:

  • Rule-Based Verdict  — Andy's literal trading rules (deterministic, §5)
  • Technical Verdict   — a transparent tally of the computed indicators (§6)

The two verdict columns are never reconciled: when they disagree, that IS the
signal worth a second look.

PERSISTENCE
-----------
On Streamlit Cloud this app's checkout is READ-ONLY and ephemeral, so the page
cannot commit JSON to GitHub the way the spec's data/ldd/ layout imagines — a
disk write would vanish on the next rebuild. The app's established durable-write
path is Google Sheets (gsheet_helper), the same store the Watchlist page uses,
so the LDD history lives there instead:

  LDD_State : cell A1 holds the running latest_state JSON  (the master lookup)
  LDD_Raw   : append-only, one row per parsed item per paste (audit history)

The latest_state semantics from the spec are preserved exactly: a new batch for
one timeframe overwrites ONLY that timeframe's slot for the tickers in it;
every other ticker and every other slot is left untouched, so a Monthly paste
keeps holding as "master" context across the weekly/daily pastes in between.

The technical snapshot is derived (re-computable) rather than precious, so it is
cached with st.cache_data(ttl=4h) instead of stored — "Refresh technicals"
clears that cache.
"""
import re
import json
from datetime import datetime, date, timedelta, timezone

import numpy as np
import pandas as pd
import streamlit as st

from config import (GOLD, TEXT_MUTED, TEXT_PRIMARY, ACCENT_GREEN, ACCENT_RED,
                    ACCENT_BLUE, BG_CARD, BG_PANEL, BORDER_COLOR)
from utils import section_header, calc_rsi, calc_macd, calc_sma, calc_ema
from data_loader import get_price_history


# ════════════════════════════════════════════════════════════════════════════
# PARSER  (§3 — reused verbatim; anchors on the ticker right before is/IS +
#          CONFIRMED/showing, so free-text lead-ins don't mis-capture)
# ════════════════════════════════════════════════════════════════════════════
SIGNAL_LINE_RE = re.compile(
    r'\b([A-Z][A-Z0-9.]{0,14})\s*(?:🟢\s*)?(?:is|IS)\s+(CONFIRMED|showing)\b'
)
TIMEFRAME_RE = re.compile(r'\b(MONTHLY|WEEKLY|DAILY)\b', re.IGNORECASE)
PRICE_RE = re.compile(r'\bat\s+([\d.]+)', re.IGNORECASE)

# Fair-price / "mean" weekly-section alert: price crossing the blue line
# (4-year / 200-week moving average = the "fair price / mean" per the cheat
# sheet). Confirmed live format (Sep 2026):
#     "WEAT is crossing the 4 YEAR MOVING AVERAGE!"
#     "1. CORN is crossing the 4 YEAR MOVING AVERAGE!"   (list-numbered, no price)
# A line counts as a fair-price alert only when it (a) names one of these
# phrases AND (b) has a "<TICKER> is/crossed/crossing …" anchor. Normal
# CONFIRMED/showing lines carry no fair phrase, so the two parsers never
# double-count a line. These alerts carry no "at X", so price is None and the
# computed 200-week value is the fair reference.
FAIR_PHRASE_RE = re.compile(
    r'(fair\s*price|4[\s-]?year\s+moving\s+average|blue\s*line|200[\s-]?week|\bmean\b)',
    re.IGNORECASE)
FAIR_TICKER_RE = re.compile(
    r'\b([A-Z][A-Z0-9.]{0,14})\b(?:\s*🔵)?\s+(?:is|IS|crossed|CROSSED|crossing|CROSSING)\b')

COMPOSITES = {"TOTAL", "TOTAL2", "TOTAL3", "OTHERS", "BTC.D", "ETHBTC"}
CRYPTO_SUFFIX_RE = re.compile(r'^([A-Z]+?)(USDT|USD|BTC)$')
DEFAULT_CORE_CRYPTO = {"BTC", "ETH", "XRP", "SOL", "DOGE"}

_TF_ORDER = ("monthly", "weekly", "daily")


def parse_signal_line(line: str):
    m = SIGNAL_LINE_RE.search(line)
    if not m:
        return None
    ticker = m.group(1)
    status = "confirmed" if m.group(2) == "CONFIRMED" else "showing"
    tf_match = TIMEFRAME_RE.search(line)
    timeframe = tf_match.group(1).upper() if tf_match else None
    price_match = PRICE_RE.search(line)
    price = float(price_match.group(1)) if price_match else None
    return {"ticker": ticker, "status": status, "timeframe": timeframe, "price": price}


def classify_ticker(ticker: str, core_crypto: set):
    if ticker in COMPOSITES:
        return {"type": "composite", "include": False}
    m = CRYPTO_SUFFIX_RE.match(ticker)
    if m:
        return {"type": "crypto", "base": m.group(1), "include": m.group(1) in core_crypto}
    return {"type": "equity", "include": True}


def parse_batch(text: str, tab_timeframe: str, core_crypto: set):
    """Parse a whole paste. `tab_timeframe` ('monthly'/'weekly'/'daily') is the
    fallback used when a line does not name its own timeframe. Returns
    (kept_items, filtered_items); deduped within the paste by (ticker, timeframe)."""
    seen, kept, filtered = set(), [], []
    for line in text.splitlines():
        r = parse_signal_line(line)
        if not r:
            continue
        tf = (r["timeframe"] or tab_timeframe or "").lower()
        if tf not in _TF_ORDER:
            continue
        key = (r["ticker"], tf)
        if key in seen:
            continue
        seen.add(key)
        cls = classify_ticker(r["ticker"], core_crypto)
        item = {"ticker": r["ticker"], "status": r["status"], "timeframe": tf,
                "price": r["price"], "type": cls["type"]}
        (kept if cls["include"] else filtered).append(item)
    return kept, filtered


def apply_batch_to_state(state: dict, items: list, signal_date: str) -> dict:
    """Overwrite ONLY each item's timeframe slot; other slots/tickers untouched (§2b)."""
    for it in items:
        slot = state.setdefault(it["ticker"], {"monthly": None, "weekly": None, "daily": None})
        slot[it["timeframe"]] = {"status": it["status"], "price": it["price"],
                                 "signal_date": signal_date}
    return state


def parse_fair_batch(text: str, core_crypto: set):
    """Best-effort parse of the weekly-section 'price crossing the blue line
    (200-week MA / fair price / mean)' alert. Deduped by ticker within the
    paste. Returns (kept, filtered) like parse_batch. Composites and off-list
    crypto are filtered the same way."""
    seen, kept, filtered = set(), [], []
    for line in text.splitlines():
        if not FAIR_PHRASE_RE.search(line):
            continue
        m = FAIR_TICKER_RE.search(line)
        if not m:
            continue
        ticker = m.group(1)
        if ticker in seen:
            continue
        seen.add(ticker)
        pm = PRICE_RE.search(line)
        price = float(pm.group(1)) if pm else None
        cls = classify_ticker(ticker, core_crypto)
        item = {"ticker": ticker, "price": price, "type": cls["type"]}
        (kept if cls["include"] else filtered).append(item)
    return kept, filtered


def apply_fair_to_state(state: dict, items: list, signal_date: str) -> dict:
    """Write each ticker's 'fair' slot (the 200-week / fair-price alert). Like
    the timeframe slots, this overwrites only the fair slot and leaves
    monthly/weekly/daily untouched."""
    for it in items:
        slot = state.setdefault(it["ticker"], {"monthly": None, "weekly": None, "daily": None})
        slot["fair"] = {"price": it["price"], "signal_date": signal_date}
    return state


# ════════════════════════════════════════════════════════════════════════════
# GOOGLE-SHEETS PERSISTENCE  (reuses gsheet_helper — the app's durable store)
# ════════════════════════════════════════════════════════════════════════════
_STATE_TAB = "LDD_State"
_RAW_TAB = "LDD_Raw"
_RAW_HEADERS = ["parsed_at", "signal_date", "timeframe", "ticker", "status", "price"]


def _sheets_ready() -> bool:
    try:
        from scanners.gsheet_helper import gsheets_configured
        return bool(gsheets_configured())
    except Exception:
        return False


@st.cache_data(ttl=120, show_spinner=False)
def load_state() -> tuple[dict, str]:
    """Running latest_state, read from LDD_State!A1. Returns (state, status) so
    callers can tell an empty universe apart from a connection/read failure —
    the three used to collapse to the same empty dict. status is one of:
      'ok'            — state read and non-empty
      'empty'         — connected, but A1 is blank (genuinely no tickers yet)
      'not_connected' — no [gsheets] credentials configured
      'read_error'    — Sheets threw (transient API / quota / permissions) or
                        A1 held unparseable JSON — the saved data is NOT lost
    Cached 2 min so the table doesn't re-hit Sheets on every widget interaction;
    cleared after a save or via the Reload button."""
    if not _sheets_ready():
        return {}, "not_connected"
    try:
        from scanners.gsheet_helper import _gs_sheet
        raw = _gs_sheet(_STATE_TAB).acell("A1").value
    except Exception:
        return {}, "read_error"
    if not raw:
        return {}, "empty"
    try:
        return (json.loads(raw) or {}), "ok"
    except Exception:
        return {}, "read_error"


def save_state(state: dict) -> tuple[bool, str]:
    if not _sheets_ready():
        return False, "Google Sheets not connected — add [gsheets] credentials in Secrets."
    try:
        from scanners.gsheet_helper import _gs_sheet
        _gs_sheet(_STATE_TAB).update_acell("A1", json.dumps(state))
        return True, "State saved."
    except Exception as e:
        return False, f"Save failed: {e}"


def append_raw(items: list, signal_date: str, parsed_at: str) -> None:
    if not items or not _sheets_ready():
        return
    try:
        from scanners.gsheet_helper import _gs_sheet
        ws = _gs_sheet(_RAW_TAB)
        try:
            if not ws.acell("A1").value:
                ws.update([_RAW_HEADERS], "A1")
        except Exception:
            pass
        rows = [[parsed_at, signal_date, it["timeframe"], it["ticker"], it["status"],
                 "" if it["price"] is None else it["price"]] for it in items]
        ws.append_rows(rows)
    except Exception:
        pass   # raw log is best-effort audit; never block a save on it


# ════════════════════════════════════════════════════════════════════════════
# INDICATORS  (reuse utils where it exists; add only what's missing — §7)
#   utils already gives Wilder RSI (calc_rsi) and MACD (calc_macd → macd,
#   signal, hist, prev_hist). Net-new below: Wilder RSI *series* (for StochRSI
#   direction), ADX(14), StochRSI(14,3,3), EMA34/50 cloud, Golden/Death cross,
#   extension vs EMA20, and weekly variants via a W-FRI resample.
# ════════════════════════════════════════════════════════════════════════════
def _wilder_rsi_series(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0)
    dn = (-d).clip(lower=0)
    au = up.ewm(alpha=1 / n, adjust=False).mean()
    ad = dn.ewm(alpha=1 / n, adjust=False).mean()
    rs = au / ad.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def _adx(df: pd.DataFrame, n: int = 14) -> float:
    h, l, c = df["High"], df["Low"], df["Close"]
    up, dn = h.diff(), -l.diff()
    plus_dm = up.where((up > dn) & (up > 0), 0.0)
    minus_dm = dn.where((dn > up) & (dn > 0), 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * plus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr
    mdi = 100 * minus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    return float(adx) if pd.notna(adx) else 0.0


def _stoch_rsi(close: pd.Series, rsi_n: int = 14, stoch_n: int = 14,
               k: int = 3, d: int = 3):
    """Standard StochRSI(14,3,3). Returns (%K, %D) as 0-100 floats — a best-
    effort PROXY for the indicator's proprietary blue-wave/white-line, never
    presented as equivalent."""
    rsi = _wilder_rsi_series(close, rsi_n)
    lo = rsi.rolling(stoch_n).min()
    hi = rsi.rolling(stoch_n).max()
    stoch = ((rsi - lo) / (hi - lo).replace(0, np.nan) * 100).fillna(50)
    kk = stoch.rolling(k).mean()
    dd = kk.rolling(d).mean()
    return float(kk.iloc[-1]), float(dd.iloc[-1])


def _macd_state(close: pd.Series):
    """(zone, cross) from utils.calc_macd. zone: Positive/Negative/Near-Zero;
    cross: 'bull'/'bear'/'' for a fresh histogram sign flip."""
    if len(close) < 35:
        return "n/a", ""
    macd, sig, hist, prev = calc_macd(close)
    px = float(close.iloc[-1]) or 1.0
    zone = ("Positive" if macd > px * 0.001 else
            "Negative" if macd < -px * 0.001 else "Near-Zero")
    cross = "bull" if (prev <= 0 and hist > 0) else "bear" if (prev >= 0 and hist < 0) else ""
    return zone, cross


# WaveTrend "blue wave" (LazyBear formula, identical to scanners/overkill_check.py
# so the LDD blue wave and the OverKill dots come from one engine). ±53 are the
# overbought/oversold "white lines".
_WT_OS = -53
_WT_OB = 53

# "Fair price / mean" line = the blue 4-year moving average Andy watches. On the
# weekly it is the 200-week SMA (the classic crypto "mean / fair value" line,
# ~3.85 yr). Price within ±_FAIR_BAND_PCT_DEFAULT % of it counts as "at the mean"
# (the fair-value buy zone); the band is tunable from Settings.
_FAIR_MA_WEEKS = 200
_FAIR_BAND_PCT_DEFAULT = 5.0


def _wt1_series(df: pd.DataFrame) -> pd.Series:
    """WaveTrend WT1 (the blue wave)."""
    h3 = (df["High"] + df["Low"] + df["Close"]) / 3.0
    esa = calc_ema(h3, 9)
    d = calc_ema((h3 - esa).abs(), 9).replace(0, np.nan)
    ci = (h3 - esa) / (0.015 * d)
    return calc_ema(ci, 12)


def _weekly(df: pd.DataFrame) -> pd.DataFrame:
    return (df.resample("W-FRI")
              .agg({"Open": "first", "High": "max", "Low": "min",
                    "Close": "last", "Volume": "sum"})
              .dropna(subset=["Close"]))


@st.cache_data(ttl=14400, show_spinner=False)   # 4 h — matches the "refresh stale" default
def tech_snapshot(ticker: str) -> dict:
    """All technical fields for one ticker. Cached 4 h; 'Refresh technicals'
    clears the cache. Returns a flat dict (never raises — errors → {'ok': False})."""
    out = {"ticker": ticker, "ok": False, "as_of": datetime.now(timezone.utc).isoformat()}
    try:
        # 5y so the 200-week (≈3.85 yr) fair-price SMA has enough weekly bars
        # plus a prior value for cross detection. Young tickers (< 200 weeks of
        # history) simply get an unavailable fair price — handled below.
        df = get_price_history(ticker, period="5y")
        if df is None or df.empty:
            return out
        if isinstance(df.columns, pd.MultiIndex):
            df = df.copy(); df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        c = df["Close"]
        if len(c) < 60:
            return out
        px = float(c.iloc[-1])

        rsi_d = float(calc_rsi(c))
        rsi_d_prev = float(calc_rsi(c.iloc[:-3])) if len(c) > 20 else rsi_d
        ema20 = float(calc_ema(c, 20).iloc[-1])
        ema50 = float(calc_ema(c, 50).iloc[-1])
        ema34 = float(calc_ema(c, 34).iloc[-1])
        sma50 = calc_sma(c, 50)
        sma200 = calc_sma(c, 200)
        macd_d_zone, macd_d_cross = _macd_state(c)
        adx = _adx(df)
        sk, sd = _stoch_rsi(c)

        # Golden / Death cross on SMA50×200 within the last ~15 sessions
        gd = ""
        if len(sma200.dropna()) > 16:
            diff = (sma50 - sma200).dropna()
            if len(diff) > 16:
                recent = diff.iloc[-15:]
                if (recent.iloc[0] <= 0) and (recent.iloc[-1] > 0):
                    gd = "golden"
                elif (recent.iloc[0] >= 0) and (recent.iloc[-1] < 0):
                    gd = "death"
                elif diff.iloc[-1] > 0:
                    gd = "above"    # 50 already over 200 (bullish regime, no fresh cross)
                else:
                    gd = "below"

        # Weekly
        wk = _weekly(df)
        wc = wk["Close"]
        rsi_w = float(calc_rsi(wc)) if len(wc) >= 20 else float("nan")
        macd_w_zone, macd_w_cross = _macd_state(wc) if len(wc) >= 35 else ("n/a", "")

        ema_cloud = ("bullish" if (ema34 > ema50 and px > ema34) else
                     "bearish" if (ema34 < ema50 and px < ema34) else "neutral")
        ext_ema20 = (px / ema20 - 1) * 100 if ema20 else 0.0
        adx_zone = ("Trending" if adx >= 25 else "Developing" if adx >= 20 else "Choppy")

        # WaveTrend "blue wave" — LazyBear engine, the same one that draws the
        # OverKill green/red dots. wt1 is the blue wave; the two horizontal white
        # lines are the OB/OS boundaries (±53). "Blue wave below the white line" =
        # wt1 <= WT_OS on that timeframe (the oversold buy zone). Validated against
        # Andy's own indicator screenshots (IonQ/SEI/Centene/CDW).
        wt1_d = float(_wt1_series(df).iloc[-1])
        _wtw = _wt1_series(wk)
        wt1_w = float(_wtw.iloc[-1]) if len(_wtw.dropna()) else float("nan")
        wt_w_below = bool(wt1_w == wt1_w and wt1_w <= _WT_OS)   # weekly buy zone
        wt_d_below = bool(wt1_d == wt1_d and wt1_d <= _WT_OS)
        wt_w_state = ("Below white" if wt_w_below else
                      "Above white" if (wt1_w == wt1_w and wt1_w >= _WT_OB) else
                      "Mid" if wt1_w == wt1_w else "—")
        # "Price trending above the EMA ribbon" — the daily-alert context condition.
        above_ema_ribbon = bool(px > ema20 > ema50)

        # Fair price / mean = the 200-week SMA (the blue 4-yr MA). Needs ≥200
        # weekly bars; younger names → fair unavailable (None). fair_cross flags
        # a FRESH weekly cross through the line this bar (the "crossing the blue
        # line" event); pct_vs_fair is price vs the mean. The band-based
        # "at the mean" / buy decision is applied live in _build_table so the
        # Settings band can change without busting this 4-h cache.
        fair_price = float("nan"); pct_vs_fair = None; fair_cross = ""
        if len(wc) >= _FAIR_MA_WEEKS:
            ma_w = wc.rolling(_FAIR_MA_WEEKS).mean()
            if pd.notna(ma_w.iloc[-1]):
                fair_price = float(ma_w.iloc[-1])
                pct_vs_fair = round((px / fair_price - 1) * 100, 1) if fair_price else None
                if len(ma_w) >= _FAIR_MA_WEEKS + 1 and pd.notna(ma_w.iloc[-2]):
                    pc, pf = float(wc.iloc[-2]), float(ma_w.iloc[-2])
                    lc, lf = float(wc.iloc[-1]), fair_price
                    if pc < pf and lc >= lf:
                        fair_cross = "up"
                    elif pc > pf and lc <= lf:
                        fair_cross = "down"

        out.update(dict(
            ok=True, price=round(px, 2),
            rsi_d=round(rsi_d, 1), rsi_d_dir=(1 if rsi_d > rsi_d_prev + 0.5
                                              else -1 if rsi_d < rsi_d_prev - 0.5 else 0),
            rsi_w=(round(rsi_w, 1) if rsi_w == rsi_w else None),
            macd_d_zone=macd_d_zone, macd_d_cross=macd_d_cross,
            macd_w_zone=macd_w_zone, macd_w_cross=macd_w_cross,
            ema20_gt_50=bool(ema20 > ema50),
            gd_cross=gd, ema_cloud=ema_cloud,
            ext_ema20=round(ext_ema20, 1),
            adx=round(adx, 1), adx_zone=adx_zone,
            stoch_k=round(sk, 1), stoch_d=round(sd, 1),
            wt1_w=(round(wt1_w, 1) if wt1_w == wt1_w else None),
            wt_w_below_white=wt_w_below, wt_d_below_white=wt_d_below,
            wt_w_state=wt_w_state, above_ema_ribbon=above_ema_ribbon,
            fair_price=(round(fair_price, 2) if fair_price == fair_price else None),
            pct_vs_fair=pct_vs_fair, fair_cross=fair_cross,
        ))
        return out
    except Exception:
        return out


# ════════════════════════════════════════════════════════════════════════════
# RULE-BASED VERDICT  (Andy's literal LDD rules; deterministic & inspectable)
#   Buy #1: buy on the MONTHLY (monthly green/confirmed).
#   Buy #2: buy on the WEEKLY if the blue wave is below the white line.
#   Daily : "buy as long as MONTHLY is green OR price is above the EMA ribbon."
#   The "blue wave below the white line" is a real WaveTrend recreation (see
#   _wt1_series / _WT_OS), not a rough proxy, so no proxy caveat is appended.
#   Sells (daily red zone / weekly sell) stay inert until a real example arrives.
# ════════════════════════════════════════════════════════════════════════════
def rule_based_verdict(slot: dict, tech: dict) -> str:
    slot = slot or {"monthly": None, "weekly": None, "daily": None}
    m, w, d = slot.get("monthly"), slot.get("weekly"), slot.get("daily")
    tech = tech or {}

    monthly_green = bool(m and m.get("status") == "confirmed")
    weekly_green = bool(w and w.get("status") == "confirmed")
    daily_green = bool(d and d.get("status") == "confirmed")
    blue_below = bool(tech.get("wt_w_below_white"))   # weekly blue wave below the white line
    # Fair-price buy: price at/near the 200-week mean (band-checked in
    # _build_table → tech['fair_buy']) OR a pasted "crossing the blue line" alert.
    fair_buy = bool(tech.get("fair_buy")) or bool(slot.get("fair"))

    # Compact-but-descriptive labels: the trigger (Blue Wave below vs at Mean) is
    # named in the verdict, using Month/Week shorthand to stay short.
    #
    # Both buy strategies aligned — the strongest confluence. Kept as two
    # variants so the trigger is visible in the label.
    if monthly_green and weekly_green and (blue_below or fair_buy):
        return ("Strong Buy — Month+Week+Blue Wave below" if blue_below
                else "Strong Buy — Month+Week+at Mean")
    # Buy Strategy #1 — Monthly confirmed (the strongest single standing signal).
    if monthly_green:
        return "Buy — Monthly"
    # Buy Strategy #2 — Weekly confirmed AND (blue wave below the white line OR
    # price at the 200-week mean / fair price).
    if weekly_green:
        if blue_below:
            return "Buy — Week+Blue Wave below"
        if fair_buy:
            return "Buy — Week+at Mean"
        return "Weekly — waiting (for Blue Wave below / at Mean)"
    # Standalone fair-price weekly alert — price at/near the 200-week mean with
    # no Monthly/Weekly confirm on record yet.
    if fair_buy:
        return "Buy — at Mean"
    # Daily green alert — buy as long as Monthly is green OR price is above the EMA ribbon.
    if daily_green:
        if monthly_green or tech.get("above_ema_ribbon"):
            return "Buy — Daily (Month green / EMA ribbon)"
        return "Daily — waiting (for Month green / EMA ribbon)"

    return "Watch — no signal"


# ════════════════════════════════════════════════════════════════════════════
# TECHNICAL VERDICT  (§6 — transparent tally; NEVER reconciled with the rules)
# ════════════════════════════════════════════════════════════════════════════
def technical_verdict(tech: dict) -> tuple[str, int, list]:
    """Returns (verdict, net_score, breakdown). net >= +3 Lean Buy, <= -3 Lean
    Sell, else Mixed. breakdown is a list of (label, +1/-1) for transparency."""
    if not tech or not tech.get("ok"):
        return "No Data", 0, []
    b = []
    def add(label, pts):
        if pts:
            b.append((label, pts))

    add(f"RSI {'rising' if tech['rsi_d_dir'] > 0 else 'falling' if tech['rsi_d_dir'] < 0 else 'flat'}",
        1 if tech["rsi_d_dir"] > 0 else -1 if tech["rsi_d_dir"] < 0 else 0)
    add(f"MACD {tech['macd_d_zone']}",
        1 if tech["macd_d_zone"] == "Positive" else -1 if tech["macd_d_zone"] == "Negative" else 0)
    add("MACD fresh cross " + tech["macd_d_cross"],
        1 if tech["macd_d_cross"] == "bull" else -1 if tech["macd_d_cross"] == "bear" else 0)
    add("EMA20>EMA50" if tech["ema20_gt_50"] else "EMA20<EMA50",
        1 if tech["ema20_gt_50"] else -1)
    add({"golden": "Golden cross", "death": "Death cross", "above": "50>200",
         "below": "50<200", "": ""}.get(tech["gd_cross"], ""),
        {"golden": 1, "above": 1, "death": -1, "below": -1}.get(tech["gd_cross"], 0))
    add(f"EMA cloud {tech['ema_cloud']}",
        1 if tech["ema_cloud"] == "bullish" else -1 if tech["ema_cloud"] == "bearish" else 0)
    # ADX is trend STRENGTH, not direction — it confirms the prevailing MACD sign.
    if tech["adx"] >= 25 and tech["macd_d_zone"] in ("Positive", "Negative"):
        add(f"ADX {tech['adx']:.0f} confirms",
            1 if tech["macd_d_zone"] == "Positive" else -1)

    net = sum(p for _, p in b)
    verdict = "Lean Buy" if net >= 3 else "Lean Sell" if net <= -3 else "Mixed"
    return verdict, net, b


# ════════════════════════════════════════════════════════════════════════════
# UI
# ════════════════════════════════════════════════════════════════════════════
def _slot_txt(slot):
    if not slot:
        return "—", "", ""
    return (slot.get("status", "—").capitalize(),
            f'{slot.get("price")}' if slot.get("price") is not None else "",
            slot.get("signal_date", ""))


def _build_table(state: dict, fair_band: float = _FAIR_BAND_PCT_DEFAULT) -> pd.DataFrame:
    rows = []
    for tk in sorted(state.keys()):
        slot = state[tk]
        tech = dict(tech_snapshot(tk))   # copy — we inject the live band decision
        # Fair price / mean: apply the Settings band here (cheap) so it stays
        # live without busting tech_snapshot's 4-h cache. "At the mean" = price
        # within ±band % of the 200-week SMA; a fresh weekly cross also counts.
        pctf = tech.get("pct_vs_fair")
        fair_avail = tech.get("fair_price") is not None
        at_mean = bool(fair_avail and pctf is not None and abs(pctf) <= fair_band)
        tech["fair_buy"] = bool(at_mean or tech.get("fair_cross"))
        rb = rule_based_verdict(slot, tech)
        tv, tnet, _ = technical_verdict(tech)
        m_s, m_p, m_d = _slot_txt(slot.get("monthly"))
        w_s, w_p, w_d = _slot_txt(slot.get("weekly"))
        d_s, d_p, d_d = _slot_txt(slot.get("daily"))
        # Entry = the most-recent slot that actually captured a price ("at X");
        # Gain % = current price vs that entry.
        priced = sorted(
            [(s["signal_date"], s.get("price"))
             for s in (slot.get("monthly"), slot.get("weekly"), slot.get("daily"))
             if s and s.get("price") is not None],
            key=lambda x: x[0])
        entry_price, entry_date = (priced[-1][1], priced[-1][0]) if priced else (None, "")
        cur = tech.get("price")
        gain = ((cur - entry_price) / entry_price * 100) if (entry_price and cur) else None
        # Most-recent signal date across all slots — drives the "last N weeks"
        # filter. Includes the fair slot so a ticker whose latest event is a
        # fair-price alert stays inside the recency window.
        recent_date = max([s["signal_date"] for s in
                           (slot.get("monthly"), slot.get("weekly"),
                            slot.get("daily"), slot.get("fair"))
                           if s and s.get("signal_date")], default="")
        gd = tech.get("gd_cross")
        # Fair-price display: position vs the 200-week mean + fresh-cross + a
        # marker when a "crossing the blue line" alert was actually pasted.
        if not fair_avail:
            fair_val, mean_disp, pos = None, "—", "—"
        else:
            fair_val = tech.get("fair_price")
            pos = ("At mean" if at_mean else
                   "Below mean" if (pctf is not None and pctf < 0) else "Above mean")
            arrow = (" ⤢↑ crossed" if tech.get("fair_cross") == "up" else
                     " ⤢↓ crossed" if tech.get("fair_cross") == "down" else "")
            pasted = " · alert" if slot.get("fair") else ""
            pct_txt = f"{pctf:+.1f}%" if pctf is not None else ""
            mean_disp = f"{pos} ({pct_txt}){arrow}{pasted}"
        rows.append({
            "Ticker": tk,
            "🗓️M Status": m_s, "M Price": m_p, "M Date": m_d,
            "🗓️W Status": w_s, "W Price": w_p, "W Date": w_d,
            "🗓️D Status": d_s, "D Price": d_p, "D Date": d_d,
            "Added $": entry_price, "Added": entry_date,
            "Now $": cur, "Gain %": (round(gain, 1) if gain is not None else None),
            "RSI D": tech.get("rsi_d"), "RSI W": tech.get("rsi_w"),
            "MACD D": f'{tech.get("macd_d_zone","")}{" ⚡"+tech["macd_d_cross"] if tech.get("macd_d_cross") else ""}',
            "MACD W": f'{tech.get("macd_w_zone","")}{" ⚡"+tech["macd_w_cross"] if tech.get("macd_w_cross") else ""}',
            "EMA20>50": "✅" if tech.get("ema20_gt_50") else "—",
            "G/D": "Golden" if gd in ("golden", "above") else "Death" if gd in ("death", "below") else "—",
            "Ext vs EMA20": tech.get("ext_ema20"),
            "EMA Cloud": tech.get("ema_cloud", "—"),
            "ADX": tech.get("adx"), "ADX Zone": tech.get("adx_zone", "—"),
            "Blue Wave": tech.get("wt_w_state", "—"),
            "Fair 200w": fair_val, "vs Mean": mean_disp, "vs Mean %": pctf, "Mean Pos": pos,
            "Rule-Based Verdict": rb,
            "Technical Verdict": tv,
            "_recent": recent_date, "_tnet": tnet,
        })
    return pd.DataFrame(rows)


# Column spec: (display label, group key, format kind). Groups get colored,
# spanned sub-headers so Monthly/Weekly/Daily stay scannable (spec point 5).
_PURPLE = "#9C27B0"
_TEAL = "#0EA5A5"
_GROUPS = {"ID": ("", TEXT_MUTED), "M": ("Monthly", ACCENT_BLUE), "W": ("Weekly", ACCENT_GREEN),
           "D": ("Daily", _PURPLE), "P": ("Performance", _TEAL), "T": ("Technicals", TEXT_MUTED),
           "ID2": ("", TEXT_MUTED), "V": ("Verdicts", GOLD)}
_COLS = [
    ("Ticker", "ID", "tk"), ("Signal", "ID", "raw"),
    ("Status", "M", "stat"), ("Price", "M", "raw"),
    ("Status", "W", "stat"), ("Price", "W", "raw"),
    ("Status", "D", "stat"), ("Price", "D", "raw"),
    # Verdicts immediately after Daily.
    ("Rule-Based Verdict", "V", "rb"), ("Technical Verdict", "V", "tv"),
    ("Blue Wave (W)", "T", "raw"),
    ("vs Mean", "T", "fairpos"),
    ("Cloud 34/50", "T", "raw"),
    ("Trend 20>50", "T", "raw"), ("Regime 50/200", "T", "raw"),
    ("MACD D", "T", "raw"),
    ("RSI D", "T", "num"), ("RSI W", "T", "num"),
    # 2nd ticker re-anchors the row identity just before Performance (the end).
    ("Ticker", "ID2", "tk"),
    ("Added $", "P", "usd"), ("Added", "P", "raw"), ("Now $", "P", "usd"), ("Gain %", "P", "gainpct"),
]
# maps each (label, group) to the source column in the built DataFrame
_SRC = {
    ("Ticker", "ID"): "Ticker", ("Ticker", "ID2"): "Ticker", ("Signal", "ID"): "_recent",
    ("Status", "M"): "🗓️M Status", ("Price", "M"): "M Price",
    ("Status", "W"): "🗓️W Status", ("Price", "W"): "W Price",
    ("Status", "D"): "🗓️D Status", ("Price", "D"): "D Price",
    ("Added $", "P"): "Added $", ("Added", "P"): "Added", ("Now $", "P"): "Now $", ("Gain %", "P"): "Gain %",
    ("RSI D", "T"): "RSI D", ("RSI W", "T"): "RSI W",
    ("MACD D", "T"): "MACD D",
    ("Trend 20>50", "T"): "EMA20>50", ("Regime 50/200", "T"): "G/D", ("Cloud 34/50", "T"): "EMA Cloud",
    ("Blue Wave (W)", "T"): "Blue Wave",
    ("vs Mean", "T"): "vs Mean",
    ("Rule-Based Verdict", "V"): "Rule-Based Verdict", ("Technical Verdict", "V"): "Technical Verdict",
}


def _html_table(view: pd.DataFrame) -> str:
    """Render the results as an HTML <table> — st.dataframe's canvas grid does
    not paint on this app's Streamlit Cloud deployment (see home.py Best
    Scanners), so every table here is hand-built HTML."""
    def fmt(v, kind):
        if v is None or v == "" or (isinstance(v, float) and pd.isna(v)):
            return "—"
        if kind == "usd":
            try: return f"${float(v):,.2f}"
            except (TypeError, ValueError): return "—"
        if kind in ("pct", "gainpct"):
            try: return f"{float(v):+.1f}%"
            except (TypeError, ValueError): return "—"
        if kind == "num":
            try: return f"{float(v):.1f}"
            except (TypeError, ValueError): return str(v)
        if kind == "stat":   # abbreviate for display; df keeps "Confirmed"/"Showing" for filters
            return {"Confirmed": "Conf.", "Showing": "Show."}.get(str(v), str(v))
        return str(v)

    def cell_color(v, kind):
        if kind == "stat":
            s = str(v).lower()
            return ACCENT_GREEN if s.startswith("confirm") else GOLD if s.startswith("show") else TEXT_MUTED
        if kind == "gainpct":
            try: g = float(v)
            except (TypeError, ValueError): return TEXT_MUTED
            return ACCENT_GREEN if g > 0 else ACCENT_RED if g < 0 else TEXT_MUTED
        if kind == "rb":
            s = str(v)
            return (ACCENT_GREEN if (s.startswith("Buy") or s.startswith("Strong Buy"))
                    else ACCENT_RED if s.startswith("Sell")
                    else GOLD if "waiting" in s
                    else TEXT_MUTED)
        if kind == "tv":
            return {"Lean Buy": ACCENT_GREEN, "Lean Sell": ACCENT_RED, "Mixed": GOLD}.get(str(v), TEXT_MUTED)
        if kind == "fairpos":
            s = str(v)
            if "crossed" in s:
                return ACCENT_GREEN if "↑" in s else ACCENT_RED
            if s.startswith("At mean"):
                return GOLD          # the fair-value buy zone
            if s.startswith("Below"):
                return ACCENT_BLUE   # trading under fair value (cheap)
            return TEXT_MUTED        # Above mean (rich) / —
        return TEXT_PRIMARY

    # group header row (spanned) — count columns per group in order
    grp_hdr = ""
    i = 0
    while i < len(_COLS):
        g = _COLS[i][1]
        span = 1
        while i + span < len(_COLS) and _COLS[i + span][1] == g:
            span += 1
        label, col = _GROUPS[g]
        grp_hdr += (f'<th colspan="{span}" style="background:{col}22;color:{col};'
                    f'border:1px solid {BORDER_COLOR};padding:3px 6px;font-size:10px;'
                    f'font-weight:800;text-align:center">{label}</th>')
        i += span

    _TH = (f"background:{BG_CARD};color:{TEXT_MUTED};border:1px solid {BORDER_COLOR};"
           f"padding:3px 6px;font-size:9.5px;font-weight:700;white-space:nowrap")
    col_hdr = "".join(f'<th style="{_TH}">{lbl}</th>' for lbl, _g, _k in _COLS)

    _TD = f"border:1px solid {BORDER_COLOR};padding:3px 7px;font-size:10.5px;white-space:nowrap"
    body = ""
    for j, (_, r) in enumerate(view.iterrows()):
        # Row color: tinted by the rule-based verdict, with a subtle zebra for
        # neutral (watch / no-signal) rows so they stay separable.
        rb = str(r.get("Rule-Based Verdict", ""))
        if rb.startswith("Buy") or rb.startswith("Strong Buy"):
            row_bg = f"{ACCENT_GREEN}1f"
        elif rb.startswith("Sell"):
            row_bg = f"{ACCENT_RED}1f"
        elif "waiting" in rb:
            row_bg = f"{GOLD}1f"
        else:
            row_bg = BG_PANEL if (j % 2) else BG_CARD
        tds = ""
        for lbl, g, kind in _COLS:
            v = r.get(_SRC[(lbl, g)])
            txt = fmt(v, kind)
            col = cell_color(v, kind)
            weight = "700" if (kind in ("tk", "rb", "tv", "gainpct") or (kind == "stat" and txt != "—")) else "400"
            tds += f'<td style="{_TD};color:{col};font-weight:{weight}">{txt}</td>'
        body += f'<tr style="background:{row_bg}">{tds}</tr>'

    return (f'<div style="overflow-x:auto;border:1px solid {BORDER_COLOR};border-radius:8px">'
            f'<table style="border-collapse:collapse;font-family:Inter,sans-serif;min-width:100%">'
            f'<thead><tr>{grp_hdr}</tr><tr>{col_hdr}</tr></thead>'
            f'<tbody>{body}</tbody></table></div>')


# ════════════════════════════════════════════════════════════════════════════
# PERFORMANCE  — "what's working": group return-since-signal (the Gain % already
# in the table = current price vs the price the alert fired at) by verdict and
# by condition, so the buckets that actually paid off are visible. It is a
# rough scorecard, not a backtest: entries are the alert's "at X" price, exits
# are live, samples are small, and a signal fired today shows ~0%.
# ════════════════════════════════════════════════════════════════════════════
def _perf_group(df: pd.DataFrame, col: str) -> list:
    """Return [(key, n, win%, avg, median, best, worst)] for rows that have a
    Gain %, grouped by `col`, sorted by average gain descending."""
    sub = df[pd.to_numeric(df["Gain %"], errors="coerce").notna()].copy()
    sub["_g"] = pd.to_numeric(sub["Gain %"], errors="coerce")
    out = []
    for key, g in sub.groupby(col):
        n = len(g)
        if not n:
            continue
        wins = int((g["_g"] > 0).sum())
        out.append((str(key), n, wins / n * 100.0, g["_g"].mean(),
                    g["_g"].median(), g["_g"].max(), g["_g"].min()))
    out.sort(key=lambda r: r[3], reverse=True)
    return out


def _perf_html(title: str, rows: list) -> str:
    if not rows:
        return ""
    def col_g(v):
        return ACCENT_GREEN if v > 0 else ACCENT_RED if v < 0 else TEXT_MUTED
    _TH = (f"background:{BG_CARD};color:{TEXT_MUTED};border:1px solid {BORDER_COLOR};"
           f"padding:3px 8px;font-size:10px;font-weight:700;white-space:nowrap;text-align:right")
    _TH0 = _TH.replace("text-align:right", "text-align:left")
    hdr = (f'<th style="{_TH0}">{title}</th><th style="{_TH}">N</th>'
           f'<th style="{_TH}">Win %</th><th style="{_TH}">Avg</th>'
           f'<th style="{_TH}">Median</th><th style="{_TH}">Best</th><th style="{_TH}">Worst</th>')
    _TD = f"border:1px solid {BORDER_COLOR};padding:3px 8px;font-size:10.5px;white-space:nowrap;text-align:right"
    _TD0 = _TD.replace("text-align:right", "text-align:left")
    body = ""
    for key, n, winp, avg, med, best, worst in rows:
        body += (
            f'<tr>'
            f'<td style="{_TD0};color:{TEXT_PRIMARY};font-weight:700">{key}</td>'
            f'<td style="{_TD};color:{TEXT_MUTED}">{n}</td>'
            f'<td style="{_TD};color:{col_g(winp-50)}">{winp:.0f}%</td>'
            f'<td style="{_TD};color:{col_g(avg)};font-weight:700">{avg:+.1f}%</td>'
            f'<td style="{_TD};color:{col_g(med)}">{med:+.1f}%</td>'
            f'<td style="{_TD};color:{ACCENT_GREEN}">{best:+.1f}%</td>'
            f'<td style="{_TD};color:{ACCENT_RED}">{worst:+.1f}%</td>'
            f'</tr>')
    return (f'<div style="overflow-x:auto;margin:6px 0 14px">'
            f'<table style="border-collapse:collapse;font-family:Inter,sans-serif;min-width:100%">'
            f'<thead><tr>{hdr}</tr></thead><tbody>{body}</tbody></table></div>')


def _render_performance(df: pd.DataFrame) -> None:
    """A scorecard of what's working, computed from ALL tickers in state (not the
    filtered view). Uses each ticker's return since its signal fired."""
    priced = df[pd.to_numeric(df["Gain %"], errors="coerce").notna()]
    n_priced = len(priced)
    with st.expander(f"📊 Performance — what's working ({n_priced} signal(s) with an entry price)",
                     expanded=False):
        if n_priced == 0:
            st.info("No returns to score yet — a signal contributes here once it has both an "
                    "entry price (the alert's “at X”) and a live current price. In this "
                    "environment price feeds may be blocked; the live app will populate it.")
            return
        g = pd.to_numeric(priced["Gain %"], errors="coerce")
        overall_win = (g > 0).mean() * 100
        st.markdown(
            f"<div style='font-size:12.5px;color:{TEXT_MUTED};margin-bottom:6px'>"
            f"Across <b>{n_priced}</b> signal(s) with an entry: overall win rate "
            f"<b style='color:{ACCENT_GREEN if overall_win>=50 else ACCENT_RED}'>{overall_win:.0f}%</b>, "
            f"average return <b style='color:{ACCENT_GREEN if g.mean()>=0 else ACCENT_RED}'>{g.mean():+.1f}%</b> "
            f"(median {g.median():+.1f}%). “Return” = current price vs the price the alert fired at — "
            f"a rough scorecard, not a backtest.</div>", unsafe_allow_html=True)
        for title, col in [("By Rule-Based Verdict", "Rule-Based Verdict"),
                           ("By Monthly status", "🗓️M Status"),
                           ("By Weekly status", "🗓️W Status"),
                           ("By Blue Wave (weekly)", "Blue Wave"),
                           ("By price vs 200-wk mean", "Mean Pos"),
                           ("By Technical Verdict", "Technical Verdict")]:
            html = _perf_html(title, _perf_group(df, col))
            if html:
                st.markdown(html, unsafe_allow_html=True)
        st.caption("Buckets are sorted by average return. Small samples swing hard — read N "
                   "alongside the average, and give a bucket a few names before trusting it.")


def _parse_tab(tf_label: str, tf_key: str, core_crypto: set):
    """One input tab (Monthly/Weekly/Daily)."""
    sig_date = st.date_input("Signal date", value=date.today(), key=f"ldd_date_{tf_key}",
                             help="The date the signal applies to (defaults to today).")
    txt = st.text_area(f"Paste the {tf_label} alerts", height=180, key=f"ldd_txt_{tf_key}",
                       placeholder="LULU 🟢 is CONFIRMED on the MONTHLY chart at 120.27! …")
    c1, c2 = st.columns([1, 3])
    with c1:
        go = st.button("Parse & save", type="primary", key=f"ldd_go_{tf_key}",
                       use_container_width=True)
    if not go:
        return
    if not txt.strip():
        st.warning("Nothing pasted.")
        return
    kept, filtered = parse_batch(txt, tf_key, core_crypto)
    # The fair-price / "crossing the blue line" alert lives in the weekly
    # section, so the same paste can carry both kinds. Parse it here too and
    # write the independent 'fair' slot.
    fair_kept, fair_filtered = parse_fair_batch(txt, core_crypto)
    if not kept and not filtered and not fair_kept:
        st.warning("No signal lines recognized in that paste.")
        return

    sd = sig_date.strftime("%Y-%m-%d")
    parsed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state, status = load_state()
    if status == "read_error":
        # Never merge onto a state we failed to read — saving it would overwrite
        # every existing ticker in the sheet with just this one batch.
        st.error("Couldn't read the current LDD state from Google Sheets, so this "
                 "paste was NOT saved — saving now would overwrite your existing data "
                 "with only this batch. Retry in a moment (Reload below), then paste "
                 "again. Your saved data is safe in the sheet.")
        return
    state = apply_batch_to_state(state, kept, sd)
    if fair_kept:
        state = apply_fair_to_state(state, fair_kept, sd)
    ok, msg = save_state(state)
    append_raw(kept, sd, parsed_at)
    if fair_kept:
        append_raw([{**it, "timeframe": "fair", "status": "crossing"} for it in fair_kept],
                   sd, parsed_at)
    load_state.clear()   # bust the 2-min cache so the table reflects this paste

    if ok:
        parts = []
        if kept:
            parts.append(f"{len(kept)} {tf_label.lower()} signal(s)")
        if fair_kept:
            parts.append(f"{len(fair_kept)} fair-price alert(s)")
        st.success(f"Saved {' + '.join(parts) or '0 signals'} for {sd}. "
                   f"Only the affected slots were updated for these tickers.")
        for it in kept + fair_kept:
            tech_snapshot(it["ticker"])   # warm technicals for newly-seen tickers
    else:
        st.error(msg)
    all_filtered = filtered + fair_filtered
    if all_filtered:
        with st.expander(f"Filtered out {len(all_filtered)} composite/off-list crypto ticker(s)"):
            st.write(", ".join(f'{it["ticker"]} ({it["type"]})' for it in all_filtered))


def render():
    section_header("🧭", "LDD Signal Dashboard",
                   "Discord LDD alerts → durable state → rule-based vs technical verdicts")

    if not _sheets_ready():
        st.warning("Google Sheets is not connected, so saves won't persist. Add "
                   "`[gsheets]` service-account credentials in Streamlit Secrets to "
                   "enable durable storage. You can still parse a paste to preview it below.")

    # ── Settings ──────────────────────────────────────────────────────────────
    with st.expander("⚙️ Settings", expanded=False):
        cc_raw = st.text_input(
            "Core-crypto allow-list (only these crypto bases are kept)",
            value=", ".join(sorted(DEFAULT_CORE_CRYPTO)), key="ldd_core_crypto")
        fair_band = st.slider(
            "“At the mean” band (± % of the 200-week fair price)",
            1.0, 15.0, _FAIR_BAND_PCT_DEFAULT, 0.5, key="ldd_fair_band",
            help="How close price must sit to the 200-week SMA (the blue 4-yr "
                 "MA / “fair price / mean”) to count as “at the mean” — the "
                 "fair-value buy zone. A fresh weekly cross of the line always "
                 "counts regardless of this band.")
        st.caption("**Fair price / mean** = the 200-week SMA (the blue 4-year MA). Price "
                   "within the band above — or a fresh weekly cross of it — reads as **at the "
                   "mean** (a fair-value buy). This feeds the Rule-Based Verdict as a weekly "
                   "buy condition, and a pasted “crossing the blue line” alert sets it "
                   "explicitly.")
        st.caption(f"Buy Strategy #2 uses the WaveTrend **blue wave** below the "
                   f"**white line** (oversold ≤ {_WT_OS}) on the weekly — a recreation of the "
                   "same WaveTrend engine as the OverKill dots. The red/green confirmation "
                   "dots come from your pasted alerts, not from here.")
        if st.button("🔄 Refresh technicals (clear 4h cache)", key="ldd_refresh_tech"):
            tech_snapshot.clear()
            st.success("Technical cache cleared — will re-pull on next render.")
    core_crypto = {t.strip().upper() for t in cc_raw.split(",") if t.strip()}

    # ── Input tabs ────────────────────────────────────────────────────────────
    st.markdown("#### Paste alerts")
    tM, tW, tD = st.tabs(["🗓️ Monthly", "🗓️ Weekly", "🗓️ Daily"])
    with tM:
        _parse_tab("Monthly", "monthly", core_crypto)
    with tW:
        st.caption("Weekly CONFIRMED/showing alerts **and** the new “price crossing the blue "
                   "line (200-week / fair-price / mean)” alerts can go in the same paste — "
                   "fair-price lines are routed to their own slot automatically.")
        _parse_tab("Weekly", "weekly", core_crypto)
    with tD:
        st.caption("No daily-format example exists yet — the parser is format-agnostic, "
                   "so daily pastes save into the daily slot the same way once they arrive.")
        _parse_tab("Daily", "daily", core_crypto)

    # ── Results ───────────────────────────────────────────────────────────────
    st.markdown("#### Signals")
    state, status = load_state()

    def _reload_btn(key):
        if st.button("🔄 Reload from Google Sheets", key=key,
                     help="Clear the 2-minute cache and re-read LDD_State from the sheet."):
            load_state.clear()
            st.rerun()

    if status == "not_connected":
        st.error("Google Sheets isn't connected, so there's nothing to read. Add the "
                 "`[gsheets]` service-account credentials in Streamlit **Secrets**. Any "
                 "data you saved earlier is safe in the sheet and returns once the "
                 "connection is restored.")
        return
    if status == "read_error":
        st.warning("Couldn't read **LDD_State** from Google Sheets just now — a transient "
                   "API error, a quota limit, or a change to the sheet's sharing/permissions. "
                   "**Your saved data is not lost** — it's still in the sheet; the app just "
                   "couldn't fetch it this moment. Reload to retry.")
        _reload_btn("ldd_reload_err")
        return
    if not state:   # status == "empty" — connected, but A1 really is blank
        st.info("No tickers yet — paste a batch above. The universe is closed: only "
                "tickers that have actually been pasted ever appear here. (If you've "
                "pasted before, the sheet's `LDD_State!A1` is empty — reload in case a "
                "read was cached empty, and re-paste if it's genuinely blank.)")
        _reload_btn("ldd_reload_empty")
        return

    with st.spinner("Pulling technicals…"):
        df = _build_table(state, fair_band)
    if df.empty:
        st.info("No rows to show.")
        return

    # Performance scorecard — computed from ALL history, before the display
    # filters, so it answers "what's working" across everything pasted.
    _render_performance(df)

    # Recency window — default to the last 4 weeks of signals; pull older on demand.
    rc1, rc2, _ = st.columns([1, 1, 3])
    with rc1:
        weeks = st.number_input("Show last N weeks", min_value=1, max_value=520, value=4, step=1,
                                key="ldd_weeks",
                                help="Keeps only tickers whose most-recent signal is within this many "
                                     "weeks. Raise it (or tick 'All history') to pull older signals.")
    with rc2:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        show_all = st.checkbox("All history", value=False, key="ldd_all_hist")

    # Filters (defaults: Monthly Confirmed · Technical Lean Buy · RSI D 30–70)
    fc1, fc2, fc3 = st.columns([1.2, 1.2, 1.4])
    with fc1:
        search = st.text_input("Ticker search", key="ldd_search").strip().upper()
        m_f = st.multiselect("Monthly status", ["Confirmed", "Showing", "—"],
                             default=["Confirmed"], key="ldd_mf")
        w_f = st.multiselect("Weekly status", ["Confirmed", "Showing", "—"], key="ldd_wf")
        d_f = st.multiselect("Daily status", ["Confirmed", "Showing", "—"], key="ldd_df")
    with fc2:
        rb_opts = sorted(df["Rule-Based Verdict"].unique())
        tv_opts = sorted(df["Technical Verdict"].unique())
        rb_f = st.multiselect("Rule-Based Verdict", rb_opts, key="ldd_rbf")
        tv_f = st.multiselect("Technical Verdict", tv_opts, key="ldd_tvf",
                              default=[o for o in ["Lean Buy"] if o in tv_opts])
        disagree = st.toggle("Only where Rules & Technicals disagree", key="ldd_disagree",
                             help="Rule-Based leans buy/watch while Technical leans the "
                                  "other way — the cases worth a second look.")
        only_fair = st.toggle("Only at/near the 200-wk mean (fair)", key="ldd_fairfilter",
                              help="Price within the “at the mean” band of its 200-week fair "
                                   "price, or freshly crossed the blue line this week.")
    with fc3:
        rsi_d_lo, rsi_d_hi = st.slider("RSI D range", 0, 100, (30, 70), key="ldd_rsid")
        sort_col = st.selectbox("Sort by", ["Ticker", "Gain %", "RSI D", "RSI W",
                                            "vs Mean %", "Rule-Based Verdict", "Technical Verdict"],
                                key="ldd_sort")
        asc = st.selectbox("Order", ["Ascending", "Descending"], index=1, key="ldd_order") == "Ascending"

    view = df.copy()
    # Recency filter first (by each ticker's most-recent signal date).
    if not show_all and "_recent" in view.columns:
        cutoff = (date.today() - timedelta(weeks=int(weeks))).strftime("%Y-%m-%d")
        view = view[view["_recent"].fillna("") >= cutoff]
    if search:
        view = view[view["Ticker"].str.contains(search, na=False)]
    for col, sel in [("🗓️M Status", m_f), ("🗓️W Status", w_f), ("🗓️D Status", d_f)]:
        if sel:
            view = view[view[col].isin(sel)]
    if rb_f:
        view = view[view["Rule-Based Verdict"].isin(rb_f)]
    if tv_f:
        view = view[view["Technical Verdict"].isin(tv_f)]

    def _rule_dir(s):
        return 1 if (s.startswith("Buy") or s.startswith("Strong Buy")) else -1 if s.startswith("Sell") else 0
    if disagree:
        rd = view["Rule-Based Verdict"].map(_rule_dir)
        td = view["Technical Verdict"].map({"Lean Buy": 1, "Lean Sell": -1, "Mixed": 0, "No Data": 0})
        view = view[(rd != 0) & (td != 0) & (rd != td)]
    if only_fair:
        vm = view["vs Mean"].astype(str)
        view = view[vm.str.startswith("At mean") | vm.str.contains("crossed")]

    # Numeric range filters — a missing (un-fetched) value always passes, so a
    # failed technical pull never silently hides a ticker.
    for col, lo, hi in [("RSI D", rsi_d_lo, rsi_d_hi)]:
        vals = pd.to_numeric(view[col], errors="coerce")
        view = view[(vals.between(lo, hi)) | (vals.isna())]

    view = view.sort_values(sort_col, ascending=asc, na_position="last")

    st.caption(f"{len(view)} of {len(df)} tickers · two independent verdicts — "
               "they can and will disagree, and that disagreement is signal, not noise.")
    st.markdown(_html_table(view), unsafe_allow_html=True)

    st.markdown(
        f'<div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:6px;'
        f'padding:10px 14px;margin-top:10px;color:{TEXT_MUTED};font-size:12px">'
        "💡 <b>Rule-Based Verdict</b> = Andy's literal LDD rules. <b>Buy Strategy #2</b> uses "
        f"the WaveTrend <b>blue wave</b> below the <b>white line</b> (oversold ≤ {_WT_OS}) on the "
        "weekly — a recreation of the same engine as the OverKill dots, so no “proxy” caveat. "
        "<b>Technical Verdict</b> is an independent indicator tally and is never adjusted "
        "to agree with the rules.</div>",
        unsafe_allow_html=True,
    )

    with st.expander("ℹ️ What each verdict means"):
        st.markdown(
            "**Rule-Based Verdict** — Andy's literal LDD rules "
            "(Buy #1 = Monthly; Buy #2 = Weekly + blue wave below the white line; "
            "Daily = buy as long as Monthly is green **or** price is above the EMA ribbon):\n\n"
            "*(“Month”/“Week” are Monthly/Weekly; the trigger — Blue Wave below vs at Mean — is "
            "named in the label and also shown in the Blue Wave (W) and vs Mean columns.)*\n\n"
            "- **Strong Buy — Month+Week+Blue Wave below** — both buy strategies fire: Monthly "
            "CONFIRMED **and** Weekly CONFIRMED **and** the WaveTrend blue wave is below the "
            f"white line (≤ {_WT_OS}, oversold). The highest-conviction combo.\n"
            "- **Strong Buy — Month+Week+at Mean** — same, but the weekly trigger is price "
            "at/near the 200-week mean (fair price) rather than the blue wave.\n"
            "- **Buy — Monthly** — Monthly chart CONFIRMED (Buy Strategy #1, the strongest "
            "single standing signal). Look for a trade.\n"
            "- **Buy — Week+Blue Wave below** — Buy Strategy #2: Weekly CONFIRMED **and** the "
            f"blue wave (WT1) is below the white line (≤ {_WT_OS}, oversold).\n"
            "- **Buy — Week+at Mean** — Buy Strategy #2's other trigger: Weekly CONFIRMED "
            "**and** price is at/near the 200-week fair-price line (blue 4-yr MA).\n"
            "- **Buy — at Mean** — price is at/near the 200-week mean (or freshly crossed the "
            "blue line), with no Monthly/Weekly confirm on record yet. The standalone weekly "
            "fair-price alert.\n"
            "- **Weekly — waiting (for Blue Wave below / at Mean)** — Weekly CONFIRMED, but "
            "neither the blue wave is below the white line **nor** is price at the 200-week mean "
            "yet, so Buy #2 hasn't fired. A watch, not a buy.\n"
            "- **Buy — Daily (Month green / EMA ribbon)** — a Daily CONFIRMED with its context "
            "met (Monthly is green, or price is trending above the EMA ribbon).\n"
            "- **Daily — waiting (for Month green / EMA ribbon)** — a Daily CONFIRMED but "
            "neither context condition holds yet.\n"
            "- **Watch — no signal** — no Monthly/Weekly/Daily confirm on record. (Sell "
            "strategies stay inert until a real daily-🔴/weekly-sell example format is pasted.)\n\n"
            "**vs Mean (Fair price)** — price against the **200-week SMA** (the blue 4-yr MA "
            "Andy calls the *fair price / mean*): **At mean** (within the Settings band — the "
            "fair-value buy zone), **Below mean** (cheap), or **Above mean** (rich). "
            "**⤢ crossed** flags a fresh weekly cross of the line, and **· alert** marks a "
            "ticker whose “crossing the blue line” alert you actually pasted. Tickers with "
            "under ~4 years of history show **—** (no 200-week value yet).\n\n"
            "**Reading the trend columns** (three different lenses, fast → slow, so they can "
            "disagree in a pullback):\n"
            "- **Trend 20>50** — daily **EMA20 vs EMA50** (the *fast* near-term trend, days-to-"
            "weeks). ✅ = 20 above 50.\n"
            "- **Cloud 34/50** — daily **EMA34/EMA50 cloud** vs price (a *medium* trend "
            "confirmation).\n"
            "- **Regime 50/200** — **SMA50 vs SMA200** = the *slow* long-term regime (months). "
            "**Golden** = 50 above 200, **Death** = 50 below 200. So *Trend 20>50* can be ✅ "
            "while *Regime* is still Death (a bounce inside a long downtrend), or vice-versa — "
            "that spread is the point of showing both.\n"
            "- **Blue Wave (W)** — where the weekly WaveTrend blue wave sits: **Below white** "
            f"(WT1 ≤ {_WT_OS}, the oversold buy zone), **Above white** (WT1 ≥ {_WT_OB}, "
            "overbought), or **Mid** (between the two white lines — neither zone, neutral for "
            "Buy #2).\n\n"
            "**Technical Verdict** — an independent tally of the computed indicators (RSI "
            "direction, MACD sign & fresh cross, EMA20 vs 50, Golden/Death, EMA cloud, "
            "ADX-confirmed trend), scored +1/−1 each:\n\n"
            "- **Lean Buy** — net score **≥ +3** (indicators broadly bullish).\n"
            "- **Lean Sell** — net score **≤ −3** (broadly bearish).\n"
            "- **Mixed** — net between −2 and +2, no clear lean.\n"
            "- **No Data** — technicals couldn't be fetched for this ticker.\n\n"
            "The two columns are **never reconciled** — when the rules say buy and the "
            "technicals lean sell (or vice-versa), that disagreement is the signal worth a "
            "second look (use the *“Rules & Technicals disagree”* filter)."
        )
