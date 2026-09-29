/**
 * Account avatar, presence dot and account card in the header.
 *
 * Shows the Fusion Manage profile image, falling back to initials and then a
 * generic icon. Identity comes from the `auth_profile` action.
 */
(function (ns) {
  'use strict';

  const $ = ns.$;
  const bridge = ns.bridge;

  // Element groups for the two avatars (small header one, larger card one).
  const HEADER_AVATAR = {
    frame: 'avatar', icon: 'avatar-icon', initials: 'avatar-initials', img: 'avatar-img',
  };
  const CARD_AVATAR = {
    frame: 'card-avatar', icon: 'card-avatar-icon', initials: 'card-avatar-initials', img: 'card-avatar-img',
  };

  // ---- Avatar -------------------------------------------------------------

  /** Two-letter initials for `name`, or '' when there is no name. */
  function initialsOf(name) {
    return name.split(/\s+/).filter(Boolean).slice(0, 2)
      .map(function (part) { return part[0].toUpperCase(); }).join('');
  }

  /**
   * Paint one avatar: picture if it loads, else initials, else generic icon.
   * `active` tints the background for a signed-in user.
   */
  function paintAvatar(ids, picture, initials, active) {
    const frame = $(ids.frame);
    const icon = $(ids.icon);
    const initialsEl = $(ids.initials);
    const img = $(ids.img);

    img.hidden = true;
    img.removeAttribute('src');
    icon.hidden = !!initials;
    initialsEl.hidden = !initials;
    initialsEl.textContent = initials;
    frame.classList.toggle('on', active);
    if (!picture) return;

    img.onload = function () {
      img.hidden = false;
      icon.hidden = true;
      initialsEl.hidden = true;
    };
    img.onerror = function () { img.hidden = true; };
    img.src = picture;
  }

  /** Render identity everywhere. `profile` is null when signed out. */
  function renderProfile(profile) {
    const name = profile && profile.name ? profile.name : '';
    const initials = initialsOf(name);
    const active = !!profile;

    paintAvatar(HEADER_AVATAR, profile && profile.picture, initials, active);
    // The card avatar is bigger, so it prefers the larger image.
    paintAvatar(CARD_AVATAR, profile && (profile.picture_large || profile.picture), initials, active);

    $('card-name').textContent = name || (profile ? 'Signed in' : 'Not signed in');
    $('card-email').textContent = profile ? profile.email || '' : '';
  }

  // ---- Presence -----------------------------------------------------------

  /** Update the presence dot and the status line in the account card. */
  function renderPresence(online) {
    const state = online ? 'online' : 'offline';
    $('status-dot').className = 'status-dot ' + state;
    $('card-status').className = 'card-status ' + state;
    $('card-status-text').textContent = online ? 'Online' : 'Offline';
    $('card-signout').hidden = !online;
  }

  // ---- Account card -------------------------------------------------------

  function setCardOpen(open) {
    $('user-card').hidden = !open;
    $('avatar-btn').setAttribute('aria-expanded', String(open));
  }

  /** Wire card open/close (avatar click, outside click, Escape) and sign-out. */
  function init() {
    $('avatar-btn').addEventListener('click', function (e) {
      e.stopPropagation();
      setCardOpen($('user-card').hidden);
    });
    $('user-card').addEventListener('click', function (e) { e.stopPropagation(); });
    document.addEventListener('click', function () { setCardOpen(false); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') setCardOpen(false); });
    $('card-signout').addEventListener('click', function () {
      setCardOpen(false);
      bridge.send('auth_logout');
    });

    bridge.on('auth_profile', function (r) { if (r.ok) renderProfile(r.result); });
    renderPresence(false);
  }

  ns.account = {
    init: init,
    renderProfile: renderProfile,
    renderPresence: renderPresence,
    closeCard: function () { setCardOpen(false); },
  };
})(window.MfgUi);
