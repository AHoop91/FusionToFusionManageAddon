/**
 * Info tips and the confirm dialog of the Workspaces tab, as ``ns.info``.
 *
 * ``tip(text)`` is an info icon whose click shows or hides a tip; ``confirmDefaults(kind, onYes)`` asks
 * before "Add default fields" replaces the mapped fields.
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

    function close() { document.removeEventListener('keydown', onKey); overlay.remove(); }
    function onKey(e) { if (e.key === 'Escape') close(); }
    cancel.addEventListener('click', close);
    ok.addEventListener('click', function () { close(); onYes(); });
    overlay.addEventListener('mousedown', function (e) { if (e.target === overlay) close(); });
    document.addEventListener('keydown', onKey);
    document.body.appendChild(overlay);
    cancel.focus();
  }

  ns.info = { tip: infoTip, confirmDefaults: confirmDefaults };
})(window.MfgUi);
