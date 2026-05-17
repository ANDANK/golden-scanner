# scanners/combined_scanner.py — All-in-One Signal Aggregator
# Runs every stock scanner, merges results, highlights top quality picks.

import streamlit as st
import pandas as pd
import numpy as np
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import *
from utils import section_header, empty_state, metric_card, mini_chart
from data_loader import get_price_history, prefetch_tickers

# ── Scanner metadata ────────────────────────────────────────────
SCANNER_META = {
    "Momentum":     {"hold": "10–30d",  "style": "Medium Swing",       "icon": "⚡"},
    "Trend Stack":  {"hold": "20–60d",  "style": "Trend Following",    "icon": "🏛"},
    "Multi-Factor": {"hold": "10–30d",  "style": "Confirmed Setup",    "icon": "🎯"},
    "Trend Align":  {"hold": "15–45d",  "style": "Breakout Entry",     "icon": "🎯"},
    "Trend Cont.":  {"hold": "20–60d",  "style": "Weekly Momentum",    "icon": "📈"},
    "Reset Bounce": {"hold": "10–30d",  "style": "Pullback Re-entry",  "icon": "🔄"},
    "Growth":       {"hold": "30–180d", "style": "Growth Play",        "icon": "🚀"},
}

# Conviction priority — lower number = higher priority when sorting / labelling
SCANNER_PRIORITY = {
    "Trend Cont.":  1,   # Highest conviction — pure weekly institutional momentum
    "Trend Stack":  2,   # Strictest daily MA alignment
    "Trend Align":  3,   # Daily MACD cross + weekly context
    "Multi-Factor": 4,   # 7-signal confirmation
    "Reset Bounce": 5,   # Weekly pullback re-entry
    "Momentum":     6,   # Daily swing momentum
    "Growth":       7,   # Fundamental overlay
}

# Display abbreviations for the Scanners / Source columns
SCANNER_ABBREV = {
    "Trend Cont.":  "TC",
    "Trend Stack":  "TS",
    "Trend Align":  "TA",
    "Multi-Factor": "MF",
    "Reset Bounce": "MRS",
    "Momentum":     "M",
    "Growth":       "G",
}
# Reverse map: abbreviation → full internal key (for Hold/Style lookup)
_ABBREV_TO_KEY = {v: k for k, v in SCANNER_ABBREV.items()}


# ── Upside estimator ────────────────────────────────────────────

def _estimate_upside(ticker: str, price: float) -> float:
    """Return estimated upside % to 52-week high (or ATR extension if at high)."""
    try:
        df = get_price_history(ticker, period="1y")
        if df is None or df.empty:
            return 0.0
        close = df["Close"].squeeze()
        high_52w = float(close.max())
        if price >= high_52w * 0.97:
            # Near or at 52-week high — estimate ATR-based continuation
            atr = float((df["High"].squeeze() - df["Low"].squeeze()).tail(14).mean())
            return round(max(5.0, atr / price * 100 * 8), 1)
        return round(max(3.0, (high_52w - price) / price * 100), 1)
    except Exception:
        return 0.0


# ── Normalize each scanner's output ────────────────────────────

def _norm(df: pd.DataFrame, scanner_name: str) -> pd.DataFrame:
    """Keep only columns we need and add scanner tag."""
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["_scanner"] = scanner_name
    keep = {
        "Ticker":    "Ticker",
        "Price":     "Price",
        "Change %":  "Change %",
        "RSI":       "RSI",
        "Vol Ratio": "Vol Ratio",
        "RS vs SPY": "RS vs SPY",
        "Rev Growth %": "Rev Growth %",
        "EPS Growth %": "EPS Growth %",
        "P/E":       "P/E",
        "Score":     "Score",
        "_scanner":  "_scanner",
    }
    out_cols = {v: df[k] for k, v in keep.items() if k in df.columns}
    return pd.DataFrame(out_cols)


# ── Run all scanners ────────────────────────────────────────────

def run_combined(tickers: list, include_value: bool = False,
                 include_growth: bool = False,
                 status_ph=None, status=None) -> pd.DataFrame:
    # Accept both keyword names for backward compat with headless_scan.py
    class _FakePH:
        def markdown(self, *a, **kw): pass
        def empty(self): pass

    if status_ph is None:
        status_ph = status or _FakePH()
    from scanners.technical_hackers import (
        scan_trend_stack, scan_multifactor,
    )
    from scanners.momentum_scanner import scan_momentum
    from scanners.growth_scanner import scan_growth
    from scanners.weekly_scanners import (
        scan_trend_alignment, scan_trend_continuation, scan_momentum_reset,
        clear_weekly_cache, prefetch_weekly,
    )

    # Clear the process-level weekly cache at the start of each run
    # so stale data from a prior run never bleeds through.
    clear_weekly_cache()

    # ── Batch prefetch — turns 200 sequential API calls → 3 bulk calls ──────
    # Populate _PROC_PRICE_CACHE before any scanner starts.  Each subsequent
    # get_price_history() call in the scan loop hits the local dict and makes
    # zero additional network requests for the same (period, interval) key.
    status_ph.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:12px;margin:4px 0">'
        f'Prefetching daily price data…</div>',
        unsafe_allow_html=True,
    )
    prefetch_tickers(tickers, "6mo", "1d")   # Momentum / Trend Stack / Multi-Factor / Growth

    status_ph.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:12px;margin:4px 0">'
        f'Prefetching weekly price data…</div>',
        unsafe_allow_html=True,
    )
    prefetch_weekly(tickers, years=3)         # Trend Align / Trend Cont. / Reset Bounce

    status_ph.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:12px;margin:4px 0">'
        f'Prefetching 1-year data for upside targets…</div>',
        unsafe_allow_html=True,
    )
    prefetch_tickers(tickers, "1y", "1d")    # _estimate_upside
    # ────────────────────────────────────────────────────────────────────────

    frames = []

    def _run(label, fn, *args, **kwargs):
        status_ph.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:12px;margin:4px 0">'
            f'Running <b style="color:{TEXT_PRIMARY}">{label}</b> scanner…</div>',
            unsafe_allow_html=True,
        )
        try:
            result = fn(*args, **kwargs)
            if isinstance(result, tuple):
                result = result[0]
            normed = _norm(result, label)
            if not normed.empty:
                frames.append(normed)
        except Exception as e:
            st.warning(f"{label} scanner error: {e}")

    price_min, price_max = 5.0, 5000.0

    # ── Core daily-chart scanners ─────────────────────────────────
    _run("Momentum",    scan_momentum,    tickers, 50, 72, 1.1, price_min, price_max, 0, 0)
    _run("Trend Stack", scan_trend_stack, tickers, 55, 70, 1.3, 3.0, 1.03, price_min)
    _run("Multi-Factor",scan_multifactor, tickers, 50, 72, 1.1, 1.0, False, 7.0, price_min, price_max)

    # ── Weekly-chart setups ───────────────────────────────────────
    _run("Trend Align",  scan_trend_alignment,  tickers,
         price_min=price_min, price_max=price_max, status_ph=status_ph)
    _run("Trend Cont.",  scan_trend_continuation, tickers,
         price_min=price_min, price_max=price_max, status_ph=status_ph)
    _run("Reset Bounce", scan_momentum_reset,    tickers,
         price_min=price_min, price_max=price_max, status_ph=status_ph)

    # ── Optional (slower) fundamental scanner ─────────────────────
    if include_growth:
        _run("Growth", scan_growth, tickers, 10, 8, 0.95, price_min, price_max)

    status_ph.empty()

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    combined["Score"] = pd.to_numeric(combined.get("Score", 0), errors="coerce").fillna(0).astype(int)
    combined["Price"] = pd.to_numeric(combined.get("Price", 0), errors="coerce").fillna(0)

    # Aggregate: group by Ticker — list all scanners in priority order, keep best row per ticker
    def _priority_join(scanner_series):
        """Return scanner abbreviations joined in SCANNER_PRIORITY order."""
        names = list(scanner_series.unique())
        names.sort(key=lambda n: SCANNER_PRIORITY.get(n, 99))
        return " + ".join(SCANNER_ABBREV.get(n, n) for n in names)

    scanner_lists = (
        combined.groupby("Ticker")["_scanner"]
        .apply(_priority_join)
        .reset_index()
        .rename(columns={"_scanner": "Scanners"})
    )
    best = (
        combined.sort_values("Score", ascending=False)
        .drop_duplicates("Ticker")
        .drop(columns=["_scanner"])
    )
    merged = best.merge(scanner_lists, on="Ticker", how="left")
    merged["Scanner Count"] = merged["Scanners"].str.count(r"\+") + 1

    # Hold/Style from the highest-priority scanner (reverse-map abbreviation → full key)
    def _top_scanner_key(scanners_str: str) -> str:
        abbr = scanners_str.split(" + ")[0].strip()
        return _ABBREV_TO_KEY.get(abbr, abbr)   # TC → "Trend Cont.", etc.

    merged["Hold"] = merged["Scanners"].apply(
        lambda s: SCANNER_META.get(_top_scanner_key(s), {}).get("hold", "Varies")
    )
    merged["Style"] = merged["Scanners"].apply(
        lambda s: SCANNER_META.get(_top_scanner_key(s), {}).get("style", "Mixed")
    )

    # Upside estimate
    status_ph.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:12px">Estimating upside targets…</div>',
        unsafe_allow_html=True,
    )
    merged["Est. Upside %"] = merged.apply(
        lambda r: _estimate_upside(r["Ticker"], r["Price"]), axis=1
    )
    status_ph.empty()

    # Sort: Scanner Count desc → top scanner priority asc → Score desc
    merged["_best_pri"] = merged["Scanners"].apply(
        lambda s: min(
            SCANNER_PRIORITY.get(_ABBREV_TO_KEY.get(n.strip(), n.strip()), 99)
            for n in s.split(" + ")
        )
    )
    merged = merged.sort_values(
        ["Scanner Count", "_best_pri", "Score"],
        ascending=[False, True, False]
    ).drop(columns=["_best_pri"]).reset_index(drop=True)

    return merged


# ── Top-picks banner ────────────────────────────────────────────

def _render_top_picks(df: pd.DataFrame):
    """Show top 3 quality picks. Quality = multi-scanner OR score >= 80."""
    qualified = df[
        (df["Scanner Count"] >= 2) | (df["Score"] >= 80)
    ].head(3)

    if qualified.empty:
        return

    st.markdown(
        f'<div style="color:{GOLD};font-size:13px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:1.2px;margin:0 0 12px">&#127942; Top Quality Picks</div>',
        unsafe_allow_html=True,
    )

    cols = st.columns(len(qualified))
    for col, (_, row) in zip(cols, qualified.iterrows()):
        ticker   = row["Ticker"]
        price    = float(row.get("Price", 0))
        chg      = float(row.get("Change %", 0))
        score    = int(row.get("Score", 0))
        upside   = float(row.get("Est. Upside %", 0))
        scanners = str(row.get("Scanners", ""))
        hold     = str(row.get("Hold", "—"))
        count    = int(row.get("Scanner Count", 1))
        chg_col  = ACCENT_GREEN if chg >= 0 else ACCENT_RED
        arrow    = "▲" if chg >= 0 else "▼"
        border_c = ACCENT_GREEN if score >= 80 else GOLD
        conf_lbl = f"{count} signals" if count > 1 else "High score"

        with col:
            st.markdown(
                f'<div style="background:linear-gradient(135deg,{BG_CARD},{BG_PANEL});'
                f'border:1px solid {border_c}55;border-top:3px solid {border_c};'
                f'border-radius:10px;padding:18px 20px">'
                f'<div style="display:flex;justify-content:space-between;align-items:flex-start">'
                f'<div>'
                f'<div style="color:{GOLD};font-size:28px;font-family:\'Cormorant Garamond\',serif;'
                f'font-weight:700;letter-spacing:1.5px;line-height:1">{ticker}</div>'
                f'<div style="color:{TEXT_PRIMARY};font-size:18px;font-weight:600;margin-top:4px">'
                f'${price:.2f}</div>'
                f'<div style="color:{chg_col};font-size:13px;margin-top:2px">{arrow} {chg:+.2f}%</div>'
                f'</div>'
                f'<div style="text-align:right">'
                f'<div style="color:{border_c};font-size:22px;font-weight:800">{score}</div>'
                f'<div style="color:{TEXT_MUTED};font-size:9px;text-transform:uppercase">score</div>'
                f'</div>'
                f'</div>'
                f'<div style="margin-top:12px;border-top:1px solid {BORDER_COLOR};padding-top:10px">'
                f'<div style="color:{TEXT_MUTED};font-size:10px;text-transform:uppercase;'
                f'letter-spacing:0.8px;margin-bottom:4px">&#128200; Appeared in</div>'
                f'<div style="color:{TEXT_PRIMARY};font-size:11px;line-height:1.6">{scanners}</div>'
                f'</div>'
                f'<div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">'
                f'<span style="background:{ACCENT_GREEN}22;color:{ACCENT_GREEN};border:1px solid {ACCENT_GREEN}44;'
                f'padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600">'
                f'&#9650; Est. +{upside:.1f}%</span>'
                f'<span style="background:{GOLD}22;color:{GOLD};border:1px solid {GOLD}44;'
                f'padding:2px 8px;border-radius:4px;font-size:10px">&#128337; {hold}</span>'
                f'<span style="background:{ACCENT_BLUE}22;color:{ACCENT_BLUE};border:1px solid {ACCENT_BLUE}44;'
                f'padding:2px 8px;border-radius:4px;font-size:10px">{conf_lbl}</span>'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ── Results table ───────────────────────────────────────────────

# ── Indicator signal helper ──────────────────────────────────────
# Shows which of the top-ranked indicators from the Indicator Importance
# Ranking are "firing" for each ticker, derived from already-computed
# scanner data (no extra API calls needed).
#
#  #1 MACDw  — Weekly MACD cross   → ticker in TC or TA scanner
#  #2 MAStk  — MA Trend Stack      → ticker in TS scanner
#  #3 RSIz   — RSI Zone (45–70)    → RSI column
#  #4 MACDd  — Daily MACD cross    → ticker in TA or MF scanner
#  #5 Vol×   — Volume Spike ≥1.5×  → Vol Ratio column
#  (#10 BBsq requires extra price compute — deferred)

def _signals_text(row) -> str:
    """Return comma-separated signal abbreviations that are firing."""
    fired = []
    sc = [s.strip() for s in str(row.get("Scanners", "")).split("+")]
    if "TC" in sc or "TA" in sc:
        fired.append("MACDw")   # #1 Weekly MACD cross
    if "TS" in sc:
        fired.append("MAStk")   # #2 MA Trend Stack full alignment
    try:
        rsi = float(row.get("RSI", 0) or 0)
        if 45 <= rsi <= 70:
            fired.append("RSIz")  # #3 RSI bullish zone
    except Exception:
        pass
    if "TA" in sc or "MF" in sc:
        fired.append("MACDd")   # #4 Daily MACD cross / confirmation
    try:
        vr = float(row.get("Vol Ratio", 0) or 0)
        if vr >= 1.5:
            fired.append("Vol×")  # #5 Volume spike ≥ 1.5×
    except Exception:
        pass
    return ", ".join(fired) if fired else "—"


def _render_combined_table(df: pd.DataFrame):
    # Compute Signals column before slicing display cols
    df = df.copy()
    df["Signals"] = df.apply(_signals_text, axis=1)

    display_cols = [
        "Ticker", "Price", "Change %", "Scanners", "Signals", "Style", "Hold",
        "Est. Upside %", "RSI", "Vol Ratio", "RS vs SPY", "Score", "Scanner Count",
    ]
    cols_present = [c for c in display_cols if c in df.columns]
    disp = df[cols_present].copy()

    col_a, col_b = st.columns([4, 1])
    with col_a:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:13px;padding:6px 0">'
            f'Found <b style="color:{GOLD}">{len(disp)}</b> tickers across all scanners</div>',
            unsafe_allow_html=True,
        )
    with col_b:
        st.download_button(
            "⬇ Export CSV", disp.to_csv(index=False),
            "combined_scan.csv", "text/csv", use_container_width=True,
        )

    hdr = "".join(
        f'<th style="background:{BG_PANEL};color:{GOLD};font-size:10px;font-weight:600;'
        f'text-transform:uppercase;letter-spacing:0.7px;padding:10px 12px;'
        f'border-bottom:2px solid {GOLD}44;white-space:nowrap">{c}</th>'
        for c in cols_present
    )

    rows_html = []
    for i, (_, row) in enumerate(disp.iterrows()):
        bg = BG_CARD if i % 2 == 0 else BG_PANEL
        cells = []
        for col in cols_present:
            val = row[col]
            if col == "Ticker":
                content = (
                    f'<span style="color:{GOLD};font-family:\'DM Mono\',monospace;'
                    f'font-weight:700;font-size:13px">{val}</span>'
                )
            elif col == "Scanner Count":
                color = ACCENT_GREEN if int(val) >= 2 else TEXT_MUTED
                content = f'<span style="color:{color};font-weight:700">{int(val)}</span>'
            elif col == "Scanners":
                count = str(val).count("+") + 1
                color = ACCENT_GREEN if count >= 2 else TEXT_PRIMARY
                content = f'<span style="color:{color};font-size:11px">{val}</span>'
            elif col == "Signals":
                val_str = str(val).strip()
                if val_str == "—" or not val_str:
                    content = f'<span style="color:{TEXT_MUTED};font-size:11px">—</span>'
                else:
                    sig_parts = []
                    for sig in [s.strip() for s in val_str.split(",")]:
                        if not sig or sig == "—":
                            continue
                        sig_parts.append(
                            f'<span style="background:{ACCENT_GREEN}1A;color:{ACCENT_GREEN};'
                            f'border:1px solid {ACCENT_GREEN}44;padding:1px 6px;'
                            f'border-radius:3px;font-size:10px;font-weight:600;'
                            f'white-space:nowrap">{sig}</span>'
                        )
                    content = (
                        '<div style="display:flex;flex-wrap:wrap;gap:3px;min-width:80px">'
                        + "".join(sig_parts) + "</div>"
                    )
            elif col == "Hold":
                content = f'<span style="color:{GOLD};font-size:12px">{val}</span>'
            elif col == "Style":
                content = f'<span style="color:{ACCENT_BLUE};font-size:11px">{val}</span>'
            elif col == "Est. Upside %":
                fval = float(val) if val else 0
                color = ACCENT_GREEN if fval >= 15 else (GOLD if fval >= 8 else TEXT_MUTED)
                content = f'<span style="color:{color};font-weight:600">+{fval:.1f}%</span>'
            elif col == "Score":
                sc = int(val)
                color = ACCENT_GREEN if sc >= 70 else (GOLD if sc >= 50 else ACCENT_RED)
                content = (
                    f'<div style="display:flex;align-items:center;gap:6px">'
                    f'<div style="flex:1;background:#1a1a2a;border-radius:3px;height:4px;min-width:50px">'
                    f'<div style="background:{color};height:4px;border-radius:3px;width:{sc}%"></div></div>'
                    f'<span style="color:{color};font-weight:700;font-size:12px">{sc}</span></div>'
                )
            elif col == "Change %":
                try:
                    fval = float(val)
                    color = ACCENT_GREEN if fval >= 0 else ACCENT_RED
                    content = f'<span style="color:{color};font-size:12px">{fval:+.2f}%</span>'
                except Exception:
                    content = f'<span style="color:{TEXT_MUTED};font-size:12px">{val}</span>'
            elif col == "RSI":
                try:
                    fval = float(val)
                    color = ACCENT_GREEN if 55 <= fval <= 68 else (ACCENT_RED if fval > 75 else TEXT_MUTED)
                    content = f'<span style="color:{color};font-size:12px">{fval:.1f}</span>'
                except Exception:
                    content = f'<span style="color:{TEXT_MUTED};font-size:12px">{val}</span>'
            else:
                content = f'<span style="color:{TEXT_PRIMARY};font-size:12px">{val}</span>'

            cells.append(
                f'<td style="padding:8px 12px;vertical-align:middle;white-space:nowrap;'
                f'border-bottom:1px solid {BORDER_COLOR}22;background:{bg}">{content}</td>'
            )
        rows_html.append(f'<tr>{"".join(cells)}</tr>')

    st.markdown(
        f'<div style="overflow-x:auto;border:1px solid {BORDER_COLOR};border-radius:8px;margin-top:8px">'
        f'<table style="width:100%;border-collapse:collapse;font-family:\'Inter\',sans-serif">'
        f'<thead><tr>{hdr}</tr></thead>'
        f'<tbody>{"".join(rows_html)}</tbody>'
        f'</table></div>',
        unsafe_allow_html=True,
    )

    # Charts for all tickers
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:12px;margin:20px 0 6px">&#128200; Charts &amp; Price History</div>',
        unsafe_allow_html=True,
    )
    for idx, (_, row) in enumerate(df.iterrows()):
        ticker  = str(row["Ticker"])
        chg     = float(row.get("Change %", 0))
        score   = int(row.get("Score", 0))
        scanners = str(row.get("Scanners", ""))
        label   = f"📈  {ticker}   ·   {scanners}   ·   {chg:+.2f}%   ·   Score {score}/100"
        with st.expander(label, expanded=(idx == 0)):
            df_c = get_price_history(ticker, period="6mo")
            if not df_c.empty:
                from utils import mini_chart
                st.plotly_chart(mini_chart(df_c, ticker), width='stretch')


# ── Main render ─────────────────────────────────────────────────

def render():
    section_header(
        "✦", "Golden Scan",
        "All scanners · One merged table · Multi-signal tickers ranked first",
    )

    with st.sidebar:
        st.markdown(
            f'<div style="color:{GOLD};font-size:12px;font-weight:600;margin:16px 0 8px">'
            f'&#9881;&#65039; Combined Scan Settings</div>',
            unsafe_allow_html=True,
        )
        universe_size  = st.slider("Universe Size (tickers)", 30, len(SP500_SAMPLE), 200, 10,
                                    help="First 55 = top 20 stocks + all 35 liquid ETFs. 200 = full large-cap + ETF mix.")
        include_growth = st.checkbox("Include Growth Scanner (slower — uses fundamentals)", value=False)

    tickers = SP500_SAMPLE[:universe_size]

    col1, col2, col3 = st.columns([1, 1, 4])
    with col1:
        run = st.button("▶ Run All Scanners", use_container_width=True)
    with col2:
        if st.button("🔄 Clear Cache", use_container_width=True):
            st.cache_data.clear()
            from scanners.weekly_scanners import clear_weekly_cache
            clear_weekly_cache()
            st.rerun()

    if not run and "_golden_r" not in st.session_state:
        # ── Scanner legend cards ──────────────────────────────────
        _daily_scanners  = ["Momentum", "Trend Stack", "Multi-Factor"]
        _weekly_scanners = ["Trend Align", "Trend Cont.", "Reset Bounce"]

        def _card(name, meta, badge=None):
            badge_html = (
                f'<span style="background:{ACCENT_BLUE}22;color:{ACCENT_BLUE};'
                f'border:1px solid {ACCENT_BLUE}44;font-size:9px;font-weight:700;'
                f'padding:1px 5px;border-radius:3px;letter-spacing:.5px">{badge}</span> '
                if badge else ""
            )
            return (
                f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};'
                f'border-radius:8px;padding:12px 14px">'
                f'<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">'
                f'<span style="font-size:15px">{meta["icon"]}</span>'
                f'{badge_html}'
                f'<span style="color:{GOLD};font-size:11px;font-weight:700">{name}</span>'
                f'</div>'
                f'<div style="color:{TEXT_MUTED};font-size:10px;line-height:1.5">'
                f'{meta["style"]}<br>'
                f'<span style="color:{GOLD}">&#128337; {meta["hold"]}</span>'
                f'</div></div>'
            )

        daily_cards  = "".join(_card(n, SCANNER_META[n], "DAILY")  for n in _daily_scanners)
        weekly_cards = "".join(_card(n, SCANNER_META[n], "WEEKLY") for n in _weekly_scanners)

        st.markdown(
            f'<div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:12px;'
            f'padding:32px;text-align:center;margin-top:8px">'
            f'<div style="font-size:40px;margin-bottom:12px">&#128257;</div>'
            f'<div style="font-size:22px;color:{GOLD};font-family:\'Cormorant Garamond\',serif;'
            f'margin-bottom:8px">✦ Golden Scan</div>'
            f'<div style="color:{TEXT_MUTED};font-size:13px;max-width:580px;margin:0 auto 24px;line-height:1.8">'
            f'Runs 6 independent scanners (3 daily-chart + 3 weekly-chart), merges all results, '
            f'and surfaces tickers confirmed by multiple signals. Weekly setups use real weekly bars '
            f'for institutional-grade entries. Multi-signal picks are ranked first.</div>'
            f'<div style="color:{TEXT_MUTED};font-size:10px;text-transform:uppercase;letter-spacing:1px;'
            f'margin-bottom:8px">Daily-chart scanners</div>'
            f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;'
            f'max-width:620px;margin:0 auto 16px;text-align:left">{daily_cards}</div>'
            f'<div style="color:{TEXT_MUTED};font-size:10px;text-transform:uppercase;letter-spacing:1px;'
            f'margin-bottom:8px">Weekly-chart scanners</div>'
            f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;'
            f'max-width:620px;margin:0 auto 20px;text-align:left">{weekly_cards}</div>'
            f'<div style="display:flex;justify-content:center;gap:16px;flex-wrap:wrap">'
            f'<span style="color:{ACCENT_GREEN};font-size:12px">&#9679; Multi-signal = highest conviction</span>'
            f'<span style="color:{GOLD};font-size:12px">&#9679; Est. Upside to 52-week high</span>'
            f'<span style="color:{ACCENT_BLUE};font-size:12px">&#9679; Weekly bars for weekly setups</span>'
            f'</div></div>',
            unsafe_allow_html=True,
        )
        return

    status = st.empty()
    progress_bar = st.progress(0)

    if run:
        with st.spinner("Running all scanners…"):
            df = run_combined(tickers, include_value=False, include_growth=include_growth, status=status)
            progress_bar.progress(1.0)
        progress_bar.empty()
        st.session_state["_golden_r"] = df
    else:
        progress_bar.empty()

    df = st.session_state.get("_golden_r", pd.DataFrame())
    if df.empty:
        empty_state("No setups found across any scanner. Try increasing universe size or loosening filters.")
        return

    # Compute Signals column from scanner membership + RSI + Vol Ratio
    df = df.copy()
    df["Signals"] = df.apply(_signals_text, axis=1)

    # Summary metrics
    multi_count   = int((df.get("Scanner Count", pd.Series([1])) >= 2).sum())
    avg_upside    = float(df.get("Est. Upside %", pd.Series([0])).mean())
    top_scanner   = (
        pd.Series([n.strip() for s in df["Scanners"].tolist() for n in s.split(" + ")])
        .value_counts().index[0]
        if "Scanners" in df.columns and len(df) > 0 else "—"
    )

    c1, c2, c3, c4 = st.columns(4)
    with c1: metric_card("Tickers Found", str(len(df)), color=GOLD)
    with c2: metric_card("Multi-Signal", str(multi_count), color=ACCENT_GREEN)
    with c3: metric_card("Avg Est. Upside", f"{avg_upside:.1f}%", color=ACCENT_BLUE)
    with c4: metric_card("Most Active", top_scanner, color=GOLD)

    st.markdown("<br>", unsafe_allow_html=True)

    # Top picks
    _render_top_picks(df)

    st.markdown(
        f'<div style="height:1px;background:linear-gradient(90deg,transparent,{GOLD}44,transparent);'
        f'margin:20px 0 16px"></div>',
        unsafe_allow_html=True,
    )

    # ── Green expander theme — scoped to Golden Scan page only ──────
    # Overrides the global light-blue from app.py; reverts on page navigation.
    st.markdown("""<style>
    [data-testid="stExpander"] summary {
        background: rgba(52, 211, 153, 0.09) !important;
        border: 1px solid rgba(52, 211, 153, 0.32) !important;
        border-radius: 6px !important;
        padding: 8px 14px !important;
    }
    [data-testid="stExpander"] summary:hover {
        background: rgba(52, 211, 153, 0.18) !important;
        border-color: rgba(52, 211, 153, 0.55) !important;
    }
    </style>""", unsafe_allow_html=True)

    from utils import render_results_table

    # ── Multi-signal expander (highest conviction — expanded by default) ──
    multi_df  = df[df["Scanner Count"] >= 2].copy()
    single_df = df[df["Scanner Count"] == 1].copy()

    if not multi_df.empty:
        with st.expander(
            f"**⭐ Multi-Signal Tickers** — {len(multi_df)} ticker(s) · Confirmed by 2+ independent scanners",
            expanded=True,
        ):
            render_results_table(multi_df, strategy="Stock", source="Golden Scan")

    # ── Per-scanner expanders in conviction order ─────────────────
    if not single_df.empty:
        # Derive primary scanner (first abbreviation already sorted by priority)
        single_df = single_df.copy()
        single_df["_abbr"] = single_df["Scanners"].str.split(" + ").str[0].str.strip()
        single_df["_key"]  = single_df["_abbr"].map(_ABBREV_TO_KEY)

        seen_keys = single_df["_key"].dropna().unique()
        ordered   = sorted(seen_keys, key=lambda n: SCANNER_PRIORITY.get(n, 99))

        for scanner_name in ordered:
            sub = single_df[single_df["_key"] == scanner_name].drop(columns=["_abbr", "_key"])
            if sub.empty:
                continue
            meta  = SCANNER_META.get(scanner_name, {})
            icon  = meta.get("icon", "📊")
            style = meta.get("style", "")
            hold  = meta.get("hold", "")
            abbr  = SCANNER_ABBREV.get(scanner_name, scanner_name)
            with st.expander(
                f"**{icon} {scanner_name} ({abbr})** — {len(sub)} ticker(s) · {style} · Hold {hold}",
                expanded=False,
            ):
                render_results_table(sub, strategy="Stock", source=f"GS-{abbr}")
