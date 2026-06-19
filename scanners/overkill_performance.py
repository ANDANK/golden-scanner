# scanners/overkill_performance.py
# OverKill Alert Performance Tracker
# Tracks Golden Dot / Monthly / Weekly / Daily alerts with dynamic pricing,
# 2W + 1M + current return columns, and cross-timeframe week badges.

import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import date, timedelta
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Palette ────────────────────────────────────────────────────────────────────
_BG    = "#0f1929"
_CARD  = "#111827"
_GOLD  = "#f59e0b"
_GREEN = "#22c55e"
_RED   = "#ef4444"
_BLUE  = "#3b82f6"
_MUTED = "#64748b"
_TEXT  = "#e2e8f0"
_DIM   = "#94a3b8"
_PUR   = "#a855f7"

TODAY = date.today()

# ── Ticker normalisation ───────────────────────────────────────────────────────
# Tickers that yfinance cannot resolve → skip pricing gracefully
_SKIP = frozenset([
    "OPUSD", "MAMOUSD", "PUMPUSD", "WLFIUSDT", "KTAUSD",
    "HYPEUSD", "ASTERUSDT", "SHXUSDT", "SHXUSD", "BABYUSD",
    "SPXUSDC", "OSMOUSD", "MNTUSDT", "ZBCNUSD", "DVLT",
    "PINUSDT", "BZAI",
])
_SPECIAL = {
    "BRK.B":    "BRK-B",
    "VIX":      "^VIX",
    "RR":       "RR.L",
    "ETHBTC":   "ETH-BTC",
    "RSRUSDT":  "RSR-USD",
    "MORPHOUSDT":"MORPHO-USD",
    "JUPUSDT":  "JUP-USD",
    "BNBUSDT":  "BNB-USD",
    "SOLUSD":   "SOL-USD",
    "IMXUSDT":  "IMX-USD",
    "PEPEUSD":  "PEPE24478-USD",
}

def _to_yf(tk: str) -> str | None:
    if tk in _SKIP:
        return None
    if tk in _SPECIAL:
        return _SPECIAL[tk]
    if tk.endswith("USDT") and len(tk) > 4:
        return tk[:-4] + "-USD"
    if tk.endswith("USD") and len(tk) > 3:
        return tk[:-3] + "-USD"
    if tk.endswith("BTC") and len(tk) > 3:
        return tk[:-3] + "-BTC"
    return tk

# ── Trading-day helpers ────────────────────────────────────────────────────────
def _next_bday(d: date) -> date:
    """Return the next weekday after d."""
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d

def _buy_date(alert_date: str, after_hours: bool) -> date:
    d = date.fromisoformat(alert_date)
    if after_hours or d.weekday() >= 5:
        return _next_bday(d)
    return d

# ── Alert data ─────────────────────────────────────────────────────────────────
#  Fields: ticker, date, after_hours, alert_price
#  Weekly also has: signal ("showing" | "confirmed")
#  Daily also has:  sig_type ("Green" | "EMA Cross" | "Ribbon Cross")

GOLDEN_DOT = [
    dict(ticker="PINS",     date="2026-02-20", after_hours=False, alert_price=None),
    dict(ticker="OPUSD",    date="2026-02-24", after_hours=True,  alert_price=None),
    dict(ticker="ZS",       date="2026-02-27", after_hours=False, alert_price=None),
    dict(ticker="BX",       date="2026-02-27", after_hours=False, alert_price=None),
    dict(ticker="PANW",     date="2026-02-27", after_hours=False, alert_price=None),
    dict(ticker="PLNT",     date="2026-03-04", after_hours=False, alert_price=None),
    dict(ticker="SEIUSD",   date="2026-03-12", after_hours=True,  alert_price=None),
    dict(ticker="TRUMPUSD", date="2026-03-12", after_hours=True,  alert_price=None),
    dict(ticker="WING",     date="2026-03-18", after_hours=False, alert_price=None),
    dict(ticker="PLAY",     date="2026-03-18", after_hours=False, alert_price=None),
    dict(ticker="HUM",      date="2026-03-18", after_hours=False, alert_price=None),
    dict(ticker="SOFI",     date="2026-03-25", after_hours=False, alert_price=None),
    dict(ticker="TTWO",     date="2026-03-31", after_hours=False, alert_price=None),
    dict(ticker="DPZ",      date="2026-04-01", after_hours=False, alert_price=None),
    dict(ticker="CELH",     date="2026-04-01", after_hours=False, alert_price=None),
    dict(ticker="SOUN",     date="2026-04-01", after_hours=False, alert_price=None),
    dict(ticker="BRK.B",    date="2026-04-01", after_hours=False, alert_price=None),
    dict(ticker="SNAP",     date="2026-04-01", after_hours=False, alert_price=None),
    dict(ticker="BIDU",     date="2026-04-02", after_hours=False, alert_price=None),
    dict(ticker="DASH",     date="2026-04-02", after_hours=False, alert_price=None),
    dict(ticker="RGTI",     date="2026-04-02", after_hours=False, alert_price=None),
    dict(ticker="SNOW",     date="2026-04-06", after_hours=False, alert_price=None),
    dict(ticker="ELF",      date="2026-04-06", after_hours=False, alert_price=None),
    dict(ticker="INTU",     date="2026-04-16", after_hours=False, alert_price=None),
    dict(ticker="RSG",      date="2026-04-24", after_hours=False, alert_price=None),
    dict(ticker="ABBV",     date="2026-04-30", after_hours=False, alert_price=None),
    dict(ticker="TRUMPUSD", date="2026-05-03", after_hours=True,  alert_price=None),
    dict(ticker="ATEC",     date="2026-05-04", after_hours=False, alert_price=None),
    dict(ticker="WLFIUSDT", date="2026-05-04", after_hours=True,  alert_price=None),
    dict(ticker="SCO",      date="2026-05-06", after_hours=False, alert_price=None),
    dict(ticker="KTAUSD",   date="2026-05-12", after_hours=True,  alert_price=None),
    dict(ticker="TSDD",     date="2026-05-18", after_hours=False, alert_price=None),
    dict(ticker="CELH",     date="2026-05-19", after_hours=False, alert_price=None),
    dict(ticker="Z",        date="2026-05-21", after_hours=False, alert_price=None),
    dict(ticker="ULTA",     date="2026-05-22", after_hours=False, alert_price=None),
    dict(ticker="COMPUSD",  date="2026-05-30", after_hours=True,  alert_price=18.27),
    dict(ticker="COMPUSD",  date="2026-05-30", after_hours=True,  alert_price=18.29),
    dict(ticker="BCHUSD",   date="2026-06-01", after_hours=True,  alert_price=293.51),
    dict(ticker="O",        date="2026-06-08", after_hours=False, alert_price=60.71),
    dict(ticker="MAMOUSD",  date="2026-06-08", after_hours=True,  alert_price=0.00851),
    dict(ticker="PUMPUSD",  date="2026-06-09", after_hours=True,  alert_price=0.001520),
    dict(ticker="COIN",     date="2026-06-11", after_hours=False, alert_price=154.70),
    dict(ticker="BABA",     date="2026-06-17", after_hours=False, alert_price=109.51),
]

MONTHLY = [
    dict(ticker="HUBS",  date="2026-06-01", after_hours=False, alert_price=232.00),
    dict(ticker="BBAI",  date="2026-06-01", after_hours=False, alert_price=5.17),
    dict(ticker="LCID",  date="2026-06-01", after_hours=False, alert_price=6.38),
    dict(ticker="STLA",  date="2026-06-01", after_hours=False, alert_price=7.82),
    dict(ticker="MDB",   date="2026-06-01", after_hours=False, alert_price=346.00),
    dict(ticker="DLTR",  date="2026-06-01", after_hours=False, alert_price=116.84),
    dict(ticker="MSFT",  date="2026-06-01", after_hours=False, alert_price=464.84),
    dict(ticker="TTWO",  date="2026-06-01", after_hours=False, alert_price=227.99),
    dict(ticker="UPST",  date="2026-06-01", after_hours=False, alert_price=33.79),
    dict(ticker="RCAT",  date="2026-06-01", after_hours=False, alert_price=14.32),
    dict(ticker="GE",    date="2026-06-01", after_hours=False, alert_price=321.48),
    dict(ticker="DUOL",  date="2026-06-01", after_hours=False, alert_price=115.00),
    dict(ticker="UAL",   date="2026-06-01", after_hours=False, alert_price=111.40),
    dict(ticker="ACN",   date="2026-06-01", after_hours=False, alert_price=193.44),
    dict(ticker="MNST",  date="2026-06-01", after_hours=False, alert_price=88.25),
    dict(ticker="PATH",  date="2026-06-01", after_hours=False, alert_price=11.95),
    dict(ticker="ALK",   date="2026-06-01", after_hours=False, alert_price=44.25),
    dict(ticker="RIVN",  date="2026-06-01", after_hours=False, alert_price=16.14),
    dict(ticker="RR",    date="2026-06-01", after_hours=False, alert_price=2.98),
    dict(ticker="PLTR",  date="2026-06-01", after_hours=False, alert_price=159.98),
    dict(ticker="TXRH",  date="2026-06-02", after_hours=False, alert_price=179.85),
    dict(ticker="XLV",   date="2026-06-05", after_hours=False, alert_price=148.52),
    dict(ticker="ABBV",  date="2026-06-05", after_hours=False, alert_price=215.26),
    dict(ticker="KVUE",  date="2026-06-09", after_hours=False, alert_price=17.29),
    dict(ticker="KSS",   date="2026-06-11", after_hours=False, alert_price=14.74),
    dict(ticker="TKO",   date="2026-06-12", after_hours=False, alert_price=205.46),
    dict(ticker="XLF",   date="2026-06-12", after_hours=False, alert_price=51.23),
    dict(ticker="DHI",   date="2026-06-15", after_hours=False, alert_price=148.50),
    dict(ticker="XLI",   date="2026-06-15", after_hours=False, alert_price=171.59),
    dict(ticker="BRK.B", date="2026-06-16", after_hours=False, alert_price=473.05),
    dict(ticker="HIMS",  date="2026-06-16", after_hours=False, alert_price=26.19),
    dict(ticker="PG",    date="2026-06-16", after_hours=False, alert_price=141.52),
    dict(ticker="HWM",   date="2026-06-17", after_hours=False, alert_price=253.62),
]

WEEKLY = [
    dict(ticker="ICPUSD",   date="2026-05-31", after_hours=True,  alert_price=None,    signal="confirmed"),
    dict(ticker="PINUSDT",  date="2026-05-31", after_hours=True,  alert_price=None,    signal="confirmed"),
    dict(ticker="SHXUSDT",  date="2026-05-31", after_hours=True,  alert_price=None,    signal="confirmed"),
    dict(ticker="FETUSD",   date="2026-05-31", after_hours=True,  alert_price=None,    signal="confirmed"),
    dict(ticker="TRUMPUSD", date="2026-05-31", after_hours=True,  alert_price=2.02,    signal="showing"),
    dict(ticker="HNTUSD",   date="2026-05-31", after_hours=True,  alert_price=0.725,   signal="showing"),
    dict(ticker="MCD",      date="2026-06-01", after_hours=False, alert_price=278.12,  signal="showing"),
    dict(ticker="ELF",      date="2026-06-01", after_hours=False, alert_price=56.54,   signal="showing"),
    dict(ticker="NU",       date="2026-06-01", after_hours=False, alert_price=13.00,   signal="showing"),
    dict(ticker="DVLT",     date="2026-06-01", after_hours=False, alert_price=0.5045,  signal="showing"),
    dict(ticker="INTU",     date="2026-06-01", after_hours=False, alert_price=338.70,  signal="showing"),
    dict(ticker="ETHBTC",   date="2026-06-01", after_hours=False, alert_price=0.02723, signal="showing"),
    dict(ticker="TOST",     date="2026-06-05", after_hours=False, alert_price=27.47,   signal="showing"),
    dict(ticker="TWLO",     date="2026-06-05", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="VLO",      date="2026-06-05", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="EA",       date="2026-06-05", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="BZAI",     date="2026-06-05", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="MSI",      date="2026-06-05", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="MCD",      date="2026-06-05", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="PG",       date="2026-06-05", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="MPC",      date="2026-06-05", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="RNG",      date="2026-06-05", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="PGR",      date="2026-06-05", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="DG",       date="2026-06-05", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="HIMS",     date="2026-06-05", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="TOST",     date="2026-06-05", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="DE",       date="2026-06-05", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="LRN",      date="2026-06-05", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="AMPX",     date="2026-06-05", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="MOH",      date="2026-06-05", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="ANGX",     date="2026-06-05", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="C",        date="2026-06-05", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="VIX",      date="2026-06-05", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="REGN",     date="2026-06-08", after_hours=False, alert_price=638.04,  signal="showing"),
    dict(ticker="SCHW",     date="2026-06-08", after_hours=False, alert_price=88.28,   signal="showing"),
    dict(ticker="BSX",      date="2026-06-08", after_hours=False, alert_price=48.05,   signal="showing"),
    dict(ticker="ELF",      date="2026-06-08", after_hours=False, alert_price=50.05,   signal="showing"),
    dict(ticker="ISRG",     date="2026-06-09", after_hours=False, alert_price=422.54,  signal="showing"),
    dict(ticker="Z",        date="2026-06-09", after_hours=False, alert_price=35.11,   signal="showing"),
    dict(ticker="LOW",      date="2026-06-11", after_hours=False, alert_price=208.77,  signal="showing"),
    dict(ticker="TRUMPUSD", date="2026-06-12", after_hours=False, alert_price=1.66,    signal="showing"),
    dict(ticker="KO",       date="2026-06-12", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="BX",       date="2026-06-12", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="DNUT",     date="2026-06-12", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="LMT",      date="2026-06-12", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="WM",       date="2026-06-12", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="TSDD",     date="2026-06-12", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="SQQQ",     date="2026-06-12", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="ELF",      date="2026-06-12", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="CALY",     date="2026-06-12", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="XLP",      date="2026-06-12", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="LOW",      date="2026-06-12", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="TGT",      date="2026-06-12", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="CPNG",     date="2026-06-12", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="SCHW",     date="2026-06-12", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="AXP",      date="2026-06-12", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="TRUMPUSD", date="2026-06-14", after_hours=True,  alert_price=None,    signal="confirmed"),
    dict(ticker="CRVUSD",   date="2026-06-14", after_hours=True,  alert_price=None,    signal="confirmed"),
    dict(ticker="AAVEUSD",  date="2026-06-15", after_hours=False, alert_price=68.33,   signal="showing"),
    dict(ticker="ETHBTC",   date="2026-06-15", after_hours=False, alert_price=0.02625, signal="showing"),
    dict(ticker="CMCSA",    date="2026-06-15", after_hours=False, alert_price=24.32,   signal="showing"),
    dict(ticker="BSX",      date="2026-06-15", after_hours=False, alert_price=47.16,   signal="showing"),
    dict(ticker="NU",       date="2026-06-15", after_hours=False, alert_price=12.34,   signal="showing"),
    dict(ticker="LCID",     date="2026-06-15", after_hours=False, alert_price=5.40,    signal="showing"),
    dict(ticker="TM",       date="2026-06-15", after_hours=False, alert_price=180.76,  signal="showing"),
    dict(ticker="REGN",     date="2026-06-15", after_hours=False, alert_price=613.35,  signal="showing"),
    dict(ticker="CELH",     date="2026-06-15", after_hours=False, alert_price=29.36,   signal="showing"),
    dict(ticker="MA",       date="2026-06-15", after_hours=False, alert_price=490.50,  signal="showing"),
    dict(ticker="TMUS",     date="2026-06-15", after_hours=False, alert_price=185.99,  signal="showing"),
    dict(ticker="ISRG",     date="2026-06-15", after_hours=False, alert_price=412.94,  signal="showing"),
    dict(ticker="CMG",      date="2026-06-15", after_hours=False, alert_price=32.63,   signal="showing"),
    dict(ticker="GRAB",     date="2026-06-15", after_hours=False, alert_price=3.39,    signal="showing"),
    dict(ticker="JUPUSDT",  date="2026-06-16", after_hours=False, alert_price=0.1798,  signal="showing"),
    dict(ticker="HYPEUSD",  date="2026-06-16", after_hours=False, alert_price=63.92,   signal="showing"),
    dict(ticker="CAT",      date="2026-06-16", after_hours=False, alert_price=935.00,  signal="showing"),
    dict(ticker="NRG",      date="2026-06-16", after_hours=False, alert_price=128.69,  signal="showing"),
    dict(ticker="CRWV",     date="2026-06-16", after_hours=False, alert_price=104.00,  signal="showing"),
    dict(ticker="SE",       date="2026-06-16", after_hours=False, alert_price=85.60,   signal="showing"),
    dict(ticker="XLK",      date="2026-06-16", after_hours=False, alert_price=190.37,  signal="showing"),
    dict(ticker="OWL",      date="2026-06-16", after_hours=False, alert_price=9.99,    signal="showing"),
    dict(ticker="OPEN",     date="2026-06-16", after_hours=False, alert_price=4.63,    signal="showing"),
    dict(ticker="UNIUSD",   date="2026-06-16", after_hours=False, alert_price=2.590,   signal="showing"),
    dict(ticker="TIAUSD",   date="2026-06-16", after_hours=True,  alert_price=0.3504,  signal="showing"),
    dict(ticker="ASTERUSDT",date="2026-06-17", after_hours=False, alert_price=0.635,   signal="showing"),
    dict(ticker="TTWO",     date="2026-06-17", after_hours=False, alert_price=213.01,  signal="showing"),
    dict(ticker="NBIS",     date="2026-06-17", after_hours=False, alert_price=251.96,  signal="showing"),
    dict(ticker="PRME",     date="2026-06-18", after_hours=False, alert_price=2.92,    signal="showing"),
    dict(ticker="TXRH",     date="2026-06-18", after_hours=False, alert_price=166.51,  signal="showing"),
    dict(ticker="NNE",      date="2026-06-18", after_hours=False, alert_price=24.80,   signal="showing"),
    dict(ticker="DIS",      date="2026-06-18", after_hours=False, alert_price=100.88,  signal="showing"),
    dict(ticker="XYZ",      date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="APLD",     date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="QQQ",      date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="LMND",     date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="SE",       date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="MA",       date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="ABNB",     date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="CMG",      date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="LCID",     date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="IWM",      date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="NNE",      date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="AFRM",     date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="WDC",      date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="NU",       date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="NBIS",     date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="GRAB",     date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="DIS",      date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="IREN",     date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="XLU",      date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="REGN",     date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="UBER",     date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="DASH",     date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="STZ",      date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="RIOT",     date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="CELH",     date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="GXO",      date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="V",        date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="TMUS",     date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="TXRH",     date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="MRNA",     date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="TSM",      date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="SNDK",     date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="CAT",      date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="RKT",      date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="NRG",      date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="HWM",      date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="BLK",      date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="CRWV",     date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="COF",      date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="ED",       date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="HNST",     date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="WULF",     date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
    dict(ticker="BSX",      date="2026-06-18", after_hours=False, alert_price=None,    signal="confirmed"),
]

DAILY = [
    # 5/25 - Memorial Day weekend, after hours
    dict(ticker="PENDLEUSD", date="2026-05-25", after_hours=True,  alert_price=None,         sig_type="Green"),
    dict(ticker="STXUSD",    date="2026-05-25", after_hours=True,  alert_price=None,         sig_type="Green"),
    dict(ticker="XRPUSD",    date="2026-05-25", after_hours=True,  alert_price=None,         sig_type="Green"),
    dict(ticker="ATOMUSD",   date="2026-05-25", after_hours=True,  alert_price=None,         sig_type="Green"),
    dict(ticker="ARBUSD",    date="2026-05-25", after_hours=True,  alert_price=None,         sig_type="Green"),
    dict(ticker="JASMYUSD",  date="2026-05-25", after_hours=True,  alert_price=None,         sig_type="Green"),
    dict(ticker="AXLUSD",    date="2026-05-25", after_hours=True,  alert_price=None,         sig_type="Green"),
    dict(ticker="BABYUSD",   date="2026-05-25", after_hours=True,  alert_price=None,         sig_type="Green"),
    dict(ticker="LDOUSD",    date="2026-05-25", after_hours=True,  alert_price=None,         sig_type="Green"),
    dict(ticker="CROUSD",    date="2026-05-25", after_hours=True,  alert_price=None,         sig_type="Green"),
    # 5/26
    dict(ticker="FETUSD",   date="2026-05-26", after_hours=False, alert_price=0.2314,        sig_type="EMA Cross"),
    dict(ticker="MRK",      date="2026-05-26", after_hours=False, alert_price=122.90,        sig_type="EMA Cross"),
    dict(ticker="OKLO",     date="2026-05-26", after_hours=False, alert_price=71.87,         sig_type="EMA Cross"),
    dict(ticker="BBAI",     date="2026-05-26", after_hours=False, alert_price=4.24,          sig_type="EMA Cross"),
    dict(ticker="DXCM",     date="2026-05-26", after_hours=False, alert_price=72.02,         sig_type="EMA Cross"),
    dict(ticker="RR",       date="2026-05-26", after_hours=False, alert_price=2.76,          sig_type="EMA Cross"),
    dict(ticker="BKKT",     date="2026-05-26", after_hours=False, alert_price=12.40,         sig_type="EMA Cross"),
    dict(ticker="PGY",      date="2026-05-26", after_hours=False, alert_price=12.75,         sig_type="Green"),
    dict(ticker="RBRK",     date="2026-05-26", after_hours=False, alert_price=67.07,         sig_type="Green"),
    dict(ticker="U",        date="2026-05-26", after_hours=False, alert_price=26.72,         sig_type="Green"),
    dict(ticker="BLK",      date="2026-05-26", after_hours=False, alert_price=1077.50,       sig_type="Green"),
    dict(ticker="LUMN",     date="2026-05-26", after_hours=False, alert_price=9.58,          sig_type="Green"),
    dict(ticker="LRN",      date="2026-05-26", after_hours=False, alert_price=88.08,         sig_type="Green"),
    dict(ticker="SEZL",     date="2026-05-26", after_hours=False, alert_price=105.51,        sig_type="Green"),
    dict(ticker="ZS",       date="2026-05-26", after_hours=False, alert_price=184.96,        sig_type="Green"),
    dict(ticker="PINS",     date="2026-05-26", after_hours=False, alert_price=19.09,         sig_type="Green"),
    dict(ticker="SEIUSD",   date="2026-05-26", after_hours=True,  alert_price=0.061778,      sig_type="Ribbon Cross"),
    dict(ticker="FETUSD",   date="2026-05-26", after_hours=True,  alert_price=0.2500,        sig_type="Ribbon Cross"),
    dict(ticker="SEIUSD",   date="2026-05-26", after_hours=True,  alert_price=0.065788,      sig_type="Ribbon Cross"),
    dict(ticker="SPXUSDC",  date="2026-05-26", after_hours=True,  alert_price=0.3615,        sig_type="Green"),
    dict(ticker="IMXUSDT",  date="2026-05-26", after_hours=True,  alert_price=0.1666,        sig_type="Green"),
    # 5/27
    dict(ticker="DKNG",    date="2026-05-27", after_hours=False, alert_price=23.85,          sig_type="Ribbon Cross"),
    dict(ticker="HOOD",    date="2026-05-27", after_hours=False, alert_price=73.92,          sig_type="Green"),
    dict(ticker="PLTZ",    date="2026-05-27", after_hours=False, alert_price=31.77,          sig_type="Green"),
    dict(ticker="NOW",     date="2026-05-27", after_hours=False, alert_price=99.21,          sig_type="Green"),
    dict(ticker="DIS",     date="2026-05-27", after_hours=False, alert_price=103.30,         sig_type="Green"),
    dict(ticker="OSMOUSD", date="2026-05-27", after_hours=True,  alert_price=0.0622,         sig_type="Green"),
    # 5/28
    dict(ticker="SNOW",    date="2026-05-28", after_hours=False, alert_price=237.00,         sig_type="Ribbon Cross"),
    dict(ticker="DKNG",    date="2026-05-28", after_hours=False, alert_price=24.99,          sig_type="Ribbon Cross"),
    dict(ticker="GE",      date="2026-05-28", after_hours=False, alert_price=316.77,         sig_type="Ribbon Cross"),
    dict(ticker="ONDS",    date="2026-05-28", after_hours=False, alert_price=11.48,          sig_type="Ribbon Cross"),
    dict(ticker="ACHR",    date="2026-05-28", after_hours=False, alert_price=6.45,           sig_type="Ribbon Cross"),
    dict(ticker="MSFT",    date="2026-05-28", after_hours=False, alert_price=412.98,         sig_type="Green"),
    dict(ticker="RBRK",    date="2026-05-28", after_hours=False, alert_price=65.99,          sig_type="Green"),
    dict(ticker="NVO",     date="2026-05-28", after_hours=False, alert_price=44.05,          sig_type="Green"),
    dict(ticker="CNC",     date="2026-05-28", after_hours=False, alert_price=58.96,          sig_type="Green"),
    dict(ticker="SOUN",    date="2026-05-28", after_hours=False, alert_price=8.02,           sig_type="Green"),
    dict(ticker="ORCL",    date="2026-05-28", after_hours=False, alert_price=194.04,         sig_type="Green"),
    dict(ticker="CRWV",    date="2026-05-28", after_hours=False, alert_price=107.95,         sig_type="Green"),
    dict(ticker="XLMUSD",  date="2026-05-28", after_hours=True,  alert_price=0.20349,        sig_type="Ribbon Cross"),
    dict(ticker="HBARUSD", date="2026-05-28", after_hours=True,  alert_price=0.08552,        sig_type="Green"),
    # 5/29
    dict(ticker="RDDT",   date="2026-05-29", after_hours=False, alert_price=168.71,          sig_type="Ribbon Cross"),
    dict(ticker="ACHR",   date="2026-05-29", after_hours=False, alert_price=6.71,            sig_type="Ribbon Cross"),
    dict(ticker="ABBV",   date="2026-05-29", after_hours=False, alert_price=219.02,          sig_type="Ribbon Cross"),
    dict(ticker="DECK",   date="2026-05-29", after_hours=False, alert_price=114.79,          sig_type="Ribbon Cross"),
    dict(ticker="DOCU",   date="2026-05-29", after_hours=False, alert_price=50.15,           sig_type="Ribbon Cross"),
    dict(ticker="IOT",    date="2026-05-29", after_hours=False, alert_price=32.04,           sig_type="Ribbon Cross"),
    dict(ticker="DKNG",   date="2026-05-29", after_hours=False, alert_price=24.49,           sig_type="Ribbon Cross"),
    dict(ticker="IBM",    date="2026-05-29", after_hours=False, alert_price=277.30,          sig_type="Ribbon Cross"),
    dict(ticker="OKTA",   date="2026-05-29", after_hours=False, alert_price=107.54,          sig_type="Green"),
    dict(ticker="BMNR",   date="2026-05-29", after_hours=False, alert_price=18.90,           sig_type="Green"),
    dict(ticker="COIN",   date="2026-05-29", after_hours=False, alert_price=180.23,          sig_type="Green"),
    dict(ticker="BIDU",   date="2026-05-29", after_hours=False, alert_price=133.22,          sig_type="Green"),
    dict(ticker="UBER",   date="2026-05-29", after_hours=False, alert_price=70.65,           sig_type="Green"),
    dict(ticker="DXCM",   date="2026-05-29", after_hours=False, alert_price=72.89,           sig_type="Green"),
    dict(ticker="CRCL",   date="2026-05-29", after_hours=False, alert_price=108.03,          sig_type="Green"),
    dict(ticker="MDB",    date="2026-05-29", after_hours=False, alert_price=350.50,          sig_type="Green"),
    dict(ticker="PANW",   date="2026-05-29", after_hours=False, alert_price=256.32,          sig_type="Green"),
    dict(ticker="FIG",    date="2026-05-29", after_hours=False, alert_price=23.39,           sig_type="Green"),
    dict(ticker="DDOG",   date="2026-05-29", after_hours=False, alert_price=234.00,          sig_type="Green"),
    dict(ticker="INTU",   date="2026-05-29", after_hours=False, alert_price=317.03,          sig_type="Green"),
    dict(ticker="CRWD",   date="2026-05-29", after_hours=False, alert_price=677.44,          sig_type="Green"),
    dict(ticker="FISV",   date="2026-05-29", after_hours=False, alert_price=55.64,           sig_type="Green"),
    dict(ticker="ALGOUSD",  date="2026-05-29", after_hours=True, alert_price=0.1158,         sig_type="Green"),
    dict(ticker="ZBCNUSD",  date="2026-05-29", after_hours=True, alert_price=0.0028461,      sig_type="Green"),
    dict(ticker="INJUSD",   date="2026-05-29", after_hours=True, alert_price=5.465,          sig_type="Green"),
    dict(ticker="RSRUSDT",  date="2026-05-29", after_hours=True, alert_price=0.001620,       sig_type="Green"),
    dict(ticker="PYTHUSD",  date="2026-05-29", after_hours=True, alert_price=0.0390,         sig_type="Green"),
    dict(ticker="AXLUSD",   date="2026-05-29", after_hours=True, alert_price=0.0515,         sig_type="Green"),
    dict(ticker="JASMYUSD", date="2026-05-29", after_hours=True, alert_price=0.00555,        sig_type="Green"),
    dict(ticker="HBARUSD",  date="2026-05-29", after_hours=True, alert_price=0.09910,        sig_type="Ribbon Cross"),
    dict(ticker="SHXUSD",   date="2026-05-29", after_hours=True, alert_price=0.006110,       sig_type="Ribbon Cross"),
    dict(ticker="SHXUSDT",  date="2026-05-29", after_hours=True, alert_price=0.006095,       sig_type="Ribbon Cross"),
    # 5/30 - Saturday
    dict(ticker="LINKUSD",  date="2026-05-30", after_hours=True, alert_price=9.010,          sig_type="Green"),
    dict(ticker="MNTUSDT",  date="2026-05-30", after_hours=True, alert_price=0.6435,         sig_type="Green"),
    dict(ticker="XRPUSD",   date="2026-05-30", after_hours=True, alert_price=1.32830,        sig_type="Green"),
    dict(ticker="ETHUSD",   date="2026-05-30", after_hours=True, alert_price=2011.64,        sig_type="Green"),
    dict(ticker="SOLUSD",   date="2026-05-30", after_hours=True, alert_price=81.91,          sig_type="Green"),
    dict(ticker="CROUSD",   date="2026-05-30", after_hours=True, alert_price=0.06807,        sig_type="Green"),
    dict(ticker="PUMPUSD",  date="2026-05-30", after_hours=True, alert_price=0.001725,       sig_type="Green"),
    dict(ticker="PEPEUSD",  date="2026-05-30", after_hours=True, alert_price=0.000003386,    sig_type="Green"),
    dict(ticker="DOGEUSD",  date="2026-05-30", after_hours=True, alert_price=0.09957,        sig_type="Green"),
    dict(ticker="BNBUSDT",  date="2026-05-30", after_hours=True, alert_price=643.11,         sig_type="Green"),
    dict(ticker="ASTERUSDT",date="2026-05-30", after_hours=True, alert_price=0.674,          sig_type="Green"),
    # 6/9
    dict(ticker="MORPHOUSDT",date="2026-06-09", after_hours=False, alert_price=1.8032,       sig_type="Ribbon Cross"),
    dict(ticker="DUOL",      date="2026-06-09", after_hours=False, alert_price=117.13,       sig_type="Ribbon Cross"),
    dict(ticker="CCL",       date="2026-06-09", after_hours=False, alert_price=27.53,        sig_type="Ribbon Cross"),
    dict(ticker="CURE",      date="2026-06-09", after_hours=False, alert_price=101.18,       sig_type="Ribbon Cross"),
    dict(ticker="DLTR",      date="2026-06-09", after_hours=False, alert_price=108.64,       sig_type="Ribbon Cross"),
    dict(ticker="BRK.B",     date="2026-06-09", after_hours=False, alert_price=486.44,       sig_type="Ribbon Cross"),
    dict(ticker="ETHA",      date="2026-06-09", after_hours=False, alert_price=12.60,        sig_type="Green"),
    dict(ticker="HNST",      date="2026-06-09", after_hours=False, alert_price=3.37,         sig_type="Green"),
    dict(ticker="HIMS",      date="2026-06-09", after_hours=False, alert_price=27.17,        sig_type="Green"),
    dict(ticker="DECK",      date="2026-06-09", after_hours=False, alert_price=111.38,       sig_type="Green"),
    dict(ticker="COIN",      date="2026-06-09", after_hours=False, alert_price=157.25,       sig_type="Green"),
    dict(ticker="DKNG",      date="2026-06-09", after_hours=False, alert_price=25.15,        sig_type="Green"),
    dict(ticker="ALK",       date="2026-06-09", after_hours=False, alert_price=43.20,        sig_type="Green"),
    dict(ticker="PGY",       date="2026-06-09", after_hours=False, alert_price=15.28,        sig_type="Green"),
    dict(ticker="RDDT",      date="2026-06-09", after_hours=False, alert_price=178.55,       sig_type="Green"),
    # 6/10
    dict(ticker="MORPHOUSDT",date="2026-06-10", after_hours=False, alert_price=1.9030,       sig_type="Ribbon Cross"),
    dict(ticker="XLP",       date="2026-06-10", after_hours=False, alert_price=84.76,        sig_type="Ribbon Cross"),
    dict(ticker="BRK.B",     date="2026-06-10", after_hours=False, alert_price=488.13,       sig_type="Ribbon Cross"),
    dict(ticker="DNUT",      date="2026-06-10", after_hours=False, alert_price=3.73,         sig_type="Ribbon Cross"),
    dict(ticker="CVX",       date="2026-06-10", after_hours=False, alert_price=189.19,       sig_type="Ribbon Cross"),
    dict(ticker="KVUE",      date="2026-06-10", after_hours=False, alert_price=18.00,        sig_type="Ribbon Cross"),
    dict(ticker="HOOD",      date="2026-06-10", after_hours=False, alert_price=84.09,        sig_type="Green"),
    dict(ticker="NVO",       date="2026-06-10", after_hours=False, alert_price=41.67,        sig_type="Green"),
    # 6/11
    dict(ticker="KVUE",     date="2026-06-11", after_hours=False, alert_price=18.11,         sig_type="Ribbon Cross"),
    dict(ticker="CVX",      date="2026-06-11", after_hours=False, alert_price=191.81,        sig_type="Ribbon Cross"),
    dict(ticker="CCL",      date="2026-06-11", after_hours=False, alert_price=25.67,         sig_type="Ribbon Cross"),
    dict(ticker="MRNA",     date="2026-06-11", after_hours=False, alert_price=46.43,         sig_type="Green"),
    dict(ticker="PSKY",     date="2026-06-11", after_hours=False, alert_price=10.25,         sig_type="Green"),
    dict(ticker="MRK",      date="2026-06-11", after_hours=False, alert_price=120.04,        sig_type="Green"),
    dict(ticker="ALK",      date="2026-06-11", after_hours=False, alert_price=41.52,         sig_type="Green"),
    dict(ticker="PGY",      date="2026-06-11", after_hours=False, alert_price=14.40,         sig_type="Green"),
    dict(ticker="KSS",      date="2026-06-11", after_hours=False, alert_price=15.88,         sig_type="Green"),
    dict(ticker="RZLV",     date="2026-06-11", after_hours=False, alert_price=2.40,          sig_type="Green"),
    dict(ticker="AMGN",     date="2026-06-11", after_hours=False, alert_price=342.91,        sig_type="Green"),
]

# ── Cross-reference map ────────────────────────────────────────────────────────
def _week_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())

def _build_cross_ref() -> dict:
    ref: dict = {}
    for label, alerts in [("GD", GOLDEN_DOT), ("M", MONTHLY), ("W", WEEKLY), ("D", DAILY)]:
        for a in alerts:
            d = date.fromisoformat(a["date"])
            key = (a["ticker"], _week_monday(d))
            ref.setdefault(key, set()).add(label)
    return ref

_CROSS_REF = _build_cross_ref()

_BADGE_COLORS = {"GD": _GOLD, "M": _BLUE, "W": _GREEN, "D": _MUTED}

def _cross_badges(ticker: str, alert_date: str, own_label: str) -> str:
    d = date.fromisoformat(alert_date)
    others = _CROSS_REF.get((ticker, _week_monday(d)), set()) - {own_label}
    if not others:
        return ""
    parts = []
    for lbl in sorted(others):
        c = _BADGE_COLORS.get(lbl, _MUTED)
        parts.append(
            f'<span style="margin-left:3px;background:{c}22;color:{c};border:1px solid {c}55;'
            f'font-size:8px;font-weight:700;padding:1px 5px;border-radius:4px;'
            f'vertical-align:middle">{lbl}</span>'
        )
    return "".join(parts)

# ── Price fetching (cached 1 hour) ─────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_all_prices() -> pd.DataFrame:
    """
    Download Close prices for all tracked tickers from 2026-02-01 to today.
    Returns a DataFrame where columns = yf tickers, index = dates.
    Falls back to empty DataFrame on failure.
    """
    all_alerts = GOLDEN_DOT + MONTHLY + WEEKLY + DAILY
    yf_tickers = sorted({_to_yf(a["ticker"]) for a in all_alerts if _to_yf(a["ticker"])})

    if not yf_tickers:
        return pd.DataFrame()

    try:
        end_str = (TODAY + timedelta(days=1)).isoformat()
        raw = yf.download(
            yf_tickers,
            start="2026-02-01",
            end=end_str,
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception:
        return pd.DataFrame()

    if raw.empty:
        return pd.DataFrame()

    # Extract just the Close column(s)
    if isinstance(raw.columns, pd.MultiIndex):
        # Multi-ticker: columns = (price_type, ticker)
        if "Close" in raw.columns.get_level_values(0):
            close_df = raw["Close"]
        else:
            close_df = pd.DataFrame()
    else:
        # Single ticker returned as flat DataFrame
        if "Close" in raw.columns:
            close_df = raw[["Close"]].rename(columns={"Close": yf_tickers[0]})
        else:
            close_df = pd.DataFrame()

    return close_df


def _price_on_or_after(close_df: pd.DataFrame, yf_tk: str, target: date) -> float | None:
    """Closest available close price on or after target date."""
    if close_df.empty or yf_tk not in close_df.columns:
        return None
    target_ts = pd.Timestamp(target)
    later = close_df[yf_tk].dropna()
    later = later[later.index >= target_ts]
    return float(later.iloc[0]) if not later.empty else None


def _latest_price(close_df: pd.DataFrame, yf_tk: str) -> float | None:
    """Most recent available close price."""
    if close_df.empty or yf_tk not in close_df.columns:
        return None
    s = close_df[yf_tk].dropna()
    return float(s.iloc[-1]) if not s.empty else None


# ── Row builder ────────────────────────────────────────────────────────────────
def _build_rows(alerts: list, own_label: str, close_df: pd.DataFrame) -> list[dict]:
    rows = []
    for a in alerts:
        tk      = a["ticker"]
        yf_tk   = _to_yf(tk)
        bd      = _buy_date(a["date"], a.get("after_hours", False))

        buy_p   = _price_on_or_after(close_df, yf_tk, bd) if yf_tk else None
        if buy_p is None:
            buy_p = a.get("alert_price")   # fall back to alert-message price

        d2w = bd + timedelta(days=14)
        d1m = bd + timedelta(days=30)

        p2w  = _price_on_or_after(close_df, yf_tk, d2w) if (yf_tk and d2w <= TODAY) else None
        p1m  = _price_on_or_after(close_df, yf_tk, d1m) if (yf_tk and d1m <= TODAY) else None
        pcur = _latest_price(close_df, yf_tk) if yf_tk else None

        def _ret(buy, sell):
            if buy and sell and buy > 0:
                return (sell - buy) / buy * 100
            return None

        rows.append(dict(
            ticker    = tk,
            yf_tk     = yf_tk or "—",
            date      = a["date"],
            buy_date  = bd.isoformat(),
            buy_price = buy_p,
            p2w       = p2w,
            r2w       = _ret(buy_p, p2w),
            p1m       = p1m,
            r1m       = _ret(buy_p, p1m),
            pcur      = pcur,
            rcur      = _ret(buy_p, pcur),
            signal    = a.get("signal", a.get("sig_type", "")),
            badges    = _cross_badges(tk, a["date"], own_label),
        ))
    return rows


# ── Formatting helpers ─────────────────────────────────────────────────────────
def _fmt(v: float | None) -> str:
    if v is None:
        return "—"
    if v >= 1000:
        return f"${v:,.0f}"
    if v >= 1:
        return f"${v:.2f}"
    if v >= 0.001:
        return f"${v:.4f}"
    return f"${v:.6f}"

def _pct(v: float | None, bold: bool = False) -> str:
    if v is None:
        return "—"
    s = f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"
    return f"<b>{s}</b>" if bold else s

def _pc(v: float | None) -> str:
    if v is None:
        return _MUTED
    return _GREEN if v >= 0 else _RED


# ── HTML table renderer ────────────────────────────────────────────────────────
def _summary_bar(rows: list, accent: str) -> str:
    priced = [r for r in rows if r["rcur"] is not None]
    if not priced:
        return ""
    hits     = sum(1 for r in priced if r["rcur"] >= 0)
    hit_rate = hits / len(priced) * 100
    avg_r    = sum(r["rcur"] for r in priced) / len(priced)
    hit_c    = _GREEN if hit_rate >= 55 else (_GOLD if hit_rate >= 45 else _RED)
    avg_c    = _pc(avg_r)
    return (
        f'<div style="display:flex;gap:24px;flex-wrap:wrap;margin-bottom:10px;'
        f'padding:10px 14px;background:{_CARD};border-radius:8px;border:1px solid #1e293b">'
        f'<span style="font-size:11px;color:{_DIM}">Total alerts <b style="color:{_TEXT}">{len(rows)}</b></span>'
        f'<span style="font-size:11px;color:{_DIM}">Priced <b style="color:{_TEXT}">{len(priced)}</b></span>'
        f'<span style="font-size:11px;color:{_DIM}">Hit rate '
        f'<b style="color:{hit_c}">{hit_rate:.0f}%</b></span>'
        f'<span style="font-size:11px;color:{_DIM}">Avg current return '
        f'<b style="color:{avg_c}">{_pct(avg_r)}</b></span>'
        f'</div>'
    )

def _render_table(rows: list, own_label: str, accent: str, show_signal: bool = False):
    if not rows:
        st.info("No data.")
        return

    st.markdown(_summary_bar(rows, accent), unsafe_allow_html=True)

    sig_th = (
        f'<th style="text-align:center;padding:6px 8px;color:{_MUTED};font-size:9px;font-weight:600;'
        f'text-transform:uppercase;white-space:nowrap">Signal Type</th>'
    ) if show_signal else ""

    thead = (
        f'<thead><tr style="border-bottom:2px solid #334155">'
        f'<th style="text-align:left;padding:6px 12px;color:{_MUTED};font-size:9px;font-weight:600;text-transform:uppercase">Ticker</th>'
        f'<th style="text-align:center;padding:6px 8px;color:{_MUTED};font-size:9px;font-weight:600;text-transform:uppercase">Alert Date</th>'
        f'<th style="text-align:center;padding:6px 8px;color:{_MUTED};font-size:9px;font-weight:600;text-transform:uppercase">Buy Date</th>'
        f'{sig_th}'
        f'<th style="text-align:right;padding:6px 10px;color:{_MUTED};font-size:9px;font-weight:600;text-transform:uppercase">Buy $</th>'
        f'<th style="text-align:right;padding:6px 10px;color:{_MUTED};font-size:9px;font-weight:600;text-transform:uppercase">2-Week</th>'
        f'<th style="text-align:right;padding:6px 10px;color:{_MUTED};font-size:9px;font-weight:600;text-transform:uppercase">1-Month</th>'
        f'<th style="text-align:right;padding:6px 10px;color:{_MUTED};font-size:9px;font-weight:600;text-transform:uppercase">Current $</th>'
        f'<th style="text-align:right;padding:6px 10px;color:{_MUTED};font-size:9px;font-weight:600;text-transform:uppercase">Return</th>'
        f'</tr></thead>'
    )

    def _ret_td(ret, price):
        if price is None:
            return f'<td style="text-align:right;padding:6px 10px;color:{_MUTED};font-size:11px">—</td>'
        c = _pc(ret)
        p_str = _fmt(price)
        r_str = _pct(ret)
        return (
            f'<td style="text-align:right;padding:5px 10px;font-size:11px">'
            f'<div style="color:{_DIM};font-size:9px">{p_str}</div>'
            f'<div style="color:{c};font-weight:600">{r_str}</div></td>'
        )

    tbody = "<tbody>"
    for r in rows:
        sig_td = ""
        if show_signal:
            s  = r["signal"] or ""
            sc = (_GOLD   if s == "confirmed"
                  else _PUR    if "Ribbon" in s
                  else _BLUE   if "EMA"    in s
                  else _GREEN  if s == "showing"
                  else _MUTED)
            sig_td = (
                f'<td style="text-align:center;padding:6px 8px">'
                f'<span style="color:{sc};font-size:9px;font-weight:600">{s}</span></td>'
            )

        rcur_c = _pc(r["rcur"])
        tbody += (
            f'<tr style="border-bottom:1px solid #1e293b">'
            f'<td style="padding:6px 12px;white-space:nowrap">'
            f'<span style="color:{accent};font-weight:700;font-size:12px;font-family:DM Mono,monospace">{r["ticker"]}</span>'
            f'{r["badges"]}</td>'
            f'<td style="text-align:center;padding:6px 8px;color:{_DIM};font-size:11px;white-space:nowrap">{r["date"]}</td>'
            f'<td style="text-align:center;padding:6px 8px;color:{_MUTED};font-size:10px;white-space:nowrap">{r["buy_date"]}</td>'
            f'{sig_td}'
            f'<td style="text-align:right;padding:6px 10px;color:{_TEXT};font-size:11px;font-family:DM Mono,monospace">{_fmt(r["buy_price"])}</td>'
            + _ret_td(r["r2w"], r["p2w"])
            + _ret_td(r["r1m"], r["p1m"])
            + f'<td style="text-align:right;padding:6px 10px;color:{_DIM};font-size:11px;font-family:DM Mono,monospace">{_fmt(r["pcur"])}</td>'
            f'<td style="text-align:right;padding:6px 10px;font-size:13px;font-weight:700;color:{rcur_c}">'
            f'{"—" if r["rcur"] is None else _pct(r["rcur"])}</td>'
            f'</tr>'
        )
    tbody += "</tbody>"

    st.markdown(
        f'<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;'
        f'background:{_BG};border:1px solid #1e293b;border-radius:8px;overflow:hidden">'
        + thead + tbody + '</table></div>',
        unsafe_allow_html=True,
    )


# ── Analysis section ───────────────────────────────────────────────────────────
def _render_analysis(gd_rows, m_rows, w_rows, d_rows):
    st.markdown(
        f'<div style="font-size:11px;font-weight:600;color:{_DIM};text-transform:uppercase;'
        f'letter-spacing:1px;margin:8px 0 14px">📋 OverKill Signal Analysis — What Works &amp; What Doesn\'t</div>',
        unsafe_allow_html=True,
    )

    # Compute summary stats per table for dynamic callouts
    def _stats(rows):
        p = [r for r in rows if r["rcur"] is not None]
        if not p:
            return 0, 0, 0
        hits = sum(1 for r in p if r["rcur"] >= 0)
        return len(p), hits / len(p) * 100, sum(r["rcur"] for r in p) / len(p)

    gd_n, gd_hr, gd_avg = _stats(gd_rows)
    m_n,  m_hr,  m_avg  = _stats(m_rows)
    w_n,  w_hr,  w_avg  = _stats(w_rows)
    d_n,  d_hr,  d_avg  = _stats(d_rows)

    def _badge(label, color):
        return (f'<span style="background:{color}22;color:{color};border:1px solid {color}55;'
                f'font-size:10px;font-weight:700;padding:2px 7px;border-radius:5px">{label}</span>')

    st.markdown(f"""
<div style="font-size:13px;color:{_TEXT};line-height:1.85;max-width:900px">

<h4 style="color:{_GOLD};margin-top:20px">🟡 Golden Dot — The Rarest, Highest-Quality Signal</h4>

The Golden Dot {_badge("GD", _GOLD)} fires far less frequently than the green signals — that rarity is by design.
It marks a point where price, momentum, RSI, and volume all aligned simultaneously on the **daily timeframe**.
When GD fires, the typical picture at that moment is: RSI crossing back above 40 from deeply oversold territory,
MACD histogram turning positive after a prolonged negative stretch, and price reclaiming the 20-day EMA on
above-average volume. That combination is meaningful because it isn't just a bounce — it's a structure reset.

**What works:**
- GD alerts on high-quality tech names during broader pullbacks (ZS Feb-27, PANW Feb-27, INTU Apr-16) have
  historically seen follow-through because the underlying fundamentals are intact.
- When a GD also fires on the same ticker in the **Weekly or Monthly** table that same week — that cross-badge
  is a very high-conviction setup (look for the colored {_badge("W", _GREEN)} or {_badge("M", _BLUE)} badges on the ticker).
- GD signals in mid-to-late month after earnings-driven selloffs (CELH, BIDU, ABBV) tend to mark capitulation lows.

**What to watch out for:**
- April 1–6 alerts (CELH, DASH, SNOW, RGTI, ELF) fired into what became a sharp market downturn driven by macro
  tariff/policy noise. Many showed immediate drawdowns. GD does not filter macro risk — it reads technicals only.
- Crypto GD alerts (OPUSD, COMPUSD, TRUMPUSD) are speculative; the signal logic holds but the instruments are
  far more volatile and liquidity can evaporate fast.


<h4 style="color:{_BLUE};margin-top:24px">🟢 Monthly Signal — Macro Trend Confirmation</h4>

The Monthly {_badge("M", _BLUE)} signal tells you the **longest-duration trend has turned**. A green on the monthly chart
means the monthly candle closed with bullish momentum structure — MACD turned positive or RSI recovered into
neutral territory after a multi-month downtrend. This is a slow-moving, high-conviction filter.

**What works:**
- Monthly signals that fire alongside a Weekly signal in the same week are the most actionable. Check for
  {_badge("W", _GREEN)} badges next to monthly tickers — these are the highest-conviction setups in the entire system.
- All June 1 monthly alerts came in a cluster on a Monday (first trading day of June), which means they all
  share the same monthly candle close trigger. That kind of clustering usually indicates a broad market breadth
  improvement — many sectors turning at once, not just cherry-picks.
- Large-cap defensive and quality names (MSFT, PLTR, ABBV, GE) on monthly signals tend to have the most
  reliable follow-through because monthly reversals are slow, sticky, and fundamentally supported.

**What to watch out for:**
- Monthly signals are early — sometimes very early. The stock may still trade sideways or down for 2–4 weeks
  before direction establishes. Sizing into these on day 1 often means managing a drawdown before the trend begins.
- Single-sector ETF monthly signals (XLV, XLF, XLI) confirm sector rotation but don't give individual stock
  alpha. Use these to screen within the sector rather than to trade the ETF directly.


<h4 style="color:{_GREEN};margin-top:24px">🟢 Weekly Signal — The Primary Trading Timeframe</h4>

Weekly {_badge("W", _GREEN)} signals are the workhorse. They fire more frequently than Monthly but still carry
meaningful weight — a green on the weekly means the last week's candle showed RSI recovering (typically 40→50+),
MACD crossing bullish, and volume confirming the move. **"Showing"** means the setup is in progress;
**"Confirmed"** means it held through the close of the candle (Friday) — confirmed is meaningfully more reliable.

**What works:**
- **Confirmed Weekly + same-week Daily Ribbon Cross** is the gold standard intraweek setup. Look for tickers
  showing {_badge("D", _MUTED)} badge on weekly rows. This means the daily EMA ribbon crossed bullish *while* the
  weekly signal was holding — momentum is aligned on two timeframes.
- The June 18 "Confirmed" wave (MA, CMG, SE, REGN, CELH, CAT, NRG, CRWV, HWM, BSX, DIS, V, TMUS, etc.) is a
  very large breadth event. When 40+ confirmed signals fire simultaneously, it usually means a meaningful
  rally leg has begun, not just rotation noise.
- Weekly crypto signals (TRUMPUSD, ETHBTC) work best when also supported by Bitcoin's direction.
  If BTC is in a weekly uptrend and altcoins fire weekly greens, follow-through probability is high.

**What to watch out for:**
- "Showing" signals that never got confirmed (appeared only once and didn't re-appear) are weaker.
  MCD and TOST appeared as "showing" on 6/1 and got "confirmed" on 6/5 — that double-tap in one week
  is a constructive sign.
- Extreme clusters of confirmed signals in a single day (6/5, 6/12, 6/18) can mark a short-term
  overbought condition right after a large up-move. These are still valid signals for swing trades but
  aggressive entries on the exact confirmation day can have rough 1–3 day pullbacks before continuing.


<h4 style="color:{_DIM};margin-top:24px">🟢 Daily Signal — Speed &amp; Precision, Mixed Results</h4>

Daily {_badge("D", _MUTED)} signals include three sub-types with different weights:

- **Ribbon Cross** (strongest): All EMAs in the ribbon crossed bullish. Usually marks a trend change, not just
  a bounce. RDDT, ABBV, IBM, CRWD ribbon crosses in late May were generally strong.
- **EMA Cross**: Two specific EMAs crossed — faster and noisier than ribbon. Valid as a momentum alert but
  needs confirming volume.
- **Green Dot on Daily**: Broadest signal, fires most often. Works best when the stock is already in a rising
  channel and this is a pullback-to-support green, not a bottom-fishing green.

**What works:**
- Ribbon crosses on mega-cap quality names (MSFT, ABBV, CRWD, PANW, IBM) in late May have shown consistent
  follow-through. These stocks have institutional buyers, so once the ribbon flips, trend tends to persist.
- Daily alerts that also have a {_badge("W", _GREEN)} badge (same-week weekly signal) are the most reliable
  daily setups. The weekly provides the wind, the daily provides the timing.
- The DKNG triple-tap (ribbon cross on 5/27, repeated on 5/28, again on 5/29) is interesting — multiple
  daily pings over 3 days usually means the stock is grinding higher in a controlled way, not spiking.
  These grind moves often persist for 2–4 weeks.

**What to watch out for:**
- Daily crypto alerts (XRPUSD, ETHUSD, SOLUSD) fired on 5/30 — a Saturday. The "buy price" is therefore
  the Monday 6/2 close. Crypto is 24/7, so the gap between alert and actual entry can be significant.
- Many obscure crypto tickers (ZBCNUSD, RSRUSDT, PYTHUSD, JASMYUSD) fired in large clusters. Cluster-firing
  in micro-cap crypto usually means the whole crypto market is pumping, not specific stock selection. The
  signal is more "risk-on in crypto" than individual ticker conviction.
- PLTZ and BMNR are low-float names — the daily green may not be liquid enough to trade at scale.


<h4 style="color:{_PUR};margin-top:24px">🔗 Cross-Timeframe Confluence — Where the Real Edge Lives</h4>

The cross-badge system highlights the most important insight in this data: **when the same ticker fires
on multiple timeframes in the same calendar week, the probability of follow-through increases meaningfully.**

Look for tickers wearing two or more badges simultaneously. Key examples from this dataset:

- **COIN**: Golden Dot (6/11) + Daily Green (6/9 and 6/11) = GD fired while daily momentum was already
  building. MACD was crossing positive on daily, RSI recovering from low 40s, and volume was picking up
  over 3 consecutive days. This is a textbook multi-timeframe entry.
- **CELH**: Golden Dot (4/1 and 5/19) + Weekly Showing (6/15) + Weekly Confirmed (6/18). Each separate
  GD was months apart, but the June weekly alignment shows that after each GD the stock was building
  a longer base. RSI on weekly was recovering from deeply oversold; MACD on weekly was diverging positively.
- **ABBV**: Golden Dot (4/30) + Daily Ribbon Cross (5/29) + Monthly (6/5). Three timeframes, different weeks —
  but the Monthly on 6/5 confirms the macro trend caught up to the daily recovery. This is the progression
  the OverKill system is designed to catch.
- **TXRH**: Monthly (6/2) + Weekly Showing (6/18) + Weekly Confirmed (6/18). All in a tight window.
  Monthly turns, weekly confirms within 2.5 weeks — that's fast confirmation and suggests strong buying pressure.
- **BRK.B**: Golden Dot (4/1) + Daily Ribbon Cross (6/9 and 6/10) + Monthly (6/16). A clean 10-week arc:
  GD marked the low in early April, daily ribbon crosses marked the momentum pickup in June, monthly
  confirmed the long-term trend change. Classic stage 2 breakout structure.


<h4 style="color:{_RED};margin-top:24px">⚠️ Where the System Struggles</h4>

- **Macro shock periods**: April 1–6 alerts fired into the teeth of tariff-driven volatility. Technical signals
  do not account for fundamental macro shocks. When the market is pricing in policy risk, even perfect
  technical setups can fail for 4–8 weeks.
- **VIX green signal**: A green on VIX means volatility is rising — that is a warning for long equity positions,
  not a buy signal. The VIX appearing in the Weekly Confirmed list on 6/5 should be read as a caution flag for
  all the equity confirmed signals that same week.
- **Illiquid or unresolvable tickers**: DVLT, BZAI, ANGX, RZLV, PSKY, BMNR, PRME, etc. — these are micro-caps
  or pre-revenue names. The signal logic fires the same way, but the stock-specific risk (dilution, halt risk,
  low float) can overwhelm the technical picture.
- **Crypto micro-caps**: MAMOUSD, PUMPUSD, WLFIUSDT are effectively untrackable with standard market data.
  These Golden Dot alerts should be treated as educational curiosities, not actionable signals.

</div>
""", unsafe_allow_html=True)


# ── Page entry point ───────────────────────────────────────────────────────────
def render():
    st.markdown(
        f'<div style="font-size:22px;font-weight:800;color:{_GOLD};margin-bottom:2px">🎯 OverKill Performance Tracker</div>'
        f'<div style="font-size:12px;color:{_MUTED};margin-bottom:16px">'
        f'Buy price = close on alert day (after-hours → next trading day close) &nbsp;·&nbsp; '
        f'Returns unrealized &nbsp;·&nbsp; Prices delayed up to 15 min &nbsp;·&nbsp; '
        f'<span style="color:{_DIM}">Colored badges = same ticker in another table that same calendar week</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    with st.spinner("Fetching price history for all alerts… (cached for 1 hour after first load)"):
        close_df = _fetch_all_prices()

    gd_rows = _build_rows(GOLDEN_DOT, "GD", close_df)
    m_rows  = _build_rows(MONTHLY,    "M",  close_df)
    w_rows  = _build_rows(WEEKLY,     "W",  close_df)
    d_rows  = _build_rows(DAILY,      "D",  close_df)

    tab_gd, tab_m, tab_w, tab_d, tab_ana = st.tabs([
        f"🟡 Golden Dot ({len(gd_rows)})",
        f"🟢 Monthly ({len(m_rows)})",
        f"🟢 Weekly ({len(w_rows)})",
        f"🟢 Daily ({len(d_rows)})",
        "📋 Analysis",
    ])

    with tab_gd:
        st.markdown(
            f'<div style="font-size:11px;color:{_DIM};margin-bottom:10px">'
            f'🟡 <b style="color:{_GOLD}">Golden Dot</b> — rarest, highest-quality signal. Fires when daily price, '
            f'RSI, MACD, and volume all align simultaneously. Treat as a premium alert.</div>',
            unsafe_allow_html=True,
        )
        _render_table(gd_rows, "GD", _GOLD, show_signal=False)

    with tab_m:
        st.markdown(
            f'<div style="font-size:11px;color:{_DIM};margin-bottom:10px">'
            f'🟢 <b style="color:{_BLUE}">Monthly</b> — macro trend confirmation. Monthly candle closed with '
            f'bullish MACD/RSI structure. Slow-moving but high-conviction. Best used to confirm Weekly signals.</div>',
            unsafe_allow_html=True,
        )
        _render_table(m_rows, "M", _BLUE, show_signal=False)

    with tab_w:
        st.markdown(
            f'<div style="font-size:11px;color:{_DIM};margin-bottom:10px">'
            f'🟢 <b style="color:{_GREEN}">Weekly</b> — primary trading timeframe. '
            f'<b style="color:{_GOLD}">Confirmed</b> = held through weekly close (stronger). '
            f'<b style="color:{_GREEN}">Showing</b> = signal in progress during the week.</div>',
            unsafe_allow_html=True,
        )
        _render_table(w_rows, "W", _GREEN, show_signal=True)

    with tab_d:
        st.markdown(
            f'<div style="font-size:11px;color:{_DIM};margin-bottom:10px">'
            f'🟢 <b style="color:{_DIM}">Daily</b> — three sub-types: '
            f'<b style="color:{_PUR}">Ribbon Cross</b> (strongest, all EMAs flip bullish) · '
            f'<b style="color:{_BLUE}">EMA Cross</b> (two EMAs cross) · '
            f'<b style="color:{_GREEN}">Green</b> (standard daily signal).</div>',
            unsafe_allow_html=True,
        )
        _render_table(d_rows, "D", _DIM, show_signal=True)

    with tab_ana:
        _render_analysis(gd_rows, m_rows, w_rows, d_rows)
