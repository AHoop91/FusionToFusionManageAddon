/**
 * Settings panel: the Export tab. For each file format the Export window can make, where it is attached in Fusion Manage: the item
 * or the component. The choices are saved with the rest of the form (``settings.js``).
 */
(function (ns) {
  'use strict';

  const $ = ns.$;
  const el = ns.el;
  const t = ns.i18n.t;

  const FORMATS = [   // in the order they are listed; the labels are the names of the file formats
    { key: 'step', label: 'STEP' },
    { key: 'pdf', label: 'PDF' },
    { key: 'dwg', label: 'DWG' },
    { key: 'dxf', label: 'DXF' },
  ];

  const DEFAULT_DESTINATION = 'component';   // as in ``export_models.DEFAULT_DESTINATION``

  /** What a file format is, in the language in use. */
  function describe(key) {
    switch (key) {
      case 'step': return t('settings.format_step');
      case 'pdf': return t('settings.format_pdf');
      case 'dwg': return t('settings.format_dwg');
      case 'dxf': return t('settings.format_dxf');
      default: return '';
    }
  }

  function destinations() {
    return [{ key: 'component', label: t('settings.dest_component') }, { key: 'item', label: t('settings.dest_item') }];
  }

  let wanted = {};   // the destination the user set for each format, kept while Item is not offered so it is back when the Items workspace is

  /** One row: the format, what it is, and the radio buttons for where it goes. Without the Items workspace, Item is off and Component is on. */
  function row(f, chosen, itemOn) {
    const wrap = el('div', 'ex-row');
    const name = el('span', 'ex-name', f.label);
    name.appendChild(el('span', 'ex-desc', describe(f.key)));
    wrap.appendChild(name);
    const choice = el('span', 'ex-choice');
    destinations().forEach(function (d) {
      const label = el('label', 'ex-opt');
      const input = el('input');
      input.type = 'radio';
      input.name = 'ex-' + f.key;
      input.value = d.key;
      const off = d.key === 'item' && !itemOn;
      input.disabled = off;
      input.checked = d.key === (itemOn ? chosen : DEFAULT_DESTINATION);
      if (off) {
        label.classList.add('ex-off');
        label.title = t('settings.export_item_off');
      }
      label.appendChild(input);
      label.appendChild(el('span', '', d.label));
      choice.appendChild(label);
    });
    wrap.appendChild(choice);
    return wrap;
  }

  /** Draw the rows for what the user wants, with Item offered only if the Items workspace is. */
  function draw() {
    const box = $('export-rows');
    const itemOn = ns.workspaces.itemsAvailable();
    box.replaceChildren();
    FORMATS.forEach(function (f) {
      const tile = row(f, wanted[f.key] || DEFAULT_DESTINATION, itemOn);
      tile.addEventListener('change', function (e) { wanted[f.key] = e.target.value; });
      box.appendChild(tile);
    });
  }

  /** Show the destinations Python has saved. */
  function render(settings) {
    wanted = Object.assign({}, (settings.exports || {}).destinations);
    draw();
  }

  /** The Items workspace is set on another tab, so draw the rows again when this one is opened. */
  function init() {
    document.querySelector('.tab[data-tab="exports"]').addEventListener('click', draw);
  }

  /** The destinations in the shape Python saves. Without the Items workspace every one is the component. */
  function read() {
    const itemOn = ns.workspaces.itemsAvailable();
    const destinations = {};
    FORMATS.forEach(function (f) { destinations[f.key] = itemOn && wanted[f.key] || DEFAULT_DESTINATION; });
    return { destinations: destinations };
  }

  ns.exports = { init: init, render: render, read: read };
})(window.MfgUi);
