/**
 * Publish Item panel: the Add Items picker, as ``ns.pubAddItems``. A dialog searches the Fusion Manage Items
 * workspace, by item descriptor text and by property filters, and adds the ticked items to the Bill of Materials
 * of the design's Fusion Manage item.
 *
 * Filters are rows (``property = value``) in groups; rows of a group, and groups, are joined by AND or OR. The
 * search itself is built in Python (``fm/search_query.py``): this file only sends the text and the groups.
 *
 * It is made to stay quick with thousands of matches:
 *   - pages load as the list is scrolled near its end, one request at a time, each on a Python worker thread
 *     (polled here), and a reply that no longer matches the search on screen is dropped;
 *   - a lot is as many visible rows as a page holds: when some of a page's items are hidden (the Bill of Materials already
 *     holds them) the next pages are read at once, until the lot is made up or the matches run out;
 *   - a page is appended once, as a fragment, rows are never rebuilt, and one click listener serves every row;
 *   - rows skip layout and paint while off screen (``content-visibility`` in add-items.css).
 * Items the Bill of Materials already holds, or that are staged in the panel, are left out of the list; a switch shows them ticked,
 * greyed and locked.
 */
(function (ns) {
  'use strict';

  const bridge = ns.bridge;
  const ui = ns.pubUi;
  const el = ui.el;
  function t(key, params) { return ns.i18n.t(key, params); }

  const POLL_MS = 200;          // wait between checks for an answer
  const PREFETCH_PX = 600;      // load the next page when this close to the end of the list
  const MIN_WIDTH = 760;        // smallest the dialog can be resized to
  const MIN_HEIGHT = 380;

  // The versions the search can list, by the search's ``revision`` filter.
  function versions() {   // the first is searched until another is picked
    return [{ revision: '3', label: t('publish.add_version_working') }, { revision: '1', label: t('publish.add_version_latest') }];
  }

  const KEEP = { shown: '{shown}', total: '{total}' };   // passed to ``t`` so that the two places stay in the text

  /** ``template`` (a text with ``{shown}`` and ``{total}`` left in it, see ``KEEP``) as nodes with each of the two numbers in bold. */
  function boldNumbers(template, shown, total) {
    const numbers = { shown: shown, total: total };
    const fragment = document.createDocumentFragment();
    template.split(/(\{shown\}|\{total\})/).forEach(function (part) {
      const name = /^\{(shown|total)\}$/.exec(part);
      if (name) fragment.appendChild(el('strong', '', numbers[name[1]]));
      else if (part) fragment.appendChild(document.createTextNode(part));
    });
    return fragment;
  }

  // State of the open dialog. ``generation`` changes whenever the search restarts, which makes every reply for the
  // old search stale; requests for the property list and picklists belong to the dialog, not to one search.

  let dialog = null;            // { overlay, list, ... } while open
  let generation = 0;
  let options = null;           // { itemId, staged: Set of ids already staged, onAdd(items) }
  let items = [];               // every loaded match, in list order
  let rows = new Map();         // item id -> its row element
  let byId = new Map();         // item id -> item
  let selected = new Map();     // item id -> item; survives searching and paging
  let total = 0;
  let offset = 0;               // rows of the search read so far (the next page starts here)
  let pageSize = 0;             // rows a page holds, as Python says with each page
  let wanted = 0;               // visible rows to have before waiting for the list to be scrolled: a lot more each time it is
  let query = null;             // { text, groups } of the search on screen
  let loading = false;
  let onlySelected = false;     // show only the ticked items
  let hideAdded = true;         // leave out the items the Bill of Materials already holds (the switch shows them)
  let failed = '';
  let frame = 0;
  let members = { ids: new Set(), numbers: new Set() };   // what the Bill of Materials holds
  let fields = [];              // filterable properties: { id, title, picklist }
  let fieldsNote = '';   // shown instead of the filters while the properties are not known
  let groups = [];              // filter groups being edited: { join, rows: [{ field, value, join }] }, join = how it connects to the one before
  let nextToken = 1;
  const waiting = new Map();    // token -> callback(entry) of a request in flight

  function moreToLoad() { return !failed && !!query && items.length < total && offset < total; }

  // ---- Talking to Python -------------------------------------------------------------

  /** Ask for ``action``; ``done(entry)`` gets the finished answer (``entry.ok``, ``entry.result`` or ``entry.message``). */
  function request(action, payload, done) {
    const token = String(nextToken++);
    waiting.set(token, { action: action, done: done });
    bridge.send(action, Object.assign({ token: token }, payload));
  }

  /** The bridge failed (the action raised before it could answer): finish the requests of ``action`` (every request when empty) as failed. */
  function failAll(action, message) {
    Array.from(waiting.entries()).forEach(function (pair) {
      if (action && pair[1].action !== action) return;
      waiting.delete(pair[0]);
      pair[1].done({ ok: false, message: message });
    });
  }

  function onAnswer(action, r) {
    if (!dialog) return;
    if (!r.ok) { failAll(action === 'search_status' ? '' : action, r.error || t('publish.unknown_error')); return; }
    const entry = r.result;
    const waiter = waiting.get(entry.token);
    if (!waiter) return;
    const done = waiter.done;
    if (entry.pending) {
      setTimeout(function () { if (waiting.has(entry.token)) bridge.send('search_status', { token: entry.token }); }, POLL_MS);
      return;
    }
    waiting.delete(entry.token);
    done(entry);
  }

  // ---- Loading matches ---------------------------------------------------------------

  function loadNext() {
    if (!dialog || loading || !query || (items.length && !moreToLoad())) return;   // the first page is wanted before the total is known
    loading = true;
    failed = '';
    paintStatus();
    const mine = generation;
    request('search_items', { item_id: options.itemId, text: query.text, groups: query.groups, revision: query.revision, offset: offset }, function (entry) {
      if (!dialog || mine !== generation) return;
      loading = false;
      if (!entry.ok) {
        failed = entry.message || t('publish.unknown_error');
        paintStatus();
        return;
      }
      append(entry.result);
      offset += entry.result.raw;
      // Every row is read: the count is that of the items shown. The search counts the design's own item too, which the list leaves out,
      // so its total would stay one too high ("61 of 62"). An empty page is the end as well, whatever the total said.
      if (!entry.result.raw || offset >= total) total = items.length;
      paintTotal();
      paintStatus();
      paintSelection();
      afterPage();
    });
  }

  function visibleCount() {
    return items.filter(function (item) { return !rows.get(item.id).hidden; }).length;
  }

  /** Read on while the lot is short of visible rows (some of a page is hidden) or the list is too short to scroll; a scroll to the end asks for the next lot. */
  function afterPage() {
    if (!moreToLoad() || onlySelected) return;
    if (visibleCount() < wanted) { loadNext(); return; }
    const list = dialog.list;
    if (list.scrollHeight - list.scrollTop - list.clientHeight < PREFETCH_PX) {
      wanted = visibleCount() + pageSize;
      loadNext();
    }
  }

  function onScroll() {
    if (frame) return;
    frame = requestAnimationFrame(function () {
      frame = 0;
      if (dialog) afterPage();
    });
  }

  /** What the Bill of Materials holds now, for the greying out; rows already drawn are repainted when it arrives. */
  function loadMembers() {
    request('search_members', { item_id: options.itemId }, function (entry) {
      if (!dialog || !entry.ok) return;   // without it only the panel's own staged items are locked
      members = { ids: new Set(entry.result.ids), numbers: new Set(entry.result.numbers) };
      repaintRows();
    });
  }

  function loadFields() {
    request('search_fields', {}, function (entry) {
      if (!dialog) return;
      fields = entry.ok ? entry.result.fields : [];
      fieldsNote = entry.ok ? (fields.length ? '' : t('publish.add_no_properties')) : t('publish.add_props_failed', { message: entry.message || t('publish.unknown_error') });
      renderFilters();
    });
  }

  // ---- Drawing the matches -----------------------------------------------------------

  function itemText(item) {
    return [item.number, item.name].filter(Boolean).join(' - ');
  }

  function isAdded(item) {
    return options.staged.has(item.id) || members.ids.has(item.id) || (!!item.number && members.numbers.has(item.number));
  }

  /** Tick state and look of a row: an item already in the Bill of Materials is ticked, greyed and locked. */
  function paintRow(item, row) {
    const added = isAdded(item);
    const box = row.firstChild;
    if (added) selected.delete(item.id);
    box.checked = added || selected.has(item.id);
    box.disabled = added;
    row.classList.toggle('pub-add-row-added', added);
    row.hidden = (hideAdded && added) || (onlySelected && !added && !selected.has(item.id));
    row.title = added ? t('publish.add_already', { item: itemText(item) }) : itemText(item);
  }

  function buildRow(item) {
    const row = el('div', 'pub-add-row');
    row.dataset.id = item.id;
    const box = el('input', 'pub-add-check');
    box.type = 'checkbox';
    box.setAttribute('aria-label', itemText(item));
    row.appendChild(box);
    const text = el('div', 'pub-add-text');
    text.appendChild(el('div', 'pub-add-number', item.number || item.name));
    if (item.number && item.name) text.appendChild(el('div', 'pub-add-name', item.name));
    row.appendChild(text);
    if (item.version) row.appendChild(el('span', 'pub-add-rev', t('publish.add_rev', { version: item.version })));
    paintRow(item, row);
    return row;
  }

  function append(page) {
    total = page.total;
    pageSize = page.limit || pageSize;
    if (!wanted) wanted = pageSize;   // the first page: a lot is wanted before the list waits for a scroll
    const fragment = document.createDocumentFragment();
    page.items.forEach(function (item) {
      if (byId.has(item.id)) return;
      items.push(item);
      byId.set(item.id, item);
      const row = buildRow(item);
      rows.set(item.id, row);
      fragment.appendChild(row);
    });
    dialog.list.insertBefore(fragment, dialog.status);
    paintTotal();
  }

  /** "50 of 1,234", and how many of the loaded items are left out while the added ones are hidden. */
  function paintTotal() {
    const box = dialog.total;
    box.textContent = '';
    box.hidden = !items.length && !total;
    if (box.hidden) return;
    const left = (hideAdded || onlySelected) ? items.filter(function (item) { return rows.get(item.id).hidden; }).length : 0;
    box.appendChild(boldNumbers(t('publish.add_of', KEEP), items.length.toLocaleString(), Math.max(total, items.length).toLocaleString()));
    if (left) box.appendChild(el('span', 'pub-add-total-note', t('publish.add_hidden_count', { count: left.toLocaleString() })));
  }

  function paintStatus() {
    const status = dialog.status;
    status.textContent = '';
    status.className = 'pub-add-status';
    status.hidden = false;
    if (failed) {
      status.classList.add('pub-add-status-card');
      status.appendChild(ui.svg(['M12 3l10 18H2z', 'M12 10v5', 'M12 18.2v.3'], 28));
      status.appendChild(el('h4', 'pub-error-title', t('publish.add_load_failed')));
      status.appendChild(el('p', 'muted', failed));
      const retry = el('button', 'pub-outline-button pub-retry', t('publish.retry'));
      retry.type = 'button';
      retry.addEventListener('click', loadNext);
      status.appendChild(retry);
    } else if (loading && !items.length) {
      status.classList.add('pub-add-status-card');
      status.appendChild(ui.loaderNode());
    } else if (loading) {   // later pages: small bouncing balls beside the caption
      status.classList.add('pub-add-status-busy');
      const balls = el('div', 'balls');
      balls.setAttribute('role', 'status');
      balls.setAttribute('aria-label', t('publish.loading_aria'));
      for (let i = 0; i < 3; i++) balls.appendChild(el('span'));
      status.appendChild(balls);
      status.appendChild(el('span', '', t('publish.add_loading_more')));
    } else if (!items.length) {
      status.textContent = t('publish.add_no_match');
    } else if ((onlySelected || !moreToLoad()) && items.every(function (item) { return rows.get(item.id).hidden; })) {
      status.textContent = onlySelected ? t('publish.add_none_selected') : t('publish.add_all_added');
    } else {
      status.hidden = true;
    }
  }

  /** The count, the status line and the footer. */
  function paintAll() {
    paintTotal();
    paintStatus();
    paintSelection();
  }

  /** Draw every row, the count and the status again after a switch changed what is shown. */
  function repaintRows() {
    items.forEach(function (item) { paintRow(item, rows.get(item.id)); });
    paintAll();
    afterPage();   // hidden rows leave the list short: fetch more to fill it
  }

  /** One box was ticked or unticked. Only a narrowed list changes with it: the row may have to leave. */
  function tickChanged(item, row) {
    if (!onlySelected) { paintSelection(); return; }
    if (!selected.size) { onlySelected = false; dialog.only.checked = false; repaintRows(); return; }   // nothing left to narrow to
    paintRow(item, row);
    paintAll();
  }

  /** Untick everything. */
  function clearSelection() {
    selected = new Map();
    onlySelected = false;
    dialog.only.checked = false;
    repaintRows();
  }

  /** Footer count and the Clear and Add buttons. */
  function paintSelection() {
    const count = selected.size;
    dialog.only.disabled = count === 0;
    dialog.add.disabled = count === 0;
    dialog.clear.disabled = count === 0;
    dialog.count.textContent = t('publish.add_selected_count', { count: count });
  }

  /** The filter groups as the search takes them: a row's ``join`` says how it connects to the NEXT row. */
  function payloadGroups() {
    return groups.map(function (group, g) {
      return {
        join: g + 1 < groups.length ? groups[g + 1].join : 'AND',
        filters: group.rows.map(function (row, r) {
          return { field: row.field, value: row.value, join: r + 1 < group.rows.length ? group.rows[r + 1].join : 'AND' };
        }),
      };
    });
  }

  /** Throw the list away and search from the start. Ticked items stay ticked. */
  function restart() {
    generation++;
    loading = false;
    failed = '';
    rows.forEach(function (row) { row.remove(); });
    items = [];
    rows = new Map();
    byId = new Map();
    total = 0;
    offset = 0;
    wanted = 0;
    query = { text: dialog.search.value.trim(), groups: payloadGroups(), revision: dialog.version.getPicked()[0].value };
    dialog.list.scrollTop = 0;
    paintTotal();
    paintSelection();
    loadNext();
  }

  // ---- The filters -------------------------------------------------------------------

  function newRow(join) { return { field: '', value: '', join: join || 'AND' }; }

  function fieldOf(id) {
    return fields.find(function (f) { return f.id === id; }) || null;
  }

  /** AND / OR segmented switch that connects a row (or group) to the one before it. */
  function joinSwitch(join, label, onChange) {   // the buttons say AND and OR; the value passed on stays AND or OR
    const wrap = el('div', 'pub-add-join');
    wrap.setAttribute('role', 'group');
    wrap.setAttribute('aria-label', label);
    const buttons = [['AND', t('publish.add_and')], ['OR', t('publish.add_or')]].map(function (pair) {
      const name = pair[0];
      const button = el('button', 'pub-add-join-option', pair[1]);
      button.type = 'button';
      button.setAttribute('aria-pressed', String(name === join));
      button.addEventListener('click', function () {
        onChange(name);
        buttons.forEach(function (b) { b.setAttribute('aria-pressed', String(b === button)); });
      });
      wrap.appendChild(button);
      return button;
    });
    return wrap;
  }

  /** A round button with an X in it. */
  function iconButton(className, label, size, onClick) {
    const button = el('button', className);
    button.type = 'button';
    button.title = label;
    button.setAttribute('aria-label', label);
    button.appendChild(ui.svg(['M6 6l12 12', 'M18 6L6 18'], size));
    button.addEventListener('click', onClick);
    return button;
  }

  /** A switch with its label: ``{ label, box }``. */
  function switchLabel(text, title) {
    const label = el('label', 'pub-add-switch');
    const box = el('input');
    box.type = 'checkbox';
    label.appendChild(box);
    label.appendChild(el('span', '', text));
    label.title = title;
    return { label: label, box: box };
  }

  // The drop-downs are the shared picker (shared/js/picker.js), dressed for this page in add-items.css.

  /** The choice of which versions to search: the picker over ``versions()``, with no empty choice. ``changed()`` is called when another is picked. */
  function versionPicker(changed) {
    const choices = versions();
    let value = choices[0].revision;
    const picker = ns.picker.make({
      className: 'pub-add-pk pub-add-version-wrap',
      buttonClass: 'pub-add-version',
      ariaLabel: t('publish.add_version'),
      tip: function () { return t('publish.add_version_title'); },
      required: true,
      searchFrom: Infinity,
      search: '',
      label: function (revision) { return choices.find(function (c) { return c.revision === revision; }).label; },
      groups: function () { return [{ title: '', items: choices.map(function (c) { return { value: c.revision, label: c.label }; }) }]; },
    }, value);
    picker.addEventListener('pick', function () {
      const next = picker.getPicked()[0].value;
      if (next === value) return;
      value = next;
      changed();
    });
    return picker;
  }

  /**
   * A drop-down in place of a native select: the picker, with a round X on the field while a value is chosen. ``source`` is either
   * ``[{ value, label }]`` (a short list, searched here) or a picker source ``function (text, offset, done)`` for a long one: it is read in
   * batches as the list is scrolled, and typing searches it on the server. ``pick(value)`` is called on a choice, with '' when it is cleared.
   */
  function combo(source, value, placeholder, pick, kind) {   // ``kind``: 'property' or 'value', which names the box for a screen reader
    const remote = typeof source === 'function';
    const wrap = el('div', 'pub-add-combo-wrap');
    const picker = ns.picker.make(Object.assign({
      className: 'pub-add-pk',
      buttonClass: 'pub-add-combo',
      ariaLabel: kind === 'property' ? t('publish.add_property') : t('publish.add_value'),
      required: true,   // the X on the field clears it
      placeholder: placeholder,
      search: t('publish.add_menu_search'),
      empty: function (box) { return box.querySelector('.pk-search').value.trim() ? t('publish.add_menu_no_match') : t('publish.add_menu_empty'); },
      text: {
        loading: t('publish.loading_aria'),
        showing: function (shown, total) { return t('publish.add_showing', { shown: shown.toLocaleString(), total: total.toLocaleString() }); },
      },
      label: remote ? function (v) { return v; } : function (v) { return source.find(function (e) { return e.value === v; }).label; },
    }, remote ? { source: source } : { groups: function () { return [{ title: '', items: source }]; } }), value);

    function paintSet() { wrap.classList.toggle('pub-add-combo-set', picker.getPicked().length > 0); }
    picker.addEventListener('pick', function () { paintSet(); pick(picker.getPicked()[0].value); });
    wrap.appendChild(picker);
    wrap.appendChild(iconButton('pub-add-combo-clear', kind === 'property' ? t('publish.add_clear_property') : t('publish.add_clear_value'), 10, function () {
      picker.setPicked([]);
      paintSet();
      pick('');
    }));
    paintSet();
    return wrap;
  }

  /** The value box of a row: a searchable list, read in batches, for a picklist property, else a text box. */
  function valueControl(row) {
    const field = fieldOf(row.field);
    if (field && field.picklist) {
      const source = function (text, from, done) {
        request('search_options', { lookup: field.picklist, offset: from, text: text }, function (entry) {
          if (!entry.ok) { done({ error: t('publish.add_menu_failed') }); return; }
          const page = entry.result;
          done({
            items: page.options.map(function (o) { return { value: o.title, label: o.title }; }),
            next: from + page.raw,
            total: page.raw ? page.total : 0,   // an empty page is the end, whatever the total says
          });
        });
      };
      return combo(source, row.value, t('publish.add_select_value'), function (value) { row.value = value; }, 'value');
    }
    const input = el('input', 'pub-add-input');
    input.type = 'text';
    input.placeholder = field ? t('publish.add_value') : t('publish.add_property_first');
    input.disabled = !field;
    input.value = row.value;
    input.setAttribute('aria-label', t('publish.add_value'));
    input.addEventListener('input', function () { row.value = input.value; });
    input.addEventListener('keydown', function (event) { if (event.key === 'Enter') restart(); });
    return input;
  }

  function buildFilterRow(group, row, first) {
    const wrap = el('div', 'pub-add-filter-row');
    if (!first) wrap.appendChild(joinSwitch(row.join, t('publish.add_join_row'), function (join) { row.join = join; }));
    const line = el('div', 'pub-add-filter-line');
    const entries = fields.map(function (f) { return { value: f.id, label: f.title }; });
    line.appendChild(combo(entries, row.field, t('publish.add_choose_property'), function (id) {
      row.field = id;
      row.value = '';
      renderFilters();
    }, 'property'));
    if (group.rows.length > 1 || groups.length > 1) {
      line.appendChild(iconButton('pub-add-remove', t('publish.add_remove_row'), 12, function () {
        group.rows.splice(group.rows.indexOf(row), 1);
        if (!group.rows.length) groups.splice(groups.indexOf(group), 1);
        if (!groups.length) groups.push({ join: 'AND', rows: [newRow()] });
        renderFilters();
      }));
    }
    wrap.appendChild(line);
    wrap.appendChild(valueControl(row));
    return wrap;
  }

  /** Draw the filter groups (again). Called when the properties arrive or the rows change; typing does not redraw. */
  function renderFilters() {
    const host = dialog.filters;
    host.textContent = '';
    dialog.filterNote.textContent = fieldsNote;
    dialog.filterNote.hidden = !fieldsNote;
    if (fieldsNote && !fields.length) return;
    groups.forEach(function (group, g) {
      if (g > 0) host.appendChild(joinSwitch(group.join, t('publish.add_join_group'), function (join) { group.join = join; }));
      const box = el('div', 'pub-add-group');
      const head = el('div', 'pub-add-group-head', groups.length > 1 ? t('publish.add_group_n', { number: g + 1 }) : t('publish.add_filter_head'));
      box.appendChild(head);
      group.rows.forEach(function (row, r) { box.appendChild(buildFilterRow(group, row, r === 0)); });
      const addRow = el('button', 'pub-add-link', t('publish.add_row'));
      addRow.type = 'button';
      addRow.addEventListener('click', function () { group.rows.push(newRow()); renderFilters(); });
      box.appendChild(addRow);
      host.appendChild(box);
    });
    const addGroup = el('button', 'pub-add-dashed', t('publish.add_group'));
    addGroup.type = 'button';
    addGroup.addEventListener('click', function () { groups.push({ join: 'AND', rows: [newRow()] }); renderFilters(); });
    host.appendChild(addGroup);
  }

  // ---- The dialog --------------------------------------------------------------------

  function close() {
    if (!dialog) return;
    generation++;
    waiting.clear();
    document.removeEventListener('keydown', onKey);
    dialog.overlay.remove();
    dialog = null;
    items = []; rows = new Map(); byId = new Map(); selected = new Map(); groups = [];
  }

  function onKey(event) {
    if (event.key === 'Escape') close();
  }

  function confirm() {
    const picked = Array.from(selected.values());
    const callback = options.onAdd;
    close();
    if (picked.length) callback(picked);
  }

  /**
   * Let the user drag the dialog by its title bar and resize it from the right edge, bottom edge or corner.
   * The first move pins the dialog at its current place (it starts centred); the list then takes the extra height.
   */
  function enableMoveAndResize(box, titleBar) {
    function pin() {
      if (box.classList.contains('sized')) return;
      const r = box.getBoundingClientRect();
      box.classList.add('sized');
      box.style.left = r.left + 'px';
      box.style.top = r.top + 'px';
      box.style.width = r.width + 'px';
      box.style.height = r.height + 'px';
    }

    // Follow the pointer until it is released; ``move(dx, dy)`` gets the distance from where it went down.
    function track(down, move, done) {
      down.preventDefault();
      const target = down.currentTarget;
      const x0 = down.clientX, y0 = down.clientY;
      const from = box.getBoundingClientRect();
      target.setPointerCapture(down.pointerId);
      function onMove(event) { move(event.clientX - x0, event.clientY - y0, from); }
      function onUp() {
        target.removeEventListener('pointermove', onMove);
        target.removeEventListener('pointerup', onUp);
        target.removeEventListener('pointercancel', onUp);
        if (done) done();
      }
      target.addEventListener('pointermove', onMove);
      target.addEventListener('pointerup', onUp);
      target.addEventListener('pointercancel', onUp);
    }

    titleBar.classList.add('pub-add-drag');
    titleBar.addEventListener('pointerdown', function (event) {
      if (event.button !== 0 || event.target.closest('button')) return;
      pin();
      track(event, function (dx, dy, from) {
        // Keep the title bar reachable: never fully off screen.
        box.style.left = Math.min(window.innerWidth - 80, Math.max(80 - from.width, from.left + dx)) + 'px';
        box.style.top = Math.min(window.innerHeight - 32, Math.max(0, from.top + dy)) + 'px';
      });
    });

    [['right', true, false], ['bottom', false, true], ['corner', true, true]].forEach(function (edge) {
      const grip = el('div', 'pub-add-grip pub-add-grip-' + edge[0]);
      grip.addEventListener('pointerdown', function (event) {
        if (event.button !== 0) return;
        pin();
        track(event, function (dx, dy, from) {
          if (edge[1]) box.style.width = Math.max(MIN_WIDTH, Math.min(window.innerWidth - from.left, from.width + dx)) + 'px';
          if (edge[2]) box.style.height = Math.max(MIN_HEIGHT, Math.min(window.innerHeight - from.top, from.height + dy)) + 'px';
        }, onScroll);   // a taller list may need its next page
      });
      box.appendChild(grip);
    });
  }

  function build() {
    const overlay = el('div', 'pub-add-overlay');
    const box = el('div', 'pub-add-dialog');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-label', t('publish.add_dialog_label'));

    const titleBar = el('div', 'pub-add-title');
    const title = el('h2', 'pub-add-heading', t('publish.add_items'));
    title.id = 'pub-add-heading';
    box.setAttribute('aria-labelledby', title.id);
    const closeButton = iconButton('pub-add-close', t('publish.close'), undefined, close);
    titleBar.appendChild(title);
    titleBar.appendChild(closeButton);
    box.appendChild(titleBar);

    const body = el('div', 'pub-add-body');
    box.appendChild(body);

    const top = el('div', 'pub-add-top');
    const search = el('input', 'pub-add-filter');
    search.type = 'search';
    search.placeholder = t('publish.add_search_placeholder');
    search.setAttribute('aria-label', t('publish.add_search_label'));
    const version = versionPicker(function () { restart(); });
    const searchButton = el('button', 'btn', t('publish.add_search'));
    searchButton.type = 'button';
    top.appendChild(search);
    top.appendChild(version);
    top.appendChild(searchButton);
    body.appendChild(top);

    const panes = el('div', 'pub-add-panes');
    body.appendChild(panes);

    // Left: the property filters.
    const side = el('div', 'pub-add-side');
    const filterNote = el('p', 'pub-add-note muted');
    const filters = el('div', 'pub-add-filters');
    side.appendChild(filterNote);
    side.appendChild(filters);
    panes.appendChild(side);

    // Right: the matches.
    const main = el('div', 'pub-add-main');
    const resultsHead = el('div', 'pub-add-results-head');
    resultsHead.appendChild(el('span', 'pub-add-results-title', t('publish.add_results')));
    const totalLine = el('span', 'pub-add-total');
    resultsHead.appendChild(totalLine);
    const hideSwitch = switchLabel(t('publish.add_show_hidden'), t('publish.add_show_hidden_title'));
    const hideBox = hideSwitch.box;
    resultsHead.appendChild(hideSwitch.label);
    main.appendChild(resultsHead);
    const list = el('div', 'pub-add-list');
    const status = el('div', 'pub-add-status');
    list.appendChild(status);
    main.appendChild(list);
    panes.appendChild(main);

    const footer = el('div', 'pub-add-footer');
    const count = el('span', 'pub-add-count');
    footer.appendChild(count);
    const onlySwitch = switchLabel(t('publish.add_show_selected'), t('publish.add_show_selected_title'));
    const onlyBox = onlySwitch.box;
    onlyBox.disabled = true;
    footer.appendChild(onlySwitch.label);
    const cancel = el('button', 'btn btn-secondary', t('publish.cancel'));
    cancel.type = 'button';
    const clear = el('button', 'btn btn-secondary', t('publish.add_clear'));
    clear.type = 'button';
    const add = el('button', 'btn', t('publish.add_to_bom'));
    add.type = 'button';
    footer.appendChild(cancel);
    footer.appendChild(clear);
    footer.appendChild(add);
    box.appendChild(footer);
    overlay.appendChild(box);
    enableMoveAndResize(box, titleBar);

    // One listener serves every row; a click anywhere on an unlocked row ticks it.
    list.addEventListener('click', function (event) {
      const row = event.target.closest('.pub-add-row');
      const item = row && byId.get(row.dataset.id);
      if (!item || isAdded(item)) return;
      const tick = row.firstChild;
      if (event.target !== tick) tick.checked = !tick.checked;
      if (tick.checked) selected.set(item.id, item); else selected.delete(item.id);
      tickChanged(item, row);
    });
    list.addEventListener('scroll', onScroll, { passive: true });
    search.addEventListener('keydown', function (event) { if (event.key === 'Enter') restart(); });
    searchButton.addEventListener('click', restart);
    clear.addEventListener('click', clearSelection);
    cancel.addEventListener('click', close);
    onlyBox.addEventListener('change', function () {
      onlySelected = onlyBox.checked;
      repaintRows();
    });
    add.addEventListener('click', confirm);
    hideBox.addEventListener('change', function () {
      hideAdded = !hideBox.checked;
      repaintRows();
    });
    overlay.addEventListener('mousedown', function (event) { if (event.target === overlay) close(); });
    document.addEventListener('keydown', onKey);
    document.body.appendChild(overlay);
    return { overlay: overlay, list: list, status: status, total: totalLine, add: add, clear: clear, count: count, only: onlyBox, search: search, version: version, filters: filters, filterNote: filterNote };
  }

  /**
   * Open the picker for a Fusion Manage item. ``opts``: ``itemId`` (the item whose BOM gets the items),
   * ``staged`` (ids already picked, shown ticked and locked) and ``onAdd(items)`` with the items the user added.
   */
  function open(opts) {
    close();
    options = { itemId: opts.itemId, staged: new Set(opts.staged || []), onAdd: opts.onAdd };
    generation++;
    hideAdded = true;
    onlySelected = false;
    fields = []; fieldsNote = t('publish.add_loading_props');
    members = { ids: new Set(), numbers: new Set() };
    groups = [{ join: 'AND', rows: [newRow()] }];
    dialog = build();
    renderFilters();
    paintSelection();
    dialog.search.focus();
    loadFields();
    loadMembers();
    restart();   // lists every item to begin with
  }

  ['search_items', 'search_fields', 'search_options', 'search_members', 'search_status'].forEach(function (action) { bridge.on(action, function (r) { onAnswer(action, r); }); });

  ns.pubAddItems = { open: open };
})(window.MfgUi);
