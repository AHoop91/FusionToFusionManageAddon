/**
 * Publish Item panel: the Details Panel beside the bill of materials, as ``ns.pubDetails``.
 *
 * It shows one line at a time (opened by the magnifier of a line of the structure viewer, or for the design itself), then keeps what it read. The
 * Overview tab decides from the comparison with Fusion Manage whether the item exists: when no item has the number it says so and shows the properties
 * that publishing would send (no other tab); when one does, it shows the comparison and a tab strip, with the item's own tabs beside it (``ITEM_TABS``:
 * Item details, then Attachments). A line with no Fusion Component (one only Fusion Manage has, or one added) has no comparison, only the item's tabs when it has an item.
 * The design's own properties are read by publish.js, when they are first opened, and handed in with ``setRoot``.
 *
 * ``open(line)`` takes ``{id, root, item_number, part_number, description, name, title}`` as ``bomModel.lineComponent`` makes it, with, from the viewer,
 * ``key`` and ``pane`` (the line to mark), ``itemId`` (the Fusion Manage item, when known) and ``noComponent``.
 *
 * ``init`` takes: ``request(slot, payload)`` to ask Python for a component, an item's tabs or an item's view (its sections of fields),
 * ``onRootLoad()`` when the design is opened (read its properties unless that is done or under way),
 * ``onRootRetry()`` to read the design's properties again,
 * ``onClose()`` when the panel closes, or is opened for something that is not a line of the viewer (its mark goes).
 */
(function (ns) {
  'use strict';

  const $ = ns.$;
  const ui = ns.pubUi;
  const el = ui.el;
  function t(key, params) { return ns.i18n.t(key, params); }

  // Tooltip per property status (the dot at the right of a property).
  function statusTexts() {
    return {
      match:     t('publish.prop_match'),
      mismatch:  t('publish.prop_mismatch'),
      new:       t('publish.prop_new'),
      unknown:   t('publish.prop_unknown'),
      multiple:  t('publish.prop_multiple'),
      unchecked: t('publish.prop_unchecked'),
    };
  }

  // The pill at the top right of the component title: what publishing would do.
  function pills() {
    const texts = statusTexts();
    return {
      new:      { text: t('publish.pill_new'), title: texts.new },
      mismatch: { text: t('publish.pill_update'), title: t('publish.pill_update_title') },
      match:    { text: t('publish.pill_up_to_date'), title: texts.match },
      multiple: { text: t('publish.pill_shared'), title: texts.multiple },
      unknown:  { text: t('publish.pill_error'), title: t('publish.pill_error_title') },
    };
  }

  let hooks = null;
  let pane = null;
  let selected = null;          // component whose details are open
  let rootCompare = null;       // comparison for the open design's own properties
  let rootError = '';           // why they could not be read
  let force = false;            // skip the cached copy when reading components
  const compares = {};          // component id -> comparison
  const errors = {};            // component id -> message
  const loading = {};           // component id -> true while being read
  const collapsed = {};         // sub header -> true while collapsed; kept across components
  const NEW_WIDTHS = [30, 62, 8];   // Property, Fusion, status: the table of a component with no item has no Fusion Manage column
  const DEFAULT_WIDTHS = [24, 34, 34, 8];   // Property, Fusion, Fusion Manage, status: Fusion and Fusion Manage share the room equally
  const MIN_COLUMN_PCT = 12;
  const colWidths = DEFAULT_WIDTHS.slice();   // as dragged
  const thumbs = {};            // component id -> thumbnail url ('' none, null while being read)
  const itemTabs = {};          // Fusion Manage item id -> its tabs (``item_tabs``: workspace_id, item_id, item_urn, tabs) and the ``stamp`` it was read under
  const itemTabErrors = {};     // item id -> message
  const itemTabLoading = {};    // item id -> true while being read
  const itemViews = {};         // item id -> the item as the Item panel lays it out (``item_view``: sections of fields and matrices)
  const itemViewErrors = {};    // item id -> message
  const itemViewLoading = {};   // item id -> true while being read
  const pictures = {};          // picture link -> its data uri ('' none), once read
  const pictureWaiting = {};    // picture link -> the ``done`` callbacks of the image fields that wait for it
  let drawn = {};               // item tab key -> the item id whose content it holds (read once per item and line opened)
  let tabItem = '';             // the item whose tabs the strip shows, '' when it is hidden

  /** The tabs of an item, beside Overview. The keys are the keys of ``item_tabs``' ``tabs`` (item, files, bom, whereused, workflows, changelog). A tab is one button
   *  in index.html (``data-tab``), one panel there (``pubtab-<key>``, holding a ``pub-<key>`` div to draw into: the drawing sets its class) and one entry here:
   *  ``draw(target, view)`` where ``view`` is ``{workspace_id, item_id, stamp, item_urn}``. */
  const ITEM_TABS = {
    item: { draw: function (target, view) { drawItemView(target, view.item_id); } },
    files: { draw: function (target, view) { ns.itemFiles.render(target, view, ns.itemFiles.open, ns.itemFiles.NO_TOOLS); } },
  };

  function compareOf(item) { return item.noComponent ? undefined : item.root ? rootCompare : compares[item.id]; }

  /** The Fusion Manage item a line is: the one the viewer knows, else the one the comparison found. */
  function itemIdOf(item, compare) {
    return item.itemId || (compare && compare.fm && compare.fm.state === 'found' ? compare.fm.item_id : '');
  }

  /** Why a component's details could not be read: the design's own properties fail separately from the rest. */
  function errorOf(item) { return (item.root && rootError) || errors[item.id] || ''; }

  /** True when several Fusion Manage items carry the component's item number: it cannot be published until that is fixed in Fusion Manage. */
  function isShared(compare) {
    return !!(compare && compare.fm && compare.fm.state === 'multiple');
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
      section: 'component', id: item.id, force: skipCache || force,
      item_number: item.item_number, part_number: item.part_number, description: item.description,
    });
  }

  /** The answer for a component read by ``load``. */
  function handleComponent(id, entry) {
    loading[id] = false;
    if (entry.ok) {
      compares[id] = entry.data.compare;
    } else {
      errors[id] = entry.message || t('publish.unknown_error');
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

  // ---- Reading an item's tabs ---------------------------------------------------

  function loadItemTabs(itemId, skipCache) {
    if (!itemId || itemTabs[itemId] || itemTabLoading[itemId] || itemTabErrors[itemId]) return;   // read, under way, or failed (Retry asks again)
    itemTabLoading[itemId] = true;
    hooks.request('item_tabs:' + itemId, { section: 'item_tabs', id: itemId, force: skipCache || force });
  }

  /** The answer for an item's tabs read by ``loadItemTabs``. */
  function handleItemTabs(itemId, entry) {
    if (!itemTabLoading[itemId]) return;   // asked before ``reset``: not wanted
    itemTabLoading[itemId] = false;
    if (entry.ok) {
      delete itemTabErrors[itemId];
      itemTabs[itemId] = Object.assign({}, entry.data, { stamp: entry.stamp });
    } else {
      itemTabErrors[itemId] = entry.message || t('publish.unknown_error');
    }
    paint();
  }

  // ---- Reading an item's fields (the Item details tab) ---------------------------

  /** Ask for the item's sections the first time its tab is opened, once for the design (Refresh forgets them). */
  function loadItemView(itemId, skipCache) {
    if (!itemId || itemViews[itemId] || itemViewLoading[itemId]) return;
    itemViewLoading[itemId] = true;
    delete itemViewErrors[itemId];
    hooks.request('item_view:' + itemId, { section: 'item_view', id: itemId, force: skipCache || force });
  }

  /** The answer for an item's view read by ``loadItemView``. */
  function handleItemView(itemId, entry) {
    if (!itemViewLoading[itemId]) return;   // asked before ``reset``: not wanted
    itemViewLoading[itemId] = false;
    if (entry.ok) {
      itemViews[itemId] = entry.data;
    } else {
      itemViewErrors[itemId] = entry.message || t('publish.unknown_error');
    }
    if (drawn.item === itemId) drawItemView($('pub-item'), itemId);   // the tab is still showing this item
  }

  /** A picture an image field holds, asked for once the sections are drawn (each field is a skeleton until ``done(src)`` is given the picture, or '' when it
   *  cannot be read): read once for the design, whoever waits for it is told together. */
  function loadPicture(link, done) {
    if (pictures[link] !== undefined) { done(pictures[link]); return; }
    if (pictureWaiting[link]) { pictureWaiting[link].push(done); return; }
    pictureWaiting[link] = [done];
    hooks.request('item_picture:' + link, { section: 'item_picture', id: link, force: force });
  }

  /** The answer for a picture asked for by ``loadPicture``: a picture that could not be read leaves its field empty. */
  function handlePicture(link, entry) {
    if (!pictureWaiting[link]) return;   // asked before ``reset``: not wanted
    pictures[link] = entry.ok ? entry.data.image : '';
    const waiting = pictureWaiting[link];
    delete pictureWaiting[link];
    waiting.forEach(function (done) { done(pictures[link]); });
  }

  /** The Item details tab: the item's sections as the Item panel draws them, a loader while they are read, the error (with Retry) when they could not be.
   *  The pictures of its image fields come after (a click on one does nothing: this page has no viewer for them). */
  function drawItemView(target, itemId) {
    target.replaceChildren();
    const view = itemViews[itemId];
    $('pubtab-item').classList.remove('pub-wait-fill');
    if (view) {
      view.sections.forEach(function (section) { target.appendChild(ns.itemSections.section(section, function () {}, loadPicture)); });
      if (!view.sections.length) target.appendChild(el('p', 'muted', t('item.no_fields')));
    } else if (itemViewErrors[itemId]) {
      target.appendChild(ui.errorState(itemViewErrors[itemId], function () { loadItemView(itemId, true); drawItemView(target, itemId); }));
    } else {
      $('pubtab-item').classList.add('pub-wait-fill');   // the tab gives the loader all its room, so the balls sit in the middle of it, with no box
      target.appendChild(ui.loaderNode());
      loadItemView(itemId);
    }
  }

  function retry() {
    if (!selected) return;
    const itemId = itemIdOf(selected, compareOf(selected));
    if (itemId && itemTabErrors[itemId]) {
      delete itemTabErrors[itemId];
      loadItemTabs(itemId, true);
    }
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

  // ---- Drawing the pane -------------------------------------------------------

  /** Value cell: long text wraps, with its unit after it in a muted tone. ``shown`` is the value as Fusion Manage will hold it
   *  (a number cut to its field's digits); the tooltip is ``original`` (the Data Model's own number and unit) when there is one, else the full value. */
  function valueCell(value, shown, unit, original) {
    const text = shown || value;
    const td = el('td', text ? '' : 'muted', text || '-');
    if (text && unit) td.appendChild(el('span', 'pub-unit', ' ' + unit));
    if (original || value) td.title = original || value;
    return td;
  }

  /** Drag handle on the right edge of column ``i``: it grows or shrinks against the next column, so the table keeps its width. */
  function columnGrip(i, table, apply) {
    const grip = el('span', 'pub-cmp-grip');
    grip.title = t('publish.col_resize');
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

  /** The table of properties. With ``withFm`` it has the Fusion Manage column too, and its widths can be dragged (they stay for the next component); without
   *  (a component with no item to compare with) it has fixed widths. */
  function propertyTable(rows, withFm) {
    const table = el('table', 'pub-table pub-property-table' + (withFm ? '' : ' pub-table-new'));
    // Column widths (used in the wide layout), in percent.
    const widths = withFm ? colWidths : NEW_WIDTHS;
    const cols = el('colgroup');
    function apply() { widths.forEach(function (w, i) { cols.children[i].style.width = w + '%'; }); }
    widths.forEach(function () { cols.appendChild(el('col')); });
    apply();
    table.appendChild(cols);
    const head = el('tr');
    (withFm ? [t('publish.prop_col_property'), t('publish.col_component'), t('publish.prop_col_fm'), ''] : [t('publish.prop_col_property'), t('publish.col_component'), '']).forEach(function (h, i) {
      const th = el('th', '', h);
      if (withFm && i < 2) th.appendChild(columnGrip(i, table, apply));   // moves the edge it shares with the next column
      head.appendChild(th);
    });
    table.appendChild(head);
    const texts = statusTexts();
    rows.forEach(function (r) {
      const tr = el('tr');
      const hasFm = r.fm_field && r.fm_value;
      const cells = [[t('publish.prop_col_property'), el('td', '', r.name)],
                     [t('publish.col_component'), valueCell(r.value, r.shown, r.unit, r.original)]];
      if (withFm) cells.push([t('publish.prop_col_fm'), valueCell(hasFm ? r.fm_value : '', '', r.unit)]);
      cells.forEach(function (c) {
        c[1].setAttribute('data-label', c[0]);
        tr.appendChild(c[1]);
      });
      const text = texts[r.status] || texts.unknown;
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

  /** Properties of one component, as they would be published. ``withFm`` (false for a component with no item) leaves out the Fusion Manage column and message. */
  function propertiesCard(compare, withFm) {
    const card = el('div', 'card');
    if (!compare.rows.length) {
      card.appendChild(el('p', 'muted', t('publish.prop_none')));
      return card;
    }
    if (withFm && compare.fm.message) {
      card.appendChild(el('p', compare.fm.state === 'unknown' ? 'pub-error' : 'muted', compare.fm.message));
    }
    const mapped = compare.rows.filter(function (r) { return r.status !== 'unmapped'; });
    if (mapped.length) card.appendChild(propertyTable(mapped, withFm));
    else card.appendChild(el('p', 'muted', t('publish.prop_none_mapped')));
    return card;
  }

  /** Several Fusion Manage items carry the item number: list them, and say the number has to be fixed in Fusion Manage. */
  function sharedCard(fm) {
    const card = el('div', 'card pub-pick-card');
    card.appendChild(el('h4', 'pub-pick-title', t('publish.shared_title')));
    card.appendChild(el('p', 'muted', t('publish.shared_text', { count: fm.candidates.length, number: fm.item_number })));
    fm.candidates.forEach(function (c) {
      const line = el('div', 'pub-fm-choice', c.descriptor);
      line.title = c.descriptor;
      card.appendChild(line);
    });
    return card;
  }

  /** No Fusion Manage item has the component's item number: say so, and what publishing would do. */
  function noItemCard(fm) {
    const card = el('div', 'card pub-pick-card');
    card.appendChild(el('h4', 'pub-pick-title', t('publish.detail_no_item_title')));
    card.appendChild(el('p', 'muted', t('publish.detail_no_item_text', { number: fm.item_number })));
    return card;
  }

  /** A line that has no Fusion Component to compare with: an icon, a title and what it means, centred like the other empty states. */
  function noteCard(title, text) {
    const card = el('div', 'card pub-empty pub-note-card');
    card.appendChild(ui.svg(['M3 5h10v10H3z', 'M11 9h10v10H11z', 'M4 20L20 4'], 48));   // two squares with nothing between them
    card.appendChild(el('h4', 'pub-pick-title', title));
    card.appendChild(el('p', 'muted', text));
    return card;
  }

  /** The shape of ``noteCard`` while it waits: a round icon, a title and two lines of text, as bars with the sweep of the other skeletons. */
  function noteSkeleton() {
    const card = el('div', 'card pub-empty pub-note-card');
    card.setAttribute('role', 'status');
    card.setAttribute('aria-label', t('publish.loading_aria'));
    card.appendChild(el('span', 'pub-skel pub-note-skel-icon'));
    card.appendChild(el('span', 'pub-skel pub-note-skel-title'));
    card.appendChild(el('span', 'pub-skel pub-note-skel-line'));
    card.appendChild(el('span', 'pub-skel pub-note-skel-line pub-note-skel-short'));
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

  /** The thumbnail of the header: a skeleton while it loads, nothing (null) when the component has none. */
  function thumbBox() {
    let url = selected.id ? thumbs[selected.id] : '';
    if (selected.root && url === undefined) url = null;   // the top bar is still reading it
    if (url !== null && !url) return null;
    const thumb = el('div', 'pub-props-thumb' + (url === null ? ' pub-thumb-loading' : ''));
    // Only http(s) URLs, so nothing else is ever loaded into the style.
    if (url && /^https?:\/\//i.test(url)) thumb.style.backgroundImage = 'url("' + url.replace(/"/g, '%22') + '")';
    return thumb;
  }

  /** The number is the title; the name (the design's description) is a sub heading under it. */
  function titleBlock() {
    const number = selected.item_number || selected.part_number || '';   // the item number is the master; the part number only stands in when there is none
    const name = selected.root ? selected.description : selected.name || selected.description;
    const text = el('div', 'pub-props-text');
    text.appendChild(el('h3', 'pub-props-title', number || selected.title));
    if (number && name) text.appendChild(el('p', 'pub-props-subtitle', name));
    return text;
  }

  /** The state pill, in the top right corner. */
  function stateSide(state, pillOf) {
    const side = el('div', 'pub-props-side');
    const pill = el('span', 'pub-state pub-state-' + state);
    pill.appendChild(el('span', 'pub-state-dot'));
    pill.appendChild(el('span', 'pub-state-label', pillOf.text));
    const info = el('span', 'pub-state-info');   // the small "i" says there is a tooltip to read
    info.appendChild(ui.svg(['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', 'M12 11v6', 'M12 7.5v.5']));
    pill.appendChild(info);
    pill.title = pillOf.title;
    side.appendChild(pill);
    return side;
  }

  /** Header: the component's thumbnail, number and name, the state pill and, once an item is chosen among several, a Change button. */
  function headCard(compare) {
    const head = el('div', 'pub-props-head');
    const thumb = thumbBox();
    if (thumb) head.appendChild(thumb);
    head.appendChild(titleBlock());
    const state = changeState(compare);
    const pillOf = pills()[state];
    if (compare && pillOf) head.appendChild(stateSide(state, pillOf));
    return head;
  }

  /** The Properties section of a line the comparison has not answered yet: its error, or a loader. */
  function waitingSection() {
    let content;
    if (errorOf(selected)) {
      content = ui.errorState(errorOf(selected), retry);
    } else {
      content = el('div', 'card pub-props-wait');
      content.appendChild(ui.loaderNode());
    }
    return section(t('publish.properties'), content);
  }

  /** The Overview tab: what is known of the line against Fusion Manage. Whether an item exists is the comparison's ``fm.state`` (new: none; found: one; multiple:
   *  several share the number) or, for a line the viewer knows the item of, ``selected.itemId``, which is never called "no item". */
  function paintDetails(compare) {
    const known = !!selected.itemId;
    if (selected.noComponent) {
      // A line with an item shows its card with the tabs, so it waits for them: a skeleton until they are read (or failed, which is said under the card).
      if (known && !itemTabs[selected.itemId] && !itemTabErrors[selected.itemId]) { pane.appendChild(noteSkeleton()); return; }
      pane.appendChild(known ? noteCard(t('publish.detail_no_component_title'), t('publish.detail_no_component'))
                             : noteCard(t('publish.detail_no_component_new_title'), t('publish.detail_no_component_new')));
      return;
    }
    if (!compare) {
      pane.appendChild(waitingSection());
      return;
    }
    if (isShared(compare)) {   // only the explanation, nothing else
      pane.appendChild(sharedCard(compare.fm));
      return;
    }
    if (compare.fm.state === 'new' && !known) {
      pane.appendChild(noItemCard(compare.fm));
      pane.appendChild(section(t('publish.properties'), propertiesCard(compare, false)));
      return;
    }
    // the old view; also the message of an unknown or unchecked line
    pane.appendChild(section(t('publish.properties'), propertiesCard(compare, true)));
  }

  /** The strip beside Overview, shown once the item's tabs are read: a tab is hidden when the workspace has none, and disabled when the user may not use it. */
  function labelTabs(data) {
    Object.keys(ITEM_TABS).forEach(function (key) {
      const tab = data.tabs[key];
      const button = $('pub-tabs').querySelector('[data-tab="' + key + '"]');
      button.hidden = !tab;
      if (tab) ns.itemTree.labelTab(button, tab);
    });
  }

  function selectOverviewTab() { $('pub-tabs').querySelector('[data-tab="overview"]').click(); }

  /** Show the strip when the line has an item whose tabs are read; read them first. Until then, or on a failure (said under the overview), only Overview shows. */
  function paintTabs(itemId) {
    const data = itemId ? itemTabs[itemId] : null;
    if (itemId) loadItemTabs(itemId);
    if (itemId && itemTabErrors[itemId]) pane.appendChild(ui.errorState(t('publish.detail_tabs_error', { error: itemTabErrors[itemId] }), retry));
    $('pub-tabs').closest('.tabs-scroller').hidden = !data;
    $('pub-tabs-skel').hidden = !(itemId && !data && !itemTabErrors[itemId]);   // bars where the strip will be, until the tabs are read (or failed)
    tabItem = data ? itemId : '';
    if (data) labelTabs(data);
    else selectOverviewTab();   // nothing else to be on
  }

  function paint() {
    if (!selected) return;
    pane.textContent = '';
    const compare = compareOf(selected);
    pane.appendChild(headCard(compare));
    paintDetails(compare);
    paintTabs(itemIdOf(selected, compare));   // '' for a line with no item (no number found, or shared): no strip
  }

  /** A tab of the item was opened: draw it, once for each item (Refresh forgets what was read). */
  function drawTab(key) {
    if (!tabItem || drawn[key] === tabItem) return;
    drawn[key] = tabItem;
    const data = itemTabs[tabItem];
    ITEM_TABS[key].draw($('pub-' + key), { workspace_id: data.workspace_id, item_id: data.item_id, stamp: data.stamp, item_urn: data.item_urn });
  }

  /** Nothing of the item's tabs is kept on screen, and what they were reading is cancelled. */
  function leaveTabs() {
    ns.itemTree.leave('files');
    drawn = {};
    Object.keys(ITEM_TABS).forEach(function (key) { $('pub-' + key).replaceChildren(); });
    $('pubtab-item').classList.remove('pub-wait-fill');
  }

  // ---- Opening, closing and feeding the pane -------------------------------------

  /** Show a component (a row of the bill of materials, or the design itself). */
  function open(item) {
    if (!item.pane && selected && selected.pane) hooks.onClose();   // not opened from a line of the viewer: the mark of the last one goes
    leaveTabs();
    selected = item;
    $('pub-detail').hidden = false;
    $('pub-backdrop').hidden = false;
    selectOverviewTab();
    loadThumbnail(item);   // before the first paint, so the skeleton is there from the start (a line with no component has none)
    paint();
    if (item.root) hooks.onRootLoad(); else if (item.id) load(item);   // the design's own properties are read by publish.js, once
  }

  function close() {
    selected = null;
    $('pub-detail').hidden = true;
    $('pub-backdrop').hidden = true;
    pane.textContent = '';
    leaveTabs();
    $('pub-tabs').closest('.tabs-scroller').hidden = true;
    $('pub-tabs-skel').hidden = true;
    tabItem = '';
    hooks.onClose();
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
    [compares, errors, loading, thumbs, itemTabs, itemTabErrors, itemTabLoading, itemViews, itemViewErrors, itemViewLoading, pictures, pictureWaiting].forEach(function (map) {
      Object.keys(map).forEach(function (id) { delete map[id]; });
    });
  }

  const MIN_WIDTH = 340;        // narrowest the pane can be dragged to (the CSS minimum of ``.pub-detail``)
  const MIN_BOM_WIDTH = 240;    // room always left for the bill of materials

  /** Drag the pane's left edge to change its width; arrow keys nudge it, double-click restores the default. */
  function initResize() {
    const box = $('pub-detail');
    const handle = $('pub-detail-resize');
    function setWidth(w) {
      const max = Math.max(MIN_WIDTH, box.parentElement.getBoundingClientRect().width - MIN_BOM_WIDTH);
      box.style.flexBasis = Math.min(max, Math.max(MIN_WIDTH, w)) + 'px';
    }
    let startX = 0;
    let startWidth = 0;
    handle.addEventListener('pointerdown', function (e) {
      startX = e.clientX;
      startWidth = box.getBoundingClientRect().width;
      handle.setPointerCapture(e.pointerId);
      handle.classList.add('dragging');
    });
    handle.addEventListener('pointermove', function (e) {
      if (handle.hasPointerCapture(e.pointerId)) setWidth(startWidth + startX - e.clientX);
    });
    handle.addEventListener('pointerup', function () { handle.classList.remove('dragging'); });
    handle.addEventListener('dblclick', function () { box.style.flexBasis = ''; });
    handle.addEventListener('keydown', function (e) {
      const step = e.key === 'ArrowLeft' ? 20 : e.key === 'ArrowRight' ? -20 : 0;
      if (!step) return;
      e.preventDefault();
      setWidth(box.getBoundingClientRect().width + step);
    });
  }

  function init(options) {
    hooks = options;
    pane = $('pubtab-overview');
    ns.tabs.setup('#pub-tabs', 'tab', 'pubtab-');
    $('pub-tabs').closest('.tabs-scroller').hidden = true;   // until an item's tabs are read
    Object.keys(ITEM_TABS).forEach(function (key) {
      $('pub-tabs').querySelector('[data-tab="' + key + '"]').addEventListener('click', function () { drawTab(key); });   // after the strip showed its panel
    });
    $('pub-detail-close').addEventListener('click', close);
    initResize();
    $('pub-backdrop').addEventListener('click', close);   // only drawn in the small layout, where the details are a popup
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && selected) close(); });
  }

  ns.pubDetails = {
    init: init, open: open, reset: reset, setRoot: setRoot, setRootError: setRootError,
    handleComponent: handleComponent, handleThumbnail: handleThumbnail, setThumbnail: setThumbnail, handleItemTabs: handleItemTabs, handleItemView: handleItemView, handlePicture: handlePicture, close: close,
  };
})(window.MfgUi);
