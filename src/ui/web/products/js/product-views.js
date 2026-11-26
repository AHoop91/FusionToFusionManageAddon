/**
 * The three dialogs that manage the views of the product list in the View product portfolio window: rename a view, delete a view, and create a
 * new one from a name and the columns to show (chosen on the left, in order; every other field a view can show on the right, by section). It
 * draws the dialogs and asks Python (``products_rename_view``, ``products_delete_view``, ``products_fields``, ``products_create_view``); it
 * holds no business rule. Layer: UI.
 *
 * The page starts it once with ``ns.productViews.init(host)`` and opens a dialog with the three functions it gives back. ``host`` is what the
 * page lends: ``ask(action, payload, done)`` sends a request, ``failure(answer)`` words a refusal, ``setAlert(id, message)`` shows or hides an
 * alert, ``isBusy()`` says the list is being read, ``columns()`` is the columns of that view
 * (``[{key}]``, or null while unknown), ``reload()`` reads the list of views again, ``deleted(id)`` and ``created(id)`` tell the page that a
 * view is gone or new (the page changes what it shows, then the module calls ``reload()``). It gives back ``{askRename(view), askDelete(view),
 * openNew(), closeFront()}``; ``closeFront()`` closes the one of its dialogs that is open and answers true, or answers false when none is.
 */
(function (ns) {
  'use strict';

  const $ = ns.$;
  const el = ns.el;
  const t = ns.i18n.t;

  /** Show how much of a name box's limit is used ("12/30"), in red once it is all used. */
  function showChars(input, counter) {
    const used = input.value.length;
    counter.textContent = used + '/' + input.maxLength;
    counter.classList.toggle('full', used >= input.maxLength);
  }

  /** A small round button with an icon (``paths``) that says what it does to a screen reader. */
  function makeIconButton(paths, label, onClick) {
    const button = el('button', 'pf-newview-icon');
    button.type = 'button';
    button.setAttribute('aria-label', label);
    button.title = label;
    button.appendChild(ns.svg(paths, 14));
    button.addEventListener('click', onClick);
    return button;
  }

  /** Repaint ``list`` with ``fill(list)`` and keep it scrolled where it was. */
  function repaintList(list, fill) {
    const top = list.scrollTop;
    list.textContent = '';
    fill(list);
    list.scrollTop = top;
  }

  let host = null;   // what the page lends (see the top)
  let renaming = null;   // {id, name, working} while the rename question is open
  let deleting = null;   // {id, name, working} while the delete question is open
  let newView = null;    // while the dialog is open: {fields: [{key, title, group}] (null until read), chosen: [keys, in the order shown], making}

  // ---- Rename a view -----------------------------------------------------------------

  function closeRenameView() {
    if (renaming && renaming.working) return;
    renaming = null;
    $('products-renview-modal').hidden = true;
  }

  function syncRename() {
    showChars($('products-renview-name'), $('products-renview-chars'));
    const name = $('products-renview-name').value.trim();
    $('products-renview-ok').disabled = renaming.working || !name || name === renaming.name || name.length > $('products-renview-name').maxLength;
  }

  function askRenameView(v) {
    // Views of one name are listed with their id after it, to tell them apart: it is not part of the name.
    const suffix = ' (' + v.id + ')';
    const name = v.name.slice(-suffix.length) === suffix ? v.name.slice(0, -suffix.length) : v.name;
    renaming = { id: v.id, name: name, working: false };
    $('products-renview-name').value = name;
    host.setAlert('products-renview-error', '');
    $('products-renview-modal').hidden = false;
    $('products-renview-name').select();
    syncRename();
  }

  function renameView() {
    if ($('products-renview-ok').disabled) return;
    const mine = renaming;
    mine.working = true;
    host.setAlert('products-renview-error', '');
    syncRename();
    host.ask('products_rename_view', { view: mine.id, name: $('products-renview-name').value.trim() }, function (answer) {
      mine.working = false;
      if (!answer.ok) {
        host.setAlert('products-renview-error', host.failure(answer));
        syncRename();
        return;
      }
      closeRenameView();
      host.reload();   // the view stays the one shown; the list has its new name
    });
  }

  // ---- Delete a view -----------------------------------------------------------------

  function closeDeleteView() {
    if (deleting && deleting.working) return;
    deleting = null;
    $('products-delview-modal').hidden = true;
  }

  function askDeleteView(v) {
    deleting = { id: v.id, name: v.name, working: false };
    $('products-delview-text').textContent = t('products.delview_text', { name: v.name });
    host.setAlert('products-delview-error', '');
    $('products-delview-ok').disabled = false;
    $('products-delview-modal').hidden = false;
    $('products-delview-cancel').focus();
  }

  function deleteView() {
    const mine = deleting;
    mine.working = true;
    $('products-delview-ok').disabled = true;
    host.setAlert('products-delview-error', '');
    host.ask('products_delete_view', { view: mine.id }, function (answer) {
      mine.working = false;
      if (!answer.ok) {
        host.setAlert('products-delview-error', host.failure(answer));
        $('products-delview-ok').disabled = false;
        return;
      }
      closeDeleteView();
      host.deleted(mine.id);   // the list is read again and shows another view
      host.reload();
    });
  }

  // ---- Create New View ---------------------------------------------------------------
  // A name and the columns to show: the chosen columns on the left (the columns of the view in use to start with, in their order, which can
  // be moved or removed), every other field a view can show on the right, by section. The view is made without filters: they are set on it
  // afterwards, as on any view.

  function closeNewView() {
    if (newView && newView.making) return;
    newView = null;
    $('products-newview-modal').hidden = true;
  }

  function newViewError(message) { host.setAlert('products-newview-error', message); }

  /** The button can be pressed once there is a name and a column. */
  function syncNewView() {
    const count = newView.chosen.length;
    $('products-newview-count').textContent = newView.fields ? t('products.newview_count', { n: count }) : '';
    $('products-newview-clear').hidden = !count;
    showChars($('products-newview-name'), $('products-newview-chars'));
    const name = $('products-newview-name').value.trim();
    $('products-newview-create').disabled = newView.making || !newView.fields || !count || !name || name.length > $('products-newview-name').maxLength;
  }

  /** Move a chosen column to ``to`` (its place among the chosen), and show the lists again with the keyboard on the moved row. */
  function moveChosen(from, to) {
    const keys = newView.chosen;
    if (to < 0 || to >= keys.length) return;
    keys.splice(to, 0, keys.splice(from, 1)[0]);
    paintNewView();
    $('products-newview-chosen').querySelectorAll('.pf-newview-row')[to].focus();
  }

  /** Drag a chosen column by its grip to a new place (see sortable.js). */
  function dragChosen(event, row) {
    ns.sortable.start(event, { row: row, list: $('products-newview-chosen'), rowSelector: '.pf-newview-row', onDrop: moveChosen });
  }

  function chooseField(key) {
    newView.chosen.push(key);
    paintNewView();
  }

  function unchooseField(key) {
    newView.chosen = newView.chosen.filter(function (k) { return k !== key; });
    paintNewView();
  }

  /** The two lists: the columns chosen, in the order the view will show them (left), and the fields still to choose from that match the search,
   *  under their section (right). */
  function paintNewView() {
    const fields = newView.fields;
    repaintList($('products-newview-chosen'), function (list) {
      if (!fields) return;
      const byKey = {};
      fields.forEach(function (f) { byKey[f.key] = f; });
      if (!newView.chosen.length) list.appendChild(el('p', 'pf-newview-note', t('products.newview_empty_selected')));
      newView.chosen.forEach(function (key, index) {
        const field = byKey[key];
        const row = el('div', 'pf-newview-row');
        row.tabIndex = 0;
        row.title = t('products.newview_row_hint');
        const grip = el('span', 'pf-newview-grip');
        grip.appendChild(ns.svg(ns.sortable.GRIP, 16));
        grip.addEventListener('pointerdown', function (event) { dragChosen(event, row); });
        row.appendChild(grip);
        row.appendChild(el('span', 'pf-newview-order', String(index + 1)));
        const name = el('span', 'pf-newview-name', field.title);
        if (field.group) name.title = field.group;
        row.appendChild(name);
        row.appendChild(makeIconButton(['M6 6l12 12', 'M18 6L6 18'], t('products.newview_remove', { title: field.title }), function () { unchooseField(key); }));
        row.addEventListener('keydown', function (event) {   // Alt+Up and Alt+Down move the row, Delete removes it
          if (event.target !== row) return;
          if (event.altKey && (event.key === 'ArrowUp' || event.key === 'ArrowDown')) { event.preventDefault(); moveChosen(index, index + (event.key === 'ArrowUp' ? -1 : 1)); }
          else if (event.key === 'Delete') { event.preventDefault(); unchooseField(key); }
        });
        list.appendChild(row);
      });
    });
    repaintList($('products-newview-list'), function (list) {
      if (!fields) { list.appendChild(el('p', 'pf-newview-note', t('products.newview_loading'))); return; }
      const words = $('products-newview-search').value.trim().toLowerCase();
      const left = fields.filter(function (f) { return newView.chosen.indexOf(f.key) < 0; });
      const shown = left.filter(function (f) { return !words || (f.title + ' ' + f.group).toLowerCase().indexOf(words) >= 0; });
      if (!shown.length) { list.appendChild(el('p', 'pf-newview-note', left.length ? t('products.newview_none') : t('products.newview_all_added'))); return; }
      let group = null;
      shown.forEach(function (f) {
        if (f.group !== group) { group = f.group; if (group) list.appendChild(el('h4', 'pf-newview-group', group)); }
        const button = el('button', 'pf-newview-field');
        button.type = 'button';
        button.title = t('products.newview_add', { title: f.title });
        button.appendChild(el('span', 'pf-newview-name', f.title));
        button.appendChild(ns.svg(['M12 5v14', 'M5 12h14'], 14));
        button.addEventListener('click', function () { chooseField(f.key); });
        list.appendChild(button);
      });
    });
    syncNewView();
  }

  function openNewView() {
    if (host.isBusy()) return;
    newView = { fields: null, chosen: [], making: false };
    $('products-newview-name').value = t('products.newview_default_name');
    $('products-newview-search').value = '';
    newViewError('');
    $('products-newview-modal').hidden = false;
    $('products-newview-name').select();
    paintNewView();
    syncNewView();
    const mine = newView;
    host.ask('products_fields', {}, function (answer) {
      if (newView !== mine) return;   // closed while it was read
      if (!answer.ok) { newViewError(host.failure(answer)); mine.fields = []; }
      else mine.fields = answer.result.fields;
      const known = new Set(mine.fields.map(function (f) { return f.key; }));
      mine.chosen = (host.columns() || []).map(function (c) { return c.key; }).filter(function (key) { return known.has(key); });
      paintNewView();
      syncNewView();
    });
  }

  function makeNewView() {
    if ($('products-newview-create').disabled) return;
    const mine = newView;
    const name = $('products-newview-name').value.trim();
    mine.making = true;
    newViewError('');
    $('products-newview-create').textContent = t('products.newview_creating');
    syncNewView();
    host.ask('products_create_view', { name: name, columns: mine.chosen }, function (answer) {
      mine.making = false;
      $('products-newview-create').textContent = t('products.newview_create');
      if (!answer.ok) { newViewError(host.failure(answer)); syncNewView(); return; }
      closeNewView();
      host.created(answer.result.id);   // the list is read again and the new view is the one shown
      host.reload();
    });
  }

  /** Close the dialog of this module that is open (the one on top, in the order rename, delete, new); false when none is. */
  function closeFront() {
    if (!$('products-renview-modal').hidden) { closeRenameView(); return true; }
    if (!$('products-delview-modal').hidden) { closeDeleteView(); return true; }
    if (!$('products-newview-modal').hidden) { closeNewView(); return true; }
    return false;
  }

  function closeBackdrop(modalId, close) {
    $(modalId).addEventListener('click', function (event) { if (event.target === event.currentTarget) close(); });
  }

  function wireDialogs() {
    $('products-renview-name').addEventListener('input', syncRename);
    $('products-renview-name').addEventListener('keydown', function (event) { if (event.key === 'Enter') renameView(); });
    $('products-renview-ok').addEventListener('click', renameView);
    $('products-renview-cancel').addEventListener('click', closeRenameView);
    closeBackdrop('products-renview-modal', closeRenameView);
    $('products-delview-ok').addEventListener('click', deleteView);
    $('products-delview-cancel').addEventListener('click', closeDeleteView);
    closeBackdrop('products-delview-modal', closeDeleteView);
    $('products-newview-name').addEventListener('input', syncNewView);
    $('products-newview-name').addEventListener('keydown', function (event) { if (event.key === 'Enter') makeNewView(); });
    $('products-newview-search').addEventListener('input', paintNewView);
    $('products-newview-clear').addEventListener('click', function () { newView.chosen = []; paintNewView(); });
    $('products-newview-create').addEventListener('click', makeNewView);
    $('products-newview-cancel').addEventListener('click', closeNewView);
    closeBackdrop('products-newview-modal', closeNewView);
  }

  ns.productViews = {
    init: function (lent) {
      host = lent;
      wireDialogs();
      return { askRename: askRenameView, askDelete: askDeleteView, openNew: openNewView, closeFront: closeFront };
    }
  };
})(window.MfgUi);
