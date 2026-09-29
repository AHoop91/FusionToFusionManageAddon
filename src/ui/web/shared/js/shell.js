/**
 * Reusable panel shell: the top bar with logo, avatar, presence dot and
 * account card.
 *
 * A page adds an empty `<header id="app-header" class="app-header">` and
 * calls `MfgUi.shell.mountHeader()`. Styling lives in shared/css/header.css,
 * behaviour in account.js, so every panel gets the same top bar.
 */
(function (ns) {
  'use strict';

  // Relative to a page in web/<panel>/.
  const LOGO_URL = '../shared/assets/fusion-manage-logo.svg';

  const AVATAR_ICON =
    '<svg viewBox="0 0 24 24" width="{size}" height="{size}" aria-hidden="true">' +
    '<circle cx="12" cy="8" r="4" fill="currentColor"/>' +
    '<path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7z" fill="currentColor"/></svg>';

  /** Header markup. Static content only; nothing here comes from user data. */
  function headerHtml() {
    return '' +
      '<img class="logo" src="' + LOGO_URL + '" alt="Fusion Manage">' +

      // Account avatar and card: only visible while signed in.
      '<div id="user-wrap" class="user" hidden>' +
      '  <button id="avatar-btn" class="avatar-btn" aria-haspopup="true" aria-expanded="false" title="Account">' +
      '    <span id="avatar" class="avatar">' +
      '      <span id="avatar-icon">' + AVATAR_ICON.replace(/{size}/g, '20') + '</span>' +
      '      <span id="avatar-initials" hidden></span>' +
      '      <img id="avatar-img" alt="" hidden>' +
      '    </span>' +
      '    <span id="status-dot" class="status-dot offline"></span>' +
      '  </button>' +
      '  <div id="user-card" class="user-card" hidden>' +
      '    <div class="card-head">' +
      '      <div id="card-avatar" class="card-avatar">' +
      '        <span id="card-avatar-icon">' + AVATAR_ICON.replace(/{size}/g, '30') + '</span>' +
      '        <span id="card-avatar-initials" hidden></span>' +
      '        <img id="card-avatar-img" alt="" hidden>' +
      '      </div>' +
      '      <div class="card-id">' +
      '        <p id="card-name" class="card-name"></p>' +
      '        <p id="card-email" class="card-email"></p>' +
      '      </div>' +
      '    </div>' +
      '    <div class="card-divider"></div>' +
      '    <div class="card-row">' +
      '      <span class="card-label">Status</span>' +
      '      <span id="card-status" class="card-status"><span class="card-status-dot"></span><span id="card-status-text"></span></span>' +
      '    </div>' +
      '    <button id="card-signout" class="btn btn-secondary btn-block" hidden>Sign out</button>' +
      '  </div>' +
      '</div>';
  }

  /** Fill `#app-header` with the shared top bar. */
  function mountHeader() {
    ns.$('app-header').innerHTML = headerHtml();
  }

  ns.shell = { mountHeader: mountHeader };
})(window.MfgUi);
