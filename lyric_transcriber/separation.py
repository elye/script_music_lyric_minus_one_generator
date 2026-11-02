"""Optional local vocal separation for minus-one backing tracks."""

from importlib.util import find_spec
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from .transcribe import TranscriptionError, validate_audio


def generate_minus_one(audio: Path, destination: Path) -> Path:
    """Remove vocals with Demucs and write the accompaniment as an MP3 file."""
    audio = validate_audio(audio)
    destination = Path(destination)
    if find_spec("demucs") is None:
        raise TranscriptionError(
            "Minus-one generation requires Demucs. Install it with: "
            "python -m pip install -e '.[minus-one]'"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lyric-transcriber-demucs-") as temp_dir:
        command = [
            sys.executable,
            "-m",
            "demucs",
            "--two-stems",
            "vocals",
            "--name",
            "htdemucs",
            "--mp3",
            "--mp3-bitrate",
            "320",
            "--out",
            temp_dir,
            str(audio),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False)
        except OSError as error:
            raise TranscriptionError(f"Could not start Demucs for minus-one generation: {error}") from error
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            if len(detail) > 600:
                detail = detail[-600:]
            message = f"Local minus-one generation failed (Demucs exit {result.returncode})"
            if detail:
                message += f": {detail}"
            raise TranscriptionError(
                f"{message}. Check the MP3, MP3 encoder, and model availability; the first run may download weights."
            )

        accompaniment = Path(temp_dir) / "htdemucs" / audio.stem / "no_vocals.mp3"
        if not accompaniment.is_file() or accompaniment.stat().st_size == 0:
            raise TranscriptionError("Demucs completed without producing the expected no_vocals.mp3 output")
        shutil.copyfile(accompaniment, destination)
    return destination
