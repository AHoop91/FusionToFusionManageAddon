/**
 * The publish jobs, as ``ns.pubJobs``, used by two pages. In the Publish Item panel, Publish adds a job
 * to the queue in Python (which asks for the folder) and returns at once; the panel then shows a progress
 * dialog that follows the job until it ends. The dialog can be closed at any time: the job keeps running
 * in the background. The queue itself is shown in the Job Queue window (web/jobs), opened from the ribbon: its list
 * has each job's progress, time, folder and failures. The jobs run in the background either way.
 */
(function (ns) {
  'use strict';

  const $ = ns.$;
  const bridge = ns.bridge;
  const ui = ns.pubUi;

  const ACTIONS = ['start_publish', 'list_publish_jobs', 'cancel_publish', 'clear_publish_jobs'];
  const POLL_MS = 1000;
  const FINISHED = ['done', 'error', 'cancelled'];

  let jobs = [];
  let timer = null;
  let confirming = false;   // the dialog asks whether to cancel the publish
  let watched = '';   // id of the job the progress dialog follows ("" = no dialog)

  function listOpen() { return !!$('pub-jobs-list'); }   // only the Jobs window has the list

  // Status icons (24x24 strokes): a grey clock (waiting), a blue clock (running), a green tick, a red cross.
  const ICONS = {
    queued:    { title: 'Queued', paths: ['M12 3a9 9 0 1 0 0 18a9 9 0 0 0 0-18z', 'M12 7v5l3 2'] },
    running:   { title: 'Running', paths: ['M12 3a9 9 0 1 0 0 18a9 9 0 0 0 0-18z', 'M12 7v5l3 2'] },
    done:      { title: 'Done', paths: ['M5 12.5l4.5 4.5L19 7.5'] },
    error:     { title: 'Failed', paths: ['M6 6l12 12', 'M18 6L6 18'] },
    cancelled: { title: 'Cancelled', paths: ['M6 6l12 12', 'M18 6L6 18'] },
  };

  function statusIcon(row) {
    const icon = ICONS[row.status] || ICONS.queued;
    const cell = ui.el('td', 'pub-job-status pub-job-' + row.status);
    cell.appendChild(ui.svg(icon.paths, 18));
    cell.title = icon.title + (row.detail ? ': ' + row.detail : '');
    return cell;
  }

  /** The items of a job that are still in the queue: waiting, running, failed or cancelled. Done ones leave it. */
  function visibleRows(job) {
    return (job.rows || []).filter(function (row) { return row.status !== 'done'; });
  }

  /** The items of a job, one row each: "Number - Title" and a status icon. */
  function itemRows(table, rows) {
    rows.forEach(function (row) {
      const tr = ui.el('tr');
      const name = ui.el('td', 'pub-job-item', row.description ? row.item + ' - ' + row.description : (row.item || '-'));
      name.title = name.textContent;
      if (row.status === 'error' && row.detail) name.appendChild(ui.el('div', 'pub-job-reason', row.detail));
      tr.appendChild(name);
      tr.appendChild(statusIcon(row));
      table.appendChild(tr);
    });
  }

  /** A line above the items of one publish (one assembly): its name, a note while it waits, and Cancel while it is active. */
  function jobHeading(table, job) {
    const tr = ui.el('tr', 'pub-job-group');
    const cell = ui.el('td');
    cell.colSpan = 2;
    const box = ui.el('div', 'pub-job-group-box');
    box.appendChild(ui.el('span', 'pub-job-name', 'Publish of ' + job.name));
    const note = job.phase === 'queued' ? 'Waiting' + (job.place ? ', number ' + job.place + ' in the queue' : '')
      : (job.phase === 'cancelled' ? 'Cancelled' : (job.phase === 'error' ? 'Failed' : ''));
    box.appendChild(ui.el('span', 'muted pub-job-count', note));
    if (FINISHED.indexOf(job.phase) < 0) {
      const cancel = ui.el('button', 'pub-drawing-open', 'Cancel');
      cancel.type = 'button';
      cancel.addEventListener('click', function () { bridge.send('cancel_publish', { id: job.id }); });
      box.appendChild(cancel);
    }
    cell.appendChild(box);
    tr.appendChild(cell);
    table.appendChild(tr);
  }

  /** The message in the top bar: what is running and waiting. */
  function queueMessage() {
    const running = jobs.filter(function (j) { return j.phase === 'running'; }).length;
    const waiting = jobs.filter(function (j) { return j.phase === 'queued'; }).length;
    const failed = jobs.reduce(function (n, j) { return n + (j.rows || []).filter(function (r) { return r.status === 'error'; }).length; }, 0);
    if (!running && !waiting) return failed ? 'Nothing is waiting. ' + failed + ' failed item' + (failed === 1 ? ' stays' : 's stay') + ' here until cleared.' : 'Nothing in the queue. Publish an item and it appears here.';
    return [running ? running + ' running' : '', waiting ? waiting + ' waiting' : ''].filter(Boolean).join(', ') + '. Publishing runs in the background.';
  }

  function renderList() {
    const box = $('pub-jobs-list');
    if (!box) return;
    $('pub-jobs-message').textContent = queueMessage();
    box.textContent = '';
    const table = ui.el('table', 'pub-job-rows');
    const head = ui.el('tr');
    ['Item', 'Status'].forEach(function (text) { head.appendChild(ui.el('th', '', text)); });
    table.appendChild(head);
    let shown = 0;
    jobs.slice().reverse().forEach(function (job) {   // newest first
      const rows = visibleRows(job);
      if (!rows.length && FINISHED.indexOf(job.phase) >= 0) return;   // everything in it is done
      jobHeading(table, job);
      itemRows(table, rows);
      shown += 1;
    });
    if (shown) box.appendChild(table);
    $('pub-jobs-clear').disabled = !jobs.some(function (j) { return FINISHED.indexOf(j.phase) >= 0; });
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(function () { bridge.send('list_publish_jobs'); }, POLL_MS);
  }

  // ---- Progress dialog (Publish panel) -----------------------------------------

  function isFinished(job) { return FINISHED.indexOf(job.phase) >= 0; }

  function failedRows(job) { return (job.rows || []).filter(function (r) { return r.status === 'error'; }).length; }

  /** What the dialog says for a job: title, status line, count line, bar (percent or null while waiting) and tone. */
  function describe(job) {
    const total = job.total || 0;
    const count = total ? job.done + ' of ' + total + ' Items Processed' : '';
    if (job.phase === 'queued') {
      return { title: 'Added to the publishing queue', status: job.place > 1 ? 'Waiting, number ' + job.place + ' in the queue.' : 'Waiting to start.', count: count, percent: null, tone: '' };
    }
    if (job.phase === 'running') {
      return { title: 'Publishing ' + job.name, status: job.current ? 'Processing ' + job.current + '.' : 'Starting.', count: count, percent: total ? Math.round(job.done * 100 / total) : null, tone: '' };
    }
    if (job.phase === 'error') return { title: 'Publish failed', status: job.message || 'The publish could not be completed.', count: '', percent: 100, tone: 'error' };
    if (job.phase === 'cancelled') return { title: 'Publish cancelled', status: job.name + ' was not published.', count: count, percent: total ? Math.round(job.done * 100 / total) : 0, tone: 'error' };
    const failed = failedRows(job);
    return failed
      ? { title: 'Completed with errors', status: failed + ' of ' + total + ' item' + (total === 1 ? '' : 's') + ' failed. See the Job Queue for the reasons.', count: count, percent: 100, tone: 'error' }
      : { title: 'Publish complete', status: job.name + ' is ready. The requests were written for review; nothing has been sent to Fusion Manage yet.', count: count, percent: 100, tone: 'ok' };
  }

  function showProgress(view, job) {
    const box = $('pub-progress');
    const bar = $('pub-progress-bar');
    const active = !!job && !isFinished(job);
    box.firstElementChild.classList.remove('pub-progress-ok', 'pub-progress-error');
    if (view.tone) box.firstElementChild.classList.add('pub-progress-' + view.tone);
    $('pub-progress-title').textContent = view.title;
    $('pub-progress-status').textContent = view.status;
    $('pub-progress-count').textContent = view.count || '';
    bar.classList.toggle('indeterminate', view.percent === null);
    if (view.percent === null) bar.removeAttribute('aria-valuenow'); else bar.setAttribute('aria-valuenow', String(view.percent));
    $('pub-progress-fill').style.width = view.percent === null ? '' : view.percent + '%';
    $('pub-progress-note').textContent = active
      ? 'You can close this window. Publishing continues in the background and you can follow it in Job Queue on the Fusion Manage tab.'
      : (job ? 'Details are in Job Queue on the Fusion Manage tab.' : '');
    if (!active) confirming = false;
    $('pub-progress-confirm').hidden = !confirming;
    $('pub-progress-actions').hidden = confirming;
    $('pub-progress-cancel').hidden = !active;
    box.hidden = false;
    if (!confirming) $('pub-progress-close').focus();
  }

  function closeProgress() {
    watched = '';
    confirming = false;
    clearTimeout(timer);
    $('pub-progress').hidden = true;
  }

  /** Show or hide the "cancel this publish?" question; the job keeps running until it is answered yes. */
  function askCancel(on) {
    confirming = on;
    $('pub-progress-confirm').hidden = !on;
    $('pub-progress-actions').hidden = on;
    $(on ? 'pub-progress-keep' : 'pub-progress-close').focus();
  }

  function watchedJob() {
    return jobs.filter(function (j) { return j.id === watched; })[0] || null;
  }

  /** Redraw the dialog from the latest list; true while its job is still active. */
  function updateProgress() {
    const job = watchedJob();
    if (!job) { closeProgress(); return false; }
    showProgress(describe(job), job);
    return !isFinished(job);
  }

  function handle(r) {
    if (r.ok && r.result.jobs) jobs = r.result.jobs;
    const list = listOpen();
    if (list && r.ok) renderList();
    const following = watched && r.ok ? updateProgress() : !!watched;   // keep polling through a failed read
    if (list || following) schedule();
  }

  function handleStart(r) {
    const s = r.ok ? r.result : { error: r.error || 'Could not publish.' };
    if (s.error) {
      watched = '';
      showProgress({ title: 'Could not publish', status: s.error, count: '', percent: 100, tone: 'error' }, null);
      return;
    }
    if (s.cancelled) return;   // the folder dialog was cancelled
    jobs = s.jobs || [];
    watched = s.queued;
    if (updateProgress()) schedule();
  }

  /** Queue a publish of ``payload`` (summary, items, operations); Python asks for the folder first. */
  function start(payload) {
    bridge.send('start_publish', payload);
  }

  function init() {
    ACTIONS.forEach(function (name) { bridge.on(name, name === 'start_publish' ? handleStart : handle); });
    bridge.on('open_publish_folder', function () {});
    if ($('pub-progress')) {
      $('pub-progress-close').addEventListener('click', closeProgress);
      $('pub-progress-cancel').addEventListener('click', function () { askCancel(true); });
      $('pub-progress-keep').addEventListener('click', function () { askCancel(false); });
      $('pub-progress-stop').addEventListener('click', function () {
        bridge.send('cancel_publish', { id: watched });
        askCancel(false);
      });
      document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape' || $('pub-progress').hidden) return;
        if (confirming) askCancel(false); else closeProgress();
      });
    }
    if (listOpen()) {
      $('pub-jobs-clear').addEventListener('click', function () { bridge.send('clear_publish_jobs'); });
      bridge.send('list_publish_jobs');
    }
  }

  ns.pubJobs = { init: init, start: start };
})(window.MfgUi);
