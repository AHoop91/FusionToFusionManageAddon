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

  const HELP_ICON =
    '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">' +
    '<path d="M9.2 9.6a2.9 2.9 0 1 1 4.4 2.4c-1 .6-1.6 1.2-1.6 2.3" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/>' +
    '<circle cx="12" cy="17.7" r="1.2" fill="currentColor"/></svg>';

  const AVATAR_ICON =
    '<svg viewBox="0 0 24 24" width="{size}" height="{size}" aria-hidden="true">' +
    '<circle cx="12" cy="8" r="4" fill="currentColor"/>' +
    '<path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7z" fill="currentColor"/></svg>';

  /** The text called `key`, safe to put in markup (a language file's text is not trusted to be free of markup). */
  function text(key) {
    const box = document.createElement('span');
    box.textContent = ns.i18n.t(key);
    return box.innerHTML.replace(/"/g, '&quot;');
  }

  /** The Help button. */
  function helpHtml() {
    return '<button id="help-btn" class="help-btn" type="button" title="' + text('shell.help') + '" aria-label="' + text('shell.help') + '">' + HELP_ICON + '</button>';
  }

  /** Make the Help button work: it asks Python to open the documentation. */
  function bindHelp() {
    ns.$('help-btn').addEventListener('click', function () { ns.bridge.send('open_help', {}); });
  }

  /** Header markup. Static content and the add-in's own wording only; nothing here comes from user data. */
  function headerHtml() {
    return '' +
      '<img class="logo" src="' + LOGO_URL + '" alt="Fusion Manage">' +

      '<div class="header-right">' +

      // Help: opens the documentation in the system browser, signed in or not.
      helpHtml() +

      // Account avatar and card: only visible while signed in.
      '<div id="user-wrap" class="user" hidden>' +
      '  <span id="role-pill" class="role-pill" hidden></span>' +
      '  <button id="avatar-btn" class="avatar-btn" aria-haspopup="true" aria-expanded="false" title="' + text('shell.account') + '">' +
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
      '      <span class="card-label">' + text('shell.status') + '</span>' +
      '      <span id="card-status" class="card-status"><span class="card-status-dot"></span><span id="card-status-text"></span></span>' +
      '    </div>' +
      '    <div id="card-role-row" class="card-row" hidden>' +
      '      <span class="card-label">' + text('shell.permissions') + '</span>' +
      '      <button id="card-role-refresh" class="card-link" type="button">' + text('shell.refresh') + '</button>' +
      '    </div>' +
      '    <div class="card-row">' +
      '      <span class="card-label">' + text('shell.addin') + '</span>' +
      '      <button id="card-restart" class="card-link" type="button">' + text('shell.restart') + '</button>' +
      '    </div>' +
      '    <button id="card-signout" class="btn btn-secondary btn-block" hidden>' + text('shell.sign_out') + '</button>' +
      '  </div>' +
      '</div>' +
      '</div>';
  }

  /** Fill `#app-header` with the shared top bar. */
  function mountHeader() {
    ns.$('app-header').innerHTML = headerHtml();
    bindHelp();
  }

  /** Put the Help button at the end of `node`, for a panel that has its own bar and not the shared top bar (the Job Queue). */
  function mountHelp(node) {
    node.insertAdjacentHTML('beforeend', helpHtml());
    bindHelp();
  }

  ns.shell = { mountHeader: mountHeader, mountHelp: mountHelp };
})(window.MfgUi);
