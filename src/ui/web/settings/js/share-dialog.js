/**
 * The question a Hub Admin gets after the settings have been saved, as ``ns.shareDialog``: also store the Configuration File in the Fusion
 * Hub for the hub's members?
 *
 * ``open(hubName, onShare)`` shows it; ``onShare()`` runs if the admin agrees.
 */
(function (ns) {
  'use strict';

  const el = ns.el;

  let showing = false;   // one dialog at a time

  function open(hubName, onShare) {
    if (showing) return;
    showing = true;

    const overlay = el('div', 'ws-dialog-overlay');
    const box = el('div', 'ws-dialog');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    box.setAttribute('aria-labelledby', 'share-title');

    const title = el('h3', 'ws-dialog-title', 'Settings saved');
    title.id = 'share-title';
    const text = el('p', 'ws-dialog-text');
    text.appendChild(document.createTextNode('Do you also want to share them with the members of '));
    text.appendChild(el('strong', '', hubName || 'this hub'));
    text.appendChild(document.createTextNode('? The Configuration File is stored in a folder of the hub, and members use the settings in it.'));

    const actions = el('div', 'ws-dialog-actions');
    const later = el('button', 'btn btn-secondary', 'Not now');
    const share = el('button', 'btn', 'Save to Fusion Hub');
    later.type = share.type = 'button';
    actions.appendChild(later);
    actions.appendChild(share);
    [title, text, actions].forEach(function (node) { box.appendChild(node); });
    overlay.appendChild(box);

    function close() {
      document.removeEventListener('keydown', onKey);
      overlay.remove();
      showing = false;
    }
    function onKey(e) { if (e.key === 'Escape') close(); }

    later.addEventListener('click', close);
    share.addEventListener('click', function () { close(); onShare(); });
    overlay.addEventListener('mousedown', function (e) { if (e.target === overlay) close(); });
    document.addEventListener('keydown', onKey);
    document.body.appendChild(overlay);
    share.focus();
  }

  ns.shareDialog = { open: open };
})(window.MfgUi);
