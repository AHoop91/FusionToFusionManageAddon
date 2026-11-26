/**
 * The Make or buy section of the Items card in Settings (UI layer): the field and its Make and Buy values, the source link field, the suffix
 * and the list of fields a bought version copies. workspaces.js builds the card and calls ``ns.makeOrBuy.buildSection(host, kind, config)``;
 * ``host`` is the one object that hands this file what it needs from the card, so nothing here reaches into workspaces.js. ``host`` holds:
 * ``fields(kindId)`` and ``fieldsError(kindId)`` (the loaded Fusion Manage fields and why they are missing), ``kindOf(wrap)``, ``takenFields(wrap, except)``,
 * ``componentValue(wrap)``, ``fieldItems(fields, current)``, ``fieldLabel(value)``, ``picklistFor(kindId, fieldId)``, ``valueCfg(options)``,
 * ``pickText`` and the card's layout helpers ``heading(text)``, ``describe(text)``, ``lockedSection(children)`` and ``blockTitle(title, tip)``.
 * Five settings, all Fusion Manage ids or links chosen from what the workspace holds (nothing is known of the tenant's field ids).
 */
(function (ns) {
  'use strict';

  const t = ns.i18n.t;
  const el = ns.el;
  const makePicker = ns.picker.make;

  // ---- The fields of the section ----------------------------------------------

  /** The fields the Make or buy field and the source link field hold, as a list so they can join the "taken" values. */
  function makeBuyFields(wrap) {
    const panel = wrap.closest('.ws-kind');
    if (!panel) return [];
    return ['.ws-mb-field', '.ws-mb-source'].map(function (selector) {
      const input = panel.querySelector(selector);
      return input ? input.value : '';
    }).filter(Boolean);
  }

  /** Picker config for one Make or buy field: its ``valueClass``, what it lists (``keep(field)``) and its ``text`` (functions: the language is not known when this file loads). */
  function makeBuyFieldCfg(host, valueClass, keep, text) {
    return {
      valueClass: valueClass,
      text: host.pickText,
      alignRight: true,
      get placeholder() { return text.placeholder(); },
      get search() { return t('settings.ws_search_fields'); },
      empty: function (wrap) {
        const kind = host.kindOf(wrap);
        if (host.fields(kind).length) return text.none();
        return host.fieldsError(kind) || t('settings.ws_no_fields_loaded');
      },
      takenValues: function (wrap) {
        const own = wrap.querySelector('.' + valueClass);
        return host.takenFields(wrap, own ? own.value : '');
      },
      label: host.fieldLabel,
      groups: function (current, wrap) {
        const items = host.fieldItems(host.fields(host.kindOf(wrap)).filter(keep), current);
        return items.length ? [{ title: text.group(), items: items }] : [];
      },
    };
  }

  function makeBuyFieldPick(host) {
    return makeBuyFieldCfg(host, 'ws-mb-field', function (f) { return !!f.picklist; }, {
      placeholder: function () { return t('settings.ws_make_buy_field_placeholder'); },
      group: function () { return t('settings.ws_make_buy_group_field'); },
      none: function () { return t('settings.ws_make_buy_no_field'); },
    });
  }

  function makeBuySourcePick(host) {
    return makeBuyFieldCfg(host, 'ws-mb-source', function (f) { return !!f.link_lookup; }, {
      placeholder: function () { return t('settings.ws_link_placeholder'); },
      group: function () { return t('settings.ws_make_buy_group_source'); },
      none: function () { return t('settings.ws_make_buy_no_source'); },
    });
  }

  /** The field the item number is mapped to (the add-in builds a bought item's number, so it is never copied). */
  function numberValue(wrap) {
    const panel = wrap.closest('.ws-kind');
    const row = panel && Array.prototype.filter.call(panel.querySelectorAll('.ws-row:not(.ws-static-row)'), function (r) { return r.querySelector('.ws-source').value === 'item_number'; })[0];   // as ``ITEM_NUMBER_SOURCE`` in ``workspace_models``
    const input = row && row.querySelector('.ws-fm-field');
    return input && input.value ? [input.value] : [];
  }

  // ---- The copy list of the Make or buy section ----------------------------
  // ``ctx`` is the state of one list: ``host``, ``kindId``, ``skip`` (ids not copied), ``shut`` (titles of the folded groups), ``query`` (the search, lower case)
  // and the elements ``box``, ``search``, ``all``, ``none``, ``list`` and ``count``.

  function copyMatches(ctx, f) { return (f.title + ' ' + f.id).toLowerCase().indexOf(ctx.query) >= 0; }

  /** What the add-in sets itself, and the fields that can be chosen: those the form shows (a picture is never copied, a hidden or computed field is
   *  never written, and once the sections are known, a field in none of them is not on the form). */
  function splitCopyFields(ctx) {
    const box = ctx.box;
    const panel = box.closest('.ws-kind');
    const known = panel ? ctx.host.fields(ctx.kindId) : [];
    const laidOut = known.some(function (f) { return !!f.section; });
    const set = panel ? makeBuyFields(box).concat(ctx.host.componentValue(box), numberValue(box)) : [];
    const fields = known.filter(function (f) { return !/image/i.test(f.type || ''); });
    const onForm = function (f) { return f.shown !== false && !f.computed && (!laidOut || !!f.section); };
    return { fixed: fields.filter(function (f) { return set.indexOf(f.id) >= 0; }), free: fields.filter(function (f) { return set.indexOf(f.id) < 0 && onForm(f); }) };
  }

  /** The free fields by section, in the order of the form (the title of a field in no section is empty and comes last). */
  function groupCopyFields(free) {
    const found = [];
    free.forEach(function (f) {
      const title = f.section || '';
      let group = found.filter(function (g) { return g.title === title; })[0];
      if (!group) { group = { title: title, order: f.section_order || 0, fields: [] }; found.push(group); }
      group.fields.push(f);
    });
    found.forEach(function (g) { g.fields.sort(function (x, y) { return (x.field_order || 0) - (y.field_order || 0); }); });
    return found.sort(function (x, y) { return x.order - y.order; });
  }

  function buildCopyRow(ctx, f, locked) {
    const line = el('label', 'ws-copy-row' + (locked ? ' locked' : ''));
    const tick = el('input');
    tick.type = 'checkbox';
    tick.checked = locked || !ctx.skip.has(f.id);
    tick.disabled = locked;
    tick.dataset.id = f.id;
    tick.addEventListener('change', function () {
      if (tick.checked) ctx.skip.delete(f.id); else ctx.skip.add(f.id);
      ctx.box.rebuild();
    });
    const name = el('span', 'ws-copy-name', f.title);
    name.title = f.title;   // the shared tooltip shows it when the name is cut short
    const id = el('span', 'ws-copy-id', f.id);
    id.title = f.id;
    line.append(tick, name, id);
    return line;
  }

  /** The tick of a group's bar: all of its fields, or some of them (indeterminate). */
  function buildCopyGroupTick(ctx, group, copied) {
    const { title, fields, locked } = group;
    const mark = el('input');
    mark.type = 'checkbox';
    mark.checked = copied === fields.length;
    mark.indeterminate = copied > 0 && copied < fields.length;
    mark.disabled = locked;
    mark.setAttribute('aria-label', title);
    mark.dataset.group = title;
    mark.addEventListener('click', function (event) { event.stopPropagation(); });
    mark.addEventListener('change', function () {
      fields.forEach(function (f) { if (mark.checked) ctx.skip.delete(f.id); else ctx.skip.add(f.id); });
      ctx.box.rebuild();
    });
    return mark;
  }

  /** The bar of a group: chevron, title, tick, how many are copied. Clicking it folds the group (not while searching). */
  function buildCopyGroupHead(ctx, group, open) {
    const { title, fields, locked } = group;
    const copied = fields.filter(function (f) { return locked || !ctx.skip.has(f.id); }).length;
    const head = el('div', 'ws-copy-head');
    head.setAttribute('role', 'button');
    head.tabIndex = 0;
    head.setAttribute('aria-expanded', open ? 'true' : 'false');
    head.dataset.group = title;
    const mark = buildCopyGroupTick(ctx, group, copied);
    head.append(el('span', 'ws-copy-chevron'), mark, el('span', 'ws-copy-title', title), el('span', 'ws-copy-of', t('settings.ws_make_buy_copy_group_count', { count: copied, total: fields.length })));
    function fold() { if (ctx.shut.has(title)) ctx.shut.delete(title); else ctx.shut.add(title); ctx.box.rebuild(); }
    head.addEventListener('click', function () { if (!ctx.query) fold(); });
    head.addEventListener('keydown', function (event) {
      if (!ctx.query && (event.key === 'Enter' || event.key === ' ') && event.target === head) { event.preventDefault(); fold(); }
    });
    return head;
  }

  /** One folding group: its bar and its rows. */
  function buildCopyGroup(ctx, title, fields, locked) {
    const open = !!ctx.query || !ctx.shut.has(title);
    const part = el('div', 'ws-copy-group' + (open ? ' open' : ''));
    part.appendChild(buildCopyGroupHead(ctx, { title: title, fields: fields, locked: locked }, open));
    if (open) {
      const rows = el('div', 'ws-copy-rows');
      fields.forEach(function (f) { rows.appendChild(buildCopyRow(ctx, f, locked)); });
      part.appendChild(rows);
    }
    return part;
  }

  /** What has the focus in the list, to find it again after the list is rebuilt (or null). */
  function readCopyFocus(list) {
    const on = document.activeElement;
    if (!on || !list.contains(on)) return null;
    return { id: on.dataset.id, group: on.dataset.group, head: on.classList.contains('ws-copy-head') };
  }

  function restoreCopyFocus(list, focus) {
    if (!focus) return;
    const again = focus.id ? list.querySelector('input[data-id="' + focus.id + '"]') :
      Array.prototype.filter.call(list.querySelectorAll(focus.head ? '.ws-copy-head' : 'input[data-group]'), function (n) { return n.dataset.group === focus.group; })[0];
    if (again) again.focus({ preventScroll: true });
  }

  /** Fill the list with the groups that match the search (or a line saying why there are none). */
  function fillCopyList(ctx, fixed, free) {
    const list = ctx.list;
    const own = fixed.filter(function (f) { return copyMatches(ctx, f); });
    if (own.length) list.appendChild(buildCopyGroup(ctx, t('settings.ws_make_buy_copy_group_set'), own, true));
    groupCopyFields(free.filter(function (f) { return copyMatches(ctx, f); })).forEach(function (g) {
      list.appendChild(buildCopyGroup(ctx, g.title || t('settings.ws_make_buy_copy_group_other'), g.fields, false));
    });
    if (!list.children.length) list.appendChild(el('p', 'ws-copy-empty', t('settings.ws_no_match_fields')));
  }

  function rebuildCopyList(ctx) {
    const { fixed, free } = splitCopyFields(ctx);
    const list = ctx.list;
    const top = list.scrollTop;
    const focus = readCopyFocus(list);   // what has the focus is rebuilt: find it again after
    list.replaceChildren();
    ctx.box.classList.toggle('searching', !!ctx.query);
    const empty = !fixed.length && !free.length;
    ctx.search.disabled = ctx.all.disabled = ctx.none.disabled = empty;
    if (empty) {
      list.appendChild(el('p', 'ws-copy-empty', ctx.host.fieldsError(ctx.kindId) || t('settings.ws_no_fields_loaded')));
      ctx.count.textContent = '';
      return;
    }
    fillCopyList(ctx, fixed, free);
    list.scrollTop = top;
    restoreCopyFocus(list, focus);
    ctx.count.textContent = t('settings.ws_make_buy_copy_count', { count: free.filter(function (f) { return !ctx.skip.has(f.id); }).length, total: free.length });
  }

  /** The elements of a copy list: the search and its two buttons, the list, and the count under it. */
  function buildCopyShell() {
    const box = el('div', 'ws-copy ws-mb-copy');
    const search = el('input', 'ws-copy-search');
    search.type = 'text';
    search.autocomplete = 'off';
    search.spellcheck = false;
    search.placeholder = t('settings.ws_search_fields');
    search.setAttribute('aria-label', t('settings.ws_search_fields'));
    const all = el('button', 'ws-copy-btn', t('settings.ws_make_buy_copy_all'));
    all.type = 'button';
    const none = el('button', 'ws-copy-btn', t('settings.ws_make_buy_copy_none'));
    none.type = 'button';
    const actions = el('div', 'ws-copy-actions');
    actions.append(all, none);
    const bar = el('div', 'ws-copy-bar');
    bar.append(search, actions);
    const list = el('div', 'ws-copy-list');
    const count = el('span', 'ws-copy-count');
    const foot = el('div', 'ws-copy-foot');
    foot.appendChild(count);
    box.append(bar, list, foot);
    return { box: box, search: search, all: all, none: none, list: list, count: count };
  }

  /** The fields a bought version copies from its source: every field with a tick, all ticked to begin with, in the sections of the form (each folds and
   *  has a tick of its own). What the add-in sets itself comes first, locked. What is unticked is saved (``.skipped()``) so a field added to the
   *  workspace later is copied. */
  function buildCopyList(host, kindId, stored) {
    const ctx = buildCopyShell();
    ctx.host = host;
    ctx.kindId = kindId;
    ctx.skip = new Set(stored.skip_fields || []);
    ctx.shut = new Set([t('settings.ws_make_buy_copy_group_set')]);   // the titles of the sections folded: what the add-in sets (nothing to choose there) to begin with
    ctx.query = '';
    const box = ctx.box;
    box.rebuild = function () { rebuildCopyList(ctx); };
    ctx.all.addEventListener('click', function () { splitCopyFields(ctx).free.filter(function (f) { return copyMatches(ctx, f); }).forEach(function (f) { ctx.skip.delete(f.id); }); box.rebuild(); });
    ctx.none.addEventListener('click', function () { splitCopyFields(ctx).free.filter(function (f) { return copyMatches(ctx, f); }).forEach(function (f) { ctx.skip.add(f.id); }); box.rebuild(); });
    ctx.search.addEventListener('input', function () { ctx.query = ctx.search.value.trim().toLowerCase(); box.rebuild(); });
    box.skipped = function () { return Array.from(ctx.skip); };
    return box;
  }

  // ---- The section --------------------------------------------------------------

  /** One labelled control of the Make or buy section, with its info tip. */
  function controlBlock(host, label, tip, control) {
    const block = el('div', 'ws-block');
    block.appendChild(host.blockTitle(label, tip));
    block.appendChild(control);
    return block;
  }

  /** Blocks side by side (one under the other when the card is narrow), as one block of the section. */
  function pair(blocks) {
    const box = el('div', 'ws-block ws-pair');
    blocks.forEach(function (block) { box.appendChild(block); });
    return box;
  }

  /** The Make or buy section: the field, its Make and Buy values (options of that field), the source link field and the suffix. */
  function buildSection(host, kind, config) {
    const stored = config.make_buy || {};
    const section = el('div', 'ws-section ws-mb');
    section.appendChild(host.heading(t('settings.ws_make_buy_title')));
    section.appendChild(host.describe(t('settings.ws_make_buy_desc')));

    const fieldPicker = makePicker(makeBuyFieldPick(host), stored.field || '');
    const makeSlot = el('div', 'ws-mb-slot');
    const buySlot = el('div', 'ws-mb-slot');
    function fill(slot, valueClass, current) {
      slot.textContent = '';
      const options = host.picklistFor(kind.id, fieldPicker.querySelector('.ws-mb-field').value) || [];
      slot.appendChild(makePicker(Object.assign({}, host.valueCfg(options), { valueClass: valueClass }), current));
    }
    function valueOf(valueClass) {
      const input = section.querySelector('.' + valueClass);
      return input ? input.value : '';
    }
    // The saved values are kept while the lists load (or when the workspace validates again); choosing another field clears them.
    section.rebuild = function () {
      fill(makeSlot, 'ws-mb-make', valueOf('ws-mb-make'));
      fill(buySlot, 'ws-mb-buy', valueOf('ws-mb-buy'));
    };
    fieldPicker.addEventListener('pick', function () {
      fill(makeSlot, 'ws-mb-make', '');
      fill(buySlot, 'ws-mb-buy', '');
    });
    fill(makeSlot, 'ws-mb-make', stored.make_value || '');
    fill(buySlot, 'ws-mb-buy', stored.buy_value || '');

    const copyList = buildCopyList(host, kind.id, stored);

    const suffix = el('input', 'ws-mb-suffix');
    suffix.type = 'text';
    suffix.maxLength = 20;   // as ``SUFFIX_MAX`` in workspace_models
    suffix.autocomplete = 'off';
    suffix.spellcheck = false;
    suffix.placeholder = t('settings.ws_make_buy_suffix_placeholder');
    suffix.value = stored.suffix || '';
    // Typed like an item number: other characters are dropped as they are typed.
    suffix.addEventListener('input', function () { suffix.value = suffix.value.replace(/[^A-Za-z0-9._-]/g, ''); });

    const suffixBlock = controlBlock(host, t('settings.ws_make_buy_suffix'), t('settings.ws_make_buy_suffix_tip'), suffix);
    suffixBlock.appendChild(host.describe(t('settings.ws_make_buy_suffix_hint')));

    section.appendChild(host.lockedSection([
      controlBlock(host, t('settings.ws_make_buy_field'), t('settings.ws_make_buy_field_tip'), fieldPicker),
      pair([controlBlock(host, t('settings.ws_make_buy_make'), t('settings.ws_make_buy_make_tip'), makeSlot),
            controlBlock(host, t('settings.ws_make_buy_buy'), t('settings.ws_make_buy_buy_tip'), buySlot)]),   // the two values side by side
      controlBlock(host, t('settings.ws_make_buy_source'), t('settings.ws_make_buy_source_tip'), makePicker(makeBuySourcePick(host), stored.source_field || '')),
      suffixBlock,
      controlBlock(host, t('settings.ws_make_buy_copy'), t('settings.ws_make_buy_copy_tip'), copyList),
    ]));
    return section;
  }

  ns.makeOrBuy = { buildSection: buildSection, chosenFields: makeBuyFields };
})(window.MfgUi);
