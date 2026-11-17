/**
 * Drag a row of a list to a new place by its grip (shared by the lists of columns on the page).
 *
 * ``start`` is called from the grip's ``pointerdown``. The row follows the pointer, a line shows where it will land (the classes ``sort-before`` and
 * ``sort-after`` on the row it lands beside), and the list scrolls when the pointer nears its top or bottom edge. Pointer events, so a mouse, a pen
 * and a finger all work. When it is let go somewhere else, ``onDrop(from, to)`` is told the row's place and the place it takes among the others
 * (the caller changes its data and paints the list again); let go where it was, or cancelled, it just goes back.
 */
(function (ns) {
  'use strict';

  const SCROLL_EDGE = 36;   // px from the top or bottom of the list at which dragging scrolls it

  function start(event, row, list, rowSelector, onDrop) {
    if (event.button !== 0) return;
    event.preventDefault();
    const rows = Array.from(list.querySelectorAll(rowSelector));
    const index = rows.indexOf(row);
    const others = rows.filter(function (r) { return r !== row; });
    const grip = event.currentTarget;
    const startY = event.clientY;
    const startScroll = list.scrollTop;
    const edges = list.getBoundingClientRect();
    let y = startY;
    let target = index;   // the place the row takes among the others when it is let go
    row.classList.add('sort-dragging');
    list.classList.add('sort-active');
    grip.setPointerCapture(event.pointerId);

    function follow() {
      row.style.transform = 'translateY(' + (y - startY + list.scrollTop - startScroll) + 'px)';
      const here = row.getBoundingClientRect();
      const middle = here.top + here.height / 2;
      target = others.filter(function (r) { const box = r.getBoundingClientRect(); return middle > box.top + box.height / 2; }).length;
      others.forEach(function (r, i) {
        r.classList.toggle('sort-before', i === target);
        r.classList.toggle('sort-after', i === others.length - 1 && target === others.length);
      });
    }

    const scroller = setInterval(function () {
      const step = y < edges.top + SCROLL_EDGE ? -8 : (y > edges.bottom - SCROLL_EDGE ? 8 : 0);
      if (!step) return;
      list.scrollTop += step;
      follow();
    }, 16);

    function onMove(e) { y = e.clientY; follow(); }
    function onEnd(e) {
      clearInterval(scroller);
      grip.removeEventListener('pointermove', onMove);
      grip.removeEventListener('pointerup', onEnd);
      grip.removeEventListener('pointercancel', onEnd);
      if (grip.hasPointerCapture(e.pointerId)) grip.releasePointerCapture(e.pointerId);
      row.classList.remove('sort-dragging');
      row.style.transform = '';
      list.classList.remove('sort-active');
      others.forEach(function (r) { r.classList.remove('sort-before', 'sort-after'); });
      if (e.type === 'pointerup' && target !== index) onDrop(index, target);
    }
    grip.addEventListener('pointermove', onMove);
    grip.addEventListener('pointerup', onEnd);
    grip.addEventListener('pointercancel', onEnd);
  }

  const GRIP = ['M9 6h.01', 'M15 6h.01', 'M9 12h.01', 'M15 12h.01', 'M9 18h.01', 'M15 18h.01'];   // the six dots of a grip, as paths for `ns.svg`

  ns.sortable = { start: start, GRIP: GRIP };
})(window.MfgUi);
