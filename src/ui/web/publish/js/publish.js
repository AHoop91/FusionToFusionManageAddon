/**
 * Publish Item panel: summary of the open model and the loading of what it shows. It asks Python for the sections of the model, one
 * after the other, and hands each answer on: the Bill of Materials to publish-bom.js (and its table, bom-table.js), the up-to-date
 * check to publish-check.js, and a row click, through the table, to the Details Panel (details.js).
 */
(function (ns) {
  'use strict';

  const $ = ns.$;
  const bridge = ns.bridge;
  const ui = ns.pubUi;
  const details = ns.pubDetails;
  const jobs = ns.pubJobs;
  const bom = ns.pubBom;
  const check = ns.pubCheck;

  const POLL_INTERVAL_MS = 100;   // a status check is a lookup in Python, so asking often is cheap and shortens the wait for an answer
  const SECTIONS = ['structure', 'thumbnail'];    // loaded for the open design once its summary is in
  const ALL_SECTIONS = ['properties', 'structure', 'thumbnail'];   // the design's own properties load last, once the Bill of Materials is in (for the up-to-date check), so they never slow it

  let currentSummary = null;   // summary of the open design
  let loadedKey = null;        // design the panel currently shows
  let lastLoad = 0;
  let generation = 0;          // counts reloads of the design
  const loaded = {};           // section -> true once shown for the current design
  const inflight = {};         // section -> true while loading
  const timers = {};           // section (or "component:<id>") -> poll timer
  const forceNext = {};        // section -> skip the cached copy on the next load
  const askedIn = {};          // slot -> the reload (``generation``) it was asked in; an answer for an older one is ignored

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

  // ---- Asking Python for sections --------------------------------------------------

  /** Ask Python for a section (or a component); its answer comes back to ``handleSection``. */
  function request(slot, payload) {
    clearTimeout(timers[slot]);
    bridge.send('load_publish_section', payload);
  }

  /** Ask for a slot of the Bill of Materials (the lines under an assembly, the whole tree), remembering which reload it was asked in. */
  function ask(slot, payload) {
    askedIn[slot] = generation;
    inflight[slot] = true;
    request(slot, payload);
  }

  function loadSection(name) {
    inflight[name] = true;
    if (name === 'structure') bom.showLoading();
    const force = !!forceNext[name];
    forceNext[name] = false;
    request(name, { section: name, force: force });
  }

  /** Load each section the first time it is needed for the open design. */
  function ensureSections() {
    SECTIONS.forEach(function (name) {
      if (loaded.summary && !loaded[name] && !inflight[name]) loadSection(name);
    });
  }

  /** The answer to a section that is still loading: show how far it is and ask again shortly. */
  function waitFor(name, entry) {
    if (name === 'structure') bom.status(entry);
    if (name === 'tree') bom.treeStatus(entry);
    timers[name] = setTimeout(function () {
      bridge.send('load_publish_section_status', { section: name });
    }, POLL_INTERVAL_MS);
  }

  function answerSummary(entry) {
    showLoading(false);
    if (entry.denied) { showDenied(entry.denied); return; }
    if (!entry.ok) { setThumbnail('', false); setSummary([ui.errorState(entry.message, function () { lastLoad = 0; refresh(true); })]); return; }
    loadedKey = entry.key;
    loaded.summary = true;
    renderSummary(entry.data);
    ensureSections();
  }

  /** The design's own properties, compared with Fusion Manage. */
  function answerProperties(entry) {
    const failure = entry.ok ? '' : entry.message || 'Unknown error';
    if (entry.ok) details.setRoot(entry.data.compare);
    else details.setRootError(failure);
    check.setRoot(entry.ok ? entry.data.compare : null, failure);
  }

  /** The first level of the Bill of Materials, compared with Fusion Manage. */
  function answerStructure(entry) {
    if (!entry.ok) {
      check.fail(entry.message || 'Unknown error');
      bom.showError(entry.message, function () { check.clearFailure(); loaded.structure = false; loadSection('structure'); check.update(); });
      return;
    }
    bom.showFirstLevel(entry.data);
    check.setNew(entry.data.design_new);
    if (!loaded.properties && !inflight.properties) loadSection('properties');   // quietly, after the BOM
  }

  function handleSection(r) {
    if (!r.ok) return;
    const entry = r.result;
    const name = entry.section;
    if (askedIn[name] !== undefined && askedIn[name] !== generation) return;   // asked before the last reload: it is not wanted
    clearTimeout(timers[name]);
    if (entry.pending) { waitFor(name, entry); return; }
    inflight[name] = false;
    if (name === 'tree') { bom.finishTree(entry); return; }
    if (name.indexOf('children:') === 0) { bom.finishKids(name.slice('children:'.length), entry); return; }
    if (name.indexOf('component:') === 0) { details.handleComponent(name.slice('component:'.length), entry); return; }
    if (name === 'summary') { answerSummary(entry); return; }
    if (name.indexOf('thumbnail:') === 0) { details.handleThumbnail(name.slice('thumbnail:'.length), entry); return; }
    loaded[name] = true;
    if (name === 'thumbnail') {   // no thumbnail (or none yet) just leaves the box empty
      const url = entry.ok ? entry.data.url : '';
      setThumbnail(url, false);
      details.setThumbnail(currentSummary ? currentSummary.component_id : '', url);   // the design's details show the same one
    } else if (name === 'properties') {
      answerProperties(entry);
    } else {
      answerStructure(entry);
    }
  }

  /** Read the open design again (all sections), skipping the cached copies when ``force``. ``now`` ignores the pause that merges triggers. */
  function refresh(force, now) {
    // Focus, sign-in and the button can all fire together; load once.
    if (!now && Date.now() - lastLoad < 2000) return;
    lastLoad = Date.now();
    generation++;   // answers still on their way for the old contents are ignored
    bom.reset();
    Object.keys(timers).forEach(function (slot) { clearTimeout(timers[slot]); });
    ALL_SECTIONS.forEach(function (name) {
      loaded[name] = false;
      inflight[name] = false;
      forceNext[name] = !!force;
    });
    bom.clear();
    check.reset();
    details.reset(force);
    loaded.summary = false;
    forceNext.summary = !!force;
    showLoading(true);
    loadSection('summary');
  }

  // ---- Start ---------------------------------------------------------------------

  function init() {
    bom.init({ summary: function () { return currentSummary || {}; }, ask: ask, changed: check.update });
    check.init({
      summary: function () { return currentSummary || {}; },
      rows: bom.rows,
      structureLoaded: function () { return !!loaded.structure; },
      partial: bom.partial,
    });
    details.init({
      request: request,
      // The design's row was opened: read its own properties the first time.
      onRootLoad: function () {
        if (loaded.summary && !loaded.properties && !inflight.properties) loadSection('properties');
      },
      onRootRetry: function () {
        loaded.properties = false;
        loadSection('properties');
      },
    });
    jobs.init({ onFinished: function () { refresh(true, true); }, onChecks: ns.bomTable.markChecks });   // Fusion Manage changed: read the whole panel again, not the cached copies
    bridge.on('load_publish_section', handleSection);
    bridge.on('load_publish_section_status', handleSection);
    $('pub-refresh').addEventListener('click', function () { refresh(true, true); });   // a click is always wanted: not merged with another trigger
    // The palette stays open while the user switches designs. Clicking into it also fires focus,
    // so reload only when a different design is open; the same design is read again only by the refresh button.
    bridge.on('get_publish_model_key', function (r) {
      if (r.ok && r.result.key !== loadedKey) refresh(false);
    });
    function checkDesign() {
      if (!$('view-app').hidden && !inflight.summary) bridge.send('get_publish_model_key');
    }
    window.addEventListener('focus', checkDesign);
    bridge.on('palette_opened', checkDesign);
    // The sign-in state is drawn again each time Python reports it (a token renewed, a page shown again): read the design only when the
    // user has just signed in, and otherwise only check that the open design is still the one shown.
    let wasSignedIn = false;
    ns.auth.onChange(function (signedIn) {
      const justSignedIn = signedIn && !wasSignedIn;
      wasSignedIn = signedIn;
      if (justSignedIn) refresh(true);
      else if (signedIn) checkDesign();
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
