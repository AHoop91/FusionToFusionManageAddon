// The data side of the Bill of Materials: the tree as it has been read, the lines and their keys, and what publishing does.
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { dataWindow } = require('./helpers');

const ns = dataWindow();
const tree = ns.bomTree;
const model = ns.bomModel;
const plan = ns.bomPlan;

const row = (id, number, extra) => Object.assign({
  level: 0, id: id, item_number: number, part_number: number, name: id + ' name', description: '', sequence: 1, quantity: '1',
  has_children: false, status: 'match',
}, extra || {});
const root = { item_number: 'TOP', part_number: 'TOP', name: 'Top', component_id: 'R' };
const plain = (x) => JSON.parse(JSON.stringify(x));   // the scripts run in a window of their own: arrays are compared as data
const ids = (rows) => plain(rows.map((r) => r.id + ':' + r.level));
// A Fusion Manage line at a position where the design has another item number, and the design line that takes its place.
const pair = (id, number, oldNumber, level) => [
  row('', oldNumber, { level: level || 0, status: 'extra', pair: number, part_number: oldNumber, edge_id: 'e' }),
  row(id, number, { level: level || 0, status: 'new' }),
];

test('the first level shows its unread assemblies, and reading one adds its lines under it', () => {
  tree.setTop([row('A', 'PN-A', { has_children: true }), row('B', 'PN-B', { has_children: true }), row('C', 'PN-C')]);
  assert.deepStrictEqual(plain(tree.unloaded().sort()), ['A', 'B']);
  tree.setKids('A', [row('X', 'PN-X', { has_children: true })]);
  tree.setKids('B', [row('X', 'PN-X', { has_children: true })]);
  assert.deepStrictEqual(plain(tree.unloaded()), ['X'], 'a component used twice is read once');
  tree.setKids('X', [row('Y', 'PN-Y')]);
  assert.deepStrictEqual(ids(tree.rows()), ['A:0', 'X:1', 'Y:2', 'B:0', 'X:1', 'Y:2', 'C:0']);
  assert.deepStrictEqual(plain(tree.unloaded()), []);
});

test('a component inside itself does not loop', () => {
  tree.setTop([row('A', 'PN-A', { has_children: true })]);
  tree.setKids('A', [row('A', 'PN-A', { has_children: true })]);
  assert.strictEqual(tree.rows().length, 2);
});

test('the whole tree, read in one go, keeps one set of lines for a component used twice', () => {
  tree.setAll([
    row('A', 'PN-A', { level: 0, has_children: true }), row('X', 'PN-X', { level: 1, has_children: true }), row('Y', 'PN-Y', { level: 2 }),
    row('B', 'PN-B', { level: 0, has_children: true }), row('X', 'PN-X', { level: 1, has_children: true }), row('Y', 'PN-Y', { level: 2 }),
  ]);
  assert.deepStrictEqual(ids(tree.rows()), ['A:0', 'X:1', 'Y:2', 'B:0', 'X:1', 'Y:2']);
  assert.deepStrictEqual(plain(tree.unloaded()), []);
});

test('an assembly the whole tree holds no lines for has nothing left to read', () => {
  tree.setAll([row('A', 'PN-A', { has_children: true })]);
  assert.deepStrictEqual(plain(tree.unloaded()), []);
});

test('a choice on a differing pair keeps its key when another level is read', () => {
  tree.setTop([row('A', 'PN-A', { has_children: true }), ...pair('P', 'PN-P', 'PN-OLD')]);
  const key = () => model.buildItems(tree.rows(), root).find((i) => i.status === 'mismatch').key;
  const before = key();
  tree.setKids('A', [row('Z', 'PN-Z'), row('W', 'PN-W')]);
  assert.strictEqual(key(), before);
});

test('the same pair under two parents has two keys', () => {
  tree.setTop([row('A', 'PN-A', { has_children: true }), row('B', 'PN-B', { has_children: true })]);
  tree.setKids('A', pair('P', 'PN-P', 'PN-OLD'));
  tree.setKids('B', pair('P', 'PN-P', 'PN-OLD'));
  const keys = model.buildItems(tree.rows(), root).filter((i) => i.status === 'mismatch').map((i) => i.key);
  assert.strictEqual(new Set(keys).size, 2);
});

test('a skipped assembly keeps its id and flag, and publishing leaves it and what is below it out', () => {
  tree.setTop([row('S', '', { status: 'skipped', skip: 'no_number', has_children: true }), row('A', 'PN-A', { status: 'new' })]);
  tree.setKids('S', [row('T', 'PN-T', { status: 'skipped', skip: 'parent' })]);
  const items = model.buildItems(tree.rows(), root);
  assert.strictEqual(items[1].assembly, true);
  assert.strictEqual(items[1].lineId, 'S');
  const result = plan.publishPlan(tree.rows(), root);
  assert.deepStrictEqual(plain(result.components.map((c) => c.id)), ['R', 'A']);
  assert.deepStrictEqual(plain(result.operations.map((o) => o.op + ':' + o.parent + '>' + o.number)), ['add:TOP>PN-A']);
});

test('publishing adds new lines under their parents, updates a quantity, and honours the choice on a pair', () => {
  model.clearDecisions();
  tree.setTop([
    row('A', 'PN-A', { has_children: true }), ...pair('P', 'PN-P', 'PN-OLD'),
    row('C', 'PN-C', { status: 'changed', quantity: '2', fm_quantity: '1' }),
  ]);
  tree.setKids('A', [row('X', 'PN-X', { status: 'new' })]);
  const summary = () => plain(plan.publishPlan(tree.rows(), root).operations.map((o) => o.op + ':' + o.parent + '>' + o.number));
  const key = model.buildItems(tree.rows(), root).find((i) => i.status === 'mismatch').key;
  model.decisions[key] = 'remove';   // the Fusion Manage line goes, the design line is added
  assert.deepStrictEqual(summary(), ['add:PN-A>PN-X', 'add:TOP>PN-P', 'remove:TOP>PN-OLD', 'update:TOP>PN-C']);
  model.decisions[key] = 'add';   // keep both: the old line stays, renumbered to the end
  assert.deepStrictEqual(summary(), ['add:PN-A>PN-X', 'add:TOP>PN-P', 'update:TOP>PN-C', 'renumber:TOP>PN-OLD']);
  model.clearDecisions();
});

test('the label is the item number and the part name; a line without an item number shows its part number', () => {
  tree.setTop([row('A', 'PN-A'), row('S', '', { status: 'skipped', skip: 'no_number', part_number: 'PART-9' })]);
  const items = model.buildItems(tree.rows(), root);
  assert.deepStrictEqual(plain([items[1].design.pn, items[1].design.name]), ['PN-A', 'A name']);
  assert.strictEqual(items[2].design.pn, 'PART-9');
  assert.strictEqual(items[0].design.pn, 'TOP');
});

test('what is in view: the design, and the lines of every open assembly', () => {
  const scope = ns.bomScope;
  const rows = [
    row('A', 'PN-A', { level: 0, has_children: true }), row('X', 'PN-X', { level: 1, has_children: true }), row('Y', 'PN-Y', { level: 2 }),
    row('B', 'PN-B', { level: 0, has_children: true }), row('Z', 'PN-Z', { level: 1 }), row('C', 'PN-C', { level: 0 }),
  ];
  const only = (...open) => (id) => open.includes(id);
  const seen = (isOpen) => ids(scope.visibleRows(rows, 'R', isOpen));
  assert.deepStrictEqual(seen(only('R')), ['A:0', 'B:0', 'C:0'], 'a design with every assembly closed');
  assert.deepStrictEqual(seen(only('R', 'A')), ['A:0', 'X:1', 'B:0', 'C:0']);
  assert.deepStrictEqual(seen(only('R', 'A', 'X')), ['A:0', 'X:1', 'Y:2', 'B:0', 'C:0']);
  assert.deepStrictEqual(seen(only('R', 'X')), ['A:0', 'B:0', 'C:0'], 'an open assembly under a closed one is not in view');
  assert.deepStrictEqual(seen(only('A', 'X', 'B')), [], 'a closed design shows nothing');
  assert.deepStrictEqual(seen(only('R', 'A', 'X', 'B')), ['A:0', 'X:1', 'Y:2', 'B:0', 'Z:1', 'C:0']);
  const visible = scope.visibleRows(rows, 'R', only('R', 'A'));
  assert.strictEqual(scope.closedAssemblies(visible, only('R', 'A')), 2, 'X and B are closed');
});

test('components that share an item number are all skipped, with what is below them, and are not published', () => {
  tree.setTop([row('A', 'PN-S', { has_children: true }), row('B', 'PN-S'), row('C', 'PN-C', { status: 'new' })]);
  tree.setKids('A', [row('X', 'PN-X', { status: 'new' })]);
  const items = model.buildItems(tree.rows(), root);
  assert.deepStrictEqual(plain(items.slice(1).map((i) => i.status + ':' + (i.skip || ''))), ['skipped:shared', 'skipped:parent', 'skipped:shared', 'new:']);
  assert.deepStrictEqual(plain(items[1].sharedWith), ['PN-S - B name'], 'each says which components it shares the number with');
  assert.strictEqual(items[1].lineId, 'A', 'an assembly keeps its id, so its lines can be read');
  const result = plan.publishPlan(tree.rows(), root);
  assert.deepStrictEqual(plain(result.components.map((c) => c.id)), ['R', 'C']);
  assert.deepStrictEqual(plain(result.operations.map((o) => o.op + ':' + o.parent + '>' + o.number)), ['add:TOP>PN-C']);
});

test('one component on several lines does not share its number with itself, and the case of a number does not matter', () => {
  tree.setTop([row('A', 'PN-A', { status: 'new' }), row('A', 'PN-A', { status: 'new', sequence: 2 })]);
  assert.deepStrictEqual(plain(model.buildItems(tree.rows(), root).slice(1).map((i) => i.status)), ['new', 'new']);
  tree.setTop([row('A', 'pn-a', { status: 'new' }), row('B', ' PN-A ', { status: 'new' })]);
  assert.deepStrictEqual(plain(model.buildItems(tree.rows(), root).slice(1).map((i) => i.skip)), ['shared', 'shared']);
});

test('a line that shares the number of the design is skipped, and the design is not', () => {
  tree.setTop([row('A', 'TOP', { status: 'new' }), row('B', 'PN-B', { status: 'new' })]);
  const items = model.buildItems(tree.rows(), root);
  assert.deepStrictEqual(plain(items.map((i) => i.status)), ['root', 'skipped', 'new']);
  assert.deepStrictEqual(plain(plan.publishPlan(tree.rows(), root).components.map((c) => c.id)), ['R', 'B']);
});
