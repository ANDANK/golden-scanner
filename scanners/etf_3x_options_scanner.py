# scanners/etf_3x_options_scanner.py — 3× ETF premium richness
#
# Rewritten to answer a different question. The old page picked one expiry and
# one strike near delta 0.20 and reported that contract. Two problems: the
# contract is not the decision (you pick that in your broker with a live
# chain in front of you), and the "IV Rank" gating the whole thing was
# utils.approx_iv_rank(), a fixed 10-80% scale identical for every ticker —
# see scanners/option_premium.py for why that scored a dead-calm SOXL at 74.
#
# This asks: WHICH TICKER is being paid unusually well right now, versus its
# own normal? Strikes and expiries are still read from the chain — you cannot
# price a premium without them — but they are measurement inputs, not output.
#
# Long 3x only. The inverse funds (SQQQ, SOXS, TZA...) rise on the days these
# fall, so mixing them into one "falling day + rich premium" list puts two
# opposite setups under one heading.

import streamlit as st
import pandas as pd
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import *
from utils import *
from data_loader import get_price_history, get_options_chain
from scanners import iv_history
from scanners.option_premium import (
    DROP_ATR_NOTABLE, IV_RV_FAIR, IV_RV_RICH, RV_WINDOW,
    assess, atr_move, chain_snapshot, iv_rv_ratio, pick_expiry, realized_vol,
)

# Long 3× ETFs with real options liquidity. LABU is kept despite thinner
# chains because biotech IV behaves differently from the index funds and is
# often the richest name on the board; the spread check will flag it when its
# chain is too wide to be worth writing.
LONG_3X = [
    ("TQQQ", "Nasdaq 100 3×"),
    ("SOXL", "Semiconductors 3×"),
    ("UPRO", "S&P 500 3×"),
    ("TECL", "Technology 3×"),
    ("FAS",  "Financials 3×"),
    ("TNA",  "Small Caps 3×"),
    ("LABU", "Biotech 3×"),
]


def scan_3x_premium(tickers, dte_min=21, dte_max=45, min_iv_rv=1.10,
                    falling_only=False, status_fn=None):
    """One row per ticker describing how rich its premium is right now."""
    rows, skips = [], {}
    # Loaded once for the whole scan rather than per ticker: the store is one
    # small JSON per session and re-reading it 7 times is pure waste.
    snaps = iv_history.load_snapshots()

    def skip(reason):
        skips[reason] = skips.get(reason, 0) + 1

    for i, (ticker, name) in enumerate(tickers):
        if status_fn:
            status_fn(i, len(tickers), ticker)
        try:
            df = get_price_history(ticker, period="6mo")
            if df is None or df.empty or len(df) < 60:
                skip("no price history")
                continue

            close = df["Close"].squeeze()
            price = float(close.iloc[-1])
            rv = realized_vol(close, RV_WINDOW)
            if rv <= 0:
                skip("could not measure realised volatility")
                continue

            chg_pct, drop_atr = atr_move(df)
            if falling_only and chg_pct >= 0:
                skip("not down today")
                continue

            sma50 = float(calc_sma(close, 50).iloc[-1])
            sma50_pct = round((price - sma50) / sma50 * 100, 1) if sma50 > 0 else None
            rsi = float(calc_rsi(close))

            _, _, expiries = get_options_chain(ticker)
            if not expiries:
                skip("no options chain")
                continue
            exp, dte = pick_expiry(expiries, dte_min, dte_max)
            if not exp:
                skip("no usable expiry")
                continue

            _, puts, _ = get_options_chain(ticker, exp)
            snap = chain_snapshot(puts, price, dte)
            # ATM is the stable reference for richness; fall back to the OTM
            # put reading when the ATM strike has no IV quote.
            iv = snap["iv_atm"] or snap["iv_otm"]
            if not iv:
                skip("no implied volatility in chain")
                continue

            ratio = iv_rv_ratio(iv, rv)
            if ratio is None or ratio < min_iv_rv:
                skip(f"premium not rich enough (<{min_iv_rv:.2f}×)")
                continue

            # A real IV rank once enough sessions are stored; None until
            # then, so assess() stays silent rather than inventing one.
            rk = iv_history.rank_for(ticker, iv, snapshots=snaps)
            verdict = assess(iv, rv, drop_atr, rk["rank"], snap["spread_pct"],
                             sma50_pct, rsi)

            # Selling premium and buying it are opposite trades on the same
            # number: cheap IV is what makes a LEAP attractive.
            if ratio >= IV_RV_RICH:
                side = "Sell premium (CSP)"
            elif ratio <= 0.95:
                side = "Buy premium (LEAP)"
            else:
                side = "Neither is compelling"

            rows.append({
                "Ticker":    ticker,
                "Name":      name,
                "Price":     round(price, 2),
                "Chg %":     chg_pct,
                "Drop ATR":  drop_atr,
                "IV":        round(iv * 100, 1),
                "RV":        round(rv * 100, 1),
                "IV/RV":     ratio,
                "Skew":      round(snap["skew"] * 100, 1) if snap["skew"] is not None else None,
                "Ann Prem %": snap["ann_pct"],
                "Spread %":  snap["spread_pct"],
                "OI":        snap["open_interest"],
                "RSI":       round(rsi, 1),
                "vs SMA50":  sma50_pct,
                "IV Rank":   rk["rank"],
                "IV Pctile": rk["percentile"],
                "IV Days":   rk["sessions"],
                "Verdict":   verdict["verdict"],
                "Score":     verdict["score"],
                "Why":       " · ".join(verdict["reasons"]),
                "Side":      side,
            })
        except Exception:
            skip("error while scanning")
            continue

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values("Score", ascending=False).reset_index(drop=True)
    return out, skips


# ── Render ─────────────────────────────────────────────────────────────────────

_VERDICT_STYLE = {
    "Prime CSP":     (ACCENT_GREEN, "🎯"),
    "Rich premium":  (GOLD,         "💰"),
    "Fair":          (TEXT_MUTED,   "—"),
    "Thin":          (TEXT_MUTED,   "·"),
    "Illiquid":      (ACCENT_RED,   "🚧"),
    "Avoid — knife": (ACCENT_RED,   "🔪"),
    "No data":       (TEXT_MUTED,   "?"),
}


def render():
    section_header("⚡📈", "3× ETF Premium Richness",
                   "Which leveraged ETF is paying unusually well right now — "
                   "measured against its own normal, not a fixed scale")

    with st.sidebar:
        st.markdown(f'<div style="color:{GOLD};font-size:12px;font-weight:600;'
                    f'margin:16px 0 8px">⚙️ 3× Premium Filters</div>',
                    unsafe_allow_html=True)
        min_iv_rv = st.slider("Min richness (IV ÷ realised vol)", 0.80, 2.00, 1.10, 0.05,
                              help="1.00 = options priced at the recent realised move. "
                                   "1.30+ is genuinely rich.")
        dte_min, dte_max = st.slider("Measurement horizon (days)", 7, 90, (21, 45),
                                     help="Which part of the curve to read the premium "
                                          "from. Not a recommended expiry.")
        falling_only = st.checkbox("Only tickers down today", value=False,
                                   help="Your setup: a fall bids up put premium.")

    st.markdown(
        f'<div style="background:linear-gradient(135deg,{GOLD}10,{ACCENT_BLUE}08);'
        f'border:1px solid {GOLD}44;border-radius:12px;padding:12px 18px;margin-bottom:12px;'
        f'color:{TEXT_MUTED};font-size:11px;line-height:1.75">'
        f'<b style="color:{GOLD}">No strikes, no expiries.</b> This ranks '
        f'<b style="color:{TEXT_PRIMARY}">tickers</b> by how far their option premium sits '
        f'above what the ETF has actually been doing — the part you cannot see in a broker '
        f'chain. Pick the contract there, once you know which name is worth writing.'
        f'<div style="margin-top:6px">The key number is '
        f'<b style="color:{TEXT_PRIMARY}">IV/RV</b>: implied volatility divided by realised. '
        f'{IV_RV_FAIR:.2f}× is mildly above fair, <b>{IV_RV_RICH:.2f}×+ is rich</b>. It is '
        f'comparable across tickers, which a raw IV number never is — 60% IV is cheap for '
        f'SOXL and extraordinary for SPY.</div></div>',
        unsafe_allow_html=True,
    )

    st.info("⏱ Reads a live option chain per ticker — 30–90 seconds.")

    c1, _ = st.columns([1, 5])
    with c1:
        run = st.button("▶ Run Scan", use_container_width=True, key="x3_run")

    if run:
        prog = st.progress(0, text="Reading chains…")

        def _status(i, n, tk):
            prog.progress((i + 1) / n, text=f"{tk} ({i+1}/{n})")

        df, skips = scan_3x_premium(LONG_3X, dte_min, dte_max, min_iv_rv,
                                    falling_only, status_fn=_status)
        prog.empty()
        st.session_state["_3x_prem"] = df
        st.session_state["_3x_skips"] = skips

    df = st.session_state.get("_3x_prem")
    skips = st.session_state.get("_3x_skips") or {}

    if df is None:
        st.markdown(
            f'<div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};'
            f'border-radius:8px;padding:30px;text-align:center;color:{TEXT_MUTED}">'
            f'<div style="font-size:36px;margin-bottom:12px">⚡</div>'
            f'<div style="font-size:16px;color:{TEXT_PRIMARY};margin-bottom:8px">'
            f'3× ETF Premium Richness</div>'
            f'<div style="font-size:13px">Press <b style="color:{GOLD}">▶ Run Scan</b>. '
            f'Long 3× funds only — the inverse ones rise on the days these fall.</div>'
            f'</div>', unsafe_allow_html=True)
        return

    if skips:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:11px;margin:4px 0">'
            f'ℹ️ Skipped: ' + " · ".join(f"{r}: {n}" for r, n in
                                          sorted(skips.items(), key=lambda x: -x[1]))
            + '</div>', unsafe_allow_html=True)

    if df.empty:
        empty_state("Nothing rich enough right now. Lower the richness filter, "
                    "or wait for a down day — that is when put premium gets bid up.")
        return

    prime = df[df["Verdict"] == "Prime CSP"]
    rich = df[df["Verdict"].isin(["Prime CSP", "Rich premium"])]
    c1, c2, c3, c4 = st.columns(4)
    with c1: metric_card("Scanned", str(len(df)), color=GOLD)
    with c2: metric_card("Rich premium", str(len(rich)), color=ACCENT_GREEN)
    with c3: metric_card("Prime setups", str(len(prime)), color=ACCENT_GREEN)
    with c4: metric_card("Best IV/RV", f'{df["IV/RV"].max():.2f}×', color=ACCENT_BLUE)

    # Read once, before anything that branches on it: the status banner above
    # the table and the optional IV Rank column below it must agree.
    cov = iv_history.coverage()

    if cov["ready"]:
        st.markdown(
            f'<div style="background:{ACCENT_GREEN}12;border-left:3px solid {ACCENT_GREEN};'
            f'padding:7px 12px;border-radius:0 6px 6px 0;margin:10px 0;'
            f'color:{TEXT_MUTED};font-size:11px">'
            f'<b style="color:{ACCENT_GREEN}">IV Rank is live</b> — '
            f'{cov["sessions"]} sessions stored ({cov["first"]} → {cov["last"]}). '
            f'Rank is IV against this ticker\'s OWN past year, which is stricter '
            f'than IV/RV: both must agree before a premium is genuinely unusual.</div>',
            unsafe_allow_html=True)
    else:
        st.markdown(
            f'<div style="background:{GOLD}12;border-left:3px solid {GOLD};'
            f'padding:7px 12px;border-radius:0 6px 6px 0;margin:10px 0;'
            f'color:{TEXT_MUTED};font-size:11px">'
            f'<b style="color:{GOLD}">IV Rank building — {cov["sessions"]} of '
            f'{iv_history.MIN_SESSIONS} sessions.</b> A daily job records IV after '
            f'each close; a rank from fewer sessions is not a weak rank, it is a '
            f'meaningless one, so no number is shown until the history is deep '
            f'enough. <b>IV/RV above works today</b> and carries the judgement '
            f'until then.</div>',
            unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    _TH = (f'background:{BG_PANEL};color:{TEXT_MUTED};font-size:9px;font-weight:700;'
           f'text-transform:uppercase;letter-spacing:0.7px;padding:8px 10px;'
           f'border-bottom:2px solid {GOLD}44;white-space:nowrap;text-align:left')
    cols = ["Ticker", "Verdict", "IV/RV", "Today", "IV", "Realised"]
    if cov["ready"]:
        cols.append("IV Rank")
    cols += ["Skew", "Ann Prem", "Spread", "RSI", "vs SMA50"]
    head = "".join(f'<th style="{_TH}">{c}</th>' for c in cols)

    def _fmt(v, suf="", dp=1):
        return "—" if v is None or (isinstance(v, float) and pd.isna(v)) else f"{v:.{dp}f}{suf}"

    body = ""
    for i, r in df.iterrows():
        bg = BG_CARD if i % 2 == 0 else BG_PANEL
        td = f'background:{bg};padding:8px 10px;font-size:11px'
        vcol, vicon = _VERDICT_STYLE.get(r["Verdict"], (TEXT_MUTED, "—"))
        rr = r["IV/RV"]
        r_col = ACCENT_GREEN if rr >= IV_RV_RICH else (GOLD if rr >= IV_RV_FAIR else TEXT_MUTED)
        d_col = ACCENT_RED if r["Chg %"] < 0 else ACCENT_GREEN
        sp = r["Spread %"]
        sp_col = ACCENT_GREEN if (sp is not None and sp <= 5) else (
            ACCENT_RED if (sp is not None and sp > 15) else TEXT_MUTED)
        s50 = r["vs SMA50"]
        s50_col = ACCENT_GREEN if (s50 is not None and s50 >= 0) else ACCENT_RED
        body += (
            f'<tr>'
            f'<td style="{td};white-space:nowrap">'
            f'<b style="color:{GOLD};font-family:\'DM Mono\',monospace">{r["Ticker"]}</b>'
            f'<span style="color:{TEXT_MUTED};font-size:10px"> {r["Name"]}</span></td>'
            f'<td style="{td};color:{vcol};font-weight:700;font-size:10px;white-space:nowrap">'
            f'{vicon} {r["Verdict"]}</td>'
            f'<td style="{td};color:{r_col};font-weight:700">{rr:.2f}×</td>'
            f'<td style="{td};color:{d_col};white-space:nowrap">{r["Chg %"]:+.1f}% '
            f'<span style="color:{TEXT_MUTED};font-size:10px">'
            f'({r["Drop ATR"]:+.1f} ATR)</span></td>'
            f'<td style="{td};color:{TEXT_PRIMARY}">{_fmt(r["IV"], "%")}</td>'
            f'<td style="{td};color:{TEXT_MUTED}">{_fmt(r["RV"], "%")}</td>'
            # Must mirror the header exactly: the column is present only when
            # the history is deep enough, and a mismatch here silently shifts
            # every value after it into the wrong column.
            + (f'<td style="{td};color:'
               f'{ACCENT_GREEN if (r["IV Rank"] or 0) >= 70 else TEXT_PRIMARY}">'
               f'{_fmt(r["IV Rank"], "", 0)}</td>' if cov["ready"] else "")
            + f'<td style="{td};color:{TEXT_MUTED}">{_fmt(r["Skew"], " pts")}</td>'
            f'<td style="{td};color:{ACCENT_GREEN}">{_fmt(r["Ann Prem %"], "%")}</td>'
            f'<td style="{td};color:{sp_col}">{_fmt(sp, "%")}</td>'
            f'<td style="{td};color:{TEXT_MUTED}">{_fmt(r["RSI"])}</td>'
            f'<td style="{td};color:{s50_col}">{_fmt(s50, "%")}</td>'
            f'</tr>'
        )

    st.markdown(
        f'<div style="overflow-x:auto;border:1px solid {GOLD}33;border-radius:8px">'
        f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
        f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>',
        unsafe_allow_html=True,
    )

    # Reasoning per ticker, so no verdict appears without its justification.
    st.markdown(
        f'<div style="color:{GOLD};font-size:11px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.8px;margin:16px 0 6px">Why each verdict</div>',
        unsafe_allow_html=True)
    for _, r in df.iterrows():
        vcol, vicon = _VERDICT_STYLE.get(r["Verdict"], (TEXT_MUTED, "—"))
        st.markdown(
            f'<div style="background:{BG_PANEL};border-left:3px solid {vcol};'
            f'padding:7px 12px;margin-bottom:5px;border-radius:0 6px 6px 0;font-size:11px">'
            f'<b style="color:{GOLD};font-family:\'DM Mono\',monospace">{r["Ticker"]}</b> '
            f'<span style="color:{vcol};font-weight:700">{vicon} {r["Verdict"]}</span> '
            f'<span style="color:{TEXT_MUTED}">— {r["Why"]}</span><br>'
            f'<span style="color:{TEXT_PRIMARY};font-size:10px">{r["Side"]}</span></div>',
            unsafe_allow_html=True)

    with st.expander("📖 How to read this — and what it will not tell you"):
        st.markdown(f"""
**IV/RV** — implied volatility ÷ what the ETF has actually delivered over the last
{RV_WINDOW} sessions. `1.00×` means options are priced at the recent move.
**`{IV_RV_RICH:.2f}×`+ means the market is charging well over recent damage** — that is
the condition worth selling into. Unlike a raw IV figure it is comparable across
tickers: 60% IV is cheap for SOXL and extraordinary for SPY.

**Today (± ATR)** — the fall in the ETF's own average daily range. `-2.0 ATR` is an
unusual day for anything; `-3%` means nothing on its own.

**Skew** — how much more the downside put costs than the at-the-money one, in IV
points. It widens when people pay up for protection, which is when a put seller is
paid best.

**Verdicts**

| | |
|---|---|
| 🎯 **Prime CSP** | Rich premium **and** a real drop **and** not below its 50-day |
| 💰 **Rich premium** | Premium is rich, but today was quiet — no urgency |
| 🔪 **Avoid — knife** | Rich premium *because* it is collapsing. Hard veto, whatever it pays |
| 🚧 **Illiquid** | Spread over 15% — the exit costs more than the edge |
| — **Fair / Thin** | Options priced at or below the recent move. Nothing to sell |

---

**What this does not tell you**

- **No IV Rank yet.** The strictly better measure is IV against *its own* past IV.
  Nothing was storing that, so it starts accumulating from the daily snapshot job —
  meaningful in about three months. Until then IV/RV carries the judgement alone.
- **Not a contract recommendation.** No strike, no expiry, by design. It reads a
  ~{dte_min}–{dte_max} day put to measure richness; pick your actual contract in your
  broker against a live chain.
- **Rich is not safe.** Premium is richest exactly when something is going wrong.
  The knife veto catches the obvious cases, not all of them.
        """)

    st.markdown(
        f'<div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};'
        f'border-left:3px solid {ACCENT_RED};border-radius:6px;padding:12px 16px;'
        f'margin-top:16px;color:{TEXT_MUTED};font-size:12px">'
        f'⚠️ <b>3× leveraged ETFs decay.</b> Volatility drag means they lose value over '
        f'time even when the index goes your way, so a cash-secured put here is a '
        f'premium-collection trade with an exit plan — not a position you want to be '
        f'assigned and hold. <b>Size very small.</b></div>',
        unsafe_allow_html=True)
