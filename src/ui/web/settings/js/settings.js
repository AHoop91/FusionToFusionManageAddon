/**
 * Settings panel: the connection settings form.
 *
 * The form is one element that lives on the login screen while signed out
 * (so a Client ID can be entered before the first sign-in) and under the
 * Connection tab once signed in.
 */
(function (ns) {
  'use strict';

  const $ = ns.$;
  const bridge = ns.bridge;

  // ---- Form data ----------------------------------------------------------

  /** Copy a settings object from Python into the form fields. */
  function fillSettings(s) {
    const modeRadio = document.querySelector('input[name="mode"][value="' + s.mode + '"]');
    if (modeRadio) modeRadio.checked = true;
    applyLock();
    $('f-client-id').value = s.local.client_id;
    $('f-tenant').value = s.local.tenant;
    $('f-port').value = s.local.callback_port;
    $('f-scopes').value = s.local.scopes.join(' ');
    ns.workspaces.render(s);
    ns.exports.render(s);
    $('callback-url').textContent = s.callback_url;
  }

  /** Read the form fields into the payload Python expects. */
  function readSettings() {
    return {
      mode: document.querySelector('input[name="mode"]:checked').value,
      workspaces: ns.workspaces.read(),
      exports: ns.exports.read(),
      local: {
        client_id: $('f-client-id').value,
        tenant: $('f-tenant').value,
        callback_port: $('f-port').value,
        scopes: $('f-scopes').value.split(/\s+/).filter(Boolean),
      },
    };
  }

  // ---- Shared Configuration lock -------------------------------------------

  /**
   * With Shared Configuration selected the settings come from the
   * organisation, so every form is read-only and Import is disabled. The
   * fieldsets disable their contents; Export stays available.
   */
  function applyLock() {
    const checked = document.querySelector('input[name="mode"]:checked');
    const locked = !!checked && checked.value === 'company';
    ['conn-settings', 'lock-workspaces', 'lock-exports'].forEach(function (id) { $(id).disabled = locked; });
    $('import-btn').disabled = locked;
    document.querySelectorAll('.lock-note').forEach(function (note) { note.hidden = !locked; });
  }

  // ---- Form placement -----------------------------------------------------

  /** Move the form to the login screen (signed out) or the Connection tab. */
  function placeForm(signedIn) {
    const target = signedIn ? $('settings-slot') : $('login-settings-slot');
    if ($('conn-settings').parentNode !== target) target.appendChild($('conn-settings'));
  }

  // ---- Tenant -------------------------------------------------------------

  const TENANT_POLL_MS = 500;

  /** Show the outcome of finding the tenant; a pending answer is asked for again shortly. */
  function onTenant(r) {
    const result = r.ok ? r.result : { pending: false, ok: false, message: r.error };
    const msg = $('f-tenant-msg');
    if (result.pending) {
      setTimeout(function () { bridge.send('detect_tenant_status', {}); }, TENANT_POLL_MS);
      return;
    }
    $('f-tenant-find').disabled = false;
    msg.hidden = false;
    if (result.ok) {
      $('f-tenant').value = result.tenant;
      msg.textContent = 'Found ' + result.tenant + '. Save to keep it.';
    } else {
      msg.textContent = result.message || 'The tenant could not be found.';
    }
  }

  // ---- Wiring -------------------------------------------------------------

  // Id prefix of the Save button that started the last save ('save' | 'ws-save' | 'gen-save').
  let saveSource = 'save';

  function init() {
    ns.auth.onChange(placeForm);
    document.querySelectorAll('input[name="mode"]').forEach(function (radio) {
      radio.addEventListener('change', applyLock);
    });
    ns.workspaces.init();

    bridge.on('get_settings', function (r) {
      if (!r.ok) return;
      fillSettings(r.result);
      // First run: nothing to sign in with yet, so reveal the form.
      if (!r.result.local.client_id) $('login-settings-slot').hidden = false;
    });

    bridge.on('save_settings', function (r) {
      // Report the result on the tab whose Save button was pressed.
      const msg = $(saveSource + '-msg');
      const error = $(saveSource + '-error');
      error.hidden = r.ok;
      if (!r.ok) { error.textContent = r.error; return; }
      fillSettings(r.result);
      msg.textContent = 'Saved';
      setTimeout(function () { msg.textContent = ''; }, 2000);
      // Refresh sign-in state now that the connection details changed.
      ns.auth.refresh();
    });

    bridge.on('detect_tenant', onTenant);
    bridge.on('detect_tenant_status', onTenant);
    $('f-tenant-find').addEventListener('click', function () {
      $('f-tenant-find').disabled = true;
      $('f-tenant-msg').hidden = true;
      bridge.send('detect_tenant', {});
    });

    $('toggle-conn').addEventListener('click', function () {
      $('login-settings-slot').hidden = !$('login-settings-slot').hidden;
    });
    // Keep the displayed callback URL in step with the port field.
    $('f-port').addEventListener('input', function () {
      $('callback-url').textContent = 'http://localhost:' + $('f-port').value + '/callback';
    });
    // Every tab saves the whole form; `prefix` says where to show the result.
    [['save-btn', 'save'], ['ws-save-btn', 'ws-save'], ['ex-save-btn', 'ex-save'], ['gen-save-btn', 'gen-save']].forEach(function (pair) {
      $(pair[0]).addEventListener('click', function () {
        saveSource = pair[1];
        bridge.send('save_settings', readSettings());
      });
    });
  }

  ns.settings = {
    init: init,
    apply: fillSettings,
    load: function () { bridge.send('get_settings'); },
  };
})(window.MfgUi);
