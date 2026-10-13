/**
 * Settings panel: the Export tab. For each file format the Export window can make, where it is attached in Fusion Manage: the item
 * or the component. The choices are saved with the rest of the form (``settings.js``).
 */
(function (ns) {
  'use strict';

  const $ = ns.$;
  const el = ns.el;

  const FORMATS = [   // in the order they are listed
    { key: 'step', label: 'STEP', desc: 'A 3D model of the open design.' },
    { key: 'pdf', label: 'PDF', desc: 'The open drawing, to print or share.' },
    { key: 'dwg', label: 'DWG', desc: 'The open drawing, for AutoCAD.' },
    { key: 'dxf', label: 'DXF', desc: 'The open drawing, for CAM and laser cutting.' },
  ];
  const DESTINATIONS = [{ key: 'item', label: 'Item' }, { key: 'component', label: 'Component' }];

  /** One row: the format, what it is, and the radio buttons for where it goes. */
  function row(f, chosen) {
    const wrap = el('div', 'ex-row');
    const name = el('span', 'ex-name', f.label);
    name.appendChild(el('span', 'ex-desc', f.desc));
    wrap.appendChild(name);
    const choice = el('span', 'ex-choice');
    DESTINATIONS.forEach(function (d) {
      const label = el('label', 'ex-opt');
      const input = el('input');
      input.type = 'radio';
      input.name = 'ex-' + f.key;
      input.value = d.key;
      input.checked = d.key === chosen;
      label.appendChild(input);
      label.appendChild(el('span', '', d.label));
      choice.appendChild(label);
    });
    wrap.appendChild(choice);
    return wrap;
  }

  /** Show the destinations Python has saved. */
  function render(settings) {
    const where = (settings.exports || {}).destinations || {};
    const box = $('export-rows');
    box.replaceChildren();
    FORMATS.forEach(function (f) { box.appendChild(row(f, where[f.key] || 'item')); });
  }

  /** The destinations as they are set on the page, in the shape Python saves. */
  function read() {
    const destinations = {};
    FORMATS.forEach(function (f) {
      const picked = document.querySelector('input[name="ex-' + f.key + '"]:checked');
      destinations[f.key] = picked ? picked.value : 'item';
    });
    return { destinations: destinations };
  }

  ns.exports = { render: render, read: read };
})(window.MfgUi);
