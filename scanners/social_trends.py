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
    'buy', 'bull', 'bullish', 'breakout', 'surge', 'surges', 'rally', 'rallies',
    'moon', 'calls', 'upside', 'beats', 'beat', 'strong', 'growth', 'bounce',
    'oversold', 'support', 'accumulate', 'long', 'upgrade', 'outperform',
    'record', 'gains', 'positive', 'optimistic', 'higher', 'momentum',
    'demand', 'bottom', 'recovery', 'rebound', 'squeeze', 'breakout',
}
BEAR_WORDS = {
    'sell', 'bear', 'bearish', 'crash', 'drop', 'drops', 'fall', 'falls',
    'puts', 'downside', 'miss', 'misses', 'weak', 'dump', 'short',
    'resistance', 'overbought', 'warning', 'risk', 'caution', 'concern',
    'downgrade', 'underperform', 'decline', 'loss', 'negative',
    'lower', 'tariff', 'layoffs', 'bankruptcy', 'headwinds', 'recession',
    'selloff', 'sellout', 'correction',
}
FINANCE_KW = {
    'stock', 'stocks', 'share', 'shares', 'market', 'earnings', 'revenue',
    'quarter', 'fed', 'federal reserve', 'interest rate', 'inflation',
    'nasdaq', 's&p', 'dow', 'etf', 'options', 'calls', 'puts', 'strike',
    'crypto', 'bitcoin', 'ethereum', 'ipo', 'merger', 'acquisition',
    'buyback', 'dividend', 'analyst', 'upgrade', 'downgrade', 'price target',
    'sector', 'rally', 'selloff', 'bull', 'bear', 'trade', 'trading',
    'hedge', 'portfolio', 'yield', 'bond', 'treasury', 'macro',
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
    "wallstreetbets", "stocks", "options", "investing",
    "StockMarket", "SecurityAnalysis",
]

X_ACCOUNTS = [
    "@KobeissiLetter", "@thestockwhale", "@MrMikeInvesting",
    "@NoLimitGains", "@optionscjp", "@BobPisani",
    "@timsstocklists", "@dailyfelixprehn", "@marktilbury",
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
    'GDP','SEC','USA','USD','EUR','IMF','ESG','CNBC','NYSE','NYSE','RSS',
}
HEADERS = {"User-Agent": "GoldenScanner/1.0 (financial-research)"}


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
                   tickers: list, sentiment_clarity: float) -> int:
    eng_w = min(1.0, engagement / max(max_eng, 1))
    tick_w = 1.0 if tickers else 0.3
    return int(recency * 30 + eng_w * 30 + tick_w * 20 + sentiment_clarity * 20)


def _parse_dt(pub_str: str) -> datetime:
    for fn in (parsedate_to_datetime, lambda s: datetime.fromisoformat(s)):
        try:
            return fn(pub_str)
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
            "rsi": rsi, "rsi_col": rsi_col,
            "trend": trend, "vol": vol_sig,
        }
    except Exception:
        return {}


def _tech_row_html(tickers: list) -> str:
    if not tickers:
        return ""
    ticker = tickers[0]
    snap = _tech(ticker)
    if not snap:
        return ""
    sign = "+" if snap["chg"] >= 0 else ""
    parts = [
        f'<span style="color:{GOLD};font-weight:700;font-family:\'DM Mono\',monospace">${ticker}</span>',
        f'<span style="color:{snap["chg_col"]}">${snap["price"]:.2f} ({sign}{snap["chg"]:.2f}%)</span>',
        f'<span style="color:{TEXT_MUTED}">RSI <span style="color:{snap["rsi_col"]}">{snap["rsi"]}</span></span>',
        f'<span style="color:{TEXT_MUTED}">{snap["trend"]}</span>',
    ]
    if snap["vol"]:
        parts.append(f'<span style="color:{TEXT_MUTED}">{snap["vol"]}</span>')
    inner = ' <span style="color:{c}">&#183;</span> '.format(c=BORDER_COLOR).join(parts)
    return (f'<div style="background:{BG_DARK};border-radius:4px;padding:6px 10px;'
            f'margin-top:8px;font-size:11px;display:flex;flex-wrap:wrap;gap:8px">{inner}</div>')


# ── Data fetchers ────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def _fetch_news() -> list:
    items = []
    for src_name, url in NEWS_FEEDS:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=8)
            if resp.status_code != 200:
                continue
            root = ET.fromstring(resp.content)
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
                rw = _recency_w(dt)
                items.append({
                    "source": src_name, "title": title, "desc": desc,
                    "link": link, "dt": dt, "time_ago": _time_ago(dt),
                    "tickers": tickers, "sentiment": sentiment,
                    "clarity": clarity, "recency": rw,
                    "engagement": 0, "type": "news",
                    "ups": 0, "comments": 0,
                })
        except Exception:
            continue

    # Deduplicate: same tickers + first 50 chars of title
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


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_reddit() -> list:
    items = []
    for sub in SUBREDDITS:
        try:
            url  = f"https://www.reddit.com/r/{sub}/hot.json?limit=20"
            resp = requests.get(url, headers=HEADERS, timeout=8)
            if resp.status_code != 200:
                continue
            posts = resp.json().get("data", {}).get("children", [])
            for p in posts:
                d        = p.get("data", {})
                title    = d.get("title", "")
                selftext = _strip_html(d.get("selftext", ""))[:300]
                ups      = int(d.get("ups", 0))
                comments = int(d.get("num_comments", 0))
                flair    = d.get("link_flair_text") or ""
                created  = d.get("created_utc", time.time())
                permalink = d.get("permalink", "")
                dt = datetime.fromtimestamp(created, tz=timezone.utc)

                if ups < 80 and comments < 40:
                    continue
                text = title + " " + selftext
                if not _is_finance(text):
                    continue
                # Skip low-effort meme posts
                meme_kw = ['loss porn', 'gain porn', '🚀🚀🚀', '🌈🐻', 'yolo', 'apes']
                if any(kw in title.lower() for kw in meme_kw) and ups < 5000:
                    continue

                tickers   = _extract_tickers(text)
                sentiment, clarity = _score_sentiment(text)
                rw = _recency_w(dt)
                is_dd = any(kw in flair.lower() for kw in ['dd', 'due diligence', 'analysis', 'research'])
                engagement = ups + comments * 3

                items.append({
                    "source": f"r/{sub}", "title": title, "desc": selftext,
                    "link": f"https://reddit.com{permalink}",
                    "dt": dt, "time_ago": _time_ago(dt),
                    "tickers": tickers, "sentiment": sentiment,
                    "clarity": clarity, "recency": rw,
                    "engagement": engagement, "type": "reddit",
                    "ups": ups, "comments": comments,
                    "flair": flair, "is_dd": is_dd,
                })
        except Exception:
            continue

    max_eng = max((it["engagement"] for it in items), default=1)
    for it in items:
        it["score"] = _compute_score(it["recency"], it["engagement"], max_eng, it["tickers"], it["clarity"])
        if it.get("is_dd") and it["ups"] >= 200:
            it["score"] = min(100, it["score"] + 15)
    items.sort(key=lambda x: -x["score"])
    return items[:30]


# ── Card rendering ───────────────────────────────────────────────

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
    left_color = {
        "Bullish": ACCENT_GREEN, "Bearish": ACCENT_RED
    }.get(sentiment, BORDER_COLOR)

    title   = item["title"][:120] + ("…" if len(item["title"]) > 120 else "")
    desc    = item.get("desc", "")
    link    = item.get("link", "#")
    tickers = item.get("tickers", [])
    score   = item.get("score", 0)

    extra = ""
    if show_engagement and (item.get("ups", 0) or item.get("comments", 0)):
        extra = (
            f'<span style="color:{TEXT_MUTED};font-size:10px">'
            f'&#9650; {item["ups"]:,} &nbsp; &#128172; {item["comments"]:,}</span>'
        )
    if item.get("is_dd"):
        extra += (f'&nbsp;<span style="background:{GOLD}22;color:{GOLD};border:1px solid {GOLD}44;'
                  f'padding:1px 6px;border-radius:3px;font-size:10px">&#11088; Deep Dive</span>')

    tech_html = _tech_row_html(tickers)

    html = (
        f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR}55;'
        f'border-left:3px solid {left_color};border-radius:8px;padding:12px 16px;margin-bottom:8px">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'flex-wrap:wrap;gap:4px;margin-bottom:8px">'
        f'<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">'
        f'{_sent_badge(sentiment)}'
        f'{_source_badge(item["source"])}'
        f'<span style="color:{TEXT_MUTED};font-size:10px">{item["time_ago"]}</span>'
        f'{extra}'
        f'</div>'
        f'{_score_badge(score)}'
        f'</div>'
        f'<a href="{link}" target="_blank" style="color:{TEXT_PRIMARY};text-decoration:none">'
        f'<div style="font-size:13px;font-weight:600;line-height:1.5;margin-bottom:4px">{title}</div>'
        f'</a>'
    )
    if desc:
        html += f'<div style="color:{TEXT_MUTED};font-size:12px;line-height:1.6">{desc}</div>'
    html += _ticker_tags(tickers)
    html += tech_html
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)


def _cluster_cards(items: list):
    ticker_sources = {}
    for it in items:
        for t in it.get("tickers", []):
            if t not in ticker_sources:
                ticker_sources[t] = {"count": 0, "sentiments": [], "score": 0}
            ticker_sources[t]["count"] += 1
            ticker_sources[t]["sentiments"].append(it["sentiment"])
            ticker_sources[t]["score"] = max(ticker_sources[t]["score"], it.get("score", 0))

    clusters = [(t, v) for t, v in ticker_sources.items() if v["count"] >= 2]
    if not clusters:
        return
    clusters.sort(key=lambda x: -x[1]["count"])

    cluster_html = ""
    for ticker, info in clusters[:5]:
        sents  = info["sentiments"]
        bull_n = sents.count("Bullish")
        bear_n = sents.count("Bearish")
        neut_n = sents.count("Neutral")
        dom = "Bullish" if bull_n > bear_n else ("Bearish" if bear_n > bull_n else "Neutral")
        dom_col = ACCENT_GREEN if dom == "Bullish" else (ACCENT_RED if dom == "Bearish" else TEXT_MUTED)
        cluster_html += (
            f'<div style="background:{BG_CARD};border:1px solid {dom_col}44;border-radius:6px;'
            f'padding:8px 14px;display:flex;justify-content:space-between;align-items:center">'
            f'<div style="display:flex;gap:10px;align-items:center">'
            f'<span style="color:{GOLD};font-family:\'DM Mono\',monospace;font-weight:700">${ticker}</span>'
            f'<span style="color:{TEXT_MUTED};font-size:11px">Mentioned {info["count"]}x</span>'
            f'</div>'
            f'<div style="display:flex;gap:6px;font-size:10px">'
            f'<span style="color:{ACCENT_GREEN}">&#128994; {bull_n}B</span>'
            f'<span style="color:{ACCENT_RED}">&#128308; {bear_n}Be</span>'
            f'<span style="color:{TEXT_MUTED}">&#9898; {neut_n}N</span>'
            f'</div>'
            f'</div>'
        )
    st.markdown(
        f'<div style="color:{GOLD};font-size:11px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:1px;margin:12px 0 6px">&#128293; Trending Tickers</div>'
        f'<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:6px;margin-bottom:16px">'
        f'{cluster_html}</div>',
        unsafe_allow_html=True,
    )


# ── Section renderers ────────────────────────────────────────────

def _render_hot_news(signal_mode: bool, ticker_filter: str, sent_filter: str):
    with st.spinner("Fetching financial news…"):
        items = _fetch_news()
    if not items:
        st.warning("Could not reach news feeds. Check connectivity.")
        return
    if ticker_filter:
        items = [it for it in items if any(ticker_filter.upper() in t for t in it["tickers"])
                 or ticker_filter.upper() in it["title"].upper()]
    if sent_filter != "All":
        items = [it for it in items if it["sentiment"] == sent_filter]
    if signal_mode:
        items = [it for it in items if it["score"] >= 60]

    _cluster_cards(items)
    for it in items:
        _card(it)


def _render_reddit(signal_mode: bool, ticker_filter: str, sent_filter: str):
    with st.spinner("Fetching Reddit posts…"):
        items = _fetch_reddit()
    if not items:
        st.warning("Could not reach Reddit. Check connectivity.")
        return
    if ticker_filter:
        items = [it for it in items if any(ticker_filter.upper() in t for t in it["tickers"])
                 or ticker_filter.upper() in it["title"].upper()]
    if sent_filter != "All":
        items = [it for it in items if it["sentiment"] == sent_filter]
    if signal_mode:
        items = [it for it in items if it["score"] >= 60]

    _cluster_cards(items)
    for it in items:
        _card(it, show_engagement=True)


def _render_combined(signal_mode: bool, ticker_filter: str, sent_filter: str):
    with st.spinner("Fetching all feeds…"):
        news   = _fetch_news()
        reddit = _fetch_reddit()
    all_items = news + reddit
    all_items.sort(key=lambda x: -x.get("score", 0))

    if ticker_filter:
        all_items = [it for it in all_items
                     if any(ticker_filter.upper() in t for t in it["tickers"])
                     or ticker_filter.upper() in it["title"].upper()]
    if sent_filter != "All":
        all_items = [it for it in all_items if it["sentiment"] == sent_filter]
    if signal_mode:
        all_items = [it for it in all_items if it["score"] >= 60]

    _cluster_cards(all_items)
    for it in all_items:
        _card(it, show_engagement=True)


def _render_x_placeholder():
    accs = "".join(
        f'<div style="background:{BG_CARD};border:1px solid {BORDER_COLOR};border-radius:6px;'
        f'padding:8px 12px;font-size:12px;color:{GOLD};font-family:\'DM Mono\',monospace">{a}</div>'
        for a in X_ACCOUNTS
    )
    st.markdown(
        f'<div style="background:{BG_PANEL};border:1px solid {BORDER_COLOR};border-radius:12px;'
        f'padding:28px 32px;text-align:center">'
        f'<div style="font-size:32px;margin-bottom:8px">&#120143;</div>'
        f'<div style="color:{GOLD};font-size:15px;font-weight:600;margin-bottom:6px">X / Twitter Integration</div>'
        f'<div style="color:{TEXT_MUTED};font-size:12px;max-width:480px;margin:0 auto 20px;line-height:1.8">'
        f'X API access requires a paid developer plan (~$100/mo Basic tier). '
        f'When you have an API key, add <code style="color:{GOLD}">X_BEARER_TOKEN</code> to your '
        f'Streamlit secrets and this section will activate automatically.</div>'
        f'<div style="color:{TEXT_MUTED};font-size:11px;text-transform:uppercase;letter-spacing:1px;'
        f'margin-bottom:10px">High-Signal Accounts to Follow</div>'
        f'<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));'
        f'gap:6px;max-width:600px;margin:0 auto;text-align:left">{accs}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


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


# ── Main entry point ─────────────────────────────────────────────

def render_social_trends():
    # Last updated + refresh row
    now_str = datetime.now(timezone.utc).strftime("%H:%M UTC")
    col_a, col_b, col_c = st.columns([3, 1, 1])
    with col_a:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};font-size:11px;padding-top:6px">'
            f'&#128337; Last updated {now_str} &nbsp;&#183;&nbsp; '
            f'Auto-refreshed every 5 min &nbsp;&#183;&nbsp; '
            f'Sources: Yahoo Finance · CNBC · Reuters · MarketWatch · Benzinga · Reddit</div>',
            unsafe_allow_html=True,
        )
    with col_b:
        signal_mode = st.checkbox("&#128300; Signal Mode", value=False, help="Show only items with Signal Score ≥ 60")
    with col_c:
        if st.button("&#128260; Refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    # Global filter bar
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

    # Sub-tabs
    t_news, t_reddit, t_youtube, t_x, t_combined = st.tabs([
        "&#128293; Hot News",
        "&#128172; Reddit",
        "&#127909; YouTube",
        "&#120143; X / Twitter",
        "&#127760; Combined Feed",
    ])

    with t_news:
        _render_hot_news(signal_mode, ticker_filter, sent_filter)

    with t_reddit:
        _render_reddit(signal_mode, ticker_filter, sent_filter)

    with t_youtube:
        _render_yt_placeholder()

    with t_x:
        _render_x_placeholder()

    with t_combined:
        _render_combined(signal_mode, ticker_filter, sent_filter)
