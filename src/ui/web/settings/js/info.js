/**
 * Info tips and the confirm dialog of the Item Workspace tab, as ``ns.info``.
 *
 * ``tip(text)`` is an info icon that shows a tip on hover; ``confirmDefaults(kind, onYes)`` asks
 * before "Add default fields" replaces the mapped fields.
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

  ns.info = { tip: infoTip, confirmDefaults: confirmDefaults };
})(window.MfgUi);
