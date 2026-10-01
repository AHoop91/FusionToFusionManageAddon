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
    match:   { tone: 'match',   label: 'Match',         text: 'Same line and quantity in Fusion Manage' },
    new:     { tone: 'new',     label: 'New',           text: 'Not in Fusion Manage yet: publishing adds it' },
    changed: { tone: 'changed', label: 'Updates',       text: 'Quantity differs from Fusion Manage' },
    added:   { tone: 'new',     label: 'New',           text: 'Publishing adds this line to the Fusion Manage BOM' },
    kept:    { tone: 'extra',   label: 'Keep',          text: 'Publishing keeps this Fusion Manage line, renumbered at the end of the BOM' },
    extra:   { tone: 'extra',   label: 'FM only',       text: 'Only in Fusion Manage: kept, publishing never removes lines' },
  };
  const PAIR_ASK = 'Item number differs from the Fusion Manage line at this position: choose an action';

  // Filters above the table. A row shows when it matches any filter that is on (all rows when none is).
  const FILTERS = [
    { id: 'review',  label: 'Review',      title: 'Item number differs from Fusion Manage and no action is chosen yet' },
    { id: 'new',     label: 'New',         title: 'Not in Fusion Manage yet, with the Fusion Manage line each is paired with' },
    { id: 'changed', label: 'Updates',     title: 'Quantity differs from Fusion Manage' },
    { id: 'extra',   label: 'Fusion Manage Only', title: 'Only in Fusion Manage' },
    { id: 'hidden',  label: 'Show Hidden Components', title: 'Hidden in the Fusion component tree', right: true },
  ];
  const filters = {};   // filter id -> true while on; kept across redraws

  const SLOT = 32;   // width of a chevron or icon box; every level steps in by this much

  let selectedId = null;   // component whose details are open, so its rows stay highlighted across redraws
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

  /** Item cell: indent (``item.iconX`` is where the icon starts), chevron (when ``toggle`` is given), icon, sequence, part number and name. */
  function itemCell(side, item, isAssembly, toggle) {
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

  /** Status chip. A differing pair has two rows: the design line (``fmRow`` false) and the Fusion Manage line. */
  function statusCell(item, fmRow) {
    const td = el('td', 'pub-cmp-status');
    if (item.status === 'match') {   // nothing to do: a quiet dash, not a chip
      const dash = el('span', 'pub-cmp-none', '–');
      dash.title = STATUS.match.text;
      td.appendChild(dash);
      return td;
    }
    const chip = item.status === 'mismatch' ? pairChip(item, fmRow) : STATUS[item.status];
    if (!chip) return td;
    const node = el('span', 'pub-cmp-chip pub-cmp-chip-' + chip.tone, chip.label);
    node.title = chip.text;
    td.appendChild(node);
    return td;
  }

  /** Quantity: the design's, or the Fusion Manage line's for a line only it has; a differing Fusion Manage quantity is shown beside it. */
  function quantityCell(item) {
    const td = el('td', 'num pub-cmp-qty', item.status === 'extra' || item.status === 'kept' ? item.fm.quantity : item.design.quantity);
    if (item.status === 'changed') {
      td.classList.add('pub-cmp-qty-diff');
      td.appendChild(el('span', 'pub-cmp-qty-fm', ' (FM ' + item.fm.quantity + ')'));
    }
    return td;
  }

  /** Icon buttons on the Fusion Manage line of a differing pair: keep both lines, or remove this one. A kept line has them too, to undo the choice. */
  function actionCell(item, redraw) {
    const td = el('td', 'pub-cmp-action');
    if (!item.key || item.status === 'added') return td;
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
    td.appendChild(box);
    return td;
  }

  // ---- The table -----------------------------------------------------------------

  /** Set ``item.iconX`` (where each icon starts): every level steps in by one slot, so a chevron sits under its parent's icon. */
  function layOut(items, chevronLevels) {
    const iconX = [];
    items.forEach(function (item) {
      if (iconX[item.level] === undefined) {
        iconX[item.level] = item.level === 0 ? (chevronLevels[0] ? SLOT : 0) : (iconX[item.level - 1] || 0) + SLOT;
      }
      item.iconX = iconX[item.level];
    });
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
    }
    FILTERS.forEach(function (f) {
      const b = el('button', 'pub-cmp-filter' + (f.right ? ' pub-cmp-filter-right' : ''), f.label);
      b.type = 'button';
      b.title = f.title;
      b.appendChild(el('span', 'pub-cmp-filter-count', String(counts[f.id] || 0)));
      b.addEventListener('click', function () {
        if (filters[f.id]) delete filters[f.id]; else filters[f.id] = true;
        paint();
        onChange();
      });
      buttons[f.id] = b;
      bar.appendChild(b);
    });
    paint();
    return bar;
  }

  /** Rows that pass the filters, plus the assemblies above them so a row keeps its place in the tree; null when no filter is on. */
  function visibleByFilter(items) {
    if (!Object.keys(filters).length) return null;
    const show = items.map(function (item) { return item.root || model.groupsOf(item).some(function (g) { return filters[g]; }); });
    let need = Infinity;   // level a row must be below to be the ancestor of a shown row further down
    for (let i = items.length - 1; i >= 0; i--) {
      if (show[i]) need = Math.min(need, items[i].level);
      else if (need !== Infinity && items[i].level < need) { show[i] = true; need = items[i].level; }
    }
    return show;
  }

  /** Column widths and the header row. */
  function tableHead() {
    const cols = el('colgroup');
    ['', '64px', '64px', '84px', '116px', '64px'].forEach(function (w) {
      const col = el('col');
      if (w) col.style.width = w;
      cols.appendChild(col);
    });
    const head = el('tr');
    [['Item', ''], ['Fusion', 'pub-cmp-center'], ['Manage', 'pub-cmp-center'], ['Qty', 'num'], ['Status', 'pub-cmp-status'], ['Actions', 'pub-cmp-center']].forEach(function (h) {
      head.appendChild(el('th', h[1], h[0]));
    });
    return [cols, head];
  }

  /**
   * Draw the compare table into ``host``.
   * ``rows`` are the compared BOM rows (tree order, ``level`` 0 = child of the root);
   * ``root`` is the open design's summary; ``onSelect(component)`` is called when a row is clicked.
   */
  function render(host, rows, root, onSelect) {
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
      render(host, rows, root, onSelect);
    }

    const view = el('div', 'pub-cmp-view');
    view.appendChild(filterBar(items, apply));
    const table = el('table', 'pub-cmp');
    tableHead().forEach(function (node) { table.appendChild(node); });

    items.forEach(function (item, i) {
      const tr = el('tr', 'pub-cmp-row pub-cmp-' + item.status + (item.hidden ? ' pub-cmp-is-hidden' : ''));
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
      const fmOnly = item.status === 'extra' || item.status === 'kept';
      tr.appendChild(itemCell(fmOnly ? item.fm : item.design, item, isAssembly, toggle));
      tr.appendChild(presenceCell(!fmOnly, 'the design'));
      tr.appendChild(presenceCell(item.status !== 'new' && item.status !== 'mismatch' && item.status !== 'added', 'Fusion Manage'));
      tr.appendChild(quantityCell(item));
      tr.appendChild(statusCell(item, false));
      tr.appendChild(item.status === 'kept' ? actionCell(item, redraw) : el('td', 'pub-cmp-action'));
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
        const fmCell = itemCell(item.fm, Object.assign({}, item, { hidden: false }), false, spacer);
        fmCell.querySelector('.pub-tree-pn').classList.add('pub-cmp-diff');
        fmTr.appendChild(fmCell);
        fmTr.appendChild(presenceCell(false, 'the design'));
        fmTr.appendChild(presenceCell(true, 'Fusion Manage'));
        fmTr.appendChild(el('td', 'num pub-cmp-qty', item.fm.quantity));
        fmTr.appendChild(statusCell(item, true));
        fmTr.appendChild(actionCell(item, redraw));   // the buttons sit on the line that is not in the design
        table.appendChild(fmTr);
        fmTrs[fmTrs.length - 1] = fmTr;
      }
    });

    const wrap = el('div', 'pub-cmp-wrap');
    wrap.appendChild(table);
    view.appendChild(wrap);
    host.appendChild(view);
    current = { items: items, trs: trs };
    paintSelection();
    apply();
  }

  ns.bomTable = { render: render, select: select };
})(window.MfgUi);
