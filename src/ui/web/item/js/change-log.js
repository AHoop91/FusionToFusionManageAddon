/**
 * The Change Log tab: what was done to the item, newest first, with the fields each change set shown as old value
 * struck through and the new one beside it.
 *
 * Python reads one page at a time. The next page is read as the user scrolls near the end (with a progress bar under
 * the table), and only the rows in view (plus a few either side) are in the page: the rest are two spacer rows of the
 * height they would take, so a log of thousands of entries scrolls as smoothly as one of ten.
 */
(function (ns) {
  'use strict';

  const el = ns.el;
  const tree = ns.itemTree;
  const CLASS = 'item-changelog';
  const ESTIMATE_PX = 56;     // the height of a row not yet drawn, until one has been measured
  const BUFFER_PX = 400;      // rows this far above and below the view are drawn too
  const READ_AHEAD_ROWS = 30; // the next page is asked for when the view is this close to the last row
  // heading, width, and how to read the text of a cell from a row (the description column draws its own cell)
  const COLUMNS = [
    { title: 'Date Time', width: 190, text: function (r) { return tree.formatDate(r.date); } },
    { title: 'Changed By', width: 180, text: function (r) { return r.user; } },
    { title: 'Action', width: 190, text: function (r) { return r.action; } },
    { title: 'Description', width: 420, describe: true },
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
    tree.loading(target, CLASS, 'Reading the change log...');
    function read(offset, done) {
      tree.load('changelog_load', 'changelog_result', { workspace_id: view.workspace_id, item_id: view.item_id, stamp: view.stamp, offset: offset }, function (error, page) {
        if (mine !== current) return;
        done(error, page);
      });
    }
    read(0, function (error, page) {
      if (error) { tree.centred(target, CLASS, 'Could not read the change log: ' + error, true); return; }
      draw(target, page, read);
    });
  }

  function draw(target, first, read) {
    target.className = 'view-scroll ' + CLASS + ' item-log-ready';   // a column: the table scrolls inside, the footer stays under it
    const table = el('table', 'item-files-table item-tree-table');
    const colgroup = el('colgroup');
    const head = el('tr');
    const cols = [];
    const heads = [];
    COLUMNS.forEach(function (column) {
      const col = el('col');
      col.style.width = column.width + 'px';
      colgroup.appendChild(col);
      const th = el('th', '', column.title);
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

    // under the table: how far the log has been read, and the bar while the next page is
    const foot = el('div', 'item-log-foot');
    const status = el('span', 'item-log-status muted');
    const bar = el('div', 'item-log-progress');
    bar.setAttribute('role', 'progressbar');
    bar.setAttribute('aria-label', 'Reading more of the change log');
    bar.appendChild(el('span'));
    bar.hidden = true;
    const retry = el('button', 'btn btn-secondary item-log-retry', 'Try again');
    retry.type = 'button';
    retry.hidden = true;
    foot.append(status, bar, retry);
    target.replaceChildren(scroller, foot);

    const rows = [];       // every row read so far
    const heights = [];    // the measured height of a row (undefined until it has been drawn)
    let total = 0;
    let next = null;       // the offset of the next page, or null when the whole log has been read
    let loading = false;
    let failed = false;
    let start = -1;        // the rows drawn: start up to (not including) end
    let end = -1;
    let frame = 0;

    function heightOf(i) { return heights[i] === undefined ? ESTIMATE_PX : heights[i]; }

    function showStatus() {
      status.textContent = 'Showing ' + rows.length + ' of ' + total;
      foot.hidden = !rows.length;
    }

    /** Draw the rows in view, with a spacer above and below standing in for the rest. */
    function paint(force) {
      const scrolled = Math.max(0, scroller.getBoundingClientRect().top - body.getBoundingClientRect().top);   // how far the view is into the rows (the top spacer counts)
      const view = scroller.clientHeight;
      let top = 0;
      let from = 0;
      while (from < rows.length && top + heightOf(from) < scrolled - BUFFER_PX) { top += heightOf(from); from++; }
      let to = from;
      let reach = top;
      while (to < rows.length && reach < scrolled + view + BUFFER_PX) { reach += heightOf(to); to++; }
      if (!force && from === start && to === end) return;
      start = from;
      end = to;
      let below = 0;
      for (let i = to; i < rows.length; i++) below += heightOf(i);
      const drawn = [spacer(top)];
      for (let i = from; i < to; i++) {
        const tr = el('tr');
        COLUMNS.forEach(function (column) {
          const td = el('td');
          if (column.describe) describe(td, rows[i]); else td.textContent = column.text(rows[i]);
          tr.appendChild(td);
        });
        drawn.push(tr);
      }
      drawn.push(spacer(below));
      body.replaceChildren(...drawn);
      let moved = false;
      for (let i = from; i < to; i++) {   // what the rows really took, for the next time
        const real = drawn[1 + i - from].getBoundingClientRect().height;
        if (heights[i] === undefined || Math.abs(heights[i] - real) > 0.5) { heights[i] = real; moved = true; }
      }
      if (moved) schedule(true);   // the spacers were sized from guesses: size them again from the measures
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
      bar.hidden = false;
      read(next, function (error, page) {
        loading = false;
        bar.hidden = true;
        if (error) {
          failed = true;
          status.textContent = 'Could not read more: ' + error;
          retry.hidden = false;
          return;
        }
        add(page);
      });
    }

    retry.addEventListener('click', function () { failed = false; retry.hidden = true; showStatus(); more(); });

    function add(page) {
      page.rows.forEach(function (row) { rows.push(row); });
      total = page.total;
      next = page.next;
      showStatus();
      paint(true);
    }

    // a different column width changes how the descriptions wrap, so the measured heights no longer hold
    let width = 0;
    const resize = new ResizeObserver(function () {
      const now = table.getBoundingClientRect().width;
      if (Math.abs(now - width) < 1) return;
      width = now;
      heights.length = 0;
      schedule(true);
    });
    resize.observe(table);
    function onScroll() { schedule(false); }
    scroller.addEventListener('scroll', onScroll, { passive: true });
    stop = function () {
      resize.disconnect();
      scroller.removeEventListener('scroll', onScroll);
      cancelAnimationFrame(frame);
    };

    if (!first.rows.length) {   // the columns stay, and the message is centred in the space under them
      foot.hidden = true;
      tree.emptyUnder(target, LOG_ICON, 'No changes logged', 'Changes made to this item in Fusion Manage will be listed here.');
      return;
    }
    add(first);
  }

  ns.itemChangeLog = { render: render };
})(window.MfgUi);
