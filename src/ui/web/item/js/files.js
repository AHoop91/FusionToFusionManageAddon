/**
 * The Files tab: the files attached to the item, as a table that sorts by any column.
 *
 * A file name opens the file's page in Fusion Manage, in the browser.
 * Files the open document makes (its STEP file, or its PDF, DWG and DXF) are marked Out of Date when the document was saved since.
 */
(function (ns) {
  'use strict';

  const el = ns.el;
  const t = ns.i18n.t;
  const tree = ns.itemTree;
  const CLASS = 'item-files';
  const LAST_COLUMN_MIN_PX = 200;   // the description column

  // column key, heading, and how to turn a file into the text shown and sorted on
  const COLUMNS = [
    { key: 'name', title: function () { return t('item.files_col_name'); }, width: 260 },
    { key: 'title', title: function () { return t('item.files_col_title'); }, width: 200 },
    { key: 'version', title: function () { return t('item.files_col_version'); }, width: 70, number: true },
    { key: 'type', title: function () { return t('item.files_col_type'); }, width: 130 },
    { key: 'size', title: function () { return t('item.files_col_size'); }, width: 90, number: true },
    { key: 'updated', title: function () { return t('item.col_last_updated'); }, width: 170 },
    { key: 'user', title: function () { return t('item.col_by_user'); }, width: 130 },
    { key: 'description', title: function () { return t('item.col_description'); } },
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
    if (bytes < 1024 * 1024) return t('item.size_kb', { size: (bytes / 1024).toFixed(1) });
    return t('item.size_mb', { size: (bytes / (1024 * 1024)).toFixed(1) });
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
      case 'updated': return tree.formatDate(file.updated);
      default: return String(file[column.key] || '');
    }
  }

  function sortValue(file, column) {
    const value = file[column.key];
    if (column.number) return Number(value) || 0;
    return String(value || '').toLowerCase();
  }

  let current = 0;   // the tab being drawn; an answer for an older item is ignored

  /** Read the files of the item of ``view`` and fill ``target`` with them; ``open(file)`` runs when a file name is clicked. */
  function render(target, view, open, tools) {
    const mine = ++current;
    tree.loading(target, CLASS, t('item.files_reading'));
    tree.load('files_load', 'files_result', { workspace_id: view.workspace_id, item_id: view.item_id, stamp: view.stamp, item_urn: view.item_urn }, function (error, files) {
      if (mine !== current) return;
      if (error) { tree.centred(target, CLASS, t('item.files_error', { error: error }), true); return; }
      const mark = draw(target, files, open, tools);
      if (files.length) checkFresh(files, function (stale) { if (mine === current) mark(stale); });
    });
  }

  let listening = false;
  let waiting = null;   // told which files are out of date, when Python answers

  /** Ask Python which of ``files`` are older than the latest save of the open document (the STEP file of a design, the PDF, DWG and DXF of a drawing). */
  function checkFresh(files, done) {
    if (!listening) {
      listening = true;
      ns.bridge.on('files_freshness', function (r) {
        const callback = waiting;
        waiting = null;
        if (callback && r.ok && r.result) callback(r.result.stale || {});   // a check that failed leaves the files unmarked
      });
    }
    waiting = done;
    ns.bridge.send('files_freshness', { files: files.map(function (f) { return { name: f.name, updated: f.updated }; }) });
  }

  /**
   * The bar over the table, as over the Bill of Materials: a button for each file the open document can be exported as and attached
   * (``tools.actions``: the STEP file of a design, the PDF, DWG and DXF of a drawing). ``tools`` also says when one is under way
   * (``busy``), starts one (``run``) and calls the function given to ``listen`` when any of it changes.
   */
  function toolbar(tools) {
    const bar = el('div', 'item-files-bar');
    function paint() {
      bar.replaceChildren();
      tools.actions.forEach(function (action) {
        const button = el('button', 'item-files-tool');
        button.type = 'button';
        button.append(icon(action.ext), el('span', '', action.label));
        button.title = action.ready ? t('item.files_attach_tip', { label: action.label }) : t('item.drawing_loading');
        button.disabled = tools.busy || !action.ready;
        button.addEventListener('click', function () { tools.run(action.action); });
        bar.appendChild(button);
      });
      bar.hidden = !tools.actions.length;
    }
    tools.listen(paint);
    paint();
    tools.refresh();
    return bar;
  }

  /** Fill ``target`` with the table of ``files``. */
  function draw(target, files, open, tools) {
    target.className = 'view-scroll ' + CLASS;
    target.replaceChildren();
    target.appendChild(toolbar(tools));

    let stale = {};   // file name -> why it is out of date, once Python has checked

    function nameCell(td, file) {
      if (stale[file.name]) {   // made from an earlier save of the open document
        const pill = el('span', 'item-file-stale', t('item.out_of_date'));
        pill.title = stale[file.name];
        td.appendChild(pill);
      }
      td.appendChild(icon(file.ext));
      const link = el('a', 'item-link', file.name);
      link.href = '#';
      link.title = t('item.open_in_fusion_manage');
      link.addEventListener('click', function (event) { event.preventDefault(); open(file); });
      td.appendChild(link);
    }

    const table = tree.sortableTable(target, {
      columns: COLUMNS.map(function (c) {
        return {
          key: c.key, title: c.title(), width: c.width, sort: function (file) { return sortValue(file, c); },
          cell: c.key === 'name' ? nameCell : function (td, file) { td.textContent = shown(file, c); },
        };
      }),
      rows: files,
      sortKey: 'name',
      lastMin: LAST_COLUMN_MIN_PX,
      empty: { icon: EMPTY_FOLDER, text: t('item.files_empty'), hint: t('item.files_empty_hint') },
    });
    return function (found) { stale = found; table.draw(); };   // mark the files found out of date
  }

  // A page that has no open document to export and attach from (a product, a line of the Publish viewer) gives this as ``tools``.
  const NO_TOOLS = { actions: [], busy: false, run: function () {}, listen: function () {}, refresh: function () {} };

  /** What a click on a file does on a page with no viewer of its own: its page in Fusion Manage opens. */
  function open(file) { if (file.url) ns.bridge.send('open_url', { url: file.url }); }

  ns.itemFiles = { render: render, icon: icon, open: open, NO_TOOLS: NO_TOOLS };
})(window.MfgUi);
