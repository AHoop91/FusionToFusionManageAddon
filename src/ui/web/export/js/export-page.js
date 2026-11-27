/**
 * The Export window: asks Python what the open document can be exported as and where the file can go (``export_context``), shows it,
 * and sends the choice back (``export_run``). The window stays open and follows the export (``upload_status``), then says how it went.
 *
 * Which destinations the user may attach to is read from Fusion Manage when the window opens and arrives later (``export_access``):
 * until then a grey bar stands where the reason a destination is off would be. The file the export affects is read when the format or
 * destination is chosen (``export_files``, answered by ``export_files_found``) and shown on a card: new, or already attached and whether it
 * is up to date.
 * Layer: UI, and the page controller (application) of this window.
 */
(function (ns) {
  'use strict';

  const bridge = ns.bridge;
  const $ = ns.$;
  const el = ns.el;
  const t = ns.i18n.t;

  const DENIED_ICON = ['M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z', 'M5.6 5.6l12.8 12.8'];   // a circle with a bar across it
  const CONTEXT_POLL_MS = 2000;   // how often to ask again while there is nothing to export yet
  const UPLOAD_POLL_MS = 2000;    // Python pushes every change of how far the export has got; this only asks now and then, in case a push is missed
  const START_WAIT_MS = 30000;    // how long an export may go without saying how far it is, before it is called failed
  const ACCESS_WAIT_MS = 20000;   // how long to wait for the permission check before saying it could not be done
  const FILES_ASK_DELAY_MS = 120; // how long a choice stays still before the attached files are asked for
  const FILES_WAIT_MS = 30000;    // how long to wait for the attached files before saying they could not be read

  let context = null;      // what Python said is on offer
  let thumbnail = null;     // the thumbnail of what is exported, once read: {target, url} (url empty when there is none); null until then
  let itemNumber = null;    // the item number of what is exported: null until it has been read, then it (empty when there is none)
  let format = '';         // the key of the format chosen
  let destination = '';    // the key of the destination chosen
  let denied = '';         // why every destination is off when Fusion Manage does not accept the app; "" when it does
  let access = null;       // why each destination may not be attached to, once the permission check has answered
  let accessTimer = 0;
  let files = null;        // what is attached where the export would go: {state: 'loading'}, or Python's answer; null when nothing is asked
  let filesKey = '';       // which choices `files` was asked for, so the same ones are not asked again
  let filesTimer = 0;
  let askTimer = 0;        // the pause before the files are asked for, so the choice is drawn first and quick changes ask once
  let progressCard = null; // the progress card, once mounted
  let startedAt = 0;       // when the export was asked for
  let itemsAnswer = null;  // Python's list of the items made from what is exported, until the context it is for has arrived
  let linkUrl = '';         // the page in Fusion Manage of the record the file goes to ("" when it is not known)
  let phase = 'form';      // 'form' (choosing), 'working' (the export is under way) or 'result' (how it went)

  // ---- Choices --------------------------------------------------------------------------

  /** Mark ``chosen`` as the one picked among its siblings that match ``selector``. */
  function mark(chosen, selector) {
    chosen.parentNode.querySelectorAll(selector).forEach(function (other) { other.classList.remove('is-checked'); });
    chosen.classList.add('is-checked');
  }

  /** A radio button (for the keyboard) in a joined button: a format, or a destination. ``look`` is ``{checked, off}``: ``off`` turns it off. */
  function segment(item, name, look, onPick) {
    const part = el('label', 'export-segment' + (look.checked ? ' is-checked' : '') + (look.off ? ' is-off' : ''));
    const input = el('input');
    input.type = 'radio';
    input.name = name;
    input.checked = look.checked;
    input.disabled = look.off;
    input.addEventListener('change', function () { mark(part, '.export-segment'); onPick(item.key); });
    part.appendChild(input);
    part.appendChild(el('span', '', item.label));
    return part;
  }

  /** The item number of what is exported once it is known, else the part number it is looked up by. */
  function numberText() {
    return itemNumber || context.target;
  }

  /** The id of the item the table picked, when the file is going to an item; "" otherwise (a component has no item to pick). */
  function chosenItem() {
    return destination === 'item' ? ns.exportItems.selected() : '';
  }

  /** The file goes to an item only once the table has one picked. */
  function syncRun() {
    $('export-run').disabled = !(format && destination && !context.problem && (destination !== 'item' || chosenItem()));
  }

  /** The pick in the table changed: what the button and the attached files say follows it. */
  function itemChanged() {
    if (!context) return;
    paintView();
    syncRun();
    loadFiles();
  }

  /** The items listed for what is exported are shown once the context they are for is here (the list may come first). */
  function applyItems() {
    if (!context || !itemsAnswer || itemsAnswer.target !== context.target) return;
    const answer = itemsAnswer;
    itemsAnswer = null;
    ns.exportItems.show(answer);
  }

  /** The destination the format chosen starts on (set in Preferences, on the Export tab) when it can be used, else the first that can. */
  function preferred() {
    const usable = context.destinations.filter(function (d) { return !d.reason && !d.checking; });
    const wanted = usable.filter(function (d) { return d.key === (context.defaults || {})[format]; })[0];
    return (wanted || usable[0] || { key: '' }).key;
  }

  function renderFormats() {
    const box = $('export-formats');
    box.replaceChildren();
    context.formats.forEach(function (f) {
      box.appendChild(segment(f, 'export-format', { checked: f.key === format, off: false }, function (key) {
        format = key;
        destination = preferred();
        renderDestinations();
        syncRun();
        loadFiles();
      }));
    });
    $('export-format-group').hidden = !context.formats.length;
  }

  /** A grey bar that shimmers where text is still to come. */
  function skeleton(label) {
    const bar = el('span', 'export-skeleton');
    bar.setAttribute('role', 'status');
    bar.setAttribute('aria-label', label);
    return bar;
  }

  /** Under the destinations: why any that is off is off, or a grey bar while the permissions are being read. */
  function renderDestinationNote() {
    const box = $('export-destination-note');
    box.replaceChildren();
    context.destinations.filter(function (d) { return d.reason && !d.hidden; }).forEach(function (d) {
      const note = el('span', 'export-note is-off');
      note.appendChild(el('strong', 'export-note-label', d.label));   // which destination it is about, then why it cannot be used
      note.appendChild(el('span', 'export-note-reason', d.reason));
      box.appendChild(note);
    });
    if (context.destinations.some(function (d) { return d.checking; })) box.appendChild(skeleton(t('export.checking_permissions')));
  }

  /** The record the file goes to, in the panel, with a link that opens it in Fusion Manage: the item picked, or the component. */
  function paintLinkRow() {
    let kind = '';
    let text = '';
    let url = '';
    if (destination === 'item') {
      const picked = ns.exportItems.current();
      kind = t('export.kind_item');
      text = picked ? picked.descriptor : ns.exportItems.note();
      url = picked ? picked.url : '';
    } else if (destination === 'component') {
      kind = t('export.kind_component');
      text = [numberText(), context.name].filter(Boolean).join(' - ');
      url = ns.exportItems.recordUrl();
    }
    $('export-link-row').hidden = !destination;
    $('export-link-kind').textContent = text && url ? kind : '';
    $('export-link-text').textContent = text;
    $('export-link-text').classList.toggle('is-off', !url && destination === 'item' && !ns.exportItems.current());
    linkUrl = url;
    $('export-link-open').hidden = !url;
  }

  /** What the window shows now: "finding" while the items are looked for, the table of items to choose from, or the options (the usual view). */
  function viewName() {
    if (!context) return 'finding';
    if (denied) return 'options';
    if (context.destinations.some(function (d) { return d.checking; })) return 'finding';   // the destination is not known yet: no view is chosen for it
    if (destination !== 'item') return 'options';
    const state = ns.exportItems.state();
    if (state === 'finding') return 'finding';
    return state === 'several' && !ns.exportItems.selected() ? 'choosing' : 'options';
  }

  function paintView() {
    if (!context) return;
    const view = viewName();
    document.querySelector('.export-body').classList.toggle('is-choosing', view === 'choosing');
    $('export-choose').hidden = view === 'options';
    $('export-choose').classList.toggle('is-finding', view === 'finding');   // only grey bars, until it is known whether there is a table to choose from
    $('export-panel').hidden = view !== 'options';
    $('export-change').hidden = !(view === 'options' && destination === 'item' && ns.exportItems.state() === 'several');
    $('export-choose-title').textContent = t('item.several_title', { number: numberText() });
    paintLinkRow();
  }

  /** A destination was chosen: what is shown, the button and the attached files follow it. */
  function destinationChosen(key) {
    destination = key;
    renderDestinationNote();
    paintView();
    syncRun();
    loadFiles();
  }

  function renderDestinations() {
    const box = $('export-destinations');
    box.replaceChildren();
    // A destination that is turned off is not offered. With only one left, and nothing to say about it, there is no choice to make: the whole group is hidden.
    const offered = context.destinations.filter(function (d) { return !d.hidden; });
    $('export-destination-group').hidden = offered.length < context.destinations.length && offered.every(function (d) { return !d.reason; });
    offered.forEach(function (d) {
      box.appendChild(segment(d, 'export-destination', { checked: d.key === destination, off: !!d.reason || d.checking }, destinationChosen));
    });
    renderDestinationNote();
    paintView();
  }

  // ---- The files attached where the export would go -------------------------------------

  /** A date as the user's computer writes it; the text as it came when it is not one. */
  function shortDate(stamp) {
    const when = new Date(stamp);
    return isNaN(when) ? stamp : when.toLocaleDateString();
  }

  /** A file size in the unit that reads best. */
  function fileSize(bytes) {
    if (bytes >= 1048576) return t('export.size_mb', { n: (bytes / 1048576).toFixed(1) });
    return t('export.size_kb', { n: Math.max(1, Math.round(bytes / 1024)) });
  }

  /** A grey bar of the card, ``size`` the class that gives it its width and height. */
  function bar(size) {
    return el('span', 'export-skeleton export-file-bar ' + size);
  }

  /** Grey bars in the shape of the card (the name and state, the four facts, the line about the export), while the attached files are read. */
  function loading() {
    const box = el('div', 'export-file export-file-loading');
    box.setAttribute('role', 'status');
    box.setAttribute('aria-label', t('export.reading_files'));
    const head = el('div', 'export-file-head');
    head.append(bar('is-name'), bar('is-badge'));
    const facts = el('div', 'export-stats');
    for (let i = 0; i < 4; i++) {
      const cell = el('div', 'export-stat');
      cell.append(bar('is-label'), bar('is-value'));
      facts.appendChild(cell);
    }
    box.append(head, facts, bar('is-effect'));
    return box;
  }

  /** How the card names a state of the attached file. */
  function stateName(state) {
    switch (state) {
      case 'new': return t('export.state_new');
      case 'current': return t('export.state_current');
      case 'stale': return t('export.state_stale');
      case 'unsaved': return t('export.state_unsaved');
      default: return t('export.state_unknown');
    }
  }

  /** The card for the file the export affects: its name and whether it is up to date, and what is attached now. */
  function renderFiles() {
    const box = $('export-files');
    box.replaceChildren();
    $('export-files-group').hidden = !files;
    if (!files) return;
    if (files.state === 'loading') {
      box.appendChild(loading());
      return;
    }
    if (files.state !== 'ok') {
      box.appendChild(el('p', 'export-note is-off', files.message || t('export.files_unreadable')));
      return;
    }
    box.appendChild(buildFileCard(files));
  }

  /** The state of the file already attached (``old``, or null when there is none: the export would add a new one). */
  function attachedState(old) {
    if (!old) return 'new';
    return (old.freshness || {}).state || 'unknown';
  }

  /** A fact about the file already attached: what it is about, and the fact. */
  function stat(label, value) {
    const cell = el('div', 'export-stat');
    cell.appendChild(el('dt', '', label));
    cell.appendChild(el('dd', '', value));
    return cell;
  }

  /** The facts about the file already attached, in a row: its version and size, and when and by whom it was changed. */
  function buildFileStats(old) {
    const row = el('dl', 'export-stats');
    row.appendChild(stat(t('export.row_version'), old.version || t('export.unknown')));
    if (old.size) row.appendChild(stat(t('export.row_size'), fileSize(old.size)));
    row.appendChild(stat(t('export.row_changed'), old.updated ? shortDate(old.updated) : t('export.unknown')));
    if (old.user) row.appendChild(stat(t('export.row_changed_by'), old.user));
    return row;
  }

  /** The status of the file the export affects: its name and whether it is up to date, what is attached now, and what the export will do. */
  function buildFileCard(found) {
    const old = found.existing;
    const state = attachedState(old);
    const card = el('div', 'export-file is-' + state);
    const head = el('div', 'export-file-head');
    head.appendChild(el('span', 'export-file-name', found.name));
    head.appendChild(el('span', 'export-file-badge', stateName(state)));
    card.appendChild(head);
    if (old) card.appendChild(buildFileStats(old));
    card.appendChild(el('p', 'export-file-effect', old ? t('export.effect_version') : t('export.effect_new')));
    return card;
  }

  /** Ask what is attached for the format and destination chosen, unless that was asked already or there is nothing to ask about. */
  function loadFiles() {
    const key = [format, destination, context.target, chosenItem()].join('|');
    if (!format || !destination || context.problem || (destination === 'item' && !chosenItem())) {
      files = null;
      filesKey = '';
      clearTimeout(filesTimer);
      clearTimeout(askTimer);
      renderFiles();
      return;
    }
    if (key === filesKey) return;
    filesKey = key;
    files = { state: 'loading' };
    renderFiles();
    clearTimeout(filesTimer);
    filesTimer = setTimeout(function () {
      if (!files || files.state !== 'loading') return;
      files = { state: 'unavailable', message: t('export.files_timeout') };
      renderFiles();
    }, FILES_WAIT_MS);
    clearTimeout(askTimer);
    askTimer = setTimeout(function () {   // the call into Fusion holds the page until it returns, so it waits for the choice to be drawn
      bridge.send('export_files', { format: format, destination: destination, target: context.target, item: chosenItem() });
    }, FILES_ASK_DELAY_MS);
  }

  /** An answer about the files: kept when it is for the choices now made, dropped when it is for an earlier choice. */
  function filesFound(r) {
    if (!r.ok || !files || r.result.format !== format || r.result.destination !== destination || r.result.item !== chosenItem()) return;
    clearTimeout(filesTimer);
    files = r.result;
    renderFiles();
  }

  /** The title: the item number once it is known; a grey bar until then (empty when there is none). */
  function paintTarget() {
    const title = $('export-target');
    title.replaceChildren();
    if (!context.target) return;   // nothing to export yet
    if (itemNumber === null) title.appendChild(skeleton(t('export.reading_item')));
    else title.textContent = itemNumber;
  }

  /** The thumbnail beside the title: a sweeping skeleton while it is read, the picture when it came, nothing when there is none. */
  function paintThumbnail() {
    const box = $('export-thumbnail');
    const url = thumbnail && thumbnail.target === context.target ? thumbnail.url : null;   // null: still being read
    box.hidden = !context.target || (url !== null && !/^https:\/\//i.test(url));
    box.classList.toggle('is-loading', url === null);
    box.style.backgroundImage = url ? 'url("' + url.replace(/"/g, '%22') + '")' : '';
  }

  /** When Fusion Manage does not let the user in, say so as the Item panel does, in place of the choices (the page's CSS hides them). */
  function paintDenied() {
    const box = $('export-denied');
    box.replaceChildren();
    document.querySelector('.export-body').classList.toggle('is-denied', !!denied);
    if (!denied) return;
    const icon = ns.svg(DENIED_ICON, 24);
    icon.classList.add('item-empty-icon');
    box.appendChild(icon);
    box.appendChild(el('p', 'item-empty-text', denied));
  }

  /** The choices: what is exported, any problem with it, the formats and destinations, and what pressing Export will do. */
  function renderForm() {
    if (access) applyAccess();
    const waiting = context.destinations.some(function (d) { return d.checking; });
    if (waiting && !accessTimer) accessTimer = setTimeout(accessTimedOut, ACCESS_WAIT_MS);
    paintTarget();
    paintThumbnail();
    $('export-name').textContent = context.name;   // the component's name in Fusion
    $('export-name').title = context.description || '';   // the design's description, when Fusion has one
    const problem = $('export-problem');
    problem.textContent = context.problem;
    problem.hidden = !context.problem;
    renderFormats();
    renderDestinations();
    paintDenied();
    syncRun();
    loadFiles();
  }

  /** Take in what Python said is on offer. While there is nothing to export yet (a drawing still loading) it asks again. */
  function load(result) {
    context = result;
    format = context.formats.length ? context.formats[0].key : '';
    destination = preferred();
    applyItems();
    renderForm();
    if (context.problem) setTimeout(function () { bridge.send('export_context'); }, CONTEXT_POLL_MS);
  }

  function showError(message) {
    const box = $('export-error');
    box.textContent = message || '';
    box.hidden = !message;
  }

  // ---- Permissions ----------------------------------------------------------------------

  /** Take in what the permission check found: turn off what the user may not attach to, and pick a destination that is left. */
  function applyAccess() {
    clearTimeout(accessTimer);
    context.destinations.forEach(function (d) { d.reason = access[d.key] || ''; d.checking = false; });
    const chosen = context.destinations.filter(function (d) { return d.key === destination && !d.reason; })[0];
    if (!chosen) destination = preferred();
  }

  /** The permission check has not answered in good time: say so on the destinations that were waiting, instead of shimmering on. */
  function accessTimedOut() {
    if (access || !context) return;
    access = {};
    context.destinations.forEach(function (d) {
      access[d.key] = d.reason || t('export.access_timeout');
    });
    renderForm();
  }

  // ---- The export -----------------------------------------------------------------------

  /** Show the choices alone, or over them the progress or the result of the export. */
  function setPhase(next) {
    phase = next;
    $('export-overlay').hidden = next === 'form';
    $('export-progress').hidden = next !== 'working';
    $('export-result').hidden = next !== 'result';
  }

  let uploadTimer = 0;

  function pollUpload() { clearTimeout(uploadTimer); bridge.send('upload_status'); }

  /** The export has been accepted: follow it on the progress card until Python says how it went. */
  function startWorking() {
    setPhase('working');
    progressCard.show({ active: true, stage: t('export.stage_starting'), step: -1, steps: [], percent: null });
    startedAt = Date.now();
    pollUpload();
  }

  function showResult(ok, message) {
    setPhase('result');
    $('export-result').classList.toggle('is-failed', !ok);
    $('export-result-title').textContent = ok ? t('export.complete') : t('export.failed');
    $('export-result-message').textContent = message;
    $('export-done').textContent = ok ? t('export.done') : t('export.close');
    $('export-done').classList.toggle('btn-secondary', !ok);
    $('export-retry').hidden = ok;   // a failure can be tried again
  }

  function followUpload(r) {
    if (phase !== 'working') return;
    if (!r.ok) { showResult(false, r.error); return; }
    const state = r.result;
    if (state.active) progressCard.show(state);
    else if (state.result) { showResult(state.result.ok, state.result.message); return; }
    else if (Date.now() - startedAt > START_WAIT_MS) { showResult(false, t('export.did_not_start')); return; }
    clearTimeout(uploadTimer);
    uploadTimer = setTimeout(pollUpload, UPLOAD_POLL_MS);
  }

  function run() {
    showError('');
    $('export-run').disabled = true;
    bridge.send('export_run', { format: format, destination: destination, target: context.target, item: chosenItem() });
  }

  /** Back to the choices after a failure, as they were left. */
  function retry() {
    showError('');
    setPhase('form');
    syncRun();
  }

  // ---- Start ----------------------------------------------------------------------------

  /** The sign-in state is known: the page is ready, or the sign-in screen is shown. */
  function signInKnown(signedIn) {
    $('export-ready').hidden = true;
    const placeholder = $('export-avatar-skeleton');   // the real avatar is in the bar now
    if (placeholder) placeholder.remove();
    if (signedIn && !context) bridge.send('export_context');
  }

  (function start() {
    // Fusion injects `adsk` asynchronously, so wait for it.
    if (typeof adsk === 'undefined') { setTimeout(start, 100); return; }
    if (!ns.i18n.gate(start)) return;   // the language is in before the page is built
    ns.shell.mountHeader();
    ns.account.init();
    ns.auth.init();
    progressCard = ns.uploadProgress.mount($('export-progress'));
    ns.exportItems.init({ changed: itemChanged });
    ns.exportItems.show(null);   // until Python has listed the items

    bridge.on('export_context', function (r) { if (r.ok) load(r.result); else showError(r.error); });
    bridge.on('export_item', function (r) {
      if (!r.ok) return;
      itemNumber = r.result.item_number;
      if (context && context.target === r.result.target) { paintTarget(); paintView(); }   // else it is shown when the context arrives
    });
    bridge.on('export_thumbnail', function (r) {
      if (!r.ok) return;
      thumbnail = r.result;
      if (context) paintThumbnail();   // else it is shown when the context arrives
    });
    bridge.on('export_items', function (r) {
      itemsAnswer = r.ok ? r.result : { target: context ? context.target : '', items: [], error: r.error };
      applyItems();
      if (context) renderForm();
    });
    bridge.on('export_access', function (r) {
      if (!r.ok) return;
      access = r.result.reasons;
      denied = r.result.denied || '';
      if (context) renderForm();   // else it is taken in when the context arrives
    });
    bridge.on('export_files', function (r) { if (!r.ok) { files = { state: 'unavailable', message: r.error }; renderFiles(); } });
    bridge.on('export_files_found', filesFound);
    bridge.on('export_run', function (r) {
      if (r.ok) startWorking(); else { showError(r.error); syncRun(); }
    });
    bridge.on('upload_status', followUpload);

    $('export-cancel').addEventListener('click', function () { bridge.send('export_close'); });
    $('export-done').addEventListener('click', function () { bridge.send('export_close'); });
    $('export-retry').addEventListener('click', retry);
    $('export-run').addEventListener('click', run);
    $('export-link-open').prepend(ns.svg(ns.EXTERNAL_ICON, 14));
    $('export-link-open').addEventListener('click', function () { if (linkUrl) bridge.send('open_url', { url: linkUrl }); });
    $('export-change').addEventListener('click', function () { ns.exportItems.reset(); });
    $('export-use-component').addEventListener('click', function () {
      destinationChosen('component');
      renderDestinations();   // the radio buttons follow the choice
    });

    ns.auth.onChange(signInKnown);
    ns.auth.refresh();
  })();
})(window.MfgUi);
