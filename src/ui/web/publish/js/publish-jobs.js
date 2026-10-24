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

  const ACTIONS = ['start_publish', 'list_publish_jobs', 'cancel_publish', 'clear_publish_jobs', 'retry_publish'];
  const POLL_MS = 1000;
  const FINISHED = ['done', 'error', 'cancelled'];

  let jobs = [];
  let onFinished = null;   // called with a watched job once it has ended
  let notified = '';       // id of the job onFinished was last called for
  let unseen = '';         // id of a running job whose dialog was closed: still followed, to call onFinished when it ends
  let timer = null;
  let confirming = false;   // the dialog asks whether to cancel the publish
  let watched = '';   // id of the job the progress dialog follows ("" = no dialog)

  function listOpen() { return !!$('pub-jobs-list'); }   // only the Jobs window has the list

  // Status icons (24x24 strokes): a grey clock (waiting), a blue clock (running), a red cross (failed or cancelled; a finished row is not listed).
  const ICONS = {
    queued:    { title: 'Queued', paths: ['M12 3a9 9 0 1 0 0 18a9 9 0 0 0 0-18z', 'M12 7v5l3 2'] },
    running:   { title: 'Running', paths: ['M12 3a9 9 0 1 0 0 18a9 9 0 0 0 0-18z', 'M12 7v5l3 2'] },
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

  /** What the whole job is doing, said once on its first row: waiting, cancelled or failed ("" while it runs or when it is done). */
  function jobNote(job) {
    if (job.phase === 'queued') return 'Waiting' + (job.place ? ', number ' + job.place + ' in the queue' : '');
    if (job.phase === 'cancelled') return 'Cancelled';
    return job.phase === 'error' ? 'Failed' : '';
  }

  /** The buttons of a job: Cancel while it is active, Retry once it failed (it sends the failed requests again; what was accepted is skipped). */
  function jobActions(job) {
    const cell = ui.el('td', 'pub-job-actions');
    if (FINISHED.indexOf(job.phase) < 0) {
      const cancel = ui.el('button', 'pub-outline-button', 'Cancel');
      cancel.type = 'button';
      cancel.addEventListener('click', function () { bridge.send('cancel_publish', { id: job.id }); });
      cell.appendChild(cancel);
    } else if (job.phase === 'error' || failedRows(job)) {
      const retry = ui.el('button', 'pub-outline-button', 'Retry');
      retry.type = 'button';
      retry.title = 'Send the failed requests to Fusion Manage again. What it already accepted is skipped.';
      retry.addEventListener('click', function () { retry.disabled = true; bridge.send('retry_publish', { id: job.id }); });
      cell.appendChild(retry);
    }
    return cell;
  }

  /** The items of a job, one row each: "Number - Title", a status icon and, on the first row, the job's note and buttons. */
  function itemRows(table, job, rows) {
    rows.forEach(function (row, index) {
      const tr = ui.el('tr', index === 0 ? 'pub-job-first' : '');
      const name = ui.el('td', 'pub-job-item', row.description ? row.item + ' - ' + row.description : (row.item || '-'));
      name.title = name.textContent;
      if (index === 0 && jobNote(job)) name.appendChild(ui.el('div', 'muted pub-job-note', jobNote(job)));
      if (row.status === 'error' && row.detail) name.appendChild(ui.el('div', 'pub-job-reason', row.detail));
      tr.appendChild(name);
      tr.appendChild(statusIcon(row));
      tr.appendChild(index === 0 ? jobActions(job) : ui.el('td'));
      table.appendChild(tr);
    });
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
    ['Item', 'Status', ''].forEach(function (text) { head.appendChild(ui.el('th', '', text)); });
    table.appendChild(head);
    let shown = 0;
    jobs.slice().reverse().forEach(function (job) {   // newest first
      const rows = visibleRows(job);
      if (!rows.length && FINISHED.indexOf(job.phase) >= 0) return;   // everything in it is done
      itemRows(table, job, rows.length ? rows : [{ item: job.name, description: '', status: job.phase }]);
      shown += 1;
    });
    if (shown) box.appendChild(table);
    $('pub-jobs-clear').disabled = !jobs.some(function (j) { return FINISHED.indexOf(j.phase) >= 0; });
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(function () { bridge.send('list_publish_jobs', { watching: watched }); }, POLL_MS);   // naming the job the dialog follows: Fusion shows no message box for it
  }

  // ---- Progress dialog (Publish panel) -----------------------------------------

  function isFinished(job) { return FINISHED.indexOf(job.phase) >= 0; }

  function failedRows(job) { return (job.rows || []).filter(function (r) { return r.status === 'error'; }).length; }

  /** The time on a clock: "0:07", "12:05", "1:02:30". */
  function clock(seconds) {
    const whole = Math.max(0, Math.floor(seconds));
    const h = Math.floor(whole / 3600);
    const m = Math.floor(whole % 3600 / 60);
    const sec = String(whole % 60).padStart(2, '0');
    return h ? h + ':' + String(m).padStart(2, '0') + ':' + sec : m + ':' + sec;
  }

  /** "Elapsed 0:07": the time since the job started, counting up while it runs and fixed once it ends ("" while it waits). */
  function elapsedText(job) {
    if (!job || !job.started_at) return '';
    return 'Elapsed ' + clock((job.finished_at || Date.now() / 1000) - job.started_at);
  }

  /**
   * The items of a job by result: ``successful`` (published), ``failed``, ``skipped`` (left out on purpose)
   * and ``pending`` (not finished: waiting or being worked on). A Bill of Materials row is a step after the items, not one of them.
   */
  function tally(job) {
    const total = job.total || 0;
    const items = (job.rows || []).slice(0, total || undefined);
    const failed = items.filter(function (row) { return row.status === 'error'; }).length;
    const skipped = Math.min((job.counts || {}).skipped || 0, Math.max(0, job.done - failed));
    return { successful: Math.max(0, job.done - failed - skipped), failed: failed, skipped: skipped, pending: Math.max(0, total - job.done) };
  }

  /** What a running job says it is doing: items are prepared several at a time, so no single one is "the" item being processed. */
  function runningStatus(job) {
    if (job.stage === 'bom') return 'Updating the Bill of Materials.';
    if (!job.done && !(job.rows || []).some(function (row) { return row.status === 'running'; })) return 'Reading the design and checking Fusion Manage.';
    return job.sends ? 'Checking and updating items in Fusion Manage.' : 'Checking items and preparing their requests.';
  }

  /** What the dialog says for a job: title, status line, count line, bar (percent or null while waiting) and tone. */
  function describe(job) {
    const total = job.total || 0;
    const count = total ? job.done + ' of ' + total + ' items' : '';
    if (job.phase === 'queued') {
      return { title: 'Added to the publishing queue', status: job.place > 1 ? 'Waiting, number ' + job.place + ' in the queue.' : 'Waiting to start.', count: count, percent: null, tone: '' };
    }
    if (job.phase === 'running') {   // at the Bill of Materials every item is done: it goes last
      return { title: 'Publishing ' + job.name, status: runningStatus(job), count: count,
               percent: job.stage === 'bom' ? 100 : total ? Math.round(job.done * 100 / total) : null, tone: '' };
    }
    if (job.phase === 'error') return { title: 'Publish failed', status: job.message || 'The publish could not be completed.', count: '', percent: 100, tone: 'error' };
    if (job.phase === 'cancelled') return { title: 'Publish cancelled', status: job.name + ' was not published.', count: count, percent: total ? Math.round(job.done * 100 / total) : 0, tone: 'error' };
    const failed = failedRows(job);
    if (failed) {
      return { title: 'Completed with errors', status: failed + ' of ' + total + ' item' + (total === 1 ? '' : 's') + ' failed. See the Job Queue for the reasons.',
               count: count, percent: 100, tone: 'error' };
    }
    return { title: 'Publish complete', percent: 100, tone: 'ok', count: count,
             status: job.sends ? job.name + ' was published to Fusion Manage.' : job.name + ' is ready. The requests were written for review; nothing has been sent to Fusion Manage yet.' };
  }

  /** The tally under the bar: items by result, hidden when there is no job to count. Skipped shows only when something was left out. */
  function showTally(job) {
    const box = $('progress-tally');
    box.hidden = !job || !job.total;
    if (box.hidden) return;
    const counts = tally(job);
    [['ok', counts.successful], ['failed', counts.failed], ['skipped', counts.skipped], ['pending', counts.pending]].forEach(function (stat) {
      $('tally-' + stat[0]).textContent = stat[1].toLocaleString();
      $('tally-' + stat[0]).parentNode.classList.toggle('progress-stat-on', stat[1] > 0);
    });
    $('tally-skipped-box').hidden = !counts.skipped;
  }

  function showProgress(view, job) {
    const box = $('progress');
    const bar = $('progress-bar');
    const active = !!job && !isFinished(job);
    box.firstElementChild.classList.remove('progress-ok', 'progress-error');
    if (view.tone) box.firstElementChild.classList.add('progress-' + view.tone);
    $('progress-title').textContent = view.title;
    $('progress-status').textContent = view.status;
    $('progress-count').textContent = view.count || '';
    $('progress-elapsed').textContent = elapsedText(job);
    showTally(job);
    bar.classList.toggle('indeterminate', view.percent === null);
    if (view.percent === null) bar.removeAttribute('aria-valuenow'); else bar.setAttribute('aria-valuenow', String(view.percent));
    $('progress-fill').style.width = view.percent === null ? '' : view.percent + '%';
    $('progress-note').textContent = active
      ? 'You can close this window. Publishing continues in the background and you can follow it in Job Queue on the Fusion Manage tab.'
      : (job ? 'Details are in Job Queue on the Fusion Manage tab.' : '');
    if (!active) confirming = false;
    $('progress-confirm').hidden = !confirming;
    $('progress-actions').hidden = confirming;
    $('progress-cancel').hidden = !active;
    box.hidden = false;
    if (!confirming) $('progress-close').focus();
  }

  /** Close the dialog. A publish still running keeps being followed (``unseen``), so the panel is refreshed when it ends all the same. */
  function closeProgress() {
    const job = watchedJob();
    unseen = job && !isFinished(job) ? job.id : '';
    watched = '';
    confirming = false;
    clearTimeout(timer);
    $('progress').hidden = true;
    if (unseen) schedule();
  }

  /** Tell the panel that the job closed from the dialog has ended; true while it has not. */
  function settleUnseen() {
    if (!unseen) return false;
    const job = jobs.filter(function (j) { return j.id === unseen; })[0];
    if (job && !isFinished(job)) return true;
    unseen = '';
    if (job && notified !== job.id) {
      notified = job.id;
      if (onFinished) onFinished(job);
    }
    return false;
  }

  /** Show or hide the "cancel this publish?" question; the job keeps running until it is answered yes. */
  function askCancel(on) {
    confirming = on;
    $('progress-confirm').hidden = !on;
    $('progress-actions').hidden = on;
    $(on ? 'progress-keep' : 'progress-close').focus();
  }

  function watchedJob() {
    return jobs.filter(function (j) { return j.id === watched; })[0] || null;
  }

  /** Redraw the dialog from the latest list; true while its job is still active. */
  function updateProgress() {
    const job = watchedJob();
    if (!job) { closeProgress(); return false; }
    showProgress(describe(job), job);
    if (!isFinished(job)) return true;
    if (notified !== job.id) {   // once per job, so the panel can read what the run changed
      notified = job.id;
      if (onFinished) onFinished(job);
    }
    return false;
  }

  function handle(r) {
    if (r.ok && r.result.jobs) jobs = r.result.jobs;
    const list = listOpen();
    if (list && r.ok) renderList();
    const following = watched && r.ok ? updateProgress() : !!watched;   // keep polling through a failed read
    const waiting = r.ok ? settleUnseen() : !!unseen;
    if (list || following || waiting) schedule();
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

  function init(options) {
    onFinished = options && options.onFinished;
    ACTIONS.forEach(function (name) { bridge.on(name, name === 'start_publish' ? handleStart : handle); });
    if ($('progress')) {
      $('progress-close').addEventListener('click', closeProgress);
      $('progress-cancel').addEventListener('click', function () { askCancel(true); });
      $('progress-keep').addEventListener('click', function () { askCancel(false); });
      $('progress-stop').addEventListener('click', function () {
        bridge.send('cancel_publish', { id: watched });
        askCancel(false);
      });
      document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape' || $('progress').hidden) return;
        if (confirming) askCancel(false); else closeProgress();
      });
    }
    if (listOpen()) {
      $('pub-jobs-clear').addEventListener('click', function () { bridge.send('clear_publish_jobs'); });
      bridge.send('list_publish_jobs');
    }
  }

  ns.pubJobs = { init: init, start: start, describe: describe, tally: tally, elapsedText: elapsedText };
})(window.MfgUi);
