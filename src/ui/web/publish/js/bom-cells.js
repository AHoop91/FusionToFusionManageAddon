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

  const SLOT = 32;   // width of a chevron or icon box; every level steps in by this much

  // Status chip per row status: tone (colour), label and the tooltip. A differing pair gets its chips in ``pairChip``.
  const STATUS = {
    match:   { label: 'Match',    text: 'Same line and quantity in Fusion Manage' },
    new:     { tone: 'new',     label: 'New',     text: 'Not in Fusion Manage yet: publishing adds it' },
    changed: { tone: 'changed', label: 'Updates', text: 'Quantity differs from Fusion Manage' },
    added:   { tone: 'new',     label: 'New',     text: 'Publishing adds this line to the Fusion Manage BOM' },
    kept:    { tone: 'extra',   label: 'Keep',    text: 'Publishing keeps this Fusion Manage line, renumbered at the end of the BOM' },
    linked:  { tone: 'added',   label: 'Added',   text: 'Picked with Add Existing Items: publishing adds this Fusion Manage item to the end of the Fusion Manage BOM' },
    skipped: { tone: 'skipped', label: 'Skipped', text: 'No item number: not in the Fusion Manage Components workspace, so publishing creates no item for it' },
  };
  const PAIR_ASK = 'Item number differs from the Fusion Manage line at this position: choose an action';

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
    box.title = 'Hidden in the Fusion component tree';
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

  /** Tick when the line exists on that side, a quiet dash when it does not. */
  function presenceCell(present, what) {
    const td = el('td', 'pub-cmp-presence');
    const mark = el('span', present ? 'pub-cmp-tick' : 'pub-cmp-none');
    if (present) mark.appendChild(ui.svg(ICON_TICK));
    else mark.textContent = '–';
    mark.title = (present ? 'In ' : 'Not in ') + what;
    mark.setAttribute('aria-label', mark.title);
    td.appendChild(mark);
    return td;
  }

  // ---- Status chip ---------------------------------------------------------------

  /** Chip for a differing pair: the design line (``fmRow`` false) is added; the Fusion Manage line shows the user's choice. */
  function pairChip(item, fmRow) {
    const choice = decisions[item.key];
    if (!fmRow) {
      const text = choice === 'remove' ? 'Publishing will add ' + item.design.pn + ' in place of ' + item.fm.pn
        : choice === 'add' ? 'Publishing will add ' + item.design.pn + ' and keep ' + item.fm.pn
        : 'Publishing will add ' + item.design.pn + '; choose what happens to ' + item.fm.pn;
      return { tone: 'new', label: 'New', text: text };
    }
    if (!choice) return { tone: 'pair', label: 'Review', text: PAIR_ASK };
    if (choice === 'remove') return { tone: 'removed', label: 'Remove', text: 'Publishing will remove ' + item.fm.pn + ' from Fusion Manage' };
    return { tone: 'extra', label: 'Keep', text: 'Publishing keeps ' + item.fm.pn + ' in Fusion Manage' };
  }

  /** Tooltip of the Skipped chip and of the greyed quantity box: the line's own name, and why it is left out. */
  function skippedText(item) {
    const who = item.componentName || item.design.pn || 'This line';
    return item.skip === 'parent' ? who + ' Is Skipped: A Line Above It Has No Assigned Item Number In Fusion Manage'
      : who + ' Has No Assigned Item Number In Fusion Manage';
  }

  /** The chip a line shows, or null when there is nothing to say. */
  function chipOf(item, fmRow) {
    const status = model.statusOf(item);
    if (status === 'match') return null;   // nothing to do
    if (status === 'mismatch') return pairChip(item, fmRow);
    if (status !== 'extra') return STATUS[status];
    if (decisions[item.key] === 'remove') return { tone: 'removed', label: 'Remove', text: 'Publishing will remove ' + item.fm.pn + ' from Fusion Manage' };
    return model.quantityDiffers(item) ? STATUS.changed : null;   // the ticks already say it is only in Fusion Manage
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

  /** A round icon button of a row. ``extra`` is added to the class (``chosen`` for a choice that is on). */
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
    return actionBox([actionButton('remove', 'Do not add ' + item.fm.pn + ' to the Fusion Manage BOM', ICON_MINUS, function () {
      model.unstage(item.stagedId);
      redraw();
    })]);
  }

  /** Remove button of a line only Fusion Manage has: it is kept unless this is on (click again to keep it). */
  function removeAction(item, redraw) {
    const removing = decisions[item.key] === 'remove';
    return actionBox([actionButton('remove', removing ? 'Keep ' + item.fm.pn + ' in Fusion Manage' : 'Remove ' + item.fm.pn + ' from Fusion Manage', ICON_MINUS, function () {
      toggleChoice(item, 'remove');
      redraw();
    }, removing)]);
  }

  /** Icon buttons on the Fusion Manage line of a differing pair: keep both lines, or remove this one. A kept line has them too, to undo the choice. */
  function pairActions(item, redraw) {
    if (!item.key || item.status === 'added') return null;
    const choices = [['add', 'Keep both: add ' + item.design.pn + ' and keep ' + item.fm.pn, ICON_TICK],
                     ['remove', 'Remove ' + item.fm.pn + ' from Fusion Manage and add ' + item.design.pn, ICON_MINUS]];
    return actionBox(choices.map(function (c) {
      return actionButton(c[0], c[1], c[2], function () { toggleChoice(item, c[0]); redraw(); }, decisions[item.key] === c[0]);
    }));
  }

  /** Add a revert button, beside the line's other buttons, while the user's quantity is over the line's own. */
  function withRevert(box, item, redraw) {
    if (!model.canEditQuantity(item) || !model.quantityEdited(item)) return box;
    const revert = actionButton('revert', 'Revert the quantity to ' + (item.status === 'extra' ? item.fm.quantity : item.design.quantity), ICON_UNDO, function () {
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
    td.appendChild(quantityBox(item.design.quantity, skippedText(item), 'Quantity of ' + (item.componentName || item.design.pn) + ' (skipped)', true));
    return td;
  }

  function editableQuantity(item, redraw) {
    const staged = item.status === 'linked';
    const td = el('td', 'num pub-cmp-qty');
    const input = quantityBox(staged ? item.fm.quantity : model.quantityOf(item), 'Quantity of this line in the Fusion Manage BOM',
                              'Quantity of ' + (staged || fromFm(item) ? item.fm.pn : item.design.pn));
    numbersOnly(input);
    input.addEventListener('change', function () {
      const typed = input.value;
      input.value = staged ? model.setStagedQuantity(item.stagedId, typed) : model.setQuantity(item, typed);
      if (Number(typed) !== Number(input.value)) ns.toast.show('Quantity must be a number above 0', { tone: 'error' });
      if (!staged) redraw();   // the status and filters follow the new quantity
    });
    td.appendChild(input);
    if (model.statusOf(item) === 'changed' || model.quantityDiffers(item)) td.classList.add('pub-cmp-qty-diff');   // will update Fusion Manage
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
