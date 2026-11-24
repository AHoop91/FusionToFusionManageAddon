// The structure of a manufacturing bill of materials: its edits, undo and redo, and how it differs from the EBOM and from the MBOM as read.
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { dataWindow } = require('./helpers');

const S = dataWindow().mbomStructure;
const failsWith = (key) => (error) => error.key === key;   // an edit that cannot be done says why by a key; the viewer words it
const plain = (x) => JSON.parse(JSON.stringify(x));   // the scripts run in a window of their own: arrays are compared as data
const row = (level, number, quantity, name) => ({ level: level, item_number: number, name: name || number + ' name', quantity: quantity || '1' });
// TOP: A (x2) [A1, A2], B [B1], C
const ROWS = [row(0, 'A', '2'), row(1, 'A1'), row(1, 'A2'), row(0, 'B'), row(1, 'B1'), row(0, 'C')];
const EBOM = S.ebomFromRows(ROWS, { item_number: 'TOP', name: 'Top' });

// A structure whose MBOM was read with the given lines (``{number, quantity, children}``), mapped to the EBOM by item number.
const line = (number, quantity, children) => ({ number: number, quantity: quantity, source: '', itemId: 'i' + number, edgeId: 'e', children: children || [] });
const fromRead = (ebom, children) => S.create({ ebom: ebom, mbom: S.mapByNumber({ number: 'TOP', children: children }, ebom) });

function fresh(options) {
  const s = S.create(Object.assign({ ebom: EBOM, phantom: true }, options || {}));
  const at = (...numbers) => {   // the uid of the line reached by item numbers from the top
    let node = s.root();
    numbers.forEach((n) => { node = node.children.find((c) => c.number === n); assert.ok(node, n + ' is not there'); });
    return node.uid;
  };
  const outline = (node) => (node || s.root()).children.map((c) => c.children.length ? c.number + '[' + outline(c) + ']' : c.number).join(',');
  return { s: s, at: at, outline: outline };
}

test('the EBOM is read from rows by level, with positions as keys', () => {
  assert.strictEqual(EBOM.number, 'TOP');
  assert.deepStrictEqual(plain(EBOM.children.map((c) => c.key)), ['0.0', '0.1', '0.2']);
  assert.strictEqual(EBOM.children[0].children[1].key, '0.0.1');
  assert.strictEqual(EBOM.children[0].quantity, '2');
});

test('a new MBOM starts as a copy of the EBOM, every line mapped to its EBOM line', () => {
  const { s, outline } = fresh();
  assert.strictEqual(outline(), 'A[A1,A2],B[B1],C');
  assert.strictEqual(s.root().children[0].source, '0.0');
  assert.strictEqual(s.root().children[0].quantity, '2');
});

test('moving a line to another assembly, and reordering under one', () => {
  const { s, at, outline } = fresh();
  s.move([at('A', 'A1')], at('B'), '');
  assert.strictEqual(outline(), 'A[A2],B[B1,A1],C');
  s.move([at('B', 'A1')], at('B'), at('B', 'B1'));
  assert.strictEqual(outline(), 'A[A2],B[A1,B1],C');
  s.move([at('C')], S.ROOT, at('A'));
  assert.strictEqual(outline(), 'C,A[A2],B[A1,B1]');
});

test('any line, even a part with no lines of its own, takes lines dropped on it, so a BOM can be built under it', () => {
  const { s, at, outline } = fresh();
  s.move([at('B')], at('C'), '');
  assert.strictEqual(outline(), 'A[A1,A2],C[B[B1]]');
  s.addItems([{ id: '9', number: 'X1' }], at('C', 'B', 'B1'), '');
  assert.strictEqual(outline(), 'A[A1,A2],C[B[B1[X1]]]');
});

test('a line cannot go inside itself or before a line that is not beside it', () => {
  const { s, at, outline } = fresh();
  assert.throws(() => s.move([at('A')], at('A', 'A1'), ''), failsWith('inside_itself'));
  assert.throws(() => s.move([at('A')], at('A'), ''), failsWith('inside_itself'));
  assert.throws(() => s.move([at('C')], at('B'), at('A')), failsWith('before_not_under'));
  assert.strictEqual(outline(), 'A[A1,A2],B[B1],C', 'a refused edit changes nothing');
  assert.strictEqual(s.canUndo(), false);
});

test('moving a line and the assembly it is in moves them together', () => {
  const { s, at, outline } = fresh();
  s.move([at('A'), at('A', 'A1')], at('B'), '');
  assert.strictEqual(outline(), 'B[B1,A[A1,A2]],C');
});

test('a phantom assembly can take lines in as it is made, and needs a free item number and the setting', () => {
  const { s, at, outline } = fresh();
  const id = s.createAssembly('phantom', S.ROOT, at('A'), { number: 'PH-1', name: 'Phantom' }, [at('B'), at('C')]);
  assert.strictEqual(outline(), 'PH-1[B[B1],C],A[A1,A2]');
  assert.strictEqual(s.find(id).kind, 'phantom');
  assert.strictEqual(s.find(id).isNew, true);
  assert.throws(() => s.createAssembly('phantom', S.ROOT, '', { number: 'ph-1' }), failsWith('number_used'));
  assert.throws(() => s.createAssembly('assembly', S.ROOT, '', { number: '' }), failsWith('needs_number'));
  assert.throws(() => fresh({ phantom: false }).s.createAssembly('phantom', S.ROOT, '', { number: 'P' }), failsWith('phantom_needs_settings'));
  fresh({ phantom: false }).s.createAssembly('assembly', S.ROOT, '', { number: 'P' });
});

test('adopting the line the new assembly goes before puts it where that line was', () => {
  const { s, at, outline } = fresh();
  s.createAssembly('assembly', S.ROOT, at('B'), { number: 'X' }, [at('B')]);
  assert.strictEqual(outline(), 'A[A1,A2],X[B[B1]],C');
});

test('adding items from Fusion Manage and from the EBOM, and removing lines', () => {
  const { s, at, outline } = fresh();
  s.addItems([{ id: '9', number: 'X1', name: 'Extra', quantity: '4' }], at('B'), '');
  assert.strictEqual(outline(), 'A[A1,A2],B[B1,X1],C');
  assert.strictEqual(s.find(at('B', 'X1')).itemId, '9');
  s.remove([at('B', 'X1'), at('A')]);
  assert.strictEqual(outline(), 'B[B1],C');
  const [keyed] = s.addFromEbom(['0.0'], S.ROOT, '', true);
  assert.strictEqual(outline(), 'B[B1],C,A[A1,A2]');
  assert.strictEqual(s.find(keyed).source, '0.0');
  assert.throws(() => s.remove([]), failsWith('nothing_selected'));
  assert.throws(() => s.addFromEbom(['9.9'], S.ROOT, '', false), failsWith('no_such_ebom'));
});

test('a quantity is a number above 0', () => {
  const { s, at } = fresh();
  s.setQuantity(at('C'), '2.50');
  assert.strictEqual(s.find(at('C')).quantity, '2.5');
  assert.throws(() => s.setQuantity(at('C'), '0'), failsWith('bad_quantity'));
  assert.throws(() => s.setQuantity(at('C'), 'x'), failsWith('bad_quantity'));
  assert.strictEqual(s.find(at('C')).quantity, '2.5');
});

test('undo and redo step back and forward, and a new edit drops what could be redone', () => {
  const { s, at, outline } = fresh();
  s.remove([at('C')]);
  s.move([at('B')], at('A'), '');
  assert.strictEqual(outline(), 'A[A1,A2,B[B1]]');
  s.undo();
  assert.strictEqual(outline(), 'A[A1,A2],B[B1]');
  s.undo();
  assert.strictEqual(outline(), 'A[A1,A2],B[B1],C');
  assert.strictEqual(s.canUndo(), false);
  s.redo();
  assert.strictEqual(outline(), 'A[A1,A2],B[B1]');
  s.remove([at('B')]);
  assert.strictEqual(s.canRedo(), false);
  assert.strictEqual(outline(), 'A[A1,A2]');
});

test('compare says what the MBOM lacks, what has another quantity, and what sits under another assembly', () => {
  const { s, at } = fresh();
  s.remove([at('C')]);
  s.setQuantity(at('A'), '3');
  s.move([at('B', 'B1')], at('A'), '');
  let c = s.compare();
  assert.strictEqual(c.ebom['0.2'].missing, true);
  assert.deepStrictEqual(plain(c.ebom['0.0']), { missing: false, quantity: true, exceeded: true, moved: false, matched: false, bought: false, blocked: false });
  assert.deepStrictEqual(plain(c.ebom['0.1.0']), { missing: false, quantity: false, exceeded: false, moved: true, matched: true, bought: false, blocked: false });
  assert.deepStrictEqual(plain(c.ebom['0.0.0']), { missing: false, quantity: false, exceeded: false, moved: false, matched: true, bought: false, blocked: false });
  assert.strictEqual(c.mbom[at('A')], 'mapped');
  s.createAssembly('phantom', S.ROOT, '', { number: 'PH' }, [at('A', 'A1')]);
  c = s.compare();
  assert.strictEqual(c.mbom[at('PH')], 'mfg');
  assert.strictEqual(c.ebom['0.0.0'].moved, true, 'A1 is under a phantom under the MBOM top now, not under A');
  s.move([at('PH')], at('A'), '');
  assert.strictEqual(s.compare().ebom['0.0.0'].moved, false, 'a phantom inside A does not take A1 out of A');
});

test('changes say what is new, moved, reordered or has another quantity since the MBOM was read, and what is gone', () => {
  const read = { number: 'TOP', name: 'Top', itemId: '1', children: [
    { number: 'A', source: '0.0', quantity: '2', itemId: '2', children: [{ number: 'A1', source: '0.0.0', itemId: '3' }, { number: 'A2', source: '0.0.1', itemId: '4' }] },
    { number: 'B', source: '0.1', itemId: '5', children: [] },
    { number: 'C', source: '0.2', itemId: '6' },
  ] };
  const { s, at } = fresh({ mbom: read });
  assert.deepStrictEqual(plain(s.changes().changes), {});
  assert.strictEqual(s.root().children[0].isNew, false);
  s.move([at('A', 'A1')], at('B'), '');
  s.setQuantity(at('C'), '5');
  s.createAssembly('assembly', S.ROOT, '', { number: 'NEW' });
  s.remove([at('A')]);
  const result = s.changes();
  assert.strictEqual(result.changes[at('B', 'A1')].moved, true);
  assert.strictEqual(result.changes[at('C')].quantity, true);
  assert.strictEqual(result.changes[at('C')].oldQuantity, '1');
  assert.strictEqual(result.changes[at('NEW')].new, true);
  assert.deepStrictEqual(plain(result.removed.map((r) => r.number)), ['A'], 'A2 went with A: only A is listed');
  assert.strictEqual(result.removed[0].cascade, 1);
});

test('search finds lines by number or name', () => {
  const { s, at } = fresh();
  assert.deepStrictEqual(plain(s.search('a1')), [at('A', 'A1')]);
  assert.deepStrictEqual(plain(s.search('B1 NAME')), [at('B', 'B1')]);
  assert.deepStrictEqual(plain(s.search('  ')), []);
});

const READ = () => ({ number: 'TOP', name: 'Top', itemId: '1', children: [
  { number: 'A', source: '0.0', quantity: '2', itemId: '2', edgeId: 'e2', children: [] },
  { number: 'B', source: '0.1', itemId: '5', edgeId: 'e5', children: [] },
  { number: 'C', source: '0.2', itemId: '6', edgeId: 'e6', children: [] },
  { number: 'D', source: '', itemId: '7', edgeId: 'e7', children: [] },
] });

test('a read line is built field by field: a blank quantity is 1, a uid read is ignored and an edge id is kept', () => {
  const read = READ();
  read.children[1].uid = 'x'; read.children[1].quantity = undefined; read.children[1].junk = 1;
  const { s } = fresh({ mbom: read });
  const b = s.root().children[1];
  assert.notStrictEqual(b.uid, 'x');
  assert.strictEqual(b.quantity, '1');
  assert.strictEqual(b.edgeId, 'e5');
  assert.strictEqual(b.junk, undefined);
  assert.strictEqual(b.isNew, false);
});

test('a blank EBOM quantity is 1, and the lines of a component add up against the EBOM quantity', () => {
  const rows = [row(0, 'A', ''), row(0, 'B', '2')];
  rows[0].quantity = '';
  const ebom = S.ebomFromRows(rows, { item_number: 'TOP' });
  assert.strictEqual(ebom.children[0].quantity, '1');
  const s = S.create({ ebom: ebom });
  assert.strictEqual(s.compare().ebom['0.0'].quantity, false);
  const two = fromRead(ebom, [line('A', '1'), line('B', '2'), line('B', '2')]);
  assert.strictEqual(two.compare().ebom['0.1'].quantity, true, 'two lines of 2 are 4, not 2');
  two.setQuantity(two.root().children[2].uid, '1');
  two.setQuantity(two.root().children[1].uid, '1');
  assert.strictEqual(two.compare().ebom['0.1'].quantity, false, '1 and 1 are 2');
});

test('the EBOM carries the component id', () => {
  const ebom = S.ebomFromRows([Object.assign(row(0, 'A'), { id: 'cA' })], { item_number: 'TOP' });
  assert.strictEqual(ebom.children[0].componentId, 'cA');
  assert.strictEqual(S.create({ ebom: ebom }).root().children[0].componentId, 'cA');
});

test('a line that is moving may name itself as the one to go before; a move that changes nothing is no step; ids count once, in tree order', () => {
  const { s, at, outline } = fresh();
  s.move([at('A'), at('B')], S.ROOT, at('A'));
  assert.strictEqual(outline(), 'A[A1,A2],B[B1],C');
  assert.strictEqual(s.canUndo(), false);
  s.move([at('B'), at('A'), at('B')], S.ROOT, '');
  assert.strictEqual(outline(), 'C,A[A1,A2],B[B1]');
  s.undo();
  s.move([at('B'), at('A')], S.ROOT, at('A'));
  assert.strictEqual(outline(), 'A[A1,A2],B[B1],C', 'before the next line that stays: A and B are already there');
});

test('removing the first of three lines does not make the other two reordered', () => {
  const { s, at } = fresh({ mbom: READ() });
  s.remove([at('A')]);
  const c = s.changes();
  assert.deepStrictEqual(plain(Object.keys(c.changes)), []);
  assert.deepStrictEqual(plain(c.removed.map((r) => [r.number, r.edgeId, r.cascade])), [['A', 'e2', 0]]);
  s.undo();
  s.move([at('C')], S.ROOT, at('A'));
  const r = s.changes().changes;
  assert.deepStrictEqual(plain(Object.keys(r)), [at('C')], 'only the line that was moved is reordered');
  assert.strictEqual(r[at('C')].reordered, true);
  assert.strictEqual(r[at('C')].edgeId, 'e6');
});

test('a line can be moved and have another quantity at once, and both are said', () => {
  const { s, at } = fresh({ mbom: READ() });
  s.createAssembly('assembly', S.ROOT, '', { number: 'X' });
  s.move([at('C')], at('X'), '');
  s.setQuantity(at('X', 'C'), '9');
  const flags = s.changes().changes[at('X', 'C')];
  assert.strictEqual(flags.moved, true);
  assert.strictEqual(flags.quantity, true);
  assert.strictEqual(flags.oldParent, S.ROOT);
});

test('the history keeps 50 steps', () => {
  const { s, at } = fresh();
  for (let i = 2; i < 70; i++) s.setQuantity(at('C'), String(i));
  let steps = 0;
  while (s.canUndo()) { s.undo(); steps++; }
  assert.strictEqual(steps, 50);
});

test('the MBOM read is mapped to the EBOM by item number, so one that mirrors it has nothing to say', () => {
  const rows = [row(0, 'A', '2'), row(1, 'P'), row(0, 'B'), row(1, 'P'), row(0, 'Q')];
  const ebom = S.ebomFromRows(rows, { item_number: 'TOP' });
  const node = (number, quantity, children) => ({ number: number, quantity: quantity || '1', children: children || [] });
  // siblings in another order, a number under two parents, and a number in another case
  const read = node('TOP', '', [node('q'), node('B', '1', [node('P')]), node('A', '2', [node('P')])]);
  const mapped = S.mapByNumber(read, ebom);
  assert.deepStrictEqual(plain(mapped.children.map((c) => c.source)), ['0.2', '0.1', '0.0']);
  assert.deepStrictEqual(plain(mapped.children.slice(1).map((c) => c.children[0].source)), ['0.1.0', '0.0.0']);
  assert.strictEqual(read.children[0].source, undefined, 'the tree given is left as it is');
  const s = S.create({ ebom: ebom, mbom: mapped });
  Object.values(s.compare().ebom).forEach((state) => assert.deepStrictEqual(plain(state), { missing: false, quantity: false, exceeded: false, moved: false, matched: true, bought: false, blocked: false }));
  const none = S.mapByNumber(node('TOP', '', [node(''), node('nope')]), ebom);
  assert.deepStrictEqual(plain(none.children.map((c) => c.source)), ['', '']);
});

test('a drop on a line is a place: before, after or into', () => {
  const { s, at } = fresh();
  assert.deepStrictEqual(plain(s.position('before', at('B'))), { parentId: S.ROOT, before: at('B') });
  assert.deepStrictEqual(plain(s.position('after', at('B'))), { parentId: S.ROOT, before: at('C') });
  assert.deepStrictEqual(plain(s.position('after', at('C'))), { parentId: S.ROOT, before: '' });
  assert.deepStrictEqual(plain(s.position('after', at('A', 'A2'))), { parentId: at('A'), before: '' });
  assert.deepStrictEqual(plain(s.position('into', at('A'))), { parentId: at('A'), before: '' });
  assert.deepStrictEqual(plain(s.position('into', S.ROOT)), { parentId: S.ROOT, before: '' });
  assert.throws(() => s.position('before', S.ROOT), failsWith('no_place_root'));
  assert.throws(() => s.position('after', S.ROOT), failsWith('no_place_root'));
});

test('the zone of a drop comes from where in the line the pointer is', () => {
  assert.strictEqual(S.zoneOf(2, 32, true), 'before');
  assert.strictEqual(S.zoneOf(16, 32, true), 'into');
  assert.strictEqual(S.zoneOf(30, 32, true), 'after');
  assert.strictEqual(S.zoneOf(10, 32, false), 'before');
  assert.strictEqual(S.zoneOf(20, 32, false), 'after');
});

test('lines only Fusion Manage has, which the compared rows hold, are not in the EBOM', () => {
  const rows = [row(0, 'A'), Object.assign(row(1, 'X'), { status: 'extra' }), row(0, 'B'), Object.assign(row(0, 'Y'), { status: 'extra' })];
  const ebom = S.ebomFromRows(rows, { item_number: 'TOP' });
  assert.deepStrictEqual(plain(ebom.children.map((c) => c.number)), ['A', 'B']);
  assert.deepStrictEqual(plain(ebom.children.map((c) => c.key)), ['0.0', '0.1']);
  assert.strictEqual(ebom.children[0].children.length, 0);
});

test('a quantity is plain decimal digits: no hex, exponent or sign, and it is kept as the plain decimal', () => {
  const { s, at } = fresh();
  ['0x10', '1e3', '-1', '+2', '1,5', ' ', '.5e1', 'Infinity', '1234567890123'].forEach((text) => {
    assert.throws(() => s.setQuantity(at('C'), text), failsWith('bad_quantity'), text);
  });
  s.setQuantity(at('C'), ' 007.500 ');
  assert.strictEqual(s.find(at('C')).quantity, '7.5');
  s.addItems([{ id: '1', number: 'Q', quantity: '2.0' }], S.ROOT, '');
  assert.strictEqual(s.find(at('Q')).quantity, '2');
});

test('quantities that add up to the EBOM quantity within rounding are not flagged', () => {
  const rows = [row(0, 'A', '0.3')];
  const s = fromRead(S.ebomFromRows(rows, { item_number: 'TOP' }), [line('A', '0.1'), line('A', '0.1'), line('A', '0.1')]);
  assert.strictEqual(s.compare().ebom['0.0'].quantity, false, '0.1 + 0.1 + 0.1 is 0.30000000000000004');
});

test('a few thousand lines build, edit and compare quickly, and the removal of one is not slow either', () => {
  const rows = [];
  for (let i = 0; i < 3000; i++) { rows.push(row(0, 'P' + i, '1')); if (i % 10 === 0) rows.push(row(1, 'Q' + i, '1')); }
  const ebom = S.ebomFromRows(rows, { item_number: 'TOP' });
  const start = Date.now();
  const read = { number: 'TOP', children: rows.filter((r) => r.level === 0).map((r) => ({ number: r.item_number, quantity: '1', source: '', itemId: r.item_number, edgeId: 'e', children: [] })) };
  const s = S.create({ ebom: ebom, mbom: S.mapByNumber(read, ebom) });
  s.remove([s.root().children[0].uid]);
  s.move([s.root().children[5].uid], S.ROOT, s.root().children[2000].uid);
  s.compare();
  const c = s.changes();
  assert.strictEqual(c.removed.length, 1);
  assert.ok(Date.now() - start < 3000, 'took ' + (Date.now() - start) + ' ms');
});

test('an EBOM line is matched when the lines made from it, in every assembly, add up to its quantity, and an assembly when everything under it is', () => {
  // TOP: P1 [S (x2)], P2 [S (x2)], Q (x4): S is in two places, Q is one line of 4
  const rows = [row(0, 'P1'), row(1, 'S', '2'), row(0, 'P2'), row(1, 'S', '2'), row(0, 'Q', '4')];
  const ebom = S.ebomFromRows(rows, { item_number: 'TOP' });
  const first = S.create({ ebom: ebom });
  assert.strictEqual(first.compare().ebom['0.0'].matched, true);
  assert.strictEqual(first.compare().ebom['0.2'].matched, true);
  first.setQuantity(first.root().children[2].uid, '3');
  assert.strictEqual(first.compare().ebom['0.2'].matched, false, 'part covered: stays normal, with the quantity flag');
  assert.strictEqual(first.compare().ebom['0.2'].quantity, true);
  // as read, with a second line of Q under P1: 3 + 3 = 6 is over 4
  const s = fromRead(ebom, [line('P1', '1', [line('S', '2'), line('Q', '3')]), line('P2', '1', [line('S', '2')]), line('Q', '3')]);
  const at = (...n) => { let node = s.root(); n.forEach((x) => { node = node.children.find((c) => c.number === x); }); return node.uid; };
  const state = (key) => s.compare().ebom[key];
  assert.strictEqual(state('0.2').matched, false);
  assert.strictEqual(state('0.2').quantity, true, 'over covered');
  s.setQuantity(at('P1', 'Q'), '1');   // 3 + 1 = 4: split over two assemblies
  assert.strictEqual(state('0.2').matched, true);
  assert.strictEqual(state('0.2').quantity, false);
  s.setQuantity(at('P1', 'S'), '1');
  assert.strictEqual(state('0.0.0').matched, false);
  assert.strictEqual(state('0.0').matched, false, 'an assembly is not matched while a line under it is not');
  assert.strictEqual(state('0.1').matched, true, 'the other S is still matched');
  s.remove([at('P2', 'S')]);
  assert.strictEqual(state('0.1.0').missing, true);
  assert.strictEqual(state('0.1').matched, false);
  assert.strictEqual(state('0.1.0').matched, false);
});

test('the same component in two EBOM places is matched place by place, and summed over copies of one place', () => {
  const rows = [row(0, 'P1'), row(1, 'S', '2'), row(0, 'P2'), row(1, 'S', '2')];
  const ebom = S.ebomFromRows(rows, { item_number: 'TOP' });
  const s = S.create({ ebom: ebom });
  const p1 = s.root().children[0].uid;
  const p2 = s.root().children[1].uid;
  s.move([s.find(p2).children[0].uid], p1, '');   // both S now under P1: each still stands for its own EBOM line
  const c = s.compare().ebom;
  assert.strictEqual(c['0.0.0'].matched, true);
  assert.strictEqual(c['0.1.0'].matched, true);
  assert.strictEqual(c['0.1.0'].moved, true);
  const twice = fromRead(ebom, [line('P1', '1', [line('S', '2'), line('S', '2'), line('S', '2')]), line('P2', '1')]);   // a second line made from 0.0.0: 2 + 2 against 2
  assert.strictEqual(twice.compare().ebom['0.0.0'].matched, false);
  assert.strictEqual(twice.compare().ebom['0.0.0'].quantity, true);
});

test('the EBOM carries the sequence of each line', () => {
  const ebom = S.ebomFromRows([Object.assign(row(0, 'A'), { sequence: 10 }), row(0, 'B')], { item_number: 'TOP' });
  assert.deepStrictEqual(plain(ebom.children.map((c) => c.sequence)), ['10', '']);
});

test('adding an EBOM line that is all in the MBOM already is refused, and the tree stays as it was', () => {
  const { s, at, outline } = fresh();
  const before = outline();
  assert.throws(() => s.addFromEbom(['0.1'], S.ROOT, '', false), failsWith('would_exceed'));
  assert.throws(() => s.addFromEbom(['0.0'], S.ROOT, '', true), failsWith('would_exceed'));
  assert.strictEqual(outline(), before);
  s.remove([at('B')]);
  s.addFromEbom(['0.1'], S.ROOT, '', true);
  assert.strictEqual(outline(), before.replace('B[B1],C', 'C,B[B1]'));
});

test('an assembly a purchased item stands for is matched, with bought set, though nothing under it is in the MBOM', () => {
  const ebom = S.ebomFromRows([row(0, 'P1'), row(1, 'S')], { item_number: 'TOP' });
  const s = S.create({ ebom: ebom });
  s.remove([s.root().children[0].uid]);
  assert.strictEqual(s.compare().ebom['0.0'].matched, false, 'gone from the MBOM');
  s.addItems([{ id: '9', number: 'P1-B', quantity: '1', source: '0.0' }], S.ROOT, '');
  const c = s.compare().ebom;
  assert.strictEqual(c['0.0'].matched, true);
  assert.strictEqual(c['0.0'].bought, true);
  assert.strictEqual(c['0.0.0'].missing, true, 'what is under it is not in the MBOM');
  assert.strictEqual(c['0.0.0'].bought, false);
  s.setQuantity(s.root().children[0].uid, '2');
  assert.strictEqual(s.compare().ebom['0.0'].matched, false, 'only when all its quantity is covered');
});

test('a line read from Fusion Manage that is an EBOM line\'s number and the bought suffix is that line\'s bought version: mapped to it, bought, matched', () => {
  const ebom = S.ebomFromRows([row(0, 'P1', '4'), row(1, 'S'), row(0, 'Q')], { item_number: 'TOP' });
  const read = (suffix) => S.mapByNumber({ number: 'TOP', children: [line('P1-B', '4'), line('Q', '1')] }, ebom, suffix);
  assert.strictEqual(read('').children[0].source, '', 'with no suffix it is a line with no EBOM line');
  const mapped = read('-B');
  assert.strictEqual(mapped.children[0].source, '0.0');
  assert.strictEqual(mapped.children[0].bought, true);
  assert.strictEqual(mapped.children[1].bought, false, 'a line with an EBOM line\'s own number is not');
  const s = S.create({ ebom: ebom, mbom: mapped });
  const c = s.compare();
  assert.strictEqual(c.ebom['0.0'].matched, true, 'it covers its EBOM line, which has lines of its own under it');
  assert.strictEqual(c.ebom['0.0'].bought, true);
  assert.strictEqual(c.mbom[s.root().children[0].uid], 'mapped');
  assert.deepStrictEqual(plain(s.changes().changes), {}, 'nothing changed since it was read');
});

test('a line with the EBOM line\'s own number wins over its bought version, and the bought version of a line is taken once', () => {
  const ebom = S.ebomFromRows([row(0, 'P1')], { item_number: 'TOP' });
  const both = S.mapByNumber({ number: 'TOP', children: [line('P1-B', '1'), line('P1', '1')] }, ebom, '-B');
  assert.deepStrictEqual(plain(both.children.map((c) => [c.source, c.bought])), [['', false], ['0.0', false]]);
  const twice = S.mapByNumber({ number: 'TOP', children: [line('P1-B', '1'), line('P1-B', '1')] }, ebom, '-B');
  assert.deepStrictEqual(plain(twice.children.map((c) => c.source)), ['0.0', '']);
});

test('adding an EBOM line the MBOM holds some of adds the rest to its line under the same assembly, else as a line of its own; with none left it is refused', () => {
  const ebom = S.ebomFromRows([row(0, 'P', '4'), row(0, 'Q', '2'), row(0, 'R', '4'), row(1, 'S', '1')], { item_number: 'TOP' });
  const s = S.create({ ebom: ebom, mbom: S.mapByNumber({ number: 'TOP', children: [line('P', '1'), line('Q', '2'), line('R', '1', [line('S', '1')])] }, ebom) });
  const before = s.root().children.length;
  const [uid] = s.addFromEbom(['0.0'], S.ROOT, '', false);
  assert.strictEqual(s.root().children.length, before, 'no second line: it went to the one under the same assembly');
  assert.strictEqual(s.find(uid).quantity, '4');
  assert.strictEqual(s.compare().ebom['0.0'].matched, true);
  const [other] = s.addFromEbom(['0.2'], s.find(s.root().children[0].uid).uid, '', false);   // R into P: not its assembly
  assert.strictEqual(s.find(other).quantity, '3', 'under another assembly it is a line of its own, with the rest');
  assert.strictEqual(s.root().children.length, before);
  assert.throws(() => s.addFromEbom(['0.0'], S.ROOT, '', false), failsWith('would_exceed'));
  assert.throws(() => s.addFromEbom(['0.1'], S.ROOT, '', false), failsWith('would_exceed'));
});

test('a line removed and added again in the same edit stays the line it was, not new and not removed', () => {
  const { s, at } = fresh({ mbom: READ() });
  s.remove([at('C')]);
  s.addItems([{ id: '6', number: 'C' }], S.ROOT, at('D'));
  const c = s.changes();
  assert.deepStrictEqual(plain(c.removed), [], 'the line is still there');
  assert.deepStrictEqual(plain(Object.values(c.changes).filter((f) => f.new)), [], 'and it is not new');
  assert.deepStrictEqual(plain(Object.values(c.changes)), [], 'the same place and quantity: nothing to publish');
  s.remove([s.root().children.find((n) => n.number === 'C').uid]);
  s.addItems([{ id: '6', number: 'C', quantity: '3' }], S.ROOT, at('D'));
  const q = Object.values(s.changes().changes);
  assert.strictEqual(q.length, 1);
  assert.strictEqual(q[0].quantity, true, 'a different quantity is an update of the line it was');
  assert.strictEqual(q[0].edgeId, 'e6');
});

test('what is under a purchased part is blocked: not addable, and the structure refuses it', () => {
  const ebom = S.ebomFromRows([row(0, 'P1'), row(1, 'S'), row(2, 'S1'), row(0, 'Q')], { item_number: 'TOP' });
  const s = S.create({ ebom: ebom });
  s.remove([s.root().children[0].uid]);
  assert.strictEqual(s.compare().ebom['0.0.0'].blocked, false, 'not until a purchased part stands for P1');
  s.addItems([{ id: '9', number: 'P1-B', quantity: '1', source: '0.0' }], S.ROOT, '');
  const c = s.compare().ebom;
  assert.strictEqual(c['0.0'].blocked, false, 'the purchased line itself is matched, not blocked');
  assert.strictEqual(c['0.0.0'].blocked, true);
  assert.strictEqual(c['0.0.0.0'].blocked, true, 'every level under it');
  assert.strictEqual(c['0.1'].blocked, false);
  assert.throws(() => s.addFromEbom(['0.0.0'], S.ROOT, '', true), failsWith('under_purchased'));
  assert.throws(() => s.addFromEbom(['0.0.0.0'], S.ROOT, '', false), failsWith('under_purchased'));
});

test('quick add makes the MBOM a copy of the EBOM, one step that undo gives back', () => {
  const { s, outline } = fromReadFresh();
  assert.strictEqual(s.hasLines(), true);
  s.matchEbom();
  assert.strictEqual(outline(), 'A[A1,A2],B[B1],C');
  assert.strictEqual(s.root().children[0].quantity, '2');
  assert.strictEqual(s.root().children[0].source, '0.0');
  assert.strictEqual(s.compare().ebom['0.1'].matched, true, 'B and what is under it now match');
  s.undo();
  assert.strictEqual(outline(), 'OIL,C');
  assert.strictEqual(s.canUndo(), false, 'it was the one step');
});

test('quick add keeps a line that was there with the same number and nothing under it, and removes the rest', () => {
  const { s } = fromReadFresh();
  s.matchEbom();
  const { changes, removed } = s.changes();
  assert.deepStrictEqual(plain(removed.map((r) => r.number)), ['OIL']);   // C stayed the line it was; the others are new
  const c = s.root().children.find((n) => n.number === 'C');
  assert.strictEqual(changes[c.uid], undefined);
});

test('quick add on an MBOM with no lines needs no question, and one with an EBOM of no lines is refused', () => {
  const empty = S.create({ ebom: EBOM, mbom: { number: 'TOP', name: 'Top', itemId: '1', children: [] } });
  assert.strictEqual(empty.hasLines(), false);
  empty.matchEbom();
  assert.strictEqual(empty.root().children.length, 3);
  const none = S.create({ ebom: S.ebomFromRows([], { item_number: 'TOP' }), mbom: { number: 'TOP', children: [] } });
  assert.throws(() => none.matchEbom(), failsWith('no_such_ebom'));
});

function fromReadFresh() {
  const s = fromRead(EBOM, [line('OIL', '1'), line('C', '1')]);
  const outline = (node) => (node || s.root()).children.map((c) => c.children.length ? c.number + '[' + outline(c) + ']' : c.number).join(',');
  return { s: s, outline: outline };
}

test('renumber marks the assemblies whose lines are not numbered by their places, and is one step', () => {
  const s = S.create({ ebom: EBOM, mbom: S.mapByNumber({ number: 'TOP', itemId: 'i0', children: [
    { number: 'A', quantity: '2', itemId: 'iA', edgeId: 'eA', sequence: '1', children: [] },
    { number: 'B', quantity: '1', itemId: 'iB', edgeId: 'eB', sequence: '2', children: [] },
    { number: 'C', quantity: '1', itemId: 'iC', edgeId: 'eC', sequence: '8', children: [] }] }, EBOM) });
  assert.strictEqual(s.renumber(), 1);
  assert.strictEqual(s.root().renumber, true);
  assert.strictEqual(s.renumber(), 0, 'nothing is left to mark, so it is no second step');
  s.undo();
  assert.strictEqual(s.root().renumber, undefined, 'one undo takes it back');
  assert.strictEqual(s.canUndo(), false);
});

test('a line is given a number of its own: any whole number, the lines in the order of their numbers, and a taken or non-numeric one is refused', () => {
  const { s, at, outline } = fresh();
  const shown = () => { const out = {}; s.root().children.forEach((c, i) => { out[c.uid] = String(i + 1); }); return out; };   // A B C show 1 2 3
  s.setNumber(at('C'), '10', shown());
  assert.strictEqual(outline(), 'A[A1,A2],B[B1],C');
  assert.strictEqual(s.root().children[2].pin, '10');
  assert.strictEqual(s.root().children[0].pin, '1', 'the lines beside it keep the numbers they show');
  const now = { [at('A')]: '1', [at('B')]: '2', [at('C')]: '10' };
  assert.throws(() => s.setNumber(at('C'), '2', now), failsWith('number_taken'));
  ['0', '-1', '1.5', '', 'x', '1234567890'].forEach((bad) => assert.throws(() => s.setNumber(at('C'), bad, now), failsWith('bad_number'), bad));
  assert.throws(() => s.setNumber(S.ROOT, '1', now), failsWith('root_immutable'));
  s.setNumber(at('A'), '5', now);   // 5 goes between B (2) and C (10)
  assert.strictEqual(outline(), 'B[B1],A[A1,A2],C');
  assert.strictEqual(s.canUndo(), true);
  s.undo();
  assert.strictEqual(outline(), 'A[A1,A2],B[B1],C', 'each is one step');
  s.renumber();
  assert.strictEqual(s.root().children[2].pin, undefined, 'Automatic Renumber lets go of the numbers given');
});
