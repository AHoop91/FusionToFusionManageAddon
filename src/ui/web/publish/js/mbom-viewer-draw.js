/**
 * Publish Item panel: the drawing of the structure viewer's two panes (mbom-viewer.js), as ``ns.mbomViewerDraw``. It turns the EBOM and the MBOM into rows (a line,
 * its notes, its icons, "Show more") and says what the viewer's state and the structure's comparison put in each. It reads the viewer's state through one object
 * and changes none of it: what the viewer does with a click is in mbom-viewer.js. Layer: UI (DOM drawing); the rules are in mbom-structure.js and mbom-plan.js.
 *
 * ``bind(ctx)`` is called once by the viewer with the state to read: ``host``, ``structure``, ``ebom``, ``view`` (the held, ebomAt and parentOf lookups) and ``detailsAt``
 * (read each time, so they follow the viewer's own), the sets ``selected``, ``ebomSelected``, ``hits``, ``ebomHits``, ``opened``, ``ebomOpened`` and ``openNotes``, the object
 * ``more`` (parent id -> lines drawn under it) and ``filterView()``. ``drawEbom(container, cmp)`` and ``drawMbom(container, cmp, chg)`` fill a pane and return the ids
 * of the lines drawn, in order.
 */
(function (ns) {
  'use strict';

  const ui = ns.pubUi;
  const el = ns.el;
  function t(key, params) { return ns.i18n.t(key, params); }

  const LIMIT = 200;   // lines drawn under an assembly before "Show more"
  let ctx = null;      // the viewer's state, see ``bind``

  const ICONS = {   // svg paths (24 x 24) of the buttons and of the actions on a line
    remove: ['M5 7h14', 'M9 7V4h6v3', 'M7 7l1 13h8l1-13', 'M10 11v6', 'M14 11v6'],
    assembly: ['M12 3l8 4.5v9L12 21l-8-4.5v-9z', 'M12 9.5v5', 'M9.5 12h5'],
    boxPlus: ['M10 3l7 4v6', 'M17 7l-7 4-7-4', 'M10 11v9', 'M3 7v10l7 4', 'M10 3L3 7', 'M18 14.5v7', 'M14.5 18h7'],   // a box like the BOM's, with a plus at its bottom right (the last two paths)
    bought: ['M3 4h2.5l2 11h10l2-8H7', 'M10 19.5h.01', 'M17 19.5h.01'],   // a trolley
    spanner: ['M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z'],   // a spanner: a line of manufacturing's own, not in the EBOM
    cart: ['M8 20a1 1 0 1 0 0 2 1 1 0 0 0 0-2z', 'M19 20a1 1 0 1 0 0 2 1 1 0 0 0 0-2z', 'M2 3h2l2.7 12.4a2 2 0 0 0 2 1.6h9.7a2 2 0 0 0 2-1.6L22 7H5.1'],   // a shopping cart: a purchased part
    info: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', 'M12 11v6', 'M12 7.5v.5'],   // a circle with an i: the note of a line
    position: ['M8 4v16', 'M5 7l3-3 3 3', 'M16 20V4', 'M13 17l3 3 3-3'],   // an arrow up beside an arrow down: the line goes up or down the assembly
    split: ['M12 4v5', 'M12 9L6 15', 'M12 9l6 6', 'M6 15v5', 'M18 15v5'],   // one line branching into two: a quantity shared between assemblies
    renumber: ['M4 5h2v6', 'M4 14h4v2.5l-4 2.5h4', 'M11 8h9', 'M11 17h9'],   // 1 and 2 beside two lines: the lines numbered again
    match: ['M3 12h12', 'M11 7l5 5-5 5', 'M20 5v14'],   // an arrow into a bar: the EBOM carried over to the MBOM
    addItems: ['M4 6h11', 'M4 12h7', 'M4 18h7', 'M17 14v6', 'M14 17h6'],   // a list with a plus
    grip: ['M9 6h.01', 'M15 6h.01', 'M9 12h.01', 'M15 12h.01', 'M9 18h.01', 'M15 18h.01'],
    addOne: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', 'M12 8v8', 'M8 12h8'],
    search: ['M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z', 'M16 16l4.5 4.5'],
    filter: ['M4 5h16l-6 8v6l-4-2v-4z'],   // a funnel: only the lines the search found (and what is above them)
    undo: ['M9 14L4 9l5-5', 'M4 9h10a6 6 0 0 1 0 12h-3'],
    redo: ['M15 14l5-5-5-5', 'M20 9H10a6 6 0 0 0 0 12h3'],
  };
  /** A quantity as shown: a whole number gets ".0", a decimal stays as it is. */
  function shownQuantity(text) { return /^\d+$/.test(text) ? text + '.0' : text; }

  /** A check mark for an EBOM line that is all in the MBOM (its tooltip says when a purchased part stands for it). */
  function matchedMark(bought) {
    const text = bought ? t('publish.sv_matched_bought') : t('publish.sv_matched');
    const mark = el('span', 'sv-matched');
    mark.title = text;
    mark.setAttribute('aria-label', text);
    mark.appendChild(ns.svg(['M5 12.5l4.5 4.5L19 7'], 14));
    return mark;
  }

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

  /** The colour a line's notes give it: ``warn`` (amber) for a warning or a change to a line of Fusion Manage's, ``new`` (green) for a new line, else '' (blue). */
  function toneOf(notes) {
    const has = function (tone) { return notes.some(function (n) { return n.tone === tone; }); };
    return has('warn') || has('update') ? 'warn' : has('new') ? 'new' : '';
  }

  /** The class that gives a line's icon bar the colour of its notes (``tone``, from ``toneOf``). */
  function toneClass(tone) { return tone ? 'sv-tone-' + tone : ''; }

  /** The button beside a line's quantity that opens what is to be said of the line (``notes``: ``{tone, text}``, tone ``info`` or ``warn``); the same words are its tooltip. */
  function noteButton(notes, key, tone) {   // ``tone``: the same colour as the bar beside the line's icon
    const open = ctx.openNotes.has(key);
    const button = el('button', 'sv-note-btn' + (tone ? ' sv-note-' + tone : '') + (open ? ' open' : ''));
    button.type = 'button';
    button.dataset.note = key;
    button.title = notes.map(function (n) { return n.text; }).join('\n');
    button.setAttribute('aria-label', t('publish.sv_note_label'));
    button.setAttribute('aria-expanded', open ? 'true' : 'false');
    button.appendChild(ns.svg(ICONS.info, 16));
    return button;
  }

  /** The lines under a line whose note is open. */
  function noteRow(notes, depth) {
    const row = el('div', 'sv-note-row');
    row.style.setProperty('--indent', (depth * 32) + 'px');
    notes.forEach(function (n) { row.appendChild(el('p', 'sv-note-line sv-note-' + n.tone, n.text)); });
    return row;
  }

  /** How much of the EBOM line ``key`` the MBOM holds: the quantities of the lines made from it, in every assembly. */
  function heldTotal(key) { return (ctx.view.held[key] || []).reduce(function (sum, l) { return sum + Number(l.quantity); }, 0); }

  /** What is to be said of an EBOM line: what stands for it in the MBOM, and where the quantities do not agree. */
  function ebomNotes(node, state) {
    const notes = [];
    if (!state) return notes;
    const lines = ctx.view.held[node.key] || [];
    const words = { total: shownQuantity(String(heldTotal(node.key))), quantity: shownQuantity(node.quantity) };
    if (state.bought) notes.push({ tone: 'info', text: t('publish.sv_note_bought', { numbers: lines.map(function (l) { return l.number; }).join(', ') }) });
    if (state.exceeded) notes.push({ tone: 'warn', text: t('publish.sv_note_exceeds', words) });
    else if (state.quantity) notes.push({ tone: 'warn', text: t('publish.sv_note_short', words) });
    if (state.moved) {   // which assembly of the MBOM it is under, so it need not be looked for
      const under = lines.map(function (l) { return (ctx.view.parentOf[l.uid] || {}).number || '-'; }).filter(function (n, i, all) { return all.indexOf(n) === i; });
      notes.push({ tone: 'info', text: t('publish.sv_note_moved_ebom', { numbers: under.join(', ') }) });
    }
    return notes;
  }

  /** The notes of an MBOM line on what it stands for: added, an assembly, a phantom, cut. ``from`` is the EBOM line it was made from, or null. */
  function mbomKindNotes(node, from) {
    const notes = [];
    if (node.kind === 'added' && !from) notes.push({ tone: 'info', text: t('publish.sv_note_added') });
    if (node.kind === 'assembly') notes.push({ tone: 'info', text: t('publish.sv_note_assembly') });
    if (node.kind === 'phantom') notes.push({ tone: 'info', text: t('publish.sv_note_phantom') });
    if (node.cut) notes.push({ tone: 'warn', text: t('publish.sv_note_cut') });
    return notes;
  }

  /** The notes of an MBOM line on where it comes from: a bought version of an EBOM line, or an item only Fusion Manage has. */
  function mbomOriginNotes(node, from, cmp) {
    const notes = [];
    if (from && (node.bought || node.kind === 'added')) notes.push({ tone: 'info', text: t('publish.sv_note_bought_for', { number: from.number }) });
    if (cmp.mbom[node.uid] === 'mfg' && node.kind === 'component') notes.push({ tone: 'info', text: t('publish.sv_note_mfg') });
    return notes;
  }

  /** The notes of an MBOM line on what changed in it since Fusion Manage (``flags`` is its entry in ``changes()``). */
  function mbomChangeNotes(node, flags) {
    const notes = [];
    if (flags.new) notes.push({ tone: 'new', text: t('publish.sv_note_new') });
    if (flags.moved) {
      const was = ctx.structure.find(flags.oldParent);
      notes.push({ tone: 'update', text: t('publish.sv_note_moved', { number: was ? was.number || '-' : '-' }) });
    }
    if (flags.quantity) notes.push({ tone: 'update', text: t('publish.sv_note_quantity', { from: shownQuantity(flags.oldQuantity), to: shownQuantity(node.quantity) }) });
    if (flags.reordered) notes.push({ tone: 'update', text: t('publish.sv_note_reordered') });
    return notes;
  }

  /** What is to be said of an MBOM line: what it stands for, what changed in it, and whether it holds more than the EBOM has. */
  function mbomNotes(node, cmp, flags) {
    const from = node.source ? ctx.view.ebomAt[node.source] : null;
    const notes = mbomKindNotes(node, from).concat(mbomOriginNotes(node, from, cmp));
    const state = from ? cmp.ebom[node.source] : null;
    if (state && state.exceeded) {
      notes.push({ tone: 'warn', text: t('publish.sv_note_exceeds', { total: shownQuantity(String(heldTotal(node.source))), quantity: shownQuantity(from.quantity) }) });
    }
    if (flags) notes.push.apply(notes, mbomChangeNotes(node, flags));
    return notes;
  }

  /** The open/close button of a line (disabled when it holds no lines). */
  function buildLineToggle(spec) {
    const toggle = el('button', 'sv-toggle');
    toggle.type = 'button';
    if (!spec.hasKids) {
      toggle.disabled = true;
      return toggle;
    }
    toggle.setAttribute('aria-label', t('publish.sv_toggle'));
    toggle.setAttribute('aria-expanded', spec.isOpen ? 'true' : 'false');
    const chevron = ui.chevron();
    ui.setChevron(chevron, !spec.isOpen);
    toggle.appendChild(chevron);
    return toggle;
  }

  /** The icon of a line: the table's icon, a cart for a purchased part, a spanner for an item only Fusion Manage has. */
  function buildLineIcon(spec) {
    const icon = ui.treeIcon(spec.depth === 0 ? 'root' : spec.hasKids ? 'assembly' : 'part');   // the table's icon, with its bar on the right
    if (spec.purchased) {   // a purchased part is a cart, not a box
      icon.replaceChildren(ns.svg(ICONS.cart, 16));
      icon.title = t('publish.sv_purchased_part');
    }
    if (spec.mfgOwn) {   // an item only Fusion Manage has, not a box
      icon.replaceChildren(ns.svg(ICONS.spanner, 16));
      icon.title = t('publish.sv_mfg_item');
    }
    return icon;
  }

  function buildLineLabel(spec) {
    const label = el('span', 'sv-label');
    label.appendChild(el('span', 'sv-pn', spec.number || '-'));
    if (spec.name) label.appendChild(el('span', 'sv-name', spec.name));
    return label;
  }

  /** The quantity of a line (a button when it can be edited) and the room for its note button. */
  function appendLineQuantity(row, spec) {
    if (spec.editable) {
      const qty = el('button', 'sv-qty', shownQuantity(spec.quantity));
      qty.type = 'button';
      qty.title = t('publish.sv_qty_title');
      row.appendChild(qty);
    } else {
      row.appendChild(el('span', 'sv-qty sv-qty-fixed', shownQuantity(spec.quantity)));
    }
    // The note's button is right of the quantity; a line with none keeps the room, so the quantities stay in one column.
    row.appendChild(spec.notes && spec.notes.length ? noteButton(spec.notes, spec.noteKey, spec.tone) : el('span', 'sv-note-slot'));
  }

  /** The attributes of a line: its id, its tree role and level, and what it shows of its state. */
  function describeLine(row, spec) {
    row.dataset.id = spec.id;
    if (spec.details) row.setAttribute('aria-current', 'true');
    row.setAttribute('role', 'treeitem');
    row.setAttribute('aria-level', String(spec.depth + 1));
    row.setAttribute('aria-selected', spec.selected ? 'true' : 'false');
    if (spec.hasKids) row.setAttribute('aria-expanded', spec.isOpen ? 'true' : 'false');
    row.style.setProperty('--indent', (spec.depth * 32) + 'px');
    if (spec.draggable) row.dataset.drag = '1';   // it can be dragged (by the pointer, see pointerDown)
  }

  /** One line: indent, open/close, label, quantity and badges. ``spec``: id, depth, number, name, quantity, editable, hasKids, isOpen, selected, badges, classes,
   *  draggable, actions, seq, notes, noteKey, tone (of the notes), purchased, details (its Details Panel is open). */
  function lineNode(spec) {
    const row = el('div', 'sv-row' + (spec.selected ? ' selected' : '') + (spec.details ? ' sv-details' : '') + (spec.classes ? ' ' + spec.classes : ''));
    describeLine(row, spec);
    row.appendChild(buildLineToggle(spec));
    row.appendChild(buildLineIcon(spec));
    if (spec.seq) row.appendChild(el('span', 'sv-seq', spec.seq));   // the line's number, as the table shows it
    row.appendChild(buildLineLabel(spec));
    spec.badges.forEach(function (b) { row.appendChild(b); });   // the tick, just left of the quantity
    if (spec.actions && spec.actions.length) row.appendChild(actionsNode(spec.actions, spec.draggable));   // over the end of the label, left of the quantity
    if (spec.quantity !== '') appendLineQuantity(row, spec);
    return row;
  }

  function moreNode(parentId, hidden) {
    const row = el('button', 'sv-more', t('publish.sv_more', { count: hidden }));
    row.type = 'button';
    row.dataset.more = parentId;
    return row;
  }

  /** The lines under an open assembly, no more than were asked for (``LIMIT`` at first), and "Show more" under them when there are others. ``drawKid(line)`` draws one. */
  function drawKidLines(container, parentId, kids, drawKid) {
    const shown = ctx.more[parentId] || LIMIT;
    kids.slice(0, shown).forEach(function (kid) { drawKid(kid); });
    if (kids.length > shown) container.appendChild(moreNode(parentId, kids.length - shown));
  }

  /** The icons on an EBOM line: the magnifier on every line, then Create Bought Version and add. */
  function ebomActions(node, depth, state, full) {
    const count = ctx.ebomSelected.has(node.key) ? ctx.ebomSelected.size : 1;
    const actions = [{ act: 'details', icon: 'search', label: t('publish.sv_act_details') }];   // first, on every line
    // A bought version is for a component not built in the MBOM: one already in it has none. Off, with the reason, until Make or buy is set up.
    // A component with no item in Fusion Manage is told by the dialog, which looks for it when asked. Always first, then add with its children, then add.
    if (depth && !(state && !state.missing) && !(state && state.blocked)) {
      const reason = !ctx.host.boughtReady() ? t('publish.item_bought_not_set_up') : '';
      actions.push({ act: 'bought', icon: 'bought', label: t('publish.item_act_bought', { number: node.number }), reason: reason });   // one that exists is offered by the dialog
    }
    if (depth && !full) actions.push({ act: 'add', icon: 'addOne', label: actionLabel(t('publish.sv_act_add'), count) });
    return actions;
  }

  /** The classes of an EBOM line that come from its state in the colour bar. */
  function ebomStateClasses(state) {
    if (!state) return [];
    return [state.missing && !state.blocked ? 'sv-row-missing' : '', state.matched || state.blocked ? 'sv-row-matched' : ''];
  }

  /** Whether all of an EBOM line is in the MBOM (adding it again would be more than the EBOM has), or a purchased part above it stands for it. */
  function isEbomLineFull(state) { return !!(state && (state.exceeded || state.matched || state.blocked)); }

  /** Whether the Details Panel is open for the line ``id`` of the pane. */
  function isDetailsAt(pane, id) { return !!ctx.detailsAt && ctx.detailsAt.pane === pane && ctx.detailsAt.id === id; }

  /** The classes of an EBOM line: its state, a search hit, the colour bar's context lines, and the tone of its notes. */
  function ebomLineClasses(entry, tone) {
    const node = entry.node;
    const context = entry.filter && entry.depth && !entry.filter.keep.has(node.key);
    const classes = ebomStateClasses(entry.state).concat([ctx.ebomHits.has(node.key) ? 'sv-hit' : '', context ? 'sv-row-context' : '', toneClass(tone)]);
    return classes.filter(Boolean).join(' ');
  }

  /** The ``lineNode`` spec of an EBOM line. ``entry``: node, depth, state, filter, notes, isOpen, kids. */
  function ebomLineSpec(entry) {
    const node = entry.node;
    const depth = entry.depth;
    const state = entry.state;
    const full = isEbomLineFull(state);
    const tone = toneOf(entry.notes);
    const badges = [];
    if (state && state.matched) badges.push(matchedMark(state.bought));
    return { id: node.key, depth: depth, number: node.number, name: node.name, quantity: depth ? node.quantity : '', editable: false, hasKids: entry.kids.length > 0,
             isOpen: entry.isOpen, selected: ctx.ebomSelected.has(node.key), details: isDetailsAt('ebom', node.key), badges: badges, draggable: depth > 0 && !full,
             actions: ebomActions(node, depth, state, full), seq: depth ? node.sequence : '', notes: entry.notes, noteKey: 'ebom:' + node.key, tone: tone, classes: ebomLineClasses(entry, tone) };
  }

  function drawEbom(container, cmp) {
    const list = [];
    const filter = ctx.filterView();
    function walk(node, depth) {
      const state = cmp.ebom[node.key];
      const isOpen = ctx.ebomOpened.has(node.key) || (!!filter && filter.ebom.has(node.key));   // with the filter on, what has a match under it is open
      const kids = filter ? node.children.filter(function (c) { return filter.keep.has(c.key) || filter.ebom.has(c.key); }) : node.children;
      if (depth) list.push(node.key);
      const notes = depth ? ebomNotes(node, state) : [];
      container.appendChild(lineNode(ebomLineSpec({ node: node, depth: depth, state: state, filter: filter, notes: notes, isOpen: isOpen, kids: kids })));
      if (notes.length && ctx.openNotes.has('ebom:' + node.key)) container.appendChild(noteRow(notes, depth));
      if (isOpen) drawKidLines(container, node.key, kids, function (kid) { walk(kid, depth + 1); });
    }
    walk(ctx.ebom, 0);
    return list;
  }

  /** The icons on an MBOM line: the magnifier on every line, and below the root the position, add to an assembly, and the bin last. */
  function mbomActions(node, depth) {
    const count = ctx.selected.has(node.uid) ? ctx.selected.size : 1;
    const actions = [{ act: 'details', icon: 'search', label: t('publish.sv_act_details') }];   // first, on every line
    if (depth) {
      actions.push({ act: 'position', icon: 'position', label: t('publish.sv_act_position') },
                   { act: 'split', icon: 'split', label: t('publish.sv_act_split'), reason: Number(node.quantity) > 0 && Number(node.quantity) <= 1 ? t('publish.sv_split_one') : '' },
                   { act: 'addTo', icon: 'assembly', label: actionLabel(t('publish.sv_act_add_to'), count) },
                   { act: 'remove', icon: 'remove', label: actionLabel(t('publish.sv_act_remove'), count) });
    }
    return actions;
  }

  /** Whether an MBOM line is an item only Fusion Manage has. */
  function isMfgOwnLine(node, cmp) { return cmp.mbom[node.uid] === 'mfg' && (node.kind === 'component' || node.kind === 'added'); }

  /** The classes of an MBOM line: a search hit, the colour bar's context lines, and the tone of its notes. */
  function mbomLineClasses(entry, tone) {
    const uid = entry.node.uid;
    const context = entry.filter && entry.depth && !ctx.hits.has(uid);
    return [ctx.hits.has(uid) ? 'sv-hit' : '', context ? 'sv-row-context' : '', toneClass(tone)].filter(Boolean).join(' ');
  }

  /** The ``lineNode`` spec of an MBOM line. ``entry``: node, depth, cmp, numbers, filter, notes, isOpen, kids. */
  function mbomLineSpec(entry) {
    const node = entry.node;
    const depth = entry.depth;
    const tone = toneOf(entry.notes);
    return { id: node.uid, depth: depth, number: node.number, name: node.name, quantity: depth ? node.quantity : '', editable: depth > 0,
             hasKids: entry.kids.length > 0, isOpen: entry.isOpen, selected: ctx.selected.has(node.uid), details: isDetailsAt('mbom', node.uid), badges: [], draggable: depth > 0,
             actions: mbomActions(node, depth), seq: depth ? entry.numbers[node.uid] || '' : '', classes: mbomLineClasses(entry, tone), tone: tone, notes: entry.notes, noteKey: 'mbom:' + node.uid,
             purchased: !!node.bought || (node.kind === 'added' && !!node.source), mfgOwn: isMfgOwnLine(node, entry.cmp) };
  }

  function drawMbom(container, cmp, chg) {
    const numbers = ns.mbomPlan.lineNumbers(ctx.structure, chg);   // the line numbers Fusion Manage has, or will have when published
    const list = [];
    const cut = ctx.filterView();
    const filter = cut && cut.mbomOn ? cut : null;   // the colour bar cuts down the EBOM only
    function walk(node, depth) {
      const flags = chg.changes[node.uid];
      const isOpen = ctx.opened.has(node.uid) || (!!filter && filter.mbom.has(node.uid));   // with the filter on, what has a match under it is open
      const kids = filter ? node.children.filter(function (c) { return ctx.hits.has(c.uid) || filter.mbom.has(c.uid); }) : node.children;
      if (depth) list.push(node.uid);
      const notes = depth ? mbomNotes(node, cmp, flags) : [];
      container.appendChild(lineNode(mbomLineSpec({ node: node, depth: depth, cmp: cmp, numbers: numbers, filter: filter, notes: notes, isOpen: isOpen, kids: kids })));
      if (notes.length && ctx.openNotes.has('mbom:' + node.uid)) container.appendChild(noteRow(notes, depth));
      if (isOpen) drawKidLines(container, node.uid, kids, function (kid) { walk(kid, depth + 1); });
    }
    walk(ctx.structure.root(), 0);
    return list;
  }

  /** Gives the drawing the viewer's state to read (see the top of this file). */
  function bind(state) { ctx = state; }

  ns.mbomViewerDraw = { bind: bind, drawEbom: drawEbom, drawMbom: drawMbom, shownQuantity: shownQuantity, ICONS: ICONS, LIMIT: LIMIT };
})(window.MfgUi);
