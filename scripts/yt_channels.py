#!/usr/bin/env python3
"""
scripts/yt_channels.py — the YouTube channels the Shorts scanner watches.

Handles are stored as written rather than as opaque channel IDs: the Data
API's `forHandle` parameter resolves "@NolanGouveia" to its channel ID at
request time, so adding a channel here means pasting the handle from the URL
and nothing else. Costs one extra API unit per channel per run against a
10,000/day quota, which is not worth optimising away for the readability.

`scored` decides whether a channel's picks reach the Shorts Perf tab. It is
False for channels whose Shorts are mostly tax, macro or personal-finance
commentary rather than directional trade calls -- their tickers would dilute
a hit rate that is supposed to mean "how good were the calls".

Requires env var: YOUTUBE_API_KEY.
"""

import os

import requests

# ── The watchlist ────────────────────────────────────────────────────────
# name  = what shows in the Channel column (short enough for a table cell)
# scored = feeds the Shorts Perf scoring tab
CHANNELS = [
    {"handle": "@overkilltrading",   "name": "OverKill",        "scored": True},
    {"handle": "@NolanGouveia",      "name": "Nolan Gouveia",   "scored": True},
    {"handle": "@FinancialEducation","name": "Financial Ed",    "scored": True},
    {"handle": "@InvestwithHenry",   "name": "Invest w/ Henry", "scored": True},
    {"handle": "@InTheMoney",        "name": "In The Money",    "scored": False},
    {"handle": "@ClearValueTax",     "name": "ClearValue Tax",  "scored": False},
    {"handle": "@MinorityMindset",   "name": "Minority Mindset","scored": False},
]

MAX_VIDEOS_PER_CHANNEL = 25   # how far back to look per channel each run; the
                              # uploads playlist mixes Shorts with long-form,
                              # so this needs headroom over the Shorts count

_BY_HANDLE = {c["handle"].lower(): c for c in CHANNELS}
SCORED_HANDLES = {c["handle"] for c in CHANNELS if c["scored"]}


def channel_name(handle: str) -> str:
    """Display name for a handle, falling back to the handle itself so a
    channel removed from the registry still renders sensibly in old rows."""
    c = _BY_HANDLE.get((handle or "").lower())
    return c["name"] if c else (handle or "Unknown")


def is_scored(handle: str) -> bool:
    return (handle or "") in SCORED_HANDLES


def _yt_api_get(path: str, params: dict) -> dict:
    params = {**params, "key": os.environ["YOUTUBE_API_KEY"]}
    r = requests.get(f"https://www.googleapis.com/youtube/v3/{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def uploads_playlist_for_handle(handle: str) -> str | None:
    """Resolve a @handle straight to its uploads playlist ID in one call.
    Returns None if the handle no longer resolves -- a renamed or deleted
    channel shouldn't take the whole run down with it."""
    data = _yt_api_get("channels", {"part": "contentDetails", "forHandle": handle})
    items = data.get("items") or []
    if not items:
        return None
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def list_recent_videos(playlist_id: str, max_results: int = MAX_VIDEOS_PER_CHANNEL) -> list:
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
