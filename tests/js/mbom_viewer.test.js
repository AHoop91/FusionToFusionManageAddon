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
  const opts = Object.assign({ rows: ROWS, targetId: '', phantom: false, partial: false }, options || {});
  const dom = new JSDOM('<button id="pub-add-items"></button><button id="pub-view-table"></button><button id="pub-view-structure"></button>'
    + '<section id="pub-bom"></section><section id="pub-structure" hidden></section>', { runScripts: 'outside-only', pretendToBeVisual: true });
  const w = dom.window;
  w.MfgUi = {};
  const ns = w.MfgUi;
  ['../shared/js/dom.js'].forEach((src) => run(w, src));
  ns.i18n = englishI18n();
  const added = [];
  ns.pubAddItems = { open: (o) => added.push(o) };
  ns.bomTable = { foldTools: (collapse, expand) => {   // the table's pair of buttons (tested with the table)
    const pair = w.document.createElement('div');
    [['Collapse all', collapse], ['Expand all', expand]].forEach(([label, run]) => {
      const b = w.document.createElement('button');
      b.setAttribute('aria-label', label);
      b.addEventListener('click', run);
      pair.appendChild(b);
    });
    return pair;
  } };
  ns.picker = { make: () => Object.assign(w.document.createElement('div'), { getPicked: () => [] }) };   // the real picker is tested with its own page
  ['js/ui.js', 'js/mbom-structure.js', 'js/mbom-viewer.js'].forEach((src) => run(w, src));
  const calls = { loadTree: 0, askMbom: 0 };
  const state = { partial: opts.partial };
  ns.mbomViewer.init({
    design: () => ({ item_number: 'TOP', name: 'Top', component_id: 'R' }), rows: () => opts.rows, partial: () => state.partial,
    loadTree: () => { calls.loadTree++; }, askMbom: () => { calls.askMbom++; }, targetId: () => opts.targetId, target: () => (opts.targetId ? 'TOP-M' : ''),
    phantom: () => opts.phantom,
  });
  const $ = (id) => w.document.getElementById(id);
  const api = {
    w: w, ns: ns, calls: calls, state: state, added: added,
    show: () => $('pub-view-structure').click(),
    ebom: () => $('pub-structure').querySelectorAll('.sv-pane')[0],
    mbom: () => $('pub-structure').querySelectorAll('.sv-pane')[1],
    lines: (pane) => [...pane.querySelectorAll('.sv-row')].map((r) => r.querySelector('.sv-pn').textContent),
    rowOf: (pane, number) => [...pane.querySelectorAll('.sv-row')].find((r) => r.querySelector('.sv-pn').textContent === number),
    click: (el, init) => el.dispatchEvent(new w.MouseEvent('click', Object.assign({ bubbles: true }, init || {}))),
    button: (label) => [...$('pub-structure').querySelectorAll('.sv-bar button')].find((b) => b.getAttribute('aria-label') === label),
    act: (pane, number, name) => [...api.rowOf(pane, number).querySelectorAll('.sv-act')].find((b) => b.dataset.act === name),
    message: () => $('pub-structure').querySelector('.sv-message'),
    openAll: () => api.button('Expand all').click(),
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
  assert.match(v.w.document.getElementById('pub-structure').textContent, /Reading the Bill of Materials/);
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
  v.button('Collapse all').click();
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
  assert.strictEqual(v.message().hidden, true);
  assert.ok(v.rowOf(v.mbom(), 'C').querySelector('.sv-badge-chg-quantity') === null, 'a copy of the EBOM has nothing read to change from: it is new');
  edit('0');
  assert.strictEqual(quantity(), '4.0');
  assert.strictEqual(v.message().hidden, false);
  assert.match(v.message().textContent, /above 0/);
  edit('5');
  assert.strictEqual(v.message().hidden, true, 'the next edit that works clears the message');
});

test('remove, undo and redo, and the buttons say why they cannot be used', skip, () => {
  const v = built();
  assert.strictEqual(v.button('Undo').disabled, true);
  assert.match(v.button('Undo').title, /nothing to undo/);
  assert.match(v.act(v.mbom(), 'C', 'remove').title, /Remove from the MBOM/);
  v.act(v.mbom(), 'C', 'remove').click();
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'A', 'B']);
  assert.ok(v.ebom().querySelector('.sv-row-missing'), 'the EBOM line that has no MBOM line is marked');
  v.button('Undo').click();
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'A', 'B', 'C']);
  v.button('Redo').click();
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'A', 'B']);
  assert.strictEqual(v.button('Create phantom assembly'), undefined, 'no phantom button for now');
});

test('create assembly needs a typed number that is free, takes the selected lines in, and says why when it cannot', skip, () => {
  const v = built();
  v.click(v.rowOf(v.mbom(), 'B'));
  v.click(v.rowOf(v.mbom(), 'C'), { ctrlKey: true });
  v.button('Create assembly').click();
  const form = v.w.document.querySelector('.sv-form');
  assert.strictEqual(form.hidden, false);
  const [number] = form.querySelectorAll('input');
  const submit = () => [...form.querySelectorAll('button')].find((b) => b.textContent === 'OK').click();
  number.value = 'A';
  number.dispatchEvent(new v.w.Event('input'));
  submit();
  assert.match(v.message().textContent, /already used/);
  assert.strictEqual(form.hidden, false, 'the form stays open for another number');
  number.value = 'X-1';
  number.dispatchEvent(new v.w.Event('input'));
  submit();
  assert.strictEqual(form.hidden, true);
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'A', 'X-1', 'B', 'C'], 'X-1 took B and C in, and is open');
  assert.ok(v.rowOf(v.mbom(), 'X-1').querySelector('.sv-badge-kind'));
});

test('dragging in the MBOM moves a line, with ctrl copies it, and a refused drop is said', skip, () => {
  const v = built();
  v.openAll();
  v.drag(v.rowOf(v.mbom(), 'C'), v.rowOf(v.mbom(), 'B'));   // no layout in jsdom: the middle of a line that holds lines is "into"
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'A', 'A1', 'A2', 'B', 'B1', 'C'], 'C went into B, which is open, after B1');
  assert.strictEqual(v.rowOf(v.mbom(), 'C').style.getPropertyValue('--indent'), '64px');
  v.drag(v.rowOf(v.mbom(), 'A'), v.rowOf(v.mbom(), 'A1'));
  assert.match(v.message().textContent, /inside itself|not an assembly/);
  const copied = v.drag(v.rowOf(v.mbom(), 'B1'), v.rowOf(v.mbom(), 'A'), { ctrlKey: true });
  assert.strictEqual(copied.mode, 'copy');
  v.openAll();
  assert.strictEqual(v.lines(v.mbom()).filter((n) => n === 'B1').length, 2);
});

test('dragging an EBOM line into the MBOM adds it with what is under it, and Alt without', skip, () => {
  const v = built();
  v.openAll();
  v.button('Collapse all').click();
  v.act(v.mbom(), 'B', 'remove').click();
  v.drag(v.rowOf(v.ebom(), 'B'), v.rowOf(v.mbom(), 'TOP'));
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
  assert.ok(v.rowOf(v.mbom(), 'OIL').querySelector('.sv-badge-mfg'), 'a line with no EBOM line is marked');
  assert.strictEqual(v.rowOf(v.mbom(), 'A').querySelector('.sv-badge-mfg'), null);
  assert.ok(v.rowOf(v.ebom(), 'B').classList.contains('sv-row-missing'), 'B is not in the MBOM');
  assert.strictEqual(v.mbom().closest('.sv-pane').querySelector('.sv-pane-title').textContent, 'Fusion Manage');
  v.act(v.mbom(), 'C', 'remove').click();
  assert.match(v.w.document.querySelector('.sv-removed').textContent, /Removed since it was read: C/);
  assert.strictEqual(v.rowOf(v.mbom(), 'A').classList.contains('sv-chg-new'), false);
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
  v.button('Add existing part').click();
  assert.strictEqual(v.added.length, 1);
  v.added[0].onAdd([{ id: '9', number: 'X9', name: 'Extra', link: '/api/v3/workspaces/57/items/9', linkable: null }]);
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'A', 'B', 'C', 'X9']);
  assert.ok(v.rowOf(v.mbom(), 'X9').querySelector('.sv-badge-kind'));
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

test('reading the Bill of Materials again drops the structure, the form, the selection and the search', skip, () => {
  const v = built();
  v.click(v.rowOf(v.mbom(), 'C'));
  v.button('Create assembly').click();
  const box = search(v, 'c');
  assert.strictEqual(v.w.document.querySelector('.sv-form').hidden, false);
  v.ns.mbomViewer.reset();
  assert.strictEqual(v.w.document.querySelector('.sv-form').hidden, true, 'a form left open would act on the lines of the new structure');
  assert.strictEqual(box.value, '');
  assert.match(v.w.document.getElementById('pub-structure').textContent, /Reading the Bill of Materials/);
  v.ns.mbomViewer.structureRead();
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'A', 'B', 'C']);
  assert.strictEqual(v.mbom().querySelectorAll('.sv-row.selected').length, 0);
  assert.strictEqual(found(v), '');
});

test('the Add Items picker, answering after the Bill of Materials was read again, adds nothing', skip, () => {
  const v = built();
  v.button('Add existing part').click();
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
  v.button('Collapse all').click();
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
  assert.strictEqual(v.act(v.ebom(), 'A', 'add_deep'), undefined, 'all of it is in the MBOM: nothing to add');
  assert.strictEqual(v.rowOf(v.ebom(), 'A').dataset.drag, undefined);
  ['A', 'B', 'C'].forEach((n) => v.act(v.mbom(), n, 'remove').click());
  assert.ok(v.act(v.ebom(), 'A', 'add_deep'), 'an assembly has both');
  assert.strictEqual(v.act(v.ebom(), 'C', 'add_deep'), undefined, 'a part has the one');
  v.click(v.rowOf(v.ebom(), 'B'));
  v.click(v.rowOf(v.ebom(), 'C'), { ctrlKey: true });
  assert.match(v.act(v.ebom(), 'C', 'add_one').title, /2 selected lines/);
  v.act(v.ebom(), 'C', 'add_one').click();
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'B', 'C']);
  v.act(v.ebom(), 'A', 'add_deep').click();
  v.openAll();
  assert.deepStrictEqual(v.lines(v.mbom()).slice(-3), ['A', 'A1', 'A2']);
});

test('the icons on a line: split, copy, new assembly, the bin last, and a handle to drag it by', skip, () => {
  const v = built();
  v.openAll();
  assert.ok(v.rowOf(v.mbom(), 'B').querySelector('.sv-grip'));
  assert.strictEqual(v.act(v.mbom(), 'C', 'split'), undefined, 'only an assembly is split');
  const order = (id) => [...v.rowOf(v.mbom(), id).querySelectorAll('.sv-act')].map((b) => b.dataset.act);
  assert.deepStrictEqual(order('A'), ['split', 'copy', 'assembly', 'remove'], 'the bin is always last');
  assert.deepStrictEqual(order('C'), ['copy', 'assembly', 'remove']);
  assert.strictEqual(v.act(v.mbom(), 'A', 'split').disabled, true);
  assert.match(v.act(v.mbom(), 'A', 'split').title, /Select some of the lines/);
  assert.strictEqual(v.rowOf(v.mbom(), 'TOP').querySelector('.sv-act'), null, 'the MBOM itself has none');
  v.act(v.mbom(), 'C', 'copy').click();
  assert.deepStrictEqual(v.lines(v.mbom()).filter((n) => n === 'C').length, 2);
  v.click(v.rowOf(v.mbom(), 'A2'));
  assert.strictEqual(v.act(v.mbom(), 'A', 'split').disabled, false);
  v.act(v.mbom(), 'A', 'split').click();
  const form = v.w.document.querySelector('.sv-form');
  const [number] = form.querySelectorAll('input');
  number.value = 'A-S';
  number.dispatchEvent(new v.w.Event('input'));
  [...form.querySelectorAll('button')].find((b) => b.textContent === 'OK').click();
  assert.deepStrictEqual(v.lines(v.mbom()).slice(0, 6), ['TOP', 'A', 'A1', 'A-S', 'A2', 'B']);
  v.button('Undo').click();   // A has both its lines again
  v.click(v.rowOf(v.mbom(), 'A1'));
  v.act(v.mbom(), 'A', 'split').click();
  assert.ok(v.w.document.querySelector('.sv-form > div:not(.sv-form-actions)'), 'the lines can go into an assembly that is there already (a picker; the test page has a stand-in for it)');
  v.click(v.rowOf(v.mbom(), 'B'));
  v.click(v.rowOf(v.mbom(), 'C'), { ctrlKey: true });
  v.act(v.mbom(), 'C', 'assembly').click();
  assert.match(v.w.document.querySelector('.sv-form-title').textContent, /New assembly/);
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
  assert.ok(v.rowOf(v.mbom(), 'C').querySelector('.sv-badge-cut'));
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
  v.act(v.mbom(), 'B', 'copy').click();
  assert.deepStrictEqual(v.lines(v.mbom()), ['TOP', 'A', 'A1', 'A2', 'B', 'B1', 'B']);
  assert.deepStrictEqual(seqs(v.mbom()), ['', '1', '1', '2', '2', '1', '3']);
});

test('an EBOM line all in the MBOM is greyed with a check mark, an assembly only when everything under it is', skip, () => {
  const v = built();
  v.openAll();
  const matched = () => [...v.ebom().querySelectorAll('.sv-row-matched .sv-pn')].map((n) => n.textContent);
  assert.deepStrictEqual(matched(), ['A', 'A1', 'A2', 'B', 'B1', 'C']);
  assert.match(v.rowOf(v.ebom(), 'C').querySelector('.sv-matched').title, /All of it is in the MBOM/);
  v.act(v.mbom(), 'B1', 'remove').click();
  assert.deepStrictEqual(matched(), ['A', 'A1', 'A2', 'C'], 'B is not matched while B1 is gone');
  assert.ok(v.rowOf(v.ebom(), 'B1').classList.contains('sv-row-missing'));
  assert.strictEqual(v.rowOf(v.ebom(), 'B1').querySelector('.sv-matched'), null);
  assert.strictEqual(v.rowOf(v.ebom(), 'B1').dataset.drag, '1', 'it can still be added');
  v.act(v.mbom(), 'C', 'copy').click();
  assert.ok(v.rowOf(v.ebom(), 'C').querySelector('.sv-badge-exceeded'), 'over covered: exceeded, not matched');
  assert.ok(!matched().includes('C'));
});
