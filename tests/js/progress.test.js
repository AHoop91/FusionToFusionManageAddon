// What the publish progress dialog says: no single item is "being processed" while several are prepared at once.
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const vm = require('vm');
const { run } = require('./helpers');

const window = vm.createContext({ console: console, Date: Date });
window.window = window;
window.MfgUi = {};
run(window, 'js/publish-jobs.js');
const describe = window.MfgUi.pubJobs.describe;
const tally = window.MfgUi.pubJobs.tally;
const validation = window.MfgUi.pubJobs.validation;
const elapsedText = window.MfgUi.pubJobs.elapsedText;
const line = window.MfgUi.pubJobs.line;
const listed = window.MfgUi.pubJobs.listed;

const job = (extra) => Object.assign({
  phase: 'running', stage: 'items', name: 'PN-1', total: 12, done: 0, counts: {}, sends: true, rows: [],
  started_at: 100, finished_at: 0,
}, extra);

test('a run that has just started says it is reading, not that it is processing an item', () => {
  const view = describe(job());
  assert.strictEqual(view.status, 'Reading the design and checking Fusion Manage.');
  assert.strictEqual(view.percent, 0);
});

test('a running publish says what it is doing and counts the items done', () => {
  const view = describe(job({ done: 5, rows: [{ status: 'running' }], started_at: 1 }));
  assert.strictEqual(view.status, 'Checking and updating items in Fusion Manage.');
  assert.strictEqual(view.count, '5 of 12 items');
  assert.strictEqual(view.percent, 42);
});

test('a run that only writes requests says it prepares them', () => {
  assert.match(describe(job({ done: 1, sends: false })).status, /preparing their requests/);
});

test('the Bill of Materials stage says so and the bar is full', () => {
  const view = describe(job({ stage: 'bom', done: 12 }));
  assert.strictEqual(view.status, 'Updating the Bill of Materials.');
  assert.strictEqual(view.percent, 100);
});

test('a finished publish says plainly that it is complete', () => {
  const view = describe(job({ phase: 'done', done: 12, counts: { update: 2, unchanged: 10 }, started_at: 100, finished_at: 107.9 }));
  assert.strictEqual(view.title, 'Publish complete');
  assert.strictEqual(view.status, 'PN-1 was published to Fusion Manage.');
  assert.strictEqual(view.count, '12 of 12 items');
  assert.strictEqual(view.tone, 'ok');
});

test('a finished run that only wrote requests says nothing has been sent', () => {
  const view = describe(job({ phase: 'done', done: 3, total: 3, sends: false, finished_at: 103 }));
  assert.strictEqual(view.title, 'Publish complete');
  assert.match(view.status, /^PN-1 is ready\. The requests were written for review; nothing has been sent/);
});

test('failures are counted and the reasons are in the Job Queue', () => {
  const rows = [{ status: 'error' }, { status: 'done' }];
  const view = describe(job({ phase: 'done', done: 12, counts: { update: 11 }, rows: rows, finished_at: 110 }));
  assert.strictEqual(view.title, 'Completed with errors');
  assert.strictEqual(view.status, '1 of 12 items failed. See the Job Queue for the reasons.');
});

const row = (status) => ({ status: status });
const items = (...statuses) => statuses.map(row);

test('the tally counts successful, failed and pending items however many there are', () => {
  assert.deepStrictEqual(Object.assign({}, tally(job({ total: 12 }))), { successful: 0, failed: 0, skipped: 0, pending: 12 });
  const rows = items('done', 'done', 'error', 'running', 'running', 'queued');
  assert.deepStrictEqual(Object.assign({}, tally(job({ total: 6, done: 3, rows: rows }))), { successful: 2, failed: 1, skipped: 0, pending: 3 });
  assert.deepStrictEqual(Object.assign({}, tally(job({ total: 5000, done: 4990, rows: [] }))), { successful: 4990, failed: 0, skipped: 0, pending: 10 });
});

test('items left out on purpose are counted as skipped, not as successful', () => {
  const view = tally(job({ total: 4, done: 4, counts: { update: 1, unchanged: 1, skipped: 2 }, rows: items('done', 'done', 'done', 'done') }));
  assert.deepStrictEqual(Object.assign({}, view), { successful: 2, failed: 0, skipped: 2, pending: 0 });
});

test('a failed Bill of Materials row is a failure, not an item', () => {
  const rows = items('done', 'done', 'error');   // the last is the Bill of Materials row of a run of two items
  const finished = job({ phase: 'done', total: 2, done: 2, rows: rows, finished_at: 110 });
  assert.deepStrictEqual(Object.assign({}, tally(finished)), { successful: 2, failed: 1, skipped: 0, pending: 0 });
  assert.strictEqual(describe(finished).status, 'The Bill of Materials was not updated. See the Job Queue for the reasons.');
});

test('a cancelled run leaves the items it did not reach pending', () => {
  assert.strictEqual(tally(job({ phase: 'cancelled', total: 12, done: 4 })).pending, 8);
});

test('the elapsed time counts up on a clock while the job runs and stops when it ends', () => {
  const now = Date.now() / 1000;
  assert.strictEqual(elapsedText(job({ started_at: now - 7.4 })), 'Elapsed 0:07');
  assert.strictEqual(elapsedText(job({ started_at: 100, finished_at: 107.9 })), 'Elapsed 0:07', 'it stays at what it was when the job ended');
  assert.strictEqual(elapsedText(job({ started_at: 100, finished_at: 725 })), 'Elapsed 10:25');
  assert.strictEqual(elapsedText(job({ started_at: 1, finished_at: 3700 })), 'Elapsed 1:01:39');
});

test('a job that has not started has no elapsed time', () => {
  assert.strictEqual(elapsedText(job({ phase: 'queued', started_at: 0 })), '');
  assert.strictEqual(elapsedText(null), '');
});

test('while the item numbers are looked up the validation bar fills and publishing waits', () => {
  const looking = job({ stage: 'validating', validation: { done: 10, total: 40 } });
  assert.deepStrictEqual(JSON.parse(JSON.stringify(validation(looking))), { percent: 25, count: '10 of 40 item numbers', tone: '' });
  const view = describe(looking);
  assert.match(view.status, /Looking up every item number/);
  assert.strictEqual(view.percent, 0, 'nothing is published until the numbers are checked');
});

test('once the items are being published the validation bar is full and green', () => {
  const check = validation(job({ stage: 'items', validation: { done: 40, total: 40 } }));
  assert.deepStrictEqual(JSON.parse(JSON.stringify(check)), { percent: 100, count: '40 item numbers checked', tone: 'ok' });
});

test('a run that fails in the validation shows it there and leaves publishing empty', () => {
  const failed = job({ phase: 'error', stage: 'validating', message: 'PN-1 is shared', validation: { done: 40, total: 40 } });
  assert.strictEqual(validation(failed).tone, 'error');
  const view = describe(failed);
  assert.strictEqual(view.percent, 0);
  assert.strictEqual(view.tone, '');
  assert.strictEqual(view.status, 'PN-1 is shared');
});

test('a run that fails after the validation passed keeps the validation green', () => {
  const failed = job({ phase: 'error', stage: 'items', validation: { done: 3, total: 3 } });
  assert.strictEqual(validation(failed).tone, 'ok');
  assert.strictEqual(describe(failed).tone, 'error');
});

test('with nothing to look up the validation is indeterminate until it ends', () => {
  assert.strictEqual(validation(job({ stage: 'validating', validation: { done: 0, total: 0 } })).percent, null);
  assert.strictEqual(validation(job({ stage: 'items', validation: { done: 0, total: 0 } })).percent, 100);
});

test('the Job Queue says in a sentence where each job stands', () => {
  assert.strictEqual(line(job({ phase: 'queued', place: 2 })), 'Waiting, number 2 in the queue.');
  assert.strictEqual(line(job({ done: 3 })), 'Publishing 3 of 12 items.');
  assert.strictEqual(line(job({ stage: 'validating' })), 'Checking item numbers.');
  assert.strictEqual(line(job({ phase: 'cancelled', total: 5, done: 0 })), 'Cancelled. Nothing was published.');
  assert.strictEqual(line(job({ phase: 'cancelled', total: 5, done: 2 })), 'Cancelled. 2 of 5 items published.');
  assert.strictEqual(line(job({ phase: 'error', total: 5, done: 5, rows: [{ status: 'error' }, { status: 'error' }, { status: 'done' }, { status: 'done' }, { status: 'done' }] })), 'Failed. 2 of 5 items failed.');
});

test('a job that went through leaves the Job Queue, and a cancelled or failed one stays', () => {
  assert.strictEqual(listed(job({ phase: 'done', rows: [{ status: 'done' }] })), false);
  assert.strictEqual(listed(job({ phase: 'cancelled' })), true);
  assert.strictEqual(listed(job({ phase: 'error', stage: 'items' })), true);
  assert.strictEqual(listed(job({ phase: 'done', rows: [{ status: 'error' }] })), true);
  assert.strictEqual(listed(job({ phase: 'error', stage: 'validating' })), false);
});

test('the Publishing bar runs through the items and then the Bill of Materials requests, as one', () => {
  const at = (fields) => describe(job({ phase: 'running', sends: true, total: 12, ...fields })).percent;
  assert.strictEqual(at({ stage: 'items', done: 6, bom: { done: 0, total: 4 } }), 38, '6 of the 16 steps');
  assert.strictEqual(at({ stage: 'bom', done: 12, bom: { done: 0, total: 4 } }), 75, 'the items are done, the requests are not');
  assert.strictEqual(at({ stage: 'bom', done: 12, bom: { done: 1, total: 4 } }), 81);
  assert.strictEqual(at({ stage: 'items', done: 6, sends: false, bom: { done: 0, total: 4 } }), 50, 'a job that does not send has no requests to wait for');
  const sending = job({ stage: 'bom', done: 12, bom: { done: 1, total: 4 } });
  assert.match(line(sending), /Bill of Materials, 1 of 4 requests/);
});
