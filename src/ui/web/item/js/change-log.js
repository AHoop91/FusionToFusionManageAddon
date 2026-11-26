/**
 * The Change Log tab: what was done to the item, newest first, with the fields each change set shown as old value
 * struck through and the new one beside it.
 *
 * Python reads one page at a time. The next page is read as the user scrolls near the end (with a progress bar under
 * the table), and only the rows in view (plus a few either side) are in the page: the rest are two spacer rows of the
 * height they would take, so a log of thousands of entries scrolls as smoothly as one of ten.
 * Layer: UI. Which rows to draw (``visibleRange``) is a pure function of the measured heights.
 */
(function (ns) {
  'use strict';

  const el = ns.el;
  const t = ns.i18n.t;
  const tree = ns.itemTree;
  const CLASS = 'item-changelog';
  const ESTIMATE_PX = 56;     // the height of a row not yet drawn, until one has been measured
  const BUFFER_PX = 400;      // rows this far above and below the view are drawn too
  const READ_AHEAD_ROWS = 30; // the next page is asked for when the view is this close to the last row
  // heading, width, and how to read the text of a cell from a row (the description column draws its own cell)
  const COLUMNS = [
    { title: function () { return t('item.log_col_date'); }, width: 190, text: function (r) { return tree.formatDate(r.date); } },
    { title: function () { return t('item.log_col_user'); }, width: 180, text: function (r) { return r.user; } },
    { title: function () { return t('item.log_col_action'); }, width: 190, text: function (r) { return r.action; } },
    { title: function () { return t('item.col_description'); }, width: 420, describe: true },
  ];
  // A page with lines. Static markup.
  const LOG_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5M10 13h6M10 17h6"/></svg>';

  let current = 0;   // the tab being drawn; an answer for an older item is ignored
  let stop = null;   // takes down what the tab drawn last had set up (its scroll and resize listeners)

  /** The description of a row: its text, then a bullet for each field it changed. */
  function describe(td, row) {
    if (row.description) td.appendChild(el('div', '', row.description));
    if (!row.changes.length) return;
    const list = el('ul', 'item-log-changes');
    row.changes.forEach(function (change) {
      const li = el('li');
      li.append(change.field + ': ', el('span', 'item-log-old', change.old), ' ⇒ ', el('span', 'item-log-new', change.new));
      list.appendChild(li);
    });
    td.appendChild(list);
  }

  function spacer(height) {
    const tr = el('tr', 'item-log-spacer');
    const td = el('td');
    td.colSpan = COLUMNS.length;
    td.style.height = height + 'px';
    tr.appendChild(td);
    return tr;
  }

  /** Read the change log of the item of ``view`` and fill ``target`` with it. */
  function render(target, view) {
    if (stop) { stop(); stop = null; }
    const mine = ++current;
    tree.loading(target, CLASS, t('item.log_reading'));
    function read(offset, done) {
      tree.load('changelog_load', 'changelog_result', { workspace_id: view.workspace_id, item_id: view.item_id, stamp: view.stamp, offset: offset }, function (error, page) {
        if (mine !== current) return;
        done(error, page);
      });
    }
    read(0, function (error, page) {
      if (error) { tree.centred(target, CLASS, t('item.log_error', { error: error }), true); return; }
      draw(target, page, read);
    });
  }

  /** The height of row ``i``: its measure, or the estimate until it has been drawn. */
  function heightOf(heights, i) { return heights[i] === undefined ? ESTIMATE_PX : heights[i]; }

  /**
   * Which of ``count`` rows to draw. ``scrolled`` is how far the view is into the rows and ``view`` its height; the rows this far (``BUFFER_PX``)
   * either side are drawn too. Returns ``{from, to, top}``: draw ``from`` up to (not including) ``to``, with ``top`` px of spacer above.
   */
  function visibleRange(heights, count, scrolled, view) {
    let top = 0;
    let from = 0;
    while (from < count && top + heightOf(heights, from) < scrolled - BUFFER_PX) { top += heightOf(heights, from); from++; }
    let to = from;
    let reach = top;
    while (to < count && reach < scrolled + view + BUFFER_PX) { reach += heightOf(heights, to); to++; }
    return { from: from, to: to, top: top };
  }

  /** The height of the rows from ``to`` on, which the spacer under the drawn ones stands in for. */
  function heightBelow(heights, count, to) {
    let below = 0;
    for (let i = to; i < count; i++) below += heightOf(heights, i);
    return below;
  }

  /** Record in ``heights`` what the drawn rows (``drawn[1]`` is the row ``from``) really took. Returns true when any measure changed. */
  function measureRows(heights, drawn, from, to) {
    let moved = false;
    for (let i = from; i < to; i++) {
      const real = drawn[1 + i - from].getBoundingClientRect().height;
      if (heights[i] === undefined || Math.abs(heights[i] - real) > 0.5) { heights[i] = real; moved = true; }
    }
    return moved;
  }

  /** The table row of one log entry. */
  function makeLogRow(row) {
    const tr = el('tr');
    COLUMNS.forEach(function (column) {
      const td = el('td');
      if (column.describe) describe(td, row); else td.textContent = column.text(row);
      tr.appendChild(td);
    });
    return tr;
  }

  /** The table with its resizable columns and headings, inside the scroller. Returns ``{table, body, scroller}``. */
  function makeLogTable() {
    const table = el('table', 'item-files-table item-tree-table');
    const colgroup = el('colgroup');
    const head = el('tr');
    const cols = [];
    const heads = [];
    COLUMNS.forEach(function (column) {
      const col = el('col');
      col.style.width = column.width + 'px';
      colgroup.appendChild(col);
      const th = el('th', '', column.title());
      head.appendChild(th);
      cols.push(col);
      heads.push(th);
    });
    const body = el('tbody');
    table.append(colgroup, el('thead'), body);
    table.tHead.appendChild(head);
    tree.resizable(table, cols, heads, tree.COLUMN_PX);
    const scroller = el('div', 'item-log-scroll');   // the one that scrolls: its header row stays at the top
    scroller.appendChild(table);
    return { table: table, body: body, scroller: scroller };
  }

  /** Under the table: how far the log has been read, and the bar while the next page is. Returns ``{foot, status, bar, retry}``. */
  function makeLogFoot() {
    const foot = el('div', 'item-log-foot');
    const status = el('span', 'item-log-status muted');
    const bar = el('div', 'item-log-progress');
    bar.setAttribute('role', 'progressbar');
    bar.setAttribute('aria-label', t('item.log_reading_more'));
    bar.appendChild(el('span'));
    bar.hidden = true;
    const retry = el('button', 'btn btn-secondary item-log-retry', t('item.log_retry'));
    retry.type = 'button';
    retry.hidden = true;
    foot.append(status, bar, retry);
    return { foot: foot, status: status, bar: bar, retry: retry };
  }

  /**
   * Watch the table's width (a different column width changes how the descriptions wrap, so the measured heights no longer hold) and the
   * scroller. ``onResize()`` and ``onScroll()`` are called on a change. Returns the function that stops watching.
   */
  function watchLog(parts, onResize, onScroll) {
    let width = 0;
    const resize = new ResizeObserver(function () {
      const now = parts.table.getBoundingClientRect().width;
      if (Math.abs(now - width) < 1) return;
      width = now;
      onResize();
    });
    resize.observe(parts.table);
    parts.scroller.addEventListener('scroll', onScroll, { passive: true });
    return function () {
      resize.disconnect();
      parts.scroller.removeEventListener('scroll', onScroll);
    };
  }

  /** The next page could not be read: say so in the status, with the button to try again. */
  function showMoreError(foot, error) {
    foot.status.textContent = t('item.log_more_error', { error: error });
    foot.retry.hidden = false;
  }

  /** The log has no entries: the columns stay, and the message is centred in the space under them. */
  function showEmptyLog(target, foot) {
    foot.foot.hidden = true;
    tree.emptyUnder(target, LOG_ICON, t('item.log_empty'), t('item.log_empty_hint'));
  }

  function draw(target, first, read) {
    target.className = 'view-scroll ' + CLASS + ' item-log-ready';   // a column: the table scrolls inside, the footer stays under it
    const parts = makeLogTable();
    const foot = makeLogFoot();
    target.replaceChildren(parts.scroller, foot.foot);

    const rows = [];       // every row read so far
    const heights = [];    // the measured height of a row (undefined until it has been drawn)
    let total = 0;
    let next = null;       // the offset of the next page, or null when the whole log has been read
    let loading = false;
    let failed = false;
    let start = -1;        // the rows drawn: start up to (not including) end
    let end = -1;
    let frame = 0;

    function showStatus() {
      foot.status.textContent = t('item.log_showing', { shown: rows.length, total: total });
      foot.foot.hidden = !rows.length;
    }

    /** Draw the rows in view, with a spacer above and below standing in for the rest. */
    function paint(force) {
      const scrolled = Math.max(0, parts.scroller.getBoundingClientRect().top - parts.body.getBoundingClientRect().top);   // how far the view is into the rows (the top spacer counts)
      const range = visibleRange(heights, rows.length, scrolled, parts.scroller.clientHeight);
      if (!force && range.from === start && range.to === end) return;
      start = range.from;
      end = range.to;
      const drawn = [spacer(range.top)];
      for (let i = range.from; i < range.to; i++) drawn.push(makeLogRow(rows[i]));
      drawn.push(spacer(heightBelow(heights, rows.length, range.to)));
      parts.body.replaceChildren(...drawn);
      if (measureRows(heights, drawn, range.from, range.to)) schedule(true);   // the spacers were sized from guesses: size them again from the measures
      more();
    }

    function schedule(force) {
      if (frame && !force) return;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(function () { frame = 0; paint(force); });
    }

    /** Ask for the next page when the view is near the last row read. */
    function more() {
      if (next === null || loading || failed || end < rows.length - READ_AHEAD_ROWS) return;
      loading = true;
      foot.bar.hidden = false;
      read(next, function (error, page) {
        loading = false;
        foot.bar.hidden = true;
        if (error) {
          failed = true;
          showMoreError(foot, error);
          return;
        }
        add(page);
      });
    }

    foot.retry.addEventListener('click', function () { failed = false; foot.retry.hidden = true; showStatus(); more(); });

    function add(page) {
      page.rows.forEach(function (row) { rows.push(row); });
      total = page.total;
      next = page.next;
      showStatus();
      paint(true);
    }

    const unwatch = watchLog(parts, function () { heights.length = 0; schedule(true); }, function () { schedule(false); });
    stop = function () {
      unwatch();
      cancelAnimationFrame(frame);
    };

    if (first.rows.length) add(first);
    else showEmptyLog(target, foot);
  }

  ns.itemChangeLog = { render: render };
})(window.MfgUi);
