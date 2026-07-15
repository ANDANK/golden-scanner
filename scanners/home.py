# scanners/home.py — Market Overview: the one-page command center
#
# Layout:
#   ┌─────────────────────────────────────────────────────────┐
#   │ REGIME BAR — Risk-On/Mixed/Risk-Off · indices · breadth │
#   ├────────────────────────────┬────────────────────────────┤
#   │ 🏆 Top-20 Conviction Picks │ 📰 News (picks + market)   │
#   ├────────────────────────────┼────────────────────────────┤
#   │ ⚡ Trade Today · 🔥 High IV │ 🔄 Sector Rotation (RRG)   │
#   └────────────────────────────┴────────────────────────────┘
#
# Design rules:
#   - NEVER run a scanner on page load. The Top-20 reads the latest
#     twice-daily Golden Scan JSON committed to data/ (instant).
#   - Live work is limited to cached, batched fetches (quotes, news, sectors).
#   - Every section is fail-safe: one broken feed never bricks the page.

from __future__ import annotations
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import json, glob, os, re, sys
from datetime import datetime, timezone
import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import *
from utils import section_header, calc_sma, calc_ema, calc_rsi
from data_loader import get_price_history, get_market_overview

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_GH_RAW_BASE = "https://raw.githubusercontent.com/ANDANK/golden-scanner/main/data"

ORANGE = "#F97316"
PURPLE = "#A78BFA"
MINT   = "#34D399"


# ══════════════════════════════════════════════════════════════════════════════
# SMALL HTML HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{alpha})"


def _chip(text: str, color: str, bg_alpha: float = 0.12) -> str:
    return (f'<span style="background:{_rgba(color, bg_alpha)};color:{color};'
            f'border:1px solid {color}44;font-size:10px;font-weight:700;'
            f'padding:2px 9px;border-radius:12px;white-space:nowrap">{text}</span>')


def _card(title: str, icon: str, color: str, body_html: str,
          subtitle: str = "", max_height: int = 0) -> str:
    """Colorful quadrant card with gradient header and optional scroll body."""
    scroll = (f"max-height:{max_height}px;overflow-y:auto;" if max_height else "")
    return (
        f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};'
        f'border-radius:14px;overflow:hidden;margin-bottom:14px">'
        f'<div style="background:linear-gradient(90deg,{_rgba(color,0.22)},{_rgba(color,0.04)});'
        f'border-bottom:2px solid {color}55;padding:10px 16px;'
        f'display:flex;align-items:baseline;gap:10px">'
        f'<span style="font-size:16px">{icon}</span>'
        f'<span style="color:{color};font-size:13px;font-weight:800;'
        f'letter-spacing:0.6px;text-transform:uppercase">{title}</span>'
        + (f'<span style="color:{TEXT_MUTED};font-size:10px;margin-left:auto">{subtitle}</span>'
           if subtitle else '')
        + f'</div>'
        f'<div style="padding:10px 12px;{scroll}">{body_html}</div>'
        f'</div>'
    )


_TD = "padding:6px 8px;border-bottom:1px solid #2A2A3A33;vertical-align:middle"
_TH = (f"color:{TEXT_MUTED};font-size:9px;font-weight:700;text-transform:uppercase;"
       f"letter-spacing:0.6px;padding:4px 8px;text-align:left;white-space:nowrap;"
       f"border-bottom:1px solid #2A2A3A66")


def _mono(v: str, color: str = TEXT_PRIMARY, size: int = 12, bold: bool = False) -> str:
    w = "700" if bold else "500"
    return (f'<span style="color:{color};font-family:\'DM Mono\',monospace;'
            f'font-size:{size}px;font-weight:{w}">{v}</span>')


def _chg_html(chg: float) -> str:
    col = ACCENT_GREEN if chg >= 0 else ACCENT_RED
    return _mono(f"{chg:+.1f}%", col, 11)


# ══════════════════════════════════════════════════════════════════════════════
# A. MARKET REGIME
# ══════════════════════════════════════════════════════════════════════════════

_SECTOR_ETFS = ["XLK","XLF","XLV","XLI","XLE","XLY","XLP","XLC","XLB","XLRE","XLU"]


@st.cache_data(ttl=1800, show_spinner=False)
def _regime_data() -> dict:
    """SPY/QQQ trend, VIX, and sector breadth. Cached 30 min."""
    out = {"ok": False}
    try:
        spy = get_price_history("SPY", period="1y")["Close"].squeeze()
        qqq = get_price_history("QQQ", period="1y")["Close"].squeeze()
        out["spy_v200"] = (float(spy.iloc[-1]) / float(calc_sma(spy, 200).iloc[-1]) - 1) * 100
        out["qqq_v200"] = (float(qqq.iloc[-1]) / float(calc_sma(qqq, 200).iloc[-1]) - 1) * 100
        out["spy_chg"]  = (float(spy.iloc[-1]) / float(spy.iloc[-2]) - 1) * 100
        out["qqq_chg"]  = (float(qqq.iloc[-1]) / float(qqq.iloc[-2]) - 1) * 100
        out["ok"] = True
    except Exception:
        return out
    try:
        vix = get_price_history("^VIX", period="3mo")["Close"].squeeze()
        out["vix"] = float(vix.iloc[-1])
    except Exception:
        out["vix"] = 20.0
    # Breadth: % of the 11 sector ETFs above their SMA50
    above = total = 0
    for t in _SECTOR_ETFS:
        try:
            c = get_price_history(t, period="1y")["Close"].squeeze()
            total += 1
            if float(c.iloc[-1]) > float(calc_sma(c, 50).iloc[-1]):
                above += 1
        except Exception:
            continue
    out["breadth"] = round(above / total * 100) if total else 50
    return out


def _render_regime_bar():
    d = _regime_data()
    try:
        mkt = get_market_overview()
    except Exception:
        mkt = {}

    if not d.get("ok"):
        st.warning("Market data unavailable right now — sections below still work from cached scans.")
        return

    vix, breadth = d["vix"], d["breadth"]
    risk_on  = d["spy_v200"] > 0 and d["qqq_v200"] > 0 and vix < 22 and breadth >= 55
    risk_off = d["spy_v200"] < 0 or vix > 30 or breadth < 30
    if risk_on:
        verdict, v_col, v_note = "🟢 RISK-ON", ACCENT_GREEN, "full size OK"
    elif risk_off:
        verdict, v_col, v_note = "🔴 RISK-OFF", ACCENT_RED, "defense — small size, tight stops"
    else:
        verdict, v_col, v_note = "🟡 MIXED", GOLD, "half size, be selective"

    def _mini(label, val, chg=None, col=None):
        c = col or (ACCENT_GREEN if (chg or 0) >= 0 else ACCENT_RED)
        chg_s = (f'<span style="color:{c};font-size:10px;font-weight:700"> {chg:+.2f}%</span>'
                 if chg is not None else '')
        return (f'<span style="white-space:nowrap"><span style="color:{TEXT_MUTED};'
                f'font-size:10px">{label}</span> '
                f'<span style="color:{TEXT_PRIMARY};font-family:\'DM Mono\',monospace;'
                f'font-size:12px;font-weight:700">{val}</span>{chg_s}</span>')

    chips = [
        _mini("SPY vs 200MA", f'{d["spy_v200"]:+.1f}%', d["spy_chg"]),
        _mini("QQQ vs 200MA", f'{d["qqq_v200"]:+.1f}%', d["qqq_chg"]),
        _mini("VIX", f"{vix:.1f}", col=(ACCENT_GREEN if vix < 20 else GOLD if vix < 28 else ACCENT_RED)),
        _mini("Breadth", f"{breadth}%",
              col=(ACCENT_GREEN if breadth >= 55 else GOLD if breadth >= 35 else ACCENT_RED)),
    ]
    for name, key in [("Gold", "Gold"), ("10Y", "10Y Yield")]:
        if key in mkt:
            chips.append(_mini(name, f'{mkt[key]["value"]:,.1f}', mkt[key]["change"]))

    st.markdown(
        f'<div style="background:linear-gradient(90deg,{_rgba(v_col,0.16)},{BG_CARD} 55%);'
        f'border:1px solid {v_col}55;border-radius:14px;padding:12px 18px;'
        f'display:flex;align-items:center;gap:22px;flex-wrap:wrap;margin-bottom:14px">'
        f'<span style="color:{v_col};font-size:17px;font-weight:900;letter-spacing:1px">{verdict}</span>'
        f'<span style="color:{TEXT_MUTED};font-size:11px;font-style:italic">{v_note}</span>'
        + "".join(chips)
        + f'</div>',
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# B. TOP-20 CONVICTION PICKS  (from the latest Golden Scan JSON — no scanning)
# ══════════════════════════════════════════════════════════════════════════════

# Groups drive the forced mix. Golden Scan rows are grouped by which scanners
# fired (the "Scanners" abbrev field — richer than Style, which collapses to the
# top-priority scanner). LEAPS/CSP rows from the same sched file add options-flow
# diversity.
_GROUP_META = {
    "Trend":     ("📈 Trend",     ACCENT_GREEN),
    "Momentum":  ("⚡ Momentum",  ORANGE),
    "Reversal":  ("🔄 Reversal",  PURPLE),
    "Confirmed": ("🎯 Multi-Sig", GOLD),
    "Growth":    ("🌱 Growth",    MINT),
    "LEAPS":     ("🚀 LEAPS",     ACCENT_BLUE),
    "CSP":       ("💰 CSP",       GOLD),
}
_GROUP_ORDER = ["Trend", "Momentum", "Reversal", "Confirmed", "Growth", "LEAPS", "CSP"]
_GROUP_CAPS  = {"LEAPS": 3, "CSP": 2}          # options rows season the list, not dominate
# Scanner abbrev → group; checked in this order so a TC+MRS row counts as Reversal
_ABBREV_PRIORITY = [("MRS", "Reversal"), ("M", "Momentum"), ("TA", "Momentum"),
                    ("MF", "Confirmed"), ("G", "Growth"), ("TS", "Trend"), ("TC", "Trend")]


def _golden_group(scanners: str) -> str:
    toks = [t.strip() for t in str(scanners).split("+")]
    for ab, grp in _ABBREV_PRIORITY:
        if ab in toks:
            return grp
    return "Trend"


def _sched_files() -> list[tuple]:
    """All local sched files as (date_str, slot, path), newest first."""
    files = []
    for p in glob.glob(os.path.join(DATA_DIR, "sched_*_*.json")):
        m = re.match(r"sched_(am|pm)_(\d{4}-\d{2}-\d{2})\.json", os.path.basename(p))
        if m:
            files.append((m.group(2), m.group(1), p))
    # pm sorts after am on the same day
    files.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return files


def _scan_rows(path_or_dict) -> pd.DataFrame:
    """All strategy rows (Golden Scan + LEAPS + CSP) from one sched file."""
    try:
        if isinstance(path_or_dict, dict):
            d = path_or_dict
        else:
            with open(path_or_dict) as f:
                d = json.load(f)
        df = pd.DataFrame(d.get("results", []))
        if df.empty or "Strategy" not in df.columns:
            return pd.DataFrame()
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=900, show_spinner=False)
def _load_latest_scan() -> tuple[pd.DataFrame, tuple, str]:
    """
    Latest sched-scan rows (all strategies) + previous run's tickers (for 🆕
    badges) + label. Tries today's files on GitHub raw if the repo copy is older.
    """
    candidates: list[tuple[str, pd.DataFrame]] = []

    # Today's files via GitHub raw (auto-scan commits may be newer than deploy)
    today = datetime.now(pytz.timezone("America/Chicago")).date().isoformat()
    for slot in ("pm", "am"):
        try:
            import urllib.request as _ur
            with _ur.urlopen(f"{_GH_RAW_BASE}/sched_{slot}_{today}.json", timeout=3) as r:
                d = json.loads(r.read())
            g = _scan_rows(d)
            if not g.empty:
                candidates.append((f"{today}|{slot}", g))
        except Exception:
            pass

    for date_s, slot, path in _sched_files()[:14]:
        g = _scan_rows(path)
        if not g.empty:
            candidates.append((f"{date_s}|{slot}", g))

    if not candidates:
        return pd.DataFrame(), tuple(), ""

    # Dedupe by key, keep newest first
    seen, ordered = set(), []
    for key, g in sorted(candidates, key=lambda x: x[0], reverse=True):
        if key not in seen:
            seen.add(key)
            ordered.append((key, g))

    latest_key, latest = ordered[0]
    prev_tickers = tuple(ordered[1][1]["Ticker"]) if len(ordered) > 1 else tuple()
    date_s, slot = latest_key.split("|")
    label = f"{slot.upper()} scan · {datetime.fromisoformat(date_s).strftime('%b %d')}"
    return latest, prev_tickers, label


def _build_top20(df: pd.DataFrame, n: int = 20) -> list[dict]:
    """
    Uniform pick records, force-mixed round-robin across groups:
    Trend / Momentum / Reversal / Multi-Sig / Growth (Golden Scan, grouped by
    which scanners fired) + LEAPS / CSP rows (capped) from the same scan.
    """
    if df.empty:
        return []
    picks: dict[str, list[dict]] = {g: [] for g in _GROUP_ORDER}

    golden = df[df["Strategy"] == "Golden Scan"]
    for _, r in golden.sort_values("Score", ascending=False).iterrows():
        grp   = _golden_group(r.get("Scanners", ""))
        n_sc  = r.get("Scanner Count")
        extra = f" ×{int(n_sc)}" if n_sc and not pd.isna(n_sc) and int(n_sc) >= 2 else ""
        icon, col = _GROUP_META[grp]
        picks[grp].append({
            "ticker": r["Ticker"],
            "price":  r.get("Price"),
            "chg":    r.get("Change %", 0.0),
            "chip":   icon + extra,
            "color":  col,
            "hold":   str(r.get("Hold", "—")),
            "upside": r.get("Est. Upside %"),
            "score":  r.get("Score"),
        })

    for strat in ("LEAPS", "CSP"):
        sub = df[df["Strategy"] == strat]
        if sub.empty:
            continue
        icon, col = _GROUP_META[strat]
        for _, r in sub.sort_values("Score", ascending=False).iterrows():
            sc = r.get("Score")
            if sc is None or pd.isna(sc) or sc < 65:
                continue
            dte  = r.get("DTE")
            hold = ("6–12 mo" if strat == "LEAPS" else
                    (f"{int(dte)}d (put)" if dte and not pd.isna(dte) else "1–3 wk"))
            ann  = r.get("Ann. Return%")
            picks[strat].append({
                "ticker": r["Ticker"],
                "price":  r.get("Stock Price", r.get("Price")),
                "chg":    r.get("Change %", 0.0),
                "chip":   icon,
                "color":  col,
                "hold":   hold,
                "upside": ann if strat == "CSP" else None,
                "score":  sc,
            })

    out, seen, counts = [], set(), {g: 0 for g in _GROUP_ORDER}
    while len(out) < n and any(picks.values()):
        progressed = False
        for g in _GROUP_ORDER:
            cap = _GROUP_CAPS.get(g)
            while picks[g]:
                row = picks[g].pop(0)
                if row["ticker"] in seen or (cap and counts[g] >= cap):
                    continue
                seen.add(row["ticker"])
                counts[g] += 1
                out.append(row)
                progressed = True
                break
            if len(out) >= n:
                break
        if not progressed:
            break
    return out


@st.cache_data(ttl=21600, show_spinner=False)
def _earnings_soon(tickers: tuple, days: int = 7) -> dict:
    """Ticker → days-until-earnings when within `days`. Best-effort, cached 6 h."""
    out = {}
    for t in tickers:
        try:
            cal = yf.Ticker(t).calendar
            dates = None
            if isinstance(cal, dict):
                dates = cal.get("Earnings Date") or cal.get("EarningsDate")
            elif cal is not None and hasattr(cal, "loc"):
                try:
                    dates = list(cal.loc["Earnings Date"])
                except Exception:
                    dates = None
            if not dates:
                continue
            d0 = dates[0] if isinstance(dates, (list, tuple)) else dates
            d0 = pd.Timestamp(d0).date()
            delta = (d0 - datetime.now().date()).days
            if 0 <= delta <= days:
                out[t] = delta
        except Exception:
            continue
    return out


def _render_top20(live: dict):
    scan_df, prev_tickers, label = _load_latest_scan()

    if scan_df.empty:
        st.markdown(_card(
            "Top 20 Conviction Picks", "🏆", GOLD,
            f'<div style="color:{TEXT_MUTED};padding:30px;text-align:center">'
            f'No scan results found yet — run a scheduled scan '
            f'(Admin → Scheduled Scans) and this list fills automatically.</div>'
        ), unsafe_allow_html=True)
        return []

    top = _build_top20(scan_df, 20)
    tickers = [p["ticker"] for p in top]
    earn = _earnings_soon(tuple(tickers))

    rows = ""
    for p in top:
        t = p["ticker"]
        lv    = live.get(t, {})
        price = lv.get("price", p["price"])
        chg   = lv.get("chg", p["chg"]) or 0.0
        ups   = p["upside"]
        score = p["score"]

        badges = ""
        if prev_tickers and t not in prev_tickers:
            badges += (f' <span style="background:{ACCENT_BLUE}22;color:{ACCENT_BLUE};'
                       f'font-size:8px;font-weight:800;padding:1px 5px;'
                       f'border-radius:8px">NEW</span>')
        if t in earn:
            badges += (f' <span title="Earnings in {earn[t]}d" style="background:{ACCENT_RED}22;'
                       f'color:{ACCENT_RED};font-size:8px;font-weight:800;padding:1px 5px;'
                       f'border-radius:8px">E-{earn[t]}d</span>')

        try:
            price_s = "${:,.2f}".format(float(price))
        except Exception:
            price_s = "—"
        ups_html = (_mono("+{:.0f}%".format(float(ups)), ACCENT_GREEN, 11)
                    if ups is not None and not pd.isna(ups) else
                    f'<span style="color:{TEXT_MUTED}">—</span>')
        sc_html  = (f'<span style="color:{GOLD};font-size:10px;font-weight:800">{int(score)}</span>'
                    if score is not None and not pd.isna(score) else "")

        rows += (
            f'<tr>'
            f'<td style="{_TD};white-space:nowrap">'
            f'{_mono(t, GOLD, 12, True)}{badges}</td>'
            f'<td style="{_TD}">{_mono(price_s, TEXT_PRIMARY, 11)}</td>'
            f'<td style="{_TD}">{_chg_html(float(chg))}</td>'
            f'<td style="{_TD}">{_chip(p["chip"], p["color"])}</td>'
            f'<td style="{_TD};white-space:nowrap"><span style="color:{TEXT_PRIMARY};'
            f'font-size:11px">{p["hold"]}</span></td>'
            f'<td style="{_TD};text-align:right">{ups_html}</td>'
            f'<td style="{_TD};text-align:right">{sc_html}</td>'
            f'</tr>'
        )

    body = (
        f'<table style="width:100%;border-collapse:collapse">'
        f'<thead><tr>'
        f'<th style="{_TH}">Ticker</th><th style="{_TH}">Price</th>'
        f'<th style="{_TH}">Chg</th><th style="{_TH}">Why</th>'
        f'<th style="{_TH}">Hold</th><th style="{_TH};text-align:right">Upside</th>'
        f'<th style="{_TH};text-align:right">Sc</th>'
        f'</tr></thead><tbody>{rows}</tbody></table>'
        f'<div style="color:{TEXT_MUTED};font-size:9px;margin-top:6px">'
        f'Why = which scanner fired (×N = N scanners agree) · mixed across '
        f'Trend / Momentum / Reversal / Multi-Sig / Growth / LEAPS / CSP · '
        f'NEW = not in previous scan · E-Nd = earnings within N days · '
        f'CSP upside = annualized premium</div>'
    )
    st.markdown(_card("Top 20 Conviction Picks", "🏆", GOLD, body,
                      subtitle=label, max_height=560), unsafe_allow_html=True)
    return tickers


# ══════════════════════════════════════════════════════════════════════════════
# C. NEWS — headlines for the picks + general market pulse
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=900, show_spinner=False)
def _yf_ticker_news(tickers: tuple, per_ticker: int = 2) -> list[dict]:
    """yfinance headlines for the pick list. Handles old & new item formats."""
    from scanners.social_trends import _score_sentiment, _time_ago
    items = []
    for t in tickers:
        try:
            raw = yf.Ticker(t).news or []
        except Exception:
            continue
        for it in raw[:per_ticker]:
            try:
                c = it.get("content", it)
                title = c.get("title") or ""
                if not title:
                    continue
                link = (c.get("canonicalUrl", {}) or {}).get("url") or it.get("link") or ""
                src  = ((c.get("provider", {}) or {}).get("displayName")
                        or it.get("publisher") or "")
                ts = it.get("providerPublishTime")
                if ts:
                    dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                else:
                    pub = c.get("pubDate") or c.get("displayTime") or ""
                    dt  = pd.Timestamp(pub).to_pydatetime() if pub else datetime.now(timezone.utc)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                sent, _ = _score_sentiment(title)
                items.append({"ticker": t, "title": title[:120], "link": link,
                              "src": src, "dt": dt, "ago": _time_ago(dt), "sent": sent})
            except Exception:
                continue
    # newest first, dedupe near-identical titles
    seen, out = set(), []
    for it in sorted(items, key=lambda x: x["dt"], reverse=True):
        k = it["title"][:60].lower()
        if k not in seen:
            seen.add(k)
            out.append(it)
    return out[:14]


def _sent_dot(sent: str) -> str:
    col = ACCENT_GREEN if sent == "Bullish" else ACCENT_RED if sent == "Bearish" else TEXT_MUTED
    return f'<span style="color:{col};font-size:13px;line-height:1">●</span>'


def _render_news(pick_tickers: list):
    # 1. Headlines on the picks
    tick_items = _yf_ticker_news(tuple(pick_tickers)) if pick_tickers else []

    # 2. General market pulse from the RSS machinery in social_trends
    try:
        from scanners.social_trends import _fetch_news
        market_items = _fetch_news()[:8]
    except Exception:
        market_items = []

    rows = ""
    if tick_items:
        rows += (f'<div style="color:{ACCENT_BLUE};font-size:10px;font-weight:800;'
                 f'text-transform:uppercase;letter-spacing:0.8px;margin:2px 0 6px 0">'
                 f'On your picks</div>')
        for it in tick_items:
            link_open  = f'<a href="{it["link"]}" target="_blank" style="text-decoration:none">' if it["link"] else ""
            link_close = '</a>' if it["link"] else ""
            rows += (
                f'<div style="display:flex;gap:8px;align-items:baseline;padding:5px 0;'
                f'border-bottom:1px solid #2A2A3A33">'
                f'{_sent_dot(it["sent"])}'
                f'<span style="color:{GOLD};font-family:\'DM Mono\',monospace;'
                f'font-size:10px;font-weight:700;min-width:44px">{it["ticker"]}</span>'
                f'<span style="flex:1;font-size:11px;line-height:1.45">'
                f'{link_open}<span style="color:{TEXT_PRIMARY}">{it["title"]}</span>{link_close}</span>'
                f'<span style="color:{TEXT_MUTED};font-size:9px;white-space:nowrap">{it["ago"]}</span>'
                f'</div>'
            )
    else:
        rows += (f'<div style="color:{TEXT_MUTED};font-size:11px;padding:8px 0">'
                 f'No ticker headlines right now.</div>')

    if market_items:
        rows += (f'<div style="color:{PURPLE};font-size:10px;font-weight:800;'
                 f'text-transform:uppercase;letter-spacing:0.8px;margin:12px 0 6px 0">'
                 f'Market pulse</div>')
        for it in market_items:
            link_open  = f'<a href="{it.get("link","")}" target="_blank" style="text-decoration:none">' if it.get("link") else ""
            link_close = '</a>' if it.get("link") else ""
            tks = " ".join(it.get("tickers", [])[:3])
            rows += (
                f'<div style="display:flex;gap:8px;align-items:baseline;padding:5px 0;'
                f'border-bottom:1px solid #2A2A3A33">'
                f'{_sent_dot(it.get("sentiment", "Neutral"))}'
                f'<span style="flex:1;font-size:11px;line-height:1.45">'
                f'{link_open}<span style="color:{TEXT_PRIMARY}">{it.get("title","")[:120]}</span>{link_close}'
                + (f' <span style="color:{ACCENT_BLUE};font-size:9px">{tks}</span>' if tks else '')
                + f'</span>'
                f'<span style="color:{TEXT_MUTED};font-size:9px;white-space:nowrap">'
                f'{it.get("time_ago","")}</span>'
                f'</div>'
            )

    st.markdown(_card("News & Catalysts", "📰", ACCENT_BLUE, rows,
                      subtitle="● bullish · ● bearish tone", max_height=560),
                unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# D. TRADE TODAY + HIGH IV  (one batched download powers both + live prices)
# ══════════════════════════════════════════════════════════════════════════════

_ACTIVE_LIQUID = [
    "NVDA","TSLA","AAPL","MSFT","AMZN","META","GOOGL","AMD","PLTR","AVGO",
    "NFLX","MU","COIN","MSTR","HOOD","SMCI","UBER","BA","INTC","SOFI",
    "SPY","QQQ","IWM","TQQQ","SOXL","SMH","XLE","GLD","TLT","ARKK",
]


@st.cache_data(ttl=1800, show_spinner=False)
def _batch_stats(tickers: tuple) -> dict:
    """
    One batched 1-y download → per-ticker live stats:
    price, chg%, RVOL, ATR%, HV30, HV60, vol-rank (HV30 in its 1-y range).
    """
    out: dict[str, dict] = {}
    try:
        data = yf.download(list(tickers), period="1y", interval="1d",
                           group_by="ticker", progress=False, auto_adjust=True,
                           threads=True)
    except Exception:
        return out
    if data is None or data.empty:
        return out

    for t in tickers:
        try:
            df = data[t] if isinstance(data.columns, pd.MultiIndex) else data
            close = df["Close"].dropna()
            if len(close) < 40:
                continue
            high, low = df["High"].dropna(), df["Low"].dropna()
            vol = df["Volume"].dropna()

            price = float(close.iloc[-1])
            chg   = (price / float(close.iloc[-2]) - 1) * 100

            avg_vol = float(vol.iloc[-21:-1].mean()) if len(vol) >= 21 else float(vol.mean())
            rvol    = float(vol.iloc[-1]) / avg_vol if avg_vol > 0 else 1.0

            tr = pd.concat([high - low, (high - close.shift()).abs(),
                            (low - close.shift()).abs()], axis=1).max(axis=1)
            atr_pct = float(tr.rolling(14).mean().iloc[-1]) / price * 100

            rets = close.pct_change().dropna()
            hv_s = rets.rolling(30).std().dropna() * (252 ** 0.5) * 100
            hv30 = float(hv_s.iloc[-1]) if len(hv_s) else np.nan
            hv60 = (float(rets.rolling(60).std().dropna().iloc[-1]) * (252 ** 0.5) * 100
                    if len(rets) >= 61 else hv30)
            hi, lo = (float(hv_s.max()), float(hv_s.min())) if len(hv_s) else (np.nan, np.nan)
            vrank = ((hv30 - lo) / (hi - lo) * 100) if (hi and hi > lo) else 50.0

            out[t] = {"price": round(price, 2), "chg": round(chg, 2),
                      "rvol": round(rvol, 2), "atr": round(atr_pct, 1),
                      "hv30": round(hv30, 1) if hv30 == hv30 else None,
                      "vrank": round(vrank, 0), "expanding": bool(hv30 > hv60)}
        except Exception:
            continue
    return out


def _render_today_iv(stats: dict):
    # ⚡ Trade Today: unusual volume + movement, ranked by RVOL × |chg|
    cands = [(t, d) for t, d in stats.items() if d["rvol"] >= 1.1]
    cands.sort(key=lambda x: -(x[1]["rvol"] * (abs(x[1]["chg"]) + 0.5)))
    day_rows = ""
    for t, d in cands[:6]:
        rv_col   = ACCENT_GREEN if d["rvol"] >= 1.5 else GOLD
        price_s  = "${:,.2f}".format(d["price"])
        rvol_s   = "{:.1f}×".format(d["rvol"])
        atr_s    = "{:.1f}%".format(d["atr"])
        day_rows += (
            f'<tr><td style="{_TD}">{_mono(t, GOLD, 12, True)}</td>'
            f'<td style="{_TD}">{_mono(price_s, TEXT_PRIMARY, 11)}</td>'
            f'<td style="{_TD}">{_chg_html(d["chg"])}</td>'
            f'<td style="{_TD}">{_mono(rvol_s, rv_col, 11, True)}</td>'
            f'<td style="{_TD}">{_mono(atr_s, TEXT_MUTED, 11)}</td></tr>'
        )

    # 🔥 High IV: rich premium (vol-rank), tagged sell vs buy vol regime
    ivs = [(t, d) for t, d in stats.items()
           if d.get("vrank") is not None and d.get("hv30") is not None and d["vrank"] >= 40]
    ivs.sort(key=lambda x: -x[1]["vrank"])
    iv_rows = ""
    for t, d in ivs[:6]:
        play    = "🚀 buy premium" if d["expanding"] else "💰 sell premium"
        p_col   = ACCENT_BLUE if d["expanding"] else GOLD
        hv_s    = "{:.0f}%".format(d["hv30"])
        vrank_s = "{:.0f}".format(d["vrank"])
        iv_rows += (
            f'<tr><td style="{_TD}">{_mono(t, GOLD, 12, True)}</td>'
            f'<td style="{_TD}">{_mono(hv_s, ACCENT_BLUE, 11)}</td>'
            f'<td style="{_TD}">{_mono(vrank_s, GOLD, 11, True)}</td>'
            f'<td style="{_TD}"><span style="color:{p_col};font-size:10px;'
            f'font-weight:700;white-space:nowrap">{play}</span></td></tr>'
        )

    day_empty = (f'<tr><td colspan="5" style="{_TD};color:{TEXT_MUTED}">'
                 f'Quiet tape — no unusual volume right now</td></tr>')
    iv_empty  = (f'<tr><td colspan="4" style="{_TD};color:{TEXT_MUTED}">'
                 f'No elevated-vol names right now</td></tr>')
    day_tbl = (
        f'<div style="color:{ORANGE};font-size:10px;font-weight:800;text-transform:uppercase;'
        f'letter-spacing:0.8px;margin-bottom:4px">⚡ Trade Today — unusual volume & range</div>'
        f'<table style="width:100%;border-collapse:collapse;margin-bottom:12px">'
        f'<thead><tr><th style="{_TH}">Tkr</th><th style="{_TH}">Price</th>'
        f'<th style="{_TH}">Chg</th><th style="{_TH}">RVOL</th><th style="{_TH}">ATR</th></tr></thead>'
        f'<tbody>{day_rows or day_empty}</tbody></table>'
    )
    iv_tbl = (
        f'<div style="color:{ACCENT_RED};font-size:10px;font-weight:800;text-transform:uppercase;'
        f'letter-spacing:0.8px;margin-bottom:4px">🔥 High IV — options premium plays</div>'
        f'<table style="width:100%;border-collapse:collapse">'
        f'<thead><tr><th style="{_TH}">Tkr</th><th style="{_TH}">HV30</th>'
        f'<th style="{_TH}">VRank</th><th style="{_TH}">Play</th></tr></thead>'
        f'<tbody>{iv_rows or iv_empty}</tbody></table>'
        f'<div style="color:{TEXT_MUTED};font-size:9px;margin-top:6px">'
        f'HV30 = realized-vol IV proxy · VRank = HV30 within its 52-w range · '
        f'💰 falling vol → CSP/CC selling · 🚀 rising vol → debit/LEAP</div>'
    )
    st.markdown(_card("Today's Tape", "⚡", ORANGE, day_tbl + iv_tbl, max_height=560),
                unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# E. SECTOR ROTATION — where big money is flowing (price + volume, RRG-style)
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=1800, show_spinner=False)
def _sector_flows() -> list[dict]:
    from scanners.sector_rotation import SECTORS
    try:
        spy = get_price_history("SPY", period="1y")["Close"].squeeze()
    except Exception:
        return []

    def _ratio(c, b, n):
        try:
            return (float(c.iloc[-1]) / float(c.iloc[-n])) / (float(b.iloc[-1]) / float(b.iloc[-n]))
        except Exception:
            return 1.0

    rows = []
    for tkr, name in SECTORS:
        try:
            df = get_price_history(tkr, period="1y")
            close = df["Close"].squeeze()
            vol   = df["Volume"].squeeze()
            if len(close) < 70:
                continue
            rs63 = _ratio(close, spy, 63)
            rs21 = _ratio(close, spy, 21)
            # $-flow proxy: 5-day avg dollar volume vs 63-day baseline
            dvol = (close * vol).dropna()
            flow = float(dvol.iloc[-5:].mean()) / float(dvol.iloc[-63:].mean()) if len(dvol) >= 63 else 1.0
            quad = ("Leading" if rs63 >= 1 and rs21 >= 1 else
                    "Weakening" if rs63 >= 1 else
                    "Improving" if rs21 >= 1 else "Lagging")
            rows.append({"tkr": tkr, "name": name, "rs63": rs63, "rs21": rs21,
                         "flow": round(flow, 2), "quad": quad,
                         "ret1m": round((float(close.iloc[-1]) / float(close.iloc[-21]) - 1) * 100, 1)
                                  if len(close) >= 21 else 0.0})
        except Exception:
            continue
    return rows


def _render_sectors():
    rows = _sector_flows()
    if not rows:
        st.markdown(_card("Sector Rotation", "🔄", MINT,
                          f'<div style="color:{TEXT_MUTED};padding:20px">Sector data unavailable.</div>'),
                    unsafe_allow_html=True)
        return

    q_style = {
        "Leading":   (ACCENT_GREEN, "💰 Leading — money is here"),
        "Improving": (ACCENT_BLUE,  "📈 Improving — money arriving"),
        "Weakening": (GOLD,         "⚠️ Weakening — money slipping out"),
        "Lagging":   (ACCENT_RED,   "🚪 Lagging — money gone"),
    }

    def _quad_box(quad: str) -> str:
        col, title = q_style[quad]
        etfs  = sorted([r for r in rows if r["quad"] == quad], key=lambda r: -r["rs21"])
        chips = ""
        for r in etfs:
            tip   = "RS-21d {:.2f} · flow {:.2f}× · 1M {:+.1f}%".format(r["rs21"], r["flow"], r["ret1m"])
            money = " 💰" if r["flow"] >= 1.15 else ""
            chips += (
                f'<span title="{tip}" '
                f'style="background:{_rgba(col, 0.13)};color:{col};border:1px solid {col}44;'
                f'font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px;'
                f'margin:2px;display:inline-block;cursor:help">{r["tkr"]}{money}</span>'
            )
        if not chips:
            chips = f'<span style="color:{TEXT_MUTED};font-size:10px">—</span>'
        return (f'<div style="background:{_rgba(col, 0.05)};border:1px solid {col}33;'
                f'border-radius:10px;padding:8px 10px;min-height:86px">'
                f'<div style="color:{col};font-size:9px;font-weight:800;'
                f'text-transform:uppercase;letter-spacing:0.6px;margin-bottom:5px">{title}</div>'
                f'{chips}</div>')

    grid = (
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px">'
        f'{_quad_box("Improving")}{_quad_box("Leading")}'
        f'{_quad_box("Lagging")}{_quad_box("Weakening")}'
        f'</div>'
    )

    buys  = sorted([r for r in rows if r["quad"] in ("Leading", "Improving")],
                   key=lambda r: -(r["rs21"] + (0.05 if r["flow"] >= 1.1 else 0)))[:4]
    sells = sorted([r for r in rows if r["quad"] in ("Lagging", "Weakening")],
                   key=lambda r: r["rs21"])[:4]

    buy_chips  = " ".join(_chip(r["tkr"] + " " + r["name"], ACCENT_GREEN) for r in buys)
    sell_chips = " ".join(_chip(r["tkr"] + " " + r["name"], ACCENT_RED) for r in sells)
    summary = (
        f'<div style="display:flex;flex-direction:column;gap:6px">'
        f'<div style="font-size:11px"><span style="color:{ACCENT_GREEN};font-weight:800">'
        f'💰 FOCUS (buy zone): </span>{buy_chips}</div>'
        f'<div style="font-size:11px"><span style="color:{ACCENT_RED};font-weight:800">'
        f'🚪 AVOID (money leaving): </span>{sell_chips}</div></div>'
        f'<div style="color:{TEXT_MUTED};font-size:9px;margin-top:8px">'
        f'RRG-style: RS vs SPY 63d (position) × 21d (momentum) · 💰 = dollar-volume surge ≥1.15× '
        f'— institutional flows show up in price × volume before headlines</div>'
    )

    st.markdown(_card("Sector Rotation — follow the big money", "🔄", MINT,
                      grid + summary, max_height=560), unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN RENDER
# ══════════════════════════════════════════════════════════════════════════════

def render():
    now_et = datetime.now(pytz.timezone("US/Eastern")).strftime("%A %b %d %Y · %I:%M %p ET")
    section_header("🏠", "Market Overview", f"Command Center · {now_et}")

    _, col_btn = st.columns([6, 1])
    with col_btn:
        if st.button("🔄 Refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    # ── A. Regime bar ──────────────────────────────────────────────────────────
    with st.spinner("Reading market regime…"):
        try:
            _render_regime_bar()
        except Exception:
            st.warning("Regime bar unavailable.")

    # ── Row 1: picks + news ───────────────────────────────────────────────────
    left1, right1 = st.columns(2)

    with left1:
        with st.spinner("Loading Golden Scan picks…"):
            try:
                pick_tickers = _render_top20(live={})
            except Exception:
                pick_tickers = []
                st.warning("Top-20 picks unavailable.")

    # One batched download powers live prices, Trade-Today and High-IV
    with st.spinner("Fetching live stats (batched)…"):
        try:
            all_tickers = tuple(dict.fromkeys(list(pick_tickers) + _ACTIVE_LIQUID))
            stats = _batch_stats(all_tickers)
        except Exception:
            stats = {}

    with right1:
        with st.spinner("Pulling headlines…"):
            try:
                _render_news(pick_tickers)
            except Exception:
                st.warning("News unavailable.")

    # ── Row 2: today's tape + sectors ─────────────────────────────────────────
    left2, right2 = st.columns(2)

    with left2:
        try:
            _render_today_iv(stats)
        except Exception:
            st.warning("Today's tape unavailable.")

    with right2:
        with st.spinner("Computing sector flows…"):
            try:
                _render_sectors()
            except Exception:
                st.warning("Sector rotation unavailable.")

    # ── Disclaimer ─────────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};'
        f'border-radius:6px;padding:10px 16px;color:{TEXT_MUTED};font-size:10px;'
        f'text-align:center;margin-top:6px">⚠️ <b>Disclaimer:</b> Golden Scanner is for '
        f'educational and research purposes only. Signals are technical readings, not '
        f'financial advice. Do your own due diligence.</div>',
        unsafe_allow_html=True,
    )
