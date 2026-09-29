/**
 * Shared namespace and DOM helper.
 *
 * Every script attaches its public API to `window.MfgUi`, so scripts stay
 * decoupled and load order (see index.html) is the only dependency.
 */
window.MfgUi = window.MfgUi || {};

/** Shorthand for document.getElementById. */
window.MfgUi.$ = function (id) { return document.getElementById(id); };
