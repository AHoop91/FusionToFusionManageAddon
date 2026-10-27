// The whole Publish panel (publish.js and its modules) driven in jsdom against a fake Python: the lazy Bill of Materials, from the
// first level to Expand all and publishing. Needs jsdom (``npm install jsdom``); without it these tests are skipped.
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const { pageScripts, run, PUBLISH_HTML } = require('./helpers');

let JSDOM = null;
try { JSDOM = require('jsdom').JSDOM; } catch (error) { /* skipped below */ }

const row = (id, number, extra) => Object.assign({
  level: 0, id: id, item_number: number, part_number: number, name: id + ' name', description: '', sequence: 1, quantity: '1',
  has_children: false, status: 'match',
}, extra || {});
const SUMMARY = { component_id: 'R', composition: 'RELEASED', item_number: 'TOP', part_number: 'TOP', name: 'Top', description: '' };
const plain = (x) => JSON.parse(JSON.stringify(x));   // the page runs in a window of its own: arrays are compared as data

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
  ns.shell = { mountHeader() {} };
  ns.account = { init() {} };
  ns.auth = { init() {}, refresh() {}, onChange: (fn) => { panel.authChanged = fn; } };
  panel.reading = [];   // what the progress dialog was told about the read that Publish waits for
  ns.pubJobs = {
    init() {}, start: (job) => panel.started.push(job),
    reading: (step) => panel.reading.push(step.done ? 'done' : step.status), stopReading: () => panel.reading.push('stopped'),
  };
  ns.pubAddItems = { open() {} };
  ns.diffReport = { open() {}, COLUMN_VALUE: 'v', COLUMN_FM: 'f' };
  ns.pubDetails = {
    init() {}, open() {}, setRoot() {}, setRootError() {}, handleComponent() {}, handleThumbnail() {},
    setThumbnail() {}, reset() {}, changeState: () => panel.own,
  };
  const scripts = pageScripts();
  scripts.filter((src) => /(^|\/)dom\.js$/.test(src)).forEach((src) => run(w, src));
  Object.assign(ns, { bridge: ns.bridge, shell: ns.shell, account: ns.account, auth: ns.auth, diffReport: ns.diffReport });   // dom.js made a fresh namespace's helpers; keep the stand-ins
  scripts.filter((src) => /\/ui\.js$|toast\.js$/.test(src)).forEach((src) => run(w, src));
  scripts.filter((src) => /\/bom-[a-z-]+\.js$|publish-check|publish-bom/.test(src)).forEach((src) => run(w, src));
  run(w, 'js/publish.js');
  return panel;
}

test('the lazy Bill of Materials, from the first level to publishing', { skip: JSDOM ? false : 'jsdom is not installed' }, () => {
  const panel = openPanel();
  const { w, sent, handlers, started, reading } = panel;
  const $ = (id) => w.document.getElementById(id);
  const reply = (slot, entry, via) => handlers[via || 'load_publish_section']({ ok: true, result: Object.assign({
    section: slot, pending: false, ok: true, data: null, message: '', denied: '', key: 'k', progress: 0, stage: '' }, entry) });
  const sentOf = (section) => sent.filter(([action, p]) => action === 'load_publish_section' && p.section === section);
  const lastSent = (section) => sentOf(section).pop();
  const rowsText = () => [...$('pub-bom').querySelectorAll('tr.pub-cmp-row')].filter((tr) => !tr.hidden).map((tr) => tr.textContent.trim().replace(/\s+/g, ' '));
  const click = (el) => el.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
  const rowOf = (text) => [...$('pub-bom').querySelectorAll('tr.pub-cmp-row')].find((tr) => tr.textContent.includes(text));
  const reload = () => $('pub-refresh').click();   // the refresh button: reads everything again at once
  const openDesign = (rows) => {
    reply('summary', { data: SUMMARY });
    reply('structure', { data: { rows: rows, shared: false, fm_item_id: '9' } });
  };
  const firstLevel = () => [row('A', 'PN-A', { has_children: true }), row('P', 'PN-P', { status: 'new' })];
  const wholeTree = [
    row('A', 'PN-A', { has_children: true }), row('X', 'PN-X', { has_children: true, level: 1 }),
    row('Z', 'PN-Z', { level: 2, status: 'changed', quantity: '2', fm_quantity: '1' }), row('P', 'PN-P', { status: 'new' }),
  ];

  // Open the panel: the summary, then the first level only.
  $('view-app').hidden = false;
  panel.authChanged(true);
  assert.ok(lastSent('summary'), 'the summary is asked for');
  reply('summary', { data: SUMMARY });
  assert.ok(lastSent('structure') && lastSent('thumbnail'), 'the structure and thumbnail follow the summary');
  assert.ok($('pub-publish').disabled, 'publish waits for the Bill of Materials');
  reply('structure', { data: { rows: [row('A', 'PN-A', { has_children: true }), row('B', 'PN-B', { status: 'new' }),
    row('S', '', { status: 'skipped', skip: 'no_number', has_children: true })], shared: false, fm_item_id: '9' } });
  assert.ok(lastSent('properties'), 'the design\'s own properties are read quietly after the Bill of Materials');
  assert.strictEqual(rowsText().length, 4, 'the design and its first level');
  assert.ok(!$('pub-publish').disabled);

  // Open an assembly: a spinner and grey rows, then its lines.
  click(rowOf('A name').querySelector('.pub-tree-toggle'));
  const asked = lastSent('children')[1];
  assert.deepStrictEqual(plain([asked.id, asked.item_number, asked.compared, asked.skip, asked.force]), ['A', 'PN-A', '1', '', true]);
  assert.ok(rowOf('A name').querySelector('.pub-spin'), 'a spinner replaces the chevron');
  assert.strictEqual($('pub-bom').querySelectorAll('.pub-skel-tr').length, 3, 'grey rows stand under it');
  reply('children:A', { pending: true });
  assert.ok(rowOf('A name').querySelector('.pub-spin'), 'still reading');
  reply('children:A', { data: { rows: [row('X', 'PN-X', { has_children: true }), row('Y', 'PN-Y', { status: 'new' })] } });
  assert.ok(!rowOf('A name').querySelector('.pub-spin'));
  assert.strictEqual($('pub-bom').querySelectorAll('.pub-skel-tr').length, 0);
  assert.strictEqual(rowsText().length, 6, 'its two lines are in');

  // A skipped assembly says so when it is read; a failure is that assembly's alone, with a retry.
  click(rowOf('S name').querySelector('.pub-tree-toggle'));
  const skippedAsk = lastSent('children')[1];
  assert.deepStrictEqual(plain([skippedAsk.id, skippedAsk.skip]), ['S', '1']);
  reply('children:S', { ok: false, message: 'boom' });
  assert.ok($('pub-bom').querySelector('.pub-cmp-fail'), 'a failure row');
  assert.strictEqual(rowsText().length, 7, 'the rest of the table stays');
  const asks = sentOf('children').length;
  click($('pub-bom').querySelector('.pub-cmp-fail-retry'));
  assert.strictEqual(sentOf('children').length, asks + 1, 'retry asks again');
  reply('children:S', { data: { rows: [row('T', 'PN-T', { status: 'skipped', skip: 'parent' })] } });
  assert.ok(!$('pub-bom').querySelector('.pub-cmp-fail'));

  // Reading an assembly leaves the table where it was scrolled.
  const wrapOf = () => $('pub-bom').querySelector('.pub-cmp-wrap');
  wrapOf().scrollTop = 150;
  wrapOf().dispatchEvent(new w.Event('scroll'));   // jsdom has no layout, so it does not scroll by itself
  click(rowOf('X name').querySelector('.pub-tree-toggle'));   // the table is drawn again, with the spinner
  assert.strictEqual(wrapOf().scrollTop, 150, 'still where it was while the lines are read');

  // An answer from before a reload is ignored.
  reload();
  reply('children:X', { data: { rows: [row('Z', 'PN-Z')] } });
  assert.ok(!$('pub-bom').querySelector('table'), 'the old table is gone and the late answer is not drawn');
  openDesign(firstLevel());
  assert.strictEqual(rowsText().length, 3, 'a fresh first level');
  assert.strictEqual($('pub-bom').querySelectorAll('.pub-spin').length, 0);

  // Expand all reads the rest, once, and the buttons and Publish wait for it.
  click($('pub-bom').querySelector('.pub-cmp-tool-expand'));
  assert.ok(lastSent('tree') && lastSent('tree')[1].force === true);
  assert.ok($('pub-bom').querySelector('.pub-cmp-tool-expand').disabled && $('pub-publish').disabled);
  const treeAsks = sentOf('tree').length;
  click($('pub-bom').querySelector('.pub-cmp-tool-expand'));
  assert.strictEqual(sentOf('tree').length, treeAsks, 'a second click asks nothing more');
  reply('tree', { pending: true, progress: 1200 });
  assert.match($('pub-bom').querySelector('.pub-cmp-tool-busy').title, /1,200|1200/, 'how far it is goes in the tooltip of the spinning button');
  assert.ok($('pub-bom').querySelector('.pub-cmp-tool-collapse').disabled, 'Collapse all waits');
  assert.ok(!$('pub-bom').querySelector('.pub-cmp-busy'), 'no message under the toolbar');
  reply('tree', { data: { rows: wholeTree, shared: false, fm_item_id: '9' } });
  assert.strictEqual(rowsText().length, 5, 'every level shows');
  assert.ok(!$('pub-publish').disabled);

  // Publish covers the whole design: with levels unread it reads the tree first, then goes on by itself.
  const pills = () => [...$('pub-pills').querySelectorAll('.pub-pill')].map((p) => p.textContent.trim().replace(/\s+/g, ' '));
  const operations = (job) => plain(job.operations.map((o) => o.op + ':' + o.parent + '>' + o.number));
  reload();
  openDesign(firstLevel());
  assert.deepStrictEqual(plain(pills()), ['3 Items'], 'closed assemblies are not skipped: no such pill');
  const treeReads = sentOf('tree').length;
  click($('pub-publish'));
  assert.strictEqual(sentOf('tree').length, treeReads + 1, 'the rest of the tree is read to publish');
  assert.strictEqual(started.length, 0, 'nothing is queued until it is read');
  assert.deepStrictEqual(plain(reading), ["Reading every level of the Bill of Materials before publishing."], 'the dialog opens at once, saying it is reading');
  reply('tree', { data: { rows: [
    row('A', 'PN-A', { has_children: true }), row('X', 'PN-X', { level: 1, status: 'new' }), row('P', 'PN-P', { status: 'new' })] } });
  assert.strictEqual(started.length, 1);
  assert.deepStrictEqual(plain(reading.slice(1)), ['done'], 'the dialog hands over to the job');
  assert.deepStrictEqual(plain(started[0].items.map((i) => i.id)), ['R', 'A', 'X', 'P']);
  assert.deepStrictEqual(operations(started[0]), ['add:PN-A>PN-X', 'add:TOP>PN-P']);

  // Fully read already: nothing more is read to publish.
  const reads = sent.length;
  click($('pub-publish'));
  assert.strictEqual(sent.length, reads);
  assert.strictEqual(started.length, 2);

  // The read failing publishes nothing.
  reload();
  openDesign(firstLevel());
  click($('pub-publish'));
  reply('tree', { ok: false, message: 'no' });
  assert.strictEqual(started.length, 2);
  assert.ok(!$('pub-publish').disabled);

  // Skipped lines are counted, and left out.
  reload();
  openDesign([row('S', '', { status: 'skipped', skip: 'no_number' }), row('P', 'PN-P', { status: 'new' })]);
  assert.deepStrictEqual(plain(pills()), ['2 Items', '1 Lines Skipped']);

  // A line that waits for a choice blocks publishing, folded or not.
  reload();
  openDesign([row('A', 'PN-A', { has_children: true })]);
  click(rowOf('A name').querySelector('.pub-tree-toggle'));
  reply('children:A', { data: { rows: [
    row('', 'PN-OLD', { status: 'extra', pair: 'PN-N', part_number: 'PN-OLD', edge_id: 'e' }), row('N', 'PN-N', { status: 'new' })] } });
  assert.ok($('pub-bom').querySelector('.pub-cmp-act-add'), 'the line is in view');
  assert.ok($('pub-publish').disabled, 'publishing waits for the choice');
  click(rowOf('A name').querySelector('.pub-tree-toggle'));   // close A: the line still counts
  assert.ok($('pub-publish').disabled, 'a line folded away still holds publishing back');

  // The whole tree failing leaves the table and the buttons working.
  reload();
  openDesign([row('A', 'PN-A', { has_children: true })]);
  click($('pub-bom').querySelector('.pub-cmp-tool-expand'));
  reply('tree', { ok: false, message: 'no' });
  assert.ok($('pub-bom').querySelector('table'));
  assert.ok(!$('pub-bom').querySelector('.pub-cmp-tool-expand').disabled);
});

test('the up-to-date check button says what the design and its lines come to', { skip: JSDOM ? false : 'jsdom is not installed' }, () => {
  /** The panel open on a design whose first level is ``rows``, with its own properties answered as ``compare`` and the details saying ``own``. */
  function checked(own, rows, compare) {
    const panel = openPanel();
    panel.own = own;
    const doc = panel.w.document;
    doc.getElementById('view-app').hidden = false;
    panel.authChanged(true);
    const reply = (slot, entry) => panel.handlers.load_publish_section({ ok: true, result: Object.assign({
      section: slot, pending: false, ok: true, data: null, message: '', denied: '', key: 'k', progress: 0, stage: '' }, entry) });
    reply('summary', { data: SUMMARY });
    reply('structure', { data: { rows: rows, shared: false, fm_item_id: '9' } });
    reply('properties', { data: { compare: compare, count: 1 } });
    const button = doc.getElementById('pub-check');
    return { panel: panel, reply: reply, state: () => button.dataset.state, count: () => (doc.getElementById('pub-check-count').hidden ? '' : doc.getElementById('pub-check-count').textContent),
             title: () => button.title };
  }
  const matching = { rows: [{ name: 'Mass', status: 'match', value: '1', fm_value: '1' }] };
  const differing = { rows: [{ name: 'Mass', status: 'mismatch', value: '1', fm_value: '2' }] };
  const leaf = [row('P', 'PN-P', { status: 'match' })];

  assert.strictEqual(checked('match', leaf, matching).state(), 'ok');
  assert.match(checked('match', leaf, matching).title(), /The design matches Fusion Manage/);

  const fresh = checked('new', leaf, differing);
  assert.strictEqual(fresh.state(), 'idle', 'a design not in Fusion Manage yet has nothing out of date: no button');
  assert.strictEqual(fresh.count(), '');

  const changed = checked('match', leaf, differing);
  assert.strictEqual(changed.state(), 'changes');
  assert.strictEqual(changed.count(), '1');

  const unknown = checked('unknown', leaf, differing);
  assert.strictEqual([unknown.state(), unknown.count()].join('|'), 'error|1', 'an unreadable Fusion Manage keeps the differences it found');
  const several = checked('multiple', leaf, differing);
  assert.strictEqual([several.state(), several.count()].join('|'), 'changes|1');

  const partial = checked('match', [row('A', 'PN-A', { has_children: true })], matching);
  assert.strictEqual(partial.state(), 'ok');
  assert.match(partial.title(), /levels read so far/, 'an unread level is said to be unread');

  const broken = checked('match', leaf, matching);
  broken.reply('structure', { ok: false, message: 'down' });
  assert.strictEqual(broken.state(), 'error');
  assert.match(broken.title(), /down/);
  const doc = broken.panel.w.document;
  const asks = broken.panel.sent.filter(([action, p]) => action === 'load_publish_section' && p.section === 'structure').length;
  doc.querySelector('#pub-bom .btn, #pub-bom button').dispatchEvent(new broken.panel.w.MouseEvent('click', { bubbles: true }));
  assert.strictEqual(broken.panel.sent.filter(([action, p]) => action === 'load_publish_section' && p.section === 'structure').length, asks + 1, 'retry reads the structure again');
  assert.notStrictEqual(broken.state(), 'error', 'and the failure is cleared');
});
