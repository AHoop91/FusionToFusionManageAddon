/**
 * Publish Item panel: the Details Panel beside the bill of materials, as ``ns.pubDetails``.
 *
 * It shows one component at a time: its properties compared with Fusion Manage. Components are read when their row is clicked, then kept. The design's own
 * properties are read by publish.js, when its row is first opened, and handed in with ``setRoot``.
 *
 * ``init`` takes: ``request(slot, payload)`` to ask Python for a component,
 * ``onRootLoad()`` when the design's row is opened (read its properties unless that is done or under way),
 * ``onRootChoice(itemId)`` when the user picks a Fusion Manage item for the design, and
 * ``onRootRetry()`` to read the design's properties again.
 */
(function (ns) {
  'use strict';

  const $ = ns.$;
  const ui = ns.pubUi;
  const el = ui.el;

  // Tooltip per property status (the dot at the right of a property).
  const STATUS = {
    match:     'Matches Fusion Manage',
    mismatch:  'Differs: publishing will update Fusion Manage',
    new:       'No Fusion Manage item yet: publishing will create it',
    unknown:   'Fusion Manage value could not be read',
    multiple:  'Several Fusion Manage items match: choose one',
    unchecked: 'Mapped: Fusion Manage is not checked yet',
  };

  // The pill at the top right of the component title: what publishing would do.
  const PILLS = {
    new:      { text: 'New', title: STATUS.new },
    mismatch: { text: 'Update', title: 'Publishing will update the Fusion Manage item' },
    match:    { text: 'Up to date', title: STATUS.match },
    multiple: { text: 'Choose item', title: STATUS.multiple },
    unknown:  { text: 'Error', title: 'Fusion Manage could not be read' },
  };

  let hooks = null;
  let pane = null;
  let selected = null;          // component whose details are open
  let rootCompare = null;       // comparison for the open design's own properties
  let rootError = '';           // why they could not be read
  let force = false;            // skip the cached copy when reading components
  const compares = {};          // component id -> comparison
  const errors = {};            // component id -> message
  const loading = {};           // component id -> true while being read
  const choices = {};           // item number -> Fusion Manage item id the user picked
  const changing = {};          // item number -> true while the user re-picks an already chosen item
  const collapsed = {};         // sub header -> true while collapsed; kept across components
  const DEFAULT_WIDTHS = [24, 34, 34, 8];   // Property, Fusion, Fusion Manage, status: Fusion and Fusion Manage share the room equally
  const MIN_COLUMN_PCT = 12;
  const colWidths = DEFAULT_WIDTHS.slice();   // as dragged
  const thumbs = {};            // component id -> thumbnail url ('' none, null while being read)

  function choiceKey(item) { return item.item_number || item.part_number || ''; }

  /** The Fusion Manage item the user picked for this component ('' when none). */
  function choiceFor(item) { return choices[choiceKey(item)] || ''; }

  function compareOf(item) { return item.root ? rootCompare : compares[item.id]; }

  /** Why a component's details could not be read: the design's own properties fail separately from the rest. */
  function errorOf(item) { return (item.root && rootError) || errors[item.id] || ''; }

  /** The Fusion Manage item chosen among several that share the item number, if any. */
  function pickedCandidate(compare) {
    const fm = compare && compare.fm;
    return fm && fm.candidates ? fm.candidates.filter(function (c) { return c.id === fm.item_id; })[0] : undefined;
  }

  /** True when the component must show the "which Fusion Manage item" question instead of its properties. */
  function needsPick(compare, item) {
    const fm = compare && compare.fm;
    return !!(fm && fm.candidates && fm.candidates.length && (fm.state === 'multiple' || changing[choiceKey(item)]));
  }

  /** One state for a component: does publishing change anything in Fusion Manage? */
  function changeState(compare) {
    if (!compare) return 'unchecked';
    const states = compare.rows.map(function (r) { return r.status; });
    const first = ['mismatch', 'new', 'multiple', 'unknown'].filter(function (st) { return states.indexOf(st) >= 0; })[0];
    if (first) return first;
    return states.indexOf('match') >= 0 ? 'match' : 'unchecked';
  }

  // ---- Reading components -----------------------------------------------------

  function load(item, skipCache) {
    if (!item.id || compares[item.id] || loading[item.id]) return;
    loading[item.id] = true;
    errors[item.id] = '';
    hooks.request('component:' + item.id, {
      section: 'component', id: item.id, force: skipCache || force, fm_item: choiceFor(item),
      item_number: item.item_number, part_number: item.part_number, description: item.description,
    });
  }

  /** The answer for a component read by ``load``. */
  function handleComponent(id, entry) {
    loading[id] = false;
    if (entry.ok) {
      compares[id] = entry.data.compare;
    } else {
      errors[id] = entry.message || 'Unknown error';
    }
    paint();
  }

  /** Ask for a component's thumbnail the first time its details open; it arrives on its own, after the properties.
   *  The design's own is not asked for: publish.js reads it for the top bar and hands it in with ``setThumbnail``. */
  function loadThumbnail(item) {
    if (!item.id || item.root || thumbs[item.id] !== undefined) return;
    thumbs[item.id] = null;   // null: on its way
    hooks.request('thumbnail:' + item.id, { section: 'thumbnail', id: item.id, force: force });
  }

  /** The design's thumbnail, already read for the top bar. */
  function setThumbnail(id, url) {
    thumbs[id] = url || '';
    if (selected && selected.id === id) paint();
  }

  /** The answer for a thumbnail read by ``loadThumbnail``: its url, or '' when there is none (or it could not be read). */
  function handleThumbnail(id, entry) {
    thumbs[id] = entry.ok ? entry.data.url || '' : '';
    if (selected && selected.id === id) paint();
  }

  function retry() {
    if (!selected) return;
    if (selected.root && rootError) {
      rootError = '';
      hooks.onRootRetry();
    }
    if (errors[selected.id]) {
      errors[selected.id] = '';
      loading[selected.id] = false;
      load(selected);
    }
    paint();
  }

  /** Remember the picked Fusion Manage item and compare again with it. */
  function choose(item, itemId) {
    choices[choiceKey(item)] = itemId;
    delete changing[choiceKey(item)];
    if (item.root) {
      rootCompare = null;
      hooks.onRootChoice(itemId);
    } else {
      delete compares[item.id];
      loading[item.id] = false;
      load(item, true);
    }
    paint();
  }

  // ---- Drawing the pane -------------------------------------------------------

  /** Value cell: long text wraps. ``shown`` is the value as Fusion Manage will hold it (a number cut to its field's digits); the tooltip keeps the full value. */
  function valueCell(value, shown) {
    const text = shown || value;
    const td = el('td', text ? '' : 'muted', text || '-');
    if (value) td.title = value;
    return td;
  }

  /** Drag handle on the right edge of column ``i``: it grows or shrinks against the next column, so the table keeps its width. */
  function columnGrip(i, table, apply) {
    const grip = el('span', 'pub-cmp-grip');
    grip.title = 'Drag to resize the column (double-click to reset)';
    grip.addEventListener('pointerdown', function (event) {
      event.preventDefault();
      const startX = event.clientX;
      const pair = colWidths[i] + colWidths[i + 1];
      const first = colWidths[i];
      const full = table.getBoundingClientRect().width || 1;
      grip.setPointerCapture(event.pointerId);
      grip.classList.add('dragging');
      function onMove(e) {
        colWidths[i] = Math.min(pair - MIN_COLUMN_PCT, Math.max(MIN_COLUMN_PCT, first + (e.clientX - startX) / full * 100));
        colWidths[i + 1] = pair - colWidths[i];
        apply();
      }
      function onUp() {
        grip.classList.remove('dragging');
        grip.removeEventListener('pointermove', onMove);
        grip.removeEventListener('pointerup', onUp);
        grip.removeEventListener('pointercancel', onUp);
      }
      grip.addEventListener('pointermove', onMove);
      grip.addEventListener('pointerup', onUp);
      grip.addEventListener('pointercancel', onUp);
    });
    grip.addEventListener('dblclick', function () { DEFAULT_WIDTHS.forEach(function (w, k) { colWidths[k] = w; }); apply(); });
    return grip;
  }

  function propertyTable(rows) {
    const table = el('table', 'pub-table pub-property-table');
    // Column widths (used in the wide layout), in percent; the user can drag them and they stay for the next component.
    const cols = el('colgroup');
    function apply() { colWidths.forEach(function (w, i) { cols.children[i].style.width = w + '%'; }); }
    colWidths.forEach(function () { cols.appendChild(el('col')); });
    apply();
    table.appendChild(cols);
    const head = el('tr');
    ['Property', 'Fusion', 'Fusion Manage', ''].forEach(function (h, i) {
      const th = el('th', '', h);
      if (i < 2) th.appendChild(columnGrip(i, table, apply));   // moves the edge it shares with the next column
      head.appendChild(th);
    });
    table.appendChild(head);
    rows.forEach(function (r) {
      const tr = el('tr');
      const hasFm = r.fm_field && r.fm_value;
      [['Property', el('td', '', r.name)],
       ['Fusion', valueCell(r.value, r.shown)],
       ['Fusion Manage', el('td', hasFm ? '' : 'muted', hasFm ? r.fm_value : '-')]].forEach(function (c) {
        c[1].setAttribute('data-label', c[0]);
        tr.appendChild(c[1]);
      });
      const text = STATUS[r.status] || STATUS.unknown;
      const cell = el('td', 'pub-status pub-status-' + r.status);
      const mark = el('span', 'pub-mark');
      mark.title = text;
      mark.setAttribute('aria-label', text);
      cell.appendChild(mark);
      tr.appendChild(cell);
      table.appendChild(tr);
    });
    return table;
  }

  /** Properties of one component, as they would be published. */
  function propertiesCard(compare) {
    const card = el('div', 'card');
    if (!compare.rows.length) {
      card.appendChild(el('p', 'muted', 'This item has no properties.'));
      return card;
    }
    if (!pickedCandidate(compare) && compare.fm.message) {
      card.appendChild(el('p', compare.fm.state === 'unknown' ? 'pub-error' : 'muted', compare.fm.message));
    }
    const mapped = compare.rows.filter(function (r) { return r.status !== 'unmapped'; });
    if (mapped.length) card.appendChild(propertyTable(mapped));
    else card.appendChild(el('p', 'muted', 'No properties are mapped to Fusion Manage. Map fields in Settings.'));
    return card;
  }

  /** Several Fusion Manage items share the item number: list their descriptors and ask which one. */
  function pickerCard(fm, item) {
    const card = el('div', 'card pub-pick-card');
    card.appendChild(el('h4', 'pub-pick-title', 'Which Fusion Manage item?'));
    card.appendChild(el('p', 'muted', fm.candidates.length + ' items match ' + fm.item_number + '. Choose the one to publish to.'));
    fm.candidates.forEach(function (c) {
      const button = el('button', 'pub-fm-choice' + (c.id === fm.item_id ? ' active' : ''), c.descriptor);
      button.type = 'button';
      button.title = c.descriptor;
      button.addEventListener('click', function () { choose(item, c.id); });
      card.appendChild(button);
    });
    if (fm.state !== 'multiple') {
      const cancel = el('button', 'pub-outline-button pub-retry', 'Cancel');
      cancel.type = 'button';
      cancel.addEventListener('click', function () { delete changing[choiceKey(item)]; paint(); });
      card.appendChild(cancel);
    }
    return card;
  }

  /** A sub header with a chevron that shows or hides its content. */
  function section(title, content) {
    const box = el('div', 'pub-section');
    const header = el('button', 'pub-subheading');
    header.type = 'button';
    const arrow = ui.chevron();
    header.appendChild(arrow);
    header.appendChild(el('span', '', title));
    const body = el('div', 'pub-section-body');
    body.appendChild(content);
    function apply() {
      body.hidden = !!collapsed[title];
      ui.setChevron(arrow, !!collapsed[title]);
      header.setAttribute('aria-expanded', String(!collapsed[title]));
    }
    header.addEventListener('click', function () { collapsed[title] = !collapsed[title]; apply(); });
    apply();
    box.appendChild(header);
    box.appendChild(body);
    return box;
  }

  /** Header: the component's thumbnail, number and name, the state pill and, once an item is chosen among several, a Change button. */
  function headCard(compare) {
    const head = el('div', 'pub-props-head');
    let url = selected.id ? thumbs[selected.id] : '';
    if (selected.root && url === undefined) url = null;   // the top bar is still reading it
    if (url === null || url) {   // a skeleton while it loads, nothing when the component has none
      const thumb = el('div', 'pub-props-thumb' + (url === null ? ' pub-thumb-loading' : ''));
      // Only http(s) URLs, so nothing else is ever loaded into the style.
      if (url && /^https?:\/\//i.test(url)) thumb.style.backgroundImage = 'url("' + url.replace(/"/g, '%22') + '")';
      head.appendChild(thumb);
    }
    // The number is the title; the name (the design's description) is a sub heading under it.
    const number = selected.part_number || selected.item_number || '';
    const name = selected.root ? selected.description : selected.name || selected.description;
    const text = el('div', 'pub-props-text');
    text.appendChild(el('h3', 'pub-props-title', number || selected.title));
    if (number && name) text.appendChild(el('p', 'pub-props-subtitle', name));
    head.appendChild(text);
    const state = changeState(compare);
    if (compare && PILLS[state]) {
      const pill = el('span', 'pub-pill pub-pill-' + state, PILLS[state].text);
      pill.title = PILLS[state].title;
      head.appendChild(pill);
    }
    if (pickedCandidate(compare)) {
      const change = el('button', 'pub-fm-change', 'Change');
      change.type = 'button';
      change.title = 'Choose a different Fusion Manage item';
      change.addEventListener('click', function () { changing[choiceKey(selected)] = true; paint(); });
      head.appendChild(change);
    }
    return head;
  }

  function paint() {
    if (!selected) return;
    pane.textContent = '';
    const compare = compareOf(selected);
    pane.appendChild(headCard(compare));
    const picked = pickedCandidate(compare);
    if (picked && !needsPick(compare, selected)) {
      const note = el('div', 'pub-dup-note');
      note.appendChild(el('strong', '', compare.fm.candidates.length + ' Fusion Manage items share ' + compare.fm.item_number));
      note.appendChild(el('span', '', 'Publishing to: ' + picked.descriptor));
      pane.appendChild(note);
    }
    if (needsPick(compare, selected)) {   // only the question, nothing else
      pane.appendChild(pickerCard(compare.fm, selected));
      return;
    }
    let content;
    if (compare) {
      content = propertiesCard(compare);
    } else if (errorOf(selected)) {
      content = ui.errorState(errorOf(selected), retry);
    } else {
      content = el('div', 'card pub-props-wait');
      content.appendChild(ui.loaderNode());
    }
    pane.appendChild(section('Properties', content));
  }

  // ---- Opening, closing and feeding the pane -------------------------------------

  /** Show a component (a row of the bill of materials, or the design itself). */
  function open(item) {
    selected = item;
    $('pub-detail').hidden = false;
    $('pub-backdrop').hidden = false;
    loadThumbnail(item);   // before the first paint, so the skeleton is there from the start
    paint();
    if (item.root) hooks.onRootLoad(); else load(item);   // the design's own properties are read by publish.js, once
  }

  function close() {
    selected = null;
    $('pub-detail').hidden = true;
    $('pub-backdrop').hidden = true;
    pane.textContent = '';
    ns.bomTable.select(null);
  }

  /** The design's own properties have been read. */
  function setRoot(compare) {
    rootCompare = compare;
    rootError = '';
    if (selected) paint();
  }

  function setRootError(message) {
    rootError = message;
    if (selected) paint();
  }

  /** Forget everything read for the previous design. ``skipCache`` makes components skip the cached copy. */
  function reset(skipCache) {
    close();
    rootCompare = null;
    rootError = '';
    force = !!skipCache;
    [compares, errors, loading, thumbs].forEach(function (map) {
      Object.keys(map).forEach(function (id) { delete map[id]; });
    });
  }

  const MIN_WIDTH = 260;        // narrowest the pane can be dragged to
  const MIN_BOM_WIDTH = 240;    // room always left for the bill of materials

  /** Drag the pane's left edge to change its width; arrow keys nudge it, double-click restores the default. */
  function initResize() {
    const pane0 = $('pub-detail');
    const handle = $('pub-detail-resize');
    function setWidth(w) {
      const max = Math.max(MIN_WIDTH, pane0.parentElement.getBoundingClientRect().width - MIN_BOM_WIDTH);
      pane0.style.flexBasis = Math.min(max, Math.max(MIN_WIDTH, w)) + 'px';
    }
    let startX = 0;
    let startWidth = 0;
    handle.addEventListener('pointerdown', function (e) {
      startX = e.clientX;
      startWidth = pane0.getBoundingClientRect().width;
      handle.setPointerCapture(e.pointerId);
      handle.classList.add('dragging');
    });
    handle.addEventListener('pointermove', function (e) {
      if (handle.hasPointerCapture(e.pointerId)) setWidth(startWidth + startX - e.clientX);
    });
    handle.addEventListener('pointerup', function () { handle.classList.remove('dragging'); });
    handle.addEventListener('dblclick', function () { pane0.style.flexBasis = ''; });
    handle.addEventListener('keydown', function (e) {
      const step = e.key === 'ArrowLeft' ? 20 : e.key === 'ArrowRight' ? -20 : 0;
      if (!step) return;
      e.preventDefault();
      setWidth(pane0.getBoundingClientRect().width + step);
    });
  }

  function init(options) {
    hooks = options;
    pane = $('pub-props');
    $('pub-detail-close').addEventListener('click', close);
    initResize();
    $('pub-backdrop').addEventListener('click', close);   // only drawn in the small layout, where the details are a popup
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && selected) close(); });
  }

  ns.pubDetails = {
    init: init, open: open, reset: reset, setRoot: setRoot, setRootError: setRootError,
    handleComponent: handleComponent, handleThumbnail: handleThumbnail, setThumbnail: setThumbnail, choiceFor: choiceFor,
  };
})(window.MfgUi);
