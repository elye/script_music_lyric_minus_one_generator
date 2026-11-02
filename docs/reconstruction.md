# Requirements-driven reconstruction

This project was built using `.agents/skills/reverse-engineering-anything/SKILL.md`.
There was no existing application, source, URL, or reference recording to inspect.
The user explicitly chose to build from requirements. This is not a claim to have
reverse engineered an existing product or reproduced its internals.

## Evidence ledger

| Status | Evidence / decision |
| --- | --- |
| Observed | The workspace was empty at initial inspection. Python 3.12, Node, and FFmpeg were available; no Python transcription engine was installed. |
| Required | Accept an MP3, transcribe lyrics with timing, and export lyrics for use with the MP3. |
| Required | Create a reusable repository-local reverse-engineering skill and apply it to this task. |
| Assumed | A local Python CLI avoids uploading audio or requiring a paid service. |
| Assumed | `faster-whisper` supplies estimated word timestamps. CPU/int8 is the portable default; language can be specified or detected. |
| Assumed | LRC covers common music players; SRT/VTT cover subtitle workflows; versioned JSON preserves editable word timing. |
| Assumed | A ZIP containing the original MP3, sidecars, and an offline HTML player makes the result portable. |
| Observed | The first version required raw JSON edits to correct recognition and timing mistakes. |
| Assumed | For the user's request to add a missing feature, an offline correction editor closes the most immediate usability gap without extra models or uploads. |
| Unknown | Accuracy on the user's music, languages, backing tracks, overlapping vocals, and long instrumental passages. Validate against a user-supplied recording and manually checked timings. |

## Behavioral contract

- `transcribe INPUT.mp3 --output DIRECTORY [--bundle] [--minus-one]` runs local inference, produces four UTF-8 sidecars, and optionally copies the unmodified MP3 into a portable bundle. `--minus-one` uses the optional Demucs dependency to write `<stem>-minus-one.mp3` with vocals removed at 320 kbps.
- `export TRANSCRIPT.json --output DIRECTORY [--audio INPUT.mp3 --bundle] [--minus-one]` regenerates sidecars without transcription inference. When audio is provided, its filename must match the JSON's `audio_file`; the user must ensure it is the same recording. Minus-one generation requires `--audio`.
- MP3 inputs must be nonempty regular files with an `.mp3` suffix (case insensitive). The engine performs decoding; a renamed invalid file must fail clearly rather than produce a false transcript.
- All timestamps are seconds relative to the start of the original audio, including instrumental gaps. The script does not trim, resample an exported copy, or remove silence. VAD is disabled for singing.
- JSON schema v1 contains `audio_file`, `duration`, `language`, `language_probability`, `engine`, `model`, and ordered `lines`. Each line contains `start`, `end`, `text`, and `words`; each word contains `start`, `end`, `text`, and optional `probability`. Word text retains engine spacing.
- Line splitting uses engine segment boundaries, maximum characters, maximum duration, and pauses between words. It does not infer musical verse structure. A single long word is kept intact.
- Reject nonfinite timestamps, negative times, reversed intervals, overlapping lines, and words outside their line. Small sub-millisecond duration tolerances accommodate floating-point representation, not arbitrary timing edits.
- If words are unavailable for a segment, retain its text and segment timing without inventing word alignment. The offline player then highlights the line only.
- LRC uses centisecond line starts and an empty end marker for instrumental gaps. SRT/VTT use millisecond cue starts and ends. JSON retains the engine's timestamp precision. VTT/SRT escape markup-like lyric text.
- All outputs go into a new directory. Build in a temporary sibling, reserve the destination without replacing it, and publish only after all outputs are complete. Existing directories are never overwritten. No `--force` option is provided.
- With `--bundle`, the directory also contains `index.html`, a byte-for-byte audio copy, and `bundle.zip`. The ZIP contains everything except itself. Extract it before opening the HTML player. Lyrics are embedded, so no server or network is required.
- The bundled player can edit, add, and remove lyric lines, capture playback positions, shift all timings, and undo the latest 25 changes. New and changed lines have no word alignment; unchanged edits retain original precision, and global offsets shift words and lines equally.
- Editor changes are validated before application and remain in memory. Download corrected schema-v1 JSON and run `export` to rebuild sidecars or a bundle. The editor never overwrites source files and does not promise persistence until the download is saved.
- The player and editor script are inlined into `index.html`; no server, CDN, browser storage, or new runtime dependency is needed.
- Empty recognition produces an empty transcript plus an explicit warning, not fabricated lyrics. Missing dependencies, bad audio, malformed JSON, and output conflicts produce a nonzero CLI exit.
- First Whisper inference may download model weights. `--offline` forbids Whisper model downloads; `--model` also accepts a local model directory. The default model cache is `.cache/lyric-transcriber/models` under the working directory.
- Minus-one generation uses Demucs `htdemucs`; its first run may download model weights even when transcription uses `--offline`. The resulting MP3 joins the export directory and, when requested, the ZIP. Source separation is approximate and may leave vocals or remove vocal-like instruments.

## Boundaries and validation

Whisper is a speech model, not a guaranteed singing-lyrics recognizer. Reverb,
accompaniment, stretched syllables, silence, and backing vocals can cause errors
or hallucinations. Estimated word timestamps are not forced alignment against
verified lyrics. Correct words and timings in the offline editor or JSON and
regenerate exports. The editor automatically clears a changed line's `words`
array to avoid stale word highlights; direct JSON edits must do this explicitly.

Deterministic tests cover data validation, segmentation, formatting, escaping,
bundling, overwrite refusal, CLI behavior, and the engine adapter with fake model
responses. These do not establish recognition accuracy. Real inference requires
installing the optional engine and model weights. A representative singing fixture
is needed to make any singing-accuracy claim.
