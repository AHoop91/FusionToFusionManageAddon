/**
 * Python bridge. Talks to the add-in through Fusion's palette messaging:
 *   send:    adsk.fusionSendData(action, jsonString)
 *   receive: window.fusionJavaScriptHandler.handle(action, jsonString)
 *
 * Python always replies on the same action name with an envelope
 * { ok, result, error }, and pushes the outcome of slow work the same way when it is done (no polling).
 */
(function (ns) {
  'use strict';

  const listeners = {};

  /** Register the callback that receives responses to `action`. */
  function on(action, callback) { listeners[action] = callback; }

  /**
   * Python pushes the outcome of slow work when it is done. A push that never comes would leave the panel waiting, so `expect` runs
   * `onTimeout` after `ms` unless the returned function is called first (when the push arrives).
   */
  function expect(ms, onTimeout) {
    const timer = setTimeout(onTimeout, ms);
    return function () { clearTimeout(timer); };
  }

  /** Send `action` with an object payload to Python. */
  function send(action, payload) {
    adsk.fusionSendData(action, JSON.stringify(payload || {}));
  }

  // Fusion invokes this global to deliver messages from Python.
  // A message that cannot be read, or a listener that throws, is logged and does not stop the next message from being delivered.
  window.fusionJavaScriptHandler = {
    handle: function (action, data) {
      const callback = listeners[action];
      if (callback) {
        try {
          callback(JSON.parse(data));
        } catch (error) {
          console.error('The panel could not handle "' + action + '":', error);
        }
      }
      return 'OK';
    },
  };

  ns.bridge = { on: on, send: send, expect: expect };
})(window.MfgUi);
