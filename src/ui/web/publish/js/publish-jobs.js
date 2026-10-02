/**
 * The publish jobs, as ``ns.pubJobs``, used by two pages. In the Publish Item panel, Publish adds a job
 * to the queue in Python (which asks for the folder) and returns at once; the panel says the job was
 * added. The queue itself is shown in the Job Queue window (web/jobs), opened from the ribbon: its list
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
  let noteTimer = null;

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

  /** The message above the footer of the Publish panel: the job was queued, or why it was not. */
  function note(text, isError) {
    const box = $('pub-queued');
    if (!box) return;
    $('pub-queued-text').textContent = text;
    box.classList.toggle('pub-queued-error', !!isError);
    box.hidden = !text;
    clearTimeout(noteTimer);
    if (text && !isError) noteTimer = setTimeout(function () { box.hidden = true; }, 20000);
  }

  function handle(r) {
    if (!listOpen()) return;
    if (r.ok && r.result.jobs) { jobs = r.result.jobs; renderList(); }
    schedule();
  }

  function handleStart(r) {
    const s = r.ok ? r.result : { error: r.error || 'Could not publish.' };
    if (s.error) { note(s.error, true); return; }
    if (s.cancelled) return;   // the folder dialog was cancelled
    const job = (s.jobs || []).filter(function (j) { return j.id === s.queued; })[0];
    const waiting = job && job.phase === 'queued' && job.place > 1 ? ' It is number ' + job.place + ' in the queue.' : '';
    note((job ? job.name : 'The item') + ' was added to the publishing queue. It publishes in the background and you can keep working.' + waiting
      + ' Follow it in Job Queue on the Fusion Manage tab.');
  }

  /** Queue a publish of ``payload`` (summary, items, operations); Python asks for the folder first. */
  function start(payload) {
    bridge.send('start_publish', payload);
  }

  function init() {
    ACTIONS.forEach(function (name) { bridge.on(name, name === 'start_publish' ? handleStart : handle); });
    bridge.on('open_publish_folder', function () {});
    if ($('pub-queued-close')) $('pub-queued-close').addEventListener('click', function () { note(''); });
    if (listOpen()) {
      $('pub-jobs-clear').addEventListener('click', function () { bridge.send('clear_publish_jobs'); });
      bridge.send('list_publish_jobs');
    }
  }

  ns.pubJobs = { init: init, start: start };
})(window.MfgUi);
