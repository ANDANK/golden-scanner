#!/usr/bin/env python3
"""
scripts/headless_overkill_shorts_email.py — emails the YouTube Shorts digest.

Runs right after scripts/overkill_shorts_scan.py has extracted and committed
new picks (see .github/workflows/refresh_overkill.yml), and sends:

  1. Every entry from the last 30 days across all watched channels — date,
     channel, ticker, bias, what was said, and the price captured on the
     day of the call. Rows with no ticker are general takeaways.
  2. A 6-month performance table, Bullish and Bearish split, covering only
     the channels that make directional stock calls.

Deliberately reuses scanners/overkill_shorts_perf.py's _load_picks() and
_score() rather than reimplementing them, so the email and the Shorts Perf
tab can never drift apart or disagree about a number. Streamlit is mocked
first, the same way the other headless scripts do it, so importing a UI
module from a cron job is safe.

Only sends when the run that preceded it actually found new picks — the
workflow gates this step on that. The channel doesn't post every day and
this runs twice daily, so an unconditional send would mostly be delivering
"nothing happened" twice a day.

Required env vars (GitHub Actions secrets, shared with the other emails):
  GMAIL_ADDRESS        the Gmail account to send FROM
  GMAIL_APP_PASSWORD   a 16-character Gmail App Password for that account
  OVERKILL_EMAIL_TO    recipient address, or a comma-separated list

Usage:
  python scripts/headless_overkill_shorts_email.py
"""

import os, sys, smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.email_footer import with_footer, TAG_YT_SHORTS

# ── Mock Streamlit so the perf module imports without a server (same approach
# as scripts/headless_overkill_scan.py). st.cache_data becomes a passthrough,
# which is what we want for a single run anyway.
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
import json
from scanners import overkill_shorts_perf as perf

DIGEST_DAYS = 30      # how far back the "recent picks" section reaches
PERF_DAYS = 182       # 6 months, matching the OverKill track-record window

_TH = "padding:6px 10px;text-align:left"
_TD = "padding:6px 10px;border-top:1px solid #222"


def _pct(v: float) -> str:
    col = "#22c55e" if v >= 0 else "#ef4444"
    return f'<span style="color:{col};font-weight:700">{v:+.1f}%</span>'


def _recent_picks(days: int) -> list[dict]:
    """Every pick from the last `days` days, newest first — the raw feed, not
    deduped: seeing that a ticker was repeated across several videos is itself
    signal, and it's what the Shorts tab shows."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        with open(perf.DATA_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    out = []
    for vid in data.get("videos", []):
        if vid.get("date", "") < cutoff:
            continue
        for p in vid.get("picks", []):
            out.append({**p, "date": vid.get("date", ""),
                        "url": vid.get("url", ""), "title": vid.get("title", ""),
                        "channel": vid.get("channel_name") or "OverKill"})
    out.sort(key=lambda r: (r["date"], r.get("ticker", "")), reverse=True)
    return out


def _picks_table(rows: list[dict]) -> str:
    if not rows:
        return '<p style="color:#888;font-size:13px">No picks in this window.</p>'
    header = ("".join(f'<th style="{_TH}">{h}</th>'
                      for h in ["Date", "Channel", "Ticker", "Bias", "Price @ Call", "What was said"]))
    body = ""
    for r in rows:
        bias = r.get("bias", "")
        bias_col = "#22c55e" if bias == "Bullish" else "#ef4444" if bias == "Bearish" else "#888"
        price = r.get("price")
        date_cell = (f'<a href="{r["url"]}" style="color:#888;text-decoration:none">{r["date"]}</a>'
                     if r.get("url") else r["date"])
        body += (
            "<tr>"
            f'<td style="{_TD};white-space:nowrap;color:#888">{date_cell}</td>'
            f'<td style="{_TD};color:#8ab4f8;white-space:nowrap">{r.get("channel","")}</td>'
            f'<td style="{_TD};font-weight:700;color:#f5c842">'
            + (r.get("ticker") or '<span style="color:#888">general</span>') + '</td>'
            f'<td style="{_TD};color:{bias_col}">{bias}</td>'
            f'<td style="{_TD};white-space:nowrap">'
            + (f"${price:,.2f}" if price else '<span style="color:#888">&mdash;</span>')
            + "</td>"
            f'<td style="{_TD};color:#ccc;line-height:1.5">{r.get("notes","")}</td>'
            "</tr>"
        )
    return ('<table style="border-collapse:collapse;width:100%;font-family:Arial,sans-serif;'
            'font-size:13px;background:#0d0d0d;color:#eee">'
            f'<thead><tr style="background:#1a1a1a;color:#fff">{header}</tr></thead>'
            f"<tbody>{body}</tbody></table>")


def _perf_table(rows: list[dict]) -> str:
    if not rows:
        return '<p style="color:#888;font-size:13px">No scored calls in this window yet.</p>'
    header = ("".join(f'<th style="{_TH}">{h}</th>'
                      for h in ["Ticker", "Channel", "Called", "Price @ Call", "Now", "Perf",
                                "High", "% High", "Low", "% Low"]))
    body = ""
    for r in rows:
        body += (
            "<tr>"
            f'<td style="{_TD};font-weight:700;color:#f5c842">{r["ticker"]}</td>'
            f'<td style="{_TD};color:#8ab4f8;white-space:nowrap">{r.get("channel","")}</td>'
            f'<td style="{_TD};white-space:nowrap;color:#888">{r["date"]}</td>'
            f'<td style="{_TD};white-space:nowrap">${r["entry"]:,.2f}</td>'
            f'<td style="{_TD};white-space:nowrap">${r["current"]:,.2f}</td>'
            f'<td style="{_TD};white-space:nowrap">{_pct(r["pct"])}</td>'
            f'<td style="{_TD};white-space:nowrap">${r["high"]:,.2f}</td>'
            f'<td style="{_TD};white-space:nowrap">{_pct(r["high_pct"])}</td>'
            f'<td style="{_TD};white-space:nowrap">${r["low"]:,.2f}</td>'
            f'<td style="{_TD};white-space:nowrap">{_pct(r["low_pct"])}</td>'
            "</tr>"
        )
    return ('<table style="border-collapse:collapse;width:100%;font-family:Arial,sans-serif;'
            'font-size:13px;background:#0d0d0d;color:#eee">'
            f'<thead><tr style="background:#1a1a1a;color:#fff">{header}</tr></thead>'
            f"<tbody>{body}</tbody></table>")


def _summary_line(rows: list[dict]) -> str:
    if not rows:
        return ""
    wins = sum(1 for r in rows if r["pct"] > 0)
    avg = sum(r["pct"] for r in rows) / len(rows)
    return (f'<p style="color:#888;font-size:12px;margin:4px 0 8px">'
            f'{len(rows)} call(s) · hit rate <b style="color:#eee">{wins}/{len(rows)} '
            f'({wins / len(rows) * 100:.0f}%)</b> · avg {_pct(avg)}</p>')


def build_email(recent: list[dict], green: list[dict], red: list[dict]) -> str:
    n_green = sum(1 for r in recent if r.get("bias") == "Bullish")
    n_red = sum(1 for r in recent if r.get("bias") == "Bearish")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""
    <div style="font-family:Arial,sans-serif;background:#000;padding:20px">
      <h2 style="color:#f5c842;margin:0 0 4px">YouTube Shorts</h2>
      <p style="color:#888;font-size:12px;margin:0 0 16px">
        Entries from the last {DIGEST_DAYS} days across the watched finance channels
        ({len(recent)} pick(s) · {n_green} green · {n_red} red).
        Auto-extracted from the video captions · {stamp} · not financial advice.
      </p>

      <h3 style="color:#eee;margin:18px 0 6px">Recent picks &mdash; last {DIGEST_DAYS} days</h3>
      {_picks_table(recent)}

      <h3 style="color:#22c55e;margin:22px 0 2px">Bullish &mdash; buy calls ({PERF_DAYS // 30} months)</h3>
      {_summary_line(green)}
      {_perf_table(green)}

      <h3 style="color:#ef4444;margin:22px 0 2px">Bearish &mdash; sell/short calls ({PERF_DAYS // 30} months)</h3>
      {_summary_line(red)}
      {_perf_table(red)}

      <p style="color:#666;font-size:11px;margin-top:16px;line-height:1.6">
        Perf is measured from the price on the day of the call. A bearish call wins when price falls,
        so its Perf is flipped &mdash; a price <i>drop</i> shows positive,
        meaning the call was right. High/Low are the raw range since the call and
        are never flipped. Scored per first call of each kind, so a ticker called
        Bullish in June and Bearish in August counts as two separate calls.
      </p>
    </div>
    """


def send_email(subject: str, html_body: str) -> None:
    sender = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipients = [a.strip() for a in os.environ["OVERKILL_EMAIL_TO"].split(",") if a.strip()]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(with_footer(html_body, TAG_YT_SHORTS), "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())


def main():
    for var in ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "OVERKILL_EMAIL_TO"):
        if not os.environ.get(var):
            print(f"ERROR: {var} not set — add it as a GitHub Actions secret.")
            sys.exit(1)

    recent = _recent_picks(DIGEST_DAYS)

    # Perf: same loader and scorer the Shorts Perf tab uses, windowed to 6
    # months so old calls eventually age out of the hit rate.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=PERF_DAYS)).strftime("%Y-%m-%d")
    scored = perf._score([p for p in perf._load_picks() if p["date"] >= cutoff])
    green = [r for r in scored if r["bias"] == "Bullish"]
    red = [r for r in scored if r["bias"] == "Bearish"]

    n_green = sum(1 for r in recent if r.get("bias") == "Bullish")
    subject = (f"YouTube Shorts — {len(recent)} pick(s) in {DIGEST_DAYS}d "
               f"({n_green} green) — {datetime.now(timezone.utc).strftime('%b %d')}")
    send_email(subject, build_email(recent, green, red))
    print(f"Sent: {len(recent)} recent pick(s), "
          f"{len(green)} green + {len(red)} red scored over {PERF_DAYS}d.")


if __name__ == "__main__":
    main()
