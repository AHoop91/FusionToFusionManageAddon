/**
 * Sign-in flow and view switching, shared by every panel.
 *
 * A page provides `#view-login` (shown while signed out; holds `#login-form`
 * and `#login-loader`, the latter shown while signing in) and `#view-app`
 * (shown while signed in). Signed out shows only the login view; signed in
 * shows the app, the header account controls, and loads the profile.
 *
 * Panel-specific behaviour hooks in through `onChange(callback)`.
 *
 * "Logging in" is shown from the start, until the first answer about the sign-in arrives, and while a browser sign-in is pending. Python
 * pushes the state when a sign-in ends, but an answer can be missed (the page was not ready, or a panel was opened while another one signed
 * in), so while the loader is up the state is asked for every few seconds, and after a while the loader says what to do.
 */
(function (ns) {
  'use strict';

  const $ = ns.$;
  const bridge = ns.bridge;
  const t = ns.i18n.t;

  /** What the sign-in card says for a state; the state itself for one not known. */
  function stateText(state) {
    switch (state) {
      case 'signed_out': return t('common.signin_prompt');
      case 'signing_in': return t('common.logging_in');
      case 'signed_in': return t('common.signed_in_fm');
      case 'error': return t('common.signin_failed');
      default: return state;
    }
  }

  let profileLoaded = false;
  let autoLoginTried = false;
  let loginHeld = false;   // a panel that has nothing to sign in with yet (no Client ID) holds the automatic sign-in back
  const changeListeners = [];

  const WAIT_POLL_MS = 3000;    // how often the state is asked for while "Logging in" is shown
  const WAIT_HELP_MS = 20000;   // how long "Logging in" is shown before it says what to do
  let waitTimer = 0;
  let waitSince = 0;

  /** Keep asking for the state while the loader is shown, and say what to do when it has been shown for a while; stop when it is not. */
  function watchLoader(waiting) {
    const help = $('login-help');
    if (!waiting) {
      clearInterval(waitTimer);
      waitTimer = 0;
      if (help) help.hidden = true;
      return;
    }
    if (waitTimer) return;
    waitSince = Date.now();
    waitTimer = setInterval(function () {
      bridge.send('auth_status');
      if (Date.now() - waitSince < WAIT_HELP_MS) return;
      const note = $('login-help') || ns.el('p', 'muted', t('common.login_help'));
      note.id = 'login-help';
      note.hidden = false;
      const loader = $('login-loader');
      if (note.parentNode !== loader) loader.insertBefore(note, $('cancel-btn'));
    }, WAIT_POLL_MS);
  }

  /** Call `callback(signedIn)` every time the sign-in state is rendered. */
  function onChange(callback) { changeListeners.push(callback); }

  function renderAuth(status) {
    // Opening a panel while signed out starts the login straight away, once.
    // After a cancel, an error or a sign-out the sign-in card stays.
    if (status.state === 'signed_out' && !autoLoginTried && !loginHeld) {
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

    $('conn-summary').textContent = stateText(state);
    // While the browser sign-in is pending, swap the form for the loader.
    $('login-form').hidden = state === 'signing_in';
    $('login-loader').hidden = state !== 'signing_in';
    watchLoader(state === 'signing_in');
    $('conn-error').hidden = !status.error;
    $('conn-error').textContent = status.error || '';
    ns.account.renderPresence(signedIn);

    // Clear the profile when the session ends.
    if (!signedIn) { profileLoaded = false; ns.account.renderProfile(null); }

    try {
      changeListeners.forEach(function (callback) { callback(signedIn); });
    } finally {   // a listener that fails must not stop the profile from loading or the sign-in from being polled
      // Load the profile once per session. It is asked for after the panels' own requests: Python answers a
      // message before reading the next, and the profile (a Fusion Manage call) would otherwise hold them up.
      if (signedIn && !profileLoaded) { profileLoaded = true; bridge.send('auth_profile'); }

      // While a browser sign-in is pending nothing is asked: Python pushes the state when the sign-in ends (Cancel ends it too).
    }
  }

  function init() {
    ['auth_status', 'auth_login', 'auth_logout'].forEach(function (action) {
      bridge.on(action, function (r) {
        renderAuth(r.ok ? r.result : { state: 'error', error: r.error });
      });
    });

    $('signin-btn').addEventListener('click', function () { bridge.send('auth_login'); });
    // Cancel also asks how things stand: when no sign-in is under way (the loader was only the page waiting for its first answer), there is
    // nothing for Python to cancel and no push to follow, so this is what ends the wait.
    $('cancel-btn').addEventListener('click', function () { bridge.send('auth_cancel'); bridge.send('auth_status'); });
    watchLoader($('login-loader') !== null && !$('login-loader').hidden);   // the pages that show "Logging in" until they are told otherwise
  }

  ns.auth = {
    init: init,
    onChange: onChange,
    refresh: function () { bridge.send('auth_status'); },
    holdLogin: function (held) { loginHeld = held; },
  };
})(window.MfgUi);
