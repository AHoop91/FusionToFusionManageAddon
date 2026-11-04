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
  const t = ns.i18n.t;

  const ACTIONS = ['start_publish', 'list_publish_jobs', 'cancel_publish', 'clear_publish_jobs', 'retry_publish'];
  const POLL_MS = 1000;
  const FINISHED = ['done', 'error', 'cancelled'];

  let jobs = [];
  let onFinished = null;   // called with a watched job once it has ended
  let onChecks = null;     // called with what the validation of the watched job found for each item number (see ``checks``)
  let notified = '';       // id of the job onFinished was last called for
  let unseen = '';         // id of a running job whose dialog was closed: still followed, to call onFinished when it ends
  let timer = null;
  let confirming = false;   // the dialog asks whether to cancel the publish
  let readStep = null;      // the read of the Bill of Materials a publish starts with, as drawn in the dialog (see ``reading``); null when the publish has none
  let onAbandon = null;     // called when the dialog is closed while that read is still going
  let watched = '';   // id of the job the progress dialog follows ("" = no dialog)

  function listOpen() { return !!$('pub-jobs-list'); }   // only the Jobs window has the list

  // Status icons (24x24 strokes): a grey clock (waiting), a blue clock (running), a red cross (failed), a grey cross (cancelled), and in the details of a job a tick (done) and a dash (skipped).
  const ICONS = {
    queued:    { paths: ['M12 3a9 9 0 1 0 0 18a9 9 0 0 0 0-18z', 'M12 7v5l3 2'] },
    running:   { paths: ['M12 3a9 9 0 1 0 0 18a9 9 0 0 0 0-18z', 'M12 7v5l3 2'] },
    error:     { paths: ['M6 6l12 12', 'M18 6L6 18'] },
    cancelled: { paths: ['M6 6l12 12', 'M18 6L6 18'] },
    done:      { paths: ['M5 12.5l4.5 4.5L19 7.5'] },
    skipped:   { paths: ['M6 12h12'] },
  };

  /** What a status is called, beside its icon. */
  function statusTitle(status) {
    switch (status) {
      case 'running': return t('jobs.status_running');
      case 'error': return t('jobs.status_failed');
      case 'cancelled': return t('jobs.status_cancelled');
      case 'done': return t('jobs.status_done');
      case 'skipped': return t('jobs.status_skipped');
      default: return t('jobs.status_queued');
    }
  }

  /** The status a job shows in the list: its phase, except that a finished job with failed rows reads as failed. */
  function jobStatus(job) { return job.phase === 'done' && failedRows(job) ? 'error' : job.phase; }

  /** "1 item", "3 items". */
  function itemsText(n) { return n === 1 ? t('jobs.items_one', { n: n }) : t('jobs.items_other', { n: n }); }

  /** "1 step", "2 steps". */
  function stepsText(n) { return n === 1 ? t('jobs.steps_one', { n: n }) : t('jobs.steps_other', { n: n }); }

  /** "1 request", "40 requests". */
  function requestsText(n) { return n === 1 ? t('jobs.requests_one', { n: n }) : t('jobs.requests_other', { n: n }); }

  /** "1 item number", "5 item numbers". */
  function numbersText(n) { return n === 1 ? t('jobs.numbers_one', { n: n }) : t('jobs.numbers_other', { n: n }); }

  /** The line under a job's name in the list: where it stands, in a sentence. The details window has the rest. */
  function jobLine(job) {
    const total = job.total || 0;
    const counts = tally(job);
    if (job.phase === 'queued') return job.place ? t('jobs.line_waiting_place', { place: job.place }) : t('jobs.line_waiting');
    if (job.phase === 'running' && job.stage === 'bom') return t('jobs.line_bom', { count: bomCount(job) });
    if (job.phase === 'running') return job.stage === 'validating' ? t('jobs.line_checking') : total ? t('jobs.line_publishing_of', { done: job.done, items: itemsText(total) }) : t('jobs.line_publishing');
    if (job.phase === 'cancelled') return counts.successful ? t('jobs.line_cancelled_some', { n: counts.successful, items: itemsText(total) }) : t('jobs.line_cancelled_none');
    if (job.phase === 'error') return counts.failed ? t('jobs.line_failed_of', { n: counts.failed, items: itemsText(total) }) : t('jobs.line_failed');
    return failedRows(job) ? t('jobs.line_with_errors', { steps: stepsText(failedRows(job)) }) : t('jobs.line_complete');
  }

  /** Does the job still have something to show? One that went through leaves the list. */
  function listed(job) {
    if (stoppedInValidation(job)) return false;
    return !(isFinished(job) && job.phase === 'done' && !failedRows(job));
  }

  /** Can the job be sent again? It has finished with a failed request. */
  function canRetry(job) { return isFinished(job) && (job.phase === 'error' || failedRows(job) > 0); }

  /** The buttons of a job: Cancel while it is active, Retry once it failed (it sends the failed requests again; what was accepted is skipped). */
  function jobActions(job) {
    const cell = ui.el('td');
    if (!isFinished(job)) {
      const cancel = ui.el('button', 'pub-outline-button', t('jobs.cancel_row'));
      cancel.type = 'button';
      cancel.addEventListener('click', function (e) { e.stopPropagation(); bridge.send('cancel_publish', { id: job.id }); });
      cell.appendChild(cancel);
    } else if (canRetry(job)) {
      const retry = ui.el('button', 'pub-outline-button', t('jobs.retry'));
      retry.type = 'button';
      retry.title = t('jobs.retry_tip');
      retry.addEventListener('click', function (e) { e.stopPropagation(); retry.disabled = true; bridge.send('retry_publish', { id: job.id }); });
      cell.appendChild(retry);
    }
    return cell;
  }

  /** One row per job: its status, name, where it stands, how long it has taken and its buttons. Clicking it opens the details. */
  function jobRow(table, job) {
    const status = jobStatus(job);
    const tr = ui.el('tr', 'pub-job-click');
    tr.tabIndex = 0;
    tr.setAttribute('role', 'button');
    tr.title = t('jobs.show_details');
    const icon = ICONS[status] || ICONS.queued;
    const mark = ui.el('td', 'pub-job-status pub-job-' + status);
    const label = ui.el('span', 'pub-job-status-box');
    label.appendChild(ui.svg(icon.paths, 16));
    label.appendChild(ui.el('span', '', statusTitle(status)));
    mark.appendChild(label);
    tr.appendChild(mark);
    tr.appendChild(ui.el('td', 'pub-job-item', job.name));
    tr.appendChild(ui.el('td', 'pub-job-line', jobLine(job)));
    tr.appendChild(ui.el('td', 'pub-job-time', elapsedClock(job) || '-'));
    tr.appendChild(jobActions(job));
    tr.addEventListener('click', function () { openDetails(job.id); });
    tr.addEventListener('keydown', function (e) {
      if (e.target === tr && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); openDetails(job.id); }
    });
    table.appendChild(tr);
  }

  /** The message in the top bar: what is running and waiting, and when nothing is, what stays here until cleared (cancelled publishes, failed items). */
  function queueMessage() {
    const running = jobs.filter(function (j) { return j.phase === 'running'; }).length;
    const waiting = jobs.filter(function (j) { return j.phase === 'queued'; }).length;
    const failed = jobs.reduce(function (n, j) { return n + (j.rows || []).filter(function (r) { return r.status === 'error'; }).length; }, 0);
    const cancelled = jobs.filter(function (j) { return j.phase === 'cancelled'; }).length;
    if (!running && !waiting) {
      const kept = [];
      if (cancelled) kept.push(cancelled === 1 ? t('jobs.kept_cancelled_one', { n: cancelled }) : t('jobs.kept_cancelled_other', { n: cancelled }));
      if (failed) kept.push(failed === 1 ? t('jobs.kept_failed_one', { n: failed }) : t('jobs.kept_failed_other', { n: failed }));
      if (!kept.length) return t('jobs.queue_empty');
      const what = kept.length === 2 ? t('jobs.kept_both', { first: kept[0], second: kept[1] }) : kept[0];
      return cancelled + failed === 1 ? t('jobs.kept_stays', { what: what }) : t('jobs.kept_stay', { what: what });
    }
    const counts = [];
    if (running) counts.push(t('jobs.count_running', { n: running }));
    if (waiting) counts.push(t('jobs.count_waiting', { n: waiting }));
    return t('jobs.queue_active', { counts: counts.length === 2 ? t('jobs.counts_both', { first: counts[0], second: counts[1] }) : counts[0] });
  }

  function renderList() {
    const box = $('pub-jobs-list');
    if (!box) return;
    $('pub-jobs-message').textContent = queueMessage();
    box.textContent = '';
    const table = ui.el('table', 'pub-job-rows');
    const head = ui.el('tr');
    [t('jobs.status'), t('jobs.col_job'), t('jobs.col_progress'), t('jobs.col_time'), ''].forEach(function (text) { head.appendChild(ui.el('th', '', text)); });
    table.appendChild(head);
    let shown = 0;
    jobs.slice().reverse().forEach(function (job) {   // newest first
      if (!listed(job)) return;
      jobRow(table, job);
      shown += 1;
    });
    if (shown) box.appendChild(table);
    $('pub-jobs-clear').disabled = !jobs.some(function (job) { return isFinished(job) && !stoppedInValidation(job); });
    renderDetails();
  }

  // ---- Details window (Job Queue) -------------------------------------------------

  let detailId = '';   // id of the job whose details are open ("" = none)
  let filter = 'all';   // which items the table lists: 'all' or one status
  let query = '';   // text an item's number or description must contain
  let selected = '';   // item number whose details show at the side
  const STATUS_ORDER = ['error', 'skipped', 'cancelled', 'running', 'queued', 'done'];

  function detailJob() { return jobs.filter(function (j) { return j.id === detailId; })[0] || null; }

  function closeDetails() {
    detailId = '';
    if ($('jq-detail')) $('jq-detail').hidden = true;
  }

  function openDetails(id) {
    detailId = id;
    query = '';
    selected = '';
    $('jq-search').value = '';
    filter = detailJob() && failedRows(detailJob()) ? 'error' : 'all';   // a job with failures opens on them
    renderDetails();
    if (!$('jq-detail').hidden) $('jq-close').focus();
  }

  function reasonOf(row) { return row.detail || t('jobs.no_reason'); }

  function statusOf(row) { return ICONS[row.status] ? row.status : 'queued'; }

  /** The items the filters let through. */
  function visibleItems(job) {
    const text = query.trim().toLowerCase();
    return (job.rows || []).filter(function (row) {
      if (filter !== 'all' && statusOf(row) !== filter) return false;
      return !text || ((row.item || '') + ' ' + (row.description || '')).toLowerCase().indexOf(text) >= 0;
    });
  }

  /** The buttons above the table: All, then each status the job has, with how many items. */
  function detailFilters(job) {
    const box = $('jq-filters');
    box.textContent = '';
    const rows = job.rows || [];
    const entries = [['all', t('jobs.filter_all'), rows.length]];
    STATUS_ORDER.forEach(function (status) {
      const n = rows.filter(function (row) { return statusOf(row) === status; }).length;
      if (n) entries.push([status, statusTitle(status), n]);
    });
    if (!entries.some(function (entry) { return entry[0] === filter; })) filter = 'all';
    entries.forEach(function (entry) {
      const button = ui.el('button', 'jq-tab', t('jobs.filter_count', { label: entry[1], n: entry[2] }));
      button.type = 'button';
      button.setAttribute('aria-pressed', String(entry[0] === filter));
      button.addEventListener('click', function () { filter = entry[0]; renderDetails(); });
      box.appendChild(button);
    });
  }

  function selectItem(item) {
    selected = item;
    Array.prototype.forEach.call($('jq-items').children, function (tr) {
      const on = tr.dataset.item === item;
      tr.classList.toggle('jq-selected', on);
      tr.setAttribute('aria-selected', String(on));
    });
    detailInfo(detailJob());
  }

  /** The table: one row per item, a status icon, its number and description. Clicking one shows it at the side. */
  function detailTable(rows) {
    const body = $('jq-items');
    body.textContent = '';
    if (!rows.length) {
      const empty = ui.el('td', 'muted jq-empty', t('jobs.no_match'));
      empty.colSpan = 3;
      body.appendChild(ui.el('tr')).appendChild(empty);
      return;
    }
    rows.forEach(function (row) {
      const tr = ui.el('tr', 'jq-row jq-' + statusOf(row) + (row.item === selected ? ' jq-selected' : ''));
      tr.dataset.item = row.item;
      tr.tabIndex = 0;
      tr.setAttribute('aria-selected', String(row.item === selected));
      const mark = ui.el('td', 'jq-icon');
      mark.appendChild(ui.svg(ICONS[statusOf(row)].paths, 16));
      mark.title = statusTitle(statusOf(row));
      tr.appendChild(mark);
      tr.appendChild(ui.el('td', 'jq-name', row.item || '-'));
      tr.appendChild(ui.el('td', 'jq-text', row.description || ''));
      tr.addEventListener('click', function () { selectItem(row.item); });
      tr.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectItem(row.item); }
      });
      body.appendChild(tr);
    });
  }

  /** The panel at the side: facts about the selected item and, under them, why it failed, was skipped or was cancelled. */
  function detailInfo(job) {
    const row = job && (job.rows || []).filter(function (r) { return r.item === selected; })[0];
    $('jq-info-empty').hidden = !!row;
    $('jq-facts').hidden = !row;
    if (!row) return;
    const status = statusOf(row);
    $('jq-info-title').textContent = row.item || '-';
    $('jq-info-sub').textContent = row.description || '-';
    $('jq-info-status').textContent = statusTitle(status);
    $('jq-info-status').className = 'jq-' + status;
    $('jq-info-job').textContent = job.name;
    const why = status === 'cancelled' ? t('jobs.reason_cancelled') : (status === 'error' || status === 'skipped') ? reasonOf(row) : '';
    $('jq-info-reason').textContent = why;
    $('jq-reason-row').hidden = !why;
  }

  /** What the details say after the list of items: what happened to the work, and what to do next. */
  function detailNote(job) {
    if (job.phase === 'cancelled') return t('jobs.note_cancelled');
    if (job.phase === 'error' || (isFinished(job) && failedRows(job))) return t('jobs.note_failed');
    return '';
  }

  /** Draw (or refresh) the details window of the job it is open for; close it when the job has gone from the list. */
  function renderDetails() {
    const box = $('jq-detail');
    if (!box || !detailId) return;
    const job = detailJob();
    if (!job || !listed(job)) { closeDetails(); return; }
    const view = describe(job);
    $('jq-title').textContent = view.title;
    $('jq-status').textContent = job.phase === 'done' && failedRows(job) ? failureSummary(job) : (view.status || '');
    $('jq-badge').className = 'pub-badge pub-badge-' + badgeOf(view, job);
    $('jq-elapsed').textContent = elapsedText(job);
    const wrap = document.querySelector('.jq-table-wrap');
    const scrolled = wrap.scrollTop;   // the table is drawn again at every poll: keep the place in it
    detailFilters(job);
    const rows = visibleItems(job);
    if (!rows.some(function (row) { return row.item === selected; })) selected = rows.length ? rows[0].item : '';
    detailTable(rows);
    wrap.scrollTop = scrolled;
    detailInfo(job);
    $('jq-note').textContent = detailNote(job);
    $('jq-cancel').hidden = isFinished(job);
    $('jq-retry').hidden = !canRetry(job);
    box.hidden = false;
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(function () { bridge.send('list_publish_jobs', { watching: watched }); }, POLL_MS);   // naming the job the dialog follows: Fusion shows no message box for it
  }

  // ---- Progress dialog (Publish panel) -----------------------------------------

  function isFinished(job) { return FINISHED.indexOf(job.phase) >= 0; }

  /** A job that completed with nothing failed: it leaves the Job Queue, so there are no details to point to. */
  function isClean(job) { return job.phase === 'done' && !failedRows(job); }

  /** A run that stopped in its validation wrote nothing, so it is not a job of the queue: the Jobs window and the dialog's note leave it out. */
  function stoppedInValidation(job) { return job.phase === 'error' && job.stage === 'validating'; }

  /** The failed rows of a job; with `limit`, only among its first `limit` rows (the items: a Bill of Materials row comes after them). */
  function failedRows(job, limit) { return (job.rows || []).slice(0, limit || undefined).filter(function (r) { return r.status === 'error'; }).length; }

  /** The time on a clock: "0:07", "12:05", "1:02:30". */
  function clock(seconds) {
    const whole = Math.max(0, Math.floor(seconds));
    const h = Math.floor(whole / 3600);
    const m = Math.floor(whole % 3600 / 60);
    const sec = String(whole % 60).padStart(2, '0');
    return h ? h + ':' + String(m).padStart(2, '0') + ':' + sec : m + ':' + sec;
  }

  /** "0:07": the time since the job started, counting up while it runs and fixed once it ends ("" while it waits). */
  function elapsedClock(job) {
    if (!job || !job.started_at) return '';
    return clock((job.finished_at || Date.now() / 1000) - job.started_at);
  }

  /** "Elapsed 0:07": the same, in a phrase ("" while the job waits). */
  function elapsedText(job) {
    const time = elapsedClock(job);
    return time ? t('jobs.elapsed', { time: time }) : '';
  }

  /**
   * The items of a job by result: ``successful`` (published), ``failed``, ``skipped`` (left out on purpose)
   * and ``pending`` (not finished: waiting or being worked on). A Bill of Materials row is a step after the items, not one of them.
   */
  function tally(job) {
    const total = job.total || 0;
    const failed = failedRows(job, total);
    const skipped = Math.min((job.counts || {}).skipped || 0, Math.max(0, job.done - failed));
    return { successful: Math.max(0, job.done - failed - skipped), failed: failedRows(job), skipped: skipped, pending: Math.max(0, total - job.done) };
  }

  /** What a running job says it is doing: items are prepared several at a time, so no single one is "the" item being processed. */
  function runningStatus(job) {
    if (job.stage === 'validating') return t('jobs.run_validating');
    if (job.stage === 'bom') return t('jobs.run_bom');
    if (!job.done && !(job.rows || []).some(function (row) { return row.status === 'running'; })) return t('jobs.run_reading');
    return job.sends ? t('jobs.run_sending') : t('jobs.run_preparing');
  }

  /**
   * The validation step: the look-up of every item number, which comes first and ends before anything is written. Its bar is ``percent`` (null
   * while the numbers are not counted yet), with the ``count`` line and the ``tone`` ('ok' once it passed, 'error' where the run failed in it).
   */
  function validation(job) {
    const found = job.validation || { done: 0, total: 0 };
    const looking = job.stage === 'validating';
    const words = numbersText(found.total);
    if (!looking) return { percent: 100, count: found.total ? t('jobs.validation_checked', { numbers: words }) : '', tone: 'ok' };
    if (job.phase === 'queued') return { percent: 0, count: '', tone: '' };
    const percent = found.total ? Math.round(found.done * 100 / found.total) : null;
    const failed = job.phase === 'error';
    return { percent: failed && percent === null ? 0 : percent, count: found.total ? t('jobs.validation_progress', { done: found.done, numbers: words }) : '', tone: failed ? 'error' : '' };
  }

  /** What the dialog says for a job: title, status line, count line, the publishing bar (percent or null while waiting) and tone. */
  function describe(job) {
    const total = job.total || 0;
    const count = total ? t('jobs.count_items', { done: job.done, total: total }) : '';
    if (job.phase === 'queued') {
      return { title: t('jobs.title_queued'), status: job.place > 1 ? t('jobs.line_waiting_place', { place: job.place }) : t('jobs.waiting_to_start'), count: count, percent: null, tone: '' };
    }
    const validating = job.stage === 'validating';
    if (job.phase === 'running') {   // at the Bill of Materials every item is done: it goes last
      return { title: t('jobs.title_publishing', { name: job.name }), status: runningStatus(job), count: validating ? t('jobs.waiting_validation') : count,
               percent: validating ? 0 : publishPercent(job), tone: '' };
    }
    if (job.phase === 'error') {   // a failure in the validation leaves nothing published: its own bar is the red one
      return { title: validating ? t('jobs.title_validation_failed') : t('jobs.title_failed'), status: job.message || t('jobs.failed_default'), count: validating ? t('jobs.not_started') : '',
               percent: validating ? 0 : 100, tone: validating ? '' : 'error' };
    }
    if (job.phase === 'cancelled') return { title: t('jobs.title_cancelled'), status: t('jobs.not_published', { name: job.name }), count: count, percent: total ? Math.round(job.done * 100 / total) : 0, tone: 'error' };
    if (failedRows(job)) {
      return { title: t('jobs.title_with_errors'), status: t('jobs.see_queue', { summary: failureSummary(job) }), count: count, percent: 100, tone: 'error' };
    }
    return { title: t('jobs.title_complete'), percent: 100, tone: 'ok', count: count,
             status: job.sends ? t('jobs.published', { name: job.name }) : t('jobs.ready', { name: job.name }) };
  }

  /** What failed in a job that finished with errors: the items, then the Bill of Materials. */
  function failureSummary(job) {
    const total = job.total || 0;
    const items = failedRows(job, total);
    const parts = [];
    if (items) parts.push(total === 1 ? t('jobs.items_failed_one', { n: items, total: total }) : t('jobs.items_failed_other', { n: items, total: total }));
    if (bomFailed(job)) parts.push(t('jobs.bom_not_updated'));
    return parts.join(' ');
  }

  /** The tally under the bar: items by result, hidden when there is no job to count. It belongs to the publishing, so it is hidden through the validation. Skipped shows only when something was left out. */
  function showTally(job) {
    const box = $('progress-tally');
    box.hidden = !job || !job.total || job.stage === 'validating';
    if (box.hidden) return;
    const counts = tally(job);
    [['ok', counts.successful], ['failed', counts.failed], ['skipped', counts.skipped], ['pending', counts.pending]].forEach(function (stat) {
      $('tally-' + stat[0]).textContent = stat[1].toLocaleString();
      $('tally-' + stat[0]).parentNode.classList.toggle('progress-stat-on', stat[1] > 0);
    });
    $('tally-skipped-box').hidden = !counts.skipped;
  }

  /** Did the job's Bill of Materials fail, beyond the items? Its rows come after the items, so they are the failed rows the items do not account for. */
  function bomFailed(job) { return failedRows(job) > failedRows(job, job.total || 0); }

  /** How far the Bill of Materials has come, in requests (an add, update, removal or renumber each), as the sentence "12 of 40 requests". */
  function bomCount(job) {
    const sent = job.bom || { done: 0, total: 0 };
    return t('jobs.bom_count', { done: sent.done, requests: requestsText(sent.total) });
  }

  /**
   * How far the publishing has come, as one bar: the items, then (when the job sends) the requests of the Bill of Materials, which come after them.
   * Each item and each request counts one, so the bar fills through both without a pause between.
   */
  function publishPercent(job) {
    const items = job.total || 0;
    const requests = job.sends && job.bom ? job.bom : { done: 0, total: 0 };
    const all = items + requests.total;
    return all ? Math.round((Math.min(job.done, items) + requests.done) * 100 / all) : null;
  }

  /** Draw one of the bars (``step``: 'read', 'validate' or 'publish'): ``percent`` is null while it is not measured, ``tone`` colours it. */
  function showBar(step, percent, tone) {
    const bar = $(step === 'publish' ? 'progress-bar' : step + '-bar');
    const box = $(step + '-step');
    box.classList.remove('progress-ok', 'progress-error');
    if (tone) box.classList.add('progress-' + tone);
    box.classList.toggle('progress-active', !tone && (percent === null || (percent > 0 && percent < 100)));
    box.classList.toggle('progress-idle', !tone && percent === 0);
    bar.classList.toggle('indeterminate', percent === null);
    if (percent === null) bar.removeAttribute('aria-valuenow'); else bar.setAttribute('aria-valuenow', String(percent));
    $(step === 'publish' ? 'progress-fill' : step + '-fill').style.width = percent === null ? '' : percent + '%';
  }

  /** The round icon beside the title: a spinner while the job is waiting or running, then a tick or a cross. */
  function badgeOf(view, job) {
    if (!job || !isFinished(job)) return 'busy';
    return view.tone === 'ok' ? 'ok' : 'error';
  }

  /** What a step says beside its name: its percent, "0%" included; while the percent is not known (null), ``fallback`` (what it can say instead). */
  function percentText(percent, fallback) {
    return percent === null ? fallback || '' : percent + '%';
  }

  function showProgress(view, job) {
    const box = $('progress');
    const active = !!job && !isFinished(job);
    $('progress-title').textContent = view.title;
    $('progress-status').textContent = view.status;
    $('progress-count').textContent = percentText(view.percent, view.count);
    $('progress-elapsed').textContent = elapsedText(job);
    $('progress-badge').className = 'pub-badge pub-badge-' + badgeOf(view, job);
    showTally(job);
    showBar('publish', view.percent, view.tone);
    $('read-step').hidden = !readStep;
    if (readStep) {
      $('read-count').textContent = percentText(readStep.percent, readStep.count);
      showBar('read', readStep.percent, readStep.tone);
    }
    const check = job ? validation(job) : { percent: 0, count: '', tone: '' };
    $('validate-count').textContent = percentText(check.percent, check.count);
    showBar('validate', check.percent, check.tone);
    $('progress-note').textContent = active
      ? t('jobs.note_background')
      : (job && !stoppedInValidation(job) && !isClean(job) ? t('jobs.note_details') : '');
    if (!active) confirming = false;
    $('progress-confirm').hidden = !confirming;
    $('progress-actions').hidden = confirming;
    $('progress-cancel').hidden = !active;
    box.hidden = false;
    if (!confirming) $('progress-close').focus();
  }

  /** Close the dialog. A publish still running keeps being followed (``unseen``), so the panel is refreshed when it ends all the same. */
  function closeProgress() {
    const abandon = readStep && !readStep.done ? onAbandon : null;   // closed while the Bill of Materials was still being read: the publish is dropped
    endReading();
    if (abandon) abandon();
    const job = watchedJob();
    unseen = job && !isFinished(job) ? job.id : '';
    watched = '';
    confirming = false;
    clearTimeout(timer);
    $('progress').hidden = true;
    if (unseen) schedule();
  }

  /**
   * What the validation found for each item number of the job, for the rows of the BOM: ``checking`` until the search has answered for it,
   * then ``ok`` or, when several Fusion Manage items carry it, ``review``. Keyed by the number, trimmed and in lower case.
   */
  function checks(job) {
    const counts = (job.validation || {}).counts || {};
    const looking = job.stage === 'validating' && !isFinished(job);
    const states = {};
    (job.rows || []).forEach(function (row) {
      const key = String(row.item || '').trim().toLowerCase();
      if (key && counts[row.item] !== undefined) states[key] = counts[row.item] > 1 ? 'review' : 'ok';
      else if (key && looking) states[key] = 'checking';
    });
    return states;
  }

  /** Tell the panel the job has ended, once per job, so it can read what the run changed. */
  function finish(job) {
    if (notified === job.id) return;
    notified = job.id;
    if (onFinished && !stoppedInValidation(job)) onFinished(job);
  }

  /** Tell the panel that the job closed from the dialog has ended; true while it has not. */
  function settleUnseen() {
    if (!unseen) return false;
    const job = jobs.filter(function (j) { return j.id === unseen; })[0];
    if (job && !isFinished(job)) return true;
    unseen = '';
    if (job) finish(job);
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
    if (onChecks) onChecks(checks(job));
    if (!isFinished(job)) return true;
    finish(job);
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

  let stamp = '';   // what the design on the panel was read under (see ``setStamp``)
  let release = null;   // gives the Publish button back while Python checks the permissions and queues the run (it says it is starting meanwhile)

  function handleStart(r) {
    const s = r.ok ? r.result : { error: r.error || t('jobs.could_not_publish_error') };
    if (s.checking) return;   // the answer comes later, pushed as start_publish_result
    if (release) release();
    release = null;
    if (s.error) {
      watched = '';
      endReading();
      showProgress({ title: t('jobs.could_not_publish'), status: s.error, count: '', percent: 100, tone: 'error' }, null);
      return;
    }
    if (s.cancelled) {   // the folder dialog was cancelled: the dialog that was waiting for the job goes
      stopReading();
      return;
    }
    jobs = s.jobs || [];
    watched = s.queued;
    if (updateProgress()) schedule();
  }

  /**
   * The first step of a publish that has levels of the Bill of Materials to read: the dialog opens at once and says how far the read is, so the
   * wait is not a silent one. ``step`` is ``status``, ``count`` (what the step says while it has no percent: the read has no total) and ``done``
   * (read: the job follows). ``onClose`` is called if the dialog is closed before the read ends.
   */
  function reading(step, onClose) {
    readStep = { percent: step.done ? 100 : null, count: step.count || '', tone: step.done ? 'ok' : '', done: !!step.done };
    onAbandon = onClose || null;
    showProgress({ title: step.done ? t('jobs.title_starting') : t('jobs.title_reading_bom'), status: step.status, count: '', percent: 0, tone: '' }, null);
  }

  /** Forget the read step: the dialog goes on without it. */
  function endReading() {
    readStep = null;
    onAbandon = null;
  }

  /** The read ended without a publish (it failed, or lines need a choice): take the dialog down. */
  function stopReading() {
    if (!readStep) return;
    endReading();
    $('progress').hidden = true;
  }

  /** Queue a publish of ``payload`` (summary, items, operations); Python asks for the folder first. */
  function start(payload) {
    release = ui.busy($('pub-publish'), t('jobs.starting'));
    bridge.send('start_publish', Object.assign({ stamp: stamp }, payload));
  }

  /** What the design on the panel was read under: ``start`` sends it, and Python refuses a publish when the hub or settings have changed. */
  function setStamp(value) {
    stamp = value || '';
  }

  function init(options) {
    onFinished = options && options.onFinished;
    onChecks = options && options.onChecks;
    ACTIONS.forEach(function (name) { bridge.on(name, name === 'start_publish' ? handleStart : handle); });
    if ($('pub-publish')) bridge.on('start_publish_result', handleStart);   // only the Publish panel asks, and is told
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
    if ($('jq-detail')) {
      $('jq-close').addEventListener('click', closeDetails);
      $('jq-cancel').addEventListener('click', function () { bridge.send('cancel_publish', { id: detailId }); });
      $('jq-search').addEventListener('input', function () { query = $('jq-search').value; renderDetails(); });
      $('jq-retry').addEventListener('click', function () { $('jq-retry').disabled = true; bridge.send('retry_publish', { id: detailId }); });
      $('jq-detail').addEventListener('click', function (e) { if (e.target === $('jq-detail')) closeDetails(); });
      document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !$('jq-detail').hidden) closeDetails(); });
    }
    if (listOpen()) {
      $('pub-jobs-clear').addEventListener('click', function () { bridge.send('clear_publish_jobs'); });
      bridge.send('list_publish_jobs');
    }
  }

  ns.pubJobs = { init: init, start: start, setStamp: setStamp, reading: reading, stopReading: stopReading, describe: describe, validation: validation, checks: checks, tally: tally, elapsedText: elapsedText, line: jobLine, listed: listed };
})(window.MfgUi);
