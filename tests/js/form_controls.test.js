// The shared form controls (shared/js/form-controls.js): one control for each kind of field of a WorkspaceFormService spec, run in jsdom.
// Needs jsdom (``npm install jsdom``); without it these tests are skipped.
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { run, englishI18n } = require('./helpers');

let JSDOM = null;
try { JSDOM = require('jsdom').JSDOM; } catch (error) { /* skipped below */ }
const skip = JSDOM ? false : 'jsdom is not installed (npm install jsdom)';

/** A window with the shared scripts the module needs, and a form made with ``ask`` standing in for Python. */
function setup(ask) {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { runScripts: 'outside-only' });
  const w = dom.window;
  w.MfgUi = { i18n: englishI18n() };
  ['dom.js', 'picker.js', 'validators.js', 'form-controls.js'].forEach((src) => run(w, '../shared/js/' + src));
  const fc = w.MfgUi.formControls.make({ ask: ask || (() => {}), failure: (a) => a.message, openLightbox: () => {} });
  return { w, fc };
}

function spec(over) {
  return Object.assign({ id: 'F', title: 'Field', kind: 'text', required: false, description: '', options: [], lookup: '', max_length: 0, validators: [] }, over);
}

/** Add ``field`` to the form in a line of its own, as a page does, and answer its record. */
function place(s, field) {
  const line = s.fc.fieldLine(field);
  const record = s.fc.addField(field, line.row);
  s.fc.fillLine(line, record);
  s.w.document.body.appendChild(line.row);
  return record;
}

test('each plain kind gets its own control', { skip }, () => {
  const s = setup();
  const kinds = { text: 'INPUT', textarea: 'TEXTAREA', integer: 'INPUT', number: 'INPUT', date: 'INPUT', checkbox: 'INPUT' };
  Object.keys(kinds).forEach((kind) => {
    assert.strictEqual(s.fc.control(spec({ id: kind, kind })).tagName, kinds[kind], kind);
  });
  assert.strictEqual(s.fc.control(spec({ id: 'a', kind: 'integer' })).step, '1');
  assert.strictEqual(s.fc.control(spec({ id: 'b', kind: 'number' })).step, 'any');
  assert.strictEqual(s.fc.control(spec({ id: 'c', kind: 'date' })).type, 'date');
  assert.strictEqual(s.fc.control(spec({ id: 'd', kind: 'checkbox' })).type, 'checkbox');
});

test('radio, select, link, links and image controls', { skip }, () => {
  const s = setup();
  const options = [{ value: '/o/1', title: 'One' }, { value: '/o/2', title: 'Two' }];
  const radio = s.fc.control(spec({ id: 'R', kind: 'radio', options }));
  assert.strictEqual(radio.getAttribute('role'), 'radiogroup');
  assert.strictEqual(radio.querySelectorAll('input[type=radio]').length, 2);
  const select = s.fc.control(spec({ id: 'S', kind: 'select', options }));
  assert.ok(select.getValue && select.setValue && select.querySelector('.pk-btn'));
  assert.ok(s.fc.control(spec({ id: 'L', kind: 'link', lookup: 'X' })).getValue);
  assert.ok(s.fc.control(spec({ id: 'M', kind: 'links', lookup: 'X' })).getValue);
  assert.ok(s.fc.control(spec({ id: 'I', kind: 'image' })).querySelector('input[type=file]'));
});

test('values are read out as the form sends them', { skip }, () => {
  const s = setup();
  const options = [{ value: '/o/1', title: 'One' }, { value: '/o/2', title: 'Two' }];
  const text = place(s, spec({ id: 'T' }));
  text.input.value = '  hello ';
  assert.strictEqual(s.fc.valueOf(text), 'hello');
  const box = place(s, spec({ id: 'C', kind: 'checkbox' }));
  assert.strictEqual(s.fc.valueOf(box), '');
  box.input.checked = true;
  assert.strictEqual(s.fc.valueOf(box), true);
  const radio = place(s, spec({ id: 'R', kind: 'radio', options }));
  assert.strictEqual(s.fc.valueOf(radio), '');
  radio.input.querySelectorAll('input')[1].checked = true;
  assert.strictEqual(s.fc.valueOf(radio), '/o/2');
  const select = place(s, spec({ id: 'S', kind: 'select', options }));
  assert.strictEqual(s.fc.valueOf(select), '');
  s.fc.setFieldValue(select, { link: '/o/1', title: 'One' });
  assert.strictEqual(s.fc.valueOf(select), '/o/1');
  const link = place(s, spec({ id: 'L', kind: 'link', lookup: 'X' }));
  s.fc.setFieldValue(link, { link: '/x/9', title: 'Nine' });
  assert.strictEqual(JSON.stringify(s.fc.valueOf(link)), '{"link":"/x/9"}');
  const links = place(s, spec({ id: 'M', kind: 'links', lookup: 'X' }));
  s.fc.setFieldValue(links, [{ link: '/x/1', title: 'One' }, { link: '/x/2', title: 'Two' }]);
  assert.strictEqual(JSON.stringify(s.fc.valueOf(links)), '[{"link":"/x/1"},{"link":"/x/2"}]');
  const date = place(s, spec({ id: 'D', kind: 'date' }));
  s.fc.setFieldValue(date, '2026-03-04T00:00:00Z');
  assert.strictEqual(s.fc.valueOf(date), '2026-03-04');
});

test('a field with a limit shows a count and stops at it', { skip }, () => {
  const s = setup();
  const record = place(s, spec({ id: 'T', max_length: 5 }));
  assert.strictEqual(record.input.control.maxLength, 5);
  assert.strictEqual(record.input.querySelector('.fc-count').textContent, '0 / 5');
  record.input.control.value = 'abcd';
  record.input.control.dispatchEvent(new s.w.Event('input', { bubbles: true }));
  assert.strictEqual(record.input.querySelector('.fc-count').textContent, '4 / 5');
  assert.strictEqual(s.fc.valueOf(record), 'abcd');
});

test('a required field is starred in its label', { skip }, () => {
  const s = setup();
  const needed = s.fc.fieldLine(spec({ title: 'Name', required: true }));
  assert.strictEqual(needed.label.querySelector('.form-star').textContent, '* ');
  assert.strictEqual(needed.label.textContent, '* Name');
  assert.strictEqual(s.fc.fieldLine(spec({ title: 'Name' })).label.querySelector('.form-star'), null);
  assert.ok(s.fc.fieldLine(spec({ kind: 'textarea' })).row.classList.contains('top'));
});

test('a message shows under a field that is not right, and goes when it is put right', { skip }, () => {
  const s = setup();
  const record = place(s, spec({ id: 'T', title: 'Name', required: true }));
  assert.match(s.fc.showState(record), /Name/);
  assert.strictEqual(record.error.hidden, false);
  assert.ok(record.wrap.classList.contains('invalid'));
  record.input.value = 'x';
  record.input.dispatchEvent(new s.w.Event('input', { bubbles: true }));   // an invalid field is checked again as it is edited
  assert.strictEqual(record.error.hidden, true);
  assert.ok(!record.wrap.classList.contains('invalid'));
});

test('collect gathers the non-blank values and the first field that is wrong', { skip }, () => {
  const s = setup();
  const a = place(s, spec({ id: 'A', title: 'A', required: true }));
  const b = place(s, spec({ id: 'B', title: 'B' }));
  b.input.value = 'kept';
  let got = s.fc.collect();
  assert.strictEqual(got.first, a);
  assert.strictEqual(JSON.stringify(got.values), '{"B":"kept"}');
  assert.strictEqual(a.error.hidden, false);
  a.input.value = 'now';
  got = s.fc.collect();
  assert.strictEqual(got.first, null);
  assert.strictEqual(JSON.stringify(got.values), '{"A":"now","B":"kept"}');
  assert.strictEqual(s.fc.readiness().open, 0);
});

test('readiness counts what is required and empty, and what is entered wrongly', { skip }, () => {
  const s = setup();
  place(s, spec({ id: 'A', title: 'A', required: true }));
  const n = place(s, spec({ id: 'N', title: 'N', kind: 'integer', validators: [{ name: 'integer', variables: {} }] }));
  assert.strictEqual(s.fc.readiness().open, 1);
  n.input.type = 'text';
  n.input.value = 'abc';
  const now = s.fc.readiness();
  assert.strictEqual(now.open, 2);
  assert.strictEqual(now.problems.length, 1);
});

test('refusals from Fusion Manage show under the fields they name', { skip }, () => {
  const s = setup();
  place(s, spec({ id: 'A', title: 'A' }));
  const b = place(s, spec({ id: 'B', title: 'B' }));
  assert.strictEqual(s.fc.showRefusals({ B: 'Must be unique' }), b);
  assert.strictEqual(b.error.textContent, 'Must be unique');
  assert.ok(b.wrap.classList.contains('invalid'));
  assert.strictEqual(s.fc.showRefusals({}), null);
});

test('a link picker asks for its options; auto and info pieces', { skip }, () => {
  const asked = [];
  const s = setup((action, payload, done) => asked.push({ action, payload, done }));
  const input = s.fc.control(spec({ id: 'L', kind: 'link', lookup: 'LK' }));
  s.w.document.body.appendChild(input);
  input.querySelector('.pk-btn').click();
  assert.ok(asked.length >= 1);
  assert.strictEqual(asked[0].action, 'products_options');
  assert.strictEqual(asked[0].payload.lookup, 'LK');
  const auto = s.fc.autoBox(spec({ kind: 'auto', description: 'Filled in.' }));
  assert.strictEqual(auto.textContent, 'Filled in.');
  assert.strictEqual(auto.getAttribute('aria-disabled'), 'true');
  assert.strictEqual(s.fc.infoIcon('About').title, 'About');
});

test('a held picture is asked for and shown but not sent again; reset forgets the fields', { skip }, () => {
  const asked = [];
  const s = setup((action, payload, done) => asked.push({ action, payload, done }));
  const image = place(s, spec({ id: 'I', kind: 'image' }));
  s.fc.setFieldValue(image, { link: '/pic/1' }, () => true);
  assert.strictEqual(asked[0].action, 'products_picture');
  asked[0].done({ ok: true, result: { image: 'data:image/png;base64,AA' } });
  assert.strictEqual(image.input.querySelector('.im-picture').hidden, false);
  assert.strictEqual(s.fc.valueOf(image), '');
  assert.strictEqual(s.fc.fields.length, 1);
  s.fc.reset();
  assert.strictEqual(s.fc.fields.length, 0);
});
