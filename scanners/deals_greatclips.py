"""
scanners/deals_greatclips.py — Great Clips Coupon Finder
Scrapes onecountrysweepstakes.com (primary) or weeklyadlist.com (fallback),
collects all offers.greatclips.com links, follows each one, and returns
location-specific coupon results filtered by target cities.
"""

import re
import time
import warnings
import threading
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

try:
    import requests
    from bs4 import BeautifulSoup
    _DEPS_OK = True
except ImportError:
    _DEPS_OK = False

# ── Constants ──────────────────────────────────────────────────
PRIMARY_URL   = "https://onecountrysweepstakes.com/great-clips-coupon-9-99/"
SECONDARY_URL = "https://www.weeklyadlist.com/9-99-great-clips-coupon-printable/"
SITE_ORIGIN   = "https://onecountrysweepstakes.com"

DEFAULT_CITIES = ["Plano", "McKinney", "Frisco"]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}
TIMEOUT       = 12
MAX_WORKERS   = 12           # parallel HTTP threads
CACHE_TTL_MIN = 120          # cache results for 2 hours


# ── HTTP helpers ───────────────────────────────────────────────

def _get(url: str) -> "requests.Response | None":
    try:
        return requests.get(url, headers=_HEADERS, timeout=TIMEOUT, verify=False,
                            allow_redirects=True)
    except Exception:
        return None


def _soup(url: str) -> "BeautifulSoup | None":
    r = _get(url)
    if r is None or not r.ok:
        return None
    return BeautifulSoup(r.text, "html.parser")


# ── Primary-site scraping ──────────────────────────────────────

def _collect_denomination_pages(soup: "BeautifulSoup") -> list[tuple[str, str]]:
    """Return (label, url) for every great-clips coupon page linked from the article."""
    seen: set[str] = set()
    pages: list[tuple[str, str]] = []
    article = soup.find("article") or soup
    for a in article.find_all("a", href=True):
        href = a["href"].strip()
        if (
            "onecountrysweepstakes.com/great-clips-coupon" in href
            or "onecountrysweepstakes.com/great-clips-coupons" in href
        ) and href not in seen:
            pages.append((a.get_text(strip=True) or href, href))
            seen.add(href)
    return pages


def _collect_offer_links(soup: "BeautifulSoup") -> list[str]:
    seen: set[str] = set()
    links: list[str] = []
    article = soup.find("article") or soup
    for a in article.find_all("a", href=True):
        href = a["href"].strip()
        if "offers.greatclips.com" in href and href not in seen:
            links.append(href)
            seen.add(href)
    return links


def _extract_coupon_info(url: str, page_text: str) -> dict | None:
    """Parse city, location name, address, price/type from the Sparkfly offer page."""
    try:
        m = re.search(
            r"Get a great haircut for ([^\s]+(?:\s+off)?)\s+at\s+Great Clips\s+(.+?)\s+at\s+(.+?)\s+in\s+(\w[\w\s]+?)\.",
            page_text,
            re.IGNORECASE | re.DOTALL,
        )
        if not m:
            return None

        raw_price_str, loc_name, address, city = (g.strip() for g in m.groups())

        # Normalise price — strip everything except digits and dots
        digits = re.sub(r"[^\d.]", "", raw_price_str)
        if not digits:
            return None
        amount = float(digits)

        price_lower = raw_price_str.lower()
        if "off" in price_lower:
            coupon_type = "off"
            sort_key    = -amount
        else:
            coupon_type = "flat"
            sort_key    = amount

        denom = raw_price_str if raw_price_str.startswith("$") else f"${raw_price_str}"

        return {
            "city":              city,
            "location":          loc_name,
            "address":           address,
            "raw_price":         raw_price_str,
            "amount":            amount,
            "coupon_type":       coupon_type,
            "sort_key":          sort_key,
            "coupon_url":        url,
            "denomination":      denom,
            "denomination_label": "",
        }
    except Exception:
        return None


def _fetch_offer(url: str) -> dict | None:
    r = _get(url)
    if r is None:
        return None
    return _extract_coupon_info(url, r.text)


def _scan_primary(target_cities: list[str],
                  progress_cb=None) -> tuple[list[dict], str]:
    """
    Scan the primary site.
    progress_cb(current, total, msg) called during scan.
    Returns (results, source_label).
    """
    home = _soup(PRIMARY_URL)
    if home is None:
        return [], ""

    # Collect denomination pages
    denom_pages = [(f"${PRIMARY_URL.split('-')[-2]}", PRIMARY_URL)]
    denom_pages += _collect_denomination_pages(home)

    # Deduplicate
    seen_pages: set[str] = set()
    unique_pages: list[tuple[str, str]] = []
    for label, url in denom_pages:
        if url not in seen_pages:
            unique_pages.append((label, url))
            seen_pages.add(url)

    # Collect all offer links (with their denomination label)
    offer_map: dict[str, str] = {}   # url → denomination label
    for label, page_url in unique_pages:
        soup = _soup(page_url)
        if soup is None:
            continue
        for lnk in _collect_offer_links(soup):
            if lnk not in offer_map:
                offer_map[lnk] = label

    all_offer_urls = list(offer_map.keys())
    total = len(all_offer_urls)

    cities_lower = [c.lower() for c in target_cities]
    results: list[dict] = []
    done = 0
    lock = threading.Lock()

    def _worker(url: str) -> dict | None:
        try:
            info = _fetch_offer(url)
            if info and info["city"].lower() in cities_lower:
                info["denomination_label"] = offer_map.get(url, "")
                return info
        except Exception:
            pass
        return None

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(_worker, u): u for u in all_offer_urls}
        for fut in as_completed(futures):
            done += 1
            try:
                result = fut.result()
            except Exception:
                result = None
            if result:
                with lock:
                    results.append(result)
            # progress_cb touches Streamlit state — call from main thread only
            if progress_cb:
                progress_cb(done, total, f"Checked {done}/{total} coupons…")

    return results, "onecountrysweepstakes.com"


def _scan_secondary(target_cities: list[str],
                    progress_cb=None) -> tuple[list[dict], str]:
    """
    Fallback: scrape weeklyadlist.com for Great Clips coupon pages
    and look for city-specific offer links.
    """
    home = _soup(SECONDARY_URL)
    if home is None:
        return [], ""

    cities_lower = [c.lower() for c in target_cities]
    results: list[dict] = []

    # Gather all internal links from the page
    seen: set[str] = set()
    links_to_check: list[str] = [SECONDARY_URL]
    article = home.find("article") or home
    for a in article.find_all("a", href=True):
        href = a["href"].strip()
        if "weeklyadlist.com" in href and href not in seen:
            links_to_check.append(href)
            seen.add(href)

    total = len(links_to_check)
    for i, url in enumerate(links_to_check):
        if progress_cb:
            progress_cb(i + 1, total, f"Checking {url.split('/')[-2] or url}…")
        r = _get(url)
        if r is None:
            continue
        txt = r.text
        page_cities = [c for c in target_cities if c.lower() in txt.lower()]
        if not page_cities:
            continue

        # Try to extract offers.greatclips.com links from this page
        soup2 = BeautifulSoup(txt, "html.parser")
        for a in soup2.find_all("a", href=True):
            href = a["href"].strip()
            if "offers.greatclips.com" in href:
                info = _fetch_offer(href)
                if info and info["city"].lower() in cities_lower:
                    info["denomination_label"] = "via weeklyadlist"
                    results.append(info)

        # If no offers.greatclips links, at least record the page as a reference
        if not any(r["coupon_url"].startswith("http") for r in results):
            for city in page_cities:
                results.append({
                    "city":             city,
                    "location":         "See page",
                    "address":          "",
                    "raw_price":        "9.99",
                    "amount":           9.99,
                    "coupon_type":      "flat",
                    "sort_key":         9.99,
                    "coupon_url":       url,
                    "denomination":     "$9.99",
                    "denomination_label": "weeklyadlist.com",
                })

    return results, "weeklyadlist.com"


def run_scan(target_cities: list[str],
             progress_cb=None) -> tuple[list[dict], str]:
    """
    Main entry: try primary, fall back to secondary.
    Returns (sorted_results, source_label).
    """
    results, source = _scan_primary(target_cities, progress_cb)
    if not results and source == "":
        # Primary unreachable — try secondary
        results, source = _scan_secondary(target_cities, progress_cb)

    # Sort: off coupons first (highest discount), then flat price ascending
    def _sorter(r):
        # off → type_rank=0, flat → type_rank=1; then sort_key
        type_rank = 0 if r["coupon_type"] == "off" else 1
        return (type_rank, r["sort_key"])

    results.sort(key=_sorter)
    return results, source


# ── Display helpers ────────────────────────────────────────────

_CITY_COLORS = {
    "plano":    "#1E88E5",
    "mckinney": "#43A047",
    "frisco":   "#FB8C00",
}

def _city_badge(city: str) -> str:
    color = _CITY_COLORS.get(city.lower(), "#9E9E9E")
    return (
        f'<span style="background:{color};color:#fff;padding:2px 10px;'
        f'border-radius:12px;font-size:0.78rem;font-weight:700;'
        f'letter-spacing:0.05em;">{city.upper()}</span>'
    )


def _price_badge(r: dict) -> str:
    if r["coupon_type"] == "off":
        label = f"${r['amount']:.2f} OFF"
        bg = "#2E7D32"
    else:
        label = f"${r['amount']:.2f}"
        bg = "#1565C0"
    return (
        f'<span style="background:{bg};color:#fff;padding:3px 12px;'
        f'border-radius:6px;font-size:1.05rem;font-weight:800;">{label}</span>'
    )


def _coupon_card(r: dict, idx: int) -> str:
    city_badge  = _city_badge(r["city"])
    price_badge = _price_badge(r)
    addr        = f" &nbsp;·&nbsp; {r['address']}" if r["address"] else ""
    denom_label = r.get("denomination_label", "")
    denom_note  = (
        f'<span style="font-size:0.72rem;color:#aaa;margin-left:8px;">'
        f'({denom_label})</span>'
        if denom_label else ""
    )
    return f"""
<div style="background:#1e2230;border:1px solid #2d3347;border-radius:10px;
            padding:14px 18px;margin-bottom:10px;">
  <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:6px;">
    {price_badge}
    {city_badge}
    <span style="color:#e0e0e0;font-size:0.95rem;font-weight:600;">{r['location']}</span>
    {denom_note}
  </div>
  <div style="color:#b0bec5;font-size:0.85rem;margin-bottom:8px;">
    📍 {r['address']}{addr}
  </div>
  <a href="{r['coupon_url']}" target="_blank"
     style="display:inline-block;background:#c9a227;color:#000;
            padding:5px 16px;border-radius:6px;font-size:0.85rem;
            font-weight:700;text-decoration:none;">
    🎟️ Redeem Coupon →
  </a>
</div>
"""


# ── Page render ────────────────────────────────────────────────

def render():
    # ── Deps check ─────────────────────────────────────────────
    if not _DEPS_OK:
        st.error("Missing dependencies: `pip install requests beautifulsoup4`")
        return

    # ── Header ─────────────────────────────────────────────────
    st.markdown(
        """
        <div style="border-left:4px solid #c9a227;padding:6px 16px;margin-bottom:4px;">
          <span style="font-size:1.6rem;font-weight:800;color:#c9a227;">🎟️ Great Clips Coupons</span><br>
          <span style="color:#b0bec5;font-size:0.9rem;">
            Find location-specific haircut coupons for your city — no printing required, just show on your phone.
          </span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("<br>", unsafe_allow_html=True)

    # ── City filter ────────────────────────────────────────────
    col1, col2 = st.columns([3, 1])
    with col1:
        city_input = st.text_input(
            "🏙️ Cities to search (comma-separated)",
            value=", ".join(DEFAULT_CITIES),
            help="Enter city names exactly as they appear in Texas, e.g. Plano, McKinney, Frisco",
        )
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        scan_clicked = st.button("🔍 Scan for Coupons", type="primary", use_container_width=True)

    target_cities = [c.strip() for c in city_input.split(",") if c.strip()]

    # ── Cache management ────────────────────────────────────────
    _CACHE_KEY    = "gc_coupon_results"
    _CACHE_TS_KEY = "gc_coupon_ts"
    _CITY_KEY     = "gc_coupon_cities"
    _SRC_KEY      = "gc_coupon_source"

    cache_valid = (
        _CACHE_KEY in st.session_state
        and _CACHE_TS_KEY in st.session_state
        and st.session_state.get(_CITY_KEY) == target_cities
        and datetime.now() - st.session_state[_CACHE_TS_KEY] < timedelta(minutes=CACHE_TTL_MIN)
    )

    # ── Trigger scan ────────────────────────────────────────────
    if scan_clicked or (not cache_valid and _CACHE_KEY in st.session_state):
        # Clear stale cache if cities changed
        for k in (_CACHE_KEY, _CACHE_TS_KEY, _CITY_KEY, _SRC_KEY):
            st.session_state.pop(k, None)
        cache_valid = False

    if scan_clicked and not cache_valid:
        if not target_cities:
            st.warning("Please enter at least one city name.")
            return

        status_box  = st.empty()
        progress_ph = st.empty()
        prog_bar    = st.progress(0)
        live_ph     = st.empty()

        status_box.info(
            f"🔍 Scanning coupons for **{', '.join(target_cities)}** — "
            f"this may take 30–90 seconds…"
        )

        _results_acc: list[dict] = []

        def _progress(done: int, total: int, msg: str):
            pct = done / total if total else 0
            prog_bar.progress(pct)
            progress_ph.caption(f"{msg}  ({done}/{total})")

        results, source = run_scan(target_cities, _progress)

        # Store in session state
        st.session_state[_CACHE_KEY]    = results
        st.session_state[_CACHE_TS_KEY] = datetime.now()
        st.session_state[_CITY_KEY]     = target_cities
        st.session_state[_SRC_KEY]      = source

        # Clear progress UI
        status_box.empty()
        progress_ph.empty()
        prog_bar.empty()
        live_ph.empty()
        st.rerun()

    # ── Display results (from cache) ───────────────────────────
    if _CACHE_KEY in st.session_state:
        results: list[dict] = st.session_state[_CACHE_KEY]
        source: str         = st.session_state.get(_SRC_KEY, "")
        scanned_cities      = st.session_state.get(_CITY_KEY, target_cities)
        scan_ts             = st.session_state.get(_CACHE_TS_KEY, datetime.now())

        # ── Summary bar ────────────────────────────────────────
        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        c1.metric("Coupons Found", len(results))
        c2.metric("Cities Searched", len(scanned_cities))
        c3.metric("Source", source or "N/A")
        st.caption(f"Last scanned: {scan_ts.strftime('%b %d, %Y %I:%M %p')}")

        col_rescan, _ = st.columns([1, 4])
        with col_rescan:
            if st.button("🔄 Re-scan"):
                for k in (_CACHE_KEY, _CACHE_TS_KEY, _CITY_KEY, _SRC_KEY):
                    st.session_state.pop(k, None)
                st.rerun()

        if not results:
            st.markdown("<br>", unsafe_allow_html=True)
            st.warning(
                f"No location-specific coupons found for **{', '.join(scanned_cities)}** "
                f"on {source}.\n\n"
                "These coupons may not be available for your city at this time, or "
                "the site may list only generic (all-location) deals. "
                "Try visiting [greatclips.com/coupons](https://www.greatclips.com/coupons) "
                "and entering your zip code directly."
            )
            return

        st.markdown("<br>", unsafe_allow_html=True)

        # Group by city
        city_groups: dict[str, list[dict]] = {}
        for r in results:
            city_groups.setdefault(r["city"], []).append(r)

        # ── Tabs per city ──────────────────────────────────────
        if len(city_groups) > 1:
            tab_labels = [
                f"{'🔵' if c.lower()=='plano' else '🟢' if c.lower()=='mckinney' else '🟠' if c.lower()=='frisco' else '⚪'} {c} ({len(v)})"
                for c, v in city_groups.items()
            ]
            tabs = st.tabs(tab_labels)
            for tab, (city, coupons) in zip(tabs, city_groups.items()):
                with tab:
                    _render_city_coupons(city, coupons)
        else:
            city, coupons = next(iter(city_groups.items()))
            _render_city_coupons(city, coupons)

    else:
        # No scan run yet — show instructions
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(
            """
            <div style="background:#1e2230;border:1px solid #2d3347;border-radius:10px;
                        padding:24px 28px;text-align:center;">
              <div style="font-size:2.5rem;">🎟️</div>
              <div style="font-size:1.1rem;color:#e0e0e0;margin:8px 0 4px;">
                Find Great Clips coupons for your city
              </div>
              <div style="color:#b0bec5;font-size:0.88rem;max-width:420px;margin:0 auto;">
                Enter the cities above and click <strong>Scan for Coupons</strong>.
                The scanner checks all active Great Clips offers and shows only those
                valid at locations near you.
              </div>
              <div style="margin-top:16px;font-size:0.78rem;color:#607d8b;">
                Primary source: onecountrysweepstakes.com &nbsp;·&nbsp;
                Fallback: weeklyadlist.com
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_city_coupons(city: str, coupons: list[dict]):
    """Render all coupons for one city, grouped by type."""
    off_coupons  = [r for r in coupons if r["coupon_type"] == "off"]
    flat_coupons = [r for r in coupons if r["coupon_type"] == "flat"]

    if off_coupons:
        st.markdown(
            '<div style="font-size:0.8rem;font-weight:700;color:#43A047;'
            'letter-spacing:0.08em;margin-bottom:6px;">DISCOUNT COUPONS ($ OFF)</div>',
            unsafe_allow_html=True,
        )
        for r in off_coupons:
            st.markdown(_coupon_card(r, 0), unsafe_allow_html=True)

    if flat_coupons:
        if off_coupons:
            st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(
            '<div style="font-size:0.8rem;font-weight:700;color:#1E88E5;'
            'letter-spacing:0.08em;margin-bottom:6px;">FLAT PRICE COUPONS (lowest first)</div>',
            unsafe_allow_html=True,
        )
        for r in flat_coupons:
            st.markdown(_coupon_card(r, 0), unsafe_allow_html=True)
