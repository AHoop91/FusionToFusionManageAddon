/**
 * The dialog for work on the Fusion Hub that takes a moment (saving or reading the Configuration File), as ``ns.progress``: bouncing balls
 * while it goes on, then the outcome.
 *
 * ``show(title, text)`` opens it; ``done(title, text)`` or ``fail(title, text)`` turn it into the result, with one button to close it.
 * Nothing can be done in it while the work goes on.
 */
(function (ns) {
  'use strict';

  const el = ns.el;

  const TICK = ['M5 12.5l4.5 4.5L19 7.5'];
  const CROSS = ['M6 6l12 12', 'M18 6L6 18'];

  let overlay = null;   // the dialog that is open: one at a time
  let content = null;

  function close() {
    if (overlay) overlay.remove();
    overlay = content = null;
    document.removeEventListener('keydown', onKey);
  }
  function onKey(e) { if (e.key === 'Escape' && content && content.dataset.state !== 'working') close(); }

  function show(title, text) {
    close();
    overlay = el('div', 'ws-dialog-overlay');
    const box = el('div', 'ws-dialog sp-dialog');
    box.setAttribute('role', 'alertdialog');
    box.setAttribute('aria-modal', 'true');
    box.setAttribute('aria-labelledby', 'sp-title');
    content = el('div', 'sp-content');
    box.appendChild(content);
    overlay.appendChild(box);
    document.addEventListener('keydown', onKey);
    document.body.appendChild(overlay);
    working(title, text);
  }

  function working(headline, text) {
    content.textContent = '';
    content.dataset.state = 'working';
    const balls = el('div', 'balls');
    balls.setAttribute('role', 'status');
    balls.setAttribute('aria-label', 'Working');
    for (let i = 0; i < 3; i += 1) balls.appendChild(el('span'));
    const title = el('h3', 'sp-title', headline);
    title.id = 'sp-title';
    content.appendChild(balls);
    content.appendChild(title);
    content.appendChild(el('p', 'sp-text', text));
  }

  /** Replace the balls with the outcome: a badge, what happened and a button. */
  function result(ok, headline, text) {
    if (!content) return;
    content.textContent = '';
    content.dataset.state = ok ? 'done' : 'failed';
    const badge = el('span', 'sp-badge');
    badge.appendChild(ns.svg(ok ? TICK : CROSS, 26));
    const title = el('h3', 'sp-title', headline);
    title.id = 'sp-title';
    const button = el('button', 'btn', ok ? 'Done' : 'Close');
    button.type = 'button';
    button.addEventListener('click', close);
    content.appendChild(badge);
    content.appendChild(title);
    content.appendChild(el('p', 'sp-text', text));
    content.appendChild(button);
    button.focus();
  }

  ns.progress = {
    show: show,
    /** An outcome with nothing before it to wait for: the dialog opens already done. */
    notify: function (title, text) { show(title, ''); result(true, title, text); },
    done: function (title, text) { result(true, title, text); },
    fail: function (title, text) { result(false, title, text || 'Something went wrong.'); },
  };
})(window.MfgUi);
