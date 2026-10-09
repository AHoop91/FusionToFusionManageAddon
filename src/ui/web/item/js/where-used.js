/**
 * The Where Used tab: the assemblies that hold the item, as a tree. Each parent has a chevron that reads the
 * level above it the first time it is opened. Python does the reading; this page polls for each answer.
 */
(function (ns) {
  'use strict';

  const el = ns.el;
  const tree = ns.itemTree;
  const ITEM_COLUMN_PX = 380;
  const COLUMN_PX = 120;
  const DEFAULT_COLUMNS = ['QUANTITY', 'UNITS', 'LIFECYCLE'];
  // An assembly: a parent box over two parts, joined by lines. Static markup.
  const ASSEMBLY_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8.5" y="3" width="7" height="5" rx="1"/><rect x="2.5" y="16" width="7" height="5" rx="1"/><rect x="14.5" y="16" width="7" height="5" rx="1"/><path d="M12 8v4M6 16v-4h12v4"/></svg>';
  const CLASS = 'item-where-used';

  let current = 0;   // the tab being drawn; an answer for an older item is ignored

  /** Read one level: ``up`` is the link of an earlier answer, or empty for the item itself. */
  function load(view, up, done) {
    tree.load('where_used_load', 'where_used_result', { workspace_id: view.workspace_id, item_id: view.item_id, up: up }, done);
  }

  function titleOf(key) { return key.charAt(0) + key.slice(1).toLowerCase(); }   // QUANTITY -> Quantity

  /** Fill ``target`` with the parents of the item of ``view``; ``onCount(n)`` gets how many there are. */
  function render(target, view, onCount) {
    const mine = ++current;
    onCount(null);
    tree.loading(target, CLASS, 'Reading where this item is used...');
    load(view, '', function (error, result) {
      if (mine !== current) return;
      if (error) { tree.centred(target, CLASS, 'Could not read where this item is used: ' + error, true); return; }
      onCount(result.rows.length);
      draw(target, view, result);
    });
  }

  function draw(target, view, top) {
    target.className = 'view-scroll ' + CLASS;
    // grows when a deeper level has a field the first did not; with no parents the usual columns still show
    const columns = top.rows.length ? top.columns.slice() : DEFAULT_COLUMNS.slice();
    const roots = top.rows.map(function (row) { return makeNode(row); });
    const table = el('table', 'item-files-table item-tree-table');
    const colgroup = el('colgroup');
    const head = el('tr');
    const body = el('tbody');
    table.append(colgroup, el('thead'), body);
    table.tHead.appendChild(head);

    function makeNode(row) { return { row: row, open: false, loading: false, error: '', children: null }; }

    function drawHead() {
      colgroup.replaceChildren();
      head.replaceChildren();
      const cols = [];
      const heads = [];
      const titles = ['Item', 'Version'].concat(columns.map(titleOf));
      titles.forEach(function (title, i) {
        const col = el('col');
        col.style.width = (i === 0 ? ITEM_COLUMN_PX : COLUMN_PX) + 'px';
        colgroup.appendChild(col);
        const th = el('th', '', title);
        head.appendChild(th);
        cols.push(col);
        heads.push(th);
      });
      tree.resizable(table, cols, heads, COLUMN_PX);
    }

    function toggle(node) {
      node.open = !node.open;
      if (node.open && !node.children && !node.loading) {
        node.loading = true;
        node.error = '';
        load(view, node.row.up, function (error, result) {
          node.loading = false;
          if (!table.isConnected) return;
          if (error) { node.error = error; node.open = false; }
          else {
            result.columns.forEach(function (c) { if (columns.indexOf(c) < 0) columns.push(c); });
            node.children = result.rows.map(function (row) { return makeNode(row); });
            if (!node.children.length) node.row.up = '';   // nothing above it after all: no chevron
            drawHead();
          }
          drawRows();
        });
      }
      drawRows();
    }

    function rowsOf(nodes, depth, out, prefix) {   // ``prefix`` is the parent's number, so a child is 1.1, 1.2 ...
      nodes.forEach(function (node, i) {
        const number = prefix + (i + 1);
        out.push({ node: node, depth: depth, number: number });
        if (node.open && node.children) rowsOf(node.children, depth + 1, out, number + '.');
      });
      return out;
    }

    function drawRows() {
      body.replaceChildren();
      const entries = rowsOf(roots, 0, [], '');
      const chevronDepths = {};   // a level only leaves room for a chevron when one of its rows has one
      entries.forEach(function (entry) { if (entry.node.row.up) chevronDepths[entry.depth] = true; });
      const xs = tree.iconXs(entries, chevronDepths);
      entries.forEach(function (entry) {
        const node = entry.node;
        const row = node.row;
        const tr = el('tr');
        tr.appendChild(tree.itemCell({
          iconX: xs[entry.depth], number: entry.number, row: row, kind: 'assembly', room: chevronDepths[entry.depth],
          chevron: row.up ? { open: node.open, title: node.open ? 'Collapse' : 'Show where this is used', onClick: function () { toggle(node); } } : null,
          loading: node.loading, error: node.error,
        }));
        tr.appendChild(el('td', '', row.version));
        columns.forEach(function (c) { tr.appendChild(el('td', '', row.fields[c] || '')); });
        body.appendChild(tr);
      });
    }

    drawHead();
    drawRows();
    const wrap = el('div', 'item-files-wrap');
    wrap.appendChild(table);
    target.replaceChildren(wrap);
    if (!roots.length) {   // the columns stay, and the message is centred in the space under them
      target.classList.add('item-files-stack');
      const empty = el('div', 'item-files-empty');
      empty.classList.add('item-centred');
      const icon = el('span', 'item-empty-icon item-empty-icon-large');
      icon.innerHTML = ASSEMBLY_ICON;
      empty.append(icon, el('p', 'item-empty-text', 'Not used in any assembly'),
                   el('p', 'item-empty-hint', 'Assemblies in Fusion Manage that hold this item will be listed here.'));
      target.appendChild(empty);
    }
  }

  ns.itemWhereUsed = { render: render };
})(window.MfgUi);
