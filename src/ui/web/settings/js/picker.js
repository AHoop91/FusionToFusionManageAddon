/**
 * Searchable pickers: a button plus a list of ordinary page elements, as ``ns.picker``.
 *
 * Not a native <select>: the native popup was slow to open in Fusion's embedded browser.
 * A hidden input (class `cfg.valueClass`) carries the chosen value.
 *
 * cfg: valueClass, placeholder, search (placeholder text), label(value),
 *      groups(value, wrap) -> [{title, items: [{value, label, detail}]}],
 *      empty(wrap) -> text shown when nothing is listed or matches,
 *      taken(wrap) -> values already used elsewhere, shown greyed out,
 *      alignRight -> open the list leftwards, tip() -> button tooltip, onOpen(wrap) -> called as the list opens.
 * ``make(cfg, selected)`` builds one; it fires a `pick` event on its wrapper when the value changes.
 */
(function (ns) {
  'use strict';

  const el = ns.el;

  function buildMenu(wrap, cfg) {
    const input = wrap.querySelector('.' + cfg.valueClass);
    const menu = wrap.querySelector('.ws-pick-menu');
    const list = menu.querySelector('.ws-pick-list');
    const taken = cfg.taken ? cfg.taken(wrap) : [];
    list.textContent = '';
    const oldClear = menu.querySelector('.ws-pick-clear');
    if (oldClear) oldClear.remove();
    if (input.value) {
      const clear = el('button', 'ws-pick-clear', 'Clear selection');
      clear.type = 'button';
      clear.addEventListener('click', function () {
        input.value = '';
        menu.hidden = true;
        refreshPicker(wrap, cfg);
        wrap.dispatchEvent(new Event('pick'));
      });
      menu.insertBefore(clear, list);   // pinned above the scrolling list
    }
    cfg.groups(input.value, wrap).forEach(function (group) {
      const section = el('div', 'ws-pick-section');
      section.appendChild(el('div', 'ws-pick-group', group.title));
      list.appendChild(section);
      group.items.forEach(function (item) {
        const button = el('button', 'ws-pick-item', item.label);
        button.type = 'button';
        if (item.detail) button.appendChild(el('span', 'ws-pick-detail', item.detail));
        if (item.value === input.value) {
          button.classList.add('selected');
        } else if (taken.indexOf(item.value) >= 0) {
          button.disabled = true;
          button.title = 'Already mapped';
        }
        button.addEventListener('click', function () {
          input.value = item.value;
          menu.hidden = true;
          refreshPicker(wrap, cfg);
          wrap.dispatchEvent(new Event('pick'));
        });
        section.appendChild(button);
      });
    });
    list.appendChild(el('div', 'ws-pick-empty muted', cfg.empty(wrap)));
    filterMenu(menu);
  }

  /** Hide items that do not match the search box, and groups left empty. */
  function filterMenu(menu) {
    const term = menu.querySelector('.ws-pick-search').value.trim().toLowerCase();
    let shown = 0;
    menu.querySelectorAll('.ws-pick-section').forEach(function (section) {
      let visible = 0;
      section.querySelectorAll('.ws-pick-item').forEach(function (item) {
        const match = !term || item.textContent.toLowerCase().indexOf(term) >= 0;
        item.hidden = !match;
        if (match) visible++;
      });
      section.hidden = visible === 0;
      shown += visible;
    });
    menu.querySelector('.ws-pick-empty').hidden = shown > 0;
  }

  /** Update the button text from the current value. */
  function refreshPicker(wrap, cfg) {
    const input = wrap.querySelector('.' + cfg.valueClass);
    const button = wrap.querySelector('.ws-pick-btn');
    button.querySelector('.ws-pick-text').textContent = input.value ? cfg.label(input.value) : cfg.placeholder;
    button.classList.toggle('placeholder', !input.value);
    if (cfg.tip) button.title = cfg.tip();
  }

  /**
   * Position the list inside the palette: below the button, or above it when
   * there is not enough room below, and never past the left or right edge.
   */
  function placeMenu(wrap, menu) {
    const list = menu.querySelector('.ws-pick-list');
    menu.classList.remove('up');
    list.style.maxHeight = '';
    const rect = wrap.getBoundingClientRect();
    const viewWidth = document.documentElement.clientWidth;
    const width = Math.min(Math.max(rect.width, 240), viewWidth - 16);
    menu.style.width = width + 'px';
    // Start flush with the button's left edge (or right edge for `.right`),
    // then pull the list back inside the palette.
    let left = rect.left + (menu.classList.contains('right') ? rect.width - width : 0);
    left = Math.max(8, Math.min(left, viewWidth - 8 - width));
    menu.style.left = (left - rect.left) + 'px';
    menu.style.right = 'auto';
    const chrome = menu.offsetHeight - list.offsetHeight;   // search box and padding
    const below = window.innerHeight - rect.bottom - 8;
    const above = rect.top - 8;
    if (menu.offsetHeight > below && above > below) menu.classList.add('up');
    // Never let the list run past the palette on whichever side it opens.
    const room = Math.max(above > below && menu.offsetHeight > below ? above : below, 120);
    list.style.maxHeight = Math.max(80, Math.min(220, room - chrome)) + 'px';
  }

  function makePicker(cfg, selected) {
    const wrap = el('div', 'ws-pick-wrap');
    const input = el('input', cfg.valueClass);
    input.type = 'hidden';
    input.value = selected || '';
    const button = el('button', 'ws-pick-btn');
    button.type = 'button';
    button.appendChild(el('span', 'ws-pick-text'));
    const menu = el('div', 'ws-pick-menu');
    menu.hidden = true;
    if (cfg.alignRight) menu.classList.add('right');
    const search = el('input', 'ws-pick-search');
    search.type = 'text';
    search.placeholder = cfg.search;
    search.autocomplete = 'off';
    search.spellcheck = false;
    search.addEventListener('input', function () { filterMenu(menu); });
    search.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      const first = Array.prototype.filter.call(menu.querySelectorAll('.ws-pick-item'),
        function (item) { return !item.disabled && !item.hidden && !item.closest('[hidden]'); })[0];
      if (first) first.click();
    });
    menu.appendChild(search);
    menu.appendChild(el('div', 'ws-pick-list'));
    button.addEventListener('click', function () {
      const open = menu.hidden;
      document.querySelectorAll('.ws-pick-menu').forEach(function (m) { m.hidden = true; });
      menu.hidden = !open;
      if (open) {
        // Built on open so it reflects the other rows and the latest lists.
        search.value = '';
        if (cfg.onOpen) cfg.onOpen(wrap);
        buildMenu(wrap, cfg);
        placeMenu(wrap, menu);
        search.focus();
      }
    });
    wrap.appendChild(input);
    wrap.appendChild(button);
    wrap.appendChild(menu);
    refreshPicker(wrap, cfg);
    return wrap;
  }

  // Close an open list when clicking elsewhere or pressing Escape.
  document.addEventListener('click', function (e) {
    document.querySelectorAll('.ws-pick-menu').forEach(function (menu) {
      if (!menu.parentNode.contains(e.target)) menu.hidden = true;
    });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      document.querySelectorAll('.ws-pick-menu').forEach(function (menu) { menu.hidden = true; });
    }
  });

  /** Rebuild the list of an open picker, e.g. when the items it waited for arrive. */
  function rebuildOpen(wrap, cfg) {
    const menu = wrap.querySelector('.ws-pick-menu');
    if (!menu.hidden) buildMenu(wrap, cfg);
  }

  ns.picker = { make: makePicker, refresh: refreshPicker, rebuildOpen: rebuildOpen };
})(window.MfgUi);
