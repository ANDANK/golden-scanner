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
    "GLD","SLV","TLT","HYG","LQD","USO","UNG",
    # Sector SPDRs
    "XLK","XLF","XLE","XLV","XLI","XLU","XLP","XLY",
    # Tech & semi
    "SOXX","SMH","ARKK",
    # International & emerging
    "EEM","FXI","EWZ","KWEB",
    # Real assets & thematic
    "GDX","GDXJ","VNQ","IBB",
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
    # ── Remaining ETFs (331–350) ──────────────────────────────
    "EEM","VWO","AGG","BND","LQD","MUB","VCIT","VCSH",
    "ARKW","IYR","VNQ","XRT","KRE","IAT","XLB","XLRE",
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
