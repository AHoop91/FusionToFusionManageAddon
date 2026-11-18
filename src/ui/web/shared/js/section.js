/**
 * The section card of a form or an item, as ``ns.section``: a bar with the title that folds the content away, and the content under it.
 * The Product Portfolio form and the Item panel both draw their sections with it (styled by ``shared/css/section.css``).
 *
 * ``make(title, content, options)`` returns the card (a <section>). ``content`` is the element of the section's rows (the card gives it
 * the class ``section-body``); ``options.folded`` starts it folded. A section with no ``title`` has no bar and cannot be folded.
 */
(function (ns) {
  'use strict';

  const el = ns.el;

  function make(title, content, options) {
    const card = el('section', 'section');
    content.classList.add('section-body');
    if (title) {
      const bar = el('button', 'section-title');
      bar.type = 'button';
      bar.appendChild(el('span', '', title));
      bar.appendChild(ns.svg(['M6 9l6 6 6-6'], 20));
      const fold = function (folded) {
        content.hidden = folded;
        card.classList.toggle('folded', folded);
        bar.setAttribute('aria-expanded', String(!folded));
      };
      fold(Boolean(options && options.folded));
      bar.addEventListener('click', function () { fold(!content.hidden); });
      card.appendChild(bar);
    }
    card.appendChild(content);
    return card;
  }

  ns.section = { make: make };
})(window.MfgUi);
