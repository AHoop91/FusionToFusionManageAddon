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

  function clearDecisions() {
    Object.keys(decisions).forEach(function (k) { delete decisions[k]; });
  }

  /** The component a line stands for, in the form publish.js opens: the design itself, or a BOM line. */
  function rootComponent(root) {
    return { id: root.component_id || '', root: true, item_number: root.item_number, part_number: root.part_number, description: root.description,
             title: [root.part_number, root.description].filter(Boolean).join(' - ') || 'This design' };
  }

  function lineComponent(r) {
    return { id: r.id, root: false, item_number: r.item_number, part_number: r.part_number, description: r.description,
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
    function side(r, quantity) {
      return { pn: r.part_number, name: r.name, quantity: String(quantity), sequence: String(r.sequence) };
    }
    rows.forEach(function (r) {
      if (r.status === 'extra' && r.pair) { held = r; return; }
      if (r.status === 'extra') {
        items.push({ level: r.level + 1, root: false, sequence: String(r.sequence), status: 'extra', hidden: false, design: side(r, ''), fm: side(r, r.quantity) });
        return;
      }
      const item = { level: r.level + 1, root: false, sequence: String(r.sequence), status: r.status || 'unchecked', hidden: !!r.hidden, component: lineComponent(r),
                     design: side(r, r.quantity), fm: side(r, r.status === 'match' ? r.quantity : r.fm_quantity || '') };
      if (held && held.pair === String(r.item_number || r.part_number)) {
        item.status = 'mismatch';
        item.fm = side(held, held.quantity);
        // Repeats of the same pair of numbers get their own choice: "design|Fusion Manage|n", n counting the repeats.
        const base = item.design.pn + '|' + item.fm.pn;
        repeats[base] = (repeats[base] || 0) + 1;
        item.key = base + '|' + repeats[base];
      }
      held = null;
      items.push(item);
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
      case 'kept': groups = ['extra']; break;
      case 'root': groups = []; break;
      default: groups = [item.status];
    }
    return item.hidden && !item.root ? groups.concat('hidden') : groups;
  }

  ns.bomModel = {
    decisions: decisions, clearDecisions: clearDecisions, rootComponent: rootComponent,
    buildItems: buildItems, arrange: arrange, groupsOf: groupsOf,
  };
})(window.MfgUi);
