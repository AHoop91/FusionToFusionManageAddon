/**
 * How an item's section is drawn, shared by the Item panel and the details of a product in the Product Portfolio window: a card for the section,
 * its fields as label and value (a picture, links, the sanitised markup of a formula field, or text) and its matrices as grids whose columns
 * can be resized. ``ns.itemSections.section(section, enlarge, load)`` returns the card; ``enlarge(src)`` is what a click on a picture does.
 * A picture the view did not carry (a ``link`` and no ``value``) is a skeleton until ``load(link, done)``, when it is given, calls ``done(src)``
 * with the picture (``''`` when there is none). A section the workspace lays out folded (``section.collapsed``) starts folded, and asks for the
 * pictures in it only when it is first unfolded.
 * Needs ``tree.js`` (the column grips), ``safe-html.js`` and ``section.js``.
 */
(function (ns) {
  'use strict';

  const bridge = ns.bridge;
  const el = ns.el;
  const t = ns.i18n.t;
  const LABEL_COLUMN_WIDTH = '16%';   // the row labels; the other columns share the rest equally
  const MIN_COLUMN_PX = 50;
  const FIT_SLACK_PX = 24;   // room for the cell's padding and the handle when a column is fitted to its content
  const MIN_MATRIX_COLUMN_PX = 120;   // a matrix column is never squeezed below this by a narrow panel

  /** A picture in ``node``; it enlarges when clicked. */
  function showPicture(node, src, enlarge) {
    const img = el('img', 'item-image');
    img.src = src;
    img.alt = '';
    img.title = t('item.enlarge');
    img.addEventListener('click', function () { enlarge(src); });
    node.appendChild(img);
  }

  /** Fill ``node`` with a value: text, a picture, or the (sanitised) markup of a formula field. */
  function fill(node, cell, enlarge, load) {
    if (cell.kind === 'image') {
      if (cell.value) { showPicture(node, cell.value, enlarge); return; }
      if (!cell.link || !load) return;
      const skeleton = el('div', 'item-image item-image-skeleton');
      node.appendChild(skeleton);
      load(cell.link, function (src) {
        if (!skeleton.isConnected) return;   // the page moved on to another product
        skeleton.remove();
        if (src) showPicture(node, src, enlarge);
      });
    } else if (cell.kind === 'links') {
      cell.value.forEach(function (link, i) {
        if (i) node.appendChild(document.createTextNode(', '));
        const a = el('a', 'item-link', link.title);
        a.href = '#';
        a.title = t('item.open_in_fusion_manage');
        a.addEventListener('click', function (event) {
          event.preventDefault();
          bridge.send('open_url', { url: link.url });
        });
        node.appendChild(a);
      });
    } else if (cell.kind === 'html') {
      ns.safeHtml.render(node, cell.value);
    } else {
      node.textContent = cell.value;
    }
  }

  /**
   * Let the user drag the right edge of a column header to resize that column (not below ``MIN_COLUMN_PX``).
   * Only that column changes. The last column (which has no handle) stretches to fill any space left in the
   * section, but never shrinks below the width it started with, so widening a column past the section's edge
   * adds a horizontal scroll bar instead. The first drag fixes every column at its current pixel width.
   */
  function makeResizable(table, cols, heads) {
    const last = heads.length - 1;
    let lastFloor = 0;   // the last column's width before any drag
    const original = cols.map(function (col) { return col.style.width; });   // as drawn, to go back to
    const originalMin = table.style.minWidth;
    function freeze() {
      const widths = heads.map(function (th) { return th.getBoundingClientRect().width; });
      if (!lastFloor) lastFloor = widths[last];
      widths.forEach(function (w, i) { cols[i].style.width = w + 'px'; });
    }
    function apply() {
      let others = 0;
      for (let i = 0; i < last; i++) others += parseFloat(cols[i].style.width);
      const width = Math.max(lastFloor, table.parentNode.clientWidth - others);
      cols[last].style.width = width + 'px';
      table.style.width = (others + width) + 'px';
    }
    /** How wide the content of cell ``cell`` is on one line, in px. */
    function natural(cell) {
      const probe = el('div');
      probe.style.cssText = 'position:absolute;visibility:hidden;left:-9999px;top:0;white-space:nowrap';
      const style = window.getComputedStyle(cell);
      probe.style.font = style.font;
      Array.prototype.forEach.call(cell.childNodes, function (node) { probe.appendChild(node.cloneNode(true)); });
      document.body.appendChild(probe);
      const width = probe.offsetWidth;
      probe.remove();
      return width;
    }
    /** Set column ``i`` as wide as the widest thing in it. */
    function size(i) {
      let widest = 0;
      Array.prototype.forEach.call(table.rows, function (row) {
        if (row.cells[i]) widest = Math.max(widest, natural(row.cells[i]));
      });
      cols[i].style.width = Math.max(MIN_COLUMN_PX, Math.ceil(widest) + FIT_SLACK_PX) + 'px';
    }
    /** Column ``i`` (a double click on its line) as wide as its content, within what the section can show. */
    function fit(i) {
      freeze();
      size(i);
      apply();
    }
    /** Go back to the widths the matrix had when it was drawn. */
    function reset() {
      cols.forEach(function (col, i) { col.style.width = original[i]; });
      table.style.width = '';
      table.style.minWidth = originalMin;
      lastFloor = 0;
    }
    const resetBtn = el('button', 'item-fit-btn');   // in the corner, where the row labels meet the column names
    resetBtn.type = 'button';
    resetBtn.title = t('item.matrix_reset');
    resetBtn.setAttribute('aria-label', t('item.matrix_reset'));
    resetBtn.appendChild(ns.svg(['M3 5h16v7', 'M3 5v12h7', 'M3 9h16', 'M3 13h7', 'M9 5v12', 'M20.5 15a4 4 0 1 0 .6 3.2', 'M21.2 12v3.3h-3.3'], 18));   // a table with a turn-back arrow
    resetBtn.addEventListener('click', reset);
    heads[0].appendChild(resetBtn);
    heads.slice(0, last).forEach(function (th, i) {
      const grip = ns.itemTree.grip(cols[i], { min: MIN_COLUMN_PX, onResize: apply, beforeDrag: freeze, title: t('item.matrix_resize_tip') });
      grip.addEventListener('dblclick', function (event) { event.stopPropagation(); fit(i); });
      th.appendChild(grip);
    });
  }

  function renderMatrix(matrix, enlarge, load) {
    const table = el('table', 'item-matrix');
    const cols = [];
    for (let i = 0; i <= matrix.columns.length; i++) {   // the first is the column of row labels, a little wider
      const col = el('col');
      if (i === 0) col.style.width = LABEL_COLUMN_WIDTH;
      cols.push(col);
    }
    table.appendChild(el('colgroup')).append(...cols);
    const head = el('tr');
    const heads = [el('th')];   // the column of row labels
    matrix.columns.forEach(function (c) {
      const th = el('th', '', c);
      th.title = c;
      heads.push(th);
    });
    table.style.minWidth = (heads.length * MIN_MATRIX_COLUMN_PX) + 'px';   // never narrower than this: a narrow panel scrolls the grid sideways instead (the table is 100% wide above it)
    heads.forEach(function (th) { head.appendChild(th); });
    makeResizable(table, cols, heads);
    table.appendChild(head);
    matrix.rows.forEach(function (row, i) {
      const tr = el('tr');
      tr.appendChild(el('td', 'item-matrix-label', matrix.labels[i]));
      row.forEach(function (cell) {
        const td = el('td');
        fill(td, cell, enlarge, load);
        tr.appendChild(td);
      });
      table.appendChild(tr);
    });
    const wrap = el('div', 'item-matrix-wrap');   // a wide grid scrolls sideways
    wrap.appendChild(table);
    return wrap;
  }

  function renderSection(section, enlarge, load) {
    const content = el('div');
    const folded = section.collapsed === true;
    const waiting = [];   // what a folded section asked for, until it is opened
    const ask = load && folded ? function (link, done) { waiting.push([link, done]); } : load;
    section.fields.forEach(function (f) {
      const row = el('div', 'item-field');
      row.appendChild(el('div', 'item-field-label', f.title));
      const value = el('div', 'item-field-value');
      fill(value, f, enlarge, ask);
      row.appendChild(value);
      content.appendChild(row);
    });
    section.matrices.forEach(function (m) { content.appendChild(renderMatrix(m, enlarge, ask)); });
    return ns.section.make(section.title, content, {
      folded: folded,
      onOpen: function () { waiting.splice(0).forEach(function (call) { load(call[0], call[1]); }); },
    });
  }

  ns.itemSections = { section: renderSection };
})(window.MfgUi);
