/**
 * The filters of the view shown on the Assign Product window, in two separate pieces:
 *
 * - the pop-up under a column: the funnel in a column's header opens it to filter that one column;
 * - the panel down the right-hand side (the funnel at the top right): a card for each field that has filters, and a search box listing every field
 *   the workspace's views can be filtered by (``products_fields``), by section.
 *
 * Save, in either, hands the fields that changed to the page (``host.apply``), which writes them into the view (a view is shared, so Save says so)
 * in one go.
 */
(function (ns) {
  'use strict';

  const $ = ns.$;
  const el = ns.el;
  const t = ns.i18n.t;

  const FUNNEL = 'M3 4.5C3 3.7 7 3 12 3s9 .7 9 1.5L14 12v7l-4 2v-8z';

  let host = null;           // what the page lends: see ``init``

  /** A copy of the filters a field holds, as the lines to edit. */
  function rowsOf(applied) {
    return applied.filters.map(function (f) { return { type: f.type, value: f.value }; });
  }

  function filterOf(filters, type) {
    return filters.find(function (f) { return f.id === type; });
  }

  function rowsReady(filters, rows) {
    return rows.every(function (row) {
      const f = filterOf(filters, row.type);
      return !!f && (!f.takes_value || !!row.value.trim());
    });
  }

  /** What stands for the filters of a field as edited, to tell whether they differ from what was there. */
  function entryOf(match, rows) {
    return JSON.stringify([match, rows.map(function (r) { return [r.type, r.value.trim()]; })]);
  }

  /** The filters of a field as ``products_filter`` takes them. */
  function changeOf(key, filters, match, rows) {
    return { column: key, match: match, filters: rows.map(function (r) {
      return { type: r.type, value: filterOf(filters, r.type).takes_value ? r.value.trim() : '' };
    }) };
  }

  /** A drop-down list in place of the browser's own: the shared picker with nothing to search. ``options`` is ``[{value, label}]``; ``clearable``
   *  adds an entry (named ``label``) that takes the choice back; ``onChange(value)`` is told of a new choice, '' for that entry. */
  function dropdown(options, value, label, className, clearable, onChange) {
    const picker = ns.picker.make({
      className: 'pk-dd ' + className,
      ariaLabel: label,
      required: !clearable,
      searchFrom: Infinity,
      placeholder: label,
      search: '',
      text: { clear: label },
      label: function (v) { return options.find(function (o) { return o.value === v; }).label; },
      groups: function () { return [{ title: '', items: options }]; },
    }, options.some(function (o) { return o.value === value; }) ? value : '');   // a filter no longer offered shows as not chosen
    picker.addEventListener('pick', function () {
      const picked = picker.getPicked();
      const next = picked.length ? picked[0].value : '';
      if (next !== value) onChange(next);
    });
    return picker;
  }

  /** One line of filter: its type, the value to match where the type takes one (with a button to clear it), and a bin. ``o.beforeRemove(line)``
   *  may add to it. ``o`` also says the classes, and what to do when the type or the value changes, on Enter, and when the bin is pressed. */
  function filterRowEl(filters, row, o) {
    const line = el('div', o.rowClass);
    const choices = filters.map(function (f) { return { value: f.id, label: f.name }; });
    line.appendChild(dropdown(choices, row.type, t('products.filter_select'), o.typeClass, true, function (type) { row.type = type; o.onType(); }));
    const f = filterOf(filters, row.type);
    if (f && f.takes_value) {
      const box = el('span', 'pfl-value');
      const value = el('input', 'form-input');
      value.type = 'text';
      value.maxLength = 500;
      value.value = row.value;
      value.placeholder = t('products.filter_value');
      value.setAttribute('aria-label', t('products.filter_value'));
      const clear = el('button', 'pfl-clear');
      clear.type = 'button';
      clear.title = t('products.filter_clear');
      clear.setAttribute('aria-label', clear.title);
      clear.hidden = !row.value;
      clear.appendChild(ns.svg(['M6 6l12 12', 'M18 6L6 18'], 14));
      value.addEventListener('input', function () { row.value = value.value; clear.hidden = !row.value; o.onInput(); });
      if (o.onEnter) value.addEventListener('keydown', function (event) { if (event.key === 'Enter') o.onEnter(); });
      clear.addEventListener('click', function () { row.value = ''; value.value = ''; clear.hidden = true; o.onInput(); value.focus(); });
      box.appendChild(value);
      box.appendChild(clear);
      line.appendChild(box);
    }
    if (o.beforeRemove) o.beforeRemove(line);
    const remove = el('button', 'pfl-remove');
    remove.type = 'button';
    remove.title = t('products.filter_remove');
    remove.setAttribute('aria-label', remove.title);
    remove.appendChild(ns.svg(['M9 3h6l1 1h4v2H4V4h4z', 'M6 8h12l-1 13H7z'], 18));
    remove.addEventListener('click', o.onRemove);
    line.appendChild(remove);
    return line;
  }

  // The pop-up of one column

  let filterColumn = null;   // the column being edited
  let filterRows = [];       // [{type, value}] as edited
  let filterMatch = 'ALL';   // ALL: every filter must hold; ANY: one is enough
  let filterOriginal = '';   // the filters as they were when the pop-up opened, to tell whether Save has anything to save
  let filterAnchor = null;   // the funnel the pop-up was opened from

  function closeFilter() {
    $('products-filter-pop').hidden = true;
    filterColumn = null;
  }

  function syncFilterButtons() {
    $('products-filter-save').disabled = !rowsReady(filterColumn.filters, filterRows) || entryOf(filterMatch, filterRows) === filterOriginal;
    const add = $('products-filter-add');   // a column that takes one filter shows it, but cannot add another
    add.disabled = !!filterRows.length && !filterColumn.multiple;
    add.title = add.disabled ? t('products.filter_one_only') : '';
  }

  /** The And / Or choice of a line: a column that takes one filter has nothing to join. */
  function joinChoice() {
    const choices = [{ value: 'ALL', label: t('products.filter_and') }, { value: 'ANY', label: t('products.filter_or') }];
    const join = dropdown(choices, filterMatch, t('products.filter_and'), 'pfl-join', false, function (match) { filterMatch = match; paintFilter(); });
    join.querySelector('button').disabled = !filterColumn.multiple;
    return join;
  }

  function paintFilter() {
    const body = $('products-filter-body');
    body.textContent = '';
    $('products-filter-pop').setAttribute('aria-label', t('products.filter_title', { column: filterColumn.title }));
    if (!filterRows.length) body.appendChild(el('p', 'muted pfl-none', t('products.filter_none')));
    filterRows.forEach(function (row, i) {
      body.appendChild(filterRowEl(filterColumn.filters, row, {
        rowClass: 'pfl-row', typeClass: 'pfl-type', onType: paintFilter, onInput: syncFilterButtons,
        onEnter: function () { if (!$('products-filter-save').disabled) saveFilter(); },
        onRemove: function () { filterRows.splice(i, 1); paintFilter(); },
        beforeRemove: function (line) { line.appendChild(joinChoice()); }
      }));
    });
    // The pop-up is as wide as it needs to be: narrower when no filter has a value to type.
    const typing = filterRows.some(function (r) { const f = filterOf(filterColumn.filters, r.type); return !!f && f.takes_value; });
    $('products-filter-pop').classList.toggle('pfl-narrow', !typing);
    syncFilterButtons();
    if (!$('products-filter-pop').hidden) placeFilter();
  }

  /** Put the pop-up under the column being filtered, from its left edge, and in the window. */
  function placeFilter() {
    const pop = $('products-filter-pop');
    const header = (filterAnchor.closest('th') || filterAnchor).getBoundingClientRect();
    pop.style.top = header.bottom + 'px';
    pop.style.left = Math.max(0, Math.min(header.left, window.innerWidth - pop.offsetWidth)) + 'px';
  }

  /** Open the pop-up under the header of ``column`` (a column of the view: ``{key, title, multiple, filters, applied}``); again, it closes. */
  function openColumn(column, anchor) {
    if (filterColumn && filterColumn.key === column.key && !$('products-filter-pop').hidden) { closeFilter(); return; }
    closePanel();
    filterColumn = column;
    filterRows = rowsOf(column.applied);
    filterMatch = column.applied.match;
    filterOriginal = entryOf(filterMatch, filterRows);
    if (!filterRows.length) filterRows.push({ type: '', value: '' });
    paintFilter();
    const pop = $('products-filter-pop');
    pop.hidden = false;
    filterAnchor = anchor;
    placeFilter();
    pop.querySelector('button, input').focus();
  }

  function saveFilter() {
    const change = changeOf(filterColumn.key, filterColumn.filters, filterMatch, filterRows);
    closeFilter();
    host.apply([change]);
  }

  // The panel of the whole view

  let panelState = null;      // {key: {match, rows: [{type, value}]}} as edited; a field with rows has a card
  let panelBase = null;       // the same as the view held it when the panel opened
  let fields = null;          // every field the workspace's views can be filtered by, once read: [{key, title, lower, group, multiple, filters}]
  let fieldByKey = {};        // the same by key
  let fieldGroups = [];       // [{name, fields}] in the order the sections are shown
  let fieldsLoading = false;
  const treeOpen = {};        // section name -> its fields are listed
  let tab = 'filters';        // the tab of the panel in view: 'filters' or 'columns'
  let colState = [];          // the keys of the columns to show, in order, as edited
  let colBase = [];           // the same as the view held it when the panel opened
  const colOpen = {};         // section name -> its fields are listed (in the list of available columns)

  function setFields(list) {
    fields = list.map(function (f) { return Object.assign({ lower: f.title.toLowerCase() }, f); });
    fieldByKey = {};
    const byName = new Map();
    fields.forEach(function (f) {
      fieldByKey[f.key] = f;
      if (!byName.has(f.group)) byName.set(f.group, []);
      byName.get(f.group).push(f);
    });
    fieldGroups = Array.from(byName, function (e) { return { name: e[0], fields: e[1] }; });
  }

  /** The state of every field of the view that has filters, as the view holds it. */
  function panelStateOfView() {
    const state = {};
    viewColumns().forEach(function (d) {
      if (d.applied.filters.length) state[d.key] = { match: d.applied.match, rows: rowsOf(d.applied) };
    });
    return state;
  }

  function stateEntry(state, key) {
    return state[key] ? entryOf(state[key].match, state[key].rows) : '';
  }

  /** The fields whose filters differ from what the view held. */
  function panelChanged() {
    return Object.keys(Object.assign({}, panelBase, panelState)).filter(function (key) {
      return fieldByKey[key] && stateEntry(panelState, key) !== stateEntry(panelBase, key);
    });
  }

  function panelReady() {
    return Object.keys(panelState).every(function (key) { return !fieldByKey[key] || rowsReady(fieldByKey[key].filters, panelState[key].rows); });
  }

  function closeTree() {
    $('products-view-tree').hidden = true;
    $('products-view-pick').parentNode.classList.remove('open');   // the chevron points down again
    $('products-view-pick').placeholder = t('products.panel_pick');
  }

  function closePanel() {
    $('products-view-panel').hidden = true;
    closeTree();
    panelState = null;
    colState = [];
  }

  function syncPanel() {
    $('products-view-save').disabled = !fields || !panelReady() || !colState.length || !(panelChanged().length || colsChanged());
  }

  /** Read every field of the workspace once (when the view's columns come in, so it is usually there before the panel is opened). If they
   *  cannot be read the panel offers the view's own columns. */
  function loadFields() {
    if (fields || fieldsLoading) return;
    fieldsLoading = true;
    host.ask('products_fields', {}, function (answer) {
      fieldsLoading = false;
      if (!answer.ok) return host.fail(answer);
      setFields(answer.result.fields);
      if (!panelState) return;
      paintPanel();
      if (!$('products-view-tree').hidden) paintTree();
      if (tab === 'columns') paintColumns();
    });
  }

  function funnelMark() {
    const mark = el('span', 'pvp-funnel');
    mark.appendChild(ns.svg([FUNNEL], 16));
    return mark;
  }

  /** The button of a field in a list of sections. */
  function fieldButton(f) {
    const item = el('button', 'pvp-field');
    item.type = 'button';
    item.appendChild(el('span', 'pvp-field-name', f.title));
    return item;
  }

  /** The sections of ``tree`` that open to their fields: ``offered(group)`` gives the fields to list, those matching ``query`` (all of a section whose
   *  name does; every section is open while there is a query), ``mark(group)`` says whether the section is marked with the green funnel, ``button(f)``
   *  makes the entry of a field, and ``again`` paints the tree anew when a section is opened or closed (in ``opened``). */
  function paintGroups(tree, query, opened, again, offered, mark, button) {
    fieldGroups.forEach(function (group) {
      const left = offered(group);
      const shown = !query || group.name.toLowerCase().indexOf(query) >= 0 ? left : left.filter(function (f) { return f.lower.indexOf(query) >= 0; });
      if (!shown.length) return;
      const open = !!query || !!opened[group.name];
      const head = el('button', 'pvp-group');
      head.type = 'button';
      head.setAttribute('aria-expanded', open ? 'true' : 'false');
      head.appendChild(ns.svg(open ? ['M6 9l6 6 6-6'] : ['M9 6l6 6-6 6'], 14));
      head.appendChild(el('span', 'pvp-group-name', group.name || t('products.panel_fields')));
      if (mark(group)) head.appendChild(funnelMark());
      head.addEventListener('click', function () { opened[group.name] = !opened[group.name]; again(); });
      tree.appendChild(head);
      if (open) shown.forEach(function (f) { tree.appendChild(button(f)); });
    });
  }

  /** The list under the search box: sections that open to their fields, those holding a filter marked with a green funnel. */
  function paintTree() {
    const tree = $('products-view-tree');
    tree.textContent = '';
    paintGroups(tree, $('products-view-pick').value.trim().toLowerCase(), treeOpen, paintTree,
      function (group) { return group.fields; },
      function (group) { return group.fields.some(function (f) { return panelState[f.key]; }); },
      function (f) {
        const item = fieldButton(f);
        item.disabled = !!panelState[f.key];
        if (panelState[f.key]) item.appendChild(funnelMark());
        item.addEventListener('click', function () {
          panelState[f.key] = { match: 'ALL', rows: [{ type: '', value: '' }] };
          if (colState.indexOf(f.key) < 0) colState.push(f.key);   // a field that is filtered is shown (untick Show column to hide it)
          $('products-view-pick').value = '';
          closeTree();
          paintPanel();
        });
        return item;
      });
    if (!tree.firstChild) tree.appendChild(el('p', 'muted pvp-empty', t('products.panel_nothing')));
  }

  function openTree() {
    if (!fields) return;
    $('products-view-pick').placeholder = t('products.panel_type');
    paintTree();
    $('products-view-tree').hidden = false;
    $('products-view-pick').parentNode.classList.add('open');
  }

  /** The card of one field: its title, the And / Or between its filters, a line for each filter, and Add filter. */
  function panelCard(f) {
    const s = panelState[f.key];
    const card = el('section', 'pvp-card');
    card.appendChild(el('h3', 'pvp-card-title', f.title));
    const show = el('label', 'pvp-show');
    const tick = el('input');
    tick.type = 'checkbox';
    tick.checked = colState.indexOf(f.key) >= 0;
    tick.disabled = tick.checked && colState.length < 2;   // a view keeps at least one column
    if (tick.disabled) show.title = t('products.cols_last');
    tick.addEventListener('change', function () {
      const at = colState.indexOf(f.key);
      if (tick.checked && at < 0) colState.push(f.key);
      else if (!tick.checked && at >= 0) colState.splice(at, 1);
      paintPanel();
    });
    show.appendChild(tick);
    show.appendChild(el('span', '', t('products.show_column')));
    card.appendChild(show);
    const join = el('div', 'pvp-join');
    [['ALL', t('products.filter_and')], ['ANY', t('products.filter_or')]].forEach(function (o) {
      const label = el('label');
      const radio = el('input');
      radio.type = 'radio';
      radio.name = 'pvp-join-' + f.key;
      radio.checked = s.match === o[0];
      radio.disabled = !f.multiple;
      radio.addEventListener('change', function () { s.match = o[0]; syncPanel(); });
      label.appendChild(radio);
      label.appendChild(el('span', '', o[1]));
      join.appendChild(label);
    });
    card.appendChild(join);
    s.rows.forEach(function (row, i) {
      card.appendChild(filterRowEl(f.filters, row, {
        rowClass: 'pvp-row', typeClass: 'pvp-type', onType: paintPanel, onInput: syncPanel,
        onRemove: function () {
          s.rows.splice(i, 1);
          if (!s.rows.length) delete panelState[f.key];   // no filters left: the card goes, and the field's filters are cleared on Save
          paintPanel();
        }
      }));
    });
    const add = el('button', 'pfl-add');
    add.type = 'button';
    add.appendChild(el('span', 'pfl-plus', '+'));
    add.appendChild(document.createTextNode(' ' + t('products.add_filter')));
    add.disabled = !f.multiple;   // a field that takes one filter shows it, but cannot add another
    if (add.disabled) add.title = t('products.filter_one_only');
    add.addEventListener('click', function () { s.rows.push({ type: '', value: '' }); paintPanel(); });
    card.appendChild(add);
    return card;
  }

  function paintPanel() {
    const cards = $('products-view-cards');
    cards.textContent = '';
    $('products-view-pick').disabled = !fields;
    if (!fields) {   // not read yet: balls, not a list that then changes
      cards.appendChild(ns.balls(t('products.panel_loading'), 'pvp-loading'));
      syncPanel();
      return;
    }
    Object.keys(panelState).forEach(function (key) { if (fieldByKey[key]) cards.appendChild(panelCard(fieldByKey[key])); });
    syncPanel();
  }

  // The columns of the view

  function viewColumns() { return host.definition() || []; }

  function colsChanged() { return JSON.stringify(colState) !== JSON.stringify(colBase); }

  /** What a column is called: the workspace's own title for it, else the view's. */
  function colTitle(key) {
    if (fieldByKey[key]) return fieldByKey[key].title;
    const own = viewColumns().filter(function (c) { return c.key === key; })[0];
    return own ? own.title : key;
  }

  function moveColumn(from, to) {
    colState.splice(to, 0, colState.splice(from, 1)[0]);
    paintColumns();
    const row = $('products-cols-shown').querySelectorAll('.pvp-col-row')[to];
    if (row) row.focus();
  }

  /** The columns shown, each with a grip to drag it by and a tick that hides it (a view keeps at least one). */
  function paintShown() {
    const list = $('products-cols-shown');
    const top = list.scrollTop;
    list.textContent = '';
    colState.forEach(function (key, index) {
      const row = el('div', 'pvp-col-row');
      row.tabIndex = 0;
      row.title = t('products.cols_row_hint');
      const grip = el('span', 'pvp-col-grip');
      grip.appendChild(ns.svg(ns.sortable.GRIP, 16));
      grip.addEventListener('pointerdown', function (event) {
        ns.sortable.start(event, row, list, '.pvp-col-row', function (from, to) { moveColumn(from, to); });
      });
      row.appendChild(grip);
      const tick = el('input');
      tick.type = 'checkbox';
      tick.checked = true;
      tick.disabled = colState.length < 2;
      tick.setAttribute('aria-label', t('products.cols_hide', { title: colTitle(key) }));
      tick.title = colState.length < 2 ? t('products.cols_last') : '';
      tick.addEventListener('change', function () { colState.splice(index, 1); paintColumns(); });
      row.appendChild(tick);
      row.appendChild(el('span', 'pvp-col-name', colTitle(key)));
      if (panelState[key]) {   // a column with a filter on it: a green funnel that opens the Filters tab
        const funnel = el('button', 'pvp-col-funnel');
        funnel.type = 'button';
        funnel.title = funnel.ariaLabel = t('products.view_filters');
        funnel.appendChild(ns.svg([FUNNEL], 14));
        funnel.addEventListener('click', function () { setTab('filters'); });
        row.appendChild(funnel);
      }
      row.addEventListener('keydown', function (event) {   // Alt+Up and Alt+Down move the row
        if (event.target !== row || !event.altKey || (event.key !== 'ArrowUp' && event.key !== 'ArrowDown')) return;
        event.preventDefault();
        const to = index + (event.key === 'ArrowUp' ? -1 : 1);
        if (to >= 0 && to < colState.length) moveColumn(index, to);
      });
      list.appendChild(row);
    });
    list.scrollTop = top;
  }

  /** The sections that open to the fields not shown yet; pressing a field shows it as the last column. */
  function paintAvailable() {
    const tree = $('products-cols-tree');
    const top = tree.scrollTop;
    tree.textContent = '';
    if (!fields) { tree.appendChild(ns.balls(t('products.panel_loading'), 'pvp-loading')); return; }
    paintGroups(tree, $('products-cols-search').value.trim().toLowerCase(), colOpen, paintAvailable,
      function (group) { return group.fields.filter(function (f) { return colState.indexOf(f.key) < 0; }); },
      function () { return false; },
      function (f) {
        const item = fieldButton(f);
        item.title = t('products.cols_show', { title: f.title });
        item.addEventListener('click', function () { colState.push(f.key); paintColumns(); });
        return item;
      });
    if (!tree.firstChild) tree.appendChild(el('p', 'muted pvp-empty', t('products.cols_none')));
    tree.scrollTop = top;
  }

  function paintColumns() {
    paintShown();
    paintAvailable();
    syncPanel();
  }

  /** Hang the panel under the buttons that open it, its right edge at the Columns button's, as tall as its content up to the window, with a
   *  point at the button of the tab in view. */
  function placePanel() {
    const panel = $('products-view-panel');
    if (panel.hidden) return;
    const filterButton = $('products-view-filter').getBoundingClientRect();
    const columnsButton = $('products-view-columns').getBoundingClientRect();
    const width = panel.offsetWidth;
    const top = Math.max(filterButton.bottom, columnsButton.bottom) + 8;
    const left = Math.max(8, Math.min(columnsButton.right - width, window.innerWidth - width - 8));
    const active = tab === 'filters' ? filterButton : columnsButton;
    panel.style.top = top + 'px';
    panel.style.left = left + 'px';
    panel.style.right = 'auto';
    panel.style.bottom = 'auto';
    panel.style.maxHeight = Math.max(260, window.innerHeight - top - 12) + 'px';
    panel.style.setProperty('--caret', Math.max(14, Math.min(width - 24, active.left + active.width / 2 - left - 5)) + 'px');
  }

  /** Show the Filters or the Columns tab of the open panel. */
  function setTab(name) {
    tab = name;
    const filters = name === 'filters';
    $('products-pane-filters').hidden = !filters;
    $('products-pane-columns').hidden = filters;
    [['products-tab-filters', filters], ['products-tab-columns', !filters]].forEach(function (p) {
      $(p[0]).classList.toggle('on', p[1]);
      $(p[0]).classList.toggle('off', !p[1]);
      $(p[0]).setAttribute('aria-selected', p[1] ? 'true' : 'false');
    });
    $('products-view-panel').setAttribute('aria-label', filters ? t('products.view_filters') : t('products.view_columns_tab'));
    closeTree();
    if (filters) paintPanel(); else paintColumns();
    placePanel();
  }
  function openPanel(name) {
    closeFilter();
    panelState = panelStateOfView();
    panelBase = panelStateOfView();
    colState = viewColumns().map(function (c) { return c.key; });
    colBase = colState.slice();
    $('products-view-pick').value = '';
    $('products-cols-search').value = '';
    $('products-view-panel').hidden = false;
    setTab(name || 'filters');
    loadFields();
  }

  /** The funnel and the columns button each open the panel on their tab; pressed again on the tab in view they close it, else they change tab. */
  function toggleTab(name) {
    if (panelState && tab === name) closePanel();
    else if (panelState) setTab(name);
    else openPanel(name);
  }

  function savePanel() {
    const changes = panelChanged().map(function (key) {
      const s = panelState[key];
      return changeOf(key, fieldByKey[key].filters, s ? s.match : 'ALL', s ? s.rows : []);
    });
    let columns = null;   // the columns to show, in order, when they were changed; none: the view's own stay as they are
    if (colsChanged()) {
      columns = colState.slice();
      changes.forEach(function (change) {   // a field filtered that is not shown is made a column by the filter: it must not be dropped here
        if (change.filters.length && columns.indexOf(change.column) < 0) columns.push(change.column);
      });
    }
    closePanel();
    host.apply(changes, columns);
  }

  /** ``host``: ``ask(action, payload, done)`` for the requests, ``fail(answer)`` to show a refused one, ``definition()`` for the columns of the view shown, ``apply(changes)`` to write
   *  filters (``[{column, match, filters}]``) into it and, when the columns were chosen, the keys of the columns to show in order (else null). */
  function init(h) {
    host = h;
    window.addEventListener('resize', placePanel);
    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape' || !(panelState || filterColumn)) return;
      event.stopPropagation();
      if (closeDropdown) closeDropdown();
      else if (filterColumn) closeFilter();
      else if ($('products-view-tree').hidden) closePanel();
      else closeTree();
    }, true);
    $('products-filter-cancel').addEventListener('click', closeFilter);
    $('products-filter-save').addEventListener('click', saveFilter);
    $('products-filter-add').addEventListener('click', function () { filterRows.push({ type: '', value: '' }); paintFilter(); });
    $('products-view-filter').addEventListener('click', function () { toggleTab('filters'); });
    $('products-view-columns').addEventListener('click', function () { toggleTab('columns'); });
    $('products-tab-filters').addEventListener('click', function () { setTab('filters'); });
    $('products-tab-columns').addEventListener('click', function () { setTab('columns'); });
    $('products-cols-search').addEventListener('input', paintAvailable);
    $('products-view-close').addEventListener('click', closePanel);
    $('products-view-cancel').addEventListener('click', closePanel);
    $('products-view-save').addEventListener('click', savePanel);
    const pick = $('products-view-pick');
    let treeWasOpen = false;   // whether the list was open when the box was pressed: pressing it again closes it
    pick.addEventListener('focus', openTree);
    pick.addEventListener('mousedown', function () { treeWasOpen = !$('products-view-tree').hidden; });
    pick.addEventListener('click', function () {
      if (treeWasOpen) closeTree(); else if ($('products-view-tree').hidden) openTree();
    });
    pick.addEventListener('input', function () { if ($('products-view-tree').hidden) openTree(); else paintTree(); });
    document.addEventListener('mousedown', function (event) {   // a press away from the pop-up closes it (a column's funnel toggles it itself)
      if (filterColumn && !event.target.closest('#products-filter-pop, .products-th-filter')) closeFilter();
    });
    document.addEventListener('mousedown', function (event) {   // a press away from the panel closes it (its own funnel toggles it; a column's funnel opens the pop-up instead)
      if (panelState && !event.target.closest('#products-view-panel, #products-view-filter, #products-view-columns, .products-th-filter, .pk-menu')) closePanel();
    });
    document.addEventListener('mousedown', function (event) {   // mousedown, not click: a click that repaints the list has taken its target out by then
      if (!$('products-view-tree').hidden && !event.target.closest('.pvp-pickwrap')) closeTree();
    });
  }

  ns.filters = { init: init, openColumn: openColumn, close: function () { closeFilter(); closePanel(); }, preload: loadFields, FUNNEL: FUNNEL };
})(window.MfgUi);
