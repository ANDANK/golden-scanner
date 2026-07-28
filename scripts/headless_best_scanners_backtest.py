#!/usr/bin/env python3
"""
scripts/headless_best_scanners_backtest.py — Run the Best Scanners ★ combo
backtest without a browser and email the results.

Exists because the interactive Backtest mode in the app (scanners/home.py)
keeps getting interrupted on large universe / long lookback combinations —
Streamlit Community Cloud throttles CPU on long-blocking sessions, and even
without an explicit throttle notice, big runs (FTF ~480 tickers × several
years) reliably get cut off partway through with no error, just a silent
reset. A GitHub Actions runner is dedicated (not shared/throttled) and gets
a multi-hour budget, so the exact same computation just finishes there.

Manual trigger only (workflow_dispatch) — see
.github/workflows/best_scanners_backtest.yml. This isn't a recurring alert
like the scan/email pipelines; run it whenever you want to validate or
recalibrate the ★ combo rules against a specific universe/lookback/hold
combination.

Usage:
  BT_UNIVERSE=FTF BT_LOOKBACK_YEARS=5 BT_HOLD_DAYS=90 python scripts/headless_best_scanners_backtest.py

Required env vars (GitHub Actions secrets):
  GMAIL_ADDRESS        the Gmail account to send FROM
  GMAIL_APP_PASSWORD   a 16-character Gmail App Password for that account
  OVERKILL_EMAIL_TO    recipient address(es), reused from the other email
                        scripts — set BEST_SCANNERS_EMAIL_TO instead if you
                        want this to go to a different list

Optional env vars:
  BEST_SCANNERS_EMAIL_TO   overrides OVERKILL_EMAIL_TO for this run only
  BT_UNIVERSE              FTF / MTPA / SP500 (default FTF, ~480 tickers)
  BT_LOOKBACK_YEARS        1-10 (default 5)
  BT_HOLD_DAYS             10-250 (default 90)

Unlike the scan/email scripts, this always sends an email — even zero
signals is a meaningful result here (and the per-ticker failure-reason
breakdown is worth seeing either way, not just silently skipped).
"""

import os, sys, csv, smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ── Mock Streamlit so scanner modules import/run without a server, same
# approach as the other headless_*.py scripts.
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
from scanners.home import _run_best_scanners_backtest, _aggregate_best_scanners_backtest

UNIVERSE_KIND  = os.environ.get("BT_UNIVERSE", "FTF").upper()
LOOKBACK_YEARS = int(os.environ.get("BT_LOOKBACK_YEARS", 5))
HOLD_DAYS      = int(os.environ.get("BT_HOLD_DAYS", 90))
_UNIVERSES = {"FTF": FTF_UNIVERSE, "MTPA": MTPA_200, "SP500": SP500_SAMPLE[:200]}
UNIVERSE = _UNIVERSES.get(UNIVERSE_KIND, FTF_UNIVERSE)

DATA_DIR = os.path.join(ROOT, "data")


def log(msg: str):
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}", flush=True)


def _agg_table_html(agg) -> str:
    if agg.empty:
        return '<p style="color:#888;font-size:13px">No historical ★ signals found in this window.</p>'
    header = (
        '<tr style="background:#1a1a1a;color:#fff">'
        '<th style="padding:6px 10px;text-align:left">★</th>'
        '<th style="padding:6px 10px;text-align:left">Signals</th>'
        '<th style="padding:6px 10px;text-align:left">Win Rate (beats SPY)</th>'
        '<th style="padding:6px 10px;text-align:left">Avg Excess</th>'
        '<th style="padding:6px 10px;text-align:left">Avg Stock Return</th>'
        '</tr>'
    )
    rows = ""
    for _, r in agg.iterrows():
        stars_label = "★" * int(r["stars"]) if r["stars"] > 0 else "— (0)"
        wr = r["win_rate"]
        wr_color = "#22C55E" if wr >= 55 else ("#F5C842" if wr >= 45 else "#EF4444")
        rel_color = "#22C55E" if r["avg_rel"] >= 0 else "#EF4444"
        stock_color = "#22C55E" if r["avg_stock"] >= 0 else "#EF4444"
        rows += (
            '<tr>'
            f'<td style="padding:6px 10px;color:#F5C842;border-bottom:1px solid #333">{stars_label}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #333">{int(r["n"])}</td>'
            f'<td style="padding:6px 10px;color:{wr_color};font-weight:700;border-bottom:1px solid #333">{wr:.0f}%</td>'
            f'<td style="padding:6px 10px;color:{rel_color};border-bottom:1px solid #333">{r["avg_rel"]:+.1f}%</td>'
            f'<td style="padding:6px 10px;color:{stock_color};border-bottom:1px solid #333">{r["avg_stock"]:+.1f}%</td>'
            '</tr>'
        )
    return (
        '<table style="border-collapse:collapse;width:100%;font-family:Arial,sans-serif;'
        f'font-size:13px;background:#0d0d0d;color:#eee"><thead>{header}</thead>'
        f'<tbody>{rows}</tbody></table>'
    )


def build_email(records: list[dict], agg, reasons: dict) -> tuple[str, str]:
    n = len(records)
    wins = sum(1 for r in records if r["win"])
    subject = (f"Best Scanners Backtest — {UNIVERSE_KIND} {LOOKBACK_YEARS}y/{HOLD_DAYS}d — "
               f"{n} signals ({datetime.utcnow().strftime('%Y-%m-%d')})")
    reasons_txt = " · ".join(f"{v} × {k}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]))
    html = f"""
    <div style="font-family:Arial,sans-serif;background:#000;padding:20px">
      <h2 style="color:#F5C842;margin-bottom:4px">Best Scanners Backtest</h2>
      <p style="color:#888;font-size:12px;margin-top:0">
        {UNIVERSE_KIND} universe (~{len(UNIVERSE)}) · {LOOKBACK_YEARS}-year lookback ·
        {HOLD_DAYS}-day hold · {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
      </p>
      <p style="color:#ccc;font-size:13px">{n} historical ★ signals ({wins} beat SPY, {n - wins} didn't)</p>
      {_agg_table_html(agg)}
      <p style="color:#666;font-size:11px;margin-top:20px">Diagnostics — {reasons_txt}</p>
      <p style="color:#666;font-size:11px;margin-top:16px;line-height:1.5">
        "Win" = the stock's forward return over the hold period beat SPY's return over the same
        window, not just "went up". Raw per-signal records are attached as a CSV. Educational/
        research use only, not financial advice.
      </p>
    </div>
    """
    return subject, html


def send_email(subject: str, html_body: str, csv_path: str | None) -> None:
    sender = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    to_raw = os.environ.get("BEST_SCANNERS_EMAIL_TO") or os.environ["OVERKILL_EMAIL_TO"]
    recipients = [addr.strip() for addr in to_raw.split(",") if addr.strip()]

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html"))

    if csv_path and os.path.exists(csv_path):
        with open(csv_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(csv_path)}"')
        msg.attach(part)

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

    log(f"Backtesting {UNIVERSE_KIND} (~{len(UNIVERSE)} tickers), "
        f"lookback={LOOKBACK_YEARS}y, hold={HOLD_DAYS}d…")

    def _cb(i, total, ticker):
        if i % 20 == 0 or i == total - 1:
            log(f"  {i + 1}/{total} — {ticker}")

    records, reasons = _run_best_scanners_backtest(UNIVERSE, LOOKBACK_YEARS, HOLD_DAYS, progress_cb=_cb)
    log(f"Done: {len(records)} signal(s). Reasons: {reasons}")

    agg = _aggregate_best_scanners_backtest(records)

    csv_path = None
    if records:
        os.makedirs(DATA_DIR, exist_ok=True)
        csv_path = os.path.join(
            DATA_DIR,
            f"bs_backtest_{UNIVERSE_KIND}_{LOOKBACK_YEARS}y_{HOLD_DAYS}d_"
            f"{datetime.utcnow().strftime('%Y%m%d_%H%M')}.csv",
        )
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["ticker", "date", "stars", "stock_ret",
                                                     "spy_ret", "rel_ret", "win"])
            writer.writeheader()
            writer.writerows(records)
        log(f"Wrote {csv_path}")

    subject, html = build_email(records, agg, reasons)
    send_email(subject, html, csv_path)


if __name__ == "__main__":
    run()
