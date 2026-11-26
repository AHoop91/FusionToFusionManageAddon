// The scripts every panel shares (bridge.js, upload-progress.js), run in the browser.
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { run, englishI18n } = require('../helpers');

const { PageWindow } = require('../browser/window');

function page(scripts) {
  const dom = new PageWindow('<!doctype html><html><body></body></html>');
  dom.window.MfgUi = { i18n: englishI18n() };
  dom.window.adsk = { fusionSendData: () => {} };
  scripts.forEach((src) => run(dom.window, '../shared/js/' + src));
  return dom.window;
}

test('a listener that throws is logged and the next message is still delivered', () => {
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

test('a message that is not JSON is logged, not thrown into Fusion', () => {
  const w = page(['dom.js', 'bridge.js']);
  w.console.error = () => {};
  w.MfgUi.bridge.on('x', () => assert.fail('no listener call for unreadable data'));
  assert.strictEqual(w.fusionJavaScriptHandler.handle('x', 'not json'), 'OK');
});

test('a message nobody listens for is ignored', () => {
  const w = page(['dom.js', 'bridge.js']);
  assert.strictEqual(w.fusionJavaScriptHandler.handle('nobody', '{}'), 'OK');
});

test('the upload bar has no value while the share done is unknown', () => {
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

test('the restart in the account card asks the add-in to start again', () => {
  const dom = new PageWindow('<!doctype html><html><body><div id="app-header"></div></body></html>');
  const w = dom.window;
  w.MfgUi = {};
  w.sent = [];
  w.adsk = { fusionSendData: (action, data) => w.sent.push([action, JSON.parse(data)]) };
  ['dom.js', 'bridge.js', 'i18n.js', 'shell.js', 'account.js'].forEach((src) => run(w, '../shared/js/' + src));
  w.MfgUi.shell.mountHeader();
  w.MfgUi.account.init();
  w.sent.length = 0;
  w.document.getElementById('card-restart').click();
  assert.deepStrictEqual(w.sent, [['restart_addin', {}]]);
});

test('the Help button in the top bar asks Python to open the documentation, signed in or not', () => {
  const w = new PageWindow('<!doctype html><html><body><div id="app-header"></div></body></html>').window;
  w.MfgUi = {};
  w.sent = [];
  w.adsk = { fusionSendData: (action, data) => w.sent.push([action, JSON.parse(data)]) };
  ['dom.js', 'bridge.js', 'i18n.js', 'shell.js'].forEach((src) => run(w, '../shared/js/' + src));
  w.MfgUi.shell.mountHeader();
  w.sent.length = 0;
  w.document.getElementById('help-btn').click();
  assert.deepStrictEqual(w.sent, [['open_help', {}]]);
});

test('a picture the view did not carry is a skeleton until it is loaded, and is dropped when the page has moved on', () => {
  const w = page(['dom.js', 'section.js', '../../item/js/safe-html.js', '../../item/js/tree.js', '../../item/js/item-sections.js']);
  const field = { id: 'IMAGE', title: 'Image', kind: 'image', link: '/api/v2/workspaces/1/items/2/field-values/IMAGE/image/3', value: '' };
  const draw = (load, enlarged) => w.MfgUi.itemSections.section({ title: 'Basic', fields: [field], matrices: [] }, enlarged || (() => {}), load);
  const asked = [];
  const card = draw((link, done) => asked.push({ link, done }));
  w.document.body.appendChild(card);
  assert.strictEqual(asked.length, 1);
  assert.strictEqual(asked[0].link, field.link);
  assert.ok(card.querySelector('.item-image-skeleton'), 'a skeleton stands in for the picture');
  asked[0].done('data:image/png;base64,AAAA');
  assert.ok(!card.querySelector('.item-image-skeleton'));
  assert.strictEqual(card.querySelector('img.item-image').src, 'data:image/png;base64,AAAA');
  const gone = draw((link, done) => asked.push({ link, done }));   // never put on the page: the page moved on
  asked[1].done('data:image/png;base64,BBBB');
  assert.ok(!gone.querySelector('img'), 'nothing is drawn into a card that has left the page');
  const none = draw((link, done) => asked.push({ link, done }));
  w.document.body.appendChild(none);
  asked[2].done('');   // no picture could be read
  assert.ok(!none.querySelector('.item-image-skeleton') && !none.querySelector('img'));
  const plain = draw(undefined);   // a page that asks for nothing (the Item panel) shows no skeleton
  assert.ok(!plain.querySelector('.item-image-skeleton'));
});

test('a section laid out folded starts folded and asks for its pictures only when it is first opened', () => {
  const w = page(['dom.js', 'section.js', '../../item/js/safe-html.js', '../../item/js/tree.js', '../../item/js/item-sections.js']);
  const image = (id) => ({ id, title: id, kind: 'image', link: '/api/v2/workspaces/1/items/2/field-values/' + id + '/image/1', value: '' });
  const asked = [];
  const load = (link, done) => asked.push({ link, done });
  const draw = (collapsed) => w.MfgUi.itemSections.section({ title: 'Images', collapsed, fields: [image('A')], matrices: [{ columns: ['One'], labels: ['x'], rows: [[image('B')]] }] }, () => {}, load);
  const open = draw(false);
  assert.strictEqual(asked.length, 2, 'an open section asks for its pictures at once');
  const folded = draw(true);
  w.document.body.appendChild(folded);
  assert.strictEqual(asked.length, 2, 'a folded one asks for nothing');
  assert.ok(folded.classList.contains('folded'));
  assert.ok(folded.querySelector('.item-image-skeleton'), 'the skeleton is ready for when it is opened');
  folded.querySelector('.section-title').click();
  assert.strictEqual(asked.length, 4, 'opening it asks for all its pictures together');
  folded.querySelector('.section-title').click();   // fold it
  folded.querySelector('.section-title').click();   // and open it again
  assert.strictEqual(asked.length, 4, 'only the first opening asks');
  assert.ok(open && !open.classList.contains('folded'));
});
