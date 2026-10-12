/**
 * Toasts (Material "snackbars"), shared by the panels, as ``ns.toast``.
 * ``show(message, opts)`` slides a short message up from the bottom of the panel and removes it after a few seconds;
 * ``opts``: ``tone`` ('success', 'error' or 'info', default 'info'). Three show at once: the oldest goes first.
 * A toast stays while the pointer is over it.
 */
(function (ns) {
  'use strict';

  const el = ns.el;

  const svg = ns.svg;

  const MAX_TOASTS = 3;
  const DURATION_MS = 4000;
  const LEAVE_MS = 200;   // matches the leave animation in toast.css
  const ICONS = {
    success: ['M5 12l5 5L20 7'],
    error: ['M12 8v5', 'M12 16.5v.5', 'M12 3l10 18H2z'],
    info: ['M12 11v6', 'M12 7.5v.5', 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z'],
  };

  let host = null;

  function hostNode() {
    if (!host) {
      host = el('div', 'toasts');
      host.setAttribute('role', 'status');
      host.setAttribute('aria-live', 'polite');
      document.body.appendChild(host);
    }
    return host;
  }

  function dismiss(toast) {
    if (toast.leaving) return;
    toast.leaving = true;
    clearTimeout(toast.timer);
    toast.node.classList.add('leaving');
    setTimeout(function () { toast.node.remove(); }, LEAVE_MS);
  }

  function show(message, opts) {
    const options = opts || {};
    const tone = ICONS[options.tone] ? options.tone : 'info';
    const container = hostNode();
    while (container.children.length >= MAX_TOASTS) container.firstChild.remove();

    const node = el('div', 'toast toast-' + tone);
    const icon = el('span', 'toast-icon');
    icon.appendChild(svg(ICONS[tone]));
    node.appendChild(icon);
    node.appendChild(el('span', 'toast-text', message));
    const close = el('button', 'toast-close');
    close.appendChild(svg(['M6 6l12 12', 'M18 6L6 18']));
    close.type = 'button';
    close.title = 'Dismiss';
    close.setAttribute('aria-label', 'Dismiss');
    node.appendChild(close);
    container.appendChild(node);

    const toast = { node: node, timer: 0, leaving: false };
    function arm() { toast.timer = setTimeout(function () { dismiss(toast); }, DURATION_MS); }
    node.addEventListener('mouseenter', function () { clearTimeout(toast.timer); });
    node.addEventListener('mouseleave', arm);
    close.addEventListener('click', function () { dismiss(toast); });
    arm();
  }

  ns.toast = { show: show };
})(window.MfgUi);
