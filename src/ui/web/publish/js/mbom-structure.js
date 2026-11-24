/**
 * Publish Item panel: the structure of a manufacturing bill of materials, as ``ns.mbomStructure``.
 *
 * The MBOM is a tree of its own, not a copy of the engineering one: components can sit under other assemblies, in another order, more than
 * once, or under assemblies that only manufacturing has (a phantom is one of them: an Items record whose Type is the phantom value). This
 * module holds that tree and the edits of it, with undo and redo, and says how it differs from the EBOM and from the MBOM as it was read.
 * Pure data, no DOM and no requests: the viewer draws it and the publish plan turns it into requests.
 *
 * An EBOM node is ``{key, number, name, quantity, componentId, sequence, children}`` (``sequence`` is the line's number in the design, as the table shows it); ``ebomFromRows`` makes the tree from the rows the panel has read.
 * An MBOM node is ``{uid, kind, number, name, quantity, source, itemId, edgeId, isNew, cut, children}`` (an added item also has ``link`` and ``linkable``):
 *
 * * ``kind`` is ``component`` (made from an EBOM node, which is its ``source``), ``added`` (an existing item picked in Fusion Manage),
 *   ``assembly`` (a new manufacturing assembly) or ``phantom`` (a new phantom assembly);
 * * ``itemId`` is the id of the item Fusion Manage holds for it ("" for one that does not exist yet) and ``edgeId`` the id of its BOM line
 *   there ("" for a line that is not in Fusion Manage yet);
 * * ``cut`` is true for a line read at the deepest level whose own lines were not read (the answer shows it has some);
 * * ``isNew`` is true for a node the user made or copied, which has no BOM line in Fusion Manage yet.
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

  /** A quantity worked out from others, which must come out as an ordinary number (no more than 6 decimals). */
  function clean(value, what) {
    const rounded = Number(value.toFixed(6));
    if (!isFinite(value) || value <= 0 || Math.abs(rounded - value) > 1e-9 * Math.max(1, Math.abs(value))) throw fail('quantity_inexact', what);
    return rounded;
  }

  /** Where a drop on a line goes, from where in the line the pointer is: the top quarter is before it, the bottom quarter after it, and the middle
   *  inside it (``canHold``); a line that cannot hold lines has only before (top half) and after. */
  function zoneOf(offsetY, height, canHold) {
    const at = height > 0 ? offsetY / height : 0.5;
    if (!canHold) return at < 0.5 ? 'before' : 'after';
    return at < 0.25 ? 'before' : at > 0.75 ? 'after' : 'into';
  }

  /** The MBOM tree as read, with each line's ``source`` set to the EBOM line with its item number (a copy; the tree given is left as it is).
   *  Where an item number is in the EBOM more than once, a line takes the one under the EBOM line its nearest mapped assembly is, then one
   *  not taken yet, then the first. A line with no item number is not mapped. */
  function mapByNumber(tree, ebom) {
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
    return map(tree, ebom.key, true);
  }

  /** A new structure. ``options.ebom``: the EBOM; ``options.mbom``: the MBOM as read (``{number, name, itemId, children}``, lines with their
   *  ``source``, see ``mapByNumber``) or none, which starts it as a copy of the EBOM; ``options.phantom``: whether the workspace can mark a
   *  phantom (Settings names the field and value). */
  function create(options) {
    const ebom = options.ebom;
    let counter = 0;
    const phantomAllowed = !!options.phantom;
    const lookup = {};   // EBOM key -> EBOM node
    (function index(node) { lookup[node.key] = node; node.children.forEach(index); })(ebom);

    function uid() { counter += 1; return 'n' + counter; }

    function fromEbom(node, deep) {
      return { uid: uid(), kind: KINDS.component, number: node.number, name: node.name, quantity: node.quantity || '1', source: node.key,
               itemId: '', edgeId: '', componentId: node.componentId || '', isNew: true, cut: false, children: deep ? node.children.map(function (c) { return fromEbom(c, true); }) : [] };
    }

    /** A node as read from Fusion Manage, field by field (not new, and no other field comes along). */
    function adopt(read, isRoot) {
      const kind = read.kind && KINDS[read.kind] ? read.kind : KINDS.component;
      return { uid: isRoot ? ROOT : uid(), kind: kind, number: String(read.number || ''), name: String(read.name || ''),
               quantity: isRoot ? '' : quantityText(read.quantity), source: String(read.source || ''), itemId: String(read.itemId || ''),
               edgeId: String(read.edgeId || ''), cut: !!read.cut, isNew: false, children: (read.children || []).map(function (c) { return adopt(c, false); }) };
    }

    function snapshot(node) { return JSON.parse(JSON.stringify(node)); }

    let mbom;
    let baseline;
    if (options.mbom) {
      mbom = adopt(Object.assign({}, options.mbom, { source: ebom.key }), true);
      baseline = snapshot(mbom);
    } else {
      mbom = { uid: ROOT, kind: KINDS.component, number: ebom.number, name: ebom.name, quantity: '', source: ebom.key, itemId: '', edgeId: '', isNew: true, cut: false,
               children: ebom.children.map(function (c) { return fromEbom(c, true); }) };
      baseline = null;   // nothing in Fusion Manage to compare with: everything is new
    }
    const past = [];
    let future = [];

    function find(id, from) {
      const node = from || mbom;
      if (node.uid === id) return node;
      for (let i = 0; i < node.children.length; i++) {
        const hit = find(id, node.children[i]);
        if (hit) return hit;
      }
      return null;
    }

    function parentOf(id, from) {
      const node = from || mbom;
      for (let i = 0; i < node.children.length; i++) {
        if (node.children[i].uid === id) return node;
        const hit = parentOf(id, node.children[i]);
        if (hit) return hit;
      }
      return null;
    }

    function contains(node, id) { return find(id, node) !== null; }

    function need(id) {
      const node = find(id);
      if (!node) throw fail('no_such_line');
      return node;
    }

    /** Can lines go under ``node``: the MBOM itself, an assembly of manufacturing's own, or a line that has lines or whose EBOM node has. */
    function holds(node) {
      if (node.uid === ROOT || node.kind === KINDS.phantom || node.kind === KINDS.assembly || node.children.length) return true;
      return !!(node.source && lookup[node.source] && lookup[node.source].children.length);
    }

    function target(id) {
      const node = need(id);
      if (!holds(node)) throw fail('not_assembly', { number: node.number });
      return node;
    }

    function usedNumbers() {
      const numbers = {};
      (function walk(node) { numbers[numberKey(node.number)] = true; node.children.forEach(walk); })(mbom);
      return numbers;
    }

    /** Run an edit as one step of the history: when it throws, the structure is as it was; when it changes nothing, there is no step. */
    function edit(change) {
      const text = JSON.stringify(mbom);   // the one copy of the tree as it was: it is parsed only to keep as a step, or to restore
      const beforeCounter = counter;
      try {
        const result = change();
        if (JSON.stringify(mbom) !== text) {
          past.push(JSON.parse(text));
          if (past.length > HISTORY) past.shift();
          future = [];
        }
        return result;
      } catch (error) {
        mbom = JSON.parse(text);
        counter = beforeCounter;
        throw error;
      }
    }

    /** ``ids`` once each, without those that sit under another of them (what an edit of the one takes the other along with), in tree order. One walk. */
    function topmost(ids) {
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
      })(mbom, false);
      if (count < wanted.size) throw fail('no_such_line');
      return found;
    }

    /** One check for every edit that puts lines already in the MBOM somewhere (``moves``: they leave their place; a copy does not). Returns
     *  ``{moving, anchor}``: the lines, once each in tree order, and the sibling to go before. A ``before`` that is not a line directly under
     *  ``parentId`` is refused; one that is moving itself becomes the next sibling that stays. */
    function guardPlacement(ids, parentId, before, moves) {
      if (!ids.length) throw fail('nothing_selected');
      const moving = topmost(ids);
      moving.forEach(function (id) {
        if (id === parentId || contains(need(id), parentId)) throw fail('inside_itself');
      });
      const parent = target(parentId);
      let anchor = before || '';
      if (anchor) {
        const at = parent.children.findIndex(function (c) { return c.uid === anchor; });
        if (at < 0) throw fail('before_not_under');
        if (moves && moving.indexOf(anchor) >= 0) {
          anchor = '';
          for (let i = at + 1; i < parent.children.length && !anchor; i++) {
            if (moving.indexOf(parent.children[i].uid) < 0) anchor = parent.children[i].uid;
          }
        }
      }
      return { moving: moving, anchor: anchor };
    }

    function detach(ids) {
      return ids.map(function (id) {
        const parent = parentOf(id);
        if (!parent) throw fail('no_such_line');
        return parent.children.splice(parent.children.findIndex(function (c) { return c.uid === id; }), 1)[0];
      });
    }

    function insert(parent, nodes, anchor) {
      let at = parent.children.length;
      if (anchor) at = parent.children.findIndex(function (c) { return c.uid === anchor; });
      parent.children.splice(at, 0, ...nodes);
    }

    /** Put new ``nodes`` under ``parentId`` before ``before``. */
    function placeNew(nodes, parentId, before) {
      const parent = target(parentId);
      if (before && !parent.children.some(function (c) { return c.uid === before; })) throw fail('before_not_under');
      insert(parent, nodes, before);
    }

    function fresh(kind, spec) {
      if (kind === KINDS.phantom && !phantomAllowed) throw fail('phantom_needs_settings');
      const number = String(spec.number || '').trim();
      if (!number) throw fail('needs_number');
      if (usedNumbers()[numberKey(number)]) throw fail('number_used', { number: number });
      return { uid: uid(), kind: kind, number: number, name: String(spec.name || '').trim(), quantity: spec.quantity ? positive(spec.quantity) : '1', source: '',
               itemId: '', edgeId: '', isNew: true, cut: false, children: [] };
    }

    function clone(node) {
      if (node.kind === KINDS.assembly || node.kind === KINDS.phantom) throw fail('copy_new_assembly', { number: node.number });
      return Object.assign({}, node, { uid: uid(), isNew: true, edgeId: '', children: node.children.map(clone) });
    }

    const api = {
      root: function () { return mbom; },
      find: function (id) { return find(id); },
      parentOf: function (id) { return parentOf(id); },
      holds: function (id) { return holds(need(id)); },

      /** The place a drop on line ``id`` means: ``zone`` is ``before``, ``after`` or ``into``; gives ``{parentId, before}``. */
      position: function (zone, id) {
        const node = need(id);
        if (zone === 'into') return { parentId: id, before: '' };
        const parent = parentOf(id);
        if (!parent) throw fail('no_place_root');
        if (zone === 'before') return { parentId: parent.uid, before: node.uid };
        if (zone !== 'after') throw fail('unknown_place', { zone: zone });
        const at = parent.children.findIndex(function (c) { return c.uid === id; });
        return { parentId: parent.uid, before: at + 1 < parent.children.length ? parent.children[at + 1].uid : '' };
      },

      /** A new manufacturing assembly (``kind`` "assembly") or phantom ("phantom") under ``parentId``; ``adopt`` lines already in the MBOM go into it. */
      createAssembly: function (kind, parentId, before, spec, adoptIds) {
        return edit(function () {
          const node = fresh(kind, spec);
          if (adoptIds && adoptIds.length) {
            const guard = guardPlacement(adoptIds, parentId, before, true);
            node.children = detach(guard.moving);
            insert(need(parentId), [node], guard.anchor);
          } else {
            placeNew([node], parentId, before);
          }
          return node.uid;
        });
      },

      /** Move lines (and what is under them) under ``parentId``, before ``before``: between assemblies and, under one, reordering. */
      move: function (ids, parentId, before) {
        edit(function () {
          const guard = guardPlacement(ids, parentId, before, true);
          insert(need(parentId), detach(guard.moving), guard.anchor);
        });
      },

      /** Copy lines (with what is under them) to another place: a component used in several places. New assemblies cannot be copied. */
      copy: function (ids, parentId, before) {
        return edit(function () {
          const guard = guardPlacement(ids, parentId, before, false);
          const copies = guard.moving.map(function (id) { return clone(need(id)); });
          insert(need(parentId), copies, guard.anchor);
          return copies.map(function (c) { return c.uid; });
        });
      },

      /** Add the EBOM nodes (``keys``) as components: just them, or with everything under them when ``deep``. */
      addFromEbom: function (keys, parentId, before, deep) {
        return edit(function () {
          const nodes = keys.map(function (key) {
            if (!lookup[key]) throw fail('no_such_ebom');
            return fromEbom(lookup[key], !!deep);
          });
          placeNew(nodes, parentId, before);
          const states = api.compare().ebom;   // a line that would hold more than the EBOM has is refused, and the tree goes back as it was
          (function check(list) {
            list.forEach(function (n) {
              if (states[n.source] && states[n.source].exceeded) throw fail('would_exceed', { number: n.number });
              check(n.children);
            });
          })(nodes);
          return nodes.map(function (n) { return n.uid; });
        });
      },

      /** Add existing Fusion Manage items (``{id, number, name, link, linkable, quantity}``) as lines. */
      addItems: function (items, parentId, before) {
        return edit(function () {
          const nodes = items.map(function (item) {
            return { uid: uid(), kind: KINDS.added, number: item.number, name: item.name || '', quantity: item.quantity ? positive(item.quantity) : '1', source: '',
                     itemId: item.id || '', edgeId: '', link: item.link || '', linkable: item.linkable || null, isNew: true, children: [] };
          });
          placeNew(nodes, parentId, before);
          return nodes.map(function (n) { return n.uid; });
        });
      },

      remove: function (ids) {
        edit(function () {
          if (!ids.length) throw fail('nothing_selected');
          detach(topmost(ids));
        });
      },

      setQuantity: function (id, value) {
        edit(function () {
          const node = need(id);
          if (id === ROOT) throw fail('root_no_quantity');
          node.quantity = positive(value);
        });
      },

      /** Split lines off an assembly into another one that is there already: ``ids`` (lines directly under ``assemblyId``, some of them and not all)
       *  go into ``targetId`` (the MBOM itself or an assembly), with their quantities scaled to how many of the target are made. A line the target has
       *  already (same item number, same kind, no lines under either) is not added twice: its quantity takes the other's, so it stays one line. */
      splitInto: function (assemblyId, ids, targetId) {
        edit(function () {
          const assembly = need(assemblyId);
          if (assemblyId === ROOT) throw fail('split_root');
          const into = target(targetId);
          if (targetId === assemblyId) throw fail('split_same');
          const wanted = new Set(ids);
          const chosen = assembly.children.filter(function (c) { return wanted.has(c.uid); });
          if (!wanted.size || wanted.size >= assembly.children.length) throw fail('split_some');
          if (chosen.length < wanted.size) throw fail('split_direct');
          if (chosen.some(function (c) { return contains(c, targetId); })) throw fail('split_inside');
          const factor = (Number(assembly.quantity) || 1) / (Number(into.quantity) || 1);
          const what = { source: assembly.number, target: into.number };
          const lines = chosen.map(function (child) { return { child: child, quantity: clean(Number(child.quantity) * factor, what) }; });
          detach(chosen.map(function (c) { return c.uid; }));
          lines.forEach(function (line) {
            const child = line.child;
            const same = into.children.find(function (c) {
              return numberKey(c.number) === numberKey(child.number) && c.kind === child.kind && !c.children.length && !child.children.length;
            });
            if (same) same.quantity = String(clean(Number(same.quantity) + line.quantity, what));
            else { child.quantity = String(line.quantity); into.children.push(child); }
          });
        });
      },

      /** Break an assembly in two: ``ids`` (lines directly under ``assemblyId``) go into a new assembly of ``kind`` next to it, with its quantity. */
      split: function (assemblyId, ids, kind, spec) {
        return edit(function () {
          const assembly = need(assemblyId);
          const parent = parentOf(assemblyId);
          if (!parent) throw fail('split_root');
          const wanted = new Set(ids);
          const chosen = assembly.children.filter(function (c) { return wanted.has(c.uid); }).map(function (c) { return c.uid; });   // once each, in the assembly's order
          if (!wanted.size || wanted.size >= assembly.children.length) throw fail('split_some');
          if (chosen.length < wanted.size) throw fail('split_direct');
          const node = fresh(kind, Object.assign({ quantity: assembly.quantity }, spec));
          node.children = detach(chosen);
          parent.children.splice(parent.children.findIndex(function (c) { return c.uid === assemblyId; }) + 1, 0, node);
          return node.uid;
        });
      },

      canUndo: function () { return past.length > 0; },
      canRedo: function () { return future.length > 0; },
      undo: function () {
        if (!past.length) return;
        future.push(snapshot(mbom));
        mbom = past.pop();
      },
      redo: function () {
        if (!future.length) return;
        past.push(snapshot(mbom));
        mbom = future.pop();
      },

      /** UIDs of the lines whose number or name holds ``text`` (any case); none for no text. */
      search: function (text) {
        const needle = numberKey(text);
        const hits = [];
        if (!needle) return hits;
        (function walk(node) {
          if (numberKey(node.number).indexOf(needle) >= 0 || numberKey(node.name).indexOf(needle) >= 0) hits.push(node.uid);
          node.children.forEach(walk);
        })(mbom);
        return hits;
      },

      /** How the MBOM stands against the EBOM. ``ebom`` has, for each EBOM key, ``{missing, quantity, exceeded, moved, matched}`` (``missing``: no MBOM line;
       *  ``quantity``: the quantities of its lines together are not the EBOM's; ``moved``: no line is under the assembly the EBOM has it in; the last
       *  two can both be true; ``matched``: its quantity is all in the MBOM and so is everything under it), and ``mbom`` each line's state (``mapped`` or ``mfg``, a line with no EBOM node). Phantoms and assemblies of
       *  manufacturing's own do not count as the parent: a line under one still has its EBOM parent. */
      compare: function () {
        const lines = {};   // EBOM key -> [{node, ancestor}]
        const mbomState = {};
        (function walk(node, ancestor) {
          node.children.forEach(function (child) {
            if (child.source) (lines[child.source] = lines[child.source] || []).push({ node: child, ancestor: ancestor });
            mbomState[child.uid] = child.source ? 'mapped' : 'mfg';
            walk(child, child.source || ancestor);
          });
        })(mbom, mbom.source);
        const ebomState = {};
        (function walk(node, parentKey) {   // gives whether every line under ``node`` is matched
          let all = true;
          node.children.forEach(function (child) {
            const held = lines[child.key] || [];
            const total = held.reduce(function (sum, h) { return sum + Number(h.node.quantity); }, 0);   // over every MBOM line made from it, in every assembly
            const state = {
              missing: !held.length,
              quantity: held.length > 0 && Math.abs(total - Number(child.quantity)) > 1e-9 * Math.max(1, Math.abs(total)),
              moved: held.length > 0 && held.every(function (h) { return h.ancestor !== parentKey; }),
            };
            state.exceeded = state.quantity && total > Number(child.quantity);   // more in the MBOM than the EBOM has (``quantity`` is true too)
            const below = walk(child, child.key);
            state.matched = !state.missing && !state.quantity && below;
            ebomState[child.key] = state;
            if (!state.matched) all = false;
          });
          return all;
        })(ebom, ebom.key);
        return { ebom: ebomState, mbom: mbomState };
      },

      /** What changed since the MBOM was read. ``changes`` maps a line's uid to its flags: ``{new}`` for a line with no BOM line yet, else any of
       *  ``moved`` (with ``oldParent``, a uid), ``quantity`` (with ``oldQuantity``) and ``reordered`` (its place among the siblings it kept
       *  changed), each independent, and ``edgeId``, the line it has in Fusion Manage. ``removed`` lists the lines of the read MBOM that are gone
       *  and whose assembly is not (``{uid, number, parent, edgeId, itemId, quantity, cascade}``): ``cascade`` counts the lines under it that went
       *  with it. With no MBOM read, every line is new. */
      changes: function () {
        const changes = {};
        const removed = [];
        const old = {};   // uid -> {node, parent, at}
        if (baseline) {
          (function walk(node) {
            node.children.forEach(function (c, at) { old[c.uid] = { node: c, parent: node.uid, at: at }; walk(c); });
          })(baseline);
        }
        (function walk(node) {
          const kept = [];   // the old places of the lines that were under this assembly before too, in the order they are now
          node.children.forEach(function (c) {
            const was = old[c.uid];
            if (!was) changes[c.uid] = { new: true };
            else {
              const flags = {};
              if (was.parent !== node.uid) { flags.moved = true; flags.oldParent = was.parent; }
              else kept.push({ uid: c.uid, at: was.at });
              if (Number(was.node.quantity) !== Number(c.quantity)) { flags.quantity = true; flags.oldQuantity = was.node.quantity; }
              if (Object.keys(flags).length) { flags.edgeId = was.node.edgeId || ''; changes[c.uid] = flags; }
            }
            walk(c);
          });
          // The lines that keep their relative order are the longest run that rises in their old places: the others were reordered.
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
          kept.forEach(function (k) {
            if (stays.has(k.uid)) return;
            changes[k.uid] = Object.assign(changes[k.uid] || { edgeId: old[k.uid].node.edgeId || '' }, { reordered: true });
          });
        })(mbom);
        const present = new Set();   // the uids in the tree now, from one walk
        (function walk(node) { node.children.forEach(function (c) { present.add(c.uid); walk(c); }); })(mbom);
        const gone = {};
        Object.keys(old).forEach(function (id) { if (!present.has(id)) gone[id] = true; });
        function count(node) { return node.children.reduce(function (sum, c) { return sum + (gone[c.uid] ? 1 + count(c) : count(c)); }, 0); }
        Object.keys(gone).forEach(function (id) {
          if (gone[old[id].parent]) return;   // it went with its assembly: that one says so
          const n = old[id].node;
          removed.push({ uid: id, number: n.number, parent: old[id].parent, edgeId: n.edgeId || '', itemId: n.itemId || '', quantity: n.quantity, cascade: count(n) });
        });
        return { changes: changes, removed: removed };
      },
    };
    return api;
  }

  ns.mbomStructure = { create: create, ebomFromRows: ebomFromRows, mapByNumber: mapByNumber, zoneOf: zoneOf, ROOT: ROOT };
})(window.MfgUi);
