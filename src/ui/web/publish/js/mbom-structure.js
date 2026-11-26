/**
 * Publish Item panel: the structure of a manufacturing bill of materials, as ``ns.mbomStructure``.
 *
 * The MBOM is a tree of its own, not a copy of the engineering one: components can sit under other assemblies, in another order, more than
 * once, or under assemblies that only manufacturing has (a phantom is one of them: an Items record whose Type is the phantom value). This
 * module holds that tree and the edits of it, with undo and redo, and says how it differs from the EBOM and from the MBOM as it was read.
 * Pure data, no DOM and no requests: the viewer draws it and the publish plan turns it into requests. Layer: domain.
 *
 * An EBOM node is ``{key, number, name, quantity, componentId, sequence, children}`` (``sequence`` is the line's number in the design, as the table shows it); ``ebomFromRows`` makes the tree from the rows the panel has read.
 * An MBOM node is ``{uid, kind, number, name, quantity, source, itemId, edgeId, sequence (the BOM line number it has in Fusion Manage), isNew, cut, children}`` (an added item also has ``link`` and ``linkable``):
 *
 * * ``kind`` is ``component`` (made from an EBOM node, which is its ``source``), ``added`` (an existing item picked in Fusion Manage),
 *   ``assembly`` (a new manufacturing assembly) or ``phantom`` (a new phantom assembly);
 * * ``itemId`` is the id of the item Fusion Manage holds for it ("" for one that does not exist yet) and ``edgeId`` the id of its BOM line
 *   there ("" for a line that is not in Fusion Manage yet);
 * * ``renumber`` is true on an assembly whose lines the publish numbers 1, 2, 3 in the tree's order whatever else changed (see ``renumber``); ``pin`` is the
 *   BOM line number the user gave a line (see ``setNumber``), which the publish keeps;
 * * ``cut`` is true for a line read at the deepest level whose own lines were not read (the answer shows it has some);
 * * ``isNew`` is true for a node the user made or added, which has no BOM line in Fusion Manage yet.
 *
 * Every edit that cannot be done throws an ``Error`` with a ``key`` (and ``params``) saying why, and changes nothing then. An edit that changes nothing is not a
 * step of the history. A place to put nodes is a parent and the sibling to go before (``before``, "" for the end). The tree is replaced by
 * a copy on a refused edit, undo and redo: keep uids, never nodes.
 */
(function (ns) {
  'use strict';

  const ROOT = 'root';
  const KINDS = { component: 'component', added: 'added', assembly: 'assembly', phantom: 'phantom' };
  const HISTORY = 50;   // steps of undo kept

  /** The error of an edit that cannot be done: it carries a ``key`` (and ``params``), and the viewer puts it in words. */
  function fail(key, params) {
    const error = new Error(key);
    error.key = key;
    error.params = typeof params === 'string' ? { detail: params } : params || {};
    return error;
  }

  function numberKey(text) { return String(text === undefined || text === null ? '' : text).trim().toLowerCase(); }

  function quantityText(value) {
    const text = String(value === undefined || value === null ? '' : value).trim();
    return text || '1';
  }

  /** ``{key, number, name, quantity, componentId, children}`` for the design and every row below it. ``rows`` hold every level (``level``,
   *  ``item_number`` or ``part_number``, ``name`` or ``description``, ``quantity``, ``id``); the keys are the positions ("0", "0.1", "0.1.0").
   *  A blank quantity is 1. Rows the comparison with Fusion Manage added (status ``extra``) are left out. */
  function ebomFromRows(rows, root) {
    const top = { key: '0', number: root.item_number || root.part_number || '', name: root.name || root.description || '', quantity: '', componentId: root.component_id || '', children: [] };
    const path = [top];
    rows.forEach(function (r) {
      if (r.status === 'extra') return;   // a line only Fusion Manage has (the compared rows add them): it is not in the EBOM
      const parent = path[r.level];
      const node = { key: parent.key + '.' + parent.children.length, number: r.item_number || r.part_number || '', name: r.name || r.description || '',
                     quantity: quantityText(r.quantity), componentId: r.id || '',
                     sequence: r.sequence === undefined || r.sequence === null ? '' : String(r.sequence), children: [] };
      parent.children.push(node);
      path[r.level + 1] = node;
    });
    return top;
  }

  /** A quantity typed: plain decimal digits (no sign, exponent or hex), above 0, kept as the plain decimal it is. */
  function positive(value) {
    const text = String(value).trim();
    if (!/^(\d{1,12})(\.\d{1,6})?$/.test(text)) throw fail('bad_quantity');
    const n = Number(text);
    if (!(n > 0)) throw fail('bad_quantity');
    return String(n);
  }

  /** Where a drop on a line goes, from where in the line the pointer is: the top quarter is before it, the bottom quarter after it, and the middle
   *  inside it (``canHold``); a line that cannot hold lines has only before (top half) and after. */
  function zoneOf(offsetY, height, canHold) {
    const at = height > 0 ? offsetY / height : 0.5;
    if (!canHold) return at < 0.5 ? 'before' : 'after';
    return at < 0.25 ? 'before' : at > 0.75 ? 'after' : 'into';
  }

  /** The MBOM tree as read, with each line's ``source`` set to the EBOM line with its item number (a copy; the tree given is left as it is). ``suffix`` (that of
   *  bought versions, from Settings) also maps a line that is an EBOM line's number and the suffix: see below.
   *  Where an item number is in the EBOM more than once, a line takes the one under the EBOM line its nearest mapped assembly is, then one
   *  not taken yet, then the first. A line with no item number is not mapped. */
  function mapByNumber(tree, ebom, suffix) {
    const byNumber = {};   // number -> [{key, parent, taken}]
    (function index(node) {
      node.children.forEach(function (c) {
        const k = numberKey(c.number);
        if (k) (byNumber[k] = byNumber[k] || []).push({ key: c.key, parent: node.key, taken: false });
        index(c);
      });
    })(ebom);
    function map(node, ancestor, isRoot) {
      let source = isRoot ? ebom.key : '';
      const k = numberKey(node.number);
      if (!isRoot && k && byNumber[k]) {
        const list = byNumber[k];
        const pick = list.find(function (c) { return !c.taken && c.parent === ancestor; }) || list.find(function (c) { return !c.taken; })
          || list.find(function (c) { return c.parent === ancestor; }) || list[0];
        pick.taken = true;
        source = pick.key;
      }
      return Object.assign({}, node, { source: source, children: (node.children || []).map(function (c) { return map(c, source || ancestor, false); }) });
    }
    const mapped = map(tree, ebom.key, true);
    const tail = numberKey(suffix);
    if (!tail) return mapped;
    // A line left over whose number is an EBOM line's and the suffix of bought versions is the bought version of that line: it stands for it, as one
    // added in the viewer does (``bought``). Only an EBOM line no line has the number of is taken, so a line with the same number always wins.
    const taken = new Set();
    (function used(node) { node.children.forEach(function (c) { if (c.source) taken.add(c.source); used(c); }); })(mapped);
    const suffixed = {};   // the number of an EBOM line and the suffix -> [{key, parent}]
    (function index(node) {
      node.children.forEach(function (c) {
        const k = numberKey(c.number);
        if (k) (suffixed[k + tail] = suffixed[k + tail] || []).push({ key: c.key, parent: node.key });
        index(c);
      });
    })(ebom);
    function boughtPass(node, ancestor, isRoot) {
      let source = node.source;
      let bought = !!node.bought;
      if (!isRoot && !source) {
        const list = suffixed[numberKey(node.number)] || [];
        const pick = list.find(function (c) { return !taken.has(c.key) && c.parent === ancestor; }) || list.find(function (c) { return !taken.has(c.key); });
        if (pick) { taken.add(pick.key); source = pick.key; bought = true; }
      }
      return Object.assign({}, node, { source: source, bought: bought, children: node.children.map(function (c) { return boughtPass(c, source || ancestor, false); }) });
    }
    return boughtPass(mapped, ebom.key, true);
  }

  // ---- The state of one structure ---------------------------------------------------
  // ``create`` holds one state object (``st``) and every edit below is a function of it: ``mbom`` (the tree, replaced by a copy on a refused edit, undo and
  // redo), ``baseline`` (the MBOM as read, or null), ``past`` and ``future`` (the history), ``counter`` (the last uid made), and what never changes.

  function newUid(st) { st.counter += 1; return 'n' + st.counter; }

  function snapshotOf(node) { return JSON.parse(JSON.stringify(node)); }

  function sequenceText(value) { return value === undefined || value === null ? '' : String(value); }

  function textOf(value) { return String(value || ''); }

  /** A quantity rounded to the six decimals the quantities are kept in. */
  function roundQuantity(value) { return Math.round(value * 1e6) / 1e6; }

  function fromEbomNode(st, node, deep) {
    return { uid: newUid(st), kind: KINDS.component, number: node.number, name: node.name, quantity: node.quantity || '1', source: node.key,
             itemId: '', edgeId: '', componentId: node.componentId || '', isNew: true, cut: false, children: deep ? node.children.map(function (c) { return fromEbomNode(st, c, true); }) : [] };
  }

  /** A node as read from Fusion Manage, field by field (not new, and no other field comes along). */
  function adoptRead(st, read, isRoot) {
    return { uid: isRoot ? ROOT : newUid(st), kind: read.kind && KINDS[read.kind] ? read.kind : KINDS.component, number: textOf(read.number), name: textOf(read.name),
             quantity: isRoot ? '' : quantityText(read.quantity), source: textOf(read.source), itemId: textOf(read.itemId),
             bought: !!read.bought, edgeId: textOf(read.edgeId), sequence: sequenceText(read.sequence), cut: !!read.cut, isNew: false,
             children: (read.children || []).map(function (c) { return adoptRead(st, c, false); }) };
  }

  /** The state of a new structure: the MBOM as read, or a copy of the EBOM when there is none read. */
  function newState(options) {
    const ebom = options.ebom;
    const lookup = {};   // EBOM key -> EBOM node
    (function index(node) { lookup[node.key] = node; node.children.forEach(index); })(ebom);
    const st = { ebom: ebom, lookup: lookup, phantomAllowed: !!options.phantom, counter: 0, mbom: null, baseline: null, past: [], future: [] };
    if (options.mbom) {
      st.mbom = adoptRead(st, Object.assign({}, options.mbom, { source: ebom.key }), true);
      st.baseline = snapshotOf(st.mbom);
    } else {
      st.mbom = { uid: ROOT, kind: KINDS.component, number: ebom.number, name: ebom.name, quantity: '', source: ebom.key, itemId: '', edgeId: '', isNew: true, cut: false,
                  children: ebom.children.map(function (c) { return fromEbomNode(st, c, true); }) };
      // nothing in Fusion Manage to compare with: everything is new (the baseline stays null)
    }
    return st;
  }

  // ---- Reading the tree --------------------------------------------------------------

  function findNode(root, id) {
    if (root.uid === id) return root;
    for (let i = 0; i < root.children.length; i++) {
      const hit = findNode(root.children[i], id);
      if (hit) return hit;
    }
    return null;
  }

  function findParent(root, id) {
    for (let i = 0; i < root.children.length; i++) {
      if (root.children[i].uid === id) return root;
      const hit = findParent(root.children[i], id);
      if (hit) return hit;
    }
    return null;
  }

  function needNode(st, id) {
    const node = findNode(st.mbom, id);
    if (!node) throw fail('no_such_line');
    return node;
  }

  /** Is ``node`` an assembly already: the MBOM itself, an assembly of manufacturing's own, or a line that has lines or whose EBOM node has. (Any line
   *  may still take a drop; this picks the place a new item goes.) */
  function holdsLines(st, node) {
    if (node.uid === ROOT || node.kind === KINDS.phantom || node.kind === KINDS.assembly || node.children.length) return true;
    return !!(node.source && st.lookup[node.source] && st.lookup[node.source].children.length);
  }

  function usedNumbers(root) {
    const numbers = {};
    (function walk(node) { numbers[numberKey(node.number)] = true; node.children.forEach(walk); })(root);
    return numbers;
  }

  /** How much of the EBOM line ``key`` the MBOM holds: the quantities of the lines made from it, in every assembly. */
  function heldQuantity(root, key) {
    let total = 0;
    (function walk(node) { node.children.forEach(function (c) { if (c.source === key) total += Number(c.quantity) || 0; walk(c); }); })(root);
    return total;
  }

  // ---- Making an edit ------------------------------------------------------------------

  /** Run an edit as one step of the history: when it throws, the structure is as it was; when it changes nothing, there is no step. */
  function editStep(st, change) {
    const text = JSON.stringify(st.mbom);   // the one copy of the tree as it was: it is parsed only to keep as a step, or to restore
    const beforeCounter = st.counter;
    try {
      const result = change();
      if (JSON.stringify(st.mbom) !== text) {
        st.past.push(JSON.parse(text));
        if (st.past.length > HISTORY) st.past.shift();
        st.future = [];
      }
      return result;
    } catch (error) {
      st.mbom = JSON.parse(text);
      st.counter = beforeCounter;
      throw error;
    }
  }

  /** ``ids`` once each, without those that sit under another of them (what an edit of the one takes the other along with), in tree order. One walk. */
  function topmostIds(root, ids) {
    const wanted = new Set(ids);
    if (wanted.has(ROOT)) throw fail('root_immutable');
    const found = [];
    let count = 0;   // lines wanted that are in the tree, taken along with others or not
    (function walk(node, inside) {
      node.children.forEach(function (c) {
        const isWanted = wanted.has(c.uid);
        if (isWanted) { count += 1; if (!inside) found.push(c.uid); }
        walk(c, inside || isWanted);
      });
    })(root, false);
    if (count < wanted.size) throw fail('no_such_line');
    return found;
  }

  /** The first sibling after position ``at`` of ``parent`` that is not moving: where a line that was to go before a moving one goes instead. "" when none. */
  function nextStayingSibling(parent, moving, at) {
    for (let i = at + 1; i < parent.children.length; i++) {
      if (moving.indexOf(parent.children[i].uid) < 0) return parent.children[i].uid;
    }
    return '';
  }

  /** One check for every edit that moves lines already in the MBOM. Returns ``{moving, anchor}``: the lines, once each in tree order, and the
   *  sibling to go before. A ``before`` that is not a line directly under ``parentId`` is refused; one that is moving itself becomes the next
   *  sibling that stays. */
  function guardPlacement(st, ids, parentId, before) {
    if (!ids.length) throw fail('nothing_selected');
    const moving = topmostIds(st.mbom, ids);
    moving.forEach(function (id) {
      if (id === parentId || findNode(needNode(st, id), parentId) !== null) throw fail('inside_itself');
    });
    const parent = needNode(st, parentId);   // any line of the MBOM may take lines: manufacturing may build a BOM for a part the design has none for
    let anchor = before || '';
    if (anchor) {
      const at = parent.children.findIndex(function (c) { return c.uid === anchor; });
      if (at < 0) throw fail('before_not_under');
      if (moving.indexOf(anchor) >= 0) anchor = nextStayingSibling(parent, moving, at);
    }
    return { moving: moving, anchor: anchor };
  }

  function detachNodes(st, ids) {
    return ids.map(function (id) {
      const parent = findParent(st.mbom, id);
      if (!parent) throw fail('no_such_line');
      return parent.children.splice(parent.children.findIndex(function (c) { return c.uid === id; }), 1)[0];
    });
  }

  function insertNodes(parent, nodes, anchor) {
    let at = parent.children.length;
    if (anchor) at = parent.children.findIndex(function (c) { return c.uid === anchor; });
    parent.children.splice(at, 0, ...nodes);
  }

  /** Put new ``nodes`` under ``parentId`` before ``before``. */
  function placeNew(st, nodes, parentId, before) {
    const parent = needNode(st, parentId);
    if (before && !parent.children.some(function (c) { return c.uid === before; })) throw fail('before_not_under');
    insertNodes(parent, nodes, before);
  }

  function freshNode(st, kind, spec) {
    if (kind === KINDS.phantom && !st.phantomAllowed) throw fail('phantom_needs_settings');
    const number = String(spec.number || '').trim();
    if (!number) throw fail('needs_number');
    if (usedNumbers(st.mbom)[numberKey(number)]) throw fail('number_used', { number: number });
    return { uid: newUid(st), kind: kind, number: number, name: String(spec.name || '').trim(), quantity: spec.quantity ? positive(spec.quantity) : '1', source: '',
             itemId: '', edgeId: '', isNew: true, cut: false, children: [] };
  }

  // ---- The edits -----------------------------------------------------------------------

  /** The place a drop on line ``id`` means: ``zone`` is ``before``, ``after`` or ``into``; gives ``{parentId, before}``. */
  function positionOf(st, zone, id) {
    const node = needNode(st, id);
    if (zone === 'into') return { parentId: id, before: '' };
    const parent = findParent(st.mbom, id);
    if (!parent) throw fail('no_place_root');
    if (zone === 'before') return { parentId: parent.uid, before: node.uid };
    if (zone !== 'after') throw fail('unknown_place', { zone: zone });
    const at = parent.children.findIndex(function (c) { return c.uid === id; });
    return { parentId: parent.uid, before: at + 1 < parent.children.length ? parent.children[at + 1].uid : '' };
  }

  /** A new manufacturing assembly (``kind`` "assembly") or phantom ("phantom") under ``where.parentId``; ``where.adoptIds`` lines already in the MBOM go into it.
   *  ``where``: ``{kind, parentId, before, spec, adoptIds}``. */
  function createAssemblyAt(st, where) {
    return editStep(st, function () {
      const node = freshNode(st, where.kind, where.spec);
      if (where.adoptIds && where.adoptIds.length) {
        const guard = guardPlacement(st, where.adoptIds, where.parentId, where.before);
        node.children = detachNodes(st, guard.moving);
        insertNodes(needNode(st, where.parentId), [node], guard.anchor);
      } else {
        placeNew(st, [node], where.parentId, where.before);
      }
      return node.uid;
    });
  }

  /** Move lines (and what is under them) under ``parentId``, before ``before``: between assemblies and, under one, reordering. */
  function moveLines(st, ids, parentId, before) {
    editStep(st, function () {
      const guard = guardPlacement(st, ids, parentId, before);
      const moving = detachNodes(st, guard.moving);
      moving.forEach(function (n) { delete n.pin; });   // a line put elsewhere has no number of its own any more
      insertNodes(needNode(st, parentId), moving, guard.anchor);
    });
  }

  /** The line of ``dest`` that takes an amount split off ``node``: an item is once in an assembly, so a line of the same item number there takes the amount (whatever made it), else the same item. */
  function findSplitTarget(dest, node) {
    const key = numberKey(node.number);
    return dest.children.find(function (c) { return key ? numberKey(c.number) === key : !!node.itemId && c.itemId === node.itemId; });
  }

  /** Split the quantity of a line between assemblies: ``amount`` of it goes to the assembly ``parentId`` and the line keeps the rest (``amount`` must be
   *  less than its quantity, and the assembly another one than its own, and not inside it). The assembly takes the amount as a line of its own made like this
   *  one (not what is under it: the lines of an item are the same wherever it is used), unless it has the same item number already: then that line has the amount added. Returns the uid of the line that took it. */
  function splitLine(st, id, parentId, amount) {
    return editStep(st, function () {
      if (id === ROOT) throw fail('root_immutable');
      const node = needNode(st, id);
      const moved = positive(amount);
      const left = roundQuantity(Number(node.quantity) - Number(moved));
      if (!(left > 0)) throw fail('split_too_much', { quantity: node.quantity });
      if (id === parentId || findNode(node, parentId) !== null) throw fail('inside_itself');
      const dest = needNode(st, parentId);
      if (dest === findParent(st.mbom, id)) throw fail('split_same_assembly');
      node.quantity = String(left);
      const same = findSplitTarget(dest, node);
      if (same) {
        same.quantity = String(roundQuantity(Number(same.quantity) + Number(moved)));
        return same.uid;
      }
      const made = Object.assign({}, node, { uid: newUid(st), edgeId: '', isNew: true, cut: false, quantity: moved, children: [] });   // what is under the line stays where it is: an item's own lines are the same wherever it is used
      delete made.sequence;
      delete made.pin;
      delete made.renumber;
      dest.children.push(made);
      return made.uid;
    });
  }

  /** Refuse the EBOM lines (``keys``) that sit under a purchased item bought whole. */
  function refuseBlockedLines(st, keys) {
    const standing = compareStructure(st).ebom;
    keys.forEach(function (key) {
      if (standing[key] && standing[key].blocked) throw fail('under_purchased', { number: st.lookup[key].number });
    });
  }

  /** Add ``left`` (what is left of the EBOM line ``key``'s quantity) to the line of ``parent`` made from it. Returns that line, or null when ``parent`` has none. */
  function mergeIntoSameLine(parent, key, left) {
    const same = parent.children.find(function (c) { return c.kind === KINDS.component && c.source === key; });
    if (!same) return null;   // not under this assembly yet
    same.quantity = String(roundQuantity(Number(same.quantity) + left));   // the line is under this assembly already: it takes the rest, not a second line beside it
    return same;
  }

  /** The lines the EBOM lines (``keys``) add under ``parent``: ``{merged, nodes}``, the lines that took the rest of their quantity and the new ones. */
  function takeFromEbom(st, parent, keys, deep) {
    const merged = [];   // lines of that assembly made from the same EBOM line that took the rest of its quantity
    const nodes = [];
    keys.forEach(function (key) {
      if (!st.lookup[key]) throw fail('no_such_ebom');
      const node = fromEbomNode(st, st.lookup[key], deep);
      const wanted = Number(st.lookup[key].quantity || 1);
      const left = roundQuantity(wanted - heldQuantity(st.mbom, key));
      if (left <= 0) throw fail('would_exceed', { number: node.number });
      const same = mergeIntoSameLine(parent, key, left);
      if (same) { merged.push(same); return; }
      if (left < wanted) node.quantity = String(left);
      nodes.push(node);
    });
    return { merged: merged, nodes: nodes };
  }

  /** A line that would hold more than the EBOM has is refused (the edit then puts the tree back as it was). */
  function refuseExceeded(states, nodes) {
    nodes.forEach(function (n) {
      if (states[n.source] && states[n.source].exceeded) throw fail('would_exceed', { number: n.number });
      refuseExceeded(states, n.children);
    });
  }

  /** Add the EBOM nodes (``keys``) as components: just them, or with everything under them when ``place.deep``. A line the MBOM holds some of already takes
   *  what is left of its quantity (4 in the EBOM and 1 in the MBOM adds 3): added to the line under ``place.parentId`` that is made from it, when there is one, else as a
   *  line of its own; one that has none left is refused. ``place``: ``{parentId, before, deep}``. */
  function addFromEbom(st, keys, place) {
    return editStep(st, function () {
      const parent = needNode(st, place.parentId);
      refuseBlockedLines(st, keys);
      const taken = takeFromEbom(st, parent, keys, !!place.deep);
      placeNew(st, taken.nodes, place.parentId, place.before);
      refuseExceeded(compareStructure(st).ebom, taken.nodes);
      return taken.merged.concat(taken.nodes).map(function (n) { return n.uid; });
    });
  }

  /** The lines of ``theirs`` (EBOM nodes) as lines of the MBOM, keeping the ``mine`` lines that have the same item number. */
  function mergeEbomLines(st, mine, theirs) {
    const pool = mine.filter(function (m) { return m.kind === KINDS.component || m.kind === KINDS.added; });
    return theirs.map(function (e) {
      const key = numberKey(e.number);
      const at = key ? pool.findIndex(function (m) { return numberKey(m.number) === key; }) : -1;
      if (at < 0) return fromEbomNode(st, e, true);
      const node = pool.splice(at, 1)[0];
      node.quantity = e.quantity || '1';
      node.source = e.key;
      if (!node.cut) node.children = mergeEbomLines(st, node.children, e.children);   // a line cut at the deepest level has lines that were not read: they stay unread
      return node;
    });
  }

  /** Quick add: make the MBOM a copy of the EBOM, every line with what is under it, in the EBOM's order, with its quantity. A line Fusion Manage has with the same
   *  item number under the same assembly stays that line (its line id, number and what is under it are kept, so nothing is removed and added again, and an
   *  assembly keeps its own bill of materials); the lines it has that the EBOM does not are dropped, and the rest are new. One step of the history. */
  function matchEbom(st) {
    return editStep(st, function () {
      if (!st.ebom.children.length) throw fail('no_such_ebom');
      st.mbom.children = mergeEbomLines(st, st.mbom.children, st.ebom.children);
    });
  }

  /** The assemblies ``renumber`` would mark: those that have a line of Fusion Manage's whose BOM line number is not its place (1, 2, 3 in the tree's order),
   *  or a line given a number of its own (``setNumber``), and are not marked yet. */
  function assembliesToRenumber(st) {
    const found = [];
    (function walk(node) {
      const lacks = !node.renumber && node.children.some(function (c, at) {
        return c.pin !== undefined || (!c.isNew && sequenceText(c.sequence).trim() !== String(at + 1));
      });
      if (lacks) found.push(node);
      node.children.forEach(walk);
    })(st.mbom);
    return found;
  }

  /** Renumber: the assemblies of ``renumbering()`` are marked (``renumber``) and the numbers their lines were given are let go, so the publish numbers their lines
   *  1, 2, 3 in the tree's order. Returns how many were marked; none is no step of the history. */
  function renumberAssemblies(st) {
    return editStep(st, function () {
      const marking = assembliesToRenumber(st);
      marking.forEach(function (node) {
        node.renumber = true;
        node.children.forEach(function (c) { delete c.pin; });
      });
      return marking.length;
    });
  }

  /** Refuse ``wanted`` when a line of ``parent`` other than ``node`` shows it already. */
  function refuseTakenNumber(parent, node, current, wanted) {
    parent.children.forEach(function (c) {
      if (c !== node && Number(current[c.uid]) === wanted) throw fail('number_taken', { number: String(wanted) });
    });
  }

  /** The lines in the order of their numbers (``pin``), and the order they have where those are the same. */
  function sortedByPin(children) {
    return children.map(function (c, at) { return { c: c, at: at }; })
      .sort(function (x, y) { return Number(x.c.pin) - Number(y.c.pin) || x.at - y.at; }).map(function (e) { return e.c; });
  }

  /** Give a line the BOM line number ``value`` (a whole number, 1 or more, with no other limit). ``current`` is the number each line of the assembly shows now
   *  (``{uid: number}``): they are kept as they are, so only this line changes, and the lines are put in the order of their numbers. Another line with that number
   *  is refused (``number_taken``), a value that is not a whole number too (``bad_number``). */
  function setLineNumber(st, id, value, current) {
    editStep(st, function () {
      if (id === ROOT) throw fail('root_immutable');
      const node = needNode(st, id);
      const parent = findParent(st.mbom, id);
      const text = String(value).trim();
      if (!/^\d{1,9}$/.test(text) || Number(text) < 1) throw fail('bad_number');
      const wanted = Number(text);
      refuseTakenNumber(parent, node, current, wanted);
      parent.children.forEach(function (c) { if (c !== node && current[c.uid] !== undefined) c.pin = String(Number(current[c.uid])); });
      node.pin = String(wanted);
      delete parent.renumber;
      parent.children = sortedByPin(parent.children);
    });
  }

  /** Add existing Fusion Manage items (``{id, number, name, link, linkable, quantity, source}``) as lines. ``source`` (an EBOM key) is for the bought
   *  version of a component: the line stands for that EBOM line in the comparison. */
  function addItemLines(st, items, parentId, before) {
    return editStep(st, function () {
      const nodes = items.map(function (item) {
        return { uid: newUid(st), kind: KINDS.added, number: item.number, name: item.name || '', quantity: item.quantity ? positive(item.quantity) : '1', source: item.source || '',
                 itemId: item.id || '', edgeId: '', link: item.link || '', linkable: item.linkable || null, isNew: true, children: [] };
      });
      placeNew(st, nodes, parentId, before);
      return nodes.map(function (n) { return n.uid; });
    });
  }

  /** Put a line at ``position`` (1 is the first) among the lines of its assembly. A position that is not a whole number from 1 to how many lines the assembly
   *  has is refused (``bad_position``, with ``max``). The publish then numbers the assembly 1, 2, 3 in this order. */
  function setLinePosition(st, id, position) {
    editStep(st, function () {
      if (id === ROOT) throw fail('root_immutable');
      const node = needNode(st, id);
      const parent = findParent(st.mbom, id);
      const max = parent.children.length;
      const text = String(position).trim();
      const wanted = /^\d{1,6}$/.test(text) ? Number(text) : 0;
      if (wanted < 1 || wanted > max) throw fail('bad_position', { max: max });
      parent.children.splice(parent.children.indexOf(node), 1);
      parent.children.splice(wanted - 1, 0, node);
    });
  }

  function removeLines(st, ids) {
    editStep(st, function () {
      if (!ids.length) throw fail('nothing_selected');
      detachNodes(st, topmostIds(st.mbom, ids));
    });
  }

  function setLineQuantity(st, id, value) {
    editStep(st, function () {
      const node = needNode(st, id);
      if (id === ROOT) throw fail('root_no_quantity');
      node.quantity = positive(value);
    });
  }

  function undoEdit(st) {
    if (!st.past.length) return;
    st.future.push(snapshotOf(st.mbom));
    st.mbom = st.past.pop();
  }

  function redoEdit(st) {
    if (!st.future.length) return;
    st.past.push(snapshotOf(st.mbom));
    st.mbom = st.future.pop();
  }

  /** UIDs of the lines whose number or name holds ``text`` (any case); none for no text. */
  function searchLines(st, text) {
    const needle = numberKey(text);
    const hits = [];
    if (!needle) return hits;
    (function walk(node) {
      if (numberKey(node.number).indexOf(needle) >= 0 || numberKey(node.name).indexOf(needle) >= 0) hits.push(node.uid);
      node.children.forEach(walk);
    })(st.mbom);
    return hits;
  }

  // ---- How the MBOM stands against the EBOM --------------------------------------------

  /** EBOM key -> the MBOM lines made from it, ``[{node, ancestor}]``, and each MBOM line's state (``mapped`` or ``mfg``). */
  function collectMbomLines(mbom) {
    const lines = {};
    const mbomState = {};
    (function walk(node, ancestor) {
      node.children.forEach(function (child) {
        if (child.source) (lines[child.source] = lines[child.source] || []).push({ node: child, ancestor: ancestor });
        mbomState[child.uid] = child.source ? 'mapped' : 'mfg';
        walk(child, child.source || ancestor);
      });
    })(mbom, mbom.source);
    return { lines: lines, mbomState: mbomState };
  }

  /** The state of one EBOM line against the ``held`` MBOM lines made from it (``matched`` and ``blocked`` come after): ``parentKey`` is the EBOM line it is under. */
  function ebomLineState(child, held, parentKey) {
    const total = held.reduce(function (sum, h) { return sum + Number(h.node.quantity); }, 0);   // over every MBOM line made from it, in every assembly
    const state = {
      missing: !held.length,
      quantity: held.length > 0 && Math.abs(total - Number(child.quantity)) > 1e-9 * Math.max(1, Math.abs(total)),
      moved: held.length > 0 && held.every(function (h) { return h.ancestor !== parentKey; }),
    };
    state.exceeded = state.quantity && total > Number(child.quantity);   // more in the MBOM than the EBOM has (``quantity`` is true too)
    return state;
  }

  /** The state of every EBOM line, from the MBOM lines made from each (``lines``). */
  function compareEbomLines(ebom, lines) {
    const ebomState = {};
    (function walk(node, parentKey, under) {   // gives whether every line under ``node`` is matched; ``under``: a purchased item stands for an ancestor
      let all = true;
      node.children.forEach(function (child) {
        const held = lines[child.key] || [];
        const bought = held.length > 0 && held.every(function (h) { return h.node.kind === KINDS.added || h.node.bought; });   // a purchased item stands for it (it has no lines under it)
        const state = ebomLineState(child, held, parentKey);
        state.bought = bought;
        state.blocked = under;   // the purchased item above it is bought whole: what is under it is not added
        const below = walk(child, child.key, under || bought);
        state.matched = !state.missing && !state.quantity && (below || state.bought);
        ebomState[child.key] = state;
        if (!state.matched) all = false;
      });
      return all;
    })(ebom, ebom.key, false);
    return ebomState;
  }

  /** How the MBOM stands against the EBOM: ``{ebom, mbom}``. ``ebom`` has, for each EBOM key, ``{missing, quantity, exceeded, moved, matched, bought, blocked}``:
   *  ``missing``: no MBOM line is made from it; ``quantity``: the quantities of its lines together are not the EBOM's; ``exceeded``: they are more (``quantity``
   *  is true too); ``moved``: no line is under the assembly the EBOM has it in (it and ``quantity`` can both be true); ``matched``: its quantity is all in the
   *  MBOM and so is everything under it, unless a purchased item stands for it; ``bought``: every line made from it is an added item or a bought version
   *  read from Fusion Manage (``mapByNumber`` with the suffix); ``blocked``: a purchased item above it is bought whole, so what is under it is not added.
   *  ``mbom`` has each line's state: ``mapped``, or ``mfg`` for a line with no EBOM node. Phantoms and assemblies of manufacturing's own do not count as
   *  the parent: a line under one still has its EBOM parent. */
  function compareStructure(st) {
    const collected = collectMbomLines(st.mbom);
    return { ebom: compareEbomLines(st.ebom, collected.lines), mbom: collected.mbomState };
  }

  // ---- What changed since the MBOM was read --------------------------------------------

  /** uid -> {node, parent, at} for every line of the MBOM as read; empty when none was read. */
  function indexReadPlaces(baseline) {
    const old = {};
    if (!baseline) return old;
    (function walk(node) {
      node.children.forEach(function (c, at) { old[c.uid] = { node: c, parent: node.uid, at: at }; walk(c); });
    })(baseline);
    return old;
  }

  /** The uids in the tree now, from one walk. */
  function presentUids(mbom) {
    const present = new Set();
    (function walk(node) { node.children.forEach(function (c) { present.add(c.uid); walk(c); }); })(mbom);
    return present;
  }

  /** An item's number -> {child number -> {sequence, edgeId, quantity}}: the bill of materials Fusion Manage has for it, as read. */
  function readBillsOfMaterials(baseline) {
    const held = {};
    (function lines(node) {
      const mine = held[numberKey(node.number)] = held[numberKey(node.number)] || {};
      node.children.forEach(function (c) { if (!mine[numberKey(c.number)]) mine[numberKey(c.number)] = { sequence: String(c.sequence || ''), edgeId: c.edgeId || '', quantity: c.quantity }; lines(c); });
    })(baseline || { number: '', children: [] });
    return held;
  }

  /** The line of the read MBOM that ``c`` (a line with no place in it) replaces: the same item removed from this assembly, with nothing under it. */
  function findReadded(diff, c, parent) {
    if (c.children.length) return null;
    const id = Object.keys(diff.old).find(function (k) {
      return !diff.present.has(k) && !diff.claimed[k] && diff.old[k].parent === parent.uid && diff.old[k].node.number === c.number && !diff.old[k].node.children.length;
    });
    if (id) diff.claimed[id] = true;
    return id ? diff.old[id] : null;
  }

  /** Flag line ``c`` of ``node``: new, moved, with another quantity (or none of them). A line that kept its assembly is added to ``kept`` with its old place. */
  function flagLine(diff, node, c, kept) {
    const was = diff.old[c.uid] || findReadded(diff, c, node);
    if (was && !diff.old[c.uid]) diff.identity[c.uid] = { sequence: String(was.node.sequence || ''), edgeId: was.node.edgeId || '' };
    if (!was) { diff.changes[c.uid] = { new: true }; return; }
    const flags = {};
    if (was.parent !== node.uid) { flags.moved = true; flags.oldParent = was.parent; }
    else kept.push({ uid: c.uid, at: was.at, was: was });
    flagQuantity(flags, was, c);
    if (Object.keys(flags).length) { flags.edgeId = was.node.edgeId || ''; diff.changes[c.uid] = flags; }
  }

  function flagQuantity(flags, was, c) {
    if (Number(was.node.quantity) === Number(c.quantity)) return;
    flags.quantity = true;
    flags.oldQuantity = was.node.quantity;
  }

  /** The uids of the ``kept`` lines that keep their relative order: the longest run that rises in their old places (the others were reordered). */
  function keptInOrder(kept) {
    const tails = [];   // tails[n]: the index in ``kept`` that ends the best rising run of n + 1 lines
    const from = kept.map(function () { return -1; });
    kept.forEach(function (k, i) {
      let low = 0;
      let high = tails.length;
      while (low < high) {
        const mid = (low + high) >> 1;
        if (kept[tails[mid]].at < k.at) low = mid + 1; else high = mid;
      }
      if (low > 0) from[i] = tails[low - 1];
      tails[low] = i;
    });
    const stays = new Set();
    for (let i = tails.length ? tails[tails.length - 1] : -1; i >= 0; i = from[i]) stays.add(kept[i].uid);
    return stays;
  }

  /** Flag the lines of ``node`` and of everything under it. */
  function flagChildren(diff, node) {
    const kept = [];   // the old places of the lines that were under this assembly before too, in the order they are now
    node.children.forEach(function (c) {
      flagLine(diff, node, c, kept);
      flagChildren(diff, c);
    });
    const stays = keptInOrder(kept);
    kept.forEach(function (k) {
      if (stays.has(k.uid)) return;
      diff.changes[k.uid] = Object.assign(diff.changes[k.uid] || { edgeId: k.was.node.edgeId || '' }, { reordered: true });
    });
  }

  /** The lines of the read MBOM that are gone and whose assembly is not. */
  function removedLines(diff) {
    const gone = {};
    Object.keys(diff.old).forEach(function (id) { if (!diff.present.has(id) && !diff.claimed[id]) gone[id] = true; });
    function count(node) { return node.children.reduce(function (sum, c) { return sum + (gone[c.uid] ? 1 + count(c) : count(c)); }, 0); }
    const removed = [];
    Object.keys(gone).forEach(function (id) {
      if (gone[diff.old[id].parent]) return;   // it went with its assembly: that one says so
      const n = diff.old[id].node;
      removed.push({ uid: id, number: n.number, parent: diff.old[id].parent, edgeId: n.edgeId || '', itemId: n.itemId || '', quantity: n.quantity, sequence: n.sequence || '', cascade: count(n) });
    });
    return removed;
  }

  /** What changed since the MBOM was read. ``changes`` maps a line's uid to its flags: ``{new}`` for a line with no BOM line yet, else any of
   *  ``moved`` (with ``oldParent``, a uid), ``quantity`` (with ``oldQuantity``) and ``reordered`` (its place among the siblings it kept
   *  changed), each independent, and ``edgeId``, the line it has in Fusion Manage. ``held`` is the bill of materials Fusion Manage has for each item as read (an item's own lines are the same wherever it is used). ``identity`` gives a line removed and added again in one edit the number and line id of the line it stands for. ``removed`` lists the lines of the read MBOM that are gone
   *  and whose assembly is not (``{uid, number, parent, edgeId, itemId, quantity, sequence, cascade}``): ``cascade`` counts the lines under it that went
   *  with it. With no MBOM read, every line is new. */
  function changesSince(st) {
    const diff = {
      changes: {}, identity: {},   // identity: uid of a line added again -> the number and the line id the one it replaces has in Fusion Manage
      claimed: {},   // old uid -> true: a line that was removed and added again in the same edit stays the line it was
      old: indexReadPlaces(st.baseline), present: presentUids(st.mbom),
    };
    const held = readBillsOfMaterials(st.baseline);
    flagChildren(diff, st.mbom);
    return { changes: diff.changes, removed: removedLines(diff), identity: diff.identity, held: held };
  }

  // ---- The structure ---------------------------------------------------------------------

  /** A new structure. ``options.ebom``: the EBOM; ``options.mbom``: the MBOM as read (``{number, name, itemId, children}``, lines with their
   *  ``source``, see ``mapByNumber``) or none, which starts it as a copy of the EBOM; ``options.phantom``: whether the workspace can mark a
   *  phantom (Settings names the field and value). The methods of the result are the edits above, on the state this makes. */
  function create(options) {
    const st = newState(options);
    return {
      root: function () { return st.mbom; },
      find: function (id) { return findNode(st.mbom, id); },
      holds: function (id) { return holdsLines(st, needNode(st, id)); },
      position: function (zone, id) { return positionOf(st, zone, id); },
      // Five parameters: the public call shape the viewer and tests use; they are gathered into one object at once.
      createAssembly: function (kind, parentId, before, spec, adoptIds) {
        return createAssemblyAt(st, { kind: kind, parentId: parentId, before: before, spec: spec, adoptIds: adoptIds });
      },
      move: function (ids, parentId, before) { moveLines(st, ids, parentId, before); },
      split: function (id, parentId, amount) { return splitLine(st, id, parentId, amount); },
      addFromEbom: function (keys, parentId, before, deep) { return addFromEbom(st, keys, { parentId: parentId, before: before, deep: deep }); },
      hasLines: function () { return st.mbom.children.length > 0; },   // Does the MBOM have any line under it?
      matchEbom: function () { return matchEbom(st); },
      renumbering: function () { return assembliesToRenumber(st); },
      renumber: function () { return renumberAssemblies(st); },
      setNumber: function (id, value, current) { setLineNumber(st, id, value, current); },
      addItems: function (items, parentId, before) { return addItemLines(st, items, parentId, before); },
      setPosition: function (id, position) { setLinePosition(st, id, position); },
      remove: function (ids) { removeLines(st, ids); },
      setQuantity: function (id, value) { setLineQuantity(st, id, value); },
      canUndo: function () { return st.past.length > 0; },
      canRedo: function () { return st.future.length > 0; },
      undo: function () { undoEdit(st); },
      redo: function () { redoEdit(st); },
      search: function (text) { return searchLines(st, text); },
      compare: function () { return compareStructure(st); },
      changes: function () { return changesSince(st); },
    };
  }

  ns.mbomStructure = { numberKey: numberKey, create: create, ebomFromRows: ebomFromRows, mapByNumber: mapByNumber, zoneOf: zoneOf, ROOT: ROOT };
})(window.MfgUi);
