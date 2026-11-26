/**
 * The controls of a form made from a ``WorkspaceFormService`` spec (see dev/workspace-forms.md), shared by the Products and Publish pages.
 * Layer: UI (shared form controls; the checks themselves are ``ns.validators``).
 *
 * ``ns.formControls.make({ask, failure, openLightbox, actions})`` answers one form's worth of controls:
 *   ``ask(action, payload, done)`` sends a request to Python and calls ``done(answer)`` (``answer.ok``, ``answer.result``);
 *   ``failure(answer)`` says in words why a request failed; ``openLightbox(src)`` shows a picture large;
 *   ``actions`` (optional) names the requests: ``options`` (a page of a picklist, default ``products_options``) and ``picture``
 *   (the picture a link names, default ``products_picture``).
 * Each spec is ``{id, title, kind, required, description, options, lookup, max_length, validators}``. A record is made of one with
 * ``addField(spec, wrap)``; ``valueOf(record)`` reads the value it would send (see the table in dev/workspace-forms.md).
 */
(function (ns) {
  'use strict';

  const el = ns.el;
  const t = ns.i18n.t;
  const blank = ns.validators.blank;

  const MAX_IMAGE_MB = 5;   // an image larger than this is not sent
  const SELECT_SEARCH_FROM = 8;   // a list of choices shows its search box from this many on

  // ``io`` below is ``{ask, failure, actions}`` of the form that was made: how a control reaches Python.

  /** A field that takes items of another workspace: the shared picker, its list read from Python as it is searched and scrolled; the choice is
   *  shown on the button (or as chips, for several). */
  function linkPicker(field, multi, io) {
    const root = ns.picker.make({
      className: 'pk-form',
      inlineSearch: true,
      buttonClass: 'form-input',
      multi: multi,
      placeholder: t('products.link_select'),
      search: t('products.link_search'),
      empty: function () { return t('products.link_empty'); },
      text: {
        clear: t('products.link_clear'),
        loading: t('products.link_loading'),
        showing: function (shown, total) { return t('products.link_showing', { shown: shown.toLocaleString(), total: total.toLocaleString() }); },
      },
      source: function (text, offset, done) {
        io.ask(io.actions.options, { lookup: field.lookup, offset: offset, text: text }, function (answer) {
          if (!answer.ok) { done({ error: io.failure(answer) }); return; }
          const page = answer.result;
          done({
            items: page.options.map(function (o) { return { value: o.value, label: o.title }; }),
            next: offset + page.raw,
            total: page.raw ? page.total : 0,   // an empty page is the end, whatever the total says
          });
        });
      },
    });
    root.setValue = function (raw) {   // the items a product holds already, as Fusion Manage gives them: {link, title}, or a list of them
      root.setPicked((Array.isArray(raw) ? raw : [raw]).filter(function (o) { return o.link; })
        .map(function (o) { return { value: o.link, label: o.title || o.link }; }));
    };
    root.getValue = function () {
      const picked = root.getPicked();
      if (!picked.length) return '';
      return multi ? picked.map(function (o) { return { link: o.value }; }) : { link: picked[0].value };
    };
    return root;
  }

  /** A field with a fixed list of choices: the shared picker, with the first entry ("Choose...") taking the choice back. The value is the choice's
   *  value, '' for none. */
  function selectPicker(field) {
    const options = field.options.map(function (o) { return { value: o.value, label: o.title }; });
    const root = ns.picker.make({
      className: 'pk-form',
      inlineSearch: true,
      buttonClass: 'form-input',
      ariaLabel: field.title,
      searchFrom: SELECT_SEARCH_FROM,
      placeholder: t('products.select_none'),
      search: t('products.link_search'),
      empty: function () { return t('products.link_empty'); },
      text: { clear: t('products.select_none') },
      label: function (value) { return options.find(function (o) { return o.value === value; }).label; },
      groups: function () { return [{ title: '', items: options }]; },
    });
    root.addEventListener('pick', function () { root.dispatchEvent(new Event('change', { bubbles: true })); });   // the form looks at the field again
    root.control = root.querySelector('.pk-btn');   // what the form focuses
    root.setValue = function (raw) {   // a choice the list does not hold leaves it unchosen
      root.setPicked(options.filter(function (o) { return o.value === (raw.link || ''); }));
    };
    root.getValue = function () { const picked = root.getPicked(); return picked.length ? picked[0].value : ''; };
    return root;
  }

  /** The parts of an image field, put together: ``{root, zone, text, picture, skeleton, choose, remove, problem, file}``. */
  function buildImageParts() {
    const root = el('div', 'im');
    const zone = el('div', 'im-zone');
    const text = el('span', 'im-text', t('products.image_drop'));
    const picture = el('img', 'im-picture');
    picture.alt = '';
    picture.hidden = true;
    const skeleton = el('div', 'im-skeleton');   // stands in for the picture a product holds while it is on its way
    skeleton.hidden = true;
    zone.appendChild(text);
    zone.appendChild(picture);
    zone.appendChild(skeleton);
    const choose = el('button', 'btn btn-secondary im-choose', t('products.image_choose'));
    choose.type = 'button';
    const remove = el('button', 'btn btn-secondary im-choose', t('products.image_remove'));
    remove.type = 'button';
    remove.hidden = true;
    const problem = el('p', 'im-problem');
    problem.hidden = true;
    const file = el('input');
    file.type = 'file';
    file.accept = 'image/*';
    file.hidden = true;
    root.appendChild(zone);
    const side = el('div', 'im-side');
    side.appendChild(choose);
    side.appendChild(remove);
    side.appendChild(problem);
    root.appendChild(side);
    root.appendChild(file);
    return { root: root, zone: zone, text: text, picture: picture, skeleton: skeleton, choose: choose, remove: remove, problem: problem, file: file };
  }

  /** Is ``chosen`` (a File) a picture the form may send? */
  function isAcceptableImage(chosen) {
    return /^image\//.test(chosen.type) && chosen.size <= MAX_IMAGE_MB * 1024 * 1024;
  }

  /** Make the drop zone take a dragged file with ``take(file)``. */
  function wireDropZone(zone, take) {
    ['dragenter', 'dragover'].forEach(function (name) {
      zone.addEventListener(name, function (event) { event.preventDefault(); zone.classList.add('over'); });
    });
    ['dragleave', 'drop'].forEach(function (name) {
      zone.addEventListener(name, function (event) { event.preventDefault(); zone.classList.remove('over'); });
    });
    zone.addEventListener('drop', function (event) { take(event.dataTransfer.files[0]); });
  }

  /** An image field: a drop zone with a preview and a button to choose a file. The value is the picture as a data URL, as the publish sends one. */
  function imagePicker(openLightbox) {
    const parts = buildImageParts();
    const root = parts.root;
    const picture = parts.picture;
    picture.addEventListener('click', function () { openLightbox(picture.src); });

    let data = '';       // the picture chosen here, sent on saving
    let existing = '';   // the picture the product holds, shown until it is cleared (never sent again)
    let loading = false;
    // With a picture there is no Choose button: it is cleared first, and then another can be chosen.
    function show(url) {
      data = url;
      const seen = url || existing;
      picture.src = seen;
      picture.hidden = !seen;
      parts.text.hidden = !!seen || loading;
      parts.skeleton.hidden = !loading;
      parts.choose.hidden = !!seen || loading;
      parts.remove.hidden = !seen;
      root.dispatchEvent(new Event('change', { bubbles: true }));   // the form's footer looks again
    }
    function take(chosen) {
      parts.problem.hidden = true;
      if (!chosen || data || existing || loading) return;
      if (!isAcceptableImage(chosen)) {
        parts.problem.textContent = t('products.image_bad', { size: MAX_IMAGE_MB });
        parts.problem.hidden = false;
        return;
      }
      const reader = new FileReader();
      reader.onload = function () { show(String(reader.result)); };
      reader.readAsDataURL(chosen);
    }
    parts.choose.addEventListener('click', function () { parts.file.click(); });
    parts.file.addEventListener('change', function () { take(parts.file.files[0]); parts.file.value = ''; });
    parts.remove.addEventListener('click', function () { existing = ''; show(''); });
    wireDropZone(parts.zone, take);
    root.getValue = function () { return data; };
    root.setLoading = function () { loading = true; show(data); };
    root.setExisting = function (url) { existing = url || ''; loading = false; show(data); };
    return root;
  }

  /** Is ``input`` a control of its own that a label can point at (a radio group and a picker are not: they hold several)? */
  function aimable(kind, input) { return kind !== 'radio' && !input.getValue; }

  function buildTextarea() {
    const input = el('textarea', 'form-input');
    input.rows = 2;
    return input;
  }

  /** A short list is all in view, as in Fusion Manage. */
  function buildRadios(field) {
    const input = el('div', 'form-radios');
    input.setAttribute('role', 'radiogroup');
    input.setAttribute('aria-label', field.title);
    field.options.forEach(function (o) {
      const label = el('label', 'form-radio');
      const radio = el('input');
      radio.type = 'radio';
      radio.name = 'f-' + field.id;
      radio.value = o.value;
      label.appendChild(radio);
      label.appendChild(el('span', '', o.title));
      input.appendChild(label);
    });
    return input;
  }

  function buildCheckbox() {
    const input = el('input', 'form-check');
    input.type = 'checkbox';
    return input;
  }

  /** The ``type`` of the box of a field that is typed in. */
  function textInputType(kind) {
    if (kind === 'date') return 'date';
    if (kind === 'integer' || kind === 'number') return 'number';
    return 'text';
  }

  function buildTextInput(field) {
    const input = el('input', 'form-input');
    input.type = textInputType(field.kind);
    if (field.kind === 'integer') input.step = '1';
    else if (field.kind === 'number') input.step = 'any';
    input.autocomplete = 'off';
    input.spellcheck = false;
    return input;
  }

  /** The builders of the kinds that are not a plain text box: kind -> ``(field, deps) => element``. ``deps`` is ``{io, openLightbox}``. */
  const INPUT_BUILDERS = new Map([
    ['link', function (field, deps) { return linkPicker(field, false, deps.io); }],
    ['links', function (field, deps) { return linkPicker(field, true, deps.io); }],
    ['image', function (field, deps) { return imagePicker(deps.openLightbox); }],
    ['textarea', buildTextarea],
    ['select', selectPicker],
    ['radio', buildRadios],
    ['checkbox', buildCheckbox],
  ]);

  /** ``input`` (a text box) with a count of its characters against ``limit`` in its corner: it stops at the limit and the count warns as it nears. */
  function counted(input, limit) {
    const wrap = el('div', 'fc' + (input.tagName === 'TEXTAREA' ? ' fc-area' : ''));
    const count = el('span', 'fc-count');
    count.setAttribute('aria-live', 'off');
    input.maxLength = limit;
    function update() {
      const n = input.value.length;
      count.textContent = t('products.char_count', { used: n, max: limit });
      count.classList.toggle('near', n >= limit * 0.9 && n < limit);
      count.classList.toggle('full', n >= limit);
    }
    input.addEventListener('input', update);
    wrap.appendChild(input);
    wrap.appendChild(count);
    wrap.control = input;   // what the form reads and focuses
    update();
    return wrap;
  }

  /** The control for one field. */
  function buildControl(field, deps) {
    const build = INPUT_BUILDERS.get(field.kind) || buildTextInput;
    const input = build(field, deps);
    input.id = 'f-' + field.id;
    if (aimable(field.kind, input)) input.setAttribute('aria-label', field.title);
    return field.max_length ? counted(input, field.max_length) : input;
  }

  /** The message under a field that is not right, for the form to fill. */
  function errorLine() {
    const line = el('p', 'pf-error');
    line.hidden = true;
    line.setAttribute('role', 'alert');
    return line;
  }

  /** The value of a field as sent: blank is left out, a checkbox only when ticked. */
  function valueOf(field) {
    if (field.input.getValue) return field.input.getValue();   // a picker or an image holds its own value
    if (field.input.control) return field.input.control.value.trim();   // a text box with a count
    if (field.kind === 'checkbox') return field.input.checked ? true : '';
    if (field.kind === 'radio') {
      const chosen = field.input.querySelector('input:checked');
      return chosen ? chosen.value : '';
    }
    return field.input.value.trim();
  }

  /** Check one field and show what is wrong with it beside it. Answers the message ('' when it is fine). */
  function showState(record) {
    const message = ns.validators.check(record, valueOf(record), record.lookup);
    record.error.textContent = message;
    record.error.hidden = !message;
    record.wrap.classList.toggle('invalid', !!message);
    return message;
  }

  /** Tell the person what is wrong with a field when they leave it (not before: an empty required field is not wrong yet). */
  function watchFocus(record) {
    record.wrap.addEventListener('focusout', function () { if (!blank(valueOf(record)) || record.wrap.classList.contains('invalid')) showState(record); });
  }

  /** Look at the whole form without marking any field: what is required, what is not right, and what is left to Fusion Manage. */
  function readFormReadiness(fields) {
    const needed = [];
    const problems = [];
    fields.forEach(function (field) {
      const value = valueOf(field);
      const empty = blank(value);
      if (field.required) needed.push({ field: field, done: !empty });
      const message = ns.validators.check(field, value, field.lookup);
      if (message && !(field.required && empty)) problems.push({ field: field, message: message });
    });
    const missing = needed.filter(function (n) { return !n.done; }).length;
    return { needed: needed, problems: problems, open: missing + problems.length };
  }

  /** The round "i" beside a field that has something to say about itself. */
  function infoIcon(text) {
    const icon = el('span', 'form-info', 'i');
    icon.title = text;
    icon.setAttribute('role', 'img');
    icon.setAttribute('aria-label', text);
    return icon;
  }

  /** What a field the add-in fills in itself shows in place of a control: a disabled box with the message. */
  function autoBox(field) {
    const box = el('div', 'form-input form-auto', field.description);
    box.setAttribute('aria-disabled', 'true');
    return box;
  }

  /** A line of the form for ``field``: its row (a tall control is aligned to the top), its label (starred when required) and the box for the control. */
  function fieldLine(field) {
    const row = el('div', 'pf-field' + (['textarea', 'radio', 'image', 'links'].indexOf(field.kind) >= 0 ? ' top' : ''));
    const label = el('label', 'pf-label');
    if (field.required) label.appendChild(el('span', 'form-star', '* '));
    label.appendChild(document.createTextNode(field.title));
    const value = el('div', 'pf-value');
    row.appendChild(label);
    row.appendChild(value);
    return { row: row, label: label, value: value };
  }

  /** Put the control of ``record`` and its message in ``line``, and point the label at the control where it can. */
  function fillLine(line, record) {
    if (aimable(record.kind, record.input)) line.label.htmlFor = (record.input.control || record.input).id;
    line.value.appendChild(record.input);
    line.value.appendChild(record.error);
  }

  /** The text of a value Fusion Manage holds: a picklist or a link is an object with a title. */
  function plain(raw) {
    return typeof raw === 'object' ? String(raw.title) : String(raw);
  }

  /** Ask for the picture a product holds and show it. ``wanted()`` (optional) says whether the form is still the one it was asked for. */
  function setImageValue(input, raw, wanted, io) {
    if (!raw.link) return;
    input.setLoading();   // every picture is asked for at once: the item has given the link to each
    io.ask(io.actions.picture, { link: raw.link }, function (answer) {
      if (!wanted || wanted()) input.setExisting(answer.ok ? answer.result.image : '');
    });
  }

  /** Put ``raw`` in the box or the radios of a field that holds no value of its own. */
  function setPlainValue(record, raw) {
    const input = record.input;
    const target = input.control || input;
    const link = raw.link || '';
    if (record.kind === 'checkbox') target.checked = raw === true || raw === 'true';
    else if (record.kind === 'radio') Array.prototype.forEach.call(input.querySelectorAll('input'), function (r) { r.checked = r.value === link; });
    else if (record.kind === 'date') target.value = plain(raw).slice(0, 10);
    else target.value = plain(raw);
    target.dispatchEvent(new Event('input', { bubbles: true }));   // the count of characters and the footer look again
  }

  /** Put what a product holds in the control of a field. A picture is shown as it is held, and sent only when a new one is chosen.
   *  ``wanted()`` (optional) says whether the form is still the one the picture was asked for. */
  function setFieldValue(record, raw, wanted, io) {
    if (raw === null || raw === undefined) return;
    if (record.kind === 'image') {   // the picture is asked for on its own, as the list's cells do
      setImageValue(record.input, raw, wanted, io);
      return;
    }
    if (record.input.setValue) { record.input.setValue(raw); return; }
    setPlainValue(record, raw);
  }

  /** Check every field and show what is wrong beside it. Answers ``{values, first}``: the non-blank values by field id, and the first record
   *  that is not right (null when all are). */
  function collectValues(fields) {
    let first = null;
    const values = {};
    fields.forEach(function (field) {
      const value = valueOf(field);
      if (showState(field) && !first) first = field;
      if (value !== '') values[field.id] = value;
    });
    return { values: values, first: first };
  }

  /** Show what Fusion Manage said of each field it named (``messages``: ``{field id: text}``). Answers the first record named, or null. */
  function showFieldRefusals(fields, messages) {
    let first = null;
    fields.forEach(function (field) {
      const message = messages && messages[field.id];
      if (!message) return;
      field.error.textContent = message;
      field.error.hidden = false;
      field.wrap.classList.add('invalid');
      if (!first) first = field;
    });
    return first;
  }

  function make(deps) {
    const io = {
      ask: deps.ask,
      failure: deps.failure,
      actions: Object.assign({ options: 'products_options', picture: 'products_picture' }, deps.actions),
    };
    const controlDeps = { io: io, openLightbox: deps.openLightbox };
    const fields = [];   // [{id, title, kind, required, validators, input, wrap, error, lookup}] of the form shown

    function control(field) { return buildControl(field, controlDeps); }

    /** The control of ``field`` with the message under it and the element that shows it invalid. ``lookup(id)`` gives the checks another field of the form. */
    function makeRecord(field, wrap, lookup) {
      return { id: field.id, title: field.title, kind: field.kind, required: field.required, validators: field.validators,
               input: control(field), wrap: wrap, error: errorLine(), lookup: lookup };
    }

    /** The other field of the form called ``id``, as the checks look at it. */
    function lookupField(id) {
      const other = fields.find(function (f) { return f.id === id; });
      return other ? { title: other.title, value: valueOf(other) } : null;
    }

    /** Make the control of ``field`` and keep it in ``fields``; what is wrong is told again as it is put right. Answers the record. */
    function addField(field, wrap) {
      const record = makeRecord(field, wrap, lookupField);
      fields.push(record);
      watchFocus(record);
      ['input', 'change'].forEach(function (name) {
        wrap.addEventListener(name, function () { if (wrap.classList.contains('invalid')) showState(record); });
      });
      return record;
    }

    return {
      fields: fields,
      reset: function () { fields.length = 0; },   // the form is about to be painted again or closed
      control: control,
      makeRecord: makeRecord,
      addField: addField,
      watchFocus: watchFocus,
      lookupField: lookupField,
      showState: showState,
      readiness: function () { return readFormReadiness(fields); },
      collect: function () { return collectValues(fields); },
      showRefusals: function (messages) { return showFieldRefusals(fields, messages); },
      valueOf: valueOf,
      setFieldValue: function (record, raw, wanted) { setFieldValue(record, raw, wanted, io); },
      aimable: aimable,
      fieldLine: fieldLine,
      fillLine: fillLine,
      infoIcon: infoIcon,
      autoBox: autoBox,
    };
  }

  ns.formControls = { make: make };
})(window.MfgUi);
