"""
scanners/sector_rotation.py — Sector Rotation Scanner

Tracks the 11 SPDR sector ETFs + key macro ETFs ranked by Relative Strength vs SPY.
Rising RS + price above SMA50 + volume expansion = institutional rotation IN.
Declining RS + price below SMA50 = rotation OUT.

Trade guidance:
  Rotating IN  + RSI 45-65 + near EMA9 → CSP or LEAP candidate
  Rotating OUT + below SMA50            → avoid / let it base
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st
import sys, os
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

            price     = float(close.iloc[-1])
            sma20     = float(calc_sma(close, 20).iloc[-1])
            sma50     = float(calc_sma(close, 50).iloc[-1])
            ema9      = float(calc_ema(close, 9).iloc[-1])
            rsi       = float(calc_rsi(close))

            # Returns
            ret_1m  = round((price / float(close.iloc[-21]) - 1) * 100, 1) if len(close) >= 21 else 0.0
            ret_3m  = round((price / float(close.iloc[-63]) - 1) * 100, 1) if len(close) >= 63 else 0.0

            # Relative strength vs SPY
            rs_val  = _rs(close, spy_close) if spy_close is not None else 1.0
            rs_dir  = _rs_trend(close, spy_close) if spy_close is not None else "—"

            # Volume
            avg_vol  = float(volume.iloc[-21:-1].mean()) if (volume is not None and len(volume) >= 21) else 0
            cur_vol  = float(volume.iloc[-2]) if (volume is not None and len(volume) >= 2) else 0
            vol_ratio = round(cur_vol / avg_vol, 2) if avg_vol > 0 else 1.0

            pct_above_ema9 = round((price - ema9) / ema9 * 100, 1) if ema9 > 0 else 0

            idea = _trade_idea(
                rs_val, rs_dir, rsi,
                price > sma50, price > sma20,
                vol_ratio, pct_above_ema9
            )

            rows.append({
                "Ticker":       ticker,
                "Sector":       name,
                "Price":        round(price, 2),
                "1M Ret %":     ret_1m,
                "3M Ret %":     ret_3m,
                "RS vs SPY":    rs_val,
                "RS Trend":     rs_dir,
                "RSI":          round(rsi, 1),
                "Vol Ratio":    vol_ratio,
                "vs EMA9":      pct_above_ema9,
                "vs SMA20":     round((price - sma20) / sma20 * 100, 1) if sma20 > 0 else 0,
                "vs SMA50":     round((price - sma50) / sma50 * 100, 1) if sma50 > 0 else 0,
                "above_sma50":  price > sma50,
                "Trade Idea":   idea,
            })
        except Exception:
            continue

    df_out = pd.DataFrame(rows)
    if not df_out.empty:
        df_out = df_out.sort_values("RS vs SPY", ascending=False).reset_index(drop=True)

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
        "Sector", "Price", "1M Ret", "3M Ret",
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

        td = f'background:{bg};padding:8px 12px;font-size:12px'
        rows_html += (
            f'<tr>'
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
