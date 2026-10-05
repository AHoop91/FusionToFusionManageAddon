/**
 * Publish Item panel: the data side of the Bill of Materials, as ``ns.bomModel``.
 *
 * Turns the compared rows (design rows compared with Fusion Manage) into the lines the table
 * draws, applies the user's choices for lines whose item numbers differ, and says which
 * filters a line belongs to. Drawing is bom-table.js.
 *
 * Fusion Manage extends the design BOM, so lines only it has are kept. When the item number
 * differs at one position, the design line and the Fusion Manage line share an item and the
 * user picks an action for it.
 */
(function (ns) {
  'use strict';

  // What the user chose for each line whose item numbers differ: 'remove' (the Fusion Manage line goes,
  // the design line is added) or 'add' (keep both). Keyed "design number|Fusion Manage number|n"
  // (see ``buildItems``), so a choice survives a redraw. Publishing will read it.
  const decisions = {};

  // Fusion Manage items the user picked with Add Items: lines of the Fusion Manage BOM that publishing adds
  // under the design, at the end. Each is { id, link, number, name, quantity }.
  const staged = [];
  const DEFAULT_QUANTITY = '1';

  function clearDecisions() {
    Object.keys(decisions).forEach(function (k) { delete decisions[k]; });
    staged.length = 0;
  }

  /** Add the picked items (those not staged already) as lines at the end of the Bill of Materials. */
  function stage(picked) {
    picked.forEach(function (p) {
      if (staged.some(function (s) { return s.id === p.id; })) return;
      staged.push({ id: p.id, link: p.link, linkable: p.linkable || null, number: p.number, name: p.name, quantity: DEFAULT_QUANTITY });
    });
  }

  function unstage(id) {
    const at = staged.findIndex(function (s) { return s.id === id; });
    if (at >= 0) staged.splice(at, 1);
  }

  /** Set the quantity of a picked line; returns the quantity now held (unchanged when ``value`` is not a positive number). */
  function setStagedQuantity(id, value) {
    const line = staged.find(function (s) { return s.id === id; });
    if (!line) return '';
    const n = Number(String(value).trim());
    if (isFinite(n) && n > 0) line.quantity = String(n);
    return line.quantity;
  }

  function stagedIds() {
    return staged.map(function (s) { return s.id; });
  }

  /** The component a line stands for, in the form publish.js opens: the design itself, or a BOM line. */
  function rootComponent(root) {
    return { id: root.component_id || '', root: true, item_number: root.item_number, part_number: root.part_number, description: root.description,
             title: [root.part_number, root.description].filter(Boolean).join(' - ') || 'This design' };
  }

  function lineComponent(r) {
    return { id: r.id, root: false, item_number: r.item_number, part_number: r.part_number, description: r.description, name: r.name, thumbnail: r.thumbnail || '',
             title: [r.part_number, r.name].filter(Boolean).join(' - ') };
  }

  /**
   * Lines to draw: the open design first, then each compared row. A Fusion Manage line that
   * sits beside a design line with another item number is folded into that design line.
   */
  function buildItems(rows, root) {
    const rootName = root.description || '';
    const rootPn = root.part_number || root.item_number || '';
    const items = [{ level: 0, root: true, sequence: '', status: 'root', hidden: false, component: rootComponent(root),
                     design: { pn: rootPn, name: rootName || (rootPn ? '' : 'This design'), quantity: '', sequence: '' },
                     fm: { pn: rootPn, name: rootName, quantity: '', sequence: '' } }];
    const repeats = {};
    let held = null;   // paired Fusion Manage line waiting for its design line, which follows it
    function side(r, quantity, edge) {
      return { pn: r.part_number, name: r.name, quantity: String(quantity), sequence: String(r.sequence), edge: edge || '' };
    }
    rows.forEach(function (r) {
      if (r.status === 'extra' && r.pair) { held = r; return; }
      if (r.status === 'extra') {
        items.push({ level: r.level + 1, root: false, sequence: String(r.sequence), status: 'extra', hidden: false, design: side(r, ''), fm: side(r, r.quantity, r.edge_id) });
        return;
      }
      const item = { level: r.level + 1, root: false, sequence: String(r.sequence), status: r.status || 'unchecked', hidden: !!r.hidden, component: lineComponent(r),
                     design: side(r, r.quantity), fm: side(r, r.status === 'match' ? r.quantity : r.fm_quantity || '', r.fm_edge_id) };
      if (held && held.pair === String(r.item_number || r.part_number)) {
        item.status = 'mismatch';
        item.fm = side(held, held.quantity, held.edge_id);
        // Repeats of the same pair of numbers get their own choice: "design|Fusion Manage|n", n counting the repeats.
        const base = item.design.pn + '|' + item.fm.pn;
        repeats[base] = (repeats[base] || 0) + 1;
        item.key = base + '|' + repeats[base];
      }
      held = null;
      items.push(item);
    });
    // Picked Fusion Manage items go last, numbered after the highest line directly under the design.
    let highest = 0;
    items.forEach(function (item) { if (item.level === 1) highest = Math.max(highest, parseInt(item.sequence, 10) || 0); });
    staged.forEach(function (s, i) {
      const number = String(highest + 1 + i);
      items.push({ level: 1, root: false, sequence: number, status: 'linked', hidden: false, stagedId: s.id, link: s.link, linkable: s.linkable,
                   design: { pn: '', name: '', quantity: '', sequence: '' },
                   fm: { pn: s.number, name: s.name, quantity: s.quantity, sequence: number } });
    });
    return items;
  }

  /**
   * Apply the "keep both" choices: the design line stays where it is, and the Fusion Manage line it was
   * paired with is renumbered (highest sibling sequence + 1) and moves to the end of the parent's lines.
   */
  function arrange(items) {
    const out = items.slice();
    for (let i = 0; i < out.length; i++) {
      const item = out[i];
      if (item.status !== 'mismatch' || decisions[item.key] !== 'add') continue;
      out[i] = Object.assign({}, item, { status: 'added' });
      let parent = i - 1;
      while (out[parent].level >= item.level) parent--;
      let last = parent + 1;
      while (last < out.length && out[last].level > out[parent].level) last++;
      let highest = 0;
      for (let k = parent + 1; k < last; k++) {
        if (out[k].level === item.level) highest = Math.max(highest, parseInt(out[k].sequence, 10) || 0);
      }
      const number = String(highest + 1);
      out.splice(last, 0, Object.assign({}, item, { status: 'kept', hidden: false, sequence: number, fm: Object.assign({}, item.fm, { sequence: number }) }));
    }
    return out;
  }

  /**
   * The filters a line belongs to. "review" is a differing pair still waiting for a choice; "new" also takes
   * the design line of a pair and a line added by "keep both"; "hidden" is a component hidden in Fusion.
   */
  function groupsOf(item) {
    let groups;
    switch (item.status) {
      case 'mismatch': groups = decisions[item.key] ? ['new', 'extra'] : ['new', 'review', 'extra']; break;   // its Fusion Manage line is only in Fusion Manage
      case 'added': groups = ['new']; break;
      case 'linked': groups = ['added']; break;   // picked with Add Items
      case 'kept': groups = ['extra']; break;
      case 'root': groups = []; break;
      default: groups = [item.status];
    }
    return item.hidden && !item.root ? groups.concat('hidden') : groups;
  }

  /** How many differing pairs still wait for a choice (the lines the Review filter shows). */
  function pendingReviews(items) {
    return items.filter(function (item) { return item.status === 'mismatch' && !decisions[item.key]; }).length;
  }

  /**
   * What publishing does: the components whose Fusion Manage item is created or updated (the design and every
   * line that is new, or the design side of a differing pair) and the BOM operations (add, update the quantity,
   * remove, renumber a kept line), each naming its parent by item number. Fusion Manage only lines with no
   * choice are left alone.
   */
  function publishPlan(rows, root) {
    const base = buildItems(rows, root);
    const items = arrange(base);
    const oldSequence = {};
    base.forEach(function (item) { if (item.key) oldSequence[item.key] = item.fm.sequence; });
    const numberAt = [];   // item number of the latest line on each level, so a line finds its parent
    const components = [];
    const seen = {};
    const operations = [];
    items.forEach(function (item) {
      const own = item.component ? String(item.component.item_number || item.design.pn || '') : String(item.fm.pn || '');
      const parent = item.level > 0 ? numberAt[item.level - 1] || '' : '';
      numberAt[item.level] = own;
      if (item.root) { components.push(Object.assign({}, item.component, { root: true })); return; }
      const line = { parent: parent, number: own, quantity: item.design.quantity, sequence: item.design.sequence };
      switch (item.status) {
        case 'new': case 'added': operations.push(Object.assign({ op: 'add' }, line)); break;
        case 'mismatch':   // only a pair that chose 'remove' is still a mismatch here
          operations.push(Object.assign({ op: 'add' }, line));
          operations.push({ op: 'remove', parent: parent, number: item.fm.pn, sequence: item.fm.sequence, edge: item.fm.edge });
          break;
        case 'linked':   // an existing Fusion Manage item: only the BOM line is added, never the item
          operations.push({ op: 'add', parent: parent, number: own, quantity: item.fm.quantity, sequence: item.fm.sequence, link: item.link, linkable: item.linkable });
          break;
        case 'changed': operations.push(Object.assign({ op: 'update', fm_quantity: item.fm.quantity, edge: item.fm.edge }, line)); break;
        case 'kept':
          operations.push({ op: 'renumber', parent: parent, number: item.fm.pn, from_sequence: oldSequence[item.key], sequence: item.sequence, edge: item.fm.edge });
          break;
        default: break;
      }
      const creates = item.status === 'new' || item.status === 'added' || item.status === 'mismatch';
      if (creates && item.component && item.component.id && !seen[item.component.id]) {
        seen[item.component.id] = true;
        components.push(item.component);
      }
    });
    return { components: components, operations: operations };
  }

  ns.bomModel = {
    decisions: decisions, clearDecisions: clearDecisions, stage: stage, unstage: unstage, setStagedQuantity: setStagedQuantity, stagedIds: stagedIds, rootComponent: rootComponent,
    buildItems: buildItems, arrange: arrange, groupsOf: groupsOf, pendingReviews: pendingReviews, publishPlan: publishPlan,
  };
})(window.MfgUi);
