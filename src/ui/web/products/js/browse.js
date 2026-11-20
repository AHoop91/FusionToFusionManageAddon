/**
 * The details screen of the Browse Product Portfolio window, laid out and read as the Item panel does it: a header with the product's name and
 * workflow state and its actions (open its design, open in the browser, read again), a breadcrumb back to the list above them, the tabs
 * the workspace has, and under them the content of the tab.
 *
 * The product is read as the Item panel reads an item (``products_view``): every section of its fields on the first tab, drawn by the same code
 * (``ns.itemSections``), and the name and count of each tab the workspace has. The tabs the Item panel has (Attachments, Bill of Materials, Where
 * Used, Associated Workflows, Change Log) are drawn by its own code, read when the tab is first opened. The Grid tab is this screen's own: the
 * rows of the product's Grid (``products_contents``), with a link on each that opens the design of its component in Fusion.
 *
 * The page lends what it shares (``host``: ``ask`` for a request to Python, ``failure``, ``open`` to open a component's design in Fusion,
 * ``openLightbox`` to show a picture large, and ``back`` to return to the list) and asks for a product with ``ns.browse.init(host).show(item)``.
 */
(function (ns) {
  'use strict';

  const bridge = ns.bridge;
  const $ = ns.$;
  const el = ns.el;
  const t = ns.i18n.t;

  // A product is not the open design, so there is nothing to export and attach to it from here.
  const NO_TOOLS = { actions: [], busy: false, run: function () {}, listen: function () {}, refresh: function () {} };
  const ORDER = ['item', 'files', 'grid', 'bom', 'whereused', 'workflows', 'changelog'];   // the tabs, left to right, when the workspace has them
  const LAZY = {   // the tabs read when they are opened, and what draws each (the Item panel's own code)
    files: function (pane, view) {
      ns.itemFiles.render(pane, view, function (file) { if (file.url) bridge.send('open_url', { url: file.url }); }, NO_TOOLS);
    },
    bom: function (pane, view) { ns.itemBom.render(pane, view); },
    whereused: function (pane, view) { ns.itemWhereUsed.render(pane, view); },
    workflows: function (pane, view) { ns.itemWorkflows.render(pane, view); },
    changelog: function (pane, view) { ns.itemChangeLog.render(pane, view); },
  };
  const GRID_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 5h18v14H3z"/><path d="M3 10h18M3 15h18M9 5v14M15 5v14"/></svg>';   // a table (static markup)
  const GRID_OPEN_PX = 136;     // the column of buttons: the width of the button and the padding of its cell
  const GRID_COLUMN_PX = 200;   // the width a column starts with
  const GRID_LAST_PX = 200;     // the least the last column, which takes what is left, is
  const PIN = 'M12 22s-7-6.3-7-12a7 7 0 0 1 14 0c0 5.7-7 12-7 12zm0-9.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z';   // a map pin: where the product is in its workflow

  let host = null;   // what the page lends: see ``init``
  let seq = 0;       // numbers the reads, so the answer to an earlier one is dropped
  let current = '';  // the id of the product shown
  let url = '';      // its page in Fusion Manage
  let tab = 'item';  // the tab shown
  let view = null;   // the product as read (``products_view``), once it is
  let grid = null;   // its grid (``products_contents``), once it is
  let panes = {};    // tab key -> its pane
  let buttons = {};  // tab key -> its button
  let loaded = {};   // tab key -> true once a lazy tab has been asked for

  /** The header: the product's name, and under it where it is in its workflow (the state). */
  function paintHeader() {
    $('products-browse-title').textContent = view.title;
    $('products-browse-crumb-here').textContent = view.title;
    const status = $('products-browse-status');
    status.replaceChildren();
    if (view.state) {   // only the state, with a pin before it: a product has no revision or life cycle to show
      const pin = ns.svg([PIN], 16);
      pin.setAttribute('class', 'pb-pin');
      pin.querySelector('path').setAttribute('fill-rule', 'evenodd');
      status.append(pin, el('span', '', view.state));
    }
    url = view.url;
    $('products-browse-open').hidden = !url;
  }

  /** The Grid tab, drawn as the Attachments tab draws its files: columns of a width to drag, a heading to sort by and, when there are no rows,
   *  the columns with an icon and a line in the space under them (the table is ``ns.itemTree.sortableTable``, as the Attachments tab's is). The columns are the grid's, as Fusion Manage lays them out, after one of ours:
   *  Open Design, a link on each row that opens the design of its component in Fusion. The column that names the component is a link that
   *  opens the item in Fusion Manage, as a linked field is on the Item tab. */
  function paintGrid() {
    const pane = panes.grid;
    if (!pane || !grid) return;
    const columns = [{
      key: '__open_design', title: '', width: GRID_OPEN_PX, resize: false,   // the column of buttons has no title, and nothing to sort or resize
      cell: function (td, row) { if (row.link) td.appendChild(openButton(function (done) { host.open(row.link, done); })); },
    }].concat(grid.columns.map(function (column, i) {
      return {
        key: column.id, title: column.title, width: i < grid.columns.length - 1 ? GRID_COLUMN_PX : 0,   // the last takes what is left
        sort: function (row) { return (row.cells[column.id] || '').toLowerCase(); },
        cell: function (td, row) {
          td.title = row.cells[column.id] || '';
          if (column.id === grid.link_column && row.url) td.appendChild(rowLink(row.title, function () { bridge.send('open_url', { url: row.url }); }));
          else td.textContent = row.cells[column.id] || '';
        },
      };
    }));
    pane.className = 'view-scroll item-files item-grid';
    pane.replaceChildren();
    if (!grid.link_column) pane.appendChild(el('p', 'pu-muted', t('products.browse_no_column')));
    ns.itemTree.sortableTable(pane, {
      columns: columns,
      rows: grid.rows,
      lastMin: GRID_LAST_PX,
      empty: { icon: GRID_ICON, text: t('products.browse_grid_empty'), hint: t('products.browse_grid_empty_hint') },
    });
  }

  /** Make ``button`` run ``run(done)`` when pressed, and show it is under way (a turning ring, and not to be pressed again) until ``done`` is called. */
  function pressing(button, run) {
    const label = button.textContent;
    button.addEventListener('click', function () {
      button.disabled = true;
      button.classList.add('busy');
      button.textContent = t('products.browse_opening');
      run(function () {
        button.disabled = false;
        button.classList.remove('busy');
        button.textContent = label;
      });
    });
  }

  /** The button of a row that opens the design of its component in Fusion. */
  function openButton(run) {
    const button = el('button', 'btn btn-secondary pb-open', t('products.browse_open_design'));
    button.type = 'button';
    pressing(button, run);
    return button;
  }

  /** A link in a cell of the grid. */
  function rowLink(text, run) {
    const link = el('a', 'item-link', text);
    link.href = '#';
    link.addEventListener('click', function (event) { event.preventDefault(); run(); });
    return link;
  }

  /** A tab's button text: its name as the workspace gives it, and how many entries it holds. */
  function tabText(key) {
    const info = view.tabs[key];
    return info.allowed && info.count ? info.label + ' (' + info.count + ')' : info.label;
  }

  /** The balls and a line in the middle of ``pane`` (across and down) while it is read. */
  function loading(pane) {
    ns.itemTree.loading(pane, '', t('products.browse_loading'));
  }

  function failed(pane, answer) {
    pane.textContent = '';
    pane.appendChild(el('p', 'pu-bad', t('products.browse_failed', { reason: host.failure(answer) })));
  }

  /** Show the tab ``name``, reading it first if it is one that is read when opened. */
  function select(name) {
    if (tab && name !== tab) ns.itemTree.leave(tab);   // what the tab left was still reading is not wanted
    tab = name;
    Object.keys(panes).forEach(function (key) {
      panes[key].hidden = key !== name;
      buttons[key].classList.toggle('item-tab-active', key === name);
      buttons[key].setAttribute('aria-selected', String(key === name));
    });
    if (LAZY[name] && !loaded[name]) { loaded[name] = true; LAZY[name](panes[name], view); }
  }

  /** The tabs of the product, once it is read: one for each of ``ORDER`` the workspace has, the Item tab drawn now. */
  function buildTabs() {
    const strip = $('products-browse-tabs');
    const area = $('products-browse-panes');
    strip.replaceChildren();
    area.replaceChildren();
    panes = {};
    buttons = {};
    loaded = {};
    ORDER.filter(function (key) { return view.tabs[key]; }).forEach(function (key) {
      const button = el('button', 'item-tab', tabText(key));
      button.type = 'button';
      button.setAttribute('role', 'tab');
      button.disabled = !view.tabs[key].allowed;
      if (button.disabled) button.title = t('item.tab_no_permission');
      button.addEventListener('click', function () { select(key); });
      strip.appendChild(button);
      const pane = el('div', 'view-scroll');
      pane.id = key === 'item' ? 'item-body' : 'item-' + key;   // the Item panel's styles are by these ids
      pane.setAttribute('role', 'tabpanel');
      pane.hidden = true;
      area.appendChild(pane);
      buttons[key] = button;
      panes[key] = pane;
    });
    if (panes.item) {
      view.sections.forEach(function (section) { panes.item.appendChild(ns.itemSections.section(section, host.openLightbox, loadPicture)); });
      if (!view.sections.length) panes.item.appendChild(el('p', 'pu-muted', t('item.no_fields')));
    }
    if (panes.grid) { if (grid) paintGrid(); else loading(panes.grid); }
    const wanted = panes[tab] && !buttons[tab].disabled ? tab : ORDER.find(function (key) { return panes[key] && !buttons[key].disabled; });
    tab = '';
    if (wanted) select(wanted);
  }

  /** A picture one of the product's image fields holds, asked for after the sections are drawn: ``done(src)`` is given the picture, or '' when it
   *  could not be read (the field is then left empty). */
  function loadPicture(link, done) {
    host.ask('products_picture', { link: link }, function (answer) {
      done(answer.ok && answer.result ? answer.result.image : '');
    });
  }

  /** Read the product ``item`` and show it, on the tab the person was on when it is there. */
  function show(item) {
    const mine = ++seq;
    const was = tab;
    $('products-browseview').classList.remove('failed');
    $('products-browseview').classList.add('reading');   // the header and tabs are shown once the product is read, not before
    ns.itemTree.leave();
    current = item;
    url = '';
    view = null;
    grid = null;
    $('products-browse-title').textContent = '';
    $('products-browse-crumb-here').textContent = '';
    $('products-browse-status').replaceChildren();
    $('products-browse-open').hidden = true;
    $('products-browse-design').hidden = true;
    $('products-browse-tabs').replaceChildren();
    const area = $('products-browse-panes');
    area.replaceChildren();
    const first = el('div', 'view-scroll');
    area.appendChild(first);
    loading(first);
    host.ask('products_view', { item: item }, function (answer) {
      if (mine !== seq) return;
      if (!answer.ok) {
        $('products-browseview').classList.replace('reading', 'failed');   // only the way back above the reason
        failed(first, answer);
        return;
      }
      $('products-browseview').classList.remove('reading');
      view = answer.result;
      paintHeader();
      tab = was;
      buildTabs();
    });
    host.ask('products_contents', { item: item }, function (answer) {
      if (mine !== seq) return;
      if (!answer.ok) { if (panes.grid) failed(panes.grid, answer); return; }
      grid = answer.result;
      $('products-browse-design').hidden = !(grid.primary && grid.primary.link);   // opens the Primary Component's design
      paintGrid();
    });
  }

  /** Wire the screen to the page. Returns ``{show}``: ``show(item)`` reads a product and shows it. */
  function init(lent) {
    host = lent;
    $('products-browse-crumb').addEventListener('click', function () { seq++; ns.itemTree.leave(); host.back(); });
    pressing($('products-browse-design'), function (done) { host.open(grid.primary.link, done); });
    $('products-browse-refresh').addEventListener('click', function () { if (current) show(current); });
    $('products-browse-open').addEventListener('click', function () { if (url) bridge.send('open_url', { url: url }); });
    return { show: show };
  }

  ns.browse = { init: init };
})(window.MfgUi);
