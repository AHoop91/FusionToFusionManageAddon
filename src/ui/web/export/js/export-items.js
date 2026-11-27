/**
 * The Export window's items (``ns.exportItems``): the items of the Items workspace made from what is exported, and the one the file goes to.
 * When several are made from it the window opens on the shared table of choices (``ns.choiceTable``, as the Item panel does) and the options
 * follow the pick; "Change item" brings the table back.
 *
 * ``init(host)``: ``host.changed()`` is called when the pick changes. ``show(result)`` takes Python's answer (``{target, items}``, or ``error``
 * for why they could not be listed). ``state()`` is ``finding`` (not answered yet), ``failed``, ``none``, ``one`` or ``several``. The one item is
 * picked at once; with several none is until the user picks. ``selected()`` is the id picked ("" when none), ``current()`` the item picked (or
 * null), ``reset()`` forgets the pick, ``recordUrl()`` the page of the component's record in Fusion Manage, ``note()`` the words for no items or a
 * failure. ``#export-items`` holds the table, or grey bars while the items are looked for.
 */
(function (ns) {
  'use strict';

  const $ = ns.$;
  const el = ns.el;
  const t = ns.i18n.t;
  const ROWS = 4;   // the grey rows shown while the items are looked for

  let host = null;
  let result = null;   // Python's answer; null while it is awaited
  let chosen = '';
  let componentUrl = '';   // the page of the component's own record in Fusion Manage ("" when it has none)

  function init(hostApi) { host = hostApi; }

  /** A grey bar, ``size`` the class that gives it its width. */
  function bar(size) {
    return el('span', 'export-skeleton export-wait-bar ' + size);
  }

  /** The table in grey while the items are looked for: the search field, the column titles, the rows and the count, where they will be. */
  function waiting() {
    const box = el('div', 'export-items-waiting');
    box.setAttribute('role', 'status');
    box.setAttribute('aria-label', t('export.items_finding'));
    const head = el('div', 'export-wait-head');
    head.append(bar('is-title-one'), bar('is-title-two'));
    const pane = el('div', 'export-wait-pane');
    pane.appendChild(head);
    for (let i = 0; i < ROWS; i++) {
      const row = el('div', 'export-wait-row');
      row.append(bar('is-number'), bar('is-descriptor'));
      pane.appendChild(row);
    }
    const foot = el('div', 'export-wait-foot');
    foot.appendChild(bar('is-count'));
    pane.appendChild(foot);
    box.append(bar('is-search'), pane);
    return box;
  }

  function state() {
    if (result === null) return 'finding';
    if (result.error) return 'failed';
    if (!result.items.length) return 'none';
    return result.items.length === 1 ? 'one' : 'several';
  }

  function table(items) {
    return ns.choiceTable.make({
      rows: items.map(function (item) { return { key: item.id, first: item.number || item.descriptor, second: item.number ? item.descriptor : '' }; }),
      titles: [t('item.choice_col_number'), t('item.choice_col_descriptor')],
      text: { search: t('item.choice_search'), hint: '', label: t('item.choice_label'),
              count: function (n) { return t('item.choice_count', { count: n }); }, none: t('item.choice_none') },
      onPick: function (id) { chosen = id; host.changed(); },
    });
  }

  function paintTable() {
    const box = $('export-items');
    if (state() === 'several') box.replaceChildren(table(result.items));
    else box.replaceChildren(waiting());
  }

  /** Take in the answer: the one item is picked at once, as the Item panel opens it; with several the user picks. */
  function show(answer) {
    result = answer;
    componentUrl = answer ? answer.component_url || '' : '';
    chosen = answer && !answer.error && answer.items.length === 1 ? answer.items[0].id : '';
    paintTable();
    host.changed();
  }

  /** Forget the pick, so the table is asked again. */
  function reset() {
    chosen = '';
    host.changed();
  }

  function selected() { return chosen; }

  /** The item picked, or null. */
  function current() {
    if (!chosen || !result || !result.items) return null;
    return result.items.filter(function (item) { return item.id === chosen; })[0] || null;
  }

  /** What to say in place of an item: why the items could not be listed, or that there are none; "" when there are items. */
  function note() {
    const s = state();
    if (s === 'failed') return result.error;
    return s === 'none' ? t('export.items_none') : '';
  }

  /** The page of the component's record in Fusion Manage ("" when it has none, or it is not known yet). */
  function recordUrl() { return componentUrl; }

  ns.exportItems = { recordUrl: recordUrl, init: init, show: show, reset: reset, state: state, selected: selected, current: current, note: note };
})(window.MfgUi);
