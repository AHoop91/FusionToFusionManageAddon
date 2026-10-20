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
    $('f-client-id').value = s.local.client_id;
    $('f-tenant').value = s.local.tenant;
    $('f-port').value = s.local.callback_port;
    $('f-scopes').value = s.local.scopes.join(' ');
    ns.workspaces.render(s);
    ns.exports.render(s);
    $('callback-url').textContent = s.callback_url;
    showHub(s.hub);
    $('wiz-callback').textContent = s.callback_url;
    savedTenant = s.local.tenant;
    hubFile = s.hub_file || null;
    renderHubFile();
    showWizard(!s.local.client_id);
    updateViews();
    if (signedInNow) checkRole(true);   // the role belongs to the active hub, which may have changed
  }

  // ---- Hub ------------------------------------------------------------------

  let hubId = '';   // the hub the form's values belong to; Python refuses a save for another

  /** Show which hub the settings are for. A different hub than before starts its first setup again. */
  function showHub(hub) {
    const name = hub && hub.name ? hub.name : 'no hub open';
    document.querySelectorAll('[data-hub-name]').forEach(function (el) { el.textContent = name; });
    if (hub && hub.id !== hubId) {
      tenantStepDone = false;
      signInAfterSave = false;
      roleState = '';   // another hub: its role is not known yet
      updateViews();
    }
    hubId = hub ? hub.id : '';
  }

  // ---- Role in the hub ------------------------------------------------------

  const ROLE_WAIT_MS = 45000;   // how long Python is given to push the answer
  const ROLE_TEXT = {
    admin: 'You are a Hub Admin of this hub.',
    member: 'You are a member of this hub, not a Hub Admin.',
    unknown: 'Your role in this hub could not be checked.',
  };
  let stopRoleWait = function () {};   // cancels the wait for the role's answer
  let roleAsked = false;   // an answer is awaited: one question at a time
  let roleState = '';      // '', 'pending', 'admin', 'member' or 'unknown' for the active hub


  /** Ask Python for the user's role in the active hub (it reads it in the background, so the answer may be `pending` first). */
  function checkRole(refresh, visible) {
    if (roleAsked) return;
    roleAsked = true;
    if (!roleState) { roleState = 'pending'; updateViews(); }   // validating, until Python answers (at once when it already knows)
    if (visible || roleState === 'pending') ns.account.renderRole('pending');   // a read the user asked for shows; a quiet re-check does not
    stopRoleWait();
    stopRoleWait = bridge.expect(ROLE_WAIT_MS, function () { onRole({ ok: true, result: { state: 'unknown' } }); });
    bridge.send('get_hub_role', refresh ? { refresh: true } : {});
  }

  /** The panel stays open between uses: ask again when it comes back into view, so a role that changed shows without restarting Fusion. */
  const ROLE_RECHECK_MS = 5000;
  let lastRoleCheck = Date.now();
  function recheckRole() {
    if (document.hidden || !signedInNow || Date.now() - lastRoleCheck < ROLE_RECHECK_MS) return;
    lastRoleCheck = Date.now();
    refreshedOnOpen = false;
    checkRole(true);
  }
  window.addEventListener('focus', recheckRole);
  document.addEventListener('visibilitychange', recheckRole);

  let roleDialog = false;   // the user asked for the role to be read again: a dialog is open until it is answered

  function onRole(r) {
    const result = r.ok ? r.result : { state: 'unknown' };
    if (result.state === 'pending') {
      return;   // only the start: Python pushes the answer when it has read it
    }
    stopRoleWait();
    roleAsked = false;
    roleState = result.state;
    ns.account.renderRole(result.state);
    updateViews();
    if (roleDialog) {
      roleDialog = false;
      if (result.state === 'unknown') ns.progress.fail('Could not check your permissions', ROLE_TEXT.unknown + ' Check your connection and try again.');
      else ns.progress.done('Permissions refreshed', ROLE_TEXT[result.state]);
    }
    // A member reads the Configuration File again each time the panel opens, so a Hub Admin's changes reach them.
    if (result.state === 'member' && hubFile && !refreshedOnOpen) { refreshedOnOpen = true; useHubConfig({}, true); }
  }

  // ---- Configuration File in the Hub (members) --------------------------------

  const USE_WAIT_MS = 60000;   // how long Python is given to push the outcome
  let stopUseWait = function () {};
  let hubFile = null;           // {name, read_at, ...} of the file this hub's settings were read from, or null
  let refreshedOnOpen = false;  // the file was read again since the panel was opened
  let usingFile = false;        // a read of the file is under way

  let readQuietly = false;      // that read is the one made when the panel opens: no dialog, only a message if it fails

  /** Show, to the member, how reading the file stands: on the prompt when they have none yet, on the file bar when they do. */
  function fileMessage(text, state) {
    [$('member-status'), $('hub-file-msg')].forEach(function (node) {
      node.hidden = !text;
      node.textContent = text;
      node.dataset.state = state || '';
    });
  }

  function whenRead(iso) {
    const when = new Date(iso);
    return isNaN(when) ? '' : 'Read ' + when.toLocaleString();
  }

  function renderHubFile() {
    $('hub-file-name').textContent = hubFile ? hubFile.name : '';
    $('hub-file-when').textContent = hubFile ? whenRead(hubFile.read_at) : '';
  }

  /** Read the Configuration File and make it this hub's settings; ``ref`` names the file, or is empty for the one already in use. */
  function useHubConfig(ref, quietly) {
    if (usingFile) return;
    usingFile = true;
    readQuietly = !!quietly;
    ['member-find', 'hub-file-update', 'hub-file-change'].forEach(function (id) { $(id).disabled = true; });
    const name = ref.name || (hubFile && hubFile.name) || 'the file';
    if (quietly) fileMessage('Reading the Configuration File...', '');
    else ns.progress.show('Reading the Configuration File', 'Reading ' + name + ' from the hub. This takes a few seconds.');
    stopUseWait();
    stopUseWait = bridge.expect(USE_WAIT_MS, function () { onUseHubConfig({ ok: false, error: 'The hub did not answer in time. Try again.' }); });
    bridge.send('use_hub_config', ref);
  }

  function onUseHubConfig(r) {
    const result = r.ok ? r.result : { pending: false, ok: false, message: r.error };
    if (result.pending) return;   // only the start: Python pushes the outcome when it is done
    stopUseWait();
    usingFile = false;
    ['member-find', 'hub-file-update', 'hub-file-change'].forEach(function (id) { $(id).disabled = false; });
    const failed = result.message || 'The Configuration File could not be read.';
    if (!result.ok) {
      if (readQuietly) fileMessage(failed, 'error'); else ns.progress.fail('Could not read the Configuration File', failed);
      return;
    }
    fileMessage('', '');
    fillSettings(result.settings);   // the file is now this hub's settings
    if (!readQuietly) ns.progress.done('Settings loaded', (result.settings.hub_file ? result.settings.hub_file.name : 'The file') + ' is now the settings of this hub. They are read-only: only a Hub Admin can change them.');
  }

  function findFile() {
    ns.hubPicker.open(document.querySelector('[data-hub-name]').textContent, function (file) { useHubConfig(file); });
  }

  function initMemberFlow() {
    bridge.on('use_hub_config', onUseHubConfig);
    bridge.on('use_hub_config_status', onUseHubConfig);
    $('member-find').addEventListener('click', findFile);
    $('hub-file-change').addEventListener('click', findFile);
    $('hub-file-update').addEventListener('click', function () { useHubConfig({}); });
  }

  // ---- Save to the Fusion Hub (Hub Admins) ------------------------------------

  const SAVE_POLL_MS = 500;
  const CONFIG_FILE_NAME = 'Fusion-Manage-Item-Management-config.json';   // the name Python stores the file under
  let hubSavePlace = '';   // where the file is being saved, for the dialog that shows how it goes

  /** Show how saving to the hub stands: the dialog's balls while it is under way, its outcome when it ends. */
  function onHubSave(r) {
    if (!hubSavePlace) return;
    const result = r.ok ? r.result : { pending: false, ok: false };
    if (result.pending) {
      setTimeout(function () { bridge.send('save_to_hub_status', {}); }, SAVE_POLL_MS);
      return;
    }
    const place = hubSavePlace;
    hubSavePlace = '';
    if (r.ok) ns.progress.done('Saved to Fusion Hub', 'The Configuration File is in ' + place + '. Members of the hub can find it there.');
    else ns.progress.fail('Could not save to Fusion Hub', r.error);
  }

  /** After a save, ask where in the hub to keep the Configuration File and store it there. */
  function saveToHub() {
    ns.hubPicker.open(document.querySelector('[data-hub-name]').textContent, function (place) {
      hubSavePlace = place.path;
      ns.progress.show('Saving to Fusion Hub', 'Storing the Configuration File in ' + place.path + '. This takes a few seconds.');
      bridge.send('save_to_hub', { project_id: place.project_id, folder_id: place.folder_id });
    }, { folder: true, hubId: hubId, title: 'Save to Fusion Hub', action: 'Save here', fileName: CONFIG_FILE_NAME });
  }

  /** Save the settings. A Hub Admin is asked, once they are saved, whether to share them with the hub too. */
  function saveClicked(source) {
    saveSource = source;
    askShareAfterSave = roleState === 'admin';
    bridge.send('save_settings', readSettings());
  }

  /** A member of the hub cannot change its settings: every form and Save is switched off. */
  function applyMemberLock(locked) {
    ['lock-connection', 'lock-workspaces', 'lock-exports'].forEach(function (id) { $(id).disabled = locked; });
    $('save-btn').disabled = locked;
    document.querySelectorAll('.lock-note').forEach(function (note) {
      note.hidden = !locked;
      if (locked) note.textContent = 'These settings come from the hub\'s Configuration File. Only a Hub Admin can change them.';
    });
  }

  /** Read the form fields into the payload Python expects. */
  function readSettings() {
    return {
      hub_id: hubId,
      mode: 'local',   // Shared Configuration is not offered for now, so saving always uses the local settings
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

  // ---- Form placement -----------------------------------------------------

  /** Move the form to the login screen (signed out) or the Connection tab. */
  function placeForm(signedIn) {
    const target = signedIn ? $('settings-slot') : $('login-settings-slot');
    if ($('conn-settings').parentNode !== target) target.appendChild($('conn-settings'));
  }

  // ---- Tenant -------------------------------------------------------------

  const TENANT_WAIT_MS = 60000;   // how long Python is given to push the outcome
  let stopTenantWait = function () {};

  /** Show the outcome of finding the tenant. A pending answer is only the start; the outcome is pushed when it is known. */
  function onTenant(r) {
    const result = r.ok ? r.result : { pending: false, ok: false, message: r.error };
    if (result.pending) return;
    stopTenantWait();
    $('f-tenant-find').disabled = $('wt-find').disabled = false;
    // The Connection tab and the first-setup tenant step share the answer.
    const failed = result.message || 'The tenant could not be found.';
    $('f-tenant-msg').hidden = false;
    $('f-tenant-msg').textContent = result.ok ? 'Found ' + result.tenant + '. Save to keep it.' : failed;
    $('wt-msg').hidden = false;
    $('wt-msg').dataset.state = result.ok ? 'ok' : 'error';
    $('wt-msg').textContent = result.ok ? 'Found tenant "' + result.tenant + '". Select Save and finish to keep it.' : failed + ' You can also enter the tenant yourself.';
    if (result.ok) {
      $('f-tenant').value = $('wt-tenant').value = result.tenant;
      $('wt-save').disabled = false;
    }
  }

  /** Ask for the tenant of the open design's Fusion Manage item; the answer arrives in ``onTenant``. */
  function findTenant() {
    $('f-tenant-find').disabled = $('wt-find').disabled = true;
    $('f-tenant-msg').hidden = true;
    $('wt-msg').hidden = false;
    $('wt-msg').dataset.state = '';
    $('wt-msg').textContent = 'Searching the open design...';
    stopTenantWait();
    stopTenantWait = bridge.expect(TENANT_WAIT_MS, function () { onTenant({ ok: false, error: 'The tenant could not be found in time. Try again.' }); });
    bridge.send('detect_tenant', {});
  }

  // ---- First setup wizard ---------------------------------------------------

  const GUIDE_URL = 'https://aps.autodesk.com/en/docs/oauth/v2/tutorials/create-app/';

  // Set when the wizard's sign-in is waiting for the Client ID to be saved.
  let signInAfterSave = false;
  let askShareAfterSave = false;   // an admin pressed Save: once the save has passed validation, they are asked about the hub

  /** The wizard replaces the sign-in card until a Client ID is saved; the automatic sign-in waits too (it would fail without one). */
  function showWizard(needed) {
    $('setup-wizard').hidden = !needed;
    $('login-card').hidden = needed;
    ns.auth.holdLogin(needed);
  }

  function updateWizard() {
    const entered = !!$('wiz-client-id').value.trim();
    $('wiz-signin').disabled = !entered;
    $('wiz-client-id').closest('.wiz-step').classList.toggle('done', entered);
  }

  /** Copy ``text`` to the clipboard; the select-and-copy way works where the clipboard API is not offered. */
  function copyText(text) {
    const box = document.createElement('textarea');
    box.value = text;
    document.body.appendChild(box);
    box.select();
    try { document.execCommand('copy'); } finally { box.remove(); }
  }

  function initWizard() {
    [$('wiz-guide'), $('conn-guide')].forEach(function (button) {
      button.addEventListener('click', function () { bridge.send('open_url', { url: GUIDE_URL }); });
    });
    $('wiz-client-id').addEventListener('input', updateWizard);
    $('wiz-copy').addEventListener('click', function () {
      copyText($('wiz-callback').textContent);
      $('wiz-copy').textContent = 'Copied';
      setTimeout(function () { $('wiz-copy').textContent = 'Copy'; }, 2000);
    });
    $('wiz-signin').addEventListener('click', function () {
      $('f-client-id').value = $('wiz-client-id').value.trim();
      signInAfterSave = true;
      saveSource = 'wiz';
      bridge.send('save_settings', readSettings());
    });
  }

  // ---- Tenant step: the last step of the first setup, once signed in ---------

  let signedInNow = false;
  let savedTenant = '';
  let tenantStepDone = false;   // a tenant has been saved: the step is not shown again until the panel is reloaded

  /**
   * What the signed-in panel shows, one thing at a time: while the user's role in the hub is checked, a loader; a member of the hub (not a
   * Hub Admin) with no Configuration File yet, the request to find it; an admin with no tenant saved yet, the tenant step; otherwise the
   * tabs, read-only for a member (who also sees which file they came from). When the check could not be made ('unknown') the panel is
   * left usable, so a failed check does not lock out an admin.
   */
  function updateViews() {
    if (savedTenant) tenantStepDone = true;
    const checking = signedInNow && roleState === 'pending';
    const member = signedInNow && roleState === 'member';
    const prompt = member && !hubFile;
    const tenant = signedInNow && !checking && !member && !tenantStepDone;
    $('role-check').hidden = !checking;
    $('member-prompt').hidden = !prompt;
    $('tenant-wizard').hidden = !tenant;
    const tabs = !(checking || prompt || tenant);
    $('settings-tabs').hidden = !tabs;
    $('settings-main').hidden = !tabs;
    $('hub-file-bar').hidden = !(member && hubFile);
    applyMemberLock(member);
  }

  function initTenantStep() {
    ns.account.onRefreshRole(function () {
      ns.account.closeCard();
      roleDialog = true;
      ns.progress.show('Checking your permissions', 'Reading your role in this hub. This takes a few seconds.');
      checkRole(true, true);
    });
    ns.auth.onChange(function (signedIn) { signedInNow = signedIn; updateViews(); if (signedIn) checkRole(); });
    bridge.on('get_hub_role', onRole);
    $('wt-tenant').addEventListener('input', function () { $('wt-save').disabled = !$('wt-tenant').value.trim(); });
    $('wt-find').addEventListener('click', findTenant);
    $('wt-save').addEventListener('click', function () {
      $('f-tenant').value = $('wt-tenant').value.trim();
      saveSource = 'wt';
      bridge.send('save_settings', readSettings());
    });
  }

  // ---- Wiring -------------------------------------------------------------

  // Id prefix of the Save button that started the last save ('save' | 'ws-save' | 'ex-save' | 'wiz' | 'wt').
  let saveSource = 'save';

  function init() {
    ns.auth.onChange(placeForm);
    ns.workspaces.init();
    initWizard();
    initTenantStep();
    initMemberFlow();
    ns.hubPicker.init();
    // The panel is only hidden when closed, so it is shown again with whatever hub was active before: read the active hub's settings again.
    // Every opening validates the user's role again, and a member's Configuration File is read again.
    bridge.on('palette_opened', function () { roleState = ''; refreshedOnOpen = false; ns.settings.load(); ns.auth.refresh(); });

    bridge.on('get_settings', function (r) {
      if (r.ok) fillSettings(r.result);
    });

    bridge.on('save_settings', function (r) {
      // Report the result on the tab whose Save button was pressed.
      const msg = $(saveSource + '-msg');
      const error = $(saveSource + '-error');
      const problems = r.ok ? (r.result.problems || []) : [{ message: r.error, where: {} }];
      ns.validation.show(error, problems);
      const signIn = signInAfterSave;
      const askShare = askShareAfterSave;
      signInAfterSave = askShareAfterSave = false;
      if (problems.length) return;
      fillSettings(r.result);
      msg.textContent = 'Saved';
      setTimeout(function () { msg.textContent = ''; }, 2000);
      if (askShare) ns.shareDialog.open(document.querySelector('[data-hub-name]').textContent, saveToHub);   // a file in the hub never holds settings that failed validation
      // Refresh sign-in state now that the connection details changed (or sign in, from the wizard).
      if (signIn) bridge.send('auth_login'); else ns.auth.refresh();
    });

    bridge.on('detect_tenant', onTenant);
    bridge.on('detect_tenant_status', onTenant);
    $('f-tenant-find').addEventListener('click', findTenant);

    $('toggle-conn').addEventListener('click', function () {
      $('login-settings-slot').hidden = !$('login-settings-slot').hidden;
    });
    // Keep the displayed callback URL in step with the port field.
    $('f-port').addEventListener('input', function () {
      $('callback-url').textContent = 'http://localhost:' + $('f-port').value + '/callback';
    });
    // Every tab saves the whole form; `prefix` says where to show the result.
    $('callback-copy').addEventListener('click', function () {
      copyText($('callback-url').textContent);
      $('callback-copy').textContent = 'Copied';
      setTimeout(function () { $('callback-copy').textContent = 'Copy'; }, 2000);
    });
    [['save-btn', 'save'], ['ws-save-btn', 'ws-save'], ['ex-save-btn', 'ex-save']].forEach(function (pair) {
      $(pair[0]).addEventListener('click', function () { saveClicked(pair[1]); });
    });
    bridge.on('save_to_hub', onHubSave);
    bridge.on('save_to_hub_status', onHubSave);
  }

  ns.settings = {
    init: init,
    apply: fillSettings,
    load: function () { bridge.send('get_settings'); },
  };
})(window.MfgUi);
