/**
 * What a failed save shows, as ``ns.validation``.
 *
 * Each problem Python reports has a message and where it is (see ``config/problems.py``). ``show(bar, problems)`` marks the field of each
 * problem in red with its message under it, and fills the bar by the Save button with a count; selecting the bar lists the problems, and
 * selecting one closes the list and goes to its field. Putting a field right removes its problem from the list and the count.
 * ``clear(bar)`` takes it all away.
 */
(function (ns) {
  'use strict';

  const el = ns.el;

  const ALERT_ICON = '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M12 2.5 22 20H2z" fill="currentColor" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M12 9v5" stroke="#fff" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="17" r="1.2" fill="#fff"/></svg>';

  let pending = [];   // the problems still open: {message, target (the marked field, or null), note (its message under it), stop}
  let barNow = null;  // the bar that shows them

  /** The element a problem is about, or null when the panel has nothing for it (for example a row that is gone). */
  function find(where) {
    if (where.input) return document.getElementById(where.input);
    const card = where.workspace ? document.querySelector('#workspace-cards .ws-kind[data-kind="' + where.workspace + '"]') : null;
    if (!card) return null;
    let part = null;
    if (where.area === 'id') part = card.querySelector('.ws-id');
    else if (where.area === 'component') part = card.querySelector('.ws-component-field');
    else if (where.area === 'mappings') return card.querySelector('.ws-add-btn');
    else {
      const rows = card.querySelectorAll(where.area === 'static' ? '.ws-static-row' : '.ws-row:not(.ws-static-row)');
      const row = rows[where.row];
      if (row) part = row.querySelector(where.part === 'source' ? '.ws-source' : '.ws-fm-field');
    }
    return part ? part.parentNode : null;   // a picker's wrapper holds its value input and its button
  }

  /** What the message says about its own field: the part before the colon names the row, which the note stands under. */
  function inline(message, where) {
    const text = where.input ? message : message.replace(/^[^:]+: /, '');
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  /** Put a message under its field: in a row, in a line of its own under the row with the message in the field's column. */
  function place(note, target) {
    const row = target.closest('.ws-row');
    if (row) {
      let box = row.nextElementSibling;
      if (!box || !box.classList.contains('ws-row-notes')) {
        box = el('div', 'ws-row-notes');
        row.parentNode.insertBefore(box, row.nextSibling);
      }
      note.style.gridColumn = target === row.firstElementChild ? '1' : '3';
      note.style.gridRow = '1';   // the messages share a line whatever order they came in
      box.appendChild(note);
      return;
    }
    const anchor = target.closest('.ws-id-row') || target;
    anchor.parentNode.insertBefore(note, anchor.nextSibling);
  }

  function countText(count) {
    return count === 1 ? '1 issue needs your attention' : count + ' issues need your attention';
  }

  /** Fill the bar with the count of open problems, or hide it when none are left. */
  function paintBar() {
    const bar = barNow;
    bar.hidden = pending.length === 0;
    bar.textContent = '';
    if (!pending.length) return;
    const icon = el('span', 'vbar-icon');
    icon.innerHTML = ALERT_ICON;
    const text = el('span', 'vbar-text');
    text.appendChild(el('strong', '', 'Validation failed'));
    text.appendChild(el('span', '', countText(pending.length)));
    bar.appendChild(icon);
    bar.appendChild(text);
    bar.appendChild(el('span', 'vbar-action', 'View details'));
  }

  function release(problem) {
    problem.stop();
    if (problem.target) problem.target.classList.remove('invalid');
    if (problem.note) {
      const box = problem.note.parentNode;
      problem.note.remove();
      if (box.classList.contains('ws-row-notes') && !box.firstChild) box.remove();   // the last message of a row
    }
  }

  /** A field was put right: its problem is closed. */
  function resolve(problem) {
    release(problem);
    pending = pending.filter(function (p) { return p !== problem; });
    paintBar();
  }

  function mark(problem, target, message) {
    target.classList.add('invalid');
    problem.target = target;
    problem.note = el('p', 'field-error', message);
    problem.note.setAttribute('role', 'alert');
    place(problem.note, target);
    // Choosing or typing in the field puts it right.
    const event = target.classList.contains('ws-pick-wrap') ? 'pick' : 'input';
    // A cleared picker is still wrong, so only a choice puts it right.
    const done = function () { if (event === 'input' || target.querySelector('input').value) resolve(problem); };
    target.addEventListener(event, done);
    problem.stop = function () { target.removeEventListener(event, done); };
  }

  /** Bring the field of a problem into view, on the tab that holds it. */
  function reveal(target) {
    const panel = target.closest('[id^="sub-"]');
    const tab = panel && document.querySelector('.tab[data-tab="' + panel.id.slice(4) + '"]');
    if (tab && !tab.classList.contains('active')) tab.click();
    target.scrollIntoView({ block: 'center' });
    const control = target.matches('input, button') ? target : target.querySelector('button, input');
    if (control) control.focus({ preventScroll: true });
  }

  /** The dialog listing the open problems; selecting one closes it and goes to its field. */
  function openDialog() {
    if (!pending.length) return;
    const overlay = el('div', 'ws-dialog-overlay');
    const box = el('div', 'ws-dialog val-dialog');
    box.setAttribute('role', 'alertdialog');
    box.setAttribute('aria-modal', 'true');
    box.setAttribute('aria-labelledby', 'val-title');

    const head = el('div', 'val-head');
    const badge = el('span', 'val-badge');
    badge.innerHTML = ALERT_ICON;
    const heading = el('div', 'val-heading');
    const title = el('h3', 'val-title', 'Validation failed');
    title.id = 'val-title';
    heading.appendChild(title);
    heading.appendChild(el('p', 'val-sub', 'Your settings were not saved. ' + countText(pending.length) + '. Select one to go to it.'));
    head.appendChild(badge);
    head.appendChild(heading);
    box.appendChild(head);

    function close() { document.removeEventListener('keydown', onKey); overlay.remove(); }
    function onKey(e) { if (e.key === 'Escape') close(); }

    const list = el('ol', 'val-list');
    pending.forEach(function (problem) {
      const item = el('li');
      const target = problem.target;
      const row = el(target ? 'button' : 'div', 'val-item');
      row.appendChild(el('span', 'val-text', problem.message));
      if (target) {
        row.type = 'button';
        row.appendChild(el('span', 'val-go', 'Go to field'));
        row.addEventListener('click', function () { close(); reveal(target); });
      }
      item.appendChild(row);
      list.appendChild(item);
    });
    box.appendChild(list);

    const actions = el('div', 'ws-dialog-actions');
    const ok = el('button', 'btn', 'Close');
    ok.type = 'button';
    ok.addEventListener('click', close);
    actions.appendChild(ok);
    box.appendChild(actions);
    overlay.appendChild(box);
    overlay.addEventListener('mousedown', function (e) { if (e.target === overlay) close(); });
    document.addEventListener('keydown', onKey);
    document.body.appendChild(overlay);
    ok.focus();
  }

  /** A row or card is being removed: its problems go with it. */
  function forget(container) {
    pending.filter(function (p) { return p.target && container.contains(p.target); }).forEach(resolve);
  }

  /** Take away the marks and empty the bar. */
  function clear(bar) {
    pending.forEach(release);
    pending = [];
    bar.hidden = true;
    bar.textContent = '';
  }

  /** Mark the fields of ``problems`` (``[{message, where}]``) and show their count in ``bar``; an empty list only clears. */
  function show(bar, problems) {
    clear(bar);
    barNow = bar;
    bar.onclick = openDialog;
    let first = null;
    problems.forEach(function (item) {
      const problem = { message: item.message, target: null, note: null, stop: function () {} };
      const target = find(item.where || {});
      if (target) {
        mark(problem, target, inline(item.message, item.where));
        first = first || target;
      }
      pending.push(problem);
    });
    paintBar();
    if (first && first.offsetParent) first.scrollIntoView({ block: 'center' });   // only when its tab is the one showing
  }

  ns.validation = { show: show, clear: clear, forget: forget };
})(window.MfgUi);
