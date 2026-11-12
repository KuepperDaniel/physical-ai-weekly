#!/usr/bin/env python3
"""Builds any pending Industrial AI Weekly episodes from episodes/_work/ into
final episode MP3s and updates the RSS feed (podcast.xml / feed.xml)."""

import json
import os
import re
import subprocess
import tempfile

from voice_segments import voice_missing_segments

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EPISODES_DIR = os.path.join(REPO_ROOT, "episodes")
WORK_DIR = os.path.join(EPISODES_DIR, "_work")
FEED_FILES = ["podcast.xml", "feed.xml"]
BASE_URL = "https://KuepperDaniel.github.io/physical-ai-weekly"

# Jingles. Any format FFmpeg reads works; the first existing file of each name is used,
# and a missing file is simply skipped. Replace the placeholders by dropping in new files.
AUDIO_DIR = os.path.join(REPO_ROOT, "audio")
JINGLE_EXTS = (".mp3", ".wav", ".m4a", ".aiff", ".flac")
JINGLE_LOUDNESS = "loudnorm=I=-17:TP=-1.5:LRA=11"   # sits level with / just under the voices


def find_pending_episodes():
    pending = []
    if not os.path.isdir(WORK_DIR):
        return pending
    for entry in sorted(os.listdir(WORK_DIR)):
        work_path = os.path.join(WORK_DIR, entry)
        manifest_path = os.path.join(work_path, "manifest.json")
        if not os.path.isfile(manifest_path):
            continue
        padded = entry.replace("episode-", "")
        final_mp3 = os.path.join(EPISODES_DIR, f"episode-{padded}.mp3")
        if os.path.isfile(final_mp3):
            continue
        pending.append((padded, work_path, manifest_path))
    return pending


def make_silence(duration_ms, workdir):
    path = os.path.join(workdir, f"silence_{duration_ms}ms.mp3")
    duration_s = duration_ms / 1000.0
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "anullsrc=r=24000:cl=mono",
        "-t", str(duration_s),
        "-q:a", "9",
        path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return path


def find_jingle(name):
    for ext in JINGLE_EXTS:
        path = os.path.join(AUDIO_DIR, name + ext)
        if os.path.isfile(path):
            return path
    return None


def prepare_jingle(name, workdir):
    """Convert a jingle to the segments' format (24 kHz mono MP3) at voice loudness,
    so the concat step can join it with the speech."""
    src = find_jingle(name)
    if not src:
        print(f"  no {name} jingle in audio/, skipping it")
        return None
    out = os.path.join(workdir, f"jingle_{name}.mp3")
    cmd = ["ffmpeg", "-y", "-i", src, "-af", JINGLE_LOUDNESS,
           "-ar", "24000", "-ac", "1", "-c:a", "libmp3lame", "-q:a", "2", out]
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"  using {os.path.relpath(src, REPO_ROOT)} as the {name} jingle")
    return out


def merge_segments(work_path, segments, default_pause_ms, output_path):
    with tempfile.TemporaryDirectory() as tmpdir:
        silence_cache = {}

        def silence(ms):
            if ms not in silence_cache:
                silence_cache[ms] = make_silence(ms, tmpdir)
            return silence_cache[ms]

        list_path = os.path.join(tmpdir, "concat_list.txt")
        ordered = sorted(segments, key=lambda s: s["id"])
        intro, kickoff, sting = (prepare_jingle(n, tmpdir) for n in ("intro", "kickoff", "sting"))
        # The kickoff jingle (instrumental opening) follows the cold open, which Module 2 labels 'cold-open'.
        cold_open = next((i for i, s in enumerate(ordered) if s.get("topic_id") == "cold-open"), None)
        if kickoff and cold_open is None:
            print("  no 'cold-open' segment in this manifest, kickoff jingle skipped")
        with open(list_path, "w") as f:
            def add(path):
                f.write(f"file '{os.path.abspath(path)}'\n")
            if intro:
                add(intro)
                add(silence(250))
            for i, seg in enumerate(ordered):
                add(os.path.join(work_path, seg["fileName"]))
                if kickoff and i == cold_open:
                    add(silence(200))
                    add(kickoff)
                    add(silence(120))
                elif i < len(ordered) - 1:
                    add(silence(seg.get("pause_after_ms") or default_pause_ms))
            if sting:
                add(silence(350))
                add(sting)
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_path,
            "-c:a", "libmp3lame", "-q:a", "2",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg merge failed: {result.stderr}")


def get_duration_seconds(mp3_path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        mp3_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def format_duration(seconds):
    total = int(round(seconds))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def build_rss_item(manifest, padded, duration_str, file_size, pub_date):
    title = manifest["title"]
    description = manifest["short_description"]
    show_notes_html = manifest["show_notes_html"]
    episode_number = manifest["episode_number"]
    guid = f"physical-ai-weekly-episode-{padded}"
    enclosure_url = f"{BASE_URL}/episodes/episode-{padded}.mp3"
    return f"""<item>
<title>{title}</title>
<description>{description}</description>
<content:encoded><![CDATA[
{show_notes_html}
]]></content:encoded>
<pubDate>{pub_date}</pubDate>
<guid isPermaLink="false">{guid}</guid>
<enclosure url="{enclosure_url}" length="{file_size}" type="audio/mpeg"/>
<itunes:duration>{duration_str}</itunes:duration>
<itunes:episode>{episode_number}</itunes:episode>
<itunes:episodeType>full</itunes:episodeType>
<itunes:explicit>false</itunes:explicit>
</item>
"""


def insert_item_into_feed(feed_path, item_xml):
    with open(feed_path, "r", encoding="utf-8") as f:
        content = f.read()
    marker = re.search(r"<itunes:image.*?/>\s*\n", content)
    if not marker:
        raise RuntimeError(f"Could not find insertion marker in {feed_path}")
    insert_at = marker.end()
    new_content = content[:insert_at] + "\n" + item_xml + content[insert_at:]
    with open(feed_path, "w", encoding="utf-8") as f:
        f.write(new_content)


def main():
    pending = find_pending_episodes()
    if not pending:
        print("No pending episodes to build.")
        return

    for padded, work_path, manifest_path in pending:
        print(f"Building episode {padded}...")
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        # Since Nov 2026 n8n sends only the script lines; the voices are recorded here with the
        # Realtime API (voice_segments.py). Segments that already have an audio file are left alone.
        voice_missing_segments(work_path, manifest["segments"])

        final_mp3 = os.path.join(EPISODES_DIR, f"episode-{padded}.mp3")
        pause_ms = manifest.get("pauseMsDefault", 300)
        merge_segments(work_path, manifest["segments"], pause_ms, final_mp3)

        duration_seconds = get_duration_seconds(final_mp3)
        duration_str = format_duration(duration_seconds)
        file_size = os.path.getsize(final_mp3)

        show_notes_path = os.path.join(EPISODES_DIR, f"episode-{padded}-show-notes.md")
        with open(show_notes_path, "w", encoding="utf-8") as f:
            f.write(f"# Episode {manifest['episode_number']}: {manifest['title']}\n\n")
            f.write(manifest["show_notes_html"])
            f.write("\n")

        pub_date = subprocess.run(
            ["date", "-u", "+%a, %d %b %Y %H:%M:%S GMT"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        item_xml = build_rss_item(manifest, padded, duration_str, file_size, pub_date)
        for feed_file in FEED_FILES:
            feed_path = os.path.join(REPO_ROOT, feed_file)
            insert_item_into_feed(feed_path, item_xml)

        print(f"Episode {padded} built: {final_mp3} ({duration_str}, {file_size} bytes)")


if __name__ == "__main__":
    main()
