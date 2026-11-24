/**
 * Publish Item panel: the Bill of Materials area, as ``ns.pubBom``.
 *
 * Reads the design's Bill of Materials (the first level, then the whole tree) and hands it to the structure viewer (mbom-viewer.js), which is
 * what the user works in and what Publish sends. This area shows only what comes before it: the loading skeleton, a message or an error. It
 * reads the whole tree when the viewer asks for it, keeps the rows that were read and
 * queues the publish from the plan the viewer gives (mbom-plan.js). The panel (publish.js) sends the requests and hands the answers back,
 * through ``host``.
 */
(function (ns) {
  'use strict';

  const $ = ns.$;
  const ui = ns.pubUi;
  const details = ns.pubDetails;
  const jobs = ns.pubJobs;
  const model = ns.bomModel;
  const tree = ns.bomTree;
  function t(key, params) { return ns.i18n.t(key, params); }

  let host = null;          // { summary(), ask(slot, payload), changed(), treeDone(entry), plan(), showStructure(), showNotice() }, given to ``init``
  let rows = [];            // compared rows of the Bill of Materials read so far
  let treeLoading = false;  // the whole tree is being read
  let statusText = '';      // what the loading line last said

  // ---- Publish -------------------------------------------------------------------

  /** Publish is available once the structure is shown and has nothing that cannot be published; ``reason`` says why it is not. */
  function setPublishState(reason) {
    const button = $('pub-publish');
    button.disabled = !!reason;
    button.title = reason || t('publish.publish_title');
  }

  /** Why the plan cannot be published, in a sentence ("" when it can). The first kind of problem is told; the others once that is dealt with. */
  function problemText(problems) {
    const first = problems[0];
    if (!first) return '';
    const numbers = first.numbers.slice(0, 5).join(', ') + (first.numbers.length > 5 ? ' (+' + (first.numbers.length - 5) + ')' : '');
    switch (first.kind) {
      case 'unpublishable': return t('publish.plan_unpublishable', { numbers: numbers });
      case 'skipped': return t('publish.plan_skipped', { numbers: numbers });
      default: return t('publish.plan_ambiguous', { numbers: numbers });
    }
  }

  // ---- What the area shows -------------------------------------------------------

  function clear() {
    setPublishState(t('publish.waiting_bom'));
    host.showNotice();
    const area = $('pub-bom');
    area.classList.remove('pub-loading');
    area.textContent = '';
    return area;
  }

  /** What the Bill of Materials is doing: reading it (and how far, once it takes several pages), then comparing it with Fusion Manage. */
  function status(entry) {
    const note = $('pub-bom-status');
    if (!note) return;
    const text = entry.stage === 'comparing' ? t('publish.comparing')
      : entry.progress ? t('publish.reading_bom_lines', { count: Number(entry.progress).toLocaleString() })
      : t('publish.reading_bom');
    if (text === statusText && note.textContent) return;   // the same words must not restart the "taking longer" timer
    statusText = text;
    ui.warnWhenSlow(note, text);   // adds a note if nothing new has been said for a long while
  }

  /** Rows of grey bars while it loads, with a line saying what is happening. */
  function showLoading() {
    const area = clear();
    const note = ui.el('p', 'muted pub-bom-status');
    note.id = 'pub-bom-status';
    area.appendChild(note);
    const skeleton = ui.el('div', 'card pub-skel-table');
    skeleton.setAttribute('aria-hidden', 'true');
    for (let n = 0; n < 8; n++) {
      const line = ui.el('div', 'pub-skel-row');
      ['pub-skel-wide', 'pub-skel-mid', 'pub-skel-short'].forEach(function (width) { line.appendChild(ui.el('span', 'pub-skel ' + width)); });
      skeleton.appendChild(line);
    }
    area.appendChild(skeleton);
    status({});
  }

  function showMessage(text) {
    const card = ui.el('div', 'card');
    card.appendChild(ui.el('p', 'muted', text));
    clear().appendChild(card);
  }

  /** A failure in the middle of the panel, so the message centres in it. */
  function showError(message, onRetry) {
    clear().classList.add('pub-loading');
    $('pub-bom').appendChild(ui.errorState(message, onRetry));
  }

  /** The first level has been read and compared: the structure viewer takes over (it asks for the rest). A design whose number is shared says so instead. */
  function showFirstLevel(data) {
    tree.setTop(data.rows);   // the rest is read when the viewer asks for it
    rows = tree.rows();
    if (data.shared) {   // no structure until the number is fixed in Fusion Manage, so open the design's details, which say so
      showMessage(t('publish.design_shared_message'));
      setPublishState(t('publish.design_shared_fix'));
      details.open(model.rootComponent(host.summary()));
      return;
    }
    clear();
    host.showStructure();
  }

  // ---- Reading the whole tree ----------------------------------------------------

  /** Read every level that is not read yet (the structure needs the whole EBOM). */
  function loadTree() {
    if (treeLoading) return;
    treeLoading = true;
    host.ask('tree', { section: 'tree', force: true });
  }

  function finishTree(entry) {
    treeLoading = false;
    if (entry.ok) {
      tree.setAll(entry.data.rows);
      rows = tree.rows();
      host.changed();
    }
    host.treeDone(entry);
  }

  /** The design is read again: forget what was read of the tree. */
  function reset() {
    tree.clear();
    rows = [];
    treeLoading = false;
  }

  /** The structure was drawn or edited: say whether anything in it cannot be published (the button says why). */
  function refreshScope() {
    const plan = host && host.plan();
    setPublishState(plan ? problemText(plan.problems) : t('publish.waiting_bom'));
  }

  // ---- Publish -------------------------------------------------------------------

  /**
   * Publish what the structure holds: the design, the components its lines are made from, and the BOM lines it adds, changes and removes. Nothing is
   * sent when the structure is not shown yet or holds something that cannot be published (the button says so too).
   */
  function publish() {
    const plan = host.plan();
    if (!plan) { ns.toast.show(t('publish.waiting_bom'), { tone: 'error' }); return; }
    if (plan.problems.length) { ns.toast.show(problemText(plan.problems), { tone: 'error' }); return; }
    const summary = host.summary();
    jobs.start({
      summary: summary,
      root_number: summary.item_number || '',
      operations: plan.operations,
      items: plan.components.map(function (c) {
        return { id: c.id, root: !!c.root, item_number: c.item_number, part_number: c.part_number, description: c.description, name: c.name || '' };
      }),
    });
  }

  /**
   * ``hostApi`` is the panel: ``summary()`` of the open design, ``ask(slot, payload)`` to request a section (its answer comes back to ``finishTree``),
   * ``changed()`` to say what was read has changed, ``treeDone(entry)`` to say the whole tree was read (or failed), ``plan()`` for what the structure
   * would publish (null before it is shown), and ``showStructure()`` / ``showNotice()`` for which of the viewer and this area is on screen.
   */
  function init(hostApi) {
    host = hostApi;
    $('pub-publish').addEventListener('click', publish);
  }

  ns.pubBom = {
    init: init, clear: clear, showLoading: showLoading, showError: showError, showFirstLevel: showFirstLevel, status: status,
    finishTree: finishTree, reset: reset, loadTree: loadTree, refreshScope: refreshScope,
    rows: function () { return rows; }, partial: function () { return tree.unloaded().length > 0; },
  };
})(window.MfgUi);
