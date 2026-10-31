# My Lyric Transcriber

A local Python CLI that turns an MP3 into estimated lyrics and timestamps. Export
LRC for music players, SRT/VTT for subtitles, editable JSON with word timings, or a
ZIP containing the original MP3 and an offline, word-highlighting lyrics player.

Audio stays on your machine. No API key or paid transcription service is needed.
The first run downloads model weights unless you use `--offline`.

## Install

Python 3.10 or later is required. From this folder:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[transcribe]'
```

On Windows, use `.venv\Scripts\python.exe` and
`.venv\Scripts\lyric-transcriber.exe` instead of the `.venv/bin/` paths.

`faster-whisper` uses PyAV to decode MP3s; a separate FFmpeg installation is not
normally required for transcription. The optional dependency set constrains PyAV
to `>=11,<17`, because the tested faster-whisper version uses a decoder option
removed in PyAV 19. The default device is CPU with int8 computation, including on Apple Silicon. This backend does not use Apple's MPS.
CUDA needs a compatible NVIDIA GPU and runtime libraries.

## Transcribe an MP3

```bash
.venv/bin/lyric-transcriber transcribe "/path/to/song.mp3" \
  --language en \
  --output exports/song \
  --bundle
```

Omit `--language` to detect it. The default model is multilingual `small` (roughly
0.5 GB of weights); `tiny` is faster and much smaller but usually less accurate.
A larger model can help, but none guarantees accurate singing recognition.

```bash
# Quick pass with a smaller model
.venv/bin/lyric-transcriber transcribe song.mp3 --model tiny --output exports/quick

# No model downloads; tiny must already be cached
.venv/bin/lyric-transcriber transcribe song.mp3 --model tiny --offline --output exports/offline

# Tune lyric line length and splitting at pauses
.venv/bin/lyric-transcriber transcribe song.mp3 \
  --max-chars 42 --max-seconds 8 --gap-seconds 0.9 --output exports/tuned
```

Downloads go to `.cache/lyric-transcriber/models` relative to your current working
directory. Use `--cache-dir PATH` to change it or `--model /path/to/local/model`
to use a converted faster-whisper/CTranslate2 model directory. `--offline` fails
rather than downloading missing model files. For CUDA, use `--device cuda` and a
supported `--compute-type` such as `float16`.

The CLI can also run without installation as `python -m lyric_transcriber` from
this folder. Transcription still requires its optional dependencies.

## Outputs and playback

With `--bundle`, `exports/song/` contains:

```text
song.mp3       Original bytes, copied without re-encoding
song.lrc       Line-start timestamps with centisecond precision
song.srt       Subtitle intervals with millisecond precision
song.vtt       WebVTT subtitle intervals
song.json      Editable transcript with estimated word starts/ends
index.html     Offline audio player with line and word highlighting
bundle.zip     Everything above, ready to extract and play
```

Without `--bundle`, only the four lyric/transcript files are created. An output
directory must not already exist; use a new name for each run. The app never
overwrites your MP3 or an existing export. A bundle stores two copies of the MP3
(one loose and one in the ZIP), so allow enough disk space.

- **Music player:** put `song.lrc` beside `song.mp3` with the same base filename,
  then open the audio in a player that supports external LRC files. Support varies;
  empty LRC end markers clear lyrics during instrumental gaps where supported.
- **Portable playback:** extract `bundle.zip`, then open `index.html` in a modern
  browser and press Play. No server, CDN, or network request is needed. Click a
  lyric line to seek. Playback speed and automatic lyric following are adjustable.
- **Video/subtitle tools:** import the SRT or VTT alongside the audio.
- **Other scripts:** read the versioned JSON. Timestamps are floating-point seconds
  from the beginning of the original MP3, not relative to individual lyric lines.

LRC is line-timed, not enhanced word-level karaoke LRC. Word timing lives in JSON
and drives the HTML player. Audio is not modified and lyrics are not embedded in
MP3 ID3 tags.

## Correct lyrics without rerunning inference

Copy and edit the exported JSON. Keep `schema_version: 1` and the original audio
filename. Update a line's `text`, `start`, and `end` as needed.

If the line contains `words`, update those words and their times too. Word strings
preserve leading spaces: joining them must match the line's text. Alternatively,
set `"words": []` for a corrected line to use line-only highlighting. Do not pretend
that old word timings align newly written lyrics.

```bash
.venv/bin/lyric-transcriber export exports/song/song.json \
  --audio "/path/to/song.mp3" \
  --output exports/song-corrected \
  --bundle
```

Export-only use has no third-party dependencies:

```bash
python3 -m lyric_transcriber export corrected.json --output exports/corrected
```

Export validates ordered, non-overlapping line intervals, word boundaries,
nonfinite numbers, and filename safety. Providing `--audio` checks the filename,
not the recording's identity: use the same original MP3. No automatic forced
alignment to supplied corrected lyrics is implemented.

## Accuracy and privacy limits

Whisper is primarily a speech recognizer. Music, reverb, backing vocals, stretched
syllables, and instrumental passages can produce incorrect or hallucinated lyrics.
Word timestamps are estimates, not sample-accurate musical alignment. Long songs
may take substantial time on CPU. Check the results before publishing or using
precise karaoke cues.

The app disables voice-activity filtering to avoid cutting quiet singing and uses
independent text context between decoding windows to reduce repetition. It does
not separate vocals, identify speakers, infer verses, or guarantee silence
suppression. Model downloads contact the model host; inference itself is local.
Use audio you are authorized to process and share.

## Development and validation

```bash
python3 -m unittest discover -s tests -v
node tests/test_player.cjs
```

The Python suite uses the standard library. It tests validation, segmentation,
sidecar formats, escaping, bundle integrity, safe publishing, CLI failures, and a
controlled inference adapter. The Node test exercises the player logic with a
minimal DOM harness; it is not a full browser rendering or audio-playback test.

See [docs/validation.md](docs/validation.md) for actual checks and the real-engine
smoke test. Synthetic spoken audio proves pipeline connectivity, not singing
accuracy; no user-provided song was available during development.

## Repository skill

The reusable skill is at
[.agents/skills/reverse-engineering-anything/SKILL.md](.agents/skills/reverse-engineering-anything/SKILL.md).
It covers evidence-led reconstruction, safe probing, explicit assumptions,
implementation, and validation. A new Glean Tau session will discover it; use
`/reload` to refresh resources in the current session.

This app was built using that skill as a **requirements-driven reconstruction**,
not reverse engineering of an existing application. See
[docs/reconstruction.md](docs/reconstruction.md) for the evidence ledger and
behavioral contract. No commit, push, or remote repository was created.
