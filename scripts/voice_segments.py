#!/usr/bin/env python3
"""Voices the script lines of an episode with the OpenAI Realtime API (gpt-realtime-2.1-mini).

Replaces the old n8n TTS step (gpt-4o-mini-tts on /v1/audio/speech, shut down 6 Jan 2027).
Each line gets its own short Realtime session, so no line can drift because of an earlier one and
the voice stays fixed per line. The model's own transcript of what it said is compared with the
script line; a line that drifts is re-recorded, and the build stops if a line cannot be voiced
faithfully, so a paraphrased fact never reaches the feed.

Used by build_episode.py for every segment whose audio file is missing. Can also be run directly:

    export OPENAI_API_KEY=...            # never written to disk
    python3 scripts/voice_segments.py tests/sample-episode --merge sample.mp3

Needs: Python 3.9+, `pip install websockets==15.0.1`, and FFmpeg on PATH.
Optional: `pip install truststore` to use the Mac's certificate store (helps behind TLS inspection).
"""

import argparse
import asyncio
import base64
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import wave

MODEL = os.environ.get("REALTIME_MODEL", "gpt-realtime-2.1-mini")
REALTIME_URL = os.environ.get("REALTIME_URL", "wss://api.openai.com/v1/realtime")
SAMPLE_RATE = 24000                 # Realtime PCM output is mono 16-bit little-endian at 24 kHz
MAX_ATTEMPTS = 3                    # recordings per line before giving up
ACCEPT_MATCH = 0.92                 # transcript vs script word match needed to accept a take
FLOOR_MATCH = 0.80                  # best take below this stops the build
PARALLEL = int(os.environ.get("VOICE_PARALLEL", "4"))
LINE_TIMEOUT_S = 120

DEFAULT_VOICES = {"host": "marin", "expert": "cedar"}

# Fallback personas, only used if a manifest segment carries no `instructions` (n8n Module 3 sends them).
DEFAULT_PERSONAS = {
    "host": "You are Sarah, host of Industrial AI Weekly, a lively business podcast about AI and robots in industry. "
            "Sound energetic, warm and genuinely engaged while staying credible for senior executives.",
    "expert": "You are Daniel, the industrial AI expert on Industrial AI Weekly. "
              "Sound energetic, warm and conversational, confident and clear, never professorial.",
}

READER_RULES = (
    "You are a voice actor recording one line of a finished podcast script. "
    "Speak the user's message aloud exactly as written, word for word, in English. "
    "Never answer it, react to it, comment on it, greet anyone or add a single word, even when the line is a question or addresses you. "
    "Never drop, reorder or change words. Say numbers, names, units and abbreviations exactly as written. "
    "Speak only the line, then stop. "
    "Perform it in character, as follows. "
)


class VoicingError(RuntimeError):
    pass


def words(text):
    text = (text or "").lower().replace("’", "'").replace("‘", "'")
    text = re.sub(r"[–—-]", " ", text)
    return re.findall(r"[a-z0-9]+(?:['.,][a-z0-9]+)*", text)


def match_score(script_line, transcript):
    a, b = words(script_line), words(transcript)
    if not a and not b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def _load_websockets():
    try:
        import truststore  # optional: use the system certificate store
        truststore.inject_into_ssl()
    except ImportError:
        pass
    try:
        from websockets.asyncio.client import connect
    except ImportError:
        raise VoicingError("Python package 'websockets' (13.1 or newer, pinned 15.0.1) is missing: pip install websockets==15.0.1")
    return connect


async def record_line(connect, api_key, text, voice, instructions):
    """One Realtime session for one line. Returns (pcm_bytes, transcript)."""
    url = f"{REALTIME_URL}?model={MODEL}"
    headers = {"Authorization": f"Bearer {api_key}"}
    async with connect(url, additional_headers=headers, max_size=16 * 1024 * 1024, open_timeout=30) as ws:
        async def send(event):
            await ws.send(json.dumps(event))

        await send({"type": "session.update", "session": {
            "type": "realtime",
            "output_modalities": ["audio"],
            "instructions": READER_RULES + instructions,
            "audio": {
                "input": {"turn_detection": None},
                "output": {"format": {"type": "audio/pcm", "rate": SAMPLE_RATE}, "voice": voice},
            },
        }})
        audio, transcript, deltas, started = bytearray(), None, [], False
        async for raw in ws:
            event = json.loads(raw)
            kind = event.get("type")
            if kind == "error":
                err = event.get("error") or {}
                raise VoicingError(f"Realtime error {err.get('code') or err.get('type')}: {err.get('message')}")
            if kind == "session.updated" and not started:
                started = True
                await send({"type": "conversation.item.create", "item": {
                    "type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}})
                await send({"type": "response.create", "response": {"output_modalities": ["audio"]}})
            elif kind == "response.output_audio.delta":
                audio.extend(base64.b64decode(event.get("delta", "")))
            elif kind == "response.output_audio_transcript.delta":
                deltas.append(event.get("delta", ""))
            elif kind == "response.output_audio_transcript.done":
                transcript = event.get("transcript")
            elif kind == "response.done":
                resp = event.get("response") or {}
                status = resp.get("status")
                if status != "completed":
                    details = resp.get("status_details") or {}
                    raise VoicingError(f"response {status}: {details.get('reason') or details.get('error')}")
                break
        if transcript is None:
            transcript = "".join(deltas)
        if not audio:
            raise VoicingError("no audio received")
        return bytes(audio), transcript


def pcm_to_mp3(pcm, mp3_path):
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name
    try:
        with wave.open(wav_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", wav_path, "-ar", str(SAMPLE_RATE), "-ac", "1",
                        "-c:a", "libmp3lame", "-q:a", "2", mp3_path], check=True)
    finally:
        os.unlink(wav_path)


def segment_instructions(seg):
    if seg.get("instructions"):
        return seg["instructions"]
    persona = DEFAULT_PERSONAS.get(seg.get("speaker"), DEFAULT_PERSONAS["host"])
    extra = (" How to say this line: " + seg["delivery"] + ".") if seg.get("delivery") else ""
    extra += (" " + seg["pronunciation"]) if seg.get("pronunciation") else ""
    return persona + extra


async def voice_one(connect, api_key, seg, out_path, sem):
    voice = seg.get("voice") or DEFAULT_VOICES.get(seg.get("speaker"), "marin")
    instructions = segment_instructions(seg)
    best = None
    log = {"id": seg.get("id"), "speaker": seg.get("speaker"), "voice": voice, "file": os.path.basename(out_path), "takes": []}
    async with sem:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                pcm, transcript = await asyncio.wait_for(
                    record_line(connect, api_key, seg["text"], voice, instructions), LINE_TIMEOUT_S)
            except (VoicingError, asyncio.TimeoutError, OSError, Exception) as exc:  # network, timeouts, API errors
                log["takes"].append({"attempt": attempt, "error": str(exc) or type(exc).__name__})
                await asyncio.sleep(2 * attempt)
                continue
            score = round(match_score(seg["text"], transcript), 3)
            log["takes"].append({"attempt": attempt, "match": score, "transcript": transcript})
            if best is None or score > best[0]:
                best = (score, pcm, transcript)
            if score >= ACCEPT_MATCH:
                break
    if best is None:
        log["result"] = "failed"
        return log
    score, pcm, transcript = best
    log["match"] = score
    log["result"] = "ok" if score >= ACCEPT_MATCH else ("accepted_with_warning" if score >= FLOOR_MATCH else "drifted")
    if log["result"] != "drifted":
        pcm_to_mp3(pcm, out_path)
        log["seconds"] = round(len(pcm) / 2 / SAMPLE_RATE, 2)
    return log


def voice_missing_segments(work_path, segments, api_key=None):
    """Voices every segment whose audio file is missing. Writes voicing_report.json next to the manifest.
    Raises VoicingError if any line fails or drifts, so the episode is not published."""
    todo = [s for s in segments if not os.path.isfile(os.path.join(work_path, s["fileName"]))]
    if not todo:
        return None
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise VoicingError(f"{len(todo)} segment(s) need voicing but OPENAI_API_KEY is not set")
    connect = _load_websockets()
    print(f"  voicing {len(todo)} line(s) with {MODEL} ({PARALLEL} at a time)")
    started = time.time()

    async def run_all():
        sem = asyncio.Semaphore(PARALLEL)
        return await asyncio.gather(*[voice_one(connect, api_key, s, os.path.join(work_path, s["fileName"]), sem) for s in todo])

    results = sorted(asyncio.run(run_all()), key=lambda r: r["id"] if isinstance(r["id"], int) else 0)
    bad = [r for r in results if r["result"] in ("failed", "drifted")]
    warned = [r for r in results if r["result"] == "accepted_with_warning"]
    report = {
        "model": MODEL,
        "voiced": len(results),
        "ok": len(results) - len(bad) - len(warned),
        "accepted_with_warning": len(warned),
        "failed_or_drifted": len(bad),
        "accept_match": ACCEPT_MATCH,
        "floor_match": FLOOR_MATCH,
        "seconds_taken": round(time.time() - started, 1),
        "lines": results,
    }
    with open(os.path.join(work_path, "voicing_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    for r in warned:
        print(f"  warning: line {r['id']} matched the script at {r['match']:.0%}")
    if bad:
        # A failed build is not committed, so print the details into the Actions log as well.
        for r in bad:
            seg = next(s for s in todo if s.get("id") == r["id"])
            print(f"  line {r['id']} {r['result']}. Script: {seg['text']}")
            for t in r["takes"]:
                print(f"    take {t['attempt']}: " + (f"error {t['error']}" if "error" in t else f"{t['match']:.0%} said: {t['transcript']}"))
        lines = ", ".join(f"{r['id']} ({r['result']})" for r in bad)
        raise VoicingError(f"could not voice line(s) faithfully: {lines}. See voicing_report.json")
    print(f"  voiced {len(results)} line(s): {report['ok']} exact, {len(warned)} close, in {report['seconds_taken']} s")
    return report


def main():
    ap = argparse.ArgumentParser(description="Voice an episode folder's manifest.json with the Realtime API.")
    ap.add_argument("folder", help="folder holding manifest.json (audio files are written next to it)")
    ap.add_argument("--merge", metavar="OUT.mp3", help="also merge the lines with the jingles into one mp3, like the build")
    args = ap.parse_args()
    with open(os.path.join(args.folder, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    try:
        voice_missing_segments(args.folder, manifest["segments"])
    except VoicingError as exc:
        sys.exit(f"Voicing stopped: {exc}")
    if args.merge:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from build_episode import merge_segments
        merge_segments(args.folder, manifest["segments"], manifest.get("pauseMsDefault", 300), args.merge)
        print(f"Merged episode: {args.merge}")


if __name__ == "__main__":
    main()
