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
  const t = ns.i18n.t;

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
    // First setup: the hub's Configuration File is looked for before anything is asked. Fusion is signed in, so this needs no Client ID.
    if (!s.local.client_id && !hubFile && s.hub && !fileOffered) { fileOffered = true; offerFile(); }
    updateViews();
    if (signedInNow) checkRole(true);   // the role belongs to the active hub, which may have changed
  }

  // ---- Hub ------------------------------------------------------------------

  let hubId = '';   // the hub the form's values belong to; Python refuses a save for another

  /** Show which hub the settings are for. A different hub than before starts its first setup again. */
  function showHub(hub) {
    const name = hub && hub.name ? hub.name : t('settings.no_hub');
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

  /** What the user's role in the hub is, in a sentence. */
  function roleText(state) {
    switch (state) {
      case 'admin': return t('settings.role_admin');
      case 'member': return t('settings.role_member');
      default: return t('settings.role_unknown');
    }
  }
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
    if (firstRun) firstRunRole(result.state);
    ns.account.renderRole(result.state);
    updateViews();
    ns.language.render();   // only a Hub Admin is offered to add a language
    if (roleDialog) {
      roleDialog = false;
      if (result.state === 'unknown') ns.progress.fail(t('settings.role_failed_title'), t('settings.role_failed_text'));
      else ns.progress.done(t('settings.role_refreshed'), roleText(result.state));
    }
  }

  // ---- Configuration File in the Hub (members) --------------------------------

  const USE_WAIT_MS = 60000;   // how long Python is given to push the outcome
  let stopUseWait = function () {};
  let hubFile = null;           // {name, project_name, modified, modified_by, version, read_at, ...} of the file this hub's settings were read from, or null
  let usingFile = false;        // a read of the file is under way
  let fileOffered = false;      // the picker was opened by itself since the panel was opened: it is not forced open again

  function whenText(iso) {
    const when = new Date(iso);
    return iso && !isNaN(when) ? when.toLocaleString() : '';
  }

  /** Put `children` in `node`, in place of what it held. */
  function fill(node, children) {
    node.textContent = '';
    children.forEach(function (child) { node.appendChild(child); });
  }

  const FILE_ICON = ['M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z', 'M14 3v5h5'];
  const REFRESH_ICON = ['M4 12a8 8 0 0 1 14-5.3L20 9', 'M20 4v5h-5', 'M20 12a8 8 0 0 1-14 5.3L4 15', 'M4 20v-5h5'];
  const STATUS_ICONS = {
    current: ['M5 13l4 4L19 7'],
    updated: REFRESH_ICON,
    unknown: ['M12 8v5', 'M12 17h.01', 'M10.3 3.9L2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z'],
    checking: REFRESH_ICON,
  };

  /** What the Configuration tab says about whether the file is the one in the hub: `state` is current, updated, unknown or checking. */
  function setFileStatus(state, title, sub) {
    $('cfg-status').dataset.state = state;
    fill($('cfg-icon'), [ns.svg(STATUS_ICONS[state], 18)]);
    $('cfg-status-title').textContent = title;
    $('cfg-status-sub').textContent = sub || '';
  }

  function renderHubFile() {
    const shown = hubFile || {};
    $('hub-file-name').textContent = shown.name || '';
    $('hub-file-place').textContent = shown.project_name ? t('settings.in_project', { name: shown.project_name }) : '';
    $('hub-file-modified').textContent = whenText(shown.modified) || '-';
    $('hub-file-by').textContent = shown.modified_by || '-';
    $('hub-file-version').textContent = shown.version || '-';
    $('hub-file-read').textContent = whenText(shown.read_at) || '-';
    fill($('cfg-file-icon'), [ns.svg(FILE_ICON, 20)]);
    if (hubFile && $('cfg-status').dataset.state === 'current' && !$('cfg-status-sub').textContent) setFileStatus('current', t('settings.up_to_date'), t('settings.read_at', { when: whenText(hubFile.read_at) }));
  }

  // ---- Keeping up with the Hub Admin's changes -----------------------------------

  const CHECK_WAIT_MS = 60000;
  let stopCheckWait = function () {};
  let checkingFile = false;

  /** Ask Python whether the file in the hub is still the one the settings came from; if not it reads it again. */
  function checkFile() {
    if (checkingFile || !hubFile) return;
    checkingFile = true;
    $('cfg-check').disabled = true;
    setFileStatus('checking', t('settings.checking'), '');
    stopCheckWait();
    stopCheckWait = bridge.expect(CHECK_WAIT_MS, function () { onFileChecked({ ok: false, error: t('settings.hub_timeout') }); });
    bridge.send('check_hub_file', {});
  }

  /** The outcome of a look at the file, asked for by the panel or made by Python when the add-in starts (which pushes it, panel open or not). */
  function onFileChecked(r) {
    const result = r.ok ? r.result : { state: 'unknown', message: r.error };
    if (result.pending) return;
    stopCheckWait();
    checkingFile = false;
    $('cfg-check').disabled = false;
    const checked = whenText(result.checked_at);
    if (result.state === 'updated') {
      fillSettings(result.settings);   // the Hub Admin changed the file: these are the settings now
      setFileStatus('updated', t('settings.updated_latest'), result.by ? t('settings.changed_it_read', { name: result.by, when: checked }) : t('settings.read_at', { when: checked }));
    } else if (result.state === 'current') {
      setFileStatus('current', t('settings.up_to_date'), t('settings.checked_at', { when: checked }));
    } else if (result.state === 'unknown') {
      setFileStatus('unknown', t('settings.check_failed'), result.message || t('settings.try_again_moment'));
    } else {
      renderHubFile();
    }
  }

  /** Switch off (or on) every button that starts or changes the read of a Configuration File, while one is read. */
  function setFileButtons(disabled) {
    ['member-find', 'wiz-file-find', 'cfg-check', 'hub-file-change'].forEach(function (id) { $(id).disabled = disabled; });
  }

  /** Read the Configuration File ``file`` (``{project_id, item_id, name}``) and make it this hub's settings. */
  function useHubConfig(file) {
    if (usingFile) return;
    usingFile = true;
    setFileButtons(true);
    ns.progress.show(t('settings.reading_title'), t('settings.reading_text', { name: file.name || t('settings.the_file') }));
    stopUseWait();
    stopUseWait = bridge.expect(USE_WAIT_MS, function () { onUseHubConfig({ ok: false, error: t('settings.hub_timeout_retry') }); });
    bridge.send('use_hub_config', file);
  }

  function onUseHubConfig(r) {
    const result = r.ok ? r.result : { pending: false, ok: false, message: r.error };
    if (result.pending) return;   // only the start: Python pushes the outcome when it is done
    stopUseWait();
    usingFile = false;
    setFileButtons(false);
    if (!result.ok) {
      ns.progress.fail(t('settings.read_failed_title'), result.message || t('settings.read_failed_text'));
      if (!hubFile) { readFailed = true; showWizard(wizardNeeded); }
      return;
    }
    readFailed = false;
    fillSettings(result.settings);   // the file is now this hub's settings
    if (hubFile) setFileStatus('current', t('settings.up_to_date'), t('settings.read_at', { when: whenText(hubFile.read_at) }));
    ns.progress.done(t('settings.loaded_title'), t('settings.loaded_text', { name: hubFile ? hubFile.name : t('settings.the_file_cap') }));
  }

  function findFile() {
    ns.hubPicker.open(document.querySelector('[data-hub-name]').textContent, function (file) { useHubConfig(file); });
  }

  function initMemberFlow() {
    bridge.on('use_hub_config', onUseHubConfig);
    bridge.on('use_hub_config_status', onUseHubConfig);
    $('member-find').addEventListener('click', findFile);
    $('wiz-file-find').addEventListener('click', findFile);
    $('first-find').addEventListener('click', openMemberPicker);
    $('hub-file-change').addEventListener('click', findFile);
    $('cfg-check').addEventListener('click', checkFile);
    bridge.on('check_hub_file', onFileChecked);
    bridge.on('check_hub_file_status', onFileChecked);
    bridge.on('hub_file_checked', onFileChecked);
  }

  // ---- Save to the Fusion Hub (Hub Admins) ------------------------------------

  const SAVE_POLL_MS = 500;
  const CONFIG_FILE_NAME = 'Fusion-Manage-Item-Management-config.json';   // the name Python stores the file under
  let hubSavePlace = '';   // where the file is being saved, for the dialog that shows how it goes
  const TAB_SAVES = ['save', 'ws-save', 'ex-save'];   // id prefixes of the tabs' Save buttons, as against the first-setup steps

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
    if (r.ok) ns.progress.done(t('settings.saved_hub_title'), t('settings.saved_hub_text', { place: place }));
    else ns.progress.fail(t('settings.save_hub_failed'), r.error);
    ns.language.settled();   // a language chosen with Save & Publish is applied once the file is in the hub
  }

  /** After a save, ask where in the hub to keep the Configuration File and store it there. */
  function saveToHub() {
    ns.hubPicker.open(document.querySelector('[data-hub-name]').textContent, function (place) {
      hubSavePlace = place.path;
      ns.progress.show(t('settings.saving_hub_title'), t('settings.saving_hub_text', { path: place.path }));
      bridge.send('save_to_hub', { project_id: place.project_id, folder_id: place.folder_id });
    }, { folder: true, hubId: hubId, title: t('settings.save_hub_title'), action: t('settings.save_here'), fileName: CONFIG_FILE_NAME });
  }

  /** Save the settings. With ``publish`` (Hub Admins only), once they are saved the Configuration File is stored in the hub too. */
  function saveClicked(source, publish) {
    if (publish && roleState !== 'admin') return;
    saveSource = source;
    publishAfterSave = publish;
    bridge.send('save_settings', readSettings());
  }

  /** A member of the hub cannot change its settings: every form and Save is switched off. */
  function applyMemberLock(locked) {
    ['lock-connection', 'lock-workspaces', 'lock-exports'].forEach(function (id) { $(id).disabled = locked; });
    $('save-btn').disabled = locked;
    $('f-client-id').type = locked ? 'password' : 'text';   // a member does not set up the sign-in, so the Client ID is not shown to them
    ns.workspaces.setViewOnly(locked);   // the Item Workspace tab shows what the file defines, and checks nothing
    document.querySelectorAll('.lock-note').forEach(function (note) {
      note.hidden = !locked;
      if (locked) note.textContent = t('settings.lock_member');
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
    const failed = result.message || t('settings.tenant_not_found');
    $('f-tenant-msg').hidden = false;
    $('f-tenant-msg').textContent = result.ok ? t('settings.tenant_found', { tenant: result.tenant }) : failed;
    $('wt-msg').hidden = false;
    $('wt-msg').dataset.state = result.ok ? 'ok' : 'error';
    $('wt-msg').textContent = result.ok ? t('settings.tenant_found_wizard', { tenant: result.tenant }) : t('settings.tenant_failed_wizard', { message: failed });
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
    $('wt-msg').textContent = t('settings.tenant_searching');
    stopTenantWait();
    stopTenantWait = bridge.expect(TENANT_WAIT_MS, function () { onTenant({ ok: false, error: t('settings.tenant_timeout') }); });
    bridge.send('detect_tenant', {});
  }

  // ---- First setup wizard ---------------------------------------------------

  const GUIDE_URL = 'https://aps.autodesk.com/en/docs/oauth/v2/tutorials/create-app/';

  // Set when the wizard's sign-in is waiting for the Client ID to be saved.
  let signInAfterSave = false;
  let publishAfterSave = false;   // an admin pressed Save & Publish: once the save has passed validation, the file goes to the hub

  /**
   * First setup, until a Client ID is saved. A Hub Admin gets the wizard; anyone else is asked to find the hub's Configuration File, and
   * never sees the wizard. Neither shows before the role is known. The automatic sign-in waits too (it would fail without a Client ID).
   */
  let wizardNeeded = false;
  let readFailed = false;   // a member's read of the file failed: only then is the request to find it shown, never behind the picker
  function showWizard(needed) {
    wizardNeeded = needed;
    $('setup-wizard').hidden = !(needed && roleState === 'admin');
    $('login-card').hidden = needed;
    $('first-file').hidden = !(needed && readFailed && roleState !== 'admin');
    ns.auth.holdLogin(needed);
  }

  let firstRun = false;   // the role is awaited to decide what a first setup shows

  /** First setup: nothing is shown until the user's role in the hub is known (Fusion tells it without a Client ID). */
  function offerFile() {
    firstRun = true;
    showWizard(wizardNeeded);
    checkRole(true);
  }

  /** The role is known: a Hub Admin gets the wizard, anyone else the search for the Configuration File. */
  function firstRunRole(state) {
    firstRun = false;
    showWizard(wizardNeeded);
    if (state !== 'admin') openMemberPicker();
  }

  /** The picker for a member's first setup: closing it without a file closes the panel. */
  function openMemberPicker() {
    readFailed = false;
    showWizard(wizardNeeded);
    ns.hubPicker.open(document.querySelector('[data-hub-name]').textContent, function (file) { useHubConfig(file); },
      { onDismiss: function () { bridge.send('close_settings', {}); } });
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

  const SETUP_OPTIONS = [['wiz-opt-new', false], ['wiz-opt-file', true]];   // [button id, whether it sets up from a Configuration File]

  /** The first setup of a Hub Admin starts as a new setup, or from the Configuration File another Hub Admin saved. */
  function chooseSetup(useFile) {
    $('wiz-new').hidden = useFile;
    $('wiz-file').hidden = !useFile;
    SETUP_OPTIONS.forEach(function (option) {
      const chosen = option[1] === useFile;
      $(option[0]).classList.toggle('active', chosen);
      $(option[0]).setAttribute('aria-pressed', String(chosen));
    });
  }

  function initWizard() {
    SETUP_OPTIONS.forEach(function (option) {
      $(option[0]).addEventListener('click', function () { chooseSetup(option[1]); });
    });
    [$('wiz-guide'), $('conn-guide')].forEach(function (button) {
      button.addEventListener('click', function () { bridge.send('open_url', { url: GUIDE_URL }); });
    });
    $('wiz-client-id').addEventListener('input', updateWizard);
    $('wiz-copy').addEventListener('click', function () {
      copyText($('wiz-callback').textContent);
      $('wiz-copy').textContent = t('settings.copied');
      setTimeout(function () { $('wiz-copy').textContent = t('settings.copy'); }, 2000);
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
  let memberTabShown = false;   // the Configuration tab has been opened for this member since they became one
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
    $('cfg-file-view').hidden = !(member && hubFile);
    // The Configuration tab is a member's: it comes first, and is what they see when they open the panel.
    const fileTab = document.querySelector('.tab[data-tab="config"]');
    fileTab.hidden = !member;
    if (!member) memberTabShown = false;
    if (!member && fileTab.classList.contains('active')) document.querySelector('.tab[data-tab="connection"]').click();
    if (member && !memberTabShown) { memberTabShown = true; fileTab.click(); }
    applyMemberLock(member);
    const publisher = signedInNow && roleState === 'admin';   // only a Hub Admin publishes
    TAB_SAVES.forEach(function (prefix) { $(prefix + '-publish-btn').hidden = !publisher; });
  }

  function initTenantStep() {
    ns.account.onRefreshRole(function () {
      ns.account.closeCard();
      roleDialog = true;
      ns.progress.show(t('settings.role_checking_title'), t('settings.role_checking_text'));
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
    // Every opening validates the user's role again.
    bridge.on('palette_opened', function () { roleState = ''; fileOffered = false; ns.settings.load(); ns.auth.refresh(); });

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
      const publish = publishAfterSave;
      signInAfterSave = publishAfterSave = false;
      if (problems.length) return;
      fillSettings(r.result);
      if (publish) saveToHub();   // a file in the hub never holds settings that failed validation
      else if (TAB_SAVES.indexOf(saveSource) >= 0) ns.progress.notify(t('settings.saved_title'), t('settings.saved_text'));
      else {   // the first-setup steps have no dialog: they say it beside the button
        msg.textContent = t('settings.saved');
        setTimeout(function () { msg.textContent = ''; }, 2000);
      }
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
      $('callback-copy').textContent = t('settings.copied');
      setTimeout(function () { $('callback-copy').textContent = t('settings.copy'); }, 2000);
    });
    TAB_SAVES.forEach(function (prefix) {
      $(prefix + '-btn').addEventListener('click', function () { saveClicked(prefix, false); });
      $(prefix + '-publish-btn').addEventListener('click', function () { saveClicked(prefix, true); });
    });
    bridge.on('save_to_hub', onHubSave);
    bridge.on('save_to_hub_status', onHubSave);
  }

  ns.settings = {
    init: init,
    apply: fillSettings,
    load: function () { bridge.send('get_settings'); },
    publish: function () { if (roleState === 'admin') saveToHub(); },   // Save & Publish from the Language tab
    roleState: function () { return roleState; },   // '', 'pending', 'admin', 'member' or 'unknown'
  };
})(window.MfgUi);
