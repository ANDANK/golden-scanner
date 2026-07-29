#!/usr/bin/env python3
"""
scripts/headless_best_scanners_full_analysis.py — Backtest every individual
scanner and every 1-3-scanner combo (92 total), not just the ones hardcoded
in _STAR_RULES, plus compare the * tier system against raw scanner count as
predictors. Emails the aggregated summary; raw per-onset records (can run
into the hundreds of thousands of rows for a full universe/lookback) are
written to CSV and uploaded as a workflow artifact only, not emailed.

Manual trigger only (workflow_dispatch) — see
.github/workflows/best_scanners_full_analysis.yml. This is a research tool,
not a recurring alert.

Usage:
  BT_UNIVERSE=FTF BT_LOOKBACK_YEARS=5 BT_HOLD_DAYS=90 python scripts/headless_best_scanners_full_analysis.py

Required env vars (GitHub Actions secrets):
  GMAIL_ADDRESS, GMAIL_APP_PASSWORD, and OVERKILL_EMAIL_TO (or
  BEST_SCANNERS_EMAIL_TO override) — reused from the other email scripts.

Optional env vars:
  BT_UNIVERSE          FTF / MTPA / SP500 (default FTF, ~480 tickers)
  BT_LOOKBACK_YEARS     1-10 (default 5)
  BT_HOLD_DAYS          10-250 (default 90)
  BT_MIN_N              minimum onset events for a combo to be "ranked" (default 30)
  BT_TOP_N              how many top combos to show in the email body (default 25)
"""

import os, sys, csv, smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

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

from config import FTF_UNIVERSE, MTPA_200, SP500_SAMPLE
from scanners.home import _run_full_analysis_backtest, _aggregate_full_analysis

UNIVERSE_KIND  = os.environ.get("BT_UNIVERSE", "FTF").upper()
LOOKBACK_YEARS = int(os.environ.get("BT_LOOKBACK_YEARS", 5))
HOLD_DAYS      = int(os.environ.get("BT_HOLD_DAYS", 90))
MIN_N          = int(os.environ.get("BT_MIN_N", 30))
TOP_N          = int(os.environ.get("BT_TOP_N", 25))
_UNIVERSES = {"FTF": FTF_UNIVERSE, "MTPA": MTPA_200, "SP500": SP500_SAMPLE[:200]}
UNIVERSE = _UNIVERSES.get(UNIVERSE_KIND, FTF_UNIVERSE)

DATA_DIR = os.path.join(ROOT, "data")


def log(msg: str):
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}", flush=True)


def _rows_html(rows, tier_label="Combo") -> str:
    if not rows:
        return '<p style="color:#888;font-size:13px">None met the minimum sample size.</p>'
    header = (
        '<tr style="background:#1a1a1a;color:#fff">'
        f'<th style="padding:6px 10px;text-align:left">{tier_label}</th>'
        '<th style="padding:6px 10px;text-align:left">N</th>'
        '<th style="padding:6px 10px;text-align:left">Win Rate</th>'
        '<th style="padding:6px 10px;text-align:left">Avg Excess</th>'
        '<th style="padding:6px 10px;text-align:left">Avg Stock Return</th>'
        '</tr>'
    )
    body = ""
    for r in rows:
        wr = r["win_rate"]
        wr_color = "#22C55E" if wr >= 55 else ("#F5C842" if wr >= 45 else "#EF4444")
        rel_color = "#22C55E" if r["avg_rel"] >= 0 else "#EF4444"
        stock_color = "#22C55E" if r["avg_stock"] >= 0 else "#EF4444"
        body += (
            '<tr>'
            f'<td style="padding:6px 10px;color:#F5C842;border-bottom:1px solid #333;font-size:12px">{r["tier"]}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #333">{int(r["n"])}</td>'
            f'<td style="padding:6px 10px;color:{wr_color};font-weight:700;border-bottom:1px solid #333">{wr:.0f}%</td>'
            f'<td style="padding:6px 10px;color:{rel_color};border-bottom:1px solid #333">{r["avg_rel"]:+.2f}%</td>'
            f'<td style="padding:6px 10px;color:{stock_color};border-bottom:1px solid #333">{r["avg_stock"]:+.2f}%</td>'
            '</tr>'
        )
    return (
        '<table style="border-collapse:collapse;width:100%;font-family:Arial,sans-serif;'
        f'font-size:13px;background:#0d0d0d;color:#eee"><thead>{header}</thead>'
        f'<tbody>{body}</tbody></table>'
    )


def build_email(agg) -> tuple[str, str]:
    n_total = int(agg["n"].sum()) if not agg.empty else 0
    subject = (f"Best Scanners Full Analysis — {UNIVERSE_KIND} {LOOKBACK_YEARS}y/{HOLD_DAYS}d — "
               f"{n_total} onsets ({datetime.utcnow().strftime('%Y-%m-%d')})")

    if agg.empty:
        html = '<p style="color:#888">No historical signals found in this window.</p>'
        return subject, html

    ranked = agg[agg["ranked"]]

    # 1. individual scanners = combo dimension, single-label tiers (no "+")
    singles = ranked[(ranked["dimension"] == "combo") & (~ranked["tier"].str.contains(r"\+"))]
    singles = singles.sort_values("avg_rel", ascending=False).to_dict("records")

    # 2. best combos (2-3 scanners) = combo dimension, multi-label tiers
    multis = ranked[(ranked["dimension"] == "combo") & (ranked["tier"].str.contains(r"\+"))]
    multis = multis.sort_values("avg_rel", ascending=False).head(TOP_N).to_dict("records")
    n_multi_ranked = int((ranked["dimension"] == "combo").sum()) - len(singles)

    # 3. star tier vs raw count, side by side
    star_rows = agg[agg["dimension"] == "star"].sort_values("tier", ascending=False).to_dict("records")
    count_rows = agg[agg["dimension"] == "count"].sort_values(
        "tier", key=lambda s: s.astype(int), ascending=False).to_dict("records")

    html = f"""
    <div style="font-family:Arial,sans-serif;background:#000;padding:20px">
      <h2 style="color:#F5C842;margin-bottom:4px">Best Scanners — Full Analysis</h2>
      <p style="color:#888;font-size:12px;margin-top:0">
        {UNIVERSE_KIND} universe (~{len(UNIVERSE)}) · {LOOKBACK_YEARS}-year lookback ·
        {HOLD_DAYS}-day hold · min {MIN_N} onsets to rank · {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
      </p>

      <h3 style="color:#F5C842;margin-top:22px">Individual Scanners (which of 8 is best alone)</h3>
      {_rows_html(singles, "Scanner")}

      <h3 style="color:#F5C842;margin-top:22px">Top {len(multis)} Combos (2-3 scanners, ranked by excess return)</h3>
      <p style="color:#888;font-size:11px;margin:2px 0 8px">
        {n_multi_ranked} combos met the {MIN_N}-onset minimum in total — full list in the attached CSV.
      </p>
      {_rows_html(multis, "Combo")}

      <h3 style="color:#F5C842;margin-top:22px">★ Tier vs. Raw Scanner Count</h3>
      <div style="display:flex;gap:16px;flex-wrap:wrap">
        <div style="flex:1;min-width:280px">
          <p style="color:#ccc;font-size:12px;margin-bottom:4px">By ★ tier</p>
          {_rows_html(star_rows, "★")}
        </div>
        <div style="flex:1;min-width:280px">
          <p style="color:#ccc;font-size:12px;margin-bottom:4px">By raw scanner count</p>
          {_rows_html(count_rows, "#")}
        </div>
      </div>

      <p style="color:#666;font-size:11px;margin-top:20px;line-height:1.5">
        "Win" = the stock's forward return over the hold period beat SPY's return over the same
        window. Rows below the {MIN_N}-onset minimum are excluded here as unreliable — see the
        attached aggregate CSV for every dimension/tier including unranked ones, and the full raw
        per-onset records are in this run's workflow artifact (too large to email). Educational/
        research use only, not financial advice.
      </p>
    </div>
    """
    return subject, html


def send_email(subject: str, html_body: str, attachment_path: str | None) -> None:
    sender = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    to_raw = os.environ.get("BEST_SCANNERS_EMAIL_TO") or os.environ["OVERKILL_EMAIL_TO"]
    recipients = [addr.strip() for addr in to_raw.split(",") if addr.strip()]

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html"))

    if attachment_path and os.path.exists(attachment_path):
        with open(attachment_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(attachment_path)}"')
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

    log(f"Full analysis: {UNIVERSE_KIND} (~{len(UNIVERSE)} tickers), "
        f"lookback={LOOKBACK_YEARS}y, hold={HOLD_DAYS}d, min_n={MIN_N}…")

    def _cb(i, total, ticker):
        if i % 10 == 0 or i == total - 1:
            log(f"  {i + 1}/{total} — {ticker}")

    records, reasons = _run_full_analysis_backtest(UNIVERSE, LOOKBACK_YEARS, HOLD_DAYS, progress_cb=_cb)
    log(f"Done: {len(records)} raw onset record(s). Reasons: {reasons}")

    agg = _aggregate_full_analysis(records, min_n=MIN_N)
    log(f"Aggregated to {len(agg)} (dimension, tier) rows.")

    os.makedirs(DATA_DIR, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M")
    base = f"bs_full_{UNIVERSE_KIND}_{LOOKBACK_YEARS}y_{HOLD_DAYS}d_{stamp}"

    agg_path = os.path.join(DATA_DIR, f"{base}_aggregate.csv")
    agg.to_csv(agg_path, index=False)
    log(f"Wrote {agg_path}")

    raw_path = None
    if records:
        raw_path = os.path.join(DATA_DIR, f"{base}_raw.csv")
        with open(raw_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["ticker", "date", "dimension", "tier",
                                                     "stock_ret", "spy_ret", "rel_ret", "win"])
            writer.writeheader()
            writer.writerows(records)
        log(f"Wrote {raw_path} ({len(records)} rows — artifact only, not emailed)")

    subject, html = build_email(agg)
    send_email(subject, html, agg_path)


if __name__ == "__main__":
    run()
