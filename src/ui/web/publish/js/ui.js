/**
 * Publish Item panel: small drawing helpers (elements, icons, loading / empty / error states)
 * shared by the other scripts of the panel, as ``ns.pubUi``.
 */
(function (ns) {
  'use strict';

  const SVG_NS = 'http://www.w3.org/2000/svg';

  const el = ns.el;
  const svg = ns.svg;

  // ---- Tree icons and chevrons -------------------------------------------------

  const CUBE = ['M12 3l8 4.5v9L12 21l-8-4.5v-9z', 'M4 7.5l8 4.5 8-4.5', 'M12 12v9'];
  const TREE_ICONS = {
    root:     { title: 'This design', paths: ['M5 3h11l3 3v15H5z', 'M8 3v6h7V3', 'M8 21v-7h8v7'] },
    assembly: { title: 'Assembly', paths: CUBE },
    part:     { title: 'Part', paths: CUBE },
  };

  /** Icon in a grey square: the design, an assembly (has children) or a part. */
  function treeIcon(kind) {
    const icon = TREE_ICONS[kind];
    const box = el('span', 'pub-tree-icon pub-tree-icon-' + kind);
    box.title = icon.title;
    box.appendChild(svg(icon.paths, 16));
    return box;
  }

  function setChevron(node, collapsed) {
    node.firstChild.setAttribute('points', collapsed ? '10 6 16 12 10 18' : '6 10 12 16 18 10');
  }

  function chevron() {
    const node = svg([], 16);
    node.appendChild(document.createElementNS(SVG_NS, 'polyline'));
    setChevron(node, false);
    return node;
  }

  // ---- Loading, empty and error states ------------------------------------------

  const SLOW_MS = 15000;          // a wait this long gets a "taking longer" note
  const slowTimers = new WeakMap();   // caption -> its timer

  /**
   * Start timing a wait: ``caption`` shows ``text`` now and, if the loader is still on screen after
   * ``SLOW_MS``, adds that it is taking longer than expected. Call again to restart (a loader shown again).
   */
  function warnWhenSlow(caption, text) {
    clearTimeout(slowTimers.get(caption));
    caption.textContent = text;
    slowTimers.set(caption, setTimeout(function () {
      if (caption.isConnected && !caption.closest('[hidden]')) {
        caption.textContent = text + ' This may take a moment.';
      }
    }, SLOW_MS));
  }

  /** Bouncing balls with a caption. */
  function loaderNode() {
    const box = el('div', 'loader');
    const balls = el('div', 'balls');
    balls.setAttribute('role', 'status');
    balls.setAttribute('aria-label', 'Loading');
    for (let i = 0; i < 3; i++) balls.appendChild(el('span'));
    box.appendChild(balls);
    const caption = el('p', 'muted');
    box.appendChild(caption);
    warnWhenSlow(caption, 'Loading...');
    return box;
  }

  /** Centred failure message with a warning icon and a Retry button. A timeout gets its own wording. */
  function errorState(message, onRetry) {
    const timedOut = /timed out|timeout/i.test(message || '');
    const card = el('div', 'card pub-empty pub-error-state');
    // A clock for a timeout, a warning triangle for anything else.
    card.appendChild(svg(timedOut ? ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', 'M12 7v5l3 2'] : ['M12 3l10 18H2z', 'M12 10v5', 'M12 18.2v.3'], 28));
    card.appendChild(el('h4', 'pub-error-title', timedOut ? 'Timed out' : 'Could not load'));
    card.appendChild(el('p', 'muted', timedOut ? 'The request took too long. Please try again.' : (message || 'Unknown error')));
    const retry = el('button', 'pub-outline-button pub-retry', 'Retry');
    retry.type = 'button';
    retry.addEventListener('click', onRetry);
    card.appendChild(retry);
    return card;
  }

  ns.pubUi = {
    el: el, svg: svg, treeIcon: treeIcon, chevron: chevron, setChevron: setChevron,
    loaderNode: loaderNode, warnWhenSlow: warnWhenSlow, errorState: errorState,
  };
})(window.MfgUi);
