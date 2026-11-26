// Runs inside the browser page (run.mjs wraps this function in parentheses and calls it with the files). It stands in for the few things the test
// files ask of Node: ``node:test``, ``node:assert``, ``fs``, ``path``, and ``require`` itself, over the files run.mjs sent. Anything a test asks for
// that is not here throws, so a test never passes on a stand-in that does nothing.
async function runSuite(payload) {
  'use strict';
  const files = payload.files;   // posix path under the repository -> text
  const TIMEOUT = payload.timeout;
  const SETTLE = 20;   // ms a test is given after it returns for the error of a timer or a promise to show: one that comes later is not seen

  // ---- path and fs, over the files that were sent
  const normalize = (p) => {
    const out = [];
    p.split('/').forEach((part) => { if (part === '..') out.pop(); else if (part && part !== '.') out.push(part); });
    return out.join('/');
  };
  const path = { join: (...parts) => normalize(parts.join('/')), dirname: (p) => normalize(p).split('/').slice(0, -1).join('/') };
  const fs = {
    readFileSync(p) {
      const key = normalize(p);
      if (!Object.prototype.hasOwnProperty.call(files, key)) throw new Error('ENOENT: ' + key + ' was not sent to the browser (see collect() in run.mjs)');
      return files[key];
    },
  };
  const vm = { createContext() { throw new Error('vm is not available in the browser: use a page (browser/window.js)'); } };

  // ---- node:assert, as far as the tests use it
  class AssertionError extends Error {}
  const fail = (message, detail) => { throw new AssertionError(message instanceof Error ? message.message : (message ? message + ' (' + detail + ')' : detail)); };
  const show = (v) => { try { if (v instanceof Error) return String(v); if (v && typeof v.nodeType === 'number') return v.outerHTML || String(v); return typeof v === 'string' ? JSON.stringify(v) : typeof v === 'function' ? String(v) : JSON.stringify(v); } catch (e) { return String(v); } };
  const tag = (v) => Object.prototype.toString.call(v);
  const kind = (v) => { const proto = Object.getPrototypeOf(v); return proto === null ? 'null' : proto.constructor && proto.constructor.name; };   // by name: a page's Array is not this page's Array
  function same(a, b) {   // strict: Object.is for values, the kind and own enumerable keys for objects
    if (Object.is(a, b)) return true;
    if (typeof a !== 'object' || typeof b !== 'object' || a === null || b === null || tag(a) !== tag(b) || kind(a) !== kind(b)) return false;
    if (typeof a.nodeType === 'number') return false;   // two nodes are equal only when they are the one node (Object.is, above)
    if (a instanceof Date) return a.getTime() === b.getTime();
    if (tag(a) === '[object Error]') return a.name === b.name && a.message === b.message;
    if (['[object String]', '[object Number]', '[object Boolean]'].includes(tag(a))) return Object.is(a.valueOf(), b.valueOf());
    if (a instanceof RegExp) return String(a) === String(b);
    if (tag(a) === '[object Map]') return a.size === b.size && [...a].every(([k, v]) => b.has(k) && same(v, b.get(k)));
    if (tag(a) === '[object Set]') return a.size === b.size && [...a].every((v) => b.has(v));
    const ka = Object.keys(a);
    const kb = Object.keys(b);
    return ka.length === kb.length && ka.every((k) => Object.prototype.hasOwnProperty.call(b, k) && same(a[k], b[k]));
  }
  const assert = {
    AssertionError: AssertionError,
    ok: (value, message) => { if (!value) fail(message, 'expected a truthy value, got ' + show(value)); },
    strictEqual: (a, b, message) => { if (!Object.is(a, b)) fail(message, 'expected ' + show(b) + ', got ' + show(a)); },
    notStrictEqual: (a, b, message) => { if (Object.is(a, b)) fail(message, 'expected anything but ' + show(b)); },
    deepStrictEqual: (a, b, message) => { if (!same(a, b)) fail(message, 'expected ' + show(b) + ', got ' + show(a)); },
    match: (text, re, message) => { if (typeof text !== 'string' || !re.test(text)) fail(message, show(text) + ' does not match ' + re); },
    doesNotMatch: (text, re, message) => { if (typeof text !== 'string' || re.test(text)) fail(message, show(text) + (typeof text === 'string' ? ' matches ' : ' is not a string, so it cannot be tested against ') + re); },
    fail: (message) => fail(message, 'failed'),
  };

  // ---- node:test: tests are collected as the files load, then run one at a time
  let current = null;   // the file being loaded, for naming its tests
  const collected = [];
  const test = (name, options, fn) => {
    if (typeof options === 'function') { fn = options; options = {}; }
    Object.keys(options || {}).forEach((key) => { if (key !== 'skip') throw new Error('test(' + show(name) + '): the option ' + key + ' is not supported by the browser runner'); });
    collected.push({ file: current, name: name, fn: fn, skip: options && options.skip });
  };

  // ---- require, over the files sent
  const builtins = { 'node:test': test, 'node:assert': assert, assert: assert, fs: fs, path: path, vm: vm };
  const cache = {};
  function load(key) {
    if (cache[key]) return cache[key].exports;
    if (!Object.prototype.hasOwnProperty.call(files, key)) throw new Error('Cannot find ' + key + ' among the files sent to the browser (see collect() in run.mjs)');
    const module = { exports: {} };
    cache[key] = module;
    const dir = path.dirname(key);
    try {
      new Function('require', 'module', 'exports', '__dirname', '__filename', files[key] + '\n//# sourceURL=' + key)(requireFrom(dir), module, module.exports, dir, key);
    } catch (error) { delete cache[key]; throw error; }   // a module that threw is not kept half made for the next file to find
    return module.exports;
  }
  function requireFrom(dir) {
    return (name) => {
      if (Object.prototype.hasOwnProperty.call(builtins, name)) return builtins[name];
      if (!name.startsWith('.')) throw new Error('require(' + show(name) + '): nothing by that name in the browser runner');
      const base = path.join(dir, name);
      return load(Object.prototype.hasOwnProperty.call(files, base) ? base : base + '.js');
    };
  }

  // ---- run
  window.__mfgPageErrors = [];   // the errors of this page and of the pages of the tests (window.js)
  window.addEventListener('error', (event) => window.__mfgPageErrors.push(event.error || new Error(event.message)));
  window.addEventListener('unhandledrejection', (event) => window.__mfgPageErrors.push(event.reason));
  const loadErrors = [];
  payload.entries.forEach((entry) => {
    current = entry;
    const before = collected.length;
    try { load(entry); } catch (error) { loadErrors.push({ file: entry, error: String(error && error.stack || error) }); return; }
    if (collected.length === before) loadErrors.push({ file: entry, error: 'the file loaded and registered no test' });
  });

  const results = [];
  let timedOut = null;   // a test that ran out of time cannot be stopped, so nothing else is run beside what it leaves going
  for (const t of collected) {
    if (timedOut) { results.push({ file: t.file, name: t.name, status: 'fail', ms: 0, error: 'not run: "' + timedOut + '" ran out of time and could not be stopped' }); continue; }
    const started = performance.now();
    const outcome = { file: t.file, name: t.name, status: 'pass', ms: 0, error: '' };
    window.__mfgPageErrors.length = 0;
    localStorage.clear(); sessionStorage.clear();   // every page of the tests shares one origin: a test starts with the storage empty
    if (t.skip) outcome.status = 'skip';
    else {
      let timer;
      try {
        await Promise.race([
          Promise.resolve().then(() => t.fn()),
          new Promise((resolve, reject) => { timer = setTimeout(() => reject(new Error('the test took more than ' + TIMEOUT + ' ms')), TIMEOUT); }),
        ]);
        await new Promise((resolve) => setTimeout(resolve, SETTLE));   // let a late error or an unhandled rejection of a page be reported
        if (window.__mfgPageErrors.length) throw new Error('the page threw: ' + window.__mfgPageErrors.map((e) => String(e && e.stack || e)).join('\n'));
      } catch (error) {
        if (/^the test took more than/.test(error.message)) timedOut = t.name;
        outcome.status = 'fail';
        outcome.error = String(error && error.stack || error);
      } finally { clearTimeout(timer); }
    }
    document.querySelectorAll('iframe').forEach((frame) => frame.remove());
    outcome.ms = Math.round(performance.now() - started);
    results.push(outcome);
  }
  return { results: results, loadErrors: loadErrors };
}
