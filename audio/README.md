# Jingles

`scripts/build_episode.py` adds three jingles to every episode it builds. These are the final "Cinematic"
files (since 12 Nov 2026; the opening order was changed the same evening):

| File | Source file | Length | Where it plays |
|---|---|---|---|
| `intro.wav` | `IAW_Cinematic_Opening_with_Title.wav` | 7.0 s | The very start of the episode: the cinematic opening with the show title, before the cold open (Sarah's short summary). |
| `kickoff.wav` | `IAW_Cinematic_Opening_Instrumental.wav` | 7.0 s | Straight after the cold open (the line Module 2 labels `cold-open`): the same opening without title or host. Sarah follows with the welcome. |
| `sting.wav` | `IAW_Cinematic_Outro.wav` | 3.3 s | The very end, after the sign-off. |

Episode order: opening with title → cold open → instrumental opening → welcome (Sarah), Daniel's intro,
AI-voice disclosure (Sarah) → Daniel's energetic "Let's go!" with almost no pause → stories → sign-off → outro.
The "Let's go!" is a spoken line that Module 2 inserts into every script, not part of the music.

All three are 48 kHz stereo 24-bit WAV. The build converts each to the episodes' format (24 kHz mono MP3)
and evens out the loudness (`loudnorm I=-17`), so no manual prep is needed.

To replace one, drop a new file here under the same name. Any format FFmpeg reads works (`.mp3`, `.wav`, `.m4a`, `.aiff`, `.flac`). Keep only one file per name. If a file is missing, the build skips that jingle instead of failing.

Changing files here does not trigger an episode build, and already-published episodes are not rebuilt.
