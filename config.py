# config.py — Golden Scanner Constants & Configuration

# ── Color Palette ──────────────────────────────────────────────
GOLD         = "#F5C842"
GOLD_DARK    = "#C9A227"
GOLD_LIGHT   = "#FFE07A"
BG_DARK      = "#0A0A0F"
BG_CARD      = "#111118"
BG_PANEL     = "#16161F"
ACCENT_BLUE  = "#3B82F6"
ACCENT_GREEN = "#22C55E"
ACCENT_RED   = "#EF4444"
TEXT_PRIMARY = "#F1F1F1"
TEXT_MUTED   = "#6B7280"
BORDER_COLOR = "#2A2A3A"

# ── Universe — Stocks + ETFs combined ─────────────────────────
# Positions 1–20:   Top mega-cap stocks
# Positions 21–55:  ALL liquid ETFs (OPTIONS_ETF_UNIVERSE + VTI/VOO)
#                   — always included even with small universe sizes
# Positions 56–215: Large-cap S&P 500 stocks
# Positions 216+:   Extended S&P 500 + remaining ETFs
SP500_SAMPLE = [
    # ── Mega-cap stocks (1–20) ────────────────────────────────
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","BRK-B","LLY","AVGO","TSLA",
    "UNH","JPM","XOM","V","MA","PG","JNJ","HD","COST","MRK",
    # ── Liquid ETFs with active options (21–55) ───────────────
    # Broad market & vol
    "SPY","QQQ","IWM","DIA","VTI","VOO","UVXY","VXX",
    # Commodities & bonds
    "GLD","SLV","TLT","HYG","LQD",
    # Sector SPDRs
    "XLK","XLF","XLE","XLV","XLI","XLU","XLP","XLY",
    # Tech & semi
    "SOXX","SMH","ARKK",
    # International & emerging
    "EEM","FXI","EWZ","KWEB",
    # Real assets & thematic
    "GDX","GDXJ","VNQ","IBB","USO","UNG",
    # ── Large-cap S&P 500 (56–215) ───────────────────────────
    "ABBV","CVX","CRM","BAC","PEP","ADBE","NFLX","TMO","ACN","WMT",
    "MCD","AMD","CSCO","ORCL","ABT","CAT","GS","TXN","INTU","QCOM",
    "MS","ISRG","AMAT","AMGN","BLK","MDT","SPGI","AXP","GILD","BKNG",
    "ADI","NOW","PLD","DUK","SO","NEE","SLB","CI","ELV","HUM",
    "DE","MMM","F","GM","INTC","GE","BA","RTX","LMT","HON",
    "ZTS","BSX","SYK","DHR","EW","REGN","VRTX","MRNA","PFE","BMY",
    "KO","MDLZ","STZ","MO","PM","EL","CL","KMB","GIS","HSY",
    "WFC","C","USB","PNC","TFC","COF","AIG","PRU","MET","AFL",
    "DIS","TMUS","VZ","T","CMCSA","CHTR","NWSA","RDDT","WBD","FOXA",
    "NKE","SBUX","LOW","TJX","ROST","DG","DLTR","ABNB","MAR","HLT",
    "KR","SYY","ADM","CHD","CLX","MNST","CHRW","COR","DPZ","YUM",
    "COP","OXY","PSX","MPC","VLO","EOG","KMI","WMB","OKE","VST",
    "SCHW","BX","KKR","AON","MMC","CB","TRV","ALL","PGR","MCO",
    "ICE","CME","NDAQ","BK","STT","NTRS","AMP","TROW","RJF","BEN",
    "MCK","CAH","CNC","IQV","A","ILMN","IDXX","VEEV","ZBH","HCA",
    # ── Extended S&P 500 stocks (201–330) ────────────────────
    "EMR","ETN","ITW","PH","ROK","FAST","GWW","URI","CMI","CARR",
    "OTIS","PCAR","GD","NOC","LHX","UNP","CSX","NSC","UPS","FDX",
    "ADP","PAYX","FIS","FI","IBM","PANW","FTNT","SNPS","CDNS","ADSK",
    "WDAY","PLTR","SNOW","CRWD","NET","DDOG","MDB","OKTA","ZS","TEAM",
    "ECL","SHW","LIN","APD","DD","DOW","NEM","FCX","NUE","ALB",
    "AMT","EQIX","CCI","PSA","AVB","EQR","WELL","VTR","O","DLR",
    "LULU","ETSY","RL","TPR","HAS","AZO","ORLY","TSCO","BBY","KMX",
    "DVN","FANG","APA","CEG","HAL","BKR","CTRA","SRE","ED","EIX",
    "MCHP","SWKS","KEYS","TER","MPWR","ZBRA","IT","CDW","VRSN","APP",
    "CTSH","AKAM","EFX","BR","UBER","APTV","BWA","GPC","LKQ","PAYC",
    "WAT","ALGN","RMD","DXCM","MTD","IEX","TFX","HOLX","BIO","VTRS",
    "UAL","LUV","ODFL","JBHT","IR","GNRC","TT","EXPD",
    "ZION","CFG","FITB","KEY","HBAN","RF","WRB","CINF","FAF","FHN",
    # ── Remaining ETFs ────────────────────────────────────────
    "VWO","AGG","BND","MUB","VCIT","VCSH",
    "ARKW","IYR","XRT","KRE","IAT","XLRE",
    # ── 3× Leveraged ETFs ────────────────────────────────────
    "TQQQ","SOXL","TECL","CURE","NAIL","UPRO","SPXL","TNA",
    "FNGU","LABU","FAS","UDOW","DPST","HIBL","NUGT","WEBL",
]

# ── MTPA Scanner universe — 200 curated tickers ───────────────
# Criteria: growth-oriented, volatile enough for momentum setups,
# quality companies you would not regret holding long-term.
# Excluded: airlines, tobacco, legacy telecoms, bond ETFs,
#   commodity futures ETFs, declining-AUM financials, regional banks.
MTPA_200 = [
    # ── Mega-cap (20) ────────────────────────────────────────────
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","BRK-B","LLY","AVGO","TSLA",
    "UNH","JPM","XOM","V","MA","PG","JNJ","HD","COST","MRK",
    # ── Core ETFs — growth & sector momentum (22) ────────────────
    "SPY","QQQ","IWM","DIA","VTI","VOO","GLD","SLV",
    "XLK","XLF","XLE","XLV","XLI","XLU","XLP","XLY",
    "SOXX","SMH","ARKK","IBB","GDX","VNQ",
    # ── Technology / Software / Cloud / Cyber / Semis (30) ───────
    "CRM","ADBE","AMD","ORCL","TXN","INTU","QCOM","AMAT","ADI","NOW",
    "PANW","CRWD","FTNT","NET","ZS","WDAY","SNOW","PLTR","DDOG","MDB",
    "CDNS","SNPS","ADSK","MCHP","MPWR","APP","ADP","FI","TEAM","UBER",
    # ── Healthcare / Biotech / MedTech (22) ──────────────────────
    "ABBV","TMO","ABT","ISRG","EW","REGN","VRTX","SYK","BSX","DHR",
    "ZTS","AMGN","GILD","DXCM","IDXX","IQV","VEEV","HCA","MDT","MRNA",
    "RMD","ALGN",
    # ── Financials / Fintech / Exchanges (18) ────────────────────
    "GS","MS","BAC","BX","KKR","SCHW","AXP","MCO","SPGI","ICE",
    "CME","WFC","COF","BLK","NDAQ","PGR","AON","MMC",
    # ── Consumer / Retail / Travel / Media (16) ──────────────────
    "MCD","NFLX","NKE","SBUX","BKNG","LOW","TJX","ROST","ABNB","MAR",
    "HLT","DIS","LULU","AZO","ORLY","WMT",
    # ── Industrials / Aerospace / Defense (18) ───────────────────
    "CAT","DE","HON","GE","BA","RTX","LMT","GD","NOC","ETN",
    "ITW","UNP","CSX","URI","FAST","SHW","TT","ODFL",
    # ── Energy / Clean Energy (10) ───────────────────────────────
    "CVX","COP","EOG","OXY","SLB","NEE","CEG","VST","FANG","HAL",
    # ── Real Estate / Infrastructure (8) ─────────────────────────
    "AMT","EQIX","CCI","PSA","WELL","O","DLR","PLD",
    # ── Consumer Brands / Staples / Services (8) ─────────────────
    "KO","PEP","MNST","YUM","DPZ","TSCO","ACN","TMUS",
    # ── More Tech / IT Services (12) ─────────────────────────────
    "CSCO","PAYC","EFX","KEYS","TER","IT","CDW","AKAM","PAYX","BR",
    "OKTA","VRSN",
    # ── Materials / Specialty Chemicals (6) ──────────────────────
    "LIN","ECL","FCX","NEM","ALB","APD",
    # ── More Healthcare / Life Sciences (5) ──────────────────────
    "A","ILMN","MTD","ELV","MCK",
    # ── More Industrials / Automation / Defense (5) ──────────────
    "PH","ROK","IR","GNRC","LHX",
    # ── 3× Leveraged & Single-Stock ETFs (12) ────────────────────
    "TQQQ","SOXL","TECL","NAIL","CURE","BULZ","WEBL","DPST",
    "UPRO","SPXL","3TSL","NVDL",
]

# ── India Top 150 — NSE tickers (.NS suffix) ──────────────────
# Criteria: Nifty 50 backbone + Nifty Next 50 quality names +
#           top growth/momentum stocks across all sectors.
# Excluded: illiquid small-caps, weak-data tickers, pure PSU plays.
# 150 chosen over 200 — NSE data on yfinance gets patchy past ~150 names.
INDIA_150 = [
    # ── Nifty 50 backbone (50) ────────────────────────────────────
    "RELIANCE.NS","TCS.NS","HDFCBANK.NS","INFY.NS","ICICIBANK.NS",
    "HINDUNILVR.NS","ITC.NS","SBIN.NS","BHARTIARTL.NS","KOTAKBANK.NS",
    "LT.NS","AXISBANK.NS","BAJFINANCE.NS","HCLTECH.NS","ASIANPAINT.NS",
    "MARUTI.NS","SUNPHARMA.NS","TITAN.NS","WIPRO.NS","ULTRACEMCO.NS",
    "POWERGRID.NS","NTPC.NS","NESTLEIND.NS","BAJAJFINSV.NS","ONGC.NS",
    "COALINDIA.NS","TATASTEEL.NS","TECHM.NS","CIPLA.NS","JSWSTEEL.NS",
    "INDUSINDBK.NS","BRITANNIA.NS","BPCL.NS","M&M.NS","TATACONSUM.NS",
    "EICHERMOT.NS","APOLLOHOSP.NS","HDFCLIFE.NS","SBILIFE.NS","ADANIPORTS.NS",
    "DIVISLAB.NS","TATAMOTORS.NS","GRASIM.NS","HINDALCO.NS","HEROMOTOCO.NS",
    "SHREECEM.NS","DRREDDY.NS","BAJAJ-AUTO.NS","ZOMATO.NS","TRENT.NS",
    # ── IT / Tech / Digital / Fintech (15) ───────────────────────
    "LTIM.NS","MPHASIS.NS","PERSISTENT.NS","COFORGE.NS","TATAELXSI.NS",
    "KPIT.NS","LTTS.NS","PAYTM.NS","NYKAA.NS","CDSL.NS",
    "BSE.NS","MCX.NS","ANGELONE.NS","MOTILALOFS.NS","DELHIVERY.NS",
    # ── Healthcare / Pharma / Diagnostics (15) ───────────────────
    "ZYDUSLIFE.NS","LUPIN.NS","AUROPHARMA.NS","TORNTPHARM.NS","ALKEM.NS",
    "MANKIND.NS","SYNGENE.NS","LALPATHLAB.NS","METROPOLIS.NS","FORTIS.NS",
    "MAXHEALTH.NS","IPCA.NS","GLENMARK.NS","PIIND.NS","ABBOTINDIA.NS",
    # ── Consumer / FMCG / Retail / Hospitality (15) ──────────────
    "MARICO.NS","DABUR.NS","GODREJCP.NS","COLPAL.NS","BERGEPAINT.NS",
    "PIDILITIND.NS","VARUNBEV.NS","JUBLFOOD.NS","BATAINDIA.NS","PAGEIND.NS",
    "IRCTC.NS","DMART.NS","NAUKRI.NS","INDIGO.NS","KAJARIACER.NS",
    # ── Industrials / Capital Goods / Power / Infra (20) ─────────
    "SIEMENS.NS","ABB.NS","HAL.NS","BEL.NS","BHEL.NS",
    "HAVELLS.NS","POLYCAB.NS","VOLTAS.NS","CROMPTON.NS","DIXON.NS",
    "CONCOR.NS","TATAPOWER.NS","ADANIENT.NS","ADANIGREEN.NS","NHPC.NS",
    "IRFC.NS","RECLTD.NS","PFC.NS","TORNTPOWER.NS","BHARATFORG.NS",
    # ── Additional Financials / NBFCs / Insurance (15) ───────────
    "BANKBARODA.NS","CANBK.NS","CHOLAFIN.NS","MUTHOOTFIN.NS","MANAPPURAM.NS",
    "ICICIGI.NS","HDFCAMC.NS","M&MFIN.NS","LICHSGFIN.NS","IDFCFIRSTB.NS",
    "ABCAPITAL.NS","BANDHANBNK.NS","FEDERALBNK.NS","SBICARD.NS","PNBHOUSING.NS",
    # ── Materials / Specialty Chemicals / Cement (10) ────────────
    "AMBUJACEM.NS","ACC.NS","ASTRAL.NS","SUPREMEIND.NS","AMBER.NS",
    "RAMCOCEM.NS","ATUL.NS","DEEPAKNTR.NS","BALKRISIND.NS","TATACHEMICALS.NS",
    # ── Real Estate / Auto Components (10) ───────────────────────
    "DLF.NS","LODHA.NS","OBEROIRLTY.NS","PHOENIXLTD.NS","PRESTIGE.NS",
    "GODREJPROP.NS","TVSMOTOR.NS","ESCORTS.NS","MOTHERSON.NS","TIINDIA.NS",
]

# NAV-4: Liquid ETFs with active options chains — merged into CSP/CC/LEAPS universe
OPTIONS_ETF_UNIVERSE = [
    "SPY","QQQ","IWM","DIA","GLD","SLV","TLT","HYG","LQD",
    "XLK","XLF","XLE","XLV","XLI","XLU","XLP","XLY",
    "GDX","GDXJ","EEM","EFA","ARKK","SOXX","SMH","VNQ","IBB",
    "FXI","EWZ","KWEB","USO","UNG","UVXY","VXX",
]

# ETF_UNIVERSE kept for backward compatibility with etf_scanner.py
ETF_UNIVERSE = [
    "SPY","QQQ","IWM","DIA","VTI","VOO","GLD","SLV","TLT","HYG",
    "XLK","XLF","XLE","XLV","XLI","XLU","XLP","XLY","XLB","XLRE",
    "EEM","EFA","VEA","VWO","AGG","BND","LQD","MUB","VCIT","VCSH",
    "ARKK","ARKW","ARKG","IYR","VNQ","JETS","XRT","KRE","IAT","SOXX",
]

ETF_3X_UNIVERSE = [
    "TQQQ","SOXL","UPRO","SPXL","TECL","FNGU","LABU","CURE","DFEN","ERX",
    "FAS","TNA","UDOW","URTY","WANT","NAIL","DPST","HIBL","MIDU","INDL",
    "SQQQ","SOXS","SPXS","TECS","FNGD","LABD","WEBS","FAZ","TZA","SDOW",
]

# ── Default Thresholds ─────────────────────────────────────────
MOMENTUM_DEFAULTS = {
    "rsi_min": 55, "rsi_max": 68,
    "vol_mult": 1.25, "price_min": 10, "price_max": 5000,
    "mcap_min": 1e9,
}

VALUE_DEFAULTS = {
    "pe_max": 25, "pb_max": 3.0,
    "roe_min": 12, "de_max": 1.0,
    "price_min": 5, "price_max": 5000,
}

GROWTH_DEFAULTS = {
    "rev_growth_min": 15, "eps_growth_min": 12,
    "rs_min": 1.02, "price_min": 10,
}

CSP_DEFAULTS = {
    "iv_rank_min": 25, "delta_min": 0.15, "delta_max": 0.30,
    "premium_pct_min": 0.70, "spread_pct_max": 5.0,
    "dte_min": 1, "dte_max": 20,
}

CC_DEFAULTS = {
    "delta_min": 0.15, "delta_max": 0.25,
    "premium_pct_min": 0.70,
    "dte_min": 1, "dte_max": 20,
}

LEAPS_DEFAULTS = {
    "dte_min": 300, "delta_min": 0.60, "delta_max": 0.75,
    "iv_rank_max": 40,
}

# ── Options Strike Targeting ───────────────────────────────────
OPTIONS_STRIKE_RANGES = {
    "CSP":   {"min_pct": 0.75, "max_pct": 0.98, "target_delta": 0.22,
              "fallback_pct": 0.91, "is_call": False,
              "delta_floor": 0.05, "delta_ceiling": 0.50},
    "CC":    {"min_pct": 1.01, "max_pct": 1.30, "target_delta": 0.20,
              "fallback_pct": 1.05, "is_call": True,
              "delta_floor": 0.05, "delta_ceiling": 0.50},
    "LEAPS": {"min_pct": 0.75, "max_pct": 0.99, "target_delta": 0.70,
              "fallback_pct": 0.88, "is_call": True,
              "delta_floor": 0.40, "delta_ceiling": 0.95},
}

ETF_DEFAULTS = {
    "rs_min": 1.02, "rsi_min": 50, "rsi_max": 70,
    "price_min": 5,
}

ETF3X_DEFAULTS = {
    "rsi_min": 55, "rsi_max": 70,
    "vol_mult": 1.25, "price_min": 5,
}

# ── Signal Score Weights ───────────────────────────────────────
SCORE_WEIGHTS = {
    "trend": 25,
    "momentum": 25,
    "volume": 20,
    "fundamentals": 15,
    "volatility": 15,
}

# ── UI Labels ──────────────────────────────────────────────────
SIGNAL_LABELS = {
    (80, 100): ("🔥 Strong Buy", ACCENT_GREEN),
    (60,  80): ("✅ Bullish",    "#86EFAC"),
    (40,  60): ("⚪ Neutral",    TEXT_MUTED),
    (20,  40): ("🔻 Bearish",   "#FCA5A5"),
    ( 0,  20): ("💀 Strong Sell", ACCENT_RED),
}

def get_signal_label(score: float):
    for (lo, hi), (label, color) in SIGNAL_LABELS.items():
        if lo <= score <= hi:
            return label, color
    return "⚪ Neutral", TEXT_MUTED
