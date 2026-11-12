#!/bin/bash
# Builds a test episode exactly as the GitHub Action does (Realtime voicing, jingles, RSS item),
# but in a throwaway copy of the repo: nothing is committed, pushed or published.
#
#   bash tests/run_test_episode.sh                  # uses tests/sample-episode
#   bash tests/run_test_episode.sh path/to/folder   # any folder holding a manifest.json
#   bash tests/run_test_episode.sh --clipboard      # takes the key you just copied (Mac), then clears the clipboard
#
# Asks for the podcast OpenAI key (hidden input) unless OPENAI_API_KEY is already set.
# The key lives only in this shell process; it is never written to disk.
# Results land in ~/Desktop/realtime-test-<time>/ : the episode mp3, voicing_report.json, RSS item.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
KEY_FROM_CLIPBOARD=0
if [ "${1:-}" = "--clipboard" ]; then KEY_FROM_CLIPBOARD=1; shift; fi   # Mac: read the copied key, then clear the clipboard
EPISODE_SRC="${1:-$REPO/tests/sample-episode}"
VENV="$HOME/podcast-venv"
OUT="$HOME/Desktop/realtime-test-$(date +%H%M%S)"

[ -f "$EPISODE_SRC/manifest.json" ] || { echo "No manifest.json in $EPISODE_SRC"; exit 1; }
command -v ffmpeg >/dev/null || { echo "FFmpeg is missing. Install it with: brew install ffmpeg"; exit 1; }

# Python with the two packages the build needs (own folder, does not touch the system Python).
if [ -n "${IAW_PYTHON:-}" ]; then
  PY="$IAW_PYTHON"                       # for offline testing of this script only
else
  if [ ! -x "$VENV/bin/python" ]; then
    echo "Creating Python environment in $VENV ..."
    python3 -m venv "$VENV"
  fi
  echo "Installing websockets 15.0.1 and truststore ..."
  "$VENV/bin/pip" install -q --disable-pip-version-check websockets==15.0.1 truststore \
    || "$VENV/bin/pip" install -q --disable-pip-version-check --use-feature=truststore websockets==15.0.1 truststore
  PY="$VENV/bin/python"
fi

if [ "$KEY_FROM_CLIPBOARD" = 1 ]; then
  CLIP="$(pbpaste 2>/dev/null || true)"
  # Accept the key on its own or with text around it (a label, quotes, OPENAI_API_KEY=...).
  OPENAI_API_KEY="$(printf '%s' "$CLIP" | grep -oE 'sk-[A-Za-z0-9_-]{20,}' | head -1 || true)"
  if [ -n "$OPENAI_API_KEY" ]; then
    printf '' | pbcopy                   # clear the clipboard again
    echo "Key taken from the clipboard (clipboard cleared)."
  else
    # Say what was there without printing it.
    echo "No OpenAI key found in the clipboard (an OpenAI key starts with sk-)."
    echo "The clipboard holds ${#CLIP} characters$( [ ${#CLIP} -gt 0 ] && printf ', no sk- key among them' ). It was left unchanged."
    echo "Tip: copy the key as plain text, e.g. from the OpenAI dashboard or the password manager's Copy button, then run again."
    exit 1
  fi
  export OPENAI_API_KEY
elif [ -z "${OPENAI_API_KEY:-}" ]; then
  read -rs -p "Paste the podcast OpenAI key and press Enter (nothing will show): " OPENAI_API_KEY
  echo
  export OPENAI_API_KEY
fi
[ -n "$OPENAI_API_KEY" ] || { echo "No key entered."; exit 1; }

# Throwaway copy of the repo with the test episode waiting in episodes/_work/.
WORK="$(mktemp -d "${TMPDIR:-/tmp}/iaw-test.XXXXXX")"
cp -R "$REPO/scripts" "$REPO/audio" "$WORK/"
mkdir -p "$WORK/episodes/_work"
cp "$REPO/podcast.xml" "$WORK/podcast.xml"
cp "$REPO/podcast.xml" "$WORK/feed.xml"
cp -R "$EPISODE_SRC" "$WORK/episodes/_work/episode-00"
find "$WORK/episodes/_work/episode-00" -name '*.mp3' -delete   # always voice fresh
find "$WORK/episodes/_work/episode-00" -name 'voicing_report.json' -delete

echo "Building test episode (voicing with the Realtime API, then jingles and RSS) ..."
STATUS=0
(cd "$WORK" && "$PY" scripts/build_episode.py) || STATUS=$?

mkdir -p "$OUT"
cp "$WORK/episodes/_work/episode-00/voicing_report.json" "$OUT/" 2>/dev/null || true
cp "$WORK/episodes/_work/episode-00/"*.mp3 "$OUT/" 2>/dev/null || true
if [ -f "$WORK/episodes/episode-00.mp3" ]; then
  cp "$WORK/episodes/episode-00.mp3" "$OUT/test-episode.mp3"
  "$PY" - "$WORK/podcast.xml" "$OUT/rss-item.xml" <<'PYEOF'
import re, sys
item = re.search(r"<item>.*?</item>", open(sys.argv[1], encoding="utf-8").read(), re.S)
open(sys.argv[2], "w", encoding="utf-8").write(item.group(0) + "\n" if item else "no item found\n")
PYEOF
fi

echo
echo "---------- Result ----------"
if [ -f "$OUT/voicing_report.json" ]; then
  "$PY" - "$OUT/voicing_report.json" <<'PYEOF'
import json, sys
r = json.load(open(sys.argv[1], encoding="utf-8"))
print(f"Model {r['model']}: {r['voiced']} lines, {r['ok']} exact, {r['accepted_with_warning']} close, "
      f"{r['failed_or_drifted']} failed or drifted, {r['seconds_taken']} s")
for l in r["lines"]:
    takes = len(l["takes"])
    match = f"{l['match']:.0%}" if "match" in l else "-"
    print(f"  line {l['id']:>3} {l['speaker']:<6} {l['voice']:<6} {l['result']:<22} match {match:>4}  takes {takes}")
PYEOF
fi
if [ "$STATUS" -eq 0 ]; then
  echo "Build OK. Listen to: $OUT/test-episode.mp3"
else
  echo "Build stopped (exit $STATUS). Details are above and in $OUT/voicing_report.json"
fi
echo "Results folder: $OUT"
exit "$STATUS"
