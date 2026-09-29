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
    unchecked: { mark: '·', text: 'Mapped: Fusion Manage is not checked yet' },
    unmapped: { mark: '–', text: 'Not mapped: not published' },
  };

  /** Properties of one component, as they would be published. */
  function propertiesCard(compare) {
    const card = el('div', 'card');
    if (!compare.rows.length) {
      card.appendChild(el('p', 'muted', 'This item has no properties.'));
      return card;
    }
    if (compare.fm.message) {
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
  let structureRows = null;     // the BOM tree rows
  let selectedItem = null;      // component chosen on the Details tab
  let propsPane = null;
  let forceComponents = false;
  const componentCompare = {};  // component id -> comparison
  const componentError = {};    // component id -> message
  const componentDrawings = {}; // component id -> drawings of its primary model

  /** One state for a component: does publishing change anything in Fusion Manage? */
  function changeState(compare) {
    if (!compare) return 'unchecked';
    const states = compare.rows.map(function (r) { return r.status; });
    const first = ['mismatch', 'new', 'unknown'].filter(function (st) { return states.indexOf(st) >= 0; })[0];
    if (first) return first;
    return states.indexOf('match') >= 0 ? 'match' : 'unchecked';
  }

  let listMarks = [];   // [{item, node}] for the end-of-row change indicators

  function updateMarks() {
    listMarks.forEach(function (m) {
      const state = changeState(m.item.root ? rootCompare : componentCompare[m.item.id]);
      const status = STATUS[state];
      m.node.className = 'pub-comp-status pub-status-' + state;
      m.node.textContent = '';
      const mark = el('span', 'pub-mark');
      mark.title = state === 'unchecked' && !(m.item.root || componentCompare[m.item.id])
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
    propsPane.appendChild(head);
    const compare = selectedItem.root ? rootCompare : componentCompare[selectedItem.id];
    let content;
    if (compare) {
      content = propertiesCard(compare);
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
    const slot = 'component:' + item.id;
    if (!item.id || componentCompare[item.id] || inflight[slot]) return;
    inflight[slot] = true;
    componentError[item.id] = '';
    clearTimeout(timers[slot]);
    bridge.send('load_publish_section', {
      section: 'component', id: item.id, force: forceComponents,
      item_number: item.item_number, part_number: item.part_number, description: item.description,
    });
  }

  /** Component list (this design, then the BOM tree) beside the selected one's properties. */
  function renderProperties() {
    const host = clearPanel('pub-tab-details');
    const root = currentSummary || {};
    const seen = {};   // a part used in several places is listed once
    const items = [{ id: root.component_id || '', root: true, title: [root.part_number, root.description].filter(Boolean).join(' - ') || 'This design' }]
      .concat(structureRows.filter(function (b) {
        if (seen[b.id]) return false;
        seen[b.id] = true;
        return true;
      }).map(function (b) {
        return { id: b.id, title: [b.part_number, b.name].filter(Boolean).join(' - '),
                 item_number: b.item_number, part_number: b.part_number, description: b.description };
      }));
    listMarks = [];

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
      if (i === 0) button.click();
    });

    const split = el('div', 'pub-split');
    split.appendChild(pick);
    split.appendChild(list);
    split.appendChild(propsPane);
    host.appendChild(split);
    updateMarks();
  }

  /** Draw whichever panels have everything they need. */
  function renderReady() {
    if (loaded.structure && structureRows) renderBom(structureRows);
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

  // Change against Fusion Manage. Its BOM is not read yet, so rows stay "unchecked".
  const BOM_CHANGE = {
    new:       { mark: '+', text: 'New entry: publishing will add it to Fusion Manage' },
    removed:   { mark: '−', text: 'Removed: publishing will remove it from Fusion Manage' },
    unchecked: { mark: '·', text: 'Fusion Manage BOM is not checked yet' },
  };

  function renderBom(rows) {
    const host = clearPanel('pub-tab-bom');
    if (!rows.length) { panelMessage('pub-tab-bom', 'This item has no child components.'); return; }

    // The open design is the first row; its parts sit one level below it.
    const root = currentSummary || {};
    const numbers = [];   // sequence number at each depth, to number rows 1, 2, 2.1, 2.2, 3 ...
    const items = [{ level: 0, sequence: '', quantity: '', status: '', root: true,
                     pn: root.part_number || root.item_number || '', name: root.description || (root.part_number || root.item_number ? '' : 'This design') }]
      .concat(rows.map(function (b) {
        numbers[b.level] = String(b.sequence);
        return { level: b.level + 1, sequence: String(b.sequence), quantity: String(b.quantity),
                 path: numbers.slice(0, b.level + 1).join('.'),
                 status: b.status || 'unchecked',
                 pn: b.part_number, name: b.name };
      }));

    const t = el('table', 'pub-tree');
    const head = el('tr');
    head.appendChild(el('th', '', 'Descriptor'));
    head.appendChild(el('th', 'num', 'Qty'));
    head.appendChild(el('th', 'pub-tree-status-col', ''));
    t.appendChild(head);

    const collapsed = {};
    const trs = [];
    // Hide every row under a collapsed assembly.
    function apply() {
      let hideBelow = null;
      trs.forEach(function (tr, i) {
        const level = items[i].level;
        if (hideBelow !== null && level > hideBelow) { tr.hidden = true; return; }
        hideBelow = null;
        tr.hidden = false;
        if (collapsed[i]) hideBelow = level;
      });
    }

    items.forEach(function (item, i) {
      const tr = el('tr', item.root ? 'pub-tree-root' : '');
      const cell = el('td');
      const box = el('div', 'pub-tree-cell');
      box.style.setProperty('--level', String(item.level));   // the stylesheet turns depth into indent
      const toggle = el('button', 'pub-tree-toggle');
      toggle.type = 'button';
      const isAssembly = !!(items[i + 1] && items[i + 1].level > item.level);
      if (isAssembly) {
        toggle.appendChild(chevron());
        toggle.setAttribute('aria-label', 'Collapse or expand');
        toggle.addEventListener('click', function () {
          collapsed[i] = !collapsed[i];
          setChevron(toggle.firstChild, collapsed[i]);
          apply();
        });
      } else {
        toggle.disabled = true;
      }
      box.appendChild(toggle);
      box.appendChild(treeIcon(item.root ? 'root' : isAssembly ? 'assembly' : 'part'));
      if (item.sequence) {
        // The wide tree shows the row's own number (nesting shows where it belongs); the flat
        // list shows the full number, such as 2.1.
        const seq = el('span', 'pub-tree-seq' + (isAssembly ? ' pub-tree-asm' : ''));
        seq.appendChild(el('span', 'pub-seq-own', item.sequence));
        seq.appendChild(el('span', 'pub-seq-path', item.path));
        box.appendChild(seq);
      }
      const label = el('span', 'pub-tree-label');
      label.title = [item.pn, item.name].filter(Boolean).join(' - ');   // full text when the row is cut short
      if (item.pn) label.appendChild(el('span', 'pub-tree-pn', item.pn));
      if (item.name) label.appendChild(el('span', 'pub-tree-name', item.name));
      box.appendChild(label);
      cell.appendChild(box);
      tr.appendChild(cell);
      tr.appendChild(el('td', 'num', item.quantity));
      const state = el('td', 'pub-tree-status-col');
      const change = BOM_CHANGE[item.status];
      if (change) {
        const mark = el('span', 'pub-bom-mark pub-bom-' + item.status, change.mark);
        mark.title = change.text;
        mark.setAttribute('aria-label', change.text);
        state.appendChild(mark);
      }
      tr.appendChild(state);
      if (item.status === 'removed') tr.classList.add('pub-tree-removed');
      t.appendChild(tr);
      trs.push(tr);
    });

    host.appendChild(t);
  }

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
    loaded[name] = true;
    if (!entry.ok) {
      SECTION_PANELS[name].forEach(function (id) {
        panelError(id, entry.message, function () { loaded[name] = false; loadSection(name); });
      });
      return;
    }
    if (name === 'properties') rootCompare = entry.data.compare;
    else structureRows = entry.data;
    renderReady();
  }

  function loadSection(name) {
    inflight[name] = true;
    clearTimeout(timers[name]);
    (SECTION_PANELS[name] || []).forEach(tabLoading);
    const force = !!forceNext[name];
    forceNext[name] = false;
    bridge.send('load_publish_section', { section: name, force: force });
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
    ns.tabs.setup('.tabs[data-group="publish"]', 'tab', 'pub-tab-');
    document.querySelectorAll('.tabs[data-group="publish"] .tab').forEach(function (button) {
      button.addEventListener('click', function () { ensureTab(button.dataset.tab); });
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
