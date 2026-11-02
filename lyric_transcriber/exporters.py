"""Deterministic sidecars and an all-or-nothing portable export directory."""

import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import quote
import zipfile

from .models import Transcript
from .transcribe import validate_audio


def ticks(seconds: float, resolution: int) -> int:
    return math.floor(seconds * resolution + 0.5)


def lrc_time(centiseconds: int) -> str:
    minutes, remainder = divmod(centiseconds, 6000)
    seconds, fraction = divmod(remainder, 100)
    return f"{minutes:02}:{seconds:02}.{fraction:02}"


def subtitle_time(milliseconds: int, separator: str) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, fraction = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}{separator}{fraction:03}"


def render_lrc(transcript: Transcript) -> str:
    rows = []
    if transcript.lines and ticks(transcript.lines[0].start, 100) > 0:
        rows.append("[00:00.00]")
    for index, line in enumerate(transcript.lines):
        rows.append(f"[{lrc_time(ticks(line.start, 100))}]{line.text}")
        end = ticks(line.end, 100)
        next_start = ticks(transcript.lines[index + 1].start, 100) if index + 1 < len(transcript.lines) else None
        if end > ticks(line.start, 100) and (next_start is None or end < next_start):
            rows.append(f"[{lrc_time(end)}]")
    return "\n".join(rows) + ("\n" if rows else "")


def render_subtitles(transcript: Transcript, *, vtt: bool = False) -> str:
    blocks = ["WEBVTT"] if vtt else []
    separator = "." if vtt else ","
    for index, line in enumerate(transcript.lines, 1):
        start = ticks(line.start, 1000)
        end = max(start + 1, ticks(line.end, 1000))
        timing = f"{subtitle_time(start, separator)} --> {subtitle_time(end, separator)}"
        # Lyrics are plain text, never subtitle markup or cue syntax.
        lyric = html.escape(line.text, quote=False)
        blocks.append(f"{index}\n{timing}\n{lyric}")
    return "\n\n".join(blocks) + ("\n\n" if blocks else "")


def render_json(transcript: Transcript) -> str:
    return json.dumps(transcript.to_dict(), ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def render_player(transcript: Transcript, *, minus_one: bool = False) -> str:
    data = render_json(transcript)
    for original, escaped in (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e"), ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        data = data.replace(original, escaped)
    template = Path(__file__).with_name("player.html").read_text(encoding="utf-8")
    audio_source = html.escape(quote(transcript.audio_file, safe=""), quote=True)
    minus_one_source = html.escape(
        quote(f"{Path(transcript.audio_file).stem}-minus-one.mp3", safe=""), quote=True
    ) if minus_one else ""
    replacements = {
        "AUDIO_SOURCE": audio_source,
        "MINUS_ONE_SOURCE": minus_one_source,
        "TRACK_CONTROL_HIDDEN": "" if minus_one else " hidden",
        "TRANSCRIPT_DATA": data,
        "PLAYER_SCRIPT": Path(__file__).with_name("player.js").read_text(encoding="utf-8"),
    }
    # Substitute only tokens in the template, never token-like text in user data.
    return re.sub(
        r"__(AUDIO_SOURCE|MINUS_ONE_SOURCE|TRACK_CONTROL_HIDDEN|TRANSCRIPT_DATA|PLAYER_SCRIPT)__",
        lambda match: replacements[match[1]], template,
    )


def export_transcript(
    transcript: Transcript,
    output: Path,
    *,
    audio: Path | None = None,
    bundle: bool = False,
    minus_one: bool = False,
) -> Path:
    output = Path(output).expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Output already exists; choose a new directory: {output}")
    if audio is not None:
        audio = validate_audio(audio)
        if audio.name != transcript.audio_file:
            raise ValueError("The MP3 filename must match audio_file in the transcript JSON")
    if bundle and audio is None:
        raise ValueError("A portable bundle requires the original MP3 (--audio)")
    if minus_one and audio is None:
        raise ValueError("Minus-one generation requires the original MP3 (--audio)")

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    reserved = False
    try:
        stem = Path(transcript.audio_file).stem
        files = {
            f"{stem}.json": render_json(transcript),
            f"{stem}.lrc": render_lrc(transcript),
            f"{stem}.srt": render_subtitles(transcript),
            f"{stem}.vtt": render_subtitles(transcript, vtt=True),
        }
        for name, contents in files.items():
            (staging / name).write_text(contents, encoding="utf-8")
        if minus_one:
            from .separation import generate_minus_one

            generate_minus_one(audio, staging / f"{stem}-minus-one.mp3")
        if bundle:
            shutil.copyfile(audio, staging / transcript.audio_file)
            (staging / "index.html").write_text(render_player(transcript, minus_one=minus_one), encoding="utf-8")
            # Store audio without recompressing; MP3 is already compressed.
            with zipfile.ZipFile(staging / "bundle.zip", "w") as archive:
                for path in sorted(staging.iterdir()):
                    if path.name != "bundle.zip":
                        compression = zipfile.ZIP_STORED if path.suffix.lower() == ".mp3" else zipfile.ZIP_DEFLATED
                        archive.write(path, arcname=path.name, compress_type=compression)
        # Reserve a new destination atomically; never replace a pre-existing directory.
        output.mkdir(exist_ok=False)
        reserved = True
        os.replace(staging, output)
        reserved = False
        return output
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if reserved:
            output.rmdir()  # Only the empty directory created by this invocation.
