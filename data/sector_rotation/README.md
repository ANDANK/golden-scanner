# Sector rotation snapshots

One JSON file per trading session: `YYYY-MM-DD_close.json`, where the date is
the **bar date**, not the wall clock — a job that runs at 21:15 UTC Friday and
one that runs at 00:30 UTC Saturday describe the same session.

Written once a day after the close by `scripts/headless_sector_rotation.py`
(via `.github/workflows/sector_rotation_history.yml`, which has
`contents: write`). The Streamlit app only ever reads: it has no git write
access and would produce a file per page load.

Each file holds the rotation table exactly as the scanner printed it:

```json
{
  "date": "2026-08-21",
  "slot": "close",
  "saved_utc": "2026-08-21 20:47 UTC",
  "market": { "spy_price": 0.0, "bull_market": true, "as_of": "2026-08-21" },
  "rows":   [ { "ticker": "XLK", "rank": 1, "rs": 1.041, "idea": "CSP" } ]
}
```

Read them with `scanners.sector_history.load_snapshots()`. Pruned past
`RETENTION_DAYS` (~18 months) — sector leadership cycles run in quarters, so a
year-plus is the shortest window in which a handoff is even visible.

The History panel in the app does **not** depend on these files: it rebuilds
the same series by replaying the scan over the trailing price history. These
snapshots are the audit trail of what was actually shown, which survives any
future retuning of the thresholds in `scanners/sector_rotation.py`.
