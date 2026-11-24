/**
 * Publish Item panel: the dialog of the structure viewer, as ``ns.pubItemPanel``. A modal dialog over the page holds a form for
 * (a) a new manufacturing item (``items_form`` / ``items_create``) or (b) a bought version of an item the MBOM holds (``bought_open``, which answers
 * the bought version there is already or the form, then ``bought_create``). Both forms are the Items workspace's own, drawn with the shared ``ns.formControls`` (dev/workspace-forms.md); Python sets
 * the item number of a bought version, Make or buy and the source link itself: those fields stay in their sections of the form, locked, showing the
 * value they will have (``locked``).
 *
 * Requests: ``items_*`` answers are polled with ``items_status`` as ``products_*`` are polled with ``products_status``. The options of a picklist or
 * link field are read with ``search_options`` (polled with ``search_status``), which the Add Items picker uses too: the bridge keeps one listener
 * for an action, so ``add-items.js`` hands this file the ``search_*`` answers through ``claims``. A picklist is asked for by its name alone, so
 * the action is not tied to the Items workspace.
 *
 * ``open({mode: 'assembly'})`` or ``open({mode: 'bought', sourceNumber, number, onFound, onCreated})`` (the create is sent with the ``source_id`` the answer holds); a bought dialog offers the bought
 * version found (``onFound``) and ``close()``. The values typed are kept when saving
 * fails, and Save stays off while a request runs, so one click makes one item. A saved item is told in the dialog with its number and given to
 * ``onCreated`` (a bought one found in Fusion Manage, to ``onFound``): the viewer adds it to the structure.
 */
(function (ns) {
  'use strict';

  const bridge = ns.bridge;
  const ui = ns.pubUi;
  const el = ui.el;
  function t(key, params) { return ns.i18n.t(key, params); }

  const POLL_MS = 200;
  const ICON_CLOSE = ['M6 6l12 12', 'M18 6L6 18'];
  // The icons of the viewer's two buttons (``mbom-viewer.js``), shown in front of the title of the dialog they open. The last two paths of the box are its plus.
  const ICON_NEW = ['M10 3l7 4v6', 'M17 7l-7 4-7-4', 'M10 11v9', 'M3 7v10l7 4', 'M10 3L3 7', 'M18 14.5v7', 'M14.5 18h7'];
  const ICON_BOUGHT = ['M3 4h2.5l2 11h10l2-8H7', 'M10 19.5h.01', 'M17 19.5h.01'];
  const ICON_OPEN = ['M15 3h6v6', 'M10 14L21 3', 'M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6'];   // a square with an arrow out of it
  const OWN = ['items_form', 'items_create', 'bought_open', 'bought_create'];

  // ---- Talking to Python -------------------------------------------------------------

  let nextToken = 1;
  const waiting = new Map();   // token -> {poll: the status action, done}

  /** Send ``action`` and call ``done(answer)`` with ``{ok, result, message, fields}`` once Python has one. */
  function ask(action, payload, done) {
    const token = 'ic' + (nextToken++);
    waiting.set(token, { poll: action === 'search_options' ? 'search_status' : 'items_status', done: done });
    bridge.send(action, Object.assign({ token: token }, payload));
  }

  /** The bridge refused (the action raised before it could answer): tell every request polled with ``poll`` that it failed. */
  function failAll(poll, message) {
    Array.from(waiting.entries()).forEach(function (pair) {
      if (pair[1].poll !== poll) return;
      waiting.delete(pair[0]);
      pair[1].done({ ok: false, message: message });
    });
  }

  /** An answer of an ``items_*`` or ``search_*`` action. Answers whose token is not ours are ignored. Returns whether the answer was ours. */
  function onAnswer(action, r) {
    if (!r.ok) { failAll(/^search_/.test(action) ? 'search_status' : 'items_status', r.error || t('publish.unknown_error')); return false; }
    const answer = r.result;
    const waiter = answer && waiting.get(answer.token);
    if (!waiter) return false;
    if (answer.pending) {
      setTimeout(function () { if (waiting.has(answer.token)) bridge.send(waiter.poll, { token: answer.token }); }, POLL_MS);
      return true;
    }
    waiting.delete(answer.token);
    waiter.done(answer);
    return true;
  }

  /** For ``add-items.js``, which owns the ``search_options`` and ``search_status`` listeners: true when ``r`` answers a request made here (a failure is
   *  passed on to the requests of both). */
  function claims(action, r) { return onAnswer(action, r); }

  function failure(answer) { return answer.message || t('publish.unknown_error'); }

  const fc = ns.formControls.make({
    ask: ask, failure: failure, openLightbox: function () {},
    actions: { options: 'search_options' },   // a picklist is read by its name: the same request as the Add Items picker's
  });

  // ---- The dialog -------------------------------------------------------------------------

  let modal = null;   // {root (the overlay), title, message, body, save, close} once made
  let view = null;     // the open form: {mode, sourceNumber, sourceId, working, saved}

  function ensure() {
    if (modal) return modal;
    const root = el('div', 'ic-overlay');
    root.hidden = true;
    const dialog = el('section', 'ic-dialog');
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    const head = el('div', 'ic-head');
    const lead = el('span', 'ic-title-icon');
    lead.setAttribute('aria-hidden', 'true');
    const title = el('h3', 'ic-title');
    const close = el('button', 'ic-close');
    close.type = 'button';
    close.title = t('products.close');
    close.setAttribute('aria-label', t('products.close'));
    close.appendChild(ns.svg(ICON_CLOSE, 18));
    head.append(lead, title, close);
    const message = el('p', 'error ic-message');
    message.setAttribute('role', 'alert');
    message.hidden = true;
    const body = el('div', 'ic-body');
    const foot = el('div', 'ic-foot');
    const save = el('button', 'btn ic-save', t('publish.item_save'));
    save.type = 'button';
    const cancel = el('button', 'btn btn-secondary ic-cancel', t('products.cancel'));
    cancel.type = 'button';
    foot.append(save, cancel);
    dialog.append(head, message, body, foot);
    root.appendChild(dialog);
    document.body.appendChild(root);
    root.addEventListener('mousedown', function (event) { if (event.target === root) close_(); });
    close.addEventListener('click', function () { close_(); });
    cancel.addEventListener('click', function () { close_(); });
    save.addEventListener('click', submit);
    root.addEventListener('keydown', function (event) { if (event.key === 'Escape') close_(); });
    modal = { root: root, dialog: dialog, lead: lead, title: title, message: message, body: body, foot: foot, save: save, cancel: cancel, close: close };
    return modal;
  }

  function say(text) {
    modal.message.textContent = text;
    modal.message.hidden = !text;
  }

  /** Is a request of the dialog under way? */
  function busy() { return !!(view && view.working); }

  /** Close the dialog. A request under way cannot be taken back, so it keeps the dialog until its answer is in. */
  function close_() {
    if (!modal || busy()) return;
    view = null;
    fc.reset();
    modal.root.hidden = true;
    modal.body.replaceChildren();
    say('');
  }

  /** Set Save and the other buttons for the state of the form: ``on`` lets Save be used. */
  function setButtons() {
    const working = busy();
    const saved = !!(view && view.saved);
    modal.save.hidden = saved;
    modal.save.disabled = working || !view || !view.ready;
    modal.save.textContent = working ? t('publish.item_saving') : view && view.found ? t('publish.item_use_existing') : t('publish.item_save');
    modal.cancel.disabled = working;
    modal.close.disabled = working;
    modal.cancel.textContent = saved ? t('products.close') : t('products.cancel');
  }

  // ---- Painting the form ------------------------------------------------------------------

  /** A value ``form_value`` (Python) gives, as ``setFieldValue`` takes it: the controls take a picklist option as ``{link}``, as Fusion Manage holds it. */
  function held(spec, value) {
    return (spec.kind === 'select' || spec.kind === 'radio') && typeof value === 'string' ? { link: value } : value;
  }

  /** The fields of a form made by ``WorkspaceFormService``, in the order of its sections (a matrix is laid out row by row). */
  function specsOf(form) {
    const list = [];
    form.sections.forEach(function (section) {
      const fields = section.fields.slice();
      section.matrices.forEach(function (m) { m.rows.forEach(function (row) { row.forEach(function (s) { if (s) fields.push(s); }); }); });
      list.push({ title: section.title, fields: fields, collapsed: section.collapsed === true });
    });
    return list;
  }

  const MANY_OPTIONS = 6;   // a list of radio buttons longer than this takes more room than the dialog has

  /** A field of radio buttons with many options, as a drop-down (the same value: the option's value), so it does not push the form down. */
  function longRadios(spec) {
    return spec.kind === 'radio' && spec.options.length > MANY_OPTIONS ? Object.assign({}, spec, { kind: 'select' }) : spec;
  }

  /** A line of the form for a read-only value: the label and the value in a box that cannot be changed. */
  function readOnlyLine(label, text, tip) {
    const line = fc.fieldLine({ title: label, required: false, kind: 'text' });
    line.value.appendChild(fc.autoBox({ description: text }));
    if (tip) line.label.appendChild(fc.infoIcon(tip));
    return line.row;
  }

  function paintForm(result) {
    const body = modal.body;
    fc.reset();
    body.replaceChildren();
    const bought = view.mode === 'bought';
    const locked = result.locked || {};   // {field id: the value the add-in gives it}: in its own section, shown and never sent
    const values = result.values || {};
    const sections = specsOf(result.form);
    sections.forEach(function (section) {
      if (!section.fields.length) return;
      const box = el('div', 'ic-section');
      section.fields.forEach(function (field) {
        const spec = longRadios(field);
        if (Object.prototype.hasOwnProperty.call(locked, spec.id)) {
          box.appendChild(readOnlyLine(spec.title, locked[spec.id], bought && spec.id === result.number_field ? t('publish.bought_number_tip') : ''));
          return;
        }
        if (spec.kind === 'auto' || spec.kind === 'info') {   // Fusion Manage fills it in: shown, never sent
          box.appendChild(readOnlyLine(spec.title, spec.description, ''));
          return;
        }
        const line = fc.fieldLine(spec);
        const record = fc.addField(spec, line.row);
        fc.fillLine(line, record);
        if (spec.description) line.label.appendChild(fc.infoIcon(spec.description));
        if (Object.prototype.hasOwnProperty.call(values, spec.id)) fc.setFieldValue(record, held(spec, values[spec.id]));
        box.appendChild(line.row);
      });
      const needed = section.fields.some(function (f) { return f.required && !Object.prototype.hasOwnProperty.call(locked, f.id); });
      body.appendChild(ns.section.make(section.title, box, { folded: section.collapsed && !needed }));   // as the workspace has it, but never hides a required field
    });
    body.appendChild(el('p', 'muted ic-required', t('publish.item_required_note')));
    view.ready = result.can_create !== false;
    if (!view.ready) say(t('publish.item_no_permission'));
    setButtons();
  }

  function paintFailure(text, again) {
    const mine = view;
    modal.body.replaceChildren(ui.errorState(text, function () { if (view === mine) (again || load)(); }));
    view.ready = false;
    setButtons();
  }

  // ---- Reading and saving ---------------------------------------------------------------

  /** Read what the dialog shows. A bought version is one request, ``bought_open``: ``{found: {id, link, number, name, url}}``, the bought version there is
   *  already (offered with ``paintFound`` so a second is not made), or the form, which holds ``source_id``, the item the create is sent with (it searches for
   *  nothing). A new item reads the Items form. */
  function load() {
    const mine = view;
    mine.ready = false;
    say('');
    modal.body.replaceChildren(ui.loaderNode());
    setButtons();
    const bought = mine.mode === 'bought';
    ask(bought ? 'bought_open' : 'items_form', bought ? { source_number: mine.sourceNumber } : { kind: 'assembly' }, function (answer) {
      if (view !== mine) return;
      if (!answer.ok) { paintFailure(failure(answer)); return; }
      if (bought && answer.result.found) { paintFound(answer.result.found); return; }
      mine.sourceId = answer.result.source_id || '';
      paintForm(answer.result);
    });
  }

  /** Show what a refused save said: under each field it names, and in the message line for the rest (a field the form does not hold, such as the
   *  number of a bought version). Answers the first field named. */
  function showRefusal(answer) {
    const first = fc.showRefusals(answer.fields);
    const shown = new Set(fc.fields.map(function (f) { return f.id; }));
    const extra = Object.keys(answer.fields || {}).filter(function (id) { return !shown.has(id); }).map(function (id) { return answer.fields[id]; });
    const lines = [answer.message].concat(extra).filter(function (text, i, all) { return text && all.indexOf(text) === i; });
    say(lines.length ? lines.join(' ') : t('publish.unknown_error'));
    return first;
  }

  /** Unfold the sections that hold a field with a message, so none is left hidden behind a folded bar. */
  function reveal() {
    [].forEach.call(modal.body.querySelectorAll('.section.folded'), function (card) {
      if ([].some.call(card.querySelectorAll('.pf-error'), function (line) { return !line.hidden; })) ns.section.unfold(card);
    });
  }

  function submit() {
    if (!view || !view.ready || view.working) return;
    if (view.found) {   // the bought version that is there already is used: nothing is made
      const found = view.found;
      const use = view.onFound;
      close_();
      if (use) use(found);
      return;
    }
    say('');
    const picked = fc.collect();
    if (picked.first) {
      say(t('publish.item_fix_fields'));
      reveal();
      (picked.first.input.control || picked.first.input).focus();
      return;
    }
    const mine = view;
    const bought = mine.mode === 'bought';
    mine.working = true;
    setButtons();
    ask(bought ? 'bought_create' : 'items_create', bought ? { source_id: mine.sourceId, values: picked.values } : { values: picked.values }, function (answer) {
      mine.working = false;
      if (view !== mine) return;
      if (!answer.ok) {   // the values stay as they were typed
        const first = showRefusal(answer);
        reveal();
        if (first) (first.input.control || first.input).focus();
        setButtons();
        return;
      }
      mine.saved = true;
      if (mine.onCreated) mine.onCreated(answer.result);
      fc.reset();
      modal.body.replaceChildren(el('p', 'ic-saved', t('publish.item_saved', { number: answer.result.number })));
      say('');
      setButtons();
      modal.cancel.focus();
    });
  }

  /** Say that the bought version exists; Save (now "Use existing item") hands it to ``onFound`` and closes the dialog. */
  function paintFound(found) {
    fc.reset();
    view.found = found;
    const card = el('div', 'ic-found-card');
    const text = el('div', 'ic-found-text');
    text.append(el('strong', 'ic-found-number', found.number), el('span', 'ic-found-name', found.name || ''));
    card.appendChild(text);
    if (found.url) {   // its page in Fusion Manage, in the system browser
      const open = el('button', 'ic-found-open');
      open.type = 'button';
      open.append(ns.svg(ICON_OPEN, 14), el('span', '', t('publish.item_found_open')));
      open.addEventListener('click', function () { bridge.send('open_url', { url: found.url }); });
      card.appendChild(open);
    }
    const wrap = el('div', 'ic-found');
    wrap.append(el('p', 'ic-found-lead', t('publish.item_found_lead', { source: view.sourceNumber })), card, el('p', 'ic-found-ask', t('publish.item_found_ask')));
    modal.body.replaceChildren(wrap);
    view.ready = true;
    setButtons();
    modal.save.focus();
  }

  /** Open the dialog for ``spec`` (``{mode: 'assembly'}`` or ``{mode: 'bought', sourceNumber, number, onFound, onCreated}``; ``onCreated(result)`` is called
   *  when the item was saved, ``onFound(item)`` when the bought version found was chosen). A request under way keeps the modal as it is. */
  function open(spec) {
    ensure();
    if (busy()) return;
    fc.reset();
    view = { mode: spec.mode, sourceNumber: spec.sourceNumber || '', sourceId: '',
             working: false, saved: false, ready: false, onCreated: spec.onCreated, onFound: spec.onFound, found: null };
    const title = spec.mode === 'bought' ? t('publish.item_title_bought', { number: spec.number }) : t('publish.item_title_assembly');
    modal.title.textContent = title;
    const icon = ns.svg(spec.mode === 'bought' ? ICON_BOUGHT : ICON_NEW, 20);
    if (spec.mode !== 'bought') [].slice.call(icon.querySelectorAll('path'), -2).forEach(function (p) { p.setAttribute('class', 'ic-plus'); });
    modal.lead.replaceChildren(icon);
    modal.dialog.setAttribute('aria-label', title);
    modal.root.hidden = false;
    load();
    modal.close.focus();
  }

  OWN.concat(['items_status']).forEach(function (action) { bridge.on(action, function (r) { onAnswer(action, r); }); });

  ns.pubItemPanel = { open: open, close: close_, claims: claims };
})(window.MfgUi);
