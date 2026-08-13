#!/usr/bin/env python3
"""
scripts/refresh_overkill_shorts.py — video-listing library for OverKill Shorts.

No longer scheduled on its own — scripts/overkill_shorts_scan.py (the full
detect -> fetch transcript -> Claude-extract pipeline, run daily by
.github/workflows/refresh_overkill.yml) imports get_uploads_playlist_id(),
list_recent_videos(), CHANNEL_ID, and _CRYPTO_TITLE_RE from this file rather
than duplicating them. Kept as a standalone, runnable script too (below)
purely as a manual debug tool — running it directly still does the old
detect-only behavior (writes candidates to data/overkill_pending.json,
no transcript/extraction), useful for checking what the channel has posted
without touching data/overkill_shorts.json.

Lists the @overkilltrading channel's newest YouTube Shorts via the official
YouTube Data API and compares against what's already captured in
data/overkill_shorts.json. The official Data API call here is a normal
authenticated request, not scraping, so it's unaffected by the bot-check
that blocks yt-dlp-based video/transcript pulls from GitHub Actions'
shared IP ranges (see overkill_shorts_scan.py's docstring for that history).

Requires env var: YOUTUBE_API_KEY.

Usage:
  python scripts/refresh_overkill_shorts.py
"""

import json, os, re

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(ROOT, "data", "overkill_shorts.json")
PENDING_PATH = os.path.join(ROOT, "data", "overkill_pending.json")

CHANNEL_ID = "UCmN5oK_nYL55aannadOlrqg"   # @overkilltrading
MAX_VIDEOS_TO_CHECK = 40                  # how far back to look each run (uploads playlist mixes
                                           # Shorts + long-form videos, so this must be generous)

# Light heuristic just to declutter the pending list — final crypto/stock call
# still happens when someone actually reviews the video, this only hides the
# obvious ones (titles observed on this channel consistently say one of these).
_CRYPTO_TITLE_RE = re.compile(r"\b(crypto|altcoin)s?\b", re.IGNORECASE)


def _yt_api_get(path: str, params: dict) -> dict:
    params = {**params, "key": os.environ["YOUTUBE_API_KEY"]}
    r = requests.get(f"https://www.googleapis.com/youtube/v3/{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def get_uploads_playlist_id() -> str:
    data = _yt_api_get("channels", {"part": "contentDetails", "id": CHANNEL_ID})
    return data["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]


def list_recent_videos(playlist_id: str, max_results: int = MAX_VIDEOS_TO_CHECK) -> list:
    data = _yt_api_get("playlistItems", {
        "part": "snippet", "playlistId": playlist_id, "maxResults": max_results,
    })
    out = []
    for item in data.get("items", []):
        sn = item["snippet"]
        rid = sn.get("resourceId", {})
        if rid.get("kind") != "youtube#video":
            continue
        out.append({
            "video_id": rid["videoId"],
            "title": sn["title"],
            "date": sn["publishedAt"][:10],
        })
    return out


def main():
    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)

    known_ids = set()
    for v in data.get("videos", []):
        m = re.search(r"shorts/([\w-]+)", v.get("url", ""))
        if m:
            known_ids.add(m.group(1))

    playlist_id = get_uploads_playlist_id()
    recent = list_recent_videos(playlist_id)
    candidates = [v for v in recent if v["video_id"] not in known_ids]

    print(f"Checked {len(recent)} most recent uploads (limit={MAX_VIDEOS_TO_CHECK}); "
          f"{len(known_ids)} already known; {len(candidates)} new candidate(s).")
    if recent:
        oldest = recent[-1]
        print(f"  oldest upload in this window: {oldest['date']} — {oldest['title']}")

    likely_stock = [v for v in candidates if not _CRYPTO_TITLE_RE.search(v["title"])]
    likely_crypto = len(candidates) - len(likely_stock)
    print(f"  {len(likely_stock)} look non-crypto by title, {likely_crypto} look crypto-only (title heuristic).")

    pending = [{
        "video_id": v["video_id"],
        "title": v["title"],
        "date": v["date"],
        "url": f"https://www.youtube.com/shorts/{v['video_id']}",
    } for v in likely_stock]

    # Always rewrite (even to empty) so items that got captured since the last
    # run correctly drop off the pending list.
    with open(PENDING_PATH, "w", encoding="utf-8") as f:
        json.dump({"checked": recent[0]["date"] if recent else None, "pending": pending}, f,
                  indent=2, ensure_ascii=False)
        f.write("\n")

    if pending:
        print(f"Wrote {len(pending)} pending candidate(s) to {PENDING_PATH} — ask Claude to review them.")
    else:
        print("No new non-crypto candidates — pending list cleared.")


if __name__ == "__main__":
    main()
