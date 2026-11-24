// The Make or buy section of the Items card in Settings (settings/js/workspaces.js and validation.js), run in jsdom.
// Needs jsdom (``npm install jsdom``); without it these tests are skipped.
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { run, englishI18n } = require('./helpers');

let JSDOM = null;
try { JSDOM = require('jsdom').JSDOM; } catch (error) { /* skipped below */ }
const skip = JSDOM ? false : 'jsdom is not installed (npm install jsdom)';

const MAKE = '/api/v3/lookups/MB/options/1';
const BUY = '/api/v3/lookups/MB/options/2';
const FIELDS = [
  { id: 'NUMBER', title: 'Number', type: 'Single Line Text', picklist: '', link_lookup: '', section: 'General', section_order: 0 },
  { id: 'WEIGHT', title: 'Weight', type: 'Single Line Text', picklist: '', link_lookup: '', section: 'Physical', section_order: 1, field_order: 1 },
  { id: 'COLOUR', title: 'Colour', type: 'Single Line Text', picklist: '', link_lookup: '', section: 'Physical', section_order: 1, field_order: 0 },
  { id: 'HIDDEN', title: 'Hidden', type: 'Single Line Text', picklist: '', link_lookup: '', section: 'Physical', section_order: 1, shown: false },
  { id: 'SUM', title: 'Sum', type: 'Single Line Text', picklist: '', link_lookup: '', section: 'Physical', section_order: 1, computed: true },
  { id: 'MB', title: 'Make or buy', type: 'Radio Button', picklist: 'MB', link_lookup: '' },
  { id: 'SOURCE', title: 'Source item', type: 'Single Line Text', picklist: '', link_lookup: 'ITEMS' },
  { id: 'COMP', title: 'Component', type: 'Single Line Text', picklist: '', link_lookup: 'CLOOKUP' },
];
const PICKLISTS = { MB: [{ value: MAKE, title: 'Make' }, { value: BUY, title: 'Buy' }] };

/** The settings page's own parts that workspaces.js reads, with the workspace already validated so the Items card is open. */
function setup(makeBuy) {
  const dom = new JSDOM('<!doctype html><html><body><div id="sub-workspaces" class="tab-panel active"><div class="ws-busy" hidden></div><div id="workspace-cards"></div></div>' +
    '<div id="sub-portfolio" class="tab-panel"><div class="ws-busy" hidden></div><div id="portfolio-cards"></div></div><div id="bar" hidden></div></body></html>', { runScripts: 'outside-only' });
  const w = dom.window;
  w.HTMLElement.prototype.scrollIntoView = () => {};   // jsdom has none; the picker scrolls its chosen item into view
  const handlers = {};
  const sent = [];
  w.MfgUi = { i18n: englishI18n() };
  ['dom.js', 'picker.js', 'section.js'].forEach((src) => run(w, '../shared/js/' + src));
  w.MfgUi.bridge = { on: (name, fn) => { handlers[name] = fn; }, send: (name, data) => sent.push([name, data]), expect: () => () => {} };
  w.MfgUi.settings = { roleState: () => 'admin' };
  ['info.js', 'validation.js', 'workspaces.js'].forEach((src) => run(w, '../settings/js/' + src));
  w.MfgUi.workspaces.init();
  const kind = { id: 'items', title: 'Items', description: 'Items.', component_lookup: 'CLOOKUP', mapped: true, default_mappings: [] };
  w.MfgUi.workspaces.render({
    catalog: { kinds: [kind], source_fields: [] },
    workspaces: { items: { workspace_id: '5', mappings: [], static_values: [], component_field: 'COMP', enabled: true, make_buy: makeBuy } },
  });
  return { w, handlers, sent, validate: () => handlers.validate_workspace({ ok: true, result: {
    kind: 'items', workspace_id: '5', pending: false, valid: true, message: '', fields: FIELDS, picklists: PICKLISTS, grid_fields: [], grid_error: '' } }) };
}

const SAVED = { field: 'MB', make_value: MAKE, buy_value: BUY, source_field: 'SOURCE', suffix: '-B', skip_fields: ['NUMBER'] };

test('the Items card has a Make or buy section with a tip on each of its controls', { skip }, () => {
  const s = setup(SAVED);
  const section = s.w.document.querySelector('.ws-mb');
  assert.ok(section);
  assert.strictEqual(section.querySelector('.ws-heading').textContent, 'Make or buy');
  ['.ws-mb-field', '.ws-mb-make', '.ws-mb-buy', '.ws-mb-source', '.ws-mb-suffix', '.ws-mb-copy'].forEach((c) => assert.ok(section.querySelector(c), c));
  assert.strictEqual(section.querySelectorAll('.ws-block:not(.ws-pair)').length, 6);
  assert.deepStrictEqual([...section.querySelectorAll('.ws-pair .ws-block-name')].map((n) => n.textContent), ['Make value', 'Buy value'], 'the two values sit side by side');
  assert.strictEqual(section.querySelectorAll('.ws-block-namebox .tip').length, 6);   // an info tip per control
  assert.match(section.textContent, /ABC123-B/);
  assert.strictEqual(section.querySelector('.ws-mb-suffix').maxLength, 20);
});

test('read() sends the five settings, and none when the card has no section', { skip }, () => {
  const s = setup(SAVED);
  assert.strictEqual(JSON.stringify(s.w.MfgUi.workspaces.read().items.make_buy), JSON.stringify(SAVED));
  s.w.document.querySelector('.ws-mb').remove();
  assert.ok(!('make_buy' in s.w.MfgUi.workspaces.read().items));
});

test('an Items card saved before Make or buy existed reads back empty settings', { skip }, () => {
  const s = setup(undefined);
  const made = s.w.MfgUi.workspaces.read().items.make_buy;
  assert.strictEqual(JSON.stringify(made), JSON.stringify({ field: '', make_value: '', buy_value: '', source_field: '', suffix: '', skip_fields: [] }));
});

test('the pickers list the picklist fields, the linking fields and the options of the chosen field', { skip }, () => {
  const s = setup(SAVED);
  s.validate();
  const doc = s.w.document;
  const items = (selector) => {
    const wrap = doc.querySelector(selector).parentNode;
    wrap.querySelector('.pk-btn').click();
    const labels = Array.from(wrap.querySelectorAll('.pk-item')).map((i) => i.textContent);
    wrap.querySelector('.pk-btn').click();
    return labels;
  };
  assert.deepStrictEqual(items('.ws-mb-field').map((l) => l.split('MB')[0]), ['Make or buy']);   // only a picklist field
  assert.strictEqual(items('.ws-mb-source').length, 2);   // both fields that link: the source item and the component
  assert.deepStrictEqual(items('.ws-mb-make'), ['Make', 'Buy']);
  // The saved values show as the options' titles once the workspace is validated.
  assert.strictEqual(doc.querySelector('.ws-mb-make').parentNode.querySelector('.pk-text').textContent, 'Make');
  assert.strictEqual(doc.querySelector('.ws-mb-buy').parentNode.querySelector('.pk-text').textContent, 'Buy');
});

test('choosing another field clears the two values', { skip }, () => {
  const s = setup(SAVED);
  s.validate();
  const doc = s.w.document;
  doc.querySelector('.ws-mb-field').parentNode.dispatchEvent(new s.w.Event('pick'));
  assert.strictEqual(doc.querySelector('.ws-mb-make').value, '');
  assert.strictEqual(doc.querySelector('.ws-mb-buy').value, '');
  assert.strictEqual(doc.querySelector('.ws-mb-field').value, 'MB');
});

test('validating again keeps the saved values', { skip }, () => {
  const s = setup(SAVED);
  s.validate();
  s.validate();
  assert.strictEqual(s.w.document.querySelector('.ws-mb-make').value, MAKE);
  assert.strictEqual(s.w.document.querySelector('.ws-mb-buy').value, BUY);
});

test('the suffix drops characters an item number cannot hold', { skip }, () => {
  const s = setup(SAVED);
  const suffix = s.w.document.querySelector('.ws-mb-suffix');
  suffix.value = '-B 1/x*';
  suffix.dispatchEvent(new s.w.Event('input'));
  assert.strictEqual(suffix.value, '-B1x');
});

test('the Make or buy section is locked until the workspace is validated', { skip }, () => {
  const s = setup(SAVED);
  const box = s.w.document.querySelector('.ws-mb .ws-locked');
  assert.strictEqual(box.disabled, true);
  s.validate();
  assert.strictEqual(box.disabled, false);
});

test('the Make or buy section is on the Items card only', { skip }, () => {
  const s = setup(SAVED);
  s.w.MfgUi.workspaces.render({
    catalog: { kinds: [{ id: 'products', title: 'Products', description: 'P.', assign: true, mapped: false }], source_fields: [] },
    workspaces: { products: { workspace_id: '', variants: { link_column: '' } } },
  });
  assert.strictEqual(s.w.document.querySelectorAll('.ws-mb').length, 0);
});

test('a Make or buy problem marks its own control and goes away when the control is put right', { skip }, () => {
  const s = setup({ field: 'MB', make_value: MAKE, buy_value: MAKE, source_field: 'SOURCE', suffix: '' });
  s.validate();
  const bar = s.w.document.getElementById('bar');
  const where = (part) => ({ workspace: 'items', area: 'make_buy', row: 0, part: part });
  s.w.MfgUi.validation.show(bar, [
    { message: 'Make or buy: the Make value and the Buy value must differ.', where: where('buy_value') },
    { message: 'Make or buy: the suffix can hold letters.', where: where('suffix') },
    { message: 'Make or buy: choose the field.', where: where('field') },
  ]);
  const doc = s.w.document;
  assert.ok(doc.querySelector('.ws-mb-buy').parentNode.classList.contains('invalid'));
  assert.ok(doc.querySelector('.ws-mb-suffix').classList.contains('invalid'));
  assert.ok(doc.querySelector('.ws-mb-field').parentNode.classList.contains('invalid'));
  assert.strictEqual(doc.querySelectorAll('.ws-mb .field-error').length, 3);
  assert.strictEqual(doc.querySelector('.ws-mb-suffix').nextElementSibling.textContent, 'The suffix can hold letters.');
  const suffix = doc.querySelector('.ws-mb-suffix');
  suffix.value = '-B';
  suffix.dispatchEvent(new s.w.Event('input'));
  assert.ok(!suffix.classList.contains('invalid'));
  assert.strictEqual(doc.querySelectorAll('.ws-mb .field-error').length, 2);
});

test('a field used twice marks the source field when that is the one that clashes', { skip }, () => {
  const s = setup({ field: 'MB', make_value: MAKE, buy_value: BUY, source_field: 'COMP', suffix: '-B' });   // COMP is also the Component field
  const bar = s.w.document.getElementById('bar');
  s.w.MfgUi.validation.show(bar, [{ message: 'The source link field: COMP is filled twice.',
    where: { workspace: 'items', area: 'make_buy', row: 0, part: 'field' } }]);
  assert.ok(s.w.document.querySelector('.ws-mb-source').parentNode.classList.contains('invalid'));
  assert.ok(!s.w.document.querySelector('.ws-mb-field').parentNode.classList.contains('invalid'));
});

test('the Items settings are cards that fold: Make or buy starts folded and a problem in it opens it', { skip }, () => {
  const s = setup(SAVED);
  s.validate();
  const doc = s.w.document;
  const cards = [...doc.querySelectorAll('.ws-fold')];
  assert.deepStrictEqual(cards.map((c) => c.querySelector('.section-title').textContent), ['Linking and mapping', 'Additional functionality']);
  const make = doc.querySelector('.ws-mb').closest('.section');
  assert.ok(make.classList.contains('folded'), 'rarely changed: folded to begin with');
  assert.ok(!cards[0].classList.contains('folded'));
  assert.deepStrictEqual([...cards[0].querySelectorAll('.ws-heading')].map((h) => h.textContent), ['Component linking', 'Field mapping'], 'the two are one card');
  make.querySelector('.section-title').click();
  assert.ok(!make.classList.contains('folded'), 'the bar opens it');
  make.querySelector('.section-title').click();
  s.w.MfgUi.validation.show(doc.getElementById('bar'), [{ message: 'Make or buy: choose the field.', where: { workspace: 'items', area: 'make_buy', row: 0, part: 'field' } }]);
  assert.ok(!make.classList.contains('folded'), 'a problem found in it opens it');
});

test('a card of the settings still folds and opens when its fieldset is disabled (Enabled off, or a member who may only look)', { skip }, () => {
  const s = setup(SAVED);
  const doc = s.w.document;
  doc.querySelector('.pf-rest').disabled = true;
  const make = doc.querySelector('.ws-mb').closest('.section');
  const bar = make.querySelector('.section-title');
  bar.dispatchEvent(new s.w.MouseEvent('click', { bubbles: true }));
  assert.ok(!make.classList.contains('folded'), 'the bar is not a button, which a disabled fieldset would block');
  bar.dispatchEvent(new s.w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  assert.ok(make.classList.contains('folded'), 'and it answers the keyboard');
});

test('the fields to copy are a checklist, all ticked, with what the add-in sets locked and what is unticked saved', { skip }, () => {
  const s = setup(Object.assign({}, SAVED, { skip_fields: ['NUMBER'] }));
  s.validate();
  const doc = s.w.document;
  const list = doc.querySelector('.ws-mb-copy');
  const row = (id) => list.querySelector('input[data-id="' + id + '"]');
  const head = (title) => [...list.querySelectorAll('.ws-copy-head')].find((h) => h.querySelector('.ws-copy-title').textContent === title);
  assert.ok(!row('MB'), 'what the add-in sets is folded to begin with');
  head('Set by the add-in').click();
  assert.ok(row('MB').disabled && row('MB').checked, 'Make or buy is set by the add-in: locked');
  assert.ok(row('SOURCE').disabled && row('COMP').disabled, 'so are the source link and the component link');
  assert.ok(!row('NUMBER').checked, 'what was saved as left out is unticked');
  assert.ok(!row('HIDDEN') && !row('SUM'), 'a hidden field and a computed one are not offered');
  assert.deepStrictEqual([...list.querySelectorAll('.ws-copy-group')[2].querySelectorAll('input[data-id]')].map((i) => i.dataset.id), ['COLOUR', 'WEIGHT'], 'the fields are in the order of their section');
  assert.strictEqual(list.querySelector('.ws-copy-count').textContent, '2 of 3 fields copied', 'the footer says how many');
  assert.deepStrictEqual([...list.querySelectorAll('.ws-copy-title')].map((n) => n.textContent), ['Set by the add-in', 'General', 'Physical'], 'the sections of the form, the add-in own first');
  row('NUMBER').click();
  assert.ok(row('NUMBER').checked);
  assert.strictEqual(JSON.stringify(s.w.MfgUi.workspaces.read().items.make_buy.skip_fields), '[]', 'all ticked saves nothing left out');
  row('NUMBER').click();
  assert.strictEqual(JSON.stringify(s.w.MfgUi.workspaces.read().items.make_buy.skip_fields), '["NUMBER"]');
  const search = list.querySelector('.ws-copy-search');
  search.value = 'zzz';
  search.dispatchEvent(new s.w.Event('input'));
  assert.strictEqual(list.querySelectorAll('input[type=checkbox]').length, 0, 'the search narrows the list');
  search.value = '';
  search.dispatchEvent(new s.w.Event('input'));
  head('Physical').click();
  assert.ok(!row('WEIGHT'), 'a section folds');
  head('Physical').click();
  assert.ok(row('WEIGHT'), 'and opens');
  head('Physical').querySelector('input').click();
  assert.ok(!row('WEIGHT').checked && !row('COLOUR').checked, 'the tick of a section unticks all of it');
  [...list.querySelectorAll('.ws-copy-btn')].find((b) => /Untick all/.test(b.textContent)).click();
  assert.ok(s.w.MfgUi.workspaces.read().items.make_buy.skip_fields.includes('NUMBER'));
  assert.ok(!s.w.MfgUi.workspaces.read().items.make_buy.skip_fields.includes('MB'), 'a locked field is never left out');
});
