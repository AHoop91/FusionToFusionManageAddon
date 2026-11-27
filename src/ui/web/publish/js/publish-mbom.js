/**
 * Publish Item panel: the manufacturing bills of materials (MBOM) of the open design, as ``ns.pubMbom``.
 *
 * A dropdown (the shared picker, dressed as the Add Existing Items ones) at the right of the summary lists the items of the Items workspace made
 * from the design (found by its lineage id and asset id): the one chosen is the item the Bill of Materials is compared with. Its last entry,
 * "New Bill of Materials", asks for a new item number, which starts as the design's item number and a hyphen and may be changed
 * completely, checks that no item has it, and chooses it: the item is made by Publish. A lookup that failed is the panel's to show (publish.js).
 *
 * Several items: the Bill of Materials is not read until the user picks one from a list in its place (the dropdown stays, to switch). One
 * item is chosen at once, and none leaves the design's own item number in use.
 *
 * ``init(host)``: ``host.itemNumber()`` of the design, ``host.check(number)`` asks whether an item has the number (its answer is told to
 * ``answer``) and ``host.choose(number)`` is told which MBOM was chosen.
 */
(function (ns) {
  'use strict';

  const $ = ns.$;
  const el = ns.pubUi.el;
  function t(key, params) { return ns.i18n.t(key, params); }

  const NUMBER = /^[A-Za-z0-9._-]+$/;   // what a new number may hold
  const PLUS = ['M12 5v14', 'M5 12h14'];

  let host = null;
  let found = [];     // the items Fusion Manage holds for the design: {id, number, descriptor}
  let added = [];     // the numbers made here that Fusion Manage does not hold yet: Publish makes them
  let pending = '';   // the number whose check is on its way
  let form = null;    // what the form of a new number is made of while it is open

  function init(hostApi) { host = hostApi; }

  function foundNumbers() { return found.map(function (item) { return item.number; }); }

  function numbers() { return foundNumbers().concat(added.filter(function (n) { return foundNumbers().indexOf(n) < 0; })); }

  function itemOf(number) { return found.filter(function (f) { return f.number === number; })[0]; }

  /** What the list shows for a number: the item's descriptor, or the number itself when it has none or the item is not made yet. */
  function labelOf(number) {
    const item = itemOf(number);
    return item && item.descriptor ? item.descriptor : number;
  }

  /** The id of the item Fusion Manage holds with this number ("" for a new one): the item is read by it, whatever its number becomes. */
  function idOf(number) {
    const item = itemOf(number);
    return item ? item.id : '';
  }

  /** Offer the items the lookup found (``[{id, number, descriptor}]``). Gives the number chosen: ``wanted`` if it is one of them, the only one
   *  when there is one, "" when there is none (the design's own item number is used), and ``null`` when there are several and none is wanted:
   *  the user says which (``offer``). */
  function show(items, wanted) {
    found = items;
    const all = numbers();
    const selected = all.indexOf(wanted) >= 0 ? wanted : all.length > 1 ? null : all[0] || '';
    draw(selected || '');
    return selected;
  }

  /** The text a row of the list of choices shows after the number: the item's descriptor ("" when the item is not made yet). */
  function descriptorOf(number) {
    const item = itemOf(number);
    return item && item.descriptor ? item.descriptor : '';
  }

  /** Several items were found and none is chosen: list them in ``area`` (the Bill of Materials' place) with the shared table of choices
   *  (``ns.choiceTable``), the structure viewer's pane. The user picks the one to work on. */
  function offer(area) {
    area.appendChild(ns.choiceTable.make({
      className: 'pub-mbom-choices',
      rows: numbers().map(function (number) {
        return { key: number, first: number, second: descriptorOf(number), pill: itemOf(number) ? '' : t('publish.mbom_pill') };
      }),
      titles: [t('publish.mbom_col_number'), t('publish.mbom_col_descriptor')],
      text: {
        search: t('publish.sv_search_placeholder'), hint: t('publish.mbom_choose_hint'), label: t('publish.mbom_choose_title'),
        count: function (n) { return t('publish.sv_search_count', { count: n }); }, none: t('publish.sv_search_none'),
      },
      onPick: function (number) { draw(number); host.choose(number); },
    }));
  }

  /** A small "New" pill at the right of the button when the item chosen is not made yet (the list's entries carry theirs as their detail). */
  function tag(picker) {
    const button = picker.querySelector('.pk-btn');
    const old = button.querySelector('.pub-mbom-pill');
    if (old) old.remove();
    const picked = picker.getPicked()[0];
    if (picked && !itemOf(picked.value)) button.querySelector('.pk-text').after(el('span', 'pub-mbom-pill', t('publish.mbom_pill')));
  }

  function draw(selected) {
    closeForm();
    const all = numbers();
    const picker = ns.picker.make({
      className: 'pub-add-pk pub-add-version-wrap pub-mbom-pk',
      buttonClass: 'pub-add-version',
      ariaLabel: t('publish.mbom_title'),
      required: true,
      searchFrom: Infinity,
      alignRight: true,
      placeholder: t('publish.mbom_placeholder'),
      search: '',
      label: labelOf,
      groups: function () { return [{ title: '', items: all.map(function (n) { return { value: n, label: labelOf(n), detail: itemOf(n) ? '' : t('publish.mbom_pill') }; }) }]; },
      footer: function () { return host.itemNumber() ? { label: t('publish.mbom_new'), icon: PLUS, run: openForm } : null; },
    }, selected);
    tag(picker);
    picker.addEventListener('pick', function () { tag(picker); host.choose(picker.getPicked()[0].value); });
    const box = $('pub-mbom');
    box.replaceChildren(el('label', 'pub-mbom-label', t('publish.mbom_title')), picker);
    if (host.itemNumber()) {   // quick access to the same entry the list ends with
      const add = el('button', 'pub-mbom-add');
      add.type = 'button';
      add.title = t('publish.mbom_new');
      add.setAttribute('aria-label', t('publish.mbom_new'));
      add.appendChild(ns.svg(PLUS, 16));
      add.addEventListener('click', openForm);
      box.appendChild(add);
    }
    box.hidden = false;
  }

  // ---- A new number ----------------------------------------------------------------

  function openForm() {
    closeForm();
    const prefix = host.itemNumber() + '-';
    const input = el('input', 'pub-mbom-input');
    input.type = 'text';
    input.value = prefix;
    input.setAttribute('aria-label', t('publish.mbom_number'));
    input.autocomplete = 'off';
    input.spellcheck = false;
    const error = el('p', 'error pub-mbom-error');
    error.hidden = true;
    error.setAttribute('role', 'alert');
    const cancel = el('button', 'btn btn-secondary', t('publish.cancel'));
    cancel.type = 'button';
    const create = el('button', 'btn', t('publish.mbom_create'));
    create.type = 'submit';
    const actions = el('div', 'pub-mbom-actions');
    actions.append(cancel, create);
    const node = el('form', 'pub-mbom-form');
    node.append(el('h4', 'pub-mbom-form-title', t('publish.mbom_new_title')), input, el('p', 'pub-mbom-hint', t('publish.mbom_hint')), error, actions);
    node.addEventListener('submit', function (event) { event.preventDefault(); submit(); });
    node.addEventListener('keydown', function (event) { if (event.key === 'Escape') closeForm(); });
    cancel.addEventListener('click', closeForm);
    form = { node: node, input: input, error: error, create: create, prefix: prefix, done: null };
    $('pub-mbom').appendChild(node);
    input.focus();
    input.setSelectionRange(prefix.length, prefix.length);   // the end is what is typed; the rest can be changed too
  }

  function closeForm() {
    if (form) form.node.remove();
    form = null;
    pending = '';
  }

  function fail(message) {
    if (form.done) form.done();
    form.done = null;
    form.error.textContent = message;
    form.error.hidden = false;
    form.input.focus();
  }

  function submit() {
    const number = form.input.value.trim();
    form.error.hidden = true;
    if (!NUMBER.test(number)) { fail(t('publish.mbom_number_invalid')); return; }
    if (number === form.prefix) { fail(t('publish.mbom_number_incomplete')); return; }   // the start alone is not a new number
    if (numbers().some(function (n) { return n.toLowerCase() === number.toLowerCase(); })) { fail(t('publish.mbom_taken', { number: number })); return; }
    pending = number;
    form.done = ns.pubUi.busy(form.create, t('publish.mbom_checking'));
    host.check(number);
  }

  /** The answer to ``host.check``: the number is chosen when no item has it, else the form says why not. */
  function answer(entry) {
    if (!form || entry.target !== pending) return;   // the form was closed, or another number was asked since
    const number = pending;
    pending = '';
    if (!entry.ok) { fail(entry.message || t('publish.unknown_error')); return; }
    if (entry.data.taken) { fail(t('publish.mbom_taken', { number: number })); return; }
    added.push(number);
    closeForm();
    draw(number);
    host.choose(number);
  }

  /** The lookup is on its way: the label and a grey bar where the dropdown will be, so it does not appear late. */
  function loading() {
    closeForm();
    const bar = el('span', 'pub-skel pub-mbom-skel');
    bar.setAttribute('aria-hidden', 'true');
    const box = $('pub-mbom');
    box.replaceChildren(el('label', 'pub-mbom-label', t('publish.mbom_title')), bar);
    box.hidden = false;
  }

  /** Hide the dropdown while the design is read again. */
  function reset() {
    closeForm();
    $('pub-mbom').hidden = true;
  }

  /** The design shown is another one: the numbers made for the last are not its. */
  function forget() {
    added = [];
  }

  ns.pubMbom = { init: init, loading: loading, show: show, offer: offer, answer: answer, idOf: idOf, reset: reset, forget: forget };
})(window.MfgUi);
