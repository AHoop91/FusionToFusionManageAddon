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
