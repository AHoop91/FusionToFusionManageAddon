// What publishing does with the structure: the job (components and BOM operations) made from the edited MBOM.
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { dataWindow } = require('./helpers');

const ns = dataWindow();
const S = ns.mbomStructure;
const plain = (x) => JSON.parse(JSON.stringify(x));
const row = (id, level, number, extra) => Object.assign({ id: id, level: level, item_number: number, part_number: number, name: number + ' name', description: '', sequence: 1, quantity: '1', status: 'new' }, extra || {});
// TOP: A (x2) [A1, A2], B [B1], C
const ROWS = [row('a', 0, 'A', { quantity: '2', sequence: 1 }), row('a1', 1, 'A1', { sequence: 1 }), row('a2', 1, 'A2', { sequence: 2 }), row('b', 0, 'B', { sequence: 2 }), row('b1', 1, 'B1', { sequence: 1 }), row('c', 0, 'C', { sequence: 3 })];
const SUMMARY = { item_number: 'TOP-M', part_number: 'TOP', name: 'Top', component_id: 'root' };
const EBOM = S.ebomFromRows(ROWS, { item_number: 'TOP', name: 'Top', component_id: 'root' });

function plan(structure, extra) {
  return plain(ns.mbomPlan.build(Object.assign({ structure: structure, ebom: EBOM, rows: ROWS, summary: SUMMARY, skipped: {} }, extra || {})));
}

// An MBOM read from Fusion Manage: TOP-M [A (x2, line 10) [A1 (1), A2 (2)], B (line 20)]
const read = () => S.create({ ebom: EBOM, mbom: S.mapByNumber({ number: 'TOP-M', itemId: 'i0', children: [
  { number: 'A', quantity: '2', itemId: 'iA', edgeId: 'eA', sequence: '10', children: [{ number: 'A1', quantity: '1', itemId: 'iA1', edgeId: 'eA1', sequence: '1', children: [] }, { number: 'A2', quantity: '1', itemId: 'iA2', edgeId: 'eA2', sequence: '2', children: [] }] },
  { number: 'B', quantity: '1', itemId: 'iB', edgeId: 'eB', sequence: '20', children: [] },
] }, EBOM) });

// The same assembly in two places of the MBOM read: its lines are one BOM in Fusion Manage, so both places carry the same line ids.
const twice = () => {
  const lines = () => [{ number: 'A1', quantity: '1', itemId: 'iA1', edgeId: 'eA1', sequence: '1', children: [] }, { number: 'A2', quantity: '1', itemId: 'iA2', edgeId: 'eA2', sequence: '2', children: [] }];
  return S.create({ ebom: EBOM, mbom: S.mapByNumber({ number: 'TOP-M', itemId: 'i0', children: [
    { number: 'A', quantity: '1', itemId: 'iA', edgeId: 'eA', sequence: '10', children: lines() },
    { number: 'A', quantity: '1', itemId: 'iA', edgeId: 'eA2', sequence: '20', children: lines() },
  ] }, EBOM) });
};

test('a design with no MBOM item publishes every line as an add, numbered 1, 2, 3 under each assembly, with the design and each component as items', () => {
  const p = plan(S.create({ ebom: EBOM }));
  assert.deepStrictEqual(p.operations.map((o) => [o.op, o.parent, o.number, o.quantity, o.sequence].join('|')),
    ['add|TOP-M|A|2|1', 'add|A|A1|1|1', 'add|A|A2|1|2', 'add|TOP-M|B|1|2', 'add|B|B1|1|1', 'add|TOP-M|C|1|3']);
  assert.deepStrictEqual(p.components.map((c) => c.id), ['root', 'a', 'a1', 'a2', 'b', 'b1', 'c']);
  assert.strictEqual(p.components[0].root, true);
  assert.strictEqual(p.components[0].item_number, 'TOP-M', 'the design goes under the number of the MBOM chosen');
  assert.deepStrictEqual(p.problems, []);
});

test('an unedited MBOM that was read has nothing to add, update or remove, but its components still go through the comparison', () => {
  const p = plan(read());
  assert.deepStrictEqual(p.operations, []);
  assert.deepStrictEqual(p.components.map((c) => c.id), ['root', 'a', 'a1', 'a2', 'b']);
});

test('a purchased item added is one add with its link and no component; the line it stands for is removed', () => {
  const s = read();
  const b = s.root().children.find((c) => c.number === 'B');
  s.remove([b.uid]);
  s.addItems([{ id: '9', number: 'B-B', link: '/api/v3/workspaces/1/items/9', quantity: '1', source: '0.1' }], S.ROOT, '');
  const p = plan(s);
  assert.deepStrictEqual(p.operations, [
    { op: 'remove', parent: 'TOP-M', number: 'B', sequence: '20', edge: 'eB' },
    { op: 'add', parent: 'TOP-M', number: 'B-B', quantity: '1', sequence: '11', link: '/api/v3/workspaces/1/items/9', linkable: null },
  ]);
  assert.ok(!p.components.some((c) => c.id === 'b'), 'B is gone from the MBOM, and a bought item is never an item to publish');
  assert.deepStrictEqual(p.problems, []);
});

test('a quantity change is an update with the line, its old quantity and its place', () => {
  const s = read();
  s.setQuantity(s.root().children[1].uid, '3');
  assert.deepStrictEqual(plan(s).operations, [{ op: 'update', parent: 'TOP-M', number: 'B', quantity: '3', fm_quantity: '1', sequence: '20', edge: 'eB' }]);
});

test('a line moved to another assembly is removed from the one it left and added to the new one, after its lines', () => {
  const s = read();
  const b = s.root().children[1];
  const a = s.root().children[0];
  s.move([b.uid], a.uid, '');
  assert.deepStrictEqual(plan(s).operations, [
    { op: 'remove', parent: 'TOP-M', number: 'B', sequence: '20', edge: 'eB' },
    { op: 'add', parent: 'A', number: 'B', quantity: '1', sequence: '3' },
  ]);
});

test('a removed line is a remove; one that went with its assembly is not', () => {
  const s = read();
  const a = s.root().children[0];
  s.remove([a.children[0].uid]);
  assert.deepStrictEqual(plan(s).operations, [{ op: 'remove', parent: 'A', number: 'A1', sequence: '1', edge: 'eA1' }]);
  const t = read();
  t.remove([t.root().children[0].uid]);
  assert.deepStrictEqual(plan(t).operations, [{ op: 'remove', parent: 'TOP-M', number: 'A', sequence: '10', edge: 'eA' }], 'its own lines stay in its item');
});

test('what is not published is said, never dropped: a new assembly of manufacturing only and the same assembly with different lines', () => {
  const t = S.create({ ebom: EBOM, phantom: true });
  t.createAssembly('assembly', S.ROOT, '', { number: 'MFG-1' });
  assert.deepStrictEqual(plan(t).problems, [{ kind: 'unpublishable', numbers: ['MFG-1'] }]);
  const u = twice();
  const two = u.root().children[1].children[0];   // the first line of the second A
  u.setQuantity(two.uid, '2');
  assert.ok(plan(u).problems.some((p) => p.kind === 'ambiguous' && p.numbers.includes('A')));
});

test('a component the table leaves out of publishing, and a line with no item number, are said and not sent', () => {
  const p = plan(S.create({ ebom: EBOM }), { skipped: { c: 'C' } });
  assert.deepStrictEqual(p.problems, [{ kind: 'skipped', numbers: ['C'] }]);
  assert.ok(!p.components.some((c) => c.id === 'c'));
  const s = S.create({ ebom: EBOM });
  s.addItems([{ id: '9', number: '', quantity: '1' }], S.ROOT, '');
  assert.ok(plan(s).problems.some((x) => x.kind === 'skipped'));
});

test('the same assembly in two places with the same change is changed once', () => {
  const s = twice();
  s.setQuantity(s.root().children[0].children[0].uid, '2');
  s.setQuantity(s.root().children[1].children[0].uid, '2');
  assert.deepStrictEqual(plan(s).operations, [{ op: 'update', parent: 'A', number: 'A1', quantity: '2', fm_quantity: '1', sequence: '1', edge: 'eA1' }], 'one update, not two');
});

test('for a design with no MBOM item the structure gives the same job as the table did', () => {
  const old = plain(ns.bomPlan.publishPlan(ROWS, SUMMARY));
  const now = plan(S.create({ ebom: EBOM }));
  const short = (o) => [o.op, o.parent, o.number, o.quantity, o.sequence].join('|');
  assert.deepStrictEqual(now.operations.map(short).sort(), old.operations.map(short).sort());
  assert.deepStrictEqual(now.components.map((c) => c.id).sort(), old.components.map((c) => c.id).sort());
});

// TOP-M [P (10), Q (20), R (30), S (40)] as read from Fusion Manage.
const four = () => S.create({ ebom: EBOM, mbom: S.mapByNumber({ number: 'TOP-M', itemId: 'i0', children: ['P', 'Q', 'R', 'S'].map((n, i) => (
  { number: n, quantity: '1', itemId: 'i' + n, edgeId: 'e' + n, sequence: String((i + 1) * 10), children: [] })) }, EBOM) });

/** The numbers the lines of TOP-M have in Fusion Manage after the plan's requests (the requests find a line by its edge), in the order Fusion Manage lists them. */
function after(structure, extra) {
  const p = plan(structure, extra);
  const numbers = { P: 10, Q: 20, R: 30, S: 40 };
  const edges = { eP: 'P', eQ: 'Q', eR: 'R', eS: 'S' };
  p.operations.filter((o) => o.op === 'remove').forEach((o) => { delete numbers[edges[o.edge]]; });
  const taken = new Set(Object.values(numbers));
  p.operations.filter((o) => o.op === 'renumber').forEach((o) => {
    assert.ok(!taken.has(Number(o.sequence)) || numbers[edges[o.edge]] === Number(o.sequence), 'no line is given a number another holds');
    numbers[edges[o.edge]] = Number(o.sequence);
  });
  p.operations.filter((o) => o.op === 'add').forEach((o) => {
    assert.ok(!Object.values(numbers).includes(Number(o.sequence)), 'a new line does not take a number that is held');
    numbers[o.number] = Number(o.sequence);
  });
  assert.strictEqual(new Set(Object.values(numbers)).size, Object.values(numbers).length, 'every number is held once');
  return { order: Object.keys(numbers).sort((x, y) => numbers[x] - numbers[y]).join(''), plan: p };
}
const uidOf = (s, n) => s.root().children.find((c) => c.number === n).uid;

test('a line moved up or down among its siblings is renumbered, so Fusion Manage lists the lines in the tree\'s order', () => {
  const swap = four();
  swap.move([uidOf(swap, 'S')], S.ROOT, uidOf(swap, 'Q'));   // P S Q R
  const r = after(swap);
  assert.strictEqual(r.order, 'PSQR');
  assert.deepStrictEqual(r.plan.problems, []);
  assert.ok(r.plan.operations.every((o) => o.op === 'renumber'), 'only renumbers, nothing added or removed');
  const front = four();
  front.move([uidOf(front, 'R')], S.ROOT, uidOf(front, 'P'));   // R P Q S
  assert.strictEqual(after(front).order, 'RPQS');
  const last = four();
  last.move([uidOf(last, 'P')], S.ROOT, '');   // Q R S P
  assert.strictEqual(after(last).order, 'QRSP');
});

test('lines before the first change keep their numbers, and a new line in the middle takes the lines after it with it', () => {
  const s = four();
  s.addItems([{ id: '9', number: 'N', quantity: '1' }], S.ROOT, uidOf(s, 'R'));   // P Q N R S
  const r = after(s);
  assert.strictEqual(r.order, 'PQNRS');
  assert.deepStrictEqual(r.plan.operations.filter((o) => o.op === 'renumber').map((o) => o.number), ['R', 'S'], 'P and Q are not touched');
  const end = four();
  end.addItems([{ id: '9', number: 'N', quantity: '1' }], S.ROOT, '');   // appended
  assert.deepStrictEqual(plan(end).operations.map((o) => o.op), ['add'], 'an appended line is only added');
  assert.strictEqual(after(end).order, 'PQRSN');
});

test('a reorder together with a quantity change is one request for the line, and a removal that frees a number does not clash with it', () => {
  const s = four();
  s.move([uidOf(s, 'S')], S.ROOT, uidOf(s, 'Q'));
  s.setQuantity(uidOf(s, 'S'), '5');
  const renumber = plan(s).operations.find((o) => o.op === 'renumber' && o.number === 'S');
  assert.strictEqual(renumber.quantity, '5', 'the quantity goes with the new number');
  assert.ok(!plan(s).operations.some((o) => o.op === 'update' && o.number === 'S'), 'not a second request on the same line');
  const t = four();
  t.remove([uidOf(t, 'S')]);
  t.move([uidOf(t, 'R')], S.ROOT, uidOf(t, 'P'));   // R P Q, S gone
  const r = after(t);
  assert.strictEqual(r.order, 'RPQ');
});

test('a bought version read from Fusion Manage does not make its EBOM component an item to publish', () => {
  const mapped = S.mapByNumber({ number: 'TOP-M', itemId: 'i0', children: [
    { number: 'A-B', quantity: '2', itemId: 'iAB', edgeId: 'eAB', sequence: '10', children: [] },
    { number: 'B', quantity: '1', itemId: 'iB', edgeId: 'eB', sequence: '20', children: [] }] }, EBOM, '-B');
  const p = plan(S.create({ ebom: EBOM, mbom: mapped }));
  assert.deepStrictEqual(p.components.map((c) => c.id), ['root', 'b']);
  assert.deepStrictEqual(p.operations, []);
});
