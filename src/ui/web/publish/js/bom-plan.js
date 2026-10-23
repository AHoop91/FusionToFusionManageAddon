/**
 * Publish Item panel: what publishing does, as ``ns.bomPlan``.
 *
 * Turns the lines of bom-model.js (with the user's choices and edited quantities) into the components whose Fusion Manage item is
 * created or updated and the BOM operations to run, each naming its parent by item number.
 */
(function (ns) {
  'use strict';

  const model = ns.bomModel;
  const decisions = model.decisions;

  function removal(parent, item) {
    return { op: 'remove', parent: parent, number: item.fm.pn, sequence: item.fm.sequence, edge: item.fm.edge };
  }

  function update(item, line, sequence) {
    return Object.assign({ op: 'update', fm_quantity: item.fm.quantity, edge: item.fm.edge }, line, sequence === undefined ? {} : { sequence: sequence });
  }

  /** The BOM operations of one line. ``line`` is its parent, number, quantity and sequence; ``oldSequence`` is the sequence of a kept line before it moved. */
  function operationsOf(item, line, oldSequence) {
    switch (item.status) {
      case 'new': case 'added': case 'uncompared':
        return [Object.assign({ op: 'add' }, line)];
      case 'mismatch':   // only a pair that chose 'remove' is still a mismatch here
        return [Object.assign({ op: 'add' }, line), removal(line.parent, item)];
      case 'linked':   // an existing Fusion Manage item: only the BOM line is added, never the item
        return [{ op: 'add', parent: line.parent, number: line.number, quantity: item.fm.quantity, sequence: item.fm.sequence, link: item.link, linkable: item.linkable }];
      case 'extra':   // only in Fusion Manage: left alone unless the user chose to remove it
        if (decisions[item.key] === 'remove') return [removal(line.parent, item)];
        return model.quantityDiffers(item) ? [update(item, line, item.fm.sequence)] : [];
      case 'match': case 'changed':   // an edit can turn either into an update, or an update back into nothing
        return model.quantityDiffers(item) ? [update(item, line)] : [];
      case 'kept':
        return [{ op: 'renumber', parent: line.parent, number: item.fm.pn, from_sequence: oldSequence, sequence: item.sequence, edge: item.fm.edge }];
      default:
        return [];
    }
  }

  /**
   * What publishing does: the components whose Fusion Manage item is created or updated (the design and every component of it; the
   * comparison finds out which of them differ) and the BOM operations (add, update the quantity, remove, renumber a kept line). Fusion
   * Manage only lines are left alone unless the user chose to remove them. A skipped line, and everything below it, is left out.
   * ``rows`` must hold every level of the tree.
   */
  function publishPlan(rows, root) {
    const base = model.buildItems(rows, root);
    const items = model.arrange(base);
    const oldSequence = {};
    base.forEach(function (item) { if (item.key) oldSequence[item.key] = item.fm.sequence; });
    const numberAt = [];   // item number of the latest line on each level, so a line finds its parent
    const components = [];
    const seen = {};
    const operations = [];
    items.forEach(function (item) {
      if (item.status === 'skipped') { numberAt[item.level] = ''; return; }   // no item, no BOM line, and none for what is below it
      const own = item.component ? String(item.component.item_number || item.design.pn || '') : String(item.fm.pn || '');
      const parent = item.level > 0 ? numberAt[item.level - 1] || '' : '';
      numberAt[item.level] = own;
      if (item.root) { components.push(Object.assign({}, item.component, { root: true })); return; }
      const line = { parent: parent, number: own, quantity: model.quantityOf(item), sequence: item.design.sequence };
      operationsOf(item, line, oldSequence[item.key]).forEach(function (operation) { operations.push(operation); });
      // Every design component goes through the comparison, so an existing item is updated when its properties differ.
      if (item.component && item.component.id && !seen[item.component.id]) {
        seen[item.component.id] = true;
        components.push(item.component);
      }
    });
    return { components: components, operations: operations };
  }

  ns.bomPlan = { publishPlan: publishPlan };
})(window.MfgUi);
