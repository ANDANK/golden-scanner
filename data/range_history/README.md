# Morning-range records

One JSON per (source, date). Written only by the scheduled headless scripts —
the Streamlit app has no git write access and would write a file per page
load, so it only ever reads these.

| source | interval | window | written by |
|---|---|---|---|
| `accum` | 5m | 09:30–12:00, read at noon | `scripts/headless_range_accumulator.py` (daily, after the close) |
| `backfill60m` | 60m | 09:30–**11:30**, read at 11:30 | `scripts/headless_range_backfill.py` (manual, one-shot seed) |

**The two sources are different measurements and must not be pooled without
checking.** Hourly bars are stamped 09:30/10:30/11:30 and the 11:30 bar runs
to 12:30, so reaching noon on an hourly grid would fold post-noon information
into a number whose whole point is to be knowable at noon. The backfill stops
at 11:30 instead. `range_history.window_comparison()` measures how far apart
the two reads sit on the days both cover — in particular how often they
disagree about which *zone* a session is in, which is the only difference
that changes a trade.

**Nothing here is re-fetchable.** Yahoo serves 5-minute bars for 60 calendar
days on a rolling window; a session not captured inside it is gone at any
interval fine enough to show a morning range. `RETENTION_DAYS` is `None` for
that reason — pruning this directory deletes the only copy.
