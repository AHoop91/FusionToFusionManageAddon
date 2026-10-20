/**
 * Pieces the Where Used and Bill of Materials tabs share: asking Python for an answer that takes a while,
 * a centred message or loader, and the item cell of a tree row (chevron, icon box, number, part number - description).
 */
(function (ns) {
  'use strict';

  const bridge = ns.bridge;
  const el = ns.el;
  const POLL_INTERVAL_MS = 300;
  const MIN_COLUMN_PX = 40;
  const ITEM_COLUMN_PX = 380;   // the first column of a tree table
  const COLUMN_PX = 120;   // the others
  const SLOT_PX = 28;   // width of the chevron box, and how far each level steps in
  const CHEVRON_CLOSED = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><polyline points="10 6 16 12 10 18"/></svg>';
  const CHEVRON_OPEN = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><polyline points="6 10 12 16 18 10"/></svg>';
  // The cube the Publish Bill of Materials uses for an assembly and for a part.
  const CUBE = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5"/><path d="M12 12v9"/></svg>';

  // The icon of the item itself, as in the Publish Bill of Materials.
  const ROOT = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M5 3h11l3 3v15H5z"/><path d="M8 3v6h7V3"/><path d="M8 21v-7h8v7"/></svg>';

  const waiting = {};   // request id -> { done: callback(error text, result), tab: the tab it was asked for (see ``leave``) }
  const listening = {};   // result action -> true once its listener is registered
  // The tab each kind of look-up is for. Leaving a tab ends its look-ups, in Python too (the request to Fusion Manage is cancelled).
  const TAB_OF = { files_load: 'files', bom_load: 'bom', where_used_load: 'whereused', workflows_load: 'workflows', changelog_load: 'changelog', sync_check_load: 'item', bom_check_load: 'bom', tab_counts_load: 'counts' };
  let counter = 0;

  function poll(resultAction, id) {
    setTimeout(function () { if (waiting[id]) bridge.send(resultAction, { request: id }); }, POLL_INTERVAL_MS);
  }

  /** Ask Python (``startAction`` with ``payload``) and poll ``resultAction`` until ``done(error, result)`` can run. */
  function load(startAction, resultAction, payload, done) {
    if (!listening[resultAction]) {
      listening[resultAction] = true;
      bridge.on(resultAction, function (r) {
        const entry = r.ok ? r.result : { request: '', pending: false, ok: false, message: r.error };
        const asked = waiting[entry.request];
        if (!asked) return;
        if (entry.pending) { poll(resultAction, entry.request); return; }
        delete waiting[entry.request];
        if (entry.cancelled) return;   // it was left: nobody waits for it
        if (entry.ok) asked.done('', entry.result); else asked.done(entry.message || 'Could not read it from Fusion Manage.', null);
      });
    }
    const id = 'lk' + (++counter);
    waiting[id] = { done: done, tab: TAB_OF[startAction] || '' };
    bridge.send(startAction, Object.assign({ request: id }, payload));
    poll(resultAction, id);
  }

  /**
   * End the look-ups of a tab (``tab``), or of every tab when none is given: nothing waits for their answers any more, and Python is told to
   * stop reading for them. Returns how many were ended.
   */
  function leave(tab) {
    const ids = Object.keys(waiting).filter(function (id) { return !tab || waiting[id].tab === tab; });
    ids.forEach(function (id) { delete waiting[id]; });
    if (ids.length) bridge.send('lookup_cancel', { requests: ids });
    return ids.length;
  }

  /**
   * Where the icon of each level starts: every level steps in by one chevron box, so a chevron sits under its
   * parent's icon. A level that has a chevron on any row leaves room for it on every row.
   */
  function iconXs(entries, chevronDepths) {
    return ns.stepIn(entries.map(function (entry) { return entry.depth; }), chevronDepths[0], SLOT_PX);
  }

  /**
   * A handle on a heading's right edge: dragging it sets the width (px) of ``col``, not below ``options.min``.
   * ``options.onResize()`` runs after each change; ``options.beforeDrag()`` once when a drag starts (before the width is read);
   * ``options.stopClick`` keeps the press from reaching the heading (a sortable heading must not sort).
   */
  function grip(col, options) {
    const handle = el('span', 'item-grip');
    if (options.title) handle.title = options.title;
    if (options.stopClick) handle.addEventListener('click', function (event) { event.stopPropagation(); });
    handle.addEventListener('mousedown', function (event) {
      event.preventDefault();
      if (options.stopClick) event.stopPropagation();
      if (options.beforeDrag) options.beforeDrag();
      const startX = event.clientX;
      const startWidth = parseFloat(col.style.width);
      handle.classList.add('item-grip-active');
      function move(e) {
        col.style.width = Math.max(options.min, startWidth + e.clientX - startX) + 'px';
        options.onResize();
      }
      function stop() {
        document.removeEventListener('mousemove', move);
        document.removeEventListener('mouseup', stop);
        handle.classList.remove('item-grip-active');
      }
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', stop);
    });
    return handle;
  }

  /**
   * Let the user drag the right edge of a heading to resize its column (not below ``MIN_COLUMN_PX``). The last column
   * has no width of its own: it takes what is left, and the table is never narrower than its columns, so a narrow
   * panel scrolls it sideways. ``cols`` and ``heads`` are the table's <col> and <th> elements, with widths set in px.
   */
  function resizable(table, cols, heads, lastMinPx) {
    const last = cols.length - 1;
    cols[last].style.width = '';
    function fit() {
      let sum = lastMinPx;
      for (let i = 0; i < last; i++) sum += parseFloat(cols[i].style.width) || 0;
      table.style.minWidth = sum + 'px';
    }
    fit();
    heads.slice(0, last).forEach(function (th, i) {
      th.appendChild(grip(cols[i], { min: MIN_COLUMN_PX, onResize: fit, title: 'Drag to resize the column' }));
    });
  }

  /** A date and time of Fusion Manage's (an ISO stamp) in the user's own format ("" when there is none). */
  function formatDate(stamp) {
    const date = new Date(stamp);
    return stamp && !isNaN(date) ? date.toLocaleString() : '';
  }

  /** A line of text (and a hint under it) in the middle of ``target``. */
  function centred(target, className, text, isError, hint) {
    target.className = 'view-scroll item-centred ' + className;
    target.replaceChildren(el('p', 'item-empty-text' + (isError ? ' error' : ''), text));
    if (hint) target.appendChild(el('p', 'item-empty-hint', hint));
  }

  /** Under a table that shows only its columns: an icon (static markup), a line of text and a hint, centred in the space left. */
  function emptyUnder(target, iconMarkup, text, hint) {
    target.classList.add('item-files-stack');
    const empty = el('div', 'item-files-empty item-centred');
    const icon = el('span', 'item-empty-icon item-empty-icon-large');
    icon.innerHTML = iconMarkup;   // static markup
    empty.append(icon, el('p', 'item-empty-text', text), el('p', 'item-empty-hint', hint));
    target.appendChild(empty);
  }

  /** The bouncing balls and a caption in the middle of ``target``. */
  function loading(target, className, text) {
    target.className = 'view-scroll item-centred ' + className;
    const balls = el('div', 'balls');
    balls.setAttribute('role', 'status');
    balls.setAttribute('aria-label', text);
    balls.append(el('span'), el('span'), el('span'));
    target.replaceChildren(balls, el('p', 'muted', text));
  }

  /**
   * The item cell of a row. ``opts``: ``iconX`` (where its icon starts, from ``iconXs``), ``number`` (1, 1.1 ...), ``row`` (title, number, name, url),
   * ``kind`` ('assembly' or 'part'), ``chevron`` (null, or ``{open, title, onClick}``), ``room`` (leave the width of a
   * chevron when this row has none), ``quiet`` (black text that looks like a link only under the pointer), ``loading`` and ``error`` (notes beside the name).
   */
  function itemCell(opts) {
    const row = opts.row;
    const td = el('td', 'item-tree-first');
    const cell = el('div', 'item-tree-cell');
    cell.style.paddingLeft = Math.max(0, opts.iconX - (opts.chevron || opts.room ? SLOT_PX : 0)) + 'px';
    if (opts.chevron) {
      const chevron = el('button', 'item-tree-toggle');
      chevron.type = 'button';
      chevron.title = opts.chevron.title;
      chevron.setAttribute('aria-expanded', opts.chevron.open ? 'true' : 'false');
      chevron.innerHTML = opts.chevron.open ? CHEVRON_OPEN : CHEVRON_CLOSED;   // static markup
      chevron.addEventListener('click', opts.chevron.onClick);
      cell.appendChild(chevron);
    } else if (opts.room) {
      cell.appendChild(el('span', 'item-tree-toggle'));
    }
    const icon = el('span', 'item-tree-icon' + (opts.kind === 'part' ? ' item-tree-icon-part' : ''));
    icon.title = opts.kind === 'root' ? 'This item' : opts.kind === 'part' ? 'Part' : 'Assembly';
    icon.innerHTML = opts.kind === 'root' ? ROOT : CUBE;   // static markup
    cell.appendChild(icon);
    cell.appendChild(el('span', 'item-tree-seq', opts.number));
    const label = row.url ? el('a', 'item-tree-label item-link' + (opts.quiet ? ' item-tree-label-quiet' : '')) : el('span', 'item-tree-label');
    if (row.url) {
      label.href = '#';
      label.addEventListener('click', function (event) { event.preventDefault(); bridge.send('open_url', { url: row.url }); });
    }
    label.title = (row.url ? 'Open in Fusion Manage in your browser: ' : '') + row.title;
    if (row.number) label.appendChild(el('span', 'item-tree-pn', row.number));
    if (row.name) label.appendChild(el('span', 'item-tree-name', row.name));
    cell.appendChild(label);
    if (opts.loading) cell.appendChild(el('span', 'item-tree-note muted', 'Loading...'));
    if (opts.error) cell.appendChild(el('span', 'item-tree-note error', opts.error));
    td.appendChild(cell);
    return td;
  }

  ns.itemTree = { ITEM_COLUMN_PX: ITEM_COLUMN_PX, COLUMN_PX: COLUMN_PX, load: load, leave: leave, formatDate: formatDate, centred: centred, emptyUnder: emptyUnder, loading: loading, itemCell: itemCell, iconXs: iconXs, grip: grip, resizable: resizable };
})(window.MfgUi);
