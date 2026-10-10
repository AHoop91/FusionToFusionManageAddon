/**
 * The window of a STEP upload started from the right-click menu: asks Python how far it has got (``step_status``)
 * and shows it on the shared card. Python closes the window when the upload ends.
 */
(function (ns) {
  'use strict';

  const bridge = ns.bridge;
  const POLL_MS = 250;

  function poll() { bridge.send('step_status'); }

  (function start() {
    // Fusion injects `adsk` asynchronously, so wait for it.
    if (typeof adsk === 'undefined') { setTimeout(start, 100); return; }
    const card = ns.stepProgress.mount(document.getElementById('step-card'));
    bridge.on('step_status', function (r) {
      if (r.ok && r.result) card.show(r.result);
      setTimeout(poll, POLL_MS);
    });
    poll();
  })();
})(window.MfgUi);
