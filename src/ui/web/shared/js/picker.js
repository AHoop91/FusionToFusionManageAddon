/**
 * The one picker of the add-in's pages, as ``ns.picker``: a button that opens a list of ordinary page elements (a native <select> popup was slow
 * to open in Fusion's embedded browser). The list is laid out in the window, so a scrolling card does not cut it off; it closes on a click
 * elsewhere, on Escape, on a scroll of the page and when another picker opens. Arrow keys, Enter and Escape work as on a native one.
 * Layer: UI (shared page element).
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
 * How it looks: className on the wrapper, buttonClass on the button; inlineSearch -> the search box is typed into the button's own field
 * (it covers the button's text while the list is open) instead of sitting at the top of the list.
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

  // A picker is one object ``p``: its page elements, its ``cfg`` and the state below. The functions of this module each take ``p``.
  //   chosen [{value, label}]; active: the item the arrow keys are on; found: a source's items read so far for the text in the search box;
  //   offset, total: where the next batch starts and how many the source holds; loading: a batch is on its way; failed: what went wrong;
  //   token: a batch is only taken if no newer search has taken its place; timer: the search box's rest.
  function createPicker(cfg, selected) {
    return {
      cfg: cfg,
      id: 'pk' + (++seq),
      inline: !!cfg.inlineSearch,
      wrap: el('div', cfg.className ? 'pk ' + cfg.className : 'pk'),
      input: cfg.valueClass ? el('input', cfg.valueClass) : null,
      chips: cfg.multi ? el('div', 'pk-chips') : null,
      button: el('button', cfg.buttonClass ? 'pk-btn ' + cfg.buttonClass : 'pk-btn'),
      text: el('span', 'pk-text'),
      menu: el('div', 'pk-menu'),
      search: el('input', 'pk-search'),
      clear: el('button', 'pk-clear'),   // pinned above the scrolling list
      count: el('p', 'pk-count'),   // "Showing 50 of 1,234"
      list: el('div', 'pk-list'),
      status: el('p', 'pk-status'),   // the balls while a batch is on its way, what went wrong, or that there is nothing
      chosen: selected ? [{ value: selected }] : [],
      active: null,
      found: [],
      offset: 0,
      total: 0,
      loading: false,
      failed: '',
      token: 0,
      timer: 0
    };
  }

  /** Set the attributes of the page elements and put them together. */
  function assembleParts(p) {
    const cfg = p.cfg;
    if (p.input) p.input.type = 'hidden';
    p.button.type = 'button';
    p.button.setAttribute('aria-haspopup', 'listbox');
    p.button.setAttribute('aria-expanded', 'false');
    if (cfg.ariaLabel) p.button.setAttribute('aria-label', cfg.ariaLabel);
    p.menu.hidden = true;
    p.search.type = 'text';
    p.search.placeholder = cfg.search;
    p.search.setAttribute('aria-label', cfg.search);
    p.search.autocomplete = 'off';
    p.search.spellcheck = false;
    p.clear.type = 'button';
    p.list.id = p.id;
    p.list.setAttribute('role', 'listbox');
    if (cfg.multi) p.list.setAttribute('aria-multiselectable', 'true');
    p.button.setAttribute('aria-controls', p.id);
    p.button.appendChild(p.text);
    if (p.inline) p.wrap.classList.add('pk-inline');
    const menuParts = p.inline ? [p.clear, p.count, p.list, p.status] : [p.search, p.clear, p.count, p.list, p.status];
    menuParts.forEach(function (part) { p.menu.appendChild(part); });
    [p.input, p.chips, p.button, p.inline ? p.search : null, p.menu].forEach(function (part) { if (part) p.wrap.appendChild(part); });
  }

  function currentValue(p) { return p.chosen.length ? p.chosen[0].value : ''; }
  function labelOf(p, entry) { return p.cfg.label ? p.cfg.label(entry.value) : entry.label; }

  /** The button, the chips and the value input from what is chosen. */
  function paint(p) {
    const cfg = p.cfg;
    if (p.input) p.input.value = currentValue(p);
    p.text.textContent = !cfg.multi && p.chosen.length ? labelOf(p, p.chosen[0]) : cfg.placeholder;
    p.button.classList.toggle('placeholder', cfg.multi || !p.chosen.length);
    if (cfg.tip) p.button.title = cfg.tip();
    if (p.chips) paintChips(p);
  }

  function paintChips(p) {
    p.chips.textContent = '';
    p.chosen.forEach(function (entry, i) {
      const chip = el('span', 'pk-chip', labelOf(p, entry));
      const remove = el('button', 'pk-chip-x', '×');
      remove.type = 'button';
      remove.title = p.cfg.text.clear;
      remove.setAttribute('aria-label', p.cfg.text.clear + ': ' + labelOf(p, entry));
      remove.addEventListener('click', function () { p.chosen.splice(i, 1); changed(p); });
      chip.appendChild(remove);
      p.chips.appendChild(chip);
    });
    p.chips.hidden = !p.chosen.length;
  }

  function changed(p) {
    paint(p);
    p.wrap.dispatchEvent(new Event('pick'));
  }

  function choose(p, items) {
    p.chosen = items;
    p.close();
    p.button.focus();
    changed(p);
  }

  function enabledItems(p) {
    return Array.prototype.filter.call(p.menu.querySelectorAll('.pk-item, .pk-act'), function (item) { return !item.disabled && !item.closest('[hidden]'); });
  }

  /** The arrow keys' mark on an entry (and on the row that holds it, whose buttons then show). */
  function light(node, on) {
    node.classList.toggle('active', on);
    const line = node.closest('.pk-row');
    if (line) line.classList.toggle('on', on);
  }

  function mark(p, item) {
    if (p.active) light(p.active, false);
    p.active = item;
    [p.button, p.search].forEach(function (part) { part.setAttribute('aria-activedescendant', item ? item.id : ''); });
    if (!item) return;
    light(item, true);
    item.scrollIntoView({ block: 'nearest' });
  }

  /** ``node`` as a button of the list that closes it, gives the focus back to the picker's button and then runs ``run``. */
  function press(p, node, run) {
    node.type = 'button';
    node.addEventListener('mousedown', function (event) { event.preventDefault(); });
    node.addEventListener('click', function () { p.close(); p.button.focus(); run(); });
    return node;
  }

  /** The button of one item, marked as chosen or taken. */
  function buildItem(p, item, index, taken) {
    const cfg = p.cfg;
    const node = el('button', 'pk-item', item.label);
    node.type = 'button';
    node.id = p.id + '-' + index;
    node.setAttribute('role', 'option');
    if (item.detail) node.appendChild(el('span', 'pk-detail', item.detail));
    const isChosen = p.chosen.some(function (entry) { return entry.value === item.value; });
    node.setAttribute('aria-selected', String(isChosen));
    if (isChosen) {
      node.classList.add('selected');
      node.disabled = !!cfg.multi;   // one item is not chosen twice
    } else if (taken.indexOf(item.value) >= 0) {
      node.disabled = true;
      node.title = cfg.text.taken;
    }
    node.addEventListener('mousedown', function (event) { event.preventDefault(); });   // the focus stays where it is
    node.addEventListener('click', function () {
      const entry = { value: item.value, label: item.label };
      choose(p, cfg.multi ? p.chosen.concat([entry]) : [entry]);
    });
    return node;
  }

  /** The item and its small buttons side by side. */
  function buildActionRow(p, node, item) {
    const line = el('div', 'pk-row');
    line.appendChild(node);
    item.actions.forEach(function (action, n) {
      const act = press(p, el('button', 'pk-act ' + (action.className || '')), function () { action.run(item); });
      act.id = node.id + '-' + n;
      act.title = action.label;
      act.setAttribute('aria-label', action.label);
      act.appendChild(ns.svg(action.icon, 16));
      line.appendChild(act);
    });
    return line;
  }

  function buildRow(p, item, index, taken) {
    const node = buildItem(p, item, index, taken);
    return item.actions ? buildActionRow(p, node, item) : node;
  }

  /** Hide the items that do not match the search box, and the groups left empty. */
  function filter(p) {
    const term = p.search.value.trim().toLowerCase();
    let shown = 0;
    p.list.querySelectorAll('.pk-section').forEach(function (section) {
      let visible = 0;
      section.querySelectorAll('.pk-item').forEach(function (item) {
        const hide = !!term && item.textContent.toLowerCase().indexOf(term) < 0;
        (item.closest('.pk-row') || item).hidden = hide;
        if (!hide) visible++;
      });
      section.hidden = visible === 0;
      shown += visible;
    });
    p.status.textContent = shown ? '' : p.cfg.empty(p.wrap);
  }

  function buildSection(group) {
    const section = el('div', 'pk-section');
    section.setAttribute('role', 'group');
    if (group.title) {   // a list of one kind has no heading
      section.appendChild(el('div', 'pk-group', group.title));
      section.setAttribute('aria-label', group.title);
    }
    return section;
  }

  /** Add the groups to the list; gives the number of items shown. */
  function renderGroups(p, groups, taken) {
    let index = 0;
    groups.forEach(function (group) {
      const section = buildSection(group);
      group.items.forEach(function (item) { section.appendChild(buildRow(p, item, index++, taken)); });
      p.list.appendChild(section);
    });
    return index;
  }

  /** After the items, set apart: a way to make a new one. */
  function renderFooter(p) {
    const more = p.cfg.footer && p.cfg.footer(p.wrap);
    if (!more) return;
    const node = press(p, el('button', 'pk-item pk-footer', more.label), more.run);
    node.id = p.id + '-footer';
    node.appendChild(ns.svg(more.icon, 16));
    p.list.appendChild(node);
  }

  /** A source's status line (the balls, the error or that there is nothing) and its count. */
  function renderSourceStatus(p) {
    p.status.textContent = '';
    if (p.loading) p.status.appendChild(ns.balls(p.cfg.text.loading, 'pk-balls'));
    else if (p.failed) p.status.textContent = p.failed;
    else if (!p.found.length) p.status.textContent = p.cfg.empty(p.wrap);
    p.count.textContent = p.found.length ? p.cfg.text.showing(p.found.length, Math.max(p.total, p.found.length)) : '';
  }

  /** The list from what is chosen, the other rows and the latest items. */
  function render(p) {
    const cfg = p.cfg;
    const taken = cfg.takenValues ? cfg.takenValues(p.wrap) : [];
    const groups = cfg.source ? [{ title: '', items: p.found }] : cfg.groups(currentValue(p), p.wrap);
    p.list.textContent = '';
    p.clear.hidden = cfg.multi || !!cfg.required || !p.chosen.length;
    if (!p.clear.hidden) p.clear.textContent = cfg.text.clear;
    const shownCount = renderGroups(p, groups, taken);
    renderFooter(p);
    mark(p, null);
    p.search.hidden = !cfg.source && cfg.searchFrom !== undefined && shownCount < cfg.searchFrom;   // a short list needs no search
    if (cfg.source) renderSourceStatus(p); else filter(p);
    if (!p.menu.hidden) place(p);
  }

  /** Ask for the next batch while the list is scrolled near its end, or is too short to scroll and there is more. */
  function fillList(p) {
    if (p.loading || !p.found.length || p.offset >= p.total) return;
    if (p.list.scrollHeight - p.list.scrollTop - p.list.clientHeight < NEAR_END_PX) load(p, true);
  }

  function takeBatch(p, answer) {
    p.loading = false;
    if (answer.error) {
      p.failed = answer.error;
      render(p);
      return;
    }
    p.found = p.found.concat(answer.items);
    p.offset = answer.next;
    p.total = answer.total;
    render(p);
    fillList(p);
  }

  function load(p, next) {
    if (!next) { p.found = []; p.offset = 0; p.total = 0; }
    p.failed = '';
    p.loading = true;
    render(p);
    const mine = ++p.token;
    p.cfg.source(p.search.value.trim(), p.offset, function (answer) {
      if (mine !== p.token) return;
      takeBatch(p, answer);
    });
  }

  /** The search box over the button's text, leaving room for its arrow. */
  function placeInlineSearch(p) {
    p.search.style.left = p.button.offsetLeft + 1 + 'px';
    p.search.style.top = p.button.offsetTop + 1 + 'px';
    p.search.style.width = p.button.offsetWidth - 34 + 'px';
    p.search.style.height = p.button.offsetHeight - 2 + 'px';
  }

  /** Lay the list out in the window: below the button, or above it when there is not enough room below, and never past an edge. */
  function place(p) {
    const menu = p.menu;
    const list = p.list;
    const box = p.button.getBoundingClientRect();
    const view = document.documentElement.clientWidth;
    list.style.maxHeight = '';
    const cap = parseFloat(getComputedStyle(list).maxHeight);
    menu.style.width = box.width + 'px';   // a stylesheet may make it wider
    p.wrap.classList.toggle('searching', p.inline && !p.search.hidden);
    if (p.inline) placeInlineSearch(p);
    const width = menu.offsetWidth;
    menu.style.left = Math.max(8, Math.min(p.cfg.alignRight ? box.right - width : box.left, view - 8 - width)) + 'px';
    const chrome = menu.offsetHeight - list.offsetHeight;   // search box and padding
    const below = window.innerHeight - box.bottom - 8;
    const above = box.top - 8;
    const up = menu.offsetHeight > below && above > below;
    menu.classList.toggle('up', up);
    p.wrap.classList.toggle('opens-up', up);   // a stylesheet joins the list to the button on the side it opens
    menu.style.top = up ? 'auto' : box.bottom + 'px';
    menu.style.bottom = up ? window.innerHeight - box.top + 'px' : 'auto';
    list.style.maxHeight = Math.max(80, Math.min(cap, Math.max(up ? above : below, 120) - chrome)) + 'px';
  }

  function closeMenu(p) {
    p.menu.hidden = true;
    p.wrap.classList.remove('searching');
    p.button.setAttribute('aria-expanded', 'false');
    p.token++;   // a batch still on its way is let go
    clearTimeout(p.timer);
    document.removeEventListener('mousedown', p.outside, true);
    document.removeEventListener('keydown', p.escape, true);
    document.removeEventListener('scroll', p.scrolled, true);
    window.removeEventListener('resize', p.close);
    if (closeOpen === p.close) closeOpen = null;
  }

  function openMenu(p) {
    const cfg = p.cfg;
    if (closeOpen) closeOpen();
    p.menu.hidden = false;
    p.button.setAttribute('aria-expanded', 'true');
    closeOpen = p.close;
    document.addEventListener('mousedown', p.outside, true);
    document.addEventListener('keydown', p.escape, true);
    document.addEventListener('scroll', p.scrolled, true);
    window.addEventListener('resize', p.close);
    p.search.value = '';
    if (p.inline) p.search.placeholder = !cfg.multi && p.chosen.length ? labelOf(p, p.chosen[0]) : cfg.search;   // what is chosen stays readable until typing
    if (cfg.onOpen) cfg.onOpen(p.wrap);
    if (cfg.source) load(p, false); else render(p);   // built on open, so it reflects the other rows and the latest lists
    mark(p, p.menu.querySelector('.pk-item.selected'));
    if (!p.search.hidden) p.search.focus({ preventScroll: true });
  }

  /** The handlers that close the list, kept on ``p`` so the same functions are added to and removed from the document. */
  function defineCloseHandlers(p) {
    p.close = function () { closeMenu(p); };
    p.outside = function (event) { if (!p.wrap.contains(event.target)) p.close(); };
    p.scrolled = function (event) { if (!p.menu.contains(event.target)) p.close(); };   // the list scrolling itself does not close it
    p.escape = function (event) {
      if (event.key !== 'Escape') return;
      event.stopPropagation();
      p.close();
      p.button.focus();
    };
  }

  function moveActive(p, event) {
    event.preventDefault();
    if (p.menu.hidden) { openMenu(p); return; }
    const items = enabledItems(p);
    const at = items.indexOf(p.active) + (event.key === 'ArrowDown' ? 1 : -1);
    if (items.length) mark(p, items[Math.max(0, Math.min(items.length - 1, at))]);
  }

  function isSelectKey(p, event) {
    const onField = event.target === p.button || event.target === p.search;
    return !p.menu.hidden && onField && (event.key === 'Enter' || (event.key === ' ' && event.target === p.button));
  }

  function selectActive(p, event) {
    event.preventDefault();   // the button's own click would close the list
    const item = p.active || enabledItems(p)[0];
    if (item) item.click();
  }

  function handleKeydown(p, event) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') moveActive(p, event);
    else if (isSelectKey(p, event)) selectActive(p, event);
    else if (!p.menu.hidden && event.key === 'Tab') p.close();
  }

  function handleSearchInput(p) {
    if (!p.cfg.source) { filter(p); return; }
    clearTimeout(p.timer);
    p.timer = setTimeout(function () { load(p, false); }, SEARCH_DELAY_MS);
  }

  function bindEvents(p) {
    p.button.addEventListener('click', function () { if (p.menu.hidden) openMenu(p); else p.close(); });
    p.clear.addEventListener('mousedown', function (event) { event.preventDefault(); });
    p.clear.addEventListener('click', function () { choose(p, []); });
    p.search.addEventListener('input', function () { handleSearchInput(p); });
    p.list.addEventListener('scroll', function () { if (p.cfg.source) fillList(p); });
    p.wrap.addEventListener('keydown', function (event) { handleKeydown(p, event); });
  }

  function make(cfg, selected) {
    const p = createPicker(cfg, selected);
    assembleParts(p);
    defineCloseHandlers(p);
    bindEvents(p);
    p.wrap.refresh = function () { paint(p); };
    p.wrap.rebuildOpen = function () { if (!p.menu.hidden) render(p); };
    p.wrap.setPicked = function (entries) { p.chosen = entries; paint(p); };
    p.wrap.getPicked = function () { return p.chosen; };
    paint(p);
    return p.wrap;
  }

  ns.picker = { make: make };
})(window.MfgUi);
