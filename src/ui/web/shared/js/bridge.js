/**
 * Python bridge. Talks to the add-in through Fusion's palette messaging:
 *   send:    adsk.fusionSendData(action, jsonString)
 *   receive: window.fusionJavaScriptHandler.handle(action, jsonString)
 *
 * Python always replies on the same action name with an envelope
 * { ok, result, error }.
 */
(function (ns) {
  'use strict';

  const listeners = {};

  /** Register the callback that receives responses to `action`. */
  function on(action, callback) { listeners[action] = callback; }

  /** Send `action` with an object payload to Python. */
  function send(action, payload) {
    adsk.fusionSendData(action, JSON.stringify(payload || {}));
  }

  // Fusion invokes this global to deliver messages from Python.
  window.fusionJavaScriptHandler = {
    handle: function (action, data) {
      const callback = listeners[action];
      if (callback) callback(JSON.parse(data));
      return 'OK';
    },
  };

  // A button marked `data-close` closes the palette it is in (the palettes have no Close button of Fusion's own).
  document.addEventListener('click', function (event) {
    if (event.target.closest('[data-close]')) send('palette_close');
  });

  ns.bridge = { on: on, send: send };
})(window.MfgUi);
