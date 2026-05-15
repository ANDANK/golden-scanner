# scanners/scheduled_scans.py — Scheduled AM/PM Options Scans

import streamlit as st
import pandas as pd
import json, os
from datetime import datetime, date
from typing import Optional, Tuple
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *
from utils import section_header, metric_card, empty_state, render_results_table

try:
    import pytz
    _CST = pytz.timezone("America/Chicago")
    def _now_cst() -> datetime:
        return datetime.now(_CST)
except Exception:
    from datetime import timezone, timedelta
    def _now_cst() -> datetime:
        return datetime.now(timezone(timedelta(hours=-6)))

# ── Config ─────────────────────────────────────────────────────
DATA_DIR             = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
SCHED_STOCKS         = 20          # tickers per stock scan (keep short for automation)
SCHED_WINDOW_MIN     = 45          # minutes after target time the auto-banner still shows
SLOTS                = {"am": (9, 0), "pm": (13, 0)}
SLOT_LABELS          = {"am": "Morning  9:00 AM CST", "pm": "Afternoon  1:00 PM CST"}
SLOT_ICONS           = {"am": "🌅", "pm": "🌇"}
AUTO_TRACK_THRESHOLD = 60          # min score to auto-add diff tickers
STRAT_DISPLAY_ORDER  = ["CSP", "LEAPS", "CC"]   # fixed display order; unknowns appended last


# ── Helpers ────────────────────────────────────────────────────

def _current_slot() -> Optional[str]:
    now = _now_cst()
    now_mins = now.hour * 60 + now.minute
    for slot, (h, m) in SLOTS.items():
        if h * 60 <= now_mins < h * 60 + SCHED_WINDOW_MIN:
            return slot
    return None


def _results_path(slot: str) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, f"sched_{slot}_{date.today().isoformat()}.json")


def _save_results(slot: str, df: pd.DataFrame):
    data = {
        "run_at":  _now_cst().strftime("%Y-%m-%d %H:%M CST"),
        "slot":    slot,
        "results": df.to_dict("records") if not df.empty else [],
    }
    with open(_results_path(slot), "w") as f:
        json.dump(data, f, default=str)


def _load_results(slot: str) -> Tuple[pd.DataFrame, str]:
    path = _results_path(slot)
    if not os.path.exists(path):
        return pd.DataFrame(), ""
    try:
        with open(path) as f:
            d = json.load(f)
        return pd.DataFrame(d.get("results", [])), d.get("run_at", "")
    except Exception:
        return pd.DataFrame(), ""


# ── Run all 6 options scans ────────────────────────────────────

def _run_all_scans(top_prog=None) -> pd.DataFrame:
    from scanners.csp_scanner   import scan_csp
    from scanners.leaps_scanner import scan_leaps

    stocks = SP500_SAMPLE[:SCHED_STOCKS]
    etfs   = OPTIONS_ETF_UNIVERSE

    # (display_label, strategy_tag, universe_label, fn, tickers, positional_args)
    # CC removed — requires owning 100 shares per contract.
    # CSP: premium 0.65% (was 0.70%), DTE max 35 (was 45)
    # LEAPS: IV rank max 35 (was 40) to avoid high-IV noise
    scan_plan = [
        ("CSP — Stocks",   "CSP",   "Stocks", scan_csp,   stocks,
         (25, 0.15, 0.30, 0.65, 20.0, 1, 35)),
        ("CSP — ETFs",     "CSP",   "ETFs",   scan_csp,   etfs,
         (25, 0.15, 0.30, 0.65, 20.0, 1, 35)),
        ("LEAPS — Stocks", "LEAPS", "Stocks", scan_leaps, stocks,
         (300, 0.60, 0.75, 35, 5.0, 5000.0)),
        ("LEAPS — ETFs",   "LEAPS", "ETFs",   scan_leaps, etfs,
         (300, 0.60, 0.75, 35, 5.0, 5000.0)),
    ]

    n_plans = len(scan_plan)
    frames = []

    for idx, (label, strategy, universe_lbl, fn, tickers, args) in enumerate(scan_plan):
        pct_done = int((idx / n_plans) * 90)   # reserve last 10% for save/finish
        if top_prog is not None:
            top_prog.progress(pct_done, text=f"📡 Strategy {idx+1}/{n_plans}: {label}…")
        st.markdown(
            f'<div style="color:{GOLD};font-size:12px;font-weight:600;'
            f'padding:6px 0 2px;border-top:1px solid {BORDER_COLOR};margin-top:6px">'
            f'📡 {label} ({len(tickers)} tickers)…</div>',
            unsafe_allow_html=True,
        )
        try:
            df, _ = fn(tickers, *args)
        except Exception as e:
            st.warning(f"{label} failed: {e}")
            df = pd.DataFrame()

        if not df.empty:
            df = df.copy()
            df["Strategy"] = strategy
            df["Universe"] = universe_lbl
            frames.append(df)

        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:11px;margin-bottom:2px">'
            f'{"✓ " + str(len(df)) + " setup(s)" if not df.empty else "— none passed filters"}</div>',
            unsafe_allow_html=True,
        )

    if top_prog is not None:
        top_prog.progress(95, text="💾 Saving results…")

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    # Best row per (Ticker, Strategy) by Score
    if "Score" in combined.columns:
        combined["Score"] = pd.to_numeric(combined["Score"], errors="coerce").fillna(0)
        combined = (
            combined
            .sort_values("Score", ascending=False)
            .drop_duplicates(subset=["Ticker", "Strategy"])
            .reset_index(drop=True)
        )
    return combined


# ── Diff logic ─────────────────────────────────────────────────

def _compute_diff(df_am: pd.DataFrame, df_pm: pd.DataFrame) -> pd.DataFrame:
    """
    Compare AM vs PM results.
    - NEW:     ticker+strategy in PM but not AM  → auto-track if score ≥ 60
    - DROPPED: ticker+strategy in AM but not PM  → informational
    - MOVED:   in both but |score_pm - score_am| ≥ 10  → informational
    Returns a combined diff DataFrame with 'Change' and 'Auto-Tracked' columns.
    """
    def _keys(df: pd.DataFrame) -> set:
        if df.empty or "Ticker" not in df.columns:
            return set()
        strat = df["Strategy"] if "Strategy" in df.columns else pd.Series(["?"] * len(df))
        return set(zip(df["Ticker"].astype(str), strat.astype(str)))

    am_keys = _keys(df_am)
    pm_keys = _keys(df_pm)

    new_keys     = pm_keys - am_keys
    dropped_keys = am_keys - pm_keys
    common_keys  = am_keys & pm_keys

    rows = []

    # ── NEW tickers ──────────────────────────────────────────
    for tk, strat in sorted(new_keys):
        match = df_pm[df_pm["Ticker"] == tk]
        if match.empty:
            continue
        r = match.iloc[0].to_dict()
        score = int(float(str(r.get("Score", 0))))
        auto_tracked = False
        if score >= AUTO_TRACK_THRESHOLD:
            try:
                from scanners.gsheet_helper import add_to_tracking
                price_str = str(r.get("Stock Price", r.get("Price", "")))
                ok, _ = add_to_tracking(tk, strat, "Sched-PM", price_str, r)
                auto_tracked = ok
            except Exception:
                pass
        rows.append({**r, "Change": "🆕 New in PM", "Auto-Tracked": "✅ Yes" if auto_tracked else "—"})

    # ── DROPPED tickers ───────────────────────────────────────
    for tk, strat in sorted(dropped_keys):
        match = df_am[df_am["Ticker"] == tk]
        if match.empty:
            continue
        r = match.iloc[0].to_dict()
        rows.append({**r, "Change": "❌ Dropped", "Auto-Tracked": "—"})

    # ── SCORE MOVERS ──────────────────────────────────────────
    for tk, strat in sorted(common_keys):
        am_row = df_am[df_am["Ticker"] == tk]
        pm_row = df_pm[df_pm["Ticker"] == tk]
        if am_row.empty or pm_row.empty:
            continue
        am_sc = int(float(str(am_row.iloc[0].get("Score", 0))))
        pm_sc = int(float(str(pm_row.iloc[0].get("Score", 0))))
        if abs(pm_sc - am_sc) >= 10:
            arrow = "⬆️" if pm_sc > am_sc else "⬇️"
            r = pm_row.iloc[0].to_dict()
            rows.append({**r, "Change": f"{arrow} Score {am_sc}→{pm_sc}", "Auto-Tracked": "—"})

    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ── Result card ────────────────────────────────────────────────

def _slot_card(slot: str, df: pd.DataFrame, run_at: str):
    icon  = SLOT_ICONS[slot]
    label = SLOT_LABELS[slot]
    if df.empty:
        status_color = TEXT_MUTED
        status_text  = "Not run today"
        count_text   = "—"
    else:
        status_color = ACCENT_GREEN
        status_text  = run_at or "Done"
        count_text   = str(len(df))

    st.markdown(
        f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};'
        f'border-top:3px solid {GOLD if not df.empty else BORDER_COLOR};'
        f'border-radius:10px;padding:16px 20px">'
        f'<div style="color:{GOLD};font-size:15px;font-weight:700;margin-bottom:4px">'
        f'{icon} {label}</div>'
        f'<div style="color:{status_color};font-size:11px;margin-bottom:8px">{status_text}</div>'
        f'<div style="font-size:28px;font-weight:800;color:{GOLD if not df.empty else TEXT_MUTED};'
        f'font-family:\'Cormorant Garamond\',serif">{count_text}</div>'
        f'<div style="color:{TEXT_MUTED};font-size:10px;text-transform:uppercase;letter-spacing:0.8px">'
        f'setups found</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ── Main render ────────────────────────────────────────────────

def render():
    section_header(
        "📅", "Scheduled Scans",
        "Auto-runs at 9 AM & 1 PM CST · Diffs new vs morning setups · Score ≥ 60 auto-tracked",
    )

    _is_admin = st.session_state.get("_is_admin", False)
    now_cst   = _now_cst()
    auto_slot = _current_slot()

    # ── Load today's stored results ───────────────────────────
    with st.spinner("Loading today's scan results…"):
        df_am, am_at = _load_results("am")
        df_pm, pm_at = _load_results("pm")

    # ── Auto-run banner (admin only) ──────────────────────────
    if _is_admin and auto_slot:
        label = SLOT_LABELS[auto_slot]
        already_run = (df_am if auto_slot == "am" else df_pm)
        if already_run.empty:
            st.success(
                f"⏰ **{label} scan window is open!**  "
                f"Click **▶ Run {auto_slot.upper()} Scan** below to start automatically.",
                icon="⏰",
            )
        else:
            st.info(f"✅ {label} scan already completed today at {am_at if auto_slot == 'am' else pm_at}.")

    # ── Status cards ──────────────────────────────────────────
    c1, c2 = st.columns(2)
    with c1:
        _slot_card("am", df_am, am_at)
    with c2:
        _slot_card("pm", df_pm, pm_at)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Action buttons (admin-only) ───────────────────────────────
    run_am = False
    run_pm = False

    if _is_admin:
        col1, col2, col3 = st.columns([1, 1, 4])
        with col1:
            run_am = st.button("🌅 Run AM Scan", use_container_width=True, key="sched_run_am")
        with col2:
            run_pm = st.button("🌇 Run PM Scan", use_container_width=True, key="sched_run_pm")
    else:
        st.markdown(
            f'<div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};'
            f'border-left:3px solid {BORDER_COLOR};border-radius:6px;'
            f'padding:10px 16px;font-size:12px;color:{TEXT_MUTED};margin-bottom:8px">'
            f'🔒 <strong style="color:{TEXT_PRIMARY}">Manual scan triggers are restricted to admins.</strong>'
            f' Scans run automatically at 9 AM &amp; 1 PM CST — results appear here once complete.'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── Execute scan ──────────────────────────────────────────
    if run_am or run_pm:
        slot = "am" if run_am else "pm"
        run_start = _now_cst().strftime("%H:%M CST")

        # Immediate visible feedback — renders before heavy scan begins
        st.toast(f"🚀 {SLOT_LABELS[slot]} scan started…", icon="⏳")
        _scan_banner = st.info(
            f"⏳ **{SLOT_LABELS[slot]} scan running** — scanning all strategies across stocks & ETFs. "
            f"This takes ~4 minutes. Please keep this tab open…",
            icon="🔍",
        )
        _top_prog = st.progress(0, text="Initializing scan…")

        # Run (internal scanners update their own sub-progress bars)
        df_new = _run_all_scans(_top_prog)

        _top_prog.progress(100, text="✅ All strategies complete!")
        _scan_banner.empty()

        _save_results(slot, df_new)
        st.success(f"✅ {SLOT_LABELS[slot]} scan complete at {run_start} — {len(df_new)} total setup(s) found.")
        from data_loader import show_api_warnings
        show_api_warnings()
        # Reload
        if slot == "am":
            df_am, am_at = df_new, run_start
        else:
            df_pm, pm_at = df_new, run_start
        st.rerun()

    # ── Results tabs ──────────────────────────────────────────
    has_am = not df_am.empty
    has_pm = not df_pm.empty

    tab_labels = []
    if has_am: tab_labels.append("🌅 AM Results")
    if has_pm: tab_labels.append("🌇 PM Results")
    if has_am and has_pm: tab_labels.append("🔀 AM vs PM Diff")

    if not tab_labels:
        st.markdown("<br>", unsafe_allow_html=True)
        if _is_admin:
            empty_state("No scans run today yet. Click ▶ Run AM Scan to start.")
        else:
            empty_state("No scans have run today yet — check back after 9 AM CST.")
        return

    tabs = st.tabs(tab_labels)
    tab_idx = 0

    if has_am:
        with tabs[tab_idx]:
            st.markdown(
                f'<div style="color:{TEXT_MUTED};font-size:12px;margin-bottom:8px">'
                f'Run at {am_at} · {len(df_am)} setup(s)</div>',
                unsafe_allow_html=True,
            )
            _show_results(df_am, "AM")
        tab_idx += 1

    if has_pm:
        with tabs[tab_idx]:
            st.markdown(
                f'<div style="color:{TEXT_MUTED};font-size:12px;margin-bottom:8px">'
                f'Run at {pm_at} · {len(df_pm)} setup(s)</div>',
                unsafe_allow_html=True,
            )
            _show_results(df_pm, "PM")
        tab_idx += 1

    if has_am and has_pm:
        with tabs[tab_idx]:
            _show_diff(df_am, df_pm)


def _show_results(df: pd.DataFrame, slot_label: str):
    """Show scan results with strategy filter + sort.
    Auto-tracks every row with score ≥ AUTO_TRACK_THRESHOLD to Google Sheets
    (scheduled scans are the only path that writes automatically).
    """
    from datetime import date as _date
    _today_str = str(_date.today())
    _auto_set  = st.session_state.setdefault("_sched_auto_tracked", set())
    slot_prefix = slot_label.upper()   # "AM" or "PM"

    # ── Strategy filter ────────────────────────────────────────
    _all_strats = sorted(df["Strategy"].dropna().unique().tolist()) if "Strategy" in df.columns else []
    _sf1, _sf2  = st.columns([1.2, 4])
    with _sf1:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:11px;padding:7px 0">Filter:</div>',
            unsafe_allow_html=True,
        )
    with _sf2:
        _strat_sel = st.multiselect(
            "Filter strategy", _all_strats,
            key=f"sched_strat_{slot_label}",
            label_visibility="collapsed",
            placeholder="All strategies",
        )
    _fdf = df[df["Strategy"].isin(_strat_sel)] if _strat_sel else df

    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:11px;margin:4px 0 10px">'
        f'{len(_fdf)} setup(s) shown</div>',
        unsafe_allow_html=True,
    )

    # ── Ordered strategies: CSP → LEAPS → CC → everything else ──
    _all_unique = list(_fdf["Strategy"].dropna().unique()) if "Strategy" in _fdf.columns else []
    _ordered = [s for s in STRAT_DISPLAY_ORDER if s in _all_unique]
    _ordered += sorted(s for s in _all_unique if s not in STRAT_DISPLAY_ORDER)

    for strat in _ordered:
        if "Strategy" not in _fdf.columns or strat not in _fdf["Strategy"].values:
            continue
        # Keep "Universe" so render_results_table can embed it in the source tag
        # (hidden from display via _NEVER_SHOW_COLS in utils.py)
        sub = _fdf[_fdf["Strategy"] == strat].drop(columns=["Strategy"], errors="ignore")

        # Collapsible section — expanded by default so results are immediately visible
        with st.expander(f"**{strat}** — {len(sub)} setup(s)", expanded=True):
            # ── Auto-track high-scoring picks (scheduled runs only) ──
            for _, row in sub.iterrows():
                tk = str(row.get("Ticker", "")).strip()
                if not tk:
                    continue
                try:
                    score = int(float(str(row.get("Score", 0) or 0)))
                except Exception:
                    score = 0
                _auto_key = f"{tk}_{slot_prefix}_{_today_str}"
                if score >= AUTO_TRACK_THRESHOLD and _auto_key not in _auto_set:
                    try:
                        from scanners.gsheet_helper import add_to_tracking
                        price_str = str(row.get("Stock Price", row.get("Price", "")))
                        # Include Universe (Stocks / ETFs) in the source tag so tracking shows
                        # "AM·CSP·Stocks" / "AM·LEAPS·ETFs" instead of the bare "AM·CSP"
                        _univ = str(row.get("Universe", "")).strip()
                        _univ_sfx = f"·{_univ}" if _univ and _univ.lower() not in ("nan", "none", "") else ""
                        source_tag = f"{slot_prefix}·{strat}{_univ_sfx}"
                        # Build proper extra_meta so Score, Style, HOLD are stored correctly
                        _extra = {
                            "Score_At_Track": str(score),
                            "HOLD":           str(row.get("Hold", row.get("HOLD", ""))),
                            "Est_Upside":     str(row.get("Est. Upside %", "")),
                            "Style":          str(row.get("Style", "")),
                        }
                        ok, _ = add_to_tracking(tk, strat, source_tag, price_str, _extra)
                        if ok:
                            _auto_set.add(_auto_key)
                    except Exception:
                        pass

            render_results_table(sub, strategy=strat, source=f"Sched-{slot_label}")


def _diff_html_rows(df: pd.DataFrame, accent_color: str):
    """Render a diff sub-table as styled HTML (avoids st.dataframe dark-theme blank issue)."""
    if df.empty:
        return

    th_s = (f'color:{TEXT_MUTED};font-size:10px;font-weight:700;letter-spacing:.7px;'
            f'text-transform:uppercase;padding:7px 10px;border-bottom:2px solid {GOLD}55;'
            f'background:{BG_PANEL};white-space:nowrap')
    td_base = f'padding:7px 10px;font-size:12px;border-bottom:1px solid {BORDER_COLOR}22'

    hdr_html = "".join(f'<th style="{th_s}">{c}</th>' for c in df.columns)

    row_htmls = []
    for i, (_, row) in enumerate(df.iterrows()):
        bg = BG_CARD if i % 2 == 0 else BG_PANEL
        cells = []
        for col in df.columns:
            raw = str(row[col]) if pd.notna(row[col]) else "—"
            # Colour-code special columns
            if col == "Ticker":
                cell = (f'<td style="{td_base};background:{bg};color:{GOLD};'
                        f'font-family:\'DM Mono\',monospace;font-weight:800">{raw}</td>')
            elif col == "Change":
                c = (ACCENT_GREEN if "New" in raw else
                     ACCENT_RED   if "Drop" in raw else GOLD)
                cell = (f'<td style="{td_base};background:{bg};color:{c};font-weight:700">{raw}</td>')
            elif col == "Auto-Tracked":
                c = ACCENT_GREEN if raw == "✅ Yes" else TEXT_MUTED
                cell = (f'<td style="{td_base};background:{bg};color:{c};font-weight:600">{raw}</td>')
            elif col == "Score":
                try:
                    sv = float(raw)
                    sc = (ACCENT_GREEN if sv >= 70 else GOLD if sv >= 50 else ACCENT_RED)
                except Exception:
                    sc = TEXT_MUTED
                cell = (f'<td style="{td_base};background:{bg};color:{sc};'
                        f'font-family:\'DM Mono\',monospace;font-weight:700">{raw}</td>')
            else:
                cell = f'<td style="{td_base};background:{bg};color:{TEXT_PRIMARY}">{raw}</td>'
            cells.append(cell)
        row_htmls.append(f'<tr>{"".join(cells)}</tr>')

    html = (
        f'<div style="overflow-x:auto;border-radius:8px;border:1px solid {BORDER_COLOR}44;'
        f'margin-bottom:12px">'
        f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif">'
        f'<thead><tr>{hdr_html}</tr></thead>'
        f'<tbody>{"".join(row_htmls)}</tbody>'
        f'</table></div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def _show_diff(df_am: pd.DataFrame, df_pm: pd.DataFrame):
    """Show the AM→PM diff with auto-track status."""
    df_diff = _compute_diff(df_am, df_pm)

    new_count     = (df_diff["Change"] == "🆕 New in PM").sum() if not df_diff.empty else 0
    dropped_count = (df_diff["Change"] == "❌ Dropped").sum()   if not df_diff.empty else 0
    tracked_count = (df_diff.get("Auto-Tracked", pd.Series()) == "✅ Yes").sum() if not df_diff.empty else 0

    c1, c2, c3 = st.columns(3)
    with c1: metric_card("New in PM",      str(new_count),     color=ACCENT_GREEN)
    with c2: metric_card("Dropped from AM",str(dropped_count), color=ACCENT_RED)
    with c3: metric_card("Auto-Tracked",   str(tracked_count), color=GOLD)

    st.markdown("<br>", unsafe_allow_html=True)

    if df_diff.empty:
        empty_state("No significant differences between AM and PM scans.")
        return

    # Group by change type
    for change_type in ["🆕 New in PM", "❌ Dropped", "⬆️", "⬇️"]:
        sub = df_diff[df_diff["Change"].str.startswith(change_type[:2])]
        if sub.empty:
            continue
        color = ACCENT_GREEN if "New" in change_type else (ACCENT_RED if "Drop" in change_type else GOLD)
        st.markdown(
            f'<div style="color:{color};font-size:12px;font-weight:700;'
            f'text-transform:uppercase;letter-spacing:1px;margin:14px 0 6px">'
            f'{change_type.split()[0]} {change_type.split()[1] if len(change_type.split()) > 1 else ""} '
            f'— {len(sub)} ticker(s)</div>',
            unsafe_allow_html=True,
        )
        display_cols = ["Ticker", "Strategy", "Score", "Change", "Auto-Tracked"] + [
            c for c in ["Stock Price", "Premium", "Delta", "DTE", "Expiry"]
            if c in sub.columns
        ]
        _diff_sub = sub[[c for c in display_cols if c in sub.columns]].reset_index(drop=True)
        _diff_html_rows(_diff_sub, color)
