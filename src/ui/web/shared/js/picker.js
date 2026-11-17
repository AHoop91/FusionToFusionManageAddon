/**
 * The one picker of the add-in's pages, as ``ns.picker``: a button that opens a list of ordinary page elements (a native <select> popup was slow
 * to open in Fusion's embedded browser). The list is laid out in the window, so a scrolling card does not cut it off; it closes on a click
 * elsewhere, on Escape, on a scroll of the page and when another picker opens. Arrow keys, Enter and Escape work as on a native one.
 *
 * Where the items come from (one of):
 *   groups(current, wrap) -> [{title, items: [{value, label, detail, actions}]}]   a list the page holds: the search box filters it; an item's
 *                                                                         ``actions`` [{label, icon: svg paths, className, run(item)}] are small buttons beside it
 *   source(text, offset, done)                                            a list somewhere else, asked for in batches as the search box
 *                                                                         changes and the list is scrolled; ``done({items: [{value, label}],
 *                                                                         next: offset of the next batch, total})`` or ``done({error})``
 * What it shows:
 *   placeholder, search (the search box's placeholder), empty(wrap) -> text for a list with nothing to show, label(value) -> the text of a value
 *   the page holds (a source's items bring their own), tip() -> the button's tooltip, ariaLabel,
 *   text: {clear, taken (tooltip of a taken item), loading, showing(shown, total)}, only what the picker's kind uses.
 * How it works:
 *   multi -> several values, shown as chips; required -> there is no "clear" entry; searchFrom -> a page's list shows the search box from this
 *   many items on; takenValues(wrap) -> values used elsewhere, greyed out; alignRight -> the list opens leftwards; onOpen(wrap) -> called as it opens;
 *   footer(wrap) -> {label, icon: svg paths, run} or null: an entry after the items that is not a choice but an action (it closes the list);
 *   valueClass -> a hidden input of that class carries the (first) value.
 * How it looks: className on the wrapper, buttonClass on the button.
 *
 * ``make(cfg, selected)`` builds one (``selected``: the value a page's single picker holds) and fires a `pick` event on its wrapper when the choice
 * changes. The wrapper has ``refresh()`` (the button's text, after the lists change), ``rebuildOpen()`` (the list, if open, after the items
 * it waited for arrive), ``setPicked([{value, label}])`` and ``getPicked()``.
 */
(function (ns) {
  'use strict';

  const el = ns.el;

  const SEARCH_DELAY_MS = 300;   // how long the search box rests before a source is asked
  const NEAR_END_PX = 80;        // how close to the end of the list the next batch is asked for
  let closeOpen = null;          // closes the picker that is open, if one is
  let seq = 0;

  function make(cfg, selected) {
    const wrap = el('div', cfg.className ? 'pk ' + cfg.className : 'pk');
    const id = 'pk' + (++seq);
    const input = cfg.valueClass ? el('input', cfg.valueClass) : null;
    const chips = cfg.multi ? el('div', 'pk-chips') : null;
    const button = el('button', cfg.buttonClass ? 'pk-btn ' + cfg.buttonClass : 'pk-btn');
    const text = el('span', 'pk-text');
    const menu = el('div', 'pk-menu');
    const search = el('input', 'pk-search');
    const clear = el('button', 'pk-clear');   // pinned above the scrolling list
    const count = el('p', 'pk-count');   // "Showing 50 of 1,234"
    const list = el('div', 'pk-list');
    const status = el('p', 'pk-status');   // the balls while a batch is on its way, what went wrong, or that there is nothing
    let chosen = selected ? [{ value: selected }] : [];   // [{value, label}]
    let active = null;     // the item the arrow keys are on
    let found = [];        // a source: the items read so far for the text in the search box
    let offset = 0;
    let total = 0;
    let loading = false;   // a batch is on its way
    let failed = '';
    let token = 0;         // a batch is only taken if no newer search has taken its place
    let timer = 0;

    if (input) input.type = 'hidden';
    button.type = 'button';
    button.setAttribute('aria-haspopup', 'listbox');
    button.setAttribute('aria-expanded', 'false');
    if (cfg.ariaLabel) button.setAttribute('aria-label', cfg.ariaLabel);
    menu.hidden = true;
    search.type = 'text';
    search.placeholder = cfg.search;
    search.setAttribute('aria-label', cfg.search);
    search.autocomplete = 'off';
    search.spellcheck = false;
    clear.type = 'button';
    list.id = id;
    list.setAttribute('role', 'listbox');
    if (cfg.multi) list.setAttribute('aria-multiselectable', 'true');
    button.setAttribute('aria-controls', id);
    button.appendChild(text);
    [search, clear, count, list, status].forEach(function (part) { menu.appendChild(part); });
    [input, chips, button, menu].forEach(function (part) { if (part) wrap.appendChild(part); });

    function current() { return chosen.length ? chosen[0].value : ''; }
    function labelOf(entry) { return cfg.label ? cfg.label(entry.value) : entry.label; }

    /** The button, the chips and the value input from what is chosen. */
    function paint() {
      if (input) input.value = current();
      text.textContent = !cfg.multi && chosen.length ? labelOf(chosen[0]) : cfg.placeholder;
      button.classList.toggle('placeholder', cfg.multi || !chosen.length);
      if (cfg.tip) button.title = cfg.tip();
      if (!chips) return;
      chips.textContent = '';
      chosen.forEach(function (entry, i) {
        const chip = el('span', 'pk-chip', labelOf(entry));
        const remove = el('button', 'pk-chip-x', '×');
        remove.type = 'button';
        remove.title = cfg.text.clear;
        remove.setAttribute('aria-label', cfg.text.clear + ': ' + labelOf(entry));
        remove.addEventListener('click', function () { chosen.splice(i, 1); changed(); });
        chip.appendChild(remove);
        chips.appendChild(chip);
      });
      chips.hidden = !chosen.length;
    }

    function changed() {
      paint();
      wrap.dispatchEvent(new Event('pick'));
    }

    function choose(items) {
      chosen = items;
      close();
      button.focus();
      changed();
    }

    function enabledItems() {
      return Array.prototype.filter.call(menu.querySelectorAll('.pk-item, .pk-act'), function (item) { return !item.disabled && !item.closest('[hidden]'); });
    }

    /** The arrow keys' mark on an entry (and on the row that holds it, whose buttons then show). */
    function light(node, on) {
      node.classList.toggle('active', on);
      const line = node.closest('.pk-row');
      if (line) line.classList.toggle('on', on);
    }

    function mark(item) {
      if (active) light(active, false);
      active = item;
      [button, search].forEach(function (part) { part.setAttribute('aria-activedescendant', item ? item.id : ''); });
      if (!item) return;
      light(item, true);
      item.scrollIntoView({ block: 'nearest' });
    }

    /** ``node`` as a button of the list that closes it, gives the focus back to the picker's button and then runs ``run``. */
    function press(node, run) {
      node.type = 'button';
      node.addEventListener('mousedown', function (event) { event.preventDefault(); });
      node.addEventListener('click', function () { close(); button.focus(); run(); });
      return node;
    }

    function row(item, index, taken) {
      const node = el('button', 'pk-item', item.label);
      node.type = 'button';
      node.id = id + '-' + index;
      node.setAttribute('role', 'option');
      if (item.detail) node.appendChild(el('span', 'pk-detail', item.detail));
      const isChosen = chosen.some(function (entry) { return entry.value === item.value; });
      node.setAttribute('aria-selected', String(isChosen));
      if (isChosen) {
        node.classList.add('selected');
        node.disabled = !!cfg.multi;   // one item is not chosen twice
      } else if (taken.indexOf(item.value) >= 0) {
        node.disabled = true;
        node.title = cfg.text.taken;
      }
      node.addEventListener('mousedown', function (event) { event.preventDefault(); });   // the focus stays where it is
      node.addEventListener('click', function () { choose(cfg.multi ? chosen.concat([{ value: item.value, label: item.label }]) : [{ value: item.value, label: item.label }]); });
      if (!item.actions) return node;
      const line = el('div', 'pk-row');   // the item and its small buttons side by side
      line.appendChild(node);
      item.actions.forEach(function (action, n) {
        const act = press(el('button', 'pk-act ' + (action.className || '')), function () { action.run(item); });
        act.id = node.id + '-' + n;
        act.title = action.label;
        act.setAttribute('aria-label', action.label);
        act.appendChild(ns.svg(action.icon, 16));
        line.appendChild(act);
      });
      return line;
    }

    /** Hide the items that do not match the search box, and the groups left empty. */
    function filter() {
      const term = search.value.trim().toLowerCase();
      let shown = 0;
      list.querySelectorAll('.pk-section').forEach(function (section) {
        let visible = 0;
        section.querySelectorAll('.pk-item').forEach(function (item) {
          const hide = !!term && item.textContent.toLowerCase().indexOf(term) < 0;
          (item.closest('.pk-row') || item).hidden = hide;
          if (!hide) visible++;
        });
        section.hidden = visible === 0;
        shown += visible;
      });
      status.textContent = shown ? '' : cfg.empty(wrap);
    }

    /** The list from what is chosen, the other rows and the latest items. */
    function render() {
      const taken = cfg.takenValues ? cfg.takenValues(wrap) : [];
      const groups = cfg.source ? [{ title: '', items: found }] : cfg.groups(current(), wrap);
      let index = 0;
      list.textContent = '';
      clear.hidden = cfg.multi || !!cfg.required || !chosen.length;
      if (!clear.hidden) clear.textContent = cfg.text.clear;
      groups.forEach(function (group) {
        const section = el('div', 'pk-section');
        section.setAttribute('role', 'group');
        if (group.title) {   // a list of one kind has no heading
          section.appendChild(el('div', 'pk-group', group.title));
          section.setAttribute('aria-label', group.title);
        }
        group.items.forEach(function (item) { section.appendChild(row(item, index++, taken)); });
        list.appendChild(section);
      });
      const more = cfg.footer && cfg.footer(wrap);
      if (more) {   // after the items, set apart: a way to make a new one
        const node = press(el('button', 'pk-item pk-footer', more.label), more.run);
        node.id = id + '-footer';
        node.appendChild(ns.svg(more.icon, 16));
        list.appendChild(node);
      }
      mark(null);
      search.hidden =!cfg.source && cfg.searchFrom !== undefined && index < cfg.searchFrom;   // a short list needs no search
      if (cfg.source) {
        status.textContent = '';
        if (loading) status.appendChild(ns.balls(cfg.text.loading, 'pk-balls'));
        else if (failed) status.textContent = failed;
        else if (!found.length) status.textContent = cfg.empty(wrap);
        count.textContent = found.length ? cfg.text.showing(found.length, Math.max(total, found.length)) : '';
      } else {
        filter();
      }
      if (!menu.hidden) place();
    }

    /** Ask for the next batch while the list is scrolled near its end, or is too short to scroll and there is more. */
    function fillList() {
      if (loading || !found.length || offset >= total) return;
      if (list.scrollHeight - list.scrollTop - list.clientHeight < NEAR_END_PX) load(true);
    }

    function load(next) {
      if (!next) { found = []; offset = 0; total = 0; }
      failed = '';
      loading = true;
      render();
      const mine = ++token;
      cfg.source(search.value.trim(), offset, function (answer) {
        if (mine !== token) return;
        loading = false;
        if (answer.error) {
          failed = answer.error;
          render();
          return;
        }
        found = found.concat(answer.items);
        offset = answer.next;
        total = answer.total;
        render();
        fillList();
      });
    }

    /** Lay the list out in the window: below the button, or above it when there is not enough room below, and never past an edge. */
    function place() {
      const box = button.getBoundingClientRect();
      const view = document.documentElement.clientWidth;
      list.style.maxHeight = '';
      const cap = parseFloat(getComputedStyle(list).maxHeight);
      menu.style.width = box.width + 'px';   // a stylesheet may make it wider
      const width = menu.offsetWidth;
      menu.style.left = Math.max(8, Math.min(cfg.alignRight ? box.right - width : box.left, view - 8 - width)) + 'px';
      const chrome = menu.offsetHeight - list.offsetHeight;   // search box and padding
      const below = window.innerHeight - box.bottom - 8;
      const above = box.top - 8;
      const up = menu.offsetHeight > below && above > below;
      menu.classList.toggle('up', up);
      menu.style.top = up ? 'auto' : box.bottom + 'px';
      menu.style.bottom = up ? window.innerHeight - box.top + 'px' : 'auto';
      list.style.maxHeight = Math.max(80, Math.min(cap, Math.max(up ? above : below, 120) - chrome)) + 'px';
    }

    function outside(event) { if (!wrap.contains(event.target)) close(); }
    function scrolled(event) { if (!menu.contains(event.target)) close(); }   // the list scrolling itself does not close it
    function escape(event) {
      if (event.key !== 'Escape') return;
      event.stopPropagation();
      close();
      button.focus();
    }

    function close() {
      menu.hidden = true;
      button.setAttribute('aria-expanded', 'false');
      token++;   // a batch still on its way is let go
      clearTimeout(timer);
      document.removeEventListener('mousedown', outside, true);
      document.removeEventListener('keydown', escape, true);
      document.removeEventListener('scroll', scrolled, true);
      window.removeEventListener('resize', close);
      if (closeOpen === close) closeOpen = null;
    }

    function open() {
      if (closeOpen) closeOpen();
      menu.hidden = false;
      button.setAttribute('aria-expanded', 'true');
      closeOpen = close;
      document.addEventListener('mousedown', outside, true);
      document.addEventListener('keydown', escape, true);
      document.addEventListener('scroll', scrolled, true);
      window.addEventListener('resize', close);
      search.value = '';
      if (cfg.onOpen) cfg.onOpen(wrap);
      if (cfg.source) load(false); else render();   // built on open, so it reflects the other rows and the latest lists
      mark(menu.querySelector('.pk-item.selected'));
      if (!search.hidden) search.focus({ preventScroll: true });
    }

    button.addEventListener('click', function () { if (menu.hidden) open(); else close(); });
    clear.addEventListener('mousedown', function (event) { event.preventDefault(); });
    clear.addEventListener('click', function () { choose([]); });
    search.addEventListener('input', function () {
      if (!cfg.source) { filter(); return; }
      clearTimeout(timer);
      timer = setTimeout(function () { load(false); }, SEARCH_DELAY_MS);
    });
    list.addEventListener('scroll', function () { if (cfg.source) fillList(); });
    wrap.addEventListener('keydown', function (event) {
      const isOpen = !menu.hidden;
      const onField = event.target === button || event.target === search;
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        if (!isOpen) { open(); return; }
        const items = enabledItems();
        const at = items.indexOf(active) + (event.key === 'ArrowDown' ? 1 : -1);
        if (items.length) mark(items[Math.max(0, Math.min(items.length - 1, at))]);
      } else if (isOpen && onField && (event.key === 'Enter' || (event.key === ' ' && event.target === button))) {
        event.preventDefault();   // the button's own click would close the list
        const item = active || enabledItems()[0];
        if (item) item.click();
      } else if (isOpen && event.key === 'Tab') {
        close();
      }
    });

    wrap.refresh = paint;
    wrap.rebuildOpen = function () { if (!menu.hidden) render(); };
    wrap.setPicked = function (entries) { chosen = entries; paint(); };
    wrap.getPicked = function () { return chosen; };
    paint();
    return wrap;
  }

  ns.picker = { make: make };
})(window.MfgUi);
