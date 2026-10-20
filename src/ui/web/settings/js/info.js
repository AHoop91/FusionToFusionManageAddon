/**
 * Info tips and the confirm dialog of the Item Workspace tab, as ``ns.info``.
 *
 * ``tip(text)`` is an info icon that shows a tip on hover; ``confirmDefaults(kind, onYes)`` asks
 * before "Add default fields" replaces the mapped fields; ``showValidation`` reports a failed save.
 */
(function (ns) {
  'use strict';

  const el = ns.el;

  const INFO_ICON = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="currentColor"/><path d="M12 11v6" stroke="#fff" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="7.5" r="1.4" fill="#fff"/></svg>';

  /** An info icon that shows a tip with `text` on hover or focus, the same as on the Connection tab. */
  function infoTip(text) {
    const icon = el('span', 'info', 'i');
    icon.tabIndex = 0;
    icon.setAttribute('aria-label', 'More information');
    const tip = el('span', 'tip', text);
    tip.setAttribute('role', 'tooltip');
    icon.appendChild(tip);
    return icon;
  }

  /** Show a dialog overlay and focus ``focus``; Escape or a click outside closes it. Returns the function that closes it. */
  function present(overlay, focus) {
    function close() { document.removeEventListener('keydown', onKey); overlay.remove(); }
    function onKey(e) { if (e.key === 'Escape') close(); }
    overlay.addEventListener('mousedown', function (e) { if (e.target === overlay) close(); });
    document.addEventListener('keydown', onKey);
    document.body.appendChild(overlay);
    focus.focus();
    return close;
  }

  /** Ask before "Add default fields" replaces the mapped fields; ``onYes`` runs if the user agrees; ``kind`` names the workspace. */
  function confirmDefaults(kind, onYes) {
    const overlay = el('div', 'ws-dialog-overlay');
    const box = el('div', 'ws-dialog');
    box.setAttribute('role', 'alertdialog');
    box.setAttribute('aria-modal', 'true');
    box.setAttribute('aria-labelledby', 'ws-dialog-title');
    const title = el('h3', 'ws-dialog-title', 'Load default fields?');
    title.id = 'ws-dialog-title';
    box.appendChild(title);
    box.appendChild(el('p', 'ws-dialog-text',
      'Loading the default fields replaces all existing field mappings with the standard set. Any mappings you have added or changed will be removed. Do you want to continue?'));
    const note = el('div', 'ws-info');
    note.setAttribute('role', 'note');
    const icon = el('span', 'ws-info-icon');
    icon.innerHTML = INFO_ICON;
    note.appendChild(icon);
    note.appendChild(el('p', 'ws-info-text',
      'The defaults reflect the out-of-the-box ' + kind.title + ' workspace. If your workspace has been customized, you will need to adjust the mappings manually.'));
    box.appendChild(note);

    const actions = el('div', 'ws-dialog-actions');
    const cancel = el('button', 'btn btn-secondary', 'Cancel');
    const ok = el('button', 'btn', 'Load default fields');
    cancel.type = ok.type = 'button';
    actions.appendChild(cancel);
    actions.appendChild(ok);
    box.appendChild(actions);
    overlay.appendChild(box);

    const close = present(overlay, cancel);
    cancel.addEventListener('click', close);
    ok.addEventListener('click', function () { close(); onYes(); });
  }

  const ALERT_ICON = '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M12 2.5 22 20H2z" fill="currentColor" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M12 9v5" stroke="#fff" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="17" r="1.2" fill="#fff"/></svg>';

  // What to do about a known problem, shown under it in the dialog.
  const FIXES = [
    ['Item Number must be mapped', 'On the Item Workspace tab, choose Add field mapping, set the Component Property to Item Number and the Fusion Manage Item Field to NUMBER. Add default fields includes this mapping.'],
  ];

  /** `{area, text, fix}` for one problem line such as "Items: Workspace ID must be a number.". */
  function describeProblem(line) {
    const match = /^([A-Za-z][A-Za-z ]{0,24}): (.+)$/.exec(line);
    const text = match ? match[2] : line;
    const found = FIXES.find(function (f) { return text.indexOf(f[0]) !== -1; });
    return { area: match ? match[1] : '', text: text, fix: found ? found[1] : '' };
  }

  /** The lines of a save error, one problem each. */
  function problemLines(message) {
    return String(message).split('\n').map(function (l) { return l.trim(); })
      .filter(function (l, i, all) { return l && all.indexOf(l) === i; });   // a problem found on several rows is listed once
  }

  /** Fill a validation bar with its summary, or hide it when ``message`` is empty. Clicking it opens the details. */
  function showValidation(bar, message) {
    const lines = problemLines(message);
    bar.hidden = lines.length === 0;
    bar.textContent = '';
    if (!lines.length) return;
    const icon = el('span', 'vbar-icon');
    icon.innerHTML = ALERT_ICON;
    const text = el('span', 'vbar-text');
    text.appendChild(el('strong', '', 'Validation failed'));
    text.appendChild(el('span', '', lines.length === 1 ? '1 issue needs your attention' : lines.length + ' issues need your attention'));
    bar.appendChild(icon);
    bar.appendChild(text);
    bar.appendChild(el('span', 'vbar-action', 'View details'));
    bar.onclick = function () { validationDialog(lines); };
  }

  /** The dialog listing each validation problem, with how to fix it where that is known. */
  function validationDialog(lines) {
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
    heading.appendChild(el('p', 'val-sub', 'Your settings were not saved. Resolve ' + (lines.length === 1 ? 'the issue' : 'these issues') + ' below, then save again.'));
    head.appendChild(badge);
    head.appendChild(heading);
    box.appendChild(head);

    const list = el('ol', 'val-list');
    lines.forEach(function (line) {
      const p = describeProblem(line);
      const item = el('li', 'val-item');
      if (p.area) item.appendChild(el('span', 'val-area', p.area));
      item.appendChild(el('p', 'val-text', p.text));
      if (p.fix) {
        const fix = el('p', 'val-fix');
        fix.appendChild(el('strong', '', 'How to fix: '));
        fix.appendChild(document.createTextNode(p.fix));
        item.appendChild(fix);
      }
      list.appendChild(item);
    });
    box.appendChild(list);

    const actions = el('div', 'ws-dialog-actions');
    const ok = el('button', 'btn', 'Got it');
    ok.type = 'button';
    actions.appendChild(ok);
    box.appendChild(actions);
    overlay.appendChild(box);

    ok.addEventListener('click', present(overlay, ok));
  }

  ns.info = { tip: infoTip, confirmDefaults: confirmDefaults, showValidation: showValidation };
})(window.MfgUi);
