/**
 * Info tips and the confirm dialog of the Item Workspace tab, as ``ns.info``.
 *
 * ``tip(text)`` is an info icon that shows a tip on hover; ``confirmDefaults(kind, onYes)`` asks
 * before "Add default fields" replaces the mapped fields; ``unauthorized()`` says what to check when Fusion Manage refuses a workspace.
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

  /** Say that Fusion Manage refused the user, and what to check. One at a time: asking again while it is open does nothing. */
  function unauthorized() {
    if (document.getElementById('ws-unauthorized')) return;
    const overlay = el('div', 'ws-dialog-overlay');
    overlay.id = 'ws-unauthorized';
    const box = el('div', 'ws-dialog ws-denied');
    box.setAttribute('role', 'alertdialog');
    box.setAttribute('aria-modal', 'true');
    box.setAttribute('aria-labelledby', 'ws-unauthorized-title');
    const icon = el('span', 'ws-denied-icon');
    icon.setAttribute('aria-hidden', 'true');
    icon.appendChild(ns.svg(['M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z', 'M5.6 5.6l12.8 12.8'], 28));
    box.appendChild(icon);
    const title = el('h3', 'ws-dialog-title', t('settings.unauthorized_title'));
    title.id = 'ws-unauthorized-title';
    box.appendChild(title);
    box.appendChild(el('p', 'ws-dialog-text', t('settings.unauthorized_intro')));
    const steps = el('ol', 'ws-denied-list');
    [t('settings.unauthorized_step_signin'), t('settings.unauthorized_step_open'), t('settings.unauthorized_step_add'),
      t('settings.unauthorized_step_retry')].forEach(function (text) { steps.appendChild(el('li', '', text)); });
    box.appendChild(steps);
    const actions = el('div', 'ws-dialog-actions');
    const close = el('button', 'btn', t('settings.close'));
    close.type = 'button';
    actions.appendChild(close);
    box.appendChild(actions);
    overlay.appendChild(box);
    close.addEventListener('click', present(overlay, close));
  }

  ns.info = { tip: infoTip, confirmDefaults: confirmDefaults, unauthorized: unauthorized };
})(window.MfgUi);
