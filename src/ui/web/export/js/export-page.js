/**
 * The Export window: asks Python what the open document can be exported as and where the file can go (``export_context``), shows it,
 * and sends the choice back (``export_run``). The window stays open and follows the export (``upload_status``), then says how it went.
 *
 * Which destinations the user may attach to is read from Fusion Manage when the window opens and arrives later (``export_access``):
 * until then a grey bar stands where the reason a destination is off would be. The file the export affects is read when the format or
 * destination is chosen (``export_files``, answered by ``export_files_found``) and shown on a card: new, or already attached and whether it
 * is up to date.
 */
(function (ns) {
  'use strict';

  const bridge = ns.bridge;
  const $ = ns.$;
  const el = ns.el;

  const CONTEXT_POLL_MS = 2000;   // how often to ask again while there is nothing to export yet
  const UPLOAD_POLL_MS = 2000;    // Python pushes every change of how far the export has got; this only asks now and then, in case a push is missed
  const START_WAIT_MS = 30000;    // how long an export may go without saying how far it is, before it is called failed
  const ACCESS_WAIT_MS = 20000;   // how long to wait for the permission check before saying it could not be done
  const FILES_ASK_DELAY_MS = 120; // how long a choice stays still before the attached files are asked for
  const FILES_WAIT_MS = 30000;    // how long to wait for the attached files before saying they could not be read

  let context = null;      // what Python said is on offer
  let itemNumber = null;    // the item number of what is exported: null until it has been read, then it (empty when there is none)
  let format = '';         // the key of the format chosen
  let destination = '';    // the key of the destination chosen
  let access = null;       // why each destination may not be attached to, once the permission check has answered
  let accessTimer = 0;
  let files = null;        // what is attached where the export would go: {state: 'loading'}, or Python's answer; null when nothing is asked
  let filesKey = '';       // which choices `files` was asked for, so the same ones are not asked again
  let filesTimer = 0;
  let askTimer = 0;        // the pause before the files are asked for, so the choice is drawn first and quick changes ask once
  let progressCard = null; // the progress card, once mounted
  let startedAt = 0;       // when the export was asked for
  let phase = 'form';      // 'form' (choosing), 'working' (the export is under way) or 'result' (how it went)

  // ---- Choices --------------------------------------------------------------------------

  /** Mark ``chosen`` as the one picked among its siblings that match ``selector``. */
  function mark(chosen, selector) {
    chosen.parentNode.querySelectorAll(selector).forEach(function (other) { other.classList.remove('is-checked'); });
    chosen.classList.add('is-checked');
  }

  /** A radio button (for the keyboard) in a joined button: a format, or a destination (turned off when ``off``). */
  function segment(item, name, checked, off, onPick) {
    const part = el('label', 'export-segment' + (checked ? ' is-checked' : '') + (off ? ' is-off' : ''));
    const input = el('input');
    input.type = 'radio';
    input.name = name;
    input.checked = checked;
    input.disabled = off;
    input.addEventListener('change', function () { mark(part, '.export-segment'); onPick(item.key); });
    part.appendChild(input);
    part.appendChild(el('span', '', item.label));
    return part;
  }

  function syncRun() {
    $('export-run').disabled = !(format && destination && !context.problem);
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
      box.appendChild(segment(f, 'export-format', f.key === format, false, function (key) {
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
    context.destinations.filter(function (d) { return d.reason; }).forEach(function (d) {
      box.appendChild(el('span', 'export-note is-off', d.label + ': ' + d.reason));
    });
    if (context.destinations.some(function (d) { return d.checking; })) box.appendChild(skeleton('Checking permissions'));
  }

  /** What shows in the pill at the top: the destination chosen, or why there is none. */
  function summarizeDestination() {
    const chosen = context.destinations.filter(function (d) { return d.key === destination; })[0];
    const waiting = context.destinations.some(function (d) { return d.checking; });
    const pill = $('export-destination-summary');
    pill.textContent = chosen ? chosen.label : waiting ? 'Checking...' : 'None available';
    pill.dataset.kind = chosen ? chosen.key : '';
  }

  function renderDestinations() {
    const box = $('export-destinations');
    box.replaceChildren();
    context.destinations.forEach(function (d) {
      box.appendChild(segment(d, 'export-destination', d.key === destination, !!d.reason || d.checking, function (key) {
        destination = key;
        summarizeDestination();
        renderDestinationNote();
        syncRun();
        loadFiles();
      }));
    });
    summarizeDestination();
    renderDestinationNote();
  }

  // ---- The files attached where the export would go -------------------------------------

  /** A date as the user's computer writes it; the text as it came when it is not one. */
  function shortDate(stamp) {
    const when = new Date(stamp);
    return isNaN(when) ? stamp : when.toLocaleDateString();
  }

  /** A file size in the unit that reads best. */
  function fileSize(bytes) {
    if (bytes >= 1048576) return (bytes / 1048576).toFixed(1) + ' MB';
    return Math.max(1, Math.round(bytes / 1024)) + ' KB';
  }

  /** Bouncing balls and a line of text, while the attached files are read. */
  function loading() {
    const box = el('div', 'export-files-loading');
    const balls = el('div', 'balls');
    balls.setAttribute('role', 'status');
    balls.setAttribute('aria-label', 'Reading the attached files');
    for (let i = 0; i < 3; i++) balls.appendChild(el('span'));
    box.appendChild(balls);
    box.appendChild(el('span', 'export-note', 'Checking what is attached...'));
    return box;
  }

  /** A line of the card: what it is about, and the fact. */
  function detail(label, value) {
    const row = el('div', 'export-file-row');
    row.appendChild(el('dt', '', label));
    row.appendChild(el('dd', '', value));
    return row;
  }

  const FILE_STATES = {   // how the card names each state of the attached file
    new: 'New file',
    current: 'Up to date',
    stale: 'Out of date',
    unsaved: 'Unsaved changes',
    unknown: 'Not known',
  };

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
      box.appendChild(el('p', 'export-note is-off', files.message || 'The attached files could not be read.'));
      return;
    }
    const old = files.existing;
    const state = old ? (old.freshness || {}).state || 'unknown' : 'new';
    const card = el('div', 'export-file is-' + state);
    const head = el('div', 'export-file-head');
    head.appendChild(el('span', 'export-file-name', files.name));
    head.appendChild(el('span', 'export-file-badge', FILE_STATES[state]));
    card.appendChild(head);
    if (old) {
      const rows = el('dl', 'export-file-rows');
      if (old.freshness && old.freshness.modified) rows.appendChild(detail('Component Last Modified', shortDate(old.freshness.modified)));
      rows.appendChild(detail('Version', old.version || 'Unknown'));
      if (old.size) rows.appendChild(detail('Size', fileSize(old.size)));
      rows.appendChild(detail('Last changed', old.updated ? shortDate(old.updated) : 'Unknown'));
      if (old.user) rows.appendChild(detail('Changed by', old.user));
      card.appendChild(rows);
    }
    box.appendChild(card);
  }

  /** Ask what is attached for the format and destination chosen, unless that was asked already or there is nothing to ask about. */
  function loadFiles() {
    const key = [format, destination, context.target].join('|');
    if (!format || !destination || context.problem) {
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
      files = { state: 'unavailable', message: 'Fusion Manage did not answer, so the attached files could not be read.' };
      renderFiles();
    }, FILES_WAIT_MS);
    clearTimeout(askTimer);
    askTimer = setTimeout(function () {   // the call into Fusion holds the page until it returns, so it waits for the choice to be drawn
      bridge.send('export_files', { format: format, destination: destination, target: context.target });
    }, FILES_ASK_DELAY_MS);
  }

  /** An answer about the files: kept when it is for the choices now made, dropped when it is for an earlier choice. */
  function filesFound(r) {
    if (!r.ok || !files || r.result.format !== format || r.result.destination !== destination) return;
    clearTimeout(filesTimer);
    files = r.result;
    renderFiles();
  }

  /** The title: the item number once it is known; a grey bar until then (empty when there is none). */
  function paintTarget() {
    const title = $('export-target');
    title.replaceChildren();
    if (!context.target) return;   // nothing to export yet
    if (itemNumber === null) title.appendChild(skeleton('Reading the item number'));
    else title.textContent = itemNumber;
  }

  /** The choices: what is exported, any problem with it, the formats and destinations, and what pressing Export will do. */
  function renderForm() {
    if (access) applyAccess();
    const waiting = context.destinations.some(function (d) { return d.checking; });
    if (waiting && !accessTimer) accessTimer = setTimeout(accessTimedOut, ACCESS_WAIT_MS);
    paintTarget();
    $('export-description').textContent = context.description;   // when Fusion has one for the design
    const problem = $('export-problem');
    problem.textContent = context.problem;
    problem.hidden = !context.problem;
    renderFormats();
    renderDestinations();
    syncRun();
    loadFiles();
  }

  /** Take in what Python said is on offer. While there is nothing to export yet (a drawing still loading) it asks again. */
  function load(result) {
    context = result;
    format = context.formats.length ? context.formats[0].key : '';
    destination = preferred();
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
      access[d.key] = d.reason || 'Permissions could not be checked: Fusion Manage did not answer.';
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
    progressCard.show({ active: true, stage: 'Starting', step: -1, steps: [], percent: null });
    startedAt = Date.now();
    pollUpload();
  }

  function showResult(ok, message) {
    setPhase('result');
    $('export-result').classList.toggle('is-failed', !ok);
    $('export-result-title').textContent = ok ? 'Export complete' : 'Export failed';
    $('export-result-message').textContent = message;
    $('export-done').textContent = ok ? 'Done' : 'Close';
    $('export-done').classList.toggle('btn-secondary', !ok);
    $('export-retry').hidden = ok;   // a failure can be tried again
  }

  function followUpload(r) {
    if (phase !== 'working') return;
    if (!r.ok) { showResult(false, r.error); return; }
    const state = r.result;
    if (state.active) progressCard.show(state);
    else if (state.result) { showResult(state.result.ok, state.result.message); return; }
    else if (Date.now() - startedAt > START_WAIT_MS) { showResult(false, 'The export did not start.'); return; }
    clearTimeout(uploadTimer);
    uploadTimer = setTimeout(pollUpload, UPLOAD_POLL_MS);
  }

  function run() {
    showError('');
    $('export-run').disabled = true;
    bridge.send('export_run', { format: format, destination: destination, target: context.target });
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
    ns.shell.mountHeader();
    ns.account.init();
    ns.auth.init();
    progressCard = ns.uploadProgress.mount($('export-progress'));

    bridge.on('export_context', function (r) { if (r.ok) load(r.result); else showError(r.error); });
    bridge.on('export_item', function (r) {
      if (!r.ok) return;
      itemNumber = r.result.item_number;
      if (context && context.target === r.result.target) paintTarget();   // else it is shown when the context arrives
    });
    bridge.on('export_access', function (r) {
      if (!r.ok) return;
      access = r.result.reasons;
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

    ns.auth.onChange(signInKnown);
    ns.auth.refresh();
  })();
})(window.MfgUi);
