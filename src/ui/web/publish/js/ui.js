/**
 * Publish Item panel: small drawing helpers (elements, icons, loading / empty / error states)
 * shared by the other scripts of the panel, as ``ns.pubUi``.
 */
(function (ns) {
  'use strict';

  const SVG_NS = 'http://www.w3.org/2000/svg';

  const el = ns.el;
  const svg = ns.svg;
  function t(key, params) { return ns.i18n.t(key, params); }

  // ---- Tree icons and chevrons -------------------------------------------------

  const CUBE = ['M12 3l8 4.5v9L12 21l-8-4.5v-9z', 'M4 7.5l8 4.5 8-4.5', 'M12 12v9'];
  const TREE_ICONS = {
    root:     { paths: ['M5 3h11l3 3v15H5z', 'M8 3v6h7V3', 'M8 21v-7h8v7'] },
    assembly: { paths: CUBE },
    part:     { paths: CUBE },
  };

  function treeIconTitle(kind) {
    if (kind === 'root') return t('publish.tree_this_design');
    return kind === 'assembly' ? t('publish.tree_assembly') : t('publish.tree_part');
  }

  /** Icon in a grey square: the design, an assembly (has children) or a part. */
  function treeIcon(kind) {
    const icon = TREE_ICONS[kind];
    const box = el('span', 'pub-tree-icon pub-tree-icon-' + kind);
    box.title = treeIconTitle(kind);
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

  // ---- Collapse all and Expand all ----------------------------------------------

  // The icons of the structure viewer's bar: a solid box with a minus (collapse all) or a plus (expand all).
  const FOLD_ICONS = {
    collapse: ['M8 12h8'],
    expand: ['M8 12h8', 'M12 8v8'],
  };

  function foldTool(kind, title, onClick) {
    const b = el('button', 'pub-cmp-tool pub-cmp-tool-' + kind);
    b.type = 'button';
    b.title = title;
    b.setAttribute('aria-label', title);
    const icon = svg(FOLD_ICONS[kind]);
    const box = document.createElementNS(SVG_NS, 'rect');
    [['x', 4], ['y', 4], ['width', 16], ['height', 16], ['rx', 2]].forEach(function (a) { box.setAttribute(a[0], String(a[1])); });
    icon.insertBefore(box, icon.firstChild);
    b.appendChild(icon);
    b.addEventListener('click', onClick);
    return b;
  }

  /** Collapse all and expand all, as a pair of buttons. */
  function foldTools(collapseAll, expandAll) {
    const pair = el('div', 'pub-cmp-pair');
    pair.appendChild(foldTool('collapse', t('publish.collapse_all'), collapseAll));
    pair.appendChild(foldTool('expand', t('publish.expand_all'), expandAll));
    return pair;
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
        caption.textContent = text + ' ' + t('publish.slow_note');
      }
    }, SLOW_MS));
  }

  /** Bouncing balls with a caption (``text``, "Loading..." when it is not given). */
  function loaderNode(text) {
    const box = el('div', 'loader');
    const balls = el('div', 'balls');
    balls.setAttribute('role', 'status');
    balls.setAttribute('aria-label', t('publish.loading_aria'));
    for (let i = 0; i < 3; i++) balls.appendChild(el('span'));
    box.appendChild(balls);
    const caption = el('p', 'muted');
    box.appendChild(caption);
    warnWhenSlow(caption, text || t('publish.loading'));
    return box;
  }

  /** ``count`` rows of grey bars with the thumbnail's sweep: the shape of a table that is on its way. Hidden from assistive technology. */
  function skeletonRows(count) {
    const rows = [];
    for (let n = 0; n < count; n++) {
      const row = el('div', 'pub-skel-row');
      row.setAttribute('aria-hidden', 'true');
      ['pub-skel-wide', 'pub-skel-mid', 'pub-skel-short'].forEach(function (width) { row.appendChild(el('span', 'pub-skel ' + width)); });
      rows.push(row);
    }
    return rows;
  }

  /** Centred failure message with a warning icon and a Retry button. A timeout gets its own wording. */
  function errorState(message, onRetry) {
    const timedOut = /timed out|timeout/i.test(message || '');
    const card = el('div', 'card pub-empty pub-error-state');
    // A clock for a timeout, a warning triangle for anything else.
    card.appendChild(svg(timedOut ? ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', 'M12 7v5l3 2'] : ['M12 3l10 18H2z', 'M12 10v5', 'M12 18.2v.3'], 28));
    card.appendChild(el('h4', 'pub-error-title', timedOut ? t('publish.error_timed_out') : t('publish.error_could_not_load')));
    card.appendChild(el('p', 'muted', timedOut ? t('publish.error_timeout_text') : (message || t('publish.unknown_error'))));
    const retry = el('button', 'pub-outline-button pub-retry', t('publish.retry'));
    retry.type = 'button';
    retry.addEventListener('click', onRetry);
    card.appendChild(retry);
    return card;
  }

  /** Disable ``button`` and show ``label`` on it while something is under way. Returns the function that gives it back its own label (the caller sets
   *  whether it is enabled). */
  function busy(button, label) {
    const was = button.textContent;
    button.disabled = true;
    button.textContent = label;
    return function release() {
      button.disabled = false;
      button.textContent = was;
    };
  }

  ns.pubUi = {
    busy: busy, el: el, svg: svg, treeIcon: treeIcon, chevron: chevron, setChevron: setChevron,
    loaderNode: loaderNode, skeletonRows: skeletonRows, warnWhenSlow: warnWhenSlow, errorState: errorState, foldTools: foldTools,
  };
})(window.MfgUi);
