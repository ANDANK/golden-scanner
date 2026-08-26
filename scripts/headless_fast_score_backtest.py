#!/usr/bin/env python3
"""
scripts/headless_fast_score_backtest.py — walk-forward backtest of the Fast
Score scanner, written to data/ and emailed as a summary.

Run from GitHub Actions (workflow_dispatch) rather than the Streamlit app: a
456-ticker, 3-year run is ~71k live scanner evaluations, roughly 4-5 minutes.
The app reads the committed JSON instead of recomputing (CLAUDE.md → Data
snapshots).

Usage:
  FAST_SCORE_BT_YEARS=3 python scripts/headless_fast_score_backtest.py

Env vars:
  GMAIL_ADDRESS / GMAIL_APP_PASSWORD / OVERKILL_EMAIL_TO   as the other jobs
  FAST_SCORE_EMAIL_TO      overrides the recipient list
  FAST_SCORE_BT_YEARS      years of history to test (default 3)
  FAST_SCORE_BT_UNIVERSE   FTF / MTPA / SP500 (default FTF)
  FAST_SCORE_BT_NO_EMAIL   set to 1 to write results without emailing
"""

import json
import os
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.email_footer import with_footer, TAG_FAST_SCORE

from unittest.mock import MagicMock


class _FakeSS(dict):
    def __missing__(self, key):
        return None


class _MockST:
    session_state = _FakeSS()

    @staticmethod
    def cache_data(ttl=None, show_spinner=True):
        def _dec(fn):
            return fn
        return _dec

    def __getattr__(self, name):
        return MagicMock()


sys.modules["streamlit"] = _MockST()

from scanners import fast_score as fs
from scanners import fast_score_backtest as bt

YEARS = int(os.environ.get("FAST_SCORE_BT_YEARS", "3"))
UNI_KIND = os.environ.get("FAST_SCORE_BT_UNIVERSE", "FTF").upper()
NO_EMAIL = os.environ.get("FAST_SCORE_BT_NO_EMAIL") == "1"
OUT_DIR = os.path.join(ROOT, "data", "fast_score_backtest")
TODAY = datetime.utcnow().strftime("%Y-%m-%d")


def log(msg: str) -> None:
    print(f"[fs-backtest] {msg}", flush=True)


def _row(label: str, a: dict, indent: bool = False) -> str:
    def c(v, good=0.0):
        return "#3fcf7f" if v is not None and v > good else "#f0704a"
    ex = a.get("mean_excess")
    mae = a.get("mean_mae")
    # Precomputed rather than inlined: nesting the same quote style inside an
    # f-string expression is a syntax error on Python 3.11, which is what the
    # workflow runs.
    ex_txt = "—" if ex is None else f"{ex:+.1f}%"
    mae_txt = "—" if mae is None else f"{mae:+.1f}%"
    ex_color = "#6B7280" if ex is None else c(ex)
    return (
        f'<tr>'
        f'<td style="padding:6px 8px;color:#F1F1F1;font-size:12px'
        f'{";padding-left:22px" if indent else ""}">{label}</td>'
        f'<td style="padding:6px 8px;text-align:right;color:#a89f8a;font-size:12px">{a["n"]}</td>'
        f'<td style="padding:6px 8px;text-align:right;color:{c(a["win_rate"], 50)};'
        f'font-size:12px;font-weight:700">{a["win_rate"]:.0f}%</td>'
        f'<td style="padding:6px 8px;text-align:right;color:{c(a["median"])};font-size:12px">'
        f'{a["median"]:+.1f}%</td>'
        f'<td style="padding:6px 8px;text-align:right;color:{c(a["mean"])};font-size:12px">'
        f'{a["mean"]:+.1f}%</td>'
        f'<td style="padding:6px 8px;text-align:right;color:{ex_color};'
        f'font-size:12px;font-weight:700">{ex_txt}</td>'
        f'<td style="padding:6px 8px;text-align:right;color:#f0704a;font-size:12px">'
        f'{mae_txt}</td>'
        f'</tr>'
    )


def _table(summary: dict, horizon: str) -> str:
    head = "".join(
        f'<td style="padding:0 8px 6px 8px;color:#6B7280;font-size:9px;font-weight:800;'
        f'letter-spacing:.08em;text-align:{"left" if i == 0 else "right"}">{h}</td>'
        for i, h in enumerate(
            ["", "N", "WIN%", "MEDIAN", "MEAN", "VS SPY", "AVG MAE"])
    )
    body = []
    o = summary["overall"].get(horizon)
    if o:
        body.append(_row(f"<b>All picks · {horizon}</b>", o))
    for tier, per in summary["by_tier"].items():
        if horizon in per:
            body.append(_row(tier, per[horizon], indent=True))
    for band in ("12-15", "9-11", "6-8", "0-5"):
        per = summary["by_score_band"].get(band)
        if per and horizon in per:
            body.append(_row(f"score {band}", per[horizon], indent=True))
    if not body:
        return ""
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;border-collapse:collapse;margin-bottom:18px">'
        f'<tr>{head}</tr>{"".join(body)}</table>'
    )


def build_email(summary: dict, n_universe: int) -> tuple[str, str]:
    o4 = summary["overall"].get("4w") or {}
    subject = (
        f"🔬 Fast Score backtest — {summary['n_picks']} picks, "
        f"{o4.get('win_rate', 0):.0f}% win @4w · {datetime.utcnow().strftime('%b %d')}"
    )
    tables = "".join(
        f'<div style="color:#F5C842;font-size:12px;font-weight:800;letter-spacing:.06em;'
        f'text-transform:uppercase;margin:4px 0 6px 0">{h} horizon</div>{_table(summary, h)}'
        for h in (f"{x}w" for x in summary["horizons"])
    )
    html = f"""
    <div style="background:#0A0A0F;padding:24px;font-family:Arial,Helvetica,sans-serif;
                max-width:820px;margin:0 auto">
      <h1 style="color:#F5C842;font-family:Georgia,serif;font-size:24px;margin:0 0 4px 0">
        🔬 Fast Score — walk-forward backtest
      </h1>
      <p style="color:#6B7280;font-size:11px;margin:0 0 16px 0">
        {summary['n_picks']} picks across {summary['n_tickers']} tickers ·
        {summary['date_min']} → {summary['date_max']} ·
        universe {n_universe} · benchmark {bt.BENCHMARK}
      </p>
      <div style="background:#17140f;border:1px solid rgba(245,200,66,0.08);border-radius:10px;
                  padding:12px 14px;margin-bottom:18px;font-size:13px;color:#a89f8a;line-height:1.5">
        <b style="color:#F5C842">Read "VS SPY" first.</b> A positive median in a rising
        market means little on its own — the excess over SPY across the same window is the
        column that says whether the scanner added anything.
      </div>
      {tables}
      <div style="background:#1a1410;border:1px solid rgba(240,112,74,0.18);border-radius:10px;
                  padding:12px 14px;font-size:12px;color:#c9a99a;line-height:1.6">
        <b style="color:#f0704a">What this cannot tell you.</b>
        The universe is today's list, so delisted and acquired companies are absent —
        this biases every number OPTIMISTIC and no amount of care removes it.
        Entries assume the weekly close of the signal bar with no slippage or commission.
        Recently-added index members are tested over years they were not members.
        Repeats within {bt.MIN_REPEAT_GAP_WKS} weeks are suppressed, but picks in the same
        week are still correlated with each other and with the market.
      </div>
      <p style="color:#666;font-size:11px;margin-top:18px;line-height:1.5">
        Every historical evaluation calls the live scanner against a slice of bars ending
        at the week under test, so the gates measured here are exactly the gates running
        today, and no evaluation can see a bar after its own.
      </p>
    </div>
    """
    return subject, html


def send_email(subject: str, html_body: str) -> None:
    sender = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    to_raw = os.environ.get("FAST_SCORE_EMAIL_TO") or os.environ["OVERKILL_EMAIL_TO"]
    recipients = [a.strip() for a in to_raw.split(",") if a.strip()]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(with_footer(html_body, TAG_FAST_SCORE), "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())
    log(f"Email sent to {', '.join(recipients)}")


def run():
    universe = fs.universe_for(UNI_KIND)
    log(f"Backtesting {UNI_KIND} ({len(universe)} symbols) over {YEARS}y of weekly bars…")

    def _cb(i, total, msg):
        if i % 50 == 0:
            log(msg)

    records, summary = bt.run_backtest(universe, test_years=YEARS, progress_cb=_cb)
    log(f"{summary['n_picks']} picks across {summary['n_tickers']} tickers.")
    if not records:
        log("No picks produced — nothing to write or send.")
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    payload = {
        "generated": datetime.utcnow().isoformat() + "Z",
        "universe": UNI_KIND, "universe_size": len(universe),
        "test_years": YEARS, "benchmark": bt.BENCHMARK,
        "min_repeat_gap_wks": bt.MIN_REPEAT_GAP_WKS,
        "build": fs.BUILD, "summary": summary, "picks": records,
    }
    # Two files: a stable name the app reads, and an archive copy keyed by
    # BOTH universe and test length. Dating alone was not enough -- a 5-year
    # run dispatched the same day as a 3-year one wrote the identical
    # filename and destroyed the earlier evidence, which is exactly what the
    # archive copy exists to prevent.
    for name in (f"latest_{UNI_KIND}.json", f"{TODAY}_{UNI_KIND}_{YEARS}y.json"):
        with open(os.path.join(OUT_DIR, name), "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=1)
    log(f"Wrote results to {OUT_DIR}")

    for h in summary["horizons"]:
        a = summary["overall"].get(f"{h}w")
        if a:
            ex = a.get("mean_excess")
            log(f"  {h}w: n={a['n']} win={a['win_rate']:.0f}% median={a['median']:+.1f}% "
                f"mean={a['mean']:+.1f}% vs-SPY={'n/a' if ex is None else f'{ex:+.1f}%'}")

    if NO_EMAIL:
        log("FAST_SCORE_BT_NO_EMAIL=1 — skipping email.")
        return
    if not os.environ.get("GMAIL_ADDRESS") or not os.environ.get("GMAIL_APP_PASSWORD"):
        log("No mail credentials — results written, email skipped.")
        return
    subject, html = build_email(summary, len(universe))
    send_email(subject, html)


if __name__ == "__main__":
    run()
