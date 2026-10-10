/**
 * The Associated Workflows tab: the workflow items (such as change orders) that reference the item, with where each
 * is in its workflow and the last step taken. A title opens the workflow in Fusion Manage.
 */
(function (ns) {
  'use strict';

  const bridge = ns.bridge;
  const el = ns.el;
  const tree = ns.itemTree;
  const CLASS = 'item-workflows';
  // heading, width, and how to read the text of a cell from a row; the title column links to the workflow
  const COLUMNS = [
    { title: 'Workflow', width: 260, link: true, text: function (r) { return r.title; } },
    { title: 'Status', width: 110, text: function (r) { return r.state; } },
    { title: 'Last Action', width: 110, text: function (r) { return r.last.action; } },
    { title: 'By User', width: 120, text: function (r) { return r.last.user; } },
    { title: 'Last Updated', width: 190, text: function (r) { return tree.formatDate(r.last.date); } },
    { title: 'Comments', width: 200, text: function (r) { return r.last.comments; } },
  ];
  // A page with a tick: a change that is being worked through. Static markup.
  const WORKFLOW_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5M10 14l2 2 4-4"/></svg>';

  let current = 0;   // the tab being drawn; an answer for an older item is ignored

  /** Read the associated workflows of the item of ``view`` and fill ``target`` with them. */
  function render(target, view) {
    const mine = ++current;
    tree.loading(target, CLASS, 'Reading the associated workflows...');
    tree.load('workflows_load', 'workflows_result', { workspace_id: view.workspace_id, item_id: view.item_id }, function (error, rows) {
      if (mine !== current) return;
      if (error) { tree.centred(target, CLASS, 'Could not read the associated workflows: ' + error, true); return; }
      draw(target, rows);
    });
  }

  function draw(target, rows) {
    target.className = 'view-scroll ' + CLASS;
    const table = el('table', 'item-files-table item-tree-table');
    const colgroup = el('colgroup');
    const head = el('tr');
    const cols = [];
    const heads = [];
    COLUMNS.forEach(function (column) {
      const col = el('col');
      col.style.width = column.width + 'px';
      colgroup.appendChild(col);
      const th = el('th', '', column.title);
      head.appendChild(th);
      cols.push(col);
      heads.push(th);
    });
    const body = el('tbody');
    rows.forEach(function (row) {
      const tr = el('tr');
      COLUMNS.forEach(function (column) {
        const td = el('td');
        const text = column.text(row);
        if (column.link && row.url) {
          const a = el('a', 'item-link', text);
          a.href = '#';
          a.title = 'Open in Fusion Manage in your browser';
          a.addEventListener('click', function (event) {
            event.preventDefault();
            bridge.send('open_url', { url: row.url });
          });
          td.appendChild(a);
        } else {
          td.textContent = text;
        }
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    table.append(colgroup, el('thead'), body);
    table.tHead.appendChild(head);
    tree.resizable(table, cols, heads, tree.COLUMN_PX);
    const wrap = el('div', 'item-files-wrap');
    wrap.appendChild(table);
    target.replaceChildren(wrap);
    if (!rows.length) {   // the columns stay, and the message is centred in the space under them
      tree.emptyUnder(target, WORKFLOW_ICON, 'No associated workflows', 'Workflows in Fusion Manage that reference this item will be listed here.');
    }
  }

  ns.itemWorkflows = { render: render };
})(window.MfgUi);
