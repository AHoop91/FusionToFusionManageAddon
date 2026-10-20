/**
 * The window of an upload started from the right-click menu or the ribbon: asks Python how far it has got (``upload_status``)
 * and shows it on the shared card. Python closes the window when the upload ends.
 */
(function (ns) {
  'use strict';

  const bridge = ns.bridge;
  const POLL_MS = 2000;   // Python pushes every change of the status; this only asks now and then, in case a push is missed
  const ready = document.getElementById('getting-ready');   // the spinner shown until the first status arrives
  let timer = 0;

  function poll() { bridge.send('upload_status'); }

  (function start() {
    // Fusion injects `adsk` asynchronously, so wait for it.
    if (typeof adsk === 'undefined') { setTimeout(start, 100); return; }
    const card = ns.uploadProgress.mount(document.getElementById('upload-card'));
    bridge.on('upload_status', function (r) {
      if (r.ok && r.result && r.result.active) {
        card.show(r.result);
        ready.remove();   // the card has something to show now
      }
      clearTimeout(timer);
      timer = setTimeout(poll, POLL_MS);
    });
    poll();
  })();
})(window.MfgUi);
