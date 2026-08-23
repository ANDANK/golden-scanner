"""
scanners/sector_rotation.py — Sector Rotation Scanner

Tracks the 11 SPDR sector ETFs + key macro ETFs ranked by Relative Strength vs SPY.
Rising RS + price above SMA50 + volume expansion = institutional rotation IN.
Declining RS + price below SMA50 = rotation OUT.

Trade guidance:
  Rotating IN  + RSI 45-65 + near EMA9 → CSP or LEAP candidate
  Rotating OUT + below SMA50            → avoid / let it base

Every figure here is computed off the LAST bar, which during market hours is
still forming — so the table legitimately moves between refreshes. Two
companion modules exist so that movement can be judged rather than guessed at:

  scanners/sector_history.py   the same table replayed over past settled
                               closes, plus churn/stability metrics — is the
                               leaderboard really turning over, or is it the
                               live bar?
  scanners/sector_validate.py  the same table recomputed from an independent
                               price feed, plus the published references
                               worth eyeballing.
"""

from __future__ import annotations

import html as _html
import numpy as np
import pandas as pd
import pytz
import streamlit as st
import sys, os
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_loader import get_price_history
from utils import calc_rsi, calc_ema, calc_sma


# ── Sector universe ────────────────────────────────────────────────────────────
SECTORS = [
    ("XLK",  "Technology"),
    ("XLF",  "Financials"),
    ("XLV",  "Healthcare"),
    ("XLI",  "Industrials"),
    ("XLE",  "Energy"),
    ("XLY",  "Cons. Discretionary"),
    ("XLP",  "Cons. Staples"),
    ("XLC",  "Communication"),
    ("XLB",  "Materials"),
    ("XLRE", "Real Estate"),
    ("XLU",  "Utilities"),
    # Macro / cross-asset context
    ("QQQ",  "Growth (QQQ)"),
    ("IWM",  "Small Caps (IWM)"),
    ("GLD",  "Gold (GLD)"),
    ("TLT",  "Long Bonds (TLT)"),
]


def _rs(close: pd.Series, bench: pd.Series, days: int = 63) -> float:
    """Return ticker/bench return ratio over `days` trading days."""
    try:
        n = min(len(close), len(bench), days)
        t = float(close.iloc[-1]) / float(close.iloc[-n]) if float(close.iloc[-n]) else 1.0
        b = float(bench.iloc[-1]) / float(bench.iloc[-n]) if float(bench.iloc[-n]) else 1.0
        return round(t / b, 4)
    except Exception:
        return 1.0


def _rs_trend(close: pd.Series, bench: pd.Series) -> str:
    """Is RS improving or deteriorating vs 4 weeks ago?"""
    try:
        rs_now  = _rs(close, bench, 63)
        rs_4wk  = _rs(close.iloc[:-20], bench.iloc[:-20], 63)
        if rs_now > rs_4wk * 1.01:
            return "↑ Improving"
        elif rs_now < rs_4wk * 0.99:
            return "↓ Weakening"
        return "→ Flat"
    except Exception:
        return "—"


def _is_live_bar(series) -> bool:
    """True when the last bar of `series` is today's still-forming session.

    Same predicate scanners/home.py uses to drop the partial bar. Here it is
    not used to drop anything -- the table deliberately shows live prices --
    but to LABEL them, so a number that moved since the last refresh is
    self-explanatory rather than looking like the scanner is unstable.
    """
    try:
        now_et = datetime.now(pytz.timezone("US/Eastern"))
        return (pd.Timestamp(series.index[-1]).date() == now_et.date()
                and now_et.weekday() < 5
                and (now_et.hour < 16))
    except Exception:
        return False


def _trade_idea(rs: float, rs_trend: str, rsi: float,
                above_sma50: bool, above_sma20: bool,
                vol_ratio: float, pct_above_ema9: float) -> str:
    """Return a trade suggestion for the sector ETF."""
    rotating_in  = rs > 1.02 and "Improving" in rs_trend
    rotating_out = rs < 0.98 and "Weakening" in rs_trend
    extended     = rsi > 68 or pct_above_ema9 > 6
    weak         = not above_sma50

    if rotating_out or weak:
        return "Avoid"
    if rotating_in and not extended and rsi >= 45:
        if pct_above_ema9 <= 3:
            return "LEAP / CSP"   # tight to support = great entry
        return "CSP"              # pulled back enough for put-selling
    if rotating_in and extended:
        return "Wait — Extended"
    if rs >= 1.0 and above_sma50 and rsi >= 45:
        return "Watch / CSP"
    return "Neutral"


def compute_row(ticker: str, name: str, close, volume, spy_close) -> dict | None:
    """Compute one sector row from price series that END on the bar being
    evaluated.

    Pulled out of run_sector_rotation() so history/backfill can replay the
    exact same maths on truncated series: pass `close.loc[:d]` and you get
    the row the live scan WOULD have produced on day d, with no second
    implementation to drift out of sync. Returns None if the series is too
    short to say anything meaningful.
    """
    if close is None or len(close) < 60:
        return None

    price = float(close.iloc[-1])
    sma20 = float(calc_sma(close, 20).iloc[-1])
    sma50 = float(calc_sma(close, 50).iloc[-1])
    ema9  = float(calc_ema(close, 9).iloc[-1])
    rsi   = float(calc_rsi(close))

    # Returns
    ret_1m = round((price / float(close.iloc[-21]) - 1) * 100, 1) if len(close) >= 21 else 0.0
    ret_3m = round((price / float(close.iloc[-63]) - 1) * 100, 1) if len(close) >= 63 else 0.0

    # Relative strength vs SPY, over both horizons.
    rs_val = _rs(close, spy_close) if spy_close is not None else 1.0
    rs_21  = _rs(close, spy_close, 21) if spy_close is not None else 1.0
    rs_10  = _rs(close, spy_close, 10) if spy_close is not None else 1.0
    rs_dir = _rs_trend(close, spy_close) if spy_close is not None else "—"

    # RRG quadrant, same rule as home.py's _sector_flows() so the Market
    # Overview tab can label its history in the vocabulary already on that
    # page (Leading/Improving/...) rather than the trade-action vocabulary
    # this page uses. Two names for one state confuses more than it informs.
    quadrant = ("Leading"   if rs_val >= 1 and rs_21 >= 1 else
                "Weakening" if rs_val >= 1 else
                "Improving" if rs_21 >= 1 else "Lagging")

    # Volume. iloc[-2] deliberately: the final bar is the one being evaluated
    # and is still forming during market hours, so its volume is a partial
    # count that would read as artificially low.
    avg_vol   = float(volume.iloc[-21:-1].mean()) if (volume is not None and len(volume) >= 21) else 0
    cur_vol   = float(volume.iloc[-2]) if (volume is not None and len(volume) >= 2) else 0
    vol_ratio = round(cur_vol / avg_vol, 2) if avg_vol > 0 else 1.0

    pct_above_ema9 = round((price - ema9) / ema9 * 100, 1) if ema9 > 0 else 0

    idea = _trade_idea(
        rs_val, rs_dir, rsi,
        price > sma50, price > sma20,
        vol_ratio, pct_above_ema9,
    )

    return {
        "Ticker":      ticker,
        "Sector":      name,
        "Price":       round(price, 2),
        "1M Ret %":    ret_1m,
        "3M Ret %":    ret_3m,
        "RS vs SPY":   rs_val,
        "RS 21d":      rs_21,
        "RS 10d":      rs_10,
        "Quadrant":    quadrant,
        "RS Trend":    rs_dir,
        "RSI":         round(rsi, 1),
        "Vol Ratio":   vol_ratio,
        "vs EMA9":     pct_above_ema9,
        "vs SMA20":    round((price - sma20) / sma20 * 100, 1) if sma20 > 0 else 0,
        "vs SMA50":    round((price - sma50) / sma50 * 100, 1) if sma50 > 0 else 0,
        "above_sma50": price > sma50,
        "Trade Idea":  idea,
    }


def rank_rows(rows: list[dict]) -> pd.DataFrame:
    """Sort rows by RS descending and stamp a 1-based Rank column."""
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values("RS vs SPY", ascending=False).reset_index(drop=True)
    df.insert(0, "Rank", df.index + 1)
    return df


def run_sector_rotation(status_fn=None) -> tuple[pd.DataFrame, dict]:
    """
    Fetch data for all sector ETFs and SPY, compute RS + technicals.
    Returns (DataFrame sorted by RS desc, market_context dict).
    """
    spy_df = get_price_history("SPY", period="1y", interval="1d")
    spy_close = spy_df["Close"].squeeze() if spy_df is not None and not spy_df.empty else None

    rows = []
    total = len(SECTORS)

    for i, (ticker, name) in enumerate(SECTORS):
        if status_fn:
            status_fn(i, total, ticker)
        try:
            df = get_price_history(ticker, period="1y", interval="1d")
            if df is None or df.empty or len(df) < 60:
                continue

            close  = df["Close"].squeeze()
            volume = df["Volume"].squeeze() if "Volume" in df.columns else None

            row = compute_row(ticker, name, close, volume, spy_close)
            if row:
                rows.append(row)
        except Exception:
            continue

    df_out = rank_rows(rows)

    # Market context from SPY
    mkt = {}
    if spy_close is not None and len(spy_close) >= 50:
        spy_sma50  = float(calc_sma(spy_close, 50).iloc[-1])
        spy_sma200 = float(calc_sma(spy_close, 200).iloc[-1]) if len(spy_close) >= 200 else spy_sma50
        spy_rsi    = float(calc_rsi(spy_close))
        spy_price  = float(spy_close.iloc[-1])
        mkt = {
            "spy_price":    round(spy_price, 2),
            "spy_sma50":    round(spy_sma50, 2),
            "spy_sma200":   round(spy_sma200, 2),
            "spy_rsi":      round(spy_rsi, 1),
            "bull_market":  spy_price > spy_sma200,
            "above_sma50":  spy_price > spy_sma50,
        }
        # The as-of date of the last bar, and whether that bar is still
        # forming. Everything on this page is computed off close.iloc[-1],
        # so when that bar is live the whole table moves with the tape --
        # which is exactly why two refreshes an hour apart disagree.
        try:
            mkt["as_of"] = pd.Timestamp(spy_close.index[-1]).strftime("%Y-%m-%d")
        except Exception:
            mkt["as_of"] = ""
        mkt["live_bar"] = _is_live_bar(spy_close)

    return df_out, mkt


# ── Render ─────────────────────────────────────────────────────────────────────

def render_sector_rotation():
    from config import (
        GOLD, BG_CARD, BG_PANEL, BG_DARK,
        ACCENT_GREEN, ACCENT_RED, ACCENT_BLUE,
        TEXT_PRIMARY, TEXT_MUTED, BORDER_COLOR,
    )
    G  = ACCENT_GREEN
    GL = GOLD
    R  = ACCENT_RED
    B  = ACCENT_BLUE

    # ── Header ────────────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="background:linear-gradient(135deg,{GL}10,{B}08);'
        f'border:1px solid {GL}44;border-radius:12px;padding:14px 20px;margin-bottom:14px">'
        f'<div style="color:{GL};font-size:14px;font-weight:700;margin-bottom:4px">'
        f'📊 Sector Rotation — Where Is Institutional Money Moving?</div>'
        f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.7">'
        f'Ranks all 11 SPDR sectors by <b style="color:#fff">Relative Strength vs SPY</b> '
        f'(3-month return ratio). Rising RS + price above SMA50 + volume expansion = '
        f'institutional rotation <b style="color:{G}">IN</b>. '
        f'Falling RS + below SMA50 = rotation <b style="color:{R}">OUT</b>.'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    # ── Controls ──────────────────────────────────────────────────────────────
    run_col, clear_col, _ = st.columns([1, 1, 4])
    with run_col:
        run_btn = st.button("▶ Run Scan", type="primary",
                            use_container_width=True, key="sr_run")
    with clear_col:
        if st.button("🔄 Clear", use_container_width=True, key="sr_clear"):
            st.session_state.pop("sr_df", None)
            st.session_state.pop("sr_mkt", None)
            st.session_state.pop("sr_ts", None)
            try:
                from data_loader import get_price_history, _PROC_PRICE_CACHE
                get_price_history.clear()
                _PROC_PRICE_CACHE.clear()
            except Exception:
                pass
            st.rerun()

    if st.session_state.get("sr_ts"):
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:11px;margin-top:2px">'
            f'Last scan: {st.session_state["sr_ts"]}</div>',
            unsafe_allow_html=True,
        )

    # ── Run ───────────────────────────────────────────────────────────────────
    if run_btn:
        prog = st.progress(0, text="Fetching sector data…")
        stat = st.empty()

        def _status(i, n, tk):
            prog.progress((i + 1) / n, text=f"Fetching {tk} ({i+1}/{n})")
            stat.markdown(
                f'<div style="color:{TEXT_MUTED};font-size:11px">📡 {tk}</div>',
                unsafe_allow_html=True,
            )

        df, mkt = run_sector_rotation(status_fn=_status)
        prog.empty(); stat.empty()

        st.session_state["sr_df"]  = df
        st.session_state["sr_mkt"] = mkt
        st.session_state["sr_ts"]  = pd.Timestamp.now().strftime("%b %d %Y  %I:%M %p")
        st.rerun()

    if "sr_df" not in st.session_state:
        st.markdown(
            f'<div style="border:1px dashed {BORDER_COLOR};border-radius:10px;'
            f'padding:40px;text-align:center;color:{TEXT_MUTED}">'
            f'Press <b style="color:{GL}">▶ Run Scan</b> to load sector rotation data'
            f'</div>',
            unsafe_allow_html=True,
        )
        return

    df  = st.session_state["sr_df"]
    mkt = st.session_state.get("sr_mkt", {})

    if df.empty:
        st.warning("No data returned — check network connection.")
        return

    # ── Market context banner ─────────────────────────────────────────────────
    if mkt:
        bull   = mkt.get("bull_market", True)
        mk_col = G if bull else R
        mk_lbl = "🟢 Bull Market (SPY above SMA200)" if bull else "🔴 Bear Market (SPY below SMA200)"
        a50    = mkt.get("above_sma50", True)
        a50_lbl= "above SMA50 ✓" if a50 else "below SMA50 ⚠️"
        st.markdown(
            f'<div style="display:flex;gap:12px;align-items:center;margin-bottom:12px;flex-wrap:wrap">'
            f'<span style="background:{mk_col}18;color:{mk_col};border:1px solid {mk_col}44;'
            f'font-size:11px;font-weight:700;padding:4px 14px;border-radius:20px">'
            f'{mk_lbl}</span>'
            f'<span style="color:{TEXT_MUTED};font-size:11px">'
            f'SPY ${mkt["spy_price"]} · RSI {mkt["spy_rsi"]} · {a50_lbl}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── Data freshness ──────────────────────────────────────────────
    # Every figure below is computed off the LAST bar. During market hours
    # that bar is still forming, so the table legitimately moves with the
    # tape -- the single most common reason two refreshes disagree. Say so
    # on the page rather than leaving it to be inferred.
    live = bool(mkt.get("live_bar"))
    as_of = mkt.get("as_of", "")
    fr_col = GL if live else G
    fr_lbl = ("⚡ LIVE BAR — today's session is still open, so these numbers "
              "move with the tape") if live else \
             "✓ Settled close — these numbers are fixed until the next session"
    st.markdown(
        f'<div style="background:{fr_col}12;border-left:3px solid {fr_col};'
        f'padding:6px 12px;border-radius:0 6px 6px 0;margin-bottom:12px;'
        f'color:{TEXT_MUTED};font-size:11px">'
        f'<b style="color:{fr_col}">{fr_lbl}</b>'
        + (f' · last bar {as_of}' if as_of else '')
        + '</div>',
        unsafe_allow_html=True,
    )

    # History for the Δ column: yesterday's settled ranking, replayed from
    # the same price series the live scan used (no extra network calls).
    hist = _sector_history_cached(as_of=as_of)
    deltas = {}
    if not hist.empty:
        try:
            from scanners.sector_history import rank_deltas
            deltas = rank_deltas(hist, df)
        except Exception:
            deltas = {}

    # ── Rotation Table ────────────────────────────────────────────────────────
    _IDEA_STYLE = {
        "LEAP / CSP":     (G,        "🚀"),
        "CSP":            (GL,       "💰"),
        "Watch / CSP":    (GL,       "👀"),
        "Wait — Extended":(TEXT_MUTED,"⏳"),
        "Neutral":        (TEXT_MUTED,"—"),
        "Avoid":          (R,        "🚫"),
    }

    _HD = (f'background:{BG_PANEL};color:{TEXT_MUTED};font-size:9px;font-weight:700;'
           f'text-transform:uppercase;letter-spacing:0.7px;padding:8px 12px;'
           f'border-bottom:2px solid {GL}44;white-space:nowrap;text-align:left')
    hdr = "".join(f'<th style="{_HD}">{c}</th>' for c in [
        "#", "Δ", "Sector", "Price", "1M Ret", "3M Ret",
        "RS vs SPY", "RS Trend", "RSI", "Vol Ratio",
        "vs EMA9", "vs SMA50", "Trade Idea",
    ])

    rows_html = ""
    for i, row in df.iterrows():
        bg    = BG_CARD if i % 2 == 0 else BG_PANEL
        rs    = row["RS vs SPY"]
        rs_col= G if rs >= 1.03 else (R if rs < 0.97 else TEXT_MUTED)

        ret1m = row["1M Ret %"]
        ret3m = row["3M Ret %"]
        r1_col= G if ret1m >= 0 else R
        r3_col= G if ret3m >= 0 else R

        rsi_v = row["RSI"]
        rsi_col = G if 50 <= rsi_v <= 65 else (GL if 45 <= rsi_v < 50 or 65 < rsi_v <= 70 else R)

        vr    = row["Vol Ratio"]
        vr_col= G if vr >= 1.2 else (GL if vr >= 0.8 else TEXT_MUTED)

        ema9g  = row["vs EMA9"]
        e9_col = G if ema9g <= 3 else (GL if ema9g <= 6 else R)

        s50g   = row["vs SMA50"]
        s50_col= G if s50g >= 0 else R

        rs_trend = row["RS Trend"]
        rt_col   = G if "Improving" in rs_trend else (R if "Weakening" in rs_trend else TEXT_MUTED)

        idea     = row["Trade Idea"]
        i_col, i_icon = _IDEA_STYLE.get(idea, (TEXT_MUTED, "—"))

        # Δ vs the prior settled close. Blank when there is no history for
        # this ticker yet; "–" when the rank did not move at all.
        dlt = deltas.get(row["Ticker"])
        if dlt is None:
            d_txt, d_col = "", TEXT_MUTED
        elif dlt > 0:
            d_txt, d_col = f'▲{dlt}', G
        elif dlt < 0:
            d_txt, d_col = f'▼{abs(dlt)}', R
        else:
            d_txt, d_col = "–", TEXT_MUTED

        td = f'background:{bg};padding:8px 12px;font-size:12px'
        rows_html += (
            f'<tr>'
            f'<td style="{td};color:{TEXT_MUTED};font-family:\'DM Mono\',monospace">'
            f'{int(row["Rank"]) if "Rank" in row else i + 1}</td>'
            f'<td style="{td};color:{d_col};font-size:10px;font-weight:700">{d_txt}</td>'
            f'<td style="{td};white-space:nowrap">'
            f'<span style="color:{GL};font-family:\'DM Mono\',monospace;font-weight:700">'
            f'{row["Ticker"]}</span>'
            f'<span style="color:{TEXT_MUTED};font-size:10px"> {row["Sector"]}</span></td>'
            f'<td style="{td};font-family:\'DM Mono\',monospace;color:{TEXT_PRIMARY}">'
            f'${row["Price"]}</td>'
            f'<td style="{td};color:{r1_col};font-weight:700">{ret1m:+.1f}%</td>'
            f'<td style="{td};color:{r3_col};font-weight:700">{ret3m:+.1f}%</td>'
            f'<td style="{td};color:{rs_col};font-weight:700">{rs:.3f}</td>'
            f'<td style="{td};color:{rt_col}">{rs_trend}</td>'
            f'<td style="{td};color:{rsi_col};font-weight:700">{rsi_v}</td>'
            f'<td style="{td};color:{vr_col}">{vr}×</td>'
            f'<td style="{td};color:{e9_col}">{ema9g:+.1f}%</td>'
            f'<td style="{td};color:{s50_col}">{s50g:+.1f}%</td>'
            f'<td style="{td};white-space:nowrap">'
            f'<span style="background:{i_col}22;color:{i_col};border:1px solid {i_col}44;'
            f'font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px">'
            f'{i_icon} {idea}</span></td>'
            f'</tr>'
        )

    st.markdown(
        f'<div style="overflow-x:auto;border-radius:8px;border:1px solid {GL}33;margin-bottom:18px">'
        f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
        f'<thead><tr>{hdr}</tr></thead><tbody>{rows_html}</tbody>'
        f'</table></div>',
        unsafe_allow_html=True,
    )
    if deltas:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:10px;margin:-12px 0 16px">'
            f'<b>Δ</b> = rank change vs the prior settled close (▲ = moved up the '
            f'leaderboard). See <b>Rotation History</b> below for how much of that '
            f'movement is signal and how much is noise.</div>',
            unsafe_allow_html=True,
        )

    # ── Trade Ideas Summary ────────────────────────────────────────────────────
    leap_csp = df[df["Trade Idea"].isin(["LEAP / CSP", "CSP"])].head(4)
    avoid    = df[df["Trade Idea"] == "Avoid"]

    c1, c2 = st.columns(2)

    with c1:
        st.markdown(
            f'<div style="color:{G};font-size:12px;font-weight:700;'
            f'text-transform:uppercase;letter-spacing:0.8px;margin-bottom:8px">'
            f'🎯 Best Sectors for Options / LEAPs</div>',
            unsafe_allow_html=True,
        )
        if leap_csp.empty:
            st.markdown(f'<div style="color:{TEXT_MUTED};font-size:12px">No strong setups right now</div>',
                        unsafe_allow_html=True)
        else:
            for _, row in leap_csp.iterrows():
                idea     = row["Trade Idea"]
                i_col, _ = _IDEA_STYLE.get(idea, (TEXT_MUTED, "—"))
                pct_ema9 = row["vs EMA9"]
                entry_note = (
                    f'tight to EMA9 ({pct_ema9:+.1f}%) → <b style="color:{G}">LEAP or CSP</b>'
                    if pct_ema9 <= 3 else
                    f'{pct_ema9:+.1f}% above EMA9 → <b style="color:{GL}">CSP only</b>'
                )
                st.markdown(
                    f'<div style="background:{BG_PANEL};border-left:3px solid {i_col};'
                    f'padding:8px 12px;margin-bottom:6px;border-radius:0 6px 6px 0">'
                    f'<span style="color:{GL};font-weight:700">{row["Ticker"]}</span> '
                    f'<span style="color:{TEXT_MUTED};font-size:10px">{row["Sector"]}</span><br>'
                    f'<span style="color:{TEXT_MUTED};font-size:11px">'
                    f'RS {row["RS vs SPY"]:.3f} · {row["RS Trend"]} · RSI {row["RSI"]} · {entry_note}'
                    f'</span></div>',
                    unsafe_allow_html=True,
                )

    with c2:
        st.markdown(
            f'<div style="color:{R};font-size:12px;font-weight:700;'
            f'text-transform:uppercase;letter-spacing:0.8px;margin-bottom:8px">'
            f'🚫 Avoid — Money Rotating Out</div>',
            unsafe_allow_html=True,
        )
        if avoid.empty:
            st.markdown(f'<div style="color:{TEXT_MUTED};font-size:12px">No sectors clearly rotating out</div>',
                        unsafe_allow_html=True)
        else:
            for _, row in avoid.iterrows():
                st.markdown(
                    f'<div style="background:{BG_PANEL};border-left:3px solid {R};'
                    f'padding:8px 12px;margin-bottom:6px;border-radius:0 6px 6px 0">'
                    f'<span style="color:{R};font-weight:700">{row["Ticker"]}</span> '
                    f'<span style="color:{TEXT_MUTED};font-size:10px">{row["Sector"]}</span><br>'
                    f'<span style="color:{TEXT_MUTED};font-size:11px">'
                    f'RS {row["RS vs SPY"]:.3f} · {row["RS Trend"]} · '
                    f'{"below SMA50" if not row["above_sma50"] else "RSI " + str(row["RSI"])}'
                    f'</span></div>',
                    unsafe_allow_html=True,
                )

    # ── History & Validation ──────────────────────────────────────────────────
    _render_history_panel(df, hist)
    _render_validation_panel(df)

    # ── How to Read Guide ─────────────────────────────────────────────────────
    with st.expander("📖 How to Read & Use This — Practical Rotation Trading Guide"):
        st.markdown(
            f"""
**What is Sector Rotation?**
Institutional money constantly moves between sectors based on economic expectations.
When financials lead and utilities lag, it signals economic confidence (risk-on).
When utilities lead and tech lags, money is moving to safety (risk-off).

---

**Reading the Table**

| Column | What it tells you |
|---|---|
| **RS vs SPY** | > 1.00 = outperforming SPY · < 1.00 = underperforming. > 1.03 = strong leader |
| **RS Trend** | Is relative strength improving or weakening vs 4 weeks ago? |
| **vs EMA9** | How far above 9-day EMA. ≤ 3% = tight to support = good entry zone |
| **vs SMA50** | Positive = above 50-day MA (uptrend). Negative = below (avoid) |
| **Vol Ratio** | > 1.2× = institutional accumulation. < 0.8× = low interest |

---

**Trade Rules**

🚀 **LEAP** — Sector ETF has strong RS + RSI 45-65 + price within 3% of EMA9
> Buy a deep ITM call (delta 0.70+) 12-18 months out. Trend is in, ride it.

💰 **CSP** — Sector ETF above SMA50 + RS improving + RSI not overbought
> Sell a put 5-8% below market, 3-4 weeks out. Collect premium in a rising sector.

👀 **Watch/CSP** — RS neutral but positive trend, above SMA50
> Watch for confirmation or sell smaller CSP positions.

🚫 **Avoid** — RS declining + below SMA50
> No positions. If already holding, tighten stops.

---

**Classic Rotation Patterns**

- **XLF leading + XLU lagging** → Economic optimism, risk-on → favor XLK, XLY, XLF
- **XLU + XLP leading** → Defensive rotation, risk-off → reduce position size, raise cash
- **XLE spiking** → Oil shock or energy leadership → commodity plays
- **XLK making new RS highs** → Tech bull run → QQQ, TQQQ, tech LEAPs

---

**Quick Rule of Thumb**
> Top 3 sectors by RS + improving trend + RSI < 68 = your watch list for the week.
> Any of those within 3% of their EMA9 = your entry list.
            """,
            unsafe_allow_html=True,
        )


# ── History & stability panel ──────────────────────────────────────────────────

DEFAULT_HISTORY_SESSIONS = 120


@st.cache_data(ttl=3600, show_spinner=False)
def _sector_history_cached(sessions: int = DEFAULT_HISTORY_SESSIONS,
                           as_of: str = "") -> pd.DataFrame:
    """The rotation table replayed over the last `sessions` settled closes.

    `as_of` is not read — it is the cache key that makes this recompute when
    the underlying bars roll to a new date, and only then. The price series
    come from get_price_history, which the live scan has already cached, so
    this costs CPU rather than network.
    """
    from scanners.sector_history import backfill_from_prices

    try:
        spy_df = get_price_history("SPY", period="1y", interval="1d")
        if spy_df is None or spy_df.empty:
            return pd.DataFrame()
        spy_close = spy_df["Close"].squeeze()

        price_map = {}
        for ticker, _ in SECTORS:
            df = get_price_history(ticker, period="1y", interval="1d")
            if df is not None and not df.empty:
                price_map[ticker] = df

        return backfill_from_prices(price_map, spy_close, SECTORS, sessions=sessions)
    except Exception:
        return pd.DataFrame()


def _stored_history() -> pd.DataFrame:
    """Committed post-close snapshots, if the daily job has written any."""
    try:
        from scanners.sector_history import load_snapshots, snapshots_to_frame
        return snapshots_to_frame(load_snapshots())
    except Exception:
        return pd.DataFrame()


def _render_history_panel(df: pd.DataFrame, hist: pd.DataFrame,
                          label_col: str = "Trade Idea"):
    """Rotation over time: is the leaderboard actually churning, or does it
    only look that way because every refresh lands on a different moment of
    the same session?

    label_col picks the verdict vocabulary — "Trade Idea" (LEAP / CSP /
    Avoid) on the Strategies page, "Quadrant" (Leading / Improving /
    Weakening / Lagging) on Market Overview, which already speaks that
    language in the card above this panel.
    """
    from config import (
        GOLD, BG_CARD, BG_PANEL, ACCENT_GREEN, ACCENT_RED,
        TEXT_PRIMARY, TEXT_MUTED, BORDER_COLOR,
    )
    G, GL, R = ACCENT_GREEN, GOLD, ACCENT_RED

    from scanners.sector_history import (
        churn_summary, leadership_spells, stability_report,
    )

    with st.expander("📈 Rotation History — how fast does this table really change?",
                     expanded=False):
        if hist is None or hist.empty:
            st.markdown(
                f'<div style="color:{TEXT_MUTED};font-size:12px">'
                f'Not enough price history to rebuild the timeline. Run the scan '
                f'again once SPY and the sector ETFs have returned a full year of bars.'
                f'</div>',
                unsafe_allow_html=True,
            )
            return

        dates = sorted(hist["Date"].unique())
        stored = _stored_history()

        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.7;margin-bottom:12px">'
            f'Every point below is a <b style="color:{TEXT_PRIMARY}">settled close</b>, '
            f'so it is a like-for-like comparison — unlike two intraday refreshes, which '
            f'differ because the last bar is still forming, not because anything rotated. '
            f'Rebuilt from the same price series the scan above uses, covering '
            f'<b style="color:{GL}">{len(dates)} sessions</b> '
            f'({dates[0]} → {dates[-1]}).'
            + (f' <b style="color:{G}">{stored["Date"].nunique()} committed snapshots</b> '
               f'on disk agree independently.' if not stored.empty else '')
            + '</div>',
            unsafe_allow_html=True,
        )

        # ── The headline answer, in numbers ──────────────────────────────
        if label_col not in hist.columns:
            label_col = "Trade Idea"
        label_noun = "Quadrant" if label_col == "Quadrant" else "Trade Idea"

        # Plain-English guide. A raw <details> block rather than st.expander:
        # this panel is ALREADY inside an expander and Streamlit refuses to
        # nest them, so the collapsible has to be HTML.
        _n = len(SECTORS)
        st.markdown(
            f'<details style="background:{BG_PANEL};border:1px solid {GL}33;'
            f'border-radius:8px;padding:8px 12px;margin-bottom:14px">'
            f'<summary style="color:{GL};font-size:11px;font-weight:700;cursor:pointer;'
            f'text-transform:uppercase;letter-spacing:0.7px">'
            f'📖 How to read these two tables</summary>'

            f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.75;margin-top:10px">'

            f'<b style="color:{TEXT_PRIMARY}">Rank trail</b> — each day the {_n} sectors '
            f'are sorted by relative strength vs SPY and numbered '
            f'<b style="color:{G}">1</b> (strongest) to '
            f'<b style="color:{R}">{_n}</b> (weakest). Rows are sectors, columns are '
            f'trading days (oldest left, newest right). Colours are just those ranks '
            f'banded: <span style="color:{G}">green = 1-3</span>, '
            f'<span style="color:{GL}">gold = 4-6</span>, grey = middle, '
            f'<span style="color:{R}">red = bottom 3</span>.'

            f'<div style="margin:8px 0 8px 10px;color:{TEXT_MUTED}">'
            f'· <b style="color:{TEXT_PRIMARY}">flat and low</b> (2 2 1 2 3) = durable '
            f'leadership, tradeable<br>'
            f'· <b style="color:{TEXT_PRIMARY}">flat and high</b> (13 14 15 14) = genuinely '
            f'broken, stay away<br>'
            f'· <b style="color:{TEXT_PRIMARY}">zig-zag</b> (3 11 5 12 4) = noise, one day\'s '
            f'reading means nothing<br>'
            f'· <b style="color:{TEXT_PRIMARY}">trending</b> (12 10 9 7 5 3) = money rotating '
            f'IN — the one to watch</div>'

            f'A single snapshot cannot tell "rank 3 and climbing for six weeks" from '
            f'"rank 3 for one day by accident". That is what this grid is for.'

            f'<div style="height:10px"></div>'

            f'<b style="color:{TEXT_PRIMARY}">Per-sector stability</b> — the same data '
            f'summarised per sector instead of per day.'
            f'<div style="margin:8px 0 8px 10px">'
            f'· <b style="color:{TEXT_PRIMARY}">Avg Rank</b> — its average spot. Lower is '
            f'better; under 5 = consistently strong.<br>'
            f'· <b style="color:{TEXT_PRIMARY}">Best / Worst</b> — the range it covered. '
            f'Best 1 / Worst 14 is a rollercoaster, not leadership.<br>'
            f'· <b style="color:{TEXT_PRIMARY}">Rank Churn</b> — places moved on an average '
            f'day. <span style="color:{G}">≤1 = steady</span>; '
            f'<span style="color:{R}">&gt;2 = jumpy</span>, do not trust one reading.<br>'
            f'· <b style="color:{TEXT_PRIMARY}">{label_noun} Flips / Hold</b> — how often the '
            f'label changed, and how many sessions it survives on average. '
            f'<span style="color:{G}">≥5 = solid</span>; '
            f'<span style="color:{R}">&lt;3 = a hint, not an instruction</span>.<br>'
            f'· <b style="color:{TEXT_PRIMARY}">Streak</b> — days the current label has held. '
            f'A 15-day streak is far more confirmed than a 1-day one.</div>'

            f'<div style="background:{G}12;border-left:3px solid {G};padding:7px 11px;'
            f'border-radius:0 6px 6px 0;color:{TEXT_PRIMARY};margin-top:4px">'
            f'<b>The rule:</b> favour sectors with a <b style="color:{G}">low Avg Rank</b> '
            f'AND <b style="color:{G}">low Rank Churn</b>. Low rank alone can be a one-day '
            f'fluke; low churn alone just means reliably mediocre. You want consistently '
            f'near the top and not bouncing. Then use <b>Streak</b> as the confidence '
            f'check.</div>'

            f'</div></details>',
            unsafe_allow_html=True,
        )

        churn = churn_summary(hist, top_n=3, label_col=label_col)
        if churn:
            chips = [
                ("Top-3 changed", f'{churn["top_turnover_pct"]:.0f}% of sessions',
                 G if churn["top_turnover_pct"] < 25 else GL),
                ("#1 changed hands", f'{churn["leader_changes"]}× in {churn["sessions"]}', GL),
                ("Median daily rank move", f'{churn["median_rank_move"]:.1f} places',
                 G if churn["median_rank_move"] <= 1 else GL),
                (f"{label_noun} flipped", f'{churn["idea_change_pct"]:.0f}% of days',
                 G if churn["idea_change_pct"] < 20 else R),
            ]
            st.markdown(
                '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px">'
                + "".join(
                    f'<div style="background:{BG_PANEL};border:1px solid {c}33;'
                    f'border-radius:8px;padding:8px 14px;min-width:130px">'
                    f'<div style="color:{TEXT_MUTED};font-size:9px;text-transform:uppercase;'
                    f'letter-spacing:0.6px">{label}</div>'
                    f'<div style="color:{c};font-size:14px;font-weight:700;'
                    f'font-family:\'DM Mono\',monospace">{val}</div></div>'
                    for label, val, c in chips
                )
                + "</div>",
                unsafe_allow_html=True,
            )

            verdict = (
                "Stable — day-to-day movement is mostly noise around a steady "
                "leadership order. What you see changing between refreshes is the "
                "live bar, not rotation."
                if churn["median_rank_move"] <= 1 and churn["top_turnover_pct"] < 25 else
                "Genuinely rotating — leadership really is turning over at this pace, "
                "so the changes between sessions are signal, not just the live bar."
            )
            st.markdown(
                f'<div style="background:{BG_PANEL};border-left:3px solid {GL};'
                f'padding:8px 12px;border-radius:0 6px 6px 0;margin-bottom:16px;'
                f'color:{TEXT_PRIMARY};font-size:12px">{verdict}</div>',
                unsafe_allow_html=True,
            )

        # ── Rank trail ───────────────────────────────────────────────────
        n_show = min(24, len(dates))
        trail_dates = dates[-n_show:]
        order = (df["Ticker"].tolist() if not df.empty
                 else hist[hist["Date"] == dates[-1]].sort_values("Rank")["Ticker"].tolist())

        pivot = (hist[hist["Date"].isin(trail_dates)]
                 .pivot_table(index="Ticker", columns="Date", values="Rank"))

        def _rank_col(v):
            if pd.isna(v):
                return TEXT_MUTED
            if v <= 3:
                return G
            if v <= 6:
                return GL
            if v >= len(order) - 2:
                return R
            return TEXT_MUTED

        _TH = (f'background:{BG_PANEL};color:{TEXT_MUTED};font-size:8px;font-weight:700;'
               f'padding:5px 4px;border-bottom:2px solid {GL}44;white-space:nowrap')
        head = f'<th style="{_TH};text-align:left;padding-left:10px">Sector</th>' + "".join(
            f'<th style="{_TH}">{d[5:]}</th>' for d in trail_dates
        )

        body = ""
        for i, tkr in enumerate(order):
            if tkr not in pivot.index:
                continue
            bg = BG_CARD if i % 2 == 0 else BG_PANEL
            cells = ""
            for d in trail_dates:
                v = pivot.at[tkr, d] if d in pivot.columns else float("nan")
                c = _rank_col(v)
                txt = "·" if pd.isna(v) else f"{int(v)}"
                cells += (f'<td style="background:{bg};color:{c};font-size:10px;'
                          f'text-align:center;padding:5px 4px;'
                          f'font-family:\'DM Mono\',monospace">{txt}</td>')
            body += (f'<tr><td style="background:{bg};padding:5px 10px;font-size:11px;'
                     f'white-space:nowrap;color:{GL};font-weight:700;'
                     f'font-family:\'DM Mono\',monospace">{tkr}</td>{cells}</tr>')

        st.markdown(
            f'<div style="color:{GL};font-size:11px;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:0.8px;margin-bottom:6px">Rank trail — last {n_show} sessions</div>'
            f'<div style="overflow-x:auto;border:1px solid {GL}33;border-radius:8px;margin-bottom:6px">'
            f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
            f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
            f'<div style="color:{TEXT_MUTED};font-size:10px;margin-bottom:16px">'
            f'Each cell is that sector\'s RS rank on that close. Flat rows = durable '
            f'leadership. Rows that zig-zag through the middle are the ones where a '
            f'single day\'s reading means little.</div>',
            unsafe_allow_html=True,
        )

        # ── RS trend chart for the current leaders ───────────────────────
        try:
            import plotly.graph_objects as go

            leaders = order[:5]
            fig = go.Figure()
            palette = [GL, G, "#60A5FA", "#A78BFA", "#F59E0B"]
            for j, tkr in enumerate(leaders):
                g = hist[hist["Ticker"] == tkr].sort_values("Date")
                if g.empty:
                    continue
                fig.add_trace(go.Scatter(
                    x=g["Date"], y=g["RS vs SPY"], mode="lines", name=tkr,
                    line=dict(color=palette[j % len(palette)], width=2),
                    hovertemplate=f"<b>{tkr}</b><br>%{{x}}<br>RS %{{y:.3f}}<extra></extra>",
                ))
            fig.add_hline(y=1.0, line=dict(color=TEXT_MUTED, width=1, dash="dot"))
            fig.update_layout(
                title=dict(text="Relative strength vs SPY — current top 5",
                           font=dict(color=GOLD, size=13, family="Cormorant Garamond"),
                           x=0.01, y=0.95),
                paper_bgcolor=BG_CARD, plot_bgcolor=BG_CARD, height=300,
                margin=dict(l=8, r=8, t=44, b=8),
                xaxis=dict(showgrid=False, color=TEXT_MUTED, tickfont=dict(size=9)),
                yaxis=dict(showgrid=True, gridcolor=BORDER_COLOR, color=TEXT_MUTED,
                           tickfont=dict(size=10, family="DM Mono")),
                legend=dict(font=dict(color=TEXT_MUTED, size=10), bgcolor=BG_CARD,
                            orientation="h", y=-0.15),
            )
            st.plotly_chart(fig, use_container_width=True)
            st.markdown(
                f'<div style="color:{TEXT_MUTED};font-size:10px;margin:-8px 0 16px">'
                f'A line grinding steadily above 1.00 is real leadership. A line '
                f'crossing 1.00 repeatedly is a sector the RS column will keep '
                f'reclassifying no matter how good the data is.</div>',
                unsafe_allow_html=True,
            )
        except Exception:
            pass

        # ── Per-sector stability ─────────────────────────────────────────
        rep = stability_report(hist, label_col=label_col)
        if not rep.empty:
            _TH2 = (f'background:{BG_PANEL};color:{TEXT_MUTED};font-size:9px;font-weight:700;'
                    f'text-transform:uppercase;letter-spacing:0.7px;padding:7px 10px;'
                    f'border-bottom:2px solid {GL}44;white-space:nowrap;text-align:left')
            cols = ["Sector", "Avg Rank", "Best", "Worst", "Rank Churn",
                    f"{label_noun} Flips", f"{label_noun} Hold",
                    f"Current {label_noun}", "Streak"]
            h2 = "".join(f'<th style="{_TH2}">{c}</th>' for c in cols)
            b2 = ""
            for i, r in rep.iterrows():
                bg = BG_CARD if i % 2 == 0 else BG_PANEL
                td = f'background:{bg};padding:7px 10px;font-size:11px'
                churn_col = G if r["Rank Churn"] <= 1 else (GL if r["Rank Churn"] <= 2 else R)
                hold_col = G if r["Idea Hold"] >= 5 else (GL if r["Idea Hold"] >= 3 else R)
                b2 += (
                    f'<tr>'
                    f'<td style="{td};white-space:nowrap">'
                    f'<span style="color:{GL};font-weight:700;'
                    f'font-family:\'DM Mono\',monospace">{r["Ticker"]}</span>'
                    f'<span style="color:{TEXT_MUTED};font-size:10px"> {r["Sector"]}</span></td>'
                    f'<td style="{td};color:{TEXT_PRIMARY}">{r["Avg Rank"]}</td>'
                    f'<td style="{td};color:{G}">{r["Best"]}</td>'
                    f'<td style="{td};color:{R}">{r["Worst"]}</td>'
                    f'<td style="{td};color:{churn_col};font-weight:700">{r["Rank Churn"]}</td>'
                    f'<td style="{td};color:{TEXT_MUTED}">{r["Idea Flips"]}</td>'
                    f'<td style="{td};color:{hold_col};font-weight:700">{r["Idea Hold"]}d</td>'
                    f'<td style="{td};color:{TEXT_PRIMARY};font-size:10px">{r["Current Idea"]}</td>'
                    f'<td style="{td};color:{TEXT_MUTED}">{r["Current Streak"]}d</td>'
                    f'</tr>'
                )
            st.markdown(
                f'<div style="color:{GL};font-size:11px;font-weight:700;text-transform:uppercase;'
                f'letter-spacing:0.8px;margin-bottom:6px">Per-sector stability</div>'
                f'<div style="overflow-x:auto;border:1px solid {GL}33;border-radius:8px">'
                f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
                f'<thead><tr>{h2}</tr></thead><tbody>{b2}</tbody></table></div>'
                f'<div style="color:{TEXT_MUTED};font-size:10px;margin:6px 0 16px">'
                f'<b>Rank Churn</b> = average places moved per session. '
                f'<b>{label_noun} Hold</b> = how many sessions a {label_noun} survives on '
                f'average — anything under 3 is a label to treat as a hint, not an '
                f'instruction.</div>',
                unsafe_allow_html=True,
            )

        # ── Leadership spells ────────────────────────────────────────────
        spells = [s for s in leadership_spells(hist, top_n=3) if s["sessions"] >= 2][:8]
        if spells:
            items = ""
            for s in spells:
                col = G if s["ongoing"] else TEXT_MUTED
                tail = "ongoing" if s["ongoing"] else f'ended {s["end"]}'
                items += (
                    f'<div style="background:{BG_PANEL};border-left:3px solid {col};'
                    f'padding:6px 12px;margin-bottom:5px;border-radius:0 6px 6px 0;'
                    f'font-size:11px;color:{TEXT_MUTED}">'
                    f'<b style="color:{GL}">{s["ticker"]}</b> held a top-3 slot for '
                    f'<b style="color:{col}">{s["sessions"]} sessions</b> '
                    f'from {s["start"]} · {tail}</div>'
                )
            st.markdown(
                f'<div style="color:{GL};font-size:11px;font-weight:700;text-transform:uppercase;'
                f'letter-spacing:0.8px;margin-bottom:6px">Leadership spells (top 3)</div>'
                + items
                + f'<div style="color:{TEXT_MUTED};font-size:10px;margin-top:6px">'
                  f'A two-session spell and a two-month spell look identical in a single '
                  f'snapshot. This is where you tell them apart.</div>',
                unsafe_allow_html=True,
            )


# ── Validation panel ───────────────────────────────────────────────────────────

def _render_validation_panel(df: pd.DataFrame, key_prefix: str = "sr"):
    """Cross-check the table against an independent price feed, and list the
    published references worth eyeballing.

    key_prefix namespaces the button and the stored results: this panel is
    rendered from two different pages (Strategies and Home), and Streamlit
    raises DuplicateWidgetID if two buttons share a key.
    """
    from config import (
        GOLD, BG_CARD, BG_PANEL, ACCENT_GREEN, ACCENT_RED, ACCENT_BLUE,
        TEXT_PRIMARY, TEXT_MUTED,
    )
    G, GL, R, B = ACCENT_GREEN, GOLD, ACCENT_RED, ACCENT_BLUE

    from scanners.sector_validate import (
        RANK_CORR_MIN, SOURCES, cross_check, self_checks,
    )

    with st.expander("🔍 Validate — cross-check against independent sources", expanded=False):
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.7;margin-bottom:12px">'
            f'Everything on this page comes from one feed (Yahoo Finance), and SPY is the '
            f'denominator of every RS figure — so a single bad SPY bar quietly skews all '
            f'15 rows at once. Two layers of checking: '
            f'<b style="color:{TEXT_PRIMARY}">self-checks</b> below run automatically and '
            f'need no other provider, and the button re-pulls the same tickers from '
            f'<b style="color:{TEXT_PRIMARY}">Stooq</b>, an unrelated provider, to '
            f'recompute the leaderboard from scratch.</div>',
            unsafe_allow_html=True,
        )

        # ── Self-checks: always available ────────────────────────────────
        # These used to be absent, so when Stooq was unreachable the panel
        # had nothing at all to say. They test arithmetic that must hold
        # regardless of who supplied the prices, so they work offline.
        try:
            ours_now = {}
            for ticker, _ in SECTORS + [("SPY", "Benchmark")]:
                d = get_price_history(ticker, period="1y", interval="1d")
                if d is not None and not d.empty:
                    ours_now[ticker] = d["Close"].squeeze()
            checks = self_checks(ours_now, SECTORS, bench="SPY")
        except Exception as e:
            checks = [{"name": "Self-checks", "status": "fail",
                       "detail": f"could not run: {e}"}]

        _S_COL = {"pass": (G, "✓"), "warn": (GL, "!"), "fail": (R, "✕")}
        n_fail = sum(1 for c in checks if c["status"] == "fail")
        n_warn = sum(1 for c in checks if c["status"] == "warn")
        head_col = R if n_fail else (GL if n_warn else G)
        head_txt = ("✓ All self-checks passed" if not (n_fail or n_warn) else
                    f'{n_fail} failed · {n_warn} warning(s)')
        rows_html = ""
        for c in checks:
            col, icon = _S_COL.get(c["status"], (TEXT_MUTED, "·"))
            rows_html += (
                f'<div style="display:flex;gap:8px;align-items:baseline;'
                f'padding:4px 0;font-size:11px">'
                f'<span style="color:{col};font-weight:700;width:12px">{icon}</span>'
                f'<span style="color:{TEXT_PRIMARY};min-width:210px">{c["name"]}</span>'
                f'<span style="color:{TEXT_MUTED}">{c["detail"]}</span></div>'
            )
        st.markdown(
            f'<div style="background:{BG_PANEL};border-left:3px solid {head_col};'
            f'padding:8px 12px;border-radius:0 6px 6px 0;margin-bottom:14px">'
            f'<div style="color:{head_col};font-size:11px;font-weight:700;'
            f'text-transform:uppercase;letter-spacing:0.7px;margin-bottom:4px">'
            f'Self-checks — {head_txt}</div>{rows_html}</div>',
            unsafe_allow_html=True,
        )

        if st.button("🔍 Run independent check", key=f"{key_prefix}_validate",
                     use_container_width=False):
            prog = st.progress(0, text="Fetching reference data…")

            def _st(i, n, tk):
                prog.progress((i + 1) / n, text=f"Reference: {tk} ({i+1}/{n})")

            ours = {}
            for ticker, _ in SECTORS + [("SPY", "Benchmark")]:
                try:
                    d = get_price_history(ticker, period="1y", interval="1d")
                    if d is not None and not d.empty:
                        ours[ticker] = d["Close"].squeeze()
                except Exception:
                    continue

            vdf, vsum = cross_check(ours, SECTORS, bench="SPY", progress_fn=_st)
            prog.empty()
            st.session_state[f"{key_prefix}_val_df"] = vdf
            st.session_state[f"{key_prefix}_val_sum"] = vsum

        vdf = st.session_state.get(f"{key_prefix}_val_df")
        vsum = st.session_state.get(f"{key_prefix}_val_sum") or {}

        if vsum.get("status") == "unreachable":
            why = vsum.get("reasons") or []
            st.markdown(
                f'<div style="background:{GL}12;border-left:3px solid {GL};'
                f'padding:8px 12px;border-radius:0 6px 6px 0;margin-bottom:12px;'
                f'font-size:11px;line-height:1.7;color:{TEXT_MUTED}">'
                f'<b style="color:{GL}">Independent cross-check unavailable.</b> '
                f'{vsum.get("message", "")}'
                + (('<div style="margin-top:6px;color:' + TEXT_PRIMARY
                    + ';font-family:\'DM Mono\',monospace;font-size:10px">'
                    # ESCAPE. These strings are server-controlled response
                    # bodies, and this block renders with unsafe_allow_html.
                    # Unescaped, an HTML block page renders as markup instead
                    # of text: the diagnostic came out blank and an unclosed
                    # tag swallowed the reason after it.
                    + "<br>".join(_html.escape(str(w)) for w in why[:4])
                    + '</div>') if why else '')
                + (f'<div style="margin-top:6px">Stooq blocks datacenter IP ranges, '
                   f'which is what this app runs on — so this means <b>Stooq refused '
                   f'us</b>, not that the host lacks outbound network (the price feed '
                   f'on this same page works). '
                   f'To turn the cross-check on, add a free '
                   f'<a href="https://www.tiingo.com/" target="_blank" '
                   f'style="color:{GL}">Tiingo</a> key to the app\'s secrets as '
                   f'<code style="color:{TEXT_PRIMARY}">[reference]</code> '
                   f'<code style="color:{TEXT_PRIMARY}">tiingo = "..."</code> — it '
                   f'serves datacenter IPs and is dividend-adjusted like our own '
                   f'data.</div>'
                   if not vsum.get("keyed") else
                   f'<div style="margin-top:6px">A Tiingo key <b>is</b> configured, so '
                   f'this is a key or quota problem rather than a blocked host — check '
                   f'the value and the daily request limit.</div>')
                + f'<div style="margin-top:6px">The self-checks above are unaffected, '
                  f'and the published references below still apply.</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        elif vdf is not None and not vdf.empty:
            corr = vsum.get("rank_corr")
            ok = vsum.get("rank_ok")
            hdr_col = G if ok else R
            corr_txt = f'{corr:.3f}' if corr is not None else "n/a"
            st.markdown(
                f'<div style="background:{hdr_col}12;border-left:3px solid {hdr_col};'
                f'padding:8px 12px;border-radius:0 6px 6px 0;margin-bottom:12px;font-size:12px">'
                f'<b style="color:{hdr_col}">'
                f'{"✓ Leaderboard confirmed" if ok else "⚠️ Leaderboard disagrees"}</b>'
                f'<span style="color:{TEXT_MUTED}"> — rank correlation with '
                f'<b style="color:{TEXT_PRIMARY}">{vsum.get("source", "the reference feed")}</b> '
                f'is <b style="color:{TEXT_PRIMARY}">{corr_txt}</b> '
                f'(need ≥ {RANK_CORR_MIN}); '
                f'{vsum.get("top3_overlap", 0)}/3 of the top three match; '
                f'{vsum.get("confirmed", 0)}/{vsum.get("checked", 0)} rows agree on price '
                f'and 3-month return as of {vsum.get("as_of", "—")}.</span></div>',
                unsafe_allow_html=True,
            )

            _TH = (f'background:{BG_PANEL};color:{TEXT_MUTED};font-size:9px;font-weight:700;'
                   f'text-transform:uppercase;letter-spacing:0.7px;padding:7px 10px;'
                   f'border-bottom:2px solid {GL}44;white-space:nowrap;text-align:left')
            cols = ["Sector", "Status", "Our Close", "Reference", "Δ Price %",
                    "Our 3M %", "Ref 3M %", "Δ pts", "Our RS", "Ref RS"]
            head = "".join(f'<th style="{_TH}">{c}</th>' for c in cols)

            body = ""
            for i, r in vdf.iterrows():
                bg = BG_CARD if i % 2 == 0 else BG_PANEL
                td = f'background:{bg};padding:7px 10px;font-size:11px'
                s_col = {"Confirmed": G, "Price mismatch": R,
                         "Return drift": GL}.get(r["Status"], TEXT_MUTED)
                fmt = lambda v, suf="": "—" if v is None or pd.isna(v) else f"{v}{suf}"
                body += (
                    f'<tr>'
                    f'<td style="{td};white-space:nowrap">'
                    f'<span style="color:{GL};font-weight:700;'
                    f'font-family:\'DM Mono\',monospace">{r["Ticker"]}</span></td>'
                    f'<td style="{td};color:{s_col};font-weight:700;font-size:10px">'
                    f'{r["Status"]}</td>'
                    f'<td style="{td};color:{TEXT_PRIMARY};'
                    f'font-family:\'DM Mono\',monospace">{fmt(r["Ours"])}</td>'
                    f'<td style="{td};color:{TEXT_MUTED};'
                    f'font-family:\'DM Mono\',monospace">{fmt(r["Reference"])}</td>'
                    f'<td style="{td};color:{s_col}">{fmt(r["Δ Price %"], "%")}</td>'
                    f'<td style="{td};color:{TEXT_PRIMARY}">{fmt(r["Ours 3M %"], "%")}</td>'
                    f'<td style="{td};color:{TEXT_MUTED}">{fmt(r["Ref 3M %"], "%")}</td>'
                    f'<td style="{td};color:{TEXT_MUTED}">{fmt(r["Δ 3M pts"])}</td>'
                    f'<td style="{td};color:{TEXT_PRIMARY}">{fmt(r["Ours RS"])}</td>'
                    f'<td style="{td};color:{TEXT_MUTED}">{fmt(r["Ref RS"])}</td>'
                    f'</tr>'
                )

            st.markdown(
                f'<div style="overflow-x:auto;border:1px solid {GL}33;border-radius:8px">'
                f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
                f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
                f'<div style="color:{TEXT_MUTED};font-size:10px;margin:6px 0 16px;line-height:1.6">'
                + ('Both feeds are dividend-adjusted here, so the 3-month returns should '
                   'line up closely and a gap is a real difference. '
                   if vsum.get("div_adjusted") else
                   'Our closes are dividend-adjusted; this reference feed\'s are not — so '
                   'our 3-month return reading <b>slightly higher</b> (about a quarter\'s '
                   'yield, more on XLU / XLP / XLRE) is agreement, not drift. ')
                + f'''<b style="color:{TEXT_PRIMARY}">Δ Price %</b> is the check that should be '
                f'<b style="color:{TEXT_PRIMARY}">Δ Price %</b> is the check that should be '
                f'near zero: it compares the same close on the same date.</div>''',
                unsafe_allow_html=True,
            )

        # ── Published references ─────────────────────────────────────────
        st.markdown(
            f'<div style="color:{GL};font-size:11px;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:0.8px;margin:4px 0 8px">Published references</div>',
            unsafe_allow_html=True,
        )
        for s in SOURCES:
            st.markdown(
                f'<div style="background:{BG_PANEL};border-left:3px solid {B};'
                f'padding:8px 12px;margin-bottom:6px;border-radius:0 6px 6px 0">'
                f'<a href="{s["url"]}" target="_blank" '
                f'style="color:{GL};font-weight:700;font-size:12px;text-decoration:none">'
                f'{s["name"]} ↗</a>'
                f'<div style="color:{TEXT_PRIMARY};font-size:11px;margin-top:2px">'
                f'Checks: {s["check"]}</div>'
                f'<div style="color:{TEXT_MUTED};font-size:10px;line-height:1.6;margin-top:2px">'
                f'{s["note"]}</div></div>',
                unsafe_allow_html=True,
            )

        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:10px;line-height:1.7;margin-top:10px">'
            f'<b style="color:{TEXT_PRIMARY}">Comparing by hand?</b> Match the basis first. '
            f'Published "1 month" is almost always a calendar month and this page\'s is '
            f'21 trading days; published returns are usually total return (dividends in) '
            f'and RS here is a 63-session price ratio. Compare the <b>ordering</b> of the '
            f'sectors rather than the decimals — that is the part that has to agree.</div>',
            unsafe_allow_html=True,
        )
