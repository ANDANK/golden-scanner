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

SLOT      = os.environ.get("SCAN_SLOT", "am").lower()
UNI_KIND  = os.environ.get("BEST_SCANNERS_UNIVERSE", "FTF").upper()
_UNIVERSES = {"FTF": FTF_UNIVERSE, "MTPA": MTPA_200, "SP500": SP500_SAMPLE[:200]}
UNIVERSE  = _UNIVERSES.get(UNI_KIND, FTF_UNIVERSE)
IS_QUALITY_UNIVERSE = UNI_KIND in ("FTF", "SP500")
TOP_N = 5

_VERDICT_COLOR = {"Strong Setup": "#3fcf7f", "Mixed Signal": "#f0b94a"}
_VERDICT_BG = {"Strong Setup": "rgba(63,207,127,0.16)", "Mixed Signal": "rgba(240,185,74,0.16)"}


def log(msg: str):
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}", flush=True)


def _hold_text(hold_range) -> str:
    if not hold_range:
        return "—"
    lo, hi = hold_range
    return f"{lo}-{hi}d"


def _points_text(verdict: str, hold_range, n: int) -> str:
    if hold_range == (10, 90):
        span = "Works short or long-term"
    elif hold_range == (10, 60):
        span = "Validated through ~2 months"
    else:
        span = "Best for short-term (10-30d)"
    sample = "Large, consistent sample" if verdict == "Strong Setup" else "Smaller sample — worth confirming"
    return f"{span} &middot; {sample}"


def _top_card_html(row) -> str:
    return (
        '<div style="background:rgba(245,200,66,0.10);border:1px solid rgba(245,200,66,0.30);'
        'border-radius:10px;padding:10px 12px">'
        f'<span style="font-family:monospace;font-weight:700;font-size:14px;color:#F5C842">{row["Ticker"]}</span>'
        f'<div style="font-size:11px;color:#a89f8a;margin-top:4px">'
        f'{row["_verdict"]} &middot; {_hold_text(row["_hold_range"])} &middot; N={int(row["_edge_n"]):,}</div>'
        '</div>'
    )


def _card_html(row) -> str:
    verdict = row["_verdict"]
    color = _VERDICT_COLOR.get(verdict, "#8b8578")
    bg = _VERDICT_BG.get(verdict, "rgba(139,133,120,0.16)")
    scanners = [s.strip() for s in (row.get("Scanners") or "").split("·") if s.strip()]
    scanner_pills = "".join(
        f'<span style="font-family:monospace;font-size:9.5px;color:#726b5a;'
        f'background:#1d1a13;border-radius:4px;padding:1px 6px;margin:0 4px 4px 0;display:inline-block">{s}</span>'
        for s in scanners
    )
    return (
        '<div style="background:#17140f;border:1px solid rgba(245,200,66,0.08);border-radius:9px;padding:10px 11px">'
        '<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px">'
        f'<span style="font-family:monospace;font-weight:700;font-size:13px;color:#F5C842">{row["Ticker"]}</span>'
        f'<span style="font-family:monospace;font-size:10.5px;color:#726b5a">${row.get("Price", 0):,.2f}</span>'
        '</div>'
        f'<span style="display:inline-block;font-size:10px;font-weight:600;border-radius:5px;padding:3px 7px;'
        f'margin-bottom:6px;color:{color};background:{bg}">{verdict}</span>'
        f'<div style="font-size:10.5px;color:#a89f8a;margin-bottom:5px">{_hold_text(row["_hold_range"])}</div>'
        f'<div style="font-size:10.5px;color:#726b5a;margin-bottom:7px">{_points_text(verdict, row["_hold_range"], row["_edge_n"])}</div>'
        f'<div>{scanner_pills}</div>'
        '</div>'
    )


def _detail_row_html(row) -> str:
    n = row.get("_edge_n")
    score = row.get("_edge_score")
    return (
        '<tr>'
        f'<td style="padding:7px 10px;font-weight:bold;color:#F5C842;border-bottom:1px solid #262626">{row["Ticker"]}</td>'
        f'<td style="padding:7px 10px;color:{_VERDICT_COLOR.get(row["_verdict"], "#8b8578")};border-bottom:1px solid #262626">{row["_verdict"]}</td>'
        f'<td style="padding:7px 10px;color:#a89f8a;border-bottom:1px solid #262626">{_hold_text(row["_hold_range"])}</td>'
        f'<td style="padding:7px 10px;font-family:monospace;font-size:11px;color:#726b5a;border-bottom:1px solid #262626">{row.get("_combo") or "—"}</td>'
        f'<td style="padding:7px 10px;font-family:monospace;color:#a89f8a;border-bottom:1px solid #262626">{int(n):,}</td>'
        f'<td style="padding:7px 10px;font-family:monospace;color:#a89f8a;border-bottom:1px solid #262626">{score:+.2f}%</td>'
        '</tr>'
    )


def build_email(filtered, top5) -> tuple[str, str]:
    subject = (f"Best Scanners [{SLOT}] — {len(filtered)} setups"
               + (f", {len(top5)} featured" if len(top5) else "")
               + f" ({datetime.utcnow().strftime('%Y-%m-%d')})")

    top5_html = ""
    if len(top5):
        cards = "".join(_top_card_html(r) for _, r in top5.iterrows())
        top5_html = (
            '<div style="font-size:11px;font-weight:600;color:#c9a53a;text-transform:uppercase;'
            'letter-spacing:0.06em;margin:0 0 10px">'
            f'Top picks today ({len(top5)} of possible {TOP_N})</div>'
            f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:22px">{cards}</div>'
        )
    elif not IS_QUALITY_UNIVERSE:
        top5_html = (
            '<p style="color:#666;font-size:11px;margin-bottom:20px">'
            f'No Top 5 this run — {UNI_KIND} isn\'t a large-cap-anchored universe, '
            'so featured picks are skipped (still shown in the full list below).</p>'
        )

    if filtered.empty:
        grid_html = '<p style="color:#888;font-size:13px">Nothing qualified this run.</p>'
        table_html = ""
    else:
        cards = "".join(_card_html(r) for _, r in filtered.iterrows())
        grid_html = f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-bottom:22px">{cards}</div>'
        header = (
            '<tr style="background:#1d1a13;color:#fff">'
            '<th style="padding:8px 10px;text-align:left;font-size:11px">Ticker</th>'
            '<th style="padding:8px 10px;text-align:left;font-size:11px">Verdict</th>'
            '<th style="padding:8px 10px;text-align:left;font-size:11px">Hold</th>'
            '<th style="padding:8px 10px;text-align:left;font-size:11px">Combo</th>'
            '<th style="padding:8px 10px;text-align:left;font-size:11px">N</th>'
            '<th style="padding:8px 10px;text-align:left;font-size:11px">Edge</th>'
            '</tr>'
        )
        rows = "".join(_detail_row_html(r) for _, r in filtered.iterrows())
        table_html = (
            '<div style="font-size:11px;font-weight:600;color:#c9a53a;text-transform:uppercase;'
            'letter-spacing:0.06em;margin:0 0 10px">Full detail</div>'
            '<div style="overflow-x:auto;border:1px solid #262626;border-radius:10px">'
            '<table style="border-collapse:collapse;width:100%;font-family:Arial,sans-serif;'
            f'font-size:12px;background:#0d0d0d;color:#eee"><thead>{header}</thead>'
            f'<tbody>{rows}</tbody></table></div>'
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
        <b style="color:#F5C842">How to read this:</b> look at the colored badge and the hold-length
        line — that's the whole decision. Everything else is detail for anyone who wants to dig in.
      </div>
      {top5_html}
      <div style="font-size:11px;font-weight:600;color:#c9a53a;text-transform:uppercase;
                  letter-spacing:0.06em;margin:0 0 10px">Everything that qualified</div>
      {grid_html}
      {table_html}
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

    if filtered.empty:
        log("Nothing qualified this run — skipping email.")
        return

    top5 = filtered.iloc[0:0]
    if IS_QUALITY_UNIVERSE:
        top5 = filtered[filtered["_verdict"] == "Strong Setup"].head(TOP_N)
    log(f"Top picks: {len(top5)} of a possible {TOP_N} (quality universe: {IS_QUALITY_UNIVERSE}).")

    subject, html = build_email(filtered, top5)
    send_email(subject, html)


if __name__ == "__main__":
    run()
