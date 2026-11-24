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
 * * a BOM line number (``sequence``) is unique under its assembly and follows the tree: an assembly with a line that is new, moved in or out of order
 *   has its lines numbered 1, 2, 3 in the tree's order (a line that has its number already is left alone; a kept line is ``renumber``ed, a new one is
 *   added with its number). Where a line would take a number another still holds, the lines that change go by a number above the others first (a second
 *   ``renumber``), so no two requests ever want the same number;
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
   *  line that has none yet or takes another), ``staged`` (the passage numbers) and ``rank`` (the order the lines that go at once are sent in). */
  function numbering(root, changes) {
  // The BOM line numbers. An assembly with any line that is new, moved in or out of order is numbered 1, 2, 3 in the tree's order, so the numbers
  // are the places of the lines and Fusion Manage lists them as the tree does. A line that has its place's number already is left alone. A number is
  // unique under its assembly, so when a line is to take a number a line that stays still holds, every line that has to change goes by a number
  // above all the others first (``staged``) and then to its own: no two lines ever hold the same number in a request.
  const sequences = {};   // uid -> the number the line is given (a line that keeps its own has none here)
  const rank = {};        // uid -> when a line that goes by its own number is sent, among its assembly's
  const staged = {};      // uid -> the number it passes through on the way (only where a line would take a number another holds)
  (function assign(node) {
    const flagged = function (c) { const f = changes[c.uid]; return !!(f && (f.new || f.moved || f.reordered)); };
    if (node.children.some(flagged)) {
      const entering = function (c) { return !!(changes[c.uid] && (changes[c.uid].new || changes[c.uid].moved)); };   // no line of this assembly in Fusion Manage yet
      const moving = [];   // the lines Fusion Manage has under this assembly that take another number
      node.children.forEach(function (c, at) {
        const place = at + 1;
        if (entering(c)) sequences[c.uid] = String(place);
        else if (!String(c.sequence).trim() || numeric(c.sequence) !== place) { sequences[c.uid] = String(place); moving.push(c); }
      });
      // A line goes once the number it takes is free, so one that takes the number of another goes after it (lines shifted down by an insert go from
      // the last one up). What is left is lines that take each other's numbers: they go through a number above all the others.
      const heldBy = {};   // number -> the uid of the line that holds it now
      node.children.forEach(function (c) { if (!entering(c) && String(c.sequence).trim()) heldBy[numeric(c.sequence)] = c.uid; });
      const left = moving.slice();
      let turn = 0;
      while (left.length) {
        const at = left.findIndex(function (c) { return heldBy[numeric(sequences[c.uid])] === undefined; });
        if (at < 0) break;
        const c = left.splice(at, 1)[0];
        rank[c.uid] = turn++;
        if (String(c.sequence).trim()) delete heldBy[numeric(c.sequence)];
      }
      let above = node.children.reduce(function (high, c) { return Math.max(high, numeric(c.sequence)); }, node.children.length) + 1;
      left.forEach(function (c) { staged[c.uid] = String(above++); });
    }
    node.children.forEach(assign);
  })(root);
  return { sequences: sequences, staged: staged, rank: rank };
  }

  /** The BOM line number of every line of the structure as Fusion Manage will have it once published: ``{uid: number}``. A line the publish does not number again
   *  has the number it has now (the one Fusion Manage gave it); a new line has the one it will be added with. */
  function lineNumbers(structure, changes) {
    const root = structure.root();
    const given = numbering(root, changes.changes).sequences;
    const out = {};
    (function walk(node) { node.children.forEach(function (c) { out[c.uid] = given[c.uid] !== undefined ? given[c.uid] : String(c.sequence === undefined || c.sequence === null ? '' : c.sequence); walk(c); }); })(root);
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

    const numbers = numbering(root, changes);
    const sequences = numbers.sequences;
    const staged = numbers.staged;
    const rank = numbers.rank;

    const operations = [];
    const direct = [];   // the lines that take their number at once, with their ``rank``
    const passage = [];   // the first step of the lines that go through a number of passage
    const later = [];   // the second step of the lines that go through a number of passage: after every line was moved aside
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
            if (was) push({ op: 'remove', parent: numberOf(was.node), number: c.number, sequence: c.sequence || '', edge: flags.edgeId || '' });   // from the assembly it left
          }
          if (flags && (flags.new || flags.moved)) {
            const line = { op: 'add', parent: parent, number: c.number, quantity: c.quantity, sequence: given };
            if (c.kind === 'added') { line.link = c.link || ''; line.linkable = c.linkable || null; }   // it has its item already: only the line is added
            push(line);
          } else if (given) {   // a line of Fusion Manage's that takes another number; its new quantity goes with it, in the one request that gives its number
            const edge = (flags && flags.edgeId) || c.edgeId || '';
            const line = { op: 'renumber', parent: parent, number: c.number, from_sequence: c.sequence || '', sequence: given, edge: edge };
            if (flags && flags.quantity) line.quantity = c.quantity;
            if (staged[c.uid]) {   // by a number nobody holds first; every line has been moved aside before the first one is given its own
              passage.push({ op: 'renumber', parent: parent, number: c.number, from_sequence: c.sequence || '', sequence: staged[c.uid], edge: edge });
              line.from_sequence = staged[c.uid];
              later.push(line);
            } else {
              direct.push({ rank: rank[c.uid], line: line });
            }
          } else if (flags && flags.quantity) {
            push({ op: 'update', parent: parent, number: c.number, quantity: c.quantity, fm_quantity: flags.oldQuantity, sequence: c.sequence || '', edge: flags.edgeId || '' });
          }
        }
        walk(c);
      });
    })(root);
    direct.sort(function (x, y) { return x.rank - y.rank; }).forEach(function (d) { push(d.line); });   // sort is stable: lines of other assemblies keep their places
    passage.forEach(push);
    later.forEach(push);
    found.removed.forEach(function (r) {
      const was = nodeAt[r.parent];
      if (was) push({ op: 'remove', parent: numberOf(was.node), number: r.number, sequence: r.sequence || '', edge: r.edgeId || '' });
    });

    // An assembly in two places has one BOM in Fusion Manage: its lines have to be the same in both.
    const instances = {};   // number -> the lines under each place of it
    (function index(node) {
      node.children.forEach(function (c) {
        if (c.kind !== 'added') {
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
