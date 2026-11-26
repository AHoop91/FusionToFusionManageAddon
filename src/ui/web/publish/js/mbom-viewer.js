/**
 * Publish Item panel: the structure viewer, as ``ns.mbomViewer``. Two panes side by side: the EBOM (the design's Bill of Materials, read-only) and the
 * MBOM (the manufacturing Bill of Materials, which can be edited). The MBOM is ``ns.mbomStructure``; this file draws it and turns what the user
 * does into its edits. Nothing here is sent to Fusion Manage by the viewer itself: the Publish button sends what ``plan()`` makes of the structure
 * (mbom-plan.js). Layer: UI (DOM and events); the rules are in mbom-structure.js and mbom-plan.js.
 *
 * Where the trees come from: the EBOM from the rows the panel has read (all levels, read at once); the
 * MBOM from the ``mbom_tree`` section (the target item read by its id, every level), mapped to the EBOM by item number. A design with no MBOM item
 * starts as a copy of the EBOM.
 *
 * The viewer keeps uids and EBOM keys only, never nodes: the structure replaces its tree by a copy on a refused edit, undo and redo. Only the
 * lines of an open assembly are drawn, and no more than ``LIMIT`` under one at first, so a large tree stays quick. Every edit goes through
 * ``run``, which says the reason an edit was refused in a toast.
 *
 * The magnifier on every line opens the Details Panel (details.js) for it, and that line stays marked while the panel is open (``detailsAt``); a plain click opens nothing.
 *
 * ``host``: ``design()`` (the open design's summary), ``rows()`` (the rows of the Bill of Materials that was read),
 * ``askMbom()`` (to ask for the MBOM again after it failed), ``targetId()``, ``target()`` (item number), ``phantom()`` (whether Settings allow phantoms), ``summary()`` (the design, under the
 * target's item number), ``boughtSuffix()``, ``boughtReady()`` and ``planned()`` (called when the structure may have changed: what publishing covers is
 * worked out again).
 */
(function (ns) {
  'use strict';

  const ui = ns.pubUi;
  const el = ns.el;
  const S = ns.mbomStructure;
  const model = ns.bomModel;
  function t(key, params) { return ns.i18n.t(key, params); }

  const DEST_LIMIT = 300;   // lines drawn in the Add to assembly menu before it asks for a search
  const SKELETON_ROWS = 10;   // grey rows in each table while the structure is on its way
  const LIMIT = 200;   // lines drawn under an assembly before "Show more"

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

  /** The words for what the structure refuses (it throws errors with a ``key`` and ``params``). */
  const ERRORS = {
    bad_quantity: function () { return t('publish.sv_err_bad_quantity'); },
    phantom_needs_settings: function () { return t('publish.sv_phantom_off'); },
    needs_number: function () { return t('publish.sv_err_needs_number'); },
    number_used: function (p) { return t('publish.sv_err_number_used', p); },
    root_immutable: function () { return t('publish.sv_err_root_immutable'); },
    nothing_selected: function () { return t('publish.sv_err_nothing_selected'); },
    inside_itself: function () { return t('publish.sv_err_inside_itself'); },
    before_not_under: function () { return t('publish.sv_err_before_not_under'); },
    no_such_line: function () { return t('publish.sv_err_no_such_line'); },
    no_place_root: function () { return t('publish.sv_err_no_place_root'); },
    unknown_place: function (p) { return t('publish.sv_err_unknown_place', p); },
    no_such_ebom: function () { return t('publish.sv_err_no_such_ebom'); },
    would_exceed: function (p) { return t('publish.sv_err_would_exceed', p); },
    under_purchased: function (p) { return t('publish.sv_err_under_purchased', p); },
    root_no_quantity: function () { return t('publish.sv_err_root_no_quantity'); },
    bad_number: function () { return t('publish.sv_pos_invalid'); },
    number_taken: function (p) { return t('publish.sv_pos_taken', p); },
    split_too_much: function (p) { return t('publish.sv_split_too_much', p); },
    split_same_assembly: function () { return t('publish.sv_err_split_same'); },
  };

  /** An error of an edit in words; one that is not the structure's refusal is shown as it is, never hidden. */
  function describe(error) {
    const words = error.key && ERRORS[error.key];
    return words ? words(error.params) : error.message || String(error);
  }

  let host = null;
  let dom = null;            // the elements of the viewer, made when it is first shown
  let active = false;        // the Structure view is the one on screen
  let ready = false;         // the Bill of Materials (every level) has been read
  let mbomTree = null;       // the ``mbom_tree`` answer, held until the Bill of Materials is read too (the two are read at the same time)
  let phase = 'idle';        // idle, or error (the MBOM could not be read)
  let note = '';             // what the viewer is waiting for, or the error
  let skeleton = false;      // the tables hold the grey bars of the wait
  let structure = null;
  let ebom = null;
  let drag = null;           // what is being dragged: { from: 'mbom' | 'ebom', ids }
  let dropMark = null;       // the row showing where a drop would go
  let searchText = '';
  let hitIndex = -1;
  const hits = new Set();    // uids of the MBOM lines the search found
  const ebomHits = new Set();   // keys of the EBOM lines the search found
  let statusFilter = '';     // the colour bar's choice: only the EBOM lines that are 'missing', 'quantity' (a different quantity) or 'matched' are drawn, '' for all
  let filtering = false;     // only the lines the search found are drawn, with the assemblies above them greyed
  const opened = new Set([S.ROOT]);   // uids of the MBOM lines that are open
  const ebomOpened = new Set(['0']);  // keys of the EBOM lines that are open
  const more = {};           // parent id -> how many lines under it are drawn
  const selected = new Set();       // MBOM uids
  const openNotes = new Set();      // the lines whose note is open: 'ebom:<key>' or 'mbom:<uid>'
  let view = emptyView();           // for the notes: the MBOM lines made from each EBOM line (by key), the EBOM lines by key, and the assembly of each MBOM line (by uid)
  let compared = null;              // {cmp, chg}: the structure's compare() and changes(), kept until it changes (see ``reindex``)
  let skippedFor = null;            // {rows, key, skipped}: what ``plan`` found for the rows read and the design it was found for
  const ebomSelected = new Set();   // EBOM keys
  let anchor = '';                  // where a shift-click range starts, in the pane last clicked
  let detailsAt = null;             // the line whose Details Panel is open: {pane, id} (an EBOM key or an MBOM uid)
  let visible = { mbom: [], ebom: [] };   // the lines drawn, in order, for ranges
  let index = new Map();            // MBOM uid -> {node, parent, at}, made again after every edit (the structure replaces its nodes on undo)
  let order = [];                   // the MBOM lines, in tree order

  function emptyView() { return { held: {}, ebomAt: {}, parentOf: {} }; }

  // ---- Making the structure ------------------------------------------------------------

  function mbomFromTree(node) {
    return { number: node.number, name: node.name, quantity: node.quantity || '', itemId: node.item_id, edgeId: node.edge_id, sequence: node.sequence, cut: !!node.cut,
             children: (node.children || []).map(mbomFromTree) };
  }

  /** Build the structure from the EBOM and, when Fusion Manage has the MBOM item, its tree (else the MBOM starts as a copy of the EBOM). */
  function build(tree) {
    const design = host.design();
    ebom = S.ebomFromRows(host.rows(), { item_number: design.item_number, name: design.name || design.description || design.file_name, component_id: design.component_id });
    const read = tree ? S.mapByNumber(mbomFromTree(tree), ebom, host.boughtSuffix()) : null;
    structure = S.create({ ebom: ebom, mbom: read, phantom: !!host.phantom() });
    view = emptyView();
    (function indexEbom(node) { view.ebomAt[node.key] = node; node.children.forEach(indexEbom); })(ebom);
    phase = 'idle';
    clearState();
    reindex();
  }

  /** What belongs to one structure: a drag, the search, the selection and the folds (uids start again with each structure). */
  function clearState() {
    if (ns.pubItemPanel) ns.pubItemPanel.close();   // its line may be gone (it stays while a save is under way)
    detailsAt = null;   // the panel is closed by ``details.reset`` already
    clearMark();
    drag = null;
    searchText = '';
    statusFilter = '';
    openNotes.clear();
    hitIndex = -1;
    dom.search.value = '';
    hits.clear(); ebomHits.clear(); selected.clear(); ebomSelected.clear();
    anchor = '';
    resetFolds();
    Object.keys(more).forEach(function (k) { delete more[k]; });
  }

  /** Only the root of the MBOM and of the EBOM are open. */
  function resetFolds() {
    opened.clear(); opened.add(S.ROOT);
    ebomOpened.clear(); ebomOpened.add('0');
  }

  /** The structure changed (or may have): its lines are looked up again, and what was worked out from the old tree is dropped. */
  function reindex() {
    index = new Map();
    order = [];
    compared = null;
    view.held = {};
    view.parentOf = {};
    (function walk(node, parent, at) {
      index.set(node.uid, { node: node, parent: parent, at: at });
      if (parent) {
        order.push(node);
        view.parentOf[node.uid] = parent;
        if (node.source) (view.held[node.source] = view.held[node.source] || []).push(node);
      }
      node.children.forEach(function (c, i) { walk(c, node, i); });
    })(structure.root(), null, 0);
  }

  /** Go as far as the data allows: wait for the EBOM and, when the design has an MBOM item, for its tree (the panel asks for both at once), then build and
   *  draw. A structure that exists (with edits) is never replaced. */
  function refresh() {
    if (!active) return;
    if (structure) { update(); return; }
    if (phase === 'error') return;
    if (!ready) { wait(t('publish.reading_bom')); return; }
    if (host.targetId() && !mbomTree) { wait(t('publish.sv_reading_mbom')); return; }
    build(mbomTree);
    update();
  }

  /** Say what the skeleton waits for (under the two tables). The same words are not said again: they must not restart the "taking longer" timer. */
  function say(text) {
    if (text === note && dom.status.textContent) return;
    note = text;
    ui.warnWhenSlow(dom.status, text);
  }

  function wait(text) {
    say(text);
    update();
  }

  function fail(text, retry) {
    phase = 'error';
    note = text;
    dom.state.replaceChildren(ui.errorState(text, retry));
    update();
  }

  /** The answer of the ``mbom_tree`` section, which may come before or after the Bill of Materials is read. One that nobody waits for (the structure is
   *  built, or the design has no MBOM item) is ignored, so edits are never replaced; a failed one is told, with a way to ask for it again. */
  function answer(entry) {
    if (structure || !host.targetId()) return;
    if (!entry.ok) {
      fail(entry.message || t('publish.unknown_error'), function () { phase = 'idle'; mbomTree = null; host.askMbom(); refresh(); });
      return;
    }
    mbomTree = entry.data;
    if (ready) refresh();
  }

  /** The Bill of Materials is read again: what was built from the old one is dropped. */
  function reset() {
    ready = false;
    mbomTree = null;
    structure = null;
    ebom = null;
    phase = 'idle';
    clearState();
    index = new Map();
    order = [];
    compared = null;
    view = emptyView();
    if (active) refresh();
  }

  // ---- Edits ---------------------------------------------------------------------------

  function prune() {
    Array.from(selected).forEach(function (id) { if (!index.has(id)) selected.delete(id); });
    if (anchor && !selected.has(anchor) && !ebomSelected.has(anchor)) anchor = '';
  }

  /** The search again, in both panes, for the lines now in the tree (an edit may have added, removed or renamed some); ``open`` opens what is above each hit. */
  function findHits(open) {
    hits.clear();
    ebomHits.clear();
    hitIndex = -1;
    if (!searchText) return;
    structure.search(searchText).forEach(function (uid) { hits.add(uid); if (open) reveal(uid); });
    const needle = searchText.toLowerCase();
    (function walk(node, path) {
      if (node.number.toLowerCase().indexOf(needle) >= 0 || node.name.toLowerCase().indexOf(needle) >= 0) {
        ebomHits.add(node.key);
        if (open) revealEbom(path);
      }
      node.children.forEach(function (c, at) { walk(c, path.concat([{ key: node.key, at: at }])); });
    })(ebom, []);
  }

  /** After the structure changed (an edit, undo or redo): its lines are looked up again, and the selection and the search follow. */
  function changed() {
    reindex();
    prune();
    findHits(false);
    update();
  }

  /** Run an edit. A refusal is said in a toast and nothing changes. Returns ``{ok, value}``. */
  function run(change) {
    let value;
    try {
      value = change();
    } catch (error) {
      ns.toast.show(describe(error), { tone: 'error' });   // said for a moment, not in a line of its own above the panes
      reindex();   // a refused edit puts back a copy of the tree
      update();
      return { ok: false };
    }
    changed();
    return { ok: true, value: value };
  }

  function openPlace(place) { opened.add(place.parentId); }

  /** ``dropped`` (``{from, ids}``) is dropped at ``place``. */
  function dropOn(place, dropped, event) {
    openPlace(place);
    if (dropped.from === 'ebom') {
      const keys = dropped.ids;
      run(function () { structure.addFromEbom(keys, place.parentId, place.before, !event.altKey); });
    } else {
      const ids = dropped.ids;
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

  function undo() { structure.undo(); changed(); }
  function redo() { structure.redo(); changed(); }

  /** Where new lines go: inside the one assembly that is selected, else at the end of the MBOM. */
  function placeForNew() {
    const ids = chosenIds();
    if (ids.length === 1 && structure.holds(ids[0])) return { parentId: ids[0], before: '' };
    return { parentId: S.ROOT, before: '' };
  }

  let destMenu = null;   // the open "Add to assembly" menu: {close}

  function closeDestMenu() {
    if (destMenu) destMenu.close();
    destMenu = null;
  }

  /** The line numbers of the MBOM pane for each line, by uid, as "3.1" (the numbers of the lines from the top down). */
  function numberDestLines() {
    const numbers = ns.mbomPlan.lineNumbers(structure, compare().chg);   // the line numbers the MBOM pane shows
    const lead = {};
    (function number(node, dotted) {
      node.children.forEach(function (c) {
        lead[c.uid] = dotted ? dotted + '.' + numbers[c.uid] : numbers[c.uid];
        number(c, lead[c.uid]);
      });
    })(structure.root(), '');
    return lead;
  }

  /** The elements of the tree menu: the tree, the search field, its count, the list of lines and the bar that holds the search. */
  function buildDestShell(spec) {
    const node = el('div', 'sv-dest-tree');
    const find = el('input', 'sv-input sv-dest-search');
    find.type = 'text';
    find.autocomplete = 'off';
    find.spellcheck = false;
    find.placeholder = t('publish.sv_search_placeholder');
    find.setAttribute('aria-label', t('publish.sv_search_placeholder'));
    const count = el('div', 'sv-dest-count');
    const list = el('div', 'sv-dest-list');
    list.setAttribute('role', 'tree');
    const bar = el('div', 'sv-dest-bar');   // the search opens under the top bar with the magnifier
    bar.hidden = !spec.searchShown;
    bar.append(find, count);
    node.append(bar, list);
    return { node: node, find: find, count: count, list: list, bar: bar };
  }

  function destMatches(ctx, line) {
    return ((ctx.lead[line.uid] || '') + ' ' + line.number + ' ' + line.name).toLowerCase().indexOf(ctx.query) >= 0;
  }

  /** Whether the line, or a line under it, matches the search. */
  function destWanted(ctx, line) {
    if (ctx.moving.has(line.uid)) return false;
    return destMatches(ctx, line) || line.children.some(function (child) { return destWanted(ctx, child); });
  }

  /** How many lines match the search, drawn or not. */
  function countDestHits(ctx, line) {
    if (ctx.moving.has(line.uid)) return 0;
    return (destMatches(ctx, line) ? 1 : 0) + line.children.reduce(function (sum, child) { return sum + countDestHits(ctx, child); }, 0);
  }

  /** The fold button of a line of the tree menu. */
  function buildDestToggle(ctx, entry) {
    const line = entry.line;
    const toggle = el('button', 'sv-dest-toggle');
    toggle.type = 'button';
    toggle.tabIndex = -1;
    toggle.dataset.id = line.uid;
    toggle.disabled = !entry.kids.length || !!ctx.query || line.uid === S.ROOT;
    if (entry.kids.length && line.uid !== S.ROOT) {
      const chevron = ui.chevron();
      ui.setChevron(chevron, !entry.isOpen);
      toggle.appendChild(chevron);
    }
    toggle.addEventListener('click', function () {
      if (ctx.open.has(line.uid)) ctx.open.delete(line.uid); else ctx.open.add(line.uid);
      ctx.draw();
    });
    return toggle;
  }

  /** The button that chooses a line of the tree menu. */
  function buildDestPick(ctx, line) {
    const spec = ctx.spec;
    const pick = el('button', 'sv-dest-pick' + (spec.chosen && spec.chosen() === line.uid ? ' sv-dest-chosen' : ''));
    pick.type = 'button';
    pick.dataset.id = line.uid;
    const why = spec.locked ? spec.locked(line.uid) : '';
    if (why) { pick.disabled = true; pick.title = why; }
    if (ctx.lead[line.uid]) pick.appendChild(el('span', 'sv-dest-lead', ctx.lead[line.uid]));
    pick.appendChild(el('span', 'sv-dest-number', line.number));
    if (line.name) pick.appendChild(el('span', 'sv-dest-name', line.name));
    pick.addEventListener('mouseover', function (event) {   // the full text for the shared tooltip (it reads the title as the pointer arrives, after this), only when the line cuts it short
      if (pick.contains(event.relatedTarget)) return;   // moving between the parts of this line, not arriving
      const label = pick.querySelector('.sv-dest-name');
      if (label && label.scrollWidth > label.clientWidth) pick.title = line.number + ' ' + line.name; else pick.removeAttribute('title');
    });
    pick.addEventListener('click', function () { spec.onPick(line.uid); });
    return pick;
  }

  /** One line of the tree menu. ``entry``: line, depth, kids (the lines under it that are not moving), isOpen, hit. */
  function buildDestRow(ctx, entry) {
    const line = entry.line;
    const row = el('div', 'sv-dest-row' + (entry.hit ? ' sv-dest-hit' : ''));
    row.setAttribute('role', 'treeitem');
    row.setAttribute('aria-level', String(entry.depth + 1));
    if (ctx.spec.chosen) row.setAttribute('aria-selected', String(ctx.spec.chosen() === line.uid));
    if (entry.kids.length) row.setAttribute('aria-expanded', entry.isOpen ? 'true' : 'false');
    for (let g = 0; g < entry.depth; g++) row.appendChild(el('span', 'sv-dest-guide'));   // a line down from each line above, so the tree reads as one
    row.append(buildDestToggle(ctx, entry), buildDestPick(ctx, line));
    return row;
  }

  /** Draws the lines of the tree menu from the top, no more than ``DEST_LIMIT``, and the count of the search. */
  function drawDestTree(ctx) {
    ctx.list.replaceChildren();
    const progress = { drawn: 0, cut: false };
    function walk(line, depth) {
      if (ctx.moving.has(line.uid) || (ctx.query && !destWanted(ctx, line))) return;
      const hit = !!ctx.query && destMatches(ctx, line);
      if (progress.drawn >= DEST_LIMIT) { progress.cut = true; return; }
      progress.drawn += 1;
      const kids = line.children.filter(function (child) { return !ctx.moving.has(child.uid); });
      const isOpen = !!ctx.query || ctx.open.has(line.uid);
      ctx.list.appendChild(buildDestRow(ctx, { line: line, depth: depth, kids: kids, isOpen: isOpen, hit: hit }));
      if (isOpen) kids.forEach(function (child) { walk(child, depth + 1); });
    }
    walk(structure.root(), 0);
    if (progress.cut) ctx.list.appendChild(el('div', 'sv-dest-more', t('publish.sv_dest_more', { count: DEST_LIMIT })));
    const total = ctx.query ? countDestHits(ctx, structure.root()) : 0;
    ctx.count.textContent = ctx.query ? (total ? t('publish.sv_search_count', { count: total }) : t('publish.sv_search_none')) : '';
  }

  function listDestPicks(ctx) { return Array.from(ctx.node.querySelectorAll('.sv-dest-pick:not(:disabled)')); }

  /** The focus moves ``by`` lines from ``from`` (a line is the focus, or the search). */
  function stepDestFocus(ctx, from, by) {
    const all = listDestPicks(ctx);
    const at = all.indexOf(from);
    const next = all[Math.max(0, Math.min(all.length - 1, (at < 0 ? (by > 0 ? -1 : all.length) : at) + by))];
    if (next) next.focus();
  }

  function moveDestFocusUp(ctx, on) {
    if (on === ctx.find) return;   // the search is the top of the menu
    if (listDestPicks(ctx)[0] === on) { if (!ctx.bar.hidden) ctx.find.focus(); } else stepDestFocus(ctx, on, -1);
  }

  /** Right opens and Left closes the line in focus (the root and a line with nothing under it have no fold). */
  function foldDestLineByKey(ctx, event, on) {
    if (ctx.query || !on || !on.classList.contains('sv-dest-pick')) return;
    const row = on.parentNode;
    if (!row.hasAttribute('aria-expanded') || on.dataset.id === S.ROOT) return;
    if ((row.getAttribute('aria-expanded') === 'true') !== (event.key === 'ArrowLeft')) return;
    event.preventDefault();
    row.querySelector('.sv-dest-toggle').click();
    const again = ctx.node.querySelector('.sv-dest-pick[data-id="' + on.dataset.id + '"]');
    if (again) again.focus();
  }

  function handleDestKey(ctx, event) {
    const on = document.activeElement;
    if (event.key === 'ArrowDown') { event.preventDefault(); stepDestFocus(ctx, on, 1); }
    else if (event.key === 'ArrowUp') { event.preventDefault(); moveDestFocusUp(ctx, on); }
    else if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') foldDestLineByKey(ctx, event, on);
  }

  /** The MBOM as a tree to choose an assembly from, with a search above it: the one of "Add to assembly" and of "Split Quantity". It shows every line but the ones in
   *  ``spec.moving`` (and what is under them), each with the line number it has in the MBOM pane (3.1 is the first line of line 3). ``spec.onPick(uid)`` is called for a line chosen;
   *  ``spec.locked(uid)`` (optional) gives the reason a line cannot be chosen (it is greyed out, with the reason as its tooltip) or '', ``spec.chosen()`` (optional) gives the one to mark. A search shows the lines that match with the
   *  ones above them, all open. Only the lines in view are drawn, and no more than ``DEST_LIMIT``, so a large MBOM stays quick.
   *  Returns ``{node, draw, toggleSearch, focus, focusFirst}``: the element to place, drawing it again, showing or hiding the search (it starts hidden unless ``spec.searchShown``) and the focus. */
  function destTree(spec) {
    const shell = buildDestShell(spec);
    const ctx = Object.assign({ spec: spec, moving: spec.moving, open: new Set([S.ROOT]), lead: numberDestLines(), query: '' }, shell);
    ctx.draw = function () { drawDestTree(ctx); };
    shell.find.addEventListener('input', function () { ctx.query = shell.find.value.trim().toLowerCase(); ctx.draw(); });
    shell.node.addEventListener('keydown', function (event) { handleDestKey(ctx, event); });
    ctx.draw();
    return {
      node: shell.node,
      draw: ctx.draw,
      toggleSearch: function () {   // shows or hides the search; returns whether it is shown
        shell.bar.hidden = !shell.bar.hidden;
        if (shell.bar.hidden) { shell.find.value = ''; ctx.query = ''; ctx.draw(); } else shell.find.focus();
        return !shell.bar.hidden;
      },
      focus: function (uid) {   // the focus back on a line after the tree was drawn again
        const pick = shell.node.querySelector('.sv-dest-pick[data-id="' + uid + '"]');
        if (pick) pick.focus();
      },
      focusFirst: function () {
        const first = shell.node.querySelector('.sv-dest-pick:not(:disabled)');
        if (first) first.focus();
      },
    };
  }

  /** The "Add to assembly" menu, at the left of ``button``: the MBOM as a tree to fold and unfold (without ``targets`` and what is under them), with a search
   *  behind the magnifier. Choosing a line moves ``targets`` to the end of it. */
  function openDestMenu(button, targets) {
    closeDestMenu();
    const box = el('div', 'sv-dest');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-label', t('publish.sv_dest_title'));
    const head = el('div', 'sv-dest-head');
    const cross = el('button', 'sv-dest-btn sv-dest-close');
    cross.type = 'button';
    cross.setAttribute('aria-label', t('publish.sv_dest_close'));
    cross.title = t('publish.sv_dest_close');
    cross.appendChild(ns.svg(['M6 6l12 12', 'M18 6L6 18'], 14));
    cross.addEventListener('click', function () { closeDestMenu(); button.focus(); });
    const lens = el('button', 'sv-dest-btn sv-dest-find');
    lens.type = 'button';
    lens.setAttribute('aria-label', t('publish.sv_dest_search'));
    lens.title = t('publish.sv_dest_search');
    lens.setAttribute('aria-expanded', 'false');
    lens.appendChild(ns.svg(ICONS.search, 14));
    const tools = el('span', 'sv-dest-tools');
    tools.append(lens, cross);
    head.append(el('span', 'sv-dest-title', t('publish.sv_dest_title')), tools);
    const tree = destTree({
      moving: new Set(targets),
      onPick: function (uid) {
        closeDestMenu();
        openPlace({ parentId: uid });
        run(function () { structure.move(targets, uid, ''); });
      },
    });
    box.append(head, tree.node);
    lens.addEventListener('click', function () {
      lens.setAttribute('aria-expanded', tree.toggleSearch() ? 'true' : 'false');
      if (lens.getAttribute('aria-expanded') === 'false') lens.focus();
    });

    document.body.appendChild(box);
    const spot = button.getBoundingClientRect();
    const height = Math.min(360, window.innerHeight - 16);   // room for the menu at its tallest (opening a branch grows it), so it never runs off the window and its list scrolls
    box.style.maxHeight = height + 'px';
    box.style.right = Math.max(8, Math.min(window.innerWidth - spot.left + 4, window.innerWidth - box.offsetWidth - 8)) + 'px';   // kept inside the window
    box.style.top = Math.max(8, Math.min(spot.top, window.innerHeight - height - 8)) + 'px';
    function outside(event) { if (!box.contains(event.target) && !button.contains(event.target)) closeDestMenu(); }   // the button that opened it shuts it with its click
    function key(event) { if (event.key === 'Escape') { event.stopPropagation(); closeDestMenu(); button.focus(); } }
    document.addEventListener('mousedown', outside, true);
    document.addEventListener('keydown', key, true);
    destMenu = { button: button, close: function () {
      document.removeEventListener('mousedown', outside, true);
      document.removeEventListener('keydown', key, true);
      box.remove();
    } };
    tree.focusFirst();
  }

  /** A small box with one value, at the left of ``button`` (the one of "Set Position" and "Split Quantity"): ``title`` and ``label``, ``value`` to start from, and ``action``
   *  as the button; ``inputMode`` the keypad of the value; ``extra`` (an element with its own label, such as the tree of assemblies) goes under the value, before the button. ``check(text)`` gives the words a value is refused with (or ''); a value that passes goes to ``accept(text)`` and the box closes. A refusal stays in the box. */
  function openValueBox(button, spec) {
    closeDestMenu();
    const box = el('div', 'sv-dest sv-pos');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-label', spec.title);
    const head = el('div', 'sv-dest-head');
    const cross = el('button', 'sv-dest-btn sv-dest-close');
    cross.type = 'button';
    cross.setAttribute('aria-label', t('publish.sv_dest_close'));
    cross.title = t('publish.sv_dest_close');
    cross.appendChild(ns.svg(['M6 6l12 12', 'M18 6L6 18'], 14));
    cross.addEventListener('click', function () { closeDestMenu(); button.focus(); });
    head.append(el('span', 'sv-dest-title', spec.title + ' ' + spec.number), cross);
    const body = el('div', 'sv-pos-body');
    const input = el('input', 'sv-input sv-pos-input');
    input.type = 'text';
    input.inputMode = spec.inputMode;
    input.autocomplete = 'off';
    input.value = spec.value || '';
    input.setAttribute('aria-label', spec.label);
    const set = el('button', 'btn sv-pos-set', spec.action);
    set.type = 'button';
    const row = el('div', 'sv-pos-row');
    row.appendChild(input);
    if (!spec.extra) row.appendChild(set);
    const message = el('p', 'error sv-pos-message');
    message.setAttribute('role', 'alert');
    message.hidden = true;
    body.append(el('label', 'sv-pos-label', spec.label), row);
    if (spec.extra) body.append(spec.extra, set);
    body.appendChild(message);
    box.append(head, body);
    if (spec.className) box.classList.add(spec.className);
    function submit() {
      const text = input.value.trim();
      const refusal = spec.check(text);
      if (refusal) {
        message.textContent = refusal;
        message.hidden = false;
        input.focus();
        return;
      }
      closeDestMenu();
      spec.accept(text);
    }
    set.addEventListener('click', submit);
    input.addEventListener('keydown', function (event) { if (event.key === 'Enter') { event.preventDefault(); submit(); } });
    document.body.appendChild(box);
    const spot = button.getBoundingClientRect();
    box.style.right = Math.max(8, Math.min(window.innerWidth - spot.left + 4, window.innerWidth - box.offsetWidth - 8)) + 'px';
    box.style.top = Math.max(8, Math.min(spot.top, window.innerHeight - box.offsetHeight - 8)) + 'px';
    function outside(event) { if (!box.contains(event.target) && !button.contains(event.target)) closeDestMenu(); }
    function key(event) { if (event.key === 'Escape') { event.stopPropagation(); closeDestMenu(); button.focus(); } }
    document.addEventListener('mousedown', outside, true);
    document.addEventListener('keydown', key, true);
    destMenu = { button: button, close: function () {
      document.removeEventListener('mousedown', outside, true);
      document.removeEventListener('keydown', key, true);
      box.remove();
    } };
    input.focus();
    input.select();
  }

  /** "Set Position": the BOM line number the line is to have (any whole number from 1; the line goes to the place its number gives it among the lines of its
   *  assembly, the others keep their numbers). A value that is not a number, or one another line has, is said in the box, which stays open. */
  function openPositionBox(button, id) {
    const entry = index.get(id);
    const shown = ns.mbomPlan.lineNumbers(structure, compare().chg);   // the numbers the lines of the assembly show now
    const current = {};
    entry.parent.children.forEach(function (c) { current[c.uid] = shown[c.uid]; });
    openValueBox(button, {
      title: t('publish.sv_pos_title'), number: entry.node.number, label: t('publish.sv_pos_label'), inputMode: 'numeric', value: current[id] || '', action: t('publish.sv_pos_set'),
      check: function (text) {
        if (!/^\d{1,9}$/.test(text) || Number(text) < 1) return t('publish.sv_pos_invalid');
        if (Number(text) === Number(current[id])) return '';
        const clash = entry.parent.children.some(function (c) { return c.uid !== id && Number(current[c.uid]) === Number(text); });
        return clash ? t('publish.sv_pos_taken', { number: String(Number(text)) }) : '';
      },
      accept: function (text) { if (Number(text) !== Number(current[id])) run(function () { structure.setNumber(id, text, current); }); },
    });
  }

  /** "Split Quantity": one box with how much of the line's quantity goes to another assembly (less than it has) and the assembly to give it to, chosen in the tree of the MBOM
   *  (the line, what is under it and the assembly it is in cannot be chosen). The line keeps the rest; the assembly gets a line of its own for the amount, or the line it has
   *  already of the same item takes it. */
  function openSplitBox(button, id) {
    const entry = index.get(id);
    const have = Number(entry.node.quantity);
    let chosen = '';
    const tree = destTree({
      moving: new Set([id]), searchShown: true, chosen: function () { return chosen; },
      locked: function (uid) { return uid === entry.parent.uid ? t('publish.sv_err_split_same') : ''; },
      onPick: function (uid) { chosen = uid; tree.draw(); tree.focus(uid); },
    });
    tree.node.classList.add('sv-split-tree');
    const extra = el('div', 'sv-split-field');
    extra.append(el('label', 'sv-pos-label', t('publish.sv_split_assembly')), tree.node);
    openValueBox(button, {
      title: t('publish.sv_split_title'), number: entry.node.number, label: t('publish.sv_split_label', { quantity: entry.node.quantity }), inputMode: 'decimal', value: '', action: t('publish.sv_split_do'),
      extra: extra, className: 'sv-split',
      check: function (text) {
        if (!/^\d{1,12}(\.\d{1,6})?$/.test(text) || !(Number(text) > 0)) return t('publish.sv_err_bad_quantity');
        if (!(Number(text) < have)) return t('publish.sv_split_too_much', { quantity: entry.node.quantity });
        return chosen ? '' : t('publish.sv_split_pick');
      },
      accept: function (text) {
        openPlace({ parentId: chosen });
        run(function () { structure.split(id, chosen, text); });
      },
    });
  }

  /** Quick add: the MBOM becomes a copy of the EBOM, item numbers and all. When Fusion Manage has lines already, the user is asked first, as this replaces them
   *  (they are only replaced in the viewer: nothing is written until Publish, and undo gives them back). */
  function matchEbom() {
    const mine = structure;
    function go() {
      if (structure !== mine) return;   // the Bill of Materials was read again while the question was open
      opened.clear();
      opened.add(S.ROOT);   // the MBOM itself stays open, or the lines just made would be folded away
      run(function () { structure.matchEbom(); });
    }
    if (!mine.hasLines()) { go(); return; }
    ns.pubItemPanel.confirm({ title: t('publish.sv_match_title'), lead: t('publish.sv_match_lead'), ask: t('publish.sv_match_ask'), confirm: t('publish.sv_match_confirm'),
                              icon: ICONS.match, onConfirm: go });
  }

  /** Automatic renumber of every assembly (the toolbar), after a question, as it changes the numbers Fusion Manage has (only when the publish sends them:
   *  nothing is sent now, and Undo takes it back). Nothing to renumber is said, with no question. */
  function renumber() {
    const mine = structure;
    if (!mine.renumbering().length) { ns.toast.show(t('publish.sv_renumber_none'), { tone: 'info' }); return; }
    ns.pubItemPanel.confirm({
      title: t('publish.sv_renumber'), lead: t('publish.sv_renumber_lead_all'), ask: t('publish.sv_renumber_ask'), confirm: t('publish.sv_renumber_confirm'), icon: ICONS.renumber,
      onConfirm: function () {
        if (structure !== mine) return;   // the Bill of Materials was read again while the question was open
        run(function () { return structure.renumber(); });
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

  /** The bought item ``made`` goes into the MBOM, standing for the EBOM line ``node`` it was made from, in the quantity that line has. */
  function addBought(mine, node, made) {
    if (structure !== mine) return;
    const place = placeForNew();
    openPlace(place);
    run(function () {
      return structure.addItems([{ id: made.id, number: made.number, name: made.name || node.name, link: made.link, quantity: node.quantity, source: node.key }], place.parentId, place.before);
    });
  }

  /** Create Bought Version on an EBOM line: the dialog opens at once and looks in Fusion Manage first. A bought version that is there already is offered
   *  in the dialog and, once confirmed, added to the MBOM (``onFound``) instead of making a second; else the form shows and the new item is added
   *  (``onCreated``). */
  function createBought(node) {
    const mine = structure;
    ns.pubItemPanel.open({ mode: 'bought', sourceNumber: node.number, number: node.number,
                           onFound: function (found) { addBought(mine, node, found); },
                           onCreated: function (made) { addBought(mine, node, made); } });
  }

  /** An icon on an EBOM line was used: Create Bought Version, or else add the line (an assembly comes with the lines under it, as a drag does). */
  function ebomRowAction(id, act, targets) {
    if (act === 'bought') {
      const node = ebomNode(id);   // the dialog finds the component's item from the Data Model's link, else by number
      createBought(node);
      return;
    }
    const place = placeForNew();
    openPlace(place);
    run(function () { structure.addFromEbom(targets, place.parentId, place.before, true); });
  }

  /** An icon on an MBOM line was used (not the magnifier). */
  function mbomRowAction(id, act, button, targets) {
    if (act === 'position') { openPositionBox(button, id); return; }
    if (act === 'split') { openSplitBox(button, id); return; }
    if (act === 'remove') { run(function () { structure.remove(targets); }); return; }
    if (act !== 'addTo') return;
    if (destMenu && destMenu.button === button) closeDestMenu(); else openDestMenu(button, targets);
  }

  /** An icon on a line was used. */
  function rowAction(pane, id, act, button) {
    if (act === 'details') { showDetails(pane, id); return; }
    const targets = targetsOf(pane, id);
    if (pane === 'ebom') ebomRowAction(id, act, targets);
    else mbomRowAction(id, act, button, targets);
  }

  /** The component of the EBOM with this key. */
  function ebomNode(key) { return view.ebomAt[key]; }

  /** The row of the Bill of Materials the component ``id`` was read from, in the form the Details Panel opens (``bomModel.lineComponent``). */
  function componentOf(id) {
    const row = host.rows().find(function (r) { return r.id === id; });
    if (!row) throw new Error('No row of the Bill of Materials has the component ' + id);   // never guess which component a line stands for
    return model.lineComponent(row);
  }

  /** The EBOM line whose component a line is (``from``, or null) and the Fusion Manage item it is (``itemId``, or ''). */
  function detailsOrigin(pane, node) {
    if (pane === 'ebom') return { from: node, itemId: '' };
    const source = node.source ? ebomNode(node.source) : null;
    const same = !!source && S.numberKey(source.number) === S.numberKey(node.number);   // the same item: not a bought version (number and suffix) or an added item
    return { from: same ? source : null, itemId: node.itemId || '' };
  }

  /** What the Details Panel opens for a line (``pubDetails.open``): the design itself for either root; a line with a Fusion Component, to compare with Fusion Manage;
   *  else a line with no component (``noComponent``: one only Fusion Manage has, one added, a bought version, a new one). ``itemId`` is the Fusion Manage item the
   *  line is, when it is known (an MBOM line read from Fusion Manage), and decides the item tabs. */
  function detailsLine(pane, id) {
    const base = { key: id, pane: pane };
    if (id === (pane === 'ebom' ? '0' : S.ROOT)) return Object.assign(model.rootComponent(host.summary()), base);
    const node = pane === 'ebom' ? ebomNode(id) : index.get(id).node;
    const origin = detailsOrigin(pane, node);
    const from = origin.from;
    const itemId = origin.itemId;
    if (from && from.componentId) return Object.assign(componentOf(from.componentId), base, { itemId: itemId });
    return Object.assign({ id: '', root: false, noComponent: true, item_number: node.number, part_number: '', description: '', name: node.name,
                           title: [node.number, node.name].filter(Boolean).join(' - '), itemId: itemId }, base);
  }

  /** The magnifier on a line: the Details Panel opens for it, and the line stays marked until the panel closes. */
  function showDetails(pane, id) {
    const line = detailsLine(pane, id);   // first: when it throws, the mark stays where it was
    detailsAt = { pane: pane, id: id };
    ns.pubDetails.open(line);
    markDetails();
  }

  /** Marks the line whose Details Panel is open, and no other, without drawing the trees again. */
  function markDetails() {
    closeDestMenu();
    [['ebom', dom.ebomTree], ['mbom', dom.mbomTree]].forEach(function (pair) {
      pair[1].querySelectorAll('.sv-row').forEach(function (row) {
        const on = !!detailsAt && detailsAt.pane === pair[0] && row.dataset.id === detailsAt.id;
        row.classList.toggle('sv-details', on);
        if (on) row.setAttribute('aria-current', 'true'); else row.removeAttribute('aria-current');
      });
    });
  }

  function lineExists(at) { return at.pane === 'ebom' ? !!view.ebomAt[at.id] : index.has(at.id); }

  /** The Details Panel was closed (or opened for something that is not a line): the mark goes. */
  function detailsClosed() {
    const had = detailsAt;
    detailsAt = null;
    if (had && structure) markDetails();
  }

  /** The state of each toolbar button: enabled, or disabled with the reason as its tooltip. */
  function updateTools() {
    const b = dom.tools;
    function set(button, reason) { button.disabled = !!reason; button.title = reason || button.getAttribute('aria-label'); }   // the reason is the tooltip of one that cannot be used
    set(b.undo, structure.canUndo() ? '' : t('publish.sv_nothing_to_undo'));
    set(b.redo, structure.canRedo() ? '' : t('publish.sv_nothing_to_redo'));
    set(b.match, ebom.children.length ? '' : t('publish.sv_match_nothing'));
  }

  // ---- Drawing -------------------------------------------------------------------------

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
    const open = openNotes.has(key);
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
  function heldTotal(key) { return (view.held[key] || []).reduce(function (sum, l) { return sum + Number(l.quantity); }, 0); }

  /** What is to be said of an EBOM line: what stands for it in the MBOM, and where the quantities do not agree. */
  function ebomNotes(node, state) {
    const notes = [];
    if (!state) return notes;
    const lines = view.held[node.key] || [];
    const words = { total: shownQuantity(String(heldTotal(node.key))), quantity: shownQuantity(node.quantity) };
    if (state.bought) notes.push({ tone: 'info', text: t('publish.sv_note_bought', { numbers: lines.map(function (l) { return l.number; }).join(', ') }) });
    if (state.exceeded) notes.push({ tone: 'warn', text: t('publish.sv_note_exceeds', words) });
    else if (state.quantity) notes.push({ tone: 'warn', text: t('publish.sv_note_short', words) });
    if (state.moved) {   // which assembly of the MBOM it is under, so it need not be looked for
      const under = lines.map(function (l) { return (view.parentOf[l.uid] || {}).number || '-'; }).filter(function (n, i, all) { return all.indexOf(n) === i; });
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
      const was = structure.find(flags.oldParent);
      notes.push({ tone: 'update', text: t('publish.sv_note_moved', { number: was ? was.number || '-' : '-' }) });
    }
    if (flags.quantity) notes.push({ tone: 'update', text: t('publish.sv_note_quantity', { from: shownQuantity(flags.oldQuantity), to: shownQuantity(node.quantity) }) });
    if (flags.reordered) notes.push({ tone: 'update', text: t('publish.sv_note_reordered') });
    return notes;
  }

  /** What is to be said of an MBOM line: what it stands for, what changed in it, and whether it holds more than the EBOM has. */
  function mbomNotes(node, cmp, flags) {
    const from = node.source ? view.ebomAt[node.source] : null;
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
    const shown = more[parentId] || LIMIT;
    kids.slice(0, shown).forEach(function (kid) { drawKid(kid); });
    if (kids.length > shown) container.appendChild(moreNode(parentId, kids.length - shown));
  }

  /** The icons on an EBOM line: the magnifier on every line, then Create Bought Version and add. */
  function ebomActions(node, depth, state, full) {
    const count = ebomSelected.has(node.key) ? ebomSelected.size : 1;
    const actions = [{ act: 'details', icon: 'search', label: t('publish.sv_act_details') }];   // first, on every line
    // A bought version is for a component not built in the MBOM: one already in it has none. Off, with the reason, until Make or buy is set up.
    // A component with no item in Fusion Manage is told by the dialog, which looks for it when asked. Always first, then add with its children, then add.
    if (depth && !(state && !state.missing) && !(state && state.blocked)) {
      const reason = !host.boughtReady() ? t('publish.item_bought_not_set_up') : '';
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
  function isDetailsAt(pane, id) { return !!detailsAt && detailsAt.pane === pane && detailsAt.id === id; }

  /** The classes of an EBOM line: its state, a search hit, the colour bar's context lines, and the tone of its notes. */
  function ebomLineClasses(entry, tone) {
    const node = entry.node;
    const context = entry.filter && entry.depth && !entry.filter.keep.has(node.key);
    const classes = ebomStateClasses(entry.state).concat([ebomHits.has(node.key) ? 'sv-hit' : '', context ? 'sv-row-context' : '', toneClass(tone)]);
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
             isOpen: entry.isOpen, selected: ebomSelected.has(node.key), details: isDetailsAt('ebom', node.key), badges: badges, draggable: depth > 0 && !full,
             actions: ebomActions(node, depth, state, full), seq: depth ? node.sequence : '', notes: entry.notes, noteKey: 'ebom:' + node.key, tone: tone, classes: ebomLineClasses(entry, tone) };
  }

  function drawEbom(container, cmp) {
    const list = [];
    const filter = filterView();
    function walk(node, depth) {
      const state = cmp.ebom[node.key];
      const isOpen = ebomOpened.has(node.key) || (!!filter && filter.ebom.has(node.key));   // with the filter on, what has a match under it is open
      const kids = filter ? node.children.filter(function (c) { return filter.keep.has(c.key) || filter.ebom.has(c.key); }) : node.children;
      if (depth) list.push(node.key);
      const notes = depth ? ebomNotes(node, state) : [];
      container.appendChild(lineNode(ebomLineSpec({ node: node, depth: depth, state: state, filter: filter, notes: notes, isOpen: isOpen, kids: kids })));
      if (notes.length && openNotes.has('ebom:' + node.key)) container.appendChild(noteRow(notes, depth));
      if (isOpen) drawKidLines(container, node.key, kids, function (kid) { walk(kid, depth + 1); });
    }
    walk(ebom, 0);
    visible.ebom = list;
  }

  /** The icons on an MBOM line: the magnifier on every line, and below the root the position, add to an assembly, and the bin last. */
  function mbomActions(node, depth) {
    const count = selected.has(node.uid) ? selected.size : 1;
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
    const context = entry.filter && entry.depth && !hits.has(uid);
    return [hits.has(uid) ? 'sv-hit' : '', context ? 'sv-row-context' : '', toneClass(tone)].filter(Boolean).join(' ');
  }

  /** The ``lineNode`` spec of an MBOM line. ``entry``: node, depth, cmp, numbers, filter, notes, isOpen, kids. */
  function mbomLineSpec(entry) {
    const node = entry.node;
    const depth = entry.depth;
    const tone = toneOf(entry.notes);
    return { id: node.uid, depth: depth, number: node.number, name: node.name, quantity: depth ? node.quantity : '', editable: depth > 0,
             hasKids: entry.kids.length > 0, isOpen: entry.isOpen, selected: selected.has(node.uid), details: isDetailsAt('mbom', node.uid), badges: [], draggable: depth > 0,
             actions: mbomActions(node, depth), seq: depth ? entry.numbers[node.uid] || '' : '', classes: mbomLineClasses(entry, tone), tone: tone, notes: entry.notes, noteKey: 'mbom:' + node.uid,
             purchased: !!node.bought || (node.kind === 'added' && !!node.source), mfgOwn: isMfgOwnLine(node, entry.cmp) };
  }

  function drawMbom(container, cmp, chg) {
    const numbers = ns.mbomPlan.lineNumbers(structure, chg);   // the line numbers Fusion Manage has, or will have when published
    const list = [];
    const cut = filterView();
    const filter = cut && cut.mbomOn ? cut : null;   // the colour bar cuts down the EBOM only
    function walk(node, depth) {
      const flags = chg.changes[node.uid];
      const isOpen = opened.has(node.uid) || (!!filter && filter.mbom.has(node.uid));   // with the filter on, what has a match under it is open
      const kids = filter ? node.children.filter(function (c) { return hits.has(c.uid) || filter.mbom.has(c.uid); }) : node.children;
      if (depth) list.push(node.uid);
      const notes = depth ? mbomNotes(node, cmp, flags) : [];
      container.appendChild(lineNode(mbomLineSpec({ node: node, depth: depth, cmp: cmp, numbers: numbers, filter: filter, notes: notes, isOpen: isOpen, kids: kids })));
      if (notes.length && openNotes.has('mbom:' + node.uid)) container.appendChild(noteRow(notes, depth));
      if (isOpen) drawKidLines(container, node.uid, kids, function (kid) { walk(kid, depth + 1); });
    }
    walk(structure.root(), 0);
    visible.mbom = list;
  }

  /** Draw the structure, and tell the panel it may have changed (what publishing covers). For what changes the structure or the data it is drawn from;
   *  a selection, a fold, a note or the search only needs ``render``. */
  function update() {
    render();
    host.planned();
  }

  /** The structure's ``compare()`` and ``changes()``, worked out once for each state of the structure. */
  function compare() {
    if (!compared) compared = { cmp: structure.compare(), chg: structure.changes() };
    return compared;
  }

  /** Rows of grey bars in both tables. Drawn once for as long as the wait lasts: drawing them again would restart their sweep. */
  function drawSkeleton() {
    if (skeleton) return;
    skeleton = true;
    [dom.ebomTree, dom.mbomTree].forEach(function (tree) { tree.replaceChildren.apply(tree, ui.skeletonRows(SKELETON_ROWS)); });
    dom.found.textContent = '';
  }

  /** Shows the parts of the viewer that fit the phase: the panes, or the error; the status and the busy mark while the structure is awaited. */
  function showPhase(failed, waiting) {
    dom.panes.hidden = failed;
    dom.tools.bar.hidden = failed;
    dom.footer.hidden = failed;
    dom.state.hidden = !failed;
    dom.tools.bar.toggleAttribute('inert', waiting);   // nothing to search or edit yet
    dom.status.hidden = !waiting;
    dom.removed.hidden = waiting;
    [dom.ebomTree, dom.mbomTree].forEach(function (tree) { tree.setAttribute('aria-busy', String(waiting)); });
  }

  /** A line the filters leave undrawn is not selected any more: Add, Remove and drag would act on what cannot be seen. ``cut`` is ``filterView()``. */
  function dropUndrawnSelection(cut) {
    if (!cut) return;
    Array.from(ebomSelected).forEach(function (key) { if (!cut.keep.has(key) && !cut.ebom.has(key)) ebomSelected.delete(key); });
    if (cut.mbomOn) Array.from(selected).forEach(function (uid) { if (!hits.has(uid) && !cut.mbom.has(uid)) selected.delete(uid); });
  }

  /** The numbers of the lines the plan removes, under the MBOM. */
  function showRemoved(chg) {
    dom.removed.textContent = chg.removed.length
      ? t('publish.sv_removed', { numbers: chg.removed.map(function (r) { return r.cascade ? r.number + ' (+' + r.cascade + ')' : r.number; }).join(', ') }) : '';
  }

  /** How many lines the search found, with where as the tooltip. */
  function showFound() {
    const found = hits.size + ebomHits.size;   // in both panes
    dom.found.textContent = !searchText ? '' : !found ? t('publish.sv_found_none') : found === 1 ? t('publish.sv_found_one') : t('publish.sv_found_many', { count: found });
    dom.found.title = searchText && found ? t('publish.sv_found_where', { ebom: ebomHits.size, mbom: hits.size }) : '';
    dom.found.classList.toggle('none', !!searchText && !found);
  }

  function render() {
    closeDestMenu();
    if (!dom) return;
    if (detailsAt && structure && !lineExists(detailsAt)) {   // its line was removed (or an edit was undone): the panel for it goes
      detailsAt = null;
      ns.pubDetails.close();
    }
    const failed = phase === 'error';
    const waiting = !structure && !failed;   // the toolbar and the two tables with no lines yet, and what they wait for
    showPhase(failed, waiting);
    if (waiting) { drawSkeleton(); return; }
    if (failed) return;
    skeleton = false;
    const cmp = compare().cmp;
    const chg = compare().chg;
    const scroll = [dom.ebomTree.scrollTop, dom.mbomTree.scrollTop];
    dom.ebomTree.replaceChildren();
    dom.mbomTree.replaceChildren();
    drawMeter(cmp);
    dropUndrawnSelection(filterView());
    drawEbom(dom.ebomTree, cmp);
    drawMbom(dom.mbomTree, cmp, chg);
    dom.ebomTree.scrollTop = scroll[0];
    dom.mbomTree.scrollTop = scroll[1];
    showRemoved(chg);
    showFound();
    dom.tools.filter.setAttribute('aria-pressed', String(filtering));
    updateTools();
  }

  // ---- Events (one listener for each pane) ---------------------------------------------

  function expandAll(on) {
    resetFolds();
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

  /** Open the assemblies above an EBOM line (``path``: each assembly above it and the place of the next one under it), and draw it past the first lines. */
  function revealEbom(path) {
    path.forEach(function (step) {
      ebomOpened.add(step.key);
      if (step.at >= (more[step.key] || LIMIT)) more[step.key] = step.at + 1;
    });
  }

  /** The status of an EBOM line for the colour bar: 'missing' (no MBOM line is made from it), 'quantity' (the MBOM lines do not add up to its quantity),
   *  'matched' (all else), or '' for a line a purchased part above it stands for (it is not counted). */
  function statusOf(state) {
    if (!state || state.blocked) return '';
    return state.missing ? 'missing' : state.quantity ? 'quantity' : 'matched';
  }

  /** What the filters leave drawn (the search with the filter button on, and the colour bar's choice): ``{mbom, ebom, keep, mbomOn}``. ``mbom`` and ``ebom`` hold
   *  the assemblies above a line kept (uids and keys), ``keep`` the EBOM keys kept, ``mbomOn`` whether the MBOM is cut down too (only the search does that).
   *  Null when neither is on (every line is drawn). */
  function filterView() {
    const bySearch = filtering && !!searchText;
    if (!bySearch && !statusFilter) return null;
    const up = { mbom: new Set(), ebom: new Set(), keep: new Set(), mbomOn: bySearch };
    if (bySearch) {
      hits.forEach(function (uid) {
        let entry = index.get(uid);
        while (entry && entry.parent) { up.mbom.add(entry.parent.uid); entry = index.get(entry.parent.uid); }
      });
    }
    const states = compare().cmp.ebom;
    (bySearch ? Array.from(ebomHits) : Object.keys(states)).forEach(function (key) {
      if (statusFilter && statusOf(states[key]) !== statusFilter) return;
      up.keep.add(key);
      const parts = key.split('.');
      for (let n = 1; n < parts.length; n++) up.ebom.add(parts.slice(0, n).join('.'));
    });
    return up;
  }

  /** The colour bar under the Fusion Component pane: a green, an amber and a red part, as wide as the EBOM lines added, with a different quantity and missing.
   *  A part is a button that keeps only those lines (and the assemblies above them); pressing it again shows all. */
  function drawMeter(cmp) {
    const counts = { matched: 0, quantity: 0, missing: 0 };
    Object.keys(cmp.ebom).forEach(function (key) { const status = statusOf(cmp.ebom[key]); if (status) counts[status]++; });
    if (statusFilter && !counts[statusFilter]) statusFilter = '';   // nothing is left of it
    const total = counts.matched + counts.quantity + counts.missing;
    dom.meter.hidden = !total;
    Object.keys(dom.meterParts).forEach(function (status) {
      const part = dom.meterParts[status];
      part.hidden = !counts[status];
      part.style.flexGrow = String(counts[status]);
      part.textContent = String(counts[status]);
      const words = { count: counts[status] };
      const label = status === 'matched' ? t('publish.sv_meter_matched', words) : status === 'quantity' ? t('publish.sv_meter_quantity', words) : t('publish.sv_meter_missing', words);
      part.title = label;
      part.setAttribute('aria-label', label);
      part.setAttribute('aria-pressed', String(statusFilter === status));
    });
    dom.meter.classList.toggle('sv-meter-on', !!statusFilter);
  }

  function pickStatus(status) {
    statusFilter = statusFilter === status ? '' : status;
    render();
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

  /** Enter in the search: scroll to the next match, the lines of the Fusion Component pane first, then the Fusion Manage ones. */
  function nextHit() {
    const list = Array.from(ebomHits).map(function (key) { return { tree: dom.ebomTree, id: key }; })
      .concat(Array.from(hits).map(function (uid) { return { tree: dom.mbomTree, id: uid }; }))
      .filter(function (hit) { return !!hit.tree.querySelector('[data-id="' + hit.id + '"]'); });   // the colour bar may leave a hit undrawn
    if (!list.length) return;
    hitIndex = (hitIndex + 1) % list.length;
    const row = list[hitIndex].tree.querySelector('[data-id="' + list[hitIndex].id + '"]');
    if (row && row.scrollIntoView) row.scrollIntoView({ block: 'center' });
  }

  function toggleFilter() {
    filtering = !filtering;
    render();
  }

  /** The note of a line opens or closes under it. */
  function toggleNote(button) {
    const key = button.dataset.note;
    if (openNotes.has(key)) openNotes.delete(key); else openNotes.add(key);
    render();
  }

  /** The fold button of a line: the assembly opens or closes. */
  function toggleFold(pane, id) {
    const set = pane === 'mbom' ? opened : ebomOpened;
    if (set.has(id)) set.delete(id); else set.add(id);
    dropHidden();
    render();
  }

  /** A click on a line that was not on an icon, the note or "Show more": the grip, the fold, the quantity, or else the line is selected. */
  function clickLine(pane, id, event) {
    if (event.target.closest('.sv-grip')) return;
    if (event.target.closest('.sv-toggle')) { toggleFold(pane, id); return; }
    if (pane === 'mbom' && event.target.closest('button.sv-qty')) { editQuantity(event.target.closest('button.sv-qty'), id); return; }
    if (pane === 'mbom' && id === S.ROOT) return;
    if (pane === 'mbom') choose(selected, visible.mbom, id, event);
    else if (id !== '0') choose(ebomSelected, visible.ebom, id, event);
    render();
  }

  function paneClick(pane, event) {
    const moreButton = event.target.closest('.sv-more');
    if (moreButton) { moreClick(moreButton.dataset.more); return; }
    const noteButtonClicked = event.target.closest('.sv-note-btn');
    if (noteButtonClicked) { toggleNote(noteButtonClicked); return; }
    const row = event.target.closest('.sv-row');
    if (!row) return;
    const act = event.target.closest('.sv-act');
    if (act) { if (!act.disabled) rowAction(pane, row.dataset.id, act.dataset.act, act); return; }
    clickLine(pane, row.dataset.id, event);
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
    const zone = id === S.ROOT ? 'into' : S.zoneOf(event.clientY - box.top, box.height, true);   // a drop in the middle of any line goes under it
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
    const lines = pane === 'mbom' ? visible.mbom : visible.ebom;
    if (!set.has(id)) {   // no redraw: the line being dragged must stay in the page
      set.clear(); set.add(id);
      (pane === 'mbom' ? dom.mbomTree : dom.ebomTree).querySelectorAll('.sv-row').forEach(function (r) {
        r.classList.toggle('selected', r.dataset.id === id);
        r.setAttribute('aria-selected', r.dataset.id === id ? 'true' : 'false');
      });
    }
    drag = { from: pane, ids: lines.filter(function (x) { return set.has(x); }) };
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

  /** The pointer, with the button down, went far enough from where it was pressed for it to be a drag and not a click. */
  function pointerPassedStart(event) {
    return Math.abs(event.clientX - pressed.x) >= DRAG_START_PX || Math.abs(event.clientY - pressed.y) >= DRAG_START_PX;
  }

  /** The drag starts: the lines to drag are chosen, and the ghost that follows the pointer is made. */
  function beginDrag() {
    startDrag(pressed.pane, pressed.row);
    const first = pressed.row.querySelector('.sv-label');
    pressed.ghost = el('div', 'sv-ghost', (first ? first.textContent : '') + (drag.ids.length > 1 ? ' +' + (drag.ids.length - 1) : ''));
    document.body.appendChild(pressed.ghost);
    document.body.style.cursor = 'grabbing';
  }

  function moveGhost(event) {
    const ghost = pressed.ghost;
    ghost.style.left = (event.clientX + 14) + 'px';
    ghost.style.top = (event.clientY + 10) + 'px';
    ghost.dataset.mode = drag.from === 'mbom' ? 'move' : 'add';
  }

  /** Marks the place a drop over ``over`` (an element of the MBOM pane) would go to, and the mark of the place before goes. */
  function markDropPlace(over, event) {
    const where = placeAt({ target: over, clientY: event.clientY });
    if (where.row && where.row === dropMark && dropMark.classList.contains('sv-drop-' + where.zone)) return;   // the same place as the last move
    clearMark();
    if (where.row) { dropMark = where.row; dropMark.classList.add('sv-drop-' + where.zone); }
  }

  function pointerMove(event) {
    if (!pressed || !structure) return;
    if (!pressed.ghost) {
      if (!pointerPassedStart(event)) return;
      beginDrag();
    }
    event.preventDefault();
    moveGhost(event);
    const over = mbomTarget(event);
    if (!over) { clearMark(); return; }
    scrollNear(dom.mbomTree, event.clientY);
    markDropPlace(over, event);
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
    if (place) dropOn(place, dropped, event);
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

  /** Whether the key is Ctrl (or Command) with ``letter``. */
  function isShortcut(event, letter) { return (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === letter; }

  function keyMbom(event) {
    if (event.target.closest('input, button')) return;   // a key in a field or on an icon is that control's
    if (event.key === 'Delete' && selected.size) {
      event.preventDefault();
      const ids = chosenIds();
      run(function () { structure.remove(ids); });
    } else if (isShortcut(event, 'z') && structure.canUndo()) {
      event.preventDefault();
      undo();
    } else if (isShortcut(event, 'y') && structure.canRedo()) {
      event.preventDefault();
      redo();
    }
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
    const found = el('span', 'sv-found');   // a small badge: how many lines matched, and where (its tooltip)
    tools.undo = iconButton('undo', t('publish.sv_undo'), undo);
    tools.redo = iconButton('redo', t('publish.sv_redo'), redo);
    tools.fold = ns.pubUi.foldTools(function () { expandAll(false); }, function () { expandAll(true); });
    const history = el('div', 'sv-pair');   // undo and redo, as a pair like collapse and expand
    history.append(tools.undo, tools.redo);
    tools.add = iconButton('addItems', t('publish.sv_add_items'), addItems);
    tools.newItem = iconButton('boxPlus', t('publish.item_new'), function () { ns.pubItemPanel.open({ mode: 'assembly' }); });
    const searchBox = el('div', 'sv-search-box');   // the field with a magnifier inside it
    searchBox.append(ns.svg(ICONS.search, 16), search);
    tools.match = iconButton('match', t('publish.sv_match'), matchEbom);
    tools.renumber = iconButton('renumber', t('publish.sv_renumber'), renumber);
    tools.filter = iconButton('filter', t('publish.sv_filter'), toggleFilter);
    tools.filter.setAttribute('aria-pressed', 'false');
    tools.bar.append(searchBox, tools.filter, found, tools.fold, history, tools.add, tools.newItem, tools.match, tools.renumber);
    const state = el('div', 'sv-state');
    const left = pane(t('publish.sv_ebom_title'), t('publish.sv_ebom_tip'));
    const meter = el('div', 'sv-meter');   // the colour bar under the Fusion Component lines
    meter.setAttribute('role', 'group');
    meter.setAttribute('aria-label', t('publish.sv_meter_label'));
    const meterParts = {};
    [['matched', 'sv-meter-ok'], ['quantity', 'sv-meter-warn'], ['missing', 'sv-meter-bad']].forEach(function (pair) {
      const part = el('button', 'sv-meter-part ' + pair[1]);
      part.type = 'button';
      part.addEventListener('click', function () { if (structure) pickStatus(pair[0]); });
      meterParts[pair[0]] = part;
      meter.appendChild(part);
    });
    meter.hidden = true;
    left.box.appendChild(meter);
    left.tree.classList.add('sv-tree-ebom');   // its hover icons sit nearer the quantity: no quantity box to clear
    const right = pane(t('publish.sv_mbom_title'), t('publish.sv_mbom_tip'));
    const panes = el('div', 'sv-panes');
    panes.append(left.box, right.box);
    const removed = el('p', 'muted sv-removed');
    const status = el('p', 'muted sv-status');   // what the skeleton waits for
    status.setAttribute('role', 'status');
    const footer = el('div', 'sv-footer');
    footer.append(status, removed);
    root.replaceChildren(tools.bar, state, panes, footer);

    left.tree.addEventListener('click', function (event) { paneClick('ebom', event); });
    right.tree.addEventListener('click', function (event) { paneClick('mbom', event); });
    [['ebom', left.tree], ['mbom', right.tree]].forEach(function (pair) {
      pair[1].addEventListener('mousedown', function (event) { pointerDown(pair[0], event); });
      pair[1].addEventListener('click', function (event) { if (justDragged) { event.stopPropagation(); justDragged = false; } }, true);   // the end of a drag selects nothing
    });
    right.tree.addEventListener('keydown', keyMbom);
    return { tools: tools, search: search, state: state, panes: panes, footer: footer, status: status, removed: removed, found: found, meter: meter, meterParts: meterParts,
             ebomTree: left.tree, mbomTree: right.tree };
  }

  /** Show the structure (``on``) or the area beside it, which holds the loading skeleton, a message, an error or the choice of the MBOM. What was
   *  built is kept while that is on, so edits are not lost. */
  function show(on) {
    active = on;
    ns.$('pub-bom').hidden = on;
    ns.$('pub-structure').hidden = !on;
    if (on) refresh();
  }

  /** What publishing would do with the structure now (``mbom-plan.js``), or null while there is none to publish. */
  function plan() {
    if (!structure || phase === 'error') return null;
    const summary = host.summary();
    return ns.mbomPlan.build({ structure: structure, changes: compare().chg, ebom: ebom, rows: host.rows(), summary: summary, skipped: skippedLines(host.rows(), summary) });
  }

  /** The components the design's own rules leave out (no item number, a number Fusion Manage shares): ``{component id: item number}``. Found again only
   *  when the rows read (the panel gives a new list whenever it reads more) or the design change. */
  function skippedLines(rows, summary) {
    const key = JSON.stringify(summary);
    if (skippedFor && skippedFor.rows === rows && skippedFor.key === key) return skippedFor.skipped;
    const skipped = {};
    model.buildItems(rows, summary).forEach(function (item) { if (item.status === 'skipped' && item.lineId) skipped[item.lineId] = item.design.pn || item.componentName; });
    skippedFor = { rows: rows, key: key, skipped: skipped };
    return skipped;
  }

  /** ``hostApi`` is the panel (see the header). */
  function init(hostApi) {
    host = hostApi;
    dom = makeDom(ns.$('pub-structure'));
  }

  ns.mbomViewer = {
    init: init, reset: reset, answer: answer, say: say,
    structureRead: function () { ready = true; refresh(); },
    show: show, plan: plan,
    detailsClosed: detailsClosed,
    showTable: function () { show(false); },   // the MBOM has to be chosen, and the choice is drawn in the area beside the structure
  };
})(window.MfgUi);
