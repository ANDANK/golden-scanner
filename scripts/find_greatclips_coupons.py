"""
Great Clips Coupon Finder for Plano / McKinney / Frisco, TX

Strategy:
  1. Start at the $9.99 page; collect all other denomination page links.
  2. For every denomination page, collect all offers.greatclips.com short links.
  3. Follow each unique coupon link and check the page text for target cities.
     (The Sparkfly offer page embeds city/address in its static HTML.)
  4. Report every matching coupon with its denomination, city, and URL.
"""

import re
import sys
import time
import warnings
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

warnings.filterwarnings("ignore", message="Unverified HTTPS request")
sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "https://onecountrysweepstakes.com/great-clips-coupon-9-99/"
SITE_ORIGIN = "https://onecountrysweepstakes.com"
TARGET_CITIES = ["plano", "mckinney", "frisco"]
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}
TIMEOUT = 15
DELAY = 0.6  # seconds between requests


def fetch(url: str) -> BeautifulSoup | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, verify=False)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except requests.RequestException as e:
        print(f"  [FETCH ERROR] {url}: {e}")
        return None


def get_page_text(url: str) -> tuple[str, str]:
    """Return (final_url, page_text) following redirects."""
    try:
        r = requests.get(
            url, headers=HEADERS, timeout=TIMEOUT, verify=False, allow_redirects=True
        )
        return r.url, r.text
    except requests.RequestException:
        return url, ""


def collect_denomination_pages(soup: BeautifulSoup, base_page_url: str) -> list[tuple[str, str]]:
    """Return (label, url) for every great-clips coupon page linked from the article."""
    pages = []
    seen = set()
    article = soup.find("article") or soup
    for a in article.find_all("a", href=True):
        href = a["href"].strip()
        if (
            "onecountrysweepstakes.com/great-clips-coupon" in href
            or "onecountrysweepstakes.com/great-clips-coupons" in href
        ):
            if href not in seen and href != base_page_url:
                pages.append((a.get_text(strip=True) or href, href))
                seen.add(href)
    return pages


def collect_offer_links(soup: BeautifulSoup) -> list[str]:
    """Return unique offers.greatclips.com links from the article."""
    seen: set[str] = set()
    links = []
    article = soup.find("article") or soup
    for a in article.find_all("a", href=True):
        href = a["href"].strip()
        if "offers.greatclips.com" in href and href not in seen:
            links.append(href)
            seen.add(href)
    return links


def cities_in_text(text: str) -> list[str]:
    t = text.lower()
    return [c for c in TARGET_CITIES if c in t]


def snippet(text: str, city: str, ctx: int = 120) -> str:
    m = re.search(re.escape(city), text, re.IGNORECASE)
    if not m:
        return ""
    s, e = max(0, m.start() - ctx), min(len(text), m.end() + ctx)
    return f"...{text[s:e].replace(chr(10), ' ')}..."


def main():
    print(f"Step 1 — Loading main coupon page: {BASE_URL}\n")
    home_soup = fetch(BASE_URL)
    if home_soup is None:
        print("Cannot load main page. Exiting.")
        return

    denom_pages = collect_denomination_pages(home_soup, BASE_URL)
    # Include the starting page itself
    all_pages: list[tuple[str, str]] = [("$9.99", BASE_URL)] + denom_pages
    # Deduplicate
    seen_pages: set[str] = set()
    unique_pages = []
    for label, url in all_pages:
        if url not in seen_pages:
            unique_pages.append((label, url))
            seen_pages.add(url)

    print(f"Found {len(unique_pages)} denomination page(s):\n")
    for label, url in unique_pages:
        print(f"  {label:40s}  {url}")

    # Collect all unique offer links across all denomination pages
    print("\nStep 2 — Collecting offers.greatclips.com links from each page...\n")
    all_offer_links: dict[str, list[str]] = {}  # url -> [denomination labels]
    for label, page_url in unique_pages:
        time.sleep(DELAY)
        soup = fetch(page_url)
        if soup is None:
            continue
        links = collect_offer_links(soup)
        print(f"  {label}: {len(links)} offer link(s)")
        for lnk in links:
            all_offer_links.setdefault(lnk, []).append(label)

    unique_offers = list(all_offer_links.keys())
    print(f"\nTotal unique offer links: {len(unique_offers)}\n")
    print("-" * 70)
    print(f"Step 3 — Checking each link for: {TARGET_CITIES}\n")

    city_hits: dict[str, list[dict]] = {c: [] for c in TARGET_CITIES}
    total = len(unique_offers)

    for idx, offer_url in enumerate(unique_offers, 1):
        labels = ", ".join(all_offer_links[offer_url])
        print(f"[{idx:4d}/{total}] {offer_url}  [{labels}]", end="  ", flush=True)
        time.sleep(DELAY)

        final_url, page_text = get_page_text(offer_url)
        found = cities_in_text(final_url + " " + page_text)
        if found:
            print(f"MATCH: {found}")
            for city in found:
                city_hits[city].append(
                    {
                        "coupon_url": offer_url,
                        "final_url": final_url,
                        "denominations": labels,
                        "snippet": snippet(page_text, city),
                    }
                )
        else:
            print("(no match)")

    # Summary
    print("\n" + "=" * 70)
    print("RESULTS — Great Clips Coupons for Plano / McKinney / Frisco, TX")
    print("=" * 70)

    any_found = False
    for city in TARGET_CITIES:
        hits = city_hits[city]
        if hits:
            any_found = True
            print(f"\n{city.upper()} — {len(hits)} coupon(s) found:")
            for h in hits:
                print(f"  Denomination: {h['denominations']}")
                print(f"  Coupon URL  : {h['coupon_url']}")
                print(f"  Final URL   : {h['final_url']}")
                if h["snippet"]:
                    print(f"  Context     : {h['snippet'][:220]}")
                print()

    if not any_found:
        print(
            "\nNo location-specific coupons found for Plano, McKinney, or Frisco.\n"
            "The coupons on this site appear to be for other regions.\n"
            "For DFW-area Great Clips coupons, try visiting a Plano/Frisco/McKinney\n"
            "Great Clips location directly at https://www.greatclips.com/coupons\n"
            "and entering your zip code."
        )


if __name__ == "__main__":
    main()
