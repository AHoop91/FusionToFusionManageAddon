/**
 * Workspaces tab: one card with a tab per Fusion Manage workspace ("Items", ...).
 *
 * Each tab stacks that workspace's sections: Workspace ID with Validate,
 * Options (none today) and Field
 * mapping (source field -> Fusion Manage field id, one row optionally the
 * match key). Kinds, options and source fields come from the catalog Python
 * sends, so a new workspace or option only needs a Python-side entry.
 */
(function (ns) {
  'use strict';

  const $ = ns.$;
  let catalog = { kinds: [], source_fields: [] };

  // ---- DOM helpers --------------------------------------------------------

  /** Create an element with a class and optional text. */
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // ---- Mapping rows -------------------------------------------------------

  function customPrefix() { return catalog.custom_prefix || 'custom:'; }
  function basePrefix() { return catalog.base_prefix || 'base:'; }
  function hubPrefixes() { return [customPrefix(), basePrefix()]; }

  // ---- Hub properties -----------------------------------------------------
  // Python lists the active hub's base and custom properties (per hub). They
  // are fetched when a workspace validates and fill "Base Properties" and
  // "Custom Properties" groups in every source picker. Stored as
  // "base:<name>" or "custom:<name>".

  let propsState = 'idle';   // idle | loading | ready | error
  let hubProps = [];         // [{name, group: 'base'|'custom', specification}]
  let propsTip = '';         // why the load failed, shown as a tooltip

  // ---- Pickers ------------------------------------------------------------
  // A button plus a searchable list of ordinary page elements, not a native
  // <select>: the native popup was slow to open in Fusion's embedded browser.
  // A hidden input (class `cfg.valueClass`) carries the chosen value.
  //
  // cfg: valueClass, placeholder, search (placeholder text), label(value),
  //      groups(value, wrap) -> [{title, items: [{value, label, detail}]}],
  //      empty(wrap) -> text shown when nothing is listed or matches,
  //      taken(wrap) -> values already used elsewhere, shown greyed out.

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

  /** Values held by the other rows of this workspace, for greying out. */
  function valuesInOtherRows(wrap, valueClass) {
    const panel = wrap.closest('.ws-kind');
    const own = wrap.querySelector('.' + valueClass);
    const values = [];
    if (panel) {
      panel.querySelectorAll('.ws-row .' + valueClass).forEach(function (input) {
        if (input !== own && input.value) values.push(input.value);
      });
    }
    return values;
  }

  // ---- Source field picker: properties, files, hub custom properties ------

  const sourceCfg = {
    valueClass: 'ws-source',
    placeholder: 'Source field...',
    search: 'Search fields...',
    tip: function () { return propsTip; },
    empty: function () { return 'No matching fields'; },
    taken: function (wrap) { return valuesInOtherRows(wrap, 'ws-source'); },
    label: function (value) {
      const field = catalog.source_fields.filter(function (f) { return f.id === value; })[0];
      if (field) return field.label;
      const prefix = hubPrefixes().filter(function (p) { return value.indexOf(p) === 0; })[0];
      return prefix ? value.slice(prefix.length) : value;
    },
    groups: function (current) {
      const groups = [['Properties', 'property'], ['Files', 'file']].map(function (g) {
        return { title: g[0], items: catalog.source_fields
          .filter(function (f) { return (f.kind || 'property') === g[1]; })
          .map(function (f) { return { value: f.id, label: f.label }; }) };
      });
      [['base', basePrefix(), 'Base Properties'], ['custom', customPrefix(), 'Custom Properties']].forEach(function (g) {
        const names = hubProps.filter(function (p) { return p.group === g[0]; })
          .map(function (p) { return p.name; });
        // A saved hub property missing from the list must still be shown.
        if (current.indexOf(g[1]) === 0 && names.indexOf(current.slice(g[1].length)) < 0) {
          names.push(current.slice(g[1].length));
        }
        groups.push({ title: g[2], items: names.map(function (n) {
          return { value: g[1] + n, label: n };
        }) });
      });
      return groups.filter(function (g) { return g.items.length; });
    },
  };

  // ---- FM field picker: the workspace's fields, loaded at validation ------

  const fmFields = {};        // kindId -> [{id, title, type}]
  const fmFieldsError = {};   // kindId -> why the field list is missing

  function kindOf(wrap) {
    const panel = wrap.closest('.ws-kind');
    return panel ? panel.dataset.kind : '';
  }

  const fmFieldCfg = {
    valueClass: 'ws-fm-field',
    alignRight: true,
    placeholder: 'FM field...',
    search: 'Search fields...',
    empty: function (wrap) {
      const kind = kindOf(wrap);
      if ((fmFields[kind] || []).length) return 'No matching fields';
      return fmFieldsError[kind] || 'No fields loaded. Validate the workspace first.';
    },
    taken: function (wrap) { return valuesInOtherRows(wrap, 'ws-fm-field').concat(componentValue(wrap)); },
    label: function (value) {
      // Show the title with the id that is actually stored.
      for (const kind in fmFields) {
        const field = fmFields[kind].filter(function (f) { return f.id === value; })[0];
        if (field) return field.title + ' (' + field.id + ')';
      }
      return value;
    },
    groups: function (current, wrap) {
      const fields = fmFields[kindOf(wrap)] || [];
      const items = fields.map(function (f) { return { value: f.id, label: f.title, detail: f.id + ' · ' + f.type }; });
      // A saved field id missing from the list must still be shown.
      if (current && !fields.some(function (f) { return f.id === current; })) {
        items.push({ value: current, label: current });
      }
      return items.length ? [{ title: 'Fusion Manage Fields', items: items }] : [];
    },
  };

  const fmPicklists = {};     // kindId -> {lookupId: [{value, title}]}

  /** The options for a fixed-list field, or null when the field takes free text. */
  function picklistFor(kind, fieldId) {
    const field = (fmFields[kind] || []).filter(function (f) { return f.id === fieldId; })[0];
    return field && field.picklist && (fmPicklists[kind] || {})[field.picklist] || null;
  }

  /** Picker config for the options of one picklist; the stored value is the option's link. */
  function valueCfg(options) {
    return {
      valueClass: 'ws-static-value',
      alignRight: true,
      placeholder: 'Choose a value...',
      search: 'Search values...',
      empty: function () { return 'No matching values'; },
      label: function (value) {
        const option = options.filter(function (o) { return o.value === value; })[0];
        return option ? option.title : value;
      },
      groups: function (current) {
        const items = options.map(function (o) { return { value: o.value, label: o.title }; });
        // A saved value no longer in the list must still be shown.
        if (current && !options.some(function (o) { return o.value === current; })) {
          items.push({ value: current, label: current });
        }
        return [{ title: 'Values', items: items }];
      },
    };
  }

  /** The workspace's chosen component-linking field, as a list so it can join the "taken" values. */
  function componentValue(wrap) {
    const panel = wrap.closest('.ws-kind');
    const input = panel && panel.querySelector('.ws-component-field');
    return input && input.value ? [input.value] : [];
  }

  /** Picker config for the field that links an item to a component: fields using the component picklist. */
  const componentCfg = {
    valueClass: 'ws-component-field',
    alignRight: true,
    placeholder: 'Choose the linking field...',
    search: 'Search fields...',
    empty: function (wrap) {
      const kind = kindOf(wrap);
      if ((fmFields[kind] || []).length) return 'No field links to the component picklist';
      return fmFieldsError[kind] || 'No fields loaded. Validate the workspace first.';
    },
    taken: function (wrap) {
      const panel = wrap.closest('.ws-kind');
      const values = [];
      if (panel) {
        panel.querySelectorAll('.ws-row .ws-fm-field').forEach(function (i) { if (i.value) values.push(i.value); });
      }
      return values;
    },
    label: fmFieldCfg.label,
    groups: function (current, wrap) {
      const kind = kindOf(wrap);
      const lookup = (catalog.kinds.filter(function (k) { return k.id === kind; })[0] || {}).component_lookup;
      const fields = (fmFields[kind] || []).filter(function (f) { return lookup && f.link_lookup === lookup; });
      const items = fields.map(function (f) { return { value: f.id, label: f.title, detail: f.id + ' · ' + f.type }; });
      if (current && !fields.some(function (f) { return f.id === current; })) {
        items.push({ value: current, label: current });
      }
      return items.length ? [{ title: 'Component linking fields', items: items }] : [];
    },
  };

  function onProperties(r) {
    const result = r.ok ? r.result : { pending: false, ok: false, message: r.error };
    if (result.pending) {
      setTimeout(function () { ns.bridge.send('list_custom_properties_status', {}); }, POLL_MS);
      return;
    }
    propsState = result.ok ? 'ready' : 'error';
    hubProps = result.properties || [];
    propsTip = result.ok ? '' : 'Could not load the hub\'s properties: ' + (result.message || 'unknown error');
    document.querySelectorAll('.ws-source').forEach(function (input) {
      refreshPicker(input.parentNode, sourceCfg);   // lists build on open; this updates the tooltip
    });
  }

  /** Ask Python for the hub's properties; called each time a workspace validates. */
  function loadProperties() {
    if (propsState === 'loading') return;
    propsState = 'loading';
    ns.bridge.send('list_custom_properties', {});
  }

  /** Files cannot be the match key. */
  function syncRow(row) {
    const value = row.querySelector('.ws-source').value;
    const field = catalog.source_fields.filter(function (f) { return f.id === value; })[0];
    const canMatch = !field || field.can_match !== false;
    const radio = row.querySelector('.ws-match');
    radio.disabled = !canMatch;
    if (!canMatch) radio.checked = false;
    row.querySelector('.ws-key').style.opacity = canMatch ? '' : '0.4';
  }

  /** A round button with a drawn X, so it looks the same everywhere. */
  function removeButton() {
    const button = el('button', 'ws-remove');
    button.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
    return button;
  }

  /** Build one mapping row; the match-key radio group is per workspace kind. */
  function mappingRow(kindId, mapping) {
    const row = el('div', 'ws-row');
    const stored = mapping.source || '';
    const picker = makePicker(sourceCfg, stored);
    row.appendChild(picker);
    row.appendChild(el('span', 'ws-arrow', '→'));
    row.appendChild(makePicker(fmFieldCfg, mapping.fm_field_id || ''));

    const key = el('label', 'ws-key');
    key.title = 'Match key: identifies an existing item so it is updated, not duplicated';
    const radio = el('input', 'ws-match');
    radio.type = 'checkbox';   // square box, but only one row can hold the key
    radio.addEventListener('change', function () {
      if (!radio.checked) return;
      const panel = row.closest('.ws-kind');
      if (panel) panel.querySelectorAll('.ws-match').forEach(function (other) { if (other !== radio) other.checked = false; });
    });
    radio.checked = !!mapping.match_key;
    key.appendChild(radio);
    row.appendChild(key);

    const remove = removeButton();
    remove.type = 'button';
    remove.title = 'Remove mapping';
    remove.addEventListener('click', function () { row.remove(); });
    row.appendChild(remove);
    picker.addEventListener('pick', function () { syncRow(row); });
    syncRow(row);
    return row;
  }

  /** A Fusion Manage field that always gets the same value. */
  function staticRow(kindId, item) {
    const row = el('div', 'ws-row ws-static-row');
    const fieldPicker = makePicker(fmFieldCfg, item.fm_field_id || '');
    row.appendChild(fieldPicker);
    row.appendChild(el('span', 'ws-arrow', '='));
    // The value is typed, or picked from the options when the field is a picklist.
    const slot = el('div', 'ws-static-slot');
    row.appendChild(slot);
    function buildValue(current) {
      slot.textContent = '';
      const fieldId = fieldPicker.querySelector('.ws-fm-field').value;
      const options = picklistFor(kindId, fieldId);
      if (options) {
        slot.appendChild(makePicker(valueCfg(options), current));
        return;
      }
      const value = el('input', 'ws-static-value');
      value.type = 'text';
      value.placeholder = 'Static value';
      value.autocomplete = 'off';
      value.spellcheck = false;
      value.value = current;
      slot.appendChild(value);
    }
    row.rebuildValue = function () {
      const old = slot.querySelector('.ws-static-value');
      buildValue(old ? old.value : '');
    };
    fieldPicker.addEventListener('pick', function () { buildValue(''); });
    buildValue(item.value || '');
    const remove = removeButton();
    remove.type = 'button';
    remove.title = 'Remove static value';
    remove.addEventListener('click', function () { row.remove(); });
    row.appendChild(remove);
    return row;
  }

  // ---- Validation state ---------------------------------------------------
  // A workspace must be validated before its options and mapping can be
  // edited. The result is remembered per kind for the current session, keyed
  // by the id it was validated for, so re-rendering after a save keeps it.

  const validated = {};   // kindId -> workspace id that passed validation

  function cardOf(kindId) {
    return $('workspace-cards').querySelector('.ws-kind[data-kind="' + kindId + '"]');
  }

  /** Lock or unlock every gated section of a card and show the status text. */
  function setValid(card, valid, message) {
    card.querySelectorAll('.ws-locked, .ws-lock-btn').forEach(function (f) { f.disabled = !valid; });
    card.querySelectorAll('.ws-hint').forEach(function (h) { h.hidden = valid; });
    const status = card.querySelector('.ws-status');
    // Success is shown by the tick; only failures get a message.
    const text = valid ? '' : message || '';
    status.textContent = text;
    status.className = 'ws-status ' + (text ? 'error' : 'muted');
    card.querySelector('.ws-tick').hidden = !valid;
    // Nothing to validate again until the id changes (or it is empty).
    card.querySelector('.ws-validate').disabled = valid || !card.querySelector('.ws-id').value.trim();
  }

  /** Show or hide the bouncing-ball overlay while Python checks the workspace. */
  function setBusy(card, busy) {
    card.querySelector('.ws-busy').hidden = !busy;
  }

  // Options the user's Fusion Manage permissions rule out: kindId -> {optionId: reason}.
  const blocked = {};

  /** Switch off and lock the options in `blocked[kindId]`; free the rest. */
  function applyBlocked(card, kindId) {
    const reasons = blocked[kindId] || {};
    card.querySelectorAll('.ws-option').forEach(function (row) {
      const box = row.querySelector('.ws-option-box');
      const note = row.querySelector('.ws-option-note');
      const reason = reasons[box.dataset.option];
      box.disabled = !!reason;
      if (reason) box.checked = false;
      row.classList.toggle('ws-option-blocked', !!reason);
      note.textContent = reason || '';
      note.hidden = !reason;
    });
  }

  // Validations in flight: kindId -> workspace id being checked. Python answers
  // `validate_workspace` at once with `pending`, so the panel polls the status.
  const polling = {};
  const POLL_MS = 300;

  /** Abandon an in-flight validation (id edited, or the call itself failed). */
  function stopBusy(card, kindId) {
    delete polling[kindId];
    card.querySelector('.ws-validate').textContent = 'Validate';
    setBusy(card, false);
  }

  /** Called with Python's answer to `validate_workspace` / `_status`. */
  function onValidated(r) {
    if (!r.ok) {
      // No kind to go on: end every validation and show the error.
      Object.keys(polling).forEach(function (kindId) {
        const failed = cardOf(kindId);
        if (!failed) return;
        stopBusy(failed, kindId);
        setValid(failed, false, r.error);
      });
      return;
    }
    const result = r.result;
    const card = cardOf(result.kind);
    // Ignore answers for a validation that was abandoned or is for an old id.
    if (!card || polling[result.kind] !== result.workspace_id) return;
    if (result.pending) {
      setTimeout(function () {
        if (polling[result.kind] === result.workspace_id) {
          ns.bridge.send('validate_workspace_status', { kind: result.kind });
        }
      }, POLL_MS);
      return;
    }
    stopBusy(card, result.kind);
    if (result.valid) {
      validated[result.kind] = card.querySelector('.ws-id').value.trim();
      blocked[result.kind] = result.blocked || {};
      fmFields[result.kind] = result.fields || [];
      fmFieldsError[result.kind] = result.fields_error || '';
      fmPicklists[result.kind] = result.picklists || {};
      // Saved ids show their titles once the field list is known.
      card.querySelectorAll('.ws-component-field').forEach(function (i) { refreshPicker(i.parentNode, componentCfg); });
      // Static rows built before validation (typed values) become pickers where the field has a list.
      card.querySelectorAll('.ws-static-row').forEach(function (row) { row.rebuildValue(); });
      loadProperties();   // custom properties are per hub, so refresh with each validation
    } else {
      delete validated[result.kind];
      delete blocked[result.kind];
    }
    applyBlocked(card, result.kind);
    setValid(card, result.valid, result.message);
  }

  // ---- Workspace sections -------------------------------------------------
  // A workspace's settings are stacked sections: Workspace (id + Validate),
  // Options, Field mapping. Gated sections (options, mapping) sit in
  // `fieldset.ws-locked`, which validation enables. The id row is never gated.

  /** Section heading. */
  function heading(text) { return el('h3', 'ws-heading', text); }

  /** Wrap content in the fieldset that validation locks. */
  function lockedSection(children) {
    const box = el('fieldset', 'ws-locked');
    children.forEach(function (c) { box.appendChild(c); });
    return box;
  }

  function hint() {
    return el('p', 'ws-hint muted', 'Validate the workspace to enable these settings.');
  }

  /** Workspace id input with its Validate button and status line. */
  function buildIdSection(kind, config) {
    const section = el('div', 'ws-section');
    section.appendChild(el('label', 'ws-id-label', kind.title + ' Workspace ID'));
    const idRow = el('div', 'ws-id-row');
    const idInput = el('input', 'ws-id');
    idInput.type = 'text';
    idInput.inputMode = 'numeric';
    idInput.autocomplete = 'off';
    idInput.spellcheck = false;
    idInput.placeholder = 'e.g. 83';
    idInput.value = config.workspace_id || '';
    // The input sits in a wrapper so a green tick can overlay its right edge.
    const wrap = el('div', 'ws-id-wrap');
    wrap.appendChild(idInput);
    const tick = el('span', 'ws-tick', '✓');
    tick.title = 'Workspace validated';
    tick.hidden = true;
    wrap.appendChild(tick);
    idRow.appendChild(wrap);
    const validate = el('button', 'btn btn-secondary ws-validate', 'Validate');
    validate.type = 'button';
    idRow.appendChild(validate);
    section.appendChild(idRow);
    section.appendChild(el('p', 'ws-status muted'));
    return section;
  }

  /** Options: the workspace id row, then the kind's on/off options. */
  function buildOptionsSection(kind, config) {
    const section = el('div', 'ws-section');
    section.appendChild(buildIdSection(kind, config));
    if (!(kind.options || []).length) return section;   // no options: the mapping section carries the hint
    section.appendChild(hint());
    section.appendChild(lockedSection((kind.options || []).map(function (o) {
      const row = el('label', 'ws-option');
      const box = el('input', 'ws-option-box');
      box.type = 'checkbox';
      box.dataset.option = o.id;
      box.checked = !!(config.options && config.options[o.id]);
      const text = el('span', 'ws-option-text');
      text.appendChild(el('span', 'ws-option-label', o.label));
      text.appendChild(el('span', 'ws-option-desc muted', o.description));
      const note = el('span', 'ws-option-note error');
      note.hidden = true;
      text.appendChild(note);
      row.appendChild(box);
      row.appendChild(text);
      return row;
    })));
    return section;
  }

  /** Column titles above a block of rows; the spans line up with the row's grid columns. */
  function columnHeads(titles, className) {
    const row = el('div', 'ws-cols ' + (className || ''));
    titles.forEach(function (t) { row.appendChild(el('span', '', t)); });
    return row;
  }

  const INFO_ICON = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="currentColor"/><path d="M12 11v6" stroke="#fff" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="7.5" r="1.4" fill="#fff"/></svg>';

  /** Close any open info tip. */
  function closeTips(except) {
    document.querySelectorAll('.ws-tip-wrap.open').forEach(function (w) { if (w !== except) w.classList.remove('open'); });
  }
  document.addEventListener('click', function (e) { if (!e.target.closest('.ws-tip-wrap')) closeTips(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeTips(); });

  /** An info icon button; clicking it shows or hides a tip with `text`. */
  function infoTip(text) {
    const wrap = el('span', 'ws-tip-wrap');
    const btn = el('button', 'ws-tip-btn');
    btn.type = 'button';
    btn.setAttribute('aria-label', 'More information');
    btn.innerHTML = INFO_ICON;
    const tip = el('span', 'ws-tip', text);
    tip.setAttribute('role', 'tooltip');
    btn.addEventListener('click', function () {
      const open = !wrap.classList.contains('open');
      closeTips(wrap);
      wrap.classList.toggle('open', open);
    });
    wrap.appendChild(btn);
    wrap.appendChild(tip);
    return wrap;
  }

  /** A sub-heading with an info icon (click for what the block does) and an optional action at the right. */
  function blockTitle(title, text, action) {
    const box = el('div', 'ws-block-title');
    const head = el('div', 'ws-block-head');
    const name = el('div', 'ws-block-namebox');
    name.appendChild(el('h4', 'ws-block-name', title));
    if (text) name.appendChild(infoTip(text));
    head.appendChild(name);
    if (action) head.appendChild(action);   // sits at the right of the title
    box.appendChild(head);
    return box;
  }

  /** Ask before "Add default fields" replaces the mapped fields; ``onYes`` runs if the user agrees. */
  function confirmDefaults(onYes) {
    const overlay = el('div', 'ws-dialog-overlay');
    const box = el('div', 'ws-dialog');
    box.setAttribute('role', 'alertdialog');
    box.setAttribute('aria-modal', 'true');
    box.setAttribute('aria-labelledby', 'ws-dialog-title');
    const title = el('h3', 'ws-dialog-title', 'Load default fields?');
    title.id = 'ws-dialog-title';
    box.appendChild(title);
    box.appendChild(el('p', 'ws-dialog-text',
      'Loading the default fields replaces all existing field mappings with the standard set. Any mappings you have added or changed will be removed. Do you want to continue?'));
    const note = el('div', 'ws-info');
    note.setAttribute('role', 'note');
    const icon = el('span', 'ws-info-icon');
    icon.innerHTML = INFO_ICON;
    note.appendChild(icon);
    note.appendChild(el('p', 'ws-info-text',
      'The defaults reflect the out-of-the-box Items workspace. If your workspace has been customized, you will need to adjust the mappings manually.'));
    box.appendChild(note);

    const actions = el('div', 'ws-dialog-actions');
    const cancel = el('button', 'btn btn-secondary', 'Cancel');
    const ok = el('button', 'btn', 'Load default fields');
    cancel.type = ok.type = 'button';
    actions.appendChild(cancel);
    actions.appendChild(ok);
    box.appendChild(actions);
    overlay.appendChild(box);

    function close() { document.removeEventListener('keydown', onKey); overlay.remove(); }
    function onKey(e) { if (e.key === 'Escape') close(); }
    cancel.addEventListener('click', close);
    ok.addEventListener('click', function () { close(); onYes(); });
    overlay.addEventListener('mousedown', function (e) { if (e.target === overlay) close(); });
    document.addEventListener('keydown', onKey);
    document.body.appendChild(overlay);
    cancel.focus();
  }

  /** The Fusion Manage field that links each item to its component. */
  function buildComponentSection(kind, config) {
    const section = el('div', 'ws-section');
    section.appendChild(heading('Component linking'));
    section.appendChild(hint());
    const block = el('div', 'ws-block');
    block.appendChild(blockTitle('Component field',
      'The Fusion Manage field that links an item to its component. It must be a picklist that uses the component workspace list (' + kind.component_lookup + ').'));
    block.appendChild(makePicker(componentCfg, config.component_field || ''));
    section.appendChild(lockedSection([block]));
    return section;
  }

  /** Source field -> FM field id rows, then the static values. */
  function buildMappingSection(kind, config) {
    const section = el('div', 'ws-section');
    const head = el('div', 'ws-section-head');   // heading on the left, Add default fields on the right
    head.appendChild(heading('Field mapping'));
    section.appendChild(head);
    section.appendChild(hint());

    const rows = el('div', 'ws-rows');
    config.mappings.forEach(function (m) { rows.appendChild(mappingRow(kind.id, m)); });
    const add = el('button', 'ws-add-btn', '+ Add field mapping');
    add.type = 'button';
    add.addEventListener('click', function () {
      rows.appendChild(mappingRow(kind.id, { source: '', fm_field_id: '', match_key: false }));
    });
    const defaults = el('button', 'btn btn-secondary ws-defaults ws-lock-btn', 'Add default fields');
    defaults.type = 'button';
    defaults.title = 'Replace the mapped fields with the standard mappings (part number, name, description)';
    defaults.addEventListener('click', function () {
      confirmDefaults(function () {
        rows.innerHTML = '';
        (kind.default_mappings || []).forEach(function (m) {
          rows.appendChild(mappingRow(kind.id, { source: m.source, fm_field_id: m.fm_field_id, match_key: m.match_key }));
        });
      });
    });
    head.appendChild(defaults);
    const mapping = el('div', 'ws-block');
    mapping.appendChild(blockTitle('Mapped fields',
      'Maps each Fusion field to a field in the Fusion Manage workspace. Select Key on the one mapping used to identify existing items, so a matching item is updated rather than duplicated.'));
    mapping.appendChild(columnHeads(['Fusion field', '', 'Manage field', 'Key', ''], 'ws-cols-map'));
    mapping.appendChild(rows);
    mapping.appendChild(add);

    const statics = el('div', 'ws-rows');
    (config.static_values || []).forEach(function (s) { statics.appendChild(staticRow(kind.id, s)); });
    const addStatic = el('button', 'ws-add-btn', '+ Add static value');
    addStatic.type = 'button';
    addStatic.addEventListener('click', function () {
      statics.appendChild(staticRow(kind.id, { fm_field_id: '', value: '' }));
    });
    const fixed = el('div', 'ws-block');
    fixed.appendChild(blockTitle('Static values', 'Sets a Fusion Manage field to the same fixed value on every published item, regardless of the design.'));
    fixed.appendChild(columnHeads(['Manage field', '', 'Value', ''], 'ws-cols-static'));
    fixed.appendChild(statics);
    fixed.appendChild(addStatic);

    section.appendChild(lockedSection([mapping, fixed]));
    return section;
  }

  // ---- Workspace panels and the card --------------------------------------
  // One card holds a tab per workspace kind ("Items", ...). Each tab shows
  // that workspace's sections.

  function buildKindPanel(kind, config) {
    const panel = el('div', 'ws-kind ws-panel');
    panel.dataset.kind = kind.id;
    panel.appendChild(el('p', 'ws-desc muted', kind.description));
    panel.appendChild(buildOptionsSection(kind, config));
    if (kind.component_lookup) panel.appendChild(buildComponentSection(kind, config));
    panel.appendChild(buildMappingSection(kind, config));

    // Overlay shown while the workspace is being validated.
    const busy = el('div', 'ws-busy loader');
    busy.hidden = true;
    const balls = el('div', 'balls');
    balls.setAttribute('role', 'status');
    balls.setAttribute('aria-label', 'Validating');
    for (let i = 0; i < 3; i++) balls.appendChild(el('span'));
    busy.appendChild(balls);
    busy.appendChild(el('p', 'muted', 'Validating workspace...'));
    panel.appendChild(busy);

    // Wiring: changing the id invalidates; Validate asks Python.
    const idInput = panel.querySelector('.ws-id');
    const validate = panel.querySelector('.ws-validate');
    setValid(panel, !!validated[kind.id] && validated[kind.id] === idInput.value.trim(), '');
    applyBlocked(panel, kind.id);
    idInput.addEventListener('input', function () {
      delete validated[kind.id];
      delete blocked[kind.id];
      stopBusy(panel, kind.id);
      applyBlocked(panel, kind.id);
      setValid(panel, false, '');
    });
    validate.addEventListener('click', function () {
      validate.disabled = true;
      validate.textContent = 'Validating...';
      setBusy(panel, true);
      polling[kind.id] = idInput.value.trim();
      ns.bridge.send('validate_workspace', { kind: kind.id, workspace_id: polling[kind.id] });
    });
    return panel;
  }

  /** Build the card: a tab strip of workspace kinds over their panels. */
  function buildCard(kinds, settings) {
    const card = el('section', 'ws-card');
    const strip = el('div', 'ws-tabs');
    strip.setAttribute('role', 'tablist');
    const body = el('div', 'ws-body');
    const panels = [];

    kinds.forEach(function (kind, i) {
      const tab = el('button', 'ws-tab' + (i === 0 ? ' active' : ''), kind.title);
      tab.type = 'button';
      tab.setAttribute('role', 'tab');
      const panel = buildKindPanel(kind, settings.workspaces[kind.id] ||
        { workspace_id: '', mappings: [], static_values: [], options: {} });
      panel.hidden = i !== 0;
      panels.push(panel);
      tab.addEventListener('click', function () {
        strip.querySelectorAll('.ws-tab').forEach(function (t) { t.classList.toggle('active', t === tab); });
        panels.forEach(function (p) { p.hidden = p !== panel; });
      });
      strip.appendChild(tab);
      body.appendChild(panel);
    });

    card.appendChild(strip);
    card.appendChild(body);
    return card;
  }

  // ---- Public API ---------------------------------------------------------

  /** Validate every workspace that has an id but is not validated yet (on opening the tab). */
  function autoValidate() {
    $('workspace-cards').querySelectorAll('.ws-kind').forEach(function (card) {
      const button = card.querySelector('.ws-validate');
      if (!button.disabled && card.querySelector('.ws-id').value.trim() && !polling[card.dataset.kind]) button.click();
    });
  }

  /** Listen for validation results. Call once at start-up. */
  function init() {
    const tab = document.querySelector('.tab[data-tab="workspaces"]');
    if (tab) tab.addEventListener('click', autoValidate);
    ns.bridge.on('validate_workspace', onValidated);
    ns.bridge.on('validate_workspace_status', onValidated);
    ns.bridge.on('list_custom_properties', onProperties);
    ns.bridge.on('list_custom_properties_status', onProperties);
  }

  /** Rebuild the card from `settings.workspaces` and `settings.catalog`. */
  function render(settings) {
    catalog = settings.catalog;
    // Keep the selected workspace tab across a rebuild (e.g. after Save).
    const active = document.querySelector('#workspace-cards .ws-tab.active');
    const container = $('workspace-cards');
    container.textContent = '';
    container.appendChild(buildCard(catalog.kinds, settings));
    if (active) {
      Array.prototype.forEach.call(container.querySelectorAll('.ws-tab'), function (tab) {
        if (tab.textContent === active.textContent) tab.click();
      });
    }
    // Settings can load while the Workspaces tab is already showing.
    if ($('sub-workspaces').classList.contains('active')) autoValidate();
  }

  /** Read every card back into the `workspaces` payload Python expects. */
  function read() {
    const result = {};
    $('workspace-cards').querySelectorAll('.ws-kind').forEach(function (card) {
      const options = {};
      card.querySelectorAll('.ws-option-box').forEach(function (box) {
        options[box.dataset.option] = box.checked;
      });
      result[card.dataset.kind] = {
        workspace_id: card.querySelector('.ws-id').value,
        options: options,
        component_field: (card.querySelector('.ws-component-field') || { value: '' }).value,
        mappings: Array.prototype.map.call(card.querySelectorAll('.ws-row:not(.ws-static-row)'), function (row) {
          return {
            source: row.querySelector('.ws-source').value,
            fm_field_id: row.querySelector('.ws-fm-field').value,
            match_key: row.querySelector('.ws-match').checked,
          };
        }),
        static_values: Array.prototype.map.call(card.querySelectorAll('.ws-static-row'), function (row) {
          return {
            fm_field_id: row.querySelector('.ws-fm-field').value,
            value: row.querySelector('.ws-static-value').value,
          };
        }),
      };
    });
    return result;
  }

  ns.workspaces = { init: init, render: render, read: read };
})(window.MfgUi);
