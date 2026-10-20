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

  function open(hubName, onPick, options) {
    if (current) return;
    const folderMode = !!(options && options.folder);
    const crumbs = [{ label: hubName || 'Hub', project_id: '', folder_id: '' }];
    if (folderMode && lastPlace[options.hubId]) lastPlace[options.hubId].forEach(function (crumb) { crumbs.push(crumb); });
    let chosen = null;
    let enterNew = '';   // the name of what was just made: it is opened once the list shows it

    // ---- The dialog ----

    const overlay = el('div', 'ws-dialog-overlay');
    const box = el('div', 'ws-dialog hp-dialog');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    box.setAttribute('aria-labelledby', 'hp-title');

    const header = el('div', 'hp-header');
    const heading = el('div', 'hp-heading');
    const title = el('h3', 'hp-title', folderMode ? options.title : 'Find the Configuration File');
    title.id = 'hp-title';
    heading.appendChild(title);
    heading.appendChild(el('p', 'hp-sub', folderMode
      ? 'Choose the project and folder to keep the Configuration File in.'
      : 'Open a project and choose the Configuration File a Hub Admin saved there.'));
    const x = el('button', 'hp-x');
    x.type = 'button';
    x.setAttribute('aria-label', 'Close');
    x.appendChild(icon('close', 18));
    header.appendChild(icon(folderMode ? 'cloud' : 'search', 22, 'hp-badge-icon'));
    header.appendChild(heading);
    header.appendChild(x);

    const head = el('div', 'hp-head');
    const trail = el('nav', 'hp-trail');
    trail.setAttribute('aria-label', 'Location in the hub');
    head.appendChild(trail);
    const make = el('button', 'hp-make');
    make.type = 'button';
    if (folderMode) head.appendChild(make);

    const body = el('div', 'hp-body');
    const newRow = el('form', 'hp-newrow');
    newRow.hidden = true;
    const list = el('ul', 'hp-list');
    const state = el('div', 'hp-state');
    body.appendChild(newRow);
    body.appendChild(list);
    body.appendChild(state);

    const footer = el('div', 'hp-footer');
    const target = el('p', 'hp-target');
    const actions = el('div', 'hp-actions');
    const cancel = el('button', 'btn btn-secondary', 'Cancel');
    const select = el('button', 'btn', folderMode ? options.action : 'Use this file');
    cancel.type = select.type = 'button';
    select.disabled = true;
    actions.appendChild(cancel);
    actions.appendChild(select);
    footer.appendChild(target);
    footer.appendChild(actions);

    [header, head, body, footer].forEach(function (node) { box.appendChild(node); });
    overlay.appendChild(box);

    function close() {
      document.removeEventListener('keydown', onKey);
      overlay.remove();
      current = null;
      wanted += 1;   // whatever is still on its way is not wanted
    }
    function onKey(e) { if (e.key === 'Escape' && !e.target.closest('.hp-newrow')) close(); }

    // ---- What the dialog says about where you are and what you chose ----

    function here() { return crumbs[crumbs.length - 1]; }
    function atHub() { return crumbs.length === 1; }
    function placeName() { return crumbs.slice(1).map(function (c) { return c.label; }).join(' / '); }

    function drawTrail() {
      trail.textContent = '';
      crumbs.forEach(function (crumb, index) {
        if (index) trail.appendChild(icon('chevron', 12, 'hp-sep'));
        const last = index === crumbs.length - 1;
        const part = el(last ? 'span' : 'button', last ? 'hp-crumb hp-here' : 'hp-crumb');
        if (!index) part.appendChild(icon('home', 14));
        part.appendChild(document.createTextNode(crumb.label));
        if (!last) {
          part.type = 'button';
          part.addEventListener('click', function () { crumbs.length = index + 1; load(); });
        }
        trail.appendChild(part);
      });
    }

    function drawMake() {
      make.textContent = '';
      make.appendChild(icon('plus', 14));
      make.appendChild(document.createTextNode(atHub() ? 'New project' : 'New folder'));
    }

    /** The line over the buttons: where the file will go, or which file is chosen. */
    function drawTarget() {
      target.textContent = '';
      if (folderMode) {
        if (atHub()) { target.textContent = 'Open a project to choose where to save.'; return; }
        target.appendChild(document.createTextNode('Saving to '));
        target.appendChild(el('strong', 'hp-place', placeName()));
        return;
      }
      if (chosen) { target.appendChild(document.createTextNode('Selected ')); target.appendChild(el('strong', 'hp-place', chosen.name)); }
      else target.textContent = 'Select the Configuration File.';
    }

    // ---- Making a project or folder, in a row at the top of the list ----

    function closeNewRow() { newRow.hidden = true; newRow.textContent = ''; }

    function openNewRow() {
      const kind = atHub() ? 'project' : 'folder';
      newRow.textContent = '';
      newRow.hidden = false;
      const input = el('input');
      input.type = 'text';
      input.maxLength = 100;
      input.autocomplete = 'off';
      input.spellcheck = false;
      input.placeholder = kind === 'project' ? 'Name of the new project' : 'Name of the new folder';
      input.setAttribute('aria-label', input.placeholder);
      const create = el('button', 'btn', 'Create');
      const back = el('button', 'hp-x');
      create.type = 'submit';
      back.type = 'button';
      back.setAttribute('aria-label', 'Cancel');
      back.appendChild(icon('close', 16));
      const problem = el('p', 'hp-newerror');
      problem.hidden = true;
      const line = el('div', 'hp-newline');
      line.appendChild(icon(kind === 'project' ? 'cloud' : 'folder', 18, 'hp-tile hp-new-tile'));
      line.appendChild(input);
      line.appendChild(create);
      line.appendChild(back);
      newRow.appendChild(line);
      newRow.appendChild(problem);
      input.focus();
      back.addEventListener('click', closeNewRow);
      input.addEventListener('keydown', function (e) { if (e.key === 'Escape') { e.stopPropagation(); closeNewRow(); } });
      newRow.onsubmit = function (e) {
        e.preventDefault();
        const name = input.value.trim();
        if (!name) { input.focus(); return; }
        create.disabled = back.disabled = input.disabled = true;
        problem.hidden = true;
        bridge.send('create_in_hub', { kind: kind, name: name, project_id: here().project_id, folder_id: here().folder_id });
      };
    }

    /** The answer to making a project or folder: show the list again and open the new one, or say what went wrong. */
    function created(r) {
      if (!r.ok) {
        newRow.querySelectorAll('input, button').forEach(function (n) { n.disabled = false; });
        const problem = newRow.querySelector('.hp-newerror');
        if (problem) { problem.hidden = false; problem.textContent = r.error; }
        return;
      }
      enterNew = r.result.name;
      closeNewRow();
      load();
    }

    // ---- The list ----

    function row(entry, isFolder) {
      const item = el('li');
      // To save, files are only shown so that what is in the folder can be seen.
      const inert = folderMode && !isFolder;
      const button = el(inert ? 'div' : 'button', 'hp-row' + (isFolder ? ' hp-folder' : ' hp-file') + (inert ? ' hp-inert' : ''));
      if (!inert) button.type = 'button';
      button.appendChild(icon(isFolder ? 'folder' : 'file', 18, 'hp-tile'));
      const text = el('span', 'hp-text');   // the name, and under it (for the file that will be replaced) what will happen to it
      const name = el('span', 'hp-name', entry.name);
      name.title = entry.name;
      text.appendChild(name);
      if (inert && entry.name === options.fileName) text.appendChild(el('span', 'hp-tag', 'Will be updated'));
      button.appendChild(text);
      if (isFolder) {
        button.appendChild(icon('chevron', 16, 'hp-chevron'));
        button.addEventListener('click', function () { enter(entry); });
      } else if (!inert) {
        button.addEventListener('click', function () {
          list.querySelectorAll('.hp-row.selected').forEach(function (n) { n.classList.remove('selected'); });
          button.classList.add('selected');
          chosen = { project_id: here().project_id, item_id: entry.id, name: entry.name };
          select.disabled = false;
          drawTarget();
        });
        button.addEventListener('dblclick', pick);
      }
      item.appendChild(button);
      return item;
    }

    function enter(entry) {
      const place = here();
      const projectId = place.project_id || entry.id;   // from the hub's list the entry is a project, below it a folder
      crumbs.push({ label: entry.name, project_id: projectId, folder_id: place.project_id ? entry.id : '' });
      load();
    }

    function pick() {
      if (folderMode) {
        if (atHub()) return;
        lastPlace[options.hubId] = crumbs.slice(1);
        const place = { project_id: here().project_id, folder_id: here().folder_id, path: placeName() };
        close();
        onPick(place);
        return;
      }
      if (!chosen) return;
      const file = chosen;
      close();
      onPick(file);
    }

    /** What stands where the list is when there is no list: the placeholder rows while loading, a message when empty or failed. */
    function say(kind, headline, detail) {
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

    function show(result) {
      list.textContent = '';
      chosen = null;
      select.disabled = !(folderMode && !atHub());
      drawTarget();
      if (!result.ok) {
        say('error', 'The hub could not be read', result.message);
        select.disabled = true;   // a place that cannot be read is not one to save into
        return;
      }
      if (result.folder_id && !here().folder_id) here().folder_id = result.folder_id;   // a project's one top folder is the project itself: saving and making go in it
      if (enterNew) {   // what was just made: open it, once the hub lists it
        const name = enterNew;
        enterNew = '';
        const made = result.folders.filter(function (f) { return f.name === name; })[0];
        if (made) { enter(made); return; }
      }
      const files = result.files.filter(function (f) { return isConfigFile(f.name); });
      result.folders.forEach(function (f) { list.appendChild(row(f, true)); });
      files.forEach(function (f) { list.appendChild(row(f, false)); });
      if (result.folders.length || files.length) { say('', ''); return; }
      if (atHub()) say('empty', 'No projects yet', 'No project of this hub is open to you.');
      else say('empty', 'This folder is empty', folderMode ? 'Save here, or make a new folder first.' : 'There is no folder or .json file here.');
    }

    function load() {
      drawTrail();
      if (folderMode) drawMake();
      list.textContent = '';
      chosen = null;
      select.disabled = true;
      drawTarget();
      say('loading');
      wanted = -1;   // the id comes with the answer to the request below
      stopWaiting();
      stopWaiting = bridge.expect(WAIT_MS, function () {
        if (current) current.show({ id: wanted, pending: false, ok: false, message: 'The hub did not answer in time. Try again.' });
      });
      bridge.send('browse_hub_files', { project_id: here().project_id, folder_id: here().folder_id });
    }

    make.addEventListener('click', openNewRow);
    x.addEventListener('click', close);
    cancel.addEventListener('click', close);
    select.addEventListener('click', pick);
    overlay.addEventListener('mousedown', function (e) { if (e.target === overlay) close(); });
    document.addEventListener('keydown', onKey);
    document.body.appendChild(overlay);
    current = { show: show, created: created };
    load();
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
