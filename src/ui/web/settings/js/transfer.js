/**
 * Export / Import of the configuration file (General tab).
 *
 * Python opens Fusion's own file dialogs and does the file work; this module
 * only triggers the actions and reports the outcome. After an export it offers to follow the file as the Shared Configuration.
 */
(function (ns) {
  'use strict';

  const $ = ns.$;
  const bridge = ns.bridge;

  /** Show a status line (success) or an error under the buttons. */
  function report(message, isError) {
    $('transfer-error').hidden = !isError;
    $('transfer-error').textContent = isError ? message : '';
    $('transfer-msg').textContent = isError ? '' : message;
  }

  function fileName(path) { return path.split(/[\/]/).pop(); }

  function init() {
    bridge.on('export_config', function (r) {
      if (!r.ok) return report(r.error, true);
      report(r.result.cancelled ? '' : 'Exported to ' + fileName(r.result.path));
      if (r.result.offer_shared) {
        ns.info.shareDialog(r.result.path, function () { bridge.send('use_shared_config', { path: r.result.path }); });
      }
    });

    bridge.on('use_shared_config', function (r) {
      if (!r.ok) return report(r.error, true);
      ns.settings.apply(r.result.settings);
      ns.auth.refresh();
      report('Now using ' + fileName(r.result.path) + ' as the Shared Configuration');
    });

    bridge.on('import_config', function (r) {
      if (!r.ok) return report(r.error, true);
      if (r.result.cancelled) return report('');
      // Refill every form from the imported settings and re-check sign-in.
      ns.settings.apply(r.result.settings);
      ns.auth.refresh();
      report('Imported ' + fileName(r.result.path));
    });

    $('export-btn').addEventListener('click', function () { report(''); bridge.send('export_config'); });
    $('import-btn').addEventListener('click', function () { report(''); bridge.send('import_config'); });
  }

  ns.transfer = { init: init };
})(window.MfgUi);
