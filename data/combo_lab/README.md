# Combo Lab results

Written only by `scripts/headless_combo_lab.py`, run from the **Combo Lab**
GitHub Actions workflow. The Streamlit tab reads `latest.json` and never
writes — it has no git access, and a ~500-ticker two-timeframe study is not
something to run inside a page load.

| file | contents |
|---|---|
| `latest.json` | what the tab renders: consensus + every per-window table |
| `<date>_<universe>.json` | the same payload, kept per run |
| `<date>_<universe>_CONSENSUS.csv` | the headline table, for Excel |
| `<date>_<universe>_<Timeframe>-<Window>-<hold>b.csv` | one ranked table per cell |

## What the numbers mean

**Edge** is average return per trade minus SPY over the same bars — not raw
return, so a combination is not credited for the market having gone up.

**The two windows do not overlap.** `Recent 1y` and `Prior 2y` share no
trades, so a combination positive in both is genuinely positive twice rather
than the same trades counted twice.

**Ranking is by consistency first, size of edge second.** 191 combinations
tested at once is 191 chances for one to look good by luck; at a 5% threshold
roughly 10 should print "significant" with no edge at all. A number that only
appears in one window is not evidence, however large.

## Two states that are rare by construction, not by accident

- **C2** (price between EMA20 and EMA50 within a few bars of them crossing).
  At the cross the two lines are equal, so the band between them is a sliver.
  Expect it under the low-N flag.
- **Weekly V1**. A weekly bar's volume is a five-day sum and therefore much
  smoother than a daily bar's, so clearing 1.2x its own average is a higher
  bar than it is on daily.

Both are reported rather than patched: widening either to manufacture signals
would be inventing a condition nobody asked to test.
