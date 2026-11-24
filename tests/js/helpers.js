// Loads the Publish panel's scripts the way the page does, into a window of our own, so they can be tested without Fusion.
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const WEB = path.join(__dirname, '..', '..', 'src', 'ui', 'web');
const PUBLISH_HTML = path.join(WEB, 'publish', 'index.html');

/** A stand-in for shared/js/i18n.js that is already in English: the texts are those of resources/languages/en.json, as the add-in ships them. */
function englishI18n() {
  const strings = JSON.parse(fs.readFileSync(path.join(WEB, '..', '..', '..', 'resources', 'languages', 'en.json'), 'utf8')).strings;
  const t = function (key, params) {
    const text = Object.prototype.hasOwnProperty.call(strings, key) ? strings[key] : key;
    return params ? text.replace(/\{(\w+)\}/g, function (all, name) { return params[name] !== undefined ? String(params[name]) : all; }) : text;
  };
  return { gate: function () { return true; }, init: function (start) { start(); }, t: t, apply: function () {}, use: function () {}, state: function () { return {}; }, onRefused: function () {} };
}

/** The scripts of the Publish page, in the order the page loads them, as paths under src/ui/web/publish. */
function pageScripts() {
  return [...fs.readFileSync(PUBLISH_HTML, 'utf8').matchAll(/<script src="([^"]+)"/g)].map(function (m) { return m[1]; });
}

/** Run the script ``src`` (as written in index.html) in ``window``, a vm context or a jsdom window. */
function run(window, src) {
  const code = fs.readFileSync(path.join(WEB, 'publish', src), 'utf8');
  if (typeof window.eval === 'function') window.eval(code);
  else vm.runInContext(code, window, { filename: src });
}

/** A bare window with ``MfgUi`` and the scripts of the Bill of Materials data (no DOM needed) loaded. */
function dataWindow() {
  const window = vm.createContext({ console: console });
  window.window = window;
  window.MfgUi = {};
  pageScripts().filter(function (src) { return /\/(bom-(tree|model|plan|scope)|mbom-(structure|plan))\.js$/.test(src); }).forEach(function (src) { run(window, src); });
  return window.MfgUi;
}

module.exports = { englishI18n: englishI18n, WEB: WEB, PUBLISH_HTML: PUBLISH_HTML, pageScripts: pageScripts, run: run, dataWindow: dataWindow };
