/**
 * Publish Item panel: Bill of Materials table, as ``ns.bomTable``. One table lists the design BOM
 * with Fusion and Fusion Manage columns that tick where each line exists, then the quantity, a
 * status and the actions for the row, with filter buttons above it.
 *
 * The lines come from bom-model.js. Clicking a row hands its component to the caller, which shows
 * the details. Drawing helpers come from ``ns.pubUi``.
 */
(function (ns) {
  'use strict';

  const ui = ns.pubUi;
  const el = ui.el;
  const model = ns.bomModel;
  const decisions = model.decisions;

  // Status chip per row status: tone (colour), label and the tooltip. A differing pair gets its chips in ``pairChip``.
  const STATUS = {
    match:   { label: 'Match',         text: 'Same line and quantity in Fusion Manage' },
    new:     { tone: 'new',     label: 'New',           text: 'Not in Fusion Manage yet: publishing adds it' },
    changed: { tone: 'changed', label: 'Updates',       text: 'Quantity differs from Fusion Manage' },
    added:   { tone: 'new',     label: 'New',           text: 'Publishing adds this line to the Fusion Manage BOM' },
    kept:    { tone: 'extra',   label: 'Keep',          text: 'Publishing keeps this Fusion Manage line, renumbered at the end of the BOM' },
    linked:  { tone: 'added',   label: 'Added',        text: 'Picked with Add Existing Items: publishing adds this Fusion Manage item to the end of the Fusion Manage BOM' },
  };
  const PAIR_ASK = 'Item number differs from the Fusion Manage line at this position: choose an action';

  // Filters above the table. A row shows when it matches any filter that is on (all rows when none is).
  const FILTERS = [
    { id: 'review',  label: 'Review',      title: 'Item number differs from Fusion Manage and no action is chosen yet' },
    { id: 'new',     label: 'New',         title: 'Not in Fusion Manage yet, with the Fusion Manage line each is paired with' },
    { id: 'added',   label: 'Added',       title: 'Picked with Add Existing Items: publishing adds them to the Fusion Manage BOM' },
    { id: 'changed', label: 'Updates',     title: 'Quantity differs from Fusion Manage' },
    { id: 'extra',   label: 'Fusion Manage Only', title: 'Only in Fusion Manage' },
    { id: 'hidden',  label: 'Show Hidden Components', title: 'Hidden in the Fusion component tree', right: true },
  ];
  const filters = {};   // filter id -> true while on; kept across redraws

  const SLOT = 32;   // width of a chevron or icon box; every level steps in by this much

  let selectedId = null;   // component whose details are open, so its rows stay highlighted across redraws
  let seenStaged = new Set();   // picked lines already drawn, so only a new one animates in
  let current = null;      // { items, trs } of the table on screen

  function selectionKey(c) {
    return c.root ? 'root' : c.id;
  }

  function paintSelection() {
    if (!current) return;
    current.trs.forEach(function (tr, i) {
      const c = current.items[i].component;
      tr.classList.toggle('selected', !!c && selectedId !== null && selectionKey(c) === selectedId);
    });
  }

  /** Highlight the rows of a component (or none), without opening anything. */
  function select(id) {
    selectedId = id;
    paintSelection();
  }

  // ---- Cells ---------------------------------------------------------------------

  /** Eye with a slash: the component is hidden in the Fusion component tree. */
  function hiddenIcon() {
    const box = el('span', 'pub-cmp-hidden');
    box.title = 'Hidden in the Fusion component tree';
    box.setAttribute('aria-label', box.title);
    box.appendChild(ui.svg(['M2 12s3.5-6.5 10-6.5S22 12 22 12s-3.5 6.5-10 6.5S2 12 2 12z', 'M12 9.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z', 'M4 4l16 16']));
    return box;
  }

  /** Item cell: indent (``item.iconX`` is where the icon starts), chevron (when ``toggle`` is given), icon, sequence, part number and name, then ``actions`` and the status ``chip``. */
  function itemCell(side, item, isAssembly, toggle, actions, chip) {
    const td = el('td', 'pub-cmp-item');
    const box = el('div', 'pub-tree-cell');
    box.style.setProperty('--indent', (item.iconX - (toggle ? SLOT : 0)) + 'px');
    if (toggle) box.appendChild(toggle);
    box.appendChild(ui.treeIcon(item.root ? 'root' : isAssembly ? 'assembly' : 'part'));
    if (item.sequence) box.appendChild(el('span', 'pub-tree-seq' + (isAssembly ? ' pub-tree-asm' : ''), side.sequence));
    const label = el('span', 'pub-tree-label');
    label.title = [side.pn, side.name].filter(Boolean).join(' - ');
    if (side.pn) label.appendChild(el('span', 'pub-tree-pn', side.pn));
    if (side.name) label.appendChild(el('span', 'pub-tree-name', side.name));
    box.appendChild(label);
    if (item.hidden) box.appendChild(hiddenIcon());
    if (actions || chip) {   // at the end of the item: the buttons (shown while the row is hovered), then the status chip
      const end = el('span', 'pub-cmp-end');
      if (actions) end.appendChild(actions);
      if (chip) end.appendChild(chip);
      box.appendChild(end);
    }
    td.appendChild(box);
    return td;
  }

  /** Tick when the line exists on that side, a quiet dash when it does not. */
  function presenceCell(present, what) {
    const td = el('td', 'pub-cmp-presence');
    const mark = el('span', present ? 'pub-cmp-tick' : 'pub-cmp-none');
    if (present) mark.appendChild(ui.svg(['M5 12l5 5L20 7']));
    else mark.textContent = '–';
    mark.title = (present ? 'In ' : 'Not in ') + what;
    mark.setAttribute('aria-label', mark.title);
    td.appendChild(mark);
    return td;
  }

  /** Chip for a differing pair: the design line (``fmRow`` false) is added; the Fusion Manage line shows the user's choice. */
  function pairChip(item, fmRow) {
    const choice = decisions[item.key];
    if (!fmRow) {
      const text = choice === 'remove' ? 'Publishing will add ' + item.design.pn + ' in place of ' + item.fm.pn
        : choice === 'add' ? 'Publishing will add ' + item.design.pn + ' and keep ' + item.fm.pn
        : 'Publishing will add ' + item.design.pn + '; choose what happens to ' + item.fm.pn;
      return { tone: 'new', label: 'New', text: text };
    }
    if (!choice) return { tone: 'pair', label: 'Review', text: PAIR_ASK };
    if (choice === 'remove') return { tone: 'removed', label: 'Remove', text: 'Publishing will remove ' + item.fm.pn + ' from Fusion Manage' };
    return { tone: 'extra', label: 'Keep', text: 'Publishing keeps ' + item.fm.pn + ' in Fusion Manage' };
  }

  /** Status chip, or null when there is nothing to say. A differing pair has two rows: the design line (``fmRow`` false) and the Fusion Manage line. */
  function statusChip(item, fmRow) {
    const status = model.statusOf(item);
    if (status === 'match') return null;   // nothing to do
    let chip;
    if (status === 'mismatch') chip = pairChip(item, fmRow);
    else if (status !== 'extra') chip = STATUS[status];
    else if (decisions[item.key] === 'remove') chip = { tone: 'removed', label: 'Remove', text: 'Publishing will remove ' + item.fm.pn + ' from Fusion Manage' };
    else chip = model.quantityDiffers(item) ? STATUS.changed : null;   // the ticks already say it is only in Fusion Manage
    if (!chip) return null;
    const node = el('span', 'pub-cmp-chip pub-cmp-chip-' + chip.tone, chip.label);
    node.title = chip.text;
    return node;
  }

  /** A line drawn from its Fusion Manage side: one only Fusion Manage has, or one picked with Add Items. */
  function fromFm(item) {
    return item.status === 'extra' || item.status === 'kept' || item.status === 'linked';
  }

  /** Remove button of a line picked with Add Items. */
  function unstageActions(item, redraw) {
    const box = el('span', 'pub-cmp-actions');
    const b = el('button', 'pub-cmp-act pub-cmp-act-remove');
    b.type = 'button';
    b.title = 'Do not add ' + item.fm.pn + ' to the Fusion Manage BOM';
    b.setAttribute('aria-label', b.title);
    b.appendChild(ui.svg(['M5 12h14']));
    b.addEventListener('click', function () {
      model.unstage(item.stagedId);
      redraw();
    });
    box.appendChild(b);
    return box;
  }

  /** Remove button of a line only Fusion Manage has: it is kept unless this is on (click again to keep it). */
  function removeAction(item, redraw) {
    const box = el('span', 'pub-cmp-actions');
    const b = el('button', 'pub-cmp-act pub-cmp-act-remove' + (decisions[item.key] === 'remove' ? ' chosen' : ''));
    b.type = 'button';
    b.title = decisions[item.key] === 'remove' ? 'Keep ' + item.fm.pn + ' in Fusion Manage' : 'Remove ' + item.fm.pn + ' from Fusion Manage';
    b.setAttribute('aria-label', b.title);
    b.appendChild(ui.svg(['M5 12h14']));
    b.addEventListener('click', function () {
      if (decisions[item.key] === 'remove') delete decisions[item.key]; else decisions[item.key] = 'remove';
      redraw();
    });
    box.appendChild(b);
    return box;
  }

  /** Add a revert button, beside the line's other buttons, while the user's quantity is over the line's own. */
  function withRevert(box, item, redraw) {
    if (!model.canEditQuantity(item) || !model.quantityEdited(item)) return box;
    const b = el('button', 'pub-cmp-act pub-cmp-act-revert');
    b.type = 'button';
    b.title = 'Revert the quantity to ' + (item.status === 'extra' ? item.fm.quantity : item.design.quantity);
    b.setAttribute('aria-label', b.title);
    b.appendChild(ui.svg(['M9 14L4 9l5-5', 'M4 9h10.5a5.5 5.5 0 0 1 0 11H11']));   // a curved undo arrow
    b.addEventListener('click', function () {
      model.revertQuantity(item);
      redraw();
    });
    const out = box || el('span', 'pub-cmp-actions');
    out.appendChild(b);
    return out;
  }

  /** Quantity: the design's, or the Fusion Manage line's for a line only it has; a differing Fusion Manage quantity is shown beside it. A line picked with Add Items has a box to edit it. */
  function quantityCell(item, redraw) {
    const staged = item.status === 'linked';
    if (staged || model.canEditQuantity(item)) {
      const td = el('td', 'num pub-cmp-qty');
      const input = el('input', 'pub-cmp-qty-input');
      input.type = 'text';
      input.inputMode = 'decimal';
      input.value = staged ? item.fm.quantity : model.quantityOf(item);
      input.title = 'Quantity of this line in the Fusion Manage BOM';
      input.setAttribute('aria-label', 'Quantity of ' + (staged || fromFm(item) ? item.fm.pn : item.design.pn));
      input.addEventListener('input', function () {   // numbers only: digits and one decimal point, whether typed or pasted
        const clean = input.value.replace(/[^0-9.]/g, '').replace(/^([^.]*\.)(.*)$/, function (_, head, tail) { return head + tail.replace(/\./g, ''); });
        if (clean !== input.value) input.value = clean;
      });
      input.addEventListener('change', function () {
        const typed = input.value;
        input.value = staged ? model.setStagedQuantity(item.stagedId, typed) : model.setQuantity(item, typed);
        if (Number(typed) !== Number(input.value)) ns.toast.show('Quantity must be a number above 0', { tone: 'error' });
        if (!staged) redraw();   // the status and filters follow the new quantity
      });
      td.appendChild(input);
      if (model.statusOf(item) === 'changed' || model.quantityDiffers(item)) td.classList.add('pub-cmp-qty-diff');   // will update Fusion Manage
      return td;
    }
    return el('td', 'num pub-cmp-qty', fromFm(item) ? item.fm.quantity : item.design.quantity);
  }

  /** Icon buttons on the Fusion Manage line of a differing pair: keep both lines, or remove this one. A kept line has them too, to undo the choice. */
  function actionButtons(item, redraw) {
    if (!item.key || item.status === 'added') return null;
    const box = el('span', 'pub-cmp-actions');
    [['add', 'Keep both: add ' + item.design.pn + ' and keep ' + item.fm.pn, ['M5 12l5 5L20 7']],
     ['remove', 'Remove ' + item.fm.pn + ' from Fusion Manage and add ' + item.design.pn, ['M5 12h14']]].forEach(function (a) {
      const b = el('button', 'pub-cmp-act pub-cmp-act-' + a[0] + (decisions[item.key] === a[0] ? ' chosen' : ''));
      b.type = 'button';
      b.title = a[1];
      b.setAttribute('aria-label', a[1]);
      b.appendChild(ui.svg(a[2]));
      b.addEventListener('click', function () {
        if (decisions[item.key] === a[0]) delete decisions[item.key]; else decisions[item.key] = a[0];
        redraw();
      });
      box.appendChild(b);
    });
    return box;
  }

  // ---- The table -----------------------------------------------------------------

  /** Set ``item.iconX`` (where each icon starts): every level steps in by one slot, so a chevron sits under its parent's icon. */
  function layOut(items, chevronLevels) {
    const iconX = ns.stepIn(items.map(function (item) { return item.level; }), chevronLevels[0], SLOT);
    items.forEach(function (item) { item.iconX = iconX[item.level]; });
  }

  /** Toggle buttons above the table; ``onChange`` runs after one is flipped. */
  function filterBar(items, onChange) {
    const bar = el('div', 'pub-cmp-filters');
    bar.setAttribute('role', 'group');
    bar.setAttribute('aria-label', 'Filter the Bill of Materials');
    const counts = {};
    items.forEach(function (item) { model.groupsOf(item).forEach(function (g) { counts[g] = (counts[g] || 0) + 1; }); });
    const buttons = {};
    function paint() {
      FILTERS.forEach(function (f) {
        buttons[f.id].classList.toggle('on', !!filters[f.id]);
        buttons[f.id].setAttribute('aria-pressed', filters[f.id] ? 'true' : 'false');
      });
      paintMenu();
    }
    function flip(id) {
      if (filters[id]) delete filters[id]; else filters[id] = true;
      paint();
      onChange();
    }
    FILTERS.forEach(function (f) {
      const b = el('button', 'pub-cmp-filter' + (f.right ? ' pub-cmp-filter-right' : ''), f.label);
      b.type = 'button';
      b.title = f.title;
      b.appendChild(el('span', 'pub-cmp-filter-count', String(counts[f.id] || 0)));
      b.addEventListener('click', function () { flip(f.id); });
      buttons[f.id] = b;
      bar.appendChild(b);
    });

    // In a narrow panel the buttons are replaced by one Filters drop-down with a tick list (any number on at once).
    const menu = el('div', 'pub-cmp-menu');
    const trigger = el('button', 'pub-cmp-menu-btn');
    trigger.type = 'button';
    trigger.setAttribute('aria-haspopup', 'true');
    trigger.setAttribute('aria-expanded', 'false');
    trigger.appendChild(el('span', '', 'Filters'));
    const badge = el('span', 'pub-cmp-filter-count');
    trigger.appendChild(badge);
    trigger.appendChild(ui.svg(['M6 9l6 6 6-6']));
    const pop = el('div', 'pub-cmp-menu-pop');
    pop.hidden = true;
    const boxes = {};
    FILTERS.forEach(function (f) {
      const row = el('label', 'pub-cmp-menu-item' + (f.right ? ' pub-cmp-menu-sep' : ''));
      row.title = f.title;
      const box = el('input');
      box.type = 'checkbox';
      box.addEventListener('change', function () { flip(f.id); });
      boxes[f.id] = box;
      row.appendChild(box);
      row.appendChild(el('span', 'pub-cmp-menu-text', f.label));
      row.appendChild(el('span', 'pub-cmp-filter-count', String(counts[f.id] || 0)));
      pop.appendChild(row);
    });
    const clear = el('button', 'pub-cmp-menu-clear', 'Clear filters');
    clear.type = 'button';
    clear.addEventListener('click', function () {
      Object.keys(filters).forEach(function (id) { delete filters[id]; });
      paint();
      onChange();
    });
    pop.appendChild(clear);
    menu.appendChild(trigger);
    menu.appendChild(pop);
    bar.appendChild(menu);

    function paintMenu() {
      const active = Object.keys(filters).length;
      FILTERS.forEach(function (f) { boxes[f.id].checked = !!filters[f.id]; });
      badge.textContent = String(active);
      badge.hidden = !active;
      trigger.classList.toggle('on', active > 0);
      clear.disabled = !active;
    }
    function closeMenu() {
      pop.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
      document.removeEventListener('mousedown', outside, true);
      document.removeEventListener('keydown', onEsc, true);
    }
    function outside(event) { if (!menu.contains(event.target)) closeMenu(); }
    function onEsc(event) { if (event.key === 'Escape') closeMenu(); }
    trigger.addEventListener('click', function () {
      if (!pop.hidden) { closeMenu(); return; }
      pop.hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
      document.addEventListener('mousedown', outside, true);
      document.addEventListener('keydown', onEsc, true);
    });

    paint();
    return bar;
  }

  /**
   * Rows that pass the filters, plus the assemblies above them so a row keeps its place in the tree; null when nothing is left out.
   * Show Hidden Components is not a filter of its own: off, components hidden in Fusion are left out; on, they join the rest.
   */
  function visibleByFilter(items) {
    const groupOn = Object.keys(filters).some(function (id) { return id !== 'hidden'; });
    if (!groupOn && filters.hidden) return null;
    const show = items.map(function (item) {
      if (item.root) return true;
      if (item.hidden && !filters.hidden) return false;
      return !groupOn || model.groupsOf(item).some(function (g) { return g !== 'hidden' && filters[g]; });
    });
    let need = Infinity;   // level a row must be below to be the ancestor of a shown row further down
    for (let i = items.length - 1; i >= 0; i--) {
      if (show[i]) need = Math.min(need, items[i].level);
      else if (need !== Infinity && items[i].level < need) { show[i] = true; need = items[i].level; }
    }
    return show;
  }

  // Column widths (px; 0 = takes the rest). The user can drag a header edge; each layout remembers its own widths.
  const NARROW = window.matchMedia('(max-width: 760px)');
  const DEFAULT_WIDTHS = { wide: [0, 84, 84, 84], narrow: [0, 76, 76, 72] };
  const MIN_WIDTHS = [120, 64, 64, 56];
  const HEADS = [['Item', ''], ['Fusion', 'pub-cmp-center'], ['Manage', 'pub-cmp-center'], ['Qty', 'num']];
  const dragged = { wide: {}, narrow: {} };   // layout -> column index -> width the user chose

  function layoutKey() { return NARROW.matches ? 'narrow' : 'wide'; }

  /** Column widths and the header row (with a drag handle on each column's right edge). */
  function tableHead(table) {
    const key = layoutKey();
    const cols = HEADS.map(function () { return el('col'); });
    function widthOf(i) { return dragged[key][i] !== undefined ? dragged[key][i] : DEFAULT_WIDTHS[key][i]; }
    const last = HEADS.length - 1;
    function apply() {
      const fixed = dragged[key][0] !== undefined;   // the Item column has a width of its own
      let others = 0;
      cols.forEach(function (col, i) {
        const w = widthOf(i);
        col.style.width = w ? w + 'px' : '';
        if (i < last) others += w;
      });
      // Then the table is as wide as its columns (it scrolls when that is wider than the panel), and the last column
      // takes any space the panel has left, never less than its own width.
      let tail = widthOf(last);
      if (fixed) {
        tail = Math.max(tail, (table.parentNode ? table.parentNode.clientWidth : 0) - others);
        cols[last].style.width = tail + 'px';
      }
      table.style.width = fixed ? (others + tail) + 'px' : '';
      table.style.setProperty('--qty-w', tail + 'px');   // row buttons stick beside Qty
    }
    // Once the table is in the page, follow the width of its panel.
    requestAnimationFrame(function () {
      if (table.parentNode && window.ResizeObserver) new ResizeObserver(apply).observe(table.parentNode);
    });
    const group = el('colgroup');
    cols.forEach(function (col) { group.appendChild(col); });

    const head = el('tr');
    HEADS.forEach(function (h, i) {
      const th = el('th', h[1], h[0]);
      head.appendChild(th);
      if (i === last) return;   // the last column has no handle: it takes what is left
      const grip = el('span', 'pub-cmp-grip');
      grip.title = 'Drag to resize the column (double-click to reset)';
      grip.addEventListener('pointerdown', function (event) {
        event.preventDefault();
        event.stopPropagation();
        const from = th.getBoundingClientRect().width;
        const x0 = event.clientX;
        grip.setPointerCapture(event.pointerId);
        grip.classList.add('dragging');
        function onMove(e) { dragged[key][i] = Math.max(MIN_WIDTHS[i], Math.round(from + e.clientX - x0)); apply(); }
        function onUp() {
          grip.classList.remove('dragging');
          grip.removeEventListener('pointermove', onMove);
          grip.removeEventListener('pointerup', onUp);
          grip.removeEventListener('pointercancel', onUp);
        }
        grip.addEventListener('pointermove', onMove);
        grip.addEventListener('pointerup', onUp);
        grip.addEventListener('pointercancel', onUp);
      });
      grip.addEventListener('dblclick', function () { delete dragged[key][i]; apply(); });
      th.appendChild(grip);
    });
    apply();
    return [group, head];
  }

  /**
   * Draw the compare table into ``host``.
   * ``rows`` are the compared BOM rows (tree order, ``level`` 0 = child of the root);
   * ``root`` is the open design's summary; ``onSelect(component)`` is called when a row is clicked;
   * ``onReview(pending)`` is called after each draw with the number of lines still waiting for a choice.
   */
  function render(host, rows, root, onSelect, onReview) {
    const items = model.arrange(model.buildItems(rows, root));
    const chevronLevels = {};
    items.forEach(function (item, i) { if (items[i + 1] && items[i + 1].level > item.level) chevronLevels[item.level] = true; });
    layOut(items, chevronLevels);

    const collapsed = {};
    const trs = [];
    const fmTrs = [];   // per item: the Fusion Manage row of a differing pair, else null
    function apply() {   // hide rows under a collapsed assembly, and rows the filters leave out
      const show = visibleByFilter(items);
      let hideBelow = null;
      trs.forEach(function (tr, i) {
        const level = items[i].level;
        let hide = show ? !show[i] : false;
        if (hideBelow !== null && level > hideBelow) hide = true; else hideBelow = null;
        if (hideBelow === null && collapsed[i]) hideBelow = level;
        tr.hidden = hide;
        if (fmTrs[i]) fmTrs[i].hidden = hide;
      });
    }
    function redraw() {
      host.removeChild(view);
      render(host, rows, root, onSelect, onReview);
    }

    const view = el('div', 'pub-cmp-view');
    view.appendChild(filterBar(items, apply));
    const table = el('table', 'pub-cmp');
    tableHead(table).forEach(function (node) { table.appendChild(node); });

    const seenBefore = seenStaged;
    seenStaged = new Set(items.filter(function (item) { return item.stagedId !== undefined; }).map(function (item) { return item.stagedId; }));
    items.forEach(function (item, i) {
      const fresh = item.stagedId !== undefined && !seenBefore.has(item.stagedId);   // picked since the last draw
      const tr = el('tr', 'pub-cmp-row pub-cmp-' + model.statusOf(item) + (item.hidden ? ' pub-cmp-is-hidden' : '') + (fresh ? ' pub-cmp-fresh' : ''));
      const isAssembly = !!(items[i + 1] && items[i + 1].level > item.level);
      const toggle = chevronLevels[item.level] ? el('button', 'pub-tree-toggle') : null;
      if (toggle) toggle.type = 'button';
      if (isAssembly) {
        toggle.appendChild(ui.chevron());
        toggle.setAttribute('aria-label', 'Collapse or expand');
        toggle.addEventListener('click', function () {
          collapsed[i] = !collapsed[i];
          ui.setChevron(toggle.firstChild, collapsed[i]);
          apply();
        });
      } else if (toggle) {
        toggle.disabled = true;
      }

      // A line only Fusion Manage has is drawn from its own side; every other row from the design's.
      const fmOnly = fromFm(item);
      const actions = withRevert(item.status === 'kept' ? actionButtons(item, redraw) : item.status === 'linked' ? unstageActions(item, redraw)
        : item.status === 'extra' ? removeAction(item, redraw) : null, item, redraw);
      if (item.status === 'extra' && decisions[item.key] === 'remove') tr.classList.add('pub-cmp-removing');
      tr.appendChild(itemCell(fmOnly ? item.fm : item.design, item, isAssembly, toggle, actions, statusChip(item, false)));
      tr.appendChild(presenceCell(!fmOnly, 'the design'));
      tr.appendChild(presenceCell(!['new', 'mismatch', 'added', 'linked', 'uncompared'].includes(item.status), 'Fusion Manage'));
      tr.appendChild(quantityCell(item, redraw));
      if (item.component && (item.root || item.component.id !== '')) {
        tr.classList.add('pub-cmp-pick');
        tr.addEventListener('click', function (event) {
          if (event.target.closest('button')) return;   // chevrons and action buttons do their own thing
          selectedId = selectionKey(item.component);
          paintSelection();
          onSelect(item.component);
        });
      }
      table.appendChild(tr);
      trs.push(tr);
      fmTrs.push(null);
      if (item.status === 'mismatch') {   // the Fusion Manage line at this position gets its own row
        const fmTr = el('tr', 'pub-cmp-row pub-cmp-fmline' + (decisions[item.key] === 'remove' ? ' pub-cmp-removing' : ''));
        const spacer = chevronLevels[item.level] ? Object.assign(el('button', 'pub-tree-toggle'), { type: 'button', disabled: true }) : null;
        const fmCell = itemCell(item.fm, Object.assign({}, item, { hidden: false }), false, spacer, actionButtons(item, redraw), statusChip(item, true));   // the buttons sit on the line that is not in the design
        fmCell.querySelector('.pub-tree-pn').classList.add('pub-cmp-diff');
        fmTr.appendChild(fmCell);
        fmTr.appendChild(presenceCell(false, 'the design'));
        fmTr.appendChild(presenceCell(true, 'Fusion Manage'));
        fmTr.appendChild(el('td', 'num pub-cmp-qty', item.fm.quantity));
        table.appendChild(fmTr);
        fmTrs[fmTrs.length - 1] = fmTr;
      }
    });

    const wrap = el('div', 'pub-cmp-wrap');
    wrap.appendChild(table);
    view.appendChild(wrap);
    host.appendChild(view);
    current = { items: items, trs: trs, redraw: redraw };
    paintSelection();
    apply();
    if (onReview) onReview(model.pendingReviews(items));
  }

  // Crossing between the wide and narrow layouts changes the default column widths: draw the table again.
  NARROW.addEventListener('change', function () { if (current && current.redraw) current.redraw(); });

  ns.bomTable = { render: render, select: select };
})(window.MfgUi);
