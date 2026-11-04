"""Command-line entry point."""

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .exporters import export_transcript
from .models import Transcript
from .transcribe import DEFAULT_MODEL_CACHE_DIR, LineOptions, TranscriptionError, transcribe, validate_audio


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Transcribe an MP3 into local, timed lyric exports.")
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="command", required=True)

    run = commands.add_parser("transcribe", help="Recognize lyrics and estimated word timestamps locally")
    run.add_argument("audio", type=Path, help="Original .mp3 file")
    run.add_argument("--output", type=Path, help="New directory (default: exports/<audio-stem>)")
    run.add_argument("--bundle", action="store_true", help="Include the MP3, offline player, and ZIP")
    run.add_argument(
        "--minus-one", action="store_true",
        help="Also generate a vocal-removed minus-one MP3 (requires Demucs)",
    )
    run.add_argument("--model", default="small", help="Whisper model name or local model directory (default: small)")
    run.add_argument("--language", help="Language code, e.g. en; omitted means automatic detection")
    run.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    run.add_argument("--compute-type", choices=("int8", "float16", "float32", "int8_float16"), default="int8")
    run.add_argument(
        "--cache-dir", type=Path, default=DEFAULT_MODEL_CACHE_DIR,
        help="Directory for downloaded model weights (default: .cache/lyric-transcriber/models)",
    )
    run.add_argument(
        "--offline", action="store_true",
        help="Use cached/local Whisper model files only; never download Whisper weights",
    )
    run.add_argument("--max-chars", type=int, default=42, help="Target maximum characters per lyric line")
    run.add_argument("--max-seconds", type=float, default=8.0, help="Target maximum duration of a lyric line")
    run.add_argument("--gap-seconds", type=float, default=0.9, help="Split lyric lines across longer pauses")

    export = commands.add_parser("export", help="Regenerate exports from corrected transcript JSON; no inference")
    export.add_argument("transcript", type=Path)
    export.add_argument("--output", type=Path, required=True, help="New output directory")
    export.add_argument("--audio", type=Path, help="Original MP3; required for --bundle")
    export.add_argument("--bundle", action="store_true")
    export.add_argument(
        "--cache-dir", type=Path, default=DEFAULT_MODEL_CACHE_DIR,
        help="Directory for downloaded model weights (default: .cache/lyric-transcriber/models)",
    )
    export.add_argument(
        "--minus-one", action="store_true",
        help="Also generate a vocal-removed minus-one MP3 (requires --audio and Demucs)",
    )
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "transcribe":
            audio = validate_audio(args.audio)
            output = (args.output or Path("exports") / audio.stem).expanduser()
            if output.exists() or output.is_symlink():
                raise FileExistsError(f"Output already exists; choose a new directory: {output}")
            options = LineOptions(args.max_chars, args.max_seconds, args.gap_seconds)
            print("Transcribing locally. Model weights may download unless --offline is set.", file=sys.stderr)
            transcript = transcribe(
                audio,
                model=args.model,
                language=args.language,
                device=args.device,
                compute_type=args.compute_type,
                cache_dir=args.cache_dir,
                offline=args.offline,
                line_options=options,
            )
        else:
            transcript = Transcript.from_dict(json.loads(args.transcript.expanduser().read_text(encoding="utf-8")))
            audio, output = args.audio, args.output
        if args.minus_one:
            print(
                "Generating a minus-one MP3 locally; Demucs may download model weights on its first run.",
                file=sys.stderr,
            )
            if args.command == "transcribe" and args.offline:
                print("Note: --offline applies to Whisper only; Demucs may still download weights.", file=sys.stderr)
        exported = export_transcript(
            transcript, output, audio=audio, bundle=args.bundle, minus_one=args.minus_one,
            cache_dir=args.cache_dir,
        )
        print(f"Exported {len(transcript.lines)} lyric lines to {exported}")
        formats = "Formats: LRC, SRT, VTT, JSON"
        if args.bundle:
            formats += "; MP3, index.html, bundle.zip"
        if args.minus_one:
            formats += "; minus-one MP3"
        print(formats)
        if not transcript.lines:
            print("Warning: no lyrics were recognized. Check the recording, language, and model.", file=sys.stderr)
        print("Review lyrics and timing: singing, accompaniment, and silence can cause recognition errors.", file=sys.stderr)
        return 0
    except (OSError, ValueError, TranscriptionError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130
