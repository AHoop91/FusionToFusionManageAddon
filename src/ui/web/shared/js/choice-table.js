/**
 * A table to choose one row from, as ``ns.choiceTable`` (styled by shared/css/choice-table.css, with the structure viewer's pane and search).
 *
 * ``ns.choiceTable.make(cfg)`` gives the element. A bar holds a search field and a hint over a pane: the column titles, a row for each
 * choice (its first text, an optional pill, its second text and an arrow) and a footer that counts the rows shown. The search keeps the rows
 * whose two texts hold what was typed. A click on a row calls ``cfg.onPick(key)``.
 *
 * ``cfg``: ``rows`` ``[{key, first, second, pill}]`` (``pill`` is the small tag after the first text, or empty), ``titles`` ``[first, second]``,
 * ``text`` ``{search, hint, label, count(n), none}`` (the caller's own words: this script holds none), ``className`` (added to the table),
 * ``onPick(key)``.
 */
(function (ns) {
  'use strict';

  const el = ns.el;
  const SEARCH = ['M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z', 'M16 16l4.5 4.5'];
  const CHEVRON = ['M9 6l6 6-6 6'];

  /** One row: the first text (with its pill), the second text and an arrow. */
  function row(item, onPick) {
    const choice = el('button', 'ct-row');
    choice.type = 'button';
    const first = el('span', 'ct-first');
    first.appendChild(el('span', 'ct-text', item.first));
    if (item.pill) first.appendChild(el('span', 'ct-pill', item.pill));
    choice.appendChild(first);
    choice.appendChild(el('span', 'ct-text', item.second));
    const arrow = el('span', 'ct-arrow');
    arrow.appendChild(ns.svg(CHEVRON, 16));
    choice.appendChild(arrow);
    choice.addEventListener('click', function () { onPick(item.key); });
    return choice;
  }

  function make(cfg) {
    const text = cfg.text;
    const wrap = el('div', 'ct-wrap' + (cfg.className ? ' ' + cfg.className : ''));
    const search = el('input', 'sv-input sv-search');
    search.type = 'search';
    search.placeholder = text.search;
    search.setAttribute('aria-label', text.search);
    const searchBox = el('div', 'sv-search-box');
    searchBox.append(ns.svg(SEARCH, 16), search);
    const bar = el('div', 'sv-bar');
    bar.append(searchBox, el('span', 'ct-hint', text.hint));
    const box = el('div', 'sv-pane');
    const titles = el('div', 'sv-pane-head ct-titles');   // the column titles are the pane's header
    titles.append(el('span', '', cfg.titles[0]), el('span', '', cfg.titles[1]), el('span'));
    const list = el('div', 'ct-list');
    list.setAttribute('role', 'group');
    list.setAttribute('aria-label', text.label);
    const count = el('div', 'ct-footer');   // the pane's footer: how many rows show
    box.append(titles, list, count);
    function fill() {
      const wanted = search.value.trim().toLowerCase();
      const shown = cfg.rows.filter(function (item) { return (item.first + ' ' + item.second).toLowerCase().indexOf(wanted) >= 0; });
      count.textContent = text.count(shown.length);
      list.replaceChildren.apply(list, shown.length ? shown.map(function (item) { return row(item, cfg.onPick); }) : [el('p', 'ct-none', text.none)]);
    }
    search.addEventListener('input', fill);
    wrap.append(bar, box);
    fill();
    return wrap;
  }

  ns.choiceTable = { make: make };
})(window.MfgUi);
