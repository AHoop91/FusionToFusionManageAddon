/**
 * Publish Item panel: summary and bill of materials of the open model. It loads the sections
 * from Python, one after the other, and hands them to the table (bom-table.js) and, through a
 * row click, to the Details Panel (details.js).
 */
(function (ns) {
  'use strict';

  const $ = ns.$;
  const bridge = ns.bridge;
  const ui = ns.pubUi;
  const details = ns.pubDetails;
  const jobs = ns.pubJobs;

  const POLL_INTERVAL_MS = 700;
  const SECTIONS = ['properties', 'structure'];   // loaded for the open design once its summary is in

  let currentSummary = null;   // summary of the open design
  let loadedKey = null;        // design the panel currently shows
  let lastLoad = 0;
  let currentRows = [];        // compared rows of the Bill of Materials shown
  let fmItemId = '';           // Fusion Manage item the BOM was compared with; empty when the design has none
  const loaded = {};           // section -> true once shown for the current design
  const inflight = {};         // section -> true while loading
  const timers = {};           // section (or "component:<id>") -> poll timer
  const forceNext = {};        // section -> skip the cached copy on the next load

  // ---- Summary -----------------------------------------------------------------

  function line(label, value) {
    const row = ui.el('div', 'pub-line');
    row.appendChild(ui.el('span', 'pub-label', label));
    row.appendChild(ui.el('span', 'pub-value', value));
    return row;
  }

  function setSummary(children) {
    const box = $('pub-summary');
    box.textContent = '';
    children.forEach(function (c) { box.appendChild(c); });
  }

  function setThumbnail(url) {
    // Only http(s) URLs, so nothing else is ever loaded into the style.
    $('pub-thumb').style.backgroundImage = /^https?:\/\//i.test(url) ? 'url("' + url.replace(/"/g, '%22') + '")' : '';
  }

  function renderSummary(s) {
    currentSummary = s;
    setThumbnail(s.thumbnail);
    setSummary([
      line('Item Number', s.item_number || '-'),
      line('Part Number', s.part_number || '-'),
      line('Description', s.description || '-'),
    ]);
  }

  /** Show the bouncing balls in place of the panel content while the summary loads. */
  function showLoading(on) {
    $('pub-loader').hidden = !on;
    $('pub-content').hidden = on;
  }

  // ---- Bill of materials panel ---------------------------------------------------

  /** Publish is available once the Bill of Materials is shown and every differing line has a choice. */
  function setPublishState(pending, reason) {
    const button = $('pub-publish');
    button.disabled = pending > 0 || !!reason;
    button.title = reason || (pending > 0
      ? 'Review ' + pending + ' line' + (pending === 1 ? '' : 's') + ' first: choose keep both or remove on each Review line.'
      : 'Publish the changes.');
  }

  /** Publish: queue the changed items and BOM lines; they go to a folder for review in the background (nothing is sent to Fusion Manage yet). */
  function publish() {
    const summary = currentSummary || {};
    const root = summary;
    const model = ns.bomModel;
    if (model.pendingReviews(model.arrange(model.buildItems(currentRows, root))) > 0) return;
    const plan = model.publishPlan(currentRows, root);
    jobs.start({
      summary: summary,
      root_number: summary.item_number || summary.part_number || '',
      operations: plan.operations,
      items: plan.components.map(function (c) {
        return { id: c.id, root: !!c.root, item_number: c.item_number, part_number: c.part_number, description: c.description, name: c.name || '', thumbnail: c.thumbnail || '', fm_item: details.choiceFor(c) };
      }),
    });
  }

  /** Add Items needs the Fusion Manage item of the design; ``reason`` says why it is not available yet. */
  function setAddItemsState(reason) {
    const button = $('pub-add-items');
    button.disabled = !!reason;
    button.title = reason || 'Add Fusion Manage items to the end of the Bill of Materials.';
  }

  function openAddItems() {
    const model = ns.bomModel;
    ns.pubAddItems.open({
      itemId: fmItemId,
      staged: model.stagedIds(),
      onAdd: function (picked) {
        model.stage(picked);
        ns.pubToast.show(picked.length === 1 ? 'Added ' + (picked[0].number || picked[0].name) + ' to the Bill of Materials' : 'Added ' + picked.length + ' items to the Bill of Materials', { tone: 'success' });
        renderBom(currentRows, false);   // draw the table again with the new lines at the end
      },
    });
  }

  function clearBom() {
    setAddItemsState('Waiting for the Bill of Materials.');
    setPublishState(0, 'Waiting for the Bill of Materials.');
    const host = $('pub-bom');
    host.classList.remove('pub-loading');
    host.textContent = '';
    return host;
  }

  function bomLoading() {
    clearBom().classList.add('pub-loading');
    $('pub-bom').appendChild(ui.loaderNode());
  }

  function bomMessage(text) {
    const card = ui.el('div', 'card');
    card.appendChild(ui.el('p', 'muted', text));
    clearBom().appendChild(card);
  }

  /** A failure in the middle of the panel, so the message centres in it. */
  function bomError(message, onRetry) {
    clearBom().classList.add('pub-loading');
    $('pub-bom').appendChild(ui.errorState(message, onRetry));
  }

  /** The design and Fusion Manage lines in one compare table; a row click opens its details. */
  function renderBom(rows, pick) {
    const host = clearBom();
    if (pick) {   // no table until the question is answered, so open the design's details, which ask it
      bomMessage('Several Fusion Manage items match this design. Choose one in the details to compare the Bill of Materials.');
      setAddItemsState('Choose the Fusion Manage item for this design first.');
      setPublishState(0, 'Choose the Fusion Manage item for this design first.');
      details.open(ns.bomModel.rootComponent(currentSummary || {}));
      return;
    }
    currentRows = rows;
    const addReason = fmItemId ? '' : 'The design is not in Fusion Manage yet, so there is no Bill of Materials to add to.';
    if (!rows.length && !ns.bomModel.stagedIds().length) {
      bomMessage('This item has no child components.');
      setAddItemsState(addReason);
      setPublishState(0);
      return;
    }
    ns.bomTable.render(host, rows, currentSummary || {}, details.open, setPublishState);
    setAddItemsState(addReason);
  }

  // ---- Loading sections ------------------------------------------------------------

  /** Ask Python for a section (or a component); its answer comes back to ``handleSection``. */
  function request(slot, payload) {
    clearTimeout(timers[slot]);
    bridge.send('load_publish_section', payload);
  }

  function loadSection(name) {
    inflight[name] = true;
    if (name === 'structure') bomLoading();
    const force = !!forceNext[name];
    forceNext[name] = false;
    const rootItem = name === 'properties' || name === 'structure' ? currentSummary || {} : null;
    request(name, { section: name, force: force, fm_item: rootItem ? details.choiceFor(rootItem) : '' });
  }

  /** Load each section the first time it is needed for the open design. */
  function ensureSections() {
    SECTIONS.forEach(function (name) {
      if (loaded.summary && !loaded[name] && !inflight[name]) loadSection(name);
    });
  }

  function handleSection(r) {
    if (!r.ok) return;
    const entry = r.result;
    const name = entry.section;
    clearTimeout(timers[name]);
    if (entry.pending) {
      timers[name] = setTimeout(function () {
        bridge.send('load_publish_section_status', { section: name });
      }, POLL_INTERVAL_MS);
      return;
    }
    inflight[name] = false;
    if (name.indexOf('component:') === 0) {
      details.handleComponent(name.slice('component:'.length), entry);
      return;
    }
    if (name === 'summary') {
      showLoading(false);
      if (!entry.ok) { setThumbnail(''); setSummary([ui.errorState(entry.message, function () { lastLoad = 0; refresh(true); })]); return; }
      loadedKey = entry.key;
      loaded.summary = true;
      renderSummary(entry.data);
      ensureSections();
      return;
    }
    loaded[name] = true;
    if (name === 'properties') {
      if (entry.ok) details.setRoot(entry.data.compare);
      else details.setRootError(entry.message || 'Unknown error');
      return;
    }
    if (!entry.ok) {
      bomError(entry.message, function () { loaded.structure = false; loadSection('structure'); });
      return;
    }
    ns.bomModel.clearDecisions();   // fresh comparison: nothing is chosen or added yet
    fmItemId = entry.data.fm_item_id || '';
    renderBom(entry.data.rows, !!entry.data.pick);
  }

  /** Read the open design again (all sections), skipping the cached copies when ``force``. */
  function refresh(force) {
    // Focus, sign-in and the button can all fire together; load once.
    if (Date.now() - lastLoad < 2000) return;
    lastLoad = Date.now();
    SECTIONS.forEach(function (name) {
      loaded[name] = false;
      inflight[name] = false;
      forceNext[name] = !!force;
      clearTimeout(timers[name]);
    });
    clearBom();
    details.reset(force);
    loaded.summary = false;
    forceNext.summary = !!force;
    showLoading(true);
    loadSection('summary');
  }

  // ---- Start ---------------------------------------------------------------------

  function init() {
    details.init({
      request: request,
      // The user picked a Fusion Manage item for the design: compare its properties and BOM again with it.
      onRootChoice: function () {
        inflight.properties = true;
        bridge.send('load_publish_section', { section: 'properties', force: true, fm_item: details.choiceFor(currentSummary || {}) });
        if (loaded.structure) {
          inflight.structure = true;
          bomLoading();   // not the old comparison while the new one loads
          bridge.send('load_publish_section', { section: 'structure', force: true, fm_item: details.choiceFor(currentSummary || {}) });
        }
      },
      onRootRetry: function () {
        loaded.properties = false;
        loadSection('properties');
      },
    });
    jobs.init();
    $('pub-publish').addEventListener('click', publish);
    bridge.on('load_publish_section', handleSection);
    bridge.on('load_publish_section_status', handleSection);
    $('pub-refresh').addEventListener('click', function () { refresh(true); });
    $('pub-add-items').addEventListener('click', openAddItems);
    // The palette stays open while the user switches designs. Clicking into it
    // also fires focus, so reload only when a different design is open.
    bridge.on('get_publish_model_key', function (r) {
      if (r.ok && r.result.key !== loadedKey) refresh(false);
    });
    window.addEventListener('focus', function () {
      if (!$('view-app').hidden && !inflight.summary) bridge.send('get_publish_model_key');
    });
    ns.auth.onChange(function (signedIn) { if (signedIn) refresh(false); });
  }

  function start() {
    // Fusion injects `adsk` asynchronously, so wait for it.
    if (typeof adsk === 'undefined') { setTimeout(start, 100); return; }
    ns.shell.mountHeader();
    ns.account.init();
    ns.auth.init();
    init();
    ns.auth.refresh();
  }

  start();
})(window.MfgUi);
