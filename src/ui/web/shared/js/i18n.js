/**
 * The panel's own wording, in the language the user chose.
 *
 * Python holds the language files (see core/i18n.py) and answers `get_language` with the language in use and all of its strings. A page
 * starts through `MfgUi.i18n.init(start)`, so what it builds is built in that language. Only the add-in's own wording goes through here:
 * what Fusion Manage and Fusion return (names, field values, picklists, a server's error) is shown as it came.
 *
 * Fixed text in a page's HTML:
 *   data-i18n="key"                      sets the text of the element
 *   data-i18n-html="key"                 the same, where the text has <b>, <strong>, <em> or <code> (nothing else is read as markup)
 *   data-i18n-attr="title:key;alt:key"   sets those attributes
 * The page keeps its English text in the HTML, which shows until the language arrives (and is what a page shows without one).
 * Text a script builds uses `t(key, {name: value})`; `{name}` in the text is replaced by the value.
 */
(function (ns) {
  'use strict';

  const bridge = ns.bridge;
  const WAIT_MS = 4000;   // a language that does not arrive leaves the page in its HTML's English
  const TAB_KEY = 'mfg.tab';   // where a page that loads again in a new language leaves the tab that was open
  const MARKUP = /(<\/?(?:b|strong|em|code)>)/;

  let strings = {};
  let state = { code: 'en', languages: [], user_dir: '', shipped_dir: '', restart: false, invalid: [] };
  let onRefused = function () {};   // told when Python will not use the language that was chosen
  let reloading = false;
  let ready = false;   // the language has arrived (or the wait for it is over)
  let loading = false;

  /** The text called `key` in the language in use, with `{name}` replaced from `params`. A key nothing has is answered as itself. */
  function t(key, params) {
    const text = Object.prototype.hasOwnProperty.call(strings, key) ? strings[key] : key;
    return params ? text.replace(/\{(\w+)\}/g, function (all, name) { return params[name] !== undefined ? String(params[name]) : all; }) : text;
  }

  /** Put `text` in `node`, reading <b>, <strong>, <em> and <code> as markup. Built as nodes, so nothing else in it is ever parsed. */
  function setMarkup(node, text) {
    node.textContent = '';
    let open = node;
    text.split(MARKUP).forEach(function (part) {
      const tag = /^<(\/?)(b|strong|em|code)>$/.exec(part);
      if (!tag) { if (part) open.appendChild(document.createTextNode(part)); return; }
      if (tag[1]) { if (open !== node) open = open.parentNode; return; }
      const child = document.createElement(tag[2]);
      open.appendChild(child);
      open = child;
    });
  }

  /** Translate the fixed text under `root` (the whole page when omitted). */
  function apply(root) {
    const scope = root || document;
    scope.querySelectorAll('[data-i18n]').forEach(function (node) { node.textContent = t(node.getAttribute('data-i18n')); });
    scope.querySelectorAll('[data-i18n-html]').forEach(function (node) { setMarkup(node, t(node.getAttribute('data-i18n-html'))); });
    scope.querySelectorAll('[data-i18n-attr]').forEach(function (node) {
      node.getAttribute('data-i18n-attr').split(';').forEach(function (pair) {
        const at = pair.indexOf(':');
        if (at > 0) node.setAttribute(pair.slice(0, at).trim(), t(pair.slice(at + 1).trim()));
      });
    });
  }

  /** Use `result` (what `get_language` answers) and translate the page. */
  function use(result) {
    strings = result.strings || {};
    state = { code: result.code || 'en', languages: result.languages || [], user_dir: result.user_dir || '', shipped_dir: result.shipped_dir || '', restart: !!result.restart, invalid: result.invalid || [] };
    document.documentElement.lang = state.code;
    apply();
  }

  /** Load this page again, once, in the language now in use. The tab that is open is kept for the page to open again (see `tabs.js`). */
  function reload() {
    if (reloading) return;
    reloading = true;
    const open = document.querySelector('.tabs .tab.active');
    try { if (open) window.sessionStorage.setItem(TAB_KEY, open.dataset.tab); } catch (e) { /* no storage: the first tab opens, as for any new page */ }
    window.location.reload();
  }

  /** The tab that was open when this page loaded itself again in a new language (once: later reads find none), or '' for a page that did not. */
  function takeOpenTab() {
    try {
      const tab = window.sessionStorage.getItem(TAB_KEY) || '';
      window.sessionStorage.removeItem(TAB_KEY);
      return tab;
    } catch (e) { return ''; }
  }

  /** Ask for the language, translate the page, then run `start`. `start` runs once, also when no answer comes. */
  function init(start) {
    let started = false;
    function begin() { if (!started) { started = true; ready = true; start(); } }
    const stop = bridge.expect(WAIT_MS, begin);
    bridge.on('get_language', function (r) {
      stop();
      if (r.ok) use(r.result);
      begin();
    });
    bridge.on('set_language', function (r) { if (r.ok) reload(); else onRefused(r.error); });
    bridge.on('language_changed', reload);
    bridge.send('get_language');
  }

  /**
   * For a page whose `start` waits for Fusion's `adsk` and may run more than once: `if (!ns.i18n.gate(start)) return;` after that wait.
   * It answers true once the language is in; until then it asks for it, and runs `start` again when it has arrived.
   */
  function gate(start) {
    if (ready) return true;
    if (!loading) { loading = true; init(start); }
    return false;
  }

  ns.i18n = {
    init: init,
    gate: gate,
    t: t,
    apply: apply,
    use: use,
    takeOpenTab: takeOpenTab,
    set: function (code) { bridge.send('set_language', { code: code }); },
    state: function () { return state; },
    onRefused: function (callback) { onRefused = callback; },
  };
})(window.MfgUi);
