/**
 * Publish Item panel: the Bill of Materials area, as ``ns.pubBom``.
 *
 * Shows what has been read of the Bill of Materials (the table, bom-table.js; or the loading skeleton, a message, or an error),
 * reads the lines under an assembly when it is opened and the whole tree for Expand all or for Publish, and queues the publish.
 * Publishing covers the whole design; the pills in the footer count what that is. The panel (publish.js) sends the requests and hands
 * the answers back, through ``host``.
 */
(function (ns) {
  'use strict';

  const $ = ns.$;
  const ui = ns.pubUi;
  const details = ns.pubDetails;
  const jobs = ns.pubJobs;
  const model = ns.bomModel;
  const tree = ns.bomTree;
  function t(key, params) { return ns.i18n.t(key, params); }

  function readingTree() { return t('publish.reading_tree'); }
  function readingForPublish() { return t('publish.reading_for_publish'); }
  function linesSoFar(progress) { return t('publish.lines_so_far', { count: Number(progress).toLocaleString() }); }

  let host = null;          // { summary(), ask(slot, payload), request(slot, payload), changed() }, given to ``init``
  let rows = [];            // compared rows of the Bill of Materials read so far
  let fmItemId = '';        // Fusion Manage item the BOM was compared with; empty when the design has none
  let designNew = false;    // Fusion Manage holds no item for the design: publishing creates it, and items can still be added to its BOM
  const kidsLoading = {};   // component id -> true while the lines under it are read
  const kidsFailed = {};    // component id -> why they could not be read
  let treeLoading = false;  // the rest of the tree is being read (Expand all)
  let treeProgress = '';    // how far, while it is
  let publishAfterTree = false;   // Publish was clicked with levels unread: it goes on once the tree is read
  let shown = false;        // the table is on screen (not the skeleton, a message or an error)
  let statusText = '';      // what the loading line last said

  // ---- Buttons of the area -------------------------------------------------------

  /** Publish is available once the Bill of Materials is shown and every differing line has a choice. */
  function setPublishState(pending, reason) {
    const button = $('pub-publish');
    button.disabled = pending > 0 || !!reason;
    button.title = reason || (pending > 0
      ? (pending === 1 ? t('publish.review_first_one', { count: pending }) : t('publish.review_first_many', { count: pending }))
      : t('publish.publish_title'));
  }

  /** Add Items needs the design to be compared with Fusion Manage (an item found, or none yet); ``reason`` says why it is not available. */
  function setAddItemsState(reason) {
    const button = $('pub-add-items');
    button.disabled = !!reason;
    button.title = reason || t('publish.add_items_title');
  }

  // ---- What the area shows -------------------------------------------------------

  function clear() {
    shown = false;
    renderPills(null);
    setAddItemsState(t('publish.waiting_bom'));
    setPublishState(0, t('publish.waiting_bom'));
    const area = $('pub-bom');
    area.classList.remove('pub-loading');
    area.textContent = '';
    return area;
  }

  /** What the Bill of Materials is doing: reading it (and how far, once it takes several pages), then comparing it with Fusion Manage. */
  function status(entry) {
    const note = $('pub-bom-status');
    if (!note) return;
    const text = entry.stage === 'comparing' ? t('publish.comparing')
      : entry.progress ? t('publish.reading_bom_lines', { count: Number(entry.progress).toLocaleString() })
      : t('publish.reading_bom');
    if (text === statusText && note.textContent) return;   // the same words must not restart the "taking longer" timer
    statusText = text;
    ui.warnWhenSlow(note, text);   // adds a note if nothing new has been said for a long while
  }

  /** Rows of grey bars in place of the table while it loads, with a line saying what is happening. */
  function showLoading() {
    const area = clear();
    const note = ui.el('p', 'muted pub-bom-status');
    note.id = 'pub-bom-status';
    area.appendChild(note);
    const skeleton = ui.el('div', 'card pub-skel-table');
    skeleton.setAttribute('aria-hidden', 'true');
    for (let n = 0; n < 8; n++) {
      const line = ui.el('div', 'pub-skel-row');
      ['pub-skel-wide', 'pub-skel-mid', 'pub-skel-short'].forEach(function (width) { line.appendChild(ui.el('span', 'pub-skel ' + width)); });
      skeleton.appendChild(line);
    }
    area.appendChild(skeleton);
    status({});
  }

  function showMessage(text) {
    const card = ui.el('div', 'card');
    card.appendChild(ui.el('p', 'muted', text));
    clear().appendChild(card);
  }

  /** A failure in the middle of the panel, so the message centres in it. */
  function showError(message, onRetry) {
    clear().classList.add('pub-loading');
    $('pub-bom').appendChild(ui.errorState(message, onRetry));
  }

  /** What the table asks of the panel for the lines it has not read. */
  const lazy = {
    loaded: function (id) { return tree.isLoaded(id); },
    loading: function (id) { return !!kidsLoading[id]; },
    failed: function (id) { return kidsFailed[id] || ''; },
    load: function (item) { loadKids(item); },
    expandAll: function () { loadTree(); },
    folded: function () { refreshScope(); },
    incomplete: function () { return tree.unloaded().length > 0; },
    busy: function () { return treeLoading; },
    busyText: function () { return treeProgress || readingTree(); },
  };

  /** The design and Fusion Manage lines in one compare table; a row click opens its details. ``keepFolds`` leaves the assemblies open or closed as they are. */
  function show(lines, shared, keepFolds) {
    const area = clear();
    if (shared) {   // no table until the number is fixed in Fusion Manage, so open the design's details, which say so
      showMessage(t('publish.design_shared_message'));
      setAddItemsState(t('publish.design_shared_fix'));
      setPublishState(0, t('publish.design_shared_fix'));
      details.open(model.rootComponent(host.summary()));
      return;
    }
    rows = lines;
    const addReason = fmItemId || designNew ? '' : t('publish.not_compared');
    if (!lines.length && !model.stagedIds().length) {
      showMessage(t('publish.no_children'));
      setAddItemsState(addReason);
      setPublishState(0);
      return;
    }
    shown = true;
    ns.bomTable.render(area, lines, host.summary(), details.open, refreshScope, keepFolds, lazy);   // it calls back after each draw
    setAddItemsState(addReason);
  }

  /** Draw what has been read so far. */
  function draw(keepFolds) {
    show(tree.rows(), false, keepFolds);
  }

  /** The first level has been read and compared: show it (a new comparison, so nothing is chosen or added yet). */
  function showFirstLevel(data) {
    model.clearDecisions();
    fmItemId = data.fm_item_id || '';
    designNew = !!data.design_new;
    tree.setTop(data.rows);   // the rest is read as it is opened
    show(tree.rows(), !!data.shared);
  }

  // ---- Reading more of the tree --------------------------------------------------

  /** Read the lines directly under one assembly (its chevron was clicked) and compare them with Fusion Manage. */
  function loadKids(item) {
    const id = item.lineId;
    if (!id || kidsLoading[id]) return;
    delete kidsFailed[id];
    kidsLoading[id] = true;
    host.ask('children:' + id, {
      section: 'children', id: id, force: true,   // the panel keeps what it has read; a copy kept in Python may be from before a Refresh
      item_number: item.component ? item.component.item_number || '' : '',
      skip: item.status === 'skipped' ? '1' : '',
      compared: fmItemId ? '1' : '',
    });
    draw(true);   // the spinner and the grey rows
  }

  /** The lines under an assembly arrived. A failure is that assembly's alone: the rest of the table stays. */
  function finishKids(id, entry) {
    delete kidsLoading[id];
    if (!entry.ok) {
      kidsFailed[id] = entry.message || t('publish.unknown_error');
      draw(true);
      return;
    }
    delete kidsFailed[id];
    tree.setKids(id, entry.data.rows);
    draw(true);
    host.changed();
  }

  /** Read every level that is not read yet (Expand all). */
  function loadTree() {
    if (treeLoading) return;
    treeLoading = true;
    treeProgress = '';
    draw(true);
    host.ask('tree', { section: 'tree', force: true });
  }

  /** How far the whole tree is read; the tooltip of the spinning Expand all button says so. */
  function treeStatus(entry) {
    treeProgress = entry.stage === 'comparing' ? t('publish.comparing')
      : entry.progress ? t('publish.reading_bom_lines', { count: Number(entry.progress).toLocaleString() }) : '';
    const button = document.querySelector('.pub-cmp-tool-busy');
    if (button) { button.title = lazy.busyText(); button.setAttribute('aria-label', button.title); }
    if (publishAfterTree) {   // Publish is waiting on it: the dialog says how far it is
      const comparing = entry.stage === 'comparing';
      showReading(comparing ? t('publish.comparing_every_line') : readingForPublish(), !comparing && entry.progress ? linesSoFar(entry.progress) : '');
    }
  }

  /** The progress dialog on its Reading step. Closing it before the read ends drops the publish. */
  function showReading(status, count) {
    jobs.reading({ status: status, count: count || '' }, function () { publishAfterTree = false; });
  }

  function finishTree(entry) {
    treeLoading = false;
    const publishing = publishAfterTree;
    publishAfterTree = false;
    if (!entry.ok) {
      if (publishing) jobs.stopReading();
      ns.toast.show((publishing ? t('publish.tree_failed_publish', { message: entry.message || t('publish.unknown_error') }) : t('publish.tree_failed', { message: entry.message || t('publish.unknown_error') })), { tone: 'error' });
      draw(true);
      host.treeDone(entry);
      return;
    }
    tree.setAll(entry.data.rows);
    ns.bomTable.openAllOnNextDraw();   // Expand all: everything opens
    draw(true);
    host.changed();
    host.treeDone(entry);
    if (publishing) goOn();
  }

  /** The tree is read for a publish: go on with it, in the same dialog. Lines that need a choice stop it instead, and are in view for it. */
  function goOn() {
    const cover = covered();
    if (model.pendingReviews(cover.items) > 0) {
      jobs.stopReading();
    } else {
      const found = ns.bomPlan.publishPlan(rows, cover.summary).components.length;   // items, as the other steps count: the design and each component once
      jobs.reading({ done: true, count: (found === 1 ? t('publish.items_found_one', { count: found.toLocaleString() }) : t('publish.items_found_many', { count: found.toLocaleString() })), status: t('publish.starting_publish') });
    }
    publish();   // says which lines wait for a choice, or queues the job
  }

  /** The design is read again: forget what was read of the tree. */
  function reset() {
    tree.clear();
    [kidsLoading, kidsFailed].forEach(function (map) { Object.keys(map).forEach(function (id) { delete map[id]; }); });
    treeLoading = false;
    shown = false;
    ns.bomTable.markChecks({});   // the rings were of the last publish
  }

  // ---- What publishing covers ----------------------------------------------------

  /** What publishing covers: every line read of the design, as lines of the table. Publishing reads the rest of the tree first, so folds do not matter. */
  function covered() {
    const summary = host.summary();
    return { summary: summary, items: model.arrange(model.buildItems(rows, summary)) };
  }

  function pill(kind, count, label, tip) {
    const node = ui.el('span', 'pub-pill pub-pill-' + kind);
    node.appendChild(ui.el('span', 'pub-pill-dot'));
    node.appendChild(ui.el('b', '', String(count)));
    node.appendChild(ui.el('span', 'pub-pill-label', label));
    const info = ui.el('span', 'pub-pill-info');   // the small "i" says there is a tooltip to read
    info.appendChild(ui.svg(['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', 'M12 11v6', 'M12 7.5v.5']));
    node.appendChild(info);
    node.title = tip;
    return node;
  }

  /** The pills in the footer: what publishing covers (``null``: nothing is shown, so no pills). */
  function renderPills(cover) {
    const box = $('pub-pills');
    box.textContent = '';
    if (!cover) return;
    const plan = ns.bomPlan.publishPlan(rows, cover.summary);
    const skipped = cover.items.filter(function (item) { return item.status === 'skipped' && item.skip !== 'shared'; }).length;
    const shared = cover.items.filter(function (item) { return item.skip === 'shared'; }).length;
    box.appendChild(pill('items', plan.components.length, ' ' + t('publish.pill_items'), t('publish.pill_items_tip')));
    if (skipped) box.appendChild(pill('skipped', skipped, ' ' + t('publish.pill_skipped'), t('publish.pill_skipped_tip')));
    if (shared) box.appendChild(pill('skipped', shared, ' ' + t('publish.pill_shared_numbers'), t('publish.pill_shared_numbers_tip')));
  }

  /** The table was drawn again (or an assembly opened or closed): count again what publishing covers, and whether a choice still waits. */
  function refreshScope() {
    if (!shown) { renderPills(null); return; }
    const cover = covered();
    if (treeLoading) setPublishState(0, readingTree());
    else setPublishState(model.pendingReviews(cover.items));   // only lines in view wait for a choice: the others are not published
    renderPills(cover);
  }

  // ---- Publish -------------------------------------------------------------------

  /**
   * Publish the whole design. Levels not read yet are read and compared first (the whole tree, as Expand all does); lines that then
   * need a choice are shown and hold the publish back, and the next click goes on. The requests go to a folder for review in the
   * background (nothing is sent to Fusion Manage yet).
   */
  function publish() {
    if (treeLoading) return;
    if (tree.unloaded().length > 0) {
      publishAfterTree = true;
      showReading(readingForPublish());
      loadTree();
      return;
    }
    const cover = covered();
    const pending = model.pendingReviews(cover.items);
    if (pending > 0) {
      ns.toast.show((pending === 1 ? t('publish.needs_choice_one', { count: pending }) : t('publish.needs_choice_many', { count: pending })), { tone: 'error' });
      return;
    }
    const plan = ns.bomPlan.publishPlan(rows, cover.summary);
    jobs.start({
      summary: cover.summary,
      root_number: cover.summary.item_number || '',
      operations: plan.operations,
      items: plan.components.map(function (c) {
        return { id: c.id, root: !!c.root, item_number: c.item_number, part_number: c.part_number, description: c.description, name: c.name || '' };
      }),
    });
  }

  function openAddItems() {
    ns.pubAddItems.open({
      itemId: fmItemId,
      staged: model.stagedIds(),
      onAdd: function (picked) {
        model.stage(picked);
        draw(true);   // the new lines at the end, the folds as they were
      },
    });
  }

  /**
   * ``hostApi`` is the panel: ``summary()`` of the open design, ``ask(slot, payload)`` to request a section (its answer comes back
   * to ``finishKids`` / ``finishTree``), ``changed()`` to say what was read has changed and ``treeDone(entry)`` to say the whole tree was read (or failed).
   */
  function init(hostApi) {
    host = hostApi;
    $('pub-publish').addEventListener('click', publish);
    $('pub-add-items').addEventListener('click', openAddItems);
  }

  ns.pubBom = {
    init: init, clear: clear, showLoading: showLoading, showError: showError, showFirstLevel: showFirstLevel, status: status,
    finishKids: finishKids, finishTree: finishTree, treeStatus: treeStatus, reset: reset, loadTree: loadTree,
    rows: function () { return rows; }, partial: function () { return tree.unloaded().length > 0; },
  };
})(window.MfgUi);
