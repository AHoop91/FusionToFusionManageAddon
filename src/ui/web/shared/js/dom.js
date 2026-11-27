/**
 * Shared namespace and DOM helper.
 *
 * Every script attaches its public API to `window.MfgUi`, so scripts stay
 * decoupled and load order (see index.html) is the only dependency.
 */
window.MfgUi = window.MfgUi || {};

/** Shorthand for document.getElementById. */
window.MfgUi.$ = function (id) { return document.getElementById(id); };

/** Create an element with a class and optional text (set with textContent, so nothing is parsed as HTML). */
window.MfgUi.el = function (tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

/** A 24x24 icon drawn from path strings; ``size`` (px) is optional, the stylesheet can size it instead. */
window.MfgUi.EXTERNAL_ICON = ['M15 3h6v6', 'M10 14L21 3', 'M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6'];   // a square with an arrow out of it, for a link that opens outside the panel

window.MfgUi.svg = function (paths, size) {
  const namespace = 'http://www.w3.org/2000/svg';
  const node = document.createElementNS(namespace, 'svg');
  node.setAttribute('viewBox', '0 0 24 24');
  node.setAttribute('aria-hidden', 'true');
  if (size) {
    node.setAttribute('width', String(size));
    node.setAttribute('height', String(size));
  }
  paths.forEach(function (d) {
    const path = document.createElementNS(namespace, 'path');
    path.setAttribute('d', d);
    node.appendChild(path);
  });
  return node;
};

/** The three bouncing balls of a wait: ``label`` is what a screen reader says; ``className`` may add to ``balls``. */
window.MfgUi.balls = function (label, className) {
  const node = window.MfgUi.el('div', className ? 'balls ' + className : 'balls');
  node.setAttribute('role', 'status');
  node.setAttribute('aria-label', label);
  for (let i = 0; i < 3; i++) node.appendChild(window.MfgUi.el('span'));
  return node;
};

/**
 * Where the icon of each tree level starts (px, by level): every level steps in by one ``slot`` (a chevron box), so a
 * chevron sits under its parent's icon. ``room`` is whether the top level has a chevron on any row, so it leaves space for it.
 */
window.MfgUi.stepIn = function (levels, room, slot) {
  const xs = [];
  levels.forEach(function (level) {
    if (xs[level] === undefined) xs[level] = level === 0 ? (room ? slot : 0) : (xs[level - 1] || 0) + slot;
  });
  return xs;
};
