# Implied-volatility history

One JSON per trading session: `YYYY-MM-DD.json`, dated by the **bar date** of
the underlying rather than the wall clock, so a job that runs late (or twice)
cannot file one session under two dates.

Written once per weekday after the close by `scripts/headless_iv_snapshot.py`
(via `.github/workflows/iv_snapshot.yml`, which has `contents: write`). The
Streamlit app only ever reads: it has no git write access.

```json
{
  "date": "2026-08-25",
  "saved_utc": "2026-08-25 20:34 UTC",
  "rows": [
    { "ticker": "TQQQ", "iv_atm": 0.0, "iv_otm": 0.0, "skew": 0.0,
      "rv": 0.0, "iv_rv": 0.0, "price": 0.0, "dte": 30, "spread_pct": 0.0 }
  ]
}
```

## Why this exists

yfinance serves the **current** option chain and nothing else — there is no
endpoint for "what was TQQQ's IV in March". So "is this IV high *for this
ticker*" can only ever be answered by writing it down daily, starting now.

Until ~60 sessions accumulate, `scanners/iv_history.rank_for()` returns
`rank: None` and reports how many sessions it has. That is deliberate: a rank
over three weeks of data looks identical to one over a year and is worthless.
Showing it anyway is exactly how `utils.approx_iv_rank` misled for so long.

Meanwhile `scanners/option_premium.py` compares IV against **realised**
volatility, which needs no history and works from day one.

Read it with `scanners.iv_history.load_snapshots()` / `rank_for()` /
`coverage()`. Pruned past ~500 days.
