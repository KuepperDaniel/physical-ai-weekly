# Jingles

`scripts/build_episode.py` adds three jingles to every episode it builds. Since 12 Nov 2026 these are the
final "Cinematic" files (replacing the synthesised placeholders):

| File | Source file | Length | Where it plays |
|---|---|---|---|
| `intro.wav` | `IAW_Cinematic_Intro.wav` | 3.0 s | The very start of the episode, before the cold open (Sarah's short summary). |
| `kickoff.wav` | `IAW_Cinematic_Opening_Title_plus_Host.wav`, silent tail trimmed from 1.0 s to 0.3 s | 7.2 s | Straight after the cold open (the line Module 2 labels `cold-open`). Opening music plus the host announcing the show and "Let's go!"; Sarah follows with the welcome. |
| `sting.wav` | `IAW_Cinematic_Outro.wav` | 3.3 s | The very end, after the sign-off. |

Episode order: intro → cold open → opening (title + host, "Let's go!") → welcome, stories, sign-off → outro.

All three are 48 kHz stereo 24-bit WAV. The build converts each to the episodes' format (24 kHz mono MP3)
and evens out the loudness (`loudnorm I=-17`), so no manual prep is needed.

To replace one, drop a new file here under the same name. Any format FFmpeg reads works (`.mp3`, `.wav`, `.m4a`, `.aiff`, `.flac`). Keep only one file per name. If a file is missing, the build skips that jingle instead of failing.

Changing files here does not trigger an episode build, and already-published episodes are not rebuilt.
