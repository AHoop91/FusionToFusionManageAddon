/**
 * Publish Item panel: the Bill of Materials area, as ``ns.pubBom``.
 *
 * Shows what has been read of the Bill of Materials (the table, bom-table.js; or the loading skeleton, a message, or an error),
 * reads the lines under an assembly when it is opened and the whole tree for Expand all, and queues the publish. Publishing covers
 * what is in view (see bom-scope.js); the pills in the footer count what that is. The panel (publish.js) sends the requests and hands
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

  const READING_TREE = 'Reading every level of the Bill of Materials...';

  let host = null;          // { summary(), ask(slot, payload), request(slot, payload), changed() }, given to ``init``
  let rows = [];            // compared rows of the Bill of Materials read so far
  let fmItemId = '';        // Fusion Manage item the BOM was compared with; empty when the design has none
  let designNew = false;    // Fusion Manage holds no item for the design: publishing creates it, and items can still be added to its BOM
  const kidsLoading = {};   // component id -> true while the lines under it are read
  const kidsFailed = {};    // component id -> why they could not be read
  let treeLoading = false;  // the rest of the tree is being read (Expand all)
  let treeProgress = '';    // how far, while it is
  let shown = false;        // the table is on screen (not the skeleton, a message or an error)
  let statusText = '';      // what the loading line last said

  // ---- Buttons of the area -------------------------------------------------------

  /** Publish is available once the Bill of Materials is shown and every differing line has a choice. */
  function setPublishState(pending, reason) {
    const button = $('pub-publish');
    button.disabled = pending > 0 || !!reason;
    button.title = reason || (pending > 0
      ? 'Review ' + pending + ' line' + (pending === 1 ? '' : 's') + ' first: choose keep both or remove on each Review line.'
      : 'Publish the changes.');
  }

  /** Add Items needs the design to be compared with Fusion Manage (an item found, or none yet); ``reason`` says why it is not available. */
  function setAddItemsState(reason) {
    const button = $('pub-add-items');
    button.disabled = !!reason;
    button.title = reason || 'Add Fusion Manage items to the end of the Bill of Materials.';
  }

  // ---- What the area shows -------------------------------------------------------

  function clear() {
    shown = false;
    renderPills(null);
    setAddItemsState('Waiting for the Bill of Materials.');
    setPublishState(0, 'Waiting for the Bill of Materials.');
    const area = $('pub-bom');
    area.classList.remove('pub-loading');
    area.textContent = '';
    return area;
  }

  /** What the Bill of Materials is doing: reading it (and how far, once it takes several pages), then comparing it with Fusion Manage. */
  function status(entry) {
    const note = $('pub-bom-status');
    if (!note) return;
    const text = entry.stage === 'comparing' ? 'Comparing with Fusion Manage...'
      : entry.progress ? 'Reading the Bill of Materials... ' + Number(entry.progress).toLocaleString() + ' lines so far'
      : 'Reading the Bill of Materials...';
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
    busyText: function () { return treeProgress || READING_TREE; },
  };

  /** The design and Fusion Manage lines in one compare table; a row click opens its details. ``keepFolds`` leaves the assemblies open or closed as they are. */
  function show(lines, shared, keepFolds) {
    const area = clear();
    if (shared) {   // no table until the number is fixed in Fusion Manage, so open the design's details, which say so
      showMessage('Several Fusion Manage items carry this design\'s item number. Renumber or remove the extra items in Fusion Manage, then refresh. The Bill of Materials is not compared until then.');
      setAddItemsState('Several Fusion Manage items carry this design\'s item number: fix it in Fusion Manage first.');
      setPublishState(0, 'Several Fusion Manage items carry this design\'s item number: fix it in Fusion Manage first.');
      details.open(model.rootComponent(host.summary()));
      return;
    }
    rows = lines;
    const addReason = fmItemId || designNew ? '' : 'Fusion Manage has not been compared with this design yet.';
    if (!lines.length && !model.stagedIds().length) {
      showMessage('This item has no child components.');
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
      kidsFailed[id] = entry.message || 'Unknown error';
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
    treeProgress = entry.stage === 'comparing' ? 'Comparing with Fusion Manage...'
      : entry.progress ? 'Reading the Bill of Materials... ' + Number(entry.progress).toLocaleString() + ' lines so far' : '';
    const button = document.querySelector('.pub-cmp-tool-busy');
    if (button) { button.title = lazy.busyText(); button.setAttribute('aria-label', button.title); }
  }

  function finishTree(entry) {
    treeLoading = false;
    if (!entry.ok) {
      ns.toast.show('Could not read the whole Bill of Materials: ' + (entry.message || 'Unknown error'), { tone: 'error' });
      draw(true);
      return;
    }
    tree.setAll(entry.data.rows);
    ns.bomTable.openAllOnNextDraw();   // Expand all: everything opens
    draw(true);
    host.changed();
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

  /** What is in view: the design and the lines of every open assembly, as lines of the table, and how many assemblies are closed. */
  function covered() {
    const summary = host.summary();
    const isOpen = ns.bomTable.isOpen;
    const visible = ns.bomScope.visibleRows(rows, summary.component_id || '', isOpen);
    return { summary: summary, visible: visible, items: model.arrange(model.buildItems(visible, summary)), closed: ns.bomScope.closedAssemblies(visible, isOpen) };
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
    const plan = ns.bomPlan.publishPlan(cover.visible, cover.summary);
    const skipped = cover.items.filter(function (item) { return item.status === 'skipped' && item.skip !== 'shared'; }).length;
    const shared = cover.items.filter(function (item) { return item.skip === 'shared'; }).length;
    box.appendChild(pill('items', plan.components.length, ' Items', 'Items checked against Fusion Manage when you publish, and created or updated where they differ: the design and every component in view.'));
    if (skipped) box.appendChild(pill('skipped', skipped, ' Lines Skipped', 'No item number, or below a skipped line: nothing is published for these lines, or for what is below them.'));
    if (shared) box.appendChild(pill('skipped', shared, ' Shared Item Numbers', 'Components that carry the same item number would write to one Fusion Manage item, so none of them is published, nor what is below them. Give each its own item number in Fusion.'));
    if (cover.closed) box.appendChild(pill('closed', cover.closed, ' Sub Assemblies Skipped', 'Closed sub assemblies: what is under them is not published. Open them, or use Expand all, to include them.'));
  }

  /** What is in view changed (a draw, an assembly opened or closed): count again what publishing covers, and whether a choice still waits. */
  function refreshScope() {
    if (!shown) { renderPills(null); return; }
    const cover = covered();
    if (treeLoading) setPublishState(0, READING_TREE);
    else setPublishState(model.pendingReviews(cover.items));   // only lines in view wait for a choice: the others are not published
    renderPills(cover);
  }

  // ---- Publish -------------------------------------------------------------------

  /**
   * Publish what is in view: the design and the lines of every open assembly. What is under a closed assembly is left out, so the
   * panel publishes exactly what it shows. The requests go to a folder for review in the background (nothing is sent to Fusion Manage yet).
   */
  function publish() {
    if (treeLoading) return;
    const cover = covered();
    const pending = model.pendingReviews(cover.items);
    if (pending > 0) {
      ns.toast.show(pending + ' line' + (pending === 1 ? ' needs' : 's need') + ' a choice before publishing: keep both or remove, on each Review line.', { tone: 'error' });
      return;
    }
    const plan = ns.bomPlan.publishPlan(cover.visible, cover.summary);
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
   * to ``finishKids`` / ``finishTree``), and ``changed()`` to say what was read has changed.
   */
  function init(hostApi) {
    host = hostApi;
    $('pub-publish').addEventListener('click', publish);
    $('pub-add-items').addEventListener('click', openAddItems);
  }

  ns.pubBom = {
    init: init, clear: clear, showLoading: showLoading, showError: showError, showFirstLevel: showFirstLevel, status: status,
    finishKids: finishKids, finishTree: finishTree, treeStatus: treeStatus, reset: reset,
    rows: function () { return rows; }, partial: function () { return tree.unloaded().length > 0; },
  };
})(window.MfgUi);
