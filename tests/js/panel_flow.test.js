// The whole Publish panel (publish.js and its modules) driven in jsdom against a fake Python: the Bill of Materials, from the MBOM
// lookup to publishing. Needs jsdom (``npm install jsdom``); without it these tests are skipped.
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const { englishI18n, pageScripts, run, PUBLISH_HTML } = require('./helpers');

let JSDOM = null;
try { JSDOM = require('jsdom').JSDOM; } catch (error) { /* skipped below */ }

const row = (id, number, extra) => Object.assign({
  level: 0, id: id, item_number: number, part_number: number, name: id + ' name', description: '', sequence: 1, quantity: '1',
  has_children: false, status: 'match',
}, extra || {});
const SUMMARY = { component_id: 'R', composition: 'RELEASED', item_number: 'TOP', part_number: 'TOP', name: 'Top', description: '' };
const plain = (x) => JSON.parse(JSON.stringify(x));   // the page runs in a window of its own: arrays are compared as data

/** What Python gives back of the item an answer was read for: the id the request named. */
const echoed = (sent, slot) => (sent.filter(([action, p]) => action === 'load_publish_section' && p.section === slot).pop() || [0, {}])[1].target_id || '';

/** The panel loaded into a window, with the shell, bridge, account, auth, jobs and details replaced by stand-ins that record what they are told. */
function openPanel() {
  const html = fs.readFileSync(PUBLISH_HTML, 'utf8');
  const dom = new JSDOM(html, { runScripts: 'outside-only', pretendToBeVisual: true });
  const w = dom.window;
  w.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
  w.adsk = {};
  w.MfgUi = {};
  const ns = w.MfgUi;
  const panel = { w: w, sent: [], handlers: {}, started: [], authChanged: null, own: 'match' };   // own: what the details say of the design's own state
  ns.bridge = { send: (action, payload) => panel.sent.push([action, payload || {}]), on: (action, fn) => { panel.handlers[action] = fn; } };
  ns.i18n = englishI18n();
  ns.shell = { mountHeader() {} };
  ns.account = { init() {} };
  ns.auth = { init() {}, refresh() {}, onChange: (fn) => { panel.authChanged = fn; } };
  ns.pubJobs = {
    init: (options) => { panel.jobsOptions = options; }, start: (job) => panel.started.push(job), setStamp: (stamp) => { panel.stamp = stamp; },
  };
  ns.pubAddItems = { open() {} };
  let found = [];
  ns.pubMbom = {   // chooses the MBOM it is asked for, else the first; ``panel.mbomHost`` is what the panel gave it, to choose as the user would
    init: (host) => { panel.mbomHost = host; }, show: (items, wanted) => { found = items; return items.some((i) => i.number === wanted) ? wanted : items.length > 1 ? null : (items[0] || {}).number || ''; },
    idOf: (number) => (found.find((i) => i.number === number) || {}).id || '', answer() {}, offer() {}, loading() {}, reset() {}, forget() {},
  };
  ns.diffReport = { open() {}, COLUMN_VALUE: 'v', COLUMN_FM: 'f' };
  ns.pubDetails = {
    init() {}, open() {}, setRoot() {}, setRootError() {}, handleComponent() {}, handleThumbnail() {},
    setThumbnail() {}, reset() {}, close() {}, handleItemTabs() {}, handleItemView() {}, changeState: () => panel.own,
  };
  const scripts = pageScripts();
  scripts.filter((src) => /(^|\/)dom\.js$/.test(src)).forEach((src) => run(w, src));
  Object.assign(ns, { bridge: ns.bridge, i18n: ns.i18n, shell: ns.shell, account: ns.account, auth: ns.auth, diffReport: ns.diffReport });   // dom.js made a fresh namespace's helpers; keep the stand-ins
  scripts.filter((src) => /\/ui\.js$|toast\.js$/.test(src)).forEach((src) => run(w, src));
  scripts.filter((src) => /\/m?bom-[a-z-]+\.js$|publish-bom/.test(src)).forEach((src) => run(w, src));
  run(w, 'js/publish.js');
  return panel;
}

test('the structure, from the MBOM lookup to publishing', { skip: JSDOM ? false : 'jsdom is not installed' }, () => {
  const panel = openPanel();
  const { w, sent, handlers, started } = panel;
  const $ = (id) => w.document.getElementById(id);
  const reply = (slot, entry, via) => handlers[via || 'load_publish_section']({ ok: true, result: Object.assign({
    section: slot, pending: false, ok: true, data: null, message: '', denied: '', key: 'k', progress: 0, target_id: echoed(sent, slot) }, entry) });
  const sentOf = (section) => sent.filter(([action, p]) => action === 'load_publish_section' && p.section === section);
  const lastSent = (section) => sentOf(section).pop();
  const click = (el) => el.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
  const reload = () => $('pub-refresh').click();   // the refresh button: reads everything again at once
  const operations = (job) => plain(job.operations.map((o) => o.op + ':' + o.parent + '>' + o.number));
  const lines = (pane) => [...$('pub-structure').querySelectorAll('.sv-pane')[pane].querySelectorAll('.sv-row .sv-pn')].map((n) => n.textContent);
  const openDesign = (rows) => {
    reply('summary', { data: SUMMARY });
    reply('mbom', { data: [] });
    reply('structure', { data: { rows: rows, shared: false } });
  };
  const wholeTree = (extra) => [row('A', 'PN-A', { has_children: true }), row('X', 'PN-X', { level: 1, status: 'new' }), row('P', 'PN-P', { status: 'new' })].concat(extra || []);

  // Open the panel: the summary, then the MBOM lookup, then the whole structure.
  $('view-app').hidden = false;
  panel.authChanged(true);
  assert.ok(lastSent('summary'), 'the summary is asked for');
  reply('summary', { data: SUMMARY });
  assert.ok(lastSent('mbom') && lastSent('thumbnail'), 'the MBOM lookup and the thumbnail follow the summary');
  assert.ok(!lastSent('structure'), 'nothing is searched in Fusion Manage by item number before the MBOM lookup has answered');
  assert.ok(!$('pub-bom').hidden && $('pub-structure').hidden, 'the lookup is told with bouncing balls where the structure will be');
  assert.ok($('pub-bom').querySelector('.balls'), 'the balls');
  assert.match($('pub-bom').textContent, /Checking for existing Bill of Materials in Fusion Manage/, 'and say what is being looked for');
  assert.strictEqual($('pub-structure').querySelectorAll('.pub-skel-row').length, 0, 'no skeleton yet');
  reply('mbom', { data: [] });
  assert.ok(lastSent('structure'), 'the Bill of Materials follows the lookup');
  assert.ok($('pub-publish').disabled, 'publish waits for the Bill of Materials');
  assert.ok($('pub-bom').hidden && !$('pub-structure').hidden, 'the viewer is on screen from the lookup answer: a skeleton of its two tables and toolbar');
  assert.strictEqual($('pub-structure').querySelectorAll('.sv-pane').length, 2);
  assert.ok($('pub-structure').querySelectorAll('.sv-tree')[0].querySelector('.pub-skel-row') && $('pub-structure').querySelectorAll('.sv-tree')[1].querySelector('.pub-skel-row'), 'both tables hold grey rows');
  assert.ok(!$('pub-structure').querySelector('.sv-bar').hidden && $('pub-structure').querySelector('.sv-bar').hasAttribute('inert'), 'the toolbar is there, not yet usable');
  const bars = [...$('pub-structure').querySelectorAll('.pub-skel')];
  assert.match($('pub-structure').querySelector('.sv-status').textContent, /Reading the Fusion Component structure/);
  assert.ok(!$('pub-view-table'), 'there is no table to switch to');

  // The whole structure comes in one read: the structure takes over, and nothing else is asked of the Data Model.
  assert.ok($('pub-publish').disabled, 'nothing to publish until the structure is built');
  openDesign(wholeTree());
  assert.ok($('pub-bom').hidden && !$('pub-structure').hidden, 'the structure is the view');
  assert.ok(bars.every((bar) => !bar.isConnected), 'the skeleton made way for the tables');
  assert.ok(lastSent('properties'), 'the design own properties are read quietly after the Bill of Materials');
  assert.strictEqual(sentOf('structure').length, 1, 'the structure is read once');
  assert.strictEqual(sentOf('tree').length, 0, 'there is no second read of its levels');
  assert.strictEqual(sentOf('mbom_tree').length, 0, 'a design with no MBOM item has no MBOM to read');
  assert.ok(lines(0).includes('PN-A') && lines(0).includes('PN-P'), 'the EBOM is drawn');
  assert.ok(lines(1).includes('PN-A'), 'and the MBOM starts as a copy of it');
  assert.strictEqual($('pub-structure').querySelectorAll('.pub-skel-row').length, 0, 'the skeleton is gone');
  assert.ok(!$('pub-structure').querySelector('.sv-bar').hasAttribute('inert'), 'and the toolbar can be used');
  assert.ok(!$('pub-publish').disabled);
  assert.strictEqual($('pub-pills'), null, 'there is no count of items in the footer: the lines say what is happening');

  // Publish sends what the structure holds.
  click($('pub-publish'));
  assert.strictEqual(started.length, 1);
  assert.deepStrictEqual(plain(started[0].items.map((i) => i.id)), ['R', 'A', 'X', 'P']);
  assert.deepStrictEqual(operations(started[0]), ['add:TOP>PN-A', 'add:PN-A>PN-X', 'add:TOP>PN-P']);
  assert.strictEqual(started[0].root_number, 'TOP');

  // A line the design leaves out of publishing is said, and holds Publish back.
  reload();
  openDesign([row('S', '', { status: 'skipped', skip: 'no_number' }), row('P', 'PN-P', { status: 'new' })]);
  assert.ok($('pub-publish').disabled, 'it cannot be published');
  assert.match($('pub-publish').title, /no item number/);
  click($('pub-publish'));
  assert.strictEqual(started.length, 1, 'and nothing is sent');

  // The structure failing publishes nothing, and the panel says why.
  reload();
  reply('summary', { data: SUMMARY });
  reply('mbom', { data: [] });
  reply('structure', { ok: false, message: 'no' });
  assert.ok($('pub-publish').disabled);
  assert.strictEqual(started.length, 1);
});

test('choosing another MBOM reads the Bill of Materials again, compared with that item', { skip: JSDOM ? false : 'jsdom is not installed' }, () => {
  const panel = openPanel();
  panel.w.document.getElementById('view-app').hidden = false;
  panel.authChanged(true);
  const reply = (slot, entry) => panel.handlers.load_publish_section({ ok: true, result: Object.assign({
    section: slot, pending: false, ok: true, data: null, message: '', denied: '', key: 'k', progress: 0, target_id: echoed(panel.sent, slot) }, entry) });
  const targets = (section) => panel.sent.filter(([action, p]) => action === 'load_publish_section' && p.section === section).map(([, p]) => p.target);
  reply('summary', { data: SUMMARY });
  assert.deepStrictEqual(plain(targets('summary')), [''], 'the summary is the design\'s own');
  reply('mbom', { data: [{ id: '1', number: 'M-1' }, { id: '2', number: 'M-2' }] });
  assert.deepStrictEqual(plain(targets('structure')), [], 'several MBOMs: the Bill of Materials waits for the user to choose one');
  assert.ok(!panel.w.document.getElementById('pub-bom').hidden && !panel.w.document.querySelector('#pub-bom .balls') && !panel.w.document.querySelector('#pub-structure .pub-skel-row'), 'the area is the list of the ones found (the balls are gone), not a skeleton');
  panel.mbomHost.choose('M-1');
  assert.ok(panel.w.document.getElementById('pub-bom').hidden && panel.w.document.querySelector('#pub-structure .pub-skel-row'), 'the one chosen opens the skeleton of the two tables');
  assert.deepStrictEqual(plain(targets('structure')), ['M-1'], 'the one chosen is what the Bill of Materials is read for');
  reply('structure', { data: { rows: [row('P', 'PN-P', { status: 'new' })], shared: false } });
  const mbomAsk = panel.sent.filter(([action, p]) => action === 'load_publish_section' && p.section === 'mbom_tree').pop();
  assert.ok(mbomAsk && mbomAsk[1].force === true, 'the MBOM is read afresh each time, never from a copy kept in Python');
  panel.mbomHost.choose('M-2');
  assert.deepStrictEqual(plain(targets('structure')), ['M-1', 'M-2'], 'another MBOM: the Bill of Materials is asked for again');
  const ids = panel.sent.filter(([action, p]) => action === 'load_publish_section' && p.section === 'structure').map(([, p]) => p.target_id);
  assert.deepStrictEqual(plain(ids), ['1', '2'], 'each is asked for by the id of its item, whatever its number becomes');
  reply('structure', { data: { rows: [row('P', 'PN-P')], shared: false } });
  assert.deepStrictEqual(plain(targets('properties')), ['M-1', 'M-2'], 'and the design\'s own properties are compared with it');
});

test('a structure that could not be read is read again by the retry button', { skip: JSDOM ? false : 'jsdom is not installed' }, () => {
  const panel = openPanel();
  const doc = panel.w.document;
  doc.getElementById('view-app').hidden = false;
  panel.authChanged(true);
  const reply = (slot, entry) => panel.handlers.load_publish_section({ ok: true, result: Object.assign({
    section: slot, pending: false, ok: true, data: null, message: '', denied: '', key: 'k', progress: 0, target_id: echoed(panel.sent, slot) }, entry) });
  reply('summary', { data: SUMMARY });
  reply('mbom', { data: [] });
  reply('structure', { ok: false, message: 'down' });
  const asks = () => panel.sent.filter(([action, p]) => action === 'load_publish_section' && p.section === 'structure').length;
  const before = asks();
  doc.querySelector('#pub-bom .btn, #pub-bom button').dispatchEvent(new panel.w.MouseEvent('click', { bubbles: true }));
  assert.strictEqual(asks(), before + 1, 'retry reads the structure again');
});

test('when a publish ends the whole panel is read again, the MBOM included, and never from a copy kept before', { skip: JSDOM ? false : 'jsdom is not installed' }, () => {
  const panel = openPanel();
  const { w, sent, handlers } = panel;
  const $ = (id) => w.document.getElementById(id);
  const reply = (slot, entry) => handlers.load_publish_section({ ok: true, result: Object.assign({
    section: slot, pending: false, ok: true, data: null, message: '', denied: '', key: 'k', progress: 0, target_id: echoed(sent, slot) }, entry) });
  const asks = (section) => sent.filter(([action, p]) => action === 'load_publish_section' && p.section === section);
  const rows = [row('P', 'PN-P', { status: 'new' })];
  const read = () => {
    reply('summary', { data: SUMMARY });
    reply('mbom', { data: [{ id: '1', number: 'M-1' }] });
    reply('structure', { data: { rows: rows, shared: false } });
  };
  $('view-app').hidden = false;
  panel.authChanged(true);
  read();
  assert.strictEqual(asks('mbom_tree').length, 1);
  assert.deepStrictEqual(plain(asks('mbom_tree')[0][1].target_id), '1', 'the MBOM item is read by its id');
  panel.jobsOptions.onFinished({ id: 'job' });   // the run ended: Fusion Manage has changed
  assert.ok(asks('summary').length === 2 && asks('summary')[1][1].force === true, 'the design is read again, past the copies kept');
  read();
  assert.strictEqual(asks('mbom_tree').length, 2, 'and so is the MBOM');
  assert.strictEqual(asks('mbom_tree')[1][1].force, true);
  assert.strictEqual(asks('structure')[1][1].force, true);
  assert.strictEqual(asks('mbom')[1][1].force, true, 'the lookup of the MBOM item too');
});

/** A panel with the MBOM ``M-1`` (item 1) chosen: ``reply`` answers a section, ``mbomTree`` is what Fusion Manage holds of it. */
function openWithMbom() {
  const panel = openPanel();
  const { w, sent, handlers } = panel;
  const $ = (id) => w.document.getElementById(id);
  $('view-app').hidden = false;
  panel.authChanged(true);
  const api = {
    panel: panel, $: $,
    reply: (slot, entry) => handlers.load_publish_section({ ok: true, result: Object.assign({
      section: slot, pending: false, ok: true, data: null, message: '', denied: '', key: 'k', progress: 0, target_id: echoed(sent, slot) }, entry) }),
    sentOf: (section) => sent.filter(([action, p]) => action === 'load_publish_section' && p.section === section),
    skeleton: () => $('pub-structure').querySelectorAll('.pub-skel-row').length > 0,
    lines: (pane) => [...$('pub-structure').querySelectorAll('.sv-pane')[pane].querySelectorAll('.sv-row .sv-pn')].map((n) => n.textContent),
    mbomTree: (line) => ({ data: { number: 'M-1', name: 'M one', item_id: '1', children: [{ number: line || 'PN-P', name: 'P', quantity: '1', edge_id: 'e1', item_id: 'iP', sequence: '1', children: [] }] } }),
    whole: () => ({ data: { rows: [row('P', 'PN-P')], shared: false } }),
  };
  api.reply('summary', { data: SUMMARY });
  api.reply('mbom', { data: [{ id: '1', number: 'M-1' }] });
  return api;
}

test('the structure and the MBOM are asked for together, and the viewer keeps its skeleton until both are in', { skip: JSDOM ? false : 'jsdom is not installed' }, () => {
  [['structure', 'mbom_tree'], ['mbom_tree', 'structure']].forEach(([first, second]) => {
    const p = openWithMbom();
    assert.strictEqual(p.sentOf('structure').length, 1, 'the structure is asked for as soon as the MBOM is known');
    assert.strictEqual(p.sentOf('mbom_tree').length, 1, 'and so is the MBOM tree, without waiting for the structure');
    assert.strictEqual(p.sentOf('mbom_tree')[0][1].force, true, 'a copy kept before is never used');
    assert.strictEqual(p.sentOf('mbom_tree')[0][1].target_id, '1', 'it is read by the id of its item');
    const answers = { structure: p.whole(), mbom_tree: p.mbomTree() };
    p.reply(first, answers[first]);
    assert.ok(p.skeleton(), 'with only the ' + first + ' in, nothing is drawn');
    assert.ok(p.$('pub-publish').disabled);
    p.reply(second, answers[second]);
    assert.ok(!p.skeleton(), 'both are in: the tables are drawn');
    assert.deepStrictEqual(plain(p.lines(1)), ['M-1', 'PN-P']);
    assert.ok(!p.$('pub-publish').disabled);
  });
});

test('a failed read of the MBOM is said in the viewer and is read again alone', { skip: JSDOM ? false : 'jsdom is not installed' }, () => {
  const p = openWithMbom();
  p.reply('mbom_tree', { ok: false, message: 'Fusion Manage said no' });
  p.reply('structure', p.whole());
  assert.match(p.$('pub-structure').textContent, /Fusion Manage said no/);
  assert.ok(p.$('pub-publish').disabled);
  p.$('pub-structure').querySelector('.pub-retry').dispatchEvent(new p.panel.w.MouseEvent('click', { bubbles: true }));
  assert.strictEqual(p.sentOf('mbom_tree').length, 2, 'the MBOM is asked for again');
  assert.strictEqual(p.sentOf('structure').length, 1, 'the structure, which was read, is not');
  p.reply('mbom_tree', p.mbomTree());
  assert.deepStrictEqual(plain(p.lines(1)), ['M-1', 'PN-P']);
});

test('another MBOM asks only for what depends on it, and a refresh asks for everything', { skip: JSDOM ? false : 'jsdom is not installed' }, () => {
  const p = openWithMbom();
  p.reply('structure', p.whole());
  p.reply('mbom_tree', p.mbomTree());
  p.panel.mbomHost.choose('M-1');   // the same list: another choice of the one item
  const again = p.sentOf('structure').pop();
  assert.strictEqual(again[1].force, false, 'another MBOM does not force the read: Python keeps what it read of the design');
  assert.strictEqual(p.sentOf('mbom_tree').length, 2, 'the MBOM tree is read for the one chosen');
  p.panel.w.document.getElementById('pub-refresh').click();   // the refresh button
  p.reply('summary', { data: SUMMARY });
  p.reply('mbom', { data: [{ id: '1', number: 'M-1' }] });
  assert.strictEqual(p.sentOf('structure').pop()[1].force, true, 'a refresh reads the design again');
});

test('answers for the Bill of Materials or the MBOM of an earlier reload are ignored', { skip: JSDOM ? false : 'jsdom is not installed' }, () => {
  [['structure', 'mbom_tree'], ['mbom_tree', 'structure']].forEach(([first, second]) => {
    const p = openWithMbom();
    p.panel.w.document.getElementById('pub-refresh').click();   // read again: the summary is on its way
    p.reply('mbom_tree', p.mbomTree('OLD'));
    p.reply('structure', p.whole());
    assert.ok(p.$('pub-publish').disabled, 'nothing is built from what was asked for before the refresh');
    p.reply('summary', { data: SUMMARY });
    p.reply('mbom', { data: [{ id: '1', number: 'M-1' }] });
    assert.ok(p.skeleton(), 'the old answers do not count as the new ones');
    const answers = { structure: p.whole(), mbom_tree: p.mbomTree() };
    p.reply(first, answers[first]);
    assert.ok(p.skeleton(), 'with only the new ' + first + ' in, the other is still awaited');
    p.reply(second, answers[second]);
    assert.deepStrictEqual(plain(p.lines(1)), ['M-1', 'PN-P'], 'only the answers to the new reads are used');
  });
});

test('an answer read for an MBOM that is no longer the one chosen is ignored', { skip: JSDOM ? false : 'jsdom is not installed' }, () => {
  const p = openWithMbom();
  p.reply('mbom_tree', Object.assign(p.mbomTree('OLD'), { target_id: '2' }));
  p.reply('structure', Object.assign(p.whole(), { target_id: '2' }));
  assert.ok(p.skeleton(), 'what was read for another item is not built');
  assert.ok(p.$('pub-publish').disabled);
  p.reply('mbom_tree', p.mbomTree());
  p.reply('structure', p.whole());
  assert.deepStrictEqual(plain(p.lines(1)), ['M-1', 'PN-P'], 'the answers for the chosen one are');
});

test('a forced refresh keeps its force when the MBOM has to be chosen again', { skip: JSDOM ? false : 'jsdom is not installed' }, () => {
  const p = openWithMbom();
  p.panel.w.document.getElementById('pub-refresh').click();   // read it all again, past the copies kept
  p.reply('summary', { data: SUMMARY });
  p.reply('mbom', { data: [{ id: '2', number: 'M-2' }, { id: '3', number: 'M-3' }] });   // M-1 is gone: the user chooses
  p.panel.mbomHost.choose('M-2');
  const asked = p.sentOf('structure').pop();
  assert.strictEqual(asked[1].force, true, 'the Data Model is read again, as the refresh said');
});
