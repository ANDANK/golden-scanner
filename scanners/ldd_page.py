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
from datetime import datetime, date, timezone

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
def load_state() -> dict:
    """Running latest_state, read from LDD_State!A1. Cached 2 min so the table
    doesn't re-hit Sheets on every widget interaction; cleared after a save."""
    if not _sheets_ready():
        return {}
    try:
        from scanners.gsheet_helper import _gs_sheet
        raw = _gs_sheet(_STATE_TAB).acell("A1").value
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


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
        df = get_price_history(ticker, period="2y")
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
        ))
        return out
    except Exception:
        return out


# ════════════════════════════════════════════════════════════════════════════
# RULE-BASED VERDICT  (§5 — Andy's literal rules; deterministic & inspectable)
#   Any verdict leaning on a proprietary/approximated part of the paid
#   indicator (StochRSI blue-wave/white-line, red/green "zones") says so INLINE
#   in the string, never only in a tooltip.
# ════════════════════════════════════════════════════════════════════════════
_PROXY = " — proxy, verify on your indicator"


def rule_based_verdict(slot: dict, tech: dict, white_line_k: float = 20.0) -> str:
    slot = slot or {"monthly": None, "weekly": None, "daily": None}
    m, w = slot.get("monthly"), slot.get("weekly")
    tech = tech or {}

    # Buy Strategy #1 — Monthly confirmed is the strongest standing signal.
    if m and m.get("status") == "confirmed":
        if tech.get("ema_cloud") == "bullish":
            # Andy's "any other format supports → almost a buy" confluence note.
            return "Buy — Monthly Confirm + EMA-Cloud confluence" + _PROXY
        return "Buy Candidate — Monthly Confirm"

    # Buy Strategy #2 — Weekly confirmed AND StochRSI below the white line.
    # The blue-wave/white-line is proprietary; StochRSI %K < threshold is a proxy.
    if w and w.get("status") == "confirmed":
        k = tech.get("stoch_k")
        if k is not None and k < white_line_k:
            return "Buy Candidate — Weekly Confirm + StochRSI oversold" + _PROXY
        return "Weekly Confirm — awaiting StochRSI trigger" + _PROXY

    # Sell Strategies #1/#2 depend on a daily 🔴 "red zone" / weekly sell format
    # that has no example yet — intentionally not fired until one is seen (§5).
    return "No Rule Signal — Watch"


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


def _build_table(state: dict, white_line_k: float) -> pd.DataFrame:
    rows = []
    for tk in sorted(state.keys()):
        slot = state[tk]
        tech = tech_snapshot(tk)
        rb = rule_based_verdict(slot, tech, white_line_k)
        tv, tnet, _ = technical_verdict(tech)
        m_s, m_p, m_d = _slot_txt(slot.get("monthly"))
        w_s, w_p, w_d = _slot_txt(slot.get("weekly"))
        d_s, d_p, d_d = _slot_txt(slot.get("daily"))
        rows.append({
            "Ticker": tk,
            "🗓️M Status": m_s, "M Price": m_p, "M Date": m_d,
            "🗓️W Status": w_s, "W Price": w_p, "W Date": w_d,
            "🗓️D Status": d_s, "D Price": d_p, "D Date": d_d,
            "Price": tech.get("price"),
            "RSI D": tech.get("rsi_d"), "RSI W": tech.get("rsi_w"),
            "MACD D": f'{tech.get("macd_d_zone","")}{" ⚡"+tech["macd_d_cross"] if tech.get("macd_d_cross") else ""}',
            "MACD W": f'{tech.get("macd_w_zone","")}{" ⚡"+tech["macd_w_cross"] if tech.get("macd_w_cross") else ""}',
            "EMA20>50": "✅" if tech.get("ema20_gt_50") else "—",
            "G/D Cross": {"golden": "🟡 Golden", "death": "🔴 Death", "above": "50>200",
                          "below": "50<200"}.get(tech.get("gd_cross"), "—"),
            "Ext vs EMA20": tech.get("ext_ema20"),
            "EMA Cloud": tech.get("ema_cloud", "—"),
            "ADX": tech.get("adx"), "ADX Zone": tech.get("adx_zone", "—"),
            "StochRSI %K": tech.get("stoch_k"),
            "Rule-Based Verdict": rb,
            "Technical Verdict": tv,
            "_tnet": tnet,
        })
    return pd.DataFrame(rows)


# Column spec: (display label, group key, format kind). Groups get colored,
# spanned sub-headers so Monthly/Weekly/Daily stay scannable (spec point 5).
_PURPLE = "#9C27B0"
_GROUPS = {"ID": ("", TEXT_MUTED), "M": ("Monthly", ACCENT_BLUE), "W": ("Weekly", ACCENT_GREEN),
           "D": ("Daily", _PURPLE), "T": ("Technicals", TEXT_MUTED), "V": ("Verdicts", GOLD)}
_COLS = [
    ("Ticker", "ID", "tk"),
    ("Status", "M", "stat"), ("Price", "M", "raw"), ("Signal", "M", "raw"),
    ("Status", "W", "stat"), ("Price", "W", "raw"), ("Signal", "W", "raw"),
    ("Status", "D", "stat"), ("Price", "D", "raw"), ("Signal", "D", "raw"),
    ("Price", "T", "usd"), ("RSI D", "T", "num"), ("RSI W", "T", "num"),
    ("MACD D", "T", "raw"), ("MACD W", "T", "raw"), ("EMA20>50", "T", "raw"),
    ("G/D", "T", "raw"), ("Ext%", "T", "pct"), ("Cloud", "T", "raw"),
    ("ADX", "T", "num"), ("ADX Zone", "T", "raw"), ("StRSI %K", "T", "num"),
    ("Rule-Based Verdict", "V", "rb"), ("Technical Verdict", "V", "tv"),
]
# maps each (label, group) to the source column in the built DataFrame
_SRC = {
    ("Ticker", "ID"): "Ticker",
    ("Status", "M"): "🗓️M Status", ("Price", "M"): "M Price", ("Signal", "M"): "M Date",
    ("Status", "W"): "🗓️W Status", ("Price", "W"): "W Price", ("Signal", "W"): "W Date",
    ("Status", "D"): "🗓️D Status", ("Price", "D"): "D Price", ("Signal", "D"): "D Date",
    ("Price", "T"): "Price", ("RSI D", "T"): "RSI D", ("RSI W", "T"): "RSI W",
    ("MACD D", "T"): "MACD D", ("MACD W", "T"): "MACD W", ("EMA20>50", "T"): "EMA20>50",
    ("G/D", "T"): "G/D Cross", ("Ext%", "T"): "Ext vs EMA20", ("Cloud", "T"): "EMA Cloud",
    ("ADX", "T"): "ADX", ("ADX Zone", "T"): "ADX Zone", ("StRSI %K", "T"): "StochRSI %K",
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
        if kind == "pct":
            try: return f"{float(v):+.1f}%"
            except (TypeError, ValueError): return "—"
        if kind == "num":
            try: return f"{float(v):.1f}"
            except (TypeError, ValueError): return str(v)
        return str(v)

    def cell_color(v, kind):
        if kind == "stat":
            s = str(v).lower()
            return ACCENT_GREEN if s.startswith("confirm") else GOLD if s.startswith("show") else TEXT_MUTED
        if kind == "rb":
            s = str(v)
            return (ACCENT_GREEN if s.startswith("Buy") else ACCENT_RED if s.startswith("Sell")
                    else GOLD if s.startswith("Weekly Confirm") else TEXT_MUTED)
        if kind == "tv":
            return {"Lean Buy": ACCENT_GREEN, "Lean Sell": ACCENT_RED, "Mixed": GOLD}.get(str(v), TEXT_MUTED)
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
    for _, r in view.iterrows():
        tds = ""
        for lbl, g, kind in _COLS:
            v = r.get(_SRC[(lbl, g)])
            txt = fmt(v, kind)
            col = cell_color(v, kind)
            weight = "700" if (kind in ("tk", "rb", "tv") or (kind == "stat" and txt != "—")) else "400"
            tds += f'<td style="{_TD};color:{col};font-weight:{weight}">{txt}</td>'
        body += f"<tr>{tds}</tr>"

    return (f'<div style="overflow-x:auto;border:1px solid {BORDER_COLOR};border-radius:8px">'
            f'<table style="border-collapse:collapse;font-family:Inter,sans-serif;min-width:100%">'
            f'<thead><tr>{grp_hdr}</tr><tr>{col_hdr}</tr></thead>'
            f'<tbody>{body}</tbody></table></div>')


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
    if not kept and not filtered:
        st.warning("No signal lines recognized in that paste.")
        return

    sd = sig_date.strftime("%Y-%m-%d")
    parsed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state = load_state()
    state = apply_batch_to_state(state, kept, sd)
    ok, msg = save_state(state)
    append_raw(kept, sd, parsed_at)
    load_state.clear()   # bust the 2-min cache so the table reflects this paste

    if ok:
        st.success(f"Saved {len(kept)} {tf_label} signal(s) for {sd}. "
                   f"Only the {tf_label.lower()} slot was updated for these tickers.")
        for it in kept:
            tech_snapshot(it["ticker"])   # warm technicals for newly-seen tickers
    else:
        st.error(msg)
    if filtered:
        with st.expander(f"Filtered out {len(filtered)} composite/off-list crypto ticker(s)"):
            st.write(", ".join(f'{it["ticker"]} ({it["type"]})' for it in filtered))


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
        white_line_k = st.slider(
            "StochRSI 'white line' %K threshold (Buy #2 trigger — proxy)",
            0, 50, 20, key="ldd_white_k",
            help="Proxy for the paid indicator's blue-wave/white-line: Weekly Confirm "
                 "counts as a buy candidate only when StochRSI %K is below this.")
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
        _parse_tab("Weekly", "weekly", core_crypto)
    with tD:
        st.caption("No daily-format example exists yet — the parser is format-agnostic, "
                   "so daily pastes save into the daily slot the same way once they arrive.")
        _parse_tab("Daily", "daily", core_crypto)

    # ── Results ───────────────────────────────────────────────────────────────
    st.markdown("#### Signals")
    state = load_state()
    if not state:
        st.info("No tickers yet — paste a batch above. The universe is closed: only "
                "tickers that have actually been pasted ever appear here.")
        return

    with st.spinner("Pulling technicals…"):
        df = _build_table(state, white_line_k)
    if df.empty:
        st.info("No rows to show.")
        return

    # Filters
    fc1, fc2, fc3 = st.columns([1.2, 1.2, 1.4])
    with fc1:
        search = st.text_input("Ticker search", key="ldd_search").strip().upper()
        m_f = st.multiselect("Monthly status", ["Confirmed", "Showing", "—"], key="ldd_mf")
        w_f = st.multiselect("Weekly status", ["Confirmed", "Showing", "—"], key="ldd_wf")
        d_f = st.multiselect("Daily status", ["Confirmed", "Showing", "—"], key="ldd_df")
    with fc2:
        rb_opts = sorted(df["Rule-Based Verdict"].unique())
        tv_opts = sorted(df["Technical Verdict"].unique())
        rb_f = st.multiselect("Rule-Based Verdict", rb_opts, key="ldd_rbf")
        tv_f = st.multiselect("Technical Verdict", tv_opts, key="ldd_tvf")
        disagree = st.toggle("Only where Rules & Technicals disagree", key="ldd_disagree",
                             help="Rule-Based leans buy/watch while Technical leans the "
                                  "other way — the cases worth a second look.")
    with fc3:
        rsi_d_lo, rsi_d_hi = st.slider("RSI D range", 0, 100, (0, 100), key="ldd_rsid")
        rsi_w_lo, rsi_w_hi = st.slider("RSI W range", 0, 100, (0, 100), key="ldd_rsiw")
        adx_lo, adx_hi = st.slider("ADX range", 0, 100, (0, 100), key="ldd_adx")
        sort_col = st.selectbox("Sort by", ["Ticker", "RSI D", "RSI W", "ADX",
                                            "Rule-Based Verdict", "Technical Verdict"],
                                key="ldd_sort")
        asc = st.selectbox("Order", ["Ascending", "Descending"], index=1, key="ldd_order") == "Ascending"

    view = df.copy()
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
        return 1 if s.startswith("Buy") else -1 if s.startswith("Sell") else 0
    if disagree:
        rd = view["Rule-Based Verdict"].map(_rule_dir)
        td = view["Technical Verdict"].map({"Lean Buy": 1, "Lean Sell": -1, "Mixed": 0, "No Data": 0})
        view = view[(rd != 0) & (td != 0) & (rd != td)]

    for col, lo, hi in [("RSI D", rsi_d_lo, rsi_d_hi), ("RSI W", rsi_w_lo, rsi_w_hi),
                        ("ADX", adx_lo, adx_hi)]:
        vals = pd.to_numeric(view[col], errors="coerce")
        # keep NaNs only when the full range is selected (don't hide un-fetched rows by accident)
        full = (lo == 0 and hi == 100)
        view = view[(vals.between(lo, hi)) | (full & vals.isna())]

    view = view.sort_values(sort_col, ascending=asc, na_position="last")

    st.caption(f"{len(view)} of {len(df)} tickers · two independent verdicts — "
               "they can and will disagree, and that disagreement is signal, not noise.")
    st.markdown(_html_table(view), unsafe_allow_html=True)

    st.markdown(
        f'<div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:6px;'
        f'padding:10px 14px;margin-top:10px;color:{TEXT_MUTED};font-size:12px">'
        "💡 <b>Rule-Based Verdict</b> = Andy's literal rules (Monthly/Weekly confirms). "
        "Verdicts marked <i>“— proxy, verify on your indicator”</i> lean on the paid "
        "indicator's proprietary StochRSI/zone elements approximated from price. "
        "<b>Technical Verdict</b> is an independent indicator tally and is never adjusted "
        "to agree with the rules.</div>",
        unsafe_allow_html=True,
    )
