/**
 * The Assign Product window: browses the Portfolio Management workspace by view. It asks for the views (``products_views``), and for a page of
 * the rows of the one chosen (``products_rows``), and creates a new product (``products_create``) from a form made of the workspace's own
 * sections and fields (``products_form``). Python answers a request at once with
 * "pending" and the page asks for the outcome (``products_status``) until it is there. Choosing a row only marks it for now.
 */
(function (ns) {
  'use strict';

  const bridge = ns.bridge;
  const $ = ns.$;
  const el = ns.el;
  const t = ns.i18n.t;
  const blank = ns.validators.blank;

  const POLL_MS = 300;       // how often an unanswered request is asked about again
  const PAGE_SIZE = 50;      // rows asked for at a time
  const COMPACT_KEY = 'products.compact';   // whether the rows are shown close together, kept for the next opening
  const VIEW_KEY = 'products.view';   // the view chosen last, kept for the next opening
  const CHECK = 'M5 12.5l4.5 4.5L19 7.5';   // the tick beside the view in use
  const FORM_DEBOUNCE_MS = 150;   // the form's filters and its footer look again once the typing has paused

  let seq = 0;               // numbers the requests, so each has a token of its own
  const waiting = {};        // token -> what to do with the answer
  let rowsToken = '';        // the rows read that counts: an older one that arrives late is dropped
  let started = false;       // the views have been asked for
  let views = [];            // [{id, name}]
  let view = '';             // id of the view shown
  let viewCount = '';        // " (n)": how many records the view holds, once its rows are in
  let viewPicker = null;     // the shared picker that chooses the view
  let page = 1;
  let more = false;          // whether there is a page after this one
  let selected = '';         // id of the row chosen
  let busy = true;           // the list is being read: nothing on the page can be pressed until it is done
  let canCreate = true;      // the user may add items to the workspace, so may create a product
  let assigning = false;     // the open design is being assigned to the chosen product
  let columnsToken = null;   // the read of columns that is wanted
  let definition = null;     // [{id, title, filters, applied}] of the view chosen, as the view describes itself (null until known)
  let definitionView = '';   // the view the definition is of

  /** Show ``message`` in the alert ``id``, or hide the alert when there is none. */
  function setAlert(id, message) {
    const box = $(id);
    box.textContent = message;
    box.hidden = !message;
  }

  /** What a refused request says, in words. */
  function failure(answer) { return answer.message || t('products.unknown_error'); }

  /** ``fn`` run once ``ms`` after the last call. */
  function debounced(fn, ms) {
    let timer = 0;
    return function () { clearTimeout(timer); timer = setTimeout(fn, ms); };
  }

  // ---- Asking Python -------------------------------------------------------------------

  /** Send ``action`` and call ``done(answer)`` with its outcome once Python has one. */
  function ask(action, payload, done) {
    const token = 'p' + (++seq);
    waiting[token] = done;
    bridge.send(action, Object.assign({ token: token }, payload));
    return token;
  }

  function onAnswer(r) {
    if (!r.ok) {   // the request itself was refused: every request that waits is told
      Object.keys(waiting).forEach(function (token) {
        const done = waiting[token];
        delete waiting[token];
        done({ ok: false, message: r.error || t('products.unknown_error') });
      });
      return;
    }
    const answer = r.result;
    const done = waiting[answer.token];
    if (!done) return;
    if (answer.pending) {
      setTimeout(function () { if (waiting[answer.token]) bridge.send('products_status', { token: answer.token }); }, POLL_MS);
      return;
    }
    delete waiting[answer.token];
    done(answer);
  }

  // ---- Menus ---------------------------------------------------------------------------
  // The actions are a small pop-up menu: one open at a time, closed by a click elsewhere or Escape.

  const menus = [];   // {button, list}

  function closeMenus(except) {
    menus.forEach(function (m) {
      if (m === except) return;
      m.list.hidden = true;
      m.button.setAttribute('aria-expanded', 'false');
    });
  }

  function items(m) {
    return Array.prototype.filter.call(m.list.querySelectorAll('[role="menuitem"], [role="menuitemcheckbox"]'), function (i) { return !i.disabled; });
  }

  /** Make ``button`` open and close ``list``, with the arrow keys moving through its entries. */
  function menu(button, list) {
    const m = { button: button, list: list };
    menus.push(m);
    function open(focusLast) {
      closeMenus(m);
      list.hidden = false;
      button.setAttribute('aria-expanded', 'true');
      const entries = items(m);
      const target = focusLast ? entries[entries.length - 1] : entries[0];
      if (target) target.focus();
    }
    function close(refocus) {
      closeMenus();
      if (refocus) button.focus();
    }
    button.addEventListener('click', function () { if (list.hidden) open(false); else close(false); });
    button.addEventListener('keydown', function (event) {
      if (event.key === 'ArrowDown') { event.preventDefault(); open(false); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); open(true); }
    });
    list.addEventListener('keydown', function (event) {
      const entries = items(m);
      const at = entries.indexOf(document.activeElement);
      if (event.key === 'ArrowDown') { event.preventDefault(); entries[(at + 1) % entries.length].focus(); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); entries[(at - 1 + entries.length) % entries.length].focus(); }
      else if (event.key === 'Home') { event.preventDefault(); entries[0].focus(); }
      else if (event.key === 'End') { event.preventDefault(); entries[entries.length - 1].focus(); }
      else if (event.key === 'Escape') { event.preventDefault(); close(true); }
      else if (event.key === 'Tab') close(false);
    });
    list.addEventListener('click', function () { close(true); });
  }

  document.addEventListener('click', function (event) {
    if (!event.target.closest('.products-dropdown')) closeMenus();
  });

  // ---- Views ---------------------------------------------------------------------------

  function showError(message) { setAlert('products-error', message); }

  /** Let the buttons be pressed, or not: none while the list is read. */
  function refreshControls() {
    viewPicker.querySelector('.pk-btn').disabled = busy || !views.length;
    $('products-refresh-view').disabled = busy;
    $('products-view-filter').disabled = busy || !definition;
    $('products-view-columns').disabled = busy || !definition;
    $('products-new').hidden = !canCreate;
    $('products-new').disabled = busy;
    $('products-edit').disabled = busy || assigning || !selected;
    $('products-assign').disabled = busy || assigning || !selected;
    $('products-prev').disabled = busy || page === 1;
    $('products-next').disabled = busy || !more;
  }

  /** Say something in the middle of the table (nothing clears it). Whatever was loading is done. */
  function setStatus(text) {
    busy = false;
    refreshControls();
    $('products-loading').hidden = true;
    $('products-status').textContent = text;
  }

  /** Three bouncing balls in the middle of the table, ``label`` for a screen reader, until the next ``setStatus``. */
  function setLoading(label) {
    busy = true;
    refreshControls();
    $('products-status').textContent = '';
    $('products-balls').setAttribute('aria-label', label);
    $('products-loading').hidden = false;
  }

  function remembered() { return window.localStorage.getItem(VIEW_KEY) || ''; }

  function remember(id) { window.localStorage.setItem(VIEW_KEY, id); }

  /** Show the rows close together, or not (and keep the choice). */
  function setCompact(on) {
    $('products-table').classList.toggle('compact', on);
    $('products-compact').setAttribute('aria-checked', String(on));
    window.localStorage.setItem(COMPACT_KEY, on ? '1' : '');
  }

  /** A picture shown large over the page; a click anywhere on it, or Escape, puts it away. */
  function openLightbox(src) {
    if (!src) return;
    const shade = el('div', 'products-lightbox');
    shade.setAttribute('role', 'dialog');
    shade.setAttribute('aria-modal', 'true');
    const img = el('img', 'products-lightbox-img');
    img.src = src;
    img.alt = '';
    shade.appendChild(img);
    function close() {
      shade.remove();
      document.removeEventListener('keydown', onKey, true);
    }
    function onKey(event) {
      if (event.key !== 'Escape') return;
      event.stopPropagation();   // the form behind stays open
      close();
    }
    shade.addEventListener('click', close);
    document.addEventListener('keydown', onKey, true);
    document.body.appendChild(shade);
  }

  /** In compact rows a picture is small: pointing at one shows it larger, beside the pointer, until the pointer leaves it. */
  function initPreview() {
    const tip = el('img', 'products-preview');
    tip.alt = '';
    tip.hidden = true;
    document.body.appendChild(tip);
    const table = $('products-table');
    const body = table.tBodies[0];
    function place(event) {
      const gap = 16;
      const w = tip.offsetWidth, h = tip.offsetHeight;
      const left = event.clientX + gap + w > window.innerWidth ? event.clientX - gap - w : event.clientX + gap;
      tip.style.left = Math.max(0, left) + 'px';
      tip.style.top = Math.max(0, Math.min(event.clientY + gap, window.innerHeight - h)) + 'px';
    }
    body.addEventListener('mouseover', function (event) {
      const img = event.target.closest('.products-thumb');
      if (!img || !table.classList.contains('compact')) return;
      tip.src = img.src;
      tip.hidden = false;
      place(event);
    });
    body.addEventListener('mousemove', function (event) { if (!tip.hidden) place(event); });
    body.addEventListener('mouseout', function (event) { if (event.target.closest('.products-thumb')) tip.hidden = true; });
    window.addEventListener('scroll', function () { tip.hidden = true; }, true);
  }

  /** The button of the view picker: the name of the view, with how many records it holds once they are in. */
  function viewLabel(id) {
    const current = views.find(function (v) { return v.id === id; });
    return current ? current.name + viewCount : '';
  }

  /** The view picker: each view with buttons to rename and delete it, the one in use marked, and after them the way to make one (a view of its
   *  own filter, kept in Fusion Manage). */
  function makeViewPicker() {
    const picker = ns.picker.make({
      className: 'pk-view',
      ariaLabel: t('products.view_label'),
      required: true,
      alignRight: true,
      searchFrom: Infinity,
      placeholder: '',
      search: '',
      label: viewLabel,
      empty: function () { return t('products.no_views'); },
      groups: function () {
        return [{ title: '', items: views.map(function (v) {
          return { value: v.id, label: v.name, actions: [
            { label: t('products.renview_label', { name: v.name }), icon: ['M4 20h4L19 9l-4-4L4 16z', 'M13.5 6.5l4 4'], className: 'pk-act-rename', run: function () { askRenameView(v); } },
            { label: t('products.delview_label', { name: v.name }), icon: ['M4 7h16', 'M10 11v6', 'M14 11v6', 'M6 7l1 13h10l1-13', 'M9 7V4h6v3'], className: 'pk-act-delete', run: function () { askDeleteView(v); } },
          ] };
        }) }];
      },
      footer: function () { return views.length ? { label: t('products.create_view'), icon: ['M12 5v14', 'M5 12h14'], run: openNewView } : null; },
    });
    picker.addEventListener('pick', function () {
      const id = picker.getPicked()[0].value;
      if (id !== view) chooseView(id);
    });
    return picker;
  }

  /** The view picker shows the view in use (without its count, until the rows are in). */
  function paintViews() {
    viewCount = '';
    viewPicker.setPicked(view ? [{ value: view }] : []);
    refreshControls();
  }

  function loadViews() {
    started = true;
    showError('');
    setLoading(t('products.loading_views'));
    ask('products_views', {}, function (answer) {
      if (!answer.ok) { showError(failure(answer)); setStatus(''); return; }
      views = answer.result.views;
      canCreate = answer.result.can_create;
      refreshControls();
      if (!views.length) { view = ''; paintViews(); setStatus(t('products.no_views')); clearRows(); return; }
      const has = function (id) { return views.some(function (v) { return v.id === id; }); };
      view = has(view) ? view : (has(remembered()) ? remembered() : views[0].id);
      paintViews();
      loadRows(1);
    });
  }

  function chooseView(id) {
    view = id;
    remember(id);
    selected = '';
    paintViews();
    loadRows(1);
  }

  // ---- Rows ----------------------------------------------------------------------------

  function clearRows() {
    $('products-table').tHead.textContent = '';
    $('products-table').tBodies[0].textContent = '';
    $('products-count').textContent = '';
    $('products-pager').hidden = true;
  }

  // ---- Column widths: drag the right edge of a header. The first drag fixes every column at the width it has; after that only the one dragged moves.

  const MIN_COLUMN_PX = 60;
  const DEFAULT_COLUMN_PX = 160;
  const PICK_COLUMN_PX = 48;   // the first column: the radio button that picks the row
  const columnWidths = {};   // column id -> px, once any column has been dragged

  function applyWidths(columns) {
    const table = $('products-table');
    const old = table.querySelector('colgroup');
    if (old) old.remove();
    const sized = Object.keys(columnWidths).length > 0;
    table.classList.toggle('sized', sized);
    table.style.width = '';
    if (!sized) return;
    const group = el('colgroup');
    const pick = el('col');
    pick.style.width = PICK_COLUMN_PX + 'px';
    group.appendChild(pick);
    let total = PICK_COLUMN_PX;
    columns.forEach(function (c) {
      const col = el('col');
      const width = columnWidths[c.id] || DEFAULT_COLUMN_PX;
      col.style.width = width + 'px';
      total += width;
      group.appendChild(col);
    });
    table.insertBefore(group, table.firstChild);
    table.style.width = total + 'px';
  }

  function startResize(event, columns, column) {
    event.preventDefault();
    event.stopPropagation();
    if (!Object.keys(columnWidths).length) {
      const heads = $('products-table').tHead.rows[0].cells;
      columns.forEach(function (c, i) { columnWidths[c.id] = Math.round(heads[i + 1].getBoundingClientRect().width); });
    }
    const from = event.clientX;
    const start = columnWidths[column.id];
    function move(e) {
      columnWidths[column.id] = Math.max(MIN_COLUMN_PX, Math.round(start + e.clientX - from));
      applyWidths(columns);
    }
    function stop() {
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', stop);
    }
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', stop);
    applyWidths(columns);
  }

  /** The header row of the table: a title for each column. */
  function paintHeader(columns) {
    const head = $('products-table').tHead;
    head.textContent = '';
    const headRow = el('tr');
    headRow.appendChild(el('th', 'products-pick-th'));
    columns.forEach(function (c) {
      const th = el('th');
      const box = el('div', 'products-th');
      box.appendChild(el('span', 'products-th-title', c.title));
      if (c.filters && c.filters.length) {   // a column of the view's own definition can be filtered
        const button = el('button', 'products-th-filter' + (c.applied && c.applied.filters.length ? ' on' : ''));
        button.type = 'button';
        button.title = t('products.filter_open', { column: c.title });
        button.setAttribute('aria-label', button.title);
        button.appendChild(ns.svg([ns.filters.FUNNEL], 16));
        button.addEventListener('click', function (event) {
          event.stopPropagation();
          if (!busy) ns.filters.openColumn(c, button);
        });
        box.appendChild(button);
      }
      th.appendChild(box);
      const grip = el('span', 'products-th-grip');
      grip.addEventListener('mousedown', function (event) { startResize(event, columns, c); });
      grip.addEventListener('click', function (event) { event.stopPropagation(); });
      th.appendChild(grip);
      headRow.appendChild(th);
    });
    head.appendChild(headRow);
    applyWidths(columns);
  }

  // ---- Pictures: a row names its picture only by number, so each is asked for on its own once the rows are up, a few at a time

  const PICTURES_AT_ONCE = 8;
  const pictureQueue = [];
  let pictureRunning = 0;
  const pictureCache = {};   // 'item:field' -> data uri ('' when there is none)

  function pumpPictures() {
    while (pictureRunning < PICTURES_AT_ONCE && pictureQueue.length) {
      const job = pictureQueue.shift();
      if (!job.cell.isConnected) continue;   // the page of rows has been replaced
      pictureRunning++;
      ask('products_image', { item: job.item, field: job.field, number: job.number }, function (answer) {
        pictureRunning--;
        const uri = answer.ok ? answer.result.image : '';
        pictureCache[job.item + ':' + job.field] = uri;
        showPicture(job.cell, uri);
        pumpPictures();
      });
    }
  }

  function showPicture(cell, uri) {
    cell.textContent = '';
    if (!uri) return;
    const img = el('img', 'products-thumb');
    img.src = uri;
    img.alt = '';
    img.addEventListener('click', function (event) { event.stopPropagation(); openLightbox(uri); });   // the row is not chosen by it
    cell.appendChild(img);
  }

  /** A cell of a row: the formatted text of a formula (through the sanitiser), a picture, or plain text. The first column is the product
   *  itself, a link as in Fusion Manage. */
  function cellOf(row, column, primary, pictures) {
    const td = el('td', primary ? 'products-primary' : '');
    const text = row.cells[column.id] || '';
    const markup = row.html && row.html[column.id];
    if (markup) {
      ns.safeHtml.render(td, markup);
    } else if (pictures[column.id] && text && row.id) {
      const key = row.id + ':' + column.id;
      if (key in pictureCache) showPicture(td, pictureCache[key]);
      else {   // a grey block that shimmers stands in for the picture until it is there
        td.appendChild(el('div', 'products-thumb-skeleton'));
        pictureQueue.push({ cell: td, item: row.id, field: column.id, number: text });   // asked once the rows are in the page (see drawRows)
      }
    } else {
      td.textContent = text;
    }
    return td;
  }

  function drawRows(result) {
    more = result.total ? page * PAGE_SIZE < result.total : result.raw >= PAGE_SIZE;
    const body = $('products-table').tBodies[0];
    clearRows();
    const rows = result.rows;
    const total = result.total || ((page - 1) * PAGE_SIZE + rows.length);
    viewCount = ' (' + total + ')';
    viewPicker.refresh();
    const columns = definition || result.columns;   // the view's own, so an empty view still shows its header
    const pictures = {};   // ids of the columns that hold pictures
    result.columns.forEach(function (c) { if (c.kind === 'image') pictures[c.id] = true; });
    paintHeader(columns);
    rows.forEach(function (r) {
      const tr = el('tr', r.id && r.id === selected ? 'selected' : '');
      tr.tabIndex = 0;
      const pick = el('td', 'products-pick-cell');
      const box = el('div', 'products-pick');
      const radio = el('input');
      radio.type = 'radio';
      radio.name = 'products-pick';
      radio.checked = !!r.id && r.id === selected;
      radio.setAttribute('aria-label', t('products.pick_row', { name: String(r.cells[columns[0] ? columns[0].id : ''] || '') }));
      box.appendChild(radio);
      pick.appendChild(box);
      tr.appendChild(pick);
      columns.forEach(function (c, i) { tr.appendChild(cellOf(r, c, i === 0, pictures)); });
      function choose() {   // one row at a time, as a radio button: another row takes its place; choosing the chosen one again lets it go
        selected = r.id && selected !== r.id ? r.id : '';
        body.querySelectorAll('tr').forEach(function (other) {
          other.classList.toggle('selected', other === tr && !!selected);
          other.querySelector('input[type="radio"]').checked = other === tr && !!selected;
        });
        refreshControls();
      }
      tr.addEventListener('click', function () { choose(); });
      tr.addEventListener('keydown', function (event) { if (event.target === tr && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); choose(); } });
      body.appendChild(tr);
    });
    pumpPictures();
    if (selected && !rows.some(function (r) { return r.id === selected; })) selected = '';   // not on this page
    setStatus(rows.length ? '' : t('products.empty'));
    $('products-count').textContent = t('products.records', { shown: rows.length, total: total });
    $('products-page').textContent = t('products.page', { page: page });
    $('products-pager').hidden = page === 1 && !more;
    refreshControls();
  }

  // ---- Filters -------------------------------------------------------------------------
  // The panel itself is filters.js; here is what it asks of the page: write the changed filters into the view, and read the view again.

  function applyFilterChanges(changes, columns) {   // ``columns``: the keys of the columns to show, in order, when they were chosen (else null)
    selected = '';
    showError('');
    setLoading(t('products.loading_rows'));
    ask('products_filter', { view: view, changes: changes, columns: columns }, function (answer) {
      if (!answer.ok) { showError(failure(answer)); setStatus(''); return; }
      definition = answer.result.columns;
      definitionView = view;
      loadRows(1, true);   // the columns are those just answered
    });
  }

  /** Read the columns of ``id`` and show the header at once, while its rows are still on the way. */
  function readColumns(id) {
    if (definitionView !== id) definition = null;   // what is held is of another view
    const token = ask('products_columns', { view: id }, function (answer) {
      if (token !== columnsToken || id !== view) return;   // a newer read has taken its place
      ns.filters.preload();
      if (!answer.ok) return showError(failure(answer));
      if (!answer.result.columns.length) return;   // the header is then the rows' own
      definition = answer.result.columns;
      definitionView = id;
      refreshControls();
      if (!$('products-table').tBodies[0].rows.length) paintHeader(definition);
    });
    columnsToken = token;
  }

  /** Read page ``number`` of the view chosen (the first also reads the view's columns, unless ``haveColumns``: they were just answered). */
  function loadRows(number, haveColumns) {
    if (!view) return;
    page = number;
    if (number === 1 && !haveColumns) readColumns(view);
    showError('');
    setLoading(t('products.loading_rows'));
    const token = ask('products_rows', { view: view, page: number, size: PAGE_SIZE }, function (answer) {
      if (token !== rowsToken) return;   // a newer read has taken its place
      if (!answer.ok) { showError(failure(answer)); setStatus(''); return; }
      drawRows(answer.result);
    });
    rowsToken = token;
  }

  // ---- A new product -------------------------------------------------------------------
  // The form is the workspace's own, laid out as the Item panel lays out an item: a bar for each section, a label and its control on each
  // line, and the grids of fields as grids. It takes the place of the list, under the same top bar, and is read from Fusion Manage each
  // time it is opened, so a change to the workspace shows at once.

  const MIN_MATRIX_COLUMN_PX = 150;   // a grid column is never squeezed below this: a narrow panel scrolls the grid sideways
  const LABEL_COLUMN_WIDTH = '160px';

  let formFields = [];   // [{id, title, kind, required, input, wrap}] of the form shown
  let formParts = [];    // [{card, rows: [record], grids: [{wrap, records}]}]: what the filters of the form show and hide
  let editing = '';      // the id of the product the form changes ('' while it makes a new one)
  let opened = 0;        // counts the openings of the form, so an answer for one that has been closed is let go

  function formShown() { return !$('products-formview').hidden; }

  function formError(message) { setAlert('products-form-error', message); }

  // ---- Fields of other kinds ---------------------------------------------------------------

  const MAX_IMAGE_MB = 5;   // an image larger than this is not sent
  const SELECT_SEARCH_FROM = 8;   // a list of choices shows its search box from this many on

  /** A field that takes items of another workspace: the shared picker, its list read from Python as it is searched and scrolled; the choice is
   *  shown on the button (or as chips, for several). */
  function linkPicker(field, multi) {
    const root = ns.picker.make({
      className: 'pk-form',
      buttonClass: 'form-input',
      multi: multi,
      placeholder: t('products.link_select'),
      search: t('products.link_search'),
      empty: function () { return t('products.link_empty'); },
      text: {
        clear: t('products.link_clear'),
        loading: t('products.link_loading'),
        showing: function (shown, total) { return t('products.link_showing', { shown: shown.toLocaleString(), total: total.toLocaleString() }); },
      },
      source: function (text, offset, done) {
        ask('products_options', { lookup: field.lookup, offset: offset, text: text }, function (answer) {
          if (!answer.ok) { done({ error: failure(answer) }); return; }
          const page = answer.result;
          done({
            items: page.options.map(function (o) { return { value: o.value, label: o.title }; }),
            next: offset + page.raw,
            total: page.raw ? page.total : 0,   // an empty page is the end, whatever the total says
          });
        });
      },
    });
    root.setValue = function (raw) {   // the items a product holds already, as Fusion Manage gives them: {link, title}, or a list of them
      root.setPicked((Array.isArray(raw) ? raw : [raw]).filter(function (o) { return o.link; })
        .map(function (o) { return { value: o.link, label: o.title || o.link }; }));
    };
    root.getValue = function () {
      const picked = root.getPicked();
      if (!picked.length) return '';
      return multi ? picked.map(function (o) { return { link: o.value }; }) : { link: picked[0].value };
    };
    return root;
  }

  /** A field with a fixed list of choices: the shared picker, with the first entry ("Choose...") taking the choice back. The value is the choice's
   *  value, '' for none. */
  function selectPicker(field) {
    const options = field.options.map(function (o) { return { value: o.value, label: o.title }; });
    const root = ns.picker.make({
      className: 'pk-form',
      buttonClass: 'form-input',
      ariaLabel: field.title,
      searchFrom: SELECT_SEARCH_FROM,
      placeholder: t('products.select_none'),
      search: t('products.link_search'),
      empty: function () { return t('products.link_empty'); },
      text: { clear: t('products.select_none') },
      label: function (value) { return options.find(function (o) { return o.value === value; }).label; },
      groups: function () { return [{ title: '', items: options }]; },
    });
    root.addEventListener('pick', function () { root.dispatchEvent(new Event('change', { bubbles: true })); });   // the form looks at the field again
    root.control = root.querySelector('.pk-btn');   // what the form focuses
    root.setValue = function (raw) {   // a choice the list does not hold leaves it unchosen
      root.setPicked(options.filter(function (o) { return o.value === (raw.link || ''); }));
    };
    root.getValue = function () { const picked = root.getPicked(); return picked.length ? picked[0].value : ''; };
    return root;
  }

  /** An image field: a drop zone with a preview and a button to choose a file. The value is the picture as a data URL, as the publish sends one. */
  function imagePicker() {
    const root = el('div', 'im');
    const zone = el('div', 'im-zone');
    const text = el('span', 'im-text', t('products.image_drop'));
    const picture = el('img', 'im-picture');
    picture.alt = '';
    picture.hidden = true;
    picture.addEventListener('click', function () { openLightbox(picture.src); });
    const skeleton = el('div', 'im-skeleton');   // stands in for the picture a product holds while it is on its way
    skeleton.hidden = true;
    zone.appendChild(text);
    zone.appendChild(picture);
    zone.appendChild(skeleton);
    const choose = el('button', 'btn btn-secondary im-choose', t('products.image_choose'));
    choose.type = 'button';
    const remove = el('button', 'btn btn-secondary im-choose', t('products.image_remove'));
    remove.type = 'button';
    remove.hidden = true;
    const problem = el('p', 'im-problem');
    problem.hidden = true;
    const file = el('input');
    file.type = 'file';
    file.accept = 'image/*';
    file.hidden = true;
    root.appendChild(zone);
    const side = el('div', 'im-side');
    side.appendChild(choose);
    side.appendChild(remove);
    side.appendChild(problem);
    root.appendChild(side);
    root.appendChild(file);

    let data = '';       // the picture chosen here, sent on saving
    let existing = '';   // the picture the product holds, shown until it is cleared (never sent again)
    let loading = false;
    // With a picture there is no Choose button: it is cleared first, and then another can be chosen.
    function show(url) {
      data = url;
      const seen = url || existing;
      picture.src = seen;
      picture.hidden = !seen;
      text.hidden = !!seen || loading;
      skeleton.hidden = !loading;
      choose.hidden = !!seen || loading;
      remove.hidden = !seen;
      root.dispatchEvent(new Event('change', { bubbles: true }));   // the form's footer looks again
    }
    function take(chosen) {
      problem.hidden = true;
      if (!chosen || data || existing || loading) return;
      if (!/^image\//.test(chosen.type) || chosen.size > MAX_IMAGE_MB * 1024 * 1024) {
        problem.textContent = t('products.image_bad', { size: MAX_IMAGE_MB });
        problem.hidden = false;
        return;
      }
      const reader = new FileReader();
      reader.onload = function () { show(String(reader.result)); };
      reader.readAsDataURL(chosen);
    }
    choose.addEventListener('click', function () { file.click(); });
    file.addEventListener('change', function () { take(file.files[0]); file.value = ''; });
    remove.addEventListener('click', function () { existing = ''; show(''); });
    ['dragenter', 'dragover'].forEach(function (name) {
      zone.addEventListener(name, function (event) { event.preventDefault(); zone.classList.add('over'); });
    });
    ['dragleave', 'drop'].forEach(function (name) {
      zone.addEventListener(name, function (event) { event.preventDefault(); zone.classList.remove('over'); });
    });
    zone.addEventListener('drop', function (event) { take(event.dataTransfer.files[0]); });
    root.getValue = function () { return data; };
    root.setLoading = function () { loading = true; show(data); };
    root.setExisting = function (url) { existing = url || ''; loading = false; show(data); };
    return root;
  }

  /** Is ``input`` a control of its own that a label can point at (a radio group and a picker are not: they hold several)? */
  function aimable(kind, input) { return kind !== 'radio' && !input.getValue; }

  /** The control for one field. */
  function control(field) {
    let input;
    if (field.kind === 'link' || field.kind === 'links') { input = linkPicker(field, field.kind === 'links'); }
    else if (field.kind === 'image') { input = imagePicker(); }
    else if (field.kind === 'textarea') { input = el('textarea', 'form-input'); input.rows = 2; }
    else if (field.kind === 'select') { input = selectPicker(field); }
    else if (field.kind === 'radio') {   // a short list is all in view, as in Fusion Manage
      input = el('div', 'form-radios');
      input.setAttribute('role', 'radiogroup');
      input.setAttribute('aria-label', field.title);
      field.options.forEach(function (o) {
        const label = el('label', 'form-radio');
        const radio = el('input');
        radio.type = 'radio';
        radio.name = 'f-' + field.id;
        radio.value = o.value;
        label.appendChild(radio);
        label.appendChild(el('span', '', o.title));
        input.appendChild(label);
      });
    } else if (field.kind === 'checkbox') { input = el('input', 'form-check'); input.type = 'checkbox'; }
    else {
      input = el('input', 'form-input');
      input.type = field.kind === 'date' ? 'date' : (field.kind === 'integer' || field.kind === 'number' ? 'number' : 'text');
      if (field.kind === 'integer') input.step = '1';
      else if (field.kind === 'number') input.step = 'any';
      input.autocomplete = 'off';
      input.spellcheck = false;
    }
    input.id = 'f-' + field.id;
    if (aimable(field.kind, input)) input.setAttribute('aria-label', field.title);
    return field.max_length ? counted(input, field.max_length) : input;
  }

  /** ``input`` (a text box) with a count of its characters against ``limit`` in its corner: it stops at the limit and the count warns as it nears. */
  function counted(input, limit) {
    const wrap = el('div', 'fc' + (input.tagName === 'TEXTAREA' ? ' fc-area' : ''));
    const count = el('span', 'fc-count');
    count.setAttribute('aria-live', 'off');
    input.maxLength = limit;
    function update() {
      const n = input.value.length;
      count.textContent = t('products.char_count', { used: n, max: limit });
      count.classList.toggle('near', n >= limit * 0.9 && n < limit);
      count.classList.toggle('full', n >= limit);
    }
    input.addEventListener('input', update);
    wrap.appendChild(input);
    wrap.appendChild(count);
    wrap.control = input;   // what the form reads and focuses
    update();
    return wrap;
  }

  /** The message under a field that is not right, for the form to fill. */
  function errorLine() {
    const line = el('p', 'pf-error');
    line.hidden = true;
    line.setAttribute('role', 'alert');
    return line;
  }

  /** The control of ``field`` with the message under it and the element that shows it invalid. ``lookup(id)`` gives the checks another field of the form. */
  function makeRecord(field, wrap, lookup) {
    return { id: field.id, title: field.title, kind: field.kind, required: field.required, validators: field.validators,
             input: control(field), wrap: wrap, error: errorLine(), lookup: lookup };
  }

  /** Tell the person what is wrong with a field when they leave it (not before: an empty required field is not wrong yet). */
  function watchFocus(record) {
    record.wrap.addEventListener('focusout', function () { if (!blank(valueOf(record)) || record.wrap.classList.contains('invalid')) showState(record); });
  }

  /** Make the control of ``field`` and keep it in ``formFields``; what is wrong is told again as it is put right. Answers the record. */
  function addField(field, wrap) {
    const record = makeRecord(field, wrap, lookupField);
    formFields.push(record);
    watchFocus(record);
    ['input', 'change'].forEach(function (name) {
      wrap.addEventListener(name, function () { if (wrap.classList.contains('invalid')) showState(record); });
    });
    return record;
  }

  /** Does the field pass the filters above the form (``filters``: ``{text, required}``)? */
  function fieldShown(record, filters) {
    if (filters.text && record.title.toLowerCase().indexOf(filters.text) < 0) return false;
    return !filters.required || !!record.required;
  }

  /** Show the fields that pass the filters, and the sections and grids that still have one. */
  function applyFormFilters() {
    const filters = { text: $('products-fields-search').value.trim().toLowerCase(), required: $('products-fields-required').checked };
    let any = false;
    formParts.forEach(function (part) {
      let shown = 0;
      part.rows.forEach(function (record) {
        const on = fieldShown(record, filters);
        record.wrap.classList.toggle('pf-filtered', !on);
        if (on) shown++;
      });
      part.grids.forEach(function (grid) {
        const on = grid.records.some(function (record) { return fieldShown(record, filters); });
        grid.wrap.classList.toggle('pf-filtered', !on);
        if (on) shown++;
      });
      part.card.classList.toggle('pf-filtered', !shown);
      if (shown) any = true;
    });
    $('products-fields-none').hidden = any || !formFields.length;
  }

  function resetFormFilters() {
    $('products-fields-search').value = '';
    $('products-fields-required').checked = false;
  }

  /** The other field of the form called ``id``, as the checks look at it. */
  function lookupField(id) {
    const other = formFields.find(function (f) { return f.id === id; });
    return other ? { title: other.title, value: valueOf(other) } : null;
  }

  /** Check one field and show what is wrong with it beside it. Answers the message ('' when it is fine). */
  function showState(record) {
    const message = ns.validators.check(record, valueOf(record), record.lookup);
    record.error.textContent = message;
    record.error.hidden = !message;
    record.wrap.classList.toggle('invalid', !!message);
    return message;
  }

  // ---- Footer: the form checked live -------------------------------------------------------

  let sending = false;

  /** Look at the whole form without marking any field: what is required, what is not right, and what is left to Fusion Manage. */
  function readiness() {
    const needed = [];
    const problems = [];
    formFields.forEach(function (field) {
      const value = valueOf(field);
      const empty = blank(value);
      if (field.required) needed.push({ field: field, done: !empty });
      const message = ns.validators.check(field, value, field.lookup);
      if (message && !(field.required && empty)) problems.push({ field: field, message: message });
    });
    const missing = needed.filter(function (n) { return !n.done; }).length;
    return { needed: needed, problems: problems, open: missing + problems.length };
  }

  /** Show the form's state in the footer, and let Save be pressed only when nothing is left to fix. */
  function refreshFooter() {
    const footer = $('products-footer');
    const text = $('products-footer-text');
    if (!formFields.length) {
      footer.dataset.state = 'loading';
      text.textContent = formShown() && !$('products-form-body').querySelector('.form-empty') ? t('products.footer_loading') : '';
      $('products-create').disabled = true;
      return;
    }
    const now = readiness();
    footer.dataset.state = now.open ? 'issues' : 'ready';
    text.textContent = now.open ? t('products.footer_issues', { n: now.open })
      : t('products.footer_ready');
    $('products-create').disabled = sending || now.open > 0;
    if (!$('products-checklist-modal').hidden) paintChecklist(now);
  }

  const scheduleFormFilters = debounced(applyFormFilters, FORM_DEBOUNCE_MS);
  const scheduleFooter = debounced(refreshFooter, FORM_DEBOUNCE_MS);   // after the control has taken the change, and the typing has paused

  /** Take the person to a field and say what is wrong with it. */
  function goTo(record, keepMessage) {
    if (!keepMessage) showState(record);
    const target = record.input.control || record.input.querySelector('input, textarea, button, select') || record.input;
    target.focus();
    target.scrollIntoView({ block: 'center' });
  }

  function checklistGroup(title, items) {
    const group = el('section', 'pf-check-group');
    group.appendChild(el('h3', '', title));
    items.forEach(function (item) { group.appendChild(item); });
    return group;
  }

  function checklistItem(record, mark, text, jump) {
    const item = el(jump ? 'button' : 'div', 'pf-check-item ' + mark);
    if (jump) {
      item.type = 'button';
      item.addEventListener('click', function () { closeChecklist(); goTo(record); });
    }
    item.appendChild(el('span', 'pf-check-mark', mark === 'done' ? '✓' : '!'));
    const words = el('span', 'pf-check-text');
    words.appendChild(el('b', '', record.title));
    if (text) words.appendChild(el('span', '', text));
    item.appendChild(words);
    return item;
  }

  /** The list behind the footer: every required field, everything entered that is not right, and what Fusion Manage checks for itself. */
  function paintChecklist(now) {
    const body = $('products-checklist-body');
    body.textContent = '';
    const done = now.needed.filter(function (n) { return n.done; }).length;
    body.appendChild(checklistGroup(t('products.check_required', { done: done, total: now.needed.length }),
      now.needed.length ? now.needed.map(function (n) { return checklistItem(n.field, n.done ? 'done' : 'bad', '', !n.done); })
        : [el('p', 'muted', t('products.check_required_none'))]));
    body.appendChild(checklistGroup(t('products.check_attention', { n: now.problems.length }),
      now.problems.length ? now.problems.map(function (p) { return checklistItem(p.field, 'bad', p.message, true); })
        : [el('p', 'muted', t('products.check_attention_none'))]));
  }

  function openChecklist() {
    $('products-checklist-modal').hidden = false;
    paintChecklist(readiness());
    $('products-checklist-close').focus();
  }

  function closeChecklist() { $('products-checklist-modal').hidden = true; }

  /** Saving: three bouncing balls over the form until Fusion Manage answers. */
  function setSending(on) {
    sending = on;
    $('products-sending').hidden = !on;
    $('products-form').setAttribute('aria-busy', String(on));
    $('products-form-cancel').disabled = on;
    refreshFooter();
  }

  /** The round "i" beside a field that has something to say about itself. */
  function infoIcon(text) {
    const icon = el('span', 'form-info', 'i');
    icon.title = text;
    icon.setAttribute('role', 'img');
    icon.setAttribute('aria-label', text);
    return icon;
  }

  function matrixTable(matrix, records) {
    const table = el('table', 'item-matrix');
    const cols = el('colgroup');
    for (let i = 0; i <= matrix.columns.length; i++) {   // the first is the column of row labels, a little wider
      const col = el('col');
      if (i === 0) col.style.width = LABEL_COLUMN_WIDTH;
      cols.appendChild(col);
    }
    table.appendChild(cols);
    table.style.minWidth = ((matrix.columns.length + 1) * MIN_MATRIX_COLUMN_PX) + 'px';
    const head = el('tr');
    head.appendChild(el('th'));
    matrix.columns.forEach(function (c) {
      const th = el('th', '', c);
      th.title = c;
      head.appendChild(th);
    });
    table.appendChild(head);
    matrix.rows.forEach(function (row, i) {
      const tr = el('tr');
      tr.appendChild(el('td', 'item-matrix-label', matrix.labels[i]));
      row.forEach(function (field) {
        const td = el('td', 'form-cell');
        if (field && field.kind === 'auto') {
          td.appendChild(autoBox(field));
        } else if (field) {
          const record = addField(field, td);
          records.push(record);
          td.appendChild(record.input);
          td.appendChild(record.error);
          if (field.required) td.title = field.title + ' *';
        }
        tr.appendChild(td);
      });
      table.appendChild(tr);
    });
    const wrap = el('div', 'item-matrix-wrap');   // a wide grid scrolls sideways
    wrap.appendChild(table);
    return wrap;
  }

  /** What a field the add-in fills in itself shows in place of a control: a disabled box with the message. */
  function autoBox(field) {
    const box = el('div', 'form-input form-auto', field.description);
    box.setAttribute('aria-disabled', 'true');
    return box;
  }

  function clearFormBody() {
    const body = $('products-form-body');
    body.textContent = '';
    body.classList.remove('loading');
  }

  /** A line of the form for ``field``: its row (a tall control is aligned to the top), its label (starred when required) and the box for the control. */
  function fieldLine(field) {
    const row = el('div', 'pf-field' + (['textarea', 'radio', 'image', 'links'].indexOf(field.kind) >= 0 ? ' top' : ''));
    const label = el('label', 'pf-label');
    if (field.required) label.appendChild(el('span', 'form-star', '* '));
    label.appendChild(document.createTextNode(field.title));
    const value = el('div', 'pf-value');
    row.appendChild(label);
    row.appendChild(value);
    return { row: row, label: label, value: value };
  }

  /** Put the control of ``record`` and its message in ``line``, and point the label at the control where it can. */
  function fillLine(line, record) {
    if (aimable(record.kind, record.input)) line.label.htmlFor = (record.input.control || record.input).id;
    line.value.appendChild(record.input);
    line.value.appendChild(record.error);
  }

  function paintForm(form) {
    clearFormBody();
    const body = $('products-form-body');
    formFields = [];
    formParts = [];
    form.sections.forEach(function (section, index) {
      const content = el('div');
      const part = { card: null, rows: [], grids: [] };
      formParts.push(part);
      section.fields.forEach(function (field) {
        const line = fieldLine(field);
        if (field.kind === 'auto' || field.kind === 'info') {   // not editable, but the filters still apply to it
          if (field.kind === 'auto') line.value.appendChild(autoBox(field));
          part.rows.push({ title: field.title, required: false, wrap: line.row });
        } else {
          const record = addField(field, line.row);
          part.rows.push(record);
          fillLine(line, record);
        }
        line.row.appendChild(field.description ? infoIcon(field.description) : el('span'));
        content.appendChild(line.row);
      });
      section.matrices.forEach(function (matrix) {
        const records = [];
        const wrap = matrixTable(matrix, records);
        part.grids.push({ wrap: wrap, records: records });
        content.appendChild(wrap);
      });
      // as the workspace has it: a section it holds folded starts folded
      part.card = ns.section.make(section.title + ' (' + (index + 1) + ' of ' + form.sections.length + ')', content, { folded: section.collapsed });
      body.appendChild(part.card);
    });
    if (!formFields.length) body.appendChild(el('p', 'form-empty', t('products.form_empty')));
    applyFormFilters();
    refreshFooter();
  }

  function showLoading() {
    const body = $('products-form-body');
    body.textContent = '';
    body.classList.add('loading');   // the balls are in the middle of the page, not at the top
    const loader = el('div', 'loader form-loader');
    loader.appendChild(ns.balls(t('products.loading_form')));
    loader.appendChild(el('p', 'muted', t('products.loading_form')));
    body.appendChild(loader);
  }

  function showPage(form) {
    $('products-formview').hidden = !form;
    document.querySelector('.products').hidden = form;
  }

  /** The text of a value Fusion Manage holds: a picklist or a link is an object with a title. */
  function plain(raw) {
    return typeof raw === 'object' ? String(raw.title) : String(raw);
  }

  /** Put what a product holds in the control of a field. A picture is shown as it is held, and sent only when a new one is chosen. */
  function setFieldValue(record, raw) {
    if (raw === null || raw === undefined) return;
    const input = record.input;
    if (record.kind === 'image') {   // the picture is asked for on its own, as the list's cells do
      if (!raw.link) return;
      const asked = opened;
      input.setLoading();   // every picture is asked for at once: the item has given the link to each
      ask('products_picture', { link: raw.link }, function (answer) {
        if (asked === opened) input.setExisting(answer.ok ? answer.result.image : '');
      });
      return;
    }
    if (input.setValue) { input.setValue(raw); return; }
    const target = input.control || input;
    const link = raw.link || '';
    if (record.kind === 'checkbox') target.checked = raw === true || raw === 'true';
    else if (record.kind === 'radio') Array.prototype.forEach.call(input.querySelectorAll('input'), function (r) { r.checked = r.value === link; });
    else if (record.kind === 'date') target.value = plain(raw).slice(0, 10);
    else target.value = plain(raw);
    target.dispatchEvent(new Event('input', { bubbles: true }));   // the count of characters and the footer look again
  }

  // ---- Assigning ------------------------------------------------------------------------
  // The open design becomes the Primary Component of the chosen product. When the product has one already, the person is asked whether to
  // replace it or to add the design as a variant (``mode`` ``replace`` or ``variant``).

  const ASSIGNING_DELAY_MS = 250;   // an assign that is done sooner shows no dialog, so it does not flash
  let assigningTimer = 0;

  /** ``checking``: the first request, that looks at what the product holds; after a choice it is the update that is named. */
  function setAssigning(on, checking) {
    assigning = on;
    clearTimeout(assigningTimer);
    $('products-assigning-title').textContent = checking ? t('products.checking_title') : t('products.assigning_title');
    $('products-assigning-text').textContent = checking ? t('products.checking_text') : t('products.assigning_text');
    if (on) assigningTimer = setTimeout(function () { $('products-assigning').hidden = false; }, ASSIGNING_DELAY_MS);
    else $('products-assigning').hidden = true;
    $('products-assign').textContent = on ? t('products.assigning') : t('products.assign');
    refreshControls();
  }

  function closeAssignAsk() { $('products-assign-modal').hidden = true; assignAsk++; }

  let assignChoice = '';      // 'replace', 'variant', or '' while nothing is chosen
  let assignStep = 'choose';  // where the person is in the question: choose, review (Replace) or details (the new row)
  let assignInfo = null;      // what the product holds of components, and how the design stands to it (``products_inspect``)
  let assignAsk = 0;          // numbers the times the question is asked, so an answer for an earlier one is dropped
  let variantSpecs = null;    // the columns of the Variants grid to fill in, once read
  let variantRecords = null;  // the controls for them in the question: null until they are there

  /** Press Assign Product: look at what the product holds, then assign at once when nothing is in the way, else ask what to do. */
  function startAssign() {
    showError('');
    setAssigning(true, true);
    ask('products_inspect', { item: selected }, function (answer) {
      setAssigning(false);
      if (!answer.ok) { showError(failure(answer)); return; }
      const info = answer.result;
      if (!info.primary && !info.rows.some(function (r) { return r.state !== 'other'; })) { assign(''); return; }
      openAssign(info);
    });
  }

  function setCard(id, off, sub) {
    $(id).disabled = off;
    $(id + '-sub').textContent = sub;
  }

  /** A component with its revision: ``PN-1 - Axle`` and a badge. */
  function revisionBadge(badge, label) {
    badge.textContent = label || '';
    badge.hidden = !label;
  }

  /** What the texts of the question fill in: the design's number, and the primary component the product has. */
  function namesOf(info) {
    return { number: info.number, current: info.primary ? info.primary.title : '' };
  }

  function openAssign(info) {
    assignInfo = info;
    assignAsk++;
    variantRecords = null;
    const product = info.product || t('products.assign_this_product');
    const names = namesOf(info);
    $('products-assign-title').textContent = t('products.assign_title_open', { product: product, number: info.number });
    const primarySame = info.primary_state === 'same';
    const variantSame = info.rows.some(function (r) { return r.state === 'same'; });
    setCard('products-assign-replace', primarySame, primarySame ? t('products.assign_card_primary_same') : t('products.assign_replace_sub'));
    setCard('products-assign-variant', variantSame, variantSame ? t('products.assign_card_variant_same') : t('products.assign_variant_sub'));
    paintReplacePane(info, names);
    paintRevisions(info, names);
    $('products-assign-keep-row').hidden = $('products-assign-options-title').hidden = !info.primary || info.primary_state !== 'other';
    $('products-assign-keep').checked = true;
    $('products-assign-keep-text').textContent = t('products.assign_keep', names);
    $('products-assign-fields-list').textContent = '';
    $('products-assign-fields-note').hidden = true;
    markChoice('');
    goStep('choose');
    loadVariantFields();
    $('products-assign-modal').hidden = false;
    const first = info.primary ? 'variant' : 'replace';   // a product with a primary gets a variant; one without gets its primary
    if (!$('products-assign-' + first).disabled) { chooseAssign(first); $('products-assign-' + first).focus(); }
  }

  /** The right-hand pane of Replace: the primary component the product has, and what takes its place. */
  function paintReplacePane(info, names) {
    const p = info.primary;
    $('products-assign-cur-name').textContent = p ? p.title : t('products.assign_no_primary');
    revisionBadge($('products-assign-cur-rev'), p ? p.revision : '');
    $('products-assign-new-name').textContent = info.title || info.number;
    revisionBadge($('products-assign-new-rev'), info.revision);
    const note = $('products-assign-replace-note');   // nothing is said of a plain change: the two lines show it
    note.textContent = info.primary_state === 'same' ? t('products.assign_same_note', names)
      : info.primary_state === 'revision' ? t('products.assign_revision_note', { number: info.number, have: (p.revision || p.title), want: (info.revision || info.title) })
      : '';
    note.hidden = !note.textContent;
  }

  /** What is under the cards when the design is added as a variant and another revision of it is one already: each, with the way to update it. */
  function paintRevisions(info, names) {
    const box = $('products-assign-revisions');
    box.textContent = '';
    const others = info.rows.filter(function (r) { return r.state === 'revision'; });
    box.dataset.has = others.length ? '1' : '';
    if (!others.length) return;
    box.appendChild(el('p', 'pfa-note', t('products.assign_variant_revision_note', names)));
    others.forEach(function (r) {
      const line = el('div', 'pfa-rev');
      line.appendChild(el('span', 'pfa-rev-name', r.title));
      line.appendChild(el('span', 'pfa-badge warn', t('products.assign_state_revision')));
      const update = el('button', 'btn btn-secondary pfa-rev-update', t('products.assign_update_revision', { revision: info.revision || info.title }));
      update.type = 'button';
      update.addEventListener('click', function () { closeAssignAsk(); assign('variant_update', {}, r.id); });
      line.appendChild(update);
      box.appendChild(line);
    });
  }

  function markChoice(which) {
    assignChoice = which;
    $('products-assign-replace').setAttribute('aria-checked', String(which === 'replace'));
    $('products-assign-variant').setAttribute('aria-checked', String(which === 'variant'));
  }

  /** Mark one of the two cards as chosen (the person goes on with Next). */
  function chooseAssign(which) {
    markChoice(which);
    syncAssign();
  }

  /** Whether a row is to be added to the Variants grid with this choice: the design as a variant, or the one replaced kept as a variant. */
  function addsRow() {
    return assignChoice === 'variant' || (assignChoice === 'replace' && !$('products-assign-keep-row').hidden && $('products-assign-keep').checked);
  }

  /** The steps of the question for the choice made: setting the primary is reviewed; a row added to the Variants grid has details to fill in. */
  function stepsOf() {
    if (!assignChoice) return ['choose'];
    const details = addsRow() && (variantRecords === null || variantRecords.length > 0) ? ['details'] : [];
    return (assignChoice === 'replace' ? ['choose', 'review'] : ['choose']).concat(details);
  }

  /** Show one step: its part of the dialog, and what is said above it. */
  function goStep(step) {
    assignStep = step;
    $('products-assign-card').dataset.step = step;
    $('products-assign-choices').hidden = step !== 'choose';
    $('products-assign-panel').hidden = step === 'choose';
    $('products-assign-pane-replace').hidden = step !== 'review';
    $('products-assign-fields').hidden = step !== 'details';
    const names = namesOf(assignInfo);
    $('products-assign-text').textContent = step === 'review' ? t('products.assign_lead_review')
      : step === 'details' ? t('products.assign_lead_details')
      : (assignInfo.primary ? t('products.assign_lead', names) : t('products.assign_lead_open', names));
    syncAssign();
  }

  function nextAssign() {
    if ($('products-assign-confirm').disabled) return;
    const steps = stepsOf();
    const at = steps.indexOf(assignStep);
    if (at < steps.length - 1) goStep(steps[at + 1]); else confirmAssign();
  }

  function backAssign() {
    const steps = stepsOf();
    const at = steps.indexOf(assignStep);
    if (at > 0) goStep(steps[at - 1]);
  }

  /** A grid has no other field of the form to check a column against. */
  function noOtherField() { return null; }

  /** Show the columns of the Variants grid to fill in, in the question. */
  function paintVariantFields(specs) {
    const list = $('products-assign-fields-list');
    list.textContent = '';
    const records = [];
    specs.forEach(function (field) {
      if (field.kind === 'auto' || field.kind === 'info') return;
      const line = fieldLine(field);
      const record = makeRecord(field, line.row, noOtherField);
      fillLine(line, record);
      if (field.description) line.label.appendChild(infoIcon(field.description));   // what the column is for, beside its name
      watchFocus(record);
      list.appendChild(line.row);
      records.push(record);
    });
    return records;
  }

  /** Read the columns of the Variants grid (once), and show them in the question. */
  function loadVariantFields() {
    const note = $('products-assign-fields-note');
    function show(specs, message) {
      variantRecords = paintVariantFields(specs);
      note.textContent = message || (variantRecords.length ? '' : t('products.assign_fields_none'));
      note.hidden = !note.textContent;
      syncAssign();
    }
    if (variantSpecs) { show(variantSpecs, ''); return; }
    note.textContent = t('products.assign_fields_loading');
    note.hidden = false;
    const mine = assignAsk;
    ask('products_variant_form', {}, function (answer) {
      if (mine !== assignAsk) return;
      if (answer.ok) { variantSpecs = answer.result.fields; show(variantSpecs, ''); }
      else show([], failure(answer));
    });
  }

  /** The steps of the question as a row of numbered dots: the ones done are ticked, the one in view is filled. */
  function paintStepper(steps, at) {
    const names = { choose: t('products.assign_step_choose'), review: t('products.assign_step_review'),
                    details: t('products.assign_step_details') };
    const list = $('products-assign-stepper');
    list.textContent = '';
    steps.forEach(function (step, i) {
      const item = el('li', i < at ? 'done' : (i === at ? 'current' : ''));
      if (i === at) item.setAttribute('aria-current', 'step');
      const dot = el('span', 'pfa-dot');
      if (i < at) dot.appendChild(ns.svg([CHECK], 14)); else dot.textContent = String(i + 1);
      item.appendChild(dot);
      item.appendChild(el('span', 'pfa-step-name', names[step]));
      list.appendChild(item);
    });
  }

  /** The state of the question: the step's buttons, and Next or Confirm pressable once the step is done. */
  function syncAssign() {
    const steps = stepsOf();
    const at = Math.max(0, steps.indexOf(assignStep));
    const last = at === steps.length - 1 && assignStep !== 'choose';
    paintStepper(steps, at);
    $('products-assign-revisions').hidden = assignStep !== 'choose' || assignChoice !== 'variant' || !$('products-assign-revisions').dataset.has;   // under the cards, once the variant is chosen
    $('products-assign-back').hidden = assignStep === 'choose';
    $('products-assign-confirm').textContent = last ? t('products.assign_confirm') : t('products.assign_next');
    let ready = assignStep === 'choose' ? !!assignChoice : true;
    if (assignStep === 'details') {
      ready = variantRecords !== null && variantRecords.every(function (r) {
        const v = valueOf(r);
        return blank(v) ? !r.required : !ns.validators.check(r, v, r.lookup);
      });
    }
    $('products-assign-confirm').disabled = !ready;
  }

  function confirmAssign() {
    const mode = assignChoice === 'variant' ? 'variant' : (addsRow() ? 'replace_move' : 'replace');
    const row = {};
    if (addsRow()) variantRecords.forEach(function (r) { const v = valueOf(r); if (!blank(v)) row[r.id] = v; });
    closeAssignAsk();
    assign(mode, row);
  }

  /** Show how much of a name box's limit is used ("12/30"), in red once it is all used. */
  function showChars(input, counter) {
    const used = input.value.length;
    counter.textContent = used + '/' + input.maxLength;
    counter.classList.toggle('full', used >= input.maxLength);
  }

  // ---- Rename a view -------------------------------------------------------------------

  let renaming = null;   // {id, name, working} while the question is open

  function closeRenameView() {
    if (renaming && renaming.working) return;
    renaming = null;
    $('products-renview-modal').hidden = true;
  }

  function syncRename() {
    showChars($('products-renview-name'), $('products-renview-chars'));
    const name = $('products-renview-name').value.trim();
    $('products-renview-ok').disabled = renaming.working || !name || name === renaming.name || name.length > $('products-renview-name').maxLength;
  }

  function askRenameView(v) {
    // Views of one name are listed with their id after it, to tell them apart: it is not part of the name.
    const suffix = ' (' + v.id + ')';
    const name = v.name.slice(-suffix.length) === suffix ? v.name.slice(0, -suffix.length) : v.name;
    renaming = { id: v.id, name: name, working: false };
    $('products-renview-name').value = name;
    setAlert('products-renview-error', '');
    $('products-renview-modal').hidden = false;
    $('products-renview-name').select();
    syncRename();
  }

  function renameView() {
    if ($('products-renview-ok').disabled) return;
    const mine = renaming;
    mine.working = true;
    setAlert('products-renview-error', '');
    syncRename();
    ask('products_rename_view', { view: mine.id, name: $('products-renview-name').value.trim() }, function (answer) {
      mine.working = false;
      if (!answer.ok) {
        setAlert('products-renview-error', failure(answer));
        syncRename();
        return;
      }
      closeRenameView();
      loadViews();   // the view stays the one shown; the list has its new name
    });
  }

  // ---- Delete a view -------------------------------------------------------------------

  let deleting = null;   // {id, name, working} while the question is open

  function closeDeleteView() {
    if (deleting && deleting.working) return;
    deleting = null;
    $('products-delview-modal').hidden = true;
  }

  function askDeleteView(v) {
    deleting = { id: v.id, name: v.name, working: false };
    $('products-delview-text').textContent = t('products.delview_text', { name: v.name });
    setAlert('products-delview-error', '');
    $('products-delview-ok').disabled = false;
    $('products-delview-modal').hidden = false;
    $('products-delview-cancel').focus();
  }

  function deleteView() {
    const mine = deleting;
    mine.working = true;
    $('products-delview-ok').disabled = true;
    setAlert('products-delview-error', '');
    ask('products_delete_view', { view: mine.id }, function (answer) {
      mine.working = false;
      if (!answer.ok) {
        setAlert('products-delview-error', failure(answer));
        $('products-delview-ok').disabled = false;
        return;
      }
      closeDeleteView();
      if (view === mine.id) { view = ''; remember(''); selected = ''; }   // the list is read again and shows another view
      loadViews();
    });
  }

  // ---- Create New View -----------------------------------------------------------------
  // A name and the columns to show: the chosen columns on the left (the columns of the view in use to start with, in their order, which can be
  // moved or removed), every other field a view can show on the right, by section. The view is made without filters: they are set on it
  // afterwards, as on any view.

  let newView = null;   // while the dialog is open: {fields: [{key, title, group}] (null until read), chosen: [keys, in the order shown], making}

  function closeNewView() {
    if (newView && newView.making) return;
    newView = null;
    $('products-newview-modal').hidden = true;
  }

  function newViewError(message) { setAlert('products-newview-error', message); }

  /** The button can be pressed once there is a name and a column. */
  function syncNewView() {
    const count = newView.chosen.length;
    $('products-newview-count').textContent = newView.fields ? t('products.newview_count', { n: count }) : '';
    $('products-newview-clear').hidden = !count;
    showChars($('products-newview-name'), $('products-newview-chars'));
    const name = $('products-newview-name').value.trim();
    $('products-newview-create').disabled = newView.making || !newView.fields || !count || !name || name.length > $('products-newview-name').maxLength;
  }

  /** A small round button with an icon (``paths``) that says what it does to a screen reader. */
  function newViewIcon(paths, label, onClick) {
    const button = el('button', 'pf-newview-icon');
    button.type = 'button';
    button.setAttribute('aria-label', label);
    button.title = label;
    button.appendChild(ns.svg(paths, 14));
    button.addEventListener('click', onClick);
    return button;
  }

  /** Move a chosen column to ``to`` (its place among the chosen), and show the lists again with the keyboard on the moved row. */
  function moveChosen(from, to) {
    const keys = newView.chosen;
    if (to < 0 || to >= keys.length) return;
    keys.splice(to, 0, keys.splice(from, 1)[0]);
    paintNewView();
    $('products-newview-chosen').querySelectorAll('.pf-newview-row')[to].focus();
  }

  /** Drag a chosen column by its grip to a new place (see sortable.js). */
  function dragChosen(event, row) {
    ns.sortable.start(event, row, $('products-newview-chosen'), '.pf-newview-row', moveChosen);
  }

  function chooseField(key) {
    newView.chosen.push(key);
    paintNewView();
  }

  function unchooseField(key) {
    newView.chosen = newView.chosen.filter(function (k) { return k !== key; });
    paintNewView();
  }

  /** Repaint ``list`` with ``fill(list)`` and keep it scrolled where it was. */
  function repaintList(list, fill) {
    const top = list.scrollTop;
    list.textContent = '';
    fill(list);
    list.scrollTop = top;
  }

  /** The two lists: the columns chosen, in the order the view will show them (left), and the fields still to choose from that match the search,
   *  under their section (right). */
  function paintNewView() {
    const fields = newView.fields;
    repaintList($('products-newview-chosen'), function (list) {
      if (!fields) return;
      const byKey = {};
      fields.forEach(function (f) { byKey[f.key] = f; });
      if (!newView.chosen.length) list.appendChild(el('p', 'pf-newview-note', t('products.newview_empty_selected')));
      newView.chosen.forEach(function (key, index) {
        const field = byKey[key];
        const row = el('div', 'pf-newview-row');
        row.tabIndex = 0;
        row.title = t('products.newview_row_hint');
        const grip = el('span', 'pf-newview-grip');
        grip.appendChild(ns.svg(ns.sortable.GRIP, 16));
        grip.addEventListener('pointerdown', function (event) { dragChosen(event, row); });
        row.appendChild(grip);
        row.appendChild(el('span', 'pf-newview-order', String(index + 1)));
        const name = el('span', 'pf-newview-name', field.title);
        if (field.group) name.title = field.group;
        row.appendChild(name);
        row.appendChild(newViewIcon(['M6 6l12 12', 'M18 6L6 18'], t('products.newview_remove', { title: field.title }), function () { unchooseField(key); }));
        row.addEventListener('keydown', function (event) {   // Alt+Up and Alt+Down move the row, Delete removes it
          if (event.target !== row) return;
          if (event.altKey && (event.key === 'ArrowUp' || event.key === 'ArrowDown')) { event.preventDefault(); moveChosen(index, index + (event.key === 'ArrowUp' ? -1 : 1)); }
          else if (event.key === 'Delete') { event.preventDefault(); unchooseField(key); }
        });
        list.appendChild(row);
      });
    });
    repaintList($('products-newview-list'), function (list) {
      if (!fields) { list.appendChild(el('p', 'pf-newview-note', t('products.newview_loading'))); return; }
      const words = $('products-newview-search').value.trim().toLowerCase();
      const left = fields.filter(function (f) { return newView.chosen.indexOf(f.key) < 0; });
      const shown = left.filter(function (f) { return !words || (f.title + ' ' + f.group).toLowerCase().indexOf(words) >= 0; });
      if (!shown.length) { list.appendChild(el('p', 'pf-newview-note', left.length ? t('products.newview_none') : t('products.newview_all_added'))); return; }
      let group = null;
      shown.forEach(function (f) {
        if (f.group !== group) { group = f.group; if (group) list.appendChild(el('h4', 'pf-newview-group', group)); }
        const button = el('button', 'pf-newview-field');
        button.type = 'button';
        button.title = t('products.newview_add', { title: f.title });
        button.appendChild(el('span', 'pf-newview-name', f.title));
        button.appendChild(ns.svg(['M12 5v14', 'M5 12h14'], 14));
        button.addEventListener('click', function () { chooseField(f.key); });
        list.appendChild(button);
      });
    });
    syncNewView();
  }

  function openNewView() {
    if (busy) return;
    newView = { fields: null, chosen: [], making: false };
    $('products-newview-name').value = t('products.newview_default_name');
    $('products-newview-search').value = '';
    newViewError('');
    $('products-newview-modal').hidden = false;
    $('products-newview-name').select();
    paintNewView();
    syncNewView();
    const mine = newView;
    ask('products_fields', {}, function (answer) {
      if (newView !== mine) return;   // closed while it was read
      if (!answer.ok) { newViewError(failure(answer)); mine.fields = []; }
      else mine.fields = answer.result.fields;
      const known = new Set(mine.fields.map(function (f) { return f.key; }));
      mine.chosen = (definition || []).map(function (c) { return c.key; }).filter(function (key) { return known.has(key); });
      paintNewView();
      syncNewView();
    });
  }

  function makeNewView() {
    if ($('products-newview-create').disabled) return;
    const mine = newView;
    const name = $('products-newview-name').value.trim();
    mine.making = true;
    newViewError('');
    $('products-newview-create').textContent = t('products.newview_creating');
    syncNewView();
    ask('products_create_view', { name: name, columns: mine.chosen }, function (answer) {
      mine.making = false;
      $('products-newview-create').textContent = t('products.newview_create');
      if (!answer.ok) { newViewError(failure(answer)); syncNewView(); return; }
      closeNewView();
      view = answer.result.id;   // the list is read again and the new view is the one shown
      remember(view);
      selected = '';
      loadViews();
    });
  }

  function assign(mode, row = {}, rowId = '') {
    showError('');
    setAssigning(true, !mode);
    ask('products_assign', { item: selected, mode: mode, row: row, row_id: rowId }, function (answer) {
      setAssigning(false);
      if (!answer.ok) { showError(failure(answer)); return; }
      const done = answer.result;
      if (done.status === 'exists') { startAssign(); return; }
      loadRows(page);
    });
  }

  /** Open the form: for a new product, or (with ``itemId``) for changing that one, filled with what it holds. */
  function openForm(itemId) {
    ns.filters.close();
    resetFormFilters();
    editing = itemId || '';
    const mine = ++opened;
    $('products-form-title').textContent = editing ? t('products.form_edit_title') : t('products.form_title');
    showPage(true);
    formError('');
    showLoading();
    refreshFooter();
    let form = null;
    let values = null;
    let failed = false;
    function arrived() {
      if (failed || mine !== opened || !form || (editing && !values)) return;
      paintForm(form);
      if (values) formFields.forEach(function (f) { if (f.id in values) setFieldValue(f, values[f.id]); });
      refreshFooter();
      const first = formFields.find(function (f) { return aimable(f.kind, f.input) || f.kind === 'select'; });
      if (first) (first.input.control || first.input).focus();
    }
    function failedWith(answer) {
      if (failed || mine !== opened) return;
      failed = true;
      clearFormBody();
      formError(failure(answer));
    }
    ask('products_form', {}, function (answer) {
      if (!answer.ok) { failedWith(answer); return; }
      form = answer.result;
      arrived();
    });
    if (editing) {
      ask('products_item', { item: editing }, function (answer) {
        if (!answer.ok) { failedWith(answer); return; }
        values = answer.result;
        arrived();
      });
    }
  }

  function closeForm() {
    opened++;
    editing = '';
    showPage(false);
    clearFormBody();
    formFields = [];
    formParts = [];
    closeChecklist();
    refreshFooter();
  }

  /** The value of a field as sent: blank is left out, a checkbox only when ticked. */
  function valueOf(field) {
    if (field.input.getValue) return field.input.getValue();   // a picker or an image holds its own value
    if (field.input.control) return field.input.control.value.trim();   // a text box with a count
    if (field.kind === 'checkbox') return field.input.checked ? true : '';
    if (field.kind === 'radio') {
      const chosen = field.input.querySelector('input:checked');
      return chosen ? chosen.value : '';
    }
    return field.input.value.trim();
  }

  /** Fusion Manage did not accept the product: what it said of the form, and under each field it named what it said of that. */
  function refused(answer) {
    formError(failure(answer));
    let first = null;
    formFields.forEach(function (field) {
      const message = answer.fields && answer.fields[field.id];
      if (!message) return;
      field.error.textContent = message;
      field.error.hidden = false;
      field.wrap.classList.add('invalid');
      if (!first) first = field;
    });
    if (first) goTo(first, true);
  }

  function create(event) {
    event.preventDefault();
    formError('');
    let first = null;
    const values = {};
    formFields.forEach(function (field) {
      const value = valueOf(field);
      if (showState(field) && !first) first = field;
      if (value !== '') values[field.id] = value;
    });
    if (first) {
      formError(t('products.fix_fields'));
      goTo(first);
      return;
    }
    if (sending) return;
    setSending(true);
    const changing = editing;
    ask(changing ? 'products_update' : 'products_create', changing ? { item: changing, values: values } : { values: values }, function (answer) {
      setSending(false);
      if (!answer.ok) { refused(answer); return; }
      selected = answer.result.id;
      closeForm();
      loadRows(changing ? page : 1);   // a new product is in the view, if the view's filter lets it be; a changed one is read again where it is
    });
  }

  // ---- Start ---------------------------------------------------------------------------

  /** The sign-in state is known: the page is ready, or the sign-in screen is shown. */
  function signInKnown(signedIn) {
    $('products-ready').hidden = true;
    if (signedIn && !started) loadViews();
  }

  (function start() {
    // Fusion injects `adsk` asynchronously, so wait for it.
    if (typeof adsk === 'undefined') { setTimeout(start, 100); return; }
    if (!ns.i18n.gate(start)) return;   // the language is in before the page is built
    viewPicker = makeViewPicker();
    viewPicker.querySelector('.pk-btn').disabled = true;   // until there are views
    $('products-view').appendChild(viewPicker);
    ns.shell.mountHeader();
    ns.account.init();
    ns.auth.init();

    ['products_views', 'products_columns', 'products_fields', 'products_image', 'products_picture', 'products_filter', 'products_create_view', 'products_rename_view', 'products_delete_view', 'products_rows', 'products_form', 'products_variant_form', 'products_inspect', 'products_options', 'products_create', 'products_item', 'products_update', 'products_assign', 'products_status'].forEach(function (action) { bridge.on(action, onAnswer); });
    bridge.on('palette_opened', function () { if (started) loadViews(); ns.auth.refresh(); });

    $('products-refresh-view').addEventListener('click', function () { loadRows(page); });
    menu($('products-actions'), $('products-actions-list'));
    initPreview();
    $('products-compact').addEventListener('click', function () { setCompact($('products-compact').getAttribute('aria-checked') !== 'true'); });
    setCompact(window.localStorage.getItem(COMPACT_KEY) === '1');

    $('products-new').addEventListener('click', function () { openForm(''); });
    $('products-edit').addEventListener('click', function () { openForm(selected); });
    $('products-assign').addEventListener('click', startAssign);
    $('products-assign-replace').addEventListener('click', function () { chooseAssign('replace'); });
    $('products-assign-back').addEventListener('click', backAssign);
    $('products-assign-variant').addEventListener('click', function () { chooseAssign('variant'); });
    $('products-assign-confirm').addEventListener('click', nextAssign);
    $('products-assign-keep').addEventListener('change', syncAssign);
    ['input', 'change'].forEach(function (name) { $('products-assign-fields').addEventListener(name, syncAssign); });
    $('products-assign-cancel').addEventListener('click', closeAssignAsk);
    $('products-assign-modal').addEventListener('click', function (event) { if (event.target === event.currentTarget) closeAssignAsk(); });
    $('products-renview-name').addEventListener('input', syncRename);
    $('products-renview-name').addEventListener('keydown', function (event) { if (event.key === 'Enter') renameView(); });
    $('products-renview-ok').addEventListener('click', renameView);
    $('products-renview-cancel').addEventListener('click', closeRenameView);
    $('products-renview-modal').addEventListener('click', function (event) { if (event.target === event.currentTarget) closeRenameView(); });
    $('products-delview-ok').addEventListener('click', deleteView);
    $('products-delview-cancel').addEventListener('click', closeDeleteView);
    $('products-delview-modal').addEventListener('click', function (event) { if (event.target === event.currentTarget) closeDeleteView(); });
    $('products-newview-name').addEventListener('input', syncNewView);
    $('products-newview-name').addEventListener('keydown', function (event) { if (event.key === 'Enter') makeNewView(); });
    $('products-newview-search').addEventListener('input', paintNewView);
    $('products-newview-clear').addEventListener('click', function () { newView.chosen = []; paintNewView(); });
    $('products-newview-create').addEventListener('click', makeNewView);
    $('products-newview-cancel').addEventListener('click', closeNewView);
    $('products-newview-modal').addEventListener('click', function (event) { if (event.target === event.currentTarget) closeNewView(); });
    ['search', 'required'].forEach(function (name) { $('products-fields-' + name).addEventListener('input', scheduleFormFilters); });
    ns.filters.init({ ask: ask, fail: function (answer) { showError(failure(answer)); }, definition: function () { return definition; }, apply: applyFilterChanges });
    $('products-form-cancel').addEventListener('click', closeForm);
    $('products-form').addEventListener('submit', create);
    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape' || sending) return;
      if (!$('products-renview-modal').hidden) closeRenameView();
      else if (!$('products-delview-modal').hidden) closeDeleteView();
      else if (!$('products-newview-modal').hidden) closeNewView();
      else if (!$('products-assign-modal').hidden) closeAssignAsk();
      else if (!$('products-checklist-modal').hidden) closeChecklist();
      else if (formShown()) closeForm();
    });
    ['input', 'change', 'click'].forEach(function (name) { $('products-form').addEventListener(name, scheduleFooter); });
    $('products-checklist').addEventListener('click', openChecklist);
    $('products-checklist-close').addEventListener('click', closeChecklist);
    $('products-checklist-modal').addEventListener('click', function (event) { if (event.target === event.currentTarget) closeChecklist(); });
    $('products-prev').addEventListener('click', function () { loadRows(page - 1); });
    $('products-next').addEventListener('click', function () { loadRows(page + 1); });

    ns.auth.onChange(signInKnown);
    ns.auth.refresh();
  })();
})(window.MfgUi);
