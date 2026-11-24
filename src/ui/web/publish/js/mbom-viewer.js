/**
 * Publish Item panel: the structure viewer, as ``ns.mbomViewer``. Two panes side by side: the EBOM (the design's Bill of Materials, read-only) and the
 * MBOM (the manufacturing Bill of Materials, which can be edited). The MBOM is ``ns.mbomStructure``; this file draws it and turns what the user
 * does into its edits. Nothing here is sent to Fusion Manage by the viewer itself: the Publish button sends what ``plan()`` makes of the structure
 * (mbom-plan.js).
 *
 * Where the trees come from: the EBOM from the rows the panel has read (all levels, so the whole tree is read first, as Expand all does); the
 * MBOM from the ``mbom_tree`` section (the target item read by its id, every level), mapped to the EBOM by item number. A design with no MBOM item
 * starts as a copy of the EBOM.
 *
 * The viewer keeps uids and EBOM keys only, never nodes: the structure replaces its tree by a copy on a refused edit, undo and redo. Only the
 * lines of an open assembly are drawn, and no more than ``LIMIT`` under one at first, so a large tree stays quick. Every edit goes through
 * ``run``, which says the reason an edit was refused in a toast.
 *
 * ``host``: ``design()`` (the open design's summary), ``rows()`` (compared rows read so far), ``partial()`` (levels not read yet), ``loadTree()``,
 * ``askMbom()``, ``targetId()``, ``target()`` (item number), ``phantom()`` (whether Settings allow phantoms), ``summary()`` (the design, under the
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
    cart: ['M8 20a1 1 0 1 0 0 2 1 1 0 0 0 0-2z', 'M19 20a1 1 0 1 0 0 2 1 1 0 0 0 0-2z', 'M2 3h2l2.7 12.4a2 2 0 0 0 2 1.6h9.7a2 2 0 0 0 2-1.6L22 7H5.1'],   // a shopping cart: a purchased part
    info: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', 'M12 11v6', 'M12 7.5v.5'],   // a circle with an i: the note of a line
    match: ['M3 12h12', 'M11 7l5 5-5 5', 'M20 5v14'],   // an arrow into a bar: the EBOM carried over to the MBOM
    addItems: ['M4 6h11', 'M4 12h7', 'M4 18h7', 'M17 14v6', 'M14 17h6'],   // a list with a plus
    grip: ['M9 6h.01', 'M15 6h.01', 'M9 12h.01', 'M15 12h.01', 'M9 18h.01', 'M15 18h.01'],
    addOne: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', 'M12 8v8', 'M8 12h8'],
    search: ['M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z', 'M16 16l4.5 4.5'],
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
  let skeleton = false;      // the tables hold the grey bars of the wait
  let structure = null;
  let ebom = null;
  let drag = null;           // what is being dragged: { from: 'mbom' | 'ebom', ids }
  let dropMark = null;       // the row showing where a drop would go
  let searchText = '';
  let hitIndex = -1;
  const hits = new Set();    // uids of the lines the search found
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
    clearMark();
    drag = null;
    searchText = '';
    openNotes.clear();
    hitIndex = -1;
    dom.search.value = '';
    hits.clear(); selected.clear(); ebomSelected.clear();
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

  /** Go as far as the data allows: wait for the first level, read the whole EBOM, read the MBOM, then build and draw. Each read is asked once:
   *  while one is on its way the viewer only waits, and a structure that exists (with edits) is never replaced. */
  function refresh() {
    if (!active) return;
    if (structure) { update(); return; }
    if (phase === 'mbom') return;
    if (!ready) { wait('structure', t('publish.reading_bom')); return; }
    if (host.partial()) {
      if (phase !== 'tree') { wait('tree', t('publish.reading_bom')); host.loadTree(); }
      return;
    }
    if (host.targetId()) { wait('mbom', t('publish.sv_reading_mbom')); host.askMbom(); return; }
    build(null);
    update();
  }

  /** Say what the skeleton waits for (under the two tables). The same words are not said again: they must not restart the "taking longer" timer. */
  function say(text) {
    if (text === note && dom.status.textContent) return;
    note = text;
    ui.warnWhenSlow(dom.status, text);
  }

  function wait(next, text) {
    phase = next;
    say(text);
    update();
  }

  function fail(text, retry) {
    phase = 'error';
    note = text;
    dom.state.replaceChildren(ui.errorState(text, retry));
    update();
  }

  /** The answer of the ``mbom_tree`` section. One that nobody waits for (a second answer, or one after the Bill of Materials was read again) is ignored,
   *  so edits are never replaced. */
  function answer(entry) {
    if (structure || phase !== 'mbom') return;
    if (!entry.ok) { fail(entry.message || t('publish.unknown_error'), function () { phase = 'idle'; refresh(); }); return; }
    build(entry.data);
    update();
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
    compared = null;
    view = emptyView();
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

  /** The "Add to assembly" menu, at the left of ``button``: the MBOM as a tree to fold and unfold (without ``targets`` and what is under them), with a
   *  search on top. Choosing a line moves ``targets`` to the end of it. A search shows the lines that match with the ones above them, all open. Only
   *  the lines in view are drawn, and no more than ``DEST_LIMIT``, so a large MBOM stays quick. */
  function openDestMenu(button, targets) {
    closeDestMenu();
    const moving = new Set(targets);
    const open = new Set([S.ROOT]);
    let query = '';
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
    box.appendChild(head);
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
    bar.hidden = true;
    bar.append(find, count);
    box.append(bar, list);
    lens.addEventListener('click', function () {
      bar.hidden = !bar.hidden;
      lens.setAttribute('aria-expanded', bar.hidden ? 'false' : 'true');
      if (bar.hidden) { find.value = ''; query = ''; draw(); lens.focus(); } else find.focus();
    });

    function matches(node) {
      return (node.number + ' ' + node.name).toLowerCase().indexOf(query) >= 0;
    }
    /** Whether the line, or a line under it, matches the search. */
    function wanted(node) {
      if (moving.has(node.uid)) return false;
      return matches(node) || node.children.some(wanted);
    }

    /** How many lines match the search, drawn or not. */
    function countHits(node) {
      if (moving.has(node.uid)) return 0;
      return (matches(node) ? 1 : 0) + node.children.reduce(function (sum, c) { return sum + countHits(c); }, 0);
    }

    function draw() {
      list.replaceChildren();
      let drawn = 0;
      let cut = false;
      (function walk(node, depth) {
        if (moving.has(node.uid) || (query && !wanted(node))) return;
        const hit = !!query && matches(node);
        if (drawn >= DEST_LIMIT) { cut = true; return; }
        drawn += 1;
        const kids = node.children.filter(function (c) { return !moving.has(c.uid); });
        const isOpen = !!query || open.has(node.uid);
        const row = el('div', 'sv-dest-row' + (hit ? ' sv-dest-hit' : ''));
        row.setAttribute('role', 'treeitem');
        row.setAttribute('aria-level', String(depth + 1));
        if (kids.length) row.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
        for (let g = 0; g < depth; g++) row.appendChild(el('span', 'sv-dest-guide'));   // a line down from each line above, so the tree reads as one
        const toggle = el('button', 'sv-dest-toggle');
        toggle.type = 'button';
        toggle.tabIndex = -1;
        toggle.dataset.id = node.uid;
        toggle.disabled = !kids.length || !!query || node.uid === S.ROOT;
        if (kids.length && node.uid !== S.ROOT) {
          const chevron = ui.chevron();
          ui.setChevron(chevron, !isOpen);
          toggle.appendChild(chevron);
        }
        toggle.addEventListener('click', function () {
          if (open.has(node.uid)) open.delete(node.uid); else open.add(node.uid);
          draw();
        });
        const pick = el('button', 'sv-dest-pick');
        pick.type = 'button';
        pick.dataset.id = node.uid;
        pick.appendChild(el('span', 'sv-dest-number', node.number));
        if (node.name) pick.appendChild(el('span', 'sv-dest-name', node.name));
        pick.addEventListener('mouseover', function (event) {   // the full text for the shared tooltip (it reads the title as the pointer arrives, after this), only when the line cuts it short
          if (pick.contains(event.relatedTarget)) return;   // moving between the parts of this line, not arriving
          const label = pick.querySelector('.sv-dest-name');
          if (label && label.scrollWidth > label.clientWidth) pick.title = node.number + ' ' + node.name; else pick.removeAttribute('title');
        });
        pick.addEventListener('click', function () {
          closeDestMenu();
          openPlace({ parentId: node.uid });
          run(function () { structure.move(targets, node.uid, ''); });
        });
        row.append(toggle, pick);
        list.appendChild(row);
        if (isOpen) kids.forEach(function (c) { walk(c, depth + 1); });
      })(structure.root(), 0);
      if (cut) list.appendChild(el('div', 'sv-dest-more', t('publish.sv_dest_more', { count: DEST_LIMIT })));
      const total = query ? countHits(structure.root()) : 0;
      count.textContent = query ? (total ? t('publish.sv_search_count', { count: total }) : t('publish.sv_search_none')) : '';
    }

    function picks() { return Array.from(box.querySelectorAll('.sv-dest-pick')); }
    function step(from, by) {
      const all = picks();
      const at = all.indexOf(from);
      const next = all[Math.max(0, Math.min(all.length - 1, (at < 0 ? (by > 0 ? -1 : all.length) : at) + by))];
      if (next) next.focus();
    }

    find.addEventListener('input', function () { query = find.value.trim().toLowerCase(); draw(); });
    box.addEventListener('keydown', function (event) {
      const on = document.activeElement;
      if (event.key === 'ArrowDown') { event.preventDefault(); step(on, 1); }
      else if (event.key === 'ArrowUp') {
        event.preventDefault();
        if (on === find) return;   // the search is the top of the menu
        if (picks()[0] === on) { if (!bar.hidden) find.focus(); } else step(on, -1);
      } else if (!query && on && on.classList.contains('sv-dest-pick') && (event.key === 'ArrowRight' || event.key === 'ArrowLeft')) {
        const row = on.parentNode;
        if (row.hasAttribute('aria-expanded') && on.dataset.id !== S.ROOT && (row.getAttribute('aria-expanded') === 'true') === (event.key === 'ArrowLeft')) {
          event.preventDefault();
          row.querySelector('.sv-dest-toggle').click();
          const again = box.querySelector('.sv-dest-pick[data-id="' + on.dataset.id + '"]');
          if (again) again.focus();
        }
      }
    });

    draw();
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
    const first = box.querySelector('.sv-dest-pick');
    if (first) first.focus();
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

  /** An icon on a line was used. */
  function rowAction(pane, id, act, button) {
    const targets = targetsOf(pane, id);
    if (pane === 'ebom' && act === 'bought') {
      const node = ebomNode(id);   // the dialog finds the component's item from the Data Model's link, else by number
      createBought(node);
    } else if (pane === 'ebom') {
      const place = placeForNew();
      openPlace(place);
      run(function () { structure.addFromEbom(targets, place.parentId, place.before, true); });   // an assembly comes with the lines under it, as a drag does
    } else if (act === 'remove') {
      run(function () { structure.remove(targets); });
    } else if (act === 'addTo') {
      if (destMenu && destMenu.button === button) closeDestMenu(); else openDestMenu(button, targets);
    }
  }

  /** The component of the EBOM with this key. */
  function ebomNode(key) { return view.ebomAt[key]; }

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

  /** What is to be said of an MBOM line: what it stands for, what changed in it, and whether it holds more than the EBOM has. */
  function mbomNotes(node, cmp, flags) {
    const notes = [];
    const from = node.source ? view.ebomAt[node.source] : null;
    if (node.kind === 'added' && !from) notes.push({ tone: 'info', text: t('publish.sv_note_added') });
    if (node.kind === 'assembly') notes.push({ tone: 'info', text: t('publish.sv_note_assembly') });
    if (node.kind === 'phantom') notes.push({ tone: 'info', text: t('publish.sv_note_phantom') });
    if (node.cut) notes.push({ tone: 'warn', text: t('publish.sv_note_cut') });
    if (from && (node.bought || node.kind === 'added')) notes.push({ tone: 'info', text: t('publish.sv_note_bought_for', { number: from.number }) });
    if (cmp.mbom[node.uid] === 'mfg' && node.kind === 'component') notes.push({ tone: 'info', text: t('publish.sv_note_mfg') });
    const state = from ? cmp.ebom[node.source] : null;
    if (state && state.exceeded) {
      notes.push({ tone: 'warn', text: t('publish.sv_note_exceeds', { total: shownQuantity(String(heldTotal(node.source))), quantity: shownQuantity(from.quantity) }) });
    }
    if (flags) {
      if (flags.new) notes.push({ tone: 'new', text: t('publish.sv_note_new') });
      if (flags.moved) {
        const was = structure.find(flags.oldParent);
        notes.push({ tone: 'update', text: t('publish.sv_note_moved', { number: was ? was.number || '-' : '-' }) });
      }
      if (flags.quantity) notes.push({ tone: 'update', text: t('publish.sv_note_quantity', { from: shownQuantity(flags.oldQuantity), to: shownQuantity(node.quantity) }) });
      if (flags.reordered) notes.push({ tone: 'update', text: t('publish.sv_note_reordered') });
    }
    return notes;
  }

  /** One line: indent, open/close, label, quantity and badges. ``spec``: id, depth, number, name, quantity, editable, hasKids, isOpen, selected, badges, classes,
   *  draggable, actions, seq, notes, noteKey, tone (of the notes), purchased. */
  function lineNode(spec) {
    const row = el('div', 'sv-row' + (spec.selected ? ' selected' : '') + (spec.classes ? ' ' + spec.classes : ''));
    row.dataset.id = spec.id;
    row.setAttribute('role', 'treeitem');
    row.setAttribute('aria-level', String(spec.depth + 1));
    row.setAttribute('aria-selected', spec.selected ? 'true' : 'false');
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
    const icon = ui.treeIcon(spec.depth === 0 ? 'root' : spec.hasKids ? 'assembly' : 'part');   // the table's icon, with its bar on the right
    if (spec.purchased) {   // a purchased part is a cart, not a box
      icon.replaceChildren(ns.svg(ICONS.cart, 16));
      icon.title = t('publish.sv_purchased_part');
    }
    row.appendChild(icon);
    if (spec.seq) row.appendChild(el('span', 'sv-seq', spec.seq));   // the line's number, as the table shows it
    const label = el('span', 'sv-label');
    label.appendChild(el('span', 'sv-pn', spec.number || '-'));
    if (spec.name) label.appendChild(el('span', 'sv-name', spec.name));
    row.appendChild(label);
    spec.badges.forEach(function (b) { row.appendChild(b); });   // the tick, just left of the quantity
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
      // The note's button is right of the quantity; a line with none keeps the room, so the quantities stay in one column.
      row.appendChild(spec.notes && spec.notes.length ? noteButton(spec.notes, spec.noteKey, spec.tone) : el('span', 'sv-note-slot'));
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
    (function walk(node, depth) {
      const state = cmp.ebom[node.key];
      const badges = [];
      if (state && state.matched) badges.push(matchedMark(state.bought));
      const isOpen = ebomOpened.has(node.key);
      if (depth) list.push(node.key);
      const count = ebomSelected.has(node.key) ? ebomSelected.size : 1;
      const full = !!(state && (state.exceeded || state.matched || state.blocked));   // all of it is in the MBOM (adding it again would be more than the EBOM has), or a purchased part above it stands for it
      const actions = [];
      // A bought version is for a component not built in the MBOM: one already in it has none. Off, with the reason, until Make or buy is set up.
      // A component with no item in Fusion Manage is told by the dialog, which looks for it when asked. Always first, then add with its children, then add.
      if (depth && !(state && !state.missing) && !(state && state.blocked)) {
        const reason = !host.boughtReady() ? t('publish.item_bought_not_set_up') : '';
        actions.push({ act: 'bought', icon: 'bought', label: t('publish.item_act_bought', { number: node.number }), reason: reason });   // one that exists is offered by the dialog
      }
      if (depth && !full) actions.push({ act: 'add', icon: 'addOne', label: actionLabel(t('publish.sv_act_add'), count) });
      const notes = depth ? ebomNotes(node, state) : [];
      const tone = toneOf(notes);
      const row = lineNode({ id: node.key, depth: depth, number: node.number, name: node.name, quantity: depth ? node.quantity : '', editable: false, hasKids: node.children.length > 0,
                             isOpen: isOpen, selected: ebomSelected.has(node.key), badges: badges, draggable: depth > 0 && !full, actions: actions, seq: depth ? node.sequence : '', notes: notes, noteKey: 'ebom:' + node.key,
                             tone: tone, classes: [state && state.missing && !state.blocked ? 'sv-row-missing' : '', state && (state.matched || state.blocked) ? 'sv-row-matched' : '', toneClass(tone)].filter(Boolean).join(' ') });
      container.appendChild(row);
      if (notes.length && openNotes.has('ebom:' + node.key)) container.appendChild(noteRow(notes, depth));
      if (!isOpen) return;
      const shown = more[node.key] || LIMIT;
      node.children.slice(0, shown).forEach(function (c) { walk(c, depth + 1); });
      if (node.children.length > shown) container.appendChild(moreNode(node.key, node.children.length - shown));
    })(ebom, 0);
    visible.ebom = list;
  }

  function drawMbom(container, cmp, chg) {
    const numbers = ns.mbomPlan.lineNumbers(structure, chg);   // the line numbers Fusion Manage has, or will have when published
    const list = [];
    (function walk(node, depth) {
      const badges = [];
      const flags = chg.changes[node.uid];
      const isOpen = opened.has(node.uid);
      if (depth) list.push(node.uid);
      const count = selected.has(node.uid) ? selected.size : 1;
      const actions = [];
      if (depth) {   // always in this order: add to an assembly, and the bin last
        actions.push({ act: 'addTo', icon: 'assembly', label: actionLabel(t('publish.sv_act_add_to'), count) },
                     { act: 'remove', icon: 'remove', label: actionLabel(t('publish.sv_act_remove'), count) });
      }
      const notes = depth ? mbomNotes(node, cmp, flags) : [];
      const tone = toneOf(notes);
      container.appendChild(lineNode({ id: node.uid, depth: depth, number: node.number, name: node.name, quantity: depth ? node.quantity : '', editable: depth > 0,
                                       hasKids: node.children.length > 0, isOpen: isOpen, selected: selected.has(node.uid), badges: badges, draggable: depth > 0, actions: actions, seq: depth ? numbers[node.uid] || '' : '',
                                       classes: [hits.has(node.uid) ? 'sv-hit' : '', toneClass(tone)].filter(Boolean).join(' '), tone: tone, notes: notes, noteKey: 'mbom:' + node.uid, purchased: !!node.bought || (node.kind === 'added' && !!node.source) }));
      if (notes.length && openNotes.has('mbom:' + node.uid)) container.appendChild(noteRow(notes, depth));
      if (!isOpen) return;
      const shown = more[node.uid] || LIMIT;
      node.children.slice(0, shown).forEach(function (c) { walk(c, depth + 1); });
      if (node.children.length > shown) container.appendChild(moreNode(node.uid, node.children.length - shown));
    })(structure.root(), 0);
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

  function render() {
    closeDestMenu();
    if (!dom) return;
    const failed = phase === 'error';
    const waiting = !structure && !failed;   // the toolbar and the two tables with no lines yet, and what they wait for
    dom.panes.hidden = failed;
    dom.tools.bar.hidden = failed;
    dom.footer.hidden = failed;
    dom.state.hidden = !failed;
    dom.tools.bar.toggleAttribute('inert', waiting);   // nothing to search or edit yet
    dom.status.hidden = !waiting;
    dom.removed.hidden = waiting;
    [dom.ebomTree, dom.mbomTree].forEach(function (tree) { tree.setAttribute('aria-busy', String(waiting)); });
    if (waiting) { drawSkeleton(); return; }
    if (failed) return;
    skeleton = false;
    const cmp = compare().cmp;
    const chg = compare().chg;
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
    const noteButtonClicked = event.target.closest('.sv-note-btn');
    if (noteButtonClicked) {   // the note of a line opens or closes under it
      const key = noteButtonClicked.dataset.note;
      if (openNotes.has(key)) openNotes.delete(key); else openNotes.add(key);
      render();
      return;
    }
    const row = event.target.closest('.sv-row');
    if (!row) return;
    const id = row.dataset.id;
    const act = event.target.closest('.sv-act');
    if (act) { if (!act.disabled) rowAction(pane, id, act.dataset.act, act); return; }
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
    ghost.dataset.mode = drag.from === 'mbom' ? 'move' : 'add';
    const over = mbomTarget(event);
    if (!over) { clearMark(); return; }
    scrollNear(dom.mbomTree, event.clientY);
    const where = placeAt({ target: over, clientY: event.clientY });
    if (where.row && where.row === dropMark && dropMark.classList.contains('sv-drop-' + where.zone)) return;   // the same place as the last move
    clearMark();
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
    tools.fold = ns.pubUi.foldTools(function () { expandAll(false); }, function () { expandAll(true); });
    const history = el('div', 'sv-pair');   // undo and redo, as a pair like collapse and expand
    history.append(tools.undo, tools.redo);
    tools.add = iconButton('addItems', t('publish.sv_add_items'), addItems);
    tools.newItem = iconButton('boxPlus', t('publish.item_new'), function () { ns.pubItemPanel.open({ mode: 'assembly' }); });
    const searchBox = el('div', 'sv-search-box');   // the field with a magnifier inside it
    searchBox.append(ns.svg(ICONS.search, 16), search);
    tools.match = iconButton('match', t('publish.sv_match'), matchEbom);
    tools.bar.append(searchBox, found, tools.fold, history, tools.add, tools.newItem, tools.match);
    const state = el('div', 'sv-state');
    const left = pane(t('publish.sv_ebom_title'), t('publish.sv_ebom_tip'));
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
    return { tools: tools, search: search, state: state, panes: panes, footer: footer, status: status, removed: removed, found: found,
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
    init: init, reset: reset, answer: answer, treeDone: treeDone, say: say,
    structureRead: function () { ready = true; refresh(); },
    show: show, plan: plan,
    showTable: function () { show(false); },   // the MBOM has to be chosen, and the choice is drawn in the area beside the structure
  };
})(window.MfgUi);
