/**
 * Publish Item panel: what publishing does with the structure, as ``ns.mbomPlan``.
 *
 * Turns the edited MBOM (``ns.mbomStructure``, with what it changed since it was read) into the same job the publish has always sent: the
 * components whose Fusion Manage item is created or updated and the BOM operations (``add``, ``update``, ``renumber``, ``remove``), each naming its parent by
 * item number. Python is not changed: ``bom_requests`` writes the requests from these operations. Pure data, no DOM and no requests. Layer: domain.
 *
 * What it does with the structure:
 * * a line the user added or moved is added under its assembly; a moved line is also removed from the one it left;
 * * a line whose quantity changed is updated; a line that is gone is removed (its own lines stay in its item, which is left alone);
 * * the components are the design (the root) and every line made from an EBOM component (``source``), once each: all go through the comparison
 *   with Fusion Manage, so an item whose properties differ is updated. An added item (a bought version, or one picked in Fusion Manage) is never one
 *   of them: it exists already;
 * * a BOM line number (``sequence``) is unique under its assembly and follows the tree: an assembly with a line that is new, moved in or out of order (or one the user asked to renumber)
 *   has its lines numbered 1, 2, 3 in the tree's order (one that has a line given a number by the user keeps the numbers it has, and that line its own); (a line that has its number already is left alone; a kept line is ``renumber``ed, a new one is
 *   added with its number). A line goes straight to its number, one ``renumber`` each: Fusion Manage lets two lines hold a number for a moment, so
 *   no line has to wait for another or pass through a number of passage;
 *
 * What it will not publish, it says in ``problems`` (``{kind, numbers}``) and the panel refuses the publish, so no edit is dropped quietly:
 * ``unpublishable`` (a line with no item behind it, such as a new manufacturing assembly),
 * ``skipped`` (a component with no item number or one that Fusion Manage shares with another) and ``ambiguous`` (an assembly in two places
 * with different lines, which have the one BOM in Fusion Manage).
 */
(function (ns) {
  'use strict';

  function key(text) { return String(text === undefined || text === null ? '' : text).trim().toLowerCase(); }

  function numeric(text) {
    const n = parseInt(String(text), 10);
    return isFinite(n) ? n : 0;
  }

  /** The numbers the lines of the assembly tree under ``root`` are given (``changes`` is the structure's ``changes().changes``): ``sequences`` (uid -> number, for each
   *  line that has none yet or takes another) and ``rank`` (the order the lines are listed in). */
  function numbering(root, changes, identity) {
  const seqOf = function (c) { return identity[c.uid] ? identity[c.uid].sequence : c.sequence; };   // a line added again has the number of the line it replaces
  // The BOM line numbers. An assembly with any line that is new, moved in or out of order is numbered 1, 2, 3 in the tree's order, so the numbers
  // are the places of the lines and Fusion Manage lists them as the tree does. A line that has its place's number already is left alone. An assembly
  // with a line the user gave a number to (``pin``) keeps the numbers it has instead, each above the one before it: a line takes its own number, else the one it
  // has when that is above the one before, else the one above the one before. Fusion Manage accepts two lines with one number, so each line that changes
  // takes its number in one request, whatever order the requests arrive in.
  const sequences = {};   // uid -> the number the line is given (a line that keeps its own has none here)
  const rank = {};        // uid -> when a line that goes by its own number is sent, among its assembly's
  (function assign(node) {
    const flagged = function (c) { const f = changes[c.uid]; return !!(f && (f.new || f.moved || f.reordered)); };
    const pinned = function (c) { return c.pin !== undefined && c.pin !== ''; };
    const keeps = !node.renumber && node.children.some(pinned);
    if (node.renumber || keeps || node.children.some(flagged)) {   // ``renumber``: the user asked for the lines of this assembly to be numbered again
      const entering = function (c) { return !!(changes[c.uid] && (changes[c.uid].new || changes[c.uid].moved)); };   // no line of this assembly in Fusion Manage yet
      const given = {};   // uid -> the number it ends with
      const moving = [];   // the lines Fusion Manage has under this assembly that take another number
      let previous = 0;
      node.children.forEach(function (c, at) {
        let number = at + 1;
        if (keeps) {
          if (pinned(c)) number = Math.max(Number(c.pin), previous + 1);
          else if (!entering(c) && String(seqOf(c)).trim() && numeric(seqOf(c)) > previous) number = numeric(seqOf(c));
          else number = previous + 1;
        }
        previous = number;
        given[c.uid] = number;
        if (entering(c)) sequences[c.uid] = String(number);
        else if (!String(seqOf(c)).trim() || numeric(seqOf(c)) !== number) { sequences[c.uid] = String(number); moving.push(c); }
      });
      // Listed so that a line goes once the number it takes is free where that can be (lines shifted down by an insert from the last one up); the order
      // does not matter to Fusion Manage, it only keeps the requests easy to read.
      const heldBy = {};   // number -> the uid of the line that holds it now
      node.children.forEach(function (c) { if (!entering(c) && String(seqOf(c)).trim()) heldBy[numeric(seqOf(c))] = c.uid; });
      const left = moving.slice();
      let turn = 0;
      while (left.length) {
        const at = left.findIndex(function (c) { return heldBy[numeric(sequences[c.uid])] === undefined; });
        if (at < 0) break;
        const c = left.splice(at, 1)[0];
        rank[c.uid] = turn++;
        if (String(seqOf(c)).trim()) delete heldBy[numeric(seqOf(c))];
      }
      left.forEach(function (c) { rank[c.uid] = turn++; });   // lines that take each other's numbers
    }
    node.children.forEach(assign);
  })(root);
  return { sequences: sequences, rank: rank };
  }

  /** The BOM line number of every line of the structure as Fusion Manage will have it once published: ``{uid: number}``. A line the publish does not number again
   *  has the number it has now (the one Fusion Manage gave it); a new line has the one it will be added with. */
  function lineNumbers(structure, changes) {
    const root = structure.root();
    const identity = changes.identity || {};
    const given = numbering(root, changes.changes, identity).sequences;
    const out = {};
    (function walk(node) { node.children.forEach(function (c) { out[c.uid] = given[c.uid] !== undefined ? given[c.uid] : String(identity[c.uid] ? identity[c.uid].sequence : c.sequence === undefined || c.sequence === null ? '' : c.sequence); walk(c); }); })(root);
    return out;
  }

  /** The line number a line has in Fusion Manage now: the one of the line it replaces when it was added again, else its own. */
  function sequenceOf(identity, c) { return identity[c.uid] ? identity[c.uid].sequence : c.sequence; }

  /** The edge id a line has in Fusion Manage now: the one of the line it replaces when it was added again, else its own. */
  function edgeIdOf(identity, c) { return identity[c.uid] ? identity[c.uid].edgeId : c.edgeId; }

  /** Note a problem of ``kind`` (once per kind) with the item number or name it is about (once each). */
  function addProblem(problems, kind, number) {
    let entry = problems.find(function (p) { return p.kind === kind; });
    if (!entry) { entry = { kind: kind, numbers: [] }; problems.push(entry); }
    if (number && entry.numbers.indexOf(number) < 0) entry.numbers.push(number);
  }

  /** EBOM key -> its node. */
  function indexEbom(ebom) {
    const ebomAt = {};
    (function index(node) { ebomAt[node.key] = node; node.children.forEach(index); })(ebom);
    return ebomAt;
  }

  /** MBOM uid -> {node, parent}. */
  function indexMbom(root) {
    const nodeAt = {};
    nodeAt[root.uid] = { node: root, parent: null };
    (function index(node) { node.children.forEach(function (c) { nodeAt[c.uid] = { node: c, parent: node }; index(c); }); })(root);
    return nodeAt;
  }

  /** The state the plan is built in: the structure's changes, the numbering, and the operations and problems found so far. */
  function makeContext(input) {
    const root = input.structure.root();
    const found = input.changes || input.structure.changes();
    const identity = found.identity || {};
    const numbers = numbering(root, found.changes, identity);
    return {
      root: root, rootNumber: String(input.summary.item_number || root.number || ''),
      found: found, changes: found.changes, identity: identity, held: found.held || {},
      sequences: numbers.sequences, rank: numbers.rank, nodeAt: indexMbom(root),
      operations: [], direct: [],   // direct: the lines that take their number at once, with their ``rank``
      seen: {}, problems: [],
    };
  }

  function numberOfParent(ctx, parent) { return parent.uid === ctx.root.uid ? ctx.rootNumber : String(parent.number); }

  function pushOperation(ctx, operation) {
    const id = JSON.stringify(operation);
    if (ctx.seen[id]) return;   // the same assembly in two places gives the same lines twice
    ctx.seen[id] = true;
    ctx.operations.push(operation);
  }

  /** A moved line is removed from the assembly it left. */
  function planLeftAssembly(ctx, c, flags) {
    const was = ctx.nodeAt[flags.oldParent];
    if (!was) return;
    pushOperation(ctx, { op: 'remove', parent: numberOfParent(ctx, was.node), number: c.number, sequence: sequenceOf(ctx.identity, c) || '', edge: flags.edgeId || '' });
  }

  /** A line the user added or moved in: added under its assembly, unless the item has it in its own bill of materials already. */
  function planEnteringLine(ctx, c, parent, given) {
    const there = (ctx.held[key(parent)] || {})[key(c.number)];   // the item has this line in its own bill of materials in Fusion Manage already
    if (there) {   // (a copy of an assembly that was removed and added again): it is not added a second time, only its quantity brought in step
      if (Number(there.quantity) !== Number(c.quantity)) pushOperation(ctx, { op: 'update', parent: parent, number: c.number, quantity: c.quantity, fm_quantity: there.quantity, sequence: there.sequence, edge: there.edgeId });
      return;
    }
    const line = { op: 'add', parent: parent, number: c.number, quantity: c.quantity, sequence: given };
    if (c.kind === 'added') { line.link = c.link || ''; line.linkable = c.linkable || null; }   // it has its item already: only the line is added
    pushOperation(ctx, line);
  }

  /** A line of Fusion Manage's that takes another number; its new quantity goes with it, in the one request that gives its number. */
  function planRenumberedLine(ctx, c, parent) {
    const flags = ctx.changes[c.uid];
    const given = ctx.sequences[c.uid];
    const edge = (flags && flags.edgeId) || edgeIdOf(ctx.identity, c) || '';
    const line = { op: 'renumber', parent: parent, number: c.number, from_sequence: sequenceOf(ctx.identity, c) || '', sequence: given, edge: edge };
    if (flags && flags.quantity) line.quantity = c.quantity;
    ctx.direct.push({ rank: ctx.rank[c.uid], line: line });
  }

  function planQuantityUpdate(ctx, c, parent, flags) {
    pushOperation(ctx, { op: 'update', parent: parent, number: c.number, quantity: c.quantity, fm_quantity: flags.oldQuantity, sequence: sequenceOf(ctx.identity, c) || '', edge: flags.edgeId || edgeIdOf(ctx.identity, c) || '' });
  }

  /** A component line with an item number that the user changed or that takes another number. */
  function planChangedLine(ctx, node, c) {
    const flags = ctx.changes[c.uid];
    const given = ctx.sequences[c.uid];
    const parent = numberOfParent(ctx, node);
    if (flags && flags.moved) planLeftAssembly(ctx, c, flags);
    if (flags && (flags.new || flags.moved)) planEnteringLine(ctx, c, parent, given);
    else if (given) planRenumberedLine(ctx, c, parent);
    else if (flags && flags.quantity) planQuantityUpdate(ctx, c, parent, flags);
  }

  /** The operations for one line of ``node``, or the problem that stops it being published. */
  function planLine(ctx, node, c) {
    const flags = ctx.changes[c.uid];
    const given = ctx.sequences[c.uid];
    if ((flags || given) && !String(c.number).trim()) addProblem(ctx.problems, 'skipped', c.name);   // no item number: there is no item to put in a BOM
    else if (c.kind === 'assembly' || c.kind === 'phantom') { if (flags) addProblem(ctx.problems, 'unpublishable', c.number); }
    else if (flags || given) planChangedLine(ctx, node, c);
  }

  /** The operations for every line of the tree, then the lines that were removed. */
  function planOperations(ctx) {
    (function walk(node) {
      node.children.forEach(function (c) {
        planLine(ctx, node, c);
        walk(c);
      });
    })(ctx.root);
    ctx.direct.sort(function (x, y) { return x.rank - y.rank; }).forEach(function (d) { pushOperation(ctx, d.line); });   // sort is stable: lines of other assemblies keep their places
    ctx.found.removed.forEach(function (r) {
      const was = ctx.nodeAt[r.parent];
      if (was) pushOperation(ctx, { op: 'remove', parent: numberOfParent(ctx, was.node), number: r.number, sequence: r.sequence || '', edge: r.edgeId || '' });
    });
  }

  /** An assembly in two places has one BOM in Fusion Manage: its lines have to be the same in both. */
  function checkAmbiguousAssemblies(ctx) {
    const changes = ctx.changes;
    const instances = {};   // number -> the lines under each place of it
    (function index(node) {
      node.children.forEach(function (c) {
        if (c.kind !== 'added' && !(changes[c.uid] && changes[c.uid].new && !c.children.length)) {   // a new line with no lines is another use of an item (a split, a shallow add): its lines are the item's own, not a second BOM
          (instances[key(c.number)] = instances[key(c.number)] || []).push(c.children.map(function (k) { return key(k.number) + '|' + Number(k.quantity); }).join(','));
        }
        index(c);
      });
    })(ctx.root);
    ctx.operations.forEach(function (o) {
      const lines = instances[key(o.parent)] || [];
      if (lines.some(function (l) { return l !== lines[0]; })) addProblem(ctx.problems, 'ambiguous', o.parent);
    });
  }

  /** The components: the design, then each EBOM component a line was made from, once. */
  function collectComponents(ctx, input) {
    const ebomAt = indexEbom(input.ebom);
    const rowById = {};
    input.rows.forEach(function (r) { if (r.id && !rowById[r.id]) rowById[r.id] = r; });
    const components = [ns.bomModel.rootComponent(input.summary)];
    const taken = {};
    (function collect(node) {
      node.children.forEach(function (c) {
        const from = c.kind === 'component' && c.source && !c.bought ? ebomAt[c.source] : null;   // a bought version stands for its EBOM line: that component is not published for it
        const id = from ? from.componentId : '';
        if (id && !taken[id]) {
          taken[id] = true;
          if (Object.prototype.hasOwnProperty.call(input.skipped, id)) addProblem(ctx.problems, 'skipped', input.skipped[id] || c.number);
          else if (rowById[id]) components.push(ns.bomModel.lineComponent(rowById[id]));
        }
        collect(c);
      });
    })(ctx.root);
    return components;
  }

  /** Remove first, then renumber, then the rest: a line is freed, then moved, before another takes its number (the sort is stable). */
  function sortByPhase(operations) {
    const phase = { remove: 0, renumber: 1 };
    operations.sort(function (x, y) { return (x.op in phase ? phase[x.op] : 2) - (y.op in phase ? phase[y.op] : 2); });
  }

  /**
   * ``input``: ``structure`` (``ns.mbomStructure``'s), ``ebom`` (its tree), ``rows`` (every compared row of the design), ``summary`` (the design as
   * the panel reads it, with the target's item number in place of its own) and ``skipped`` (the ids of the rows that are left out of publishing, from
   * ``bomModel.buildItems``, with their item numbers: ``{id: number}``) and, when the caller has it, ``changes`` (the structure's ``changes()``, so it is not
   * worked out twice).
   * Returns ``{components, operations, problems}``.
   */
  function build(input) {
    const ctx = makeContext(input);
    planOperations(ctx);
    checkAmbiguousAssemblies(ctx);
    const components = collectComponents(ctx, input);
    sortByPhase(ctx.operations);
    return { components: components, operations: ctx.operations, problems: ctx.problems };
  }

  ns.mbomPlan = { build: build, lineNumbers: lineNumbers };
})(window.MfgUi);
