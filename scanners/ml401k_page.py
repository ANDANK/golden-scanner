"""ML 401K Analyzer — Fund comparison and portfolio analysis for BofA/ML 401k plan.

Data source: yfinance via proxy tickers (CIT funds are private trusts, not publicly traded).
Performance, holdings, and sector data are from the closest publicly-traded equivalent.
"""

import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta

# ── Fund Catalog ───────────────────────────────────────────────────────────────
# proxy = closest publicly-traded Yahoo Finance ticker for data
# is_cit = True means the ML symbol itself is a private Collective Investment Trust
FUND_CATALOG = [
    # ── EQUITY / STOCK ────────────────────────────────────────────────────────
    {"symbol":"GGRRT","name":"Acadian All World Ex-US Equity",  "cat":"Equity","sub":"International",     "proxy":"ACWX",  "is_cit":True,  "price":22.17},
    {"symbol":"EDFMT","name":"BlackRock Equity Dividend CL M",  "cat":"Equity","sub":"Dividend Equity",   "proxy":"DVY",   "is_cit":True,  "price":21.51},
    {"symbol":"BUFTT","name":"BlackRock LG Cap Growth EQ CL T", "cat":"Equity","sub":"Large Cap Growth",  "proxy":"IWF",   "is_cit":True,  "price":71.10},
    {"symbol":"RRUST","name":"BlackRock Russell 2000 Fund G1",  "cat":"Equity","sub":"Small Cap",         "proxy":"IWM",   "is_cit":True,  "price":20.11},
    {"symbol":"DOXGX","name":"Dodge & Cox Stock CL X",           "cat":"Equity","sub":"Large Cap Value",   "proxy":"DOXGX", "is_cit":False, "price":16.89},
    {"symbol":"EPSCT","name":"Earnest Partners SMID CP Core",    "cat":"Equity","sub":"SMID Cap",          "proxy":"IJH",   "is_cit":True,  "price":20.70},
    {"symbol":"MIGFT","name":"MFS International Growth",         "cat":"Equity","sub":"Intl Growth",       "proxy":"EFG",   "is_cit":True,  "price":31.47},
    {"symbol":"NSRIX","name":"Northern World Selection CL I",    "cat":"Equity","sub":"International",     "proxy":"VXUS",  "is_cit":True,  "price":27.50},
    {"symbol":"SSRLT","name":"State Street Real Asset K",        "cat":"Equity","sub":"Real Assets",       "proxy":"GNR",   "is_cit":True,  "price":15.46},
    {"symbol":"JAQNT","name":"T Rowe Large-Cap GR TRUS",         "cat":"Equity","sub":"Large Cap Growth",  "proxy":"TRLGX", "is_cit":True,  "price":26.84},
    {"symbol":"VGINT","name":"Vanguard INSTL 500 Index Trust",   "cat":"Equity","sub":"S&P 500 Index",     "proxy":"VOO",   "is_cit":True,  "price":330.86},
    {"symbol":"VGIET","name":"Vanguard INSTL Extended Market",   "cat":"Equity","sub":"Extended Market",   "proxy":"VXF",   "is_cit":True,  "price":238.72},
    {"symbol":"VGIST","name":"Vanguard INSTL TTL INTL STOCK",    "cat":"Equity","sub":"Total International","proxy":"VXUS", "is_cit":True,  "price":196.14},
    {"symbol":"BACSF","name":"BAC COM STK FUND",                  "cat":"Equity","sub":"Company Stock ⚠️", "proxy":"BAC",   "is_cit":True,  "price":18.51},
    # ── BOND / FIXED INCOME ───────────────────────────────────────────────────
    {"symbol":"FJAMT","name":"FIAM Core Plus II COM Pool CLB",   "cat":"Bond","sub":"Core Plus Bond",      "proxy":"FBNDX", "is_cit":True,  "price":10.13},
    {"symbol":"SEIFT","name":"PIMCO Total Return CIT IV",         "cat":"Bond","sub":"Core Bond",           "proxy":"PTTRX", "is_cit":True,  "price":15.93},
    {"symbol":"VIPIX","name":"Vanguard Inflation-Protected",      "cat":"Bond","sub":"TIPS",                "proxy":"VIPIX", "is_cit":False, "price":9.44},
    {"symbol":"VGITT","name":"Vanguard INSTL TTL BD MKT IND",    "cat":"Bond","sub":"Total Bond Market",   "proxy":"BND",   "is_cit":True,  "price":115.34},
    # ── ALLOCATION FUNDS ──────────────────────────────────────────────────────
    {"symbol":"BLIFT","name":"BlackRock Global Alloc CL J",       "cat":"Allocation","sub":"Global Balanced",   "proxy":"MDLOX", "is_cit":True,  "price":18.00},
    {"symbol":"BRK2T","name":"LifePath Index 2030 Fund D",        "cat":"Allocation","sub":"Target Date 2030",  "proxy":"VTHRX", "is_cit":True,  "price":11.97},
    {"symbol":"BRK3T","name":"LifePath Index 2035 Fund D",        "cat":"Allocation","sub":"Target Date 2035",  "proxy":"VTTHX", "is_cit":True,  "price":12.25},
    {"symbol":"BRK4T","name":"LifePath Index 2040 Fund D",        "cat":"Allocation","sub":"Target Date 2040",  "proxy":"VFORX", "is_cit":True,  "price":12.55},
    {"symbol":"BRK5T","name":"LifePath Index 2045 Fund D",        "cat":"Allocation","sub":"Target Date 2045",  "proxy":"VTIVX", "is_cit":True,  "price":12.84},
    {"symbol":"BRK6T","name":"LifePath Index 2050 Fund D",        "cat":"Allocation","sub":"Target Date 2050",  "proxy":"VFIFX", "is_cit":True,  "price":13.12},
    {"symbol":"BRK7T","name":"LifePath Index 2055 Fund D",        "cat":"Allocation","sub":"Target Date 2055",  "proxy":"VFFVX", "is_cit":True,  "price":13.25},
    {"symbol":"BRK8T","name":"LifePath Index 2060 Fund D",        "cat":"Allocation","sub":"Target Date 2060",  "proxy":"VTTSX", "is_cit":True,  "price":13.27},
    {"symbol":"BRK9T","name":"LifePath Index 2065 Fund D",        "cat":"Allocation","sub":"Target Date 2065",  "proxy":"VLXVX", "is_cit":True,  "price":13.27},
    {"symbol":"BRK0T","name":"LifePath Index 2070 Fund D",        "cat":"Allocation","sub":"Target Date 2070",  "proxy":"VTTSX", "is_cit":True,  "price":13.27},
    {"symbol":"BRK1T","name":"LifePath Index Retirement FD D",   "cat":"Allocation","sub":"Target Retirement",  "proxy":"VTINX", "is_cit":True,  "price":11.71},
    {"symbol":"PAAIX","name":"PIMCO All Asset Fund",              "cat":"Allocation","sub":"Multi-Asset",        "proxy":"PAAIX", "is_cit":False, "price":12.29},
    # ── STABLE VALUE ──────────────────────────────────────────────────────────
    {"symbol":"MLSVF","name":"Stable Value Fund",                 "cat":"Stable","sub":"Capital Preservation",  "proxy":"BIL",   "is_cit":True,  "price":26.87},
]

FUND_BY_SYMBOL = {f["symbol"]: f for f in FUND_CATALOG}

GROUPS = [
    ("📈 Equity / Stock",     [f for f in FUND_CATALOG if f["cat"] == "Equity"]),
    ("🏦 Bond / Fixed Income",[f for f in FUND_CATALOG if f["cat"] == "Bond"]),
    ("⚖️ Allocation Funds",   [f for f in FUND_CATALOG if f["cat"] == "Allocation"]),
    ("🛡️ Stable Value",       [f for f in FUND_CATALOG if f["cat"] == "Stable"]),
]

# Approximate expense ratios (fetched from Yahoo when available, fallback to these)
KNOWN_EXPENSE = {
    "GGRRT":0.60,"EDFMT":0.28,"BUFTT":0.05,"RRUST":0.04,"DOXGX":0.52,
    "EPSCT":0.68,"MIGFT":0.65,"NSRIX":0.55,"SSRLT":0.55,"JAQNT":0.52,
    "VGINT":0.02,"VGIET":0.03,"VGIST":0.04,"BACSF":0.00,
    "FJAMT":0.35,"SEIFT":0.46,"VIPIX":0.10,"VGITT":0.03,
    "BLIFT":0.82,"BRK2T":0.09,"BRK3T":0.09,"BRK4T":0.09,"BRK5T":0.09,
    "BRK6T":0.09,"BRK7T":0.09,"BRK8T":0.09,"BRK9T":0.09,"BRK0T":0.09,
    "BRK1T":0.09,"PAAIX":0.79,"MLSVF":0.00,
}

# Static top-10 holdings fallback (when yfinance doesn't return holdings)
STATIC_HOLDINGS = {
    "VOO":  [("Apple Inc","AAPL",7.1),("Microsoft","MSFT",6.5),("NVIDIA","NVDA",6.2),("Amazon","AMZN",3.8),("Alphabet A","GOOGL",2.2),("Meta Platforms","META",2.5),("Tesla","TSLA",1.8),("Berkshire B","BRK-B",1.6),("Broadcom","AVGO",2.3),("JPMorgan","JPM",1.4)],
    "IWF":  [("Apple Inc","AAPL",12.5),("Microsoft","MSFT",11.8),("NVIDIA","NVDA",10.4),("Amazon","AMZN",5.9),("Meta Platforms","META",4.1),("Alphabet A","GOOGL",3.5),("Tesla","TSLA",2.9),("Broadcom","AVGO",3.2),("Eli Lilly","LLY",2.0),("Costco","COST",1.4)],
    "IWM":  [("Sprouts Farmers","SFM",0.5),("Fabrinet","FN",0.4),("Applied Indust","AIT",0.4),("Hims & Hers","HIMS",0.4),("ITT Inc","ITT",0.4),("Clearfield","CLFD",0.3),("Chemed Corp","CHE",0.3),("Tenet Healthcare","THC",0.5),("Vistra Corp","VST",0.6),("Nu Holdings","NU",0.3)],
    "DVY":  [("Altria Group","MO",4.1),("AT&T","T",3.8),("Verizon","VZ",3.5),("Intl Paper","IP",3.1),("AbbVie","ABBV",2.6),("Phillip Morris","PM",2.5),("LyondellBasell","LYB",2.3),("Williams Cos","WMB",2.0),("Realty Income","O",1.9),("Kimberly-Clark","KMB",1.7)],
    "ACWX": [("TSMC","TSM",1.8),("Novo Nordisk","NVO",1.4),("Nestle SA","NSRGY",1.2),("ASML Holding","ASML",1.1),("Samsung Elec","",1.0),("Tencent Holdings","",0.9),("AstraZeneca","AZN",0.7),("Toyota Motor","TM",0.7),("LVMH","",0.6),("Shell plc","SHEL",0.6)],
    "EFG":  [("ASML Holding","ASML",3.2),("Novo Nordisk","NVO",2.8),("SAP SE","SAP",2.4),("LVMH","",1.9),("Ferrari NV","RACE",1.7),("Hermes Intl","",1.6),("Wolters Kluwer","",1.5),("Schneider Elec","",1.4),("Industria De Dis","IDEXY",1.3),("L'Oreal","",1.2)],
    "VXF":  [("Palantir","PLTR",0.9),("Super Micro","SMCI",1.2),("DoorDash","DASH",0.7),("Trade Desk","TTD",0.6),("Vistra Corp","VST",0.7),("MicroStrategy","MSTR",0.5),("Robinhood","HOOD",0.5),("Samsara","IOT",0.5),("Celsius Holding","CELH",0.4),("Spotify","SPOT",0.6)],
    "VXUS": [("TSMC","TSM",1.8),("Novo Nordisk","NVO",1.4),("Nestle SA","NSRGY",1.0),("ASML Holding","ASML",1.1),("Samsung Elec","",0.9),("Tencent","",0.9),("AstraZeneca","AZN",0.7),("LVMH","",0.6),("Roche","",0.6),("Shell plc","SHEL",0.6)],
    "DOXGX":[("Wells Fargo","WFC",5.2),("Microsoft","MSFT",5.0),("Charles Schwab","SCHW",4.6),("Bank of America","BAC",4.3),("Capital One","COF",3.9),("Charter Comms","CHTR",3.5),("FedEx Corp","FDX",3.2),("HP Inc","HPQ",3.0),("Comcast","CMCSA",2.9),("Meta Platforms","META",2.8)],
    "BND":  [("US Tsy 4.75% 2053","",1.5),("US Tsy 4.625% 2026","",1.2),("FNMA MBS 3%","",0.8),("FHLMC MBS","",0.6),("US Tsy 3.875%","",0.7),("US Tsy 4.5%","",0.5),("GNMA MBS","",0.4),("Corp Bond IG","",0.3),("Agency Securities","",0.3),("T-Bills","",0.2)],
    "FBNDX":[("US Tsy Bonds","",30.0),("Corp IG Bonds","",25.0),("FNMA MBS","",20.0),("Agency Bonds","",10.0),("Intl Developed","",5.0),("HY Bonds","",4.0),("TIPS","",3.0),("ABS","",2.0),("Cash","",1.0),("Other","",0.0)],
    "PTTRX":[("US Tsy 5Y-7Y","",12.0),("FNMA MBS","",10.0),("Corp IG","",9.0),("Intl Sov","",8.0),("T-Bills","",6.0),("Agency MBS","",5.0),("TIPS","",4.0),("HY Bonds","",3.0),("EM Debt","",2.0),("ABS","",1.0)],
    "VIPIX":[("US TIPS 0.875% 2029","",4.2),("US TIPS 0.125% 2031","",3.8),("US TIPS 0.625% 2032","",3.5),("US TIPS 1.625% 2027","",3.2),("US TIPS 0.25% 2028","",3.0),("US TIPS 0.5% 2028","",2.8),("US TIPS 2% 2026","",2.5),("US TIPS 0.375% 2027","",2.3),("US TIPS 1.75% 2028","",2.2),("US TIPS 2.5% 2029","",2.0)],
    "BAC":  [("Bank of America Corp","BAC",100.0)],
    "TRLGX":[("NVIDIA","NVDA",10.5),("Microsoft","MSFT",9.8),("Apple Inc","AAPL",8.2),("Amazon","AMZN",7.1),("Alphabet A","GOOGL",5.4),("Meta Platforms","META",4.8),("Tesla","TSLA",3.2),("Broadcom","AVGO",3.0),("Visa","V",2.4),("UnitedHealth","UNH",2.2)],
    "IJH":  [("Sprouts Farmers","SFM",0.5),("Tenet Healthcare","THC",0.5),("IDEX Corp","IEX",0.5),("Hubbell","HUBB",0.5),("Toll Brothers","TOL",0.4),("Curtiss-Wright","CW",0.4),("Morningstar","MORN",0.4),("WEX Inc","WEX",0.4),("Knight-Swift","KNX",0.4),("Fair Isaac","FICO",0.5)],
    "GNR":  [("BHP Group","BHP",4.5),("Rio Tinto","RIO",3.8),("ConocoPhillips","COP",3.5),("Shell plc","SHEL",3.2),("TotalEnergies","TTE",3.0),("Exxon Mobil","XOM",2.8),("Chevron","CVX",2.6),("Glencore","",2.4),("Vale SA","VALE",2.2),("Freeport-McMoRan","FCX",2.0)],
    "BIL":  [("T-Bill 1-3mo","",100.0)],
}

# Static sector weightings fallback
STATIC_SECTORS = {
    "VOO":  {"Technology":29.2,"Financials":13.5,"Healthcare":12.1,"Cons Discret":10.8,"Industrials":8.9,"Communication":8.8,"Energy":3.8,"Cons Staples":5.5,"Materials":2.3,"Real Estate":2.4,"Utilities":2.7},
    "IWF":  {"Technology":42.5,"Cons Discret":16.2,"Healthcare":9.1,"Financials":4.5,"Communication":12.3,"Industrials":6.8,"Cons Staples":3.1,"Energy":0.8,"Materials":1.2,"Real Estate":1.1,"Utilities":2.4},
    "IWM":  {"Financials":17.2,"Healthcare":15.8,"Industrials":14.7,"Technology":13.4,"Cons Discret":10.5,"Energy":5.9,"Real Estate":6.1,"Communication":3.2,"Materials":3.8,"Cons Staples":3.0,"Utilities":3.9},
    "DVY":  {"Financials":24.5,"Utilities":16.2,"Energy":14.8,"Real Estate":10.2,"Technology":8.3,"Communication":8.1,"Cons Staples":7.5,"Industrials":5.4,"Healthcare":3.0,"Materials":2.0,"Cons Discret":0.0},
    "ACWX": {"Technology":15.8,"Financials":17.2,"Industrials":12.4,"Healthcare":10.5,"Cons Discret":9.8,"Cons Staples":7.2,"Communication":6.8,"Energy":4.9,"Materials":4.8,"Real Estate":2.8,"Utilities":3.4},
    "EFG":  {"Technology":15.2,"Cons Discret":18.5,"Healthcare":12.8,"Industrials":14.2,"Communication":8.4,"Financials":10.1,"Cons Staples":9.2,"Materials":4.5,"Real Estate":2.8,"Energy":2.4,"Utilities":1.9},
    "VXF":  {"Technology":24.1,"Healthcare":16.3,"Industrials":14.8,"Financials":11.2,"Cons Discret":9.4,"Energy":3.8,"Real Estate":5.6,"Communication":4.2,"Materials":3.7,"Cons Staples":3.1,"Utilities":3.8},
    "VXUS": {"Technology":15.1,"Financials":18.2,"Industrials":12.8,"Healthcare":10.2,"Cons Discret":9.4,"Cons Staples":7.8,"Communication":6.2,"Energy":4.4,"Materials":5.8,"Real Estate":2.8,"Utilities":3.3},
    "DOXGX":{"Financials":26.5,"Communication":15.8,"Technology":12.4,"Healthcare":9.8,"Cons Discret":9.2,"Energy":7.5,"Industrials":8.4,"Cons Staples":4.8,"Materials":2.4,"Real Estate":1.6,"Utilities":1.6},
    "TRLGX":{"Technology":40.2,"Cons Discret":14.8,"Healthcare":11.2,"Communication":10.5,"Industrials":7.4,"Financials":5.8,"Cons Staples":3.2,"Materials":1.9,"Energy":1.5,"Real Estate":2.1,"Utilities":1.4},
    "BND":  {"Government":42.1,"Mortgage":20.3,"Corporate":25.8,"HY":0.5,"TIPS":4.2,"Agency":4.5,"Cash":2.6},
    "FBNDX":{"Government":30.0,"Mortgage":20.0,"Corporate":25.0,"Agency":10.0,"International":5.0,"HY":4.0,"TIPS":3.0,"Cash":3.0},
    "PTTRX":{"Government":25.0,"Mortgage":15.0,"Corporate":18.0,"International":20.0,"Cash":8.0,"HY":8.0,"TIPS":6.0},
    "VIPIX":{"TIPS":98.0,"Cash":2.0},
    "BAC":  {"Financials":100.0},
    "IJH":  {"Industrials":18.2,"Financials":16.8,"Healthcare":15.4,"Technology":12.9,"Cons Discret":11.5,"Real Estate":6.4,"Energy":4.8,"Materials":4.6,"Cons Staples":3.5,"Communication":3.0,"Utilities":2.9},
    "GNR":  {"Energy":47.2,"Materials":38.4,"Industrials":8.2,"Utilities":4.2,"Other":2.0},
    "BIL":  {"Cash/T-Bills":100.0},
    "MDLOX":{"Equity":55.0,"Bonds":37.0,"Cash":8.0},
}
# Target-date fund sectors (approximate equity/bond blend)
_td_sectors = {
    "VTHRX":{"Equity":54.0,"Bonds":40.0,"Intl Equity":16.0,"Cash":6.0},
    "VTTHX":{"Equity":59.0,"Bonds":35.0,"Intl Equity":18.0,"Cash":6.0},
    "VFORX":{"Equity":66.0,"Bonds":28.0,"Intl Equity":20.0,"Cash":6.0},
    "VTIVX":{"Equity":72.0,"Bonds":22.0,"Intl Equity":22.0,"Cash":6.0},
    "VFIFX":{"Equity":78.0,"Bonds":16.0,"Intl Equity":24.0,"Cash":6.0},
    "VFFVX":{"Equity":84.0,"Bonds":10.0,"Intl Equity":26.0,"Cash":6.0},
    "VTTSX":{"Equity":90.0,"Bonds":4.0,"Intl Equity":28.0,"Cash":6.0},
    "VLXVX":{"Equity":90.0,"Bonds":4.0,"Intl Equity":28.0,"Cash":6.0},
    "VTINX":{"Equity":30.0,"Bonds":60.0,"Intl Equity":9.0,"Cash":10.0},
}
STATIC_SECTORS.update(_td_sectors)


# ── Data fetching ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_hist(proxy: str) -> pd.DataFrame:
    """5-year daily price history via yfinance."""
    try:
        df = yf.download(proxy, period="5y", interval="1d", progress=False, auto_adjust=True)
        if df is None or df.empty:
            return pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_info(proxy: str) -> dict:
    """Fund metadata: expense ratio, category, description."""
    try:
        t = yf.Ticker(proxy)
        return t.info or {}
    except Exception:
        return {}


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_holdings_sectors(proxy: str) -> tuple:
    """Returns (holdings_list, sectors_dict) — tries yfinance funds_data first."""
    holdings, sectors = [], {}
    try:
        t = yf.Ticker(proxy)
        fd = getattr(t, "funds_data", None)
        if fd is not None:
            # Holdings
            th = getattr(fd, "top_holdings", None)
            if th is not None and not (isinstance(th, pd.DataFrame) and th.empty):
                if isinstance(th, pd.DataFrame):
                    for _, row in th.head(10).iterrows():
                        name = str(row.get("holdingName", row.get("Symbol", "")))
                        sym  = str(row.get("symbol", row.get("Symbol", "")))
                        pct  = float(row.get("holdingPercent", row.get("Percentage", 0)) or 0) * 100
                        holdings.append((name, sym, round(pct, 2)))
            # Sectors
            sw = getattr(fd, "sector_weightings", None)
            if sw is not None:
                raw = sw if isinstance(sw, dict) else (sw.to_dict() if hasattr(sw, "to_dict") else {})
                _KEY_MAP = {
                    "technology":"Technology","financial_services":"Financials",
                    "healthcare":"Healthcare","consumer_cyclical":"Cons Discret",
                    "industrials":"Industrials","communication_services":"Communication",
                    "consumer_defensive":"Cons Staples","energy":"Energy",
                    "basic_materials":"Materials","real_estate":"Real Estate",
                    "utilities":"Utilities","realestate":"Real Estate",
                }
                for k, v in raw.items():
                    label = _KEY_MAP.get(str(k).lower(), str(k).title())
                    sectors[label] = round(float(v or 0) * 100, 1)
    except Exception:
        pass

    if not holdings:
        holdings = STATIC_HOLDINGS.get(proxy, [])
    if not sectors:
        sectors = STATIC_SECTORS.get(proxy, {})
    return holdings, sectors


def _calc_returns(hist: pd.DataFrame) -> dict:
    """Returns {3M, 6M, 1Y, 3Y, 5Y} percentage returns from price history."""
    if hist.empty:
        return {}
    close = hist["Close"].dropna()
    if len(close) < 2:
        return {}
    now = float(close.iloc[-1])
    today = close.index[-1]
    out = {}
    for label, days in [("3M", 63), ("6M", 126), ("1Y", 252), ("3Y", 756), ("5Y", 1260)]:
        target = today - pd.Timedelta(days=days)
        subset = close[close.index <= target]
        if not subset.empty:
            past = float(subset.iloc[-1])
            out[label] = round((now / past - 1) * 100, 2)
    return out


def _portfolio_index(selected_symbols: list, allocations: dict) -> pd.DataFrame:
    """Build a normalized portfolio index (base=100) for the selected allocation."""
    frames = {}
    for sym in selected_symbols:
        f = FUND_BY_SYMBOL[sym]
        hist = _fetch_hist(f["proxy"])
        if hist.empty:
            continue
        close = hist["Close"].dropna()
        frames[sym] = close

    if not frames:
        return pd.DataFrame()

    df = pd.DataFrame(frames).dropna()
    if df.empty:
        return pd.DataFrame()

    # Normalize each to base 100 at first available date
    norm = df / df.iloc[0] * 100
    weights = np.array([allocations.get(s, 0) / 100 for s in norm.columns])
    port = (norm * weights).sum(axis=1)

    # Also include SPY benchmark
    spy_hist = _fetch_hist("SPY")
    if not spy_hist.empty:
        spy_close = spy_hist["Close"].dropna().reindex(df.index, method="ffill").dropna()
        common = port.index.intersection(spy_close.index)
        combined = pd.DataFrame({"Portfolio": port[common], "SPY Benchmark": spy_close[common] / spy_close[common].iloc[0] * 100})
    else:
        combined = pd.DataFrame({"Portfolio": port})

    return combined


# ── Chart helpers ─────────────────────────────────────────────────────────────

_GOLD = "#F5C842"
_BG   = "#0c1222"
_CARD = "#0f1929"
_MUTED= "#64748b"
_GREEN= "#22C55E"
_RED  = "#EF4444"

def _perf_chart(returns_dict: dict, fund_name: str, bench_returns: dict = None) -> go.Figure:
    """Grouped bar chart: fund performance vs SPY benchmark."""
    periods = ["3M", "6M", "1Y", "3Y", "5Y"]
    fund_vals = [returns_dict.get(p) for p in periods]
    bench_vals = [bench_returns.get(p) if bench_returns else None for p in periods]

    fig = go.Figure()
    colors = [(_GREEN if v and v >= 0 else _RED) if v is not None else _MUTED for v in fund_vals]
    fig.add_trace(go.Bar(
        name=fund_name[:25],
        x=[p for p, v in zip(periods, fund_vals) if v is not None],
        y=[v for v in fund_vals if v is not None],
        marker_color=[c for c, v in zip(colors, fund_vals) if v is not None],
        text=[f"{v:+.1f}%" for v in fund_vals if v is not None],
        textposition="outside",
    ))
    if bench_returns:
        bv = [bench_returns.get(p) for p in periods]
        fig.add_trace(go.Bar(
            name="SPY (S&P 500)",
            x=[p for p, v in zip(periods, bv) if v is not None],
            y=[v for v in bv if v is not None],
            marker_color="rgba(148,163,184,0.5)",
            text=[f"{v:+.1f}%" for v in bv if v is not None],
            textposition="outside",
        ))

    fig.update_layout(
        barmode="group", paper_bgcolor=_BG, plot_bgcolor=_BG,
        font=dict(color="#cbd5e1", family="Inter"),
        height=260, margin=dict(l=10,r=10,t=10,b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
        yaxis=dict(gridcolor="#1e293b", zeroline=True, zerolinecolor="#334155",
                   ticksuffix="%"),
        xaxis=dict(gridcolor="rgba(0,0,0,0)"),
    )
    return fig


def _sector_donut(sectors: dict, title: str) -> go.Figure:
    """Donut chart for sector/asset class breakdown."""
    labels = [k for k, v in sectors.items() if v > 0.5]
    vals   = [v for v in sectors.values() if v > 0.5]
    colors = px.colors.qualitative.Set3[:len(labels)]

    fig = go.Figure(go.Pie(
        labels=labels, values=vals, hole=0.5,
        marker=dict(colors=colors, line=dict(color=_BG, width=1)),
        textinfo="label+percent", textfont=dict(size=10),
        hovertemplate="%{label}: %{value:.1f}%<extra></extra>",
    ))
    fig.update_layout(
        paper_bgcolor=_BG, plot_bgcolor=_BG,
        font=dict(color="#cbd5e1", family="Inter"),
        height=240, margin=dict(l=5,r=5,t=30,b=5),
        title=dict(text=title, font=dict(size=12, color=_MUTED), x=0.5),
        showlegend=False,
    )
    return fig


def _alloc_pie(selected_symbols: list, allocations: dict) -> go.Figure:
    """Portfolio allocation pie chart."""
    labels = [FUND_BY_SYMBOL[s]["name"].replace(" Fund","").replace(" Trust","") for s in selected_symbols]
    vals   = [allocations.get(s, 0) for s in selected_symbols]
    colors = [_GOLD,"#3B82F6","#22C55E","#F97316","#A855F7","#EC4899","#06B6D4","#84CC16","#F59E0B","#6366F1"][:len(labels)]

    fig = go.Figure(go.Pie(
        labels=labels, values=vals, hole=0.4,
        marker=dict(colors=colors, line=dict(color=_BG, width=2)),
        textinfo="label+percent", textfont=dict(size=10),
        hovertemplate="%{label}: %{value}%<extra></extra>",
    ))
    fig.update_layout(
        paper_bgcolor=_BG, plot_bgcolor=_BG,
        font=dict(color="#cbd5e1", family="Inter"),
        height=260, margin=dict(l=5,r=5,t=10,b=5),
        showlegend=False,
    )
    return fig


def _growth_chart(portfolio_df: pd.DataFrame) -> go.Figure:
    """Growth of $10,000 line chart."""
    fig = go.Figure()
    for col in portfolio_df.columns:
        color = _GOLD if col == "Portfolio" else "#94a3b8"
        width = 2.5 if col == "Portfolio" else 1.5
        fig.add_trace(go.Scatter(
            x=portfolio_df.index, y=portfolio_df[col] / 100 * 10000,
            name=col, line=dict(color=color, width=width),
            hovertemplate="%{x|%b %Y}: $%{y:,.0f}<extra>" + col + "</extra>",
        ))
    fig.update_layout(
        paper_bgcolor=_BG, plot_bgcolor=_BG,
        font=dict(color="#cbd5e1", family="Inter"),
        height=280, margin=dict(l=10,r=10,t=10,b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
        yaxis=dict(gridcolor="#1e293b", tickprefix="$", tickformat=",.0f"),
        xaxis=dict(gridcolor="rgba(0,0,0,0)"),
        hovermode="x unified",
    )
    return fig


# ── Portfolio assessment ───────────────────────────────────────────────────────

def _assess_portfolio(selected_syms: list, allocations: dict) -> list:
    """Return list of (level, message) feedback items. level: good/warn/info."""
    msgs = []
    cats = [FUND_BY_SYMBOL[s]["cat"] for s in selected_syms]
    cat_counts = {c: cats.count(c) for c in set(cats)}

    # Diversification across asset classes
    n_eq  = sum(1 for s in selected_syms if FUND_BY_SYMBOL[s]["cat"] == "Equity")
    n_bd  = sum(1 for s in selected_syms if FUND_BY_SYMBOL[s]["cat"] == "Bond")
    n_al  = sum(1 for s in selected_syms if FUND_BY_SYMBOL[s]["cat"] == "Allocation")
    n_st  = sum(1 for s in selected_syms if FUND_BY_SYMBOL[s]["cat"] == "Stable")

    if n_eq > 0 and n_bd > 0:
        msgs.append(("good", "Balanced mix of equity and fixed income — good for managing volatility."))
    elif n_al > 0:
        msgs.append(("good", "Allocation/target-date fund covers both equity & bonds in a single fund."))
    elif n_eq > 0 and n_bd == 0 and n_al == 0:
        msgs.append(("warn", "Portfolio is 100% equity. No bond/stable buffer during market downturns."))

    # Expense ratio
    wtd_exp = sum(allocations.get(s, 0) / 100 * KNOWN_EXPENSE.get(s, 0.5) for s in selected_syms)
    if wtd_exp <= 0.10:
        msgs.append(("good", f"Excellent! Weighted expense ratio: {wtd_exp:.2f}% — well below the 0.50% category avg. Low costs compound into big gains over decades."))
    elif wtd_exp <= 0.30:
        msgs.append(("good", f"Reasonable weighted expense ratio: {wtd_exp:.2f}%. Slightly above Vanguard index level but acceptable."))
    else:
        msgs.append(("warn", f"Weighted expense ratio: {wtd_exp:.2f}%. Over 0.30% is a meaningful drag over 20+ year horizon. Consider shifting more weight to index funds (VGINT at 0.02%)."))

    # Company stock concentration
    bac_pct = allocations.get("BACSF", 0)
    if bac_pct > 10:
        msgs.append(("warn", f"BACSF (BAC company stock) is {bac_pct}% of portfolio. Single-stock concentration adds idiosyncratic risk — if BofA underperforms, your 401k suffers alongside your job income. Financial advisors typically cap company stock at 5-10%."))
    elif bac_pct > 0:
        msgs.append(("info", f"BAC Company Stock Fund ({bac_pct}%) gives upside if BofA performs well but adds concentration risk. Keep it under 10%."))

    # Overlap warning: two large-cap growth proxies
    lc_growth = [s for s in selected_syms if FUND_BY_SYMBOL[s]["sub"] in ("Large Cap Growth","S&P 500 Index")]
    if len(lc_growth) >= 2:
        names = " + ".join(FUND_BY_SYMBOL[s]["name"].split()[0] for s in lc_growth[:2])
        msgs.append(("warn", f"High overlap: {names} both focus on large-cap US equities. Combined holdings will heavily overlap (Apple, Microsoft, NVIDIA). Consider keeping only one."))

    # International exposure
    intl = [s for s in selected_syms if "Intl" in FUND_BY_SYMBOL[s]["sub"] or "International" in FUND_BY_SYMBOL[s]["sub"]]
    intl_pct = sum(allocations.get(s, 0) for s in intl)
    if len(selected_syms) > 1 and intl_pct == 0 and "Equity" in cats:
        msgs.append(("info", "No international exposure. Adding 10-20% in VGIST or GGRRT provides diversification outside the US market."))
    elif intl_pct > 0:
        msgs.append(("info", f"{intl_pct}% international exposure — adds geographic diversification and USD hedging benefits."))

    # Target date simplicity note
    td_funds = [s for s in selected_syms if s.startswith("BRK") and s != "BRK1T" or s == "BRK1T"]
    if len(td_funds) >= 2:
        msgs.append(("warn", "Multiple LifePath target-date funds selected. These are designed as all-in-one solutions — mixing two of the same type creates unnecessary complexity without added diversification."))

    # Stable value flag
    if n_st > 0 and n_eq > 0:
        msgs.append(("info", "Stable Value Fund is a capital preservation tool (think: high-yield savings). Pairing it with equity exposure is fine — it acts as a cash buffer."))

    return msgs


def _holdings_overlap_analysis(selected_syms: list) -> dict:
    """Find common holdings across selected funds. Returns overlap summary dict."""
    all_holdings = {}  # {sym: [(name, ticker, pct), ...]}
    for sym in selected_syms:
        f = FUND_BY_SYMBOL[sym]
        h, _ = _fetch_holdings_sectors(f["proxy"])
        if h:
            all_holdings[sym] = h

    if len(all_holdings) < 2:
        return {}

    # Find ticker symbols that appear in 2+ funds
    ticker_map = {}  # {ticker: [(fund_sym, name, pct), ...]}
    for fund_sym, holdings in all_holdings.items():
        for name, tick, pct in holdings:
            if tick and tick not in ("", "N/A"):
                if tick not in ticker_map:
                    ticker_map[tick] = []
                ticker_map[tick].append((fund_sym, name, pct))

    overlaps = {t: v for t, v in ticker_map.items() if len(v) >= 2}
    return overlaps


# ── Single fund panel ─────────────────────────────────────────────────────────

def _render_single_fund(sym: str):
    f = FUND_BY_SYMBOL[sym]
    proxy = f["proxy"]

    with st.spinner(f"Loading {f['name']}…"):
        hist    = _fetch_hist(proxy)
        info    = _fetch_info(proxy)
        holdings, sectors = _fetch_holdings_sectors(proxy)
        spy_ret = _calc_returns(_fetch_hist("SPY"))

    # Fund header card
    ret = _calc_returns(hist)
    one_yr = ret.get("1Y", None)
    perf_col = _GREEN if one_yr and one_yr > 0 else _RED if one_yr else _MUTED

    exp_pct = KNOWN_EXPENSE.get(sym, info.get("annualReportExpenseRatio", info.get("expenseRatio", None)))
    exp_str = f"{float(exp_pct)*100:.2f}%" if exp_pct and float(exp_pct) < 1 else (f"{float(exp_pct):.2f}%" if exp_pct else "N/A")
    # Handle if expense_ratio is already in pct form (e.g. 0.52 vs 0.0052)
    if exp_pct and float(exp_pct) > 1:
        exp_str = f"{float(exp_pct):.2f}%"
    elif exp_pct:
        exp_str = f"{float(exp_pct)*100:.2f}%" if float(exp_pct) < 0.2 else f"{float(exp_pct):.2f}%"

    proxy_note = f"(data via {proxy})" if f["is_cit"] else ""

    st.markdown(
        f'<div style="background:#0f1929;border:1px solid #1e293b;border-top:2px solid {_GOLD};'
        f'border-radius:10px;padding:16px 20px;margin-bottom:16px">'
        f'<div style="display:flex;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;gap:8px">'
        f'<div>'
        f'<div style="font-size:18px;font-weight:700;color:{_GOLD};margin-bottom:3px">{f["name"]}</div>'
        f'<div style="font-size:11px;color:{_MUTED}">{sym} · {f["sub"]} '
        f'<span style="background:#1e293b;padding:2px 8px;border-radius:10px;margin-left:4px">{f["cat"]}</span>'
        + ('<span style="color:#F97316;margin-left:8px;font-size:10px">CIT &mdash; proxy: ' + proxy + '</span>' if f["is_cit"] else "")
        + f'</div>'
        f'</div>'
        f'<div style="text-align:right">'
        f'<div style="font-size:24px;font-weight:700;color:{_GOLD};font-family:DM Mono,monospace">${f["price"]:.2f}</div>'
        f'<div style="font-size:10px;color:{_MUTED}">Fund NAV (as of last statement)</div>'
        f'</div></div>'
        f'<div style="display:flex;gap:24px;margin-top:14px;padding-top:12px;border-top:1px solid #1e293b">'
        f'<div><div style="font-size:9px;color:{_MUTED};text-transform:uppercase;letter-spacing:1px">Expense Ratio</div>'
        + f'<div style="font-size:16px;font-weight:700;color:{"#22C55E" if (exp_pct and float(exp_pct) < 0.20) else _GOLD}">{exp_str}</div></div>'
        f'<div><div style="font-size:9px;color:{_MUTED};text-transform:uppercase;letter-spacing:1px">1-Year Return</div>'
        f'<div style="font-size:16px;font-weight:700;color:{perf_col}">{f"{one_yr:+.1f}%" if one_yr else "N/A"}</div></div>'
        f'<div><div style="font-size:9px;color:{_MUTED};text-transform:uppercase;letter-spacing:1px">Category</div>'
        f'<div style="font-size:14px;font-weight:600;color:#cbd5e1">{f["sub"]}</div></div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    # Stable value special handling
    if f["cat"] == "Stable":
        st.info("🛡️ Stable Value funds provide principal protection with returns typically between 2–4% annually. They don't fluctuate in price. Performance chart uses BIL (T-Bill ETF) as a proxy for yield behavior.")

    # Performance chart
    if ret:
        st.markdown('<div style="font-size:12px;font-weight:600;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">Performance vs S&P 500</div>', unsafe_allow_html=True)
        st.plotly_chart(_perf_chart(ret, f["name"].split()[0], spy_ret), use_container_width=True, config={"displayModeBar": False})
    else:
        st.warning(f"Price history unavailable for proxy {proxy}.")

    # Holdings + Sectors side by side
    col_h, col_s = st.columns([1.2, 1])
    with col_h:
        st.markdown('<div style="font-size:12px;font-weight:600;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Top 10 Holdings</div>', unsafe_allow_html=True)
        if holdings:
            rows = ""
            for i, (name, tick, pct) in enumerate(holdings[:10]):
                bar_w = int(pct / max(h[2] for h in holdings[:10]) * 100) if holdings else 0
                tick_badge = f'<span style="background:#1e293b;color:#94a3b8;font-size:9px;padding:1px 6px;border-radius:8px;margin-left:4px">{tick}</span>' if tick else ""
                rows += (
                    f'<div style="margin-bottom:6px">'
                    f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:2px">'
                    f'<span style="font-size:11px;color:#cbd5e1">{name[:28]}{tick_badge}</span>'
                    f'<span style="font-size:11px;color:{_GOLD};font-family:DM Mono,monospace">{pct:.1f}%</span>'
                    f'</div>'
                    f'<div style="background:#1e293b;border-radius:3px;height:3px">'
                    f'<div style="background:{_GOLD};height:3px;border-radius:3px;width:{bar_w}%;opacity:0.7"></div></div>'
                    f'</div>'
                )
            src = f"<br><span style='font-size:9px;color:{_MUTED}'>Source: {proxy} (proxy data)</span>" if f["is_cit"] else ""
            st.markdown(f'<div style="background:#0f1929;border:1px solid #1e293b;border-radius:8px;padding:12px">{rows}{src}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div style="color:{_MUTED};font-size:12px;padding:10px">Holdings data unavailable.</div>', unsafe_allow_html=True)

    with col_s:
        if sectors:
            st.plotly_chart(_sector_donut(sectors, "Sector / Asset Mix"), use_container_width=True, config={"displayModeBar": False})


# ── Multi-fund panel ──────────────────────────────────────────────────────────

def _render_multi_fund(selected_syms: list, allocations: dict):
    total = sum(allocations.values())

    # Validate allocations
    if abs(total - 100) > 0.5:
        st.error(f"Allocations must sum to 100%. Current total: {total:.0f}%. Adjust the sliders below.")
        return

    # Header summary row
    st.markdown(
        f'<div style="background:#0f1929;border:1px solid #1e293b;border-top:2px solid {_GOLD};'
        f'border-radius:10px;padding:14px 20px;margin-bottom:16px">'
        f'<div style="font-size:16px;font-weight:700;color:{_GOLD};margin-bottom:8px">'
        f'Portfolio Analysis — {len(selected_syms)} Fund{"s" if len(selected_syms)>1 else ""}</div>'
        f'<div style="display:flex;flex-wrap:wrap;gap:8px">'
        + "".join(
            f'<span style="background:#1e293b;border:1px solid #334155;border-radius:6px;'
            f'padding:3px 10px;font-size:11px;color:#cbd5e1">'
            f'{FUND_BY_SYMBOL[s]["name"].split()[0]} '
            f'<span style="color:{_GOLD};font-weight:700">{allocations[s]:.0f}%</span></span>'
            for s in selected_syms
        )
        + f'</div></div>',
        unsafe_allow_html=True,
    )

    # Weighted expense ratio
    wtd_exp = sum(allocations.get(s, 0) / 100 * KNOWN_EXPENSE.get(s, 0.5) for s in selected_syms)

    # Performance for each fund + portfolio
    all_returns = {}
    spy_ret = _calc_returns(_fetch_hist("SPY"))
    for sym in selected_syms:
        f = FUND_BY_SYMBOL[sym]
        hist = _fetch_hist(f["proxy"])
        all_returns[sym] = _calc_returns(hist)

    # Weighted portfolio returns
    port_ret = {}
    for period in ["3M","6M","1Y","3Y","5Y"]:
        valid = [(allocations[s]/100, all_returns[s][period]) for s in selected_syms if period in all_returns.get(s,{})]
        if valid:
            total_w = sum(w for w, _ in valid)
            port_ret[period] = round(sum(w * r for w, r in valid) / total_w, 2)

    # Charts row 1: allocation pie + performance bar
    c1, c2 = st.columns([1, 1.8])
    with c1:
        st.markdown('<div style="font-size:11px;font-weight:600;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">Allocation</div>', unsafe_allow_html=True)
        st.plotly_chart(_alloc_pie(selected_syms, allocations), use_container_width=True, config={"displayModeBar": False})
        # Expense ratio metric below pie
        exp_color = _GREEN if wtd_exp <= 0.15 else (_GOLD if wtd_exp <= 0.40 else _RED)
        st.markdown(
            f'<div style="background:#0f1929;border:1px solid #1e293b;border-radius:8px;padding:10px 14px;text-align:center">'
            f'<div style="font-size:9px;color:{_MUTED};text-transform:uppercase;letter-spacing:1px">Weighted Expense Ratio</div>'
            f'<div style="font-size:22px;font-weight:700;color:{exp_color};font-family:DM Mono,monospace">{wtd_exp:.2f}%</div>'
            f'<div style="font-size:10px;color:{_MUTED}">Category avg: ~0.50%</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    with c2:
        st.markdown('<div style="font-size:11px;font-weight:600;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">Portfolio Returns vs S&P 500</div>', unsafe_allow_html=True)
        if port_ret:
            st.plotly_chart(_perf_chart(port_ret, "Your Portfolio", spy_ret), use_container_width=True, config={"displayModeBar": False})

    # Growth of $10,000
    st.markdown('<div style="font-size:11px;font-weight:600;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;margin:8px 0 4px">Growth of $10,000</div>', unsafe_allow_html=True)
    with st.spinner("Building portfolio chart…"):
        port_df = _portfolio_index(selected_syms, allocations)
    if not port_df.empty:
        st.plotly_chart(_growth_chart(port_df), use_container_width=True, config={"displayModeBar": False})

    # Sector overlap
    st.markdown('<div style="font-size:11px;font-weight:600;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;margin:12px 0 4px">Combined Sector Exposure</div>', unsafe_allow_html=True)
    combined_sectors: dict = {}
    for sym in selected_syms:
        f = FUND_BY_SYMBOL[sym]
        _, sectors = _fetch_holdings_sectors(f["proxy"])
        w = allocations.get(sym, 0) / 100
        for sec, pct in sectors.items():
            combined_sectors[sec] = combined_sectors.get(sec, 0) + pct * w
    if combined_sectors:
        # round and filter tiny positions
        combined_sectors = {k: round(v, 1) for k, v in combined_sectors.items() if v > 0.5}
        cs1, cs2 = st.columns([1, 1.5])
        with cs1:
            st.plotly_chart(_sector_donut(combined_sectors, "Portfolio Sector Mix"), use_container_width=True, config={"displayModeBar": False})
        with cs2:
            # Top 3 sector concentration text
            top3 = sorted(combined_sectors.items(), key=lambda x: x[1], reverse=True)[:5]
            rows = ""
            for sec, pct in top3:
                bar_w = int(pct / top3[0][1] * 100)
                rows += (
                    f'<div style="margin-bottom:7px">'
                    f'<div style="display:flex;justify-content:space-between;margin-bottom:2px">'
                    f'<span style="font-size:12px;color:#cbd5e1">{sec}</span>'
                    f'<span style="font-size:12px;color:{_GOLD};font-family:DM Mono,monospace">{pct:.1f}%</span>'
                    f'</div>'
                    f'<div style="background:#1e293b;border-radius:3px;height:5px">'
                    f'<div style="background:{_GOLD};height:5px;border-radius:3px;width:{bar_w}%"></div></div>'
                    f'</div>'
                )
            st.markdown(
                f'<div style="background:#0f1929;border:1px solid #1e293b;border-radius:8px;padding:14px">'
                f'<div style="font-size:11px;font-weight:600;color:#94a3b8;margin-bottom:10px">Top 5 Sectors</div>'
                f'{rows}</div>',
                unsafe_allow_html=True,
            )

    # Holdings overlap
    st.markdown('<div style="font-size:11px;font-weight:600;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;margin:12px 0 4px">Holdings Overlap</div>', unsafe_allow_html=True)
    with st.spinner("Checking holdings overlap…"):
        overlaps = _holdings_overlap_analysis(selected_syms)
    if overlaps:
        overlap_count = len(overlaps)
        overlap_color = _RED if overlap_count > 5 else (_GOLD if overlap_count > 2 else _GREEN)
        st.markdown(
            f'<div style="background:#0f1929;border:1px solid #1e293b;border-radius:8px;padding:12px 14px">'
            f'<div style="font-size:12px;color:{_MUTED};margin-bottom:8px">'
            f'<span style="color:{overlap_color};font-weight:700">{overlap_count} shared holding{"s" if overlap_count != 1 else ""}</span> appear in 2+ selected funds</div>'
            + "".join(
                f'<span style="display:inline-block;background:#1e293b;border:1px solid #334155;'
                f'border-radius:6px;padding:3px 8px;margin:2px;font-size:10px;color:#94a3b8">'
                f'{tick} <span style="color:{_GOLD}">{len(funds)}×</span></span>'
                for tick, funds in list(overlaps.items())[:20]
            )
            + f'</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(f'<div style="color:{_GREEN};font-size:12px;padding:8px">✓ No significant holdings overlap detected between selected funds.</div>', unsafe_allow_html=True)

    # Assessment / feedback
    st.markdown('<div style="font-size:11px;font-weight:600;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;margin:12px 0 4px">Portfolio Assessment</div>', unsafe_allow_html=True)
    msgs = _assess_portfolio(selected_syms, allocations)
    for level, msg in msgs:
        icon  = "✅" if level == "good" else "⚠️" if level == "warn" else "ℹ️"
        color = "#dcfce7" if level == "good" else "#fef3c7" if level == "warn" else "#dbeafe"
        bg    = "rgba(34,197,94,0.08)" if level == "good" else "rgba(251,191,36,0.08)" if level == "warn" else "rgba(59,130,246,0.08)"
        border= "rgba(34,197,94,0.25)" if level == "good" else "rgba(251,191,36,0.25)" if level == "warn" else "rgba(59,130,246,0.25)"
        st.markdown(
            f'<div style="background:{bg};border:1px solid {border};border-radius:8px;'
            f'padding:10px 14px;margin-bottom:6px;display:flex;gap:8px;align-items:flex-start">'
            f'<span style="font-size:14px">{icon}</span>'
            f'<span style="font-size:12px;color:{color};line-height:1.5">{msg}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # Per-fund performance comparison table
    with st.expander("📊 Per-Fund Performance Detail"):
        rows = []
        for sym in selected_syms:
            f = FUND_BY_SYMBOL[sym]
            r = all_returns.get(sym, {})
            rows.append({
                "Fund": f["name"][:30],
                "Alloc": f"{allocations[sym]:.0f}%",
                "Exp %": f"{KNOWN_EXPENSE.get(sym, 0):.2f}%",
                "3M": f'{r.get("3M"):+.1f}%' if r.get("3M") is not None else "—",
                "6M": f'{r.get("6M"):+.1f}%' if r.get("6M") is not None else "—",
                "1Y":  f'{r.get("1Y"):+.1f}%' if r.get("1Y") is not None else "—",
                "3Y":  f'{r.get("3Y"):+.1f}%' if r.get("3Y") is not None else "—",
                "5Y":  f'{r.get("5Y"):+.1f}%' if r.get("5Y") is not None else "—",
                "Proxy": f["proxy"] if f["is_cit"] else "—",
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)


# ── Main render ───────────────────────────────────────────────────────────────

def render():
    from config import GOLD, BG_CARD, BORDER_COLOR, TEXT_MUTED, TEXT_PRIMARY

    # Session state
    if "_401k_sel" not in st.session_state:
        st.session_state["_401k_sel"] = set()
    if "_401k_alloc" not in st.session_state:
        st.session_state["_401k_alloc"] = {}
    if "_401k_groups" not in st.session_state:
        st.session_state["_401k_groups"] = {g[0]: (i == 0) for i, g in enumerate(GROUPS)}

    # ── Top bar ───────────────────────────────────────────────────────────────
    h1, h2 = st.columns([5, 1])
    with h1:
        st.markdown(
            f'<div style="margin-bottom:4px">'
            f'<span style="font-family:Cormorant Garamond,serif;font-size:26px;'
            f'font-weight:700;color:{GOLD};letter-spacing:2px">💰 ML 401K Analyzer</span>'
            f'<span style="color:{TEXT_MUTED};font-size:11px;margin-left:12px">'
            f'BofA/Merrill Lynch Retirement Fund Analysis</span></div>',
            unsafe_allow_html=True,
        )
    with h2:
        if st.button("🔄 Refresh Prices", use_container_width=True, key="_401k_refresh"):
            _fetch_hist.clear()
            _fetch_info.clear()
            _fetch_holdings_sectors.clear()
            st.toast("Cache cleared — fetching fresh data!", icon="🔄")
            st.rerun()

    st.markdown(f'<div style="height:2px;background:linear-gradient(90deg,{GOLD}44,transparent);margin-bottom:14px"></div>', unsafe_allow_html=True)

    # ── CIT notice ────────────────────────────────────────────────────────────
    with st.expander("ℹ️ About Data Sources — Read First"):
        st.markdown(
            f"""Most ML 401k funds are **Collective Investment Trusts (CITs)** — private fund wrappers
not listed on public exchanges. Yahoo Finance cannot provide their direct price history.

**How this tool handles it:** Each CIT is mapped to the closest publicly-traded proxy ETF or mutual fund.
Performance, holdings, and sector data are from the proxy — directionally accurate but not exact.

| Type | Example | Data source |
|---|---|---|
| Standard mutual fund | DOXGX, VIPIX, PAAIX | Direct from Yahoo Finance |
| CIT (private trust) | VGINT, BUFTT, RRUST, BRK*T | Proxy ETF/MF (e.g. VGINT → VOO) |
| Stable Value | MLSVF | BIL (T-Bill ETF proxy) |

Fund closing prices shown are from your ML statement — not live data.""",
            unsafe_allow_html=True,
        )

    # ── Two-panel layout ──────────────────────────────────────────────────────
    left, right = st.columns([1, 2.2], gap="medium")

    selected = st.session_state["_401k_sel"]
    allocs   = st.session_state["_401k_alloc"]

    with left:
        st.markdown(
            f'<div style="font-size:11px;font-weight:700;color:{GOLD};text-transform:uppercase;'
            f'letter-spacing:1.5px;margin-bottom:8px">Select Funds</div>',
            unsafe_allow_html=True,
        )

        # Select/Clear all buttons
        b1, b2 = st.columns(2)
        with b1:
            if st.button("Clear All", use_container_width=True, key="_401k_clearall"):
                st.session_state["_401k_sel"]   = set()
                st.session_state["_401k_alloc"] = {}
                st.rerun()
        with b2:
            sel_count = len(selected)
            st.markdown(
                f'<div style="background:#1e293b;border-radius:6px;padding:5px 10px;'
                f'text-align:center;font-size:12px;color:{GOLD};font-weight:700">'
                f'{sel_count} selected</div>',
                unsafe_allow_html=True,
            )

        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

        for group_label, funds in GROUPS:
            is_open = st.session_state["_401k_groups"].get(group_label, False)
            chevron = "▾" if is_open else "▸"
            if st.button(f"{chevron} {group_label}", key=f"_401k_grp_{group_label}", use_container_width=True):
                st.session_state["_401k_groups"][group_label] = not is_open
                st.rerun()

            if is_open:
                for f in funds:
                    sym = f["symbol"]
                    is_sel = sym in selected
                    chk = st.checkbox(
                        f['name'],
                        value=is_sel,
                        key=f"_401k_chk_{sym}",
                        help=f"{sym} · {f['sub']} · Exp: {KNOWN_EXPENSE.get(sym, 0):.2f}% · ML price: ${f['price']}",
                    )
                    if chk and sym not in selected:
                        selected.add(sym)
                        # Default allocation: equal split
                        n = len(selected)
                        for s in selected:
                            allocs[s] = round(100 / n, 1)
                        st.session_state["_401k_sel"]   = selected
                        st.session_state["_401k_alloc"] = allocs
                        st.rerun()
                    elif not chk and sym in selected:
                        selected.discard(sym)
                        allocs.pop(sym, None)
                        if selected:
                            n = len(selected)
                            for s in selected:
                                allocs[s] = round(100 / n, 1)
                        st.session_state["_401k_sel"]   = selected
                        st.session_state["_401k_alloc"] = allocs
                        st.rerun()

            st.markdown("<div style='height:2px'></div>", unsafe_allow_html=True)

        # Allocation sliders (when 2+ selected)
        if len(selected) >= 2:
            st.markdown(
                f'<div style="height:1px;background:linear-gradient(90deg,{GOLD}33,transparent);margin:10px 0"></div>'
                f'<div style="font-size:11px;font-weight:700;color:{GOLD};text-transform:uppercase;'
                f'letter-spacing:1.5px;margin-bottom:8px">Allocation %</div>',
                unsafe_allow_html=True,
            )
            new_allocs = {}
            for sym in sorted(selected):
                f = FUND_BY_SYMBOL[sym]
                cur_val = allocs.get(sym, round(100 / len(selected), 1))
                new_val = st.number_input(
                    f"{f['name'].split()[0]} ({sym})",
                    min_value=0.0, max_value=100.0, value=float(cur_val),
                    step=5.0, key=f"_401k_alloc_{sym}",
                )
                new_allocs[sym] = new_val

            total = sum(new_allocs.values())
            color = _GREEN if abs(total - 100) < 0.5 else _RED
            st.markdown(
                f'<div style="text-align:right;font-size:12px;color:{color};'
                f'font-weight:700;padding:4px 0">Total: {total:.1f}%</div>',
                unsafe_allow_html=True,
            )
            st.session_state["_401k_alloc"] = new_allocs
            allocs = new_allocs

    # ── Right panel ───────────────────────────────────────────────────────────
    with right:
        if not selected:
            # Welcome screen
            st.markdown(
                f'<div style="background:#0f1929;border:1px solid #1e293b;border-radius:12px;'
                f'padding:48px 36px;text-align:center;margin-top:20px">'
                f'<div style="font-size:48px;margin-bottom:16px">💼</div>'
                f'<div style="font-family:Cormorant Garamond,serif;font-size:24px;color:{GOLD};'
                f'font-weight:700;margin-bottom:10px">ML 401K Fund Analyzer</div>'
                f'<div style="color:{TEXT_MUTED};font-size:13px;line-height:1.8;max-width:420px;margin:0 auto">'
                f'Select <strong style="color:#cbd5e1">one fund</strong> on the left to see performance, '
                f'top holdings, and sector breakdown.<br><br>'
                f'Select <strong style="color:#cbd5e1">two or more</strong> to compare, set allocation '
                f'percentages, and see overlap analysis, combined returns, and portfolio feedback.'
                f'</div></div>',
                unsafe_allow_html=True,
            )

        elif len(selected) == 1:
            sym = next(iter(selected))
            _render_single_fund(sym)

        else:
            total = sum(allocs.get(s, 0) for s in selected)
            if abs(total - 100) > 0.5:
                st.warning(f"⚠️ Allocations must sum to 100%. Current total: {total:.1f}%. Adjust in the left panel.")
            _render_multi_fund(list(selected), allocs)

    # Disclaimer
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:10px;text-align:center;margin-top:20px;'
        f'border-top:1px solid #1e293b;padding-top:10px">'
        f'⚠️ Not financial advice · Performance data uses publicly-traded proxy funds · '
        f'CIT fund data is approximated · Expense ratios are estimates · For informational use only</div>',
        unsafe_allow_html=True,
    )
