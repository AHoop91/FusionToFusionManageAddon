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
