// The dialog of the structure viewer (item-panel.js): a new manufacturing item and a bought version, with the shared form controls, in jsdom.
// Needs jsdom (``npm install jsdom``); without it these tests are skipped.
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { englishI18n, run } = require('./helpers');

let JSDOM = null;
try { JSDOM = require('jsdom').JSDOM; } catch (error) { /* skipped below */ }
const skip = JSDOM ? false : 'jsdom is not installed (npm install jsdom)';

const field = (over) => Object.assign({ id: 'F', title: 'Field', kind: 'text', required: false, description: '', options: [], lookup: '', max_length: 0, validators: [] }, over);
const NUMBER = field({ id: 'NUMBER', title: 'Item number', required: true });
const TITLE = field({ id: 'TITLE', title: 'Title' });
const TYPE = field({ id: 'TYPE', title: 'Type', kind: 'select', options: [{ value: '/o/1', title: 'Alpha' }, { value: '/o/2', title: 'Beta' }] });
const SUPPLIER = field({ id: 'SUPPLIER', title: 'Supplier', kind: 'link', lookup: 'SUPPLIERS' });
const formOf = (fields) => ({ sections: [{ title: 'Basic', fields: fields, matrices: [], collapsed: false }], left_out: [] });

function setup() {
  const dom = new JSDOM('<!doctype html><html><body><section id="pub-structure"></section></body></html>', { runScripts: 'outside-only' });
  const w = dom.window;
  w.MfgUi = {};
  const ns = w.MfgUi;
  run(w, '../shared/js/dom.js');
  ns.i18n = englishI18n();
  const sent = [];
  const handlers = {};
  ns.bridge = { send: (action, payload) => sent.push({ action, payload }), on: (action, fn) => { handlers[action] = fn; } };
  ['../shared/js/picker.js', '../shared/js/validators.js', '../shared/js/form-controls.js', '../shared/js/section.js', 'js/ui.js', 'js/item-panel.js'].forEach((src) => run(w, src));
  const $ = (sel) => w.document.querySelector(sel);
  const s = {
    w, ns, sent, handlers, $,
    last: () => sent[sent.length - 1],
    /** The finished answer of the request sent last, delivered the way Python's bridge does. */
    reply: (answer) => {
      const r = sent[sent.length - 1];
      handlers[r.action](Object.assign({}, { ok: true, result: Object.assign({ token: r.payload.token, pending: false, ok: true, result: null, message: '' }, answer) }));
    },
    save: () => $('.ic-save'),
    input: (id) => w.document.getElementById('f-' + id),
    type: (id, text) => { const e = s.input(id); e.value = text; e.dispatchEvent(new w.Event('input', { bubbles: true })); },
    message: () => $('.ic-message'),
  };
  return s;
}

const MAKE = field({ id: 'MAKE', title: 'Make or buy', kind: 'radio', options: [{ value: '/o/1', title: 'Make' }, { value: '/o/2', title: 'Buy' }] });
const ASSEMBLY = { form: formOf([NUMBER, TITLE, TYPE, MAKE]), locked: { MAKE: 'Make' }, number_field: 'NUMBER', can_create: true };

function openAssembly() {
  const s = setup();
  s.ns.pubItemPanel.open({ mode: 'assembly' });
  s.reply({ ok: true, result: ASSEMBLY });
  return s;
}

test('New item asks for the assembly form and draws it stacked, with required fields starred and the locked value shown in its section', { skip }, () => {
  const s = setup();
  s.ns.pubItemPanel.open({ mode: 'assembly' });
  assert.strictEqual(s.last().action, 'items_form');
  assert.strictEqual(s.last().payload.kind, 'assembly');
  assert.ok(s.$('.ic-dialog .loader'), 'it shows that it is reading');
  assert.strictEqual(s.save().disabled, true);
  s.reply({ ok: true, result: ASSEMBLY });
  assert.strictEqual(s.$('.ic-overlay').hidden, false);
  assert.strictEqual(s.$('.ic-title').textContent, 'Create New Manufacturing Item');
  assert.ok(s.$('.ic-head .ic-title-icon svg'), 'the icon of the button that opened it is in front of the title');
  const labels = [...s.w.document.querySelectorAll('.ic-dialog .pf-label')].map((l) => l.textContent);
  assert.deepStrictEqual(labels, ['* Item number', 'Title', 'Type', 'Make or buy']);
  assert.ok(s.$('.pf-label .form-star'), 'a required field has the star');
  assert.strictEqual(s.input('MAKE'), null, 'Make or buy is not a control');
  assert.strictEqual([...s.w.document.querySelectorAll('.ic-body .pf-field')].pop().querySelector('.form-auto').textContent, 'Make', 'it shows the value it will have, in its own section');
  assert.strictEqual(s.w.document.querySelectorAll('.ic-note').length, 0, 'there is no section of what the add-in sets');
  assert.strictEqual(s.save().disabled, false);
  assert.strictEqual(s.save().textContent, 'Create item');
});

test('Save checks the form, then sends the values once and stays off while the request runs', { skip }, () => {
  const s = openAssembly();
  const before = s.sent.length;
  s.save().click();
  assert.strictEqual(s.sent.length, before, 'a required field is empty: nothing is sent');
  assert.match(s.message().textContent, /Correct the fields/);
  assert.strictEqual(s.input('NUMBER').closest('.pf-field').querySelector('.pf-error').hidden, false);
  s.type('NUMBER', 'MFG-1');
  s.type('TITLE', 'Frame');
  s.save().click();
  s.save().click();
  assert.strictEqual(s.sent.length, before + 1, 'a second click makes no second request');
  assert.strictEqual(s.last().action, 'items_create');
  assert.deepStrictEqual(JSON.parse(JSON.stringify(s.last().payload.values)), { NUMBER: 'MFG-1', TITLE: 'Frame' });
  assert.strictEqual(s.save().disabled, true);
  assert.strictEqual(s.save().textContent, 'Creating...');
  assert.strictEqual(s.$('.ic-close').disabled, true, 'it cannot be closed while it is being made');
  s.reply({ ok: true, result: { id: '9', link: '/api/v3/workspaces/1/items/9', number: 'MFG-1' } });
  assert.match(s.$('.ic-saved').textContent, /Item MFG-1 was created in Fusion Manage\./);
  assert.strictEqual(s.save().hidden, true);
  assert.strictEqual(s.$('.ic-cancel').textContent, 'Close');
  s.$('.ic-cancel').click();
  assert.strictEqual(s.$('.ic-overlay').hidden, true);
});

test('a refused save keeps what was typed, shows each field named and the message, and Save works again', { skip }, () => {
  const s = openAssembly();
  s.type('NUMBER', 'MFG-1');
  s.type('TITLE', 'Frame');
  s.save().click();
  s.reply({ ok: false, message: 'Fusion Manage refused the item.', fields: { NUMBER: 'The number is taken.', ELSEWHERE: 'Not on the form.' } });
  assert.strictEqual(s.input('NUMBER').value, 'MFG-1');
  assert.strictEqual(s.input('TITLE').value, 'Frame');
  const error = s.input('NUMBER').closest('.pf-field').querySelector('.pf-error');
  assert.strictEqual(error.textContent, 'The number is taken.');
  assert.strictEqual(error.hidden, false);
  assert.match(s.message().textContent, /Fusion Manage refused the item\./);
  assert.match(s.message().textContent, /Not on the form\./, 'a field the form does not hold is said in the message');
  assert.strictEqual(s.save().disabled, false);
  assert.strictEqual(s.$('.ic-close').disabled, false);
  s.type('NUMBER', 'MFG-2');
  s.save().click();
  assert.deepStrictEqual(JSON.parse(JSON.stringify(s.last().payload.values)), { NUMBER: 'MFG-2', TITLE: 'Frame' });
});

test('a form that cannot be read says so, with a retry', { skip }, () => {
  const s = setup();
  s.ns.pubItemPanel.open({ mode: 'assembly' });
  s.reply({ ok: false, message: 'The Items workspace is not set.' });
  assert.match(s.$('.ic-body').textContent, /The Items workspace is not set\./);
  assert.strictEqual(s.save().disabled, true);
  const n = s.sent.length;
  s.$('.pub-retry').click();
  assert.strictEqual(s.sent.length, n + 1);
  assert.strictEqual(s.last().action, 'items_form');
});

test('without permission to add items Save is off and the reason is shown', { skip }, () => {
  const s = setup();
  s.ns.pubItemPanel.open({ mode: 'assembly' });
  s.reply({ ok: true, result: Object.assign({}, ASSEMBLY, { can_create: false }) });
  assert.strictEqual(s.save().disabled, true);
  assert.match(s.message().textContent, /do not have permission/);
});

const BOUGHT = {
  form: formOf([NUMBER, TITLE, TYPE, SUPPLIER, field({ id: 'LINKS', title: 'Related', kind: 'links', lookup: 'ITEMS' }), field({ id: 'SRC', title: 'Source', kind: 'link', lookup: 'ITEMS' })]),
  number_field: 'NUMBER',
  number: 'MFG-1-B',
  values: { TITLE: 'Frame', TYPE: '/o/2', SUPPLIER: { link: '/api/v3/lookups/SUPPLIERS/9' }, LINKS: [{ link: '/api/v3/workspaces/1/items/5' }] },
  copied: ['TITLE', 'TYPE', 'SUPPLIER', 'LINKS'],
  skipped: [{ field: 'NUMBER', reason: 'The number is the source number and the suffix.' }, { field: 'IMG', reason: 'Pictures are not copied.' }],
  locked: { NUMBER: 'MFG-1-B', SRC: 'MFG-1' },
  can_create: true,
  source_id: '17',
};

test('a bought version is opened with one request that carries the line, then shows its number read only, copies the values into the controls and says what is not copied', { skip }, () => {
  const s = setup();
  s.ns.pubItemPanel.open({ mode: 'bought', sourceNumber: 'MFG-1', number: 'MFG-1' });
  assert.strictEqual(s.last().action, 'bought_open', 'one request looks for a bought version and reads the form');
  assert.strictEqual(s.last().payload.source_number, 'MFG-1');
  const n = s.sent.length;
  s.reply({ ok: true, result: BOUGHT });
  assert.strictEqual(s.sent.length, n, 'nothing more is asked');
  assert.strictEqual(s.$('.ic-title').textContent, 'Create Purchased Version of MFG-1');
  const first = s.$('.ic-body .section .pf-field');
  assert.match(first.querySelector('.pf-label').textContent, /^Item number/, 'the number is in the first section, in its place');
  assert.strictEqual(first.querySelector('.form-auto').textContent, 'MFG-1-B');
  assert.strictEqual(s.input('NUMBER'), null, 'the number is not an input');
  assert.strictEqual([...s.w.document.querySelectorAll('.ic-body .form-auto')].pop().textContent, 'MFG-1', 'so is the source link, with what it will hold');
  assert.strictEqual(s.input('TITLE').value, 'Frame');
  assert.match(s.input('TYPE').textContent, /Beta/, 'an option given as its link is chosen');
  assert.match(s.input('SUPPLIER').querySelector('.pk-btn').textContent, /SUPPLIERS\/9/, 'a link is chosen');
  assert.strictEqual(s.w.document.querySelectorAll('.ic-body .section').length, 1, 'no section of what the add-in sets');
});

test('saving a bought version sends the source id the open gave, with the values, and shows the number it was given', { skip }, () => {
  const s = setup();
  s.ns.pubItemPanel.open({ mode: 'bought', sourceNumber: 'MFG-1', number: 'MFG-1' });
  s.reply({ ok: true, result: BOUGHT });
  s.type('TITLE', 'Frame bought');
  s.save().click();
  assert.strictEqual(s.last().action, 'bought_create');
  assert.strictEqual(s.last().payload.source_id, '17', 'the create is not left to search for the item number again');
  assert.strictEqual(s.last().payload.source_number, undefined);
  assert.deepStrictEqual(JSON.parse(JSON.stringify(s.last().payload.values)), { TITLE: 'Frame bought', TYPE: '/o/2', SUPPLIER: { link: '/api/v3/lookups/SUPPLIERS/9' }, LINKS: [{ link: '/api/v3/workspaces/1/items/5' }] });
  s.reply({ ok: false, message: 'MFG-1-B exists already.', fields: { NUMBER: 'The number is taken.' } });
  assert.match(s.message().textContent, /MFG-1-B exists already\./);
  assert.match(s.message().textContent, /The number is taken\./, 'the number is not a field of the form, so its refusal is in the message');
  s.save().click();
  s.reply({ ok: true, result: { id: '10', link: '/l', number: 'MFG-1-B' } });
  assert.match(s.$('.ic-saved').textContent, /Item MFG-1-B was created/);
});

test('answers are polled with items_status, and a picklist is read with search_options and polled with search_status', { skip }, async () => {
  const s = setup();
  s.ns.pubItemPanel.open({ mode: 'assembly' });
  const token = s.last().payload.token;
  s.handlers.items_form({ ok: true, result: { token, pending: true, ok: false } });
  await new Promise((resolve) => setTimeout(resolve, 300));
  assert.deepStrictEqual(JSON.parse(JSON.stringify(s.last())), { action: 'items_status', payload: { token } });
  s.handlers.items_status({ ok: true, result: { token, pending: false, ok: true, result: Object.assign({}, ASSEMBLY, { form: formOf([NUMBER, SUPPLIER]) }), message: '' } });
  s.$('.ic-body .pk-btn').click();   // opens the link picker, which reads the first page of its picklist
  const options = s.sent.filter((r) => r.action === 'search_options');
  assert.strictEqual(options.length, 1);
  assert.strictEqual(options[0].payload.lookup, 'SUPPLIERS');
  const t2 = options[0].payload.token;
  assert.strictEqual(s.ns.pubItemPanel.claims('search_options', { ok: true, result: { token: t2, pending: true } }), true, 'the answer is ours');
  await new Promise((resolve) => setTimeout(resolve, 300));
  assert.deepStrictEqual(JSON.parse(JSON.stringify(s.last())), { action: 'search_status', payload: { token: t2 } });
  const page = { options: [{ value: '/l/1', title: 'Acme' }], total: 1, raw: 1 };
  assert.strictEqual(s.ns.pubItemPanel.claims('search_status', { ok: true, result: { token: t2, pending: false, ok: true, result: page, message: '' } }), true);
  assert.match(s.$('.ic-body .pk-list').textContent, /Acme/);
  assert.strictEqual(s.ns.pubItemPanel.claims('search_status', { ok: true, result: { token: 'other', pending: false } }), false, 'the Add Items picker keeps its own answers');
});

test('the dialog cannot be closed while a save runs, and closing forgets the form', { skip }, () => {
  const s = openAssembly();
  s.type('NUMBER', 'MFG-1');
  s.save().click();
  s.ns.pubItemPanel.close();
  assert.strictEqual(s.$('.ic-overlay').hidden, false);
  s.reply({ ok: false, message: 'No.' });
  s.ns.pubItemPanel.close();
  assert.strictEqual(s.$('.ic-overlay').hidden, true);
  assert.strictEqual(s.$('.ic-body').children.length, 0);
});

test('each section of the form is a card that folds, and a section with a refused field is unfolded', { skip }, () => {
  const s = setup();
  s.ns.pubItemPanel.open({ mode: 'assembly' });
  const form = { sections: [
    { title: 'Basic', fields: [NUMBER, TITLE], matrices: [], collapsed: false },
    { title: 'Details', fields: [TYPE], matrices: [], collapsed: false }], left_out: [] };
  s.reply({ ok: true, result: { ...ASSEMBLY, form } });
  const cards = [...s.w.document.querySelectorAll('.ic-body .section')];
  assert.deepStrictEqual(cards.map((c) => c.querySelector('.section-title').textContent), ['Basic', 'Details']);
  assert.deepStrictEqual(cards.map((c) => c.classList.contains('folded')), [false, false]);
  cards[1].querySelector('.section-title').click();
  assert.ok(cards[1].classList.contains('folded'), 'a click on the bar folds it');
  s.type('NUMBER', 'MFG-1');
  s.save().click();
  s.reply({ ok: false, message: 'Refused.', fields: { TYPE: 'Choose a type.' } });
  assert.ok(!cards[1].classList.contains('folded'), 'the section of the refused field is open again');
});

test('a section the workspace folds starts folded, unless it holds a required field', { skip }, () => {
  const s = setup();
  s.ns.pubItemPanel.open({ mode: 'assembly' });
  const form = { sections: [
    { title: 'Basic', fields: [NUMBER, TITLE], matrices: [], collapsed: true },
    { title: 'Details', fields: [TYPE], matrices: [], collapsed: true },
    { title: 'Open', fields: [SUPPLIER], matrices: [], collapsed: false }], left_out: [] };
  s.reply({ ok: true, result: { ...ASSEMBLY, form } });
  const cards = [...s.w.document.querySelectorAll('.ic-body .section')];
  assert.deepStrictEqual(cards.map((c) => c.classList.contains('folded')), [false, true, false], 'Details is folded as the workspace has it; Basic holds a required field, so it is open');
});

test('a field of many radio buttons is drawn as a drop-down and a short one stays as radio buttons', { skip }, () => {
  const s = setup();
  s.ns.pubItemPanel.open({ mode: 'assembly' });
  const options = (n) => Array.from({ length: n }, (_, i) => ({ value: '/lookups/' + i, title: 'Option ' + i }));
  const many = { id: 'KIND', title: 'Kind', kind: 'radio', required: false, description: '', options: options(9), lookup: '', max_length: 0, validators: [] };
  const few = { ...many, id: 'SIZE', title: 'Size', options: options(3) };
  s.reply({ ok: true, result: { ...ASSEMBLY, form: formOf([NUMBER, many, few]) } });
  assert.ok(s.$('.ic-body .pk-btn'), 'nine options make a drop-down');
  assert.strictEqual(s.w.document.querySelectorAll('.ic-body .form-radio').length, 3, 'three options stay radio buttons');
});

test('a drop-down of the form has its search box in the field, over the button, and none at the top of the list', { skip }, () => {
  const s = setup();
  s.ns.pubItemPanel.open({ mode: 'assembly' });
  const options = Array.from({ length: 9 }, (_, i) => ({ value: '/lookups/' + i, title: 'Option ' + i }));
  const many = { id: 'KIND', title: 'Kind', kind: 'radio', required: false, description: '', options, lookup: '', max_length: 0, validators: [] };
  s.reply({ ok: true, result: { ...ASSEMBLY, form: formOf([NUMBER, many]) } });
  const wrap = s.$('.ic-body .pk-form');
  assert.ok(wrap.classList.contains('pk-inline'));
  assert.strictEqual(wrap.querySelector('.pk-menu .pk-search'), null, 'not in the list');
  assert.strictEqual(wrap.querySelector(':scope > .pk-search').parentNode, wrap, 'beside the button, in the wrapper');
  wrap.querySelector('.pk-btn').click();
  assert.ok(wrap.classList.contains('searching'), 'while it is open the search box covers the button text');
  wrap.querySelector('.pk-btn').click();
  assert.ok(!wrap.classList.contains('searching'));
});

const FOUND = { id: '9', link: '/api/v3/workspaces/1/items/9', number: 'MFG-1-B', name: 'Frame', url: 'https://acme.autodeskplm360.net/plm/workspaces/1/items/itemDetails?itemId=9' };

test('a bought version that exists is offered in the dialog; Use this item hands it over, closes and makes nothing', { skip }, () => {
  const s = setup();
  const used = [];
  s.ns.pubItemPanel.open({ mode: 'bought', sourceNumber: 'MFG-1', number: 'MFG-1', onFound: (item) => used.push(item.number) });
  s.reply({ ok: true, result: { found: FOUND } });
  assert.deepStrictEqual(s.sent.map((r) => r.action), ['bought_open'], 'it was one request, and the form is not painted');
  assert.strictEqual(s.w.document.querySelectorAll('.ic-body .section').length, 0);
  assert.match(s.$('.ic-found-lead').textContent, /A purchased version of MFG-1 already exists in Fusion Manage/);
  assert.strictEqual(s.$('.ic-found-number').textContent, 'MFG-1-B');
  assert.strictEqual(s.$('.ic-found-name').textContent, 'Frame');
  assert.strictEqual(s.$('.ic-found-ask').textContent, 'Do you want to use this item instead?');
  assert.doesNotMatch(s.$('.ic-body').textContent, /MBOM/);
  s.$('.ic-found-open').click();
  assert.deepStrictEqual(JSON.parse(JSON.stringify(s.last())), { action: 'open_url', payload: { url: FOUND.url } }, 'it opens the item in Fusion Manage');
  assert.strictEqual(s.save().textContent, 'Use this item');
  assert.strictEqual(s.save().disabled, false);
  s.save().click();
  assert.deepStrictEqual(used, ['MFG-1-B']);
  assert.strictEqual(s.$('.ic-overlay').hidden, true, 'the dialog is closed');
  assert.strictEqual(s.sent.filter((r) => r.action === 'bought_create').length, 0);
});

test('Cancel on the offer of an existing bought version uses nothing; a failed search can be tried again', { skip }, () => {
  const s = setup();
  const used = [];
  s.ns.pubItemPanel.open({ mode: 'bought', sourceNumber: 'MFG-1', number: 'MFG-1', onFound: (item) => used.push(item) });
  s.reply({ ok: false, message: 'Search is down' });
  assert.match(s.$('.ic-body').textContent, /Search is down/);
  s.$('.ic-body button').click();
  assert.strictEqual(s.last().action, 'bought_open', 'Try again looks again');
  s.reply({ ok: true, result: { found: FOUND } });
  s.$('.ic-cancel').click();
  assert.deepStrictEqual(used, []);
  assert.strictEqual(s.$('.ic-overlay').hidden, true);
});

test('a bought version that is saved tells onCreated; a refused save tells nobody', { skip }, () => {
  const s = setup();
  const made = [];
  s.ns.pubItemPanel.open({ mode: 'bought', sourceNumber: 'MFG-1', number: 'MFG-1', onCreated: (r) => made.push(r.number) });
  s.reply({ ok: true, result: BOUGHT });
  s.save().click();
  s.reply({ ok: false, message: 'No.', fields: {} });
  assert.deepStrictEqual(made, [], 'a refused save tells nobody');
  s.save().click();
  s.reply({ ok: true, result: { id: '10', link: '/l', number: 'MFG-1-B' } });
  assert.deepStrictEqual(made, ['MFG-1-B']);
});

test('a component with no item in Fusion Manage is told in the dialog, which looks for it when asked', { skip }, () => {
  const s = setup();
  s.ns.pubItemPanel.open({ mode: 'bought', sourceNumber: 'MFG-1', number: 'MFG-1' });
  s.reply({ ok: false, message: 'Item number MFG-1 is not in Fusion Manage yet. Publish it first, then make its bought version.' });
  assert.match(s.$('.ic-body').textContent, /not in Fusion Manage yet/);
  assert.strictEqual(s.save().disabled, true);
});
