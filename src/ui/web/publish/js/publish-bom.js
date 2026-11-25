/**
 * Publish Item panel: the Bill of Materials area, as ``ns.pubBom``.
 *
 * Keeps the design's Bill of Materials (every level, read at once) and hands it to the structure viewer (mbom-viewer.js), which is what the user works in
 * and what Publish sends. This area shows only what is not the viewer: the balls while Fusion Manage is checked for existing Bills of Materials, a
 * message or an error (the skeleton of the two tables is the viewer's own). It queues the publish from the plan the viewer gives (mbom-plan.js). The panel (publish.js) sends the requests and hands the answers back,
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

  let host = null;          // { summary(), plan(), say(text), showNotice() }, given to ``init``
  let rows = [];            // the rows of the Bill of Materials that was read

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

  /** What the Bill of Materials is doing: reading it, and how far once it takes several pages. The viewer says it under the skeleton. */
  function status(entry) {
    host.say(entry.progress ? t('publish.reading_bom_lines', { count: Number(entry.progress).toLocaleString() }) : t('publish.reading_bom'));
  }

  /** Bouncing balls, in the middle of the area, while Fusion Manage is checked for Bills of Materials the design already has. */
  function showChecking() {
    clear().classList.add('pub-loading');
    $('pub-bom').appendChild(ui.loaderNode(t('publish.checking_mbom')));
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

  /** The whole Bill of Materials has been read: the structure viewer, already on screen as a skeleton, goes on to read the MBOM. A design whose number is
   *  shared says so instead. */
  function showStructure(data) {
    tree.setAll(data.rows);
    rows = tree.rows();
    if (data.shared) {   // no structure until the number is fixed in Fusion Manage, so open the design's details, which say so
      showMessage(t('publish.design_shared_message'));
      setPublishState(t('publish.design_shared_fix'));
      details.open(model.rootComponent(host.summary()));
    }
  }

  /** The design is read again: forget what was read of the tree. */
  function reset() {
    tree.clear();
    rows = [];
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
   * ``hostApi`` is the panel: ``summary()`` of the open design, ``plan()`` for what the structure would publish (null before it is shown), ``say(text)`` for
   * the line under the viewer's skeleton, and ``showNotice()`` to put this area on screen in place of the viewer.
   */
  function init(hostApi) {
    host = hostApi;
    $('pub-publish').addEventListener('click', publish);
  }

  ns.pubBom = {
    init: init, clear: clear, showChecking: showChecking, showError: showError, showStructure: showStructure, status: status,
    reset: reset, refreshScope: refreshScope,
    rows: function () { return rows; },
  };
})(window.MfgUi);
