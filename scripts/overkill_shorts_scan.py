#!/usr/bin/env python3
"""
scripts/overkill_shorts_scan.py — Fully-automated OverKill Shorts pipeline.

Detects new Shorts from @overkilltrading (reuses refresh_overkill_shorts.py's
video-listing logic: get_uploads_playlist_id/list_recent_videos, official
YouTube Data API), fetches each new video's caption transcript via
youtube-transcript-api, and asks Claude (Anthropic API) to extract
structured ticker/bias/dot/notes picks from it — skipping general market
commentary and any promotional talk about the host's own indicator/course.

This replaces the old detect-only, twice-daily semi-auto pipeline: an
earlier version tried yt-dlp for transcripts and got blocked wholesale by
YouTube's bot-check from GitHub Actions' shared IPs ("Sign in to confirm
you're not a bot" — IP-reputation based). youtube-transcript-api hits a
different, lighter endpoint (the public caption/timedtext API, not a full
video-extraction pipeline), so it has a real chance of not sharing that
exact failure mode — but this is NOT guaranteed until proven by an actual
scheduled run from GitHub Actions, which is the whole reason the code
below still has a fallback path.

Successfully-extracted picks are written directly into
data/overkill_shorts.json (no human review step). Any video where the
transcript fetch fails (no captions, disabled, or blocked) or where Claude
finds no clear ticker calls falls back to data/overkill_pending.json, same
file/shape the old pipeline used — so a failure stays visible on the
OverKill Shorts tab instead of silently vanishing, without requiring a
human step for the common case.

Called by GitHub Actions once daily ~7am CT — see
.github/workflows/refresh_overkill.yml.

Required env vars (GitHub Actions secrets):
  YOUTUBE_API_KEY      YouTube Data API v3 key (existing secret)
  ANTHROPIC_API_KEY    Claude API key (new secret)

Usage:
  python scripts/overkill_shorts_scan.py
"""

import json, os, re, sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.refresh_overkill_shorts import (
    CHANNEL_ID, _CRYPTO_TITLE_RE, get_uploads_playlist_id, list_recent_videos,
)

DATA_PATH = os.path.join(ROOT, "data", "overkill_shorts.json")
PENDING_PATH = os.path.join(ROOT, "data", "overkill_pending.json")

CLAUDE_MODEL = "claude-haiku-4-5-20251001"   # cheap/fast, sufficient for a short structured-extraction task

_SYSTEM_PROMPT = """You extract structured stock picks from a trading YouTube Short's transcript.

Rules:
- Only include tickers the host gives a specific directional call on (bullish/buy or bearish/sell-short).
- "bias" and "dot" always pair together: Bullish -> Green, Bearish -> Red.
- "notes" is a concise 1-2 sentence summary of what the host specifically said about THAT ticker
  (price levels, targets, catalysts, risk) in his own words/reasoning — not generic commentary.
- Skip: general market commentary not tied to one specific ticker, and any talk about the host's
  own indicator, course, Discord, sponsorships, or other promotional content.
- If the transcript has no clear ticker calls at all, return an empty picks list — don't force one.
- Never invent a ticker or price level that isn't actually stated in the transcript."""

_EXTRACT_TOOL = {
    "name": "extract_picks",
    "description": "Record the stock ticker calls found in a trading video transcript.",
    "input_schema": {
        "type": "object",
        "properties": {
            "picks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string", "description": "Stock ticker symbol, uppercase, no $ prefix"},
                        "bias": {"type": "string", "enum": ["Bullish", "Bearish"]},
                        "dot": {"type": "string", "enum": ["Green", "Red"]},
                        "notes": {"type": "string"},
                    },
                    "required": ["ticker", "bias", "dot", "notes"],
                },
            },
        },
        "required": ["picks"],
    },
}


def log(msg: str):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


def fetch_transcript(video_id: str) -> str | None:
    """Best-effort caption text for a video. Returns None if unavailable —
    no captions, captions disabled, or the fetch itself fails/gets blocked.
    Pulls whatever caption track YouTube offers (manual or auto-generated);
    doesn't distinguish, since this channel has captions on either way."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        segments = YouTubeTranscriptApi.get_transcript(video_id)
        text = " ".join(seg["text"] for seg in segments).strip()
        return text or None
    except Exception as e:
        log(f"  transcript unavailable for {video_id}: {e}")
        return None


def extract_picks(client, transcript: str) -> list[dict]:
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        tools=[_EXTRACT_TOOL],
        tool_choice={"type": "tool", "name": "extract_picks"},
        messages=[{"role": "user", "content": f"Transcript:\n\n{transcript}"}],
    )
    for block in resp.content:
        if block.type == "tool_use" and block.name == "extract_picks":
            picks = block.input.get("picks", [])
            # Defensive: enforce the bias<->dot pairing even if the model drifts from the rule.
            for p in picks:
                p["dot"] = "Green" if p.get("bias") == "Bullish" else "Red"
            return picks
    return []


def main():
    if not os.environ.get("YOUTUBE_API_KEY"):
        log("ERROR: YOUTUBE_API_KEY not set — add it as a GitHub Actions secret.")
        sys.exit(1)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log("ERROR: ANTHROPIC_API_KEY not set — add it as a GitHub Actions secret.")
        sys.exit(1)

    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)

    known_ids = set()
    for v in data.get("videos", []):
        m = re.search(r"shorts/([\w-]+)", v.get("url", ""))
        if m:
            known_ids.add(m.group(1))

    playlist_id = get_uploads_playlist_id()
    recent = list_recent_videos(playlist_id)
    candidates = [v for v in recent if v["video_id"] not in known_ids
                  and not _CRYPTO_TITLE_RE.search(v["title"])]
    log(f"Checked {len(recent)} recent upload(s) from {CHANNEL_ID}; "
        f"{len(known_ids)} already known; {len(candidates)} new non-crypto candidate(s).")

    if not candidates:
        # Still rewrite pending (even to empty) so stale entries drop off once captured elsewhere.
        with open(PENDING_PATH, "w", encoding="utf-8") as f:
            json.dump({"checked": recent[0]["date"] if recent else None, "pending": []}, f,
                      indent=2, ensure_ascii=False)
            f.write("\n")
        log("Nothing new — done.")
        return

    from anthropic import Anthropic
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    new_videos, still_pending = [], []
    for v in candidates:
        transcript = fetch_transcript(v["video_id"])
        if transcript is None:
            still_pending.append(v)
            continue
        try:
            picks = extract_picks(client, transcript)
        except Exception as e:
            log(f"  Claude extraction failed for {v['video_id']}: {e}")
            still_pending.append(v)
            continue
        if not picks:
            log(f"  no ticker picks found in {v['video_id']} ({v['title']}) — has a transcript, "
                f"just nothing to extract, so not added to pending either.")
            continue
        new_videos.append({
            "date": v["date"],
            "url": f"https://www.youtube.com/shorts/{v['video_id']}",
            "title": v["title"],
            "picks": picks,
        })
        log(f"  extracted {len(picks)} pick(s) from {v['video_id']} ({v['title']}): "
            f"{', '.join(p['ticker'] for p in picks)}")

    if new_videos:
        data["videos"] = new_videos + data.get("videos", [])
        data["updated"] = recent[0]["date"] if recent else data.get("updated")
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        log(f"Wrote {len(new_videos)} new video(s), "
            f"{sum(len(v['picks']) for v in new_videos)} pick(s) total, to {DATA_PATH}.")

    with open(PENDING_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "checked": recent[0]["date"] if recent else None,
            "pending": [{
                "video_id": v["video_id"], "title": v["title"], "date": v["date"],
                "url": f"https://www.youtube.com/shorts/{v['video_id']}",
            } for v in still_pending],
        }, f, indent=2, ensure_ascii=False)
        f.write("\n")
    log(f"{len(still_pending)} still pending (transcript unavailable or extraction failed).")


if __name__ == "__main__":
    main()
