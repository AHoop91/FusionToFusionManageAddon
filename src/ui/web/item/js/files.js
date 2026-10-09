/**
 * The Files tab: the files attached to the item, as a table that sorts by any column.
 *
 * A file name opens the file: Python downloads it and opens it with the program the system uses for it.
 */
(function (ns) {
  'use strict';

  const el = ns.el;
  const MIN_COLUMN_PX = 50;
  const LAST_COLUMN_MIN_PX = 200;   // the description column

  // column key, heading, and how to turn a file into the text shown and sorted on
  const COLUMNS = [
    { key: 'name', title: 'File Name', width: 260 },
    { key: 'title', title: 'Title', width: 200 },
    { key: 'version', title: 'Ver.', width: 70, number: true },
    { key: 'type', title: 'Type', width: 130 },
    { key: 'size', title: 'Size', width: 90, number: true },
    { key: 'updated', title: 'Last Updated', width: 170 },
    { key: 'user', title: 'By User', width: 130 },
    { key: 'description', title: 'Description' },
  ];

  // Icon colour and badge text by kind of file; anything else is grey and badged with its own extension.
  const KINDS = [
    { color: '#d93025', label: 'PDF', exts: ['.pdf'] },
    { color: '#2b579a', label: 'DOC', exts: ['.doc', '.docx', '.rtf'] },
    { color: '#6a737d', label: 'TXT', exts: ['.txt', '.md', '.log'] },
    { color: '#217346', label: 'XLS', exts: ['.xls', '.xlsx', '.xlsm', '.csv'] },
    { color: '#d24726', label: 'PPT', exts: ['.ppt', '.pptx'] },
    { color: '#0696d7', label: 'DWF', exts: ['.dwf', '.dwfx'] },
    { color: '#7e57c2', label: 'DWG', exts: ['.dwg', '.dxf', '.idw', '.f2d'] },
    { color: '#c2185b', label: 'STEP', exts: ['.step', '.stp'] },
    { color: '#5e35b1', label: '3D', exts: ['.iam', '.ipt', '.f3d', '.stl', '.iges', '.igs', '.sldprt', '.sldasm'] },
    { color: '#00897b', label: 'IMG', exts: ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tif', '.tiff', '.svg'] },
    { color: '#f9a825', label: 'ZIP', exts: ['.zip', '.7z', '.rar', '.gz', '.tar'] },
  ];

  // An empty folder: nothing is filed here yet. Static markup.
  const EMPTY_FOLDER = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>';

  function formatSize(bytes) {
    if (!bytes) return '';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  }

  function formatDate(stamp) {
    const date = new Date(stamp);
    return stamp && !isNaN(date) ? date.toLocaleString() : '';
  }

  function icon(ext) {
    const lower = String(ext).toLowerCase();
    const kind = KINDS.find(function (k) { return k.exts.indexOf(lower) >= 0; });
    const color = kind ? kind.color : '#8a949e';
    const label = kind ? kind.label : lower.replace(/[^a-z0-9]/g, '').slice(0, 4).toUpperCase();   // letters and digits only, so it is safe markup
    const span = el('span', 'item-file-icon');
    // a white page with a folded corner and a tag in the kind's colour across it
    span.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true">' +
      '<path d="M5.5 1.5h8.5l5 5v15a1 1 0 0 1-1 1h-12.5a1 1 0 0 1-1-1v-19a1 1 0 0 1 1-1z" fill="#fff" stroke="#b8c0c8" stroke-width="1"/>' +
      '<path d="M14 1.5v4a1.5 1.5 0 0 0 1.5 1.5h3.5" fill="#e9edf1" stroke="#b8c0c8" stroke-width="1" stroke-linejoin="round"/>' +
      '<rect x="1.5" y="11.5" width="17" height="8" rx="1.5" fill="' + color + '"/>' +
      (label ? '<text x="10" y="17.4" text-anchor="middle" font-size="' + (label.length > 3 ? 5.2 : 6) + '" font-weight="700" font-family="Segoe UI, Arial, sans-serif" fill="#fff">' + label + '</text>' : '') +
      '</svg>';
    return span;
  }

  /** What a cell shows for ``file``, and the value the column sorts on. */
  function shown(file, column) {
    switch (column.key) {
      case 'size': return formatSize(file.size);
      case 'updated': return formatDate(file.updated);
      default: return String(file[column.key] || '');
    }
  }

  function sortValue(file, column) {
    const value = file[column.key];
    if (column.number) return Number(value) || 0;
    return String(value || '').toLowerCase();
  }

  /** A large icon and a line of text in the middle of ``target``, for a tab with nothing to list. */
  function centred(target, text, isError, hint) {
    target.classList.add('item-centred');
    const icon = el('span', 'item-empty-icon item-empty-icon-large');
    icon.innerHTML = EMPTY_FOLDER;
    target.appendChild(icon);
    target.appendChild(el('p', 'item-empty-text' + (isError ? ' error' : ''), text));
    if (hint) target.appendChild(el('p', 'item-empty-hint', hint));
  }

  /** A handle on a heading's right edge: dragging it sets the width of its column. */
  function grip(col, fit) {
    const handle = el('span', 'item-grip');
    handle.addEventListener('click', function (event) { event.stopPropagation(); });   // not a sort
    handle.addEventListener('mousedown', function (event) {
      event.preventDefault();
      event.stopPropagation();
      const startX = event.clientX;
      const startWidth = parseFloat(col.style.width);
      handle.classList.add('item-grip-active');
      function move(e) {
        col.style.width = Math.max(MIN_COLUMN_PX, startWidth + e.clientX - startX) + 'px';
        fit();
      }
      function stop() {
        document.removeEventListener('mousemove', move);
        document.removeEventListener('mouseup', stop);
        handle.classList.remove('item-grip-active');
      }
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', stop);
    });
    return handle;
  }

  /** Fill ``target`` with the table of ``view.files``; ``open(file)`` runs when a file name is clicked. */
  function render(target, view, open) {
    target.replaceChildren();
    target.classList.remove('item-centred', 'item-files-stack');
    if (view.files_error) { centred(target, 'Could not read the files: ' + view.files_error, true); return; }

    let sortKey = 'name';
    let ascending = true;
    const table = el('table', 'item-files-table');
    const head = el('tr');
    const body = el('tbody');
    const marks = {};

    // Each column has a pixel width the user can drag; the description (no width) takes what the panel has left.
    const colgroup = el('colgroup');
    const cols = COLUMNS.map(function (column) {
      const col = el('col');
      if (column.width) col.style.width = column.width + 'px';
      colgroup.appendChild(col);
      return col;
    });
    table.appendChild(colgroup);
    function fit() {   // the table is never narrower than its columns, so a narrow panel scrolls it sideways
      const fixed = cols.reduce(function (sum, col) { return sum + (parseFloat(col.style.width) || 0); }, 0);
      table.style.minWidth = (fixed + LAST_COLUMN_MIN_PX) + 'px';
    }
    fit();
    COLUMNS.forEach(function (column) {
      const th = el('th', '', column.title);
      th.title = 'Sort by ' + column.title;
      marks[column.key] = el('span', 'item-sort');
      th.appendChild(marks[column.key]);
      th.addEventListener('click', function () {
        ascending = sortKey === column.key ? !ascending : true;
        sortKey = column.key;
        draw();
      });
      if (column.width) th.appendChild(grip(cols[COLUMNS.indexOf(column)], fit));
      head.appendChild(th);
    });
    table.appendChild(el('thead')).appendChild(head);
    table.appendChild(body);

    function draw() {
      const column = COLUMNS.find(function (c) { return c.key === sortKey; });
      const rows = view.files.slice().sort(function (a, b) {
        const x = sortValue(a, column);
        const y = sortValue(b, column);
        return (x < y ? -1 : x > y ? 1 : 0) * (ascending ? 1 : -1);
      });
      COLUMNS.forEach(function (c) { marks[c.key].textContent = c.key === sortKey ? (ascending ? '↑' : '↓') : ''; });
      body.replaceChildren();
      rows.forEach(function (file) {
        const tr = el('tr');
        COLUMNS.forEach(function (c) {
          const td = el('td');
          if (c.key === 'name') {
            td.appendChild(icon(file.ext));
            const link = el('a', 'item-link', file.name);
            link.href = '#';
            link.title = 'Open in Fusion Manage in your browser';
            link.addEventListener('click', function (event) { event.preventDefault(); open(file); });
            td.appendChild(link);
          } else {
            td.textContent = shown(file, c);
          }
          tr.appendChild(td);
        });
        body.appendChild(tr);
      });
    }

    draw();
    const wrap = el('div', 'item-files-wrap');   // a wide table scrolls sideways
    wrap.appendChild(table);
    target.appendChild(wrap);
    if (!view.files.length) {   // the columns stay, and the empty message fills the space under them
      target.classList.add('item-files-stack');
      const empty = el('div', 'item-files-empty');
      centred(empty, 'No files attached', false, 'Files attached to this item in Fusion Manage will be listed here.');
      target.appendChild(empty);
    }
  }

  ns.itemFiles = { render: render };
})(window.MfgUi);
