/**
 * Publish Item panel: the structure viewer, as ``ns.mbomViewer``. Two panes side by side: the EBOM (the design's Bill of Materials, read-only) and the
 * MBOM (the manufacturing Bill of Materials, which can be edited). The MBOM is ``ns.mbomStructure``; this file draws it and turns what the user
 * does into its edits. Nothing here is sent to Fusion Manage: the Publish button still publishes what the table shows.
 *
 * Where the trees come from: the EBOM from the rows the panel has read (all levels, so the whole tree is read first, as Expand all does); the
 * MBOM from the ``mbom_tree`` section (the target item read by its id, every level), mapped to the EBOM by item number. A design with no MBOM item
 * starts as a copy of the EBOM.
 *
 * The viewer keeps uids and EBOM keys only, never nodes: the structure replaces its tree by a copy on a refused edit, undo and redo. Only the
 * lines of an open assembly are drawn, and no more than ``LIMIT`` under one at first, so a large tree stays quick. Every edit goes through
 * ``run``, which shows the reason an edit was refused in the message line.
 *
 * ``host``: ``design()`` (the open design's summary), ``rows()`` (compared rows read so far), ``partial()`` (levels not read yet), ``loadTree()``,
 * ``askMbom()``, ``targetId()``, ``target()`` (item number), ``phantom()`` (whether Settings allow phantoms).
 */
(function (ns) {
  'use strict';

  const ui = ns.pubUi;
  const el = ns.el;
  const S = ns.mbomStructure;
  function t(key, params) { return ns.i18n.t(key, params); }

  const LIMIT = 200;   // lines drawn under an assembly before "Show more"

  const ICONS = {   // svg paths (24 x 24) of the buttons and of the actions on a line
    copy: ['M9 9h10v10H9z', 'M5 15V5h10'],
    remove: ['M5 7h14', 'M9 7V4h6v3', 'M7 7l1 13h8l1-13', 'M10 11v6', 'M14 11v6'],
    assembly: ['M12 3l8 4.5v9L12 21l-8-4.5v-9z', 'M12 9.5v5', 'M9.5 12h5'],
    boxPlus: ['M10 3l7 4v6', 'M17 7l-7 4-7-4', 'M10 11v9', 'M3 7v10l7 4', 'M10 3L3 7', 'M18 14.5v7', 'M14.5 18h7'],   // a box like the BOM's, with a plus at its bottom right (the last two paths)
    addItems: ['M4 6h11', 'M4 12h7', 'M4 18h7', 'M17 14v6', 'M14 17h6'],   // a list with a plus
    split: ['M12 4v6', 'M12 10L6 20', 'M12 10l6 10'],
    grip: ['M9 6h.01', 'M15 6h.01', 'M9 12h.01', 'M15 12h.01', 'M9 18h.01', 'M15 18h.01'],
    addDeep: ['M4 12h11', 'M11 7l5 5-5 5', 'M20 4v16'],
    addOne: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', 'M12 8v8', 'M8 12h8'],
    search: ['M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z', 'M16 16l4.5 4.5'],
    undo: ['M9 14L4 9l5-5', 'M4 9h10a6 6 0 0 1 0 12h-3'],
    redo: ['M15 14l5-5-5-5', 'M20 9H10a6 6 0 0 0 0 12h3'],
  };

  /** The words for what the structure refuses (it throws errors with a ``key`` and ``params``). */
  const ERRORS = {
    bad_quantity: function () { return t('publish.sv_err_bad_quantity'); },
    quantity_inexact: function (p) { return t('publish.sv_err_quantity_inexact', p); },
    phantom_needs_settings: function () { return t('publish.sv_phantom_off'); },
    needs_number: function () { return t('publish.sv_err_needs_number'); },
    number_used: function (p) { return t('publish.sv_err_number_used', p); },
    not_assembly: function (p) { return t('publish.sv_err_not_assembly', p); },
    copy_new_assembly: function (p) { return t('publish.sv_err_copy_new_assembly', p); },
    root_immutable: function () { return t('publish.sv_err_root_immutable'); },
    nothing_selected: function () { return t('publish.sv_err_nothing_selected'); },
    inside_itself: function () { return t('publish.sv_err_inside_itself'); },
    before_not_under: function () { return t('publish.sv_err_before_not_under'); },
    no_such_line: function () { return t('publish.sv_err_no_such_line'); },
    no_place_root: function () { return t('publish.sv_err_no_place_root'); },
    unknown_place: function (p) { return t('publish.sv_err_unknown_place', p); },
    no_such_ebom: function () { return t('publish.sv_err_no_such_ebom'); },
    would_exceed: function (p) { return t('publish.sv_err_would_exceed', p); },
    root_no_quantity: function () { return t('publish.sv_err_root_no_quantity'); },
    split_same: function () { return t('publish.sv_err_split_same'); },
    split_inside: function () { return t('publish.sv_err_split_inside'); },
    split_root: function () { return t('publish.sv_err_split_root'); },
    split_some: function () { return t('publish.sv_err_split_some'); },
    split_direct: function () { return t('publish.sv_err_split_direct'); },
  };

  /** An error of an edit in words; one that is not the structure's refusal is shown as it is, never hidden. */
  function describe(error) {
    const words = error.key && ERRORS[error.key];
    return words ? words(error.params) : error.message || String(error);
  }

  let host = null;
  let dom = null;            // the elements of the viewer, made when it is first shown
  let active = false;        // the Structure view is the one on screen
  let ready = false;         // the first level of the Bill of Materials has been read: the whole tree can be asked for
  let phase = 'idle';        // idle, structure / tree / mbom (what is being waited for: each asked once) or error
  let note = '';             // what the viewer is waiting for, or the error
  let structure = null;
  let ebom = null;
  let message = '';          // why the last edit was refused
  let drag = null;           // what is being dragged: { from: 'mbom' | 'ebom', ids }
  let dropMark = null;       // the row showing where a drop would go
  let searchText = '';
  let hitIndex = -1;
  const hits = new Set();    // uids of the lines the search found
  const opened = new Set([S.ROOT]);   // uids of the MBOM lines that are open
  const ebomOpened = new Set(['0']);  // keys of the EBOM lines that are open
  const more = {};           // parent id -> how many lines under it are drawn
  const selected = new Set();       // MBOM uids
  const ebomSelected = new Set();   // EBOM keys
  let anchor = '';                  // where a shift-click range starts, in the pane last clicked
  let visible = { mbom: [], ebom: [] };   // the lines drawn, in order, for ranges
  let index = new Map();            // MBOM uid -> {node, parent, at}, made again after every edit (the structure replaces its nodes on undo)
  let order = [];                   // the MBOM lines, in tree order

  // ---- Making the structure ------------------------------------------------------------

  function mbomFromTree(node) {
    return { number: node.number, name: node.name, quantity: node.quantity || '', itemId: node.item_id, edgeId: node.edge_id, cut: !!node.cut,
             children: (node.children || []).map(mbomFromTree) };
  }

  /** Build the structure from the EBOM and, when Fusion Manage has the MBOM item, its tree (else the MBOM starts as a copy of the EBOM). */
  function build(tree) {
    const design = host.design();
    ebom = S.ebomFromRows(host.rows(), { item_number: design.item_number, name: design.name || design.description || design.file_name, component_id: design.component_id });
    const read = tree ? S.mapByNumber(mbomFromTree(tree), ebom) : null;
    structure = S.create({ ebom: ebom, mbom: read, phantom: !!host.phantom() });
    phase = 'idle';
    clearState();
    reindex();
  }

  /** What belongs to one structure: the form, a drag, the search, the selection and the folds (uids start again with each structure). */
  function clearState() {
    closeForm();
    clearMark();
    drag = null;
    searchText = '';
    hitIndex = -1;
    dom.search.value = '';
    hits.clear(); selected.clear(); ebomSelected.clear();
    anchor = ''; message = '';
    opened.clear(); opened.add(S.ROOT); ebomOpened.clear(); ebomOpened.add('0');
    Object.keys(more).forEach(function (k) { delete more[k]; });
  }

  function reindex() {
    index = new Map();
    order = [];
    (function walk(node, parent, at) {
      index.set(node.uid, { node: node, parent: parent, at: at });
      if (parent) order.push(node);
      node.children.forEach(function (c, i) { walk(c, node, i); });
    })(structure.root(), null, 0);
  }

  /** Go as far as the data allows: wait for the first level, read the whole EBOM, read the MBOM, then build and draw. Each read is asked once:
   *  while one is on its way the viewer only waits, and a structure that exists (with edits) is never replaced. */
  function refresh() {
    if (!active) return;
    if (structure) { render(); return; }
    if (phase === 'mbom') return;
    if (!ready) { wait('structure', t('publish.reading_bom')); return; }
    if (host.partial()) {
      if (phase !== 'tree') { wait('tree', t('publish.reading_tree')); host.loadTree(); }
      return;
    }
    if (host.targetId()) { wait('mbom', t('publish.sv_reading_mbom')); host.askMbom(); return; }
    build(null);
    render();
  }

  function wait(next, text) {
    phase = next;
    note = text;
    render();
  }

  function fail(text, retry) {
    phase = 'error';
    note = text;
    dom.state.replaceChildren(ui.errorState(text, retry));
    render();
  }

  /** The answer of the ``mbom_tree`` section. One that nobody waits for (a second answer, or one after the Bill of Materials was read again) is ignored,
   *  so edits are never replaced. */
  function answer(entry) {
    if (structure || phase !== 'mbom') return;
    if (!entry.ok) { fail(entry.message || t('publish.unknown_error'), function () { phase = 'idle'; refresh(); }); return; }
    build(entry.data);
    render();
  }

  /** The whole tree was read (or failed) for the panel's table; the viewer may have been waiting for it. */
  function treeDone(entry) {
    if (!entry.ok) {
      if (active && !structure && phase === 'tree') fail(entry.message || t('publish.unknown_error'), function () { phase = 'idle'; refresh(); });
      return;
    }
    refresh();
  }

  /** The Bill of Materials is read again: what was built from the old one is dropped. */
  function reset() {
    ready = false;
    structure = null;
    ebom = null;
    phase = 'idle';
    clearState();
    index = new Map();
    order = [];
    if (active) refresh();
  }

  // ---- Edits ---------------------------------------------------------------------------

  function prune() {
    Array.from(selected).forEach(function (id) { if (!index.has(id)) selected.delete(id); });
    if (anchor && !selected.has(anchor) && !ebomSelected.has(anchor)) anchor = '';
  }

  /** The search again, for the lines now in the tree (an edit may have added, removed or renamed some); ``open`` opens what is above each hit. */
  function findHits(open) {
    hits.clear();
    hitIndex = -1;
    if (!searchText) return;
    structure.search(searchText).forEach(function (uid) { hits.add(uid); if (open) reveal(uid); });
  }

  /** After the structure changed (an edit, undo or redo): its lines are looked up again, and the selection and the search follow. */
  function changed() {
    reindex();
    prune();
    findHits(false);
    render();
  }

  /** Run an edit. A refusal is shown in the message line and nothing changes. Returns ``{ok, value}``. */
  function run(change) {
    let value;
    try {
      value = change();
      message = '';
    } catch (error) {
      message = describe(error);
      reindex();   // a refused edit puts back a copy of the tree
      render();
      return { ok: false };
    }
    changed();
    return { ok: true, value: value };
  }

  function openPlace(place) { opened.add(place.parentId); }

  function dropOn(place, event) {
    openPlace(place);
    if (drag.from === 'ebom') {
      const keys = drag.ids;
      run(function () { structure.addFromEbom(keys, place.parentId, place.before, !event.altKey); });
    } else if (event.ctrlKey || event.metaKey) {
      const ids = drag.ids;
      run(function () { return structure.copy(ids, place.parentId, place.before); });
    } else {
      const ids = drag.ids;
      run(function () { structure.move(ids, place.parentId, place.before); });
    }
  }

  function setQuantity(id, value) { run(function () { structure.setQuantity(id, value); }); }

  function editQuantity(button, id) {
    const input = el('input', 'sv-qty-input');
    input.type = 'text';
    input.value = button.textContent;
    input.setAttribute('aria-label', t('publish.sv_qty_title'));
    let finished = false;
    function finish(commit) {
      if (finished) return;
      finished = true;
      if (commit && shownQuantity(input.value.trim()) !== button.textContent) setQuantity(id, input.value);
      else render();
    }
    input.addEventListener('keydown', function (event) {
      event.stopPropagation();
      if (event.key === 'Enter') finish(true);
      else if (event.key === 'Escape') finish(false);
    });
    input.addEventListener('blur', function () { finish(true); });
    button.replaceWith(input);
    input.focus();
    input.select();
  }

  // ---- Selection and the toolbar --------------------------------------------------------

  /** Click, ctrl-click and shift-click on ``id`` in a pane whose lines, in order, are ``list``. */
  function choose(set, list, id, event) {
    if (event.shiftKey && anchor && list.indexOf(anchor) >= 0) {
      const from = list.indexOf(anchor);
      const to = list.indexOf(id);
      if (!(event.ctrlKey || event.metaKey)) set.clear();
      list.slice(Math.min(from, to), Math.max(from, to) + 1).forEach(function (x) { set.add(x); });
      return;
    }
    anchor = id;
    if (event.ctrlKey || event.metaKey) {
      if (set.has(id)) set.delete(id); else set.add(id);
    } else {
      set.clear();
      set.add(id);
    }
  }

  function chosenIds() { return order.filter(function (n) { return selected.has(n.uid); }).map(function (n) { return n.uid; }); }

  function parentUid(id) { return index.get(id).parent.uid; }

  function undo() { structure.undo(); message = ''; changed(); }
  function redo() { structure.redo(); message = ''; changed(); }

  /** Where new lines go: inside the one assembly that is selected, else at the end of the MBOM. */
  function placeForNew() {
    const ids = chosenIds();
    if (ids.length === 1 && structure.holds(ids[0])) return { parentId: ids[0], before: '' };
    return { parentId: S.ROOT, before: '' };
  }

  /** A new assembly (or phantom) that takes in ``ids`` (the selected lines when none are named), before the first of them. */
  function assemblyForm(kind, named) {
    const ids = named || chosenIds();
    const first = ids[0];
    const place = first ? { parentId: parentUid(first), before: first } : { parentId: S.ROOT, before: '' };
    openForm({
      title: t('publish.sv_form_assembly'),
      fields: true,
      submit: function (values) {
        openPlace(place);
        const done = run(function () { return structure.createAssembly(kind, place.parentId, place.before, values, ids); });
        if (done.ok) { opened.add(done.value); render(); }
        return done.ok;
      },
    });
  }

  /** Split off the lines selected directly under the assembly ``assemblyId``: into an assembly that is there already (one the lines are not in), where
   *  an item it has already is joined to, or else into a new one named in the fields. */
  function splitForm(assemblyId) {
    const parent = index.get(assemblyId).node;
    const ids = parent.children.filter(function (c) { return selected.has(c.uid); }).map(function (c) { return c.uid; });
    const chosen = new Set(ids);
    const inside = new Set();   // the lines being split off and what is under them: the target cannot be one of them
    (function walk(list) { list.forEach(function (c) { inside.add(c.uid); walk(c.children); }); })(parent.children.filter(function (c) { return chosen.has(c.uid); }));
    const targets = [structure.root()].concat(order).filter(function (n) { return n.uid !== parent.uid && !inside.has(n.uid) && structure.holds(n.uid); });
    const label = function (uid) { const entry = index.get(uid); const n = entry && entry.node; return n ? [n.number, n.name].filter(Boolean).join(' - ') : ''; };
    openForm({
      title: t('publish.sv_form_split'),
      picker: {
        ariaLabel: t('publish.sv_split_target'), placeholder: t('publish.sv_split_target'), search: t('publish.sv_search_placeholder'), required: false,
        label: label, groups: function () { return [{ title: '', items: targets.map(function (n) { return { value: n.uid, label: label(n.uid) }; }) }]; },
      },
      fields: true,
      submit: function (values) {
        if (values.target) {
          opened.add(values.target);
          return run(function () { structure.splitInto(parent.uid, ids, values.target); }).ok;
        }
        const done = run(function () { return structure.split(parent.uid, ids, 'assembly', values); });
        if (done.ok) { opened.add(done.value); render(); }
        return done.ok;
      },
    });
  }

  function addItems() {
    const place = placeForNew();
    const staged = [];
    order.forEach(function (c) { if (c.itemId) staged.push(c.itemId); });
    const mine = structure;
    ns.pubAddItems.open({
      itemId: host.targetId(),
      staged: staged,
      onAdd: function (items) {
        if (structure !== mine) return;   // the picker was open while the Bill of Materials was read again: the lines it names are not these
        openPlace(place);
        run(function () { return structure.addItems(items, place.parentId, place.before); });
      },
    });
  }

  /** What an action on a line applies to: the whole selection when the line is part of it (and several are selected), else the line. */
  function targetsOf(pane, id) {
    if (pane === 'mbom') return selected.has(id) ? chosenIds() : [id];
    return ebomSelected.has(id) ? visible.ebom.filter(function (k) { return ebomSelected.has(k); }) : [id];
  }

  /** An icon on a line was used. */
  function rowAction(pane, id, act) {
    const targets = targetsOf(pane, id);
    if (pane === 'ebom') {
      const place = placeForNew();
      openPlace(place);
      run(function () { structure.addFromEbom(targets, place.parentId, place.before, act === 'add_deep'); });
    } else if (act === 'copy') {
      const place = structure.position('after', targets[targets.length - 1]);   // next to the last of them
      openPlace(place);
      run(function () { return structure.copy(targets, place.parentId, place.before); });
    } else if (act === 'remove') {
      run(function () { structure.remove(targets); });
    } else if (act === 'assembly') {
      assemblyForm('assembly', targets);
    } else if (act === 'split') {
      splitForm(id);
    }
  }

  /** The state of each toolbar button: enabled, or disabled with the reason as its tooltip. */
  function updateTools() {
    const b = dom.tools;
    function set(button, reason) { button.disabled = !!reason; button.title = reason || button.getAttribute('aria-label'); }   // the reason is the tooltip of one that cannot be used
    set(b.undo, structure.canUndo() ? '' : t('publish.sv_nothing_to_undo'));
    set(b.redo, structure.canRedo() ? '' : t('publish.sv_nothing_to_redo'));
  }

  // ---- Form under the toolbar ------------------------------------------------------------

  function closeForm() {
    dom.form.hidden = true;
    dom.form.replaceChildren();
  }

  /** The inline form: item number and name (``fields``) or a picker (``picker``), with Create and Cancel. ``submit(values)`` gives true when it was done. */
  function openForm(spec) {
    const form = dom.form;
    form.replaceChildren(el('h4', 'sv-form-title', spec.title));
    const values = { number: '', name: '', target: '' };
    const inputs = [];
    if (spec.fields) {
      [['number', t('publish.sv_form_number')], ['name', t('publish.sv_form_name')]].forEach(function (pair) {
        const input = el('input', 'sv-input');
        input.type = 'text';
        input.autocomplete = 'off';
        input.spellcheck = false;
        input.placeholder = pair[1];
        input.setAttribute('aria-label', pair[1]);
        input.addEventListener('input', function () { values[pair[0]] = input.value; });
        inputs.push(input);
        form.appendChild(input);
      });
    }
    if (spec.picker) {
      const picker = ns.picker.make(Object.assign({ className: 'sv-form-pk', searchFrom: 8 }, spec.picker), '');
      picker.addEventListener('pick', function () { values.target = (picker.getPicked()[0] || {}).value || ''; });
      form.appendChild(picker);
    }
    const ok = el('button', 'btn sv-btn', t('publish.sv_form_ok'));
    ok.type = 'button';
    const cancel = el('button', 'btn btn-secondary sv-btn', t('publish.cancel'));
    cancel.type = 'button';
    const actions = el('div', 'sv-form-actions');
    actions.append(ok, cancel);
    form.appendChild(actions);
    function submit() { if (spec.submit(values)) closeForm(); }
    ok.addEventListener('click', submit);
    cancel.addEventListener('click', closeForm);
    form.onkeydown = function (event) {
      if (event.key === 'Enter' && event.target.tagName === 'INPUT') { event.preventDefault(); submit(); }
      else if (event.key === 'Escape') closeForm();
    };
    form.hidden = false;
    if (inputs[0]) inputs[0].focus();
  }

  // ---- Drawing -------------------------------------------------------------------------

  /** A quantity as shown: a whole number gets ".0", a decimal stays as it is. */
  function shownQuantity(text) { return /^\d+$/.test(text) ? text + '.0' : text; }

  function badge(text, kind) { return el('span', 'sv-badge sv-badge-' + kind, text); }

  /** A check mark for an EBOM line that is all in the MBOM. */
  function matchedMark() {
    const mark = el('span', 'sv-matched');
    mark.title = t('publish.sv_matched');
    mark.setAttribute('aria-label', t('publish.sv_matched'));
    mark.appendChild(ns.svg(['M5 12.5l4.5 4.5L19 7'], 14));
    return mark;
  }

  /** One line: indent, open/close, label, quantity and badges. ``spec``: id, depth, number, name, quantity, editable, hasKids, isOpen, badges, classes, draggable. */
  /** The icons at the right of a line, shown when it is pointed at or has the keyboard (they stay in the tab order). Each is
   *  ``{act, icon, label, reason}``: a ``reason`` disables it and is its tooltip. A line that can be dragged has a handle first. */
  function actionsNode(actions, handle) {
    const box = el('span', 'sv-actions');
    box.setAttribute('role', 'group');
    if (handle) {
      const grip = el('span', 'sv-grip');
      grip.title = t('publish.sv_act_drag');
      grip.appendChild(ns.svg(ICONS.grip, 16));
      box.appendChild(grip);
    }
    actions.forEach(function (a) {
      const b = el('button', 'sv-act');
      b.type = 'button';
      b.dataset.act = a.act;
      b.setAttribute('aria-label', a.label);
      b.title = a.reason || a.label;
      b.disabled = !!a.reason;
      b.appendChild(ns.svg(ICONS[a.icon], 16));
      box.appendChild(b);
    });
    return box;
  }

  /** The text of an action on a line, with how many lines it takes in when the line is one of several selected. */
  function actionLabel(text, count) { return count > 1 ? t('publish.sv_act_many', { action: text, count: count }) : text; }

  function lineNode(spec) {
    const row = el('div', 'sv-row' + (spec.classes ? ' ' + spec.classes : ''));
    row.dataset.id = spec.id;
    row.setAttribute('role', 'treeitem');
    row.setAttribute('aria-level', String(spec.depth + 1));
    row.setAttribute('aria-selected', spec.classes && /(^| )selected( |$)/.test(spec.classes) ? 'true' : 'false');
    if (spec.hasKids) row.setAttribute('aria-expanded', spec.isOpen ? 'true' : 'false');
    row.style.setProperty('--indent', (spec.depth * 32) + 'px');
    if (spec.draggable) row.dataset.drag = '1';   // it can be dragged (by the pointer, see pointerDown)
    const toggle = el('button', 'sv-toggle');
    toggle.type = 'button';
    if (spec.hasKids) {
      toggle.setAttribute('aria-label', t('publish.sv_toggle'));
      toggle.setAttribute('aria-expanded', spec.isOpen ? 'true' : 'false');
      const chevron = ui.chevron();
      ui.setChevron(chevron, !spec.isOpen);
      toggle.appendChild(chevron);
    } else {
      toggle.disabled = true;
    }
    row.appendChild(toggle);
    row.appendChild(ui.treeIcon(spec.depth === 0 ? 'root' : spec.hasKids ? 'assembly' : 'part'));   // the table's icon, with its bar on the right
    if (spec.seq) row.appendChild(el('span', 'sv-seq', spec.seq));   // the line's number, as the table shows it
    const label = el('span', 'sv-label');
    label.appendChild(el('span', 'sv-pn', spec.number || '-'));
    if (spec.name) label.appendChild(el('span', 'sv-name', spec.name));
    row.appendChild(label);
    spec.badges.forEach(function (b) { row.appendChild(b); });
    if (spec.actions && spec.actions.length) row.appendChild(actionsNode(spec.actions, spec.draggable));   // over the end of the label, left of the quantity
    if (spec.quantity !== '') {
      if (spec.editable) {
        const qty = el('button', 'sv-qty', shownQuantity(spec.quantity));
        qty.type = 'button';
        qty.title = t('publish.sv_qty_title');
        row.appendChild(qty);
      } else {
        row.appendChild(el('span', 'sv-qty sv-qty-fixed', shownQuantity(spec.quantity)));
      }
    }
    return row;
  }

  function moreNode(parentId, hidden) {
    const row = el('button', 'sv-more', t('publish.sv_more', { count: hidden }));
    row.type = 'button';
    row.dataset.more = parentId;
    return row;
  }

  function drawEbom(container, cmp) {
    const list = [];
    const texts = { quantity: t('publish.sv_state_quantity'), exceeded: t('publish.sv_state_exceeded'), moved: t('publish.sv_state_moved') };
    (function walk(node, depth) {
      const state = cmp.ebom[node.key];
      const badges = [];
      if (state) ['quantity', 'moved'].forEach(function (k) {
        if (!state[k]) return;
        const kind = k === 'quantity' && state.exceeded ? 'exceeded' : k;   // over the EBOM's quantity is told apart from short of it
        badges.push(badge(texts[kind], kind));
      });
      if (state && state.matched) badges.unshift(matchedMark());
      const isOpen = ebomOpened.has(node.key);
      if (depth) list.push(node.key);
      const count = ebomSelected.has(node.key) ? ebomSelected.size : 1;
      const full = !!(state && (state.exceeded || state.matched));   // all of it is in the MBOM: adding it again would be more than the EBOM has
      const actions = depth && !full ? [{ act: 'add_one', icon: 'addOne', label: actionLabel(t('publish.sv_act_add_one'), count) }] : [];
      if (actions.length && node.children.length) actions.unshift({ act: 'add_deep', icon: 'addDeep', label: actionLabel(t('publish.sv_act_add_deep'), count) });
      const row = lineNode({ id: node.key, depth: depth, number: node.number, name: node.name, quantity: depth ? node.quantity : '', editable: false, hasKids: node.children.length > 0,
                             isOpen: isOpen, badges: badges, draggable: depth > 0 && !full, actions: actions, seq: depth ? node.sequence : '',
                             classes: (ebomSelected.has(node.key) ? 'selected ' : '') + (state && state.missing ? 'sv-row-missing ' : '') + (state && state.matched ? 'sv-row-matched' : '') });
      container.appendChild(row);
      if (!isOpen) return;
      const shown = more[node.key] || LIMIT;
      node.children.slice(0, shown).forEach(function (c) { walk(c, depth + 1); });
      if (node.children.length > shown) container.appendChild(moreNode(node.key, node.children.length - shown));
    })(ebom, 0);
    visible.ebom = list;
  }

  function drawMbom(container, cmp, chg) {
    const list = [];
    const flagTexts = { new: t('publish.sv_chg_new'), moved: t('publish.sv_chg_moved'), quantity: t('publish.sv_chg_quantity'), reordered: t('publish.sv_chg_reordered') };
    const kindTexts = { assembly: t('publish.sv_kind_assembly'), phantom: t('publish.sv_kind_phantom'), added: t('publish.sv_kind_added') };
    (function walk(node, depth) {
      const badges = [];
      let classes = selected.has(node.uid) ? 'selected ' : '';
      if (kindTexts[node.kind]) badges.push(badge(kindTexts[node.kind], 'kind'));
      if (node.cut) badges.push(badge(t('publish.sv_cut'), 'cut'));
      if (depth && cmp.mbom[node.uid] === 'mfg' && node.kind === 'component') badges.push(badge(t('publish.sv_unmapped'), 'mfg'));
      const flags = chg.changes[node.uid];
      if (flags) ['new', 'moved', 'quantity', 'reordered'].forEach(function (k) { if (flags[k]) { badges.push(badge(flagTexts[k], 'chg-' + k)); classes += 'sv-chg-' + k + ' '; } });
      if (hits.has(node.uid)) classes += 'sv-hit ';
      const isOpen = opened.has(node.uid);
      if (depth) list.push(node.uid);
      const count = selected.has(node.uid) ? selected.size : 1;
      const actions = [];
      if (depth) {   // always in this order: split (an assembly), copy, new assembly, and the bin last
        if (node.children.length || node.kind === 'assembly' || node.kind === 'phantom') {
          const some = node.children.filter(function (c) { return selected.has(c.uid); }).length;
          actions.push({ act: 'split', icon: 'split', label: t('publish.sv_act_split'), reason: some > 0 && some < node.children.length ? '' : t('publish.sv_need_some_lines') });
        }
        actions.push({ act: 'copy', icon: 'copy', label: actionLabel(t('publish.sv_act_copy'), count) },
                     { act: 'assembly', icon: 'assembly', label: actionLabel(t('publish.sv_act_assembly'), count) },
                     { act: 'remove', icon: 'remove', label: actionLabel(t('publish.sv_act_remove'), count) });
      }
      container.appendChild(lineNode({ id: node.uid, depth: depth, number: node.number, name: node.name, quantity: depth ? node.quantity : '', editable: depth > 0,
                                       hasKids: node.children.length > 0, isOpen: isOpen, badges: badges, draggable: depth > 0, actions: actions, seq: depth ? String(index.get(node.uid).at + 1) : '', classes: classes.trim() }));
      if (!isOpen) return;
      const shown = more[node.uid] || LIMIT;
      node.children.slice(0, shown).forEach(function (c) { walk(c, depth + 1); });
      if (node.children.length > shown) container.appendChild(moreNode(node.uid, node.children.length - shown));
    })(structure.root(), 0);
    visible.mbom = list;
  }

  function render() {
    if (!dom) return;
    const showing = !!structure && phase !== 'error';
    dom.panes.hidden = !showing;
    dom.tools.bar.hidden = !showing;
    dom.footer.hidden = !showing;
    dom.state.hidden = showing;
    if (!structure && (phase === 'structure' || phase === 'tree' || phase === 'mbom')) dom.state.replaceChildren(el('p', 'muted sv-wait', note));
    if (!structure && phase === 'idle') dom.state.replaceChildren();
    dom.message.hidden = !message;
    dom.message.textContent = message;
    if (!showing) return;
    const cmp = structure.compare();
    const chg = structure.changes();
    const scroll = [dom.ebomTree.scrollTop, dom.mbomTree.scrollTop];
    dom.ebomTree.replaceChildren();
    dom.mbomTree.replaceChildren();
    drawEbom(dom.ebomTree, cmp);
    drawMbom(dom.mbomTree, cmp, chg);
    dom.ebomTree.scrollTop = scroll[0];
    dom.mbomTree.scrollTop = scroll[1];
    dom.removed.textContent = chg.removed.length
      ? t('publish.sv_removed', { numbers: chg.removed.map(function (r) { return r.cascade ? r.number + ' (+' + r.cascade + ')' : r.number; }).join(', ') }) : '';
    dom.found.textContent = searchText ? (hits.size ? t('publish.sv_search_count', { count: hits.size }) : t('publish.sv_search_none')) : '';
    updateTools();
  }

  // ---- Events (one listener for each pane) ---------------------------------------------

  function expandAll(on) {
    opened.clear(); opened.add(S.ROOT); ebomOpened.clear(); ebomOpened.add('0');
    if (on) {
      (function walk(node) { node.children.forEach(function (c) { if (c.children.length) { opened.add(c.uid); walk(c); } }); })(structure.root());
      (function walk(node) { node.children.forEach(function (c) { if (c.children.length) { ebomOpened.add(c.key); walk(c); } }); })(ebom);
    }
    dropHidden();
    render();
  }

  /** Open the assemblies above a line, and draw it even when it is past the first lines under its assembly. */
  function reveal(uid) {
    let entry = index.get(uid);
    while (entry && entry.parent) {
      opened.add(entry.parent.uid);
      if (entry.at >= (more[entry.parent.uid] || LIMIT)) more[entry.parent.uid] = entry.at + 1;
      entry = index.get(entry.parent.uid);
    }
  }

  /** Whether the line is drawn: every assembly above it is open. */
  function isShown(uid) {
    let entry = index.get(uid);
    while (entry && entry.parent) {
      if (!opened.has(entry.parent.uid)) return false;
      entry = index.get(entry.parent.uid);
    }
    return true;
  }

  /** A selection must not hold lines that are not in view (an edit of the selection would take them along): drop what a fold hid. */
  function dropHidden() {
    Array.from(selected).forEach(function (id) { if (!isShown(id)) selected.delete(id); });
    Array.from(ebomSelected).forEach(function (key) {
      const parts = key.split('.');
      for (let n = 1; n < parts.length; n++) {
        if (!ebomOpened.has(parts.slice(0, n).join('.'))) { ebomSelected.delete(key); return; }
      }
    });
    if (anchor && !selected.has(anchor) && !ebomSelected.has(anchor)) anchor = '';
  }

  function runSearch(text) {
    searchText = text.trim();
    findHits(true);
    render();
  }

  function nextHit() {
    const list = Array.from(hits);
    if (!list.length) return;
    hitIndex = (hitIndex + 1) % list.length;
    const row = dom.mbomTree.querySelector('[data-id="' + list[hitIndex] + '"]');
    if (row && row.scrollIntoView) row.scrollIntoView({ block: 'center' });
  }

  function paneClick(pane, event) {
    const moreButton = event.target.closest('.sv-more');
    if (moreButton) { moreClick(moreButton.dataset.more); return; }
    const row = event.target.closest('.sv-row');
    if (!row) return;
    const id = row.dataset.id;
    const act = event.target.closest('.sv-act');
    if (act) { if (!act.disabled) rowAction(pane, id, act.dataset.act); return; }
    if (event.target.closest('.sv-grip')) return;
    if (event.target.closest('.sv-toggle')) {
      const set = pane === 'mbom' ? opened : ebomOpened;
      if (set.has(id)) set.delete(id); else set.add(id);
      dropHidden();
      render();
      return;
    }
    if (pane === 'mbom' && event.target.closest('button.sv-qty')) { editQuantity(event.target.closest('button.sv-qty'), id); return; }
    if (pane === 'mbom' && id === S.ROOT) return;
    if (pane === 'mbom') choose(selected, visible.mbom, id, event);
    else if (id !== '0') choose(ebomSelected, visible.ebom, id, event);
    render();
  }

  function moreClick(id) {
    more[id] = (more[id] || LIMIT) + LIMIT;
    render();
  }

  function clearMark() {
    if (dropMark) dropMark.classList.remove('sv-drop-before', 'sv-drop-after', 'sv-drop-into');
    dropMark = null;
  }

  /** The place a drag over the MBOM pane would drop: from the line it is over and where in it, else the end of the MBOM. */
  function placeAt(event) {
    const row = event.target.closest ? event.target.closest('.sv-row') : null;
    if (!row) return { place: { parentId: S.ROOT, before: '' }, row: null, zone: '' };
    const id = row.dataset.id;
    const box = row.getBoundingClientRect();
    const zone = id === S.ROOT ? 'into' : S.zoneOf(event.clientY - box.top, box.height, structure.holds(id));
    return { place: structure.position(zone, id), row: row, zone: zone };
  }

  // The drag is made from mouse events, not the browser's own drag and drop: Fusion's embedded browser does not carry that through.
  const DRAG_START_PX = 5;   // how far the pointer goes with the button down before it is a drag and not a click
  const EDGE_PX = 28;        // near the top or bottom of a pane a drag scrolls it
  let pressed = null;        // the button is down on a line: {pane, row, x, y, ghost}
  let justDragged = false;   // the click that ends a drag is not a selection

  function startDrag(pane, row) {
    const id = row.dataset.id;
    const set = pane === 'mbom' ? selected : ebomSelected;
    const order = pane === 'mbom' ? visible.mbom : visible.ebom;
    if (!set.has(id)) {   // no redraw: the line being dragged must stay in the page
      set.clear(); set.add(id);
      (pane === 'mbom' ? dom.mbomTree : dom.ebomTree).querySelectorAll('.sv-row').forEach(function (r) {
        r.classList.toggle('selected', r.dataset.id === id);
        r.setAttribute('aria-selected', r.dataset.id === id ? 'true' : 'false');
      });
    }
    drag = { from: pane, ids: order.filter(function (x) { return set.has(x); }) };
  }

  /** The element the pointer is over in the MBOM pane (a line, or the pane itself, which is the end of the MBOM), or null when it is elsewhere. */
  function mbomTarget(event) {
    const over = document.elementFromPoint(event.clientX, event.clientY);
    return over && dom.mbomTree.contains(over) ? over : null;
  }

  function scrollNear(tree, y) {
    const box = tree.getBoundingClientRect();
    if (y < box.top + EDGE_PX) tree.scrollTop -= 14;
    else if (y > box.bottom - EDGE_PX) tree.scrollTop += 14;
  }

  function pointerMove(event) {
    if (!pressed || !structure) return;
    if (!pressed.ghost) {
      if (Math.abs(event.clientX - pressed.x) < DRAG_START_PX && Math.abs(event.clientY - pressed.y) < DRAG_START_PX) return;
      startDrag(pressed.pane, pressed.row);
      const first = pressed.row.querySelector('.sv-label');
      pressed.ghost = el('div', 'sv-ghost', (first ? first.textContent : '') + (drag.ids.length > 1 ? ' +' + (drag.ids.length - 1) : ''));
      document.body.appendChild(pressed.ghost);
      document.body.style.cursor = 'grabbing';
    }
    event.preventDefault();
    const ghost = pressed.ghost;
    ghost.style.left = (event.clientX + 14) + 'px';
    ghost.style.top = (event.clientY + 10) + 'px';
    ghost.dataset.mode = drag.from === 'mbom' && !(event.ctrlKey || event.metaKey) ? 'move' : 'copy';
    clearMark();
    const over = mbomTarget(event);
    if (!over) return;
    scrollNear(dom.mbomTree, event.clientY);
    const where = placeAt({ target: over, clientY: event.clientY });
    if (where.row) { dropMark = where.row; dropMark.classList.add('sv-drop-' + where.zone); }
  }

  function endPointer() {
    if (pressed && pressed.ghost) pressed.ghost.remove();
    document.body.style.cursor = '';
    document.removeEventListener('mousemove', pointerMove);
    document.removeEventListener('mouseup', pointerUp);
    document.removeEventListener('keydown', pointerKey);
    clearMark();
    pressed = null;
    drag = null;
  }

  function pointerUp(event) {
    if (!pressed) return;
    const dragged = !!pressed.ghost;
    const over = dragged && structure ? mbomTarget(event) : null;
    if (dragged) {
      justDragged = true;
      setTimeout(function () { justDragged = false; }, 0);
    }
    const place = over ? placeAt({ target: over, clientY: event.clientY }).place : null;
    const dropped = drag;
    endPointer();
    if (place) { drag = dropped; dropOn(place, event); drag = null; }
  }

  function pointerKey(event) { if (event.key === 'Escape') endPointer(); }

  function pointerDown(pane, event) {
    if (event.button !== 0 || pressed || !structure) return;
    if (event.target.closest('button, input') && !event.target.closest('.sv-grip')) return;
    const row = event.target.closest('.sv-row');
    if (!row || row.dataset.drag !== '1') return;
    pressed = { pane: pane, row: row, x: event.clientX, y: event.clientY, ghost: null };
    document.addEventListener('mousemove', pointerMove);
    document.addEventListener('mouseup', pointerUp);
    document.addEventListener('keydown', pointerKey);
  }

  function keyMbom(event) {
    if (event.target.closest('input, button')) return;   // a key in a field or on an icon is that control's
    if (event.key === 'Delete' && selected.size) { event.preventDefault(); const ids = chosenIds(); run(function () { structure.remove(ids); }); }
    else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z' && structure.canUndo()) { event.preventDefault(); undo(); }
    else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'y' && structure.canRedo()) { event.preventDefault(); redo(); }
  }

  // ---- The page --------------------------------------------------------------------------

  /** A compact icon button: its tooltip and its accessible name are the same text. */
  function iconButton(icon, label, onClick, className) {
    const b = el('button', 'sv-icon' + (className ? ' ' + className : ''));
    b.type = 'button';
    b.title = label;
    b.setAttribute('aria-label', label);
    const svg = ns.svg(ICONS[icon], 18);
    if (icon === 'boxPlus') [].slice.call(svg.querySelectorAll('path'), -2).forEach(function (p) { p.setAttribute('class', 'sv-plus'); });
    b.appendChild(svg);
    b.addEventListener('click', onClick);
    return b;
  }

  /** One side of the viewer: a header (the title and an info icon with ``hint``) over a tree. */
  function pane(title, hint) {
    const box = el('div', 'sv-pane');
    const head = el('div', 'sv-pane-head');
    const heading = el('span', 'sv-pane-title', title);
    head.appendChild(heading);
    const tree = el('div', 'sv-tree');
    tree.tabIndex = 0;
    tree.setAttribute('role', 'tree');
    tree.setAttribute('aria-multiselectable', 'true');
    tree.setAttribute('aria-label', title);
    box.append(head, tree);
    const info = el('span', 'sv-info', 'i');   // an info icon at the right of the header: the tip shows on hover or focus
    info.tabIndex = 0;
    info.setAttribute('aria-label', t('publish.sv_info_label'));
    const tip = el('span', 'sv-tip', hint);
    tip.setAttribute('role', 'tooltip');
    info.appendChild(tip);
    head.appendChild(info);
    return { box: box, tree: tree };
  }

  function makeDom(root) {
    const tools = { bar: el('div', 'sv-bar') };
    const search = el('input', 'sv-input sv-search');
    search.type = 'search';
    search.placeholder = t('publish.sv_search_placeholder');
    search.setAttribute('aria-label', t('publish.sv_search_placeholder'));
    let timer = 0;
    search.addEventListener('input', function () {
      clearTimeout(timer);
      timer = setTimeout(function () { if (structure) runSearch(search.value); }, 150);
    });
    search.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' && structure) { if (search.value.trim() !== searchText) runSearch(search.value); nextHit(); }
    });
    const found = el('span', 'sv-found muted');
    tools.undo = iconButton('undo', t('publish.sv_undo'), undo);
    tools.redo = iconButton('redo', t('publish.sv_redo'), redo);
    tools.fold = ns.bomTable.foldTools(function () { expandAll(false); }, function () { expandAll(true); }, false, '');   // the table's own pair of buttons
    const history = el('div', 'sv-pair');   // undo and redo, as a pair like collapse and expand
    history.append(tools.undo, tools.redo);
    tools.assembly = iconButton('boxPlus', t('publish.sv_create_assembly'), function () { assemblyForm('assembly'); });
    tools.add = iconButton('addItems', t('publish.sv_add_items'), addItems);
    const searchBox = el('div', 'sv-search-box');   // the field with a magnifier inside it
    searchBox.append(ns.svg(ICONS.search, 16), search);
    tools.bar.append(searchBox, found, tools.fold, history, tools.assembly, tools.add);
    const form = el('div', 'sv-form');
    form.hidden = true;
    const messageLine = el('p', 'error sv-message');
    messageLine.setAttribute('role', 'alert');
    messageLine.hidden = true;
    const state = el('div', 'sv-state');
    const left = pane(t('publish.sv_ebom_title'), t('publish.sv_ebom_tip'));
    const right = pane(t('publish.sv_mbom_title'), t('publish.sv_mbom_tip'));
    const panes = el('div', 'sv-panes');
    panes.append(left.box, right.box);
    const removed = el('p', 'muted sv-removed');
    const footer = el('div', 'sv-footer');
    footer.appendChild(removed);
    root.replaceChildren(tools.bar, form, messageLine, state, panes, footer);

    left.tree.addEventListener('click', function (event) { paneClick('ebom', event); });
    right.tree.addEventListener('click', function (event) { paneClick('mbom', event); });
    [['ebom', left.tree], ['mbom', right.tree]].forEach(function (pair) {
      pair[1].addEventListener('mousedown', function (event) { pointerDown(pair[0], event); });
      pair[1].addEventListener('click', function (event) { if (justDragged) { event.stopPropagation(); justDragged = false; } }, true);   // the end of a drag selects nothing
    });
    right.tree.addEventListener('keydown', keyMbom);
    return { root: root, tools: tools, search: search, form: form, message: messageLine, state: state, panes: panes, footer: footer, removed: removed, found: found,
             ebomTree: left.tree, mbomTree: right.tree };
  }

  /** Show the Structure view (``on``) or the table. What was built is kept while the table is on, so edits are not lost. */
  function show(on) {
    active = on;
    ns.$('pub-bom').hidden = on;
    ns.$('pub-structure').hidden = !on;
    ns.$('pub-add-items').hidden = on;
    ns.$('pub-view-table').setAttribute('aria-pressed', on ? 'false' : 'true');
    ns.$('pub-view-structure').setAttribute('aria-pressed', on ? 'true' : 'false');
    if (on) refresh();
  }

  /** ``hostApi`` is the panel (see the header). Wires the two buttons that switch between the table and the structure. */
  function init(hostApi) {
    host = hostApi;
    dom = makeDom(ns.$('pub-structure'));
    ns.$('pub-view-table').addEventListener('click', function () { show(false); });
    ns.$('pub-view-structure').addEventListener('click', function () { show(true); });
  }

  ns.mbomViewer = {
    init: init, reset: reset, answer: answer, treeDone: treeDone,
    structureRead: function () { ready = true; refresh(); },
    showTable: function () { show(false); },   // the MBOM has to be chosen, and the choice is drawn in the table's place
  };
})(window.MfgUi);
