"""Validate the JavaScript editor's actual download against the Python exporter."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from lyric_transcriber.exporters import export_transcript
from lyric_transcriber.models import Transcript


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "Node.js is required for the editor/CLI bridge tests")
class EditorBridgeTests(unittest.TestCase):
    def downloaded_transcript(self, actions):
        script = """
const { loadPlayer } = require('./tests/player_harness.cjs');
const app = loadPlayer();
""" + actions + """
app.elements['download-json'].click();
app.downloads[0].blob.text().then(text => process.stdout.write(text));
"""
        result = subprocess.run(
            [shutil.which("node"), "-e", script], cwd=ROOT,
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return Transcript.from_dict(json.loads(result.stdout))

    def test_edited_download_round_trips_through_python_exports(self):
        transcript = self.downloaded_transcript("""
app.elements.lyrics.children[0].children[1].click();
app.elements['edit-text'].value = 'Corrected & <literal>';
app.elements['line-form'].dispatch('submit');
app.elements.offset.value = '0.25';
app.elements['apply-offset'].click();
""")
        self.assertEqual(transcript.audio_file, "demo.mp3")
        self.assertEqual(transcript.lines[0].words, ())
        self.assertEqual(transcript.lines[0].start, 1.25)
        self.assertEqual(transcript.lines[0].text, "Corrected & <literal>")
        with tempfile.TemporaryDirectory() as temp:
            output = export_transcript(transcript, Path(temp) / "corrected")
            self.assertIn("[00:01.25]Corrected & <literal>", (output / "demo.lrc").read_text())
            self.assertIn("Corrected &amp; &lt;literal&gt;", (output / "demo.vtt").read_text())
            restored = Transcript.from_dict(json.loads((output / "demo.json").read_text()))
            self.assertEqual(restored, transcript)

    def test_offset_download_retains_valid_word_timestamps(self):
        transcript = self.downloaded_transcript("""
app.elements.offset.value = '-0.5';
app.elements['apply-offset'].click();
""")
        self.assertEqual(transcript.lines[0].start, 0.5)
        self.assertEqual(transcript.lines[0].words[0].start, 0.5)
        self.assertEqual(transcript.lines[0].words[1].end, 2.5)
        self.assertEqual(transcript.lines[0].words[0].probability, 0.9)


if __name__ == "__main__":
    unittest.main()
