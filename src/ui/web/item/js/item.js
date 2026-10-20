/**
 * Item panel. Python finds the Fusion Manage item of the selected component and reads its
 * sections; this page polls for the answer and draws it.
 */
(function (ns) {
  'use strict';

  const bridge = ns.bridge;
  const $ = ns.$;
  const el = ns.el;
  const POLL_INTERVAL_MS = 400;
  const UPLOAD_POLL_MS = 300;   // how often the progress of an upload is asked for
  const LABEL_COLUMN_WIDTH = '16%';   // the row labels; the other columns share the rest equally
  const MIN_COLUMN_PX = 50;
  const MIN_MATRIX_COLUMN_PX = 120;   // a matrix column is never squeezed below this by a narrow panel

  let timer = null;
  let shownSeq = 0;   // the open that is on screen, so a poll for it does not redraw
  let itemUrl = '';
  let currentView = null;
  let offerPublish = false;   // the empty state is the "not published" one, which may offer Publish
  let quietRead = false;   // the item is being read again from its tab: no loading screen over what is shown

  /** Show the bouncing balls (and hide the item) while Python is still reading everything the item needs. */
  function setLoading(on, text) {
    $('item-empty').hidden = true;
    offerPublish = false;
    $('item-loader').hidden = !on;
    $('item-loader-text').textContent = text || 'Loading item...';
    document.querySelectorAll('.item-part').forEach(function (part) { part.hidden = on; });
  }

  // The icons of the two empty states. Static markup.
  const ICON_MISSING = '<path d="M13 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h4M13 3l6 6v2M13 3v4a2 2 0 0 0 2 2h4"/><circle cx="16" cy="16.5" r="3.5"/><path d="M18.6 19.1 21 21.5"/>';
  const ICON_DENIED = '<circle cx="12" cy="12" r="9"/><path d="M5.6 5.6l12.8 12.8"/>';

  /** Say, in the middle of the panel and in place of the item, ``text`` with a ``hint`` under it. */
  function showEmpty(icon, text, hint, canPublish) {
    setLoading(false);
    offerPublish = !!canPublish;
    $('item-empty-publish').hidden = true;   // shown once Python says the open document is a design, not a drawing
    if (offerPublish) bridge.send('upload_context');
    document.querySelectorAll('.item-part').forEach(function (part) { part.hidden = true; });
    $('item-empty-icon').innerHTML = icon;   // static markup
    $('item-empty-text').textContent = text;
    $('item-empty-hint').textContent = hint;
    $('item-empty').hidden = false;
  }

  const LAZY_TABS = ['files', 'bom', 'whereused', 'workflows', 'changelog'];
  const TABS = ['item'].concat(LAZY_TABS);
  const loaded = {};   // tabs read for the item shown
  LAZY_TABS.forEach(function (name) { loaded[name] = false; });

  /** Read a lazy tab the first time it is opened for the item shown. */
  function loadTab(name) {
    if (!currentView || loaded[name] !== false) return;
    loaded[name] = true;
    const target = $('item-' + name);
    if (name === 'files') {
      ns.itemFiles.render(target, currentView, function (file) {
        if (file.url) bridge.send('open_url', { url: file.url });   // the file's page in Fusion Manage
      }, uploadTool);
    } else {
      ({ bom: ns.itemBom, whereused: ns.itemWhereUsed, workflows: ns.itemWorkflows, changelog: ns.itemChangeLog })[name].render(target, currentView);
    }
  }

  /** Name each tab as Fusion Manage does, with how many entries it holds; a tab the workspace does not have is hidden. */
  function labelTabs(view) {
    TABS.forEach(function (key) {
      const tab = view.tabs[key];
      const button = $('item-tab-' + key);
      button.hidden = !tab;
      if (!tab) return;
      button.textContent = tab.allowed && tab.count ? tab.label + ' (' + tab.count + ')' : tab.label;
      button.disabled = !tab.allowed;
      if (tab.allowed) button.removeAttribute('title');
      else button.title = 'Insufficient permissions';
    });
  }

  /**
   * The one place reads are ended. Nothing waits for what ``tab`` (every tab when none is given) was still reading, any more: Python is told to
   * cancel it, and no mark is left on "checking". Returns how many reads were cut short. Called when a tab is left or clicked again, when
   * the item is read afresh and when the panel is hidden. (The reads started afterwards are not in the cancel: the bridge delivers in order.)
   */
  function leaveReads(tab) {
    const cut = ns.itemTree.leave(tab);
    Object.keys(checkOf).forEach(function (key) {
      if ((!tab || key === tab) && checkOf[key].state === 'checking') delete checkOf[key];
    });
    return cut;
  }

  /** Show one tab (one of ``TABS``) and mark its button. */
  function showTab(name, keep) {
    if (name !== shownTab) leaveReads(shownTab);
    TABS.forEach(function (key) { $(key === 'item' ? 'item-body' : 'item-' + key).hidden = key !== name; });
    if (!keep) loadTab(name);   // ``keep``: the caller reads the tab itself
    document.querySelectorAll('.item-tab[data-tab]').forEach(function (tab) {
      tab.classList.toggle('item-tab-active', tab.dataset.tab === name);
    });
    shownTab = name;
    paintCheck();
  }

  /**
   * Open a tab the user clicked, reading it again from Fusion Manage every time (also when it is the tab shown). The Item tab
   * reads the whole item again; any other tab reads only its own entries and the counts of every tab.
   */
  function openTab(name) {
    if (!currentView) return;
    showTab(name, true);
    if (name === 'item') {   // the item stays on screen until the new one is ready (and is not checked again if it was)
      quietRead = true;
      if (!checkOf.item) runCheck('item', currentView);
      bridge.send('refresh_item_view');
      return;
    }
    leaveReads(name);   // what this tab was still reading from the last click is not wanted
    runCheck(name, currentView);   // a tab is read again on every click, and so checked again
    const view = currentView;
    ns.itemTree.load('tab_counts_load', 'tab_counts_result', { workspace_id: view.workspace_id, item_id: view.item_id }, function (error, counts) {
      if (view !== currentView) return;   // another item has been opened meanwhile
      if (error) { ns.toast.show('Could not refresh the counts: ' + error, { tone: 'error' }); return; }
      Object.keys(counts).forEach(function (key) { if (view.tabs[key]) view.tabs[key].count = counts[key]; });
      labelTabs(view);
    });
    loaded[name] = false;
    $('item-' + name).replaceChildren();
    loadTab(name);
  }

  function message(text, isError) {
    setLoading(false);
    showTab('item');
    $('item-body').replaceChildren(el('p', 'item-message ' + (isError ? 'error' : 'muted'), text));
  }

  function openLightbox(src) {
    $('item-lightbox-img').src = src;
    $('item-lightbox').hidden = false;
  }

  function closeLightbox() {
    $('item-lightbox').hidden = true;
    $('item-lightbox-img').removeAttribute('src');
  }

  /** Fill ``node`` with a value: text, a picture, or the (sanitised) markup of a formula field. */
  function fill(node, cell) {
    if (cell.kind === 'image') {
      if (!cell.value) return;
      const img = el('img', 'item-image');
      img.src = cell.value;
      img.alt = '';
      img.title = 'Click to enlarge';
      img.addEventListener('click', function () { openLightbox(cell.value); });
      node.appendChild(img);
    } else if (cell.kind === 'links') {
      cell.value.forEach(function (link, i) {
        if (i) node.appendChild(document.createTextNode(', '));
        const a = el('a', 'item-link', link.title);
        a.href = '#';
        a.title = 'Open in Fusion Manage in your browser';
        a.addEventListener('click', function (event) {
          event.preventDefault();
          bridge.send('open_url', { url: link.url });
        });
        node.appendChild(a);
      });
    } else if (cell.kind === 'html') {
      ns.safeHtml.render(node, cell.value);
    } else {
      node.textContent = cell.value;
    }
  }

  /**
   * Let the user drag the right edge of a column header to resize that column (not below ``MIN_COLUMN_PX``).
   * Only that column changes. The last column (which has no handle) stretches to fill any space left in the
   * section, but never shrinks below the width it started with, so widening a column past the section's edge
   * adds a horizontal scroll bar instead. The first drag fixes every column at its current pixel width.
   */
  function makeResizable(table, cols, heads) {
    const last = heads.length - 1;
    let lastFloor = 0;   // the last column's width before any drag
    function freeze() {
      const widths = heads.map(function (th) { return th.getBoundingClientRect().width; });
      if (!lastFloor) lastFloor = widths[last];
      widths.forEach(function (w, i) { cols[i].style.width = w + 'px'; });
    }
    function apply() {
      let others = 0;
      for (let i = 0; i < last; i++) others += parseFloat(cols[i].style.width);
      const width = Math.max(lastFloor, table.parentNode.clientWidth - others);
      cols[last].style.width = width + 'px';
      table.style.width = (others + width) + 'px';
    }
    heads.slice(0, last).forEach(function (th, i) {
      th.appendChild(ns.itemTree.grip(cols[i], { min: MIN_COLUMN_PX, onResize: apply, beforeDrag: freeze }));
    });
  }

  function renderMatrix(matrix) {
    const table = el('table', 'item-matrix');
    const cols = [];
    for (let i = 0; i <= matrix.columns.length; i++) {   // the first is the column of row labels, a little wider
      const col = el('col');
      if (i === 0) col.style.width = LABEL_COLUMN_WIDTH;
      cols.push(col);
    }
    table.appendChild(el('colgroup')).append(...cols);
    const head = el('tr');
    const heads = [el('th')];   // the column of row labels
    matrix.columns.forEach(function (c) {
      const th = el('th', '', c);
      th.title = c;
      heads.push(th);
    });
    table.style.minWidth = (heads.length * MIN_MATRIX_COLUMN_PX) + 'px';   // never narrower than this: a narrow panel scrolls the grid sideways instead (the table is 100% wide above it)
    heads.forEach(function (th) { head.appendChild(th); });
    makeResizable(table, cols, heads);
    table.appendChild(head);
    matrix.rows.forEach(function (row, i) {
      const tr = el('tr');
      tr.appendChild(el('td', 'item-matrix-label', matrix.labels[i]));
      row.forEach(function (cell) {
        const td = el('td');
        fill(td, cell);
        tr.appendChild(td);
      });
      table.appendChild(tr);
    });
    const wrap = el('div', 'item-matrix-wrap');   // a wide grid scrolls sideways
    wrap.appendChild(table);
    return wrap;
  }

  function renderSection(section) {
    const wrap = el('section', 'item-section');
    const content = el('div', 'item-section-body');
    section.fields.forEach(function (f) {
      const row = el('div', 'item-field');
      row.appendChild(el('div', 'item-field-label', f.title));
      const value = el('div', 'item-field-value');
      fill(value, f);
      row.appendChild(value);
      content.appendChild(row);
    });
    section.matrices.forEach(function (m) { content.appendChild(renderMatrix(m)); });
    if (section.title) {
      const title = el('button', 'item-section-title', section.title);
      title.type = 'button';
      title.addEventListener('click', function () {
        content.hidden = !content.hidden;
        title.classList.toggle('item-collapsed', content.hidden);
        wrap.classList.toggle('item-section-folded', content.hidden);
      });
      wrap.appendChild(title);
    }
    wrap.appendChild(content);
    return wrap;
  }

  function renderHeader(view) {
    $('item-title').textContent = view.title || 'Fusion Manage Item';
    const status = $('item-status');
    status.replaceChildren();
    view.header.forEach(function (part, i) {
      if (i) status.appendChild(el('span', 'item-status-sep', '|'));
      status.appendChild(el('span', '', part));
    });
    itemUrl = view.url || '';
    $('item-open').hidden = !itemUrl;
  }

  // What the open document uploads, shared with the Files tab's toolbar: ``actions`` as Python's ``upload_context`` gives them, whether one
  // is under way (``busy``), ``run(action)`` to start one, and the one function ``listen`` was given, called when any of it changes.
  const uploadTool = {
    actions: [],
    busy: false,
    run: function () {},
    listener: null,
    listen: function (fn) { uploadTool.listener = fn; },
    changed: function () { if (uploadTool.listener) uploadTool.listener(); },
    refresh: function () { bridge.send('upload_context'); },   // the open document may have changed since the last look
  };

  /** The Actions drop-down: opens under its button, closes on a choice, a click elsewhere or Escape. */
  function initActions() {
    const button = $('item-actions-btn');
    const list = $('item-actions-list');
    function setOpen(open) {
      list.hidden = !open;
      button.setAttribute('aria-expanded', String(open));
    }

    document.addEventListener('click', function () { setOpen(false); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') setOpen(false); });
    const uploads = Array.prototype.slice.call(list.querySelectorAll('[data-upload]'));   // the STEP file of a design, or the PDF, DWG and DXF of a drawing: Python says which are offered
    let uploading = false;
    let uploadTimer = 0;
    const card = ns.uploadProgress.mount($('progress-card'));
    function syncUpload() {
      uploads.forEach(function (entry) { entry.disabled = uploading || entry.dataset.ready !== 'true'; });
    }
    /** The Upload entries for what the open document uploads (``actions``: each has ``action``, ``label``, ``ext`` of the file, ``ready``). */
    function setUpload(context) {
      const offered = context.actions || [];
      uploadTool.actions = offered;
      uploadTool.changed();
      $('item-republish').hidden = !context.publish;
      $('item-empty-publish').hidden = !(offerPublish && context.publish);
      $('item-republish').classList.toggle('item-menu-divided', offered.length > 0);
      const empty = !offered.length && !context.publish;
      $('item-actions-menu').hidden = empty;   // nothing offered: no three dots
      if (empty) setOpen(false);
      uploads.forEach(function (entry) {
        const found = offered.find(function (a) { return a.action === entry.dataset.action; });
        entry.hidden = !found;
        if (!found) return;
        entry.querySelector('.item-menu-label').textContent = found.label;
        entry.querySelector('.item-menu-icon').replaceChildren(ns.itemFiles.icon(found.ext));   // the icon the Files tab shows for that kind of file
        entry.dataset.ready = String(found.ready);
        entry.title = found.ready ? '' : 'The drawing is still loading';
      });
      syncUpload();
    }
    /** The progress dialog over the panel for ``state`` (``active``, and while it is, what ``upload-progress.js`` shows). */
    function showUpload(state) {
      uploading = !!state.active;
      $('progress').hidden = !uploading;
      uploadTool.busy = uploading;
      uploadTool.changed();
      syncUpload();
      if (uploading) card.show(state);
    }
    function pollUpload() { clearTimeout(uploadTimer); bridge.send('upload_status'); }
    function toggleMenu(open) {
      setOpen(open);
      if (open) bridge.send('upload_context');   // the document may have changed since the last time
    }
    button.addEventListener('click', function (event) { event.stopPropagation(); toggleMenu(list.hidden); });
    /** Start the upload ``action`` for the item shown (from the menu, or the Files tab's toolbar). */
    function startUpload(action) {
      setOpen(false);
      if (!currentView) return;
      showUpload({ active: true, stage: 'Starting', step: -1, steps: [], percent: null });   // at once: Python is busy for a while
      bridge.send(action, { workspace_id: currentView.workspace_id, item_id: currentView.item_id, request: action });
    }
    uploadTool.run = startUpload;
    uploads.forEach(function (entry) { entry.addEventListener('click', function () { startUpload(entry.dataset.action); }); });
    $('item-republish').addEventListener('click', function () { setOpen(false); bridge.send('open_publish'); });
    function started(r) {
      if (r.ok && r.result && r.result.started) pollUpload(); else showUpload({ active: false });   // not started: declined, or one is under way
    }
    bridge.on('add_step_file', started);
    bridge.on('upload_drawing', started);
    bridge.on('upload_dwg', started);
    bridge.on('upload_dxf', started);
    bridge.on('upload_context', function (r) { if (r.ok) setUpload(r.result); });
    window.addEventListener('focus', function () { if (currentView) bridge.send('upload_context'); });   // the open document may have changed
    bridge.on('upload_status', function (r) {
      if (!r.ok) { showUpload({ active: false }); return; }
      showUpload(r.result);
      if (r.result.active) uploadTimer = setTimeout(pollUpload, UPLOAD_POLL_MS);
    });
    bridge.on('toast', function (note) { ns.toast.show(note.message, { tone: note.tone }); });   // Python reports how an action ended
  }

  // ---- Up-to-date check of a tab ----------------------------------------------------
  // The mark at the right of the tab bar says whether the tab shown matches the open design: only a spinner while it is checked, then
  // "Out of Date" or "Check failed" when there is something to say. A tab with a check has Python's ``start`` and ``result`` actions and
  // the words for how many things differ (``differs(count)``); a tab with none shows no mark.
  const CHECKS = {
    item: {
      start: 'sync_check_load', result: 'sync_check_result',
      differs: function (n) { return n + (n === 1 ? ' mapped field differs' : ' mapped fields differ') + ' from the open design'; },
    },
    bom: {
      start: 'bom_check_load', result: 'bom_check_result',
      differs: function (n) { return n + (n === 1 ? ' component is' : ' components are') + ' not in this Bill of Materials as in the open design (not under the same parent, or in another quantity)'; },
    },
  };
  const LABELS = { changes: 'Out of Date', error: 'Check failed' };   // the pill; while checking there is only the spinner, and an up-to-date tab shows nothing
  const NAMES_SHOWN = 5;   // of what differs, in the tooltip
  let checkOf = {};   // tab -> what its mark shows ({state, text}), for the item shown
  let shownTab = 'item';

  /** What the mark shows for ``found``, Python's answer to ``check``. */
  function describe(check, found) {
    switch (found.state) {
      case 'ok': return { state: 'ok', text: '' };   // an up-to-date tab shows nothing
      case 'changes': {
        const names = found.names.slice(0, NAMES_SHOWN).join(', ') + (found.names.length > NAMES_SHOWN ? ', ...' : '');
        return { state: 'changes', text: check.differs(found.differences) + ' (' + names + '). Republish to update.' };
      }
      case 'error': return { state: 'error', text: 'Could not check: ' + found.message };
      default: return { state: 'idle', text: '' };   // nothing to compare with: no saved design, or the item of a component below its top
    }
  }

  function paintCheck() {
    const mark = checkOf[shownTab] || { state: 'idle', text: '' };
    const element = $('item-check');
    element.dataset.state = mark.state;
    element.title = mark.text;
    element.setAttribute('aria-label', mark.text);
    $('item-check-label').textContent = LABELS[mark.state] || '';
  }

  function setCheck(name, mark) {
    checkOf[name] = mark;
    if (name === shownTab) paintCheck();
  }

  /** Check tab ``name`` of ``view`` (nothing for a tab with no check). */
  function runCheck(name, view) {
    const check = CHECKS[name];
    if (!check) return;
    setCheck(name, { state: 'checking', text: 'Checking Fusion Manage...' });
    ns.itemTree.load(check.start, check.result, { workspace_id: view.workspace_id, item_id: view.item_id }, function (error, found) {
      if (!currentView || currentView.item_id !== view.item_id) return;   // another item is shown now
      setCheck(name, error ? { state: 'error', text: 'Could not check: ' + error } : describe(check, found));
    });
  }

  function render(view, keepCheck) {
    setLoading(false);
    bridge.send('upload_context');   // the three dots show once there is something in them
    renderHeader(view);
    currentView = view;
    if (!keepCheck) { leaveReads(); checkOf = {}; }   // the item is read afresh: what was still being read for the last read is not wanted
    labelTabs(view);
    if (startOnItemTab || document.querySelector('.item-tab-active').disabled) showTab('item');   // just opened, or the tab open for the last item is not allowed for this one
    startOnItemTab = false;
    if (!keepCheck) runCheck(shownTab, view);   // the tab shown is checked; the others when they are opened
    // these are read from Fusion Manage only when their tab is opened
    LAZY_TABS.forEach(function (name) {
      const tab = $('item-' + name);
      loaded[name] = false;
      tab.replaceChildren();
      if (!tab.hidden) loadTab(name);   // the tab was open when the item changed
    });
    const body = $('item-body');
    body.replaceChildren();
    if (!view.sections.length) { message('This item has no fields to show.'); return; }
    view.sections.forEach(function (section) { body.appendChild(renderSection(section)); });
  }

  function handle(r) {
    clearTimeout(timer);
    if (!r.ok) { message(r.error || 'Could not read the item.', true); return; }
    const entry = r.result;
    if (entry.pending) {
      if (shownSeq !== entry.seq) { shownSeq = entry.seq; if (!quietRead) setLoading(true, 'Finding the Fusion Manage item...'); }
      timer = setTimeout(poll, POLL_INTERVAL_MS);
      return;
    }
    const quiet = quietRead;   // the Item tab was clicked: the item is drawn again, but not checked again
    quietRead = false;
    shownSeq = entry.seq;
    if (entry.denied) { showEmpty(ICON_DENIED, entry.denied, ''); return; }
    if (entry.missing) {
      showEmpty(ICON_MISSING, 'This item has not been uploaded to the Fusion Manage Items workspace.', 'No item exists for ' + entry.missing + '. Would you like to publish it?', true);
      return;
    }
    if (!entry.seq) { message('Select a component and choose Open Fusion Manage Item.'); return; }
    if (!entry.ok) { message(entry.message || 'Could not read the item.', true); return; }
    render(entry.view, quiet);
  }

  function poll() { bridge.send('get_item_view'); }

  let startOnItemTab = false;   // set when the panel is opened; the next item shown starts on the Item tab

  setLoading(true);   // until the first answer

  function start() {
    // Fusion injects `adsk` asynchronously, so wait for it.
    if (typeof adsk === 'undefined') { setTimeout(start, 100); return; }
    ns.shell.mountHeader();
    ns.account.init();
    ns.auth.init();
    bridge.on('get_item_view', handle);
    bridge.on('item_changed', function (note) {   // Python opened another item in this palette
      quietRead = false;   // another item (or an upload's reload): the loading screen is right
      if (note && note.item_tab) startOnItemTab = true;   // the panel was opened, not just following the selection: back to the Item tab
      setLoading(true, 'Finding the Fusion Manage item...');   // at once, not after the answer to the poll
      poll();
    });
    bridge.on('refresh_item_view', handle);
    document.querySelectorAll('.item-tab[data-tab]').forEach(function (tab) {
      tab.addEventListener('click', function () { openTab(tab.dataset.tab); });
    });
    // The panel is hidden or closed: stop reading for it (every request to Fusion Manage that is still going is cancelled in Python). Shown again,
    // the tab that was cut short is read once more.
    let cutShort = false;
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) {
        cutShort = leaveReads() > 0;
      } else if (cutShort) {
        cutShort = false;
        if (currentView) openTab(shownTab);
      }
    });
    $('item-lightbox').addEventListener('click', closeLightbox);
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeLightbox(); });
    $('item-refresh').addEventListener('click', function () { bridge.send('refresh_item_view'); });
    $('item-open').addEventListener('click', function () { if (itemUrl) bridge.send('open_url', { url: itemUrl }); });
    $('item-empty-publish').addEventListener('click', function () { bridge.send('open_publish'); });
    bridge.on('open_publish', function (r) {
      const message = r.ok ? (r.result && r.result.message) : r.error;
      if (message) ns.toast.show(message, { tone: 'error' });   // a drawing cannot be published
    });
    initActions();
    ns.auth.onChange(function (signedIn) { if (signedIn) poll(); });   // read the item once signed in
    ns.auth.refresh();
    poll();
  }

  start();
})(window.MfgUi);
