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

import json, os, random, re, sys, time
from datetime import datetime, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.refresh_overkill_shorts import _CRYPTO_TITLE_RE
from scripts import yt_channels

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
MAX_TRANSCRIPTS_PER_RUN = 10  # total per run across ALL channels
MAX_PER_CHANNEL_PER_RUN = 2   # ...and at most this many from any one channel, so a
                              # prolific channel can't starve the others

# Spacing matters more than the daily total -- YouTube's limiter reacts to
# request RATE in a short window, and the run that got us blocked fired 12
# requests in ~10 seconds (~72/min). Widening from 4s to 6-8s means 10 requests
# now spread over ~65 seconds (~9/min), which is a LOWER rate than the 6-at-4s
# setting it replaces (~18/min) despite fetching more per run. The jitter is
# deliberate: perfectly even intervals are an obvious automation signature.
THROTTLE_SECONDS = 6          # base gap between transcript fetches
THROTTLE_JITTER = 2           # plus a random 0-2s, so the cadence isn't metronomic

_SYSTEM_PROMPT = """You extract structured takeaways from a finance/investing YouTube Short's transcript.

Return one entry per distinct point the host makes. There are two kinds:

1. TICKER CALL — the host gives a specific directional view on a specific stock.
   - Set "ticker" to the symbol (uppercase, no $ prefix) and "bias" to Bullish or Bearish.
   - "notes" summarises in 1-2 sentences what he said about THAT ticker: price levels,
     targets, catalysts, risks, in his own reasoning.

2. GENERAL TAKEAWAY — a substantive point with no single stock attached: a Fed or rate
   call, a tax rule or deadline, an economic datapoint, a market-wide view, a concrete
   personal-finance action.
   - Leave "ticker" as an empty string and set "bias" to Neutral.
   - "notes" states the takeaway in 1-2 sentences, specific enough to be useful later.

Rules:
- Never invent a ticker, price or figure that isn't actually stated in the transcript.
- If a point names several tickers, emit one entry per ticker.
- Skip promotional content entirely: the host's own course, newsletter, Discord, indicator,
  sponsor reads, "link in bio", giveaways.
- Skip filler with no informational content ("markets were wild today", "comment below").
- If the transcript has nothing substantive at all, return an empty list — never force one."""

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
                    "ticker": {"type": "STRING",
                               "description": "Stock ticker, uppercase, no $ prefix. "
                                              "Empty string for a general takeaway."},
                    "bias": {"type": "STRING", "enum": ["Bullish", "Bearish", "Neutral"]},
                    "notes": {"type": "STRING"},
                },
                # `dot` used to live here as Green/Red. It was derived one-to-one
                # from `bias` (Bullish -> Green), so it carried no information the
                # Bias column didn't already show, and it made no sense at all for
                # channels that don't trade a dot indicator. Dropped; the table
                # column it occupied now shows the source Channel instead.
                "required": ["ticker", "bias", "notes"],
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


_YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{}"
_YAHOO_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")


def fetch_pick_price(ticker: str, date_str: str) -> float | None:
    """Close price for `ticker` on the day the call was made (first close on
    or after the video's date), which is what a 7pm run sees as today's close
    and a 7am run sees as yesterday's.

    Pegged to the VIDEO's date rather than "price right now" on purpose: when
    a backlog video from three weeks ago finally gets processed, today's price
    would be a badly misleading entry price for performance tracking. For a
    freshly-posted Short the two are the same thing anyway.

    Hits Yahoo's chart JSON directly through requests instead of yfinance --
    the runner has no pandas/numpy/yfinance, and installing them on its Python
    3.14 to obtain one number risks breaking a pipeline that finally works.
    Always best-effort: a price lookup must never cost us an extracted pick,
    so failures return None and the UI shows a dash."""
    try:
        r = requests.get(_YAHOO_CHART.format(ticker),
                         params={"range": "6mo", "interval": "1d"},
                         headers={"User-Agent": _YAHOO_UA}, timeout=20)
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        stamps = res.get("timestamp") or []
        closes = ((res.get("indicators", {}).get("quote") or [{}])[0] or {}).get("close") or []
        target = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
        for ts, close in zip(stamps, closes):
            if close is not None and ts >= target:
                return round(float(close), 2)
        done = [c for c in closes if c is not None]      # date is past the last bar
        return round(float(done[-1]), 2) if done else None
    except Exception as e:
        log(f"  price lookup failed for {ticker}: {e}")
        return None


def _model_rank(name: str):
    """Sort key, most-preferred first:
      1. flash before pro   -- faster and far more generous on the free tier
      2. stable before preview/experimental
      3. newest version     -- unversioned '-latest' aliases sort to the BACK
         of their group, deliberately. They were ranked first at one point for
         staleness protection, but discovering the list at runtime already
         gives us that, and '-latest' is the busiest alias on the service:
         gemini-flash-latest returned 503 "high demand" on 5 of 6 videos in a
         single run. A pinned current version is the quieter door.
      4. full before lite   -- last, and deliberately so: a stable current-gen
         lite model beats an experimental older full one for a job this simple
         (short transcript in, small JSON out)."""
    s = name.lower()
    ver = re.search(r"(\d+)(?:\.(\d+))?", s)
    major, minor = (int(ver.group(1)), int(ver.group(2) or 0)) if ver else (0, 0)
    return (
        0 if "flash" in s else 1,
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

# A retired model. Move on immediately -- no amount of waiting brings it back.
_MODEL_GONE = ("404", "NOT_FOUND")

# Transient. Crucially, 503 "high demand" is PER-MODEL load, not account-wide:
# gemini-flash-latest served one video and 503'd on five others in the same
# run. An earlier version of this function re-raised everything that wasn't a
# 404, on the assumption that any other error "would fail identically on every
# model" -- that assumption was wrong, and it threw away five transcripts that
# had been fetched successfully. Try a different model, then wait and retry.
_TRANSIENT = ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED",
              "500", "INTERNAL", "deadline", "timeout", "timed out")

MODELS_PER_VIDEO = 3        # distinct models to try before backing off
RETRY_BACKOFF = (0, 10)     # seconds before each pass; len() == number of passes


def extract_picks(client, models: list[str], transcript: str) -> list[dict]:
    """Extract picks, moving to another model when one is retired or busy and
    backing off if the whole shortlist is busy at once. The model that answers
    is remembered for the rest of the run, so the search costs at most a few
    wasted calls per run rather than repeating for every video.

    Kept deliberately narrow: auth, permission and malformed-request errors
    re-raise on the first try, since those really would fail identically
    everywhere and retrying them just burns quota."""
    from google.genai import types

    global _WORKING_MODEL
    order = ([_WORKING_MODEL] if _WORKING_MODEL in models else []) + \
            [m for m in models if m != _WORKING_MODEL]
    shortlist = order[:MODELS_PER_VIDEO]

    last_err = None
    for attempt, wait in enumerate(RETRY_BACKOFF):
        if wait:
            log(f"  all {len(shortlist)} candidate model(s) busy — waiting {wait}s "
                f"before retrying")
            time.sleep(wait)
        for model in shortlist:
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
                msg = str(e)
                if any(t in msg for t in _MODEL_GONE):
                    log(f"  model {model} retired, trying next candidate")
                elif any(t in msg for t in _TRANSIENT):
                    log(f"  model {model} busy, trying next candidate")
                else:
                    raise
                last_err = e
                continue

            if model != _WORKING_MODEL:
                log(f"  using model: {model}")
                _WORKING_MODEL = model
            if not response.text:
                return []
            picks = json.loads(response.text).get("picks", [])
            # Normalise what the model returns rather than trusting it: tickers
            # uppercased and stripped of a stray $, and any entry without a
            # ticker forced to Neutral so a general takeaway can never be
            # mistaken for a directional call by the scoring tab.
            clean = []
            for p in picks:
                ticker = (p.get("ticker") or "").strip().lstrip("$").upper()
                notes = (p.get("notes") or "").strip()
                if not notes:
                    continue
                bias = p.get("bias") if p.get("bias") in ("Bullish", "Bearish") else "Neutral"
                clean.append({
                    "ticker": ticker,
                    "bias": bias if ticker else "Neutral",
                    "notes": notes,
                })
            return clean

    raise RuntimeError(
        f"All {len(shortlist)} candidate models unavailable after "
        f"{len(RETRY_BACKOFF)} passes ({', '.join(shortlist)}): {last_err}")


def _emit_new_pick_count(n: int):
    """Publish the count as a GitHub Actions step output so the workflow can
    skip the digest email when a run found nothing. The channel doesn't post
    daily and this runs twice a day, so without this most emails would be
    announcing that nothing happened. No-op outside Actions."""
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"new_picks={n}\n")
    log(f"new_picks={n}")


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

    # ── Gather candidates from every watched channel ──────────────────
    per_channel: dict[str, list] = {}
    newest_date = None
    for ch in yt_channels.CHANNELS:
        handle = ch["handle"]
        try:
            playlist_id = yt_channels.uploads_playlist_for_handle(handle)
            if not playlist_id:
                log(f"  {handle}: handle did not resolve — skipping this channel.")
                continue
            recent = yt_channels.list_recent_videos(playlist_id)
        except Exception as e:
            # One bad channel shouldn't cost us the whole run.
            log(f"  {handle}: listing failed ({e}) — skipping this channel.")
            continue
        if recent and (newest_date is None or recent[0]["date"] > newest_date):
            newest_date = recent[0]["date"]
        fresh = [{**v, "channel": handle, "channel_name": ch["name"]}
                 for v in recent
                 if v["video_id"] not in known_ids
                 and not _CRYPTO_TITLE_RE.search(v["title"])]
        per_channel[handle] = fresh
        log(f"  {ch['name']:<16} {len(recent):>3} recent · {len(fresh):>3} new")

    # Round-robin across channels so one prolific poster can't consume the
    # whole run's budget while the others go unread for days.
    candidates, round_no = [], 0
    while len(candidates) < MAX_TRANSCRIPTS_PER_RUN and round_no < MAX_PER_CHANNEL_PER_RUN:
        added = False
        for handle in per_channel:
            if len(candidates) >= MAX_TRANSCRIPTS_PER_RUN:
                break
            if len(per_channel[handle]) > round_no:
                candidates.append(per_channel[handle][round_no])
                added = True
        if not added:
            break
        round_no += 1

    total_new = sum(len(v) for v in per_channel.values())
    deferred = [v for lst in per_channel.values() for v in lst if v not in candidates]
    log(f"{len(known_ids)} already known; {total_new} new candidate(s) across "
        f"{len(per_channel)} channel(s); attempting {len(candidates)} this run "
        f"(cap {MAX_TRANSCRIPTS_PER_RUN}, max {MAX_PER_CHANNEL_PER_RUN}/channel).")

    if not candidates:
        # Still rewrite pending (even to empty) so stale entries drop off once captured elsewhere.
        with open(PENDING_PATH, "w", encoding="utf-8") as f:
            json.dump({"checked": newest_date, "pending": []}, f,
                      indent=2, ensure_ascii=False)
            f.write("\n")
        log("Nothing new — done.")
        _emit_new_pick_count(0)
        return

    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    models = usable_models(client)

    from youtube_transcript_api._errors import RequestBlocked

    attempts = candidates
    # Two very different reasons a video isn't in the table yet, tracked
    # separately: "queued" is simply waiting its turn under the per-run cap
    # (normal, self-resolving), while "failed" means the transcript couldn't be
    # fetched at all (may need a look). Lumping them together made a healthy
    # 92-video backlog read as "92 Shorts couldn't be auto-analyzed", which is
    # alarming and wrong.
    for v in deferred:
        v["reason"] = "queued"
    new_videos, still_pending = [], list(deferred)
    for i, v in enumerate(attempts):
        if i:
            time.sleep(THROTTLE_SECONDS + random.uniform(0, THROTTLE_JITTER))
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
            for rv in remaining:
                rv["reason"] = "failed"
            still_pending.extend(remaining)
            break
        if transcript is None:
            still_pending.append({**v, "reason": "failed"})
            continue
        try:
            picks = extract_picks(client, models, transcript)
        except Exception as e:
            log(f"  Gemini extraction failed for {v['video_id']}: {e}")
            still_pending.append({**v, "reason": "failed"})
            continue
        if not picks:
            log(f"  nothing substantive in {v['video_id']} ({v['title']}) — has a transcript, "
                f"just nothing worth extracting, so not added to pending either.")
            continue
        # Price at the time of the call -- the entry price the Shorts Perf tab
        # measures from. Recorded here rather than derived later so it stays
        # fixed once captured. Only ticker entries need one; a general takeaway
        # ("the Fed cut rates") has nothing to price.
        for p in picks:
            p["price"] = fetch_pick_price(p["ticker"], v["date"]) if p.get("ticker") else None

        new_videos.append({
            "date": v["date"],
            "url": f"https://www.youtube.com/shorts/{v['video_id']}",
            "title": v["title"],
            "channel": v["channel"],
            "channel_name": v["channel_name"],
            "picks": picks,
        })
        n_tick = sum(1 for p in picks if p.get("ticker"))
        log(f"  [{v['channel_name']}] {v['video_id']}: {len(picks)} entr(ies), "
            f"{n_tick} with a ticker — "
            + ", ".join((f"{p['ticker']}" + (f" @ ${p['price']}" if p.get("price") else ""))
                        if p.get("ticker") else "general"
                        for p in picks))

    if new_videos:
        data["videos"] = new_videos + data.get("videos", [])
        data["updated"] = newest_date or data.get("updated")
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
            "checked": newest_date,
            "pending": [{
                "video_id": v["video_id"], "title": v["title"], "date": v["date"],
                "channel_name": v.get("channel_name", ""),
                "reason": v.get("reason", "queued"),
                "url": f"https://www.youtube.com/shorts/{v['video_id']}",
            } for v in still_pending],
        }, f, indent=2, ensure_ascii=False)
        f.write("\n")
    n_failed = sum(1 for v in still_pending if v.get("reason") == "failed")
    log(f"{len(still_pending)} not captured: {len(still_pending) - n_failed} queued for a later "
        f"run, {n_failed} failed (transcript unavailable or extraction error).")
    _emit_new_pick_count(sum(len(v["picks"]) for v in new_videos))


if __name__ == "__main__":
    main()
