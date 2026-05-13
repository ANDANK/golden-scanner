#!/usr/bin/env python3
"""
scripts/validate_tickers.py
Check every ticker in config.py for active price data via yfinance.
Writes data/ticker_validation.json with lists of ok / bad tickers.
Run via GitHub Actions (validate_tickers.yml) — local SSL often blocks yfinance.
"""

import os, sys, json, time, random
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import SP500_SAMPLE, OPTIONS_ETF_UNIVERSE, ETF_UNIVERSE, ETF_3X_UNIVERSE
import yfinance as yf

DATA_DIR = os.path.join(ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)
OUT_PATH = os.path.join(DATA_DIR, "ticker_validation.json")

# All unique tickers across all lists
ALL = list(dict.fromkeys(
    SP500_SAMPLE + OPTIONS_ETF_UNIVERSE + ETF_UNIVERSE + ETF_3X_UNIVERSE
))

print(f"Validating {len(ALL)} unique tickers …")

ok_list  = []
bad_list = []

for i, tk in enumerate(ALL):
    try:
        info = yf.Ticker(tk).fast_info
        price = info.get("lastPrice") or info.get("regularMarketPrice")
        if price and float(price) > 0:
            ok_list.append(tk)
            print(f"  OK  {tk}: ${price:.2f}")
        else:
            bad_list.append({"ticker": tk, "reason": "price=0 or None"})
            print(f"  BAD {tk}: no price returned")
    except Exception as e:
        bad_list.append({"ticker": tk, "reason": str(e)[:120]})
        print(f"  BAD {tk}: {e}")

    if (i + 1) % 20 == 0:
        time.sleep(2 + random.uniform(0, 1))

result = {
    "run_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    "total":  len(ALL),
    "ok":     len(ok_list),
    "bad":    len(bad_list),
    "ok_tickers":  ok_list,
    "bad_tickers": bad_list,
}

with open(OUT_PATH, "w") as f:
    json.dump(result, f, indent=2)

print(f"\n=== Results ===")
print(f"OK : {len(ok_list)}")
print(f"BAD: {len(bad_list)}")
if bad_list:
    print("\nBAD tickers:")
    for b in bad_list:
        print(f"  {b['ticker']}: {b['reason'][:80]}")
print(f"\nSaved → {OUT_PATH}")
