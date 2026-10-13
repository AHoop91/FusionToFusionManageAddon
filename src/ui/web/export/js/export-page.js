/**
 * The Export window: asks Python what the open document can be exported as and where the file can go (``export_context``), shows it,
 * and sends the choice back (``export_run``). The window stays open and follows the export (``upload_status``), then says how it went.
 *
 * Which destinations the user may attach to is read from Fusion Manage when the window opens and arrives later (``export_access``):
 * until then a destination shows a skeleton where its description will be.
 */
(function (ns) {
  'use strict';

  const bridge = ns.bridge;
  const $ = ns.$;
  const el = ns.el;

  const CONTEXT_POLL_MS = 2000;   // how often to ask again while there is nothing to export yet
  const UPLOAD_POLL_MS = 250;     // how often to ask how far the export has got
  const START_WAIT_MS = 30000;    // how long an export may go without saying how far it is, before it is called failed
  const ACCESS_WAIT_MS = 20000;   // how long to wait for the permission check before saying it could not be done

  let context = null;      // what Python said is on offer
  let format = '';         // the key of the format chosen
  let destination = '';    // the key of the destination chosen
  let access = null;       // why each destination may not be attached to, once the permission check has answered
  let accessTimer = 0;
  let progressCard = null; // the progress card, once mounted
  let startedAt = 0;       // when the export was asked for
  let phase = 'form';      // 'form' (choosing), 'working' (the export is under way) or 'result' (how it went)

  // ---- Choices --------------------------------------------------------------------------

  /** Mark ``chosen`` as the one picked among its siblings that match ``selector``. */
  function mark(chosen, selector) {
    chosen.parentNode.querySelectorAll(selector).forEach(function (other) { other.classList.remove('is-checked'); });
    chosen.classList.add('is-checked');
  }

  /** A radio button (for the keyboard) in a joined button, for the format. */
  function segment(f, checked, onPick) {
    const part = el('label', 'export-segment' + (checked ? ' is-checked' : ''));
    const input = el('input');
    input.type = 'radio';
    input.name = 'export-format';
    input.checked = checked;
    input.addEventListener('change', function () { mark(part, '.export-segment'); onPick(f.key); });
    part.appendChild(input);
    part.appendChild(el('span', '', f.label));
    return part;
  }

  /** A card for a destination: its name, and under it what it is, why it is off, or a skeleton while that is being read. */
  function card(d, checked, onPick) {
    const off = !!d.reason || d.checking;
    const wrap = el('label', 'export-card' + (off ? ' is-off' : '') + (checked ? ' is-checked' : ''));
    const input = el('input');
    input.type = 'radio';
    input.name = 'export-destination';
    input.checked = checked;
    input.disabled = off;
    input.addEventListener('change', function () { mark(wrap, '.export-card'); onPick(d.key); });
    wrap.appendChild(input);
    wrap.appendChild(el('span', 'export-card-title', d.label));
    if (d.checking) {
      const bar = el('span', 'export-skeleton');
      bar.setAttribute('role', 'status');
      bar.setAttribute('aria-label', 'Checking permissions');
      wrap.appendChild(bar);
    } else {
      wrap.appendChild(el('span', 'export-card-text', d.reason || d.note));
    }
    return wrap;
  }

  /** The footer says what Export will do with the choices made. */
  function showStatus() {
    const found = context.formats.filter(function (f) { return f.key === format; })[0];
    const where = context.destinations.filter(function (d) { return d.key === destination; })[0];
    $('export-status').textContent = !found ? '' : where ? 'Uploading ' + found.label + ' file to ' + where.label : 'Choose where to attach the file';
  }

  function syncRun() {
    $('export-run').disabled = !(format && destination && !context.problem);
  }

  function renderFormats() {
    const box = $('export-formats');
    box.replaceChildren();
    context.formats.forEach(function (f) {
      box.appendChild(segment(f, f.key === format, function (key) { format = key; showStatus(); }));
    });
    $('export-format-group').hidden = !context.formats.length;
  }

  function renderDestinations() {
    const box = $('export-destinations');
    box.replaceChildren();
    context.destinations.forEach(function (d) {
      box.appendChild(card(d, d.key === destination, function (key) { destination = key; showStatus(); syncRun(); }));
    });
  }

  /** The choices: what is exported, any problem with it, the formats and destinations, and what pressing Export will do. */
  function renderForm() {
    if (access) applyAccess();
    const waiting = context.destinations.some(function (d) { return d.checking; });
    if (waiting && !accessTimer) accessTimer = setTimeout(accessTimedOut, ACCESS_WAIT_MS);
    $('export-target').textContent = context.target;
    $('export-description').textContent = context.description;   // when Fusion has one for the design
    const problem = $('export-problem');
    problem.textContent = context.problem;
    problem.hidden = !context.problem;
    renderFormats();
    renderDestinations();
    showStatus();
    syncRun();
  }

  /** Take in what Python said is on offer. While there is nothing to export yet (a drawing still loading) it asks again. */
  function load(result) {
    context = result;
    format = context.formats.length ? context.formats[0].key : '';
    destination = context.destination;
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
    if (!chosen) {
      const usable = context.destinations.filter(function (d) { return !d.reason; })[0];
      destination = usable ? usable.key : '';
    }
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

  function pollUpload() { bridge.send('upload_status'); }

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
    setTimeout(pollUpload, UPLOAD_POLL_MS);
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
    bridge.on('export_access', function (r) {
      if (!r.ok) return;
      access = r.result.reasons;
      if (context) renderForm();   // else it is taken in when the context arrives
    });
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
