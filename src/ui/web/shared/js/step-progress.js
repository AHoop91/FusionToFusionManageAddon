/**
 * The card that shows a STEP upload's progress, as ``ns.stepProgress``: an icon, the stage, the share done, a bar and the
 * three stages passed. ``mount(container)`` fills ``container`` and returns ``{ show(state) }``, where ``state`` is Python's
 * ``step_status`` answer (``stage``, ``percent`` or null while unknown). Used by the Item panel and the window of the right-click upload.
 */
(function (ns) {
  'use strict';

  const el = ns.el;
  const STAGES = [['Finding the item', 'Find item'], ['Creating the STEP file', 'Create STEP'], ['Uploading the STEP file', 'Upload']];
  const ICON = '<svg class="step-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M12 11v6M9 14h6"/></svg>';   // static markup

  function mount(container) {
    container.classList.add('step-card');
    container.setAttribute('role', 'status');
    container.setAttribute('aria-live', 'polite');
    container.replaceChildren();

    const head = el('div', 'step-head');
    head.innerHTML = ICON;
    const text = el('div');
    text.appendChild(el('h2', 'step-title', 'Uploading STEP File'));
    const status = el('p', 'muted step-status', 'Starting...');
    text.appendChild(status);
    head.appendChild(text);
    const count = el('span', 'step-count');
    head.appendChild(count);
    container.appendChild(head);

    const bar = el('div', 'progress-bar');
    bar.setAttribute('role', 'progressbar');
    bar.setAttribute('aria-valuemin', '0');
    bar.setAttribute('aria-valuemax', '100');
    const fill = el('div', 'progress-fill');
    bar.appendChild(fill);
    container.appendChild(bar);

    const stages = el('ol', 'step-stages');
    const items = STAGES.map(function (stage) { return stages.appendChild(el('li', '', stage[1])); });
    container.appendChild(stages);

    function show(state) {
      const known = state.percent !== null && state.percent !== undefined;
      status.textContent = state.stage ? state.stage + '...' : 'Starting...';
      count.textContent = known ? state.percent + '%' : '';
      bar.classList.toggle('indeterminate', !known);
      bar.setAttribute('aria-valuenow', known ? String(state.percent) : '');
      fill.style.width = known ? state.percent + '%' : '';
      const at = STAGES.findIndex(function (stage) { return stage[0] === state.stage; });
      items.forEach(function (item, index) {
        item.classList.toggle('done', index < at);
        item.classList.toggle('current', index === at);
      });
    }

    return { show: show };
  }

  ns.stepProgress = { mount: mount };
})(window.MfgUi);
