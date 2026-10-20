/**
 * The dialog a Hub Admin gets from Save, as ``ns.saveMenu``: keep the settings on this computer, or also store the Configuration File in the
 * Fusion Hub for the hub's members.
 *
 * ``open(hubName, onChoose)`` shows it; ``onChoose('local' | 'hub')`` runs when the admin confirms.
 */
(function (ns) {
  'use strict';

  const el = ns.el;

  const CHOICES = [
    { id: 'local', label: 'Save locally', note: 'Keep these settings on this computer only.',
      icon: ['M4 5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z', 'M2 20h20', 'M9 16v4', 'M15 16v4'] },
    { id: 'hub', label: 'Save to Fusion Hub', note: 'Also store the Configuration File in a folder of the hub, so its members can use these settings.',
      icon: ['M7 18a5 5 0 1 1 .9-9.9A6 6 0 0 1 19 10a4 4 0 0 1-1 8z'] },
  ];

  let showing = false;   // one dialog at a time

  function open(hubName, onChoose) {
    if (showing) return;
    showing = true;
    let choice = 'local';

    const overlay = el('div', 'ws-dialog-overlay');
    const box = el('div', 'ws-dialog sm-dialog');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    box.setAttribute('aria-labelledby', 'sm-title');

    const title = el('h3', 'ws-dialog-title', 'Save settings');
    title.id = 'sm-title';
    const sub = el('p', 'sm-sub');
    sub.appendChild(document.createTextNode('These settings are for the hub '));
    sub.appendChild(el('strong', '', hubName || 'this hub'));
    sub.appendChild(document.createTextNode('. Choose where to keep them.'));

    const group = el('div', 'sm-choices');
    group.setAttribute('role', 'radiogroup');
    group.setAttribute('aria-labelledby', 'sm-title');
    const cards = CHOICES.map(function (item) {
      const card = el('button', 'sm-choice');
      card.type = 'button';
      card.setAttribute('role', 'radio');
      const badge = el('span', 'sm-icon');
      badge.appendChild(ns.svg(item.icon, 20));
      const text = el('span', 'sm-text');
      text.appendChild(el('strong', '', item.label));
      text.appendChild(el('span', 'sm-note', item.note));
      card.appendChild(badge);
      card.appendChild(text);
      card.appendChild(el('span', 'sm-radio'));
      card.addEventListener('click', function () { choose(item.id); });
      card.addEventListener('dblclick', confirm);
      group.appendChild(card);
      return { id: item.id, card: card };
    });

    const actions = el('div', 'ws-dialog-actions');
    const cancel = el('button', 'btn btn-secondary', 'Cancel');
    const save = el('button', 'btn', 'Save');
    cancel.type = save.type = 'button';
    actions.appendChild(cancel);
    actions.appendChild(save);
    [title, sub, group, actions].forEach(function (node) { box.appendChild(node); });
    overlay.appendChild(box);

    function choose(id) {
      choice = id;
      cards.forEach(function (c) {
        c.card.classList.toggle('selected', c.id === id);
        c.card.setAttribute('aria-checked', String(c.id === id));
      });
      save.textContent = id === 'hub' ? 'Continue' : 'Save';   // the hub choice goes on to ask for the folder
    }
    function close() {
      document.removeEventListener('keydown', onKey);
      overlay.remove();
      showing = false;
    }
    function confirm() { const picked = choice; close(); onChoose(picked); }
    function onKey(e) {
      if (e.key === 'Escape') close();
      else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { choose(choice === 'local' ? 'hub' : 'local'); }
    }

    cancel.addEventListener('click', close);
    save.addEventListener('click', confirm);
    overlay.addEventListener('mousedown', function (e) { if (e.target === overlay) close(); });
    document.addEventListener('keydown', onKey);
    document.body.appendChild(overlay);
    choose('local');
    save.focus();
  }

  ns.saveMenu = { open: open };
})(window.MfgUi);
