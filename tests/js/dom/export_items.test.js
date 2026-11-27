// The Export window's items (export-items.js): grey bars while they are looked for, the table of choices when several are found, in the browser.
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { englishI18n, run } = require('../helpers');

const { PageWindow } = require('../browser/window');

const ITEMS = [{ id: '1', number: 'PN-1-A', descriptor: 'PN-1-A - Bolt' }, { id: '2', number: 'PN-1-B', descriptor: 'PN-1-B - Nut' }];

function setup() {
  const dom = new PageWindow('<!doctype html><html><body><div id="export-items"></div></body></html>');
  const w = dom.window;
  w.MfgUi = {};
  const ns = w.MfgUi;
  run(w, '../shared/js/dom.js');
  ns.i18n = englishI18n();
  ['../shared/js/choice-table.js', '../export/js/export-items.js'].forEach((src) => run(w, src));
  const changes = [];
  ns.exportItems.init({ changed: () => changes.push(ns.exportItems.selected()) });
  return { w, ns, changes, box: w.document.getElementById('export-items') };
}

test('until Python has listed the items the state is finding, with the table in grey where it will be', () => {
  const s = setup();
  s.ns.exportItems.show(null);
  assert.strictEqual(s.ns.exportItems.state(), 'finding');
  assert.ok(s.box.querySelector('.export-wait-bar.is-search'), 'the search field in grey');
  assert.strictEqual(s.box.querySelectorAll('.export-wait-row').length, 4, 'the rows in grey');
  assert.strictEqual(s.ns.exportItems.selected(), '');
});

test('the only item is picked at once, with several none is until the user picks one in the table', () => {
  const s = setup();
  s.ns.exportItems.show({ target: 'PN-1', items: [ITEMS[0]] });
  assert.strictEqual(s.ns.exportItems.state(), 'one');
  assert.strictEqual(s.ns.exportItems.selected(), '1');
  s.ns.exportItems.show({ target: 'PN-1', items: ITEMS });
  assert.strictEqual(s.ns.exportItems.state(), 'several');
  assert.strictEqual(s.ns.exportItems.selected(), '', 'several: nothing is picked for the user');
  assert.strictEqual(s.box.querySelectorAll('.ct-row').length, 2);
  s.box.querySelectorAll('.ct-row')[1].click();
  assert.strictEqual(s.ns.exportItems.selected(), '2');
  assert.strictEqual(s.ns.exportItems.current().descriptor, 'PN-1-B - Nut');
  assert.strictEqual(s.changes[s.changes.length - 1], '2', 'the window is told the pick changed');
});

test('reset forgets the pick, so the window shows the table again', () => {
  const s = setup();
  s.ns.exportItems.show({ target: 'PN-1', items: ITEMS });
  s.box.querySelectorAll('.ct-row')[0].click();
  s.ns.exportItems.reset();
  assert.strictEqual(s.ns.exportItems.selected(), '');
  assert.strictEqual(s.ns.exportItems.current(), null);
  assert.strictEqual(s.changes[s.changes.length - 1], '');
});

test('no items and a failed listing each give their words, and pick nothing', () => {
  const s = setup();
  s.ns.exportItems.show({ target: 'PN-1', items: [] });
  assert.strictEqual(s.ns.exportItems.state(), 'none');
  assert.match(s.ns.exportItems.note(), /No item made from this component yet/);
  s.ns.exportItems.show({ target: 'PN-1', items: [], error: 'The design has no record.' });
  assert.strictEqual(s.ns.exportItems.state(), 'failed');
  assert.strictEqual(s.ns.exportItems.note(), 'The design has no record.');
  assert.strictEqual(s.ns.exportItems.selected(), '');
});

test('the page of the component record comes with the answer, and is empty while it is awaited or when there is none', () => {
  const s = setup();
  s.ns.exportItems.show(null);
  assert.strictEqual(s.ns.exportItems.recordUrl(), '');
  s.ns.exportItems.show({ target: 'PN-1', items: ITEMS, component_url: 'https://acme.example/component' });
  assert.strictEqual(s.ns.exportItems.recordUrl(), 'https://acme.example/component');
  s.ns.exportItems.show({ target: 'PN-1', items: ITEMS });
  assert.strictEqual(s.ns.exportItems.recordUrl(), '');
});
