/**
 * Publish Item panel: toasts (Material "snackbars"), as ``ns.pubToast``.
 * ``show(message, opts)`` slides a short message up from the bottom of the panel and removes it after a few seconds;
 * ``opts``: ``tone`` ('success', 'error' or 'info', default 'info'), ``duration`` in ms (0 keeps it until closed),
 * ``max`` (toasts shown at once, default 3: the oldest goes first) and ``onClose`` (called once it has gone).
 * A toast stays while the pointer is over it. ``open()`` is how many are on screen.
 */
(function (ns) {
  'use strict';

  const ui = ns.pubUi;
  const el = ui.el;

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
      host = el('div', 'pub-toasts');
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
    setTimeout(function () {
      toast.node.remove();
      if (toast.onClose) toast.onClose();
    }, LEAVE_MS);
  }

  function show(message, opts) {
    const options = opts || {};
    const tone = ICONS[options.tone] ? options.tone : 'info';
    const container = hostNode();
    const max = options.max || MAX_TOASTS;
    while (container.children.length >= max) container.firstChild.remove();

    const node = el('div', 'pub-toast pub-toast-' + tone);
    const icon = el('span', 'pub-toast-icon');
    icon.appendChild(ui.svg(ICONS[tone]));
    node.appendChild(icon);
    node.appendChild(el('span', 'pub-toast-text', message));
    const close = el('button', 'pub-toast-close');
    close.appendChild(ui.svg(['M6 6l12 12', 'M18 6L6 18']));
    close.type = 'button';
    close.title = 'Dismiss';
    close.setAttribute('aria-label', 'Dismiss');
    node.appendChild(close);
    container.appendChild(node);

    const toast = { node: node, timer: 0, leaving: false, onClose: options.onClose };
    const duration = options.duration === undefined ? DURATION_MS : options.duration;
    function arm() { if (duration > 0) toast.timer = setTimeout(function () { dismiss(toast); }, duration); }
    node.addEventListener('mouseenter', function () { clearTimeout(toast.timer); });
    node.addEventListener('mouseleave', arm);
    close.addEventListener('click', function () { dismiss(toast); });
    arm();
  }

  /** How many toasts are on screen. */
  function open() { return host ? host.children.length : 0; }

  ns.pubToast = { show: show, open: open };
})(window.MfgUi);
