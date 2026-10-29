// The Add Items picker (add-items.js) driven in jsdom against a fake Python: how many rows it reads, when it reads on, and the count it shows.
// Needs jsdom (``npm install jsdom``); without it these tests are skipped.
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { run } = require('./helpers');

let JSDOM = null;
try { JSDOM = require('jsdom').JSDOM; } catch (error) { /* skipped below */ }

const PAGE = 25;            // rows a page holds, as Python says (``limit``)
const NEAR_END = 100;       // pixels from the end of the list a scroll has to reach before the next lot is wanted
const TALL = 100000;        // a list far taller than the dialog: it is not "too short to scroll"
const ROW_PX = 40;          // what a row adds to the height of the list, as in a browser

/**
 * The picker loaded into a window, with a bridge that records what it is asked. ``matches`` is every row the search finds, in order, as
 * ``{id}`` (or ``{id, parent: true}`` for the design's own item, which the page counts but leaves out); ``members`` the ids the
 * Bill of Materials already holds.
 */
function openPicker({ matches, members = [], membersLate = false }) {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { runScripts: 'outside-only', pretendToBeVisual: true });
  const w = dom.window;
  w.MfgUi = {};
  const handlers = {};
  const sent = [];
  w.MfgUi.bridge = { send: (action, payload) => sent.push([action, payload || {}]), on: (action, fn) => { handlers[action] = fn; } };
  Object.defineProperty(w.HTMLElement.prototype, 'scrollHeight', { configurable: true, get() { return TALL + this.querySelectorAll('.pub-add-row').length * ROW_PX; } });
  Object.defineProperty(w.HTMLElement.prototype, 'clientHeight', { configurable: true, get() { return 500; } });
  ['../shared/js/dom.js', 'js/ui.js', 'js/add-items.js'].forEach((src) => run(w, src));

  const picker = { w, sent, readOffsets: [] };
  const answer = (action, token, result) => handlers[action]({ ok: true, result: { token, pending: false, ok: true, result } });

  /** Answer what is waiting (the answers may ask for more), the members last when they are late. */
  picker.serve = function serve() {
    for (;;) {
      const next = sent.findIndex((one) => !one.done && !(membersLate && one[0] === 'search_members' && !picker.membersNow));
      if (next < 0) return;
      const [action, payload] = sent[next];
      sent[next].done = true;
      if (action === 'search_fields') answer(action, payload.token, { fields: [] });
      else if (action === 'search_members') answer(action, payload.token, { ids: members, numbers: [] });
      else if (action === 'search_items') {
        picker.readOffsets.push(payload.offset);
        const rows = matches.slice(payload.offset, payload.offset + PAGE);
        const items = rows.filter((row) => !row.parent).map((row) => ({ id: row.id, link: '/items/' + row.id, number: 'N-' + row.id, name: 'Item ' + row.id, version: 'A', linkable: null }));
        answer(action, payload.token, { total: matches.length, raw: rows.length, items, limit: PAGE });
      }
    }
  };
  picker.lateMembers = function lateMembers() { picker.membersNow = true; picker.serve(); };
  picker.rows = () => Array.from(w.document.querySelectorAll('.pub-add-row'));
  picker.visible = () => picker.rows().filter((row) => !row.hidden).length;
  /** "25 of 100": the two numbers of the count (it may also note how many of the rows are hidden). */
  picker.count = () => Array.from(w.document.querySelectorAll('.pub-add-total strong')).map((one) => one.textContent).join(' of ');
  picker.status = () => { const status = w.document.querySelector('.pub-add-status'); return status.hidden ? '' : status.textContent; };
  picker.scrollToEnd = async function scrollToEnd() {
    const list = w.document.querySelector('.pub-add-list');
    list.scrollTop = list.scrollHeight - 500 - NEAR_END / 2;
    list.dispatchEvent(new w.Event('scroll'));
    await new Promise((resolve) => setTimeout(resolve, 60));   // the scroll is handled on the next frame
    picker.serve();
  };
  w.MfgUi.pubAddItems.open({ itemId: '9', staged: [], onAdd() {} });
  return picker;
}

const many = (count, from = 1) => Array.from({ length: count }, (_, i) => ({ id: String(from + i) }));
const skip = JSDOM ? false : 'jsdom is not installed (npm install jsdom)';

test('the count is that of the items shown once every row is read: the item of the design itself is not in it', { skip }, () => {
  // 26 rows: the design's own item is among the first 25, so that page shows 24 and the next page is read to make up the lot.
  const matches = many(3).concat([{ id: 'P', parent: true }], many(21, 4), [{ id: '25' }]);
  const picker = openPicker({ matches });
  picker.serve();
  assert.deepStrictEqual(picker.readOffsets, [0, 25]);
  assert.strictEqual(picker.rows().length, 25);
  assert.strictEqual(picker.count(), '25 of 25');   // the search counted 26
});

test('a lot is the rows of a page, and the next one is read only when the list is scrolled to its end', { skip }, async () => {
  const picker = openPicker({ matches: many(100) });
  picker.serve();
  assert.deepStrictEqual(picker.readOffsets, [0]);
  assert.strictEqual(picker.visible(), PAGE);
  assert.strictEqual(picker.count(), '25 of 100');
  await picker.scrollToEnd();
  assert.deepStrictEqual(picker.readOffsets, [0, 25]);
  assert.strictEqual(picker.visible(), 50);
});

test('when part of a page is hidden the next pages are read until a lot is visible', { skip }, () => {
  const picker = openPicker({ matches: many(100), members: many(15).map((one) => one.id) });   // the first 15 are already in the Bill of Materials
  picker.serve();
  assert.deepStrictEqual(picker.readOffsets, [0, 25]);   // 10 visible after the first page: the next is read at once
  assert.strictEqual(picker.visible(), 35);              // and no further: a lot is made up
  assert.strictEqual(picker.rows().length, 50);
  assert.strictEqual(picker.count(), '50 of 100');
});

test('members that arrive after the first page hide rows, and the lot is made up again', { skip }, () => {
  const picker = openPicker({ matches: many(100), members: many(15).map((one) => one.id), membersLate: true });
  picker.serve();
  assert.deepStrictEqual(picker.readOffsets, [0]);
  assert.strictEqual(picker.visible(), PAGE);
  picker.lateMembers();
  assert.deepStrictEqual(picker.readOffsets, [0, 25]);
  assert.strictEqual(picker.visible(), 35);
});

test('it reads on through pages that are all hidden, stops when the matches run out, and says so', { skip }, () => {
  const matches = many(60);
  const picker = openPicker({ matches, members: matches.map((one) => one.id) });
  picker.serve();
  assert.deepStrictEqual(picker.readOffsets, [0, 25, 50]);
  assert.strictEqual(picker.visible(), 0);
  assert.match(picker.status(), /already in the Bill of Materials/);
  assert.strictEqual(picker.count(), '60 of 60');
});

test('a search with no match asks once and says so', { skip }, () => {
  const picker = openPicker({ matches: [] });
  picker.serve();
  assert.deepStrictEqual(picker.readOffsets, [0]);
  assert.strictEqual(picker.status(), 'No items match the search.');
});

test('showing the hidden items reads nothing more, and hiding them again does not either while a lot is visible', { skip }, () => {
  const picker = openPicker({ matches: many(100), members: many(15).map((one) => one.id) });
  picker.serve();
  const before = picker.readOffsets.slice();
  const label = Array.from(picker.w.document.querySelectorAll('label.pub-add-switch')).find((one) => /Show hidden items/.test(one.textContent));
  const toggle = label.querySelector('input');
  toggle.checked = true;
  toggle.dispatchEvent(new picker.w.Event('change'));
  picker.serve();
  assert.strictEqual(picker.visible(), 50);
  toggle.checked = false;
  toggle.dispatchEvent(new picker.w.Event('change'));
  picker.serve();
  assert.strictEqual(picker.visible(), 35);
  assert.deepStrictEqual(picker.readOffsets, before);
});
