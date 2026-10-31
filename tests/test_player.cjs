// Dependency-free logic check; this is not a full browser rendering test.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
  constructor() {
    this.children = [];
    this.listeners = {};
    this.attributes = {};
    this.textContent = '';
    this.checked = true;
    this.value = '1';
    this.scrollCount = 0;
    this.classes = new Set();
    this.classList = {
      add: name => this.classes.add(name),
      remove: name => this.classes.delete(name),
      toggle: (name, enabled) => enabled ? this.classes.add(name) : this.classes.delete(name),
    };
  }
  append(...children) { this.children.push(...children); }
  setAttribute(name, value) { this.attributes[name] = value; }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(event, callback) { (this.listeners[event] ??= []).push(callback); }
  dispatch(event) { for (const callback of this.listeners[event] ?? []) callback({ target: this }); }
  scrollIntoView() { this.scrollCount += 1; }
}

const transcript = {
  audio_file: 'demo.mp3', duration: 10,
  lines: [
    { start: 1, end: 3, text: 'Hello world', words: [
      { start: 1, end: 2, text: 'Hello' }, { start: 2, end: 3, text: ' world' },
    ] },
    { start: 5, end: 6, text: 'Line only', words: [] },
  ],
};
const elements = Object.fromEntries(['transcript', 'audio', 'lyrics', 'status', 'clock', 'follow', 'title', 'speed'].map(id => [id, new Element()]));
elements.transcript.textContent = JSON.stringify(transcript);
const audio = elements.audio;
Object.assign(audio, { currentTime: 0, duration: NaN, paused: true, ended: false, playCalls: 0 });
audio.play = () => { audio.playCalls += 1; return Promise.resolve(); };
const context = vm.createContext({
  document: { getElementById: id => elements[id], createElement: () => new Element() },
  window: { matchMedia: () => ({ matches: true }) },
  requestAnimationFrame: () => 1,
  cancelAnimationFrame: () => {},
});
const template = fs.readFileSync(path.join(__dirname, '../lyric_transcriber/player.html'), 'utf8');
const script = template.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
vm.runInContext(script, context, { timeout: 1000 });
assert.equal(elements.title.textContent, 'demo.mp3');
assert.equal(elements.clock.textContent, '0:00 / 0:10');
assert.equal(elements.lyrics.children.length, 2);
const [first, second] = elements.lyrics.children;
const words = first.children[1].children;

function seek(time) { audio.currentTime = time; audio.dispatch('timeupdate'); }
seek(1.5);
assert(first.classes.has('active'));
assert(words[0].classes.has('active'));
assert(!words[1].classes.has('active'));
assert.equal(first.attributes['aria-current'], 'true');
seek(2.5);
assert(!words[0].classes.has('active'));
assert(words[1].classes.has('active'));
seek(3);
assert(!first.classes.has('active'));
assert(!words[1].classes.has('active'));
assert.equal(first.attributes['aria-current'], undefined);
seek(5.5);
assert(second.classes.has('active'));
assert.equal(second.children[1].textContent, 'Line only');
seek(0);
assert(!second.classes.has('active'));

elements.follow.checked = false;
const scrolls = first.scrollCount;
seek(1.5);
assert.equal(first.scrollCount, scrolls);
first.dispatch('click');
assert.equal(audio.currentTime, 1);
assert.equal(audio.playCalls, 1);
elements.speed.value = '1.25';
elements.speed.dispatch('change');
assert.equal(audio.playbackRate, 1.25);
audio.dispatch('error');
assert(elements.status.textContent.includes('Extract the ZIP'));
console.log('Player logic checks passed: line/word highlighting, gap clearing, seeking, follow toggle, playback speed, and audio errors.');
