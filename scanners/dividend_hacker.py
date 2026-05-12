# scanners/dividend_hacker.py — Dividend Hacker
# Upcoming ex-dividend events · Yield filtering · Payout details

import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime, timedelta, date
import pytz
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import *
from utils import section_header, empty_state, metric_card
from data_loader import YF_SESSION


DIVIDEND_UNIVERSE = [
    "AAPL","MSFT","JNJ","PG","KO","PEP","MCD","ABT","ABBV","MRK",
    "HD","LOW","COST","WMT","TGT","CL","KMB","GIS","HSY","SYY",
    "ADP","ROP","PH","DOV","ITW","EMR","CAT","DE","HON","MMM",
    "LMT","GD","RTX","NOC","UNP","CSX","NSC","WM","RSG","CTAS",
    "V","MA","SPGI","MCO","BLK","BEN","TROW","CME","ICE","CB",
    "AFL","PNR","SWK","SHW","LIN","ECL","APD","CHD","MKC","HRL",
    "BDX","MDT","BMY","AMGN","CVX","XOM","COP","OXY","SLB","HAL",
    "DUK","SO","NEE","AEP","XEL","D","ED","WEC","ATO","AWK",
    "O","WPC","NNN","FRT","ESS","AVB","PLD","ARE","VICI","IRM",
    "MO","PM","BTI","UVV","VZ","T","BNS","TD","CM","RY",
    "ENB","TRP","PBA","EPD","MPLX","ET","WMB","OKE","KMI","PAA",
    "MAIN","ARCC","BXSL","OBDC","GAIN","HTGC","PFE","VTRS","KHC",
    "KEY","HBAN","USB","RF","CFG","AMCR","KVUE",
    "ABM","CINF","SJM","NWN","TR","FUL","WBA","AWR","LANC","GPC",
    "EPR","ADC","STAG","SRC","GOOD","FR","REXR","TRNO","COLD","EGP",
    "BXP","KRC","HIW","EQR","MAA","CPT","UDR","INVH","AMH","ELS",
    "SUI","EQIX","DLR","AMT","CCI","SBAC","WELL","VTR","PEAK","DOC",
    "CMS","CNP","LNT","EVRG","NI","PNW","PEG","FE","SRE","AEE",
    "DTE","OGE","IDA","BKH","POR","HE","UGI","ETR","ES","EXC",
    "EOG","DVN","FANG","PXD","MPC","VLO","TRGP","PAGP","SUN","GLP",
    "DKL","USAC","HESM","AM","NFE","LPG",
    "SCHD","DGRO","VIG","NOBL","SDY","VYM","HDV","DGRW","FDVV","CGDV",
    "SPYD","DVY","FDL","PEY","DES","DTD","DLN","DHS","QDEF","VIGI",
    "SCHY","VYMI","DEM","IDV","DON","RDIV","LVHD","TDIV","FVD","XMLV",
    "JEPI","JEPQ","DIVO","SPYI","QQQI","QYLD","XYLD","RYLD","XYLG","QYLG",
    "SVOL","PDI","PTY","EOS","ETV","ETY","UTF","UTG","BST","BSTZ",
    "GPIX","GPIQ","XPAY","KNG","FEPI","AIPI","TSLY","NVDY","CONY","MSTY",
]

ETF_KEYWORDS = ["etf","fund","trust","index","shares","ishares","vanguard",
                "spdr","invesco","schwab","fidelity","wisdom","direxion","proshares",
                "global x","amplify","neos","roundhill","defiance","kurv"]


# ── Core fetcher — fixed ex-div date logic ─────────────────────

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_dividend_info(ticker: str) -> dict:
    try:
        t    = yf.Ticker(ticker, session=YF_SESSION)
        info = t.info or {}

        name       = info.get("shortName") or info.get("longName") or ticker
        sector     = info.get("sector")    or "N/A"
        mcap       = info.get("marketCap") or 0
        price      = info.get("currentPrice") or info.get("regularMarketPrice") or 0
        avg_vol    = info.get("averageVolume") or 0
        asset_type = info.get("quoteType", "").upper()
        div_rate   = info.get("dividendRate") or 0

        # ── Yield normalization ────────────────────────────────
        # yfinance returns dividendYield as decimal (0.035) OR percent (3.5)
        raw_yield = info.get("dividendYield") or 0
        if raw_yield > 1.0:
            div_yield = round(float(raw_yield), 2)   # already percent
        else:
            div_yield = round(float(raw_yield) * 100, 2)  # convert decimal
        if div_yield > 80:
            div_yield = 0.0  # sanity cap

        # 5yr avg yield — same normalization
        five_yr = float(info.get("fiveYearAvgDividendYield") or 0)
        if 0 < five_yr < 1.0:
            five_yr = round(five_yr * 100, 2)
        else:
            five_yr = round(five_yr, 2)

        # ── Frequency ─────────────────────────────────────────
        freq_raw   = info.get("dividendFrequency")
        freq_map   = {1: "Annual", 2: "Semi-Annual", 4: "Quarterly", 12: "Monthly"}
        freq_label = freq_map.get(freq_raw, "Quarterly")

        # ── Ex-div date: 3-source waterfall ───────────────────
        # BUG FIX: yfinance .info["exDividendDate"] is the LAST ex-div (past),
        # not the next one. We must try multiple sources and only accept FUTURE dates.
        today       = date.today()
        ex_div_date = None
        pay_date    = None

        # Source 1: t.calendar — most likely to have next upcoming date
        try:
            cal = t.calendar
            if cal is not None:
                # calendar can be dict or DataFrame depending on yfinance version
                if isinstance(cal, dict):
                    v = cal.get("Ex-Dividend Date")
                    if v and str(v) not in ("NaT", "nan", "None", ""):
                        candidate = pd.Timestamp(v).date()
                        if candidate >= today:
                            ex_div_date = candidate
                elif isinstance(cal, pd.DataFrame) and not cal.empty:
                    # Try index-based access
                    for key in ["Ex-Dividend Date", "exDividendDate"]:
                        if key in cal.index:
                            try:
                                v = cal.loc[key].iloc[0]
                                if pd.notna(v):
                                    candidate = pd.Timestamp(v).date()
                                    if candidate >= today:
                                        ex_div_date = candidate
                                        break
                            except Exception:
                                pass
                    # Try column-based access
                    if ex_div_date is None:
                        for key in ["Ex-Dividend Date", "exDividendDate"]:
                            if key in cal.columns:
                                try:
                                    v = cal[key].dropna().iloc[0]
                                    candidate = pd.Timestamp(v).date()
                                    if candidate >= today:
                                        ex_div_date = candidate
                                        break
                                except Exception:
                                    pass
        except Exception:
            pass

        # Source 2: info["exDividendDate"] unix timestamp — accept only if future
        if ex_div_date is None:
            raw = info.get("exDividendDate")
            if raw:
                try:
                    candidate = datetime.utcfromtimestamp(int(raw)).date()
                    if today <= candidate <= today + timedelta(days=120):
                        ex_div_date = candidate
                except Exception:
                    pass

        # Source 3: project from dividend history — always run if history available
        # (div_rate can be 0 on cloud when t.info is restricted, but dividends still accessible)
        if ex_div_date is None:
            try:
                divs = t.dividends
                if divs is not None and not divs.empty:
                    divs_pos = divs[divs > 0]
                    if not divs_pos.empty:
                        last_ts = divs_pos.index[-1]
                        last_d  = last_ts.date() if hasattr(last_ts, "date") else date.fromisoformat(str(last_ts)[:10])
                        # Infer frequency from gap between last payments
                        if len(divs_pos) >= 2:
                            gaps = [(divs_pos.index[i] - divs_pos.index[i-1]).days
                                    for i in range(1, min(len(divs_pos), 6))]
                            avg_gap = int(sum(gaps) / len(gaps))
                        else:
                            avg_gap = {"Annual":365,"Semi-Annual":182,"Quarterly":91,"Monthly":30}.get(freq_label, 91)
                        freq_days = max(25, min(avg_gap, 370))
                        projected = last_d + timedelta(days=freq_days)
                        # Advance until we find a future date
                        while projected < today:
                            projected += timedelta(days=freq_days)
                        ex_div_date = projected
            except Exception:
                pass

        # Payment date (usually ~3 weeks after ex-div)
        if ex_div_date:
            raw_pay = info.get("lastDividendDate")
            if raw_pay:
                try:
                    pd_cand = datetime.utcfromtimestamp(int(raw_pay)).date()
                    if pd_cand > ex_div_date:
                        pay_date = pd_cand
                except Exception:
                    pass
            # Estimate if not found
            if pay_date is None:
                pay_date = ex_div_date + timedelta(days=21)

        # ── Dividend history ───────────────────────────────────
        hist = []
        try:
            divs = t.dividends
            if divs is not None and not divs.empty:
                recent = divs[divs > 0].tail(12)
                hist   = [(str(d.date()), round(float(v), 4)) for d, v in recent.items()]
        except Exception:
            pass

        return {
            "ticker":      ticker,
            "name":        name,
            "sector":      sector,
            "asset_type":  asset_type,
            "mcap":        mcap,
            "price":       price,
            "avg_vol":     avg_vol,
            "div_rate":    div_rate,
            "div_yield":   div_yield,
            "ex_div":      ex_div_date,
            "pay_date":    pay_date,
            "frequency":   freq_label,
            "five_yr_avg": five_yr,
            "history":     hist,
        }
    except Exception:
        return {}


# ── Helpers ────────────────────────────────────────────────────

def is_etf(info: dict) -> bool:
    if info.get("asset_type") in ("ETF", "MUTUALFUND"):
        return True
    name = (info.get("name") or "").lower()
    return any(k in name for k in ETF_KEYWORDS)

def is_reit(info: dict) -> bool:
    sector = (info.get("sector") or "").lower()
    name   = (info.get("name")   or "").lower()
    return "real estate" in sector or "reit" in name

def mcap_bucket(mcap: float) -> str:
    if mcap >= 200e9: return "Mega Cap"
    if mcap >= 10e9:  return "Large Cap"
    if mcap >= 2e9:   return "Mid Cap"
    if mcap >= 300e6: return "Small Cap"
    return "Micro Cap"

def days_to_ex(ex_div: date) -> int:
    return (ex_div - date.today()).days

def mcap_str(mcap: float) -> str:
    if mcap >= 1e12: return f"${mcap/1e12:.1f}T"
    if mcap >= 1e9:  return f"${mcap/1e9:.1f}B"
    if mcap >= 1e6:  return f"${mcap/1e6:.0f}M"
    return "N/A"

def urgency_badge(days: int) -> str:
    if days <= 0:
        return f'<span style="background:#6B728033;color:{TEXT_MUTED};padding:2px 8px;border-radius:4px;font-size:11px">Passed</span>'
    if days <= 7:
        return f'<span style="background:{ACCENT_GREEN}22;color:{ACCENT_GREEN};border:1px solid {ACCENT_GREEN}55;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700">🟢 {days}d</span>'
    if days <= 14:
        return f'<span style="background:#FBBF2422;color:#FBBF24;border:1px solid #FBBF2455;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600">🟡 {days}d</span>'
    return f'<span style="background:{BORDER_COLOR}44;color:{TEXT_MUTED};border:1px solid {BORDER_COLOR};padding:2px 8px;border-radius:4px;font-size:11px">{days}d</span>'

def yield_badge(yld: float) -> str:
    color = ACCENT_GREEN if yld >= 4 else (GOLD if yld >= 2 else TEXT_MUTED)
    return f'<span style="color:{color};font-weight:700">{yld:.2f}%</span>'


# ── Scan ───────────────────────────────────────────────────────

def scan_dividends(tickers, date_from, date_to, yield_min, yield_max,
                   exclude_etf, exclude_reit, mcap_filter, sector_filter,
                   freq_filter, min_vol, sort_by):

    results  = []
    skipped  = {"no_exdiv":0,"past":0,"etf":0,"reit":0,"yield":0,"vol":0,"mcap":0,"sector":0,"freq":0}
    progress = st.progress(0)
    status   = st.empty()
    today    = date.today()

    for i, ticker in enumerate(tickers):
        progress.progress((i + 1) / len(tickers))
        status.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:12px">Fetching {ticker} ({i+1}/{len(tickers)})…</div>',
            unsafe_allow_html=True
        )
        info = fetch_dividend_info(ticker)
        if not info:
            skipped["no_exdiv"] += 1; continue

        ex_div = info.get("ex_div")
        if ex_div is None:
            skipped["no_exdiv"] += 1; continue
        if ex_div < today:
            skipped["past"] += 1; continue
        if not (date_from <= ex_div <= date_to):
            skipped["past"] += 1; continue

        if exclude_etf and is_etf(info):
            skipped["etf"] += 1; continue
        if exclude_reit and is_reit(info):
            skipped["reit"] += 1; continue

        yld = info["div_yield"]
        if yld <= 0 or not (yield_min <= yld <= yield_max):
            skipped["yield"] += 1; continue
        if min_vol > 0 and info["avg_vol"] < min_vol:
            skipped["vol"] += 1; continue
        if mcap_filter != "All" and mcap_bucket(info["mcap"]) != mcap_filter:
            skipped["mcap"] += 1; continue
        if sector_filter != "All" and info["sector"] != sector_filter:
            skipped["sector"] += 1; continue
        if freq_filter != "All" and info["frequency"] != freq_filter:
            skipped["freq"] += 1; continue

        days   = days_to_ex(ex_div)
        fdiv   = {"Annual":1,"Semi-Annual":2,"Quarterly":4,"Monthly":12}.get(info["frequency"], 4)
        payout = round(info["div_rate"] / fdiv, 4) if info["div_rate"] else 0
        hist   = info.get("history", [])
        consistency = min(100, len(hist) * 100 // 12) if hist else 0

        results.append({
            "_info":         info,
            "Ticker":        ticker,
            "Company":       (info["name"] or ticker)[:30],
            "Ex-Div Date":   str(ex_div),
            "Days to Ex":    days,
            "Div Amount":    payout,
            "Yield %":       yld,
            "5yr Avg Yield": info["five_yr_avg"],
            "Pay Date":      str(info["pay_date"]) if info["pay_date"] else "—",
            "Frequency":     info["frequency"],
            "Sector":        info["sector"],
            "Mkt Cap":       mcap_str(info["mcap"]),
            "Avg Vol":       f'{info["avg_vol"]:,.0f}',
            "Consistency":   consistency,
        })

    progress.empty()
    status.empty()

    # Diagnostics — helps user understand what was filtered
    total_skip = sum(skipped.values())
    if total_skip > 0:
        parts = []
        if skipped["no_exdiv"]: parts.append(f"{skipped['no_exdiv']} no ex-div data")
        if skipped["past"]:     parts.append(f"{skipped['past']} outside date window")
        if skipped["etf"]:      parts.append(f"{skipped['etf']} ETFs excluded")
        if skipped["reit"]:     parts.append(f"{skipped['reit']} REITs excluded")
        if skipped["yield"]:    parts.append(f"{skipped['yield']} yield out of range")
        if skipped["vol"]:      parts.append(f"{skipped['vol']} below min volume")
        if skipped["mcap"]:     parts.append(f"{skipped['mcap']} market cap mismatch")
        if skipped["sector"]:   parts.append(f"{skipped['sector']} sector mismatch")
        if skipped["freq"]:     parts.append(f"{skipped['freq']} frequency mismatch")
        st.caption(f"ℹ️ Filtered: {total_skip} tickers skipped — {' · '.join(parts)}")

    df = pd.DataFrame(results)
    if df.empty:
        return df

    if sort_by == "Largest Market Cap":
        df["_mcap_raw"] = df["_info"].apply(lambda x: x.get("mcap", 0))
        df = df.sort_values("_mcap_raw", ascending=False).drop("_mcap_raw", axis=1)
    elif sort_by == "Highest Yield":
        df = df.sort_values("Yield %", ascending=False)
    elif sort_by == "Most Consistent":
        df = df.sort_values("Consistency", ascending=False)
    else:
        df = df.sort_values("Days to Ex", ascending=True)

    return df.reset_index(drop=True)


# ── History chart ──────────────────────────────────────────────

def draw_history_chart(history, ticker):
    if not history:
        return None
    dates   = [h[0] for h in history]
    amounts = [h[1] for h in history]
    fig = go.Figure(go.Bar(
        x=dates, y=amounts,
        marker_color=[GOLD if i == len(amounts)-1 else ACCENT_BLUE for i in range(len(amounts))],
        text=[f"${a:.4f}" for a in amounts],
        textposition="outside",
        textfont=dict(color=TEXT_MUTED, size=10),
    ))
    fig.update_layout(
        paper_bgcolor=BG_CARD, plot_bgcolor=BG_PANEL,
        font_color=TEXT_PRIMARY, height=220,
        margin=dict(l=10, r=10, t=30, b=50),
        title=dict(text=f"{ticker} — Dividend History", font=dict(color=GOLD, size=13)),
        xaxis=dict(gridcolor=BORDER_COLOR, tickangle=-45, tickfont=dict(size=9)),
        yaxis=dict(gridcolor=BORDER_COLOR, tickprefix="$"),
        showlegend=False,
    )
    return fig


# ── Results table ──────────────────────────────────────────────

def render_dividend_table(df: pd.DataFrame):
    display_cols = ["Ticker","Company","Ex-Div Date","Days to Ex","Div Amount",
                    "Yield %","5yr Avg Yield","Pay Date","Frequency","Sector",
                    "Mkt Cap","Consistency"]
    cols = [c for c in display_cols if c in df.columns]

    header_cells = "".join(
        f'<th style="background:{BG_PANEL};color:{GOLD};font-size:10px;font-weight:600;'
        f'text-transform:uppercase;letter-spacing:0.8px;padding:10px 12px;'
        f'border-bottom:2px solid {GOLD}44;white-space:nowrap;text-align:left">{c}</th>'
        for c in cols
    )
    row_htmls = []
    for i, (_, row) in enumerate(df.iterrows()):
        bg = BG_CARD if i % 2 == 0 else BG_PANEL
        cells = []
        for col in cols:
            val = row[col]
            if col == "Ticker":
                content = f'<span style="color:{GOLD};font-family:\'DM Mono\',monospace;font-weight:700;font-size:13px">{val}</span>'
            elif col == "Company":
                content = f'<span style="color:{TEXT_PRIMARY};font-size:12px">{val}</span>'
            elif col == "Days to Ex":
                content = urgency_badge(int(val))
            elif col == "Yield %":
                content = yield_badge(float(val))
            elif col == "5yr Avg Yield":
                fval = float(val) if val else 0
                color = ACCENT_GREEN if fval >= 3 else (TEXT_MUTED if fval == 0 else TEXT_PRIMARY)
                content = f'<span style="color:{color};font-size:12px">{fval:.2f}%</span>'
            elif col == "Div Amount":
                content = f'<span style="color:{ACCENT_GREEN};font-family:\'DM Mono\',monospace;font-size:12px">${float(val):.4f}</span>'
            elif col == "Consistency":
                pct = int(val)
                bc  = ACCENT_GREEN if pct >= 80 else (GOLD if pct >= 50 else ACCENT_RED)
                content = (
                    f'<div style="display:flex;align-items:center;gap:6px">'
                    f'<div style="flex:1;background:#1a1a2a;border-radius:3px;height:5px;min-width:50px">'
                    f'<div style="background:{bc};height:5px;border-radius:3px;width:{pct}%"></div></div>'
                    f'<span style="color:{bc};font-size:11px;font-weight:700">{pct}%</span></div>'
                )
            elif col == "Frequency":
                fc = {"Monthly":ACCENT_GREEN,"Quarterly":ACCENT_BLUE,
                      "Semi-Annual":GOLD,"Annual":TEXT_MUTED}.get(str(val), TEXT_MUTED)
                content = f'<span style="color:{fc};font-size:12px">{val}</span>'
            elif col == "Ex-Div Date":
                content = f'<span style="color:{TEXT_PRIMARY};font-family:\'DM Mono\',monospace;font-size:12px">{val}</span>'
            else:
                content = f'<span style="color:{TEXT_MUTED};font-size:12px">{val}</span>'

            cells.append(
                f'<td style="padding:9px 12px;vertical-align:middle;'
                f'border-bottom:1px solid {BORDER_COLOR}22;background:{bg}">{content}</td>'
            )
        row_htmls.append(f'<tr>{"".join(cells)}</tr>')

    st.markdown(f"""
    <div style="overflow-x:auto;border:1px solid {BORDER_COLOR};border-radius:8px;margin-top:8px">
      <table style="width:100%;border-collapse:collapse;font-family:'Inter',sans-serif">
        <thead><tr>{header_cells}</tr></thead>
        <tbody>{"".join(row_htmls)}</tbody>
      </table>
    </div>""", unsafe_allow_html=True)


# ── Detail drawer ──────────────────────────────────────────────

def render_detail_drawer(row: pd.Series):
    info    = row["_info"]
    ticker  = row["Ticker"]
    ex_div  = row["Ex-Div Date"]
    days    = int(row["Days to Ex"])
    yld     = float(row["Yield %"])
    history = info.get("history", [])

    with st.expander(
        f"📋 {ticker} — {(info.get('name') or '')[:35]}  ·  Ex-Div: {ex_div}  ·  Yield: {yld:.2f}%",
        expanded=False
    ):
        c1, c2, c3, c4 = st.columns(4)
        with c1: metric_card("Stock Price",    f"${info.get('price',0):.2f}", color=GOLD)
        with c2: metric_card("Div Yield",      f"{yld:.2f}%",                 color=ACCENT_GREEN)
        with c3: metric_card("Annual Div $",   f"${info.get('div_rate',0):.2f}", color=ACCENT_BLUE)
        with c4: metric_card("Days to Ex-Div", f"{days}d",
                             color=ACCENT_GREEN if days <= 7 else GOLD)

        st.markdown("<br>", unsafe_allow_html=True)
        lc, rc = st.columns(2)

        with lc:
            st.markdown(f"""
            <div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:8px;padding:16px">
                <div style="color:{GOLD};font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px">📅 Dividend Event</div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
                    <div style="color:{TEXT_MUTED};font-size:12px">Ex-Dividend Date</div>
                    <div style="color:{ACCENT_GREEN};font-family:'DM Mono',monospace;font-size:12px;font-weight:600">{ex_div}</div>
                    <div style="color:{TEXT_MUTED};font-size:12px">Payment Date</div>
                    <div style="color:{TEXT_PRIMARY};font-family:'DM Mono',monospace;font-size:12px">{info.get('pay_date') or '—'}</div>
                    <div style="color:{TEXT_MUTED};font-size:12px">Frequency</div>
                    <div style="color:{ACCENT_BLUE};font-size:12px">{info.get('frequency','—')}</div>
                    <div style="color:{TEXT_MUTED};font-size:12px">5yr Avg Yield</div>
                    <div style="color:{TEXT_PRIMARY};font-size:12px">{info.get('five_yr_avg',0):.2f}%</div>
                    <div style="color:{TEXT_MUTED};font-size:12px">Sector</div>
                    <div style="color:{TEXT_PRIMARY};font-size:12px">{info.get('sector','N/A')}</div>
                    <div style="color:{TEXT_MUTED};font-size:12px">Market Cap</div>
                    <div style="color:{TEXT_PRIMARY};font-size:12px">{mcap_str(info.get('mcap',0))}</div>
                </div>
            </div>
            <div style="background:{BG_PANEL};border:1px solid {GOLD}33;border-left:3px solid {GOLD};
                        border-radius:6px;padding:12px 14px;margin-top:10px;
                        color:{TEXT_MUTED};font-size:12px;line-height:1.7">
                <b style="color:{GOLD}">📌 Ex-Div Cutoff:</b><br>
                Own shares by <b style="color:{TEXT_PRIMARY}">close of business the day before {ex_div}</b>
                to qualify for this dividend. Buying on or after ex-div date means
                <b style="color:{ACCENT_RED}">no payout</b>. Stock typically drops by ~dividend amount on ex-div day.
            </div>""", unsafe_allow_html=True)

        with rc:
            if history:
                fig = draw_history_chart(history, ticker)
                if fig:
                    st.plotly_chart(fig, use_container_width=True)
                amounts = [h[1] for h in history]
                if len(amounts) >= 2:
                    trend = ("📈 Growing" if amounts[-1] > amounts[0]
                             else ("📉 Declining" if amounts[-1] < amounts[0] else "➡️ Stable"))
                    avg_p = sum(amounts) / len(amounts)
                    st.markdown(f"""
                    <div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:6px;padding:12px;margin-top:8px">
                        <div style="color:{GOLD};font-size:11px;font-weight:600;text-transform:uppercase;margin-bottom:8px">Payout Analysis</div>
                        <div style="display:flex;justify-content:space-between;margin-bottom:4px">
                            <span style="color:{TEXT_MUTED};font-size:12px">Trend</span>
                            <span style="color:{TEXT_PRIMARY};font-size:12px">{trend}</span>
                        </div>
                        <div style="display:flex;justify-content:space-between;margin-bottom:4px">
                            <span style="color:{TEXT_MUTED};font-size:12px">Avg Payout</span>
                            <span style="color:{ACCENT_GREEN};font-family:'DM Mono',monospace;font-size:12px">${avg_p:.4f}</span>
                        </div>
                        <div style="display:flex;justify-content:space-between">
                            <span style="color:{TEXT_MUTED};font-size:12px">Payments on record</span>
                            <span style="color:{TEXT_PRIMARY};font-size:12px">{len(history)}</span>
                        </div>
                    </div>""", unsafe_allow_html=True)
            else:
                st.markdown(f'<div style="color:{TEXT_MUTED};font-size:13px;padding:20px;text-align:center">No dividend history available.</div>', unsafe_allow_html=True)


# ── Main render ────────────────────────────────────────────────

def render():
    section_header("💵", "Dividend Hacker",
                   "Upcoming ex-dividend events · Yield filtering · Payout details · Consistency scoring")

    today = date.today()

    with st.sidebar:
        st.markdown(f'<div style="color:{GOLD};font-size:12px;font-weight:600;margin:16px 0 8px">📅 Date Range</div>', unsafe_allow_html=True)
        weeks_ahead = st.slider("Ex-Div window (weeks)", 1, 12, 2)
        date_to = today + timedelta(weeks=weeks_ahead)

        st.markdown(f'<div style="color:{GOLD};font-size:12px;font-weight:600;margin:12px 0 8px">💰 Dividend Yield</div>', unsafe_allow_html=True)
        yield_min, yield_max = st.slider("Yield range (%)", 0.0, 20.0, (1.0, 20.0), 0.5)

        st.markdown(f'<div style="color:{GOLD};font-size:12px;font-weight:600;margin:12px 0 8px">🔧 Filters</div>', unsafe_allow_html=True)
        exclude_etf  = st.checkbox("Exclude ETFs & Funds", value=False)
        exclude_reit = st.checkbox("Exclude REITs",         value=False)
        mcap_filter   = st.selectbox("Market Cap",  ["All","Mega Cap","Large Cap","Mid Cap","Small Cap"])
        freq_filter   = st.selectbox("Frequency",   ["All","Monthly","Quarterly","Semi-Annual","Annual"])
        sector_filter = st.selectbox("Sector", [
            "All","Technology","Healthcare","Financials","Energy","Utilities",
            "Consumer Staples","Consumer Discretionary","Industrials",
            "Materials","Real Estate","Communication Services"
        ])
        min_vol_m = st.slider("Min Avg Volume (M)", 0.0, 5.0, 0.1, 0.1)
        min_vol   = int(min_vol_m * 1_000_000)
        sort_by   = st.selectbox("Sort By", [
            "Soonest Ex-Div","Highest Yield","Largest Market Cap","Most Consistent"
        ])
        universe_size = st.slider("Universe size", 20, len(DIVIDEND_UNIVERSE),
                                  min(80, len(DIVIDEND_UNIVERSE)), 10)

    tickers = DIVIDEND_UNIVERSE[:universe_size]

    st.markdown(f"""
    <div style="display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap;align-items:center">
        <span style="background:{ACCENT_GREEN}22;color:{ACCENT_GREEN};border:1px solid {ACCENT_GREEN}55;
              padding:2px 10px;border-radius:4px;font-size:11px;font-weight:700">🟢 ≤7d — Act fast</span>
        <span style="background:#FBBF2422;color:#FBBF24;border:1px solid #FBBF2455;
              padding:2px 10px;border-radius:4px;font-size:11px">🟡 ≤14d — Plan ahead</span>
        <span style="background:{BORDER_COLOR}44;color:{TEXT_MUTED};border:1px solid {BORDER_COLOR};
              padding:2px 10px;border-radius:4px;font-size:11px">&gt;14d — Watching</span>
        <span style="color:{TEXT_MUTED};font-size:11px;margin-left:auto">
            Window: <b style="color:{TEXT_PRIMARY}">{today.strftime('%b %d')} → {date_to.strftime('%b %d, %Y')}</b>
            &nbsp;·&nbsp; {len(tickers)} tickers
        </span>
    </div>""", unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 1, 4])
    with col1:
        run = st.button("▶ Run Scan", use_container_width=True)
    with col2:
        if st.button("🔄 Clear Cache", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    if run:
        df = scan_dividends(
            tickers, today, date_to,
            yield_min, yield_max,
            exclude_etf, exclude_reit,
            mcap_filter, sector_filter,
            freq_filter, min_vol, sort_by
        )

        if df.empty:
            st.warning(
                f"No upcoming dividends found in the next **{weeks_ahead} weeks**.\n\n"
                f"**Try:** lower yield minimum · widen date window · "
                f"uncheck ETF/REIT exclusions · reduce min volume · increase universe size"
            )
            return

        urgent  = (df["Days to Ex"] <= 7).sum()
        soon    = ((df["Days to Ex"] > 7) & (df["Days to Ex"] <= 14)).sum()
        avg_yld = df["Yield %"].mean()
        monthly = (df["Frequency"] == "Monthly").sum()

        c1, c2, c3, c4, c5 = st.columns(5)
        with c1: metric_card("Found",             str(len(df)),       color=GOLD)
        with c2: metric_card("🟢 Within 7 Days",  str(urgent),        color=ACCENT_GREEN)
        with c3: metric_card("🟡 Within 14 Days", str(soon),          color="#FBBF24")
        with c4: metric_card("Avg Yield",          f"{avg_yld:.2f}%", color=ACCENT_BLUE)
        with c5: metric_card("Monthly Payers",     str(monthly),      color=GOLD)

        st.markdown("<br>", unsafe_allow_html=True)

        if len(df) >= 3:
            with st.expander("📊 Yield Distribution", expanded=False):
                bins   = [0,1,2,3,4,5,6,8,10,20]
                labels = ["0-1%","1-2%","2-3%","3-4%","4-5%","5-6%","6-8%","8-10%","10%+"]
                counts = [((df["Yield %"] >= bins[j]) & (df["Yield %"] < bins[j+1])).sum()
                          for j in range(len(bins)-1)]
                fig = go.Figure(go.Bar(
                    x=labels, y=counts,
                    marker_color=[GOLD if c == max(counts) else ACCENT_BLUE for c in counts],
                    text=counts, textposition="outside",
                ))
                fig.update_layout(
                    paper_bgcolor=BG_CARD, plot_bgcolor=BG_PANEL,
                    font_color=TEXT_PRIMARY, height=200,
                    margin=dict(l=10,r=10,t=10,b=10),
                    xaxis=dict(gridcolor=BORDER_COLOR),
                    yaxis=dict(gridcolor=BORDER_COLOR),
                    showlegend=False,
                )
                st.plotly_chart(fig, use_container_width=True)

        export_df = df.drop(columns=["_info"], errors="ignore")
        col_a, col_b = st.columns([4, 1])
        with col_a:
            st.markdown(
                f'<div style="color:{TEXT_MUTED};font-size:13px;padding:6px 0">'
                f'Found <b style="color:{GOLD}">{len(df)}</b> upcoming dividend events</div>',
                unsafe_allow_html=True
            )
        with col_b:
            st.download_button("⬇ Export CSV", export_df.to_csv(index=False),
                               f"dividend_hacker_{today}.csv", "text/csv", use_container_width=True)

        render_dividend_table(df)

        # Per-row Track / Watch strip
        from utils import render_tracker_widget, _extract_price
        tickers = df["Ticker"].dropna().tolist() if "Ticker" in df.columns else []
        prices  = {str(r["Ticker"]): _extract_price(r) for _, r in df.iterrows() if pd.notna(r.get("Ticker"))}
        render_tracker_widget(tickers, strategy="Dividend", source="Upcoming Dividends", prices=prices)

        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:12px;margin:20px 0 8px">'
            f'▼ Expand any ticker for dividend history, payout trend, and event details</div>',
            unsafe_allow_html=True
        )
        for _, row in df.iterrows():
            render_detail_drawer(row)

    else:
        st.markdown(f"""
        <div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:8px;
                    padding:36px;text-align:center;color:{TEXT_MUTED}">
            <div style="font-size:42px;margin-bottom:14px">💵</div>
            <div style="font-size:18px;color:{TEXT_PRIMARY};margin-bottom:10px;
                        font-family:'Cormorant Garamond',serif">Dividend Hacker</div>
            <div style="font-size:13px;max-width:500px;margin:0 auto;line-height:1.8">
                Scans <b style="color:{TEXT_PRIMARY}">{len(tickers)} tickers</b> for upcoming
                ex-dividend events in the next <b style="color:{TEXT_PRIMARY}">{weeks_ahead} weeks</b>.<br>
                Yield: <b style="color:{TEXT_PRIMARY}">{yield_min}%–{yield_max}%</b>
                &nbsp;·&nbsp; Sort: <b style="color:{TEXT_PRIMARY}">{sort_by}</b>
            </div>
            <div style="margin-top:16px;display:flex;justify-content:center;gap:20px;flex-wrap:wrap">
                <span style="color:{ACCENT_GREEN};font-size:13px">🟢 ≤7d — own shares now</span>
                <span style="color:#FBBF24;font-size:13px">🟡 ≤14d — plan entry</span>
                <span style="color:{TEXT_MUTED};font-size:13px">⚪ &gt;14d — watching</span>
            </div>
        </div>
        <div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:8px;
                    padding:20px 24px;margin-top:16px">
            <div style="color:{GOLD};font-size:12px;font-weight:600;text-transform:uppercase;
                        letter-spacing:1px;margin-bottom:12px">📌 How to use Dividend Hacker</div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
                <div>
                    <div style="color:{TEXT_PRIMARY};font-size:13px;font-weight:600;margin-bottom:4px">1. Set your window</div>
                    <div style="color:{TEXT_MUTED};font-size:12px;line-height:1.6">Drag the week slider to scan 1–12 weeks ahead. 8 weeks is a solid default for planning entries.</div>
                </div>
                <div>
                    <div style="color:{TEXT_PRIMARY};font-size:13px;font-weight:600;margin-bottom:4px">2. Set yield range</div>
                    <div style="color:{TEXT_MUTED};font-size:12px;line-height:1.6">Default 1%–20% catches everything. Raise minimum to 3%+ for meaningful income focus.</div>
                </div>
                <div>
                    <div style="color:{TEXT_PRIMARY};font-size:13px;font-weight:600;margin-bottom:4px">3. Check urgency badges</div>
                    <div style="color:{TEXT_MUTED};font-size:12px;line-height:1.6">🟢 = must own by close the day before ex-div. Stock drops ~dividend amount on ex-div day.</div>
                </div>
                <div>
                    <div style="color:{TEXT_PRIMARY};font-size:13px;font-weight:600;margin-bottom:4px">4. Expand for details</div>
                    <div style="color:{TEXT_MUTED};font-size:12px;line-height:1.6">Click any ticker row after scanning to see history chart, payout trend, and event timeline.</div>
                </div>
            </div>
        </div>""", unsafe_allow_html=True)
