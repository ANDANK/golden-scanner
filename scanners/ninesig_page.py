# scanners/ninesig_page.py — 9Sig Plan (leveraged 60/40 TQQQ / AGG quarterly tracker)
#
# Strategy (from azqato.github.io/leveraged-strategies/9sig.html):
#   • 60% TQQQ / 40% AGG base allocation
#   • Signal line = prior quarter-end TQQQ × 1.09 + ½ of new contributions
#   • TQQQ above signal → sell surplus to AGG · below → buy shortfall from AGG
#   • New contributions go entirely to AGG; half is added to the signal line
#   • 90% throttle: a single buy may use at most 90% of the AGG balance
#   • 30-Down (skip next sell signals) and Spike Reset (force 60/40) are manual
#     toggles the user confirms at rebalance time (dollars-only, no price feed)
#
# Two modes:
#   A) Tracked Plan — start amount + date, quarterly contributions, saved history
#   B) Quick Calculator — enter current balances + prior TQQQ, get suggested split

from __future__ import annotations
import streamlit as st
from datetime import date
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    GOLD, BG_CARD, BG_PANEL, ACCENT_GREEN, ACCENT_RED, ACCENT_BLUE,
    TEXT_PRIMARY, TEXT_MUTED, BORDER_COLOR,
)
from scanners.gsheet_helper import (
    get_ninesig, add_ninesig_row, reset_ninesig, using_google_sheets,
)

TQQQ_TARGET = 0.60          # 60% TQQQ / 40% AGG
SIGNAL_GROWTH = 1.09        # 9% quarterly signal
THROTTLE = 0.90             # max 90% of bond balance on a single buy
BOND = "AGG"
CONTRIB_OPTIONS = [0, 2000, 3000, 4000, 5000]


# ── Helpers ────────────────────────────────────────────────────
def _money(x) -> str:
    try:
        return f"${float(x):,.0f}"
    except Exception:
        return "—"

def _f(x, default=0.0) -> float:
    try:
        return float(str(x).replace("$", "").replace(",", "").strip())
    except Exception:
        return default

def _quarter_start(d: date) -> date:
    m = ((d.month - 1) // 3) * 3 + 1
    return date(d.year, m, 1)

def _next_quarter_start(d: date) -> date:
    qs = _quarter_start(d)
    return date(qs.year + 1, 1, 1) if qs.month == 10 else date(qs.year, qs.month + 3, 1)


def _compute(prior_tqqq: float, contribution: float, tqqq_now: float, agg_now: float,
             skip_sell: bool = False, force_6040: bool = False) -> dict:
    """Core 9Sig rebalance math. Returns the suggested trade and resulting balances.
    trade > 0 = BUY TQQQ (move AGG→TQQQ) · trade < 0 = SELL TQQQ (move TQQQ→AGG)."""
    agg_c  = agg_now + contribution          # contributions go to bonds first
    signal = prior_tqqq * SIGNAL_GROWTH + 0.5 * contribution
    total  = tqqq_now + agg_c

    note = ""
    if force_6040:
        trade = TQQQ_TARGET * total - tqqq_now
        if trade > 0:                         # buy side honours throttle
            cap = THROTTLE * agg_c
            if trade > cap:
                trade = cap
                note = "90% throttle"
        action = "SPIKE RESET → 60/40"
    elif tqqq_now > signal:
        sell = tqqq_now - signal
        if skip_sell:
            trade, action = 0.0, "SELL skipped (30 Down)"
        else:
            trade, action = -sell, "SELL TQQQ → AGG"
    elif tqqq_now < signal:
        want = signal - tqqq_now
        cap  = THROTTLE * agg_c
        if want > cap:
            trade, note = cap, "90% throttle"
        else:
            trade = want
        action = "BUY AGG → TQQQ"
    else:
        trade, action = 0.0, "No trade"

    tqqq_after = tqqq_now + trade
    agg_after  = agg_c - trade
    tot_after  = tqqq_after + agg_after
    pct = (tqqq_after / tot_after * 100) if tot_after > 0 else 0.0

    return {
        "signal": signal, "action": action, "trade": trade, "note": note,
        "agg_with_contrib": agg_c, "tqqq_after": tqqq_after, "agg_after": agg_after,
        "total": tot_after, "tqqq_pct": pct,
    }


def _action_color(action: str) -> str:
    if action.startswith("BUY"):    return ACCENT_GREEN
    if action.startswith("SELL") and "skipped" not in action: return ACCENT_RED
    if action.startswith("SPIKE"):  return ACCENT_BLUE
    return TEXT_MUTED


def _trade_phrase(r: dict) -> str:
    t = r["trade"]
    if abs(t) < 1:
        return "No trade needed."
    if t > 0:
        return f"Buy <b style='color:{ACCENT_GREEN}'>{_money(t)}</b> of TQQQ (sell {_money(t)} {BOND})."
    return f"Sell <b style='color:{ACCENT_RED}'>{_money(-t)}</b> of TQQQ (buy {_money(-t)} {BOND})."


# ── Composition bar ────────────────────────────────────────────
def _comp_bar(tqqq: float, agg: float):
    total = tqqq + agg
    if total <= 0:
        return
    p = tqqq / total * 100
    drift = p - 60
    drift_c = ACCENT_GREEN if abs(drift) <= 5 else (GOLD if abs(drift) <= 12 else ACCENT_RED)
    st.markdown(
        f'<div style="margin:6px 0 14px">'
        f'<div style="display:flex;height:26px;border-radius:6px;overflow:hidden;'
        f'border:1px solid {BORDER_COLOR}">'
        f'<div style="width:{p:.1f}%;background:{ACCENT_BLUE}66;display:flex;align-items:center;'
        f'justify-content:center;color:{TEXT_PRIMARY};font-size:11px;font-weight:700">'
        f'TQQQ {p:.0f}%</div>'
        f'<div style="width:{100-p:.1f}%;background:{ACCENT_GREEN}44;display:flex;align-items:center;'
        f'justify-content:center;color:{TEXT_PRIMARY};font-size:11px;font-weight:700">'
        f'{BOND} {100-p:.0f}%</div></div>'
        f'<div style="color:{TEXT_MUTED};font-size:11px;margin-top:4px">'
        f'Total {_money(total)} · drift from 60/40 target: '
        f'<b style="color:{drift_c}">{drift:+.1f}%</b></div></div>',
        unsafe_allow_html=True,
    )


# ── What-if table ──────────────────────────────────────────────
def _whatif_table(prior_tqqq: float, tqqq_now: float, agg_now: float,
                  skip_sell: bool, force_6040: bool):
    th = (f'color:{TEXT_MUTED};font-size:10px;font-weight:700;text-transform:uppercase;'
          f'letter-spacing:.6px;padding:8px 12px;border-bottom:2px solid {GOLD}55;'
          f'background:{BG_PANEL};white-space:nowrap;text-align:right')
    th_l = th.replace("text-align:right", "text-align:left")
    hdr = (f'<th style="{th_l}">Contribution</th><th style="{th}">Signal Line</th>'
           f'<th style="{th}">Action</th><th style="{th}">Trade</th>'
           f'<th style="{th}">TQQQ After</th><th style="{th}">{BOND} After</th>'
           f'<th style="{th}">TQQQ %</th>')
    rows = ""
    for c in CONTRIB_OPTIONS:
        r = _compute(prior_tqqq, c, tqqq_now, agg_now, skip_sell, force_6040)
        ac = _action_color(r["action"])
        tcolor = ACCENT_GREEN if r["trade"] > 0 else (ACCENT_RED if r["trade"] < 0 else TEXT_MUTED)
        tstr = ("—" if abs(r["trade"]) < 1
                else (f"+{_money(r['trade'])}" if r["trade"] > 0 else f"−{_money(-r['trade'])}"))
        td = f'padding:7px 12px;border-bottom:1px solid {BORDER_COLOR}22;font-size:12px;text-align:right'
        td_l = td.replace("text-align:right", "text-align:left")
        rows += (
            f'<tr>'
            f'<td style="{td_l};color:{TEXT_PRIMARY};font-weight:700">{_money(c)}</td>'
            f'<td style="{td};color:{TEXT_PRIMARY}">{_money(r["signal"])}</td>'
            f'<td style="{td};color:{ac};font-weight:600">{r["action"]}</td>'
            f'<td style="{td};color:{tcolor};font-weight:700">{tstr}</td>'
            f'<td style="{td};color:{TEXT_PRIMARY}">{_money(r["tqqq_after"])}</td>'
            f'<td style="{td};color:{TEXT_PRIMARY}">{_money(r["agg_after"])}</td>'
            f'<td style="{td};color:{TEXT_MUTED}">{r["tqqq_pct"]:.0f}%</td>'
            f'</tr>'
        )
    st.markdown(
        f'<div style="overflow-x:auto;border-radius:8px;border:1px solid {BORDER_COLOR}44">'
        f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
        f'<thead><tr>{hdr}</tr></thead><tbody>{rows}</tbody></table></div>',
        unsafe_allow_html=True,
    )


# ── History ledger ─────────────────────────────────────────────
def _history_table(rows: list):
    cols = ["Date", "Event", "Contribution", "Signal_Line", "Action",
            "Trade_Amount", "TQQQ_After", "AGG_After", "Total", "TQQQ_Pct"]
    th = (f'color:{TEXT_MUTED};font-size:10px;font-weight:700;text-transform:uppercase;'
          f'letter-spacing:.6px;padding:7px 10px;border-bottom:2px solid {GOLD}55;'
          f'background:{BG_PANEL};white-space:nowrap')
    hdr = "".join(f'<th style="{th}">{c.replace("_"," ")}</th>' for c in cols)
    body = ""
    for i, r in enumerate(rows):
        bg = BG_CARD if i % 2 == 0 else BG_PANEL
        td = f'padding:6px 10px;border-bottom:1px solid {BORDER_COLOR}22;background:{bg};font-size:11px'
        ac = _action_color(str(r.get("Action", "")))
        cells = ""
        for c in cols:
            v = r.get(c, "")
            if c in ("Contribution", "Signal_Line", "Trade_Amount", "TQQQ_After", "AGG_After", "Total"):
                v = _money(v) if str(v).strip() not in ("", "nan", "None") else "—"
            elif c == "TQQQ_Pct" and str(v).strip() not in ("", "nan", "None"):
                v = f"{_f(v):.0f}%"
            color = ac if c == "Action" else TEXT_PRIMARY
            cells += f'<td style="{td};color:{color}">{v}</td>'
        body += f"<tr>{cells}</tr>"
    st.markdown(
        f'<div style="overflow-x:auto;border-radius:8px;border:1px solid {BORDER_COLOR}44">'
        f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
        f'<thead><tr>{hdr}</tr></thead><tbody>{body}</tbody></table></div>',
        unsafe_allow_html=True,
    )


# ── Mode A: Tracked Plan ───────────────────────────────────────
def _render_tracked():
    rows = get_ninesig() or []
    setup = next((r for r in rows if str(r.get("Event", "")).lower() == "setup"), None)

    # ── First-time setup ───────────────────────────────────────
    if setup is None:
        st.markdown(
            f'<div style="border-left:4px solid {GOLD};padding:10px 16px;'
            f'background:linear-gradient(90deg,{GOLD}18,{BG_PANEL});border-radius:0 8px 8px 0;'
            f'margin-bottom:14px"><span style="color:{TEXT_PRIMARY};font-size:13px;line-height:1.6">'
            f'No plan yet. Enter your start date and amount — the plan will open at the '
            f'<b>60% TQQQ / 40% {BOND}</b> target.</span></div>',
            unsafe_allow_html=True,
        )
        c1, c2 = st.columns(2)
        with c1:
            start_date = st.date_input("Start date", value=date.today(), key="ns_start_date")
        with c2:
            start_amt = st.number_input("Starting amount ($)", min_value=100.0,
                                        value=10000.0, step=500.0, key="ns_start_amt")
        tq, ag = TQQQ_TARGET * start_amt, (1 - TQQQ_TARGET) * start_amt
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:12px;margin:6px 0 10px">'
            f'Day-one split → <b style="color:{ACCENT_BLUE}">TQQQ {_money(tq)}</b> · '
            f'<b style="color:{ACCENT_GREEN}">{BOND} {_money(ag)}</b></div>',
            unsafe_allow_html=True,
        )
        if st.button("✅ Create Plan", type="primary", key="ns_create"):
            ok, msg = add_ninesig_row({
                "Date": str(start_date), "Event": "Setup", "Contribution": start_amt,
                "TQQQ_Before": 0, "AGG_Before": 0, "Signal_Line": "",
                "Action": "Initial 60/40", "Trade_Amount": 0,
                "TQQQ_After": round(tq, 2), "AGG_After": round(ag, 2),
                "Total": round(start_amt, 2), "TQQQ_Pct": round(TQQQ_TARGET * 100, 1),
                "Notes": "Plan created",
            })
            (st.success if ok else st.error)(msg)
            if ok:
                st.rerun()
        return

    # ── Existing plan ──────────────────────────────────────────
    last = rows[-1]
    prior_tqqq = _f(last.get("TQQQ_After"))
    last_agg   = _f(last.get("AGG_After"))
    last_date  = str(last.get("Date", ""))[:10]
    try:
        last_d = date.fromisoformat(last_date)
    except Exception:
        last_d = date.today()

    next_due = _next_quarter_start(last_d)
    overdue  = date.today() >= next_due
    due_c    = ACCENT_GREEN if overdue else TEXT_MUTED
    due_lbl  = (f"Rebalance DUE (quarter ended {next_due.isoformat()})" if overdue
               else f"Next rebalance: {next_due.isoformat()}")

    c1, c2, c3, c4 = st.columns(4)
    with c1: st.metric("Start", str(setup.get("Date", ""))[:10])
    with c2: st.metric("Last TQQQ balance", _money(prior_tqqq))
    with c3: st.metric(f"Last {BOND} balance", _money(last_agg))
    with c4: st.metric("Events logged", str(len(rows)))
    st.markdown(
        f'<div style="color:{due_c};font-size:12px;font-weight:600;margin:2px 0 12px">'
        f'⏱ {due_lbl}</div>', unsafe_allow_html=True,
    )

    st.markdown(
        f'<div style="color:{GOLD};font-size:13px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:1px;margin:6px 0 8px">Quarterly Rebalance</div>', unsafe_allow_html=True,
    )
    c1, c2 = st.columns(2)
    with c1:
        tqqq_now = st.number_input("Current TQQQ value ($)", min_value=0.0,
                                   value=round(prior_tqqq, 2), step=100.0, key="ns_tqqq_now")
    with c2:
        agg_now = st.number_input(f"Current {BOND} value ($, before this quarter's deposit)",
                                  min_value=0.0, value=round(last_agg, 2), step=100.0, key="ns_agg_now")
    t1, t2 = st.columns(2)
    with t1:
        skip_sell = st.checkbox("30-Down active — skip a SELL signal", value=False, key="ns_skip")
    with t2:
        force_6040 = st.checkbox("Spike Reset — force 60/40", value=False, key="ns_spike")

    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:12px;margin:10px 0 4px">'
        f'What-if — resulting rebalance by contribution amount (prior TQQQ = {_money(prior_tqqq)}):</div>',
        unsafe_allow_html=True,
    )
    _whatif_table(prior_tqqq, tqqq_now, agg_now, skip_sell, force_6040)

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    cc1, cc2 = st.columns([1, 1])
    with cc1:
        commit_contrib = st.number_input("Contribution to commit ($)", min_value=0.0,
                                         value=3000.0, step=500.0, key="ns_commit_contrib")
    chosen = _compute(prior_tqqq, commit_contrib, tqqq_now, agg_now, skip_sell, force_6040)
    ac = _action_color(chosen["action"])
    st.markdown(
        f'<div style="background:{BG_PANEL};border:1px solid {ac}55;border-left:4px solid {ac};'
        f'border-radius:0 8px 8px 0;padding:12px 16px;margin:8px 0">'
        f'<div style="color:{ac};font-size:13px;font-weight:700;margin-bottom:4px">{chosen["action"]}'
        f'{(" · " + chosen["note"]) if chosen["note"] else ""}</div>'
        f'<div style="color:{TEXT_PRIMARY};font-size:13px;line-height:1.7">{_trade_phrase(chosen)}<br>'
        f'Signal line: <b>{_money(chosen["signal"])}</b> · '
        f'After → TQQQ <b>{_money(chosen["tqqq_after"])}</b> / {BOND} <b>{_money(chosen["agg_after"])}</b> '
        f'(TQQQ {chosen["tqqq_pct"]:.0f}%) · Total <b>{_money(chosen["total"])}</b></div></div>',
        unsafe_allow_html=True,
    )
    if st.button("💾 Commit Rebalance", type="primary", key="ns_commit"):
        ok, msg = add_ninesig_row({
            "Date": str(date.today()), "Event": "Rebalance", "Contribution": round(commit_contrib, 2),
            "TQQQ_Before": round(tqqq_now, 2), "AGG_Before": round(agg_now, 2),
            "Signal_Line": round(chosen["signal"], 2), "Action": chosen["action"],
            "Trade_Amount": round(chosen["trade"], 2),
            "TQQQ_After": round(chosen["tqqq_after"], 2), "AGG_After": round(chosen["agg_after"], 2),
            "Total": round(chosen["total"], 2), "TQQQ_Pct": round(chosen["tqqq_pct"], 1),
            "Notes": chosen["note"],
        })
        (st.success if ok else st.error)(msg)
        if ok:
            st.rerun()

    # ── History ───────────────────────────────────────────────
    st.markdown(
        f'<div style="color:{GOLD};font-size:13px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:1px;margin:18px 0 8px">Plan History</div>', unsafe_allow_html=True,
    )
    _history_table(rows)

    with st.expander("⚠️ Danger zone — reset plan", expanded=False):
        st.caption("Deletes every saved row and starts over. Cannot be undone.")
        if st.checkbox("I understand — wipe the 9Sig plan", key="ns_reset_ack"):
            if st.button("🗑 Reset plan", key="ns_reset_btn"):
                ok, msg = reset_ninesig()
                (st.success if ok else st.error)(msg)
                if ok:
                    st.rerun()


# ── Mode B: Quick Calculator ───────────────────────────────────
def _render_calculator():
    st.markdown(
        f'<div style="border-left:4px solid {ACCENT_BLUE};padding:10px 16px;'
        f'background:linear-gradient(90deg,{ACCENT_BLUE}18,{BG_PANEL});border-radius:0 8px 8px 0;'
        f'margin-bottom:14px"><span style="color:{TEXT_PRIMARY};font-size:13px;line-height:1.6">'
        f'One-off check — enter your current balances and last quarter\'s TQQQ balance to see '
        f'your composition and the suggested 9Sig split. Nothing is saved.</span></div>',
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        tqqq_now = st.number_input("Current TQQQ value ($)", min_value=0.0,
                                   value=6500.0, step=100.0, key="ns_calc_tqqq")
    with c2:
        agg_now = st.number_input(f"Current {BOND} value ($)", min_value=0.0,
                                  value=4000.0, step=100.0, key="ns_calc_agg")
    with c3:
        prior_tqqq = st.number_input("Last quarter-end TQQQ ($)", min_value=0.0,
                                     value=6000.0, step=100.0, key="ns_calc_prior")
    c4, c5 = st.columns(2)
    with c4:
        contribution = st.number_input("New contribution this quarter ($)", min_value=0.0,
                                       value=0.0, step=500.0, key="ns_calc_contrib")
    with c5:
        force_6040 = st.checkbox("Force 60/40 reset instead", value=False, key="ns_calc_spike")

    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:12px;margin-top:6px">Current composition</div>',
        unsafe_allow_html=True,
    )
    _comp_bar(tqqq_now, agg_now)

    r = _compute(prior_tqqq, contribution, tqqq_now, agg_now, force_6040=force_6040)
    ac = _action_color(r["action"])
    st.markdown(
        f'<div style="background:{BG_PANEL};border:1px solid {ac}55;border-left:4px solid {ac};'
        f'border-radius:0 8px 8px 0;padding:12px 16px;margin:8px 0">'
        f'<div style="color:{ac};font-size:13px;font-weight:700;margin-bottom:4px">{r["action"]}'
        f'{(" · " + r["note"]) if r["note"] else ""}</div>'
        f'<div style="color:{TEXT_PRIMARY};font-size:13px;line-height:1.7">{_trade_phrase(r)}<br>'
        f'9% signal line: <b>{_money(r["signal"])}</b> '
        f'(= {_money(prior_tqqq)} × 1.09{" + ½ contribution" if contribution else ""})<br>'
        f'After → TQQQ <b>{_money(r["tqqq_after"])}</b> / {BOND} <b>{_money(r["agg_after"])}</b> '
        f'(TQQQ {r["tqqq_pct"]:.0f}%) · Total <b>{_money(r["total"])}</b></div></div>',
        unsafe_allow_html=True,
    )

    # Plain 60/40 reference
    tot = tqqq_now + agg_now + contribution
    ref_tq = TQQQ_TARGET * tot
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11px">For reference, a plain 60/40 reset would target '
        f'TQQQ <b style="color:{TEXT_PRIMARY}">{_money(ref_tq)}</b> / '
        f'{BOND} <b style="color:{TEXT_PRIMARY}">{_money(tot - ref_tq)}</b>.</div>',
        unsafe_allow_html=True,
    )


# ── Entry point ────────────────────────────────────────────────
def render():
    st.markdown(
        f'<div style="font-size:18px;font-weight:800;color:{GOLD};margin-bottom:2px">'
        f'📊 9Sig Plan — TQQQ / {BOND} (60/40)</div>'
        f'<div style="font-size:12px;color:{TEXT_MUTED};margin-bottom:10px">'
        f'9% quarterly signal line · contributions go to {BOND} (½ added to signal) · '
        f'90% buy throttle · 30-Down &amp; Spike Reset as manual toggles</div>',
        unsafe_allow_html=True,
    )

    if not using_google_sheets():
        st.warning(
            "⚠️ Google Sheets not connected — the tracked plan will use local CSV "
            "and may not persist across restarts. The Quick Calculator works either way.",
            icon="⚠️",
        )

    mode = st.radio("Mode", ["📈 Tracked Plan", "🧮 Quick Calculator"],
                    horizontal=True, label_visibility="collapsed", key="ns_mode")
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    if mode.startswith("📈"):
        _render_tracked()
    else:
        _render_calculator()
