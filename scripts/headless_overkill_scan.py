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
  OVERKILL_MIN_STARS       minimum star rating to include (default 3)
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
    _verdict_stars, _vp_position, _daily_confirm_badge,
    DEFAULT_WEEKLY_FRESH_BARS, DEFAULT_MONTHLY_FRESH_BARS,
)
from scanners import scan_history

SLOT           = os.environ.get("SCAN_SLOT", "am").lower()
MIN_STARS      = int(os.environ.get("OVERKILL_MIN_STARS", 3))
WEEKLY_FRESH   = int(os.environ.get("OVERKILL_WEEKLY_FRESH", DEFAULT_WEEKLY_FRESH_BARS))
MONTHLY_FRESH  = int(os.environ.get("OVERKILL_MONTHLY_FRESH", DEFAULT_MONTHLY_FRESH_BARS))
TODAY          = datetime.utcnow().strftime("%Y-%m-%d")
HISTORY_TAG    = "default"


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
    heart = _daily_confirm_badge(bool(last and last.get("daily_confirmed")))
    return (
        '<tr>'
        f'<td style="padding:6px 10px;font-weight:bold;color:{color_hex};border-bottom:1px solid #333">{r["ticker"]}{heart}</td>'
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


def _fmt_found_date(date_str) -> str:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%b %d")
    except Exception:
        return date_str or "—"


def _track_row_html(row: dict) -> str:
    pct = row.get("pct")
    pct_color = "#888" if pct is None else ("#22C55E" if pct >= 0 else "#EF4444")
    pct_txt = "—" if pct is None else f"{pct:+.1f}%"
    cur_txt = "—" if row.get("current_price") is None else f"${row['current_price']:,.2f}"
    stars = "★" * int(row["stars"]) if row.get("stars") else "—"
    color = row.get("color")
    verdict_color = "#22C55E" if color == "Green" else ("#EF4444" if color == "Red" else "#888")
    return (
        '<tr>'
        f'<td style="padding:6px 10px;font-weight:bold;color:{"#F5C842"};border-bottom:1px solid #333">{row["ticker"]}</td>'
        f'<td style="padding:6px 10px;color:#F5C842;border-bottom:1px solid #333">{stars}</td>'
        f'<td style="padding:6px 10px;font-weight:bold;color:{verdict_color};border-bottom:1px solid #333">{color or "—"}</td>'
        f'<td style="padding:6px 10px;color:#888;font-size:12px;border-bottom:1px solid #333">{_fmt_found_date(row["first_found"])}</td>'
        f'<td style="padding:6px 10px;border-bottom:1px solid #333">${row["first_price"]:,.2f}</td>'
        f'<td style="padding:6px 10px;border-bottom:1px solid #333">{cur_txt}</td>'
        f'<td style="padding:6px 10px;font-weight:bold;color:{pct_color};border-bottom:1px solid #333">{pct_txt}</td>'
        '</tr>'
    )


def _track_record_table_html(track_rows: list[dict]) -> str:
    if not track_rows:
        return '<p style="color:#888;font-size:13px">No track record yet — check back after a few more weeks of runs.</p>'
    header = (
        '<tr style="background:#1a1a1a;color:#fff">'
        '<th style="padding:6px 10px;text-align:left">Ticker</th>'
        '<th style="padding:6px 10px;text-align:left">★</th>'
        '<th style="padding:6px 10px;text-align:left">Verdict</th>'
        '<th style="padding:6px 10px;text-align:left">Dot Date</th>'
        '<th style="padding:6px 10px;text-align:left">Price @ Dot</th>'
        '<th style="padding:6px 10px;text-align:left">Now</th>'
        '<th style="padding:6px 10px;text-align:left">Perf</th>'
        '</tr>'
    )
    rows = "".join(_track_row_html(r) for r in track_rows)
    return (
        '<table style="border-collapse:collapse;width:100%;font-family:Arial,sans-serif;'
        f'font-size:13px;background:#0d0d0d;color:#eee"><thead>{header}</thead>'
        f'<tbody>{rows}</tbody></table>'
    )


def _star_tier_html(tiers: list[dict]) -> str:
    if not tiers:
        return '<p style="color:#888;font-size:13px">No priced track record yet.</p>'
    rows = ""
    for t in tiers:
        stars_txt = "★" * t["stars"] if t["stars"] else "—"
        hit_txt = f'{t["hit_rate"]:.0f}%' if t["hit_rate"] is not None else "—"
        avg_txt = f'{t["avg_return"]:+.1f}%' if t["avg_return"] is not None else "—"
        avg_color = "#888" if t["avg_return"] is None else ("#22C55E" if t["avg_return"] >= 0 else "#EF4444")
        rows += (
            '<tr>'
            f'<td style="padding:6px 10px;color:#F5C842;font-weight:bold;border-bottom:1px solid #333">{stars_txt}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #333">{t["count"]}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #333">{hit_txt}</td>'
            f'<td style="padding:6px 10px;font-weight:bold;color:{avg_color};border-bottom:1px solid #333">{avg_txt}</td>'
            '</tr>'
        )
    header = (
        '<tr style="background:#1a1a1a;color:#fff">'
        '<th style="padding:6px 10px;text-align:left">★ Tier</th>'
        '<th style="padding:6px 10px;text-align:left"># Tickers</th>'
        '<th style="padding:6px 10px;text-align:left">Hit Rate</th>'
        '<th style="padding:6px 10px;text-align:left">Avg Return</th>'
        '</tr>'
    )
    return (
        '<table style="border-collapse:collapse;width:100%;font-family:Arial,sans-serif;'
        f'font-size:13px;background:#0d0d0d;color:#eee"><thead>{header}</thead>'
        f'<tbody>{rows}</tbody></table>'
    )


def build_email(green: list[dict], red: list[dict], track_rows: list[dict]) -> tuple[str, str]:
    subject = (f"OverKill Scan [{SLOT}] — {len(green)} green / {len(red)} red "
              f"at {MIN_STARS}★+ ({datetime.utcnow().strftime('%Y-%m-%d')})")
    html = f"""
    <div style="font-family:Arial,sans-serif;background:#000;padding:20px">
      <h2 style="color:#F5C842;margin-bottom:4px">OverKill Scan — {MIN_STARS}★+ only</h2>
      <p style="color:#888;font-size:12px;margin-top:0">
        FTF Universe (~500) · Weekly lookback {WEEKLY_FRESH} bars · {SLOT.upper()} run ·
        {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
      </p>
      <h3 style="color:#22C55E;margin-top:24px">\U0001F7E2 Green Dots ({len(green)})</h3>
      {_table_html(green, "green", "#22C55E")}
      <h3 style="color:#EF4444;margin-top:24px">\U0001F534 Red Dots ({len(red)})</h3>
      {_table_html(red, "red", "#EF4444")}
      <h3 style="color:#F5C842;margin-top:24px">Performance by Star Rating</h3>
      {_star_tier_html(scan_history.star_tier_breakdown(track_rows))}
      <h3 style="color:#F5C842;margin-top:24px">Track Record — last 6 months</h3>
      {_track_record_table_html(track_rows)}
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

    today_rows = []
    dot_pairs = []
    for color, group in (("Green", green_sorted), ("Red", red_sorted)):
        for r in group:
            last = r.get("last_w") or r.get("last_m")
            dot_date = last["date"] if last else None
            if dot_date:
                dot_pairs.append((r["ticker"], dot_date))
            today_rows.append({
                "ticker": r["ticker"],
                "color": color,
                "stars": r["_stars"],
                "price": r.get("price_now"),   # fallback; replaced below with the dot-date close when fetchable
                "dot_date": dot_date,
                "event_date": dot_date,        # first_found should track the dot itself, not the scan day
                "bars_ago": last["bars_ago"] if last else None,
            })

    # "First price" should be the close ON the dot date, not today's price_now --
    # a dot can be several bars stale by the time a scan first notices it, and using
    # today's price would understate (or hide) performance that already happened
    # between the dot and today. Falls back to price_now if the historical fetch
    # comes up empty for a ticker (delisted, data gap, etc).
    dot_prices = scan_history.fetch_prices_on_dates(dot_pairs) if dot_pairs else {}
    for row in today_rows:
        if row["dot_date"]:
            dot_price = dot_prices.get((row["ticker"], row["dot_date"]))
            if dot_price is not None:
                row["price"] = dot_price

    scan_history.save_snapshot("overkill", HISTORY_TAG, TODAY, today_rows)
    scan_history.prune_old("overkill", HISTORY_TAG, TODAY)
    log(f"Saved OverKill history snapshot for {TODAY} ({len(today_rows)} row(s)).")

    if not green_sorted and not red_sorted:
        log(f"Nothing at {MIN_STARS}★+ this run — skipping email (no news is fine, not an error).")
        return

    track_rows = scan_history.track_record("overkill", HISTORY_TAG, TODAY, today_rows)
    log(f"Track record: {len(track_rows)} distinct ticker(s) over the last 6 months.")

    subject, html = build_email(green_sorted, red_sorted, track_rows)
    send_email(subject, html)


if __name__ == "__main__":
    run()
