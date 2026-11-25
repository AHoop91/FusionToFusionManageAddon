/**
 * Tab strips.
 *
 * Buttons carry `data-tab`; the strip carries `data-group`. Panels share that
 * group and have the id `<prefix><tab>`.
 *
 * When the tabs are wider than the panel the strip scrolls sideways: arrow
 * buttons appear at the edges that have more tabs, the mouse wheel scrolls
 * it, and the selected tab is always brought into view.
 */
(function (ns) {
  'use strict';

  const $ = ns.$;
  const t = ns.i18n.t;
  const SCROLL_STEP_RATIO = 0.6;   // fraction of the visible width per arrow click

  // ---- Sideways scrolling -------------------------------------------------

  /** Wrap `nav` with edge arrows and keep them in step with its scroll state. */
  function makeScrollable(nav) {
    const wrapper = document.createElement('div');
    wrapper.className = 'tabs-scroller';
    nav.parentNode.insertBefore(wrapper, nav);

    const prev = arrowButton('prev', t('common.scroll_tabs_left'));
    const next = arrowButton('next', t('common.scroll_tabs_right'));
    wrapper.appendChild(prev);
    wrapper.appendChild(nav);
    wrapper.appendChild(next);

    function update() {
      const max = nav.scrollWidth - nav.clientWidth;
      prev.hidden = nav.scrollLeft <= 1;
      next.hidden = nav.scrollLeft >= max - 1;
    }

    function scrollBy(direction) {
      nav.scrollBy({ left: direction * nav.clientWidth * SCROLL_STEP_RATIO, behavior: 'smooth' });
    }
    prev.addEventListener('click', function () { scrollBy(-1); });
    next.addEventListener('click', function () { scrollBy(1); });

    // Let the wheel move the strip sideways, but only when it overflows.
    nav.addEventListener('wheel', function (e) {
      if (nav.scrollWidth <= nav.clientWidth) return;
      nav.scrollLeft += e.deltaY || e.deltaX;
      e.preventDefault();
    }, { passive: false });

    nav.addEventListener('scroll', update);
    // The strip is hidden while signed out, so also re-check whenever its
    // own size changes (becoming visible, or the palette being resized).
    window.addEventListener('resize', update);
    if (window.ResizeObserver) new ResizeObserver(update).observe(nav);
    update();
  }

  function arrowButton(kind, label) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'tabs-arrow tabs-arrow-' + kind;
    button.setAttribute('aria-label', label);
    button.hidden = true;
    return button;
  }

  // ---- Tab switching ------------------------------------------------------

  /** Wire one tab strip so clicking a button shows its panel. */
  function setupTabs(navSelector, buttonClass, idPrefix) {
    const nav = document.querySelector(navSelector);
    const group = nav.dataset.group;
    makeScrollable(nav);

    nav.querySelectorAll('.' + buttonClass).forEach(function (button) {
      button.addEventListener('click', function () {
        nav.querySelectorAll('.' + buttonClass).forEach(function (b) { b.classList.remove('active'); });
        document.querySelectorAll('.tab-panel[data-group="' + group + '"]').forEach(function (p) {
          p.classList.remove('active');
        });
        button.classList.add('active');
        $(idPrefix + button.dataset.tab).classList.add('active');
        // Bring the selected tab fully into view if it is partly clipped.
        if (nav.scrollWidth > nav.clientWidth) button.scrollIntoView({ block: 'nearest', inline: 'nearest' });   // only a strip that overflows has anything to scroll
      });
    });

    // A page that loaded itself again in a new language opens the tab it was on, when that tab is there to open.
    const reopen = ns.i18n.takeOpenTab();
    const tab = reopen && nav.querySelector('.' + buttonClass + '[data-tab="' + reopen + '"]');
    if (tab && !tab.hidden) tab.click();
  }

  /** Wire the Settings tabs. Add a call here for each new tab strip. */
  function init() {
    setupTabs('.tabs[data-group="settings"]', 'tab', 'sub-');
  }

  ns.tabs = { init: init, setup: setupTabs };   // ``setup(navSelector, buttonClass, idPrefix)`` wires a strip a page builds itself (Publish's details panel)
})(window.MfgUi);
