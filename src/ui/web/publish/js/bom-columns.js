/**
 * Publish Item panel: the columns of the Bill of Materials table, as ``ns.bomColumns``.
 *
 * The header row, the widths of the columns, and the handle on each header edge that resizes one. Column widths are in px (0 = takes
 * the rest); each layout (wide, narrow) remembers the widths the user dragged.
 */
(function (ns) {
  'use strict';

  const el = ns.pubUi.el;

  const NARROW = window.matchMedia('(max-width: 760px)');
  const DEFAULT_WIDTHS = { wide: [0, 84, 84, 84], narrow: [0, 76, 76, 72] };
  const MIN_WIDTHS = [120, 64, 64, 56];
  const HEADS = [['Item', ''], ['Fusion', 'pub-cmp-center'], ['Manage', 'pub-cmp-center'], ['Qty', 'num']];
  const LAST = HEADS.length - 1;
  const dragged = { wide: {}, narrow: {} };   // layout -> column index -> width the user chose

  let watcher = null;   // follows the width of the panel the table is in; one at a time, for the table on screen

  function layoutKey() { return NARROW.matches ? 'narrow' : 'wide'; }

  /** Set the widths of ``cols`` and ``table``, for the layout ``key``. */
  function sizeColumns(table, cols, key) {
    const widthOf = function (i) { return dragged[key][i] !== undefined ? dragged[key][i] : DEFAULT_WIDTHS[key][i]; };
    const fixed = dragged[key][0] !== undefined;   // the Item column has a width of its own
    let others = 0;
    cols.forEach(function (col, i) {
      const w = widthOf(i);
      col.style.width = w ? w + 'px' : '';
      if (i < LAST) others += w;
    });
    // Then the table is as wide as its columns (it scrolls when that is wider than the panel), and the last column
    // takes any space the panel has left, never less than its own width.
    let tail = widthOf(LAST);
    if (fixed) {
      tail = Math.max(tail, (table.parentNode ? table.parentNode.clientWidth : 0) - others);
      cols[LAST].style.width = tail + 'px';
    }
    table.style.width = fixed ? (others + tail) + 'px' : '';
    table.style.setProperty('--qty-w', tail + 'px');   // row buttons stick beside Qty
  }

  /** The drag handle on a header's right edge: drag to resize, double-click to reset. */
  function grip(th, index, key, resize) {
    const handle = el('span', 'pub-cmp-grip');
    handle.title = 'Drag to resize the column (double-click to reset)';
    handle.addEventListener('pointerdown', function (event) {
      event.preventDefault();
      event.stopPropagation();
      const from = th.getBoundingClientRect().width;
      const x0 = event.clientX;
      handle.setPointerCapture(event.pointerId);
      handle.classList.add('dragging');
      function onMove(e) { dragged[key][index] = Math.max(MIN_WIDTHS[index], Math.round(from + e.clientX - x0)); resize(); }
      function onUp() {
        handle.classList.remove('dragging');
        handle.removeEventListener('pointermove', onMove);
        handle.removeEventListener('pointerup', onUp);
        handle.removeEventListener('pointercancel', onUp);
      }
      handle.addEventListener('pointermove', onMove);
      handle.addEventListener('pointerup', onUp);
      handle.addEventListener('pointercancel', onUp);
    });
    handle.addEventListener('dblclick', function () { delete dragged[key][index]; resize(); });
    return handle;
  }

  /** The column group and the header row of ``table`` (with a drag handle on each column's right edge but the last, which takes what is left). */
  function head(table) {
    const key = layoutKey();
    const cols = HEADS.map(function () { return el('col'); });
    const resize = function () { sizeColumns(table, cols, key); };
    // Once the table is in the page, follow the width of its panel.
    requestAnimationFrame(function () {
      if (watcher) watcher.disconnect();
      if (table.parentNode && window.ResizeObserver) {
        watcher = new ResizeObserver(resize);
        watcher.observe(table.parentNode);
      }
    });
    const group = el('colgroup');
    cols.forEach(function (col) { group.appendChild(col); });

    const row = el('tr');
    HEADS.forEach(function (h, i) {
      const th = el('th', h[1], h[0]);
      row.appendChild(th);
      if (i < LAST) th.appendChild(grip(th, i, key, resize));
    });
    resize();
    return [group, row];
  }

  /** ``callback`` runs when the layout changes between wide and narrow, which has other default widths: the table is drawn again. */
  function onLayoutChange(callback) {
    NARROW.addEventListener('change', callback);
  }

  ns.bomColumns = { head: head, onLayoutChange: onLayoutChange };
})(window.MfgUi);
