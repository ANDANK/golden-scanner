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
# name       = what shows in the Channel column (short enough for a table cell)
# scored     = feeds the Shorts Perf scoring tab
# channel_id = optional. When present it's used directly and the handle is
#              never resolved -- handles are display names that can be changed
#              by their owner, channel IDs cannot. Worth pinning for any
#              channel whose handle has already proved unreliable.
CHANNELS = [
    {"handle": "@overkilltrading",   "name": "OverKill",        "scored": True},
    {"handle": "@NolanGouveia",      "name": "Nolan Gouveia",   "scored": True},
    {"handle": "@FinancialEducation","name": "Financial Ed",    "scored": True},
    {"handle": "@InvestwithHenry",   "name": "Invest w/ Henry", "scored": True},
    # Was "@InTheMoney", which does not resolve -- the channel's actual handle
    # is @InTheMoneyAdam. It silently produced no rows at all until the
    # absence was spotted against the other channels.
    {"handle": "@InTheMoneyAdam",    "name": "In The Money",    "scored": False},
    {"handle": "@ClearValueTax",     "name": "ClearValue Tax",  "scored": False,
     "channel_id": "UCigUBIf-zt_DA6xyOQtq2WA"},
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
    """Resolve a channel to its uploads playlist ID in one call.

    Prefers an explicit `channel_id` from the registry when one is set, since
    channel IDs are immutable while handles are display names their owner can
    change -- and a handle that stops resolving fails silently, producing a
    channel with no rows and no error until someone notices the gap.

    Returns None if the channel can't be resolved, so one dead entry doesn't
    take the whole run down with it."""
    cfg = _BY_HANDLE.get((handle or "").lower(), {})
    if cfg.get("channel_id"):
        params = {"part": "contentDetails", "id": cfg["channel_id"]}
    else:
        params = {"part": "contentDetails", "forHandle": handle}
    data = _yt_api_get("channels", params)
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
