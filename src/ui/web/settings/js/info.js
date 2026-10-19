/**
 * Info tips and the confirm dialog of the Workspaces tab, as ``ns.info``.
 *
 * ``tip(text)`` is an info icon whose click shows or hides a tip; ``confirmDefaults(kind, onYes)`` asks
 * before "Add default fields" replaces the mapped fields; ``showValidation`` reports a failed save;
 * ``shareDialog(path, onYes)`` offers to follow an exported file as the Shared Configuration.
 */
(function (ns) {
  'use strict';

  const el = ns.el;

  const INFO_ICON = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="currentColor"/><path d="M12 11v6" stroke="#fff" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="7.5" r="1.4" fill="#fff"/></svg>';

  /** Close any open info tip. */
  function closeTips(except) {
    document.querySelectorAll('.ws-tip-wrap.open').forEach(function (w) { if (w !== except) w.classList.remove('open'); });
  }
  document.addEventListener('click', function (e) { if (!e.target.closest('.ws-tip-wrap')) closeTips(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeTips(); });

  /** An info icon button; clicking it shows or hides a tip with `text`. */
  function infoTip(text) {
    const wrap = el('span', 'ws-tip-wrap');
    const btn = el('button', 'ws-tip-btn');
    btn.type = 'button';
    btn.setAttribute('aria-label', 'More information');
    btn.innerHTML = INFO_ICON;
    const tip = el('span', 'ws-tip', text);
    tip.setAttribute('role', 'tooltip');
    btn.addEventListener('click', function () {
      const open = !wrap.classList.contains('open');
      closeTips(wrap);
      wrap.classList.toggle('open', open);
    });
    wrap.appendChild(btn);
    wrap.appendChild(tip);
    return wrap;
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
    ['Item Number must be mapped', 'On the Workspaces tab, choose Add field mapping, set the source to Item Number and the Fusion Manage field to NUMBER. Add default fields includes this mapping.'],
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

  const SHARE_ICON = '<svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 14.5 11 16.5 15 12"/></svg>';

  // What changes when the exported file becomes the Shared Configuration.
  const SHARE_EFFECTS = [
    'Your settings are read from this file, so you work with the same setup as everyone who uses it.',
    'The Connection, Workspaces and Exports tabs become read-only here.',
    'Your own settings are kept. To change the shared setup, switch back to Local Configuration on the General tab, make the changes, and export over this file again.',
  ];

  /** After an export: offer to follow the exported file as the Shared Configuration. ``onYes`` runs if the user agrees. */
  function shareDialog(path, onYes) {
    const overlay = el('div', 'ws-dialog-overlay');
    const box = el('div', 'ws-dialog val-dialog share-dialog');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    box.setAttribute('aria-labelledby', 'share-title');

    const head = el('div', 'val-head');
    const badge = el('span', 'val-badge');
    badge.innerHTML = SHARE_ICON;
    const heading = el('div', 'val-heading');
    const title = el('h3', 'val-title', 'Use this file as your Shared Configuration?');
    title.id = 'share-title';
    heading.appendChild(title);
    heading.appendChild(el('p', 'val-sub', 'Your configuration was exported. You can now follow it like everyone else will.'));
    head.appendChild(badge);
    head.appendChild(heading);
    box.appendChild(head);

    const body = el('div', 'share-body');
    body.appendChild(el('span', 'share-label', 'Exported file'));
    body.appendChild(el('p', 'share-path', path));
    body.appendChild(el('span', 'share-label', 'What changes'));
    const list = el('ul', 'share-list');
    SHARE_EFFECTS.forEach(function (text) { list.appendChild(el('li', '', text)); });
    body.appendChild(list);
    body.appendChild(el('p', 'share-hint', 'Choose this only if the file is in the location everyone will use, such as a shared folder or network path.'));
    box.appendChild(body);

    const actions = el('div', 'ws-dialog-actions');
    const cancel = el('button', 'btn btn-secondary', 'Not now');
    const ok = el('button', 'btn', 'Use this file');
    cancel.type = ok.type = 'button';
    actions.appendChild(cancel);
    actions.appendChild(ok);
    box.appendChild(actions);
    overlay.appendChild(box);

    const close = present(overlay, cancel);
    cancel.addEventListener('click', close);
    ok.addEventListener('click', function () { close(); onYes(); });
  }

  ns.info = { tip: infoTip, confirmDefaults: confirmDefaults, showValidation: showValidation, shareDialog: shareDialog };
})(window.MfgUi);
