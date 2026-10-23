/**
 * Publish Item panel: what publishing covers, as ``ns.bomScope``.
 *
 * Publishing covers what the user can see in the Bill of Materials: the design, and the lines of every assembly that is open. What sits
 * under a closed assembly is not published, so a large design can be published a part at a time. ``rows`` are the flat rows of
 * bom-tree.js (tree order, ``level`` 0 = directly under the design).
 */
(function (ns) {
  'use strict';

  /**
   * The rows that are in view: those with every assembly above them open (the design too). ``isOpen(id)`` says whether the assembly
   * with that component id is open.
   */
  function visibleRows(rows, rootId, isOpen) {
    const out = [];
    const open = [];   // level -> whether the latest row on it is an open assembly
    rows.forEach(function (row) {
      let shown = isOpen(rootId);
      for (let level = 0; level < row.level && shown; level++) shown = !!open[level];
      if (shown) out.push(row);
      open[row.level] = !!row.id && isOpen(row.id);
    });
    return out;
  }

  /** How many of the rows in view are assemblies that are closed, so what is under them is left out. */
  function closedAssemblies(visible, isOpen) {
    return visible.filter(function (row) { return row.has_children && !isOpen(row.id); }).length;
  }

  ns.bomScope = { visibleRows: visibleRows, closedAssemblies: closedAssemblies };
})(window.MfgUi);
