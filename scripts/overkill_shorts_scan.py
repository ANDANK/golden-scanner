#!/usr/bin/env python3
"""
scripts/overkill_shorts_scan.py — Fully-automated OverKill Shorts pipeline.

Detects new Shorts from @overkilltrading (reuses refresh_overkill_shorts.py's
video-listing logic: get_uploads_playlist_id/list_recent_videos, official
YouTube Data API), fetches each new video's caption transcript via
youtube-transcript-api, and asks Gemini (Google's genuinely-free API tier
-- Anthropic's Developer API is pay-as-you-go with no free tier, a
separate account/billing system from any Claude subscription) to extract
structured ticker/bias/dot/notes picks from it — skipping general market
commentary and any promotional talk about the host's own indicator/course.

This replaces the old detect-only, twice-daily semi-auto pipeline: an
earlier version tried yt-dlp for transcripts and got blocked wholesale by
YouTube's bot-check from GitHub Actions' shared IPs ("Sign in to confirm
you're not a bot" — IP-reputation based). Two issues showed up across the
first two real runs, fixed in order:
  1. A v0.6.3 library pin (kept to preserve the old get_transcript()
     classmethod) returned a false "subtitles are disabled" for every
     video — fixed by moving to the current 1.x API
     (YouTubeTranscriptApi().fetch(...)) and dropping the <1.0 pin.
  2. With that fixed, the REAL error underneath was YouTube's actual
     IP-block: GitHub Actions' hosted runners sit on Google Cloud Platform
     IPs, and YouTube blocks most cloud-provider ranges from the
     transcript endpoint outright (confirmed via the library's own
     explicit "YouTube is blocking requests from your IP... cloud
     provider" error). Not a library bug — a structural block that
     yt-dlp hit too, just with a different, less specific error message.
     Fixed for free by switching the workflow to a self-hosted runner
     (see .github/workflows/refresh_overkill.yml) instead of paying for a
     proxy service — a residential IP isn't in YouTube's blocked ranges.
  3. That runner then fetched all 12 backlog transcripts successfully once,
     and got blocked on every run after — same error text, different cause:
     a volume-based rate-limit, not the cloud-range block. 12 requests in
     ~10 seconds, repeated every run, kept the ban alive because the loop
     carried on firing requests after the first block. Fixed by capping
     attempts per run, spacing them out, and stopping the run on the first
     block (see MAX_TRANSCRIPTS_PER_RUN / THROTTLE_SECONDS below).
The fallback-to-pending path below stays regardless, since transcript
fetches can still fail for legitimate reasons (captions actually off, a
transient error) even from a non-blocked IP.

Successfully-extracted picks are written directly into
data/overkill_shorts.json (no human review step). Any video where the
transcript fetch fails (no captions, disabled, or blocked) or where Gemini
finds no clear ticker calls falls back to data/overkill_pending.json, same
file/shape the old pipeline used — so a failure stays visible on the
OverKill Shorts tab instead of silently vanishing, without requiring a
human step for the common case.

Called by GitHub Actions once daily ~7am CT — see
.github/workflows/refresh_overkill.yml.

Required env vars (GitHub Actions secrets):
  YOUTUBE_API_KEY   YouTube Data API v3 key
  GEMINI_API_KEY    Google AI Studio API key (ai.google.dev) -- free tier,
                    no credit card required; ~1-12 requests/day here is
                    well within the free rate limit

Optional:
  GEMINI_MODEL      Pin a specific model instead of auto-selecting one. Only
                    needed to override the choice -- the script asks the API
                    which models the key can use, so it survives Google
                    retiring a model alias (which took the pinned
                    gemini-2.5-flash out in Aug 2026 with a 404 "no longer
                    available to new users").

Must run on a self-hosted runner (see .github/workflows/refresh_overkill.yml)
-- GitHub's own hosted runners are on cloud IPs YouTube blocks from the
transcript endpoint; without a self-hosted runner online at schedule time,
every video falls back to data/overkill_pending.json instead of being
auto-extracted.

Usage:
  python scripts/overkill_shorts_scan.py
"""

import json, os, re, sys, time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.refresh_overkill_shorts import (
    CHANNEL_ID, _CRYPTO_TITLE_RE, get_uploads_playlist_id, list_recent_videos,
)

DATA_PATH = os.path.join(ROOT, "data", "overkill_shorts.json")
PENDING_PATH = os.path.join(ROOT, "data", "overkill_pending.json")

# Model is DISCOVERED AT RUNTIME, not hardcoded. A pinned "gemini-2.5-flash"
# worked for weeks and then started 404ing mid-August with "no longer
# available to new users" -- Google retires model aliases on its own schedule,
# and this job runs unattended, so a hardcoded name is a scheduled outage.
# Asking the API which models the key can actually use costs one extra call
# per run and can't go stale. Set the GEMINI_MODEL env var to pin a specific
# one if you ever need to override the choice.
GEMINI_MODEL_ENV = "GEMINI_MODEL"

# Non-text models that can't do what we need, filtered out by name.
_MODEL_BLOCKLIST = ("embedding", "aqa", "imagen", "veo", "tts", "image",
                    "vision", "learnlm", "gemma")

# ── YouTube rate-limit hygiene ────────────────────────────────────────
# The self-hosted runner's residential IP is NOT in YouTube's blocked
# cloud-provider ranges -- an early run fetched all 12 backlog transcripts
# fine. What blocked it afterwards was request VOLUME: the script fired 12
# transcript requests in ~10 seconds, every run, at the same video IDs, and
# YouTube rate-limited the IP. Worse, once blocked, the run kept firing the
# remaining 11 requests anyway, so each scheduled run re-confirmed the ban
# and it never got a chance to age out. These three limits break that loop.
MAX_TRANSCRIPTS_PER_RUN = 6   # drain a backlog over a few days rather than in one burst
THROTTLE_SECONDS = 4          # space requests out instead of hammering

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

# Gemini's structured-output schema uses UPPERCASE type names (STRING/OBJECT/
# ARRAY), not standard-JSON-Schema lowercase -- confirmed directly against
# the installed google-genai package (GenerateContentConfig.response_json_schema),
# not assumed from memory, after a couple of wrong assumptions elsewhere in
# this same integration.
_RESPONSE_JSON_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "picks": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "ticker": {"type": "STRING", "description": "Stock ticker symbol, uppercase, no $ prefix"},
                    "bias": {"type": "STRING", "enum": ["Bullish", "Bearish"]},
                    "dot": {"type": "STRING", "enum": ["Green", "Red"]},
                    "notes": {"type": "STRING"},
                },
                "required": ["ticker", "bias", "dot", "notes"],
            },
        },
    },
    "required": ["picks"],
}


def log(msg: str):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


def fetch_transcript(video_id: str) -> str | None:
    """Best-effort caption text for a video. Returns None for the ordinary
    per-video failures (no captions, captions disabled, transient error);
    those just send that one video to the pending list.

    RequestBlocked (and its IpBlocked subclass) deliberately propagates
    instead: that's an IP-level condition, not a per-video one, so every
    remaining video this run would fail too — and each extra request while
    blocked only re-confirms the rate-limit. The caller stops the run on it.

    Must run from a residential IP (a self-hosted runner, per this repo's
    workflow) — GitHub's own hosted runners sit on Google Cloud IPs, which
    YouTube blocks outright from this endpoint, confirmed directly."""
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import RequestBlocked
    try:
        result = YouTubeTranscriptApi().fetch(video_id)
        text = " ".join(seg.text for seg in result).strip()
        return text or None
    except RequestBlocked:
        raise
    except Exception as e:
        log(f"  transcript unavailable for {video_id}: {e}")
        return None


def _model_rank(name: str):
    """Sort key, most-preferred first:
      1. flash before pro   -- faster and far more generous on the free tier
      2. '-latest' aliases  -- self-updating, so they can't go stale on us
      3. stable before preview/experimental
      4. newest version
      5. full before lite   -- last, and deliberately so: a stable current-gen
         lite model beats an experimental older full one for a job this simple
         (short transcript in, small JSON out)."""
    s = name.lower()
    ver = re.search(r"(\d+)(?:\.(\d+))?", s)
    major, minor = (int(ver.group(1)), int(ver.group(2) or 0)) if ver else (0, 0)
    return (
        0 if "flash" in s else 1,
        0 if "latest" in s else 1,
        0 if ("preview" not in s and "exp" not in s) else 1,
        -major, -minor,
        0 if "lite" not in s else 1,
        s,
    )


def usable_models(client) -> list[str]:
    """Models this API key can actually call generateContent on, best first.
    A GEMINI_MODEL override short-circuits the lookup entirely."""
    override = os.environ.get(GEMINI_MODEL_ENV, "").strip()
    if override:
        log(f"Using pinned model from {GEMINI_MODEL_ENV}: {override}")
        return [override]

    names = []
    for m in client.models.list():
        if "generateContent" not in (m.supported_actions or []):
            continue
        name = (m.name or "").split("/")[-1]
        if name and not any(b in name.lower() for b in _MODEL_BLOCKLIST):
            names.append(name)
    if not names:
        raise RuntimeError("No Gemini model supporting generateContent is available "
                           "to this API key.")
    names.sort(key=_model_rank)
    log(f"Model candidates ({len(names)}), best first: {', '.join(names[:5])}"
        + (" ..." if len(names) > 5 else ""))
    return names


_WORKING_MODEL: str | None = None   # cached across videos within a run


def extract_picks(client, models: list[str], transcript: str) -> list[dict]:
    """Extract picks, falling through the candidate list on a model-not-found.
    The first model that answers is remembered for the rest of the run, so the
    fallback costs at most one wasted call rather than one per video."""
    from google.genai import types

    global _WORKING_MODEL
    order = ([_WORKING_MODEL] if _WORKING_MODEL else []) + \
            [m for m in models if m != _WORKING_MODEL]

    last_err = None
    for model in order:
        try:
            response = client.models.generate_content(
                model=model,
                contents=f"{_SYSTEM_PROMPT}\n\nTranscript:\n\n{transcript}",
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=_RESPONSE_JSON_SCHEMA,
                ),
            )
        except Exception as e:
            # Only a missing/retired model is worth trying the next candidate
            # for; quota, auth and network errors would fail identically on
            # every model, so re-raise those immediately.
            if "NOT_FOUND" not in str(e) and "404" not in str(e):
                raise
            log(f"  model {model} unavailable, trying next candidate")
            last_err = e
            continue
        if model != _WORKING_MODEL:
            log(f"  using model: {model}")
            _WORKING_MODEL = model
        if not response.text:
            return []
        picks = json.loads(response.text).get("picks", [])
        # Defensive: enforce the bias<->dot pairing even if the model drifts from the rule.
        for p in picks:
            p["dot"] = "Green" if p.get("bias") == "Bullish" else "Red"
        return picks

    raise RuntimeError(f"No usable Gemini model among {order}: {last_err}")


def main():
    if not os.environ.get("YOUTUBE_API_KEY"):
        log("ERROR: YOUTUBE_API_KEY not set — add it as a GitHub Actions secret.")
        sys.exit(1)
    if not os.environ.get("GEMINI_API_KEY"):
        log("ERROR: GEMINI_API_KEY not set — add it as a GitHub Actions secret.")
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

    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    models = usable_models(client)

    from youtube_transcript_api._errors import RequestBlocked

    # Newest first, so a backlog drains most-recent-first -- old Shorts are
    # the least useful to capture late anyway.
    attempts = candidates[:MAX_TRANSCRIPTS_PER_RUN]
    deferred = candidates[MAX_TRANSCRIPTS_PER_RUN:]
    if deferred:
        log(f"Attempting {len(attempts)} this run (cap={MAX_TRANSCRIPTS_PER_RUN}); "
            f"{len(deferred)} deferred to the next run.")

    new_videos, still_pending = [], list(deferred)
    for i, v in enumerate(attempts):
        if i:
            time.sleep(THROTTLE_SECONDS)
        try:
            transcript = fetch_transcript(v["video_id"])
        except RequestBlocked as e:
            # IP-level block: every remaining request would fail AND would
            # extend the rate-limit window, so stop here and let it age out.
            remaining = attempts[i:]
            log(f"  YouTube is rate-limiting/blocking this IP ({type(e).__name__}) — "
                f"stopping after {i} fetch(es) rather than firing {len(remaining)} more "
                f"doomed requests, which would only extend the block. "
                f"Retrying on the next scheduled run.")
            still_pending.extend(remaining)
            break
        if transcript is None:
            still_pending.append(v)
            continue
        try:
            picks = extract_picks(client, models, transcript)
        except Exception as e:
            log(f"  Gemini extraction failed for {v['video_id']}: {e}")
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

    # Deferred-by-cap and blocked entries get appended in different passes
    # above; re-sort so the tab shows newest-first regardless of which.
    still_pending.sort(key=lambda v: v["date"], reverse=True)

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
