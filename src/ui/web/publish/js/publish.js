/**
 * Publish Item panel: summary, properties and bill of materials of the open
 * model.
 */
(function (ns) {
  'use strict';

  const $ = ns.$;
  const bridge = ns.bridge;

  /** Build an element. Text is set with textContent, so nothing is parsed as HTML. */
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function line(label, value) {
    const row = el('div', 'pub-line');
    row.appendChild(el('span', 'pub-label', label));
    row.appendChild(el('span', 'pub-value', value));
    return row;
  }

  // ---- Model: summary, properties, bill of materials --------------------------

  const POLL_INTERVAL_MS = 700;

  function setSummary(children) {
    const box = $('pub-summary');
    box.textContent = '';
    children.forEach(function (c) { box.appendChild(c); });
  }

  function setThumbnail(url) {
    // Only http(s) URLs, so nothing else is ever loaded into the style.
    $('pub-thumb').style.backgroundImage = /^https?:\/\//i.test(url) ? 'url("' + url.replace(/"/g, '%22') + '")' : '';
  }

  function clearPanel(id) {
    const host = $(id);
    host.classList.remove('pub-loading');
    host.textContent = '';
    return host;
  }

  function panelMessage(id, text, isError) {
    const host = clearPanel(id);
    const card = el('div', 'card');
    card.appendChild(el('p', isError ? 'pub-error' : 'muted', text));
    host.appendChild(card);
  }

  const STATUS = {
    match:    { mark: '✓', text: 'Matches Fusion Manage' },
    mismatch: { mark: '≠', text: 'Differs: publishing will update Fusion Manage' },
    new:      { mark: '+', text: 'No Fusion Manage item yet: publishing will create it' },
    unknown:  { mark: '?', text: 'Fusion Manage value could not be read' },
    multiple: { mark: '?', text: 'Several Fusion Manage items match: choose one' },
    unchecked: { mark: '·', text: 'Mapped: Fusion Manage is not checked yet' },
    unmapped: { mark: '–', text: 'Not mapped: not published' },
  };

  /** The Fusion Manage item chosen among several that share the item number, if any. */
  function pickedCandidate(compare) {
    const fm = compare && compare.fm;
    return fm && fm.candidates ? fm.candidates.filter(function (c) { return c.id === fm.item_id; })[0] : undefined;
  }

  /** Properties of one component, as they would be published. */
  function propertiesCard(compare, item) {
    const card = el('div', 'card');
    if (!compare.rows.length) {
      card.appendChild(el('p', 'muted', 'This item has no properties.'));
      return card;
    }
    if (!pickedCandidate(compare) && compare.fm.message) {
      card.appendChild(el('p', compare.fm.state === 'unknown' ? 'pub-error' : 'muted', compare.fm.message));
    }
    const mapped = compare.rows.filter(function (r) { return r.status !== 'unmapped'; });
    if (mapped.length) {
      card.appendChild(propertyTable(mapped));
    } else {
      card.appendChild(el('p', 'muted', 'No properties are mapped to Fusion Manage. Map fields in Settings.'));
    }
    return card;
  }

  const fmChoice = {};   // item number -> Fusion Manage item id the user picked

  function choiceKey(item) { return item.item_number || item.part_number || ''; }

  const fmChanging = {};   // item number -> true while the user re-picks an already chosen item

  /** True when the component must show the "which Fusion Manage item" question instead of its properties. */
  function needsPick(compare, item) {
    const fm = compare && compare.fm;
    return !!(fm && fm.candidates && fm.candidates.length && (fm.state === 'multiple' || fmChanging[choiceKey(item)]));
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
      button.addEventListener('click', function () { chooseItem(item, c.id); });
      card.appendChild(button);
    });
    if (fm.state !== 'multiple') {
      const cancel = el('button', 'pub-drawing-open pub-retry', 'Cancel');
      cancel.type = 'button';
      cancel.addEventListener('click', function () { delete fmChanging[choiceKey(item)]; paintProps(); });
      card.appendChild(cancel);
    }
    return card;
  }

  /** Remember the picked Fusion Manage item and compare again with it. */
  function chooseItem(item, itemId) {
    fmChoice[choiceKey(item)] = itemId;
    delete fmChanging[choiceKey(item)];
    paintValidation();
    if (item.root) {
      rootCompare = null;
      inflight.properties = true;
      bridge.send('load_publish_section', { section: 'properties', force: true, fm_item: itemId });
      if (loaded.structure) {   // the BOM is compared against the chosen item's
        inflight.structure = true;
        tabLoading('pub-tab-bom');   // not the old comparison while the new one loads
        bridge.send('load_publish_section', { section: 'structure', force: true, fm_item: itemId });
      }
    } else {
      delete componentCompare[item.id];
      inflight['component:' + item.id] = false;
      requestComponent(item, true);
    }
    paintProps();
  }

  /** Value cell: one line, cut with an ellipsis when long (the full text is the tooltip). */
  function valueCell(value) {
    const td = el('td', 'pub-cut' + (value ? '' : ' muted'), value || '-');
    if (value) td.title = value;
    return td;
  }

  function propertyTable(rows) {
    const t = el('table', 'pub-table pub-property-table');
    // Column widths (used in the wide layout): Fusion Manage starts about two thirds across.
    const cols = el('colgroup');
    ['25%', '40%', '27%', '8%'].forEach(function (w) {
      const col = document.createElement('col');
      col.style.width = w;
      cols.appendChild(col);
    });
    t.appendChild(cols);
    const head = el('tr');
    const headers = ['Property', 'Value', 'Fusion Manage', ''];
    headers.forEach(function (h) { head.appendChild(el('th', '', h)); });
    t.appendChild(head);
    rows.forEach(function (r) {
      const tr = el('tr');
      const cells = [['Property', el('td', '', r.name)],
        ['Value', valueCell(r.value)],
        ['Fusion Manage', el('td', r.fm_field && r.fm_value ? '' : 'muted', r.fm_field && r.fm_value ? r.fm_value : '-')]];
      cells.forEach(function (c) { c[1].setAttribute('data-label', c[0]); tr.appendChild(c[1]); });
      const status = STATUS[r.status] || STATUS.unknown;
      const cell = el('td', 'pub-status pub-status-' + r.status);
      const mark = el('span', 'pub-mark');
      mark.title = status.text;
      mark.setAttribute('aria-label', status.text);
      cell.appendChild(mark);
      tr.appendChild(cell);
      t.appendChild(tr);
    });
    return t;
  }

  // Which sections each tab needs, and which panels wait on each section. The
  // bill of materials tree is loaded once and shared by both tabs.
  const TAB_SECTIONS = { details: ['properties', 'structure'], bom: ['structure'] };
  const SECTION_PANELS = { properties: ['pub-tab-details'], structure: ['pub-tab-details', 'pub-tab-bom'] };

  let rootCompare = null;       // comparison for the open design's own properties
  let structureRows = null;     // the BOM tree rows, already compared with Fusion Manage
  let structurePick = false;    // the design matches several Fusion Manage items and none is chosen yet
  let selectedItem = null;      // component chosen on the Details tab
  let propsPane = null;
  let forceComponents = false;
  const componentCompare = {};  // component id -> comparison
  const componentError = {};    // component id -> message
  const componentDrawings = {}; // component id -> drawings of its primary model

  /** The pill at the top right of the component title: what publishing would do. */
  const PILLS = {
    new:      { text: 'New', title: 'No Fusion Manage item yet: publishing will create it' },
    mismatch: { text: 'Update', title: 'Publishing will update the Fusion Manage item' },
    match:    { text: 'Up to date', title: 'Matches Fusion Manage' },
    multiple: { text: 'Choose item', title: 'Several Fusion Manage items match: choose one' },
    unknown:  { text: 'Error', title: 'Fusion Manage could not be read' },
  };

  /** One state for a component: does publishing change anything in Fusion Manage? */
  function changeState(compare) {
    if (!compare) return 'unchecked';
    const states = compare.rows.map(function (r) { return r.status; });
    const first = ['mismatch', 'new', 'multiple', 'unknown'].filter(function (st) { return states.indexOf(st) >= 0; })[0];
    if (first) return first;
    return states.indexOf('match') >= 0 ? 'match' : 'unchecked';
  }

  let listMarks = [];   // [{item, node}] for the end-of-row change indicators
  let validation = null;    // Fusion Manage search of every item number: {running, done, total, results}
  const listFilters = {};   // group -> true while its checkbox is ticked
  let listButtons = [];     // [{item, button, option}] for filtering

  /** State of a component before it is opened: the quick search result, if there is one. */
  function quickState(item) {
    const r = validation && validation.results[choiceKey(item)];
    if (!r) return 'unchecked';
    return { new: 'new', multiple: 'multiple', unknown: 'unknown' }[r.state] || 'unchecked';
  }

  /** True while an item number matches several Fusion Manage items and none is chosen yet. */
  function isDuplicate(item) {
    const r = validation && validation.results[choiceKey(item)];
    return !!(r && r.state === 'multiple' && !fmChoice[choiceKey(item)]);
  }

  function updateMarks() {
    listMarks.forEach(function (m) {
      const compare = m.item.root ? rootCompare : componentCompare[m.item.id];
      const state = compare ? changeState(compare) : quickState(m.item);
      const status = STATUS[state];
      m.node.className = 'pub-comp-status pub-status-' + state;
      m.node.textContent = '';
      const mark = el('span', 'pub-mark');
      mark.title = state === 'unchecked' && !compare
        ? 'Open to check what would change in Fusion Manage' : status.text;
      mark.setAttribute('aria-label', mark.title);
      m.node.appendChild(mark);
    });
  }

  const collapsedSections = {};   // sub header -> true while collapsed; kept across components

  /** A sub header with a chevron that shows or hides its content. */
  function section(title, content) {
    const box = el('div', 'pub-section');
    const header = el('button', 'pub-subheading');
    header.type = 'button';
    const arrow = chevron();
    header.appendChild(arrow);
    header.appendChild(el('span', '', title));
    const body = el('div', 'pub-section-body');
    body.appendChild(content);
    function apply() {
      const closed = !!collapsedSections[title];
      body.hidden = closed;
      setChevron(arrow, closed);
      header.setAttribute('aria-expanded', String(!closed));
    }
    header.addEventListener('click', function () { collapsedSections[title] = !collapsedSections[title]; apply(); });
    apply();
    box.appendChild(header);
    box.appendChild(body);
    return box;
  }

  function paintProps() {
    if (!selectedItem || !propsPane) return;
    propsPane.textContent = '';
    const head = el('div', 'card pub-props-head');
    head.appendChild(el('h3', 'pub-props-title', selectedItem.title));
    const compare = selectedItem.root ? rootCompare : componentCompare[selectedItem.id];
    const pill = PILLS[changeState(compare)];
    if (compare && pill) {
      const tag = el('span', 'pub-pill pub-pill-' + changeState(compare), pill.text);
      tag.title = pill.title;
      head.appendChild(tag);
    }
    const picked = pickedCandidate(compare);
    if (picked) {
      const change = el('button', 'pub-fm-change', 'Change');
      change.type = 'button';
      change.title = 'Choose a different Fusion Manage item';
      change.addEventListener('click', function () { fmChanging[choiceKey(selectedItem)] = true; paintProps(); });
      head.appendChild(change);
    }
    propsPane.appendChild(head);
    if (picked && !needsPick(compare, selectedItem)) {
      const note = el('div', 'pub-dup-note');
      note.appendChild(el('strong', '', compare.fm.candidates.length + ' Fusion Manage items share ' + compare.fm.item_number));
      note.appendChild(el('span', '', 'Publishing to: ' + picked.descriptor));
      propsPane.appendChild(note);
    }
    if (needsPick(compare, selectedItem)) {   // only the question, nothing else
      propsPane.appendChild(pickerCard(compare.fm, selectedItem));
      updateMarks();
      return;
    }
    let content;
    if (compare) {
      content = propertiesCard(compare, selectedItem);
    } else if (componentError[selectedItem.id]) {
      content = errorState(componentError[selectedItem.id], retryComponent);
    } else {
      content = el('div', 'card pub-props-wait');
      content.appendChild(loaderNode());
    }
    propsPane.appendChild(section('Properties', content));
    if (compare || !componentError[selectedItem.id]) propsPane.appendChild(section('Drawings', drawingsBlock(selectedItem)));
    updateMarks();
  }

  /** Centred failure message with a warning icon and a Retry button. A timeout gets its own wording. */
  function errorState(message, onRetry) {
    const timedOut = /timed out|timeout/i.test(message || '');
    const card = el('div', 'card pub-empty pub-error-state');
    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('width', '28');
    svg.setAttribute('height', '28');
    svg.setAttribute('aria-hidden', 'true');
    // A clock for a timeout, a warning triangle for anything else.
    (timedOut ? ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', 'M12 7v5l3 2'] : ['M12 3l10 18H2z', 'M12 10v5', 'M12 18.2v.3']).forEach(function (d) {
      const path = document.createElementNS(SVG_NS, 'path');
      path.setAttribute('d', d);
      svg.appendChild(path);
    });
    card.appendChild(svg);
    card.appendChild(el('h4', 'pub-error-title', timedOut ? 'Timed out' : 'Could not load'));
    card.appendChild(el('p', 'muted', timedOut ? 'The Manufacturing Data Model took too long to respond.' : (message || 'Unknown error')));
    const retry = el('button', 'pub-drawing-open pub-retry', 'Retry');
    retry.type = 'button';
    retry.addEventListener('click', onRetry);
    card.appendChild(retry);
    return card;
  }

  /** Show a failure in the middle of a whole tab panel. */
  function panelError(id, message, onRetry) {
    const host = clearPanel(id);
    host.classList.add('pub-loading');   // a panel that fills the tab, so the message centres in it
    host.appendChild(errorState(message, onRetry));
  }

  /** Centred "nothing here" message with an empty-tray icon, in a white card. */
  function emptyState(text) {
    const card = el('div', 'card pub-empty');
    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('width', '28');
    svg.setAttribute('height', '28');
    svg.setAttribute('aria-hidden', 'true');
    // An empty tray.
    ['M3 13l3-8h12l3 8v6H3z', 'M3 13h5l1 3h6l1-3h5'].forEach(function (d) {
      const path = document.createElementNS(SVG_NS, 'path');
      path.setAttribute('d', d);
      svg.appendChild(path);
    });
    card.appendChild(svg);
    card.appendChild(el('p', 'muted', text));
    return card;
  }

  /** The drawings of a component, each with a link to its PDF. */
  function drawingsBlock(item) {
    const drawings = componentDrawings[item.id];
    if (!drawings) {
      if (componentError[item.id]) return errorState(componentError[item.id], retryComponent);
      const wait = el('div', 'card pub-props-wait pub-drawings-wait');
      wait.appendChild(loaderNode());
      return wait;
    }
    if (!drawings.length) return emptyState('No drawings for this component.');
    const card = el('div', 'card');
    const t = el('table', 'pub-table pub-drawings-table');
    const head = el('tr');
    ['Item Number', 'Name', ''].forEach(function (h) { head.appendChild(el('th', '', h)); });
    t.appendChild(head);
    drawings.forEach(function (d) {
      const tr = el('tr');
      const number = el('td', d.item_number ? '' : 'muted', d.item_number || '-');
      number.setAttribute('data-label', 'Item Number');
      const name = el('td', d.name ? '' : 'muted', d.name || '-');
      name.setAttribute('data-label', 'Name');
      const link = el('td', 'pub-drawing-cell');
      const pdf = d.files.filter(function (f) { return f.status === 'SUCCESS' && f.url; })[0];
      if (pdf) {
        const open = el('button', 'pub-drawing-open', 'Open');
        open.type = 'button';
        open.addEventListener('click', function () { bridge.send('open_url', { url: pdf.url }); });
        link.appendChild(open);
      }
      [number, name, link].forEach(function (td) { tr.appendChild(td); });
      t.appendChild(tr);
    });
    card.appendChild(t);
    return card;
  }

  function retryComponent() {
    if (!selectedItem) return;
    componentError[selectedItem.id] = '';
    inflight['component:' + selectedItem.id] = false;
    selectComponent(selectedItem);
  }

  /** A component's properties are read when it is clicked, then kept. */
  function selectComponent(item) {
    selectedItem = item;
    paintProps();
    requestComponent(item, forceComponents);
  }

  function requestComponent(item, force) {
    const slot = 'component:' + item.id;
    if (!item.id || componentCompare[item.id] || inflight[slot]) return;
    inflight[slot] = true;
    componentError[item.id] = '';
    clearTimeout(timers[slot]);
    bridge.send('load_publish_section', {
      section: 'component', id: item.id, force: force, fm_item: fmChoice[choiceKey(item)] || '',
      item_number: item.item_number, part_number: item.part_number, description: item.description,
    });
  }

  /** Component list (this design, then the BOM tree) beside the selected one's properties. */
  function renderProperties() {
    const host = clearPanel('pub-tab-details');
    const root = currentSummary || {};
    const seen = {};   // a part used in several places is listed once
    const items = [{ id: root.component_id || '', root: true, item_number: root.item_number, part_number: root.part_number, title: [root.part_number, root.description].filter(Boolean).join(' - ') || 'This design' }]
      .concat(structureRows.filter(function (b) {
        if (!b.id || seen[b.id]) return false;   // rows only Fusion Manage has (extra) have no component
        seen[b.id] = true;
        return true;
      }).map(function (b) {
        return { id: b.id, title: [b.part_number, b.name].filter(Boolean).join(' - '),
                 item_number: b.item_number, part_number: b.part_number, description: b.description };
      }));
    listMarks = [];
    listButtons = [];

    const list = el('div', 'pub-components');
    propsPane = el('div', 'pub-props');
    // Narrow view: the list becomes this picklist.
    const pick = el('select', 'pub-pick');
    pick.setAttribute('aria-label', 'Component');
    items.forEach(function (item, i) {
      pick.appendChild(el('option', '', item.title));
      pick.lastChild.value = String(i);
    });
    pick.addEventListener('change', function () { list.querySelectorAll('.pub-comp')[Number(pick.value)].click(); });
    list.appendChild(el('div', 'pub-comp-heading', 'Components (' + items.length + ')'));
    validationBox = el('div', 'pub-validation');
    list.appendChild(validationBox);
    items.forEach(function (item, i) {
      const button = el('button', 'pub-comp' + (item.root ? ' pub-comp-root' : ''));
      button.type = 'button';
      const name = el('span', 'pub-comp-name', item.title);
      name.title = item.title;
      button.appendChild(name);
      const mark = el('span');
      button.appendChild(mark);
      listMarks.push({ item: item, node: mark });
      button.addEventListener('click', function () {
        list.querySelectorAll('.pub-comp').forEach(function (b) { b.classList.remove('active'); });
        button.classList.add('active');
        pick.value = String(i);
        selectComponent(item);
      });
      list.appendChild(button);
      listButtons.push({ item: item, button: button, option: pick.children[i] });
      if (i === 0) button.click();
    });

    const split = el('div', 'pub-split');
    split.appendChild(pick);
    split.appendChild(list);
    split.appendChild(propsPane);
    host.appendChild(split);
    updateMarks();
    paintValidation();
    startValidation(items, false);
  }

  let validationBox = null;
  let validationTimer = null;

  /** Search Fusion Manage for every distinct item number of the list, with progress. */
  function startValidation(items, force) {
    if (!force && validation) return;
    validation = null;
    clearTimeout(validationTimer);
    const numbers = items.map(choiceKey).filter(Boolean);
    bridge.send('start_fm_validation', { numbers: numbers, force: !!force });
  }

  function handleValidation(r) {
    if (!r.ok) return;
    validation = r.result;
    clearTimeout(validationTimer);
    if (validation.running) {
      validationTimer = setTimeout(function () { bridge.send('get_fm_validation'); }, POLL_INTERVAL_MS);
    }
    updateMarks();
    paintValidation();
  }

  /** Which quick-filter group an item number belongs to: duplicate, new or update (exists, so publishing updates it). */
  function groupOf(item) {
    const r = validation && validation.results[choiceKey(item)];
    if (!r) return '';
    if (r.state === 'new') return 'new';
    if (r.state === 'unknown') return '';
    return isDuplicate(item) ? 'duplicate' : 'update';
  }

  /** Progress while validating; afterwards a checkbox per group that has items (none ticked shows everything). */
  function paintValidation() {
    if (!validationBox) return;
    validationBox.textContent = '';
    if (!validation || !validation.total) { applyFilter(); return; }
    if (validation.running) {
      const bar = el('div', 'pub-progress');
      const fill = el('span');
      fill.style.width = Math.round(100 * validation.done / validation.total) + '%';
      bar.appendChild(fill);
      validationBox.appendChild(el('p', 'muted', 'Validating with Fusion Manage ' + validation.done + ' / ' + validation.total));
      validationBox.appendChild(bar);
      applyFilter();
      return;
    }
    const counts = { duplicate: 0, new: 0, update: 0 };
    listButtons.forEach(function (b) { const g = groupOf(b.item); if (g) counts[g]++; });
    const checks = el('div', 'pub-checks');
    [['duplicate', 'Duplicate'], ['new', 'New'], ['update', 'Update']].forEach(function (f) {
      if (!counts[f[0]]) { delete listFilters[f[0]]; return; }   // nothing in this group: no checkbox
      const label = el('label', 'pub-check');
      const box = document.createElement('input');
      box.type = 'checkbox';
      box.checked = !!listFilters[f[0]];
      box.addEventListener('change', function () { listFilters[f[0]] = box.checked; applyFilter(); });
      label.appendChild(box);
      label.appendChild(el('span', '', f[1] + ' (' + counts[f[0]] + ')'));
      checks.appendChild(label);
    });
    validationBox.appendChild(checks);
    if (validation.message) validationBox.appendChild(el('p', 'pub-error', validation.message));
    applyFilter();
  }

  function applyFilter() {
    const active = Object.keys(listFilters).filter(function (k) { return listFilters[k]; });
    listButtons.forEach(function (b) {
      const show = !active.length || (!validation.running && active.indexOf(groupOf(b.item)) >= 0);
      b.button.hidden = !show;
      b.option.hidden = !show;
    });
  }

  /** Draw whichever panels have everything they need. */
  function renderReady() {
    if (loaded.structure && structureRows) { renderBom(structureRows); }
    if (loaded.structure && structureRows && loaded.properties && rootCompare) renderProperties();
  }

  let currentSummary = null;   // summary of the open design, for the root of the component list

  function renderSummary(s) {
    currentSummary = s;
    setThumbnail(s.thumbnail);
    setSummary([
      line('Item Number', s.item_number || '-'),
      line('Part Number', s.part_number || '-'),
      line('Description', s.description || '-'),
    ]);
  }

  const SVG_NS = 'http://www.w3.org/2000/svg';
  const ICON_PATHS = {
    root:     ['M5 3h11l3 3v15H5z', 'M8 3v6h7V3', 'M8 21v-7h8v7'],
    assembly: ['M12 3l8 4.5v9L12 21l-8-4.5v-9z', 'M4 7.5l8 4.5 8-4.5', 'M12 12v9'],
    part:     ['M12 3l8 4.5v9L12 21l-8-4.5v-9z', 'M4 7.5l8 4.5 8-4.5', 'M12 12v9'],
  };
  const ICON_TITLE = { root: 'This design', assembly: 'Assembly', part: 'Part' };

  /** Icon in a grey square: the design, an assembly (has children) or a part. */
  function treeIcon(kind) {
    const box = el('span', 'pub-tree-icon pub-tree-icon-' + kind);
    box.title = ICON_TITLE[kind];
    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('width', '16');
    svg.setAttribute('height', '16');
    ICON_PATHS[kind].forEach(function (d) {
      const path = document.createElementNS(SVG_NS, 'path');
      path.setAttribute('d', d);
      svg.appendChild(path);
    });
    box.appendChild(svg);
    return box;
  }

  // A row is indented (in the stylesheet) by the width of the icon box, so a child's
  // chevron sits under its parent's icon and its own icon starts where the parent's ends.

  function setChevron(svg, collapsed) {
    svg.firstChild.setAttribute('points', collapsed ? '10 6 16 12 10 18' : '6 10 12 16 18 10');
  }

  function chevron() {
    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('width', '16');
    svg.setAttribute('height', '16');
    svg.appendChild(document.createElementNS(SVG_NS, 'polyline'));
    setChevron(svg, false);
    return svg;
  }

  /** Bill of Materials tab: the design and Fusion Manage lines in one compare table (bomsplit.js). */
  function renderBom(rows) {
    const host = clearPanel('pub-tab-bom');
    if (structurePick) { panelMessage('pub-tab-bom', 'Several Fusion Manage items match this design. Choose one on the Details tab to compare the Bill of Materials.'); return; }
    if (!rows.length) { panelMessage('pub-tab-bom', 'This item has no child components.'); return; }
    ns.bomSplit.render(host, rows, currentSummary || {});
  }

  // Drawing helpers the compare table (bomsplit.js) shares.
  ns.pubTree = { el: el, treeIcon: treeIcon, chevron: chevron, setChevron: setChevron };

  /** Bouncing balls with a caption. */
  function loaderNode() {
    const box = el('div', 'loader');
    const balls = el('div', 'balls');
    balls.setAttribute('role', 'status');
    balls.setAttribute('aria-label', 'Loading');
    for (let i = 0; i < 3; i++) balls.appendChild(el('span'));
    box.appendChild(balls);
    box.appendChild(el('p', 'muted', 'Loading...'));
    return box;
  }

  /** Bouncing balls in a tab while its section loads. */
  function tabLoading(id) {
    const host = $(id);
    host.textContent = '';
    host.classList.add('pub-loading');
    host.appendChild(loaderNode());
  }

  /** Show the bouncing balls in place of the panel content while the summary loads. */
  function showLoading(on) {
    $('pub-loader').hidden = !on;
    $('pub-content').hidden = on;
  }

  let loadedKey = null;   // design the panel currently shows
  let lastLoad = 0;
  const loaded = {};      // section -> true once shown for the current design
  const inflight = {};    // section (or "component:<id>") -> true while loading
  const timers = {};      // section -> poll timer
  const forceNext = {};   // section -> skip the cached copy on the next load

  function handleSection(r) {
    if (!r.ok) { return; }
    const entry = r.result;
    const name = entry.section;
    clearTimeout(timers[name]);
    if (entry.pending) {
      timers[name] = setTimeout(function () {
        bridge.send('load_publish_section_status', { section: name });
      }, POLL_INTERVAL_MS);
      return;
    }
    inflight[name] = false;
    if (name.indexOf('component:') === 0) {
      const id = name.slice('component:'.length);
      if (entry.ok) { componentCompare[id] = entry.data.compare; componentDrawings[id] = entry.data.drawings; }
      else componentError[id] = entry.message || 'Unknown error';
      paintProps();
      return;
    }
    if (name === 'summary') {
      showLoading(false);
      if (!entry.ok) { setThumbnail(''); setSummary([errorState(entry.message, function () { lastLoad = 0; refresh(true); })]); return; }
      loadedKey = entry.key;
      loaded.summary = true;
      renderSummary(entry.data);
      ensureTab(activeTab());
      return;
    }
    const reload = loaded[name];   // a repeat load (a Fusion Manage item was chosen): redraw in place
    loaded[name] = true;
    if (!entry.ok) {
      SECTION_PANELS[name].forEach(function (id) {
        panelError(id, entry.message, function () { loaded[name] = false; loadSection(name); });
      });
      return;
    }
    if (name === 'properties') rootCompare = entry.data.compare;
    else {
      structureRows = entry.data.rows;
      structurePick = !!entry.data.pick;
      Object.keys(ns.bomSplit.decisions).forEach(function (k) { delete ns.bomSplit.decisions[k]; });   // fresh comparison: nothing is chosen yet
    }
    if (reload && name === 'properties' && selectedItem) { paintProps(); return; }
    if (reload && name === 'structure') { renderBom(structureRows); return; }
    renderReady();
  }

  function loadSection(name) {
    inflight[name] = true;
    clearTimeout(timers[name]);
    (SECTION_PANELS[name] || []).forEach(tabLoading);
    const force = !!forceNext[name];
    forceNext[name] = false;
    bridge.send('load_publish_section', { section: name, force: force, fm_item: name === 'properties' || name === 'structure' ? fmChoice[choiceKey(currentSummary || {})] || '' : '' });
  }

  function activeTab() {
    const tab = document.querySelector('.tabs[data-group="publish"] .tab.active');
    return tab ? tab.dataset.tab : 'details';
  }

  /** Load a tab's sections the first time it is shown for the open design. */
  function ensureTab(tab) {
    (TAB_SECTIONS[tab] || []).forEach(function (name) {
      if (loaded.summary && !loaded[name] && !inflight[name]) loadSection(name);
    });
  }

  function refresh(force) {
    // Focus, sign-in and the button can all fire together; load once.
    if (Date.now() - lastLoad < 2000) return;
    lastLoad = Date.now();
    Object.keys(SECTION_PANELS).forEach(function (name) {
      loaded[name] = false;
      inflight[name] = false;
      forceNext[name] = !!force;
      clearTimeout(timers[name]);
    });
    ['pub-tab-details', 'pub-tab-bom'].forEach(clearPanel);
    rootCompare = null;
    structureRows = null;
    structurePick = false;
    validation = null;
    Object.keys(listFilters).forEach(function (k) { delete listFilters[k]; });
    clearTimeout(validationTimer);
    selectedItem = null;
    propsPane = null;
    forceComponents = !!force;
    Object.keys(componentCompare).forEach(function (id) { delete componentCompare[id]; });
    Object.keys(componentError).forEach(function (id) { delete componentError[id]; });
    Object.keys(componentDrawings).forEach(function (id) { delete componentDrawings[id]; });
    loaded.summary = false;
    forceNext.summary = !!force;
    showLoading(true);
    loadSection('summary');
  }

  function init() {
    bridge.on('load_publish_section', handleSection);
    bridge.on('load_publish_section_status', handleSection);
    bridge.on('start_fm_validation', handleValidation);
    bridge.on('get_fm_validation', handleValidation);
    ns.tabs.setup('.tabs[data-group="publish"]', 'tab', 'pub-tab-');
    document.querySelectorAll('.tabs[data-group="publish"] .tab').forEach(function (button) {
      button.addEventListener('click', function () {
        ensureTab(button.dataset.tab);
        if (button.dataset.tab === 'bom') bridge.send('probe_hidden_fields');   // development: log candidate "hidden" fields
      });
    });
    $('pub-refresh').addEventListener('click', function () { refresh(true); });
    // The palette stays open while the user switches designs. Clicking into it
    // also fires focus, so reload only when a different design is open.
    bridge.on('get_publish_model_key', function (r) {
      if (r.ok && r.result.key !== loadedKey) refresh(false);
    });
    window.addEventListener('focus', function () {
      if (!$('view-app').hidden && !inflight.summary) bridge.send('get_publish_model_key');
    });
    ns.auth.onChange(function (signedIn) { if (signedIn) refresh(false); });
  }

  function start() {
    // Fusion injects `adsk` asynchronously, so wait for it.
    if (typeof adsk === 'undefined') { setTimeout(start, 100); return; }
    ns.shell.mountHeader();
    ns.account.init();
    ns.auth.init();
    init();
    ns.auth.refresh();
  }

  start();
})(window.MfgUi);
