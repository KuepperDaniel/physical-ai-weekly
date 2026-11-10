# Jingles

`scripts/build_episode.py` adds three jingles to every episode it builds:

| File | Where it plays |
|---|---|
| `intro.*` | The very start of the episode, before the cold open. Carries the spoken show name. |
| `kickoff.*` | Straight after the cold open (the line Module 2 labels `cold-open`). Carries the "Let's go!" call-out; Sarah follows with the welcome. |
| `sting.*` | After the sign-off. |

**The current files are placeholders**: synthesised demos with a stand-in macOS voice. They will be replaced once the final jingle is chosen.

To replace one, drop a new file here under the same name. Any format FFmpeg reads works (`.mp3`, `.wav`, `.m4a`, `.aiff`, `.flac`); the build converts it to the episodes' format (24 kHz mono) and loudness. Keep only one file per name. If a file is missing, the build skips that jingle instead of failing.

Changing files here does not trigger an episode build, and already-published episodes are not rebuilt.
