# scanners/social_trends.py — Social Media & News Trends

import streamlit as st
import requests
import xml.etree.ElementTree as ET
import re
import html as html_lib
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from collections import Counter
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import *
from utils import calc_rsi, calc_sma
from data_loader import get_price_history

# ── Sentiment word sets ──────────────────────────────────────────

BULL_WORDS = {
    'buy','bull','bullish','breakout','surge','surges','rally','rallies',
    'moon','calls','upside','beats','beat','strong','growth','bounce',
    'oversold','support','accumulate','long','upgrade','outperform',
    'record','gains','positive','optimistic','higher','momentum',
    'demand','bottom','recovery','rebound',
}
BEAR_WORDS = {
    'sell','bear','bearish','crash','drop','drops','fall','falls',
    'puts','downside','miss','misses','weak','dump','short',
    'resistance','overbought','warning','risk','caution','concern',
    'downgrade','underperform','decline','loss','negative',
    'lower','tariff','layoffs','bankruptcy','headwinds','recession',
    'selloff','correction',
}
FINANCE_KW = {
    'stock','stocks','share','shares','market','earnings','revenue',
    'quarter','fed','federal reserve','interest rate','inflation',
    'nasdaq','s&p','dow','etf','options','calls','puts','strike',
    'crypto','bitcoin','ethereum','ipo','merger','acquisition',
    'buyback','dividend','analyst','upgrade','downgrade','price target',
    'sector','rally','selloff','bull','bear','trade','trading',
    'hedge','portfolio','yield','bond','treasury','macro',
}

# ── Feed sources ─────────────────────────────────────────────────

NEWS_FEEDS = [
    ("Yahoo Finance",  "https://finance.yahoo.com/news/rssindex"),
    ("CNBC Markets",   "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"),
    ("Reuters Biz",    "https://feeds.reuters.com/reuters/businessNews"),
    ("Investopedia",   "https://www.investopedia.com/feedbuilder/feed/getfeed?feedName=rss_headline"),
    ("MarketWatch",    "https://feeds.content.dowjones.io/public/rss/mw_bulletins"),
    ("Benzinga",       "https://www.benzinga.com/feed/"),
]

SUBREDDITS = [
    "stocks", "investing", "options", "StockMarket",
    "SecurityAnalysis", "wallstreetbets",
]

YT_CHANNELS = [
    "Meet Kevin", "InTheMoney", "Joseph Carlson",
    "Ticker Symbol YOU", "Options with Davis", "Andrei Jikh",
    "Invest with Henry", "Graham Stephan", "Charlie Chang",
]

TICKER_RE   = re.compile(r'\$([A-Z]{1,5})\b')
WORD_RE     = re.compile(r'\b[A-Z]{2,5}\b')
KNOWN_TICKERS = {
    'SPY','QQQ','AAPL','MSFT','NVDA','TSLA','AMZN','META','GOOGL','GOOG',
    'AMD','INTC','ARM','SMCI','MU','AVGO','TSM','SOXX','SOXL','TQQQ',
    'JPM','BAC','GS','MS','XLF','V','MA','BRK',
    'XOM','CVX','OXY','USO','XLE',
    'GLD','SLV','TLT','HYG','IWM',
    'BTC','ETH','COIN','MSTR','IBIT',
    'NFLX','DIS','UBER','ABNB','BKNG',
    'PFE','JNJ','LLY','ABBV','UNH','XLV',
    'PLTR','RKLB','RIVN','NIO',
}
NOISE_WORDS = {
    'THE','AND','FOR','ARE','BUT','NOT','YOU','ALL','CAN','WAS','ONE','OUR',
    'OUT','GET','HAS','HIM','HIS','HOW','ITS','WHO','DID','NOW','OWN','SAY',
    'SHE','TWO','WAY','MAY','NEW','USE','TOP','CEO','CFO','ETF','FED','IPO',
    'GDP','SEC','USA','USD','EUR','IMF','ESG','CNBC','NYSE','RSS',
}

NEWS_HEADERS = {"User-Agent": "GoldenScanner/1.0 (financial-research-tool)"}
REDDIT_JSON_HEADERS = {
    "User-Agent": "GoldenScanner:v1.0 (financial market research; +https://github.com/ANDANK/golden-scanner)",
    "Accept": "application/json",
}
REDDIT_RSS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


# ── Helpers ──────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    return html_lib.unescape(re.sub(r'<[^>]+>', '', text)).strip()


def _extract_tickers(text: str) -> list:
    found = set(TICKER_RE.findall(text.upper()))
    found |= (set(WORD_RE.findall(text.upper())) & KNOWN_TICKERS)
    return sorted(found - NOISE_WORDS)[:6]


def _score_sentiment(text: str) -> tuple:
    words = set(re.findall(r'\b\w+\b', text.lower()))
    bull = len(words & BULL_WORDS)
    bear = len(words & BEAR_WORDS)
    if bull == 0 and bear == 0:
        return "Neutral", 0.3
    if bull > bear * 1.3:
        return "Bullish", 1.0
    if bear > bull * 1.3:
        return "Bearish", 1.0
    return "Neutral", 0.4


def _time_ago(dt: datetime) -> str:
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = max(0, (now - dt).total_seconds())
    if secs < 3600:   return f"{int(secs/60)}m ago"
    if secs < 86400:  return f"{int(secs/3600)}h ago"
    return f"{int(secs/86400)}d ago"


def _recency_w(dt: datetime) -> float:
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    h = (now - dt).total_seconds() / 3600
    if h < 6:   return 1.0
    if h < 24:  return 0.75
    return 0.5


def _is_finance(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in FINANCE_KW)


def _compute_score(recency: float, engagement: int, max_eng: int,
                   tickers: list, clarity: float) -> int:
    eng_w  = min(1.0, engagement / max(max_eng, 1))
    tick_w = 1.0 if tickers else 0.3
    return int(recency * 30 + eng_w * 30 + tick_w * 20 + clarity * 20)


def _parse_dt(s: str) -> datetime:
    for fn in (
        parsedate_to_datetime,
        lambda x: datetime.fromisoformat(x.replace("Z", "+00:00")),
    ):
        try:
            return fn(s)
        except Exception:
            pass
    return datetime.now(timezone.utc)


# ── Technical snapshot ───────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def _tech(ticker: str) -> dict:
    try:
        df = get_price_history(ticker, period="3mo")
        if df is None or df.empty or len(df) < 20:
            return {}
        close = df["Close"].squeeze()
        price = float(close.iloc[-1])
        chg   = (price - float(close.iloc[-2])) / float(close.iloc[-2]) * 100
        rsi   = round(calc_rsi(close), 1)
        sma50 = float(calc_sma(close, 50).iloc[-1]) if len(close) >= 50 else price
        trend = "&#8593; Up" if price > sma50 else "&#8595; Down"
        vol_sig = ""
        if "Volume" in df.columns:
            vol = df["Volume"].squeeze()
            avg = float(vol.iloc[-21:-1].mean()) if len(vol) > 21 else float(vol.mean())
            vr  = float(vol.iloc[-1]) / avg if avg > 0 else 1.0
            vol_sig = "&#128293; Spike" if vr >= 2.0 else ("Above Avg" if vr >= 1.2 else "Below Avg")
        chg_col = ACCENT_GREEN if chg >= 0 else ACCENT_RED
        rsi_col = ACCENT_GREEN if 50 <= rsi <= 68 else (ACCENT_RED if rsi > 75 else TEXT_MUTED)
        return {
            "price": price, "chg": chg, "chg_col": chg_col,
            "rsi": rsi, "rsi_col": rsi_col, "trend": trend, "vol": vol_sig,
        }
    except Exception:
        return {}


def _tech_row_html(tickers: list) -> str:
    if not tickers:
        return ""
    snap = _tech(tickers[0])
    if not snap:
        return ""
    ticker = tickers[0]
    sign   = "+" if snap["chg"] >= 0 else ""
    dot    = f'<span style="color:{BORDER_COLOR}"> &#183; </span>'
    parts  = [
        f'<span style="color:{GOLD};font-weight:700;font-family:\'DM Mono\',monospace">${ticker}</span>',
        f'<span style="color:{snap["chg_col"]}">${snap["price"]:.2f} ({sign}{snap["chg"]:.2f}%)</span>',
        f'<span style="color:{TEXT_MUTED}">RSI <span style="color:{snap["rsi_col"]}">{snap["rsi"]}</span></span>',
        f'<span style="color:{TEXT_MUTED}">{snap["trend"]}</span>',
    ]
    if snap["vol"]:
        parts.append(f'<span style="color:{TEXT_MUTED}">{snap["vol"]}</span>')
    return (
        f'<div style="background:{BG_DARK};border-radius:4px;padding:6px 10px;'
        f'margin-top:8px;font-size:11px;display:flex;flex-wrap:wrap;gap:8px">'
        f'{dot.join(parts)}</div>'
    )


# ── Reddit fetchers (JSON + RSS fallback) ─────────────────────────

def _reddit_json(sub: str) -> list:
    try:
        url  = f"https://www.reddit.com/r/{sub}/hot.json?limit=25&raw_json=1"
        resp = requests.get(url, headers=REDDIT_JSON_HEADERS, timeout=10)
        if resp.status_code != 200:
            return []
        posts = resp.json().get("data", {}).get("children", [])
        items = []
        for p in posts:
            d        = p.get("data", {})
            title    = d.get("title", "")
            selftext = _strip_html(d.get("selftext", ""))[:300]
            ups      = int(d.get("ups", 0))
            comments = int(d.get("num_comments", 0))
            flair    = d.get("link_flair_text") or ""
            created  = d.get("created_utc", time.time())
            plink    = d.get("permalink", "")
            dt = datetime.fromtimestamp(created, tz=timezone.utc)
            if ups < 50 and comments < 25:
                continue
            text = title + " " + selftext
            if not _is_finance(text):
                continue
            if any(kw in title.lower() for kw in ['loss porn', 'gain porn', '🌈🐻']) and ups < 5000:
                continue
            tickers   = _extract_tickers(text)
            sentiment, clarity = _score_sentiment(text)
            is_dd = any(kw in flair.lower() for kw in ['dd', 'due diligence', 'analysis', 'research'])
            items.append({
                "source": f"r/{sub}", "title": title, "desc": selftext,
                "link": f"https://reddit.com{plink}",
                "dt": dt, "time_ago": _time_ago(dt),
                "tickers": tickers, "sentiment": sentiment,
                "clarity": clarity, "recency": _recency_w(dt),
                "engagement": ups + comments * 3,
                "ups": ups, "comments": comments,
                "flair": flair, "is_dd": is_dd, "type": "reddit",
            })
        return items
    except Exception:
        return []


def _reddit_rss(sub: str) -> list:
    """RSS fallback — no vote counts but more reliably accessible."""
    try:
        url  = f"https://www.reddit.com/r/{sub}/hot/.rss?limit=25"
        resp = requests.get(url, headers=REDDIT_RSS_HEADERS, timeout=10)
        if resp.status_code != 200:
            return []
        ns   = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(resp.content)
        items = []
        for entry in root.findall("atom:entry", ns):
            title   = _strip_html(entry.findtext("atom:title", "", ns))
            link_el = entry.find("atom:link", ns)
            link    = link_el.get("href", "") if link_el is not None else ""
            updated = entry.findtext("atom:updated", "", ns)
            content = _strip_html(entry.findtext("atom:content", "", ns))[:300]
            dt = _parse_dt(updated)
            if not title:
                continue
            text = title + " " + content
            if not _is_finance(text):
                continue
            tickers   = _extract_tickers(text)
            sentiment, clarity = _score_sentiment(text)
            items.append({
                "source": f"r/{sub}", "title": title, "desc": content,
                "link": link, "dt": dt, "time_ago": _time_ago(dt),
                "tickers": tickers, "sentiment": sentiment,
                "clarity": clarity, "recency": _recency_w(dt),
                "engagement": 100,  # neutral default (no count from RSS)
                "ups": 0, "comments": 0,
                "flair": "", "is_dd": False, "type": "reddit",
            })
        return items
    except Exception:
        return []


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_reddit() -> list:
    items  = []
    errors = 0
    for i, sub in enumerate(SUBREDDITS):
        if i > 0:
            time.sleep(0.5)           # gentle rate-limit
        result = _reddit_json(sub)
        if not result:
            result = _reddit_rss(sub)  # fallback to RSS
        if result:
            items.extend(result)
        else:
            errors += 1

    if not items:
        return []

    max_eng = max((it["engagement"] for it in items), default=1)
    for it in items:
        it["score"] = _compute_score(
            it["recency"], it["engagement"], max_eng, it["tickers"], it["clarity"]
        )
        if it.get("is_dd") and it["ups"] >= 200:
            it["score"] = min(100, it["score"] + 15)

    # Deduplicate by title prefix
    seen, deduped = set(), []
    for it in sorted(items, key=lambda x: -x["score"]):
        key = it["title"][:60].lower()
        if key not in seen:
            seen.add(key)
            deduped.append(it)

    return deduped[:30]


# ── News fetcher ──────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def _fetch_news() -> list:
    items = []
    for src_name, url in NEWS_FEEDS:
        try:
            resp = requests.get(url, headers=NEWS_HEADERS, timeout=8)
            if resp.status_code != 200:
                continue
            root    = ET.fromstring(resp.content)
            channel = root.find("channel") or root
            for item in list(channel.iter("item"))[:12]:
                title = _strip_html(item.findtext("title") or "")
                desc  = _strip_html(item.findtext("description") or "")[:220]
                link  = (item.findtext("link") or "").strip()
                pub   = item.findtext("pubDate") or ""
                dt    = _parse_dt(pub)
                text  = title + " " + desc
                if not title or not _is_finance(text):
                    continue
                tickers   = _extract_tickers(text)
                sentiment, clarity = _score_sentiment(text)
                items.append({
                    "source": src_name, "title": title, "desc": desc,
                    "link": link, "dt": dt, "time_ago": _time_ago(dt),
                    "tickers": tickers, "sentiment": sentiment,
                    "clarity": clarity, "recency": _recency_w(dt),
                    "engagement": 0, "type": "news",
                    "ups": 0, "comments": 0,
                })
        except Exception:
            continue

    seen, deduped = set(), []
    for it in sorted(items, key=lambda x: -x["recency"]):
        key = (tuple(it["tickers"]), it["title"][:50].lower())
        if key not in seen:
            seen.add(key)
            deduped.append(it)

    max_eng = 1
    for it in deduped:
        it["score"] = _compute_score(it["recency"], 0, max_eng, it["tickers"], it["clarity"])
    deduped.sort(key=lambda x: -x["score"])
    return deduped[:20]


# ── Card rendering ────────────────────────────────────────────────

def _sent_badge(sentiment: str) -> str:
    cfg = {
        "Bullish": (ACCENT_GREEN, "&#128994; Bullish"),
        "Bearish": (ACCENT_RED,   "&#128308; Bearish"),
        "Neutral": (TEXT_MUTED,   "&#9898; Neutral"),
    }
    color, label = cfg.get(sentiment, (TEXT_MUTED, "&#9898; Neutral"))
    return (f'<span style="background:{color}22;color:{color};border:1px solid {color}55;'
            f'padding:2px 7px;border-radius:4px;font-size:10px;font-weight:700">{label}</span>')


def _score_badge(score: int) -> str:
    color = ACCENT_GREEN if score >= 70 else (GOLD if score >= 50 else TEXT_MUTED)
    return (f'<span style="background:{color}22;color:{color};border:1px solid {color}44;'
            f'padding:2px 8px;border-radius:4px;font-size:10px;font-weight:700">&#9889; {score}/100</span>')


def _source_badge(source: str) -> str:
    return (f'<span style="background:{BG_DARK};color:{TEXT_MUTED};border:1px solid {BORDER_COLOR};'
            f'padding:2px 7px;border-radius:4px;font-size:10px">{source}</span>')


def _ticker_tags(tickers: list) -> str:
    if not tickers:
        return ""
    tags = "".join(
        f'<span style="background:{GOLD}18;color:{GOLD};border:1px solid {GOLD}44;'
        f'padding:1px 7px;border-radius:3px;font-size:11px;font-weight:700;'
        f'font-family:\'DM Mono\',monospace">${t}</span>'
        for t in tickers
    )
    return f'<div style="display:flex;flex-wrap:wrap;gap:5px;margin:6px 0">{tags}</div>'


def _card(item: dict, show_engagement: bool = False):
    sentiment  = item.get("sentiment", "Neutral")
    left_color = {"Bullish": ACCENT_GREEN, "Bearish": ACCENT_RED}.get(sentiment, BORDER_COLOR)
    title      = item["title"][:120] + ("…" if len(item["title"]) > 120 else "")
    desc       = item.get("desc", "")
    link       = item.get("link", "#")
    tickers    = item.get("tickers", [])
    score      = item.get("score", 0)

    extra = ""
    if show_engagement and item.get("ups", 0):
        extra = (f'<span style="color:{TEXT_MUTED};font-size:10px">'
                 f'&#9650; {item["ups"]:,} &nbsp; &#128172; {item["comments"]:,}</span>')
    if item.get("is_dd"):
        extra += (f'&nbsp;<span style="background:{GOLD}22;color:{GOLD};border:1px solid {GOLD}44;'
                  f'padding:1px 6px;border-radius:3px;font-size:10px">&#11088; Deep Dive</span>')

    html = (
        f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR}55;'
        f'border-left:3px solid {left_color};border-radius:8px;padding:12px 16px;margin-bottom:8px">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'flex-wrap:wrap;gap:4px;margin-bottom:8px">'
        f'<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">'
        f'{_sent_badge(sentiment)}{_source_badge(item["source"])}'
        f'<span style="color:{TEXT_MUTED};font-size:10px">{item["time_ago"]}</span>'
        f'{extra}</div>'
        f'{_score_badge(score)}</div>'
        f'<a href="{link}" target="_blank" style="color:{TEXT_PRIMARY};text-decoration:none">'
        f'<div style="font-size:13px;font-weight:600;line-height:1.5;margin-bottom:4px">{title}</div>'
        f'</a>'
    )
    if desc:
        html += f'<div style="color:{TEXT_MUTED};font-size:12px;line-height:1.6">{desc}</div>'
    html += _ticker_tags(tickers)
    html += _tech_row_html(tickers)
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)


def _cluster_cards(items: list):
    ticker_info = {}
    for it in items:
        for t in it.get("tickers", []):
            if t not in ticker_info:
                ticker_info[t] = {"count": 0, "sentiments": []}
            ticker_info[t]["count"] += 1
            ticker_info[t]["sentiments"].append(it["sentiment"])

    clusters = [(t, v) for t, v in ticker_info.items() if v["count"] >= 2]
    if not clusters:
        return
    clusters.sort(key=lambda x: -x[1]["count"])

    cluster_html = ""
    for ticker, info in clusters[:6]:
        sents  = info["sentiments"]
        bull_n = sents.count("Bullish")
        bear_n = sents.count("Bearish")
        neut_n = sents.count("Neutral")
        dom    = "Bullish" if bull_n > bear_n else ("Bearish" if bear_n > bull_n else "Neutral")
        dom_col = ACCENT_GREEN if dom == "Bullish" else (ACCENT_RED if dom == "Bearish" else TEXT_MUTED)
        cluster_html += (
            f'<div style="background:{BG_CARD};border:1px solid {dom_col}44;border-radius:6px;'
            f'padding:8px 14px;display:flex;justify-content:space-between;align-items:center">'
            f'<div style="display:flex;gap:10px;align-items:center">'
            f'<span style="color:{GOLD};font-family:\'DM Mono\',monospace;font-weight:700">${ticker}</span>'
            f'<span style="color:{TEXT_MUTED};font-size:11px">{info["count"]}x mentioned</span>'
            f'</div>'
            f'<div style="display:flex;gap:6px;font-size:10px">'
            f'<span style="color:{ACCENT_GREEN}">&#128994; {bull_n}B</span>'
            f'<span style="color:{ACCENT_RED}">&#128308; {bear_n}Be</span>'
            f'<span style="color:{TEXT_MUTED}">&#9898; {neut_n}N</span>'
            f'</div></div>'
        )
    st.markdown(
        f'<div style="color:{GOLD};font-size:11px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:1px;margin:12px 0 6px">&#128293; Trending Tickers</div>'
        f'<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));'
        f'gap:6px;margin-bottom:16px">{cluster_html}</div>',
        unsafe_allow_html=True,
    )


# ── Section renderers ─────────────────────────────────────────────

def _render_hot_news(signal_mode, ticker_filter, sent_filter):
    with st.spinner("Fetching financial news…"):
        items = _fetch_news()
    if not items:
        st.warning("Could not fetch news feeds. Please try again shortly.")
        return
    if ticker_filter:
        items = [it for it in items if any(ticker_filter in t for t in it["tickers"])
                 or ticker_filter in it["title"].upper()]
    if sent_filter != "All":
        items = [it for it in items if it["sentiment"] == sent_filter]
    if signal_mode:
        items = [it for it in items if it["score"] >= 60]
    _cluster_cards(items)
    for it in items:
        _card(it)


def _render_reddit(signal_mode, ticker_filter, sent_filter):
    with st.spinner("Fetching Reddit posts…"):
        items = _fetch_reddit()
    if not items:
        st.info(
            "Reddit posts unavailable right now. This can happen due to temporary rate limiting. "
            "Try refreshing in a minute.",
            icon="ℹ️",
        )
        return
    if ticker_filter:
        items = [it for it in items if any(ticker_filter in t for t in it["tickers"])
                 or ticker_filter in it["title"].upper()]
    if sent_filter != "All":
        items = [it for it in items if it["sentiment"] == sent_filter]
    if signal_mode:
        items = [it for it in items if it["score"] >= 60]
    _cluster_cards(items)
    for it in items:
        _card(it, show_engagement=True)


def _render_combined(signal_mode, ticker_filter, sent_filter, yt_key: str = ""):
    with st.spinner("Fetching all feeds…"):
        news   = _fetch_news()
        reddit = _fetch_reddit()
        yt     = _fetch_youtube(yt_key) if yt_key else []
        # Filter out any sentinel error records from YouTube
        yt = [it for it in yt if "_error" not in it]

    all_items = sorted(news + reddit + yt, key=lambda x: -x.get("score", 0))
    if ticker_filter:
        all_items = [it for it in all_items
                     if any(ticker_filter in t for t in it["tickers"])
                     or ticker_filter in it["title"].upper()]
    if sent_filter != "All":
        all_items = [it for it in all_items if it["sentiment"] == sent_filter]
    if signal_mode:
        all_items = [it for it in all_items if it["score"] >= 60]
    _cluster_cards(all_items)
    for it in all_items:
        if it.get("type") == "youtube":
            _yt_card(it)
        else:
            _card(it, show_engagement=True)


def _render_yt_placeholder():
    channels = "".join(
        f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:6px;'
        f'padding:8px 12px;font-size:12px;color:{TEXT_PRIMARY}">'
        f'<span style="font-size:14px">&#127909;</span> {ch}</div>'
        for ch in YT_CHANNELS
    )
    st.markdown(
        f'<div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:12px;'
        f'padding:28px 32px;text-align:center">'
        f'<div style="font-size:32px;margin-bottom:8px">&#127909;</div>'
        f'<div style="color:{GOLD};font-size:15px;font-weight:600;margin-bottom:6px">YouTube Integration</div>'
        f'<div style="color:{TEXT_MUTED};font-size:12px;max-width:480px;margin:0 auto 20px;line-height:1.8">'
        f'YouTube Data API v3 is free (10,000 units/day). '
        f'Add <code style="color:{GOLD}">YOUTUBE_API_KEY</code> to your Streamlit secrets '
        f'and this section will activate automatically.</div>'
        f'<div style="color:{TEXT_MUTED};font-size:11px;text-transform:uppercase;letter-spacing:1px;'
        f'margin-bottom:10px">Channels Monitored</div>'
        f'<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));'
        f'gap:6px;max-width:580px;margin:0 auto;text-align:left">{channels}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ── YouTube API fetcher ───────────────────────────────────────────

# Search terms sent to YouTube — each costs 100 quota units
_YT_QUERIES = [
    "stock market analysis today",
    "stocks to buy now",
    "options trading today",
    "investing news today",
    "stock market outlook",
]

@st.cache_data(ttl=1800, show_spinner=False)   # 30-min cache — YouTube quota is finite
def _fetch_youtube(api_key: str) -> list:
    """
    Search YouTube Data API v3 for recent finance videos.
    Each _YT_QUERIES entry costs 100 quota units; 3 queries = 300/day here.
    Results cached 30 min so repeated tab switches don't burn quota.
    Returns list of items in the same schema as news/reddit items,
    OR a single sentinel dict {"_error": msg, "_debug": {...}} on failure.
    """
    from datetime import timedelta

    # 7-day window — wide enough to survive quiet weekends
    published_after = (
        datetime.now(timezone.utc) - timedelta(days=7)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    items:     list = []
    seen:      set  = set()
    api_error: str  = ""
    debug_log: list = []   # accumulate per-query diagnostics

    # Use only 3 queries to conserve quota (300 units/run)
    for query in _YT_QUERIES[:3]:
        try:
            resp = requests.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={
                    "key":               api_key.strip(),
                    "q":                 query,
                    "type":              "video",
                    "order":             "relevance",
                    "publishedAfter":    published_after,
                    "maxResults":        15,
                    "part":              "snippet",
                    "relevanceLanguage": "en",
                    # No videoDuration filter — medium (4-20 min) excluded Shorts
                    # AND long-form analysis videos (>20 min). Accept all lengths.
                },
                timeout=12,
            )

            status = resp.status_code
            debug_log.append({"query": query, "http": status})

            if status == 403:
                data   = resp.json()
                reason = (data.get("error", {})
                              .get("errors", [{}])[0]
                              .get("reason", "unknown"))
                msg    = data.get("error", {}).get("message", "")
                api_error = f"HTTP 403 — {reason}: {msg}"
                break
            if status != 200:
                try:
                    body = resp.json()
                except Exception:
                    body = resp.text[:200]
                api_error = f"HTTP {status} — {body}"
                break

            raw_items = resp.json().get("items", [])
            debug_log[-1]["raw_count"] = len(raw_items)
            kept = 0

            for item in raw_items:
                video_id = item.get("id", {}).get("videoId", "")
                if not video_id or video_id in seen:
                    continue
                seen.add(video_id)

                snippet = item.get("snippet", {})
                title   = _strip_html(snippet.get("title", ""))
                desc    = _strip_html(snippet.get("description", ""))[:220]
                channel = snippet.get("channelTitle", "YouTube")
                pub     = snippet.get("publishedAt", "")
                thumb   = (snippet.get("thumbnails", {})
                                  .get("medium", {})
                                  .get("url", ""))

                if not title:
                    continue

                # NOTE: do NOT apply _is_finance() here — YouTube search already
                # targets finance topics via the query string. Snippet descriptions
                # in search results are often truncated and fail keyword checks
                # even for valid finance videos.

                dt              = _parse_dt(pub)
                tickers         = _extract_tickers(title + " " + desc)
                sentiment, clar = _score_sentiment(title + " " + desc)
                kept += 1

                items.append({
                    "source":     channel,
                    "title":      title,
                    "desc":       desc,
                    "link":       f"https://www.youtube.com/watch?v={video_id}",
                    "dt":         dt,
                    "time_ago":   _time_ago(dt),
                    "tickers":    tickers,
                    "sentiment":  sentiment,
                    "clarity":    clar,
                    "recency":    _recency_w(dt),
                    "engagement": 0,
                    "type":       "youtube",
                    "thumb":      thumb,
                    "video_id":   video_id,
                    "ups":        0, "comments": 0,
                    "is_dd":      False, "flair": "",
                })

            debug_log[-1]["kept"] = kept

        except Exception as exc:
            api_error = str(exc)
            debug_log.append({"query": query, "exception": api_error})
            continue

    if api_error and not items:
        return [{"_error": api_error, "_debug": debug_log}]

    if not items:
        return [{"_error": "No videos returned by API — possibly quota exhausted or all filtered.",
                 "_debug": debug_log}]

    max_eng = 1
    for it in items:
        it["score"] = _compute_score(
            it["recency"], 0, max_eng, it["tickers"], it["clarity"]
        )

    seen_titles, deduped = set(), []
    for it in sorted(items, key=lambda x: -x.get("score", 0)):
        key = it["title"][:60].lower()
        if key not in seen_titles:
            seen_titles.add(key)
            deduped.append(it)

    # Attach debug to first item so caller can surface it in an expander
    if deduped:
        deduped[0]["_debug"] = debug_log
    return deduped[:25]


def _yt_card(item: dict):
    """YouTube-specific card with thumbnail."""
    sentiment  = item.get("sentiment", "Neutral")
    left_color = {"Bullish": ACCENT_GREEN, "Bearish": ACCENT_RED}.get(sentiment, BORDER_COLOR)
    title      = item["title"][:110] + ("…" if len(item["title"]) > 110 else "")
    desc       = item.get("desc", "")
    link       = item.get("link", "#")
    tickers    = item.get("tickers", [])
    score      = item.get("score", 0)
    thumb      = item.get("thumb", "")
    channel    = item.get("source", "YouTube")

    thumb_html = (
        f'<a href="{link}" target="_blank">'
        f'<img src="{thumb}" style="width:120px;height:68px;object-fit:cover;'
        f'border-radius:4px;flex-shrink:0" loading="lazy"/></a>'
        if thumb else ""
    )

    st.markdown(
        f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR}55;'
        f'border-left:3px solid {left_color};border-radius:8px;'
        f'padding:12px 16px;margin-bottom:8px">'
        # header row
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'flex-wrap:wrap;gap:4px;margin-bottom:10px">'
        f'<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">'
        f'{_sent_badge(sentiment)}'
        f'<span style="background:{BG_DARK};color:#FF0000;border:1px solid {BORDER_COLOR};'
        f'padding:2px 7px;border-radius:4px;font-size:10px">&#127909; {channel}</span>'
        f'<span style="color:{TEXT_MUTED};font-size:10px">{item["time_ago"]}</span>'
        f'</div>'
        f'{_score_badge(score)}</div>'
        # body: thumbnail + title + desc
        f'<div style="display:flex;gap:12px;align-items:flex-start">'
        f'{thumb_html}'
        f'<div style="flex:1;min-width:0">'
        f'<a href="{link}" target="_blank" style="color:{TEXT_PRIMARY};text-decoration:none">'
        f'<div style="font-size:13px;font-weight:600;line-height:1.5;margin-bottom:4px">{title}</div>'
        f'</a>'
        + (f'<div style="color:{TEXT_MUTED};font-size:11px;line-height:1.5">{desc}</div>' if desc else "")
        + f'</div></div>'
        + _ticker_tags(tickers)
        + _tech_row_html(tickers)
        + '</div>',
        unsafe_allow_html=True,
    )


def _render_youtube(api_key: str, signal_mode: bool,
                    ticker_filter: str, sent_filter: str):
    # Clear-cache button so user can force a fresh fetch without full reboot
    col_btn, col_sp = st.columns([1, 5])
    with col_btn:
        if st.button("🔄 Refresh YouTube", use_container_width=True, key="_yt_refresh"):
            st.cache_data.clear()
            st.rerun()

    with st.spinner("Fetching YouTube finance videos…"):
        items = _fetch_youtube(api_key)

    # Always show a debug expander so problems are visible
    first = items[0] if items else {}
    debug_info = first.get("_debug", [])
    with st.expander("🔧 Debug — YouTube API status", expanded=("_error" in first)):
        key_preview = api_key[:8] + "…" if len(api_key) > 8 else api_key
        st.markdown(f"**Key read:** `{key_preview}` (length {len(api_key)})")
        if debug_info:
            for d in debug_info:
                q    = d.get("query", "?")
                http = d.get("http", "—")
                raw  = d.get("raw_count", "—")
                kept = d.get("kept", "—")
                exc  = d.get("exception", "")
                if exc:
                    st.markdown(f"- `{q}` → ❌ exception: `{exc}`")
                else:
                    st.markdown(f"- `{q}` → HTTP {http} · {raw} raw · {kept} kept")
        else:
            st.markdown("_No debug data — fetch may not have run yet._")

    # API error surfaced as sentinel record
    if "_error" in first:
        err = first["_error"]
        st.error(
            f"**YouTube API error:** {err}\n\n"
            "**Checklist:**\n"
            "1. Go to [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Library\n"
            "2. Search for **YouTube Data API v3** and confirm it is **Enabled**\n"
            "3. Check your API key has no IP/referer restrictions that block Streamlit Cloud\n"
            "4. Confirm the key in Streamlit secrets is spelled exactly `YOUTUBE_API_KEY`",
            icon="🔑",
        )
        return

    if not items:
        st.info("No videos returned — try refreshing or check the debug panel above.", icon="ℹ️")
        return

    if ticker_filter:
        items = [it for it in items
                 if any(ticker_filter in t for t in it["tickers"])
                 or ticker_filter in it["title"].upper()]
    if sent_filter != "All":
        items = [it for it in items if it["sentiment"] == sent_filter]
    if signal_mode:
        items = [it for it in items if it["score"] >= 60]

    if not items:
        st.info("No YouTube results match the active filters.", icon="ℹ️")
        return

    # Summary metrics
    bull = sum(1 for it in items if it["sentiment"] == "Bullish")
    bear = sum(1 for it in items if it["sentiment"] == "Bearish")
    c1, c2, c3 = st.columns(3)
    with c1: st.markdown(
        f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:6px;'
        f'padding:8px 14px;text-align:center"><div style="color:{TEXT_MUTED};font-size:10px">Videos</div>'
        f'<div style="color:{GOLD};font-size:20px;font-weight:700">{len(items)}</div></div>',
        unsafe_allow_html=True)
    with c2: st.markdown(
        f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:6px;'
        f'padding:8px 14px;text-align:center"><div style="color:{TEXT_MUTED};font-size:10px">Bullish</div>'
        f'<div style="color:{ACCENT_GREEN};font-size:20px;font-weight:700">{bull}</div></div>',
        unsafe_allow_html=True)
    with c3: st.markdown(
        f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:6px;'
        f'padding:8px 14px;text-align:center"><div style="color:{TEXT_MUTED};font-size:10px">Bearish</div>'
        f'<div style="color:{ACCENT_RED};font-size:20px;font-weight:700">{bear}</div></div>',
        unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    _cluster_cards(items)
    for it in items:
        _yt_card(it)


# ── Main entry point ──────────────────────────────────────────────

def render():
    from utils import section_header
    section_header("📱", "Social Trends",
                   "Live financial news · Reddit · YouTube · Signal-scored & sentiment-tagged")

    now_str = datetime.now(timezone.utc).strftime("%H:%M UTC")
    col_a, col_b, col_c = st.columns([3, 1, 1])
    with col_a:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:11px;padding-top:6px">'
            f'&#128337; Last updated {now_str} &nbsp;&#183;&nbsp; '
            f'Sources: Yahoo Finance · CNBC · Reuters · MarketWatch · Benzinga · Reddit</div>',
            unsafe_allow_html=True,
        )
    with col_b:
        signal_mode = st.checkbox("&#128300; Signal score ≥ 60", value=False,
                                  help="Show only items with Signal Score ≥ 60")
    with col_c:
        if st.button("&#128260; Refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    fc1, fc2 = st.columns([2, 1])
    with fc1:
        ticker_filter = st.text_input(
            "Filter by ticker", placeholder="e.g. NVDA or SPY",
            label_visibility="collapsed",
        ).strip().upper().lstrip("$")
    with fc2:
        sent_filter = st.selectbox(
            "Sentiment", ["All", "Bullish", "Bearish", "Neutral"],
            label_visibility="collapsed",
        )

    t_news, t_reddit, t_youtube, t_combined = st.tabs([
        "&#128293; Hot News",
        "&#128172; Reddit",
        "&#127909; YouTube",
        "&#127760; Combined Feed",
    ])

    # Resolve API key — try multiple access patterns for local vs Streamlit Cloud
    yt_key = ""
    try:
        # Primary: direct key access (works on Streamlit Cloud & local secrets.toml)
        yt_key = str(st.secrets["YOUTUBE_API_KEY"]).strip()
    except (KeyError, FileNotFoundError):
        pass
    except Exception:
        try:
            # Fallback: .get() for AttrDict-style secrets
            val = st.secrets.get("YOUTUBE_API_KEY")
            if val:
                yt_key = str(val).strip()
        except Exception:
            yt_key = ""

    with t_news:
        _render_hot_news(signal_mode, ticker_filter, sent_filter)
    with t_reddit:
        _render_reddit(signal_mode, ticker_filter, sent_filter)
    with t_youtube:
        if yt_key:
            _render_youtube(yt_key, signal_mode, ticker_filter, sent_filter)
        else:
            _render_yt_placeholder()
    with t_combined:
        _render_combined(signal_mode, ticker_filter, sent_filter, yt_key)
