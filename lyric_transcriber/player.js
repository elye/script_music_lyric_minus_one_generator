'use strict';

// Keep these constraints in sync with models.py. No automatic realignment occurs here.
function validateLines(lines, duration) {
  if (!Number.isFinite(duration) || duration <= 0) throw new Error('Invalid audio duration.');
  const validText = value => typeof value === 'string' && value.trim() && !/[\x00-\x1f\x7f]/.test(value);
  let previousEnd = 0;
  for (const [index, line] of lines.entries()) {
    const prefix = `Line ${index + 1}: `;
    if (!validText(line.text)) throw new Error(prefix + 'enter nonempty, single-line lyrics.');
    if (!Number.isFinite(line.start) || !Number.isFinite(line.end) || line.start < 0 || line.end <= line.start) {
      throw new Error(prefix + 'start must be zero or later, and end must be after start.');
    }
    if (line.end > duration + 0.001) throw new Error(prefix + 'timing goes beyond the recording.');
    if (line.start < previousEnd) throw new Error(prefix + 'timing overlaps another line. Adjust the start or end.');
    previousEnd = line.end;
    let previousWord = line.start;
    for (const word of line.words) {
      if (!validText(word.text) || !Number.isFinite(word.start) || !Number.isFinite(word.end)
          || word.start < 0 || word.end < word.start || word.start < previousWord
          || word.start < line.start - 0.001 || word.end > line.end + 0.001) {
        throw new Error(prefix + 'invalid word alignment.');
      }
      if (word.probability != null && (!Number.isFinite(word.probability) || word.probability < 0 || word.probability > 1)) {
        throw new Error(prefix + 'invalid word probability.');
      }
      previousWord = word.start;
    }
    if (line.words.length && line.words.map(word => word.text).join('').trim() !== line.text.trim()) {
      throw new Error(prefix + 'word text does not match the lyric.');
    }
  }
  return lines;
}

function replaceLine(lines, index, text, start, end, duration) {
  const original = index >= 0 ? lines[index] : null;
  const unchanged = original && original.text === text && original.start === start && original.end === end;
  const replacement = unchanged ? original : { start, end, text, words: [] };
  const next = [...lines];
  if (index < 0) next.push(replacement);
  else next[index] = replacement;
  next.sort((a, b) => a.start - b.start);
  return validateLines(next, duration);
}

function shiftLines(lines, seconds, duration) {
  if (!Number.isFinite(seconds)) throw new Error('Enter a finite offset in seconds.');
  return validateLines(lines.map(line => ({
    ...line, start: line.start + seconds, end: line.end + seconds,
    words: line.words.map(word => ({ ...word, start: word.start + seconds, end: word.end + seconds })),
  })), duration);
}

function parseSeconds(value, label) {
  if (!value.trim() || !Number.isFinite(Number(value))) throw new Error(`${label} must be a finite number of seconds.`);
  return Number(value);
}

const transcript = JSON.parse(document.getElementById('transcript').textContent);
const element = id => document.getElementById(id);
const audio = element('audio');
const audioTrack = element('audio-track');
const lyrics = element('lyrics');
const status = element('status');
const clock = element('clock');
const follow = element('follow');
const dialog = element('line-editor');
const editText = element('edit-text');
const editStart = element('edit-start');
const editEnd = element('edit-end');
const editError = element('edit-error');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const fingerprint = () => JSON.stringify(transcript.lines);
let savedLines = fingerprint();
const originalLines = savedLines;
const history = [];
let rows = [];
let active = -1;
let editingIndex = -1;
let draft = null;
element('title').textContent = transcript.audio_file;
const formatTime = seconds => {
  const whole = Math.max(0, Math.floor(seconds || 0));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
};
const displaySeconds = seconds => String(Math.round(seconds * 1000) / 1000);

function editorState() {
  element('undo').disabled = history.length === 0;
  element('apply-offset').disabled = transcript.lines.length === 0;
  element('change-state').textContent = fingerprint() !== savedLines
    ? 'Undownloaded changes — download corrected JSON before closing this tab.'
    : savedLines === originalLines ? 'No pending changes.' : 'Current edits were sent to a JSON download. Keep that file to preserve them.';
}

function renderLines() {
  active = -1;
  lyrics.replaceChildren();
  rows = transcript.lines.map((line, index) => {
    const container = document.createElement('div');
    container.className = 'lyric-row';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'line';
    button.setAttribute('aria-label', `${formatTime(line.start)} ${line.text}`);
    const stamp = document.createElement('span');
    stamp.className = 'stamp';
    stamp.textContent = formatTime(line.start);
    const label = document.createElement('span');
    label.className = 'lyric';
    const words = line.words.map(word => {
      const span = document.createElement('span');
      span.className = 'word';
      span.textContent = word.text;
      label.append(span);
      return span;
    });
    if (!words.length) label.textContent = line.text;
    button.append(stamp, label);
    button.addEventListener('click', () => {
      audio.currentTime = line.start;
      audio.play().catch(() => { status.textContent = 'Press Play in the audio controls to start playback.'; });
    });
    const edit = document.createElement('button');
    edit.type = 'button';
    edit.textContent = 'Edit';
    edit.setAttribute('aria-label', `Edit line ${index + 1}: ${line.text}`);
    edit.addEventListener('click', () => openEditor(index));
    container.append(button, edit);
    lyrics.append(container);
    return { button, words, edit };
  });
  if (!rows.length) {
    const empty = document.createElement('p');
    empty.className = 'muted';
    empty.textContent = 'No lyric lines. Use Add line to enter lyrics manually.';
    lyrics.append(empty);
  }
  editorState();
  update();
}

function activeLine(time) {
  let low = 0, high = transcript.lines.length - 1, result = -1;
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    if (transcript.lines[middle].start <= time) { result = middle; low = middle + 1; }
    else high = middle - 1;
  }
  return result >= 0 && time < transcript.lines[result].end ? result : -1;
}

function update() {
  const time = audio.currentTime;
  const next = activeLine(time);
  if (next !== active) {
    if (active >= 0) {
      rows[active].button.classList.remove('active');
      rows[active].button.removeAttribute('aria-current');
      rows[active].words.forEach(word => word.classList.remove('active'));
    }
    active = next;
    if (active >= 0) {
      rows[active].button.classList.add('active');
      rows[active].button.setAttribute('aria-current', 'true');
      if (follow.checked && !dialog.open) rows[active].button.scrollIntoView({ block: 'center', behavior: reducedMotion ? 'auto' : 'smooth' });
    }
  }
  if (active >= 0) transcript.lines[active].words.forEach((word, index) => {
    rows[active].words[index].classList.toggle('active', word.start <= time && time < word.end);
  });
  clock.textContent = `${formatTime(time)} / ${formatTime(Number.isFinite(audio.duration) ? audio.duration : transcript.duration)}`;
}

function applyLines(next, message) {
  validateLines(next, transcript.duration);
  if (JSON.stringify(next) === fingerprint()) { status.textContent = 'No changes to apply.'; return; }
  history.push(transcript.lines);
  if (history.length > 25) history.shift();
  transcript.lines = next;
  renderLines();
  status.textContent = message;
}

function openEditor(index) {
  editingIndex = index;
  const start = Math.min(Math.max(audio.currentTime || 0, 0), transcript.duration);
  const line = index >= 0 ? transcript.lines[index] : { text: '', start, end: Math.min(start + 2, transcript.duration) };
  editText.value = line.text;
  editStart.value = displaySeconds(line.start);
  editEnd.value = displaySeconds(line.end);
  editStart.max = editEnd.max = String(transcript.duration);
  // Preserve original sub-millisecond precision when an input is left unchanged.
  draft = { line, text: editText.value, start: editStart.value, end: editEnd.value };
  element('edit-title').textContent = index >= 0 ? `Edit line ${index + 1}` : 'Add lyric line';
  element('remove-line').hidden = index < 0;
  editError.textContent = '';
  dialog.showModal();
  editText.focus();
}

function pendingDraft() {
  return dialog.open && draft && (editText.value !== draft.text || editStart.value !== draft.start || editEnd.value !== draft.end);
}

element('line-form').addEventListener('submit', event => {
  event.preventDefault();
  try {
    const start = editStart.value === draft.start ? draft.line.start : parseSeconds(editStart.value, 'Start');
    const end = editEnd.value === draft.end ? draft.line.end : parseSeconds(editEnd.value, 'End');
    const next = replaceLine(transcript.lines, editingIndex, editText.value, start, end, transcript.duration);
    applyLines(next, 'Line applied. Changed lines use line-only highlighting until their words are realigned.');
    dialog.close();
    element('download-json').focus();
  } catch (error) { editError.textContent = error.message; }
});
element('cancel-edit').addEventListener('click', () => dialog.close());
element('start-here').addEventListener('click', () => { editStart.value = displaySeconds(audio.currentTime); });
element('end-here').addEventListener('click', () => { editEnd.value = displaySeconds(audio.currentTime); });
element('add-line').addEventListener('click', () => openEditor(-1));
element('remove-line').addEventListener('click', () => {
  if (editingIndex < 0) return;
  applyLines(transcript.lines.filter((_, index) => index !== editingIndex), 'Line removed. Use Undo to restore it.');
  dialog.close();
  element('undo').focus();
});
element('apply-offset').addEventListener('click', () => {
  try {
    const seconds = parseSeconds(element('offset').value, 'Offset');
    applyLines(shiftLines(transcript.lines, seconds, transcript.duration), `All timings shifted by ${seconds} seconds; word alignment preserved.`);
    element('offset').value = '0';
  } catch (error) { status.textContent = error.message; }
});
element('undo').addEventListener('click', () => {
  if (!history.length) return;
  transcript.lines = history.pop();
  renderLines();
  status.textContent = 'Last change undone.';
});
element('download-json').addEventListener('click', () => {
  try {
    validateLines(transcript.lines, transcript.duration);
    const blob = new Blob([JSON.stringify(transcript, null, 2) + '\n'], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = transcript.audio_file.slice(0, -4) + '.corrected.json';
    document.body.append(link);
    try { link.click(); } finally {
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    }
    savedLines = fingerprint();
    editorState();
    status.textContent = 'JSON download requested. Check that it was saved, then run the export command to rebuild the bundle.';
  } catch (error) { status.textContent = `Download failed: ${error.message}`; }
});
window.addEventListener('beforeunload', event => {
  if (fingerprint() !== savedLines || pendingDraft()) { event.preventDefault(); event.returnValue = ''; }
});

let sourceChange = 0;
audioTrack.addEventListener('change', () => {
  const source = audioTrack.value;
  if (!source) return;
  const change = ++sourceChange;
  const position = audio.currentTime;
  const playbackRate = audio.playbackRate;
  const resume = !audio.paused && !audio.ended;
  audio.addEventListener('loadedmetadata', () => {
    if (change !== sourceChange) return;
    const duration = Number.isFinite(audio.duration) ? audio.duration : transcript.duration;
    audio.currentTime = Math.min(position, duration);
    audio.playbackRate = playbackRate;
    update();
    if (resume) audio.play().catch(() => { status.textContent = 'Press Play in the audio controls to resume playback.'; });
  }, { once: true });
  audio.src = source;
  audio.load();
});
element('speed').addEventListener('change', event => { audio.playbackRate = Number(event.target.value); });
['timeupdate', 'seeked', 'loadedmetadata', 'pause', 'ended'].forEach(event => audio.addEventListener(event, update));
audio.addEventListener('error', () => { status.textContent = 'Unable to load the MP3. Extract the ZIP and keep the audio beside index.html.'; });
let animation = null;
const animate = () => { update(); animation = audio.paused || audio.ended ? null : requestAnimationFrame(animate); };
audio.addEventListener('play', () => {
  status.textContent = '';
  if (animation !== null) cancelAnimationFrame(animation);
  animate();
});
renderLines();
