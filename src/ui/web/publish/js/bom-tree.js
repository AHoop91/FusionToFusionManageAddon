/**
 * Publish Item panel: the Bill of Materials as it has been read so far, as ``ns.bomTree``.
 *
 * Only the first level is read at first; the lines under an assembly are read when it is opened (or all of them, for Expand all and for
 * publishing). Each read gives the lines directly under one component. They are kept by that component's id, so a component used in
 * several places is read once and shows its lines in every place. ``rows`` lays them out again as one flat list in tree order, each row
 * with its ``level`` (0 = directly under the design), which is what bom-model.js turns into the lines of the table.
 */
(function (ns) {
  'use strict';

  let top = [];    // the lines directly under the design
  let kids = {};   // component id -> the lines directly under it

  function clear() {
    top = [];
    kids = {};
  }

  function setTop(rows) {
    top = rows.slice();
    kids = {};
  }

  function setKids(id, rows) {
    kids[id] = rows.slice();
  }

  /** Is what is under this component read? A component with nothing under it has nothing to read. */
  function isLoaded(id) {
    return Object.prototype.hasOwnProperty.call(kids, id);
  }

  /**
   * Take a whole tree, as flat rows with their levels, and keep it in the same shape as the levels read one at a time. A component used
   * in several places comes with its lines in each: the first place is kept.
   */
  function setAll(rows) {
    clear();
    const lineAt = [];   // level -> index of the latest row on it, so a row finds its parent
    const first = {};    // parent id -> index of the parent row whose lines are kept
    rows.forEach(function (row, i) {
      const level = Number(row.level) || 0;
      lineAt[level] = i;
      const copy = Object.assign({}, row, { level: 0 });
      if (level === 0) { top.push(copy); return; }
      const parentIndex = lineAt[level - 1];
      const parent = rows[parentIndex];
      const id = parent ? parent.id : '';
      if (!id) return;
      if (first[id] === undefined) first[id] = parentIndex;
      if (first[id] !== parentIndex) return;   // another place of the same component: its lines are the ones already kept
      (kids[id] = kids[id] || []).push(copy);
    });
    // The whole tree is read: an assembly that met no line has none, and nothing is left to wait for.
    rows.forEach(function (row) { if (row.id && !isLoaded(row.id)) kids[row.id] = []; });
  }

  function lay(list, base, ancestors, out) {
    list.forEach(function (row) {
      out.push(Object.assign({}, row, { level: base }));
      if (row.id && isLoaded(row.id) && !ancestors[row.id]) {   // a component inside itself would never end
        ancestors[row.id] = true;
        lay(kids[row.id], base + 1, ancestors, out);
        delete ancestors[row.id];
      }
    });
  }

  /** Everything read so far, flat, in tree order. */
  function rows() {
    const out = [];
    lay(top, 0, {}, out);
    return out;
  }

  /** The ids of the assemblies shown whose lines are not read yet. */
  function unloaded() {
    const found = {};
    rows().forEach(function (row) { if (row.id && row.has_children && !isLoaded(row.id)) found[row.id] = true; });
    return Object.keys(found);
  }

  ns.bomTree = { clear: clear, setTop: setTop, setKids: setKids, setAll: setAll, isLoaded: isLoaded, rows: rows, unloaded: unloaded };
})(window.MfgUi = window.MfgUi || {});
