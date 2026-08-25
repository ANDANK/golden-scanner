#!/usr/bin/env python3
"""
scripts/headless_fast_score_scan.py — run the Fast Score scan without a
browser and email the ranked table.

Independent pipeline from headless_overkill_scan.py and
headless_best_scanners_scan.py by design — separate script, separate
workflow, separate schedule — so any one can be debugged or rescheduled
without touching the others. See .github/workflows/fast_score_email.yml.

CADENCE: weekly, Friday after the close. Every input to this scanner is a
WEEKLY bar (52w/26w regression slopes, weekly MACD, 200-week SMA, weeks
since the 50-week-SMA touch) and evaluate_ticker() drops the in-progress
week, so Monday through Thursday every run reads the exact same settled
bars and would email a near-identical table four times over. Friday after
the close is the first moment the week's bar is final and the table can
actually have changed. Run it daily and it becomes noise you stop opening;
that is the failure mode this schedule is chosen to avoid.

Usage:
  python scripts/headless_fast_score_scan.py

Required env vars (GitHub Actions secrets):
  GMAIL_ADDRESS        the Gmail account to send FROM
  GMAIL_APP_PASSWORD   a 16-character Gmail App Password for that account
  OVERKILL_EMAIL_TO    recipient address(es), reused from the OverKill email —
                        set FAST_SCORE_EMAIL_TO to use a different list

Optional env vars:
  FAST_SCORE_EMAIL_TO   overrides OVERKILL_EMAIL_TO for this scan only
  FAST_SCORE_UNIVERSE   FTF / MTPA / SP500  (default FTF, ~416 stocks)
  FAST_SCORE_MIN_SCORE  drop rows below this Fast Score (default 0 = keep all)
  FAST_SCORE_MAX_ROWS   cap the emailed table (default 25)

Layout note: the email table is real <table>/<tr>/<td> markup, not flexbox —
see scanners.fast_score.email_table_html() for why.
"""

import os
import sys
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.email_footer import with_footer, TAG_FAST_SCORE

# ── Mock Streamlit so scanner modules import/run without a server, same
# approach as scripts/headless_best_scanners_scan.py.
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

# ── Now safe to import project modules ──────────────────────────────────
from scanners import fast_score as fs
from scanners import scan_history


UNI_KIND  = os.environ.get("FAST_SCORE_UNIVERSE", "FTF").upper()
MIN_SCORE = int(os.environ.get("FAST_SCORE_MIN_SCORE", "0"))
MAX_ROWS  = int(os.environ.get("FAST_SCORE_MAX_ROWS", "25"))
TODAY     = datetime.utcnow().strftime("%Y-%m-%d")


def log(msg: str) -> None:
    print(f"[fast-score] {msg}", flush=True)


def _tier_summary_html(df) -> str:
    counts = df["tier"].value_counts()
    cells = []
    for tier in (fs.TIER_EARLY, fs.TIER_FRESH, fs.TIER_FURTHER):
        color = fs._TIER_COLOR[tier]
        cells.append(
            f'<td style="padding:0 6px" width="33%">'
            f'<div style="background:#111118;border:1px solid rgba(255,255,255,0.06);'
            f'border-radius:10px;padding:14px 10px;text-align:center">'
            f'<div style="color:{color};font-size:26px;font-weight:800">'
            f'{int(counts.get(tier, 0))}</div>'
            f'<div style="color:#6B7280;font-size:10px;font-weight:800;'
            f'letter-spacing:.08em;text-transform:uppercase;margin-top:4px">'
            f'{fs._TIER_LABEL[tier]}</div></div></td>'
        )
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;border-collapse:separate;margin-bottom:18px">'
        f'<tr>{"".join(cells)}</tr></table>'
    )


def build_email(df, universe_size: int) -> tuple[str, str]:
    top = df.iloc[0] if len(df) else None
    subject = (
        f"⚡ Fast Score — {len(df)} setup(s)"
        + (f" · {top['ticker']} {int(top['score'])}/15 leads" if top is not None else "")
        + f" · {datetime.utcnow().strftime('%b %d')}"
    )

    html = f"""
    <div style="background:#0A0A0F;padding:24px;font-family:Arial,Helvetica,sans-serif;
                max-width:820px;margin:0 auto">
      <h1 style="color:#F5C842;font-family:Georgia,serif;font-size:24px;margin:0 0 4px 0">
        ⚡ Fast Score
      </h1>
      <p style="color:#6B7280;font-size:11px;margin:0 0 18px 0">
        Run: <b style="color:#F1F1F1">{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</b>
        &nbsp;|&nbsp; Universe: <b style="color:#F1F1F1">{universe_size} symbols</b>
        &nbsp;|&nbsp; Qualified: <b style="color:#F5C842">{len(df)}</b>
        &nbsp;|&nbsp; Weekly bars, settled only
      </p>

      {_tier_summary_html(df)}

      <div style="background:#17140f;border:1px solid rgba(245,200,66,0.08);border-radius:10px;
                  padding:12px 14px;margin-bottom:18px;font-size:13px;color:#a89f8a;line-height:1.5">
        <b style="color:#F5C842">How to read this:</b> every name below is already in a
        multi-year uptrend that is still accelerating, has pulled back to its 50-week line on
        quiet volume without breaking it, and has a weekly MACD turning up. The score ranks
        them; the tier tells you how early you are —
        <b style="color:{fs._TIER_COLOR[fs.TIER_EARLY]}">Early</b> has not crossed yet,
        <b style="color:{fs._TIER_COLOR[fs.TIER_FRESH]}">Fresh</b> just did,
        <b style="color:{fs._TIER_COLOR[fs.TIER_FURTHER]}">Further Along</b> is already moving.
      </div>

      {fs.email_table_html(df, max_rows=MAX_ROWS)}

      <p style="color:#666;font-size:11px;margin-top:20px;line-height:1.5">
        Ranked by Fast Score, then by tier (earlier setups first at equal score — more of the
        move is still ahead), then by slope ratio. Showing
        {min(len(df), MAX_ROWS)} of {len(df)} qualifying name(s).
        Educational/research use only, not financial advice. Open the
        <b style="color:#F5C842">⚡ Fast Score</b> tab in Golden Scanner for the full
        interactive table, the gate columns behind each row, and a CSV export.
      </p>
    </div>
    """
    return subject, html


def send_email(subject: str, html_body: str) -> None:
    sender = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    to_raw = os.environ.get("FAST_SCORE_EMAIL_TO") or os.environ["OVERKILL_EMAIL_TO"]
    recipients = [addr.strip() for addr in to_raw.split(",") if addr.strip()]

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
    if not os.environ.get("GMAIL_ADDRESS") or not os.environ.get("GMAIL_APP_PASSWORD"):
        log("ERROR: GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set — add them as GitHub Actions secrets.")
        sys.exit(1)
    if not os.environ.get("FAST_SCORE_EMAIL_TO") and not os.environ.get("OVERKILL_EMAIL_TO"):
        log("ERROR: neither FAST_SCORE_EMAIL_TO nor OVERKILL_EMAIL_TO is set — add one as a secret.")
        sys.exit(1)

    universe = fs.universe_for(UNI_KIND)
    log(f"Scanning {UNI_KIND} universe ({len(universe)} symbols) on weekly bars…")

    def _cb(i, total, msg):
        if i % 50 == 0:
            log(msg)

    df = fs.run_fast_score_scan(universe, progress_cb=_cb)
    log(f"Qualified: {len(df)} ticker(s).")

    if df.empty:
        log("Nothing qualified this run — skipping email.")
        return

    if MIN_SCORE > 0:
        before = len(df)
        df = df[df["score"] >= MIN_SCORE].reset_index(drop=True)
        df["rank"] = range(1, len(df) + 1)
        log(f"Min-score {MIN_SCORE} filter: {before} -> {len(df)}.")
        if df.empty:
            log("Nothing left after the min-score filter — skipping email.")
            return

    # History snapshot, same shape/lifecycle as the other scanners so the
    # data/ directory stays uniform (see CLAUDE.md → Data snapshots).
    today_rows = [
        {
            "ticker": str(r["ticker"]),
            "price": float(r["close"]),
            "sector": str(r["sector"]),
            "tier": str(r["tier"]),
            "score": int(r["score"]),
            "slope_52w": round(float(r["slope_52w"]), 2),
            "slope_26w": round(float(r["slope_26w"]), 2),
            "slope_ratio": round(float(r["slope_ratio"]), 3),
            "touch_pct": round(float(r["touch_pct"]), 2),
            "bounce_pct": round(float(r["bounce_pct"]), 2),
            "wks_since_touch": int(r["wks_since_touch"]),
            "macd_gap": round(float(r["macd_gap"]), 3),
            "macd_delta_3w": round(float(r["macd_delta_3w"]), 3),
            "accel_3w": round(float(r["accel_3w"]), 2),
            "dist_200w": round(float(r["dist_200w"]), 2),
            "vol_ratio": round(float(r["vol_ratio"]), 3),
        }
        for _, r in df.iterrows()
    ]
    try:
        history = scan_history.annotate_new_and_first_found(
            "fast_score", UNI_KIND, TODAY, today_rows)
        scan_history.save_snapshot("fast_score", UNI_KIND, TODAY, today_rows)
        scan_history.prune_old("fast_score", UNI_KIND, TODAY)
        n_new = sum(1 for v in history.values() if v["is_new"])
        log(f"Saved history snapshot for {TODAY} ({len(today_rows)} row(s)); {n_new} new ticker(s).")
    except Exception as e:
        # A snapshot failure must not cost the email — the email is the
        # deliverable, the snapshot is bookkeeping for later analysis.
        log(f"WARN: history snapshot failed ({e}); continuing to email anyway.")

    subject, html = build_email(df, len(universe))
    send_email(subject, html)


if __name__ == "__main__":
    run()
