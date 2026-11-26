/**
 * The dialog for finding things in the Fusion Hub, as ``ns.hubPicker``.
 *
 * ``open(hubName, onPick, options)`` shows the hub's projects, then a project's folders. To find the Configuration File (no ``options``) it
 * also lists ``.json`` files; choosing one calls ``onPick({project_id, item_id, name})``. To choose where to save it (``options.folder``)
 * the place being looked at is the choice, a project or folder can be made there, and the files already in it are shown (not chosen).
 * Python reads the hub in the background, so each folder is asked for and then polled.
 */
(function (ns) {
  'use strict';

  const el = ns.el;
  const bridge = ns.bridge;
  const t = ns.i18n.t;

  const WAIT_MS = 60000;   // how long Python is given to push the answer
  const ICONS = {
    folder: ['M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'],
    file: ['M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z', 'M14 3v5h5'],
    plus: ['M12 5v14', 'M5 12h14'],
    chevron: ['M9 6l6 6-6 6'],
    close: ['M6 6l12 12', 'M18 6L6 18'],
    home: ['M3 11l9-8 9 8', 'M5 10v10h14V10'],
    cloud: ['M7 18a5 5 0 1 1 .9-9.9A6 6 0 0 1 19 10a4 4 0 0 1-1 8z'],
    search: ['M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z', 'M21 21l-5-5'],
  };
  const SKELETON_ROWS = 4;
  const MARK = '{place}';   // stands where a name goes in a sentence that shows the name in bold

  /** Put `text` (a sentence made with `MARK` where `name` goes) in `node`, with `name` in bold. */
  function sentenceWithName(node, text, name) {
    const parts = text.split(MARK);
    if (parts[0]) node.appendChild(document.createTextNode(parts[0]));
    node.appendChild(el('strong', 'hp-place', name));
    if (parts[1]) node.appendChild(document.createTextNode(parts[1]));
  }

  let current = null;   // the dialog that is open: {show(result), created(reply)}; one at a time
  let wanted = 0;       // id of the request whose answer is expected

  function isConfigFile(name) { return /\.json$/i.test(name); }

  function icon(name, size, className) {
    const holder = el('span', className || 'hp-ico');
    holder.appendChild(ns.svg(ICONS[name], size));
    return holder;
  }

  let stopWaiting = function () {};   // cancels the wait for the current request's answer

  /** The answer to a browse request: show it. A pending answer is only the start; the real one is pushed when it is read. */
  function onBrowse(r) {
    if (!current) return;
    const result = r.ok ? r.result : { id: wanted, pending: false, ok: false, message: r.error };
    if (result.id !== wanted) return;   // an older request's answer
    if (result.pending) return;
    stopWaiting();
    current.show(result);
  }

  const lastPlace = {};   // where a folder was last chosen, by hub, so the next save starts there

  // ---- One dialog -----------------------------------------------------------
  // ``d`` is the state of the dialog that is open: ``hubName``, ``onPick``, ``options``, ``folderMode``, ``crumbs`` (the places walked into),
  // ``chosen`` (the file selected), ``enterNew`` (the name of what was just made: it is opened once the list shows it), ``picked``, ``onKey``,
  // and its elements ``overlay``, ``box``, ``trail``, ``make``, ``newRow``, ``list``, ``state``, ``target``, ``cancel``, ``select`` and ``x``.

  function buildHubHeader(d) {
    const folderMode = d.folderMode;
    const header = el('div', 'hp-header');
    const heading = el('div', 'hp-heading');
    const title = el('h3', 'hp-title', folderMode ? d.options.title : t('settings.hp_find_title'));
    title.id = 'hp-title';
    heading.appendChild(title);
    heading.appendChild(el('p', 'hp-sub', folderMode
      ? t('settings.hp_save_sub')
      : t('settings.hp_find_sub')));
    d.x = el('button', 'hp-x');
    d.x.type = 'button';
    d.x.setAttribute('aria-label', t('settings.close'));
    d.x.appendChild(icon('close', 18));
    header.appendChild(icon(folderMode ? 'cloud' : 'search', 22, 'hp-badge-icon'));
    header.appendChild(heading);
    header.appendChild(d.x);
    return header;
  }

  function buildHubHead(d) {
    const head = el('div', 'hp-head');
    d.trail = el('nav', 'hp-trail');
    d.trail.setAttribute('aria-label', t('settings.hp_location'));
    head.appendChild(d.trail);
    d.make = el('button', 'hp-make');
    d.make.type = 'button';
    if (d.folderMode) head.appendChild(d.make);
    return head;
  }

  function buildHubBody(d) {
    const body = el('div', 'hp-body');
    d.newRow = el('form', 'hp-newrow');
    d.newRow.hidden = true;
    d.list = el('ul', 'hp-list');
    d.state = el('div', 'hp-state');
    body.appendChild(d.newRow);
    body.appendChild(d.list);
    body.appendChild(d.state);
    return body;
  }

  function buildHubFooter(d) {
    const footer = el('div', 'hp-footer');
    d.target = el('p', 'hp-target');
    const actions = el('div', 'hp-actions');
    d.cancel = el('button', 'btn btn-secondary', t('settings.cancel'));
    d.select = el('button', 'btn', d.folderMode ? d.options.action : t('settings.hp_use_file'));
    d.cancel.type = d.select.type = 'button';
    d.select.disabled = true;
    actions.appendChild(d.cancel);
    actions.appendChild(d.select);
    footer.appendChild(d.target);
    footer.appendChild(actions);
    return footer;
  }

  function buildHubDialog(d) {
    d.overlay = el('div', 'ws-dialog-overlay');
    d.box = el('div', 'ws-dialog hp-dialog');
    d.box.setAttribute('role', 'dialog');
    d.box.setAttribute('aria-modal', 'true');
    d.box.setAttribute('aria-labelledby', 'hp-title');
    [buildHubHeader(d), buildHubHead(d), buildHubBody(d), buildHubFooter(d)].forEach(function (node) { d.box.appendChild(node); });
    d.overlay.appendChild(d.box);
  }

  function closeHub(d) {
    document.removeEventListener('keydown', d.onKey);
    d.overlay.remove();
    current = null;
    wanted += 1;   // whatever is still on its way is not wanted
    if (!d.picked && d.options && d.options.onDismiss) d.options.onDismiss();   // closed without choosing
  }

  // ---- What the dialog says about where you are and what you chose ----

  function hubHere(d) { return d.crumbs[d.crumbs.length - 1]; }
  function hubAtHub(d) { return d.crumbs.length === 1; }
  function hubPlaceName(d) { return d.crumbs.slice(1).map(function (c) { return c.label; }).join(' / '); }

  function drawTrail(d) {
    d.trail.textContent = '';
    d.crumbs.forEach(function (crumb, index) {
      if (index) d.trail.appendChild(icon('chevron', 12, 'hp-sep'));
      const last = index === d.crumbs.length - 1;
      const part = el(last ? 'span' : 'button', last ? 'hp-crumb hp-here' : 'hp-crumb');
      if (!index) part.appendChild(icon('home', 14));
      part.appendChild(document.createTextNode(crumb.label));
      if (!last) {
        part.type = 'button';
        part.addEventListener('click', function () { d.crumbs.length = index + 1; loadHub(d); });
      }
      d.trail.appendChild(part);
    });
  }

  function drawMake(d) {
    d.make.textContent = '';
    d.make.appendChild(icon('plus', 14));
    d.make.appendChild(document.createTextNode(hubAtHub(d) ? t('settings.hp_new_project') : t('settings.hp_new_folder')));
  }

  /** The line over the buttons: where the file will go, or which file is chosen. */
  function drawTarget(d) {
    const target = d.target;
    target.textContent = '';
    if (d.folderMode) {
      if (hubAtHub(d)) { target.textContent = t('settings.hp_open_project'); return; }
      sentenceWithName(target, t('settings.hp_saving_to', { place: MARK }), hubPlaceName(d));
      return;
    }
    if (d.chosen) sentenceWithName(target, t('settings.hp_selected', { place: MARK }), d.chosen.name);
    else target.textContent = t('settings.hp_select_file');
  }

  // ---- Making a project or folder, in a row at the top of the list ----

  function closeNewRow(d) { d.newRow.hidden = true; d.newRow.textContent = ''; }

  /** The row's controls: the name field, the Create button, the button that cancels, and the line for what goes wrong. */
  function buildNewRowParts(d, kind) {
    const input = el('input');
    input.type = 'text';
    input.maxLength = 100;
    input.autocomplete = 'off';
    input.spellcheck = false;
    input.placeholder = kind === 'project' ? t('settings.hp_name_project') : t('settings.hp_name_folder');
    input.setAttribute('aria-label', input.placeholder);
    const create = el('button', 'btn', t('settings.hp_create'));
    const back = el('button', 'hp-x');
    create.type = 'submit';
    back.type = 'button';
    back.setAttribute('aria-label', t('settings.cancel'));
    back.appendChild(icon('close', 16));
    const problem = el('p', 'hp-newerror');
    problem.hidden = true;
    const line = el('div', 'hp-newline');
    line.appendChild(icon(kind === 'project' ? 'cloud' : 'folder', 18, 'hp-tile hp-new-tile'));
    line.appendChild(input);
    line.appendChild(create);
    line.appendChild(back);
    d.newRow.appendChild(line);
    d.newRow.appendChild(problem);
    return { input: input, create: create, back: back, problem: problem };
  }

  function openNewRow(d) {
    const kind = hubAtHub(d) ? 'project' : 'folder';
    d.newRow.textContent = '';
    d.newRow.hidden = false;
    const { input, create, back, problem } = buildNewRowParts(d, kind);
    input.focus();
    back.addEventListener('click', function () { closeNewRow(d); });
    input.addEventListener('keydown', function (e) { if (e.key === 'Escape') { e.stopPropagation(); closeNewRow(d); } });
    d.newRow.onsubmit = function (e) {
      e.preventDefault();
      const name = input.value.trim();
      if (!name) { input.focus(); return; }
      create.disabled = back.disabled = input.disabled = true;
      problem.hidden = true;
      bridge.send('create_in_hub', { kind: kind, name: name, project_id: hubHere(d).project_id, folder_id: hubHere(d).folder_id });
    };
  }

  /** The answer to making a project or folder: show the list again and open the new one, or say what went wrong. */
  function showCreated(d, r) {
    if (!r.ok) {
      d.newRow.querySelectorAll('input, button').forEach(function (n) { n.disabled = false; });
      const problem = d.newRow.querySelector('.hp-newerror');
      if (problem) { problem.hidden = false; problem.textContent = r.error; }
      return;
    }
    d.enterNew = r.result.name;
    closeNewRow(d);
    loadHub(d);
  }

  // ---- The list ----

  /** The name of a row, and under it (for the file that will be replaced) what will happen to it. */
  function buildHubRowText(d, entry, inert) {
    const text = el('span', 'hp-text');
    const name = el('span', 'hp-name', entry.name);
    name.title = entry.name;
    text.appendChild(name);
    if (inert && entry.name === d.options.fileName) text.appendChild(el('span', 'hp-tag', t('settings.hp_will_update')));
    return text;
  }

  function selectHubFile(d, button, entry) {
    d.list.querySelectorAll('.hp-row.selected').forEach(function (n) { n.classList.remove('selected'); });
    button.classList.add('selected');
    d.chosen = { project_id: hubHere(d).project_id, item_id: entry.id, name: entry.name };
    d.select.disabled = false;
    drawTarget(d);
  }

  function buildHubRow(d, entry, isFolder) {
    const item = el('li');
    // To save, files are only shown so that what is in the folder can be seen.
    const inert = d.folderMode && !isFolder;
    const button = el(inert ? 'div' : 'button', 'hp-row' + (isFolder ? ' hp-folder' : ' hp-file') + (inert ? ' hp-inert' : ''));
    if (!inert) button.type = 'button';
    button.appendChild(icon(isFolder ? 'folder' : 'file', 18, 'hp-tile'));
    button.appendChild(buildHubRowText(d, entry, inert));
    if (isFolder) {
      button.appendChild(icon('chevron', 16, 'hp-chevron'));
      button.addEventListener('click', function () { enterHubEntry(d, entry); });
    } else if (!inert) {
      button.addEventListener('click', function () { selectHubFile(d, button, entry); });
      button.addEventListener('dblclick', function () { pickHub(d); });
    }
    item.appendChild(button);
    return item;
  }

  function enterHubEntry(d, entry) {
    const place = hubHere(d);
    const projectId = place.project_id || entry.id;   // from the hub's list the entry is a project, below it a folder
    d.crumbs.push({ label: entry.name, project_id: projectId, folder_id: place.project_id ? entry.id : '' });
    loadHub(d);
  }

  function pickHub(d) {
    if (d.folderMode) {
      if (hubAtHub(d)) return;
      lastPlace[d.options.hubId] = d.crumbs.slice(1);
      const place = { project_id: hubHere(d).project_id, folder_id: hubHere(d).folder_id, path: hubPlaceName(d) };
      d.picked = true;
      closeHub(d);
      d.onPick(place);
      return;
    }
    if (!d.chosen) return;
    const file = d.chosen;
    d.picked = true;
    closeHub(d);
    d.onPick(file);
  }

  /** What stands where the list is when there is no list: the placeholder rows while loading, a message when empty or failed. */
  function sayHub(d, kind, headline, detail) {
    const state = d.state;
    state.textContent = '';
    state.dataset.state = kind;
    state.hidden = !kind;
    if (kind === 'loading') {
      for (let i = 0; i < SKELETON_ROWS; i += 1) state.appendChild(el('div', 'hp-skeleton'));
      return;
    }
    if (!kind) return;
    state.appendChild(icon(kind === 'error' ? 'close' : 'folder', 26, 'hp-state-icon'));
    state.appendChild(el('strong', '', headline));
    if (detail) state.appendChild(el('span', '', detail));
  }

  /** What was just made: open it, once the hub lists it. True when it was opened. */
  function openMadeEntry(d, result) {
    if (!d.enterNew) return false;
    const name = d.enterNew;
    d.enterNew = '';
    const made = result.folders.filter(function (f) { return f.name === name; })[0];
    if (!made) return false;
    enterHubEntry(d, made);
    return true;
  }

  function fillHubList(d, result) {
    const files = result.files.filter(function (f) { return isConfigFile(f.name); });
    result.folders.forEach(function (f) { d.list.appendChild(buildHubRow(d, f, true)); });
    files.forEach(function (f) { d.list.appendChild(buildHubRow(d, f, false)); });
    if (result.folders.length || files.length) { sayHub(d, '', ''); return; }
    if (hubAtHub(d)) sayHub(d, 'empty', t('settings.hp_no_projects'), t('settings.hp_no_projects_detail'));
    else sayHub(d, 'empty', t('settings.hp_empty'), d.folderMode ? t('settings.hp_empty_save') : t('settings.hp_empty_find'));
  }

  function showHub(d, result) {
    d.list.textContent = '';
    d.chosen = null;
    d.select.disabled = !(d.folderMode && !hubAtHub(d));
    drawTarget(d);
    if (!result.ok) {
      sayHub(d, 'error', t('settings.hp_read_failed'), result.message);
      d.select.disabled = true;   // a place that cannot be read is not one to save into
      return;
    }
    if (result.folder_id && !hubHere(d).folder_id) hubHere(d).folder_id = result.folder_id;   // a project's one top folder is the project itself: saving and making go in it
    if (openMadeEntry(d, result)) return;
    fillHubList(d, result);
  }

  function loadHub(d) {
    drawTrail(d);
    if (d.folderMode) drawMake(d);
    d.list.textContent = '';
    d.chosen = null;
    d.select.disabled = true;
    drawTarget(d);
    sayHub(d, 'loading');
    wanted = -1;   // the id comes with the answer to the request below
    stopWaiting();
    stopWaiting = bridge.expect(WAIT_MS, function () {
      if (current) current.show({ id: wanted, pending: false, ok: false, message: t('settings.hub_timeout_retry') });
    });
    bridge.send('browse_hub_files', { project_id: hubHere(d).project_id, folder_id: hubHere(d).folder_id });
  }

  function wireHubDialog(d) {
    d.make.addEventListener('click', function () { openNewRow(d); });
    d.x.addEventListener('click', function () { closeHub(d); });
    d.cancel.addEventListener('click', function () { closeHub(d); });
    d.select.addEventListener('click', function () { pickHub(d); });
    d.overlay.addEventListener('mousedown', function (e) { if (e.target === d.overlay) closeHub(d); });
    d.onKey = function (e) { if (e.key === 'Escape' && !e.target.closest('.hp-newrow')) closeHub(d); };
    document.addEventListener('keydown', d.onKey);
  }

  function open(hubName, onPick, options) {
    if (current) { if (options && options.onDismiss) options.onDismiss(); return; }   // one at a time: the one open stays
    const folderMode = !!(options && options.folder);
    const crumbs = [{ label: hubName || t('settings.hp_hub'), project_id: '', folder_id: '' }];
    if (folderMode && lastPlace[options.hubId]) lastPlace[options.hubId].forEach(function (crumb) { crumbs.push(crumb); });
    const d = { onPick: onPick, options: options, folderMode: folderMode, crumbs: crumbs, chosen: null, enterNew: '', picked: false };
    buildHubDialog(d);
    wireHubDialog(d);
    document.body.appendChild(d.overlay);
    current = { show: function (result) { showHub(d, result); }, created: function (r) { showCreated(d, r); } };
    loadHub(d);
  }

  function init() {
    // The answer to starting a request names it (``id``); the answer pushed when it is done repeats that id.
    bridge.on('browse_hub_files', function (r) {
      if (r.ok) wanted = r.result.id;
      onBrowse(r);
    });
    bridge.on('browse_hub_files_status', onBrowse);
    bridge.on('create_in_hub', function (r) { if (current) current.created(r); });
  }

  ns.hubPicker = { init: init, open: open };
})(window.MfgUi);
