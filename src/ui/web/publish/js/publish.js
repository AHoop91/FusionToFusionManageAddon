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

  const POLL_INTERVAL_MS = 100;   // a status check is a lookup in Python, so asking often is cheap and shortens the wait for an answer
  const STALE_MS = 600000;   // the panel shown again after this long reads Fusion Manage afresh
  const SECTIONS = ['structure', 'thumbnail'];    // loaded for the open design once its summary is in
  const ALL_SECTIONS = ['properties', 'structure', 'thumbnail'];   // the design's own properties load last, once the Bill of Materials is in (for the up-to-date check), so they never slow it

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

  /** Show the thumbnail, or, while ``loading``, a skeleton in its place (it arrives on its own, after the rest). */
  function setThumbnail(url, loading) {
    const box = $('pub-thumb');
    box.classList.toggle('pub-thumb-loading', !!loading);
    // Only http(s) URLs, so nothing else is ever loaded into the style.
    box.style.backgroundImage = !loading && /^https?:\/\//i.test(url) ? 'url("' + url.replace(/"/g, '%22') + '")' : '';
  }

  function renderSummary(s) {
    currentSummary = s;
    setThumbnail('', true);
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
    $('pub-denied').hidden = true;
    if (on) ui.warnWhenSlow($('pub-loader').querySelector('p'), 'Loading item...');
  }

  /** Say, in the middle of the panel and in place of the item, that the user's permissions do not allow publishing. */
  function showDenied(message) {
    $('pub-content').hidden = true;
    $('pub-denied-text').textContent = message;
    $('pub-denied').hidden = false;
  }

  // ---- Up-to-date check ------------------------------------------------------------

  let rootCompare = null;   // the design's own properties compared with Fusion Manage (null until read)
  let rootFailed = '';      // why the design could not be checked

  const DIFFERING = ['new', 'changed', 'added', 'mismatch'];   // BOM lines the design has that Fusion Manage lacks or holds differently; lines only Fusion Manage has (it extends the BOM) are ignored

  function plural(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }

  const ISSUES = {
    new: 'Not in Fusion Manage',
    changed: 'Quantity differs',
    mismatch: 'Different item at this position',
    added: 'Added with Add Existing Items',
  };

  let report = { state: 'checking', text: '', props: [], lines: [], subject: '' };   // what the button last said, listed in its dialog

  function quantityText(quantity) { return quantity === '' || quantity === undefined ? '-' : 'Qty ' + quantity; }

  /** The discrepancies, as the dialog lists them: attributes of the design, then the Bill of Materials lines. */
  function discrepancies() {
    const model = ns.bomModel;
    const props = rootCompare.rows.filter(function (r) { return r.status === 'mismatch' || r.status === 'new'; }).map(function (r) {
      const own = r.shown || r.value;
      return { name: r.name, fusion: own ? own + (r.unit ? ' ' + r.unit : '') : '', fm: r.fm_value };
    });
    const items = currentRows.length ? model.arrange(model.buildItems(currentRows, currentSummary || {})) : [];
    const lines = items.filter(function (item) { return DIFFERING.indexOf(model.statusOf(item)) >= 0; }).map(function (item) {
      const status = model.statusOf(item);
      const different = status === 'mismatch';
      return {
        number: item.design.pn, name: item.design.name, issue: ISSUES[status] || status, component: item.component,
        fusion: different ? item.design.pn : quantityText(model.quantityOf(item)),
        fm: status === 'new' || status === 'added' ? '-' : different ? item.fm.pn : quantityText(item.fm.quantity),
      };
    });
    return { props: props, lines: lines };
  }

  /** Round button at the top right: scanning while the Bill of Materials and the design's properties are read, then what they say. */
  function updateCheck() {
    const button = $('pub-check');
    const count = $('pub-check-count');
    let state = 'checking', text = 'Checking Fusion Manage...', n = 0;
    let found = { props: [], lines: [] };
    if (!loaded.structure && !rootFailed) {
      state = 'idle';   // hidden until the panel has loaded; the check then runs quietly
    } else if (rootFailed) {
      state = 'error'; text = 'Could not check: ' + rootFailed;
    } else if (loaded.structure && rootCompare) {
      const own = details.changeState(rootCompare);
      found = discrepancies();
      n = found.props.length + found.lines.length;
      if (own === 'unknown') { state = 'error'; text = 'Fusion Manage could not be read.'; }
      else if (own === 'multiple') { state = 'changes'; text = 'Several Fusion Manage items match this design. Choose one in its details.'; }
      else if (own === 'new') { state = 'changes'; text = 'Not in Fusion Manage yet: publishing creates it.'; n = 0; found = { props: [], lines: [] }; }
      else if (n) { state = 'changes'; text = plural(found.props.length, 'attribute difference') + ' and ' + plural(found.lines.length, 'Bill of Materials line') + ' to update.'; }
      else { state = 'ok'; text = 'The design matches Fusion Manage.'; }
    }
    const summary = currentSummary || {};
    report = { state: state, text: text, props: found.props, lines: found.lines, subject: summary.item_number || 'this design' };
    button.dataset.state = state;
    button.title = state === 'checking' ? text : text + ' Click for details.';
    button.setAttribute('aria-label', button.title);
    count.hidden = !n;
    count.textContent = n > 99 ? '99+' : String(n);
  }

  function checkClicked() {
    if (report.state === 'checking' || report.state === 'idle') return;
    ns.pubCheckReport.open(report, {
      onLine: details.open,
    });
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
      root_number: summary.item_number || '',
      operations: plan.operations,
      items: plan.components.map(function (c) {
        return { id: c.id, root: !!c.root, item_number: c.item_number, part_number: c.part_number, description: c.description, name: c.name || '', fm_item: details.choiceFor(c) };
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

  /** Rows of grey bars in place of the table while it loads, with a line saying what is happening. */
  function bomLoading() {
    const host = clearBom();
    const status = ui.el('p', 'muted pub-bom-status');
    status.id = 'pub-bom-status';
    host.appendChild(status);
    const table = ui.el('div', 'card pub-skel-table');
    table.setAttribute('aria-hidden', 'true');
    for (let row = 0; row < 8; row++) {
      const line = ui.el('div', 'pub-skel-row');
      ['pub-skel-wide', 'pub-skel-mid', 'pub-skel-short'].forEach(function (width) { line.appendChild(ui.el('span', 'pub-skel ' + width)); });
      table.appendChild(line);
    }
    host.appendChild(table);
    bomStatus({});
  }

  let bomStatusText = '';

  /** What the Bill of Materials is doing: reading it (and how far, once it takes several pages), then comparing it with Fusion Manage. */
  function bomStatus(entry) {
    const note = $('pub-bom-status');
    if (!note) return;
    const text = entry.stage === 'comparing' ? 'Comparing with Fusion Manage...'
      : entry.progress ? 'Reading the Bill of Materials... ' + Number(entry.progress).toLocaleString() + ' lines so far'
      : 'Reading the Bill of Materials...';
    if (text === bomStatusText && note.textContent) return;   // the same words must not restart the "taking longer" timer
    bomStatusText = text;
    ui.warnWhenSlow(note, text);   // adds a note if nothing new has been said for a long while
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
      if (name === 'structure') bomStatus(entry);
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
      if (entry.denied) { showDenied(entry.denied); return; }
      if (!entry.ok) { setThumbnail('', false); setSummary([ui.errorState(entry.message, function () { lastLoad = 0; refresh(true); })]); return; }
      loadedKey = entry.key;
      loaded.summary = true;
      renderSummary(entry.data);
      ensureSections();
      return;
    }
    if (name.indexOf('thumbnail:') === 0) {
      details.handleThumbnail(name.slice('thumbnail:'.length), entry);
      return;
    }
    loaded[name] = true;
    if (name === 'thumbnail') {   // no thumbnail (or none yet) just leaves the box empty
      const url = entry.ok ? entry.data.url : '';
      setThumbnail(url, false);
      details.setThumbnail(currentSummary ? currentSummary.component_id : '', url);   // the design's details show the same one
      return;
    }
    if (name === 'properties') {
      rootCompare = entry.ok ? entry.data.compare : null;
      rootFailed = entry.ok ? '' : entry.message || 'Unknown error';
      if (entry.ok) details.setRoot(entry.data.compare);
      else details.setRootError(rootFailed);
      updateCheck();
      return;
    }
    if (!entry.ok) {
      rootFailed = entry.message || 'Unknown error';
      updateCheck();
      bomError(entry.message, function () { rootFailed = ''; loaded.structure = false; loadSection('structure'); updateCheck(); });
      return;
    }
    ns.bomModel.clearDecisions();   // fresh comparison: nothing is chosen or added yet
    fmItemId = entry.data.fm_item_id || '';
    renderBom(entry.data.rows, !!entry.data.pick);
    updateCheck();
    if (!loaded.properties && !inflight.properties) loadSection('properties');   // quietly, after the BOM
  }

  /** Read the open design again (all sections), skipping the cached copies when ``force``. ``now`` ignores the pause that merges triggers. */
  function refresh(force, now) {
    // Focus, sign-in and the button can all fire together; load once.
    if (!now && Date.now() - lastLoad < 2000) return;
    lastLoad = Date.now();
    ALL_SECTIONS.forEach(function (name) {
      loaded[name] = false;
      inflight[name] = false;
      forceNext[name] = !!force;
      clearTimeout(timers[name]);
    });
    clearBom();
    rootCompare = null;
    rootFailed = '';
    updateCheck();
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
      // The design's row was opened: read its own properties the first time.
      onRootLoad: function () {
        if (loaded.summary && !loaded.properties && !inflight.properties) loadSection('properties');
      },
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
    jobs.init({ onFinished: function () { refresh(true, true); } });   // Fusion Manage changed: read the whole panel again, not the cached copies
    $('pub-publish').addEventListener('click', publish);
    bridge.on('load_publish_section', handleSection);
    bridge.on('load_publish_section_status', handleSection);
    $('pub-check').addEventListener('click', checkClicked);
    $('pub-refresh').addEventListener('click', function () { refresh(true); });
    $('pub-add-items').addEventListener('click', openAddItems);
    // The palette stays open while the user switches designs. Clicking into it
    // also fires focus, so reload only when a different design is open.
    bridge.on('get_publish_model_key', function (r) {
      if (!r.ok) return;
      // Another design, or the same one shown again after ten minutes (Fusion Manage may have changed).
      if (r.result.key !== loadedKey) refresh(false);
      else if (Date.now() - lastLoad > STALE_MS) refresh(true);
    });
    window.addEventListener('focus', function () {
      if (!$('view-app').hidden && !inflight.summary) bridge.send('get_publish_model_key');
    });
    // Opening the panel always reads Fusion Manage again, never a copy kept from an earlier opening.
    ns.auth.onChange(function (signedIn) { if (signedIn) refresh(true); });
    bridge.on('palette_opened', function () {
      if (!$('view-app').hidden) refresh(true, true);
    });
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
