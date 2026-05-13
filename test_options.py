"""
test_options.py — Validate options chain fetching before deploying.
Run: python test_options.py
"""
import os, time

# Fix SSL cert path for curl_cffi on Windows (not needed on Linux/Cloud)
try:
    import certifi
    os.environ.setdefault("CURL_CA_BUNDLE", certifi.where())
    os.environ.setdefault("SSL_CERT_FILE",  certifi.where())
except ImportError:
    pass

import yfinance as yf

TICKERS = ["SPY", "QQQ", "AAPL", "MSFT"]

def _make_ticker(ticker: str):
    """Try curl_cffi session first, fall back to requests on SSL failure."""
    try:
        from curl_cffi import requests as curl_req
        session = curl_req.Session(verify=False, impersonate="chrome")
        return yf.Ticker(ticker, session=session)
    except Exception:
        return yf.Ticker(ticker)   # fallback: no session (cloud default)

def fetch_options(ticker: str):
    """Fetch options exactly as data_loader will after the fix."""
    t = _make_ticker(ticker)

    # Step 1: dates only
    t0 = time.time()
    try:
        dates = list(t.options or [])
    except Exception as e:
        return {"ticker": ticker, "ok": False, "stage": "dates", "error": str(e)[:120]}

    if not dates:
        return {"ticker": ticker, "ok": False, "stage": "dates", "error": "no expiry dates"}

    # Step 2: chain for first expiry
    try:
        chain = t.option_chain(dates[0])
        calls = getattr(chain, "calls", None)
        puts  = getattr(chain, "puts",  None)
    except Exception as e:
        return {"ticker": ticker, "ok": False, "stage": "chain", "error": str(e)[:120]}

    elapsed = time.time() - t0
    return {
        "ticker":    ticker,
        "ok":        True,
        "expiries":  len(dates),
        "first_exp": dates[0],
        "calls":     len(calls) if calls is not None else 0,
        "puts":      len(puts)  if puts  is not None else 0,
        "elapsed_s": round(elapsed, 2),
    }

print("=" * 60)
print("Golden Scanner — Options Fetch Test")
print("=" * 60)

all_ok = True
for i, tk in enumerate(TICKERS):
    if i > 0:
        time.sleep(0.5)   # throttle between tickers
    result = fetch_options(tk)
    if result["ok"]:
        print(f"  OK  {tk:6s}  {result['expiries']} expiries  "
              f"first={result['first_exp']}  "
              f"calls={result['calls']}  puts={result['puts']}  "
              f"({result['elapsed_s']}s)")
    else:
        print(f"  FAIL {tk:6s}  FAILED at [{result['stage']}]: {result['error']}")
        all_ok = False

print("=" * 60)
print("RESULT:", "ALL PASS" if all_ok else "SOME FAILED")
print("=" * 60)
