/**
 * Settings panel start-up: mounts the shared shell, wires each module and
 * loads initial state.
 */
(function (ns) {
  'use strict';

  function init() {
    // Fusion injects `adsk` asynchronously, so wait for it.
    if (typeof adsk === 'undefined') { setTimeout(init, 100); return; }

    // Shared shell.
    ns.shell.mountHeader();
    ns.tabs.init();
    ns.account.init();
    ns.auth.init();

    // Settings-specific.
    ns.settings.init();

    ns.settings.load();
    ns.auth.refresh();
  }

  init();
})(window.MfgUi);
