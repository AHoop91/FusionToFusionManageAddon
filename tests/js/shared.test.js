// The scripts every panel shares (bridge.js, upload-progress.js), run in jsdom.
// Needs jsdom (``npm install jsdom``); without it these tests are skipped.
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { run } = require('./helpers');

let JSDOM = null;
try { JSDOM = require('jsdom').JSDOM; } catch (error) { /* skipped below */ }
const skip = JSDOM ? false : 'jsdom is not installed (npm install jsdom)';

function page(scripts) {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { runScripts: 'outside-only' });
  dom.window.MfgUi = {};
  dom.window.adsk = { fusionSendData: () => {} };
  scripts.forEach((src) => run(dom.window, '../shared/js/' + src));
  return dom.window;
}

test('a listener that throws is logged and the next message is still delivered', { skip }, () => {
  const w = page(['dom.js', 'bridge.js']);
  const logged = [];
  w.console.error = (...args) => logged.push(args);
  const got = [];
  w.MfgUi.bridge.on('broken', () => { throw new Error('boom'); });
  w.MfgUi.bridge.on('fine', (message) => got.push(message));
  assert.strictEqual(w.fusionJavaScriptHandler.handle('broken', '{"ok":true}'), 'OK');
  assert.strictEqual(w.fusionJavaScriptHandler.handle('fine', '{"ok":true}'), 'OK');
  assert.strictEqual(JSON.stringify(got), '[{"ok":true}]');   // objects of the window have its own prototypes
  assert.strictEqual(logged.length, 1);
  assert.match(String(logged[0][0]), /"broken"/);
});

test('a message that is not JSON is logged, not thrown into Fusion', { skip }, () => {
  const w = page(['dom.js', 'bridge.js']);
  w.console.error = () => {};
  w.MfgUi.bridge.on('x', () => assert.fail('no listener call for unreadable data'));
  assert.strictEqual(w.fusionJavaScriptHandler.handle('x', 'not json'), 'OK');
});

test('a message nobody listens for is ignored', { skip }, () => {
  const w = page(['dom.js', 'bridge.js']);
  assert.strictEqual(w.fusionJavaScriptHandler.handle('nobody', '{}'), 'OK');
});

test('the upload bar has no value while the share done is unknown', { skip }, () => {
  const w = page(['dom.js', 'upload-progress.js']);
  const card = w.document.createElement('div');
  const view = w.MfgUi.uploadProgress.mount(card);
  const bar = card.querySelector('.progress-bar');
  view.show({ stage: 'Uploading', step: 0, steps: ['a', 'b'], percent: 40 });
  assert.strictEqual(bar.getAttribute('aria-valuenow'), '40');
  view.show({ stage: 'Uploading', step: 0, steps: ['a', 'b'], percent: null });
  assert.strictEqual(bar.hasAttribute('aria-valuenow'), false);
  assert.ok(bar.classList.contains('indeterminate'));
});
