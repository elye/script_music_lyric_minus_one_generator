const assert = require('node:assert/strict');
const test = require('node:test');
const { fixture, loadPlayer } = require('./player_harness.cjs');

function openFirst(app) { app.elements.lyrics.children[0].children[1].click(); }
function submit(app) { app.elements['line-form'].dispatch('submit'); }
function editText(app, value) { openFirst(app); app.elements['edit-text'].value = value; submit(app); }
function offset(app, value) { app.elements.offset.value = value; app.elements['apply-offset'].click(); }

// Exercise the same events used by the page, not a parallel editor implementation.
test('a text correction clears only that line’s stale word alignment', () => {
  const app = loadPlayer();
  editText(app, 'Corrected words');
  assert.equal(app.data().lines[0].text, 'Corrected words');
  assert.deepEqual(app.data().lines[0].words, []);
  assert.deepEqual(app.data().lines[1], fixture().lines[1]);
  assert.equal(app.elements['line-editor'].open, false);
  assert.match(app.elements['change-state'].textContent, /Undownloaded/);
  assert.equal(app.elements.lyrics.children[0].children[0].children[1].textContent, 'Corrected words');
});

test('an unchanged form preserves words and sub-millisecond timestamps', () => {
  const input = fixture();
  input.lines[0].start = input.lines[0].words[0].start = 1.000123456;
  input.lines[0].end = 3.000789;
  const app = loadPlayer(input);
  openFirst(app);
  assert.equal(app.elements['edit-start'].value, '1');
  submit(app);
  assert.deepEqual(app.data(), input);
  assert.equal(app.elements.undo.disabled, true);
});

test('changing only a line boundary clears words, and undo restores them', () => {
  const app = loadPlayer();
  openFirst(app);
  app.elements['edit-start'].value = '1.5';
  submit(app);
  assert.equal(app.data().lines[0].start, 1.5);
  assert.deepEqual(app.data().lines[0].words, []);
  app.elements.undo.click();
  assert.deepEqual(app.data(), fixture());
});

test('invalid line edits fail atomically and keep the dialog open', () => {
  for (const [field, value, message] of [
    ['edit-text', '', /nonempty/], ['edit-text', 'hello\nworld', /single-line/],
    ['edit-start', '', /finite/], ['edit-start', '-1', /zero or later/],
    ['edit-end', '0', /after start/], ['edit-end', '10.5', /beyond/],
    ['edit-end', '5.1', /overlaps/], ['edit-start', 'NaN', /finite/],
  ]) {
    const app = loadPlayer();
    openFirst(app);
    app.elements[field].value = value;
    submit(app);
    assert.match(app.elements['edit-error'].textContent, message);
    assert.equal(app.elements['line-editor'].open, true);
    assert.deepEqual(app.data(), fixture());
    assert.equal(app.elements.undo.disabled, true);
  }
});

test('cancel discards only the current draft', () => {
  const app = loadPlayer();
  openFirst(app);
  app.elements['edit-text'].value = 'Discard this draft';
  assert(app.window.dispatch('beforeunload').prevented);
  app.elements['cancel-edit'].click();
  assert.deepEqual(app.data(), fixture());
  assert(!app.window.dispatch('beforeunload').prevented);
});

test('playhead buttons capture start and end positions', () => {
  const app = loadPlayer();
  openFirst(app);
  app.audio.currentTime = 1.5;
  app.elements['start-here'].click();
  app.audio.currentTime = 2.5;
  app.elements['end-here'].click();
  submit(app);
  assert.equal(app.data().lines[0].start, 1.5);
  assert.equal(app.data().lines[0].end, 2.5);
});

test('positive and negative offsets preserve word alignment and confidence', () => {
  const app = loadPlayer();
  offset(app, '0.25');
  assert.equal(app.data().lines[0].start, 1.25);
  assert.equal(app.data().lines[0].words[0].start, 1.25);
  assert.equal(app.data().lines[0].words[1].end, 3.25);
  assert.equal(app.data().lines[0].words[0].probability, 0.9);
  assert.equal(app.data().duration, 10);
  assert.equal(app.elements.offset.value, '0');
  offset(app, '-0.25');
  assert.deepEqual(app.data(), fixture());
});

test('offset validation rejects blank, nonfinite, negative, and out-of-range results without clamping', () => {
  for (const value of ['', 'Infinity', 'NaN', '-2', '5']) {
    const app = loadPlayer();
    offset(app, value);
    assert.deepEqual(app.data(), fixture());
    assert.equal(app.elements.undo.disabled, true);
    assert.match(app.elements.status.textContent, /finite|zero or later|beyond/);
  }
});

test('zero offset is a no-op', () => {
  const app = loadPlayer();
  offset(app, '0');
  assert.deepEqual(app.data(), fixture());
  assert.equal(app.elements.undo.disabled, true);
});

test('add a missing lyric in a gap and keep chronological order', () => {
  const app = loadPlayer();
  app.audio.currentTime = 3;
  app.elements['add-line'].click();
  assert.equal(app.elements['remove-line'].hidden, true);
  app.elements['edit-text'].value = 'Missing lyric';
  submit(app);
  assert.equal(app.data().lines.length, 3);
  assert.deepEqual(app.data().lines[1], { start: 3, end: 5, text: 'Missing lyric', words: [] });
  app.elements.undo.click();
  assert.deepEqual(app.data(), fixture());
});

test('moving a line to a non-overlapping position reorders it', () => {
  const app = loadPlayer();
  openFirst(app);
  app.elements['edit-start'].value = '7';
  app.elements['edit-end'].value = '8';
  submit(app);
  assert.deepEqual(app.data().lines.map(line => line.text), ['Line only', 'Hello world']);
});

test('remove a hallucinated line and undo without losing its words', () => {
  const app = loadPlayer();
  openFirst(app);
  app.elements['remove-line'].click();
  assert.equal(app.data().lines.length, 1);
  assert.equal(app.data().lines[0].text, 'Line only');
  app.elements.undo.click();
  assert.deepEqual(app.data(), fixture());
});

test('empty transcripts allow adding a first line and safely disable offsets', () => {
  const input = fixture();
  input.lines = [];
  const app = loadPlayer(input);
  assert.equal(app.elements['apply-offset'].disabled, true);
  app.elements['add-line'].click();
  app.elements['edit-text'].value = 'First line';
  submit(app);
  assert.equal(app.data().lines.length, 1);
  assert.equal(app.elements['apply-offset'].disabled, false);
});

test('edited lyric markup stays plain text rather than HTML', () => {
  const app = loadPlayer();
  const text = '</script><img src=x onerror=alert(1)> & 你好';
  editText(app, text);
  assert.equal(app.elements.lyrics.children[0].children[0].children[1].textContent, text);
  assert.equal(app.data().lines[0].text, text);
});

test('download serializes corrected JSON without renaming the original MP3', async () => {
  const app = loadPlayer();
  editText(app, 'Corrected words');
  assert(app.window.dispatch('beforeunload').prevented);
  app.elements['download-json'].click();
  assert.equal(app.downloads.length, 1);
  assert.equal(app.downloads[0].name, 'demo.corrected.json');
  const parsed = JSON.parse(await app.downloads[0].blob.text());
  assert.deepEqual(parsed, app.data());
  assert.equal(parsed.audio_file, 'demo.mp3');
  assert(!app.window.dispatch('beforeunload').prevented);
  app.elements.undo.click();
  assert(app.window.dispatch('beforeunload').prevented);
  for (const callback of app.timers) callback();
});

test('failed downloads do not mark edits as saved', () => {
  const app = loadPlayer();
  editText(app, 'Corrected words');
  app.evaluate('URL.createObjectURL = () => { throw new Error("blocked"); }');
  app.elements['download-json'].click();
  assert.match(app.elements.status.textContent, /Download failed: blocked/);
  assert(app.window.dispatch('beforeunload').prevented);
});

test('undo history is bounded to the latest 25 changes', () => {
  const app = loadPlayer();
  for (let i = 0; i < 30; i += 1) editText(app, `Correction ${i}`);
  assert.equal(app.evaluate('history.length'), 25);
  for (let i = 0; i < 25; i += 1) app.elements.undo.click();
  assert.equal(app.data().lines[0].text, 'Correction 4');
  assert.equal(app.elements.undo.disabled, true);
});

test('word constraints mirror the Python validator', () => {
  const app = loadPlayer();
  for (const mutation of [
    'lines[0].words[0].start = -1', 'lines[0].words[0].end = 4',
    'lines[0].words[1].start = 0.5', 'lines[0].words[0].text = "other"',
    'lines[0].words[0].probability = 2', 'lines[0].words[0].probability = true',
    'lines[0].words[0].start = NaN',
  ]) {
    assert.throws(() => app.evaluate(`{ const lines = JSON.parse(JSON.stringify(transcript.lines)); ${mutation}; validateLines(lines, 10); }`));
  }
});
