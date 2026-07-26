#!/usr/bin/env python3
"""
scripts/refresh_overkill_shorts.py — Auto-refresh the Over Kill tab's picks.

Called by GitHub Actions twice daily. Pulls the @overkilltrading channel's
newest YouTube Shorts (via the YouTube Data API), skips ones already in
data/overkill_shorts.json, fetches each new video's auto-caption transcript
(via yt-dlp), and asks Claude to extract structured stock picks (ticker,
bias, wave-indicator dot, notes) from the transcript. Crypto-only Shorts are
dropped. Writes new videos to the front of data/overkill_shorts.json.

Requires env vars: YOUTUBE_API_KEY, ANTHROPIC_API_KEY.

Usage:
  python scripts/refresh_overkill_shorts.py
"""

import json, os, re, subprocess, sys, tempfile
from datetime import datetime, timezone

import requests
import anthropic

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(ROOT, "data", "overkill_shorts.json")

CHANNEL_ID = "UCmN5oK_nYL55aannadOlrqg"   # @overkilltrading
MODEL = "claude-opus-4-8"
MAX_VIDEOS_TO_CHECK = 40                  # how far back to look each run (uploads playlist mixes
                                           # Shorts + long-form videos, so this must be generous)

PICK_SCHEMA = {
    "type": "object",
    "properties": {
        "is_crypto": {
            "type": "boolean",
            "description": "true if this Short is primarily about cryptocurrency rather than stocks/ETFs",
        },
        "picks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol, e.g. HOOD. If never said aloud, infer it from context "
                                       "(company description, contracts mentioned, price levels/history) using your "
                                       "own knowledge. Omit the pick entirely if you can't identify the ticker with "
                                       "reasonable confidence.",
                    },
                    "bias": {"type": "string", "enum": ["Bullish", "Bearish", "Neutral"]},
                    "dot": {
                        "type": "string",
                        "enum": ["Green", "Red", "None"],
                        "description": "The wave-indicator signal as stated in the video: Green=buy, Red=sell/trim, None=not formed/not mentioned",
                    },
                    "notes": {
                        "type": "string",
                        "description": "1-3 terse sentences: the specific price levels, dates, and plan mentioned for this ticker, "
                                       "written like a trading journal entry (matches the style of an experienced trader's notes).",
                    },
                },
                "required": ["ticker", "bias", "dot", "notes"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["is_crypto", "picks"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You extract structured stock picks from a trading YouTube Short's auto-generated caption transcript. "
    "The channel (Overkill Trading) uses a proprietary 'wave indicator': a Green dot is a buy signal, a Red dot "
    "is a sell/trim signal, stated explicitly in the video. Classify each ticker's overall directional bias as "
    "Bullish, Bearish, or Neutral based on what the trader says. Auto-captions are imperfect — use context to "
    "correct obvious transcription errors (e.g. company names, dollar amounts). Only extract stock/ETF picks; "
    "if the video is primarily about cryptocurrency, set is_crypto to true and return an empty picks list."
)


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


def _vtt_to_text(path: str) -> str:
    lines = open(path, encoding="utf-8").read().splitlines()
    out = []
    for ln in lines:
        s = ln.strip()
        if not s or s == "WEBVTT" or "-->" in s or s.isdigit():
            continue
        s = re.sub(r"<[^>]+>", "", s)
        if not out or out[-1] != s:
            out.append(s)
    return " ".join(out)


def fetch_transcript(video_id: str) -> str | None:
    """Pull the auto-generated English caption track via yt-dlp and flatten it to plain text."""
    with tempfile.TemporaryDirectory() as tmp:
        out_tmpl = os.path.join(tmp, video_id)
        try:
            subprocess.run(
                ["yt-dlp", "--skip-download", "--write-auto-sub", "--sub-lang", "en",
                 "--sub-format", "vtt", "-o", out_tmpl, f"https://www.youtube.com/watch?v={video_id}"],
                check=True, capture_output=True, timeout=120, text=True,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"  yt-dlp failed for {video_id}: {e}", file=sys.stderr)
            return None
        vtt_path = f"{out_tmpl}.en.vtt"
        if not os.path.exists(vtt_path):
            return None
        return _vtt_to_text(vtt_path)


def extract_picks(client: anthropic.Anthropic, title: str, transcript: str) -> dict:
    resp = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": PICK_SCHEMA}},
        messages=[{"role": "user", "content": f"Video title: {title}\n\nTranscript:\n{transcript}"}],
    )
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


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

    if not candidates:
        print("No new videos since last refresh.")
        return

    client = anthropic.Anthropic()
    new_videos = []
    for v in candidates:
        print(f"Checking new video: {v['title']} ({v['video_id']})")
        transcript = fetch_transcript(v["video_id"])
        if not transcript:
            print("  no transcript available, skipping")
            continue
        try:
            result = extract_picks(client, v["title"], transcript)
        except Exception as e:
            print(f"  extraction failed: {e}", file=sys.stderr)
            continue
        if result.get("is_crypto") or not result.get("picks"):
            print("  crypto or no picks, skipping")
            continue
        new_videos.append({
            "title": v["title"],
            "date": v["date"],
            "url": f"https://www.youtube.com/shorts/{v['video_id']}",
            "picks": result["picks"],
        })
        print(f"  added {len(result['picks'])} pick(s)")

    if not new_videos:
        print("No new non-crypto stock Shorts found.")
        return

    data["videos"] = new_videos + data.get("videos", [])
    data["updated"] = max(v["date"] for v in new_videos)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote {len(new_videos)} new video(s) to {DATA_PATH}")


if __name__ == "__main__":
    main()
