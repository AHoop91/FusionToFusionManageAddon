/**
 * Publish Item panel: the up-to-date check, as ``ns.pubCheck``.
 *
 * The round button at the top right scans while the Bill of Materials and the design's own properties are read, then says whether
 * the design matches Fusion Manage; a click lists what differs. The design's properties are compared once and kept here; the Bill of
 * Materials lines come from the panel through ``host``.
 */
(function (ns) {
  'use strict';

  const $ = ns.$;
  const details = ns.pubDetails;

  // BOM lines the design has that Fusion Manage lacks or holds differently; lines only Fusion Manage has (it extends the BOM) are ignored.
  const DIFFERING = ['new', 'changed', 'added', 'mismatch'];
  const ISSUES = {
    new: 'Not in Fusion Manage',
    changed: 'Quantity differs',
    mismatch: 'Different item at this position',
    added: 'Added with Add Existing Items',
  };
  const REPORT_TITLES = { ok: 'Up to date', changes: 'Out of date', error: 'Could not check' };   // of the dialog behind the check button

  let host = null;           // { summary(), rows(), structureLoaded(), partial() }, given to ``init``
  let rootCompare = null;    // the design's own properties compared with Fusion Manage (null until read)
  let rootFailed = '';       // why the design could not be checked
  let knownNew = false;      // the BOM read found no Fusion Manage item for the design, before its properties were compared
  let report = { state: 'checking', text: '', props: [], lines: [], subject: '' };   // what the button last said, listed in its dialog

  function plural(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }

  function quantityText(quantity) { return quantity === '' || quantity === undefined ? '-' : 'Qty ' + quantity; }

  /** The attributes of the design that differ, as the dialog lists them. */
  function attributeDifferences() {
    return rootCompare.rows.filter(function (r) { return r.status === 'mismatch' || r.status === 'new'; }).map(function (r) {
      const own = r.shown || r.value;
      return { name: r.name, fusion: own ? own + (r.unit ? ' ' + r.unit : '') : '', fm: r.fm_value };
    });
  }

  /** The Bill of Materials lines (of the levels read so far) that differ, as the dialog lists them. */
  function lineDifferences() {
    const model = ns.bomModel;
    const rows = host.rows();
    const items = rows.length ? model.arrange(model.buildItems(rows, host.summary())) : [];
    return items.filter(function (item) { return DIFFERING.indexOf(model.statusOf(item)) >= 0; }).map(function (item) {
      const status = model.statusOf(item);
      const different = status === 'mismatch';
      return {
        number: item.design.pn, name: item.design.name, issue: ISSUES[status] || status, component: item.component,
        fusion: different ? item.design.pn : quantityText(model.quantityOf(item)),
        fm: status === 'new' || status === 'added' ? '-' : different ? item.fm.pn : quantityText(item.fm.quantity),
      };
    });
  }

  /** What the button says now: ``{ state, text, props, lines }``. */
  function verdict() {
    const none = { props: [], lines: [] };
    if (!host.structureLoaded() && !rootFailed) return Object.assign({ state: 'idle', text: 'Checking Fusion Manage...' }, none);   // hidden until the panel has loaded; the check then runs quietly
    if (rootFailed) return Object.assign({ state: 'error', text: 'Could not check: ' + rootFailed }, none);
    // The BOM read already searched Fusion Manage and found nothing: the design is new, so there is no check to wait for.
    if (knownNew && !rootCompare) return Object.assign({ state: 'idle', text: 'Not in Fusion Manage yet: publishing creates it.' }, none);
    if (!rootCompare) return Object.assign({ state: 'checking', text: 'Checking Fusion Manage...' }, none);
    const own = details.changeState(rootCompare);
    // Not in Fusion Manage yet: nothing is out of date, so the button stays hidden.
    if (own === 'new') return Object.assign({ state: 'idle', text: 'Not in Fusion Manage yet: publishing creates it.' }, none);
    const found = { props: attributeDifferences(), lines: lineDifferences() };
    if (own === 'unknown') return Object.assign({ state: 'error', text: 'Fusion Manage could not be read.' }, found);
    if (own === 'multiple') return Object.assign({ state: 'changes', text: 'Several Fusion Manage items carry this design\'s item number. Fix it in Fusion Manage.' }, found);
    if (found.props.length + found.lines.length) {
      return Object.assign({ state: 'changes', text: plural(found.props.length, 'attribute difference') + ' and ' + plural(found.lines.length, 'Bill of Materials line') + ' to update.' }, found);
    }
    return Object.assign({ state: 'ok', text: host.partial() ? 'The levels read so far match Fusion Manage.' : 'The design matches Fusion Manage.' }, found);
  }

  /** Draw the button: scanning while the Bill of Materials and the design's properties are read, then what they say. */
  function update() {
    const button = $('pub-check');
    const count = $('pub-check-count');
    const v = verdict();
    const n = v.props.length + v.lines.length;
    report = { state: v.state, text: v.text, props: v.props, lines: v.lines, subject: host.summary().item_number || 'this design' };
    button.dataset.state = v.state;
    button.title = v.state === 'checking' ? v.text : v.text + ' Click for details.';
    button.setAttribute('aria-label', button.title);
    count.hidden = !n;
    count.textContent = n > 99 ? '99+' : String(n);
  }

  /** The dialog behind the button: what differs. */
  function open() {
    if (report.state === 'checking' || report.state === 'idle') return;
    const sections = [];
    if (report.props.length) {
      sections.push({
        title: 'Attributes', columns: ['Property', ns.diffReport.COLUMN_VALUE, ns.diffReport.COLUMN_FM],
        rows: report.props.map(function (p) { return { cells: [p.name, p.fusion, p.fm] }; }),
      });
    }
    if (report.lines.length) {
      sections.push({
        title: 'Bill of Materials', columns: ['Item', 'Issue', ns.diffReport.COLUMN_VALUE, ns.diffReport.COLUMN_FM],
        rows: report.lines.map(function (l) {
          return { cells: [l.number, l.issue, l.fusion, l.fm], sub: l.name, onClick: l.component ? function () { details.open(l.component); } : null };
        }),
      });
    }
    ns.diffReport.open({
      state: report.state, title: REPORT_TITLES[report.state] || 'Fusion Manage check', summary: report.text, sections: sections,
      empty: report.state === 'ok' ? 'Attributes and Bill of Materials for ' + report.subject + ' are up to date.' : 'There is nothing to list.',
    });
  }

  /** The design's own properties, compared with Fusion Manage; ``failure`` says why they could not be read. */
  function setRoot(compare, failure) {
    rootCompare = compare;
    rootFailed = failure || '';
    update();
  }

  /** The Bill of Materials could not be read, so the design cannot be checked. */
  function fail(message) {
    rootFailed = message;
    update();
  }

  /** The design is read again: nothing is known of it yet. */
  function reset() {
    rootCompare = null;
    rootFailed = '';
    knownNew = false;
    update();
  }

  /** The first level of the BOM was read: ``isNew`` when Fusion Manage holds no item for the design. */
  function setNew(isNew) {
    knownNew = !!isNew;
    update();
  }

  /** ``hostApi`` gives the panel's state: ``summary()`` of the open design, ``rows()`` of the Bill of Materials read so far, ``structureLoaded()`` and ``partial()`` (levels not read yet). */
  function init(hostApi) {
    host = hostApi;
    $('pub-check').addEventListener('click', open);
  }

  ns.pubCheck = { init: init, update: update, setRoot: setRoot, setNew: setNew, fail: fail, clearFailure: function () { rootFailed = ''; }, reset: reset };
})(window.MfgUi);
