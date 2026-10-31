# Validation results

Run on 2026-10-31 on macOS / Apple Silicon with Python 3.12.3.

## Passed checks

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests -v` | 42 tests passed. |
| `node tests/test_player.cjs` | Player logic passed: line/word highlights, gap clearing, seeking, follow toggle, playback speed, and audio errors. |
| `python -m pip check` in `.venv` | No broken requirements. |
| Wheel build | Built successfully; `player.html` is packaged and the validated model source matches the workspace. |
| Repository skill | Valid YAML frontmatter, only `name` and `description`, correct directory/name, no unresolved TODOs. |
| Real `tiny` inference | Local CPU/int8 transcription of a generated MP3 completed offline after the model download. |
| Full portable bundle | LRC, SRT, VTT, JSON, MP3, HTML, and ZIP produced successfully. |
| JSON re-export | Regenerated a second valid bundle without running inference. |
| Audio integrity | Loose and zipped MP3 bytes match the original in both bundles. |
| Corrupt MP3 | Real decoder rejected a text file named `.mp3`; CLI exited 1 without a traceback or published output directory. |

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
- Full browser visual/audio-playback QA. Player behavior was tested in a minimal
  DOM harness; the bundle was checked structurally and for safe data embedding.
- LRC behavior in every music player, or GPU/CUDA behavior.
- Model performance or compatibility beyond the recorded test configuration.

A user-supplied song and manually checked reference lyrics/timestamps are needed
for meaningful singing-accuracy evaluation. The synthetic clip is only an
end-to-end connectivity and format test, not a quality benchmark.
