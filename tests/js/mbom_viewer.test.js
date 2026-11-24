// The structure viewer (mbom-viewer.js) in jsdom with a stand-in panel: its two panes, selection, edits, drag and drop, and the errors an edit gives.
// Needs jsdom (``npm install jsdom``); without it these tests are skipped.
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { englishI18n, run } = require('./helpers');

let JSDOM = null;
try { JSDOM = require('jsdom').JSDOM; } catch (error) { /* skipped below */ }

const row = (level, number, quantity, extra) => Object.assign({ level: level, id: 'c' + number, item_number: number, name: number + ' name', quantity: quantity || '1' }, extra || {});
// TOP: A (x2) [A1, A2], B [B1], C
const ROWS = [row(0, 'A', '2'), row(1, 'A1'), row(1, 'A2'), row(0, 'B'), row(1, 'B1'), row(0, 'C')];

function open(options) {
  const opts = Object.assign({ rows: ROWS, targetId: '', phantom: false, partial: false, bought: true }, options || {});
  const dom = new JSDOM('<section id="pub-bom"></section><section id="pub-structure" hidden></section>', { runScripts: 'outside-only', pretendToBeVisual: true });
  const w = dom.window;
  w.MfgUi = {};
  const ns = w.MfgUi;
  ['../shared/js/dom.js'].forEach((src) => run(w, src));
  ns.i18n = englishI18n();
  const toasts = [];   // what a refused edit says: a toast, never a line above the panes
  ns.toast = { show: (text) => toasts.push(text) };
  const added = [];
  ns.pubAddItems = { open: (o) => added.push(o) };
  ['js/ui.js', 'js/mbom-structure.js', 'js/mbom-plan.js', 'js/mbom-viewer.js'].forEach((src) => run(w, src));
  const calls = { loadTree: 0, askMbom: 0, planned: 0 };
  const state = { partial: opts.partial };
  ns.mbomViewer.init({
    design: () => ({ item_number: 'TOP', name: 'Top', component_id: 'R', composition: 'WORKING' }), rows: () => opts.rows, partial: () => state.partial,
    loadTree: () => { calls.loadTree++; }, askMbom: () => { calls.askMbom++; }, targetId: () => opts.targetId, target: () => (opts.targetId ? 'TOP-M' : ''),
    phantom: () => opts.phantom,
    boughtReady: () => opts.bought, boughtSuffix: () => '', planned: () => { calls.planned++; },
  });
  const $ = (id) => w.document.getElementById(id);
  const api = {
    w: w, ns: ns, calls: calls, state: state, added: added, toasts: toasts,
    show: () => ns.mbomViewer.show(true),
    ebom: () => $('pub-structure').querySelectorAll('.sv-pane')[0],
    mbom: () => $('pub-structure').querySelectorAll('.sv-pane')[1],
    lines: (pane) => [...pane.querySelectorAll('.sv-row')].map((r) => r.querySelector('.sv-pn').textContent),
    rowOf: (pane, number) => [...pane.querySelectorAll('.sv-row')].find((r) => r.querySelector('.sv-pn').textContent === number),
    click: (el, init) => el.dispatchEvent(new w.MouseEvent('click', Object.assign({ bubbles: true }, init || {}))),
    button: (label) => [...$('pub-structure').querySelectorAll('.sv-bar button')].find((b) => b.getAttribute('aria-label') === label),
    act: (pane, number, name) => [...api.rowOf(pane, number).querySelectorAll('.sv-act')].find((b) => b.dataset.act === name),
    openAll: () => api.button('Expand All').click(),
    drag: (fromEl, toEl, init) => {   // the pointer goes down on a line, moves over another and is released
      const doc = w.document;
      const mouse = (type, el, x, y) => {
        const e = new w.MouseEvent(type, Object.assign({ bubbles: true, cancelable: true, button: 0, clientX: x, clientY: y }, init || {}));
        el.dispatchEvent(e);
        return e;
      };
      doc.elementFromPoint = () => toEl;
      mouse('mousedown', fromEl, 5, 5);
      mouse('mousemove', doc, 40, 0);
      const ghost = doc.querySelector('.sv-ghost');
      const mode = ghost ? ghost.dataset.mode : '';
      mouse('mouseup', doc, 40, 0);
      if (ghost) mouse('click', doc.querySelector('.sv-tree'), 40, 0);   // the browser sends the click that ends a drag; it selects nothing
      return { mode: mode };
    },
  };
  return api;
}

const skip = { skip: JSDOM ? false : 'jsdom is not installed' };

function built(options) {
  const v = open(options);
  v.show();
  v.ns.mbomViewer.structureRead();
  return v;
}

test('the viewer waits for the first level, reads the whole tree, then draws both panes', skip, () => {
  const v = open({ partial: true });
  v.show();
  assert.strictEqual(v.w.document.getElementById('pub-structure').hidden, false);
  assert.strictEqual(v.w.document.getElementById('pub-bom').hidden, true);
  assert.match(v.w.document.getElementById('pub-structure').textContent, /Reading the Fusion Component structure/);
  v.ns.mbomViewer.structureRead();
  assert.strictEqual(v.calls.loadTree, 1);
  assert.strictEqual(v.ebom().querySelector('.sv-row'), null, 'nothing is drawn before the tree is read');
  v.state.partial = false;
  v.ns.mbomViewer.treeDone({ ok: true });
  assert.deepStrictEqual(v.lines(v.ebom()), ['TOP', 'A', 'B', 'C']);
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'A', 'B', 'C']);
  assert.strictEqual(v.calls.askMbom, 0, 'a design with no MBOM item starts as a copy of the EBOM');
});

test('a failed read of the tree is shown with a way to retry', skip, () => {
  const v = open({ partial: true });
  v.show();
  v.ns.mbomViewer.structureRead();
  v.ns.mbomViewer.treeDone({ ok: false, message: 'Fusion Manage said no' });
  assert.match(v.w.document.getElementById('pub-structure').textContent, /Fusion Manage said no/);
  v.state.partial = false;
  v.click(v.w.document.querySelector('.pub-retry'));
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'A', 'B', 'C']);
});

test('lines open and close one at a time and all at once, and only open lines are drawn', skip, () => {
  const v = built();
  v.click(v.rowOf(v.ebom(), 'A').querySelector('.sv-toggle'));
  assert.deepStrictEqual(v.lines(v.ebom()), ['TOP', 'A', 'A1', 'A2', 'B', 'C']);
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'A', 'B', 'C'], 'the other pane is its own');
  v.openAll();
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'A', 'A1', 'A2', 'B', 'B1', 'C']);
  v.button('Collapse All').click();
  assert.deepStrictEqual(v.lines(v.ebom()), ['TOP', 'A', 'B', 'C']);
});

test('click, ctrl-click and shift-click select lines of the MBOM', skip, () => {
  const v = built();
  v.openAll();
  const selected = () => [...v.mbom().querySelectorAll('.sv-row.selected .sv-pn')].map((n) => n.textContent);
  v.click(v.rowOf(v.mbom(), 'A1'));
  assert.deepStrictEqual(selected(), ['A1']);
  v.click(v.rowOf(v.mbom(), 'B'), { ctrlKey: true });
  assert.deepStrictEqual(selected(), ['A1', 'B']);
  v.click(v.rowOf(v.mbom(), 'B'), { ctrlKey: true });
  assert.deepStrictEqual(selected(), ['A1']);
  v.click(v.rowOf(v.mbom(), 'A1'));
  v.click(v.rowOf(v.mbom(), 'B'), { shiftKey: true });
  assert.deepStrictEqual(selected(), ['A1', 'A2', 'B']);
});

test('a quantity is changed in the line, and a refused one is said in the message line with the tree as it was', skip, () => {
  const v = built();
  const quantity = () => v.rowOf(v.mbom(), 'C').querySelector('.sv-qty').textContent;
  const edit = (text) => {
    v.click(v.rowOf(v.mbom(), 'C').querySelector('button.sv-qty'));
    const input = v.mbom().querySelector('.sv-qty-input');
    input.value = text;
    input.dispatchEvent(new v.w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  };
  edit('4');
  assert.strictEqual(quantity(), '4.0');
  assert.deepStrictEqual(v.toasts, []);
  assert.ok(v.rowOf(v.mbom(), 'C').querySelector('.sv-note-btn').title.indexOf('Quantity changed') < 0, 'a copy of the EBOM has nothing read to change from: it is new');
  edit('0');
  assert.strictEqual(quantity(), '4.0');
  assert.strictEqual(v.toasts.length, 1);
  assert.match(v.toasts[0], /above 0/);
  assert.strictEqual(v.w.document.querySelector('.sv-message'), null, 'there is no line for it above the panes');
  edit('5');
  assert.strictEqual(v.toasts.length, 1, 'an edit that works says nothing');
});

test('remove, undo and redo, and the buttons say why they cannot be used', skip, () => {
  const v = built();
  assert.strictEqual(v.button('Undo').disabled, true);
  assert.match(v.button('Undo').title, /nothing to undo/);
  assert.match(v.act(v.mbom(), 'C', 'remove').title, /Remove from the bill of materials/);
  v.act(v.mbom(), 'C', 'remove').click();
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'A', 'B']);
  assert.ok(v.ebom().querySelector('.sv-row-missing'), 'the EBOM line that has no MBOM line is marked');
  v.button('Undo').click();
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'A', 'B', 'C']);
  v.button('Redo').click();
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'A', 'B']);
  assert.strictEqual(v.button('Create assembly'), undefined, 'the toolbar has no Create assembly: Create item makes the new item');
});

test('dragging in the MBOM moves a line, and a refused drop is said', skip, () => {
  const v = built();
  v.openAll();
  const moved = v.drag(v.rowOf(v.mbom(), 'C'), v.rowOf(v.mbom(), 'B'));   // no layout in jsdom: the middle of a line that holds lines is "into"
  assert.strictEqual(moved.mode, 'move');
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'A', 'A1', 'A2', 'B', 'B1', 'C'], 'C went into B, which is open, after B1');
  assert.strictEqual(v.rowOf(v.mbom(), 'C').style.getPropertyValue('--indent'), '64px');
  v.drag(v.rowOf(v.mbom(), 'A'), v.rowOf(v.mbom(), 'A1'));
  assert.match(v.toasts[v.toasts.length - 1], /inside itself|not an assembly/);
  const again = v.drag(v.rowOf(v.mbom(), 'B1'), v.rowOf(v.mbom(), 'A'), { ctrlKey: true });
  assert.strictEqual(again.mode, 'move', 'ctrl does not copy: the line moves');
  v.openAll();
  assert.strictEqual(v.lines(v.mbom()).filter((n) => n === 'B1').length, 1);
});

test('dragging an EBOM line into the MBOM adds it with what is under it, and Alt without', skip, () => {
  const v = built();
  v.openAll();
  v.button('Collapse All').click();
  v.act(v.mbom(), 'B', 'remove').click();
  const added = v.drag(v.rowOf(v.ebom(), 'B'), v.rowOf(v.mbom(), 'TOP'));
  assert.strictEqual(added.mode, 'add');
  v.openAll();
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'A', 'A1', 'A2', 'C', 'B', 'B1']);
  v.act(v.mbom(), 'C', 'remove').click();
  v.act(v.mbom(), 'A', 'remove').click();
  v.drag(v.rowOf(v.ebom(), 'A'), v.rowOf(v.mbom(), 'TOP'), { altKey: true });
  v.openAll();
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'B', 'B1', 'A']);
});

test('the MBOM read from Fusion Manage is mapped by item number, marks what has no EBOM line, and the changes show', skip, () => {
  const v = open({ targetId: '77', phantom: false });
  v.show();
  v.ns.mbomViewer.structureRead();
  assert.strictEqual(v.calls.askMbom, 1);
  const line = (number, quantity, children) => ({ number: number, name: number + ' name', quantity: quantity, sequence: '1', edge_id: 'e' + number, item_id: 'i' + number, children: children || [] });
  v.ns.mbomViewer.answer({ ok: true, data: { number: 'TOP-M', name: 'Top M', item_id: '77', children: [line('A', '2', [line('A1', '1'), line('A2', '1')]), line('OIL', '1'), line('C', '1')] } });
  v.openAll();
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP-M', 'A', 'A1', 'A2', 'OIL', 'C']);
  assert.match(v.rowOf(v.mbom(), 'OIL').querySelector('.sv-note-btn').title, /Not in the EBOM/, 'a line with no EBOM line says so');
  assert.ok(!v.rowOf(v.mbom(), 'A').querySelector('.sv-note-btn') || !/Not in the EBOM/.test(v.rowOf(v.mbom(), 'A').querySelector('.sv-note-btn').title));
  assert.ok(v.rowOf(v.ebom(), 'B').classList.contains('sv-row-missing'), 'B is not in the MBOM');
  assert.strictEqual(v.mbom().closest('.sv-pane').querySelector('.sv-pane-title').textContent, 'Fusion Manage');
  v.act(v.mbom(), 'C', 'remove').click();
  assert.match(v.w.document.querySelector('.sv-removed').textContent, /Removed since it was read: C/);
  assert.strictEqual(v.rowOf(v.mbom(), 'A').classList.contains('sv-tone-new'), false);
});

test('a failed read of the MBOM is shown, and the search finds lines and opens what is above them', skip, () => {
  const bad = open({ targetId: '77' });
  bad.show();
  bad.ns.mbomViewer.structureRead();
  bad.ns.mbomViewer.answer({ ok: false, message: 'no such item' });
  assert.match(bad.w.document.getElementById('pub-structure').textContent, /no such item/);
  const v = built();
  const search = v.w.document.querySelector('.sv-search');
  search.value = 'a2';
  search.dispatchEvent(new v.w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'A', 'A1', 'A2', 'B', 'C']);
  assert.ok(v.rowOf(v.mbom(), 'A2').classList.contains('sv-hit'));
  assert.match(v.w.document.querySelector('.sv-found').textContent, /1 found/);
});

test('add items opens the picker with the target item and puts what it returns into the MBOM', skip, () => {
  const v = built({ targetId: '' });
  v.button('Add Existing Part').click();
  assert.strictEqual(v.added.length, 1);
  v.added[0].onAdd([{ id: '9', number: 'X9', name: 'Extra', link: '/api/v3/workspaces/57/items/9', linkable: null }]);
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'A', 'B', 'C', 'X9']);
  assert.match(v.rowOf(v.mbom(), 'X9').querySelector('.sv-note-btn').title, /Added item/);
});

const mbomTree = (children) => ({ number: 'TOP-M', name: 'Top M', item_id: '77', children: children });
const treeLine = (number, quantity, extra) => Object.assign({ number: number, name: number + ' name', quantity: quantity || '1', edge_id: 'e' + number, item_id: 'i' + number, children: [] }, extra || {});
const enter = (v, text) => {
  const input = v.mbom().querySelector('.sv-qty-input');
  input.value = text;
  input.dispatchEvent(new v.w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
};
const search = (v, text) => {
  const box = v.w.document.querySelector('.sv-search');
  box.value = text;
  box.dispatchEvent(new v.w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  return box;
};
const found = (v) => v.w.document.querySelector('.sv-found').textContent;

test('a second answer, or one after the Bill of Materials was read again, never replaces what is built', skip, () => {
  const v = open({ targetId: '77' });
  v.show();
  v.ns.mbomViewer.answer({ ok: true, data: mbomTree([treeLine('C', '1')]) });   // nobody is waiting for it yet: ignored
  assert.strictEqual(v.w.document.querySelector('.sv-row'), null);
  v.ns.mbomViewer.structureRead();
  assert.strictEqual(v.calls.askMbom, 1);
  v.ns.mbomViewer.structureRead();
  assert.strictEqual(v.calls.askMbom, 1, 'asked once while the answer is on its way');
  v.ns.mbomViewer.answer({ ok: true, data: mbomTree([treeLine('C', '1')]) });
  v.click(v.rowOf(v.mbom(), 'C').querySelector('button.sv-qty'));
  enter(v, '6');
  v.ns.mbomViewer.answer({ ok: true, data: mbomTree([treeLine('C', '1'), treeLine('D', '1')]) });
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP-M', 'C'], 'the late answer is dropped');
  assert.strictEqual(v.rowOf(v.mbom(), 'C').querySelector('.sv-qty').textContent, '6.0');
  v.ns.mbomViewer.treeDone({ ok: true });
  assert.strictEqual(v.rowOf(v.mbom(), 'C').querySelector('.sv-qty').textContent, '6.0', 'neither does a tree read for the table');
});

test('reading the Bill of Materials again drops the structure, the selection and the search', skip, () => {
  const v = built();
  v.click(v.rowOf(v.mbom(), 'C'));
  const box = search(v, 'c');
  v.ns.mbomViewer.reset();
  assert.strictEqual(box.value, '');
  assert.match(v.w.document.getElementById('pub-structure').textContent, /Reading the Fusion Component structure/);
  v.ns.mbomViewer.structureRead();
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'A', 'B', 'C']);
  assert.strictEqual(v.mbom().querySelectorAll('.sv-row.selected').length, 0);
  assert.strictEqual(found(v), '');
});

test('the Add Items picker, answering after the Bill of Materials was read again, adds nothing', skip, () => {
  const v = built();
  v.button('Add Existing Part').click();
  v.ns.mbomViewer.reset();
  v.ns.mbomViewer.structureRead();
  v.added[0].onAdd([{ id: '9', number: 'X9', name: 'Extra' }]);
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'A', 'B', 'C']);
});

test('lines a fold hides leave the selection, so an action on a line does not take them along', skip, () => {
  const v = built();
  const toggleA = () => v.click(v.rowOf(v.mbom(), 'A').querySelector('.sv-toggle'));
  toggleA();
  v.click(v.rowOf(v.mbom(), 'A1'));
  v.click(v.rowOf(v.mbom(), 'B'), { ctrlKey: true });
  assert.match(v.act(v.mbom(), 'B', 'remove').title, /2 selected lines/);
  toggleA();   // A1 is hidden now: B alone is selected
  assert.doesNotMatch(v.act(v.mbom(), 'B', 'remove').title, /selected lines/);
  v.act(v.mbom(), 'B', 'remove').click();
  v.openAll();
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'A', 'A1', 'A2', 'C']);
  v.click(v.rowOf(v.mbom(), 'A1'));
  v.button('Collapse All').click();
  assert.strictEqual(v.mbom().querySelectorAll('.sv-row.selected').length, 0);
  v.openAll();
  assert.strictEqual(v.mbom().querySelectorAll('.sv-row.selected').length, 0);
});

test('the search is run again after an edit and an undo', skip, () => {
  const v = built();
  search(v, 'C');
  assert.match(found(v), /1 found/);
  v.act(v.mbom(), 'C', 'remove').click();
  assert.match(found(v), /No match/);
  v.button('Undo').click();
  assert.match(found(v), /1 found/);
  assert.ok(v.rowOf(v.mbom(), 'C').classList.contains('sv-hit'));
});

test('EBOM lines are added with the icons on them, no drag needed, the selection together', skip, () => {
  const v = built();
  assert.strictEqual(v.act(v.ebom(), 'A', 'add'), undefined, 'all of it is in the MBOM: nothing to add');
  assert.strictEqual(v.rowOf(v.ebom(), 'A').dataset.drag, undefined);
  ['A', 'B', 'C'].forEach((n) => v.act(v.mbom(), n, 'remove').click());
  assert.ok(v.act(v.ebom(), 'A', 'add'), 'an assembly has the one Add');
  assert.strictEqual(v.act(v.ebom(), 'C', 'add_deep'), undefined, 'there is no separate add with the lines under it');
  v.click(v.rowOf(v.ebom(), 'B'));
  v.click(v.rowOf(v.ebom(), 'C'), { ctrlKey: true });
  assert.match(v.act(v.ebom(), 'C', 'add').title, /2 selected lines/);
  v.act(v.ebom(), 'C', 'add').click();
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'B', 'C']);
  v.act(v.ebom(), 'A', 'add').click();
  v.openAll();
  assert.deepStrictEqual(v.lines(v.mbom()).slice(-3), ['A', 'A1', 'A2']);
});

test('the icons on a line: add to assembly, the bin last, and a handle to drag it by', skip, () => {
  const v = built();
  v.openAll();
  assert.ok(v.rowOf(v.mbom(), 'B').querySelector('.sv-grip'));
  const order = (id) => [...v.rowOf(v.mbom(), id).querySelectorAll('.sv-act')].map((b) => b.dataset.act);
  assert.deepStrictEqual(order('A'), ['position', 'addTo', 'remove'], 'the position first, the bin always last');
  assert.deepStrictEqual(order('C'), ['position', 'addTo', 'remove']);
  assert.strictEqual(v.rowOf(v.mbom(), 'TOP').querySelector('.sv-act'), null, 'the MBOM itself has none');
  v.click(v.rowOf(v.mbom(), 'B'));
  v.click(v.rowOf(v.mbom(), 'C'), { ctrlKey: true });
});

test('Add to assembly opens a tree with a search and moves the selected lines to the one chosen', skip, () => {
  const v = built();
  v.openAll();
  v.click(v.rowOf(v.mbom(), 'B'));
  v.click(v.rowOf(v.mbom(), 'C'), { ctrlKey: true });
  v.act(v.mbom(), 'C', 'addTo').click();
  const doc = v.w.document;
  const names = () => [...doc.querySelectorAll('.sv-dest-number')].map((n) => n.textContent);
  assert.ok(doc.querySelector('.sv-dest-search'), 'a search is on top');
  assert.strictEqual(doc.querySelector('.sv-dest svg.sv-tree-icon, .sv-dest .tree-icon'), null, 'no icons on the lines');
  assert.ok(!names().includes('B') && !names().includes('C'), 'the lines being moved are not places');
  assert.ok(names().includes('A'));
  assert.strictEqual(doc.querySelector('.sv-dest-bar').hidden, true, 'the search is closed until the magnifier is used');
  doc.querySelector('.sv-dest-find').click();
  assert.strictEqual(doc.querySelector('.sv-dest-bar').hidden, false);
  const search = doc.querySelector('.sv-dest-search');
  search.value = 'a';
  search.dispatchEvent(new v.w.Event('input'));
  assert.ok(names().includes('A'), 'a search keeps the lines that match');
  [...doc.querySelectorAll('.sv-dest-pick')].find((p) => p.querySelector('.sv-dest-number').textContent === 'A').click();
  assert.strictEqual(doc.querySelector('.sv-dest'), null, 'the menu closes');
  assert.strictEqual(v.rowOf(v.mbom(), 'B').parentNode, v.rowOf(v.mbom(), 'C').parentNode);
});

test('lines are tree items, and the line selected says so', skip, () => {
  const v = built();
  v.click(v.rowOf(v.mbom(), 'B'));
  assert.strictEqual(v.mbom().querySelector('.sv-tree').getAttribute('role'), 'tree');
  assert.strictEqual(v.rowOf(v.mbom(), 'B').getAttribute('role'), 'treeitem');
  assert.strictEqual(v.rowOf(v.mbom(), 'B').getAttribute('aria-selected'), 'true');
  assert.strictEqual(v.rowOf(v.mbom(), 'C').getAttribute('aria-selected'), 'false');
  assert.strictEqual(v.rowOf(v.mbom(), 'A').getAttribute('aria-expanded'), 'false');
});

test('a line cut at the deepest level says its lines were not read', skip, () => {
  const v = open({ targetId: '77' });
  v.show();
  v.ns.mbomViewer.structureRead();
  v.ns.mbomViewer.answer({ ok: true, data: mbomTree([treeLine('C', '1', { cut: true })]) });
  assert.match(v.rowOf(v.mbom(), 'C').querySelector('.sv-note-btn').title, /not read/);
});

test('a few thousand lines build and draw quickly, only the open ones drawn', skip, () => {
  const rows = [];
  for (let i = 0; i < 4000; i++) { rows.push(row(0, 'P' + i, '1')); if (i % 8 === 0) rows.push(row(1, 'Q' + i, '1')); }
  const start = Date.now();
  const v = built({ rows: rows });
  assert.ok(v.mbom().querySelectorAll('.sv-row').length <= 201, 'the first 200 lines and the root');
  assert.ok(v.mbom().querySelector('.sv-more'));
  v.click(v.mbom().querySelector('.sv-more'));
  assert.ok(v.mbom().querySelectorAll('.sv-row').length <= 401);
  v.act(v.mbom(), 'P1', 'remove').click();
  assert.ok(Date.now() - start < 5000, 'took ' + (Date.now() - start) + ' ms');
});

test('the MBOM read from Fusion Manage shows every line, and removing a selected range is one step that Undo gives back', skip, () => {
  const v = open({ targetId: '77', rows: [row(0, 'PN-000700'), row(0, 'PN-000699'), row(0, 'PN-000705'), row(1, 'PN-000703'), row(1, 'PN-000702'), row(0, 'PN-000704')] });
  v.show();
  v.ns.mbomViewer.structureRead();
  const kids = [treeLine('PN-000703'), treeLine('PN-000702')];
  v.ns.mbomViewer.answer({ ok: true, data: { number: 'PN-000701', name: 'T', item_id: '77', children: [
    treeLine('PN-000700'), treeLine('PN-000699'), treeLine('PN-000705', '1', { children: kids }), treeLine('PN-000704')] } });
  assert.deepStrictEqual(v.lines(v.mbom()), ['PN-000701', 'PN-000700', 'PN-000699', 'PN-000705', 'PN-000704']);
  assert.strictEqual(v.button('Undo').disabled, true, 'nothing was done: nothing to undo');
  assert.strictEqual(v.w.document.querySelector('.sv-removed').textContent, '');
  v.click(v.rowOf(v.mbom(), 'PN-000700'));
  v.click(v.rowOf(v.mbom(), 'PN-000704'), { shiftKey: true });
  v.act(v.mbom(), 'PN-000700', 'remove').click();
  assert.deepStrictEqual(v.lines(v.mbom()), ['PN-000701']);
  assert.match(v.w.document.querySelector('.sv-removed').textContent, /PN-000700, PN-000699, PN-000705 \(\+2\), PN-000704/);
  v.button('Undo').click();
  assert.deepStrictEqual(v.lines(v.mbom()), ['PN-000701', 'PN-000700', 'PN-000699', 'PN-000705', 'PN-000704']);
  assert.strictEqual(v.w.document.querySelector('.sv-removed').textContent, '');
});

test('a Delete pressed on an icon or a field does not remove the selected lines', skip, () => {
  const v = built();
  v.click(v.rowOf(v.mbom(), 'A'));
  v.click(v.rowOf(v.mbom(), 'C'), { shiftKey: true });
  const press = (el) => el.dispatchEvent(new v.w.KeyboardEvent('keydown', { key: 'Delete', bubbles: true }));
  press(v.rowOf(v.mbom(), 'C').querySelector('.sv-act'));
  press(v.rowOf(v.mbom(), 'A').querySelector('.sv-toggle'));
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'A', 'B', 'C']);
  press(v.mbom().querySelector('.sv-tree'));
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP']);
});

const seqs = (pane) => [...pane.querySelectorAll('.sv-row')].map((r) => (r.querySelector('.sv-seq') || { textContent: '' }).textContent);

test('each line has its number: the design sequence in the EBOM, the place under its assembly in the MBOM, renumbered as lines move', skip, () => {
  const rows = ROWS.map((r, i) => Object.assign({}, r, { sequence: (i + 1) * 10 }));
  const v = built({ rows: rows });
  v.openAll();
  assert.deepStrictEqual(seqs(v.ebom()), ['', '10', '20', '30', '40', '50', '60']);
  assert.deepStrictEqual(seqs(v.mbom()), ['', '1', '1', '2', '2', '1', '3']);
  v.act(v.mbom(), 'C', 'remove').click();
  assert.deepStrictEqual(seqs(v.mbom()), ['', '1', '1', '2', '2', '1']);
  v.act(v.ebom(), 'C', 'add').click();
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'A', 'A1', 'A2', 'B', 'B1', 'C']);
  assert.deepStrictEqual(seqs(v.mbom()), ['', '1', '1', '2', '2', '1', '3']);
});

test('an EBOM line all in the MBOM is greyed with a check mark, an assembly only when everything under it is', skip, () => {
  const v = built();
  v.openAll();
  const matched = () => [...v.ebom().querySelectorAll('.sv-row-matched .sv-pn')].map((n) => n.textContent);
  assert.deepStrictEqual(matched(), ['A', 'A1', 'A2', 'B', 'B1', 'C']);
  assert.match(v.rowOf(v.ebom(), 'C').querySelector('.sv-matched').title, /All of it is in the bill of materials/);
  v.act(v.mbom(), 'B1', 'remove').click();
  assert.deepStrictEqual(matched(), ['A', 'A1', 'A2', 'C'], 'B is not matched while B1 is gone');
  assert.ok(v.rowOf(v.ebom(), 'B1').classList.contains('sv-row-missing'));
  assert.strictEqual(v.rowOf(v.ebom(), 'B1').querySelector('.sv-matched'), null);
  assert.strictEqual(v.rowOf(v.ebom(), 'B1').dataset.drag, '1', 'it can still be added');
  v.click(v.rowOf(v.mbom(), 'C').querySelector('button.sv-qty'));
  enter(v, '2');
  assert.match(v.rowOf(v.ebom(), 'C').querySelector('.sv-note-btn').title, /exceeds/, 'over covered: exceeded, not matched');
  assert.ok(!matched().includes('C'));
});

test('the New item button and the Create bought version action open the side panel', skip, () => {
  const v = open({ targetId: '77' });
  const opened = [];
  v.ns.pubItemPanel = { open: (o) => opened.push(o), close: () => {} };
  v.show();
  v.ns.mbomViewer.structureRead();
  v.ns.mbomViewer.answer({ ok: true, data: mbomTree([treeLine('C', '1'), treeLine('OIL', '1', { item_id: '' })]) });
  const tool = v.button('New Manufacturing Item');
  assert.ok(tool, 'the toolbar has an icon button named New Manufacturing Item');
  assert.strictEqual(tool.title, 'New Manufacturing Item');
  v.click(tool);
  assert.deepStrictEqual(JSON.parse(JSON.stringify(opened)), [{ mode: 'assembly' }]);
  assert.strictEqual(v.act(v.mbom(), 'C', 'bought'), undefined, 'the MBOM lines have no such action');
  assert.strictEqual(v.act(v.ebom(), 'TOP', 'bought'), undefined, 'the root has none');
  assert.strictEqual(v.act(v.ebom(), 'C', 'bought'), undefined, 'a component already in the MBOM has none');
  assert.strictEqual(v.act(v.ebom(), 'B', 'bought').getAttribute('aria-label'), 'Create Purchased Version of B');
  v.act(v.ebom(), 'B', 'bought').click();
  assert.strictEqual(opened[1].mode, 'bought');
  assert.strictEqual(opened[1].sourceNumber, 'B');
  assert.strictEqual(opened[1].number, 'B');
  assert.strictEqual(typeof opened[1].onFound, 'function');
  assert.strictEqual(typeof opened[1].onCreated, 'function');
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP-M', 'C', 'OIL'], 'it does not add the component to the MBOM');
});

test('Create bought version is off, with the reason, until Make or buy is set up in Settings', skip, () => {
  const v = open({ targetId: '77', bought: false });
  const opened = [];
  v.ns.pubItemPanel = { open: (o) => opened.push(o), close: () => {} };
  v.show();
  v.ns.mbomViewer.structureRead();
  v.ns.mbomViewer.answer({ ok: true, data: mbomTree([treeLine('C', '1')]) });
  const action = v.act(v.ebom(), 'B', 'bought');
  assert.strictEqual(action.disabled, true);
  assert.match(action.title, /Set up Make or buy in Settings/);
  action.click();
  assert.deepStrictEqual(opened, []);
});

function panelWith(v, opened) {
  const panel = { open: (o) => opened.push(o), close: () => {} };
  v.ns.pubItemPanel = panel;
  return panel;
}

function withPanel() {
  const v = open({ targetId: '77' });
  const opened = [];
  const panel = panelWith(v, opened);
  v.show();
  v.ns.mbomViewer.structureRead();
  v.ns.mbomViewer.answer({ ok: true, data: mbomTree([treeLine('C', '1')]) });
  return { v, opened, panel };
}

test('nothing is asked of Fusion Manage when the structure opens: no pill, and the action reads the same for every component', skip, () => {
  const { v } = withPanel();
  assert.strictEqual(v.rowOf(v.ebom(), 'B').querySelector('.sv-note-btn'), null);
  assert.strictEqual(v.act(v.ebom(), 'B', 'bought').getAttribute('aria-label'), 'Create Purchased Version of B');
  assert.strictEqual(v.act(v.ebom(), 'B', 'bought').disabled, false);
});

test('the dialog opens at once; a bought version it found and the user chose is added to the MBOM with no message line', skip, () => {
  const { v, opened } = withPanel();
  v.act(v.ebom(), 'B', 'bought').click();
  assert.strictEqual(opened.length, 1, 'opened without waiting for a search');
  opened[0].onFound({ id: '9', link: '/api/v3/workspaces/1/items/9', number: 'B-B', name: 'Bee' });
  assert.ok(v.lines(v.mbom()).includes('B-B'), 'it is added to the MBOM on the right');
  assert.deepStrictEqual(v.toasts, [], 'nothing is said');
  assert.strictEqual(v.act(v.ebom(), 'B', 'bought'), undefined, 'the EBOM line stands in the MBOM now');
});

test('a bought version created in the dialog is added to the MBOM in the quantity of the EBOM line', skip, () => {
  const { v, opened } = withPanel();
  v.act(v.ebom(), 'B', 'bought').click();
  opened[0].onCreated({ id: '9', number: 'B-B', link: '/api/v3/workspaces/1/items/9' });
  assert.ok(v.lines(v.mbom()).includes('B-B'), 'the bought item is added to the MBOM on the right');
  assert.strictEqual(v.act(v.ebom(), 'B', 'bought'), undefined, 'the EBOM line is in the MBOM now: it stands for B, so it has no such action');
  assert.strictEqual(v.rowOf(v.mbom(), 'B-B').querySelector('.sv-qty').textContent, '1.0', 'in the quantity of the EBOM line');
});

test('an EBOM line a purchased part stands for gets a check mark that says a purchased part matched it', skip, () => {
  const { v, opened } = withPanel();
  assert.strictEqual(v.rowOf(v.ebom(), 'B').querySelector('.sv-matched'), null);
  v.act(v.ebom(), 'B', 'bought').click();
  opened[0].onCreated({ id: '9', number: 'B-B', link: '/api/v3/workspaces/1/items/9' });
  const mark = v.rowOf(v.ebom(), 'B').querySelector('.sv-matched');
  assert.ok(mark, 'the line shows it was matched by a purchased part');
  assert.strictEqual(mark.title, 'Matched by a purchased part');
  assert.notStrictEqual(v.rowOf(v.ebom(), 'C').querySelector('.sv-matched').title, mark.title, 'a line made as it is has its own tooltip');
});

test('an EBOM line a purchased part stands for says which one, and a quantity that does not agree says by how much', skip, () => {
  const { v, opened } = withPanel();
  assert.strictEqual(v.rowOf(v.ebom(), 'B').querySelector('.sv-note-btn'), null, 'a line with nothing to say has no button');
  v.act(v.ebom(), 'B', 'bought').click();
  opened[0].onCreated({ id: '9', number: 'B-B', link: '/api/v3/workspaces/1/items/9' });
  const button = v.rowOf(v.ebom(), 'B').querySelector('.sv-note-btn');
  assert.ok(button, 'the icon button is there');
  assert.ok(button.previousElementSibling.classList.contains('sv-qty'), 'right of the quantity');
  assert.ok(v.rowOf(v.ebom(), 'C').querySelector('.sv-qty').nextElementSibling.classList.contains('sv-note-slot'), 'a line with none keeps its room, so the quantities line up');
  assert.ok(v.rowOf(v.ebom(), 'B').querySelector('.sv-qty').previousElementSibling.classList.contains('sv-matched'), 'the tick is just left of the quantity');
  assert.strictEqual(button.title, 'Linked to purchased part B-B');
  assert.strictEqual(v.rowOf(v.ebom(), 'B').nextElementSibling.classList.contains('sv-note-row'), false, 'closed until it is clicked');
  v.click(button);
  const note = v.rowOf(v.ebom(), 'B').nextElementSibling;
  assert.ok(note.classList.contains('sv-note-row'));
  assert.match(note.textContent, /Linked to purchased part B-B/);
  v.click(v.rowOf(v.ebom(), 'B').querySelector('.sv-note-btn'));
  assert.ok(!v.rowOf(v.ebom(), 'B').nextElementSibling || !v.rowOf(v.ebom(), 'B').nextElementSibling.classList.contains('sv-note-row'), 'a second click closes it');
  const mbomLine = v.rowOf(v.mbom(), 'B-B').querySelector('.sv-note-btn');
  assert.ok(mbomLine, 'and the MBOM line says what it is');
  assert.match(mbomLine.title, /Purchased part for B/);
  assert.match(mbomLine.title, /New line/);
  v.click(v.rowOf(v.mbom(), 'B-B').querySelector('button.sv-qty'));
  const input = v.mbom().querySelector('input');
  input.value = '3';
  input.dispatchEvent(new v.w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  const warn = v.rowOf(v.ebom(), 'B').querySelector('.sv-note-btn');
  assert.ok(warn.classList.contains('sv-note-warn'), 'more than the EBOM has is a warning');
  assert.match(warn.title, /Qty 3\.0 exceeds 1\.0 in the EBOM/);
});

test('there are no pills on a line: what they said is in its note', skip, () => {
  const v = built();
  v.show();
  assert.strictEqual(v.w.document.querySelectorAll('.sv-badge').length, 0);
});

test('an EBOM line that is under another assembly in the MBOM says which one', skip, () => {
  const v = built();
  v.openAll();
  v.drag(v.rowOf(v.mbom(), 'B1'), v.rowOf(v.mbom(), 'A'));   // B1 into A (the middle of a line is into it)
  const note = v.rowOf(v.ebom(), 'B1').querySelector('.sv-note-btn');
  assert.ok(note, 'B1 is no longer under B');
  assert.match(note.title, /Under A in the MBOM/);
});

test('adding an EBOM line the MBOM holds some of adds what is left to its line under the same assembly', skip, () => {
  const v = open({ rows: [row(0, 'A', '4')], targetId: '77' });
  v.show();
  v.ns.mbomViewer.structureRead();
  v.ns.mbomViewer.answer({ ok: true, data: mbomTree([treeLine('A', '1')]) });
  assert.strictEqual(v.rowOf(v.mbom(), 'A').querySelector('.sv-qty').textContent, '1.0');
  v.act(v.ebom(), 'A', 'add').click();
  assert.deepStrictEqual(v.toasts, [], 'not refused');
  const quantities = [...v.mbom().querySelectorAll('.sv-row')].filter((r) => r.querySelector('.sv-pn').textContent === 'A').map((r) => r.querySelector('.sv-qty').textContent);
  assert.deepStrictEqual(quantities, ['4.0'], 'the 3 that were missing went to the line that is under the same assembly');
  assert.ok(v.rowOf(v.ebom(), 'A').classList.contains('sv-row-matched'), 'and now all of it is in');
});

test('the info button and the bar beside the line icon share a colour: amber for a warning or an update, green for a new line', skip, () => {
  const v = built();
  v.openAll();
  v.click(v.rowOf(v.mbom(), 'C').querySelector('button.sv-qty'));
  const input = v.mbom().querySelector('input');
  input.value = '3';
  input.dispatchEvent(new v.w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  const c = v.rowOf(v.mbom(), 'C');
  assert.ok(c.querySelector('.sv-note-btn').classList.contains('sv-note-warn'), 'more than the EBOM has: amber');
  assert.ok(c.classList.contains('sv-tone-warn'), 'and the bar is amber too');
  const ebom = v.rowOf(v.ebom(), 'C');
  assert.ok(ebom.querySelector('.sv-note-btn').classList.contains('sv-note-warn') && ebom.classList.contains('sv-tone-warn'), 'the same on the EBOM line');
});

test('a line read from Fusion Manage whose quantity was edited is amber (an update), with no bar at the left of the line', skip, () => {
  const v = open({ rows: [row(0, 'A', '4')], targetId: '77' });
  v.show();
  v.ns.mbomViewer.structureRead();
  v.ns.mbomViewer.answer({ ok: true, data: mbomTree([treeLine('A', '4')]) });
  v.click(v.rowOf(v.mbom(), 'A').querySelector('button.sv-qty'));
  const input = v.mbom().querySelector('input');
  input.value = '3';
  input.dispatchEvent(new v.w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  const line = v.rowOf(v.mbom(), 'A');
  assert.ok(line.classList.contains('sv-tone-warn'), 'an update is amber');
  assert.ok(line.querySelector('.sv-note-btn').classList.contains('sv-note-warn'));
  assert.ok(![...line.classList].some((k) => k.startsWith('sv-chg-')), 'no bar at the left');
});

test('the panel is told to plan again only when the structure or its data changed, not by a selection, a fold, a note or the search', skip, () => {
  const v = built();
  const planned = v.calls.planned;
  assert.ok(planned > 0, 'the first draw tells the panel');
  v.click(v.rowOf(v.mbom(), 'A'));
  v.openAll();
  v.click(v.rowOf(v.mbom(), 'A').querySelector('.sv-toggle'));
  assert.strictEqual(v.calls.planned, planned, 'selecting and folding leave what publishing covers as it was');
  v.click(v.act(v.mbom(), 'B', 'remove'));
  assert.strictEqual(v.calls.planned, planned + 1, 'an edit tells it once');
  v.ns.mbomViewer.treeDone({ ok: true });
  assert.strictEqual(v.calls.planned, planned + 2, 'so does reading more of the design');
});

test('quick add asks before it overrides the lines Fusion Manage has, and matches the MBOM to the EBOM once it is confirmed', skip, () => {
  const v = open({ targetId: '77' });
  const asked = [];
  v.ns.pubItemPanel = { open: () => {}, close: () => {}, confirm: (o) => asked.push(o) };
  v.show();
  v.ns.mbomViewer.structureRead();
  v.ns.mbomViewer.answer({ ok: true, data: mbomTree([treeLine('OIL', '1'), treeLine('C', '1')]) });
  const tool = v.button('Quick Add');
  assert.ok(tool, 'the toolbar has the quick add button');
  v.click(tool);
  assert.strictEqual(asked.length, 1);
  assert.strictEqual(asked[0].title, 'Match to Fusion Component');
  assert.match(asked[0].ask, /override Fusion Manage/);
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP-M', 'OIL', 'C'], 'nothing changes until it is confirmed');
  asked[0].onConfirm();
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP-M', 'A', 'B', 'C'], 'the lines are shown at once, the top one open');
  v.openAll();
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP-M', 'A', 'A1', 'A2', 'B', 'B1', 'C']);
  v.click(v.button('Undo'));
  v.openAll();
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP-M', 'OIL', 'C'], 'undo gives the lines back');
});

test('quick add with no lines in Fusion Manage matches at once, with no question', skip, () => {
  const v = open({ targetId: '77' });
  const asked = [];
  v.ns.pubItemPanel = { open: () => {}, close: () => {}, confirm: (o) => asked.push(o) };
  v.show();
  v.ns.mbomViewer.structureRead();
  v.ns.mbomViewer.answer({ ok: true, data: mbomTree([]) });
  v.click(v.button('Quick Add'));
  assert.strictEqual(asked.length, 0);
  v.openAll();
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP-M', 'A', 'A1', 'A2', 'B', 'B1', 'C']);
});

test('the MBOM shows the line numbers Fusion Manage has, in their order, until an edit gives the assembly the numbers of its places', skip, () => {
  const v = open({ targetId: '77' });
  v.show();
  v.ns.mbomViewer.structureRead();
  v.ns.mbomViewer.answer({ ok: true, data: mbomTree([treeLine('A', '2', { sequence: '1' }), treeLine('B', '1', { sequence: '2' }), treeLine('C', '1', { sequence: '8' })]) });
  const numbers = () => [...v.mbom().querySelectorAll('.sv-row')].slice(1).map((r) => r.querySelector('.sv-seq').textContent);
  assert.deepStrictEqual(numbers(), ['1', '2', '8'], 'as Fusion Manage has them, not 1, 2, 3');
  v.act(v.mbom(), 'B', 'remove').click();
  assert.deepStrictEqual(numbers(), ['1', '8'], 'a removal leaves the others as they are');
  v.click(v.button('Undo'));
  v.drag(v.rowOf(v.mbom(), 'C'), v.rowOf(v.mbom(), 'A'));   // C goes into A (no layout in jsdom: the middle of a line is "into")
  v.openAll();
  assert.deepStrictEqual(v.lines(v.mbom()).slice(1), ['A', 'C', 'B']);
  assert.deepStrictEqual(numbers(), ['1', '1', '2'], 'A and B keep their numbers; C is line 1 of A, as it will be sent');
});

test('Automatic renumber asks first, then numbers the lines 1, 2, 3 in the order shown, says so when they are already, and undo gives the numbers back', skip, () => {
  const v = open({ targetId: '77' });
  const asked = [];
  v.ns.pubItemPanel = { open: () => {}, close: () => {}, confirm: (o) => asked.push(o) };
  v.show();
  v.ns.mbomViewer.structureRead();
  v.ns.mbomViewer.answer({ ok: true, data: mbomTree([treeLine('A', '2', { sequence: '1' }), treeLine('B', '1', { sequence: '2' }), treeLine('C', '1', { sequence: '8' })]) });
  const numbers = () => [...v.mbom().querySelectorAll('.sv-row')].slice(1).map((r) => r.querySelector('.sv-seq').textContent);
  const tool = v.button('Automatic Renumber');
  assert.ok(tool, 'the toolbar has the Automatic renumber button');
  v.click(tool);
  assert.strictEqual(asked.length, 1);
  assert.strictEqual(asked[0].title, 'Automatic Renumber');
  assert.match(asked[0].ask, /Are you sure/);
  assert.deepStrictEqual(numbers(), ['1', '2', '8'], 'nothing changes until it is confirmed');
  asked[0].onConfirm();
  assert.deepStrictEqual(numbers(), ['1', '2', '3']);
  v.click(tool);
  assert.strictEqual(asked.length, 1, 'nothing to renumber: no question');
  assert.match(v.toasts[v.toasts.length - 1], /numbered 1, 2, 3 already/);
  v.click(v.button('Undo'));
  assert.deepStrictEqual(numbers(), ['1', '2', '8']);
});

test('the Set Position hover action opens a small box with the number the line shows, and gives the line any whole number', skip, () => {
  const v = open({ targetId: '77' });
  v.show();
  v.ns.mbomViewer.structureRead();
  v.ns.mbomViewer.answer({ ok: true, data: mbomTree([treeLine('A', '1', { sequence: '1' }), treeLine('B', '1', { sequence: '2' }), treeLine('C', '1', { sequence: '8' })]) });
  const doc = v.w.document;
  const numbers = () => [...v.mbom().querySelectorAll('.sv-row')].slice(1).map((r) => r.querySelector('.sv-seq').textContent);
  const set = (value) => { const box = doc.querySelector('.sv-pos'); box.querySelector('.sv-pos-input').value = value; box.querySelector('.sv-pos-set').click(); };
  const action = v.act(v.mbom(), 'C', 'position');
  assert.strictEqual(action.getAttribute('aria-label'), 'Set Position');
  v.click(action);
  const box = doc.querySelector('.sv-pos');
  assert.ok(box, 'the box is open');
  assert.strictEqual(box.querySelector('.sv-pos-input').value, '8', 'it starts at the number the line shows');
  assert.match(box.textContent, /New position number/);
  ['', 'x', '0', '-2', '1.5'].forEach((bad) => {
    set(bad);
    assert.ok(doc.querySelector('.sv-pos'), 'a value that is not a whole number keeps the box open: ' + bad);
    assert.match(box.querySelector('.sv-pos-message').textContent, /whole number, 1 or more/);
  });
  set('2');
  assert.match(box.querySelector('.sv-pos-message').textContent, /already has the number 2/, 'a number another line has is said');
  set('10');
  assert.strictEqual(doc.querySelector('.sv-pos'), null, 'any number is taken, 10 with only three lines: the box closes');
  assert.deepStrictEqual(numbers(), ['1', '2', '10']);
  v.click(v.act(v.mbom(), 'C', 'position'));
  set('1500');
  assert.deepStrictEqual(numbers(), ['1', '2', '1500']);
  v.click(v.act(v.mbom(), 'A', 'position'));
  set('5');
  assert.deepStrictEqual(v.lines(v.mbom()).slice(1), ['B', 'A', 'C'], 'the line goes to the place its number gives it');
  assert.deepStrictEqual(numbers(), ['2', '5', '1500'], 'the other lines keep their numbers');
  v.click(v.act(v.mbom(), 'B', 'position'));
  doc.querySelector('.sv-pos-input').dispatchEvent(new v.w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  assert.strictEqual(doc.querySelector('.sv-pos'), null, 'Escape closes it');
  v.click(v.button('Undo'));
  assert.deepStrictEqual(numbers(), ['1', '2', '1500'], 'each is one step');
});
