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
 * * a BOM line number (``sequence``) is unique under its assembly and follows the tree: lines of an assembly with nothing in Fusion Manage are
 *   numbered 1, 2, 3; under one that has some, the lines up to the first that is new, moved in or out of order keep their numbers, and that line and
 *   every one after it get numbers above the highest the assembly has had (a kept line is ``renumber``ed, a new one is added with its number), so
 *   Fusion Manage lists them in the tree's order and no two requests ever want the same number;
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

    // The BOM line numbers. Under an assembly, the lines up to the first one that is new, moved in or out of order keep their numbers; that line and
    // every one after it is given a number above the highest the assembly has had, in tree order: so Fusion Manage lists them as the tree does, and no
    // number is taken that another line holds now, held a moment ago (a line the same publish removes or moves away) or is given.
    const freed = {};   // assembly uid -> the numbers of its lines this publish removes or moves away (they go while the new ones come: not to be taken)
    function noteFreed(uid, sequence) { (freed[uid] = freed[uid] || {})[numeric(sequence)] = true; }
    found.removed.forEach(function (r) { noteFreed(r.parent, r.sequence); });
    Object.keys(changes).forEach(function (uid) { if (changes[uid].moved && nodeAt[uid]) noteFreed(changes[uid].oldParent, nodeAt[uid].node.sequence); });
    const sequences = {};   // uid -> the number the line is given (a line that keeps its own has none here)
    (function assign(node) {
      const flagged = function (c) { const f = changes[c.uid]; return !!(f && (f.new || f.moved || f.reordered)); };
      const from = node.children.findIndex(flagged);
      if (from >= 0) {
        let next = node.children.reduce(function (high, c) { return changes[c.uid] && (changes[c.uid].new || changes[c.uid].moved) ? high : Math.max(high, numeric(c.sequence)); }, 0) + 1;
        node.children.slice(from).forEach(function (c) {
          while ((freed[node.uid] || {})[next]) next++;
          sequences[c.uid] = String(next++);
        });
      }
      node.children.forEach(assign);
    })(root);

    const operations = [];
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
          } else if (given) {   // a line of Fusion Manage's that takes another number; its new quantity goes with it, in the one request
            const line = { op: 'renumber', parent: parent, number: c.number, from_sequence: c.sequence || '', sequence: given, edge: (flags && flags.edgeId) || c.edgeId || '' };
            if (flags && flags.quantity) line.quantity = c.quantity;
            push(line);
          } else if (flags && flags.quantity) {
            push({ op: 'update', parent: parent, number: c.number, quantity: c.quantity, fm_quantity: flags.oldQuantity, sequence: c.sequence || '', edge: flags.edgeId || '' });
          }
        }
        walk(c);
      });
    })(root);
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
    operations.sort(function (x, y) { return (x.op === 'remove' ? 0 : 1) - (y.op === 'remove' ? 0 : 1); });   // a line is freed before another takes its number (stable)
    return { components: components, operations: operations, problems: problems };
  }

  ns.mbomPlan = { build: build };
})(window.MfgUi);
