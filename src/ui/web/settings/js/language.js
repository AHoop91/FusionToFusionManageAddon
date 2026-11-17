/**
 * The language card: choose the language of the add-in's panels, see the languages made here, and make a language file
 * to translate when the add-in has none for it.
 *
 * The language chosen in the list is used at once, with nothing to save; Save & Publish (Hub Admins) puts the user's own languages in the
 * Configuration File in the hub. Making a language file is its own button. The card is shown in the Language tab and, signed out, on the
 * sign-in screen (only to choose), so a language can be chosen before there is a sign-in.
 */
(function (ns) {
  'use strict';

  const el = ns.el;
  const t = ns.i18n.t;
  const SLOTS = ['lang-slot-tab', 'lang-slot-login'];   // each holds one card, built here

  let draft = { code: '', name: '' };   // what was typed in the form that makes a language file, kept while the card is built again
  let sent = null;                      // what Create sent, put back in the form if the file could not be made
  let note = null;                     // {kind: 'ok' | 'error', title, text, path} shown under that form
  let pickedCode = null;                // the language chosen in the list, until the panels load again in it (null: none chosen)
  let report = null;                    // what Python found checking a language file against English's, shown under the list
  let pageError = '';                   // why the language chosen cannot be used, or checked, shown at the top of the card
  let away = false;                     // the window lost focus to the editor after Edit: coming back reads the file again
  let editing = '';                     // the code of the language opened in the text editor

  /** What the user's role in the hub is: anyone makes languages of their own, only a Hub Admin publishes them to the hub. */
  function role() { return ns.settings ? ns.settings.roleState() : ''; }

  /** The language with this code among those Python listed, or undefined. */
  function findLanguage(state, code) {
    return state.languages.find(function (language) { return language.code === code; });
  }

  /** A button of the page's own look; ``kind`` is 'btn' or 'btn btn-secondary'. */
  function button(label, kind, onClick) {
    const node = el('button', kind, label);
    node.type = 'button';
    node.addEventListener('click', onClick);
    return node;
  }

  /** A text field with its label, as the rest of the page lays them out; a required one is marked as such. */
  function field(label, input, id) {
    const wrap = el('div', 'field');
    const caption = el('label', 'lang-required', label);
    input.required = true;
    input.setAttribute('aria-required', 'true');
    input.id = id;
    caption.htmlFor = id;
    wrap.appendChild(caption);
    wrap.appendChild(input);
    return wrap;
  }

  function textInput(value, placeholder, onInput) {
    const input = el('input');
    input.type = 'text';
    input.value = value;
    input.placeholder = placeholder;
    input.autocomplete = 'off';
    input.spellcheck = false;
    input.addEventListener('input', function () { onInput(input.value); });
    return input;
  }

  /** Each word of a language name starts with a capital letter (the rest is as typed): German Test. */
  function nameInput(value, placeholder, onInput) {
    const input = textInput(value, placeholder, onInput);
    input.addEventListener('input', function () {
      const named = input.value.replace(/(^|\s)(\S)/g, function (all, space, letter) { return space + letter.toUpperCase(); });
      if (named !== input.value) {
        const at = input.selectionStart;
        input.value = named;
        input.setSelectionRange(at, at);
      }
      onInput(named);
    });
    return input;
  }

  /** A language code is always in capitals: what is typed is made so as it is typed. */
  function codeInput(value, placeholder, onInput) {
    const input = textInput(value.toUpperCase(), placeholder, onInput);
    input.addEventListener('input', function () {
      const upper = input.value.toUpperCase();
      if (upper !== input.value) {
        const at = input.selectionStart;
        input.value = upper;
        input.setSelectionRange(at, at);
      }
      onInput(upper);
    });
    return input;
  }

  /** The language list, in the same searchable picker the workspaces use. Choosing waits for Save. */
  function buildPicker(state) {
    const shown = pickedCode || state.code;
    const cfg = {
      valueClass: 'lang-value',
      required: true,   // a language is always chosen: there is nothing to clear
      className: 'inline-detail',   // the code is on the row of the name
      searchFrom: 8,   // a handful of languages needs no search
      placeholder: shown,
      search: t('language.search'),
      label: function (code) {
        const found = findLanguage(state, code);
        return found ? found.name : code;
      },
      groups: function () {
        function items(source) {
          return state.languages.filter(function (language) { return language.source === source; }).map(function (language) {
            return { value: language.code, label: language.name, detail: language.code.toUpperCase() };
          });
        }
        const groups = [
          { title: t('language.group_shipped'), items: items('shipped') },
          { title: t('language.group_hub'), items: items('hub') },
          { title: t('language.group_user'), items: items('user') },
        ].filter(function (group) { return group.items.length; });
        if (groups.length === 1) groups[0].title = '';   // one kind of language needs no heading
        return groups;
      },
      empty: function () { return t('language.empty'); },
    };
    const wrap = ns.picker.make(cfg, shown);
    wrap.addEventListener('pick', function () {
      pickedCode = wrap.querySelector('.lang-value').value;
      if (pickedCode === ns.i18n.state().code) pickedCode = null;
      else ns.i18n.set(pickedCode);   // used at once: the panels load again in it
      render();   // the check offered below depends on the language chosen
    });
    return wrap;
  }

  /** The names of a report, as a line: the first ones, and how many more there are. */
  function names(listed, count) {
    return listed.join(', ') + (count > listed.length ? ' ' + t('language.check_more', { n: count - listed.length }) : '');
  }

  /** What checking a language file against English's found: how much is translated, and what needs a look. */
  function buildReport(found) {
    const trouble = found.errors.length > 0;
    const attention = trouble || found.warnings.length > 0 || found.missing_count || found.placeholder_count || found.not_text_count;
    const box = el('div', 'lang-note ' + (trouble ? 'error' : attention ? 'warn' : 'ok'));
    box.setAttribute('role', 'status');
    box.appendChild(el('strong', null, attention ? t('language.check_attention', { name: found.name }) : t('language.check_good', { name: found.name })));
    box.appendChild(el('p', null, t('language.check_summary', { translated: found.translated, total: found.total, same: found.same_as_english })));
    found.errors.concat(found.warnings).forEach(function (text) { box.appendChild(el('p', null, text)); });
    if (found.missing_count) {
      box.appendChild(el('p', null, t('language.check_missing', { n: found.missing_count })));
      box.appendChild(el('code', 'lang-path', names(found.missing, found.missing_count)));
    }
    if (found.placeholder_count) {
      box.appendChild(el('p', null, t('language.check_placeholders', { n: found.placeholder_count })));
      found.placeholders.forEach(function (item) {
        function braces(list) { return list.length ? list.map(function (name) { return '{' + name + '}'; }).join(' ') : t('language.check_none'); }
        box.appendChild(el('code', 'lang-path', t('language.check_placeholder_item', { key: item.key, expected: braces(item.expected), found: braces(item.found) })));
      });
    }
    if (found.not_text_count) {
      box.appendChild(el('p', null, t('language.check_not_text', { n: found.not_text_count })));
      box.appendChild(el('code', 'lang-path', names(found.not_text, found.not_text_count)));
    }
    if (found.unknown_count) {
      box.appendChild(el('p', null, t('language.check_unknown', { n: found.unknown_count })));
      box.appendChild(el('code', 'lang-path', names(found.unknown, found.unknown_count)));
    }
    return box;
  }

  /** Under the list, for a language that is not one the add-in ships: a check of its file against English's, and what it found. */
  function buildCheck(state) {
    const code = pickedCode || state.code;
    const chosen = findLanguage(state, code);
    const wrap = el('div', 'lang-check');
    if (!chosen || chosen.source === 'shipped') return wrap;
    wrap.appendChild(button(t('language.check'), 'btn btn-secondary', function () { pageError = ''; ns.bridge.send('check_language', { code: code }); }));
    if (report && report.code === code) wrap.appendChild(buildReport(report));
    return wrap;
  }

  /** Files in the user's and the hub's folders that cannot be used, and why: the list leaves them out, so they are named here. */
  function buildInvalid(state) {
    if (!state.invalid || !state.invalid.length) return null;
    const box = el('div', 'lang-note error');
    box.setAttribute('role', 'alert');
    box.appendChild(el('strong', null, t('language.invalid_title')));
    state.invalid.forEach(function (item) { box.appendChild(el('p', null, t('language.invalid_file', { file: item.file, reason: item.reason }))); });
    return box;
  }

  /** Open the folder the language files are in, and read the files again. */
  function actions() {
    const row = el('div', 'row lang-actions');
    row.appendChild(button(t('language.open_folder'), 'btn btn-secondary', function () { ns.bridge.send('open_language_folder'); }));
    row.appendChild(button(t('language.reload'), 'btn btn-secondary', function () { ns.i18n.set(ns.i18n.state().code); }));
    return row;
  }

  /** The note that says what to do when the language is not in the list, and how a language file works. */
  function buildHow() {
    const how = el('div', 'lang-how');
    how.appendChild(el('p', null, t('language.add_intro')));
    how.appendChild(el('strong', null, t('language.how_title')));
    const steps = el('ol');
    steps.appendChild(el('li', null, t('language.how_create')));
    steps.appendChild(el('li', null, t('language.how_translate')));
    steps.appendChild(el('li', null, t('language.how_reload')));
    how.appendChild(steps);
    how.appendChild(el('p', 'hint', t('language.how_scope')));
    return how;
  }

  const PENCIL = ['M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z'];
  const FOLDER = ['M10 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8l-2-2z'];
  const TRASH =['M6 19a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z'];

  /** An icon button for a language's tile: ``label`` is its tooltip and what a screen reader says. */
  function iconButton(paths, label, className, onClick) {
    const button = el('button', 'lang-icon ' + className);
    button.type = 'button';
    button.title = label;
    button.setAttribute('aria-label', label);
    button.appendChild(ns.svg(paths, 16));
    button.addEventListener('click', onClick);
    return button;
  }

  /** Delete a language file, after asking: it cannot be undone, and it is the same file the hub is given when the Hub Admin publishes. */
  function askDelete(language) {
    ns.progress.confirm(t('language.delete_title', { name: language.name }), t('language.delete_text', { name: language.name, file: language.code + '.json' }),
      t('language.delete'), function () {
        pageError = '';
        ns.bridge.send('delete_language', { code: language.code });
      });
  }

  /** The section's heading, with the button at its right that opens the folder the user's language files are in (the path is its tooltip). */
  function buildShareHead(state) {
    const head = el('div', 'lang-share-head');
    head.appendChild(el('h3', null, t('language.share_title')));
    const open = button('', 'btn btn-secondary lang-folder-btn', function () { ns.bridge.send('open_language_folder'); });
    open.appendChild(ns.svg(FOLDER, 16));
    open.appendChild(document.createTextNode(t('language.open_folder')));
    if (state.user_dir) open.title = state.user_dir;
    head.appendChild(open);
    return head;
  }

  /** The languages the user made, one full-width tile each: where it is (Local, or Shared once the hub has it), and Edit and
   *  Delete. All of them go in the Configuration File with Save & Publish, so there is nothing to choose. */
  function buildShare(state) {
    const own = state.languages.filter(function (language) { return language.source === 'user'; });
    const section = el('div', 'lang-add lang-share');
    section.appendChild(buildShareHead(state));
    section.appendChild(el('p', 'hint', (role() === 'admin' ? t('language.share_hint') : t('language.share_hint_member'))));
    if (!own.length) {
      section.appendChild(el('div', 'lang-share-empty', t('language.share_empty')));
      return section;
    }
    const grid = el('div', 'lang-tiles');
    own.forEach(function (language) {
      const sharing = language.sharing || {};
      const included = !!sharing.included;
      const tile = el('div', 'lang-tile' + (included ? '' : ' excluded'));
      tile.appendChild(el('span', 'lang-tile-code', language.code));
      const text = el('div', 'lang-tile-text');
      text.appendChild(el('strong', null, language.name));
      const where = el('div', 'lang-tile-where');   // where the language is: Local (only on this computer), or Shared (the hub has it)
      if (sharing.hub === 'same') {
        where.appendChild(el('span', 'lang-chip hub', t('language.badge_hub')));
      } else if (sharing.hub === 'different') {
        where.appendChild(el('span', 'lang-chip hub changed', t('language.badge_hub_changed')));   // the hub has an older version: publish again to update it
      } else {
        where.appendChild(el('span', 'lang-chip local', t('language.badge_local')));
      }
      text.appendChild(where);
      if (!included && sharing.reason) text.appendChild(el('span', 'lang-tile-reason', sharing.reason));
      tile.appendChild(text);
      const tools = el('div', 'lang-tile-tools');   // the actions on a language of the user's own
      tools.appendChild(iconButton(PENCIL, t('language.edit_label', { name: language.name }), 'lang-edit', function () {
        pageError = '';
        editing = language.code;
        away = false;
        ns.bridge.send('edit_language', { code: language.code });
      }));
      tools.appendChild(iconButton(TRASH, t('language.delete_label', { name: language.name }), 'lang-delete', function () { askDelete(language); }));
      tile.appendChild(tools);
      grid.appendChild(tile);
    });
    section.appendChild(grid);
    return section;
  }

  function buildAdd() {
    const section = el('div', 'lang-add');
    section.appendChild(el('h3', null, t('language.add_title')));
    section.appendChild(buildHow());

    const row = el('div', 'lang-add-row');
    const create = button(t('language.create'), 'btn', function () {
      if (!complete()) return;
      note = null;
      sent = draft;
      draft = { code: '', name: '' };   // cleared at once: a second press cannot make the file twice
      code.value = '';
      name.value = '';
      create.disabled = true;
      ns.bridge.send('new_language', { code: sent.code, name: sent.name });
    });
    /** Both are needed before a file can be made. */
    function complete() { return draft.code.trim() !== '' && draft.name.trim() !== ''; }
    const code = codeInput(draft.code, 'DE', function (value) { draft.code = value; create.disabled = !complete(); });
    const name = nameInput(draft.name, 'Deutsch', function (value) { draft.name = value; create.disabled = !complete(); });
    create.disabled = !complete();
    row.appendChild(field(t('language.code'), code, 'lang-code'));
    row.appendChild(field(t('language.name'), name, 'lang-name'));
    row.appendChild(create);
    section.appendChild(row);

    if (note) {
      const box = el('div', 'lang-note ' + note.kind);
      box.setAttribute('role', note.kind === 'error' ? 'alert' : 'status');
      box.appendChild(el('strong', null, note.title));
      box.appendChild(el('p', null, note.text));
      if (note.path) box.appendChild(el('code', 'lang-path', note.path));
      if (note.kind === 'ok') box.appendChild(actions());
      section.appendChild(box);
    }
    return section;
  }

  /** The card, built from what Python said about the languages (`ns.i18n.state()`). ``own`` is where it carries its own Save. */
  function buildCard(own) {
    const state = ns.i18n.state();
    const card = el('div', 'card conn-card lang-card');
    card.appendChild(el('h2', null, t('language.title')));
    card.appendChild(el('p', 'hint', t('language.intro')));
    const pick = el('div', 'field');
    pick.appendChild(el('label', null, t('language.label')));
    pick.appendChild(buildPicker(state));
    card.appendChild(pick);
    if (!own) card.appendChild(buildCheck(state));
    if (pageError) {
      const box = el('div', 'lang-note error');
      box.setAttribute('role', 'alert');
      box.appendChild(el('p', null, pageError));
      card.appendChild(box);
    }
    if (!own) {   // sharing and adding a language are the tab's: the sign-in screen's card only chooses (and its fields would repeat the tab's ids)
      const invalid = buildInvalid(state);
      if (invalid) card.appendChild(invalid);
      card.appendChild(buildShare(state));
      card.appendChild(buildAdd());
    }
    return card;
  }

  /** Build the card again in each slot (the list of languages, the role, or the note under the form, changed). */
  function render() {
    SLOTS.forEach(function (id) {
      const slot = ns.$(id);
      if (!slot) return;
      slot.textContent = '';
      slot.appendChild(buildCard(id === 'lang-slot-login'));
    });
    ns.$('lang-banner').hidden = !ns.i18n.state().restart;   // the ribbon follows the language only after Fusion is restarted
    const publish = ns.$('lang-save-publish-btn');
    if (publish) publish.hidden = role() !== 'admin';   // only a Hub Admin publishes
  }

  // ---- Save --------------------------------------------------------------------

  /** Save & Publish (a Hub Admin's) puts the languages in the Configuration File in the hub; Save has nothing more to keep, so it says so. */
  function saveChoices(publish) {
    if (publish && role() === 'admin') ns.settings.publish();
    else ns.progress.notify(t('settings.saved_title'), t('language.saved_text'));
  }

  /** The save to the hub is over (it went through, failed, or was cancelled): the list is read again, so the languages the hub now has show
   *  as Shared in hub. */
  function settled() { ns.bridge.send('get_language', {}); }

  /** Take the languages Python found: a language chosen or checked that is no longer among them (its file went) is let go. */
  function useLanguages(result) {
    ns.i18n.use(result);
    if (pickedCode && !findLanguage(result, pickedCode)) pickedCode = null;
    if (report && !findLanguage(result, report.code)) report = null;
  }

  function init() {
    ns.bridge.on('get_language', function (r) { if (r.ok) { useLanguages(r.result); render(); } });
    ns.bridge.on('new_language', function (r) {
      if (!r.ok) {
        draft = sent || draft;   // the file was not made: what was typed comes back to be fixed
        note = { kind: 'error', title: t('language.failed'), text: r.error };
      } else {
        ns.i18n.use(r.result);
        note = { kind: 'ok', title: t('language.created_title'), text: t('language.created_next'), path: r.result.created };
      }
      render();
    });
    ns.bridge.on('edit_language', function (r) {
      if (r.ok) return;   // the editor is open: nothing on the page changes
      editing = '';
      pageError = r.error;
      render();
    });
    ns.bridge.on('delete_language', function (r) {
      if (!r.ok) { pageError = r.error; render(); return; }
      const before = ns.i18n.state().code;
      useLanguages(r.result);
      render();
      if (r.result.code !== before) ns.i18n.set(r.result.code);   // the language in use was the one deleted: the panels load again in English
    });
    ns.bridge.on('check_language', function (r) {
      if (r.ok) { report = r.result; pageError = ''; } else { report = null; pageError = r.error; }
      render();
    });
    ns.i18n.onRefused(function (message) { pickedCode = null; pageError = message; render(); });   // the language chosen cannot be used
    ns.bridge.on('open_language_folder', function (r) {
      if (!r.ok) { note = { kind: 'error', title: t('language.failed'), text: r.error }; render(); }
    });
    window.addEventListener('blur', function () { if (editing) away = true; });
    window.addEventListener('focus', function () {   // back from the editor: whatever was saved there is read again
      if (!editing || !away) return;
      const code = editing;
      editing = '';
      away = false;
      if (code === ns.i18n.state().code) ns.i18n.set(code);   // the language in use was edited: the panels load again with it
      else ns.bridge.send('get_language', {});   // another one: only the list is read again (a check of the file, the files that cannot be used)
    });
    const tab = document.querySelector('.tab[data-tab="language"]');
    if (tab) tab.addEventListener('click', function () { ns.bridge.send('get_language', {}); });   // the folders are read again: files added or changed by hand show
    ns.$('lang-restart-btn').addEventListener('click', function () { ns.bridge.send('restart_addin', {}); });   // the ribbon and the panel titles are made again
    ns.$('lang-save-btn').addEventListener('click', function () { saveChoices(false); });
    ns.$('lang-save-publish-btn').addEventListener('click', function () { saveChoices(true); });
    render();
  }

  ns.language = { init: init, render: render, settled: settled };
})(window.MfgUi);
