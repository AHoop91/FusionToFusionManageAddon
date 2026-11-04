/**
 * Info tips and the confirm dialog of the Item Workspace tab, as ``ns.info``.
 *
 * ``tip(text)`` is an info icon that shows a tip on hover; ``confirmDefaults(kind, onYes)`` asks
 * before "Add default fields" replaces the mapped fields.
 */
(function (ns) {
  'use strict';

  const el = ns.el;
  const t = ns.i18n.t;

  const INFO_ICON = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="currentColor"/><path d="M12 11v6" stroke="#fff" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="7.5" r="1.4" fill="#fff"/></svg>';

  /** An info icon that shows a tip with `text` on hover or focus, the same as on the Connection tab. */
  function infoTip(text) {
    const icon = el('span', 'info', 'i');
    icon.tabIndex = 0;
    icon.setAttribute('aria-label', t('settings.more_info'));
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
    const title = el('h3', 'ws-dialog-title', t('settings.defaults_title'));
    title.id = 'ws-dialog-title';
    box.appendChild(title);
    box.appendChild(el('p', 'ws-dialog-text',
      t('settings.defaults_text')));
    const note = el('div', 'ws-info');
    note.setAttribute('role', 'note');
    const icon = el('span', 'ws-info-icon');
    icon.innerHTML = INFO_ICON;
    note.appendChild(icon);
    note.appendChild(el('p', 'ws-info-text',
      t('settings.defaults_note', { title: kind.title })));
    box.appendChild(note);

    const actions = el('div', 'ws-dialog-actions');
    const cancel = el('button', 'btn btn-secondary', t('settings.cancel'));
    const ok = el('button', 'btn', t('settings.defaults_confirm'));
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
