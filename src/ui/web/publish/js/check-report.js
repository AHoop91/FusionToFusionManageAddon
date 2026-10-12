/**
 * Publish Item panel: the report behind the up-to-date button, as ``ns.pubCheckReport``. A small dialog in the middle of the
 * panel lists every discrepancy between the design and Fusion Manage: attributes of the design, then Bill of Materials lines.
 *
 * ``open(report, hooks)``: ``report`` is ``{ state, text, subject, props: [{ name, fusion, fm }], lines: [{ level, number, name, issue, fusion, fm, component }] }``;
 * ``hooks.onLine(component)`` opens a line's details.
 */
(function (ns) {
  'use strict';

  const el = ns.pubUi.el;

  const TITLES = { ok: 'Up to date', changes: 'Out of date', error: 'Could not check' };
  const CLOSE_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>';
  const ICONS = {
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
    const icon = el('span', 'pub-rep-icon pub-rep-icon-' + state);
    icon.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true">' + (ICONS[state] || ICONS.error) + '</svg>';
    return icon;
  }

  function section(title, count, head, rows) {
    const box = el('section', 'pub-rep-section');
    const heading = el('h3', 'pub-rep-heading', title);
    heading.appendChild(el('span', 'pub-rep-count', String(count)));
    box.appendChild(heading);
    const table = el('table', 'pub-rep-table');
    const tr = el('tr');
    head.forEach(function (h) { tr.appendChild(el('th', '', h)); });
    const thead = el('thead');
    thead.appendChild(tr);
    table.appendChild(thead);
    const body = el('tbody');
    rows.forEach(function (r) { body.appendChild(r); });
    table.appendChild(body);
    box.appendChild(table);
    return box;
  }

  function cell(text, cls) {
    const td = el('td', cls || '');
    td.textContent = text === undefined || text === null || text === '' ? '-' : String(text);
    return td;
  }

  function propRow(p) {
    const tr = el('tr');
    tr.appendChild(cell(p.name, 'pub-rep-name'));
    tr.appendChild(cell(p.fusion));
    tr.appendChild(cell(p.fm));
    return tr;
  }

  function lineRow(l, hooks) {
    const tr = el('tr', l.component ? 'pub-rep-click' : '');
    const first = el('td', 'pub-rep-name');
    first.appendChild(el('span', 'pub-rep-number', l.number || '-'));
    if (l.name) first.appendChild(el('span', 'pub-rep-sub', l.name));
    tr.appendChild(first);
    tr.appendChild(cell(l.issue, 'pub-rep-issue'));
    tr.appendChild(cell(l.fusion));
    tr.appendChild(cell(l.fm));
    if (l.component) {
      tr.title = 'Open the details of this component';
      tr.addEventListener('click', function () { close(); hooks.onLine(l.component); });
    }
    return tr;
  }

  function open(report, hooks) {
    close();
    opener = document.activeElement;
    overlay = el('div', 'pub-rep-overlay');
    overlay.addEventListener('mousedown', function (event) { if (event.target === overlay) close(); });
    const dialog = el('div', 'pub-rep-dialog');
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.setAttribute('aria-labelledby', 'pub-rep-title');

    const head = el('div', 'pub-rep-head');
    head.appendChild(badge(report.state));
    const text = el('div', 'pub-rep-headtext');
    const title = el('h2', 'pub-rep-title', TITLES[report.state] || 'Fusion Manage check');
    title.id = 'pub-rep-title';
    text.appendChild(title);
    text.appendChild(el('p', 'pub-rep-summary', report.text));
    head.appendChild(text);
    const x = el('button', 'pub-rep-close');
    x.type = 'button';
    x.title = 'Close';
    x.setAttribute('aria-label', 'Close');
    x.innerHTML = CLOSE_ICON;
    x.addEventListener('click', close);
    head.appendChild(x);
    dialog.appendChild(head);

    const body = el('div', 'pub-rep-body');
    if (report.props.length) body.appendChild(section('Attributes', report.props.length, ['Property', 'Fusion', 'Fusion Manage'], report.props.map(propRow)));
    if (report.lines.length) body.appendChild(section('Bill of Materials', report.lines.length, ['Item', 'Issue', 'Fusion', 'Fusion Manage'], report.lines.map(function (l) { return lineRow(l, hooks); })));
    if (!report.props.length && !report.lines.length) {
      body.appendChild(el('p', 'pub-rep-empty', report.state === 'ok'
        ? 'Attributes and Bill of Materials for ' + report.subject + ' are up to date.'
        : 'There is nothing to list.'));
    }
    dialog.appendChild(body);

    const foot = el('div', 'pub-rep-foot');
    const done = el('button', 'btn', 'Close');
    done.type = 'button';
    done.addEventListener('click', close);
    foot.appendChild(done);
    dialog.appendChild(foot);

    overlay.appendChild(dialog);
    document.body.appendChild(overlay);
    document.addEventListener('keydown', onKey, true);
    done.focus();
  }

  ns.pubCheckReport = { open: open, close: close };
})(window.MfgUi);
