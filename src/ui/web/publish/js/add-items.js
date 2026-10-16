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
 *   - a page is appended once, as a fragment, rows are never rebuilt, and one click listener serves every row;
 *   - rows skip layout and paint while off screen (``content-visibility`` in add-items.css).
 * Items the Bill of Materials already holds, or that are staged in the panel, are shown ticked, greyed and locked.
 */
(function (ns) {
  'use strict';

  const bridge = ns.bridge;
  const el = ns.pubUi.el;

  const POLL_MS = 200;          // wait between checks for an answer
  const PREFETCH_PX = 600;      // load the next page when this close to the end of the list
  const MIN_WIDTH = 760;        // smallest the dialog can be resized to
  const MIN_HEIGHT = 380;
  const MENU_ROWS = 100;        // most choices a local drop-down draws at once; typing narrows it
  const MENU_PREFETCH_PX = 60;  // load the next batch of a long drop-down when this close to its end
  const MENU_SEARCH_MS = 250;   // typing pause before a long drop-down is searched

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
  let query = null;             // { text, groups } of the search on screen
  let loading = false;
  let onlySelected = false;     // show only the ticked items
  let hideAdded = true;         // leave out the items the Bill of Materials already holds (the switch shows them)
  let failed = '';
  let frame = 0;
  let members = { ids: new Set(), numbers: new Set() };   // what the Bill of Materials holds
  let fields = [];              // filterable properties: { id, title, picklist }
  let fieldsNote = 'Loading properties...';   // shown instead of the filters while the properties are not known
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
    if (!r.ok) { failAll(action === 'search_status' ? '' : action, r.error || 'Unknown error'); return; }
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
    request('search_items', { item_id: options.itemId, text: query.text, groups: query.groups, offset: offset }, function (entry) {
      if (!dialog || mine !== generation) return;
      loading = false;
      if (!entry.ok) {
        failed = entry.message || 'Unknown error';
        paintStatus();
        return;
      }
      append(entry.result);
      offset += entry.result.raw;
      if (!entry.result.raw) total = items.length;   // an empty page is the end, whatever the total said
      paintStatus();
      paintSelection();
      afterPage();
    });
  }

  /** Keep loading while the list is too short to scroll. */
  function afterPage() {
    if (!moreToLoad() || onlySelected) return;
    const list = dialog.list;
    if (list.scrollHeight - list.scrollTop - list.clientHeight < PREFETCH_PX) loadNext();
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
      fieldsNote = entry.ok ? (fields.length ? '' : 'The workspace has no properties to filter by.') : 'Could not load the properties: ' + (entry.message || 'Unknown error');
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
    row.title = added ? itemText(item) + ' (already in the Bill of Materials)' : itemText(item);
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
    if (item.version) row.appendChild(el('span', 'pub-add-rev', 'REV:' + item.version));
    paintRow(item, row);
    return row;
  }

  function append(page) {
    total = page.total;
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
    box.appendChild(el('strong', '', items.length.toLocaleString()));
    box.appendChild(document.createTextNode(' of '));
    box.appendChild(el('strong', '', Math.max(total, items.length).toLocaleString()));
    if (left) box.appendChild(el('span', 'pub-add-total-note', left.toLocaleString() + ' hidden'));
  }

  function paintStatus() {
    const status = dialog.status;
    status.textContent = '';
    status.className = 'pub-add-status';
    status.hidden = false;
    if (failed) {
      status.classList.add('pub-add-status-card');
      status.appendChild(ns.pubUi.svg(['M12 3l10 18H2z', 'M12 10v5', 'M12 18.2v.3'], 28));
      status.appendChild(el('h4', 'pub-error-title', 'Could not load items'));
      status.appendChild(el('p', 'muted', failed));
      const retry = el('button', 'pub-outline-button pub-retry', 'Retry');
      retry.type = 'button';
      retry.addEventListener('click', loadNext);
      status.appendChild(retry);
    } else if (loading && !items.length) {
      status.classList.add('pub-add-status-card');
      status.appendChild(ns.pubUi.loaderNode());
    } else if (loading) {   // later pages: small bouncing balls beside the caption
      status.classList.add('pub-add-status-busy');
      const balls = el('div', 'balls');
      balls.setAttribute('role', 'status');
      balls.setAttribute('aria-label', 'Loading');
      for (let i = 0; i < 3; i++) balls.appendChild(el('span'));
      status.appendChild(balls);
      status.appendChild(el('span', '', 'Loading more...'));
    } else if (!items.length) {
      status.textContent = 'No items match the search.';
    } else if ((onlySelected || !moreToLoad()) && items.every(function (item) { return rows.get(item.id).hidden; })) {
      status.textContent = onlySelected ? 'No items are selected yet.' : 'Every item found is already in the Bill of Materials. Turn on "Show hidden items" to see them.';
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
    dialog.count.textContent = count + ' selected';
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
    query = { text: dialog.search.value.trim(), groups: payloadGroups() };
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

  /** A small spinning circle. */
  function spinner() {
    const node = el('span', 'pub-add-spinner');
    node.setAttribute('role', 'status');
    node.setAttribute('aria-label', 'Loading');
    return node;
  }

  /** AND / OR segmented switch that connects a row (or group) to the one before it. */
  function joinSwitch(join, label, onChange) {
    const wrap = el('div', 'pub-add-join');
    wrap.setAttribute('role', 'group');
    wrap.setAttribute('aria-label', label);
    const buttons = ['AND', 'OR'].map(function (name) {
      const button = el('button', 'pub-add-join-option', name);
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
    button.appendChild(ns.pubUi.svg(['M6 6l12 12', 'M18 6L6 18'], size));
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

  // One drop-down list is open at a time; it hangs off the document so the filter pane cannot clip it.
  let openMenu = null;   // { menu, button }

  function closeMenu() {
    if (!openMenu) return;
    openMenu.onClose();
    openMenu.menu.remove();
    openMenu.button.setAttribute('aria-expanded', 'false');
    document.removeEventListener('mousedown', onOutside, true);
    openMenu = null;
  }

  function onOutside(event) {
    if (openMenu && !openMenu.menu.contains(event.target) && !openMenu.button.contains(event.target)) closeMenu();
  }

  /**
   * A drop-down in place of a native select: a button showing the choice, and a floating list with a search box and a
   * count ("50 of 1,234"). ``source`` is either ``[{ value, label }]`` (a short list, searched here) or
   * ``{ load(offset, text, done) }`` for a long one: it is read in batches as the list is scrolled, and typing
   * searches it on the server. ``done`` gets ``{ options: [{ title }], total, raw }``, or null when the read failed.
   * ``pick(value)`` is called on a choice.
   */
  function combo(source, value, placeholder, pick, label) {
    const remote = !Array.isArray(source);
    const wrap = el('div', 'pub-add-combo-wrap');
    const button = el('button', 'pub-add-combo');
    button.type = 'button';
    button.setAttribute('aria-haspopup', 'listbox');
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-label', label);
    const text = el('span', 'pub-add-combo-text');
    button.appendChild(text);
    button.appendChild(ns.pubUi.svg(['M6 9l6 6 6-6'], 14));
    wrap.appendChild(button);
    // A round X on the field itself, shown while a value is chosen.
    wrap.appendChild(iconButton('pub-add-combo-clear', 'Clear ' + label.toLowerCase(), 10, function () { set(''); }));

    function paintLabel() {
      const found = remote ? null : source.find(function (e) { return e.value === value; });
      text.textContent = found ? found.label : (value || placeholder);
      button.classList.toggle('pub-add-combo-empty', !value);
      wrap.classList.toggle('pub-add-combo-set', !!value);
    }
    paintLabel();

    /** Take ``next`` as the value (empty clears it) and close the list. */
    function set(next) {
      value = next;
      paintLabel();
      closeMenu();
      pick(next);
    }

    button.addEventListener('click', function () {
      if (openMenu && openMenu.button === button) { closeMenu(); return; }
      closeMenu();
      const menu = el('div', 'pub-add-menu');
      const search = el('input', 'pub-add-menu-search');
      search.type = 'search';
      search.placeholder = 'Search...';
      search.setAttribute('aria-label', 'Search the list');
      const count = el('div', 'pub-add-menu-count');
      const options = el('div', 'pub-add-menu-list');
      options.setAttribute('role', 'listbox');
      menu.appendChild(search);
      menu.appendChild(count);
      menu.appendChild(options);

      // What the list holds: for a long list the batches read so far, for a short one every entry.
      let entries = remote ? [] : source;
      let total = entries.length;
      let nextOffset = 0;
      let busy = false;
      let failedRead = false;
      let round = 0;        // changes with every new search, so a slow batch of an old one is dropped
      let started = false;  // the first batch of this search has been read, so the total is known
      let searchTimer = 0;

      function visible() {
        if (remote) return entries;
        const needle = search.value.trim().toLowerCase();
        return entries.filter(function (entry) { return !needle || entry.label.toLowerCase().indexOf(needle) >= 0; }).slice(0, MENU_ROWS);
      }

      function paint() {
        const shown = visible();
        if (!remote) total = shown.length;
        // Header: "Showing 50 of 1,234", with a spinner while a batch is on its way.
        count.textContent = '';
        const line = el('span', 'pub-add-menu-count-text');   // one box, so the flex row does not spread its words apart
        if (failedRead) {
          line.classList.add('pub-add-menu-error');
          line.textContent = 'Could not load the list';
        } else if (busy && !shown.length) {
          line.textContent = 'Loading...';
        } else {
          line.appendChild(document.createTextNode('Showing '));
          line.appendChild(el('strong', '', shown.length.toLocaleString()));
          line.appendChild(document.createTextNode(' of '));
          line.appendChild(el('strong', '', Math.max(total, shown.length).toLocaleString()));
        }
        count.appendChild(line);
        if (busy) count.appendChild(spinner());
        options.textContent = '';
        shown.forEach(function (entry) {
          const option = el('button', 'pub-add-menu-option', entry.label);
          option.type = 'button';
          option.setAttribute('role', 'option');
          option.setAttribute('aria-selected', String(entry.value === value));
          option.addEventListener('click', function () { set(entry.value); });
          options.appendChild(option);
        });
        if (busy) {
          const row = el('div', 'pub-add-menu-loading');
          row.appendChild(spinner());
          row.appendChild(el('span', '', shown.length ? 'Loading more...' : 'Loading values...'));
          options.appendChild(row);
        } else if (!shown.length) {
          options.appendChild(el('div', 'pub-add-menu-none', failedRead ? 'Try again in a moment' : (remote && !search.value.trim() ? 'Nothing to choose from' : 'No match')));
        }
      }

      /** Read the next batch of a long list (the first when the list is new). */
      function more() {
        if (!remote || busy || failedRead || (started && entries.length >= total)) return;
        busy = true;
        const mine = round;
        paint();
        source.load(nextOffset, search.value.trim(), function (page) {
          if (!openMenu || openMenu.menu !== menu || mine !== round) return;
          busy = false;
          if (!page) { failedRead = true; paint(); return; }
          started = true;
          page.options.forEach(function (o) { entries.push({ value: o.title, label: o.title }); });
          nextOffset += page.raw;
          total = page.raw ? page.total : entries.length;   // an empty batch is the end, whatever the total said
          paint();
          if (options.scrollHeight <= options.clientHeight + MENU_PREFETCH_PX) more();   // not enough rows to scroll yet
        });
      }

      function restartList() {
        round++;
        started = false;
        entries = [];
        total = 0;
        nextOffset = 0;
        busy = false;
        failedRead = false;
        options.scrollTop = 0;
        more();
      }

      options.addEventListener('scroll', function () {
        if (options.scrollHeight - options.scrollTop - options.clientHeight < MENU_PREFETCH_PX) more();
      }, { passive: true });
      search.addEventListener('input', function () {
        if (!remote) { paint(); return; }
        clearTimeout(searchTimer);
        searchTimer = setTimeout(restartList, MENU_SEARCH_MS);
      });
      search.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') { event.stopPropagation(); closeMenu(); button.focus(); }
        else if (event.key === 'Enter') {
          event.preventDefault();
          const first = options.querySelector('.pub-add-menu-option');
          if (first) first.click();
        }
      });

      document.body.appendChild(menu);
      const r = button.getBoundingClientRect();
      const below = window.innerHeight - r.bottom;
      menu.style.left = r.left + 'px';
      menu.style.width = r.width + 'px';
      if (below < 220 && r.top > below) { menu.style.bottom = (window.innerHeight - r.top + 2) + 'px'; }
      else { menu.style.top = (r.bottom + 2) + 'px'; }
      button.setAttribute('aria-expanded', 'true');
      openMenu = { menu: menu, button: button, onClose: function () { clearTimeout(searchTimer); } };
      document.addEventListener('mousedown', onOutside, true);
      search.focus();
      if (remote) restartList(); else paint();
    });
    return wrap;
  }

  /** The value box of a row: a searchable list, read in batches, for a picklist property, else a text box. */
  function valueControl(row) {
    const field = fieldOf(row.field);
    if (field && field.picklist) {
      const source = {
        load: function (from, text, done) {
          request('search_options', { lookup: field.picklist, offset: from, text: text }, function (entry) {
            done(entry.ok ? entry.result : null);
          });
        },
      };
      return combo(source, row.value, 'Select a value', function (value) { row.value = value; }, 'Value');
    }
    const input = el('input', 'pub-add-input');
    input.type = 'text';
    input.placeholder = field ? 'Value' : 'Choose a property first';
    input.disabled = !field;
    input.value = row.value;
    input.setAttribute('aria-label', 'Value');
    input.addEventListener('input', function () { row.value = input.value; });
    input.addEventListener('keydown', function (event) { if (event.key === 'Enter') restart(); });
    return input;
  }

  function buildFilterRow(group, row, first) {
    const wrap = el('div', 'pub-add-filter-row');
    if (!first) wrap.appendChild(joinSwitch(row.join, 'Join this row with the one above', function (join) { row.join = join; }));
    const line = el('div', 'pub-add-filter-line');
    const entries = fields.map(function (f) { return { value: f.id, label: f.title }; });
    line.appendChild(combo(entries, row.field, 'Choose a property', function (id) {
      row.field = id;
      row.value = '';
      renderFilters();
    }, 'Property'));
    if (group.rows.length > 1 || groups.length > 1) {
      line.appendChild(iconButton('pub-add-remove', 'Remove this row', 12, function () {
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
    closeMenu();
    const host = dialog.filters;
    host.textContent = '';
    dialog.filterNote.textContent = fieldsNote;
    dialog.filterNote.hidden = !fieldsNote;
    if (fieldsNote && !fields.length) return;
    groups.forEach(function (group, g) {
      if (g > 0) host.appendChild(joinSwitch(group.join, 'Join this group with the one above', function (join) { group.join = join; }));
      const box = el('div', 'pub-add-group');
      const head = el('div', 'pub-add-group-head', groups.length > 1 ? 'GROUP ' + (g + 1) : 'FILTER');
      box.appendChild(head);
      group.rows.forEach(function (row, r) { box.appendChild(buildFilterRow(group, row, r === 0)); });
      const addRow = el('button', 'pub-add-link', '+ Add Row');
      addRow.type = 'button';
      addRow.addEventListener('click', function () { group.rows.push(newRow()); renderFilters(); });
      box.appendChild(addRow);
      host.appendChild(box);
    });
    const addGroup = el('button', 'pub-add-dashed', '+ Add Group');
    addGroup.type = 'button';
    addGroup.addEventListener('click', function () { groups.push({ join: 'AND', rows: [newRow()] }); renderFilters(); });
    host.appendChild(addGroup);
  }

  // ---- The dialog --------------------------------------------------------------------

  function close() {
    if (!dialog) return;
    closeMenu();
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
    box.setAttribute('aria-label', 'Add existing items to the Bill of Materials');

    const titleBar = el('div', 'pub-add-title');
    const title = el('h2', 'pub-add-heading', 'Add Existing Items');
    title.id = 'pub-add-heading';
    box.setAttribute('aria-labelledby', title.id);
    const closeButton = iconButton('pub-add-close', 'Close', undefined, close);
    titleBar.appendChild(title);
    titleBar.appendChild(closeButton);
    box.appendChild(titleBar);

    const body = el('div', 'pub-add-body');
    box.appendChild(body);

    const top = el('div', 'pub-add-top');
    const search = el('input', 'pub-add-filter');
    search.type = 'search';
    search.placeholder = 'Search item descriptor...';
    search.setAttribute('aria-label', 'Search item descriptor');
    const searchButton = el('button', 'btn', 'Search');
    searchButton.type = 'button';
    top.appendChild(search);
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
    resultsHead.appendChild(el('span', 'pub-add-results-title', 'Results'));
    const totalLine = el('span', 'pub-add-total');
    resultsHead.appendChild(totalLine);
    const hideSwitch = switchLabel('Show hidden items', 'Items already in the Bill of Materials, or added in this panel, are hidden. Turn on to show them (greyed out).');
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
    const onlySwitch = switchLabel('Show only selected', 'Narrow the list to the items you have ticked');
    const onlyBox = onlySwitch.box;
    onlyBox.disabled = true;
    footer.appendChild(onlySwitch.label);
    const cancel = el('button', 'btn btn-secondary', 'Cancel');
    cancel.type = 'button';
    const clear = el('button', 'btn btn-secondary', 'Clear');
    clear.type = 'button';
    const add = el('button', 'btn', 'Add to BOM');
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
    return { overlay: overlay, list: list, status: status, total: totalLine, add: add, clear: clear, count: count, only: onlyBox, search: search, filters: filters, filterNote: filterNote };
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
    fields = []; fieldsNote = 'Loading properties...';
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
