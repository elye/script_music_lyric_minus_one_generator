"""Lazy faster-whisper adapter; exporting never imports the inference engine."""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .models import Line, Transcript, Word, number


DEFAULT_MODEL_CACHE_DIR = Path(".cache/lyric-transcriber/models")


class TranscriptionError(RuntimeError):
    """An actionable failure of the optional transcription engine."""


def validate_audio(path: Path) -> Path:
    path = Path(path).expanduser()
    if path.suffix.lower() != ".mp3":
        raise ValueError("Input must be an MP3 file (.mp3)")
    if not path.is_file():
        raise ValueError(f"MP3 file does not exist: {path}")
    if path.stat().st_size == 0:
        raise ValueError("MP3 file is empty")
    return path


@dataclass(frozen=True)
class LineOptions:
    max_chars: int = 42
    max_seconds: float = 8.0
    gap_seconds: float = 0.9

    def __post_init__(self) -> None:
        if type(self.max_chars) is not int or self.max_chars < 1:
            raise ValueError("max_chars must be a positive integer")
        if number(self.max_seconds, "max_seconds") <= 0:
            raise ValueError("max_seconds must be positive")
        number(self.gap_seconds, "gap_seconds")


def group_words(words: Iterable[Word], options: LineOptions) -> list[Line]:
    lines: list[Line] = []
    group: list[Word] = []

    def flush() -> None:
        if group:
            end = max(word.end for word in group)
            if end <= group[0].start:
                raise ValueError("Engine returned a lyric line with no positive duration")
            lines.append(Line(group[0].start, end, "".join(w.text for w in group).strip(), tuple(group)))
            group.clear()

    for word in words:
        if group:
            group_end = max(item.end for item in group)
            candidate = "".join(item.text for item in [*group, word]).strip()
            should_split = (
                len(candidate) > options.max_chars
                or word.end - group[0].start > options.max_seconds
                or word.start - group_end > options.gap_seconds
            )
            # Keep overlapping/zero-duration words together rather than inventing timing.
            if should_split and word.start >= group_end and group_end > group[0].start:
                flush()
        group.append(word)
    flush()
    return lines


def transcribe(
    audio: Path,
    *,
    model: str = "small",
    language: str | None = None,
    device: str = "cpu",
    compute_type: str = "int8",
    cache_dir: Path = DEFAULT_MODEL_CACHE_DIR,
    offline: bool = False,
    line_options: LineOptions | None = None,
) -> Transcript:
    audio = validate_audio(audio)
    options = line_options or LineOptions()
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise TranscriptionError(
            "Transcription dependencies are missing. In your virtual environment run: "
            "python -m pip install -e '.[transcribe]'"
        ) from error

    try:
        engine = WhisperModel(
            model,
            device=device,
            compute_type=compute_type,
            download_root=str(cache_dir.expanduser()),
            local_files_only=offline,
        )
        segments, info = engine.transcribe(
            str(audio),
            language=language,
            word_timestamps=True,
            vad_filter=False,
            condition_on_previous_text=False,
            beam_size=5,
        )
        lines: list[Line] = []
        for segment in segments:  # Inference is lazy; decoding failures can occur here.
            words = [
                Word(word.start, word.end, word.word, getattr(word, "probability", None))
                for word in (segment.words or [])
                if word.word.strip()
            ]
            if words:
                lines.extend(group_words(words, options))
            elif segment.text.strip():
                lines.append(Line(segment.start, segment.end, segment.text.strip()))
        return Transcript(
            audio_file=audio.name,
            duration=info.duration,
            language=info.language,
            language_probability=getattr(info, "language_probability", None),
            engine="faster-whisper",
            model=Path(model).name,  # Do not leak absolute local model paths into exports.
            lines=tuple(lines),
        )
    except Exception as error:
        raise TranscriptionError(
            f"Local transcription failed: {error}. Check the MP3, model availability, "
            "and device/compute-type settings. Offline mode requires cached or local weights."
        ) from error
