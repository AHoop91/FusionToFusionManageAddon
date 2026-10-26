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
  // the design line is added) or 'add' (keep both). Keyed by where the line sits and its two numbers
  // (see ``buildItems``), so a choice survives a redraw and lines read later. Publishing reads it.
  const decisions = {};

  // Fusion Manage items the user picked with Add Items: lines of the Fusion Manage BOM that publishing adds
  // under the design, at the end. Each is { id, link, number, name, quantity }.
  const staged = [];
  const DEFAULT_QUANTITY = '1';

  // Quantities the user typed over a line's own, keyed by ``item.qkey`` (see ``buildItems``).
  const quantities = {};
  const EDITABLE = ['match', 'new', 'changed', 'added', 'mismatch', 'extra', 'uncompared'];

  /** A quantity the way Fusion writes it: Fusion Manage's "1.0" and "2.50" read "1" and "2.5". Anything that is not a number is left as it is. */
  function plainQuantity(value) {
    const text = String(value === undefined || value === null ? '' : value).trim();
    const n = Number(text);
    return text !== '' && isFinite(n) ? String(n) : text;
  }

  function clearDecisions() {
    Object.keys(decisions).forEach(function (k) { delete decisions[k]; });
    Object.keys(quantities).forEach(function (k) { delete quantities[k]; });
    staged.length = 0;
  }

  /** The quantity a line has before any edit: the design's, or Fusion Manage's for a line only it has. */
  function baseQuantity(item) {
    return item.status === 'extra' ? item.fm.quantity : item.design.quantity;
  }

  /** Quantity a line can be edited on (a picked line has its own box). */
  function canEditQuantity(item) {
    return EDITABLE.includes(item.status) && !!item.qkey;
  }

  /** The quantity a line will have once published. */
  function quantityOf(item) {
    const typed = quantities[item.qkey];
    return typed === undefined ? baseQuantity(item) : typed;
  }

  /** ``value`` as a number above 0, or null when it is not one. */
  function positive(value) {
    const n = Number(String(value).trim());
    return isFinite(n) && n > 0 ? n : null;
  }

  /** Set a line's quantity; returns the quantity now held (unchanged when ``value`` is not a positive number). */
  function setQuantity(item, value) {
    const n = positive(value);
    if (n !== null) {
      if (n === Number(baseQuantity(item))) delete quantities[item.qkey]; else quantities[item.qkey] = String(n);
    }
    return quantityOf(item);
  }

  /** Has the user typed a quantity over the line's own? */
  function quantityEdited(item) {
    return quantities[item.qkey] !== undefined;
  }

  function revertQuantity(item) {
    delete quantities[item.qkey];
  }

  /** A line in both the design and Fusion Manage whose quantity to publish is not Fusion Manage's. */
  function quantityDiffers(item) {
    return ['match', 'changed', 'extra'].includes(item.status) && Number(quantityOf(item)) !== Number(item.fm.quantity);
  }

  /** The status a line shows: a match edited to another quantity updates, an update edited back to Fusion Manage's matches. */
  function statusOf(item) {
    if (item.status === 'match' && quantityDiffers(item)) return 'changed';
    if (item.status === 'changed' && !quantityDiffers(item)) return 'match';
    return item.status;
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
    const n = positive(value);
    if (n !== null) line.quantity = String(n);
    return line.quantity;
  }

  function stagedIds() {
    return staged.map(function (s) { return s.id; });
  }

  /** The component a line stands for, in the form publish.js opens: the design itself, or a BOM line. */
  function rootComponent(root) {
    return { id: root.component_id || '', root: true, item_number: root.item_number, part_number: root.part_number, description: root.description,
             title: [root.item_number || root.part_number, root.name || root.description].filter(Boolean).join(' - ') || 'This design' };
  }

  function lineComponent(r) {
    return { id: r.id, root: false, item_number: r.item_number, part_number: r.part_number, description: r.description, name: r.name,
             title: [r.item_number || r.part_number, r.name || r.description].filter(Boolean).join(' - ') };
  }

  /** Leave a line out of publishing, as one with no item number is. ``why`` is 'shared' (``sharedWith`` names the others) or 'parent' (a line above it is skipped). */
  function skipLine(item, why, sharedWith) {
    item.status = 'skipped';
    item.skip = why;
    item.sharedWith = sharedWith || [];
    item.componentName = item.componentName || (item.component && item.component.name) || '';
    delete item.component;   // a skipped line has no details to open
  }

  function itemNumberOf(item) {
    return item.component ? String(item.component.item_number || '').trim().toLowerCase() : '';
  }

  /**
   * Components of the design that carry one item number would all write to one Fusion Manage item, so every such line is skipped, with
   * what is below it. The design itself is never skipped: the lines that share its number are.
   */
  function markShared(items) {
    const holders = {};   // item number, lower case -> { component id -> title }
    items.forEach(function (item, at) {
      const number = itemNumberOf(item);
      if (number) (holders[number] = holders[number] || {})[item.component.id || 'line' + at] = item.component.title || number;
    });
    let below = -1;   // level of the skipped line whose lines are being passed, -1 when none
    items.forEach(function (item, at) {
      if (below >= 0 && item.level > below) {
        if (item.status !== 'skipped') skipLine(item, 'parent');
        return;
      }
      below = -1;
      const number = itemNumberOf(item);
      const group = number ? holders[number] : {};
      if (item.root || Object.keys(group).length < 2) return;
      const own = item.component.id || 'line' + at;
      skipLine(item, 'shared', Object.keys(group).filter(function (id) { return id !== own; }).map(function (id) { return group[id]; }));
      below = item.level;
    });
  }

  /**
   * Lines to draw: the open design first, then each compared row. A Fusion Manage line that
   * sits beside a design line with another item number is folded into that design line.
   */
  function buildItems(rows, root) {
    const rootName = root.name || root.description || '';
    const rootPn = root.item_number || root.part_number || '';   // the item number is the master; the part number only stands in when there is none
    const items = [{ level: 0, root: true, sequence: '', status: 'root', hidden: false, component: rootComponent(root),
                     design: { pn: rootPn, name: rootName || (rootPn ? '' : 'This design'), quantity: '', sequence: '' },
                     fm: { pn: rootPn, name: rootName, quantity: '', sequence: '' } }];
    const repeats = {};
    let held = null;   // paired Fusion Manage line waiting for its design line, which follows it
    function side(r, quantity, edge) {
      // "Item Number - Part Name"; a line without an item number shows its part number, and the description when it has no name.
      return { pn: r.item_number || r.part_number, name: r.name || r.description, quantity: plainQuantity(quantity), sequence: String(r.sequence), edge: edge || '' };
    }
    // The choices are keyed by where a line sits (the numbers of the lines above it), not by its place in the whole list: lines read later
    // (an assembly opened, the rest of the tree) must not move the choices already made.
    const pathAt = [];   // level -> number of the latest line on it
    function where(level) { return pathAt.slice(1, level).join('>'); }
    rows.forEach(function (r) {
      if (r.status === 'skipped') {   // no item number, or below a line with none: nothing is published for it, and it has no details to open
        const line = { level: r.level + 1, root: false, sequence: String(r.sequence), status: 'skipped', hidden: !!r.hidden, skip: r.skip || '', componentName: r.name || '',
                       assembly: !!r.has_children, lineId: r.id || '', design: side(r, r.quantity), fm: side(r, '') };
        pathAt[line.level] = line.design.pn;
        items.push(line);
        return;
      }
      if (r.status === 'extra' && r.pair) { held = r; return; }
      if (r.status === 'extra') {
        const line = { level: r.level + 1, root: false, sequence: String(r.sequence), status: 'extra', hidden: false, design: side(r, ''), fm: side(r, r.quantity, r.edge_id),
                       key: 'only|' + where(r.level + 1) + '|' + r.part_number + '|' + r.sequence + '|' + r.level };   // so the user can choose to remove it
        pathAt[line.level] = line.fm.pn;
        items.push(line);
        return;
      }
      const item = { level: r.level + 1, root: false, sequence: String(r.sequence), status: r.status || 'unchecked', hidden: !!r.hidden, component: lineComponent(r),
                     assembly: !!r.has_children, lineId: r.id || '',
                     design: side(r, r.quantity), fm: side(r, r.status === 'match' ? r.quantity : r.fm_quantity || '', r.fm_edge_id) };
      if (held && held.pair === String(r.item_number)) {
        item.status = 'mismatch';
        item.fm = side(held, held.quantity, held.edge_id);
        // Repeats of the same pair of numbers under one parent get their own choice: "parent path|design|Fusion Manage|n", n counting the repeats.
        const base = where(item.level) + '|' + item.design.pn + '|' + item.fm.pn;
        repeats[base] = (repeats[base] || 0) + 1;
        item.key = base + '|' + repeats[base];
      }
      held = null;
      pathAt[item.level] = item.design.pn;
      items.push(item);
    });
    markShared(items);
    const seqAt = [];   // sequence of the latest line on each level, so a line's quantity edit has a key of its own
    items.forEach(function (item) {
      if (item.root) return;
      seqAt[item.level] = item.sequence;
      item.qkey = seqAt.slice(1, item.level + 1).join('.') + '|' + item.design.pn + '|' + item.fm.pn;
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
      case 'skipped': groups = ['skipped']; break;
      case 'extra': groups = quantityDiffers(item) ? ['extra', 'changed'] : ['extra']; break;
      default: groups = [statusOf(item)];
    }
    return item.hidden && !item.root ? groups.concat('hidden') : groups;
  }

  /** How many differing pairs still wait for a choice (the lines the Review filter shows). */
  function pendingReviews(items) {
    return items.filter(function (item) { return item.status === 'mismatch' && !decisions[item.key]; }).length;
  }

  ns.bomModel = {
    decisions: decisions, clearDecisions: clearDecisions, canEditQuantity: canEditQuantity, baseQuantity: baseQuantity, quantityOf: quantityOf, setQuantity: setQuantity,
    quantityDiffers: quantityDiffers, quantityEdited: quantityEdited, revertQuantity: revertQuantity, statusOf: statusOf, stage: stage, unstage: unstage, setStagedQuantity: setStagedQuantity, stagedIds: stagedIds, rootComponent: rootComponent,
    buildItems: buildItems, arrange: arrange, groupsOf: groupsOf, pendingReviews: pendingReviews,
  };
})(window.MfgUi);
