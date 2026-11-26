/**
 * Drag a row of a list to a new place by its grip (shared by the lists of columns on the page). Layer: UI.
 *
 * ``start(event, {row, list, rowSelector, onDrop})`` is called from the grip's ``pointerdown``. The row follows the pointer, a line shows where it
 * will land (the classes ``sort-before`` and ``sort-after`` on the row it lands beside), and the list scrolls when the pointer nears its top or
 * bottom edge. Pointer events, so a mouse, a pen and a finger all work. When it is let go somewhere else, ``onDrop(from, to)`` is told the row's
 * place and the place it takes among the others (the caller changes its data and paints the list again); let go where it was, or cancelled, it
 * just goes back.
 */
(function (ns) {
  'use strict';

  const SCROLL_EDGE = 36;   // px from the top or bottom of the list at which dragging scrolls it

  // A drag is one object ``d``: {row, list, others (the other rows), index (the row's place), grip, startY, startScroll, edges, y, target,
  // scroller, onDrop}. ``target`` is the place the row takes among the others when it is let go.

  /** Move the row with the pointer and mark the row it would land beside. */
  function follow(d) {
    d.row.style.transform = 'translateY(' + (d.y - d.startY + d.list.scrollTop - d.startScroll) + 'px)';
    const here = d.row.getBoundingClientRect();
    const middle = here.top + here.height / 2;
    d.target = d.others.filter(function (r) { const box = r.getBoundingClientRect(); return middle > box.top + box.height / 2; }).length;
    d.others.forEach(function (r, i) {
      r.classList.toggle('sort-before', i === d.target);
      r.classList.toggle('sort-after', i === d.others.length - 1 && d.target === d.others.length);
    });
  }

  /** How far the list scrolls in one tick: up or down when the pointer is near an edge, else not at all. */
  function scrollStep(d) {
    if (d.y < d.edges.top + SCROLL_EDGE) return -8;
    if (d.y > d.edges.bottom - SCROLL_EDGE) return 8;
    return 0;
  }

  function scrollList(d) {
    const step = scrollStep(d);
    if (!step) return;
    d.list.scrollTop += step;
    follow(d);
  }

  /** Let the row go: stop listening, clear the marks, and tell ``onDrop`` if it landed somewhere else. */
  function finishDrag(d, listeners, e) {
    clearInterval(d.scroller);
    d.grip.removeEventListener('pointermove', listeners.move);
    d.grip.removeEventListener('pointerup', listeners.end);
    d.grip.removeEventListener('pointercancel', listeners.end);
    if (d.grip.hasPointerCapture(e.pointerId)) d.grip.releasePointerCapture(e.pointerId);
    d.row.classList.remove('sort-dragging');
    d.row.style.transform = '';
    d.list.classList.remove('sort-active');
    d.others.forEach(function (r) { r.classList.remove('sort-before', 'sort-after'); });
    if (e.type === 'pointerup' && d.target !== d.index) d.onDrop(d.index, d.target);
  }

  function beginDrag(event, drag) {
    const rows = Array.from(drag.list.querySelectorAll(drag.rowSelector));
    const index = rows.indexOf(drag.row);
    return {
      row: drag.row,
      list: drag.list,
      others: rows.filter(function (r) { return r !== drag.row; }),
      index: index,
      grip: event.currentTarget,
      startY: event.clientY,
      startScroll: drag.list.scrollTop,
      edges: drag.list.getBoundingClientRect(),
      y: event.clientY,
      target: index,
      scroller: 0,
      onDrop: drag.onDrop
    };
  }

  function start(event, drag) {
    if (event.button !== 0) return;
    event.preventDefault();
    const d = beginDrag(event, drag);
    d.row.classList.add('sort-dragging');
    d.list.classList.add('sort-active');
    d.grip.setPointerCapture(event.pointerId);
    d.scroller = setInterval(function () { scrollList(d); }, 16);
    const listeners = {
      move: function (e) { d.y = e.clientY; follow(d); },
      end: function (e) { finishDrag(d, listeners, e); }
    };
    d.grip.addEventListener('pointermove', listeners.move);
    d.grip.addEventListener('pointerup', listeners.end);
    d.grip.addEventListener('pointercancel', listeners.end);
  }

  const GRIP = ['M9 6h.01', 'M15 6h.01', 'M9 12h.01', 'M15 12h.01', 'M9 18h.01', 'M15 18h.01'];   // the six dots of a grip, as paths for `ns.svg`

  ns.sortable = { start: start, GRIP: GRIP };
})(window.MfgUi);
