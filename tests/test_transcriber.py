import contextlib
from dataclasses import replace
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

from lyric_transcriber.cli import main
from lyric_transcriber.exporters import (
    export_transcript, lrc_time, render_json, render_lrc, render_player,
    render_subtitles, subtitle_time, ticks,
)
from lyric_transcriber.models import Line, Transcript, Word
from lyric_transcriber.separation import generate_minus_one
from lyric_transcriber.transcribe import (
    LineOptions, TranscriptionError, group_words, transcribe, validate_audio,
)


def sample():
    return Transcript(
        audio_file="song.mp3", duration=12.0, language="en", language_probability=0.98,
        engine="test-fixture", model="synthetic",
        lines=(
            Line(1.25, 3.0, "Hello world", (Word(1.25, 2.0, "Hello", 0.9), Word(2.0, 3.0, " world", 0.8))),
            Line(5.0, 6.5, "Again", (Word(5.0, 6.5, "Again", 0.95),)),
        ),
    )


class ModelTests(unittest.TestCase):
    def test_json_round_trip(self):
        self.assertEqual(Transcript.from_dict(json.loads(render_json(sample()))), sample())

    def test_invalid_numbers(self):
        for invalid in (-1, float("nan"), float("inf"), True, "1", 10 ** 1000):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                Word(invalid, 2, "test")

    def test_probabilities(self):
        for invalid in (-0.1, 1.1, float("nan"), True):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                Word(0, 1, "test", invalid)

    def test_invalid_duration_and_schema(self):
        for update in ({"duration": 0}, {"duration": float("nan")}, {"schema_version": 2}, {"schema_version": True}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                replace(sample(), **update)

    def test_invalid_line_times(self):
        for start, end in ((2, 1), (1, 1), (-1, 1)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                Line(start, end, "test")

    def test_bad_word_alignment(self):
        for words in (
            (Word(0, 2, "test"),),
            (Word(1, 4, "test"),),
            (Word(2, 3, "a"), Word(1, 2, "b")),
        ):
            with self.subTest(words=words), self.assertRaises(ValueError):
                Line(1, 3, "test", words)

    def test_stale_word_text_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "clear the words"):
            replace(sample().lines[0], text="Corrected lyrics")
        self.assertEqual(replace(sample().lines[0], text="Corrected lyrics", words=()).text, "Corrected lyrics")

    def test_lines_cannot_overlap_or_exceed_audio(self):
        for lines in ((Line(1, 4, "a"), Line(3, 5, "b")), (Line(10, 13, "a"),)):
            with self.subTest(lines=lines), self.assertRaises(ValueError):
                replace(sample(), lines=lines)

    def test_invalid_audio_names(self):
        for name in ("../song.mp3", "a/b.mp3", "a\\b.mp3", "a:b.mp3", "a\n.mp3", "song.wav"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                replace(sample(), audio_file=name)

    def test_malformed_json_structures(self):
        for data in ([], {}, {**sample().to_dict(), "lines": {}}, {**sample().to_dict(), "lines": [None]}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                Transcript.from_dict(data)

    def test_control_characters_rejected(self):
        for content in ("", " \t", "a\nb", "a\x00b", "a\rb"):
            with self.subTest(content=content), self.assertRaises(ValueError):
                Line(0, 1, content)


class SegmentationTests(unittest.TestCase):
    def test_splits_at_pause_without_shifting_time(self):
        result = group_words((Word(2, 3, "Hi"), Word(5, 6, " there")), LineOptions())
        self.assertEqual([(line.start, line.end, line.text) for line in result], [(2, 3, "Hi"), (5, 6, "there")])

    def test_character_limit(self):
        result = group_words((Word(0, 1, "Hello"), Word(1, 2, " world")), LineOptions(max_chars=5))
        self.assertEqual([line.text for line in result], ["Hello", "world"])

    def test_duration_limit(self):
        result = group_words((Word(0, 2, "One"), Word(2, 4, " two")), LineOptions(max_seconds=3))
        self.assertEqual(len(result), 2)

    def test_overlapping_words_stay_together(self):
        result = group_words((Word(0, 2, "Hello"), Word(1, 3, " there")), LineOptions(max_chars=1))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].end, 3)

    def test_cjk_spacing_is_preserved(self):
        result = group_words((Word(0, 1, "你"), Word(1, 2, "好")), LineOptions())
        self.assertEqual(result[0].text, "你好")

    def test_zero_duration_words_do_not_create_empty_line(self):
        result = group_words((Word(0, 0, "A"), Word(0, 1, " word")), LineOptions(max_chars=1))
        self.assertEqual(result[0].text, "A word")
        with self.assertRaises(ValueError):
            group_words((Word(0, 0, "A"),), LineOptions())

    def test_invalid_options(self):
        for option in ({"max_chars": 0}, {"max_chars": True}, {"max_seconds": 0}, {"gap_seconds": -1}, {"max_seconds": float("nan")}):
            with self.subTest(option=option), self.assertRaises(ValueError):
                LineOptions(**option)


class ExportTests(unittest.TestCase):
    def test_timestamp_rounding_carries(self):
        self.assertEqual(lrc_time(ticks(59.999, 100)), "01:00.00")
        self.assertEqual(subtitle_time(ticks(3599.9996, 1000), ","), "01:00:00,000")

    def test_lrc_clears_instrumental_gaps(self):
        self.assertEqual(render_lrc(sample()), "[00:00.00]\n[00:01.25]Hello world\n[00:03.00]\n[00:05.00]Again\n[00:06.50]\n")

    def test_contiguous_lines_do_not_have_duplicate_end_markers(self):
        transcript = replace(sample(), lines=(Line(0, 1, "A"), Line(1, 2, "B")))
        self.assertEqual(render_lrc(transcript).count("[00:01.00]"), 1)

    def test_srt_and_vtt(self):
        self.assertIn("1\n00:00:01,250 --> 00:00:03,000\nHello world", render_subtitles(sample()))
        self.assertTrue(render_subtitles(sample(), vtt=True).startswith("WEBVTT\n\n1\n00:00:01.250"))

    def test_subtitle_text_escaping(self):
        transcript = replace(sample(), lines=(Line(0, 1, "<b>A & B</b> -->"),))
        self.assertIn("&lt;b&gt;A &amp; B&lt;/b&gt; --&gt;", render_subtitles(transcript, vtt=True))

    def test_player_escapes_embedded_data_and_audio_url(self):
        lyric = '</script><script>alert("x")</script> & 你好'
        transcript = replace(sample(), audio_file='a #"song.mp3', lines=(Line(0, 1, lyric),))
        player = render_player(transcript)
        self.assertNotIn(lyric, player)
        self.assertIn('src="a%20%23%22song.mp3"', player)
        self.assertIn('<label id="track-control" hidden>', player)
        data = player.split('<script id="transcript" type="application/json">', 1)[1].split('</script>', 1)[0]
        self.assertEqual(json.loads(data)["lines"][0]["text"], lyric)
        self.assertNotIn("__TRANSCRIPT_DATA__", player)
        self.assertNotIn("__AUDIO_SOURCE__", player)
        self.assertNotIn("__PLAYER_SCRIPT__", player)
        self.assertIn("function replaceLine(", player)
        self.assertNotIn('<script src=', player)

    def test_minus_one_player_exposes_track_switch(self):
        player = render_player(sample(), minus_one=True)
        self.assertIn('<label id="track-control">', player)
        self.assertIn('<option value="song.mp3" selected>Original</option>', player)
        self.assertIn('<option value="song-minus-one.mp3">Minus one</option>', player)

    def test_template_tokens_in_user_data_are_not_expanded(self):
        lyric = "__PLAYER_SCRIPT__ __AUDIO_SOURCE__ __TRANSCRIPT_DATA__ __MINUS_ONE_SOURCE__ __TRACK_CONTROL_HIDDEN__"
        transcript = replace(sample(), audio_file="__TRANSCRIPT_DATA__.mp3", lines=(Line(0, 1, lyric),))
        player = render_player(transcript)
        self.assertIn('src="__TRANSCRIPT_DATA__.mp3"', player)
        data = player.split('<script id="transcript" type="application/json">', 1)[1].split('</script>', 1)[0]
        self.assertEqual(json.loads(data)["lines"][0]["text"], lyric)
        self.assertEqual(player.count("function replaceLine("), 1)

    def test_empty_transcript_is_valid(self):
        empty = replace(sample(), lines=())
        self.assertEqual(render_lrc(empty), "")
        self.assertEqual(render_subtitles(empty), "")
        self.assertEqual(render_subtitles(empty, vtt=True), "WEBVTT\n\n")

    def test_bundle_contents_and_unchanged_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            audio = root / "song.mp3"
            original = b"synthetic fixture; decoder not used in export tests"
            audio.write_bytes(original)
            output = export_transcript(sample(), root / "result", audio=audio, bundle=True)
            expected = {"song.mp3", "song.lrc", "song.srt", "song.vtt", "song.json", "index.html"}
            self.assertEqual({p.name for p in output.iterdir()}, expected | {"bundle.zip"})
            with zipfile.ZipFile(output / "bundle.zip") as archive:
                self.assertEqual(set(archive.namelist()), expected)
                self.assertEqual(archive.read("song.mp3"), original)
                self.assertIsNone(archive.testzip())
            self.assertEqual((output / "song.mp3").read_bytes(), original)

    def test_minus_one_is_written_and_included_in_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            audio = root / "song.mp3"
            audio.write_bytes(b"original audio")

            def generate(audio_path, destination):
                destination.write_bytes(b"minus-one audio")
                return destination

            with patch("lyric_transcriber.separation.generate_minus_one", side_effect=generate):
                output = export_transcript(sample(), root / "out", audio=audio, bundle=True, minus_one=True)

            minus_one_file = output / "song-minus-one.mp3"
            self.assertEqual(minus_one_file.read_bytes(), b"minus-one audio")
            player = (output / "index.html").read_text(encoding="utf-8")
            self.assertIn('<option value="song-minus-one.mp3">Minus one</option>', player)
            with zipfile.ZipFile(output / "bundle.zip") as archive:
                self.assertIn("song-minus-one.mp3", archive.namelist())
                self.assertEqual(archive.read("song-minus-one.mp3"), b"minus-one audio")
                self.assertIn('<option value="song-minus-one.mp3">Minus one</option>', archive.read("index.html").decode("utf-8"))

    def test_minus_one_requires_original_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "requires the original MP3"):
                export_transcript(sample(), Path(temp) / "out", minus_one=True)

    def test_sidecar_export_has_no_audio_or_player(self):
        with tempfile.TemporaryDirectory() as temp:
            output = export_transcript(sample(), Path(temp) / "out")
            self.assertEqual({p.suffix for p in output.iterdir()}, {".json", ".lrc", ".srt", ".vtt"})

    def test_broken_output_symlink_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "out"
            output.symlink_to(Path(temp) / "missing", target_is_directory=True)
            with self.assertRaises(FileExistsError):
                export_transcript(sample(), output)
            self.assertTrue(output.is_symlink())

    def test_output_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "existing"
            output.mkdir()
            with self.assertRaises(FileExistsError):
                export_transcript(sample(), output)
            self.assertEqual(list(output.iterdir()), [])

    def test_bundle_requires_matching_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(ValueError, "requires"):
                export_transcript(sample(), root / "out", bundle=True)
            audio = root / "other.mp3"
            audio.write_bytes(b"test")
            with self.assertRaisesRegex(ValueError, "filename"):
                export_transcript(sample(), root / "out", audio=audio, bundle=True)
            self.assertFalse((root / "out").exists())

    def test_failed_bundle_cleans_staging_and_does_not_publish(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            audio = root / "song.mp3"
            audio.write_bytes(b"test")
            with patch("lyric_transcriber.exporters.shutil.copyfile", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    export_transcript(sample(), root / "out", audio=audio, bundle=True)
            self.assertEqual({p.name for p in root.iterdir()}, {"song.mp3"})

    def test_failed_publish_cleans_reserved_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch("lyric_transcriber.exporters.os.replace", side_effect=OSError("publish failed")):
                with self.assertRaises(OSError):
                    export_transcript(sample(), root / "out")
            self.assertEqual(list(root.iterdir()), [])

    def test_concurrent_destination_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "out"
            original = render_json
            def concurrent_writer(transcript):
                output.mkdir()
                (output / "keep.txt").write_text("do not overwrite")
                return original(transcript)
            with patch("lyric_transcriber.exporters.render_json", side_effect=concurrent_writer):
                with self.assertRaises(FileExistsError):
                    export_transcript(sample(), output)
            self.assertEqual((output / "keep.txt").read_text(), "do not overwrite")
            self.assertEqual({p.name for p in root.iterdir()}, {"out"})


class SeparationTests(unittest.TestCase):
    def test_generates_minus_one_mp3_with_demucs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            audio = root / "song.mp3"
            audio.write_bytes(b"fixture")
            destination = root / "song-minus-one.mp3"

            def run_demucs(command, **kwargs):
                demucs_output = Path(command[command.index("--out") + 1])
                accompaniment = demucs_output / "htdemucs" / "song" / "no_vocals.mp3"
                accompaniment.parent.mkdir(parents=True)
                accompaniment.write_bytes(b"minus-one audio")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("lyric_transcriber.separation.find_spec", return_value=object()), patch(
                "lyric_transcriber.separation.subprocess.run", side_effect=run_demucs
            ) as runner:
                result = generate_minus_one(audio, destination)

            self.assertEqual(result, destination)
            self.assertEqual(destination.read_bytes(), b"minus-one audio")
            command = runner.call_args.args[0]
            self.assertEqual(
                command[2:10],
                ["demucs", "--two-stems", "vocals", "--name", "htdemucs", "--mp3", "--mp3-bitrate", "320"],
            )
            self.assertEqual(runner.call_args.kwargs["check"], False)

    def test_missing_demucs_has_install_instructions(self):
        with tempfile.TemporaryDirectory() as temp:
            audio = Path(temp) / "song.mp3"
            audio.write_bytes(b"fixture")
            with patch("lyric_transcriber.separation.find_spec", return_value=None):
                with self.assertRaisesRegex(TranscriptionError, "pip install -e '\\.\\[minus-one\\]'" ):
                    generate_minus_one(audio, Path(temp) / "output.mp3")


class AdapterTests(unittest.TestCase):
    def test_audio_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for path in (root / "missing.mp3", root / "wrong.wav"):
                with self.assertRaises(ValueError):
                    validate_audio(path)
            audio = root / "audio.MP3"
            audio.touch()
            with self.assertRaisesRegex(ValueError, "empty"):
                validate_audio(audio)
            audio.write_bytes(b"fixture")
            self.assertEqual(validate_audio(audio), audio)

    def test_adapter_configuration_and_word_times(self):
        with tempfile.TemporaryDirectory() as temp:
            audio = Path(temp) / "song.mp3"
            audio.write_bytes(b"fixture")
            word = SimpleNamespace(start=1.25, end=2.5, word=" Hello", probability=0.88)
            segments = iter([
                SimpleNamespace(start=1, end=3, text=" Hello", words=[word]),
                SimpleNamespace(start=5, end=6, text=" Segment only", words=None),
            ])
            model = Mock()
            model.transcribe.return_value = (segments, SimpleNamespace(duration=10, language="en", language_probability=0.9))
            factory = Mock(return_value=model)
            with patch.dict(sys.modules, {"faster_whisper": SimpleNamespace(WhisperModel=factory)}):
                result = transcribe(audio, model="tiny", offline=True, cache_dir=Path(temp) / "models", language="en")
            self.assertTrue(factory.call_args.kwargs["local_files_only"])
            self.assertEqual(factory.call_args.kwargs["compute_type"], "int8")
            self.assertEqual(model.transcribe.call_args.kwargs, {
                "language": "en", "word_timestamps": True, "vad_filter": False,
                "condition_on_previous_text": False, "beam_size": 5,
            })
            self.assertEqual(result.lines[0].start, 1.25)
            self.assertEqual(result.lines[0].words[0].probability, 0.88)
            self.assertEqual(result.lines[1].words, ())

    def test_missing_dependency_is_actionable(self):
        with tempfile.TemporaryDirectory() as temp:
            audio = Path(temp) / "song.mp3"
            audio.write_bytes(b"fixture")
            with patch.dict(sys.modules, {"faster_whisper": None}):
                with self.assertRaisesRegex(TranscriptionError, "pip install"):
                    transcribe(audio)

    def test_lazy_engine_failure_is_wrapped(self):
        def broken_segments():
            raise RuntimeError("decoder failed")
            yield  # Model segments are lazily evaluated.
        with tempfile.TemporaryDirectory() as temp:
            audio = Path(temp) / "song.mp3"
            audio.write_bytes(b"fixture")
            model = Mock()
            model.transcribe.return_value = (broken_segments(), SimpleNamespace(duration=10))
            with patch.dict(sys.modules, {"faster_whisper": SimpleNamespace(WhisperModel=Mock(return_value=model))}):
                with self.assertRaisesRegex(TranscriptionError, "decoder failed"):
                    transcribe(audio)


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_export_command_without_engine(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "corrected.json"
            source.write_text(render_json(sample()), encoding="utf-8")
            with patch.dict(sys.modules, {"faster_whisper": None}):
                code, out, err = self.run_cli("export", str(source), "--output", str(root / "out"))
            self.assertEqual(code, 0, err)
            self.assertIn("Exported 2 lyric lines", out)
            self.assertTrue((root / "out" / "song.lrc").exists())

    def test_invalid_json_returns_nonzero_without_traceback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "bad.json"
            source.write_text("{broken", encoding="utf-8")
            code, out, err = self.run_cli("export", str(source), "--output", str(root / "out"))
            self.assertEqual(code, 1)
            self.assertIn("Error:", err)
            self.assertNotIn("Traceback", err)
            self.assertFalse((root / "out").exists())

    def test_preflight_output_conflict_avoids_inference(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            audio = root / "song.mp3"
            audio.write_bytes(b"fixture")
            with patch("lyric_transcriber.cli.transcribe") as engine:
                code, _, err = self.run_cli("transcribe", str(audio), "--output", str(root))
            self.assertEqual(code, 1)
            self.assertIn("already exists", err)
            engine.assert_not_called()

    def test_transcribe_minus_one_flag_reaches_export(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            audio = root / "song.mp3"
            audio.write_bytes(b"fixture")
            output = root / "out"
            with patch("lyric_transcriber.cli.transcribe", return_value=sample()), patch(
                "lyric_transcriber.cli.export_transcript", return_value=output
            ) as export:
                code, out, err = self.run_cli(
                    "transcribe", str(audio), "--output", str(output), "--minus-one", "--bundle"
                )
            self.assertEqual(code, 0, err)
            self.assertIn("minus-one MP3", out)
            self.assertEqual(export.call_args.kwargs["minus_one"], True)
            self.assertEqual(export.call_args.kwargs["bundle"], True)

    def test_empty_transcription_warns(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            audio = root / "song.mp3"
            audio.write_bytes(b"fixture")
            with patch("lyric_transcriber.cli.transcribe", return_value=replace(sample(), lines=())):
                code, _, err = self.run_cli("transcribe", str(audio), "--output", str(root / "out"))
            self.assertEqual(code, 0)
            self.assertIn("no lyrics were recognized", err)

    def test_module_entrypoint_help(self):
        result = subprocess.run([sys.executable, "-m", "lyric_transcriber", "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("transcribe", result.stdout)


if __name__ == "__main__":
    unittest.main()
