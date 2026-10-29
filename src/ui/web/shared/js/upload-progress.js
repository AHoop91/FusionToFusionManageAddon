/**
 * The card that shows a file upload's progress, as ``ns.uploadProgress``: an icon, the stage, the share done, a bar and the
 * stages of the upload. ``mount(container)`` fills ``container`` and returns ``{ show(state) }``, where ``state`` is Python's
 * ``upload_status`` answer: ``title``, ``stage`` (in words), ``step`` (which of ``steps`` it is at), ``steps`` (the names of
 * the stages) and ``percent`` (null while unknown). Used by the Item panel and the window of the right-click upload.
 */
(function (ns) {
  'use strict';

  const el = ns.el;
  const ICON = '<svg class="upload-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M12 11v6M9 14h6"/></svg>';   // static markup

  function mount(container) {
    container.classList.add('upload-card');
    container.setAttribute('role', 'status');
    container.setAttribute('aria-live', 'polite');
    container.replaceChildren();

    const head = el('div', 'upload-head');
    head.innerHTML = ICON;
    const text = el('div');
    const title = el('h2', 'upload-title', 'Uploading');
    text.appendChild(title);
    const status = el('p', 'muted upload-status', 'Starting...');
    text.appendChild(status);
    head.appendChild(text);
    const count = el('span', 'upload-count');
    head.appendChild(count);
    container.appendChild(head);

    const bar = el('div', 'progress-bar');
    bar.setAttribute('role', 'progressbar');
    bar.setAttribute('aria-valuemin', '0');
    bar.setAttribute('aria-valuemax', '100');
    const fill = el('div', 'progress-fill');
    bar.appendChild(fill);
    container.appendChild(bar);

    const stages = el('ol', 'upload-stages');
    container.appendChild(stages);

    function show(state) {
      const known = state.percent !== null && state.percent !== undefined;
      if (state.title) title.textContent = state.title;
      status.textContent = state.stage ? state.stage + '...' : 'Starting...';
      count.textContent = known ? state.percent + '%' : '';
      bar.classList.toggle('indeterminate', !known);
      if (known) bar.setAttribute('aria-valuenow', String(state.percent)); else bar.removeAttribute('aria-valuenow');
      fill.style.width = known ? state.percent + '%' : '';
      const steps = state.steps || [];
      if (stages.children.length !== steps.length) {
        stages.replaceChildren.apply(stages, steps.map(function (name) { return el('li', '', name); }));
      }
      Array.prototype.forEach.call(stages.children, function (item, index) {
        item.textContent = steps[index];
        item.classList.toggle('done', index < state.step);
        item.classList.toggle('current', index === state.step);
      });
    }

    return { show: show };
  }

  ns.uploadProgress = { mount: mount };
})(window.MfgUi);
