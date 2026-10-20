/**
 * The report of what differs between the open design and Fusion Manage, as ``ns.diffReport``: a small dialog in the middle of the panel.
 * The Publish panel and the Item panel both show it (from their up-to-date buttons), so the two always look and read the same.
 *
 * ``open(report)``: ``report`` is ``{ state, title, summary, sections, empty, actions }``.
 *   ``state``    ``changes``, ``ok`` or ``error``: the icon and its colour.
 *   ``title``    the heading; ``summary`` the line under it.
 *   ``sections`` ``[{ title, columns, rows }]``: a table each, with a count of its rows. A row is ``{ cells, sub, onClick }``: the text of each
 *                cell (an empty one shows ``-``), ``sub`` a second line under the first cell, and ``onClick`` for a row that can be opened.
 *   ``empty``    the text shown when there are no sections.
 *   ``actions``  ``[{ label, onClick }]``: buttons beside Close. The last is the main one; Close is the main one when there are none.
 */
(function (ns) {
  'use strict';

  const el = ns.el;
  const COLUMN_VALUE = 'Component Value';   // the two columns every report ends with: what the open design holds, and what Fusion Manage does
  const COLUMN_FM = 'Fusion Manage Value';
  const CLOSE_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>';
  const ICONS = {   // static markup
    ok: '<path d="M6 12.5l4 4 8-9"/>',
    changes: '<path d="M12 7v6.5M12 17v.2"/>',
    error: '<path d="M12 7v6.5M12 17v.2"/>',
  };

  let overlay = null;
  let opener = null;

  function close() {
    if (!overlay) return;
    document.removeEventListener('keydown', onKey, true);
    overlay.remove();
    overlay = null;
    if (opener && opener.focus) opener.focus();
  }

  function onKey(event) {
    if (event.key === 'Escape') { event.stopPropagation(); close(); }
  }

  function badge(state) {
    const icon = el('span', 'diff-icon diff-icon-' + state);
    icon.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true">' + (ICONS[state] || ICONS.error) + '</svg>';
    return icon;
  }

  function cell(text, cls) {
    return el('td', cls || '', text === undefined || text === null || text === '' ? '-' : String(text));
  }

  function row(entry) {
    const tr = el('tr', entry.onClick ? 'diff-click' : '');
    entry.cells.forEach(function (text, index) {
      if (index === 0 && entry.sub) {
        const first = el('td', 'diff-name');
        first.appendChild(el('span', 'diff-main', text || '-'));
        first.appendChild(el('span', 'diff-sub', entry.sub));
        tr.appendChild(first);
      } else {
        tr.appendChild(cell(text, index === 0 ? 'diff-name' : ''));
      }
    });
    if (entry.onClick) {
      tr.title = 'Open the details of this component';
      tr.addEventListener('click', function () { close(); entry.onClick(); });
    }
    return tr;
  }

  function section(entry) {
    const box = el('section', 'diff-section');
    const heading = el('h3', 'diff-heading', entry.title);
    heading.appendChild(el('span', 'diff-count', String(entry.rows.length)));
    box.appendChild(heading);
    const table = el('table', 'diff-table');
    const tr = el('tr');
    entry.columns.forEach(function (title) { tr.appendChild(el('th', '', title)); });
    table.appendChild(el('thead')).appendChild(tr);
    const body = el('tbody');
    entry.rows.forEach(function (r) { body.appendChild(row(r)); });
    table.appendChild(body);
    box.appendChild(table);
    return box;
  }

  function button(label, main, onClick) {
    const node = el('button', main ? 'btn' : 'btn btn-secondary', label);
    node.type = 'button';
    node.addEventListener('click', onClick);
    return node;
  }

  function open(report) {
    close();
    opener = document.activeElement;
    overlay = el('div', 'diff-overlay');
    overlay.addEventListener('mousedown', function (event) { if (event.target === overlay) close(); });
    const dialog = el('div', 'diff-dialog');
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.setAttribute('aria-labelledby', 'diff-title');

    const head = el('div', 'diff-head');
    head.appendChild(badge(report.state));
    const text = el('div', 'diff-headtext');
    const title = el('h2', 'diff-title', report.title);
    title.id = 'diff-title';
    text.appendChild(title);
    text.appendChild(el('p', 'diff-summary', report.summary));
    head.appendChild(text);
    const x = el('button', 'diff-close');
    x.type = 'button';
    x.title = 'Close';
    x.setAttribute('aria-label', 'Close');
    x.innerHTML = CLOSE_ICON;
    x.addEventListener('click', close);
    head.appendChild(x);
    dialog.appendChild(head);

    const body = el('div', 'diff-body');
    report.sections.forEach(function (entry) { body.appendChild(section(entry)); });
    if (!report.sections.length) body.appendChild(el('p', 'diff-empty', report.empty || 'There is nothing to list.'));
    dialog.appendChild(body);

    const foot = el('div', 'diff-foot');
    const actions = report.actions || [];
    const done = button('Close', !actions.length, close);
    foot.appendChild(done);
    actions.forEach(function (action, index) {
      foot.appendChild(button(action.label, index === actions.length - 1, function () { close(); action.onClick(); }));
    });
    dialog.appendChild(foot);

    overlay.appendChild(dialog);
    document.body.appendChild(overlay);
    document.addEventListener('keydown', onKey, true);
    (foot.lastChild).focus();
  }

  ns.diffReport = { open: open, close: close, COLUMN_VALUE: COLUMN_VALUE, COLUMN_FM: COLUMN_FM };
})(window.MfgUi);
