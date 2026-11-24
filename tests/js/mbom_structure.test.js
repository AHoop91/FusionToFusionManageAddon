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

test('a line cannot go inside itself, before itself, or under a part', () => {
  const { s, at, outline } = fresh();
  assert.throws(() => s.move([at('A')], at('A', 'A1'), ''), failsWith('inside_itself'));
  assert.throws(() => s.move([at('A')], at('A'), ''), failsWith('inside_itself'));
  assert.throws(() => s.move([at('B')], at('C'), ''), failsWith('not_assembly'));
  assert.throws(() => s.move([at('C')], at('B'), at('A')), failsWith('before_not_under'));
  assert.throws(() => s.copy([at('A')], at('A'), ''), failsWith('inside_itself'));
  assert.throws(() => s.copy([at('A')], at('A', 'A1'), ''), failsWith('inside_itself'));
  assert.strictEqual(outline(), 'A[A1,A2],B[B1],C', 'a refused edit changes nothing');
  assert.strictEqual(s.canUndo(), false);
});

test('moving a line and the assembly it is in moves them together', () => {
  const { s, at, outline } = fresh();
  s.move([at('A'), at('A', 'A1')], at('B'), '');
  assert.strictEqual(outline(), 'B[B1,A[A1,A2]],C');
});

test('copying reuses a component in another place, as a new line', () => {
  const { s, at, outline } = fresh();
  const [copy] = s.copy([at('C')], at('B'), '');
  assert.strictEqual(outline(), 'A[A1,A2],B[B1,C],C');
  assert.notStrictEqual(copy, at('C'));
  s.copy([at('A')], at('B'), '');
  assert.strictEqual(outline(), 'A[A1,A2],B[B1,C,A[A1,A2]],C');
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

test('splitting into an assembly that is there already joins the same item into one line and keeps the totals', () => {
  const { s, at, outline } = fresh();
  s.copy([at('A', 'A1')], at('B'), '');
  s.splitInto(at('A'), [at('A', 'A1')], at('B'));
  assert.strictEqual(outline(), 'A[A2],B[B1,A1],C');
  assert.strictEqual(s.find(at('B', 'A1')).quantity, '3', 'one A1 already under B, and two more: A is made twice and holds one each');
  assert.throws(() => s.splitInto(at('A'), [at('A', 'A2')], at('B')), failsWith('split_some'));
  assert.throws(() => s.splitInto(at('B'), [at('B', 'B1')], at('B')), failsWith('split_same'));
  assert.throws(() => s.splitInto(S.ROOT, [at('A')], at('B')), failsWith('split_root'));
  s.undo();
  assert.strictEqual(outline(), 'A[A1,A2],B[B1,A1],C');
  const nested = fresh();
  nested.s.copy([nested.at('B')], nested.at('A'), '');
  assert.throws(() => nested.s.splitInto(nested.at('A'), [nested.at('A', 'B')], nested.at('A', 'B')), failsWith('split_inside'));
});

test('splitting an assembly puts some of its lines in a new assembly next to it, with its quantity', () => {
  const { s, at, outline } = fresh();
  const id = s.split(at('A'), [at('A', 'A2')], 'phantom', { number: 'A-2' });
  assert.strictEqual(outline(), 'A[A1],A-2[A2],B[B1],C');
  assert.strictEqual(s.find(id).quantity, '2');
  const whole = fresh();
  assert.throws(() => whole.s.split(whole.at('A'), [], 'assembly', { number: 'Z' }), failsWith('split_some'));
  assert.throws(() => whole.s.split(whole.at('A'), [whole.at('A', 'A1'), whole.at('A', 'A2')], 'assembly', { number: 'Z' }), failsWith('split_some'));
  assert.throws(() => whole.s.split(whole.at('A'), [whole.at('B')], 'assembly', { number: 'Z' }), failsWith('split_direct'));
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
  assert.deepStrictEqual(plain(c.ebom['0.0']), { missing: false, quantity: true, exceeded: true, moved: false, matched: false });
  assert.deepStrictEqual(plain(c.ebom['0.1.0']), { missing: false, quantity: false, exceeded: false, moved: true, matched: true });
  assert.deepStrictEqual(plain(c.ebom['0.0.0']), { missing: false, quantity: false, exceeded: false, moved: false, matched: true });
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
  const b = s.root().children[1].uid;
  s.copy([b], S.ROOT, '');
  assert.strictEqual(s.compare().ebom['0.1'].quantity, true, 'two lines of 2 are 4, not 2');
  s.setQuantity(s.root().children[2].uid, '1');
  s.setQuantity(b, '1');
  assert.strictEqual(s.compare().ebom['0.1'].quantity, false, '1 and 1 are 2');
});

test('the EBOM carries the component id', () => {
  const ebom = S.ebomFromRows([Object.assign(row(0, 'A'), { id: 'cA' })], { item_number: 'TOP' });
  assert.strictEqual(ebom.children[0].componentId, 'cA');
  assert.strictEqual(S.create({ ebom: ebom }).root().children[0].componentId, 'cA');
});

test('copying a new assembly is refused, since the copy would carry the same item number', () => {
  const { s, at } = fresh();
  s.createAssembly('assembly', S.ROOT, '', { number: 'X' });
  assert.throws(() => s.copy([at('X')], S.ROOT, ''), failsWith('copy_new_assembly'));
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

test('splitting into an assembly made more than once keeps the totals, or is refused', () => {
  const { s, at, outline } = fresh();
  s.setQuantity(at('B'), '4');
  s.splitInto(at('A'), [at('A', 'A1')], at('B'));   // A is made 2 times, B 4: each A1 under A is half an A1 under B
  assert.strictEqual(outline(), 'A[A2],B[B1,A1],C');
  assert.strictEqual(s.find(at('B', 'A1')).quantity, '0.5');
  const odd = fresh();
  odd.s.setQuantity(odd.at('B'), '3');
  assert.throws(() => odd.s.splitInto(odd.at('A'), [odd.at('A', 'A1')], odd.at('B')), failsWith('quantity_inexact'));
  assert.strictEqual(odd.outline(), 'A[A1,A2],B[B1],C');
});

test('splitting joins the same item whatever its case, and only the same kind of line', () => {
  const { s, at } = fresh();
  s.addItems([{ id: '9', number: 'a1', name: 'x' }], at('B'), '');
  s.splitInto(at('A'), [at('A', 'A1')], at('B'));
  assert.strictEqual(s.find(at('B')).children.filter((c) => c.number.toLowerCase() === 'a1').length, 2, 'an added item and a component are not the same line');
  const other = fresh();
  other.s.copy([other.at('A', 'A1')], other.at('B'), '');
  other.s.setQuantity(other.at('B', 'A1'), '1');
  other.s.splitInto(other.at('A'), [other.at('A', 'A1')], other.at('B'));
  assert.strictEqual(other.s.find(other.at('B', 'A1')).quantity, '3');
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
  Object.values(s.compare().ebom).forEach((state) => assert.deepStrictEqual(plain(state), { missing: false, quantity: false, exceeded: false, moved: false, matched: true }));
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
  const s = S.create({ ebom: S.ebomFromRows(rows, { item_number: 'TOP' }) });
  const a = s.root().children[0].uid;
  s.setQuantity(a, '0.1');
  s.copy([a], S.ROOT, '');
  s.copy([a], S.ROOT, '');
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
  const s = S.create({ ebom: ebom });
  const at = (...n) => { let node = s.root(); n.forEach((x) => { node = node.children.find((c) => c.number === x); }); return node.uid; };
  const state = (key) => s.compare().ebom[key];
  assert.strictEqual(state('0.0').matched, true);
  assert.strictEqual(state('0.2').matched, true);
  s.setQuantity(at('Q'), '3');
  assert.strictEqual(state('0.2').matched, false, 'part covered: stays normal, with the quantity flag');
  assert.strictEqual(state('0.2').quantity, true);
  s.copy([at('Q')], at('P1'), '');   // 3 + 3 = 6 is over 4
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
  s.copy([s.find(p1).children[0].uid], p1, '');   // a second line made from 0.0.0: 2 + 2 against 2
  assert.strictEqual(s.compare().ebom['0.0.0'].matched, false);
  assert.strictEqual(s.compare().ebom['0.0.0'].quantity, true);
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
