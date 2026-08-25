#!/usr/bin/env python3
"""
scripts/email_footer.py — the common footer on every Golden Scanner email.

One shared helper rather than five copies, so the tag can never drift between
reports and a future change lands everywhere at once. Applied inside each
script's send_email(), which is the single choke point every message passes
through regardless of which build path produced the body.

The #goldenscanner tag exists to be filtered on. In Gmail:

    has:the-words "#goldenscanner"   ->  label:GoldenScanner

Each report also carries its own tag (#bestscanners, #overkill, #ytshorts,
#backtest, #fullanalysis, #fastscore) so the same inbox rule can split by report type
without a second filter on subject text, which changes far more often.

Note the tag is written as plain text, not a link and not styled as one --
some clients rewrite or strip anchor text, and a filter that depends on
markup surviving a client's sanitiser is a filter that breaks silently.
"""

BRAND_TAG = "#goldenscanner"

# Per-report tags. Kept short and lowercase because Gmail's filter matching is
# case-insensitive but people type these by hand.
TAG_BEST_SCANNERS = "#bestscanners"
TAG_OVERKILL = "#overkill"
TAG_YT_SHORTS = "#ytshorts"
TAG_BACKTEST = "#backtest"
TAG_FULL_ANALYSIS = "#fullanalysis"
TAG_FAST_SCORE = "#fastscore"


def footer_html(report_tag: str = "") -> str:
    """The footer block appended to every outgoing email."""
    tags = BRAND_TAG + (f" {report_tag}" if report_tag else "")
    return (
        '<div style="margin-top:22px;padding-top:12px;border-top:1px solid #333;'
        'font-family:Arial,sans-serif">'
        f'<div style="color:#f5c842;font-size:13px;font-weight:700;'
        f'letter-spacing:0.04em">{tags}</div>'
        '<div style="color:#666;font-size:11px;margin-top:4px;line-height:1.5">'
        'Automated report from Golden Scanner · not financial advice.'
        '</div></div>'
    )


def with_footer(html_body: str, report_tag: str = "") -> str:
    """Append the footer, unless it's somehow already there.

    The idempotence guard matters because these scripts are edited often and
    it would be easy to end up calling this on a body that already went
    through it -- a doubled tag looks broken and helps no one."""
    if BRAND_TAG in html_body:
        return html_body
    return html_body + footer_html(report_tag)
