"""Validated, versioned intermediate representation. Times are audio seconds."""

from dataclasses import asdict, dataclass
import math
from pathlib import Path
from typing import Any


EPSILON = 0.001


def number(value: Any, name: str, minimum: float = 0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    try:
        converted = float(value)
    except OverflowError as error:
        raise ValueError(f"{name} is outside the supported numeric range") from error
    if not math.isfinite(converted) or converted < minimum:
        raise ValueError(f"{name} must be finite and at least {minimum}")
    return converted


def text(value: Any, name: str, *, allow_blank: bool = False) -> str:
    if not isinstance(value, str) or (not allow_blank and not value.strip()):
        raise ValueError(f"{name} must be a nonempty string")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{name} cannot contain control characters or newlines")
    return value


def probability(value: Any, name: str) -> None:
    if value is not None and number(value, name) > 1:
        raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str
    probability: float | None = None

    def __post_init__(self) -> None:
        number(self.start, "word.start")
        number(self.end, "word.end")
        if self.end < self.start:
            raise ValueError("word.end cannot precede word.start")
        text(self.text, "word.text")
        probability(self.probability, "word.probability")


@dataclass(frozen=True)
class Line:
    start: float
    end: float
    text: str
    words: tuple[Word, ...] = ()

    def __post_init__(self) -> None:
        number(self.start, "line.start")
        number(self.end, "line.end")
        if self.end <= self.start:
            raise ValueError("line.end must be after line.start")
        text(self.text, "line.text")
        previous = self.start
        for word in self.words:
            if word.start < self.start - EPSILON or word.end > self.end + EPSILON:
                raise ValueError("Word timestamps must be inside their line")
            if word.start < previous:
                raise ValueError("Words must be ordered by start time")
            previous = word.start
        if self.words and "".join(word.text for word in self.words).strip() != self.text.strip():
            raise ValueError("Line text must match its words; edit both or clear the words array")


@dataclass(frozen=True)
class Transcript:
    audio_file: str
    duration: float
    language: str | None
    language_probability: float | None
    engine: str
    model: str
    lines: tuple[Line, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("Unsupported schema_version; expected integer 1")
        text(self.audio_file, "audio_file")
        if any(char in self.audio_file for char in '/\\:') or self.audio_file in (".", ".."):
            raise ValueError("audio_file must be a filename, not a path")
        if Path(self.audio_file).suffix.lower() != ".mp3":
            raise ValueError("audio_file must have an .mp3 extension")
        if number(self.duration, "duration") <= 0:
            raise ValueError("duration must be positive")
        if self.language is not None:
            text(self.language, "language")
        probability(self.language_probability, "language_probability")
        text(self.engine, "engine")
        text(self.model, "model")
        previous_end = 0.0
        for line in self.lines:
            if line.start < previous_end:
                raise ValueError("Lines must be ordered and must not overlap")
            if line.end > self.duration + EPSILON:
                raise ValueError("Line timestamps cannot exceed the audio duration")
            previous_end = line.end

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> "Transcript":
        if not isinstance(data, dict):
            raise ValueError("Transcript JSON must be an object")
        try:
            raw_lines = data["lines"]
            if not isinstance(raw_lines, list):
                raise ValueError("lines must be an array")
            lines = []
            for raw in raw_lines:
                if not isinstance(raw, dict) or not isinstance(raw.get("words", []), list):
                    raise ValueError("Each line must be an object with a words array")
                words = tuple(Word(**word) for word in raw.get("words", []))
                lines.append(Line(raw["start"], raw["end"], raw["text"], words))
            return cls(
                audio_file=data["audio_file"],
                duration=data["duration"],
                language=data["language"],
                language_probability=data.get("language_probability"),
                engine=data["engine"],
                model=data["model"],
                lines=tuple(lines),
                schema_version=data["schema_version"],
            )
        except (KeyError, TypeError) as error:
            raise ValueError(f"Malformed transcript JSON: {error}") from error
