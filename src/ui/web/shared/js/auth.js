/**
 * Sign-in flow and view switching, shared by every panel.
 *
 * A page provides `#view-login` (shown while signed out; holds `#login-form`
 * and `#login-loader`, the latter shown while signing in) and `#view-app`
 * (shown while signed in). Signed out shows only the login view; signed in
 * shows the app, the header account controls, and loads the profile.
 *
 * Panel-specific behaviour hooks in through `onChange(callback)`.
 */
(function (ns) {
  'use strict';

  const $ = ns.$;
  const bridge = ns.bridge;

  const POLL_INTERVAL_MS = 1000;
  const STATE_TEXT = {
    signed_out: 'Sign in with your Autodesk account to continue.',
    signing_in: 'Logging in...',
    signed_in: 'Signed in to Fusion Manage.',
    error: 'Sign-in failed.',
  };

  let pollTimer = null;
  let profileLoaded = false;
  let autoLoginTried = false;
  const changeListeners = [];

  /** Call `callback(signedIn)` every time the sign-in state is rendered. */
  function onChange(callback) { changeListeners.push(callback); }

  function renderAuth(status) {
    // Opening a panel while signed out starts the login straight away, once.
    // After a cancel, an error or a sign-out the sign-in card stays.
    if (status.state === 'signed_out' && !autoLoginTried) {
      autoLoginTried = true;
      bridge.send('auth_login');
      status = { state: 'signing_in', error: '' };
    }
    const state = status.state;
    const signedIn = state === 'signed_in';

    $('view-login').hidden = signedIn;
    $('view-app').hidden = !signedIn;
    $('user-wrap').hidden = !signedIn;
    if (!signedIn) ns.account.closeCard();

    $('conn-summary').textContent = STATE_TEXT[state] || state;
    // While the browser sign-in is pending, swap the form for the loader.
    $('login-form').hidden = state === 'signing_in';
    $('login-loader').hidden = state !== 'signing_in';
    $('conn-error').hidden = !status.error;
    $('conn-error').textContent = status.error || '';
    ns.account.renderPresence(signedIn);

    // Clear the profile when the session ends.
    if (!signedIn) { profileLoaded = false; ns.account.renderProfile(null); }

    changeListeners.forEach(function (callback) { callback(signedIn); });

    // Load the profile once per session. It is asked for after the panels' own requests: Python answers a
    // message before reading the next, and the profile (a Fusion Manage call) would otherwise hold them up.
    if (signedIn && !profileLoaded) { profileLoaded = true; bridge.send('auth_profile'); }

    // Poll only while a browser sign-in is pending.
    clearTimeout(pollTimer);
    if (state === 'signing_in') {
      pollTimer = setTimeout(function () { bridge.send('auth_status'); }, POLL_INTERVAL_MS);
    }
  }

  function init() {
    ['auth_status', 'auth_login', 'auth_logout'].forEach(function (action) {
      bridge.on(action, function (r) {
        renderAuth(r.ok ? r.result : { state: 'error', error: r.error });
      });
    });

    $('signin-btn').addEventListener('click', function () { bridge.send('auth_login'); });
    $('cancel-btn').addEventListener('click', function () { bridge.send('auth_cancel'); });
  }

  ns.auth = {
    init: init,
    onChange: onChange,
    refresh: function () { bridge.send('auth_status'); },
  };
})(window.MfgUi);
