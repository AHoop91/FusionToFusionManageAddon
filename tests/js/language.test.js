// The language card of the settings panel (settings/js/language.js), driven in jsdom against a fake Python.
// Needs jsdom (``npm install jsdom``); without it these tests are skipped.
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { englishI18n, run } = require('./helpers');

let JSDOM = null;
try { JSDOM = require('jsdom').JSDOM; } catch (error) { /* skipped below */ }
const skip = JSDOM ? false : 'jsdom is not installed (npm install jsdom)';

const STATE = {
  code: 'en',
  restart: false,
  languages: [{ code: 'en', name: 'English', source: 'shipped' }],
  user_dir: 'C:\\Users\\me\\AppData\\Roaming\\MfgToFm\\languages',
  shipped_dir: '',
};

function openCard(role) {
  const dom = new JSDOM('<!doctype html><html><body><div id="lang-slot-tab"></div><div id="lang-slot-login"></div>' +
    '<div id="lang-banner" hidden></div><button id="lang-restart-btn"></button><button class="tab" data-tab="language"></button><button id="lang-save-btn"></button><button id="lang-save-publish-btn" hidden></button></body></html>', { runScripts: 'outside-only' });
  const w = dom.window;
  w.MfgUi = {};
  w.sent = [];
  w.adsk = { fusionSendData: (action, data) => w.sent.push([action, JSON.parse(data)]) };
  ['../shared/js/dom.js', '../shared/js/bridge.js'].forEach((src) => run(w, src));
  const i18n = englishI18n();
  i18n.state = () => w.state;
  i18n.use = (result) => { w.state = result; };
  i18n.set = (code) => w.sent.push(['set_language', { code: code }]);
  w.MfgUi.i18n = i18n;
  w.state = STATE;
  w.MfgUi.settings = { roleState: () => (role === undefined ? 'admin' : role), publish: () => w.sent.push(['publish', {}]) };   // a Hub Admin unless the test says otherwise
  w.MfgUi.progress = { notify: (title, text) => w.sent.push(['notify', { title: title, text: text }]) };
  ['../settings/js/picker.js', '../settings/js/language.js'].forEach((src) => run(w, src));
  w.MfgUi.language.init();
  return w;
}

const reply = (w, action, result) => w.fusionJavaScriptHandler.handle(action, JSON.stringify({ ok: true, result: result, error: null }));
const fail = (w, action, error) => w.fusionJavaScriptHandler.handle(action, JSON.stringify({ ok: false, result: null, error: error }));
const $ = (w, id) => w.document.getElementById(id);

test('Create sends what was typed, and the answer shows where the file is and offers the next steps', { skip }, () => {
  const w = openCard();
  $(w, 'lang-code').value = 'de';
  $(w, 'lang-code').dispatchEvent(new w.Event('input'));
  $(w, 'lang-name').value = 'Deutsch';
  $(w, 'lang-name').dispatchEvent(new w.Event('input'));
  w.document.querySelector('.lang-add-row .btn').click();
  assert.deepStrictEqual(w.sent.pop(), ['new_language', { code: 'DE', name: 'Deutsch' }]);

  const made = Object.assign({}, STATE, {
    languages: STATE.languages.concat([{ code: 'de', name: 'Deutsch', source: 'user' }]), created: STATE.user_dir + '\\de.json' });
  reply(w, 'new_language', made);
  const note = w.document.querySelector('.lang-note.ok');
  assert.ok(note, 'the success note is shown');
  assert.match(note.textContent, /de\.json/);
  assert.deepStrictEqual([...note.querySelectorAll('button')].map((b) => b.textContent), ['Open folder', 'Reload']);
  assert.strictEqual($(w, 'lang-code').value, '', 'the form is empty for the next one');

  w.document.querySelector('.ws-pick-btn').click();   // the new language is in the list
  assert.ok([...w.document.querySelectorAll('.ws-pick-item')].some((item) => item.textContent.includes('Deutsch')));
});

test('Create waits until both the code and the name are filled in', { skip }, () => {
  const w = openCard();
  const create = w.document.querySelector('.lang-add-row .btn');
  assert.strictEqual(create.disabled, true);
  assert.strictEqual(w.document.querySelectorAll('.lang-required').length, 2);
  $(w, 'lang-code').value = 'de';
  $(w, 'lang-code').dispatchEvent(new w.Event('input'));
  assert.strictEqual(create.disabled, true, 'a code alone is not enough');
  $(w, 'lang-name').value = '   ';
  $(w, 'lang-name').dispatchEvent(new w.Event('input'));
  assert.strictEqual(create.disabled, true, 'spaces are not a name');
  $(w, 'lang-name').value = 'Deutsch';
  $(w, 'lang-name').dispatchEvent(new w.Event('input'));
  assert.strictEqual(create.disabled, false);
});

test('a short list has no search box and no heading', { skip }, () => {
  const w = openCard();
  w.document.querySelector('.ws-pick-btn').click();
  assert.strictEqual(w.document.querySelector('.ws-pick-search').hidden, true);
  assert.strictEqual(w.document.querySelector('.ws-pick-group'), null);
});

test('a language the add-in refuses is explained under the form and what was typed stays', { skip }, () => {
  const w = openCard();
  $(w, 'lang-code').value = 'x';
  $(w, 'lang-code').dispatchEvent(new w.Event('input'));
  $(w, 'lang-name').value = 'X';
  $(w, 'lang-name').dispatchEvent(new w.Event('input'));
  w.document.querySelector('.lang-add-row .btn').click();
  fail(w, 'new_language', 'Language code: enter a code such as de, fr or pt-BR.');
  assert.match(w.document.querySelector('.lang-note.error').textContent, /Language code: enter a code/);
  assert.strictEqual($(w, 'lang-code').value, 'X', 'typed capitals');
});

test('choosing a language in the list uses it at once, with no Save; the list has no clear entry', { skip }, () => {
  const w = openCard();
  w.state = Object.assign({}, STATE, { languages: STATE.languages.concat([{ code: 'de', name: 'Deutsch', source: 'user' }]) });
  w.MfgUi.language.render();
  w.document.querySelector('.ws-pick-btn').click();
  assert.strictEqual(w.document.querySelector('.ws-pick-clear'), null);
  [...w.document.querySelectorAll('.ws-pick-item')].find((item) => item.textContent.includes('Deutsch')).click();
  assert.deepStrictEqual(w.sent.pop(), ['set_language', { code: 'de' }]);
});

test('Save with nothing changed only says it is saved', { skip }, () => {
  const w = openCard();
  $(w, 'lang-save-btn').click();
  assert.strictEqual(w.sent.pop()[0], 'notify');
});

test('the Language tab has Save, and Save & Publish only for a Hub Admin', { skip }, () => {
  assert.strictEqual($(openCard('admin'), 'lang-save-publish-btn').hidden, false);
  ['member', 'unknown', 'pending', ''].forEach((role) => assert.strictEqual($(openCard(role), 'lang-save-publish-btn').hidden, true, role));
});

test('the sign-in screen card only chooses: the language is used at once, so it has no Save', { skip }, () => {
  const w = openCard('member');
  assert.ok(w.document.querySelector('#lang-slot-login .lang-card'));
  assert.strictEqual(w.document.querySelector('#lang-slot-login .lang-login-save'), null);
});

test('anyone is offered to add a language, and the note says how it works', { skip }, () => {
  ['admin', 'member', 'unknown', 'pending'].forEach((role) => {
    const w = openCard(role);
    assert.match(w.document.querySelector('.lang-how').textContent, /not supported out of the box/, role);
    assert.strictEqual(w.document.querySelectorAll('.lang-how li').length, 3);
    assert.ok(w.document.querySelector('.lang-add-row'), role + ' has the form');
    assert.doesNotMatch(w.document.querySelector('.lang-add:not(.lang-share)').textContent, /Only a Hub Admin/);
  });
});

test('Save & Publish opens the hub, and the language chosen was already in use', { skip }, () => {
  const w = openCard('admin');
  $(w, 'lang-save-publish-btn').click();
  assert.deepStrictEqual(w.sent.pop(), ['publish', {}]);
  assert.ok(!w.sent.some(([action]) => action === 'set_language'));
});

test('the languages the hub shares are in the list, under their own heading', { skip }, () => {
  const w = openCard('admin');
  w.state = Object.assign({}, STATE, { languages: STATE.languages.concat([{ code: 'es', name: 'Español', source: 'hub' }]) });
  w.MfgUi.language.render();
  w.document.querySelector('.ws-pick-btn').click();
  assert.ok([...w.document.querySelectorAll('.ws-pick-group')].some((g) => /Shared by your hub/.test(g.textContent)));
});

test('each custom language is a tile that says whether it is only local or shared in the hub; there is nothing to tick', { skip }, () => {
  const w = openCard('admin');
  w.state = Object.assign({}, STATE, { languages: STATE.languages.concat([
    { code: 'de', name: 'Deutsch', source: 'user', sharing: { included: true, reason: '', hub: 'same' } },
    { code: 'fr', name: 'Français', source: 'user', sharing: { included: false, reason: 'The file is not valid JSON: line 3', hub: 'none' } },
    { code: 'it', name: 'Italiano', source: 'user', sharing: { included: true, reason: '', hub: 'different' } },
    { code: 'pt', name: 'Português', source: 'user', sharing: { included: true, reason: '', hub: 'none' } },
    { code: 'es', name: 'Español', source: 'hub' }]) });
  w.MfgUi.language.render();
  assert.match(w.document.querySelector('.lang-share h3').textContent, /Custom languages/);
  assert.strictEqual(w.document.querySelectorAll('.lang-share input').length, 0, 'no boxes to tick');
  const tiles = [...w.document.querySelectorAll('.lang-tile')];
  assert.deepStrictEqual(tiles.map((tile) => tile.querySelector('.lang-tile-code').textContent), ['de', 'fr', 'it', 'pt'], 'only the admin\'s own files; the hub\'s are not theirs');
  const chips = (tile) => [...tile.querySelectorAll('.lang-chip')].map((chip) => chip.textContent);
  assert.deepStrictEqual(chips(tiles[0]), ['Shared'], 'the hub has this one');
  assert.deepStrictEqual(chips(tiles[1]), ['Local']);
  assert.ok(tiles[1].classList.contains('excluded'));
  assert.match(tiles[1].textContent, /not valid JSON/);
  assert.strictEqual(chips(tiles[2]).length, 1);
  assert.match(chips(tiles[2])[0], /^Shared.+not published/i, 'the hub has an older one');
  assert.deepStrictEqual(chips(tiles[3]), ['Local'], 'not in the hub yet');
});

test('a Hub Admin with no languages of their own is told so', { skip }, () => {
  const w = openCard('admin');
  assert.match(w.document.querySelector('.lang-share-empty').textContent, /no custom languages yet/);
});

test('a member sees and manages languages of their own, but is only told that a Hub Admin publishes', { skip }, () => {
  const member = openCard('member');
  member.state = Object.assign({}, STATE, { languages: STATE.languages.concat([
    { code: 'de', name: 'Deutsch', source: 'user', sharing: { included: true, reason: '', hub: 'none' } },
    { code: 'es', name: 'Español', source: 'hub' }]) });
  member.MfgUi.language.render();
  const tiles = [...member.document.querySelectorAll('.lang-tile')];
  assert.deepStrictEqual(tiles.map((tile) => tile.querySelector('.lang-tile-code').textContent), ['de'], 'their own only');
  assert.strictEqual(tiles[0].querySelectorAll('.lang-tile-tools button').length, 2, 'Edit and Delete');
  assert.match(member.document.querySelector('.lang-share .hint').textContent, /Hub Admin/);
  assert.strictEqual($(member, 'lang-save-publish-btn').hidden, true, 'publishing stays with a Hub Admin');
});

const OWN = Object.assign({}, STATE, { languages: STATE.languages.concat([
  { code: 'de', name: 'Deutsch', source: 'user', sharing: { included: true, reason: '', hub: 'none' } },
  { code: 'fr', name: 'Français', source: 'user', sharing: { included: true, reason: '', hub: 'none' } }]) });

test("each custom language has an Edit and a Delete icon, named for it", { skip }, () => {
  const w = openCard('admin');
  w.state = OWN;
  w.MfgUi.language.render();
  const tiles = [...w.document.querySelectorAll('.lang-tile')];
  assert.strictEqual(tiles.length, 2);
  tiles.forEach((tile) => {
    assert.strictEqual(tile.querySelectorAll('.lang-tile-tools button').length, 2);
    assert.ok(tile.querySelector('.lang-edit svg') && tile.querySelector('.lang-delete svg'), 'each is an icon');
  });
  assert.strictEqual(tiles[0].querySelector('.lang-edit').getAttribute('aria-label'), 'Edit Deutsch');
  assert.strictEqual(tiles[1].querySelector('.lang-delete').title, 'Delete Français');
});

test('Edit opens the file without touching the page, and coming back from the editor reads the files again', { skip }, () => {
  const w = openCard('member');
  w.state = Object.assign({}, OWN, { code: 'fr' });
  w.MfgUi.language.render();
  const tile = w.document.querySelector('.lang-tile');
  w.window.dispatchEvent(new w.window.Event('focus'));
  assert.ok(!w.sent.some(([action]) => action === 'set_language'), 'nothing was edited: focus alone does nothing');
  w.document.querySelectorAll('.lang-edit')[1].click();
  assert.deepStrictEqual(w.sent.pop(), ['edit_language', { code: 'fr' }]);
  reply(w, 'edit_language', { code: 'fr', name: 'Français' });
  assert.strictEqual(w.document.querySelector('.lang-tile'), tile, 'the page is not built again');
  assert.strictEqual(w.document.querySelector('.lang-share .lang-note'), null, 'no note');
  w.window.dispatchEvent(new w.window.Event('focus'));
  assert.deepStrictEqual(w.sent, [], 'it has not been away yet');
  w.window.dispatchEvent(new w.window.Event('blur'));
  w.window.dispatchEvent(new w.window.Event('focus'));
  assert.deepStrictEqual(w.sent.pop(), ['set_language', { code: 'fr' }], 'the language in use was edited: the panels load again');
  w.document.querySelectorAll('.lang-edit')[0].click();
  w.sent.length = 0;
  w.window.dispatchEvent(new w.window.Event('blur'));
  w.window.dispatchEvent(new w.window.Event('focus'));
  assert.deepStrictEqual(w.sent, [['get_language', {}]], 'another language: only the list is read again');
  fail(w, 'edit_language', 'The editor could not be opened.');
  assert.match(w.document.querySelector('#lang-slot-tab .lang-note.error').textContent, /could not be opened/);
});

test('Delete asks first, and only the confirmation deletes', { skip }, () => {
  const w = openCard('admin');
  const asked = [];
  w.MfgUi.progress = { confirm: (title, text, action, go) => asked.push({ title, text, action, go }), notify() {} };
  w.state = OWN;
  w.MfgUi.language.render();
  w.document.querySelectorAll('.lang-delete')[0].click();
  assert.strictEqual(asked.length, 1);
  assert.strictEqual(asked[0].title, 'Delete Deutsch?');
  assert.match(asked[0].text, /removes de\.json from your languages folder/);
  assert.strictEqual(asked[0].action, 'Delete');
  assert.ok(!w.sent.some(([action]) => action === 'delete_language'), 'nothing is deleted before it is confirmed');
  asked[0].go();
  assert.deepStrictEqual(w.sent.pop(), ['delete_language', { code: 'de' }]);
});

test('after a delete the list is without the language, and deleting the one in use loads the panels again in English', { skip }, () => {
  const w = openCard('admin');
  w.state = Object.assign({}, OWN, { code: 'fr' });
  w.MfgUi.language.render();
  reply(w, 'delete_language', Object.assign({}, STATE, { code: 'fr', languages: OWN.languages.filter((l) => l.code !== 'de') }));
  assert.deepStrictEqual([...w.document.querySelectorAll('.lang-tile-code')].map((n) => n.textContent), ['fr']);
  assert.ok(!w.sent.some(([action]) => action === 'set_language'), 'another language was deleted: nothing reloads');
  reply(w, 'delete_language', Object.assign({}, STATE, { code: 'en', languages: STATE.languages }));
  assert.deepStrictEqual(w.sent.pop(), ['set_language', { code: 'en' }]);
  fail(w, 'delete_language', 'The language is not one of your own.');
  assert.match(w.document.querySelector('#lang-slot-tab .lang-note.error').textContent, /not one of your own/);
});

test('each word of a language name starts with a capital as it is typed, and the rest is left as typed', { skip }, () => {
  const w = openCard();
  $(w, 'lang-name').value = 'german tEst';
  $(w, 'lang-name').dispatchEvent(new w.Event('input'));
  assert.strictEqual($(w, 'lang-name').value, 'German TEst');
  $(w, 'lang-code').value = 'fr';
  $(w, 'lang-code').dispatchEvent(new w.Event('input'));
  w.document.querySelector('.lang-add-row .btn').click();
  assert.deepStrictEqual(w.sent.pop(), ['new_language', { code: 'FR', name: 'German TEst' }]);
});

test('opening the Language tab reads the languages folders again', { skip }, () => {
  const w = openCard('member');
  w.sent.length = 0;
  w.document.querySelector('.tab[data-tab="language"]').click();
  assert.deepStrictEqual(w.sent, [['get_language', {}]]);
});

test('a language picked is let go when the folders no longer have its file', { skip }, () => {
  const w = openCard('member');
  const french = { code: 'FR', name: 'French', source: 'user', sharing: { included: true, hub: 'none' } };
  reply(w, 'get_language', Object.assign({}, STATE, { languages: STATE.languages.concat(french) }));
  const value = w.document.querySelector('#lang-slot-tab .lang-value');
  value.value = 'FR';
  value.parentElement.dispatchEvent(new w.Event('pick'));
  reply(w, 'get_language', STATE);   // the file was removed by hand
  w.sent.length = 0;
  w.MfgUi.language.render();
  assert.strictEqual(w.document.querySelector('#lang-slot-tab .lang-value').value, 'en', 'the list shows the language in use again');
});

test('the Custom languages section always has a button beside its heading that opens the languages folder', { skip }, () => {
  const w = openCard('member');
  w.sent.length = 0;
  w.document.querySelector('.lang-share-head .btn').click();
  assert.deepStrictEqual(w.sent, [['open_language_folder', {}]]);
});

test('when the save to the hub ends, the languages are read again to show what the hub has', { skip }, () => {
  const w = openCard('admin');
  w.sent.length = 0;
  w.MfgUi.language.settled();
  assert.deepStrictEqual(w.sent, [['get_language', {}]]);
});

test('the Restart add-in button of the notice asks the add-in to start again', { skip }, () => {
  const w = openCard('member');
  w.sent.length = 0;
  $(w, 'lang-restart-btn').click();
  assert.deepStrictEqual(w.sent, [['restart_addin', {}]]);
});
