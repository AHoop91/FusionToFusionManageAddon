/**
 * Publish Item panel: the filters of the Bill of Materials table, as ``ns.bomFilters``.
 *
 * One Filters drop-down with a tick list (any number on at once, each with how many lines it holds), and ``visible``, which says
 * which lines pass the ones that are on. The choice is kept across redraws.
 */
(function (ns) {
  'use strict';

  const ui = ns.pubUi;
  const el = ui.el;
  const model = ns.bomModel;

  // A row shows when it matches any filter that is on (all rows when none is). "hidden" is not a filter of its own: see ``visible``.
  const FILTERS = [
    { id: 'review',  label: 'Review',      title: 'Item number differs from Fusion Manage and no action is chosen yet' },
    { id: 'new',     label: 'New',         title: 'Not in Fusion Manage yet, with the Fusion Manage line each is paired with' },
    { id: 'added',   label: 'Added',       title: 'Picked with Add Existing Items: publishing adds them to the Fusion Manage BOM' },
    { id: 'changed', label: 'Update',     title: 'Quantity differs from Fusion Manage' },
    { id: 'extra',   label: 'Fusion Manage Only', title: 'Only in Fusion Manage' },
    { id: 'skipped', label: 'Skipped',     title: 'No item number, a number shared with another component, or below such a line: publishing creates no item for them' },
    { id: 'hidden',  label: 'Show Hidden Components', title: 'Hidden in the Fusion component tree', separate: true },
  ];
  const on = {};   // filter id -> true while on

  /** Is a filter on that narrows the lines (Show Hidden Components does not)? */
  function narrowing() {
    return Object.keys(on).some(function (id) { return id !== 'hidden'; });
  }

  /** The number of lines each filter holds. */
  function countsOf(items) {
    const counts = {};
    items.forEach(function (item) { model.groupsOf(item).forEach(function (g) { counts[g] = (counts[g] || 0) + 1; }); });
    return counts;
  }

  /**
   * The Filters drop-down. ``onChange`` runs after a filter is flipped; ``note`` (optional text) heads the list.
   */
  function menu(items, onChange, note) {
    const counts = countsOf(items);
    const root = el('div', 'pub-cmp-menu');
    const trigger = el('button', 'pub-cmp-menu-btn');
    trigger.type = 'button';
    trigger.setAttribute('aria-haspopup', 'true');
    trigger.setAttribute('aria-expanded', 'false');
    trigger.appendChild(el('span', '', 'Filters'));
    const badge = el('span', 'pub-cmp-filter-count');
    trigger.appendChild(badge);
    trigger.appendChild(ui.svg(['M6 9l6 6 6-6']));

    const pop = el('div', 'pub-cmp-menu-pop');
    pop.hidden = true;
    if (note) pop.appendChild(el('p', 'pub-cmp-menu-note', note));
    const boxes = {};
    FILTERS.forEach(function (f) {
      const row = el('label', 'pub-cmp-menu-item' + (f.separate ? ' pub-cmp-menu-sep' : ''));
      row.title = f.title;
      const box = el('input');
      box.type = 'checkbox';
      box.addEventListener('change', function () { flip(f.id); });
      boxes[f.id] = box;
      row.appendChild(box);
      row.appendChild(el('span', 'pub-cmp-menu-text', f.label));
      row.appendChild(el('span', 'pub-cmp-filter-count', String(counts[f.id] || 0)));
      pop.appendChild(row);
    });
    const clear = el('button', 'pub-cmp-menu-clear', 'Clear filters');
    clear.type = 'button';
    clear.addEventListener('click', function () {
      Object.keys(on).forEach(function (id) { delete on[id]; });
      paint();
      onChange();
    });
    pop.appendChild(clear);
    root.appendChild(trigger);
    root.appendChild(pop);

    function flip(id) {
      if (on[id]) delete on[id]; else on[id] = true;
      paint();
      onChange();
    }
    function paint() {
      const active = Object.keys(on).length;
      FILTERS.forEach(function (f) { boxes[f.id].checked = !!on[f.id]; });
      badge.textContent = String(active);
      badge.hidden = !active;
      trigger.classList.toggle('on', active > 0);
      clear.disabled = !active;
    }

    function close() {
      pop.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
      document.removeEventListener('mousedown', outside, true);
      document.removeEventListener('keydown', onEscape, true);
    }
    function outside(event) { if (!root.contains(event.target)) close(); }
    function onEscape(event) { if (event.key === 'Escape') close(); }
    trigger.addEventListener('click', function () {
      if (!pop.hidden) { close(); return; }
      pop.hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
      document.addEventListener('mousedown', outside, true);
      document.addEventListener('keydown', onEscape, true);
    });

    paint();
    return root;
  }

  /**
   * Which lines pass the filters: the lines of the filters that are on, plus the assemblies above them so a line keeps its place in the
   * tree; null when nothing is left out. Show Hidden Components is not a filter of its own: off, components hidden in Fusion are left
   * out; on, they join the rest.
   */
  function visible(items) {
    const narrow = narrowing();
    if (!narrow && on.hidden) return null;
    const show = items.map(function (item) {
      if (item.root) return true;
      if (item.hidden && !on.hidden) return false;
      return !narrow || model.groupsOf(item).some(function (g) { return g !== 'hidden' && on[g]; });
    });
    let need = Infinity;   // level a row must be below to be the ancestor of a shown row further down
    for (let i = items.length - 1; i >= 0; i--) {
      if (show[i]) need = Math.min(need, items[i].level);
      else if (need !== Infinity && items[i].level < need) { show[i] = true; need = items[i].level; }
    }
    return show;
  }

  ns.bomFilters = { menu: menu, visible: visible, narrowing: narrowing };
})(window.MfgUi);
