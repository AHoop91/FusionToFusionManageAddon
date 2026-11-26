/**
 * Publish Item panel: what publishing does with the structure, as ``ns.mbomPlan``.
 *
 * Turns the edited MBOM (``ns.mbomStructure``, with what it changed since it was read) into the same job the publish has always sent: the
 * components whose Fusion Manage item is created or updated and the BOM operations (``add``, ``update``, ``renumber``, ``remove``), each naming its parent by
 * item number. Python is not changed: ``bom_requests`` writes the requests from these operations. Pure data, no DOM and no requests.
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

  /**
   * ``input``: ``structure`` (``ns.mbomStructure``'s), ``ebom`` (its tree), ``rows`` (every compared row of the design), ``summary`` (the design as
   * the panel reads it, with the target's item number in place of its own) and ``skipped`` (the ids of the rows that are left out of publishing, from
   * ``bomModel.buildItems``, with their item numbers: ``{id: number}``) and, when the caller has it, ``changes`` (the structure's ``changes()``, so it is not
   * worked out twice).
   * Returns ``{components, operations, problems}``.
   */
  function build(input) {
    const structure = input.structure;
    const root = structure.root();
    const rootNumber = String(input.summary.item_number || root.number || '');
    const found = input.changes || structure.changes();
    const changes = found.changes;
    const problems = [];
    function problem(kind, number) {
      let entry = problems.find(function (p) { return p.kind === kind; });
      if (!entry) { entry = { kind: kind, numbers: [] }; problems.push(entry); }
      if (number && entry.numbers.indexOf(number) < 0) entry.numbers.push(number);
    }

    const ebomAt = {};   // EBOM key -> its node
    (function index(node) { ebomAt[node.key] = node; node.children.forEach(index); })(input.ebom);
    const nodeAt = {};   // MBOM uid -> {node, parent}
    nodeAt[root.uid] = { node: root, parent: null };
    (function index(node) { node.children.forEach(function (c) { nodeAt[c.uid] = { node: c, parent: node }; index(c); }); })(root);
    function numberOf(parent) { return parent.uid === root.uid ? rootNumber : String(parent.number); }

    const identity = found.identity || {};
    const held = found.held || {};
    const seqOf = function (c) { return identity[c.uid] ? identity[c.uid].sequence : c.sequence; };
    const edgeOf = function (c) { return identity[c.uid] ? identity[c.uid].edgeId : c.edgeId; };
    const numbers = numbering(root, changes, identity);
    const sequences = numbers.sequences;
    const rank = numbers.rank;

    const operations = [];
    const direct = [];   // the lines that take their number at once, with their ``rank``
    const seen = {};
    function push(operation) {
      const id = JSON.stringify(operation);
      if (seen[id]) return;   // the same assembly in two places gives the same lines twice
      seen[id] = true;
      operations.push(operation);
    }
    (function walk(node) {
      node.children.forEach(function (c) {
        const flags = changes[c.uid];
        const given = sequences[c.uid];
        if ((flags || given) && !String(c.number).trim()) problem('skipped', c.name);   // no item number: there is no item to put in a BOM
        else if (c.kind === 'assembly' || c.kind === 'phantom') { if (flags) problem('unpublishable', c.number); }
        else if (flags || given) {
          const parent = numberOf(node);
          if (flags && flags.moved) {
            const was = nodeAt[flags.oldParent];
            if (was) push({ op: 'remove', parent: numberOf(was.node), number: c.number, sequence: seqOf(c) || '', edge: flags.edgeId || '' });   // from the assembly it left
          }
          if (flags && (flags.new || flags.moved)) {
            const there = (held[key(parent)] || {})[key(c.number)];   // the item has this line in its own bill of materials in Fusion Manage already
            if (there) {   // (a copy of an assembly that was removed and added again): it is not added a second time, only its quantity brought in step
              if (Number(there.quantity) !== Number(c.quantity)) push({ op: 'update', parent: parent, number: c.number, quantity: c.quantity, fm_quantity: there.quantity, sequence: there.sequence, edge: there.edgeId });
            } else {
              const line = { op: 'add', parent: parent, number: c.number, quantity: c.quantity, sequence: given };
              if (c.kind === 'added') { line.link = c.link || ''; line.linkable = c.linkable || null; }   // it has its item already: only the line is added
              push(line);
            }
          } else if (given) {   // a line of Fusion Manage's that takes another number; its new quantity goes with it, in the one request that gives its number
            const edge = (flags && flags.edgeId) || edgeOf(c) || '';
            const line = { op: 'renumber', parent: parent, number: c.number, from_sequence: seqOf(c) || '', sequence: given, edge: edge };
            if (flags && flags.quantity) line.quantity = c.quantity;
            direct.push({ rank: rank[c.uid], line: line });
          } else if (flags && flags.quantity) {
            push({ op: 'update', parent: parent, number: c.number, quantity: c.quantity, fm_quantity: flags.oldQuantity, sequence: seqOf(c) || '', edge: flags.edgeId || edgeOf(c) || '' });
          }
        }
        walk(c);
      });
    })(root);
    direct.sort(function (x, y) { return x.rank - y.rank; }).forEach(function (d) { push(d.line); });   // sort is stable: lines of other assemblies keep their places
    found.removed.forEach(function (r) {
      const was = nodeAt[r.parent];
      if (was) push({ op: 'remove', parent: numberOf(was.node), number: r.number, sequence: r.sequence || '', edge: r.edgeId || '' });
    });

    // An assembly in two places has one BOM in Fusion Manage: its lines have to be the same in both.
    const instances = {};   // number -> the lines under each place of it
    (function index(node) {
      node.children.forEach(function (c) {
        if (c.kind !== 'added' && !(changes[c.uid] && changes[c.uid].new && !c.children.length)) {   // a new line with no lines is another use of an item (a split, a shallow add): its lines are the item's own, not a second BOM
          (instances[key(c.number)] = instances[key(c.number)] || []).push(c.children.map(function (k) { return key(k.number) + '|' + Number(k.quantity); }).join(','));
        }
        index(c);
      });
    })(root);
    operations.forEach(function (o) {
      const lines = instances[key(o.parent)] || [];
      if (lines.some(function (l) { return l !== lines[0]; })) problem('ambiguous', o.parent);
    });

    // The components: the design, then each EBOM component a line was made from, once.
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
          if (Object.prototype.hasOwnProperty.call(input.skipped, id)) problem('skipped', input.skipped[id] || c.number);
          else if (rowById[id]) components.push(ns.bomModel.lineComponent(rowById[id]));
        }
        collect(c);
      });
    })(root);
    const phase = { remove: 0, renumber: 1 };
    operations.sort(function (x, y) { return (x.op in phase ? phase[x.op] : 2) - (y.op in phase ? phase[y.op] : 2); });   // a line is freed, then moved, before another takes its number (stable)
    return { components: components, operations: operations, problems: problems };
  }

  ns.mbomPlan = { build: build, lineNumbers: lineNumbers };
})(window.MfgUi);
