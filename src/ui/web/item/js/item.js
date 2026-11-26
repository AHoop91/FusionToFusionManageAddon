/**
 * Item panel. Python finds the Fusion Manage item of the selected component and reads its
 * sections; this page polls for the answer and draws it.
 * Layer: UI, with the page controller (it polls Python and decides which screen shows). It holds no business rules.
 */
(function (ns) {
  'use strict';

  const bridge = ns.bridge;
  const $ = ns.$;
  const el = ns.el;
  const t = ns.i18n.t;
  const POLL_INTERVAL_MS = 2000;   // Python pushes the item when it is read; this only asks now and then, in case a push is missed
  const UPLOAD_POLL_MS = 2000;   // likewise for the progress of an upload

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
    $('item-loader-text').textContent = text || t('item.loading_item');
    document.querySelectorAll('.item-part').forEach(function (part) { part.hidden = on; });
  }

  // The icons of the two empty states. Static markup.
  const ICON_MISSING = '<path d="M13 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h4M13 3l6 6v2M13 3v4a2 2 0 0 0 2 2h4"/><circle cx="16" cy="16.5" r="3.5"/><path d="M18.6 19.1 21 21.5"/>';
  const ICON_SEVERAL = '<path d="M8 7h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z"/><path d="M4 16V6a2 2 0 0 1 2-2h10"/>';
  const ICON_DENIED = '<circle cx="12" cy="12" r="9"/><path d="M5.6 5.6l12.8 12.8"/>';

  /**
   * Say, in the middle of the panel and in place of the item, ``spec.text`` with a ``spec.hint`` under it. ``spec``: ``icon`` (static markup),
   * ``text``, ``hint``, ``canPublish`` (offer Publish) and ``number`` (the item number that has no item yet).
   */
  function showEmpty(spec) {
    const icon = spec.icon;
    const hint = spec.hint;
    const number = spec.number;
    setLoading(false);
    offerPublish = !!spec.canPublish;
    $('item-empty-publish').hidden = true;   // shown once Python says the open document is a design, not a drawing
    if (offerPublish) bridge.send('upload_context');
    document.querySelectorAll('.item-part').forEach(function (part) { part.hidden = true; });
    $('item-empty-icon').innerHTML = icon;   // static markup
    $('item-empty-text').textContent = spec.text;
    $('item-empty-hint').textContent = hint;
    $('item-empty-hint').hidden = !hint;
    $('item-empty-number').textContent = number || '';
    $('item-empty-number').hidden = !number;   // the item number that has no item yet
    $('item-empty-picker').hidden = true;   // only the "several items" state has it: see showChoices
    $('item-empty-steps').hidden = !offerPublish;   // what Publish will do: only the "not published" state has it
    $('item-empty').classList.toggle('item-empty-denied', icon === ICON_DENIED);
    $('item-empty').hidden = false;
  }

  const CHOICES_COMPACT = 4;   // more items than this are listed one line each
  const CHOICES_FILTER = 8;   // more items than this get a box to narrow them by typing

  /** Several items share the item number: list them, one button each, and send the one picked. */
  function showChoices(entry) {
    showEmpty({ icon: ICON_SEVERAL, text: t('item.several_title'), hint: t('item.several_hint'), canPublish: false, number: entry.choose_number });
    const box = $('item-empty-picker');
    const list = $('item-empty-choices');
    const filter = $('item-empty-filter');
    const note = $('item-empty-capped');
    const many = entry.choose.length > CHOICES_COMPACT;   // one line each, so a long list is quick to scan
    list.replaceChildren();
    list.classList.toggle('item-choices-compact', many);
    const rows = entry.choose.map(function (candidate) {
      const row = el('li');
      const button = el('button', 'item-choice', '');
      button.type = 'button';
      button.appendChild(el('span', 'item-choice-name', candidate.descriptor));
      button.appendChild(el('span', 'item-choice-id', many ? t('item.choice_id_short', { id: candidate.id }) : t('item.choice_id', { id: candidate.id })));
      button.addEventListener('click', function () { bridge.send('choose_item', { item_id: candidate.id, stamp: entry.stamp }); });
      row.appendChild(button);
      list.appendChild(row);
      return { row: row, text: (candidate.descriptor + ' ' + candidate.id).toLowerCase() };
    });
    filter.hidden = entry.choose.length <= CHOICES_FILTER;   // a long list can be narrowed by typing
    filter.value = '';
    filter.oninput = function () {
      const words = filter.value.toLowerCase().split(/\s+/).filter(Boolean);
      rows.forEach(function (r) { r.row.hidden = !words.every(function (w) { return r.text.indexOf(w) >= 0; }); });
    };
    note.hidden = !entry.choose_capped;   // the search returns no more than this many: the one meant may not be among them
    box.hidden = false;
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
      ns.itemFiles.render(target, currentView, ns.itemFiles.open, uploadTool);
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
      if (tab) ns.itemTree.labelTab(button, tab);
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
    ns.itemTree.load('tab_counts_load', 'tab_counts_result', { workspace_id: view.workspace_id, item_id: view.item_id, stamp: view.stamp }, function (error, counts) {
      if (view !== currentView) return;   // another item has been opened meanwhile
      if (error) { ns.toast.show(t('item.counts_error', { error: error }), { tone: 'error' }); return; }
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

  function renderHeader(view) {
    $('item-title').textContent = view.title || t('item.title_default');
    const status = $('item-status');
    status.replaceChildren();
    view.header.forEach(function (part, i) {
      if (i) status.appendChild(el('span', 'item-status-sep', '|'));
      status.appendChild(el('span', '', part));
    });
    itemUrl = view.url || '';
    $('item-open').hidden = !itemUrl;
    $('item-switch').hidden = !(view.others && view.others.length > 1);   // several items share the number: the user may pick another
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
    const menu = mountActionsMenu();
    const upload = createUploadFollower(menu);
    menu.button.addEventListener('click', function (event) {
      event.stopPropagation();
      menu.setOpen(menu.list.hidden);
      if (!menu.list.hidden) bridge.send('upload_context');   // the document may have changed since the last time
    });
    uploadTool.run = upload.startUpload;
    menu.uploads.forEach(function (entry) { entry.addEventListener('click', function () { upload.startUpload(entry.dataset.action); }); });
    $('item-republish').addEventListener('click', function () { menu.setOpen(false); bridge.send('open_publish'); });
    bridge.on('add_step_file', upload.started);
    bridge.on('upload_drawing', upload.started);
    bridge.on('upload_dwg', upload.started);
    bridge.on('upload_dxf', upload.started);
    bridge.on('upload_context', function (r) { if (r.ok) upload.setUpload(r.result); });
    window.addEventListener('focus', function () { if (currentView) bridge.send('upload_context'); });   // the open document may have changed
    bridge.on('upload_status', upload.onStatus);
    bridge.on('toast', function (note) { ns.toast.show(note.message, { tone: note.tone }); });   // Python reports how an action ended
  }

  /** The drop-down's button and list, and its closing on a click elsewhere or Escape. Returns ``{button, list, uploads, setOpen}``. */
  function mountActionsMenu() {
    const button = $('item-actions-btn');
    const list = $('item-actions-list');
    function setOpen(open) {
      list.hidden = !open;
      button.setAttribute('aria-expanded', String(open));
    }
    document.addEventListener('click', function () { setOpen(false); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') setOpen(false); });
    const uploads = Array.prototype.slice.call(list.querySelectorAll('[data-upload]'));   // the STEP file of a design, or the PDF, DWG and DXF of a drawing: Python says which are offered
    return { button: button, list: list, uploads: uploads, setOpen: setOpen };
  }

  /** Set one Upload entry of the menu from ``found``, what Python offers for its action (``label``, ``ext`` of the file, ``ready``). */
  function showUploadEntry(entry, found) {
    entry.querySelector('.item-menu-label').textContent = found.label;
    entry.querySelector('.item-menu-icon').replaceChildren(ns.itemFiles.icon(found.ext));   // the icon the Files tab shows for that kind of file
    entry.dataset.ready = String(found.ready);
    entry.title = found.ready ? '' : t('item.drawing_loading');
  }

  /**
   * The upload of the open document as the menu shows it: the Upload entries, the progress dialog and the polling of Python for its progress.
   * Returns ``{setUpload, startUpload, started, onStatus}``.
   */
  function createUploadFollower(menu) {
    let uploading = false;
    let following = false;   // an upload started here is under way; the progress of one started elsewhere is not shown
    let uploadTimer = 0;
    const card = ns.uploadProgress.mount($('progress-card'));
    function syncUpload() {
      menu.uploads.forEach(function (entry) { entry.disabled = uploading || entry.dataset.ready !== 'true'; });
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
      if (empty) menu.setOpen(false);
      menu.uploads.forEach(function (entry) {
        const found = offered.find(function (a) { return a.action === entry.dataset.action; });
        entry.hidden = !found;
        if (found) showUploadEntry(entry, found);
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
    /** Start the upload ``action`` for the item shown (from the menu, or the Files tab's toolbar). */
    function startUpload(action) {
      menu.setOpen(false);
      if (!currentView) return;
      following = true;
      showUpload({ active: true, stage: t('item.upload_starting'), step: -1, steps: [], percent: null });   // at once: Python is busy for a while
      bridge.send(action, { workspace_id: currentView.workspace_id, item_id: currentView.item_id, stamp: currentView.stamp, request: action });
    }
    function started(r) {
      if (r.ok && r.result && r.result.started) { pollUpload(); return; }
      following = false;
      showUpload({ active: false });   // not started: declined, or one is under way
    }
    function onStatus(r) {
      if (!following) return;   // pushed for an upload started in another window
      if (!r.ok) { following = false; showUpload({ active: false }); return; }
      following = !!r.result.active;
      showUpload(r.result);
      clearTimeout(uploadTimer);
      if (following) uploadTimer = setTimeout(pollUpload, UPLOAD_POLL_MS);
    }
    return { setUpload: setUpload, startUpload: startUpload, started: started, onStatus: onStatus };
  }

  // ---- Up-to-date check of a tab ----------------------------------------------------
  // The mark at the right of the tab bar says whether the tab shown matches the open design: only a spinner while it is checked, then
  // "Out of Date" or "Check failed" when there is something to say. A tab with a check has Python's ``start`` and ``result`` actions and
  // the words for how many things differ (``differs(count)``); a tab with none shows no mark.
  // ``section`` and ``columns`` (what each of ``name``, ``design`` and ``item`` of a difference is called) are for the report the pill opens.
  const CHECKS = {
    item: {
      start: 'sync_check_load', result: 'sync_check_result',
      differs: function (n) { return n === 1 ? t('item.diff_fields_one', { count: n }) : t('item.diff_fields_other', { count: n }); },
      section: function () { return t('item.section_attributes'); },
      columns: function () { return [t('item.col_field'), ns.diffReport.COLUMN_VALUE, ns.diffReport.COLUMN_FM]; },
    },
    bom: {
      start: 'bom_check_load', result: 'bom_check_result',
      differs: function (n) { return n === 1 ? t('item.diff_components_one', { count: n }) : t('item.diff_components_other', { count: n }); },
      section: function () { return t('item.section_bom'); },
      columns: function () { return [t('item.col_component'), ns.diffReport.COLUMN_VALUE, ns.diffReport.COLUMN_FM]; },
    },
  };
  /** The pill's words: while checking there is only the spinner, and an up-to-date tab shows nothing. */
  function labelOf(state) {
    if (state === 'changes') return t('item.out_of_date');
    if (state === 'error') return t('item.check_failed');
    return '';
  }
  const NAMES_SHOWN = 5;   // of what differs, in the tooltip
  let checkOf = {};   // tab -> what its mark shows ({state, text}), for the item shown
  let shownTab = 'item';

  /** What the mark shows for ``found``, Python's answer to ``check``. */
  function describe(check, found) {
    switch (found.state) {
      case 'ok': return { state: 'ok', text: '' };   // an up-to-date tab shows nothing
      case 'changes': {
        const names = found.names.slice(0, NAMES_SHOWN).join(', ') + (found.names.length > NAMES_SHOWN ? ', ...' : '');
        return { state: 'changes', text: t('item.check_changes_text', { differs: check.differs(found.differences), names: names }), check: check, details: found.details || [] };
      }
      case 'error': return { state: 'error', text: t('item.check_error_text', { message: found.message }), message: found.message };
      default: return { state: 'idle', text: '' };   // nothing to compare with: no saved design, or the item of a component below its top
    }
  }

  function paintCheck() {
    const mark = checkOf[shownTab] || { state: 'idle', text: '' };
    const element = $('item-check');
    ns.diffReport.close();   // what it says has changed: the dialog open for the old answer is not wanted
    element.dataset.state = mark.state;
    element.title = mark.text;
    element.setAttribute('aria-label', mark.text);
    $('item-check-label').textContent = labelOf(mark.state);
  }

  function setCheck(name, mark) {
    checkOf[name] = mark;
    if (name === shownTab) paintCheck();
  }

  /** Check tab ``name`` of ``view`` (nothing for a tab with no check). */
  function runCheck(name, view) {
    const check = CHECKS[name];
    if (!check) return;
    setCheck(name, { state: 'checking', text: t('item.checking') });
    ns.itemTree.load(check.start, check.result, { workspace_id: view.workspace_id, item_id: view.item_id, stamp: view.stamp }, function (error, found) {
      if (!currentView || currentView.item_id !== view.item_id) return;   // another item is shown now
      setCheck(name, error ? { state: 'error', text: t('item.check_error_text', { message: error }), message: error } : describe(check, found));
    });
  }

  // ---- The report the pill opens: what is out of date, and Republish -----------------------

  /** Open the report (the one the Publish panel shows too) for what the pill of the tab shown says; nothing when it says nothing. */
  function openDiff() {
    const mark = checkOf[shownTab];
    if (!mark || (mark.state !== 'changes' && mark.state !== 'error')) return;
    if (mark.state === 'error') {
      ns.diffReport.open({ state: 'error', title: t('item.diff_error_title'), summary: mark.message, sections: [], empty: t('item.diff_error_empty') });
      return;
    }
    ns.diffReport.open({
      state: 'changes', title: t('item.diff_title'), summary: t('item.diff_summary', { differs: mark.check.differs(mark.details.length) }),
      sections: [{
        title: mark.check.section(), columns: mark.check.columns(),
        rows: mark.details.map(function (d) { return { cells: [d.name, d.design, d.item] }; }),
      }],
      actions: [{ label: t('item.republish'), onClick: function () { bridge.send('open_publish'); } }],
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
    if (!view.sections.length) { message(t('item.no_fields')); return; }
    view.sections.forEach(function (section) { body.appendChild(ns.itemSections.section(section, openLightbox)); });
  }

  function handle(r) {
    clearTimeout(timer);
    if (!r.ok) { message(r.error || t('item.read_error'), true); return; }
    const entry = r.result;
    if (entry.pending) {
      waitForItem(entry);
      return;
    }
    const quiet = quietRead;   // the Item tab was clicked: the item is drawn again, but not checked again
    quietRead = false;
    shownSeq = entry.seq;
    showAnswer(entry, quiet);
  }

  /** Python is still reading the item: show the loading screen once for each open, and ask again soon. */
  function waitForItem(entry) {
    if (shownSeq !== entry.seq) { shownSeq = entry.seq; if (!quietRead) setLoading(true, t('item.finding')); }
    timer = setTimeout(poll, POLL_INTERVAL_MS);
  }

  /** Show what Python answered once it is no longer pending: a refusal, a choice, a missing item, a message or the item. */
  function showAnswer(entry, quiet) {
    if (entry.denied) { showEmpty({ icon: ICON_DENIED, text: entry.denied, hint: '' }); return; }
    if (entry.choose && entry.choose.length) { showChoices(entry); return; }
    if (entry.missing) {
      showEmpty({ icon: ICON_MISSING, text: t('item.missing_title'), hint: t('item.missing_hint'), canPublish: true, number: entry.missing });
      return;
    }
    if (!entry.seq) { message(t('item.select_component')); return; }
    if (!entry.ok) { message(entry.message || t('item.read_error'), true); return; }
    render(entry.view, quiet);
  }

  function poll() { bridge.send('get_item_view'); }

  let startOnItemTab = false;   // set when the panel is opened; the next item shown starts on the Item tab

  setLoading(true);   // until the first answer

  function start() {
    // Fusion injects `adsk` asynchronously, so wait for it.
    if (typeof adsk === 'undefined') { setTimeout(start, 100); return; }
    if (!ns.i18n.gate(start)) return;   // the language is in before the page is built
    ns.shell.mountHeader();
    ns.account.init();
    ns.auth.init();
    bridge.on('get_item_view', handle);
    bridge.on('item_changed', function (note) {   // Python opened another item in this palette
      quietRead = false;   // another item (or an upload's reload): the loading screen is right
      if (note && note.item_tab) startOnItemTab = true;   // the panel was opened, not just following the selection: back to the Item tab
      setLoading(true, t('item.finding'));   // at once, not after the answer to the poll
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
    $('item-check-label').addEventListener('click', openDiff);
    $('item-refresh').addEventListener('click', function () { bridge.send('refresh_item_view'); });
    $('item-switch').addEventListener('click', function () { bridge.send('choose_item', { item_id: '', stamp: currentView ? currentView.stamp : '' }); });   // forget the choice: the list is shown again
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
