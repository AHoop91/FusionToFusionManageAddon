/**
 * Publish Item panel: Bill of Materials tab. One table lists the design BOM with Fusion and
 * Fusion Manage columns that tick where each line exists, then the quantity, a status
 * and the actions for the row.
 *
 * It draws the compared rows (design rows compared with Fusion Manage), with
 * filter buttons above the table, and owns nothing else. Drawing helpers shared with
 * publish.js come from ``ns.pubTree``.
 *
 * Fusion Manage extends the design BOM, so lines only it has are kept. When the
 * item number differs at one position, the design line and the Fusion Manage line
 * share a row and the user picks an action for it.
 */
(function (ns) {
  'use strict';

  // Status chip per row status: tone (colour), label and the tooltip.
  const STATUS = {
    match:   { tone: 'match',   label: 'Match',         text: 'Same line and quantity in Fusion Manage' },
    new:     { tone: 'new',     label: 'New',           text: 'Not in Fusion Manage yet: publishing adds it' },
    changed: { tone: 'changed', label: 'Updates',       text: 'Quantity differs from Fusion Manage' },
    added:   { tone: 'add',     label: 'Add',           text: 'Publishing adds this line to the Fusion Manage BOM' },
    kept:    { tone: 'extra',   label: 'Keep',          text: 'Publishing keeps this Fusion Manage line, renumbered at the end of the BOM' },
    extra:   { tone: 'extra',   label: 'FM only',       text: 'Only in Fusion Manage: kept, publishing never removes lines' },
  };
  const PAIR_ASK = 'Item number differs from the Fusion Manage line at this position: choose an action';

  // What the user chose for each row whose item numbers differ: 'remove' (the Fusion Manage line goes, the design line is added) or 'add' (keep both).
  // Keyed "design number|Fusion Manage number|n" (see buildItems), so a choice survives a redraw. Publishing will read it.
  const decisions = {};

  // Filters above the table. A row shows when it matches any filter that is on (all rows when none is).
  // "Review" is a differing pair still waiting for a choice; "Add" is every row of a pair or an added line.
  const FILTERS = [
    { id: 'review',  label: 'Review',      title: 'Item number differs from Fusion Manage and no action is chosen yet' },
    { id: 'new',     label: 'New',         title: 'Not in Fusion Manage yet' },
    { id: 'add',     label: 'Add',         title: 'Lines publishing adds, with the Fusion Manage line each is paired with' },
    { id: 'changed', label: 'Updates',     title: 'Quantity differs from Fusion Manage' },
    { id: 'extra',   label: 'Fusion Manage Only', title: 'Only in Fusion Manage' },
    { id: 'hidden', label: 'Show Hidden Components', title: 'Hidden in the Fusion component tree', right: true },
  ];
  const filters = {};   // filter id -> true while on; kept across redraws

  /** The filters a row belongs to. */
  function groupsOf(item) {
    const groups = statusGroups(item);
    return item.hidden && !item.root ? groups.concat('hidden') : groups;
  }

  function statusGroups(item) {
    switch (item.status) {
      case 'mismatch': return decisions[item.key] ? ['add', 'extra'] : ['review', 'add', 'extra'];   // its Fusion Manage line is only in Fusion Manage
      case 'added': return ['add'];
      case 'kept': return ['add', 'extra'];
      case 'root': return [];
      default: return [item.status];
    }
  }

  function svg(viewBox, paths) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    node.setAttribute('viewBox', viewBox);
    paths.forEach(function (d) {
      const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      p.setAttribute('d', d);
      node.appendChild(p);
    });
    return node;
  }

  /** Eye with a slash: the component is hidden in the Fusion component tree. */
  function hiddenIcon() {
    const box = ns.pubTree.el('span', 'pub-cmp-hidden');
    box.title = 'Hidden in the Fusion component tree';
    box.setAttribute('aria-label', box.title);
    box.appendChild(svg('0 0 24 24', ['M2 12s3.5-6.5 10-6.5S22 12 22 12s-3.5 6.5-10 6.5S2 12 2 12z', 'M12 9.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z', 'M4 4l16 16']));
    return box;
  }

  /** Item cell: indent (``item.iconX`` is where the icon starts), chevron (when ``toggle`` is given), icon, sequence, part number and name. */
  function itemCell(side, item, isAssembly, toggle) {
    const t = ns.pubTree;
    const td = t.el('td', 'pub-cmp-item');
    const box = t.el('div', 'pub-tree-cell');
    box.style.setProperty('--indent', (item.iconX - (toggle ? 32 : 0)) + 'px');
    if (toggle) box.appendChild(toggle);
    box.appendChild(t.treeIcon(item.root ? 'root' : isAssembly ? 'assembly' : 'part'));
    if (item.sequence) box.appendChild(t.el('span', 'pub-tree-seq' + (isAssembly ? ' pub-tree-asm' : ''), side.sequence));
    const label = t.el('span', 'pub-tree-label');
    label.title = [side.pn, side.name].filter(Boolean).join(' - ');
    if (side.pn) label.appendChild(t.el('span', 'pub-tree-pn', side.pn));
    if (side.name) label.appendChild(t.el('span', 'pub-tree-name', side.name));
    box.appendChild(label);
    if (item.hidden) box.appendChild(hiddenIcon());
    td.appendChild(box);
    return td;
  }

  function decisionKey(item) {
    return item.key;
  }

  /** Tick when the line exists on that side, a quiet dash when it does not. */
  function presenceCell(present, what) {
    const td = ns.pubTree.el('td', 'pub-cmp-presence');
    const mark = ns.pubTree.el('span', present ? 'pub-cmp-tick' : 'pub-cmp-none');
    if (present) mark.appendChild(svg('0 0 24 24', ['M5 12l5 5L20 7']));
    else mark.textContent = '–';
    mark.title = (present ? 'In ' : 'Not in ') + what;
    mark.setAttribute('aria-label', mark.title);
    td.appendChild(mark);
    return td;
  }

  /** Status chip. A differing pair has two rows: the design line ("fmRow" false) and the Fusion Manage line. */
  function statusCell(item, fmRow) {
    const t = ns.pubTree;
    const td = t.el('td', 'pub-cmp-status');
    let tone;
    let label;
    let text;
    if (item.status === 'mismatch') {
      const choice = decisions[decisionKey(item)];
      if (!fmRow) {   // the design line is always added
        tone = 'add'; label = 'Add';
        text = choice === 'remove' ? 'Publishing will add ' + item.design.pn + ' in place of ' + item.fm.pn
          : choice === 'add' ? 'Publishing will add ' + item.design.pn + ' and keep ' + item.fm.pn
          : 'Publishing will add ' + item.design.pn + '; choose what happens to ' + item.fm.pn;
      } else if (!choice) {
        tone = 'pair'; label = 'Review'; text = PAIR_ASK;
      } else if (choice === 'remove') {
        tone = 'removed'; label = 'Remove'; text = 'Publishing will remove ' + item.fm.pn + ' from Fusion Manage';
      } else {
        tone = 'extra'; label = 'Keep'; text = 'Publishing keeps ' + item.fm.pn + ' in Fusion Manage';
      }
    } else if (STATUS[item.status]) {
      tone = STATUS[item.status].tone;
      label = STATUS[item.status].label;
      text = STATUS[item.status].text;
    } else {
      return td;
    }
    const chip = t.el('span', 'pub-cmp-chip pub-cmp-chip-' + tone, label);
    chip.title = text;
    td.appendChild(chip);
    return td;
  }

  /** Quantity: the design's, or the Fusion Manage line's for a line only it has; a differing Fusion Manage quantity is shown beside it. */
  function quantityCell(item) {
    const t = ns.pubTree;
    const td = t.el('td', 'num pub-cmp-qty', item.status === 'extra' || item.status === 'kept' ? item.fm.quantity : item.design.quantity);
    if (item.status === 'changed') {
      td.classList.add('pub-cmp-qty-diff');
      td.appendChild(t.el('span', 'pub-cmp-qty-fm', ' (FM ' + item.fm.quantity + ')'));
    }
    return td;
  }

  /** Icon buttons on the Fusion Manage line of a differing pair: keep both lines, or remove this one. A kept line has them too, to undo the choice. */
  function actionCell(item, redraw) {
    const t = ns.pubTree;
    const td = t.el('td', 'pub-cmp-action');
    if (!item.key || item.status === 'added') return td;
    const key = decisionKey(item);
    const box = t.el('span', 'pub-cmp-actions');
    [['add', 'Keep both: add ' + item.design.pn + ' and keep ' + item.fm.pn, ['M5 12l5 5L20 7']],
     ['remove', 'Remove ' + item.fm.pn + ' from Fusion Manage and add ' + item.design.pn, ['M5 12h14']]].forEach(function (a) {
      const b = t.el('button', 'pub-cmp-act pub-cmp-act-' + a[0] + (decisions[key] === a[0] ? ' chosen' : ''));
      b.type = 'button';
      b.title = a[1];
      b.setAttribute('aria-label', a[1]);
      b.appendChild(svg('0 0 24 24', a[2]));
      b.addEventListener('click', function () {
        if (decisions[key] === a[0]) delete decisions[key]; else decisions[key] = a[0];
        redraw();
      });
      box.appendChild(b);
    });
    td.appendChild(box);
    return td;
  }

  /**
   * Rows to draw: the open design first, then each compared row. A Fusion Manage line that
   * sits beside a design line with another item number is folded into that design line's row.
   */
  function buildItems(rows, root) {
    const rootName = root.description || '';
    const rootPn = root.part_number || root.item_number || '';
    const items = [{ level: 0, root: true, sequence: '', status: 'root', hidden: false,
                     design: { pn: rootPn, name: rootName || (rootPn ? '' : 'This design'), quantity: '', sequence: '' },
                     fm: { pn: rootPn, name: rootName, quantity: '', sequence: '' } }];
    const repeats = {};
    let held = null;   // paired Fusion Manage line waiting for its design line, which follows it
    function side(r, quantity) {
      return { pn: r.part_number, name: r.name, quantity: String(quantity), sequence: String(r.sequence) };
    }
    rows.forEach(function (r) {
      if (r.status === 'extra' && r.pair) { held = r; return; }
      if (r.status === 'extra') {
        items.push({ level: r.level + 1, root: false, sequence: String(r.sequence), status: 'extra', hidden: false, design: side(r, ''), fm: side(r, r.quantity) });
        return;
      }
      const item = { level: r.level + 1, root: false, sequence: String(r.sequence), status: r.status || 'unchecked', hidden: !!r.hidden,
                     design: side(r, r.quantity), fm: side(r, r.status === 'match' ? r.quantity : r.fm_quantity || '') };
      if (held && held.pair === String(r.item_number || r.part_number)) {
        item.status = 'mismatch';
        item.fm = side(held, held.quantity);
        // Repeats of the same pair of numbers get their own choice: "design|Fusion Manage|n", n counting the repeats.
        const base = item.design.pn + '|' + item.fm.pn;
        repeats[base] = (repeats[base] || 0) + 1;
        item.key = base + '|' + repeats[base];
      }
      held = null;
      items.push(item);
    });
    return items;
  }

  /**
   * Apply the "keep both" choices: the design line stays where it is, and the Fusion Manage line it was
   * paired with is renumbered and moves to the end of the parent's lines.
   */
  function arrange(items) {
    const out = items.slice();
    for (let i = 0; i < out.length; i++) {
      const item = out[i];
      if (item.status !== 'mismatch' || decisions[item.key] !== 'add') continue;
      out[i] = Object.assign({}, item, { status: 'added' });
      let parent = i - 1;
      while (out[parent].level >= item.level) parent--;
      let last = parent + 1;
      while (last < out.length && out[last].level > out[parent].level) last++;
      let highest = 0;
      for (let k = parent + 1; k < last; k++) {
        if (out[k].level === item.level) highest = Math.max(highest, parseInt(out[k].sequence, 10) || 0);
      }
      const number = String(highest + 1);
      out.splice(last, 0, Object.assign({}, item, { status: 'kept', hidden: false, sequence: number, fm: Object.assign({}, item.fm, { sequence: number }) }));
    }
    return out;
  }

  /**
   * Draw the compare table into ``host``.
   * ``rows`` are the compared BOM rows (tree order, ``level`` 0 = child of the root);
   * ``root`` is the open design's summary.
   */
  function render(host, rows, root) {
    const t = ns.pubTree;
    const items = arrange(buildItems(rows, root));
    // Where each level's icon starts: every level steps in 32px, the width of a chevron slot, so a
    // chevron sits under its parent's icon and the steps look the same at every depth.
    const chevronLevels = {};
    items.forEach(function (item, i) { if (items[i + 1] && items[i + 1].level > item.level) chevronLevels[item.level] = true; });
    const iconX = [];
    items.forEach(function (item) {
      if (iconX[item.level] === undefined) {
        iconX[item.level] = item.level === 0 ? (chevronLevels[0] ? 32 : 0) : (iconX[item.level - 1] || 0) + 32;
      }
      item.iconX = iconX[item.level];
    });
    const view = t.el('div', 'pub-cmp-view');
    const bar = t.el('div', 'pub-cmp-filters');
    bar.setAttribute('role', 'group');
    bar.setAttribute('aria-label', 'Filter the Bill of Materials');
    const counts = {};
    items.forEach(function (item) { groupsOf(item).forEach(function (g) { counts[g] = (counts[g] || 0) + 1; }); });
    const filterButtons = {};
    FILTERS.forEach(function (f) {
      const b = t.el('button', 'pub-cmp-filter' + (f.right ? ' pub-cmp-filter-right' : ''), f.label);
      b.type = 'button';
      b.title = f.title;
      b.appendChild(t.el('span', 'pub-cmp-filter-count', String(counts[f.id] || 0)));
      b.addEventListener('click', function () {
        if (filters[f.id]) delete filters[f.id]; else filters[f.id] = true;
        paintFilters();
        apply();
      });
      filterButtons[f.id] = b;
      bar.appendChild(b);
    });
    function paintFilters() {
      FILTERS.forEach(function (f) {
        filterButtons[f.id].classList.toggle('on', !!filters[f.id]);
        filterButtons[f.id].setAttribute('aria-pressed', filters[f.id] ? 'true' : 'false');
      });
    }
    paintFilters();
    view.appendChild(bar);
    const wrap = t.el('div', 'pub-cmp-wrap');
    const table = t.el('table', 'pub-cmp');
    const cols = t.el('colgroup');
    ['', '64px', '64px', '84px', '116px', '64px'].forEach(function (w) {
      const col = t.el('col');
      if (w) col.style.width = w;
      cols.appendChild(col);
    });
    table.appendChild(cols);

    const head = t.el('tr');
    [['Item', ''], ['Fusion', 'pub-cmp-center'], ['Manage', 'pub-cmp-center'], ['Qty', 'num'], ['Status', 'pub-cmp-status'], ['Actions', 'pub-cmp-center']].forEach(function (h) {
      head.appendChild(t.el('th', h[1], h[0]));
    });
    table.appendChild(head);

    const collapsed = {};
    const trs = [];
    const fmTrs = [];   // per item: the Fusion Manage row of a differing pair, else null
    // Rows that pass the filters, plus the assemblies above them so a row keeps its place in the tree.
    function visibleByFilter() {
      const on = Object.keys(filters);
      if (!on.length) return null;
      const show = items.map(function (item) { return item.root || groupsOf(item).some(function (g) { return filters[g]; }); });
      let need = Infinity;   // level a row must be below to be the ancestor of a shown row further down
      for (let i = items.length - 1; i >= 0; i--) {
        if (show[i]) need = Math.min(need, items[i].level);
        else if (need !== Infinity && items[i].level < need) { show[i] = true; need = items[i].level; }
      }
      return show;
    }
    function apply() {   // hide rows under a collapsed assembly, and rows the filters leave out
      const show = visibleByFilter();
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
      render(host, rows, root);
    }

    items.forEach(function (item, i) {
      const tr = t.el('tr', 'pub-cmp-row pub-cmp-' + item.status + (item.root ? ' pub-tree-root' : '') + (item.hidden ? ' pub-cmp-is-hidden' : ''));
      const isAssembly = !!(items[i + 1] && items[i + 1].level > item.level);
      const toggle = chevronLevels[item.level] ? t.el('button', 'pub-tree-toggle') : null;
      if (toggle) toggle.type = 'button';
      if (isAssembly) {
        toggle.appendChild(t.chevron());
        toggle.setAttribute('aria-label', 'Collapse or expand');
        toggle.addEventListener('click', function () {
          collapsed[i] = !collapsed[i];
          t.setChevron(toggle.firstChild, collapsed[i]);
          apply();
        });
      } else if (toggle) {
        toggle.disabled = true;
      }

      // A line only Fusion Manage has is drawn from its own side; every other row from the design's.
      const fmOnly = item.status === 'extra' || item.status === 'kept';   // drawn from the Fusion Manage line
      const cell = itemCell(fmOnly ? item.fm : item.design, item, isAssembly, toggle);
      tr.appendChild(cell);
      tr.appendChild(presenceCell(!fmOnly, 'the design'));
      tr.appendChild(presenceCell(item.status !== 'new' && item.status !== 'mismatch' && item.status !== 'added', 'Fusion Manage'));
      tr.appendChild(quantityCell(item));
      tr.appendChild(statusCell(item, false));
      tr.appendChild(item.status === 'kept' ? actionCell(item, redraw) : t.el('td', 'pub-cmp-action'));
      table.appendChild(tr);
      trs.push(tr);
      fmTrs.push(null);
      if (item.status === 'mismatch') {   // the Fusion Manage line at this position gets its own row
        const removing = decisions[decisionKey(item)] === 'remove';
        const fmTr = t.el('tr', 'pub-cmp-row pub-cmp-fmline' + (removing ? ' pub-cmp-removing' : ''));
        const fmCell = itemCell(item.fm, Object.assign({}, item, { hidden: false }), false, chevronLevels[item.level] ? Object.assign(t.el('button', 'pub-tree-toggle'), { type: 'button', disabled: true }) : null);
        fmCell.querySelector('.pub-tree-pn').classList.add('pub-cmp-diff');
        fmTr.appendChild(fmCell);
        fmTr.appendChild(presenceCell(false, 'the design'));
        fmTr.appendChild(presenceCell(true, 'Fusion Manage'));
        fmTr.appendChild(t.el('td', 'num pub-cmp-qty', item.fm.quantity));
        fmTr.appendChild(statusCell(item, true));
        fmTr.appendChild(actionCell(item, redraw));   // the buttons sit on the line that is not in the design
        table.appendChild(fmTr);
        fmTrs[fmTrs.length - 1] = fmTr;
      }
    });

    wrap.appendChild(table);
    view.appendChild(wrap);
    host.appendChild(view);
    apply();
  }

  ns.bomSplit = { render: render, decisions: decisions };
})(window.MfgUi);
