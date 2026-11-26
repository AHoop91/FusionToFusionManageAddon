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
    { op: 'renumber', parent: 'TOP-M', number: 'A', from_sequence: '10', sequence: '1', edge: 'eA' },   // the lines are numbered 1, 2 in the tree's order
    { op: 'add', parent: 'TOP-M', number: 'B-B', quantity: '1', sequence: '2', link: '/api/v3/workspaces/1/items/9', linkable: null },
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

// TOP-M [P (10), Q (20), R (30), S (40)] as read from Fusion Manage.
const four = () => S.create({ ebom: EBOM, mbom: S.mapByNumber({ number: 'TOP-M', itemId: 'i0', children: ['P', 'Q', 'R', 'S'].map((n, i) => (
  { number: n, quantity: '1', itemId: 'i' + n, edgeId: 'e' + n, sequence: String((i + 1) * 10), children: [] })) }, EBOM) });

/** The numbers the lines of TOP-M have in Fusion Manage after the plan's requests (the requests find a line by its edge), in the order Fusion Manage lists them. */
function after(structure, extra) {
  const p = plan(structure, extra);
  const numbers = { P: 10, Q: 20, R: 30, S: 40 };
  const edges = { eP: 'P', eQ: 'Q', eR: 'R', eS: 'S' };
  p.operations.filter((o) => o.op === 'remove').forEach((o) => { delete numbers[edges[o.edge]]; });
  p.operations.filter((o) => o.op === 'renumber').forEach((o) => {
    numbers[edges[o.edge]] = Number(o.sequence);
  });
  p.operations.filter((o) => o.op === 'add').forEach((o) => {
    numbers[o.number] = Number(o.sequence);
  });
  assert.strictEqual(new Set(Object.values(numbers)).size, Object.values(numbers).length, 'every number is held once when the requests are done');
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

test('an assembly with a change is numbered 1, 2, 3 in the order of the tree, and a line that has its number already is left alone', () => {
  const s = four();
  s.addItems([{ id: '9', number: 'N', quantity: '1' }], S.ROOT, uidOf(s, 'R'));   // P Q N R S, from 10 20 30 40
  const r = after(s);
  assert.strictEqual(r.order, 'PQNRS');
  assert.deepStrictEqual(r.plan.operations.filter((o) => o.op === 'add').map((o) => o.sequence), ['3'], 'N is line 3');
  assert.strictEqual(r.plan.operations.find((o) => o.op === 'renumber' && o.number === 'S').sequence, '5', 'S ends at 5');
  const tidy = () => S.create({ ebom: EBOM, mbom: S.mapByNumber({ number: 'TOP-M', itemId: 'i0', children: ['P', 'Q', 'R', 'S'].map((n, i) => (
    { number: n, quantity: '1', itemId: 'i' + n, edgeId: 'e' + n, sequence: String(i + 1), children: [] })) }, EBOM) });
  const end = tidy();
  end.addItems([{ id: '9', number: 'N', quantity: '1' }], S.ROOT, '');   // appended to lines 1 to 4
  const ops = plan(end).operations;
  assert.deepStrictEqual(ops.map((o) => o.op + o.sequence), ['add5'], 'an appended line is only added, as line 5');
  const middle = tidy();
  middle.addItems([{ id: '9', number: 'N', quantity: '1' }], S.ROOT, uidOf(middle, 'R'));   // P Q N R S: lines 1 and 2 are left alone
  assert.deepStrictEqual(plan(middle).operations.filter((o) => o.op === 'renumber').map((o) => o.number + o.sequence), ['S5', 'R4'], 'shifted from the last one up, so none waits for a number');
});

test('lines that swap numbers each go straight to their own, in one request', () => {
  const s = S.create({ ebom: EBOM, mbom: S.mapByNumber({ number: 'TOP-M', itemId: 'i0', children: ['P', 'Q'].map((n, i) => (
    { number: n, quantity: '1', itemId: 'i' + n, edgeId: 'e' + n, sequence: String(i + 1), children: [] })) }, EBOM) });
  s.move([uidOf(s, 'Q')], S.ROOT, uidOf(s, 'P'));   // Q P: P takes 2 which Q holds, and Q takes 1 which P holds
  const ops = plan(s).operations;
  assert.deepStrictEqual(ops.map((o) => [o.number, o.from_sequence, o.sequence].join(':')).sort(), ['P:1:2', 'Q:2:1']);
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

test('a renumber asked for gives the lines of the assembly their places, one request for each line that has another number', () => {
  const s = S.create({ ebom: EBOM, mbom: S.mapByNumber({ number: 'TOP-M', itemId: 'i0', children: [['P', '1'], ['Q', '2'], ['R', '3'], ['S', '8']].map((n) => (
    { number: n[0], quantity: '1', itemId: 'i' + n[0], edgeId: 'e' + n[0], sequence: n[1], children: [] })) }, EBOM) });
  assert.deepStrictEqual(plan(s).operations, [], 'nothing changed, nothing to send');
  s.renumber();
  assert.deepStrictEqual(plan(s).operations.map((o) => [o.op, o.number, o.from_sequence, o.sequence].join(':')), ['renumber:S:8:4']);
});

test('a number given to a line is the number it is sent with, and the others keep theirs', () => {
  const s = four();   // P 10, Q 20, R 30, S 40 as Fusion Manage has them
  const shown = {};
  s.root().children.forEach((c) => { shown[c.uid] = c.sequence; });
  s.setNumber(uidOf(s, 'S'), '55', shown);
  assert.deepStrictEqual(plan(s).operations.map((o) => [o.op, o.number, o.from_sequence, o.sequence].join(':')), ['renumber:S:40:55']);
  const t = four();
  const shownT = {};
  t.root().children.forEach((c) => { shownT[c.uid] = c.sequence; });
  t.setNumber(uidOf(t, 'P'), '25', shownT);   // P goes between Q (20) and R (30)
  assert.strictEqual(t.root().children.map((c) => c.number).join(''), 'QPRS');
  assert.deepStrictEqual(plan(t).operations.map((o) => [o.op, o.number, o.from_sequence, o.sequence].join(':')), ['renumber:P:10:25']);
  const added = four();
  const shownA = {};
  added.root().children.forEach((c) => { shownA[c.uid] = c.sequence; });
  added.setNumber(uidOf(added, 'S'), '100', shownA);
  added.addItems([{ id: '9', number: 'N', quantity: '1' }], S.ROOT, '');
  assert.strictEqual(plan(added).operations.find((o) => o.op === 'add').sequence, '101', 'a line added after it is numbered above it');
});

// TOP-M as Fusion Manage has it: A (line 1, with A1 and A2 under it, quantity 2), B (line 2, with B1), C (line 8)
const withSubAssemblies = () => S.create({ ebom: EBOM, mbom: S.mapByNumber({ number: 'TOP-M', itemId: 'i0', children: [
  { number: 'A', quantity: '2', itemId: 'iA', edgeId: 'eA', sequence: '1', children: [
    { number: 'A1', quantity: '1', itemId: 'iA1', edgeId: 'eA1', sequence: '1', children: [] }, { number: 'A2', quantity: '1', itemId: 'iA2', edgeId: 'eA2', sequence: '2', children: [] }] },
  { number: 'B', quantity: '1', itemId: 'iB', edgeId: 'eB', sequence: '2', children: [{ number: 'B1', quantity: '1', itemId: 'iB1', edgeId: 'eB1', sequence: '1', children: [] }] },
  { number: 'C', quantity: '1', itemId: 'iC', edgeId: 'eC', sequence: '8', children: [] }] }, EBOM) });

test('quick add over an MBOM that has sub-assemblies keeps their lines, so nothing is removed or added again; only a number that is not its place is sent', () => {
  const s = withSubAssemblies();
  s.matchEbom();
  assert.strictEqual(s.root().children.map((c) => c.number).join(), 'A,B,C');
  assert.strictEqual(s.root().children[0].edgeId, 'eA', 'a line that is there stays that line');
  assert.strictEqual(s.root().children[0].children[0].edgeId, 'eA1', 'and so do the lines under it');
  const p = plan(s);
  assert.deepStrictEqual(p.problems, []);
  assert.ok(!p.operations.some((o) => o.op === 'add' || o.op === 'remove'), 'no line is added or removed: ' + JSON.stringify(p.operations));
  assert.deepStrictEqual(JSON.parse(JSON.stringify(p.operations)), []);
});

test('a line removed and added again keeps the number and the line id it had, so its request can name the line', () => {
  const s = withSubAssemblies();
  const c = s.root().children.find((n) => n.number === 'C');
  s.remove([c.uid]);
  s.addFromEbom(['0.2'], S.ROOT, '', true);   // C of the EBOM
  s.setQuantity(s.root().children.find((n) => n.number === 'C').uid, '3');
  const ops = plan(s).operations;
  assert.deepStrictEqual(ops.map((o) => [o.op, o.number, o.sequence, o.edge].join(':')), ['update:C:8:eC']);
  const t = withSubAssemblies();
  const b = t.root().children.find((n) => n.number === 'B');
  t.remove([b.uid]);
  t.addFromEbom(['0.1'], S.ROOT, t.root().children[0].uid, true);   // B again, now before A
  const moved = plan(t).operations;
  assert.ok(!moved.some((o) => o.op === 'add' && o.parent === 'B'), 'B keeps its own lines: B1 is not added to it again: ' + JSON.stringify(moved));
  assert.ok(moved.filter((o) => o.op === 'renumber').every((o) => o.edge && o.from_sequence !== ''), 'every renumber names the line it changes');
});

test('after a quantity of an assembly is split, its own lines can still be edited and published', () => {
  const s = read();   // A (x2) [A1, A2]
  const a = s.root().children.find((c) => c.number === 'A');
  const b = s.root().children.find((c) => c.number === 'B');
  s.split(a.uid, b.uid, '1');
  s.remove([a.children[0].uid]);
  const p = plan(s);
  assert.deepStrictEqual(p.problems, [], 'the copy has no lines of its own and is not a second bill of materials');
  assert.ok(p.operations.some((o) => o.op === 'remove' && o.number === 'A1'));
  assert.ok(p.operations.some((o) => o.op === 'add' && o.parent === 'B' && o.number === 'A'));
});
