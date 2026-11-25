/**
 * Publish Item panel: summary of the open model and the loading of what it shows. It asks Python for the sections of the model (the Bill of
 * Materials and the MBOM tree together, once the MBOM is chosen), and hands each answer on: the Bill of Materials to publish-bom.js (which gives the structure to mbom-viewer.js, what Publish
 * sends), the design's own details to details.js.
 */
(function (ns) {
  'use strict';

  const $ = ns.$;
  const bridge = ns.bridge;
  const ui = ns.pubUi;
  const details = ns.pubDetails;
  const jobs = ns.pubJobs;
  const bom = ns.pubBom;
  const mbom = ns.pubMbom;
  const viewer = ns.mbomViewer;
  function t(key, params) { return ns.i18n.t(key, params); }

  const POLL_INTERVAL_MS = 100;   // a status check is a lookup in Python, so asking often is cheap and shortens the wait for an answer
  const SECTIONS = ['thumbnail', 'mbom'];    // loaded for the open design once its summary is in
  const AFTER_MBOM = ['structure'];          // what searches Fusion Manage by item number: not before the MBOM lookup (lineage and asset) has answered
  const BOM_SECTIONS = ['properties', 'structure'];   // the design's own properties load last, once the Bill of Materials is in (for the up-to-date check), so they never slow it

  let currentSummary = null;   // summary of the open design
  let target = '';             // the item number of the MBOM chosen in the dropdown: what the design is compared with and published to ("" is the design's own)
  let loadedKey = null;        // design the panel currently shows
  let loadedStamp = '';        // the hub and settings it was read under
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
      line(t('publish.item_number'), s.item_number || '-'),
      line(t('publish.file_name'), s.file_name || '-'),
      line(t('publish.description'), s.description || '-'),
    ]);
  }

  /** Show the bouncing balls in place of the panel content while the summary loads. */
  function showLoading(on) {
    $('pub-loader').hidden = !on;
    $('pub-content').hidden = on;
    $('pub-denied').hidden = true;
    if (on) ui.warnWhenSlow($('pub-loader').querySelector('p'), t('publish.loading_item'));
  }

  /** Say, in the middle of the panel and in place of the item, that the user's permissions do not allow publishing. */
  function showDenied(message) {
    $('pub-content').hidden = true;
    $('pub-denied-text').textContent = message;
    $('pub-denied').hidden = false;
  }

  // ---- Asking Python for sections --------------------------------------------------

  /** The summary of the open design as the rest of the panel reads it: with the item number of the chosen MBOM when there is one. */
  function summary() {
    return target ? Object.assign({}, currentSummary, { item_number: target }) : currentSummary || {};
  }

  /** Ask Python for a section (or a component); its answer comes back to ``handleSection``. */
  function request(slot, payload) {
    clearTimeout(timers[slot]);
    bridge.send('load_publish_section', Object.assign({ target: target, target_id: mbom.idOf(target) }, payload));   // the id: the item is read, not searched for by its number
  }

  /** The MBOM of the target, for the structure viewer: asked for at the same time as the Bill of Materials, and never a copy kept from before (its line ids
   *  are what edits are sent against, and Fusion Manage changes under the panel). */
  function askMbomTree() {
    askedIn.mbom_tree = generation;
    request('mbom_tree', { section: 'mbom_tree', force: true });
  }

  function loadSection(name) {
    inflight[name] = true;
    if (BOM_SECTIONS.indexOf(name) >= 0) askedIn[name] = generation;   // an answer for the Bill of Materials of an earlier reload (or MBOM) is ignored
    const force = !!forceNext[name];
    forceNext[name] = false;
    request(name, { section: name, force: force });
  }

  /** Load each of ``names`` the first time it is needed for the open design. */
  function ensureSections(names) {
    names.forEach(function (name) {
      if (loaded.summary && !loaded[name] && !inflight[name]) loadSection(name);
    });
  }

  /** The answer to a section that is still loading: show how far it is and ask again shortly. */
  function waitFor(name, entry) {
    if (name === 'structure') bom.status(entry);   // the long read: its line count is told
    timers[name] = setTimeout(function () {
      bridge.send('load_publish_section_status', { section: name });
    }, POLL_INTERVAL_MS);
  }

  function answerSummary(entry) {
    showLoading(false);
    if (entry.denied) { showDenied(entry.denied); return; }
    if (!entry.ok) { setThumbnail('', false); setSummary([ui.errorState(entry.message, function () { lastLoad = 0; refresh(true); })]); return; }
    if (entry.key !== loadedKey) {   // another design: the MBOM chosen, and the numbers made, for the last are not its
      target = '';
      mbom.forget();
    }
    loadedKey = entry.key;
    loadedStamp = entry.stamp || '';
    jobs.setStamp(loadedStamp);   // a publish names what the design was read under, and is refused if the hub or settings are no longer those
    loaded.summary = true;
    renderSummary(entry.data);
    ensureSections(SECTIONS);
    mbom.loading();
    bom.showChecking();   // the Bill of Materials area is not blank while the MBOM lookup is on its way
  }

  /** The design's own properties, compared with Fusion Manage. */
  function answerProperties(entry) {
    const failure = entry.ok ? '' : entry.message || t('publish.unknown_error');
    if (entry.ok) details.setRoot(entry.data.compare);
    else details.setRootError(failure);
  }

  /** The whole Bill of Materials, compared with Fusion Manage. */
  function answerStructure(entry) {
    if (!entry.ok) {
      bom.showError(entry.message, function () { loaded.structure = false; viewer.show(true); loadSection('structure'); });
      return;
    }
    bom.showStructure(entry.data);
    viewer.structureRead();   // the viewer builds the structure once the MBOM is in too (it was asked for at the same time)
    if (!loaded.properties && !inflight.properties) loadSection('properties');   // quietly, after the BOM
  }

  /** Read what the structure is built from, all at once: the design's Bill of Materials and, when Fusion Manage holds the MBOM item, its tree. The viewer
   *  keeps its skeleton until both are in. */
  function loadStructure() {
    viewer.show(true);   // the skeleton of the two tables, until the structure is built
    ensureSections(AFTER_MBOM);
    if (mbom.idOf(target)) askMbomTree();
  }

  /** Another MBOM was chosen: its item number is what the Bill of Materials is compared for. Python keeps what it read of the design from the Data Model, so
   *  only what depends on the target is read again. */
  function chooseTarget(number) {
    target = number;
    restartBom(false);
    loadStructure();
  }

  /** The manufacturing bills of materials of the design. Fusion Manage is not searched for anything else until this has answered; when it
   *  failed, the panel says why and waits for a retry. */
  function answerMbom(entry) {
    if (entry.ok) {
      const chosen = mbom.show(entry.data, target);
      if (chosen === null) {   // several, and none was chosen before: the Bill of Materials waits for the user to say which
        target = '';
        mbom.offer(bom.clear());
        viewer.showTable();   // the choice is drawn where the table is: the structure view would wait for it for ever
        return;
      }
      target = chosen;
      loadStructure();
      return;
    }
    const failure = entry.message || t('publish.unknown_error');
    mbom.reset();
    bom.showError(failure, function () { loaded.mbom = false; bom.showChecking(); loadSection('mbom'); });
  }

  function handleSection(r) {
    if (!r.ok) return;
    const entry = r.result;
    const name = entry.section;
    if (askedIn[name] !== undefined && askedIn[name] !== generation) return;   // asked before the last reload: it is not wanted
    clearTimeout(timers[name]);
    if (entry.pending) { waitFor(name, entry); return; }
    if ((name === 'structure' || name === 'mbom_tree') && entry.target_id !== mbom.idOf(target)) return;   // read for an MBOM that is no longer the one chosen
    inflight[name] = false;
    if (name.indexOf('component:') === 0) { details.handleComponent(name.slice('component:'.length), entry); return; }
    if (name === 'summary') { answerSummary(entry); return; }
    if (name.indexOf('thumbnail:') === 0) { details.handleThumbnail(name.slice('thumbnail:'.length), entry); return; }
    if (name === 'mbom_tree') { viewer.answer(entry); return; }   // the MBOM of the target, for the structure viewer
    loaded[name] = true;
    if (name === 'mbom') { answerMbom(entry); return; }
    if (name === 'mbom_number') { mbom.answer(entry); return; }
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

  /** Read the Bill of Materials and its check again; answers still on their way for the old contents are ignored. The thumbnail and the MBOM lookup are left as they are. */
  function restartBom(force) {
    generation++;
    bom.reset();
    Object.keys(timers).forEach(function (slot) { if (SECTIONS.indexOf(slot) < 0) clearTimeout(timers[slot]); });
    BOM_SECTIONS.forEach(function (name) {
      loaded[name] = false;
      inflight[name] = false;
      forceNext[name] = forceNext[name] || !!force;   // a forced refresh whose read waits for the user to choose an MBOM keeps its force
    });
    bom.clear();
    viewer.reset();
    details.reset(force);
  }

  /** Read the open design again (all sections), skipping the cached copies when ``force``. ``now`` ignores the pause that merges triggers. */
  function refresh(force, now) {
    // Focus, sign-in and the button can all fire together; load once.
    if (!now && Date.now() - lastLoad < 2000) return;
    lastLoad = Date.now();
    SECTIONS.forEach(function (name) {
      clearTimeout(timers[name]);
      loaded[name] = false;
      inflight[name] = false;
      forceNext[name] = !!force;
    });
    restartBom(force);
    mbom.reset();
    loaded.summary = false;
    forceNext.summary = !!force;
    showLoading(true);
    loadSection('summary');
  }

  // ---- Start ---------------------------------------------------------------------

  function init() {
    mbom.init({
      itemNumber: function () { return (currentSummary || {}).item_number || ''; },   // the design's own, whatever MBOM is chosen
      // A new number: no item holds it yet, so there is no id.
      check: function (number) { request('mbom_number', { section: 'mbom_number', target: number, target_id: '' }); },
      choose: chooseTarget,
    });
    bom.init({ summary: summary, plan: viewer.plan, say: viewer.say, showNotice: viewer.showTable });
    viewer.init({
      design: function () { return currentSummary || {}; },   // the design's own item number, not the target's
      summary: summary,   // with the target's, for what publishing sends
      planned: bom.refreshScope,
      rows: bom.rows,
      askMbom: askMbomTree,
      targetId: function () { return mbom.idOf(target); },   // empty for a design with no MBOM item: the viewer starts from the EBOM
      target: function () { return target; },
      boughtSuffix: function () { return (currentSummary || {}).bought_suffix || ''; },   // the suffix of bought versions: a line with an EBOM line's number and it is that line's bought version
      boughtReady: function () { return !!(currentSummary || {}).make_buy; },   // Make or buy is set up in Settings
      phantom: function () { return false; },   // Settings do not name the Type field and its Phantom value yet
    });
    details.init({
      request: request,
      // The design's row was opened: read its own properties the first time.
      onRootLoad: function () {
        if (loaded.structure && !loaded.properties && !inflight.properties) loadSection('properties');   // the Bill of Materials is in, so the lookup has answered
      },
      onRootRetry: function () {
        loaded.properties = false;
        loadSection('properties');
      },
    });
    jobs.init({ onFinished: function () { refresh(true, true); } });   // Fusion Manage changed: read the whole panel again, not the cached copies
    bridge.on('load_publish_section', handleSection);
    bridge.on('load_publish_section_status', handleSection);
    $('pub-refresh').addEventListener('click', function () { refresh(true, true); });   // a click is always wanted: not merged with another trigger
    // The palette stays open while the user switches designs. Clicking into it also fires focus,
    // so reload only when a different design is open; the same design is read again only by the refresh button.
    bridge.on('get_publish_model_key', function (r) {
      if (r.ok && (r.result.key !== loadedKey || (r.result.stamp || '') !== loadedStamp)) refresh(false);   // another design, or other settings (another hub, tenant or workspace)
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
    if (!ns.i18n.gate(start)) return;   // the language is in before the page is built
    ns.shell.mountHeader();
    ns.account.init();
    ns.auth.init();
    init();
    ns.auth.refresh();
  }

  start();
})(window.MfgUi);
