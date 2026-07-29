#!/usr/bin/env python3
"""
scripts/headless_overkill_scan.py — Run the OverKill (WaveTrend + Volume
Profile) Scan Universe without a browser, filter to high-conviction results
only, and email a summary.

Called by GitHub Actions at 9:30 AM and 1:30 PM CT (Mon-Fri) — see
.github/workflows/overkill_scan_email.yml.

Usage:
  SCAN_SLOT=am python scripts/headless_overkill_scan.py
  SCAN_SLOT=pm python scripts/headless_overkill_scan.py

Required env vars (GitHub Actions secrets):
  GMAIL_ADDRESS        the Gmail account to send FROM
  GMAIL_APP_PASSWORD   a 16-character Gmail App Password for that account
                        (Google Account -> Security -> 2-Step Verification ->
                        App Passwords — a regular Gmail password will NOT work)
  OVERKILL_EMAIL_TO    recipient address (can be the same as GMAIL_ADDRESS)

Optional env vars:
  OVERKILL_MIN_STARS       minimum star rating to include (default 4)
  OVERKILL_WEEKLY_FRESH    weekly lookback in bars (default matches the live UI)
  OVERKILL_MONTHLY_FRESH   monthly lookback in bars (badge-only, same default)
"""

import os, sys, smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ── Mock Streamlit so scanner modules import/run without a server, same
# approach as scripts/headless_scan.py — quiet logs, no-op UI calls, and
# st.cache_data becomes a passthrough (no caching needed for a single run).
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
from config import FTF_UNIVERSE
from scanners.overkill_check import (
    _scan_universe, _analyze_ticker, _color_variant, _sort_color_group,
    _verdict_stars, _vp_position, DEFAULT_WEEKLY_FRESH_BARS, DEFAULT_MONTHLY_FRESH_BARS,
)

SLOT           = os.environ.get("SCAN_SLOT", "am").lower()
MIN_STARS      = int(os.environ.get("OVERKILL_MIN_STARS", 4))
WEEKLY_FRESH   = int(os.environ.get("OVERKILL_WEEKLY_FRESH", DEFAULT_WEEKLY_FRESH_BARS))
MONTHLY_FRESH  = int(os.environ.get("OVERKILL_MONTHLY_FRESH", DEFAULT_MONTHLY_FRESH_BARS))


def log(msg: str):
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}", flush=True)


def _filter_min_stars(results: list[dict], min_stars: int) -> list[dict]:
    out = []
    for r in results:
        if "error" in r:
            continue
        last = r.get("last_w") or r.get("last_m")
        stars = _verdict_stars(last, r.get("price_now"), r.get("vp"))
        if stars >= min_stars:
            r["_stars"] = stars
            out.append(r)
    return out


def _row_html(r: dict, color_hex: str) -> str:
    last = r.get("last_w") or r.get("last_m")
    bias_text, _ = _vp_position(r.get("price_now"), r.get("vp"), last["color"] if last else None)
    dot_txt = last["date"] if last else "—"
    age_txt = f'{last["bars_ago"]}b ago' if last else "—"
    price = r.get("price_now")
    price_txt = f"${price:,.2f}" if price is not None else "—"
    return (
        '<tr>'
        f'<td style="padding:6px 10px;font-weight:bold;color:{color_hex};border-bottom:1px solid #333">{r["ticker"]}</td>'
        f'<td style="padding:6px 10px;color:#F5C842;border-bottom:1px solid #333">{"★"*r["_stars"]}</td>'
        f'<td style="padding:6px 10px;border-bottom:1px solid #333">{price_txt}</td>'
        f'<td style="padding:6px 10px;color:#888;font-size:12px;border-bottom:1px solid #333">{dot_txt}</td>'
        f'<td style="padding:6px 10px;color:#888;font-size:12px;border-bottom:1px solid #333">{age_txt}</td>'
        f'<td style="padding:6px 10px;font-size:12px;border-bottom:1px solid #333">{bias_text}</td>'
        '</tr>'
    )


def _table_html(results: list[dict], label: str, color_hex: str) -> str:
    if not results:
        return f'<p style="color:#888;font-size:13px">No {label} tickers at {MIN_STARS}★+ this run.</p>'
    rows = "".join(_row_html(r, color_hex) for r in results)
    header = (
        '<tr style="background:#1a1a1a;color:#fff">'
        '<th style="padding:6px 10px;text-align:left">Ticker</th>'
        '<th style="padding:6px 10px;text-align:left">★</th>'
        '<th style="padding:6px 10px;text-align:left">Price</th>'
        '<th style="padding:6px 10px;text-align:left">Dot</th>'
        '<th style="padding:6px 10px;text-align:left">Age</th>'
        '<th style="padding:6px 10px;text-align:left">Verdict</th>'
        '</tr>'
    )
    return (
        '<table style="border-collapse:collapse;width:100%;font-family:Arial,sans-serif;'
        f'font-size:13px;background:#0d0d0d;color:#eee"><thead>{header}</thead>'
        f'<tbody>{rows}</tbody></table>'
    )


def build_email(green: list[dict], red: list[dict]) -> tuple[str, str]:
    subject = (f"OverKill Scan [{SLOT}] — {len(green)} green / {len(red)} red "
              f"at {MIN_STARS}★+ ({datetime.utcnow().strftime('%Y-%m-%d')})")
    html = f"""
    <div style="font-family:Arial,sans-serif;background:#000;padding:20px">
      <h2 style="color:#F5C842;margin-bottom:4px">OverKill Scan — {MIN_STARS}★ and 5★ only</h2>
      <p style="color:#888;font-size:12px;margin-top:0">
        FTF Universe (~480) · Weekly lookback {WEEKLY_FRESH} bars · {SLOT.upper()} run ·
        {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
      </p>
      <h3 style="color:#22C55E;margin-top:24px">\U0001F7E2 Green Dots ({len(green)})</h3>
      {_table_html(green, "green", "#22C55E")}
      <h3 style="color:#EF4444;margin-top:24px">\U0001F534 Red Dots ({len(red)})</h3>
      {_table_html(red, "red", "#EF4444")}
      <p style="color:#666;font-size:11px;margin-top:24px;line-height:1.5">
        Approximates a public WaveTrend + Volume Profile confluence read — not his exact proprietary
        indicator, and not financial advice. Educational/research use only. Open the OverKill tab in
        Golden Scanner for full charts and the interactive table.
      </p>
    </div>
    """
    return subject, html


def send_email(subject: str, html_body: str) -> None:
    sender = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    # OVERKILL_EMAIL_TO may be one address or a comma-separated list —
    # "a@x.com" or "a@x.com, b@y.com, c@z.com" both work.
    recipients = [addr.strip() for addr in os.environ["OVERKILL_EMAIL_TO"].split(",") if addr.strip()]

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
    for var in ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "OVERKILL_EMAIL_TO"):
        if not os.environ.get(var):
            log(f"ERROR: required env var {var} is not set — add it as a GitHub Actions secret.")
            sys.exit(1)

    log(f"Scanning FTF Universe (~{len(FTF_UNIVERSE)} tickers), "
        f"weekly_fresh={WEEKLY_FRESH}, monthly_fresh={MONTHLY_FRESH}…")

    def _progress(i, total, ticker):
        if i % 40 == 0 or i == total - 1:
            log(f"  {i+1}/{total} — {ticker}")

    candidates = _scan_universe(FTF_UNIVERSE, WEEKLY_FRESH, MONTHLY_FRESH, progress_cb=_progress)
    log(f"Phase 1 done: {len(candidates)} candidate(s) with a fresh weekly dot.")

    green_results, red_results = [], []
    for c in candidates:
        base = _analyze_ticker(c["ticker"])
        if "error" in base:
            continue
        if c["has_green"]:
            green_results.append(_color_variant(base, "Green"))
        if c["has_red"]:
            red_results.append(_color_variant(base, "Red"))

    green_sorted = _filter_min_stars(_sort_color_group(green_results), MIN_STARS)
    red_sorted = _filter_min_stars(_sort_color_group(red_results), MIN_STARS)
    log(f"After {MIN_STARS}★+ filter: {len(green_sorted)} green, {len(red_sorted)} red.")

    if not green_sorted and not red_sorted:
        log(f"Nothing at {MIN_STARS}★+ this run — skipping email (no news is fine, not an error).")
        return

    subject, html = build_email(green_sorted, red_sorted)
    send_email(subject, html)


if __name__ == "__main__":
    run()
