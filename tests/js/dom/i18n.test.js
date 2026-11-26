// i18n.js: the text a panel shows in the language the user chose.
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { run } = require('../helpers');

const { PageWindow } = require('../browser/window');

function page(body) {
  const dom = new PageWindow('<!doctype html><html><body>' + (body || '') + '</body></html>');
  const w = dom.window;
  w.MfgUi = {};
  w.sent = [];
  w.adsk = { fusionSendData: (action, data) => w.sent.push([action, data]) };
  ['dom.js', 'bridge.js', 'i18n.js'].forEach((src) => run(w, '../shared/js/' + src));
  return w;
}

test('t fills {name} and answers a key nothing has as itself', () => {
  const w = page();
  w.MfgUi.i18n.use({ code: 'de', strings: { 'a.b': 'Hallo {name}' } });
  assert.strictEqual(w.MfgUi.i18n.t('a.b', { name: 'Ann' }), 'Hallo Ann');
  assert.strictEqual(w.MfgUi.i18n.t('a.b'), 'Hallo {name}');
  assert.strictEqual(w.MfgUi.i18n.t('no.such'), 'no.such');
  assert.strictEqual(w.document.documentElement.lang, 'de');
});

test('use translates the text, the markup of a text and the attributes of the page', () => {
  const w = page('<p id="a" data-i18n="x.a">English</p><p id="b" data-i18n-html="x.b">English</p>' +
                 '<button id="c" title="English" data-i18n-attr="title:x.c;aria-label:x.c">English</button>');
  w.MfgUi.i18n.use({ code: 'de', strings: { 'x.a': 'Eins', 'x.b': 'Zwei <b>fett</b> <script>x</script>', 'x.c': 'Drei' } });
  const $ = (id) => w.document.getElementById(id);
  assert.strictEqual($('a').textContent, 'Eins');
  assert.strictEqual($('b').innerHTML, 'Zwei <b>fett</b> &lt;script&gt;x&lt;/script&gt;');   // only the few tags are read as markup
  assert.strictEqual($('c').getAttribute('title'), 'Drei');
  assert.strictEqual($('c').getAttribute('aria-label'), 'Drei');
});

test('init asks for the language and starts the page once, when it arrives', () => {
  const w = page('<p data-i18n="x.a">English</p>');
  let started = 0;
  w.MfgUi.i18n.init(() => { started += 1; });
  assert.deepStrictEqual(w.sent[0][0], 'get_language');
  w.fusionJavaScriptHandler.handle('get_language', JSON.stringify({ ok: true, result: { code: 'de', strings: { 'x.a': 'Eins' } } }));
  w.fusionJavaScriptHandler.handle('get_language', JSON.stringify({ ok: true, result: { code: 'de', strings: { 'x.a': 'Eins' } } }));
  assert.strictEqual(started, 1);
  assert.strictEqual(w.document.querySelector('p').textContent, 'Eins');
  assert.strictEqual(w.MfgUi.i18n.gate(() => {}), true);
});

test('gate runs the page start again once the language has arrived', () => {
  const w = page();
  let starts = 0;
  const start = () => { starts += 1; if (!w.MfgUi.i18n.gate(start)) return; };
  start();
  assert.strictEqual(starts, 1);
  w.fusionJavaScriptHandler.handle('get_language', JSON.stringify({ ok: true, result: { code: 'en', strings: {} } }));
  assert.strictEqual(starts, 2);
});

test('a page that loaded again in a new language opens the tab it was on, once', () => {
  const html = '<nav class="tabs" data-group="settings"><button class="tab active" data-tab="a"></button><button class="tab" data-tab="b"></button></nav>' +
    '<div id="sub-a" class="tab-panel active" data-group="settings"></div><div id="sub-b" class="tab-panel" data-group="settings"></div>';
  const dom = new PageWindow('<!doctype html><html><body>' + html + '</body></html>');
  const w = dom.window;
  w.MfgUi = {};
  w.adsk = { fusionSendData: () => {} };
  ['dom.js', 'bridge.js', 'i18n.js', 'tabs.js'].forEach((src) => run(w, '../shared/js/' + src));
  w.sessionStorage.setItem('mfg.tab', 'b');
  w.MfgUi.tabs.init();
  assert.ok(w.document.querySelector('.tab[data-tab="b"]').classList.contains('active'));
  assert.ok(w.document.getElementById('sub-b').classList.contains('active'));
  assert.strictEqual(w.MfgUi.i18n.takeOpenTab(), '', 'it is taken once');
});
