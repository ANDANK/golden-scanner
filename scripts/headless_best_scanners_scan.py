#!/usr/bin/env python3
"""
scripts/headless_best_scanners_scan.py — Run the live Best Scanners scan (the
6 keeper scanners + 7Square/8Cross early-signal add-ons) without a browser,
filter to high-conviction results, and email a summary.

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

Filter: a ticker is included if it earns ANY star tier (_stars >= 1) OR is
flagged by 3 or more of the individual scanners (_count >= 3) — these are two
different dimensions (named high-conviction combos vs. raw breadth), so it's
a straight union of both, not a minimum star cutoff like OverKill's email.
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


def log(msg: str):
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}", flush=True)


def _row_html(row) -> str:
    stars = int(row.get("_stars", 0))
    star_txt = "★" * stars if stars else "—"
    count = int(row.get("_count", 0))
    chg = row.get("Chg", 0) or 0
    chg_color = "#22C55E" if chg >= 0 else "#EF4444"
    flags = ", ".join(row.get("Flags") or [])
    return (
        '<tr>'
        f'<td style="padding:6px 10px;font-weight:bold;color:#F5C842;border-bottom:1px solid #333">{row["Ticker"]}</td>'
        f'<td style="padding:6px 10px;color:#F5C842;border-bottom:1px solid #333">{star_txt}</td>'
        f'<td style="padding:6px 10px;border-bottom:1px solid #333">{count}</td>'
        f'<td style="padding:6px 10px;border-bottom:1px solid #333">${row.get("Price", 0):,.2f}</td>'
        f'<td style="padding:6px 10px;color:{chg_color};border-bottom:1px solid #333">{chg:+.1f}%</td>'
        f'<td style="padding:6px 10px;border-bottom:1px solid #333">{row.get("RSI_D", "—")}</td>'
        f'<td style="padding:6px 10px;font-size:12px;border-bottom:1px solid #333">{row.get("Scanners", "")}</td>'
        f'<td style="padding:6px 10px;font-size:12px;color:#888;border-bottom:1px solid #333">{flags}</td>'
        '</tr>'
    )


def _table_html(df) -> str:
    if df.empty:
        return '<p style="color:#888;font-size:13px">Nothing qualified this run.</p>'
    header = (
        '<tr style="background:#1a1a1a;color:#fff">'
        '<th style="padding:6px 10px;text-align:left">Ticker</th>'
        '<th style="padding:6px 10px;text-align:left">★</th>'
        '<th style="padding:6px 10px;text-align:left"># Scanners</th>'
        '<th style="padding:6px 10px;text-align:left">Price</th>'
        '<th style="padding:6px 10px;text-align:left">Chg</th>'
        '<th style="padding:6px 10px;text-align:left">RSI D</th>'
        '<th style="padding:6px 10px;text-align:left">Scanners</th>'
        '<th style="padding:6px 10px;text-align:left">Flags</th>'
        '</tr>'
    )
    rows = "".join(_row_html(r) for _, r in df.iterrows())
    return (
        '<table style="border-collapse:collapse;width:100%;font-family:Arial,sans-serif;'
        f'font-size:13px;background:#0d0d0d;color:#eee"><thead>{header}</thead>'
        f'<tbody>{rows}</tbody></table>'
    )


def build_email(df) -> tuple[str, str]:
    subject = (f"Best Scanners [{SLOT}] — {len(df)} at ★ or 3+ scanners "
               f"({datetime.utcnow().strftime('%Y-%m-%d')})")
    html = f"""
    <div style="font-family:Arial,sans-serif;background:#000;padding:20px">
      <h2 style="color:#F5C842;margin-bottom:4px">Best Scanners — ★ any tier, or 3+ scanners matched</h2>
      <p style="color:#888;font-size:12px;margin-top:0">
        {UNI_KIND} Universe (~{len(UNIVERSE)}) · {SLOT.upper()} run ·
        {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
      </p>
      {_table_html(df)}
      <p style="color:#666;font-size:11px;margin-top:24px;line-height:1.5">
        The 6 keeper scanners (1Mom/2TC/3MF/4TS/5RB/6Prime) plus 7Square/8Cross early-signal
        add-ons. ★ marks rare high-conviction label combos; # Scanners is the raw count of
        individual scanners that fired, independent of the star combo. Educational/research use
        only, not financial advice. Open the Best Scanners tab in Golden Scanner for the full
        interactive table and charts.
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

    filtered = df[(df["_stars"] >= 1) | (df["_count"] >= 3)].copy()
    filtered = filtered.sort_values(["_stars", "_count"], ascending=[False, False]).reset_index(drop=True)
    log(f"After filter (★≥1 OR scanners≥3): {len(filtered)} ticker(s).")

    if filtered.empty:
        log("Nothing qualified at ★ or 3+ scanners this run — skipping email.")
        return

    subject, html = build_email(filtered)
    send_email(subject, html)


if __name__ == "__main__":
    run()
