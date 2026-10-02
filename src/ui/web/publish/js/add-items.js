/**
 * Publish Item panel: the Add Items picker, as ``ns.pubAddItems``. A dialog lists the Fusion Manage
 * items that can be added to the Bill of Materials of the design's Fusion Manage item, 100 at a time.
 *
 * It is made to stay quick with thousands of items:
 *   - pages load as the list is scrolled near its end, one request at a time, each on a Python worker thread
 *     (polled here), and a reply that no longer matches the list on screen is dropped;
 *   - a page is appended once, as a fragment, and rows are never rebuilt: filtering only toggles ``hidden``,
 *     ticking a box updates that one row, and one click listener serves every row;
 *   - rows skip layout and paint while off screen (``content-visibility`` in add-items.css).
 */
(function (ns) {
  'use strict';

  const bridge = ns.bridge;
  const el = ns.pubUi.el;

  const POLL_MS = 200;          // wait between checks for a page being fetched
  const PREFETCH_PX = 600;      // load the next page when this close to the end of the list
  const MIN_WIDTH = 380;        // smallest the dialog can be resized to
  const MIN_HEIGHT = 340;
  const FILTER_DELAY_MS = 300;  // typing pause before the filter is applied (and more pages are fetched for it)

  // State of the open dialog. ``generation`` changes whenever the list restarts (opened, sorted, closed), which makes
  // every reply for the old list stale.
  let dialog = null;            // { overlay, list, ... } while open
  let generation = 0;
  let options = null;           // { itemId, staged: Set of ids already staged, onAdd(items) }
  let items = [];               // every loaded item, in list order
  let rows = new Map();         // item id -> its row element
  let byId = new Map();         // item id -> item
  let selected = new Map();     // item id -> item; survives filtering and paging
  let total = 0;
  let sort = 'desc';
  let filter = '';
  let loading = false;
  let failed = '';
  let pollTimer = null;
  let filterTimer = null;
  let frame = 0;
  let workspaceTitle = '';

  function moreToLoad() { return !failed && items.length < total; }

  // ---- Loading pages -----------------------------------------------------------------

  function stop() {
    clearTimeout(pollTimer);
    loading = false;
  }

  function loadNext() {
    if (!dialog || loading || (items.length && items.length >= total)) return;   // the first page is wanted before the total is known
    loading = true;
    failed = '';
    paintStatus();
    const token = generation + ':' + items.length;
    bridge.send('load_linkable_page', { token: token, item_id: options.itemId, offset: items.length, sort: sort });
  }

  function onAnswer(r) {
    if (!dialog) return;
    const entry = r.ok ? r.result : { token: '', message: r.error || 'Unknown error' };
    if (entry.token && entry.token.split(':')[0] !== String(generation)) return;   // for a list that is gone
    if (entry.pending) {
      pollTimer = setTimeout(function () { bridge.send('load_linkable_page_status', { token: entry.token }); }, POLL_MS);
      return;
    }
    loading = false;
    if (!r.ok || !entry.ok) {
      failed = entry.message || 'Unknown error';
      paintStatus();
      return;
    }
    append(entry.page);
    paintStatus();
    paintSelection();
    afterPage();
  }

  /** Keep loading while the list is too short to scroll, or while a filter waits for items that are not loaded yet. */
  function afterPage() {
    if (!moreToLoad()) return;
    const list = dialog.list;
    if (filter || list.scrollHeight - list.scrollTop - list.clientHeight < PREFETCH_PX) loadNext();
  }

  function onScroll() {
    if (frame) return;
    frame = requestAnimationFrame(function () {
      frame = 0;
      if (dialog) afterPage();
    });
  }

  // ---- Drawing -----------------------------------------------------------------------

  function matches(item) {
    return !filter || item.haystack.indexOf(filter) >= 0;
  }

  function itemText(item) {
    return [item.number, item.name].filter(Boolean).join(' - ') + (item.version ? ' ' + item.version : '');
  }

  function buildRow(item) {
    const row = el('div', 'pub-add-row');
    row.dataset.id = item.id;
    const box = el('input', 'pub-add-check');
    box.type = 'checkbox';
    const text = itemText(item);
    box.setAttribute('aria-label', text);
    const already = options.staged.has(item.id);
    box.checked = already || selected.has(item.id);
    box.disabled = already;
    row.classList.toggle('pub-add-row-added', already);
    row.appendChild(box);
    const name = el('span', 'pub-add-cell', text);
    name.title = already ? text + ' (already added)' : text;
    row.appendChild(name);
    row.appendChild(el('span', 'pub-add-cell', item.workspace));
    row.appendChild(el('span', 'pub-add-cell', item.lifecycle));
    row.hidden = !matches(item);
    return row;
  }

  function append(page) {
    if (!workspaceTitle && page.items.length) { workspaceTitle = page.items[0].workspace; dialog.workspace.textContent = workspaceTitle; }
    total = page.total;
    const fragment = document.createDocumentFragment();
    let added = 0;
    page.items.forEach(function (item) {
      if (byId.has(item.id)) return;
      added++;
      item.haystack = (itemText(item) + ' ' + item.workspace + ' ' + item.lifecycle).toLowerCase();
      items.push(item);
      byId.set(item.id, item);
      const row = buildRow(item);
      rows.set(item.id, row);
      fragment.appendChild(row);
    });
    dialog.list.insertBefore(fragment, dialog.status);
    // A page that added nothing new would be asked for again at the same offset forever; treat it as the end.
    if (!added) total = items.length;
    dialog.total.textContent = total.toLocaleString() + (total === 1 ? ' item' : ' items') + ' in total';
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
      const retry = el('button', 'pub-drawing-open pub-retry', 'Retry');
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
      status.appendChild(el('span', '', filter ? 'Searching... ' + items.length.toLocaleString() + ' of ' + total.toLocaleString() + ' loaded' : 'Loading more...'));
    } else if (filter && !items.some(matches)) {
      status.textContent = 'No items match "' + dialog.search.value.trim() + '".';
    } else if (!items.length) {
      status.textContent = 'There are no items to add.';
    } else {
      status.hidden = true;
    }
  }

  /** Footer count, Add button and the select-all box (ticked when every shown item is, dashed when some are). */
  function paintSelection() {
    const count = selected.size;
    dialog.add.disabled = count === 0;
    dialog.add.textContent = count ? 'Add (' + count + ')' : 'Add';
    dialog.count.textContent = count ? count + ' selected' : '';
    let shown = 0;
    let ticked = 0;
    items.forEach(function (item) {
      if (options.staged.has(item.id) || rows.get(item.id).hidden) return;
      shown++;
      if (selected.has(item.id)) ticked++;
    });
    dialog.all.disabled = shown === 0;
    dialog.all.checked = shown > 0 && ticked === shown;
    dialog.all.indeterminate = ticked > 0 && ticked < shown;
  }

  /** Tick or untick every item the filter shows. */
  function selectAll(on) {
    items.forEach(function (item) {
      const row = rows.get(item.id);
      if (options.staged.has(item.id) || row.hidden) return;
      row.firstChild.checked = on;
      if (on) selected.set(item.id, item); else selected.delete(item.id);
    });
    paintSelection();
  }

  function applyFilter() {
    items.forEach(function (item) { rows.get(item.id).hidden = !matches(item); });
    paintStatus();
    paintSelection();
    afterPage();
  }

  /** Throw the list away and load from the start (sort changed). Ticked items stay ticked. */
  function restart() {
    stop();
    generation++;
    rows.forEach(function (row) { row.remove(); });
    items = [];
    rows = new Map();
    byId = new Map();
    total = 0;
    failed = '';
    dialog.list.scrollTop = 0;
    dialog.total.textContent = '';
    paintSelection();
    loadNext();
  }

  // ---- The dialog --------------------------------------------------------------------

  function close() {
    if (!dialog) return;
    stop();
    generation++;
    clearTimeout(filterTimer);
    document.removeEventListener('keydown', onKey);
    dialog.overlay.remove();
    dialog = null;
    items = []; rows = new Map(); byId = new Map(); selected = new Map();
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
    box.setAttribute('aria-label', 'Add items to the Bill of Materials');

    const titleBar = el('div', 'pub-add-title');
    const title = el('h2', 'pub-add-heading', 'Add Items');
    title.id = 'pub-add-heading';
    box.setAttribute('aria-labelledby', title.id);
    const closeButton = el('button', 'pub-add-close', '×');
    closeButton.type = 'button';
    closeButton.title = 'Close';
    closeButton.setAttribute('aria-label', 'Close');
    closeButton.addEventListener('click', close);
    titleBar.appendChild(title);
    titleBar.appendChild(closeButton);
    box.appendChild(titleBar);

    const body = el('div', 'pub-add-body');
    box.appendChild(body);

    const top = el('div', 'pub-add-top');
    const workspace = el('select', 'pub-add-workspace');
    workspace.disabled = true;   // the Bill of Materials takes items of its own workspace
    workspace.appendChild(el('option', '', 'Items'));
    const search = el('input', 'pub-add-filter');
    search.type = 'search';
    search.placeholder = 'Type to filter for items';
    search.setAttribute('aria-label', 'Filter items');
    top.appendChild(workspace);
    top.appendChild(search);
    body.appendChild(top);

    const totalLine = el('div', 'pub-add-total');
    body.appendChild(totalLine);

    // The header is the list's first, sticky row, so its columns line up with the rows whatever the scrollbar does.
    const head = el('div', 'pub-add-row pub-add-head');
    const all = el('input', 'pub-add-check');
    all.type = 'checkbox';
    all.disabled = true;
    all.title = 'Select all shown items';
    all.setAttribute('aria-label', all.title);
    head.appendChild(all);
    const sortButton = el('button', 'pub-add-sort', 'Item');
    sortButton.type = 'button';
    sortButton.title = 'Sort by item';
    head.appendChild(sortButton);
    head.appendChild(el('span', 'pub-add-cell', 'Workspace'));
    head.appendChild(el('span', 'pub-add-cell', 'Lifecycle'));

    const list = el('div', 'pub-add-list');
    const status = el('div', 'pub-add-status');
    list.appendChild(head);
    list.appendChild(status);
    body.appendChild(list);

    const footer = el('div', 'pub-add-footer');
    const count = el('span', 'pub-add-count');
    footer.appendChild(count);
    const cancel = el('button', 'btn btn-secondary', 'Cancel');
    cancel.type = 'button';
    const add = el('button', 'btn', 'Add');
    add.type = 'button';
    add.disabled = true;
    footer.appendChild(cancel);
    footer.appendChild(add);
    box.appendChild(footer);
    overlay.appendChild(box);
    enableMoveAndResize(box, titleBar);

    // One listener serves every row.
    list.addEventListener('change', function (event) {
      const row = event.target.closest('.pub-add-row');
      const item = row && byId.get(row.dataset.id);
      if (!item) return;
      if (event.target.checked) selected.set(item.id, item); else selected.delete(item.id);
      paintSelection();
    });
    all.addEventListener('change', function () { selectAll(all.checked); });
    list.addEventListener('scroll', onScroll, { passive: true });
    search.addEventListener('input', function () {
      clearTimeout(filterTimer);
      filterTimer = setTimeout(function () { filter = search.value.trim().toLowerCase(); applyFilter(); }, FILTER_DELAY_MS);
    });
    sortButton.addEventListener('click', function () {
      sort = sort === 'desc' ? 'asc' : 'desc';
      sortButton.dataset.sort = sort;
      restart();
    });
    sortButton.dataset.sort = sort;
    cancel.addEventListener('click', close);
    add.addEventListener('click', confirm);
    overlay.addEventListener('mousedown', function (event) { if (event.target === overlay) close(); });
    document.addEventListener('keydown', onKey);
    document.body.appendChild(overlay);
    return { overlay: overlay, list: list, status: status, total: totalLine, add: add, all: all, count: count, workspace: workspace.firstChild, search: search };
  }

  /**
   * Open the picker for a Fusion Manage item. ``opts``: ``itemId`` (the item whose BOM gets the items),
   * ``staged`` (ids already picked, shown ticked and locked) and ``onAdd(items)`` with the items the user added.
   */
  function open(opts) {
    close();
    options = { itemId: opts.itemId, staged: new Set(opts.staged || []), onAdd: opts.onAdd };
    generation++;
    filter = ''; failed = ''; workspaceTitle = ''; total = 0;
    dialog = build();
    dialog.search.focus();
    loadNext();
  }

  bridge.on('load_linkable_page', onAnswer);
  bridge.on('load_linkable_page_status', onAnswer);

  ns.pubAddItems = { open: open };
})(window.MfgUi);
