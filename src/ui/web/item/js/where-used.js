/**
 * The Where Used tab: the assemblies that hold the item, as a tree. Each parent has a chevron that reads the
 * level above it the first time it is opened. Python does the reading; this page polls for each answer.
 * Layer: UI. The numbering of the rows (``rowsOf``) is the only rule here, and it is a pure function.
 */
(function (ns) {
  'use strict';

  const el = ns.el;
  const t = ns.i18n.t;
  const tree = ns.itemTree;
  const ITEM_COLUMN_PX = tree.ITEM_COLUMN_PX;
  const COLUMN_PX = tree.COLUMN_PX;
  const DEFAULT_COLUMNS = ['QUANTITY', 'UNITS', 'LIFECYCLE'];
  // An assembly: a parent box over two parts, joined by lines. Static markup.
  const ASSEMBLY_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8.5" y="3" width="7" height="5" rx="1"/><rect x="2.5" y="16" width="7" height="5" rx="1"/><rect x="14.5" y="16" width="7" height="5" rx="1"/><path d="M12 8v4M6 16v-4h12v4"/></svg>';
  const CLASS = 'item-where-used';

  let current = 0;   // the tab being drawn; an answer for an older item is ignored

  /** Read one level: ``up`` is the link of an earlier answer, or empty for the item itself. */
  function load(view, up, done) {
    tree.load('where_used_load', 'where_used_result', { workspace_id: view.workspace_id, item_id: view.item_id, stamp: view.stamp, up: up }, done);
  }

  function titleOf(key) { return key.charAt(0) + key.slice(1).toLowerCase(); }   // QUANTITY -> Quantity

  /** Fill ``target`` with the parents of the item of ``view``. */
  function render(target, view) {
    const mine = ++current;
    tree.loading(target, CLASS, t('item.wu_reading'));
    load(view, '', function (error, result) {
      if (mine !== current) return;
      if (error) { tree.centred(target, CLASS, t('item.wu_error', { error: error }), true); return; }
      draw(target, view, result);
    });
  }

  function makeNode(row) { return { row: row, open: false, loading: false, error: '', children: null }; }

  /** The rows to show, in order, for the nodes that are open. ``prefix`` is the parent's number, so a child is 1.1, 1.2 ... */
  function rowsOf(nodes, depth, out, prefix) {
    nodes.forEach(function (node, i) {
      const number = prefix + (i + 1);
      out.push({ node: node, depth: depth, number: number });
      if (node.open && node.children) rowsOf(node.children, depth + 1, out, number + '.');
    });
    return out;
  }

  /** The headings: item and version, then the columns (with no parents, the usual columns in words). */
  function headTitles(hasRows, columns) {
    const rest = hasRows ? columns.map(titleOf) : [t('item.bom_col_quantity'), t('item.wu_col_units'), t('item.bom_col_lifecycle')];
    return [t('item.col_item'), t('item.col_version')].concat(rest);
  }

  /** Fill the <colgroup> and heading row of ``parts`` (``table``, ``colgroup``, ``head``) with one resizable column for each of ``titles``. */
  function fillHead(parts, titles) {
    parts.colgroup.replaceChildren();
    parts.head.replaceChildren();
    const cols = [];
    const heads = [];
    titles.forEach(function (title, i) {
      const col = el('col');
      col.style.width = (i === 0 ? ITEM_COLUMN_PX : COLUMN_PX) + 'px';
      parts.colgroup.appendChild(col);
      const th = el('th', '', title);
      parts.head.appendChild(th);
      cols.push(col);
      heads.push(th);
    });
    tree.resizable(parts.table, cols, heads, COLUMN_PX);
  }

  /** An empty table with its <colgroup>, heading row and <tbody> in place. */
  function makeTableParts() {
    const table = el('table', 'item-files-table item-tree-table');
    const colgroup = el('colgroup');
    const head = el('tr');
    const body = el('tbody');
    table.append(colgroup, el('thead'), body);
    table.tHead.appendChild(head);
    return { table: table, colgroup: colgroup, head: head, body: body };
  }

  function draw(target, view, top) {
    target.className = 'view-scroll ' + CLASS;
    // grows when a deeper level has a field the first did not; with no parents the usual columns still show
    const columns = top.rows.length ? top.columns.slice() : DEFAULT_COLUMNS.slice();
    const roots = top.rows.map(function (row) { return makeNode(row); });
    const parts = makeTableParts();

    function drawHead() { fillHead(parts, headTitles(roots.length > 0, columns)); }

    /** The level above ``node`` has been read: take its columns and rows, or show why it could not be. */
    function takeAnswer(node, error, result) {
      if (error) { node.error = error; node.open = false; return; }
      result.columns.forEach(function (c) { if (columns.indexOf(c) < 0) columns.push(c); });
      node.children = result.rows.map(function (row) { return makeNode(row); });
      if (!node.children.length) node.row.up = '';   // nothing above it after all: no chevron
      drawHead();
    }

    function toggle(node) {
      node.open = !node.open;
      if (node.open && !node.children && !node.loading) {
        node.loading = true;
        node.error = '';
        load(view, node.row.up, function (error, result) {
          node.loading = false;
          if (!parts.table.isConnected) return;
          takeAnswer(node, error, result);
          drawRows();
        });
      }
      drawRows();
    }

    function drawRow(entry, xs, chevronDepths) {
      const node = entry.node;
      const row = node.row;
      const tr = el('tr');
      tr.appendChild(tree.itemCell({
        quiet: true, iconX: xs[entry.depth], number: entry.number, row: row, kind: 'assembly', room: chevronDepths[entry.depth],
        chevron: row.up ? { open: node.open, title: node.open ? t('item.collapse') : t('item.wu_show'), onClick: function () { toggle(node); } } : null,
        loading: node.loading, error: node.error,
      }));
      tr.appendChild(el('td', '', row.version));
      columns.forEach(function (c) { tr.appendChild(el('td', '', row.fields[c] || '')); });
      parts.body.appendChild(tr);
    }

    function drawRows() {
      parts.body.replaceChildren();
      const entries = rowsOf(roots, 0, [], '');
      const chevronDepths = {};   // a level only leaves room for a chevron when one of its rows has one
      entries.forEach(function (entry) { if (entry.node.row.up) chevronDepths[entry.depth] = true; });
      const xs = tree.iconXs(entries, chevronDepths);
      entries.forEach(function (entry) { drawRow(entry, xs, chevronDepths); });
    }

    drawHead();
    drawRows();
    const wrap = el('div', 'item-files-wrap');
    wrap.appendChild(parts.table);
    target.replaceChildren(wrap);
    if (!roots.length) {   // the columns stay, and the message is centred in the space under them
      tree.emptyUnder(target, ASSEMBLY_ICON, t('item.wu_empty'), t('item.wu_empty_hint'));
    }
  }

  ns.itemWhereUsed = { render: render };
})(window.MfgUi);
