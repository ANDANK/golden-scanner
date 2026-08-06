#!/usr/bin/env python3
"""
scripts/headless_best_scanners_scan.py — Run the live Best Scanners scan (the
6 keeper scanners + 7Square/8Cross early-signal add-ons) without a browser,
filter to tickers with a validated historical edge, and email a Top 5 +
card-grid + detail-table summary.

Independent pipeline from headless_overkill_scan.py by design — separate
script, separate GitHub Actions workflow, separate schedule — so either can
be debugged/rescheduled without touching the other. See
.github/workflows/best_scanners_email.yml.

Usage:
  SCAN_SLOT=am python scripts/headless_best_scanners_scan.py
  SCAN_SLOT=pm python scripts/headless_best_scanners_scan.py

Required env vars (GitHub Actions secrets):
  GMAIL_ADDRESS        the Gmail account to send FROM
  GMAIL_APP_PASSWORD   a 16-character Gmail App Password for that account
  OVERKILL_EMAIL_TO    recipient address(es), reused from the OverKill email —
                        set BEST_SCANNERS_EMAIL_TO instead if you want this
                        scan to go to a different list

Optional env vars:
  BEST_SCANNERS_EMAIL_TO   overrides OVERKILL_EMAIL_TO for this scan only
  BEST_SCANNERS_UNIVERSE   FTF / MTPA / SP500 (default FTF, ~480 tickers)

Filter: a ticker is included if scanners.home._edge_verdict() found a match
on the empirically-derived shortlist (Strong Setup or Mixed Signal) — this
replaced the old star-tier-or-3+-scanners filter once the backtests showed
neither star tier nor raw scanner count was a reliable ranker on its own
(see the analysis this shortlist was built from: 8 headless full-analysis
backtests, 2026-07-29, in scanners/home.py's _EDGE_SHORTLIST comment).

Top 5 is restricted to Strong Setup tickers from a large-cap-anchored
universe (FTF or SP500 — S&P 500 membership implies a market-cap floor) as
a free quality proxy, since we don't currently fetch market cap directly.
If this run's universe is MTPA, Top 5 is intentionally left empty — MTPA
names can still appear in the main grid/table, just not the featured picks.

Layout note: every multi-column section below is built with real HTML
<table>/<tr>/<td> markup, not CSS display:grid/flex. A grid-based version
of this email shipped once and rendered as a single vertical stack in
Gmail — grid/flex support in email clients is unreliable (Outlook desktop
doesn't support either at all), tables are the actual universal standard.
"""

import os, sys, smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ── Mock Streamlit so scanner modules import/run without a server, same
# approach as scripts/headless_overkill_scan.py.
from unittest.mock import MagicMock

class _FakeSS(dict):
    def __missing__(self, key): return None

class _MockST:
    session_state = _FakeSS()
    @staticmethod
    def cache_data(ttl=None, show_spinner=True):
        def _dec(fn): return fn
        return _dec
    def __getattr__(self, name):
        return MagicMock()

sys.modules["streamlit"] = _MockST()

# ── Now safe to import project modules ──────────────────────────────────
from config import FTF_UNIVERSE, MTPA_200, SP500_SAMPLE
from scanners.home import _run_best_scanners
from scanners import scan_history

SLOT      = os.environ.get("SCAN_SLOT", "am").lower()
UNI_KIND  = os.environ.get("BEST_SCANNERS_UNIVERSE", "FTF").upper()
_UNIVERSES = {"FTF": FTF_UNIVERSE, "MTPA": MTPA_200, "SP500": SP500_SAMPLE[:200]}
UNIVERSE  = _UNIVERSES.get(UNI_KIND, FTF_UNIVERSE)
IS_QUALITY_UNIVERSE = UNI_KIND in ("FTF", "SP500")
TOP_N = 5
TODAY = datetime.utcnow().strftime("%Y-%m-%d")

# Hidden 2026-07-29 to keep the email simple for now -- _qual_card_html()/
# _qual_grid_html() are untouched below, just not called from build_email().
# Flip back to True to restore the compact card-grid section.
SHOW_QUALIFIED_GRID = False

# Verdict badge (used in the compact grid + detail table) — semantic, not decorative.
_VERDICT_COLOR = {"Strong Setup": "#3fcf7f", "Mixed Signal": "#f0b94a"}
_VERDICT_BG = {"Strong Setup": "rgba(63,207,127,0.16)", "Mixed Signal": "rgba(240,185,74,0.16)"}
# Verdict TEXT color inside the Top 5 spheres specifically — dark green / dark amber,
# kept semantic even though the sphere's own background is fixed/decorative per design.
_VERDICT_TEXT_DARK = {"Strong Setup": "#065F46", "Mixed Signal": "#92400E"}

# Sphere background is a FIXED color per position (not tied to verdict) purely for
# visual variety — (highlight, mid, dark, secondary-text) per the radial-gradient
# "glossy sphere" look. Cycles if there were ever more than 5, though Top 5 caps at 5.
_SPHERE_COLORS = [
    ("#BFDBFE", "#3B82F6", "#1E3A8A", "#DBEAFE"),   # blue
    ("#DDD6FE", "#8B5CF6", "#4C1D95", "#EDE9FE"),   # purple
    ("#FED7AA", "#F97316", "#7C2D12", "#FFEDD5"),   # orange
    ("#FBCFE8", "#EC4899", "#831843", "#FCE7F3"),   # pink
    ("#99F6E4", "#14B8A6", "#134E4A", "#CCFBF1"),   # teal
]

# Fixed color per scanner label (identity, not meaning) so the tag row in each card
# has real variety instead of one flat gray for all 8.
_SCANNER_COLORS = {
    "1Mom":    ("rgba(96,165,250,0.16)",  "#93c5fd"),
    "2TC":     ("rgba(52,211,153,0.16)",  "#6ee7b7"),
    "3MF":     ("rgba(167,139,250,0.16)", "#c4b5fd"),
    "4TS":     ("rgba(251,146,60,0.16)",  "#fdba74"),
    "5RB":     ("rgba(244,114,182,0.16)", "#f9a8d4"),
    "6Prime":  ("rgba(129,140,248,0.16)", "#a5b4fc"),
    "7Square": ("rgba(251,191,36,0.16)",  "#fde68a"),
    "8Cross":  ("rgba(248,113,113,0.16)", "#fca5a5"),
}


def log(msg: str):
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}", flush=True)


def _hold_text(hold_range) -> str:
    if not hold_range:
        return "—"
    lo, hi = hold_range
    return f"{lo}-{hi}d"


def _fmt_found_date(date_str) -> str:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%b %d")
    except Exception:
        return date_str or "—"


def _new_badge(is_new: bool) -> str:
    return ' <span title="New in the last 7 scan-days" style="font-size:9px">\U0001F195</span>' if is_new else ""


def _chunk(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# ── Top 5 — one row of colored-ring cells (outline only, no fill shading),
# real <table> layout ───────────────────────────────────────────────────

def _sphere_cell_html(row, idx: int) -> str:
    # Ring border uses the fixed per-position color (the "mid" tone of that
    # slot's palette entry); highlight/dark/text_2 stay unused for now but
    # the palette keeps its 4-tuple shape in case a shaded version comes back.
    _highlight, mid, _dark, _text_2 = _SPHERE_COLORS[idx % len(_SPHERE_COLORS)]
    verdict = row["_verdict"]
    v_color = _VERDICT_COLOR.get(verdict, "#8b8578")
    combo = row.get("_combo") or ""
    return (
        f'<td width="20%" align="center" valign="top">'
        f'<table role="presentation" cellpadding="0" cellspacing="0"><tr><td align="center" valign="middle" '
        f'style="width:104px;height:104px;border-radius:50%;text-align:center;vertical-align:middle;'
        f'background-color:#17140f;border:3px solid {mid}">'
        f'<div style="font-family:Arial,sans-serif;font-size:7.5px;font-weight:bold;color:{v_color};'
        f'letter-spacing:0.03em">{verdict.upper()}</div>'
        f'<div style="font-family:monospace;font-weight:bold;font-size:15px;color:#ffffff">'
        f'{row["Ticker"]}{_new_badge(row.get("_is_new", False))}</div>'
        f'<div style="font-family:monospace;font-size:9.5px;color:#a89f8a">${row.get("Price", 0):,.2f}</div>'
        f'<div style="font-family:Arial,sans-serif;font-size:8px;color:#a89f8a;margin-top:1px">'
        f'{_hold_text(row["_hold_range"])}</div>'
        f'<div style="font-family:monospace;font-size:6.5px;color:{mid};margin-top:1px">{combo}</div>'
        '</td></tr></table></td>'
    )


def _top5_table_html(top5) -> str:
    cells = "".join(_sphere_cell_html(r, i) for i, (_, r) in enumerate(top5.iterrows()))
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>{cells}</tr></table>'


# ── "Everything qualified" — compact cards, 4 per row, real <table> layout ──

def _qual_card_html(row) -> str:
    verdict = row["_verdict"]
    color = _VERDICT_COLOR.get(verdict, "#8b8578")
    bg = _VERDICT_BG.get(verdict, "rgba(139,133,120,0.16)")
    # Split on " · " (with spaces, the actual join separator) not bare "·" —
    # the latter also breaks apart the "8Cross·W" weekly-confirmation suffix,
    # which uses an un-spaced "·" internally.
    scanners = [s.strip() for s in (row.get("Scanners") or "").split(" · ") if s.strip()]
    pill_cells = ""
    for s in scanners:
        base = s.replace("·W", "").strip()
        pill_bg, pill_txt = _SCANNER_COLORS.get(base, ("#1d1a13", "#726b5a"))
        pill_cells += (
            f'<td style="background:{pill_bg};color:{pill_txt};font-family:monospace;font-size:9px;'
            f'border-radius:4px;padding:2px 5px">{s}</td><td width="3"></td>'
        )
    return (
        '<td width="23.5%" valign="top">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="background:#17140f;border:1px solid rgba(245,200,66,0.10);border-radius:9px">'
        '<tr><td style="padding:9px 10px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
        f'<td style="font-family:monospace;font-weight:bold;font-size:12.5px;color:#F5C842">'
        f'{row["Ticker"]}{_new_badge(row.get("_is_new", False))}</td>'
        f'<td align="right" style="font-family:monospace;font-size:10px;color:#726b5a">${row.get("Price", 0):,.2f}</td>'
        '</tr></table>'
        '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:5px 0"><tr><td '
        f'style="background:{bg};color:{color};font-family:Arial,sans-serif;font-size:9.5px;'
        f'font-weight:bold;border-radius:5px;padding:3px 6px">{verdict}</td></tr></table>'
        f'<div style="font-family:Arial,sans-serif;font-size:10px;color:#a89f8a;margin:3px 0">'
        f'{_hold_text(row["_hold_range"])}</div>'
        f'<table role="presentation" cellpadding="0" cellspacing="0"><tr>{pill_cells}</tr></table>'
        '</td></tr></table></td>'
    )


def _qual_grid_html(filtered) -> str:
    all_rows = [r for _, r in filtered.iterrows()]
    trs = []
    for chunk in _chunk(all_rows, 4):
        tds = []
        for i in range(4):
            if i > 0:
                tds.append('<td width="2%"></td>')
            tds.append(_qual_card_html(chunk[i]) if i < len(chunk) else '<td width="23.5%"></td>')
        trs.append(f'<tr>{"".join(tds)}</tr>')
        trs.append('<tr><td colspan="7" style="height:9px"></td></tr>')
    if trs:
        trs.pop()  # drop the trailing spacer row
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{"".join(trs)}</table>'


# ── Full detail table ────────────────────────────────────────────────────

def _detail_row_html(row) -> str:
    n = row.get("_edge_n")
    score = row.get("_edge_score")
    chg = row.get("Chg", 0) or 0
    chg_color = "#3fcf7f" if chg >= 0 else "#ef5350"
    rsi_d = row.get("RSI_D")
    rsi_txt = f"{float(rsi_d):.0f}" if rsi_d is not None and rsi_d == rsi_d else "—"
    return (
        '<tr>'
        f'<td style="padding:7px 9px;font-weight:bold;color:#F5C842;border-top:1px solid #262626">'
        f'{row["Ticker"]}{_new_badge(row.get("_is_new", False))}</td>'
        f'<td style="padding:7px 9px;color:{_VERDICT_COLOR.get(row["_verdict"], "#8b8578")};border-top:1px solid #262626">{row["_verdict"]}</td>'
        f'<td style="padding:7px 9px;color:#a89f8a;border-top:1px solid #262626">{_hold_text(row["_hold_range"])}</td>'
        f'<td style="padding:7px 9px;color:#a89f8a;font-size:11px;border-top:1px solid #262626">{_fmt_found_date(row.get("_first_found"))}</td>'
        f'<td style="padding:7px 9px;font-family:monospace;color:#a89f8a;border-top:1px solid #262626">${row.get("Price", 0):,.2f}</td>'
        f'<td style="padding:7px 9px;font-family:monospace;color:{chg_color};border-top:1px solid #262626">{chg:+.1f}%</td>'
        f'<td style="padding:7px 9px;font-family:monospace;color:#a89f8a;border-top:1px solid #262626">{rsi_txt}</td>'
        f'<td style="padding:7px 9px;font-family:monospace;font-size:10.5px;color:#726b5a;border-top:1px solid #262626">{row.get("_combo") or "—"}</td>'
        f'<td style="padding:7px 9px;font-family:monospace;color:#a89f8a;border-top:1px solid #262626">{int(n):,}</td>'
        f'<td style="padding:7px 9px;font-family:monospace;color:#a89f8a;border-top:1px solid #262626">{score:+.2f}%</td>'
        '</tr>'
    )


def _detail_table_html(filtered) -> str:
    header = (
        '<tr style="background:#1d1a13;color:#fff">'
        '<th style="padding:8px 9px;text-align:left;font-size:10.5px">Ticker</th>'
        '<th style="padding:8px 9px;text-align:left;font-size:10.5px">Verdict</th>'
        '<th style="padding:8px 9px;text-align:left;font-size:10.5px">Hold</th>'
        '<th style="padding:8px 9px;text-align:left;font-size:10.5px">Date</th>'
        '<th style="padding:8px 9px;text-align:left;font-size:10.5px">Price</th>'
        '<th style="padding:8px 9px;text-align:left;font-size:10.5px">Chg</th>'
        '<th style="padding:8px 9px;text-align:left;font-size:10.5px">RSI D</th>'
        '<th style="padding:8px 9px;text-align:left;font-size:10.5px">Combo</th>'
        '<th style="padding:8px 9px;text-align:left;font-size:10.5px">N</th>'
        '<th style="padding:8px 9px;text-align:left;font-size:10.5px">Edge</th>'
        '</tr>'
    )
    rows = "".join(_detail_row_html(r) for _, r in filtered.iterrows())
    return (
        '<div style="overflow-x:auto;border:1px solid #262626;border-radius:10px">'
        '<table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%;'
        f'font-family:Arial,sans-serif;font-size:12px;background:#0d0d0d;color:#eee">{header}{rows}</table></div>'
    )


# ── Track record — every distinct ticker seen in the last 90 days, with
# % performance since it was first flagged ──────────────────────────────

def _track_row_html(row: dict) -> str:
    pct = row.get("pct")
    pct_color = "#726b5a" if pct is None else ("#3fcf7f" if pct >= 0 else "#ef5350")
    pct_txt = "—" if pct is None else f"{pct:+.1f}%"
    cur_txt = "—" if row.get("current_price") is None else f"${row['current_price']:,.2f}"
    return (
        '<tr>'
        f'<td style="padding:7px 9px;font-weight:bold;color:#F5C842;border-top:1px solid #262626">{row["ticker"]}</td>'
        f'<td style="padding:7px 9px;color:{_VERDICT_COLOR.get(row.get("verdict"), "#8b8578")};border-top:1px solid #262626">{row.get("verdict") or "—"}</td>'
        f'<td style="padding:7px 9px;font-family:monospace;font-size:10.5px;color:#726b5a;border-top:1px solid #262626">{row.get("scanners") or "—"}</td>'
        f'<td style="padding:7px 9px;color:#a89f8a;font-size:11px;border-top:1px solid #262626">{_fmt_found_date(row["first_found"])}</td>'
        f'<td style="padding:7px 9px;font-family:monospace;color:#a89f8a;border-top:1px solid #262626">${row["first_price"]:,.2f}</td>'
        f'<td style="padding:7px 9px;font-family:monospace;color:#a89f8a;border-top:1px solid #262626">{cur_txt}</td>'
        f'<td style="padding:7px 9px;font-family:monospace;font-weight:bold;color:{pct_color};border-top:1px solid #262626">{pct_txt}</td>'
        '</tr>'
    )


def _track_record_table_html(track_rows: list[dict]) -> str:
    if not track_rows:
        return '<p style="color:#888;font-size:13px">No track record yet — check back after a few more days of runs.</p>'
    header = (
        '<tr style="background:#1d1a13;color:#fff">'
        '<th style="padding:8px 9px;text-align:left;font-size:10.5px">Ticker</th>'
        '<th style="padding:8px 9px;text-align:left;font-size:10.5px">Verdict</th>'
        '<th style="padding:8px 9px;text-align:left;font-size:10.5px">Scanners</th>'
        '<th style="padding:8px 9px;text-align:left;font-size:10.5px">First Found</th>'
        '<th style="padding:8px 9px;text-align:left;font-size:10.5px">First Price</th>'
        '<th style="padding:8px 9px;text-align:left;font-size:10.5px">Now</th>'
        '<th style="padding:8px 9px;text-align:left;font-size:10.5px">Perf</th>'
        '</tr>'
    )
    rows = "".join(_track_row_html(r) for r in track_rows)
    return (
        '<div style="overflow-x:auto;border:1px solid #262626;border-radius:10px">'
        '<table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%;'
        f'font-family:Arial,sans-serif;font-size:12px;background:#0d0d0d;color:#eee">{header}{rows}</table></div>'
    )


def build_email(filtered, top5, track_rows) -> tuple[str, str]:
    subject = (f"Best Scanners [{SLOT}] — {len(filtered)} setups"
               + (f", {len(top5)} featured" if len(top5) else "")
               + f" ({datetime.utcnow().strftime('%Y-%m-%d')})")

    top5_html = ""
    if len(top5):
        top5_html = (
            '<div style="font-size:11px;font-weight:600;color:#c9a53a;text-transform:uppercase;'
            'letter-spacing:0.06em;margin:0 0 10px">'
            f'Top picks today ({len(top5)} of possible {TOP_N})</div>'
            f'{_top5_table_html(top5)}'
            '<div style="height:24px"></div>'
        )
    elif not IS_QUALITY_UNIVERSE:
        top5_html = (
            '<p style="color:#666;font-size:11px;margin-bottom:20px">'
            f'No Top 5 this run — {UNI_KIND} isn\'t a large-cap-anchored universe, '
            'so featured picks are skipped (still shown in the full list below).</p>'
        )

    qualified_section_html = ""
    if filtered.empty:
        table_html = '<p style="color:#888;font-size:13px">Nothing qualified this run.</p>'
    else:
        if SHOW_QUALIFIED_GRID:
            qualified_section_html = (
                '<div style="font-size:11px;font-weight:600;color:#c9a53a;text-transform:uppercase;'
                'letter-spacing:0.06em;margin:0 0 10px">Everything that qualified</div>'
                + _qual_grid_html(filtered) + '<div style="height:22px"></div>'
            )
        table_html = (
            '<div style="font-size:11px;font-weight:600;color:#c9a53a;text-transform:uppercase;'
            'letter-spacing:0.06em;margin:0 0 10px">Full detail</div>'
            + _detail_table_html(filtered)
        )

    track_record_html = (
        '<div style="font-size:11px;font-weight:600;color:#c9a53a;text-transform:uppercase;'
        'letter-spacing:0.06em;margin:24px 0 10px">Track record — last 90 days</div>'
        + _track_record_table_html(track_rows)
    )

    html = f"""
    <div style="font-family:Arial,sans-serif;background:#000;padding:20px">
      <h2 style="color:#F5C842;margin-bottom:4px">Best Scanners</h2>
      <p style="color:#888;font-size:12px;margin-top:0">
        {UNI_KIND} Universe (~{len(UNIVERSE)}) · {SLOT.upper()} run ·
        {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
      </p>
      <div style="background:#17140f;border:1px solid rgba(245,200,66,0.08);border-radius:10px;
                  padding:12px 14px;margin-bottom:20px;font-size:13px;color:#a89f8a;line-height:1.5">
        <b style="color:#F5C842">How to read this:</b> look at the ticker and hold-length inside each
        circle, or the badge in each card — that's the whole decision. Everything else is detail.
      </div>
      {top5_html}
      {qualified_section_html}
      {table_html}
      {track_record_html}
      <p style="color:#666;font-size:11px;margin-top:20px;line-height:1.5">
        "Strong Setup" and "Mixed Signal" reflect how this exact scanner combination performed
        historically, adjusted for how many times we've actually seen it — not a prediction.
        Educational/research use only, not financial advice. Open the Best Scanners tab in
        Golden Scanner for the full interactive table and charts.
      </p>
    </div>
    """
    return subject, html


def send_email(subject: str, html_body: str) -> None:
    sender = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    to_raw = os.environ.get("BEST_SCANNERS_EMAIL_TO") or os.environ["OVERKILL_EMAIL_TO"]
    recipients = [addr.strip() for addr in to_raw.split(",") if addr.strip()]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())
    log(f"Email sent to {', '.join(recipients)}")


def run():
    if not os.environ.get("GMAIL_ADDRESS") or not os.environ.get("GMAIL_APP_PASSWORD"):
        log("ERROR: GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set — add them as GitHub Actions secrets.")
        sys.exit(1)
    if not os.environ.get("BEST_SCANNERS_EMAIL_TO") and not os.environ.get("OVERKILL_EMAIL_TO"):
        log("ERROR: neither BEST_SCANNERS_EMAIL_TO nor OVERKILL_EMAIL_TO is set — add one as a secret.")
        sys.exit(1)

    log(f"Scanning {UNI_KIND} universe (~{len(UNIVERSE)} tickers)…")
    df = _run_best_scanners(UNIVERSE)
    log(f"Raw scan: {len(df)} ticker(s) flagged by at least one scanner.")

    if df.empty:
        log("Nothing flagged at all this run — skipping email.")
        return

    filtered = df[df["_verdict"] != "Too New"].copy().reset_index(drop=True)
    log(f"After filter (Strong Setup or Mixed Signal): {len(filtered)} ticker(s).")

    today_rows = [
        {
            "ticker": str(r["Ticker"]),
            "price": float(r.get("Price") or 0),
            "verdict": str(r["_verdict"]),
            "combo": str(r["_combo"]) if r.get("_combo") else None,
            "scanners": str(r["Scanners"]) if r.get("Scanners") else None,
            "edge_score": float(r["_edge_score"]),
            "n": int(r["_edge_n"]),
            "hold_range": [int(x) for x in r["_hold_range"]] if r.get("_hold_range") else None,
        }
        for _, r in filtered.iterrows()
    ]
    history = scan_history.annotate_new_and_first_found("best_scanners", UNI_KIND, TODAY, today_rows)
    if not filtered.empty:
        filtered["_is_new"] = filtered["Ticker"].map(lambda t: history.get(t, {}).get("is_new", True))
        filtered["_first_found"] = filtered["Ticker"].map(lambda t: history.get(t, {}).get("first_found", TODAY))
        verdict_rank = {"Strong Setup": 2, "Mixed Signal": 1}
        filtered["_verdict_rank"] = filtered["_verdict"].map(verdict_rank)
        filtered = filtered.sort_values(
            ["_verdict_rank", "_is_new", "_edge_score"], ascending=[False, False, False]
        ).drop(columns="_verdict_rank").reset_index(drop=True)

    scan_history.save_snapshot("best_scanners", UNI_KIND, TODAY, today_rows)
    scan_history.prune_old("best_scanners", UNI_KIND, TODAY)
    n_new = sum(1 for v in history.values() if v["is_new"])
    log(f"Saved history snapshot for {TODAY} ({len(today_rows)} row(s)); {n_new} new ticker(s).")

    if filtered.empty:
        log("Nothing qualified this run — skipping email.")
        return

    top5 = filtered.iloc[0:0]
    if IS_QUALITY_UNIVERSE:
        top5 = filtered[filtered["_verdict"] == "Strong Setup"].head(TOP_N)
    log(f"Top picks: {len(top5)} of a possible {TOP_N} (quality universe: {IS_QUALITY_UNIVERSE}).")

    track_rows = scan_history.track_record("best_scanners", UNI_KIND, TODAY, today_rows)
    log(f"Track record: {len(track_rows)} distinct ticker(s) over the last 90 days.")

    subject, html = build_email(filtered, top5, track_rows)
    send_email(subject, html)


if __name__ == "__main__":
    run()
