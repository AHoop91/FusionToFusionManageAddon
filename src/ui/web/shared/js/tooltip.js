/**
 * Tooltips that show quickly, as ``MfgUi.tooltip``.
 *
 * A browser waits about a second before it shows the ``title`` of an element, and that cannot be changed. This takes over the ``title``s
 * of the page: while the pointer is over an element with one, the title is held back (so the browser shows nothing of its own) and a
 * small tooltip of the page's own appears after a short pause. The title goes back on the element when the pointer leaves it, so
 * nothing else that reads titles is affected, and elements added later need nothing done.
 */
(function (ns) {
  'use strict';

  const DELAY_MS = 120;   // how long the pointer rests on an element before its tooltip shows
  const GAP = 8;          // px between the element and its tooltip
  const MARGIN = 8;       // px kept free at the edge of the window

  let tip = null;         // the tooltip's box
  let timer = 0;
  let holder = null;      // the element whose title is held back: { node, title }

  function box() {
    if (!tip) {
      tip = document.createElement('div');
      tip.className = 'mfg-tip';
      tip.setAttribute('role', 'tooltip');
      tip.hidden = true;
      document.body.appendChild(tip);
    }
    return tip;
  }

  function hide() {
    clearTimeout(timer);
    if (tip) { tip.hidden = true; tip.classList.remove('on'); }
  }

  /** Give the held-back title back to its element (unless the page has set a new one meanwhile). */
  function release() {
    if (holder && !holder.node.hasAttribute('title')) holder.node.setAttribute('title', holder.title);
    holder = null;
  }

  function place(node) {
    const t = box();
    const r = node.getBoundingClientRect();
    const w = t.offsetWidth;
    const h = t.offsetHeight;
    let left = r.left + r.width / 2 - w / 2;
    left = Math.max(MARGIN, Math.min(left, window.innerWidth - w - MARGIN));
    let top = r.top - h - GAP;   // above the element, or below it when there is no room
    if (top < MARGIN) top = r.bottom + GAP;
    t.style.left = Math.round(left) + 'px';
    t.style.top = Math.round(top) + 'px';
  }

  function show(node, text) {
    const t = box();
    t.textContent = text;
    t.hidden = false;
    place(node);
    t.classList.add('on');
  }

  document.addEventListener('mouseover', function (event) {
    const node = event.target instanceof Element ? event.target.closest('[title]') : null;
    if (!node || (holder && holder.node === node)) return;
    release();
    hide();
    const title = node.getAttribute('title');
    if (!title) return;
    node.removeAttribute('title');   // so the browser shows nothing of its own
    if (!node.hasAttribute('aria-label') && !node.textContent.trim()) node.setAttribute('aria-label', title);   // an icon with only a title keeps its name
    holder = { node: node, title: title };
    timer = setTimeout(function () { show(node, title); }, DELAY_MS);
  }, true);

  document.addEventListener('mouseout', function (event) {
    if (!holder || (event.relatedTarget instanceof Node && holder.node.contains(event.relatedTarget))) return;
    hide();
    release();
  }, true);

  // A click, a key or a scroll ends it: the element may be about to change or move.
  ['mousedown', 'keydown', 'scroll', 'blur'].forEach(function (name) {
    window.addEventListener(name, function () { hide(); release(); }, true);
  });

  ns.tooltip = { hide: hide };
})(window.MfgUi = window.MfgUi || {});
