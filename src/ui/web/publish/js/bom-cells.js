/**
 * Publish Item panel: the cells of a Bill of Materials row, as ``ns.bomCells``.
 *
 * Each function builds one piece of a row from a line of bom-model.js: the item cell (indent, chevron, icon, label, buttons and
 * status chip), the Fusion and Fusion Manage ticks, the quantity, and the buttons that act on a line. bom-table.js lays them out.
 */
(function (ns) {
  'use strict';

  const ui = ns.pubUi;
  const el = ui.el;
  const model = ns.bomModel;
  const decisions = model.decisions;
  function t(key, params) { return ns.i18n.t(key, params); }

  const SLOT = 32;   // width of a chevron or icon box; every level steps in by this much

  // Status chip per row status: tone (colour), label and the tooltip. A differing pair gets its chips in ``pairChip``.
  function statuses() {
    return {
      match:   { label: t('publish.status_match'),    text: t('publish.status_match_text') },
      new:     { tone: 'new',     label: t('publish.status_new'),     text: t('publish.status_new_text') },
      changed: { tone: 'changed', label: t('publish.status_update'),  text: t('publish.status_update_text') },
      added:   { tone: 'new',     label: t('publish.status_new'),     text: t('publish.status_added_text') },
      kept:    { tone: 'extra',   label: t('publish.status_keep'),    text: t('publish.status_keep_text') },
      linked:  { tone: 'added',   label: t('publish.status_added'),   text: t('publish.status_linked_text') },
      skipped: { tone: 'skipped', label: t('publish.status_skipped'), text: t('publish.status_skipped_text') },
    };
  }

  const ICON_HIDDEN = ['M2 12s3.5-6.5 10-6.5S22 12 22 12s-3.5 6.5-10 6.5S2 12 2 12z', 'M12 9.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z', 'M4 4l16 16'];
  const ICON_TICK = ['M5 12l5 5L20 7'];
  const ICON_MINUS = ['M5 12h14'];
  const ICON_UNDO = ['M9 14L4 9l5-5', 'M4 9h10.5a5.5 5.5 0 0 1 0 11H11'];
  const ICON_INFO = ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', 'M12 11v6', 'M12 7.5v.5'];

  /** A line drawn from its Fusion Manage side: one only Fusion Manage has, or one picked with Add Items. */
  function fromFm(item) {
    return item.status === 'extra' || item.status === 'kept' || item.status === 'linked';
  }

  // ---- Item cell -----------------------------------------------------------------

  /** Eye with a slash: the component is hidden in the Fusion component tree. */
  function hiddenIcon() {
    const box = el('span', 'pub-cmp-hidden');
    box.title = t('publish.hidden_in_tree');
    box.setAttribute('aria-label', box.title);
    box.appendChild(ui.svg(ICON_HIDDEN));
    return box;
  }

  /** Item cell: indent (``item.iconX`` is where the icon starts), chevron (when ``toggle`` is given), icon, sequence, item number and name, then ``actions`` and the status ``chip``. */
  function itemCell(side, item, isAssembly, toggle, actions, chip) {
    const td = el('td', 'pub-cmp-item');
    const box = el('div', 'pub-tree-cell');
    box.style.setProperty('--indent', (item.iconX - (toggle ? SLOT : 0)) + 'px');
    if (toggle) box.appendChild(toggle);
    box.appendChild(ui.treeIcon(item.root ? 'root' : isAssembly ? 'assembly' : 'part'));
    if (item.sequence) box.appendChild(el('span', 'pub-tree-seq' + (isAssembly ? ' pub-tree-asm' : ''), side.sequence));
    const label = el('span', 'pub-tree-label');
    label.title = [side.pn, side.name].filter(Boolean).join(' - ');
    if (side.pn) label.appendChild(el('span', 'pub-tree-pn', side.pn));
    if (side.name) label.appendChild(el('span', 'pub-tree-name', side.name));
    box.appendChild(label);
    if (item.hidden) box.appendChild(hiddenIcon());
    if (actions || chip) {   // at the end of the item: the buttons (shown while the row is hovered), then the status chip
      const end = el('span', 'pub-cmp-end');
      if (actions) end.appendChild(actions);
      if (chip) end.appendChild(chip);
      box.appendChild(end);
    }
    td.appendChild(box);
    return td;
  }

  /** Tick when the line exists on that side ('design' or 'fm'), a quiet dash when it does not. */
  function presenceCell(present, side) {
    const td = el('td', 'pub-cmp-presence');
    const mark = el('span', present ? 'pub-cmp-tick' : 'pub-cmp-none');
    if (present) mark.appendChild(ui.svg(ICON_TICK));
    else mark.textContent = '–';
    mark.title = side === 'design' ? (present ? t('publish.in_design') : t('publish.not_in_design')) : (present ? t('publish.in_fm') : t('publish.not_in_fm'));
    mark.setAttribute('aria-label', mark.title);
    td.appendChild(mark);
    return td;
  }

  // ---- Status chip ---------------------------------------------------------------

  /** The chip of a Fusion Manage line the user chose to remove. */
  function removedChip(item) {
    return { tone: 'removed', label: t('publish.status_remove'), text: t('publish.chip_remove_text', { number: item.fm.pn }) };
  }

  /** Chip for a differing pair: the design line (``fmRow`` false) is added; the Fusion Manage line shows the user's choice. */
  function pairChip(item, fmRow) {
    const choice = decisions[item.key];
    if (!fmRow) {
      const names = { design: item.design.pn, fm: item.fm.pn };
      const text = choice === 'remove' ? t('publish.chip_pair_replace', names)
        : choice === 'add' ? t('publish.chip_pair_keep_both', names)
        : t('publish.chip_pair_choose', names);
      return { tone: 'new', label: t('publish.status_new'), text: text };
    }
    if (!choice) return { tone: 'pair', label: t('publish.status_review'), text: t('publish.chip_pair_ask') };
    if (choice === 'remove') return removedChip(item);
    return { tone: 'extra', label: t('publish.status_keep'), text: t('publish.chip_keep_text', { number: item.fm.pn }) };
  }

  /** Tooltip of the Skipped chip and of the greyed quantity box: the line's own name, and why it is left out. */
  function skippedText(item) {
    const who = item.componentName || item.design.pn || t('publish.skipped_this_line');
    if (item.skip === 'shared') return t('publish.skipped_shared', { who: who, number: item.design.pn, others: item.sharedWith.join(', ') });
    return item.skip === 'parent' ? t('publish.skipped_parent', { who: who }) : t('publish.skipped_none', { who: who });
  }

  /** The Update chip: its tooltip says what the quantity is in Fusion Manage now and what publishing makes it. */
  function changedChip(item) {
    return Object.assign({}, statuses().changed, { text: t('publish.chip_changed_text', { current: item.fm.quantity, after: model.quantityOf(item) }) });
  }

  /** The chip a line shows, or null when there is nothing to say. */
  function chipOf(item, fmRow) {
    const status = model.statusOf(item);
    if (status === 'match') return null;   // nothing to do
    if (status === 'mismatch') return pairChip(item, fmRow);
    if (status === 'changed') return changedChip(item);
    if (status !== 'extra') return statuses()[status];
    if (decisions[item.key] === 'remove') return removedChip(item);
    return model.quantityDiffers(item) ? changedChip(item) : null;   // the ticks already say it is only in Fusion Manage
  }

  /** Status chip, or null when there is nothing to say. A differing pair has two rows: the design line (``fmRow`` false) and the Fusion Manage line. */
  function statusChip(item, fmRow) {
    const chip = chipOf(item, fmRow);
    if (!chip) return null;
    const node = el('span', 'pub-cmp-chip pub-cmp-chip-' + chip.tone, chip.label);
    const skipped = item.status === 'skipped';
    node.title = skipped ? skippedText(item) : chip.text;
    if (skipped) {   // the small "i" says there is something to read on hover
      node.classList.add('pub-cmp-chip-info');
      node.appendChild(ui.svg(ICON_INFO));
    }
    return node;
  }

  // ---- Buttons -------------------------------------------------------------------

  /** A round icon button of a row: its class is ``pub-cmp-act-<kind>``, plus ``chosen`` for a choice that is on. */
  function actionButton(kind, title, icon, onClick, chosen) {
    const b = el('button', 'pub-cmp-act pub-cmp-act-' + kind + (chosen ? ' chosen' : ''));
    b.type = 'button';
    b.title = title;
    b.setAttribute('aria-label', title);
    b.appendChild(ui.svg(icon));
    b.addEventListener('click', onClick);
    return b;
  }

  function actionBox(buttons) {
    const box = el('span', 'pub-cmp-actions');
    buttons.forEach(function (b) { box.appendChild(b); });
    return box;
  }

  /** Turn a choice on, or off when it is the one already made. */
  function toggleChoice(item, choice) {
    if (decisions[item.key] === choice) delete decisions[item.key]; else decisions[item.key] = choice;
  }

  /** Remove button of a line picked with Add Items. */
  function unstageActions(item, redraw) {
    return actionBox([actionButton('remove', t('publish.unstage_title', { number: item.fm.pn }), ICON_MINUS, function () {
      model.unstage(item.stagedId);
      redraw();
    })]);
  }

  /** Remove button of a line only Fusion Manage has: it is kept unless this is on (click again to keep it). */
  function removeAction(item, redraw) {
    const removing = decisions[item.key] === 'remove';
    return actionBox([actionButton('remove', removing ? t('publish.keep_in_fm', { number: item.fm.pn }) : t('publish.remove_from_fm', { number: item.fm.pn }), ICON_MINUS, function () {
      toggleChoice(item, 'remove');
      redraw();
    }, removing)]);
  }

  /** Icon buttons on the Fusion Manage line of a differing pair: keep both lines, or remove this one. A kept line has them too, to undo the choice. */
  function pairActions(item, redraw) {
    if (!item.key || item.status === 'added') return null;
    const names = { design: item.design.pn, fm: item.fm.pn };
    const choices = [['add', t('publish.pair_keep_both', names), ICON_TICK],
                     ['remove', t('publish.pair_remove', names), ICON_MINUS]];
    return actionBox(choices.map(function (c) {
      return actionButton(c[0], c[1], c[2], function () { toggleChoice(item, c[0]); redraw(); }, decisions[item.key] === c[0]);
    }));
  }

  /** Add a revert button, beside the line's other buttons, while the user's quantity is over the line's own. */
  function withRevert(box, item, redraw) {
    if (!model.canEditQuantity(item) || !model.quantityEdited(item)) return box;
    const revert = actionButton('revert', t('publish.revert_quantity', { quantity: model.baseQuantity(item) }), ICON_UNDO, function () {
      model.revertQuantity(item);
      redraw();
    });
    const out = box || actionBox([]);
    out.appendChild(revert);
    return out;
  }

  /** The buttons at the end of a line's item cell, or null. ``redraw`` draws the table again after a click. */
  function rowActions(item, redraw) {
    const box = item.status === 'kept' ? pairActions(item, redraw)
      : item.status === 'linked' ? unstageActions(item, redraw)
      : item.status === 'extra' ? removeAction(item, redraw)
      : null;
    return withRevert(box, item, redraw);
  }

  // ---- Quantity ------------------------------------------------------------------

  function quantityBox(value, title, label, disabled) {
    const input = el('input', 'pub-cmp-qty-input');
    input.type = 'text';
    input.value = value;
    input.title = title;
    input.setAttribute('aria-label', label);
    input.disabled = !!disabled;
    return input;
  }

  /** A box that only takes digits and one decimal point, whether typed or pasted. */
  function numbersOnly(input) {
    input.inputMode = 'decimal';
    input.addEventListener('input', function () {
      const clean = input.value.replace(/[^0-9.]/g, '').replace(/^([^.]*\.)(.*)$/, function (_, head, tail) { return head + tail.replace(/\./g, ''); });
      if (clean !== input.value) input.value = clean;
    });
  }

  /** The same box as an editable line, greyed out: nothing is published for a skipped line, so there is nothing to set. */
  function skippedQuantity(item) {
    const td = el('td', 'num pub-cmp-qty');
    td.appendChild(quantityBox(item.design.quantity, skippedText(item), t('publish.quantity_skipped', { name: item.componentName || item.design.pn }), true));
    return td;
  }

  function editableQuantity(item, redraw) {
    const staged = item.status === 'linked';
    const td = el('td', 'num pub-cmp-qty');
    const input = quantityBox(staged ? item.fm.quantity : model.quantityOf(item), t('publish.quantity_title'),
                              t('publish.quantity_of', { name: staged || fromFm(item) ? item.fm.pn : item.design.pn }));
    numbersOnly(input);
    input.addEventListener('change', function () {
      const typed = input.value;
      input.value = staged ? model.setStagedQuantity(item.stagedId, typed) : model.setQuantity(item, typed);
      if (Number(typed) !== Number(input.value)) ns.toast.show(t('publish.quantity_invalid'), { tone: 'error' });
      if (!staged) redraw();   // the status and filters follow the new quantity
    });
    td.appendChild(input);
    if (model.quantityDiffers(item)) td.classList.add('pub-cmp-qty-diff');   // will update Fusion Manage
    return td;
  }

  /** Quantity: the design's, or the Fusion Manage line's for a line only it has. A line that can be edited, or was picked with Add Items, has a box for it. */
  function quantityCell(item, redraw) {
    if (item.status === 'skipped') return skippedQuantity(item);
    if (item.status === 'linked' || model.canEditQuantity(item)) return editableQuantity(item, redraw);
    return el('td', 'num pub-cmp-qty', fromFm(item) ? item.fm.quantity : item.design.quantity);
  }

  ns.bomCells = {
    SLOT: SLOT, fromFm: fromFm, itemCell: itemCell, presenceCell: presenceCell, statusChip: statusChip, skippedText: skippedText,
    rowActions: rowActions, pairActions: pairActions, quantityCell: quantityCell,
  };
})(window.MfgUi);
