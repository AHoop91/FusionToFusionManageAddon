/**
 * Publish Item panel: small drawing helpers (elements, icons, loading / empty / error states)
 * shared by the other scripts of the panel, as ``ns.pubUi``.
 */
(function (ns) {
  'use strict';

  const SVG_NS = 'http://www.w3.org/2000/svg';

  const el = ns.el;

  /** A 24x24 icon drawn from path strings; ``size`` (px) is optional, the stylesheet can size it instead. */
  function svg(paths, size) {
    const node = document.createElementNS(SVG_NS, 'svg');
    node.setAttribute('viewBox', '0 0 24 24');
    node.setAttribute('aria-hidden', 'true');
    if (size) {
      node.setAttribute('width', String(size));
      node.setAttribute('height', String(size));
    }
    paths.forEach(function (d) {
      const path = document.createElementNS(SVG_NS, 'path');
      path.setAttribute('d', d);
      node.appendChild(path);
    });
    return node;
  }

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

  /** Bouncing balls with a caption. */
  function loaderNode() {
    const box = el('div', 'loader');
    const balls = el('div', 'balls');
    balls.setAttribute('role', 'status');
    balls.setAttribute('aria-label', 'Loading');
    for (let i = 0; i < 3; i++) balls.appendChild(el('span'));
    box.appendChild(balls);
    box.appendChild(el('p', 'muted', 'Loading...'));
    return box;
  }

  /** Centred failure message with a warning icon and a Retry button. A timeout gets its own wording. */
  function errorState(message, onRetry) {
    const timedOut = /timed out|timeout/i.test(message || '');
    const card = el('div', 'card pub-empty pub-error-state');
    // A clock for a timeout, a warning triangle for anything else.
    card.appendChild(svg(timedOut ? ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', 'M12 7v5l3 2'] : ['M12 3l10 18H2z', 'M12 10v5', 'M12 18.2v.3'], 28));
    card.appendChild(el('h4', 'pub-error-title', timedOut ? 'Timed out' : 'Could not load'));
    card.appendChild(el('p', 'muted', timedOut ? 'The Manufacturing Data Model took too long to respond.' : (message || 'Unknown error')));
    const retry = el('button', 'pub-drawing-open pub-retry', 'Retry');
    retry.type = 'button';
    retry.addEventListener('click', onRetry);
    card.appendChild(retry);
    return card;
  }

  /** Centred "nothing here" message with an empty-tray icon, in a white card. */
  function emptyState(text) {
    const card = el('div', 'card pub-empty');
    card.appendChild(svg(['M3 13l3-8h12l3 8v6H3z', 'M3 13h5l1 3h6l1-3h5'], 28));
    card.appendChild(el('p', 'muted', text));
    return card;
  }

  ns.pubUi = {
    el: el, svg: svg, treeIcon: treeIcon, chevron: chevron, setChevron: setChevron,
    loaderNode: loaderNode, errorState: errorState, emptyState: emptyState,
  };
})(window.MfgUi);
