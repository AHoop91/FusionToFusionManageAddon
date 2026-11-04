/**
 * Settings panel start-up: mounts the shared shell, wires each module and
 * loads initial state.
 */
(function (ns) {
  'use strict';

  function init() {
    // Fusion injects `adsk` asynchronously, so wait for it.
    if (typeof adsk === 'undefined') { setTimeout(init, 100); return; }

    // The page is built in the user's language, so it starts once the language has arrived.
    ns.i18n.init(start);
  }

  function start() {
    // Shared shell.
    ns.shell.mountHeader();
    ns.tabs.init();
    ns.account.init();
    ns.auth.init();

    // Settings-specific.
    ns.settings.init();
    ns.language.init();

    ns.settings.load();
    ns.auth.refresh();
  }

  init();
})(window.MfgUi);
