/**
 * Publish Item panel: the data side of the Bill of Materials, as ``ns.bomModel``.
 *
 * Turns the compared rows (design rows compared with Fusion Manage) into the lines the check and the structure viewer read: the status of
 * each line, its quantity, and the lines that share an item number and so are skipped.
 *
 * Fusion Manage extends the design BOM, so lines only it has are kept. When the item number
 * differs at one position, the design line and the Fusion Manage line are paired as one 'mismatch' line.
 */
(function (ns) {
  'use strict';

  function t(key, params) { return ns.i18n.t(key, params); }

  /** A quantity the way Fusion writes it: Fusion Manage's "1.0" and "2.50" read "1" and "2.5". Anything that is not a number is left as it is. */
  function plainQuantity(value) {
    const text = String(value === undefined || value === null ? '' : value).trim();
    const n = Number(text);
    return text !== '' && isFinite(n) ? String(n) : text;
  }

  /** The quantity a line will have once published: the design's, or Fusion Manage's for a line only it has. */
  function quantityOf(item) {
    return item.status === 'extra' ? item.fm.quantity : item.design.quantity;
  }

  /** A line in both the design and Fusion Manage whose quantity to publish is not Fusion Manage's. */
  function quantityDiffers(item) {
    return ['match', 'changed', 'extra'].includes(item.status) && Number(quantityOf(item)) !== Number(item.fm.quantity);
  }

  /** The status a line shows: a match whose quantity differs from Fusion Manage's is an update, an update whose quantity does not is a match. */
  function statusOf(item) {
    if (item.status === 'match' && quantityDiffers(item)) return 'changed';
    if (item.status === 'changed' && !quantityDiffers(item)) return 'match';
    return item.status;
  }

  /** The component a line stands for, in the form publish.js opens: the design itself, or a BOM line. */
  function rootComponent(root) {
    return { id: root.component_id || '', root: true, item_number: root.item_number, part_number: root.part_number, description: root.description,
             title: [root.item_number || root.part_number, root.name || root.description].filter(Boolean).join(' - ') || t('publish.tree_this_design') };
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
                     design: { pn: rootPn, name: rootName || (rootPn ? '' : t('publish.tree_this_design')), quantity: '', sequence: '' },
                     fm: { pn: rootPn, name: rootName, quantity: '', sequence: '' } }];
    let held = null;   // paired Fusion Manage line waiting for its design line, which follows it
    function side(r, quantity, edge) {
      // "Item Number - Part Name"; a line without an item number shows its part number, and the description when it has no name.
      return { pn: r.item_number || r.part_number, name: r.name || r.description, quantity: plainQuantity(quantity), sequence: String(r.sequence), edge: edge || '' };
    }
    rows.forEach(function (r) {
      if (r.status === 'skipped') {   // no item number, or below a line with none: nothing is published for it, and it has no details to open
        const line = { level: r.level + 1, root: false, sequence: String(r.sequence), status: 'skipped', hidden: !!r.hidden, skip: r.skip || '', componentName: r.name || '',
                       assembly: !!r.has_children, lineId: r.id || '', design: side(r, r.quantity), fm: side(r, '') };
        items.push(line);
        return;
      }
      if (r.status === 'extra' && r.pair) { held = r; return; }
      if (r.status === 'extra') {
        const line = { level: r.level + 1, root: false, sequence: String(r.sequence), status: 'extra', hidden: false, design: side(r, ''), fm: side(r, r.quantity, r.edge_id) };
        items.push(line);
        return;
      }
      const item = { level: r.level + 1, root: false, sequence: String(r.sequence), status: r.status || 'unchecked', hidden: !!r.hidden, component: lineComponent(r),
                     assembly: !!r.has_children, lineId: r.id || '',
                     design: side(r, r.quantity), fm: side(r, r.status === 'match' ? r.quantity : r.fm_quantity || '', r.fm_edge_id) };
      if (held && held.pair === String(r.item_number)) {
        item.status = 'mismatch';
        item.fm = side(held, held.quantity, held.edge_id);
      }
      held = null;
      items.push(item);
    });
    markShared(items);
    return items;
  }

  ns.bomModel = {
    quantityOf: quantityOf, quantityDiffers: quantityDiffers, statusOf: statusOf, rootComponent: rootComponent, lineComponent: lineComponent,
    buildItems: buildItems,
  };
})(window.MfgUi);
