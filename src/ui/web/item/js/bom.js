/**
 * The Bill of Materials tab: the item's lines as a tree. The columns are the ones Fusion Manage's own BOM view
 * of the workspace has; Python reads the whole tree in one go, so a chevron only opens or closes what is here.
 */
(function (ns) {
  'use strict';

  const el = ns.el;
  const bridge = ns.bridge;
  const tree = ns.itemTree;
  const ITEM_COLUMN_PX = 380;
  const COLUMN_PX = 120;
  const ICON_COLUMN_PX = 48;   // a column that only holds an icon
  const EMPTY_COLUMNS = ['Version', 'Quantity', 'Lifecycle'];   // shown under no lines, where the real columns are not known
  const CLASS = 'item-bom';
  // A bill of materials: a list of lines. Static markup.
  const LIST_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/></svg>';

  // Icon columns: a paperclip with how many files, a green stamp for a change in progress, a red pin for a pinned revision. Static markup.
  const ICONS = {
    attachments: '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M7 8v8a5 5 0 0 0 10 0V6a3.5 3.5 0 0 0-7 0v9.5a2 2 0 0 0 4 0V8"/></svg>',   // upright
    change: '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M12 3a3 3 0 0 0-2 5.2V12h4V8.2A3 3 0 0 0 12 3z"/><path d="M5 12h14a1 1 0 0 1 1 1v3H4v-3a1 1 0 0 1 1-1z"/><path d="M4 20h16"/></svg>',
    pin: '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><g transform="rotate(35 12 12)"><path d="M9 3h6l-1 6 3 3v2H7v-2l3-3z"/><path d="M12 14v7"/></g></svg>',   // slanted, filled red
  };
  const HEAD_KIND = { ATTACHMENTS: 'attachments', WORKING_CHANGE_ORDER: 'change', PIN: 'pin' };   // field id -> icon
  const TIPS = { attachments: 'Open the files of this item in Fusion Manage in your browser', change: 'Open the change in Fusion Manage in your browser', pin: 'The revision of this item is pinned' };

  // The bar's icons. Static markup.
  const BAR_ICONS = {
    nested: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="9" height="5" rx="1"/><rect x="12" y="10" width="9" height="4" rx="1"/><rect x="12" y="17" width="9" height="4" rx="1"/><path d="M6 8v11M6 12h6M6 19h6"/></svg>',
    collapse: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 12h8"/></svg>',
    expand: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 12h8M12 8v8"/></svg>',
    flat: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/></svg>',
    columns: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill-rule="evenodd" d="M9.91 4.69L10.52 1.50L13.48 1.50L14.09 4.69L15.68 5.35L18.38 3.53L20.47 5.62L18.65 8.32L19.31 9.91L22.50 10.52L22.50 13.48L19.31 14.09L18.65 15.68L20.47 18.38L18.38 20.47L15.68 18.65L14.09 19.31L13.48 22.50L10.52 22.50L9.91 19.31L8.32 18.65L5.62 20.47L3.53 18.38L5.35 15.68L4.69 14.09L1.50 13.48L1.50 10.52L4.69 9.91L5.35 8.32L3.53 5.62L5.62 3.53L8.32 5.35zM12 8.8a3.2 3.2 0 1 0 0 6.4 3.2 3.2 0 1 0 0-6.4z"/></svg>',
  };

  let current = 0;   // the tab being drawn; an answer for an older item is ignored
  let flat = false;   // every component in one list, instead of the tree
  const chosen = {};   // workspace id -> the view the user picked
  let menuOpen = false;   // the column menu is showing; it survives the table being drawn again
  document.addEventListener('click', function () {   // a click anywhere else closes it
    menuOpen = false;
    document.querySelectorAll('.item-bom-menu').forEach(function (m) { m.remove(); });
  });
  const hidden = {};   // column id -> true when the user turned it off

  /** Fill ``target`` with the bill of materials of the item of ``view``; ``onCount(n)`` gets how many lines are at its top. */
  function render(target, view, onCount) {
    const mine = ++current;
    onCount(null);
    function read(first) {
      if (!first) { tree.loading(target, CLASS, 'Reading the Bill of Materials...'); }
      tree.load('bom_load', 'bom_result', { workspace_id: view.workspace_id, item_id: view.item_id, view_id: chosen[view.workspace_id] || '', flat: flat }, function (error, result) {
        if (mine !== current) return;
        if (error) { tree.centred(target, CLASS, 'Could not read the Bill of Materials: ' + error, true); return; }
        onCount(result.rows.length ? result.rows[0].children.length : 0);   // the lines under the item
        draw(target, result, function (id) { if (id) chosen[view.workspace_id] = id; read(false); }, view);
      });
    }
    tree.loading(target, CLASS, 'Reading the Bill of Materials...');
    read(true);
  }

  function tool(kind, title) {
    const b = el('button', 'item-bom-tool item-bom-' + kind);
    b.type = 'button';
    b.title = title;
    b.innerHTML = BAR_ICONS[kind];   // static markup
    return b;
  }

  /** The bar: the views of the workspace, nested or flat, and which columns show. */
  function bar(bom, view, onView, redraw, onOpenAll) {
    const row = el('div', 'item-bom-bar');
    const fold = el('div', 'item-bom-pair');
    const close = tool('collapse', 'Collapse all');
    const open = tool('expand', 'Expand all');
    close.disabled = open.disabled = flat;   // a flat list has nothing to fold
    close.addEventListener('click', function () { onOpenAll(false); });
    open.addEventListener('click', function () { onOpenAll(true); });
    close.classList.add('item-bom-solid');
    open.classList.add('item-bom-solid');
    fold.append(close, open);
    fold.style.marginRight = 'auto';
    row.appendChild(fold);
    row.appendChild(el('label', '', 'Views:'));
    const select = el('select');
    select.setAttribute('aria-label', 'Views');
    (bom.views || []).forEach(function (v) {
      const option = el('option', '', v.name);
      option.value = v.id;
      option.selected = v.id === bom.view;
      select.appendChild(option);
    });
    select.disabled = !(bom.views || []).length;
    select.addEventListener('change', function () { onView(select.value); });
    row.appendChild(select);

    const pair = el('div', 'item-bom-pair');
    const nested = tool('nested', 'Nested: each assembly holds its lines');
    const plain = tool('flat', 'Flat: every component in one list');
    (flat ? plain : nested).classList.add('item-bom-on');
    nested.addEventListener('click', function () { if (flat) { flat = false; onView(''); } });
    plain.addEventListener('click', function () { if (!flat) { flat = true; onView(''); } });
    pair.append(nested, plain);
    row.appendChild(pair);


    const host = el('div', 'item-bom-menu-host');
    const gear = tool('columns', 'Choose the columns');
    host.appendChild(gear);
    function openMenu() {
      const menu = el('div', 'item-bom-menu');
      menu.addEventListener('click', function (e) { e.stopPropagation(); });   // a click inside leaves it open
      (bom.columns || []).forEach(function (c) {
        const label = el('label');
        const box = el('input');
        box.type = 'checkbox';
        box.checked = !hidden[c.id];
        box.addEventListener('change', function () { if (box.checked) delete hidden[c.id]; else hidden[c.id] = true; menuOpen = true; redraw(); });   // the table is drawn again, and the menu with it
        label.append(box, el('span', '', c.title));
        menu.appendChild(label);
      });
      host.appendChild(menu);
    }
    gear.addEventListener('click', function (event) {
      event.stopPropagation();
      const open = host.querySelector('.item-bom-menu');
      if (open) { open.remove(); menuOpen = false; return; }
      menuOpen = true;
      openMenu();
    });
    if (menuOpen) openMenu();
    row.appendChild(host);
    return row;
  }

  /** An icon column: nothing when it has no value; a link when the cell has an address. */
  function icon(td, cell) {
    if (!cell.value) return;
    const mark = cell.url ? el('a', 'item-bom-icon item-bom-' + cell.kind) : el('span', 'item-bom-icon item-bom-' + cell.kind);
    mark.title = TIPS[cell.kind] + (cell.kind === 'attachments' ? ' (' + cell.value + ')' : '');
    mark.innerHTML = ICONS[cell.kind];   // static markup
    if (cell.kind === 'attachments') mark.appendChild(el('span', 'item-bom-count', cell.value));
    if (cell.url) {
      mark.href = '#';
      mark.addEventListener('click', function (event) { event.preventDefault(); bridge.send('open_url', { url: cell.url }); });
    }
    td.appendChild(mark);
  }

  function fill(td, cell) {
    if (cell && ICONS[cell.kind]) icon(td, cell);
    else if (cell && cell.kind === 'html') ns.safeHtml.render(td, cell.value);
    else if (cell) td.textContent = cell.value;
  }

  function draw(target, full, onView, view) {
    target.className = 'view-scroll ' + CLASS;
    const bom = { rows: full.rows, views: full.views, view: full.view, columns: full.columns.filter(function (c) { return !hidden[c.id]; }) };
    const columns = bom.rows.length ? bom.columns : EMPTY_COLUMNS.map(function (title) { return { title: title, icon: false }; });
    const table = el('table', 'item-files-table item-tree-table');
    const colgroup = el('colgroup');
    const head = el('tr');
    const body = el('tbody');
    table.append(colgroup, el('thead'), body);
    table.tHead.appendChild(head);
    const cols = [];
    const heads = [];
    [{ title: 'Item', icon: false }].concat(columns).forEach(function (c, i) {
      const col = el('col');
      const width = i === 0 ? ITEM_COLUMN_PX : c.icon ? ICON_COLUMN_PX : COLUMN_PX;
      col.style.width = width + 'px';
      cols.push(col);
      colgroup.appendChild(col);
      const th = el('th', c.icon ? 'item-bom-icon-head' : '', c.icon ? '' : c.title);
      if (c.icon) {   // headed by its icon; hovering says what it is
        th.title = c.title;
        const mark = el('span', 'item-bom-head-icon item-bom-' + HEAD_KIND[c.icon]);
        mark.innerHTML = ICONS[HEAD_KIND[c.icon]];   // static markup
        th.appendChild(mark);
      }
      heads.push(th);
      head.appendChild(th);
    });
    tree.resizable(table, cols, heads, COLUMN_PX);

    function makeNode(row) { return { row: row, open: false, children: row.children.map(makeNode) }; }
    const roots = bom.rows.map(makeNode);
    roots.forEach(function (node) { if (node.row.root) node.open = true; });   // the item's own lines show at once

    function rowsOf(nodes, depth, out) {
      nodes.forEach(function (node, i) {
        const number = node.row.root ? '' : String(i + 1);   // the item itself has no number; the lines of each assembly start again at 1
        out.push({ node: node, depth: depth, number: number });
        if (node.open) rowsOf(node.children, depth + 1, out);
      });
      return out;
    }

    function drawRows() {
      body.replaceChildren();
      const entries = rowsOf(roots, 0, []);
      const chevronDepths = {};   // a level only leaves room for a chevron when one of its rows has one
      entries.forEach(function (entry) { if (entry.node.children.length) chevronDepths[entry.depth] = true; });
      const xs = tree.iconXs(entries, chevronDepths);
      entries.forEach(function (entry) {
        const node = entry.node;
        const tr = el('tr');
        tr.appendChild(tree.itemCell({
          quiet: true, iconX: xs[entry.depth], number: entry.number, row: node.row, kind: node.row.root ? 'root' : node.children.length ? 'assembly' : 'part', room: chevronDepths[entry.depth],
          chevron: node.children.length ? {
            open: node.open, title: node.open ? 'Collapse' : 'Expand',
            onClick: function () { node.open = !node.open; drawRows(); },
          } : null,
        }));
        bom.columns.forEach(function (c) {
          const td = el('td', c.icon ? 'item-bom-icon-cell' : '');
          fill(td, node.row.cells[c.id]);
          tr.appendChild(td);
        });
        body.appendChild(tr);
      });
    }

    function setAll(open) {   // every assembly open or closed; the item's own lines stay shown
      (function walk(nodes) { nodes.forEach(function (node) { node.open = open || !!node.row.root; walk(node.children); }); })(roots);
      drawRows();
    }

    drawRows();
    const wrap = el('div', 'item-files-wrap');
    wrap.appendChild(table);
    target.replaceChildren(bar(full, view, onView, function () { draw(target, full, onView, view); }, setAll), wrap);
    if (!bom.rows.length || !bom.rows[0].children.length) {   // the columns stay, and the message is centred in the space under them
      target.classList.add('item-files-stack');
      const empty = el('div', 'item-files-empty');
      empty.classList.add('item-centred');
      const icon = el('span', 'item-empty-icon item-empty-icon-large');
      icon.innerHTML = LIST_ICON;
      empty.append(icon, el('p', 'item-empty-text', 'No Bill of Materials'),
                   el('p', 'item-empty-hint', 'Items that make up this item in Fusion Manage will be listed here.'));
      target.appendChild(empty);
    }
  }

  ns.itemBom = { render: render };
})(window.MfgUi);
