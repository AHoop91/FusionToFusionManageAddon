// Prints, as JSON, the BOM operations the Publish panel's planner makes for some edits of an MBOM: what the Python end then sends to Fusion Manage
// (see tests/test_planner_to_tenant.py). Not a test of its own; the planner is tested by mbom_plan.test.js.
'use strict';

const { dataWindow } = require('./helpers');

const ns = dataWindow();
const S = ns.mbomStructure;
const row = (id, level, number) => ({ id: id, level: level, item_number: number, part_number: number, name: number + ' name', description: '', sequence: 1, quantity: '1', status: 'new' });
const EBOM = S.ebomFromRows([row('a', 0, 'A')], { item_number: 'TOP', name: 'Top', component_id: 'root' });
const SUMMARY = { item_number: 'TOP-M', part_number: 'TOP', name: 'Top', component_id: 'root' };

const tidy = (numbers, first) => S.create({ ebom: EBOM, mbom: S.mapByNumber({ number: 'TOP-M', itemId: 'i0', children: numbers.map((n, i) => (
  { number: n, quantity: '1', itemId: 'i' + n, edgeId: 'e' + n, sequence: String(first ? i + 1 : (i + 1) * 10), children: [] })) }, EBOM) });
const uid = (s, n) => s.root().children.find((c) => c.number === n).uid;
const plan = (s) => JSON.parse(JSON.stringify(ns.mbomPlan.build({ structure: s, ebom: EBOM, rows: [row('a', 0, 'A')], summary: SUMMARY, skipped: {} }).operations));

const out = {};
{ const s = tidy(['P', 'Q', 'R', 'S']); s.move([uid(s, 'R')], S.ROOT, uid(s, 'P')); out.front = { start: [['P', 10], ['Q', 20], ['R', 30], ['S', 40]], order: 'RPQS', operations: plan(s) }; }
{ const s = tidy(['P', 'Q', 'R', 'S'], true); s.addItems([{ id: '9', number: 'N', quantity: '1' }], S.ROOT, uid(s, 'R')); out.insert = { start: [['P', 1], ['Q', 2], ['R', 3], ['S', 4]], order: 'PQNRS', operations: plan(s) }; }
{ const s = tidy(['P', 'Q'], true); s.move([uid(s, 'Q')], S.ROOT, uid(s, 'P')); out.swap = { start: [['P', 1], ['Q', 2]], order: 'QP', operations: plan(s) }; }
{ const s = tidy(['P', 'Q', 'R', 'S'], true); s.move([uid(s, 'S')], S.ROOT, uid(s, 'P')); s.move([uid(s, 'R')], S.ROOT, uid(s, 'P')); out.reverse = { start: [['P', 1], ['Q', 2], ['R', 3], ['S', 4]], order: 'SRPQ', operations: plan(s) }; }
{ const s = tidy(['P', 'Q', 'R', 'S'], true); s.remove([uid(s, 'P')]); s.addItems([{ id: '9', number: 'N', quantity: '1' }], S.ROOT, ''); out.remove_and_append = { start: [['P', 1], ['Q', 2], ['R', 3], ['S', 4]], order: 'QRSN', operations: plan(s) }; }
process.stdout.write(JSON.stringify(out));
