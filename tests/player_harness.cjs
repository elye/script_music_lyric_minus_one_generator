// Small, isolated DOM harness. Real browser checks are separate.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function fixture() {
  return {
    schema_version: 1, audio_file: 'demo.mp3', duration: 10,
    language: 'en', language_probability: 0.99, engine: 'test-fixture', model: 'synthetic',
    lines: [
      { start: 1, end: 3, text: 'Hello world', words: [
        { start: 1, end: 2, text: 'Hello', probability: 0.9 },
        { start: 2, end: 3, text: ' world', probability: 0.8 },
      ] },
      { start: 5, end: 6, text: 'Line only', words: [] },
    ],
  };
}

function loadPlayer(transcript = fixture()) {
  const downloads = [];
  const blobs = new Map();
  const timers = [];
  class Element {
    constructor(tag = '') {
      this.tagName = tag;
      this.children = [];
      this.listeners = {};
      this.attributes = {};
      this.textContent = '';
      this.checked = true;
      this.value = '';
      this.scrollCount = 0;
      this.open = false;
      this.disabled = false;
      this.classes = new Set();
      this.classList = {
        add: name => this.classes.add(name),
        remove: name => this.classes.delete(name),
        toggle: (name, enabled) => enabled ? this.classes.add(name) : this.classes.delete(name),
      };
    }
    append(...children) { for (const child of children) { child.parent = this; this.children.push(child); } }
    replaceChildren(...children) { this.children = []; this.append(...children); }
    setAttribute(name, value) { this.attributes[name] = value; }
    removeAttribute(name) { delete this.attributes[name]; }
    addEventListener(event, callback) { (this.listeners[event] ??= []).push(callback); }
    dispatch(event) {
      const payload = { target: this, prevented: false, preventDefault() { this.prevented = true; } };
      for (const callback of this.listeners[event] ?? []) callback(payload);
      return payload;
    }
    click() {
      if (this.disabled) return;
      if (this.tagName === 'a') downloads.push({ name: this.download, blob: blobs.get(this.href) });
      this.dispatch('click');
    }
    remove() { if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this); }
    focus() { this.focused = true; }
    showModal() { this.open = true; }
    close() { this.open = false; this.dispatch('close'); }
    scrollIntoView() { this.scrollCount += 1; }
  }
  const template = fs.readFileSync(path.join(__dirname, '../lyric_transcriber/player.html'), 'utf8');
  const ids = [...template.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
  const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
  elements.transcript.textContent = JSON.stringify(transcript);
  elements.offset.value = '0';
  const audio = elements.audio;
  Object.assign(audio, { currentTime: 0, duration: NaN, paused: true, ended: false, playCalls: 0, src: 'demo.mp3' });
  audio.play = () => { audio.playCalls += 1; return Promise.resolve(); };
  audio.load = () => { audio.currentTime = 0; audio.duration = 10; audio.dispatch('loadedmetadata'); };
  const window = new Element();
  window.matchMedia = () => ({ matches: true });
  const context = vm.createContext({
    document: { getElementById: id => elements[id], createElement: tag => new Element(tag), body: new Element('body') },
    window,
    Blob,
    URL: { createObjectURL: blob => { const url = `blob:${blobs.size}`; blobs.set(url, blob); return url; }, revokeObjectURL: url => blobs.delete(url) },
    setTimeout: callback => timers.push(callback),
    requestAnimationFrame: () => 1,
    cancelAnimationFrame: () => {},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../lyric_transcriber/player.js'), 'utf8'), context, { timeout: 1000 });
  return {
    elements, audio, context, downloads, timers, window,
    evaluate: script => vm.runInContext(script, context, { timeout: 1000 }),
    data: () => JSON.parse(vm.runInContext('JSON.stringify(transcript)', context)),
    seek: time => { audio.currentTime = time; audio.dispatch('timeupdate'); },
  };
}

module.exports = { fixture, loadPlayer };
