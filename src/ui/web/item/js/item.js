/**
 * Item panel. Python finds the Fusion Manage item of the selected component and reads its
 * sections; this page polls for the answer and draws it.
 */
(function (ns) {
  'use strict';

  const bridge = ns.bridge;
  const $ = ns.$;
  const el = ns.el;
  const POLL_INTERVAL_MS = 400;
  const LABEL_COLUMN_WIDTH = '16%';   // the row labels; the other columns share the rest equally
  const MIN_COLUMN_PX = 50;
  const MIN_MATRIX_COLUMN_PX = 120;   // a matrix column is never squeezed below this by a narrow panel

  let timer = null;
  let shownSeq = 0;   // the open that is on screen, so a poll for it does not redraw
  let itemUrl = '';
  let currentView = null;

  /** Show the bouncing balls (and hide the item) while Python is still reading everything the item needs. */
  function setLoading(on, text) {
    $('item-empty').hidden = true;
    $('item-loader').hidden = !on;
    $('item-loader-text').textContent = text || 'Loading item...';
    document.querySelectorAll('.item-part').forEach(function (part) { part.hidden = on; });
  }

  /** Say, in the middle of the panel, that no item has this number. */
  function showMissing(number) {
    setLoading(false);
    document.querySelectorAll('.item-part').forEach(function (part) { part.hidden = true; });
    $('item-empty-text').textContent = 'No item exists for ' + number;
    $('item-empty').hidden = false;
  }

  /** Show one tab ('item' or 'files') and mark its button. */
  const loaded = { bom: false, whereused: false };   // tabs read for the item shown

  /** Read a lazy tab the first time it is opened for the item shown. */
  function loadTab(name) {
    if (!currentView || loaded[name] !== false) return;
    loaded[name] = true;
    if (name === 'bom') {
      ns.itemBom.render($('item-bom'), currentView, function (count) {
        $('item-tab-bom').textContent = count ? 'Bill of Materials (' + count + ')' : 'Bill of Materials';
      });
    } else {
      ns.itemWhereUsed.render($('item-whereused'), currentView, function (count) {
        $('item-tab-whereused').textContent = count ? 'Where Used (' + count + ')' : 'Where Used';
      });
    }
  }

  function showTab(name) {
    $('item-body').hidden = name !== 'item';
    $('item-files').hidden = name !== 'files';
    $('item-bom').hidden = name !== 'bom';
    $('item-whereused').hidden = name !== 'whereused';
    loadTab(name);
    document.querySelectorAll('.item-tab[data-tab]').forEach(function (tab) {
      tab.classList.toggle('item-tab-active', tab.dataset.tab === name);
    });
  }

  function message(text, isError) {
    setLoading(false);
    showTab('item');
    $('item-body').replaceChildren(el('p', 'item-message ' + (isError ? 'error' : 'muted'), text));
  }

  function openLightbox(src) {
    $('item-lightbox-img').src = src;
    $('item-lightbox').hidden = false;
  }

  function closeLightbox() {
    $('item-lightbox').hidden = true;
    $('item-lightbox-img').removeAttribute('src');
  }

  /** Fill ``node`` with a value: text, a picture, or the (sanitised) markup of a formula field. */
  function fill(node, cell) {
    if (cell.kind === 'image') {
      if (!cell.value) return;
      const img = el('img', 'item-image');
      img.src = cell.value;
      img.alt = '';
      img.title = 'Click to enlarge';
      img.addEventListener('click', function () { openLightbox(cell.value); });
      node.appendChild(img);
    } else if (cell.kind === 'links') {
      cell.value.forEach(function (link, i) {
        if (i) node.appendChild(document.createTextNode(', '));
        const a = el('a', 'item-link', link.title);
        a.href = '#';
        a.title = 'Open in Fusion Manage in your browser';
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
    heads.slice(0, last).forEach(function (th, i) {
      const grip = el('span', 'item-grip');
      grip.addEventListener('mousedown', function (event) {
        event.preventDefault();
        freeze();
        const startX = event.clientX;
        const startWidth = parseFloat(cols[i].style.width);
        grip.classList.add('item-grip-active');
        function move(e) {
          cols[i].style.width = Math.max(MIN_COLUMN_PX, startWidth + e.clientX - startX) + 'px';
          apply();
        }
        function stop() {
          document.removeEventListener('mousemove', move);
          document.removeEventListener('mouseup', stop);
          grip.classList.remove('item-grip-active');
        }
        document.addEventListener('mousemove', move);
        document.addEventListener('mouseup', stop);
      });
      th.appendChild(grip);
    });
  }

  function renderMatrix(matrix) {
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
        fill(td, cell);
        tr.appendChild(td);
      });
      table.appendChild(tr);
    });
    const wrap = el('div', 'item-matrix-wrap');   // a wide grid scrolls sideways
    wrap.appendChild(table);
    return wrap;
  }

  function renderSection(section) {
    const wrap = el('section', 'item-section');
    const content = el('div', 'item-section-body');
    section.fields.forEach(function (f) {
      const row = el('div', 'item-field');
      row.appendChild(el('div', 'item-field-label', f.title));
      const value = el('div', 'item-field-value');
      fill(value, f);
      row.appendChild(value);
      content.appendChild(row);
    });
    section.matrices.forEach(function (m) { content.appendChild(renderMatrix(m)); });
    if (section.title) {
      const title = el('button', 'item-section-title', section.title);
      title.type = 'button';
      title.addEventListener('click', function () {
        content.hidden = !content.hidden;
        title.classList.toggle('item-collapsed', content.hidden);
        wrap.classList.toggle('item-section-folded', content.hidden);
      });
      wrap.appendChild(title);
    }
    wrap.appendChild(content);
    return wrap;
  }

  function renderHeader(view) {
    $('item-title').textContent = view.title || 'Fusion Manage Item';
    const status = $('item-status');
    status.replaceChildren();
    view.header.forEach(function (part, i) {
      if (i) status.appendChild(el('span', 'item-status-sep', '|'));
      status.appendChild(el('span', '', part));
    });
    itemUrl = view.url || '';
    $('item-open').hidden = !itemUrl;
  }

  function render(view) {
    setLoading(false);
    renderHeader(view);
    currentView = view;
    $('item-tab-files').textContent = view.files && view.files.length ? 'Files (' + view.files.length + ')' : 'Files';
    ns.itemFiles.render($('item-files'), view, function (file) {
      if (file.url) bridge.send('open_url', { url: file.url });   // the file's page in Fusion Manage
    });
    // these two are read from Fusion Manage only when their tab is opened
    loaded.bom = loaded.whereused = false;
    $('item-bom').replaceChildren();
    $('item-whereused').replaceChildren();
    $('item-tab-bom').textContent = 'Bill of Materials';
    $('item-tab-whereused').textContent = 'Where Used';
    if (!$('item-bom').hidden) loadTab('bom');   // the tab was open when the item changed
    if (!$('item-whereused').hidden) loadTab('whereused');
    const body = $('item-body');
    body.replaceChildren();
    if (!view.sections.length) { message('This item has no fields to show.'); return; }
    view.sections.forEach(function (section) { body.appendChild(renderSection(section)); });
  }

  function handle(r) {
    clearTimeout(timer);
    if (!r.ok) { message(r.error || 'Could not read the item.', true); return; }
    const entry = r.result;
    if (entry.pending) {
      if (shownSeq !== entry.seq) { shownSeq = entry.seq; setLoading(true, 'Finding the Fusion Manage item...'); }
      timer = setTimeout(poll, POLL_INTERVAL_MS);
      return;
    }
    shownSeq = entry.seq;
    if (entry.missing) { showMissing(entry.missing); return; }
    if (!entry.seq) { message('Select a component and choose Open Fusion Manage Item.'); return; }
    if (!entry.ok) { message(entry.message || 'Could not read the item.', true); return; }
    render(entry.view);
  }

  function poll() { bridge.send('get_item_view'); }

  setLoading(true);   // until the first answer

  function start() {
    // Fusion injects `adsk` asynchronously, so wait for it.
    if (typeof adsk === 'undefined') { setTimeout(start, 100); return; }
    ns.shell.mountHeader();
    ns.account.init();
    ns.auth.init();
    bridge.on('get_item_view', handle);
    bridge.on('item_changed', poll);   // Python opened another item in this palette
    bridge.on('refresh_item_view', handle);
    bridge.on('open_url', function () {});
    bridge.on('open_attachment', function () {});
    document.querySelectorAll('.item-tab[data-tab]').forEach(function (tab) {
      tab.addEventListener('click', function () { if (currentView) showTab(tab.dataset.tab); });
    });
    $('item-lightbox').addEventListener('click', closeLightbox);
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeLightbox(); });
    $('item-refresh').addEventListener('click', function () { bridge.send('refresh_item_view'); });
    $('item-open').addEventListener('click', function () { if (itemUrl) bridge.send('open_url', { url: itemUrl }); });
    ns.auth.onChange(function (signedIn) { if (signedIn) poll(); });   // read the item once signed in
    ns.auth.refresh();
    poll();
  }

  start();
})(window.MfgUi);
