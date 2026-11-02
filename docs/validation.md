# Validation results

Run on 2026-10-31 on macOS / Apple Silicon with Python 3.12.3.

## Passed checks

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests -v` | 45 tests passed, including two JavaScript-download-to-Python-export round-trips. |
| `node tests/test_player.cjs` | Player logic passed: line/word highlights, gap clearing, seeking, follow toggle, playback speed, and audio errors. |
| `node --test tests/test_editor.cjs` | 18 editor tests passed: edits, validation, precision, offsets, add/remove, undo, download data, and unsaved-change protection. |
| `python -m pip check` in `.venv` | No broken requirements. |
| Wheel build | Built successfully; current `player.html`, `player.js`, and `exporters.py` match the workspace. The demo ZIP inlines the editor and preserves MP3 bytes. |
| Repository skill | Valid YAML frontmatter, only `name` and `description`, correct directory/name, no unresolved TODOs. |
| Real `tiny` inference | Local CPU/int8 transcription of a generated MP3 completed offline after the model download. |
| Full portable bundle | LRC, SRT, VTT, JSON, MP3, HTML, and ZIP produced successfully. |
| JSON re-export | Regenerated a second valid bundle without running inference. |
| Audio integrity | Loose and zipped MP3 bytes match the original in both bundles. |
| Corrupt MP3 | Real decoder rejected a text file named `.mp3`; CLI exited 1 without a traceback or published output directory. |

## Offline editor browser smoke check

The editor was exercised in the background in-app Browser because the visible
workbench was unavailable. The temporary preview served only the generated demo
bundle on loopback; it was stopped after testing, and the browser session was closed.

Confirmed with actual browser controls and DOM inspection:

- The edit dialog opens with the selected line and correct timestamps.
- A negative start time is rejected and leaves the original line unchanged.
- Applying corrected text and timing updates the rendered lyric and clears stale words.
- Markup-like lyrics remain literal text; no markup elements are created.
- The generated JSON download has the `.corrected.json` filename, original MP3
  filename, schema version 1, and the exact edited transcript.
- The page has no horizontal overflow at the tested 1280-pixel viewport.
- Muted playback advances and highlights the edited line when using the local
  MP3 as a browser Blob. The temporary basic HTTP server did not provide reliable
  seeking, so this playback check used the same bytes via a Blob URL instead.

The download was intercepted for inspection, not saved through the operating
system's download UI. The new demo is `exports/editor-demo/index.html`; it contains
the original synthetic transcript and the editor, not the temporary browser edits.

## Real-engine smoke fixture

The user authorized installing the optional runtime and downloading the tiny model.
Dependencies and model data were kept in `.venv/` and `.cache/` within this workspace.
No audio was uploaded to a transcription service.

A locally generated macOS Samantha speech clip used this original text:

> Morning light is shining through the window. We walk together down the open road.
> Keep the rhythm moving softly. Let the music carry us back home.

FFmpeg added two seconds of leading silence and two seconds of trailing silence,
then encoded an MP3. The resulting decoded duration was 12.814 seconds.

The test ran:

```bash
HF_HOME="$PWD/.cache/huggingface" XDG_CACHE_HOME="$PWD/.cache" \
  .venv/bin/lyric-transcriber transcribe .cache/smoke/speech.mp3 \
  --model tiny --language en --offline --output exports/smoke --bundle
```

Results:

- Four lyric lines and 26 words were recognized.
- Recognized words matched the synthetic source after ignoring punctuation and case.
- The first word was estimated to start at 1.74 seconds, despite the inserted
  2.00-second silence. This is evidence of approximate alignment, not precise timing.
- `exports/smoke/index.html` and `exports/smoke/bundle.zip` are the generated demo.
- `exports/smoke-reexport/` contains the independently re-exported bundle.
- These local generated files, the virtual environment, and caches are ignored by Git.

To repeat the command, choose a new output directory. Existing outputs are
intentionally never overwritten.

## Compatibility issue found and fixed

The first actual inference attempt used `faster-whisper 1.2.1` and `av 19.0.2`.
It failed because faster-whisper calls `av.open(..., metadata_errors="ignore")`,
which the installed PyAV rejected. The optional dependency set now explicitly
constrains PyAV to `>=11,<17`. Inference was rerun successfully with `av 16.1.0`.

Validated runtime versions include:

- faster-whisper 1.2.1
- ctranslate2 4.8.4
- av 16.1.0
- numpy 2.5.4
- Model: Systran/faster-whisper-tiny; downloaded `model.bin` size 75,538,270 bytes

The first sandboxed macOS speech-synthesis call produced an empty AIFF. After
approved native-service access, a valid speech fixture was generated. That empty
fixture was not used to claim recognition success.

## Not established

- Accuracy on actual singing, backing tracks, different languages, or long songs.
- Sample-accurate word alignment, verse detection, or forced alignment to corrected lyrics.
- Full cross-browser, mobile, accessibility, or operating-system download-dialog QA.
  The editor had a desktop browser smoke check; this is not comprehensive UI coverage.
- LRC behavior in every music player, or GPU/CUDA behavior.
- Model performance or compatibility beyond the recorded test configuration.

A user-supplied song and manually checked reference lyrics/timestamps are needed
for meaningful singing-accuracy evaluation. The synthetic clip is only an
end-to-end connectivity and format test, not a quality benchmark.
