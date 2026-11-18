/**
 * The first screen of the View product portfolio window: where the open design is used. The head says what the design is (``products_design``:
 * thumbnail, name, item number, revision and state), and two tabs, Primary Components and Variants, list the products it is the Primary
 * Component or a variant of (``products_usage``) as cards, 25 at a time. A card's picture is read only once the card is on screen.
 *
 * The page lends what it shares (``host``: ``ask`` for a request to Python, ``failure``, ``openLightbox``, and its pop-up ``menu`` with
 * ``forgetMenus``) and asks for a check with ``ns.usage.init(host).load()``.
 */
(function (ns) {
  'use strict';

  const bridge = ns.bridge;
  const $ = ns.$;
  const el = ns.el;
  const t = ns.i18n.t;

  let host = null;   // what the page lends: see ``init``

  let usageSeq = 0;   // numbers the checks, so the answer to an earlier one is dropped

  const USAGE_PAGE = 25;   // cards shown at first in each group, and added by each press of Load more
  const EMPTY_ICON = ['M3 7l9-4 9 4-9 4-9-4z', 'M3 7v10l9 4 9-4V7', 'M12 11v10'];   // an empty box: the design is in no product
  const PICTURE_ICON = ['M3 5h18v14H3z', 'M3 15l5-5 4 4 3-3 6 6'];   // stands in for a picture there is not
  const usagePictures = {};   // picture link -> data uri ('' when there is none)

  let pictureWatcher = null;   // sees which thumbnails are on screen, so a picture is read only for a card that can be seen

  /** Call ``load`` once ``box`` is on screen in the usage view: a card below the fold, or on a tab that is not shown, is not read yet. */
  function whenSeen(box, load) {
    if (!window.IntersectionObserver) { load(); return; }
    if (!pictureWatcher) {
      pictureWatcher = new IntersectionObserver(function (seen) {
        seen.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          pictureWatcher.unobserve(entry.target);
          entry.target.loadPicture();
        });
      }, { root: $('products-usageview') });
    }
    box.loadPicture = load;
    pictureWatcher.observe(box);
  }

  /** The picture of a card: a shimmer until it is on screen and read, the product's own image, or a plain icon when it holds none. */
  function usageThumb(link) {
    const box = el('div', 'pu-thumb');
    function put(uri) {
      box.classList.remove('loading');
      box.textContent = '';
      if (!uri) { box.appendChild(ns.svg(PICTURE_ICON, 28)); return; }
      const img = el('img', '');
      img.src = uri;
      img.alt = '';
      img.addEventListener('click', function () { host.openLightbox(uri); });
      box.appendChild(img);
    }
    if (!link) { put(''); return box; }
    if (link in usagePictures) { put(usagePictures[link]); return box; }
    box.classList.add('loading');
    whenSeen(box, function () {
      host.ask('products_picture', { link: link }, function (answer) {
        usagePictures[link] = answer.ok ? answer.result.image : '';
        put(usagePictures[link]);
      });
    });
    return box;
  }

  /** Open the design a product's Primary Component was published from, in Fusion: Python reads the design's id from the component's item, then
   *  Fusion opens it (``products_open_file``). Not offered on this page, where the design is open already: a menu entry
   *  (``openInFusion(product.component)``) and the text "Open in Fusion" are all it needs. */
  function openInFusion(component) {
    host.ask('products_design_file', { link: component }, function (answer) {
      if (!answer.ok) { ns.toast.show(t('products.usage_open_failed', { reason: host.failure(answer) }), { tone: 'error' }); return; }
      bridge.send('products_open_file', { file: answer.result.file });
    });
  }

  /** The three dots of a card and the menu they open, the page's own ``menu``: ``entries`` is ``[{label, run}]``. */
  function usageMenu(entries) {
    const box = el('div', 'products-dropdown pu-menu');
    const button = el('button', 'products-icon-btn', '');
    button.type = 'button';
    button.title = t('products.usage_actions');
    button.setAttribute('aria-label', t('products.usage_actions'));
    button.setAttribute('aria-haspopup', 'menu');
    button.setAttribute('aria-expanded', 'false');
    button.appendChild(ns.svg(['M12 5h.01', 'M12 12h.01', 'M12 19h.01'], 16));
    const list = el('div', 'products-menu products-menu-end', '');
    list.setAttribute('role', 'menu');
    list.hidden = true;
    entries.forEach(function (entry) {
      const item = el('button', 'products-menu-item', '');
      item.type = 'button';
      item.setAttribute('role', 'menuitem');
      item.appendChild(el('span', 'products-menu-label', entry.label));
      item.addEventListener('click', entry.run);
      list.appendChild(item);
    });
    box.appendChild(button);
    box.appendChild(list);
    host.menu(button, list);
    return box;
  }

  /** One card: the picture, the product's name and number, how the design stands to it, and the way to open it in Fusion Manage. */
  function usageCard(product, variant) {
    const card = el('div', 'pu-card');
    card.appendChild(usageThumb(product.picture));
    const info = el('div', 'pu-info');
    info.appendChild(el('div', 'pu-name', product.name));
    if (product.number) info.appendChild(el('div', 'pu-number', product.number));
    const meta = el('div', 'pu-meta');
    meta.appendChild(el('span', 'pu-badge' + (variant ? ' variant' : ''), variant ? t('products.usage_role_variant') : t('products.usage_role_primary')));
    if (variant) meta.appendChild(el('span', '', product.rows > 1 ? t('products.usage_rows', { count: product.rows }) : t('products.usage_row')));
    info.appendChild(meta);
    card.appendChild(info);
    card.appendChild(usageMenu([{ label: t('products.usage_open'), run: function () { bridge.send('open_url', { url: product.url }); } }]));
    return card;
  }

  /** A centred icon over a message, filling the space it is in. ``plain`` leaves out the dashed border. */
  function usageEmpty(message, size, plain) {
    const box = el('div', 'pu-empty' + (plain ? ' plain' : ''));
    box.appendChild(ns.svg(EMPTY_ICON, size));
    box.appendChild(el('p', '', message));
    return box;
  }

  /** The tab of one kind and the panel of its cards (or the word that there are none): ``{tab, panel, count}``. */
  function usageGroup(list, variant) {
    const panel = el('section', 'pu-panel');
    panel.setAttribute('role', 'tabpanel');
    const tab = el('button', 'tab', '');
    tab.type = 'button';
    tab.setAttribute('role', 'tab');
    /** The tab's text, with how many cards are shown of how many there are: ``Variants (25 of 80)``. */
    function title(shown) {
      const count = list.length ? t('products.usage_of', { shown: shown, total: list.length }) : '0';
      tab.textContent = variant ? t('products.usage_variant_tab', { count: count }) : t('products.usage_primary_tab', { count: count });
    }
    const group = { tab: tab, panel: panel, count: list.length };
    if (!list.length) {
      title(0);
      panel.appendChild(usageEmpty(variant ? t('products.usage_variant_none') : t('products.usage_primary_none'), 36, false));
      return group;
    }
    const cards = el('div', 'pu-cards');
    const foot = el('div', 'pu-more');
    panel.appendChild(cards);
    panel.appendChild(foot);
    let shown = 0;
    /** Add the next ``USAGE_PAGE`` cards; the tab says how many are shown and the footer offers the next ones until all are. */
    function more() {
      list.slice(shown, shown + USAGE_PAGE).forEach(function (p) { cards.appendChild(usageCard(p, variant)); });
      shown = Math.min(list.length, shown + USAGE_PAGE);
      title(shown);
      foot.textContent = '';
      if (shown >= list.length) return;
      const button = el('button', 'btn btn-secondary', t('products.usage_more'));
      button.type = 'button';
      button.addEventListener('click', more);
      foot.appendChild(button);
    }
    more();
    return group;
  }

  let usageTab = -1;   // the tab the person chose last (0 Primary, 1 Variant); -1 until they choose one

  /** The tabs of the groups and their panels, one panel shown at a time. It opens on the tab the person chose last, else on the first that has cards. */
  function usageTabs(groups) {
    const box = el('div', 'pu-tabbed');
    const strip = el('div', 'tabs pu-tabs');
    strip.setAttribute('role', 'tablist');
    function select(at) {
      groups.forEach(function (g, i) {
        g.tab.classList.toggle('active', i === at);
        g.tab.setAttribute('aria-selected', String(i === at));
        g.panel.hidden = i !== at;
      });
    }
    groups.forEach(function (g, i) {
      g.tab.addEventListener('click', function () { usageTab = i; select(i); });
      strip.appendChild(g.tab);
    });
    box.appendChild(strip);
    groups.forEach(function (g) { box.appendChild(g.panel); });
    const first = groups.findIndex(function (g) { return g.count > 0; });
    select(usageTab >= 0 && usageTab < groups.length ? usageTab : Math.max(first, 0));
    return box;
  }

  let designSeq = 0;   // numbers the reads of the design, so the answer to an earlier one is dropped

  /** The head of the page: the open design's thumbnail, name, item number, revision and state. ``details`` is null while they are read (a
   *  skeleton stands in), and blank when they could not be: the page then keeps its plain title and shows less. */
  function showDesign(details) {
    const thumb = $('products-design-thumb');
    const title = $('products-usage-title');
    const meta = $('products-design-meta');
    const loading = !details;
    thumb.classList.toggle('loading', loading);
    title.classList.toggle('loading', loading);
    thumb.textContent = '';
    meta.textContent = '';
    if (loading) {
      title.textContent = '';
      for (let n = 0; n < 2; n++) meta.appendChild(el('span', 'pu-chip loading', ''));
      return;
    }
    title.textContent = details.name || t('products.usage_title');
    if (details.thumbnail_url) {
      const img = el('img', '');
      img.src = details.thumbnail_url;
      img.alt = '';
      img.addEventListener('error', function () { thumb.textContent = ''; thumb.appendChild(ns.svg(PICTURE_ICON, 28)); });
      thumb.appendChild(img);
    } else {
      thumb.appendChild(ns.svg(PICTURE_ICON, 28));
    }
    if (details.number) meta.appendChild(el('span', '', details.number));
    if (details.revision) meta.appendChild(el('span', 'pu-chip', details.revision));
    if (details.state) meta.appendChild(el('span', 'pu-chip state', details.state));
  }

  /** The design's details, read for the head of the page. A failed read leaves the head plain: the cards below are what matters. */
  function loadDesign() {
    const mine = ++designSeq;
    showDesign(null);
    host.ask('products_design', {}, function (answer) {
      if (mine === designSeq) showDesign(answer.ok ? answer.result : {});
    });
  }

  /** What stands in for the cards while they are read: two tabs and three cards of grey blocks. */
  function usageSkeleton() {
    const box = el('div', '');
    box.setAttribute('role', 'status');
    box.setAttribute('aria-label', t('products.usage_checking'));
    const strip = el('div', 'tabs pu-tabs');
    ['220px', '160px'].forEach(function (width) { strip.appendChild(el('div', 'pu-skel pu-skel-tab', '')).style.width = width; });
    box.appendChild(strip);
    const cards = el('div', 'pu-cards');
    for (let n = 0; n < 3; n++) {
      const card = el('div', 'pu-card skeleton');
      card.appendChild(el('div', 'pu-thumb pu-skel', ''));
      const info = el('div', 'pu-info');
      [180, 110, 70].forEach(function (width) { info.appendChild(el('div', 'pu-skel pu-skel-line', '')).style.width = width + 'px'; });
      card.appendChild(info);
      cards.appendChild(card);
    }
    box.appendChild(cards);
    return box;
  }

  function usageLine(text, className) {
    $('products-usage-body').appendChild(el('p', className || '', text));
  }

  /** Show what ``products_usage`` found: the products the design is the Primary Component or a variant of, or that it is in none. A check that
   *  failed says so: it is never shown as "not used". */
  function showUsage(result) {
    const body = $('products-usage-body');
    if (pictureWatcher) pictureWatcher.disconnect();   // the cards it watched are about to go
    host.forgetMenus(body);
    body.textContent = '';
    if (!result) { body.appendChild(usageSkeleton()); return; }
    if (result.error) { usageLine(t('products.usage_failed', { reason: result.error }), 'pu-bad'); return; }
    if (result.unpublished) { usageLine(result.message, 'pu-muted'); return; }
    if (!result.primary.length && !result.variants.length) {   // used nowhere: one message, in the middle of the space there is
      const empty = usageEmpty(t('products.usage_none', { number: result.number }), 56, true);
      if (!result.variants_checked) empty.appendChild(el('p', 'pu-muted', t('products.usage_no_variants')));
      body.appendChild(empty);
      return;
    }
    const groups = [usageGroup(result.primary, false)];
    if (result.variants_checked) groups.push(usageGroup(result.variants, true));
    body.appendChild(usageTabs(groups));
    if (!result.variants_checked) usageLine(t('products.usage_no_variants'), 'pu-muted');
  }

  /** Check where the open design is used. Run when the page opens, from Refresh and after every assign. */
  function loadUsage() {
    const mine = ++usageSeq;
    showUsage(null);
    $('products-usage-recheck').disabled = true;
    loadDesign();
    host.ask('products_usage', {}, function (answer) {
      if (mine !== usageSeq) return;
      $('products-usage-recheck').disabled = false;
      showUsage(answer.ok ? answer.result : { error: host.failure(answer) });
    });
  }

  /** Wire the screen to the page. Returns ``{load}``: ``load()`` checks where the design is used and shows the answer. */
  function init(lent) {
    host = lent;
    bridge.on('products_open_file', function (answer) {   // Fusion's own answer: only a failure is said
      if (!answer.ok) ns.toast.show(t('products.usage_open_failed', { reason: answer.error }), { tone: 'error' });
    });
    return { load: loadUsage };
  }

  ns.usage = { init: init };
})(window.MfgUi);
