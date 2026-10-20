/**
 * Item Workspace tab: one card with a tab per Fusion Manage workspace ("Items", ...).
 *
 * Each tab stacks that workspace's sections: Workspace picker (validated on choosing), then Field
 * mapping (source field -> Fusion Manage field id). Kinds and source fields come from the catalog Python
 * sends, so a new workspace only needs a Python-side entry.
 */
(function (ns) {
  'use strict';

  const $ = ns.$;
  let catalog = { kinds: [], source_fields: [] };

  // ---- Shared helpers -----------------------------------------------------

  const el = ns.el;
  const makePicker = ns.picker.make;
  const refreshPicker = ns.picker.refresh;
  const infoTip = ns.info.tip;
  const confirmDefaults = ns.info.confirmDefaults;

  // ---- Mapping rows -------------------------------------------------------

  function customPrefix() { return catalog.custom_prefix || 'custom:'; }
  function basePrefix() { return catalog.base_prefix || 'base:'; }
  function physicalPrefix() { return catalog.physical_prefix || 'physical:'; }
  function hubPrefixes() { return [customPrefix(), basePrefix(), physicalPrefix()]; }

  // ---- Hub properties -----------------------------------------------------
  // Python lists the active hub's base and custom properties (per hub). They
  // are fetched when a workspace validates and fill "Base Properties" and
  // "Custom Properties" groups in every source picker. Stored as
  // "base:<name>" or "custom:<name>".

  let propsState = 'idle';   // idle | loading | ready | error
  let hubProps = [];         // [{name, group: 'base'|'custom', specification}]
  let propsTip = '';         // why the load failed, shown as a tooltip

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
    alignRight: true,
    placeholder: 'Component property...',
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
      [['base', basePrefix(), 'Base Properties'], ['physical', physicalPrefix(), 'Physical Properties'], ['custom', customPrefix(), 'Custom Properties']].forEach(function (g) {
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

  // ---- Workspace picker: the tenant's revision controlled workspaces -------

  let workspaceList = [];     // [{id, name}]
  let workspacesState = 'idle';   // idle | loading | ready | error
  let workspacesTip = '';     // why the load failed, shown as a tooltip and in the empty list

  const workspaceCfg = {
    valueClass: 'ws-id',
    placeholder: 'Choose a workspace...',
    search: 'Search workspaces...',
    tip: function () { return workspacesTip; },
    onOpen: function () { if (workspacesState === 'idle' || workspacesState === 'error') loadWorkspaces(); },   // read when the list is opened, not before
    empty: function () {
      if (workspacesState === 'loading') return 'Loading workspaces...';
      return workspacesTip || 'No revision controlled workspaces found';
    },
    label: function (value) {
      const found = workspaceList.filter(function (w) { return w.id === value; })[0];
      return found ? found.name : value;
    },
    groups: function (current) {
      const items = workspaceList.map(function (w) { return { value: w.id, label: w.name }; });
      // A saved workspace missing from the list must still be shown.
      if (current && !workspaceList.some(function (w) { return w.id === current; })) {
        items.push({ value: current, label: current });
      }
      return items.length ? [{ title: 'Revision Controlled Workspaces', items: items }] : [];
    },
  };

  const WAIT_MS = 60000;   // how long Python is given to push an answer before the panel gives up
  let stopWorkspacesWait = function () {};

  function onWorkspaces(r) {
    const result = r.ok ? r.result : { pending: false, ok: false, message: r.error };
    if (result.pending) return;   // only the start: Python pushes the list when it has read it
    stopWorkspacesWait();
    workspacesState = result.ok ? 'ready' : 'error';
    workspaceList = result.workspaces || [];
    workspacesTip = result.ok ? '' : 'Could not load the workspaces: ' + (result.message || 'unknown error');
    document.querySelectorAll('.ws-id').forEach(function (input) {
      refreshPicker(input.parentNode, workspaceCfg);   // shows names for saved ids
      ns.picker.rebuildOpen(input.parentNode, workspaceCfg);   // a list opened while loading
    });
  }

  /** Ask Python for the revision controlled workspaces; called when a picker opens, or at load to name saved ids. */
  function loadWorkspaces() {
    if (workspacesState === 'loading') return;
    workspacesState = 'loading';
    stopWorkspacesWait();
    stopWorkspacesWait = ns.bridge.expect(WAIT_MS, function () { onWorkspaces({ ok: false, error: 'Fusion Manage did not answer in time. Try again.' }); });
    ns.bridge.send('list_workspaces', {});
  }

  // ---- FM field picker: the workspace's fields, loaded at validation ------

  const fmFields = {};        // kindId -> [{id, title, type}]
  const fmFieldsError = {};   // kindId -> why the field list is missing

  function kindOf(wrap) {
    const panel = wrap.closest('.ws-kind');
    return panel ? panel.dataset.kind : '';
  }

  const fmFieldCfg = {
    valueClass: 'ws-fm-field',
    placeholder: 'Fusion Manage item field...',
    search: 'Search fields...',
    empty: function (wrap) {
      const kind = kindOf(wrap);
      if ((fmFields[kind] || []).length) return 'No matching fields';
      return fmFieldsError[kind] || 'No fields loaded. Choose a workspace first.';
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
      return fmFieldsError[kind] || 'No fields loaded. Choose a workspace first.';
    },
    taken: function (wrap) { return valuesInOtherRows(wrap, 'ws-fm-field'); },
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

  let stopPropsWait = function () {};

  function onProperties(r) {
    const result = r.ok ? r.result : { pending: false, ok: false, message: r.error };
    if (result.pending) return;   // only the start: Python pushes the properties when it has read them
    stopPropsWait();
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
    stopPropsWait();
    stopPropsWait = ns.bridge.expect(WAIT_MS, function () { onProperties({ ok: false, error: 'Fusion Manage did not answer in time. Try again.' }); });
    ns.bridge.send('list_custom_properties', {});
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
    row.appendChild(makePicker(fmFieldCfg, mapping.fm_field_id || ''));
    row.appendChild(el('span', 'ws-arrow', '='));
    row.appendChild(makePicker(sourceCfg, stored));

    const remove = removeButton();
    remove.type = 'button';
    remove.title = 'Remove mapping';
    remove.addEventListener('click', function () { ns.validation.forget(row); row.remove(); });
    row.appendChild(remove);
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
      value.placeholder = 'Default value';
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
    remove.title = 'Remove default value';
    remove.addEventListener('click', function () { ns.validation.forget(row); row.remove(); });
    row.appendChild(remove);
    return row;
  }

  // ---- Validation state ---------------------------------------------------
  // A workspace must be validated before its mapping can be
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
  }

  const busyCards = new Set();   // the cards whose workspace is being checked

  /** Show the bouncing-ball overlay, over the visible part of the tab, while Python checks a workspace. */
  function setBusy(card, busy) {
    if (busy) busyCards.add(card); else busyCards.delete(card);
    $('ws-busy').hidden = !busyCards.size;
  }

  // Validations in flight: kindId -> workspace id being checked. Python answers
  // `validate_workspace` at once with `pending`, and pushes the outcome when it is known.
  const polling = {};
  const waits = {};   // kindId -> cancels the wait for that validation's answer

  /** Abandon an in-flight validation (id edited, or the call itself failed). */
  function stopBusy(card, kindId) {
    delete polling[kindId];
    if (waits[kindId]) { waits[kindId](); delete waits[kindId]; }
    setBusy(card, false);
  }

  /** Ask Python to check the workspace chosen on a card. */
  function validateKind(card, kindId) {
    const workspaceId = card.querySelector('.ws-id').value.trim();
    if (!workspaceId) return;
    setBusy(card, true);
    polling[kindId] = workspaceId;
    if (waits[kindId]) waits[kindId]();
    waits[kindId] = ns.bridge.expect(WAIT_MS, function () {
      stopBusy(card, kindId);
      setValid(card, false, 'Fusion Manage did not answer in time. Try again.');
    });
    ns.bridge.send('validate_workspace', { kind: kindId, workspace_id: workspaceId });
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
    if (result.pending) return;   // only the start: Python pushes the outcome when it is known
    stopBusy(card, result.kind);
    if (result.valid) {
      validated[result.kind] = card.querySelector('.ws-id').value.trim();
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
    }
    setValid(card, result.valid, result.message);
  }

  // ---- Workspace sections -------------------------------------------------
  // A workspace's settings are stacked sections: Workspace (picker), then
  // Field mapping. Gated sections sit in `fieldset.ws-locked`, which validation enables.
  // The id row is never gated.

  /** Section heading. */
  function heading(text) { return el('h3', 'ws-heading', text); }

  /** Wrap content in the fieldset that validation locks. */
  function lockedSection(children) {
    const box = el('fieldset', 'ws-locked');
    children.forEach(function (c) { box.appendChild(c); });
    return box;
  }

  /** A line under a block title saying what the block is for. */
  function describe(text) { return el('p', 'ws-sub muted', text); }

  function hint() {
    return el('p', 'ws-hint muted', 'Choose a workspace to enable these settings.');
  }

  /** Workspace picker with its status line. */
  function buildIdSection(kind, config) {
    const section = el('div', 'ws-section');
    const label = el('label', 'ws-id-label', 'Workspace');
    label.appendChild(infoTip('The Fusion Manage workspace your published items are created in. Only revision controlled workspaces are listed.'));
    section.appendChild(label);
    const idRow = el('div', 'ws-id-row');
    // The picker sits in a wrapper so a green tick can overlay its right edge.
    const wrap = el('div', 'ws-id-wrap');
    wrap.appendChild(makePicker(workspaceCfg, config.workspace_id || ''));
    const tick = el('span', 'ws-tick', '✓');
    tick.title = 'Workspace validated';
    tick.hidden = true;
    wrap.appendChild(tick);
    idRow.appendChild(wrap);
    section.appendChild(idRow);
    section.appendChild(el('p', 'ws-status muted'));
    return section;
  }

  /** Column titles above a block of rows; the spans line up with the row's grid columns. */
  function columnHeads(titles, className) {
    const row = el('div', 'ws-cols ' + (className || ''));
    titles.forEach(function (t) { row.appendChild(el('span', '', t)); });
    return row;
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

  /** The Fusion Manage field that links each item to its component. */
  function buildComponentSection(kind, config) {
    const section = el('div', 'ws-section');
    section.appendChild(heading('Component linking'));
    section.appendChild(hint());
    const block = el('div', 'ws-block');
    block.appendChild(blockTitle('Component field',
      'Links each published item to its component in Fusion Manage. It must be a picklist that uses the component workspace list (' + kind.component_lookup + ').'));
    block.appendChild(makePicker(componentCfg, config.component_field || ''));
    section.appendChild(lockedSection([block]));
    return section;
  }

  /** Source field -> FM field id rows, then the static values. */
  function buildMappingSection(kind, config) {
    const section = el('div', 'ws-section');
    const head = el('div', 'ws-section-head');   // heading on the left, Add default fields on the right
    const title = heading('Field mapping');
    title.appendChild(infoTip('Choose which Fusion data fills which Fusion Manage field on each published item.'));
    head.appendChild(title);
    section.appendChild(head);
    section.appendChild(hint());

    const rows = el('div', 'ws-rows');
    config.mappings.forEach(function (m) { rows.appendChild(mappingRow(kind.id, m)); });
    const add = el('button', 'ws-add-btn', '+ Add field mapping');
    add.type = 'button';
    add.addEventListener('click', function () {
      rows.appendChild(mappingRow(kind.id, { source: '', fm_field_id: '' }));
    });
    const defaults = el('button', 'btn btn-secondary ws-defaults ws-lock-btn', 'Add default fields');
    defaults.type = 'button';
    defaults.title = 'Replace the mapped fields with the standard mappings';
    defaults.addEventListener('click', function () {
      confirmDefaults(kind, function () {
        rows.innerHTML = '';
        // Skip defaults whose Manage field is missing from the workspace (when its fields are known).
        const known = fmFields[kind.id] || [];
        (kind.default_mappings || []).forEach(function (m) {
          if (known.length && !known.some(function (f) { return f.id === m.fm_field_id; })) return;
          rows.appendChild(mappingRow(kind.id, { source: m.source, fm_field_id: m.fm_field_id }));
        });
      });
    });
    head.appendChild(defaults);
    const mapping = el('div', 'ws-block');
    mapping.appendChild(blockTitle('Mapped fields'));
    mapping.appendChild(describe('Each row copies one component property into a Fusion Manage item field. Existing items are found by their item number.'));
    mapping.appendChild(columnHeads(['Fusion Manage Item Field', '', 'Component Property', ''], 'ws-cols-map'));
    mapping.appendChild(rows);
    mapping.appendChild(add);

    const statics = el('div', 'ws-rows');
    (config.static_values || []).forEach(function (s) { statics.appendChild(staticRow(kind.id, s)); });
    const addStatic = el('button', 'ws-add-btn', '+ Add default value');
    addStatic.type = 'button';
    addStatic.addEventListener('click', function () {
      statics.appendChild(staticRow(kind.id, { fm_field_id: '', value: '' }));
    });
    const fixed = el('div', 'ws-block');
    fixed.appendChild(blockTitle('Default Fusion Manage Values'));
    fixed.appendChild(describe('Sets a Fusion Manage item field to the same fixed value on every published item, regardless of the design.'));
    fixed.appendChild(columnHeads(['Fusion Manage Item Field', '', 'Value', ''], 'ws-cols-static'));
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
    panel.appendChild(buildIdSection(kind, config));
    if (kind.component_lookup) panel.appendChild(buildComponentSection(kind, config));
    panel.appendChild(buildMappingSection(kind, config));

    // Wiring: choosing a workspace invalidates, then asks Python to validate.
    const idInput = panel.querySelector('.ws-id');
    setValid(panel, !!validated[kind.id] && validated[kind.id] === idInput.value.trim(), '');
    idInput.parentNode.addEventListener('pick', function () {
      delete validated[kind.id];
      stopBusy(panel, kind.id);
      setValid(panel, false, '');
      validateKind(panel, kind.id);   // a new choice is checked at once
    });
    return panel;
  }

  /** Build the card: a tab strip of workspace kinds over their panels. */
  function buildCard(kinds, settings) {
    const card = el('section', 'card ws-card');
    if (kinds.length === 1) {
      const head = el('header', 'ws-card-head');   // styled like the Connection card's title
      head.appendChild(el('h2', '', kinds[0].title + ' Workspace'));
      card.appendChild(head);
    }
    const strip = el('div', 'ws-tabs');
    strip.setAttribute('role', 'tablist');
    strip.hidden = kinds.length < 2;   // a lone workspace needs no tab
    const body = el('div', 'ws-body');
    const panels = [];

    kinds.forEach(function (kind, i) {
      const tab = el('button', 'ws-tab' + (i === 0 ? ' active' : ''), kind.title);
      tab.type = 'button';
      tab.setAttribute('role', 'tab');
      const panel = buildKindPanel(kind, settings.workspaces[kind.id] ||
        { workspace_id: '', mappings: [], static_values: [] });
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
      const kindId = card.dataset.kind;
      if (validated[kindId] !== card.querySelector('.ws-id').value.trim() && !polling[kindId]) validateKind(card, kindId);
    });
  }

  /** Listen for validation results. Call once at start-up. */
  function init() {
    const tab = document.querySelector('.tab[data-tab="workspaces"]');
    if (tab) tab.addEventListener('click', autoValidate);
    ns.bridge.on('validate_workspace', onValidated);
    ns.bridge.on('validate_workspace_status', onValidated);
    ns.bridge.on('list_workspaces', onWorkspaces);
    ns.bridge.on('list_workspaces_status', onWorkspaces);
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
    // Saved ids show as names, so read the list once in the background; with none saved it waits for a picker to open.
    if (workspacesState === 'idle' && Array.prototype.some.call(container.querySelectorAll('.ws-id'), function (i) { return i.value; })) loadWorkspaces();
    // Settings can load while the Workspaces tab is already showing.
    if ($('sub-workspaces').classList.contains('active')) autoValidate();
  }

  /** Read every card back into the `workspaces` payload Python expects. */
  function read() {
    const result = {};
    $('workspace-cards').querySelectorAll('.ws-kind').forEach(function (card) {
      result[card.dataset.kind] = {
        workspace_id: card.querySelector('.ws-id').value,
        component_field: (card.querySelector('.ws-component-field') || { value: '' }).value,
        mappings: Array.prototype.map.call(card.querySelectorAll('.ws-row:not(.ws-static-row)'), function (row) {
          return {
            source: row.querySelector('.ws-source').value,
            fm_field_id: row.querySelector('.ws-fm-field').value,
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
