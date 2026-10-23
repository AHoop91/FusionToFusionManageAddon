/**
 * Publish Item panel: Bill of Materials table, as ``ns.bomTable``. One table lists the design BOM with Fusion and Fusion Manage columns
 * that tick where each line exists, then the quantity, with a Filters drop-down and collapse / expand buttons above it.
 *
 * The lines come from bom-model.js, their cells from bom-cells.js, the filters from bom-filters.js and the columns from
 * bom-columns.js. Only the first level is read at first (see bom-tree.js): an assembly whose lines are not read shows a chevron, and
 * opening it asks the caller (``lazy``) to read them, with grey rows under it meanwhile. Clicking a row hands its component to the
 * caller, which shows the details.
 */
(function (ns) {
  'use strict';

  const ui = ns.pubUi;
  const el = ui.el;
  const model = ns.bomModel;
  const cells = ns.bomCells;
  const filters = ns.bomFilters;
  const columns = ns.bomColumns;
  const decisions = model.decisions;
  const SLOT = cells.SLOT;

  let selectedId = null;   // component whose details are open, so its rows stay highlighted across redraws
  let seenStaged = new Set();   // picked lines already drawn, so only a new one animates in
  let current = null;      // { items, trs, redraw } of the table on screen
  let opened = new Set();  // fold keys of the assemblies that are open (see ``render``)
  let openAllNext = false; // open every assembly in the next table drawn
  let scrolled = { top: 0, left: 0 };   // where the table was scrolled to, so a redraw (an assembly read, an edit) leaves it there

  // ---- Selection -----------------------------------------------------------------

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

  // ---- Pieces of the table -------------------------------------------------------

  /** Set ``item.iconX`` (where each icon starts): every level steps in by one slot, so a chevron sits under its parent's icon. */
  function layOut(items, chevronLevels) {
    const iconX = ns.stepIn(items.map(function (item) { return item.level; }), chevronLevels[0], SLOT);
    items.forEach(function (item) { item.iconX = iconX[item.level]; });
  }

  // The icons of the Item panel's Bill of Materials bar: a solid box with a minus (collapse all) or a plus (expand all).
  const FOLD_ICONS = {
    collapse: ['M8 12h8'],
    expand: ['M8 12h8', 'M12 8v8'],
  };

  function foldTool(kind, title, onClick) {
    const b = el('button', 'pub-cmp-tool pub-cmp-tool-' + kind);
    b.type = 'button';
    b.title = title;
    b.setAttribute('aria-label', title);
    const icon = ui.svg(FOLD_ICONS[kind]);
    const box = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    [['x', 4], ['y', 4], ['width', 16], ['height', 16], ['rx', 2]].forEach(function (a) { box.setAttribute(a[0], String(a[1])); });
    icon.insertBefore(box, icon.firstChild);
    b.appendChild(icon);
    b.addEventListener('click', onClick);
    return b;
  }

  /** Collapse all and expand all, as a pair. ``busy``: the rest of the tree is on its way, so there is nothing to fold yet. */
  function foldTools(collapseAll, expandAll, busy, busyText) {
    const pair = el('div', 'pub-cmp-pair');
    const collapse = foldTool('collapse', 'Collapse all', collapseAll);
    const expand = foldTool('expand', 'Expand all', expandAll);
    if (busy) {
      collapse.disabled = expand.disabled = true;
      expand.classList.add('pub-cmp-tool-busy');   // the button itself spins; how far it is goes in its tooltip
      expand.title = busyText;
      expand.setAttribute('aria-label', busyText);
    }
    pair.appendChild(collapse);
    pair.appendChild(expand);
    return pair;
  }

  /** Rows of grey bars under an assembly while its lines are read. */
  function skeletonRows(item) {
    return [68, 52, 60].map(function (width) {
      const tr = el('tr', 'pub-cmp-row pub-skel-tr');
      tr.setAttribute('aria-hidden', 'true');
      const td = el('td');
      td.colSpan = 4;
      const line = el('div', 'pub-skel-line');
      line.style.paddingLeft = (item.iconX + SLOT) + 'px';
      line.appendChild(el('span', 'pub-skel pub-skel-icon'));
      const bar = el('span', 'pub-skel');
      bar.style.width = width + '%';
      line.appendChild(bar);
      td.appendChild(line);
      tr.appendChild(td);
      return tr;
    });
  }

  /** The row under an assembly whose lines could not be read, with a button to try again. */
  function failureRow(item, message, retry) {
    const tr = el('tr', 'pub-cmp-row pub-cmp-fail');
    const td = el('td');
    td.colSpan = 4;
    const line = el('div', 'pub-cmp-fail-line');
    line.style.paddingLeft = (item.iconX + SLOT) + 'px';
    line.appendChild(el('span', 'pub-cmp-fail-text', 'Could not read this level: ' + message));
    const again = el('button', 'pub-cmp-fail-retry', 'Retry');
    again.type = 'button';
    again.addEventListener('click', retry);
    line.appendChild(again);
    td.appendChild(line);
    tr.appendChild(td);
    return tr;
  }

  // ---- The table -----------------------------------------------------------------

  /**
   * Draw the compare table into ``host``.
   * ``rows`` are the compared BOM rows read so far (tree order, ``level`` 0 = child of the root); ``root`` is the open design's summary;
   * ``onSelect(component)`` is called when a row is clicked; ``onReview(pending)`` is called after each draw with the number of lines
   * still waiting for a choice. A table drawn afresh starts with only the first level showing (``keepFolds`` false); a redraw keeps the
   * assemblies open or closed as they are. ``lazy`` is what the table asks of the caller for lines that are not read yet:
   * ``loaded(id)``, ``loading(id)``, ``failed(id)``, ``load(item)``, ``expandAll()``, ``incomplete()``, ``busy()``, ``busyText()`` (what the spinning Expand all button says) and ``folded()`` (an assembly was opened or closed).
   */
  function render(host, rows, root, onSelect, onReview, keepFolds, lazy) {
    const items = model.arrange(model.buildItems(rows, root));
    // An assembly is a line with lines under it, or one that says it has some that are not read yet.
    const isAssembly = function (i) { return !!(items[i].assembly || (items[i + 1] && items[i + 1].level > items[i].level)); };
    const chevronLevels = {};
    items.forEach(function (item, i) { if (isAssembly(i)) chevronLevels[item.level] = true; });
    layOut(items, chevronLevels);

    // ---- Folds: which assemblies are open
    const foldKey = function (i) { return items[i].component && items[i].component.id ? items[i].component.id : items[i].lineId || 'row|' + i; };
    const lineOf = function (i) { return items[i].lineId || ''; };   // id of the component a line stands for
    const unread = function (i) { return !!(lazy && items[i].assembly && lineOf(i) && !lazy.loaded(lineOf(i))); };   // its lines are not read yet
    const openAssemblies = function () { items.forEach(function (_, i) { if (isAssembly(i)) opened.add(foldKey(i)); }); };
    if (!keepFolds) {
      // The design itself is open (its first level is what is shown), and so are the assemblies above a line that still waits for a
      // choice, so that line is not out of sight.
      opened = new Set([foldKey(0)]);
      const above = [];   // index of the latest line on each level
      items.forEach(function (item, i) {
        above[item.level] = i;
        if (item.status === 'mismatch' && !decisions[item.key]) for (let l = 0; l < item.level; l++) opened.add(foldKey(above[l]));
      });
    }
    if (openAllNext) {   // the rest of the tree has just been read for Expand all
      openAllNext = false;
      openAssemblies();
    }
    const collapsed = {};
    function applyFolds() {   // an assembly is collapsed unless it is open
      items.forEach(function (_, i) { collapsed[i] = isAssembly(i) && !opened.has(foldKey(i)); });
    }

    // ---- Rows, and what shows
    const trs = [];       // per item: its row
    const fmTrs = [];     // per item: the Fusion Manage row of a differing pair, else null
    const toggles = [];   // per item: its chevron, or null
    const spinning = [];  // per item: true while its lines are being read (its chevron is a spinner)
    const underTrs = [];  // per item: the rows drawn under it while its lines are read (skeleton rows, or the failure and its retry), else null
    function apply() {   // hide rows under a collapsed assembly, and rows the filters leave out
      const show = filters.visible(items);
      const narrowing = filters.narrowing();   // a filter shows its lines wherever they sit
      let hideBelow = null;
      trs.forEach(function (tr, i) {
        const level = items[i].level;
        let hide = show ? !show[i] : false;
        if (!narrowing) {
          if (hideBelow !== null && level > hideBelow) hide = true; else hideBelow = null;
          if (hideBelow === null && collapsed[i]) hideBelow = level;
        }
        tr.hidden = hide;
        if (fmTrs[i]) fmTrs[i].hidden = hide;
        if (underTrs[i]) underTrs[i].forEach(function (under) { under.hidden = hide || collapsed[i]; });
        if (toggles[i] && isAssembly(i) && !spinning[i]) ui.setChevron(toggles[i].firstChild, collapsed[i]);
      });
    }
    function folded() { if (lazy && lazy.folded) lazy.folded(); }   // what is in view changed: so did what publishing covers
    function foldAll(open) {
      opened = new Set([foldKey(0)]);   // Collapse all leaves the design open, so its first level stays in view
      if (open) openAssemblies();
      applyFolds();
      apply();
      folded();
    }
    function redraw() {
      host.removeChild(view);
      render(host, rows, root, onSelect, onReview, true, lazy);
    }

    /** The chevron of an assembly's row: opens or closes it, reading its lines first when they are not read yet. */
    function chevron(i) {
      const toggle = el('button', 'pub-tree-toggle');
      toggle.type = 'button';
      if (!isAssembly(i)) {
        toggle.disabled = true;
        return toggle;
      }
      const reading = unread(i) && opened.has(foldKey(i)) && lazy.loading(lineOf(i));   // opened, and its lines are on their way
      spinning[i] = reading;
      toggle.appendChild(reading ? el('span', 'pub-spin') : ui.chevron());
      toggle.setAttribute('aria-label', reading ? 'Reading the lines of this assembly' : 'Collapse or expand');
      toggle.disabled = reading;
      toggle.addEventListener('click', function () {
        const key = foldKey(i);
        if (opened.has(key)) {
          opened.delete(key);
        } else {
          opened.add(key);
          if (unread(i) && !lazy.loading(lineOf(i))) { lazy.load(items[i]); return; }   // it draws the table again with the spinner
        }
        applyFolds();
        apply();
        folded();
      });
      return toggle;
    }

    /** The row of a line. A line only Fusion Manage has is drawn from its own side; every other row from the design's. */
    function lineRow(item, i, toggle) {
      const fresh = item.stagedId !== undefined && !seenBefore.has(item.stagedId);   // picked since the last draw
      const tr = el('tr', 'pub-cmp-row pub-cmp-' + model.statusOf(item) + (item.hidden ? ' pub-cmp-is-hidden' : '') + (fresh ? ' pub-cmp-fresh' : ''));
      const fmOnly = cells.fromFm(item);
      if (item.status === 'extra' && decisions[item.key] === 'remove') tr.classList.add('pub-cmp-removing');
      tr.appendChild(cells.itemCell(fmOnly ? item.fm : item.design, item, isAssembly(i), toggle, cells.rowActions(item, redraw), cells.statusChip(item, false)));
      tr.appendChild(cells.presenceCell(!fmOnly, 'the design'));
      tr.appendChild(cells.presenceCell(!['new', 'mismatch', 'added', 'linked', 'uncompared', 'skipped'].includes(item.status), 'Fusion Manage'));
      tr.appendChild(cells.quantityCell(item, redraw));
      if (item.component && (item.root || item.component.id !== '')) {
        tr.classList.add('pub-cmp-pick');
        tr.addEventListener('click', function (event) {
          if (event.target.closest('button')) return;   // chevrons and action buttons do their own thing
          selectedId = selectionKey(item.component);
          paintSelection();
          onSelect(item.component);
        });
      }
      return tr;
    }

    /** The Fusion Manage line at the position of a differing pair gets its own row, with the buttons that choose what happens to it. */
    function pairRow(item) {
      const tr = el('tr', 'pub-cmp-row pub-cmp-fmline' + (decisions[item.key] === 'remove' ? ' pub-cmp-removing' : ''));
      const spacer = chevronLevels[item.level] ? Object.assign(el('button', 'pub-tree-toggle'), { type: 'button', disabled: true }) : null;
      const cell = cells.itemCell(item.fm, Object.assign({}, item, { hidden: false }), false, spacer, cells.pairActions(item, redraw), cells.statusChip(item, true));
      cell.querySelector('.pub-tree-pn').classList.add('pub-cmp-diff');
      tr.appendChild(cell);
      tr.appendChild(cells.presenceCell(false, 'the design'));
      tr.appendChild(cells.presenceCell(true, 'Fusion Manage'));
      tr.appendChild(el('td', 'num pub-cmp-qty', item.fm.quantity));
      return tr;
    }

    /** What stands under an opened assembly whose lines are not read: grey rows while they are on their way, or what went wrong. */
    function underRows(item, i) {
      const failure = lazy.failed(lineOf(i));
      return failure ? [failureRow(item, failure, function () { lazy.load(item); })] : skeletonRows(item);
    }

    // ---- Build
    applyFolds();
    const view = el('div', 'pub-cmp-view');
    const busy = !!(lazy && lazy.busy());   // the rest of the tree is being read, for Expand all or for publishing
    const bar = el('div', 'pub-cmp-filters');
    bar.setAttribute('role', 'group');
    bar.setAttribute('aria-label', 'Filter the Bill of Materials');
    bar.appendChild(filters.menu(items, apply, lazy && lazy.incomplete() ? 'Counts cover the levels read so far. Expand all reads the rest.' : ''));   // the counts only know what has been read
    bar.appendChild(foldTools(function () { foldAll(false); }, function () {
      if (lazy && lazy.incomplete()) lazy.expandAll(); else foldAll(true);
    }, busy, busy ? lazy.busyText() : ''));
    view.appendChild(bar);
    const table = el('table', 'pub-cmp');
    columns.head(table).forEach(function (node) { table.appendChild(node); });

    const seenBefore = seenStaged;
    seenStaged = new Set(items.filter(function (item) { return item.stagedId !== undefined; }).map(function (item) { return item.stagedId; }));
    items.forEach(function (item, i) {
      const toggle = chevronLevels[item.level] ? chevron(i) : null;
      spinning[i] = !!spinning[i];
      toggles.push(toggle);
      const tr = lineRow(item, i, toggle);
      table.appendChild(tr);
      trs.push(tr);
      fmTrs.push(null);
      underTrs.push(null);
      if (item.status === 'mismatch') {
        fmTrs[i] = pairRow(item);
        table.appendChild(fmTrs[i]);
      }
      if (isAssembly(i) && unread(i) && opened.has(foldKey(i))) {
        underTrs[i] = underRows(item, i);
        underTrs[i].forEach(function (under) { table.appendChild(under); });
      }
    });

    const wrap = el('div', 'pub-cmp-wrap');
    wrap.addEventListener('scroll', function () { scrolled = { top: wrap.scrollTop, left: wrap.scrollLeft }; });
    wrap.appendChild(table);
    view.appendChild(wrap);
    host.appendChild(view);
    current = { items: items, trs: trs, redraw: redraw };
    paintSelection();
    apply();
    // A table drawn afresh starts at the top; a redraw keeps its place (set once the folds have settled the height).
    if (keepFolds) { wrap.scrollTop = scrolled.top; wrap.scrollLeft = scrolled.left; } else scrolled = { top: 0, left: 0 };
    if (onReview) onReview(model.pendingReviews(items));
  }

  columns.onLayoutChange(function () { if (current && current.redraw) current.redraw(); });

  ns.bomTable = {
    render: render, select: select,
    /** The next table drawn opens every assembly (the rest of the tree has just been read for Expand all). */
    openAllOnNextDraw: function () { openAllNext = true; },
    /** Is the assembly with this component id open? */
    isOpen: function (id) { return opened.has(id); },
  };
})(window.MfgUi);
