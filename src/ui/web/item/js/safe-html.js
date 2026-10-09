/**
 * Shows the HTML a Fusion Manage formula field writes (badges, buttons, tables) without running anything in it.
 *
 * The markup is parsed into an inert document and copied node by node: only listed tags are kept (any
 * other is replaced by its text), only listed style properties, and links only to http(s) addresses.
 * A link opens through Python, since a palette cannot open a browser itself.
 */
(function (ns) {
  'use strict';

  const TAGS = ['a', 'b', 'br', 'div', 'em', 'i', 'li', 'p', 'span', 'strong', 'table', 'tbody', 'td', 'th', 'thead', 'tr', 'ul'];
  const STYLES = [
    'background', 'background-color', 'border', 'border-radius', 'color', 'float', 'font-size', 'font-style',
    'font-weight', 'height', 'line-height', 'margin', 'margin-left', 'padding', 'padding-left', 'text-align',
    'text-decoration', 'white-space', 'width',
  ];
  const LINK = /^(https:\/\/|http:\/\/localhost[/:]|http:\/\/127\.0\.0\.1[/:])/i;

  function safeStyle(text) {
    return text.split(';').map(function (rule) {
      const at = rule.indexOf(':');
      if (at < 0) return '';
      const name = rule.slice(0, at).trim().toLowerCase();
      const value = rule.slice(at + 1).trim();
      return STYLES.indexOf(name) >= 0 && !/url\(|expression|javascript|[<>]/i.test(value) ? name + ':' + value.replace(/\s*!important/i, '') : '';
    }).filter(Boolean).join(';');
  }

  function copy(node, into) {
    node.childNodes.forEach(function (child) {
      if (child.nodeType === Node.TEXT_NODE) { into.appendChild(document.createTextNode(child.textContent)); return; }
      if (child.nodeType !== Node.ELEMENT_NODE) return;
      const tag = child.tagName.toLowerCase();
      if (TAGS.indexOf(tag) < 0) { copy(child, into); return; }   // an unknown tag: keep what is inside it
      const clean = document.createElement(tag);
      const style = safeStyle(child.getAttribute('style') || '');
      if (style) clean.setAttribute('style', style);
      if (tag === 'a') {
        const href = child.getAttribute('href') || '';
        if (LINK.test(href)) {
          clean.setAttribute('href', '#');
          clean.addEventListener('click', function (event) {
            event.preventDefault();
            ns.bridge.send('open_url', { url: href });
          });
        }
      }
      copy(child, clean);
      into.appendChild(clean);
    });
  }

  /** Append a safe copy of the markup ``html`` to ``target``. */
  function render(target, html) {
    const parsed = new DOMParser().parseFromString(html, 'text/html');
    copy(parsed.body, target);
  }

  ns.safeHtml = { render: render };
})(window.MfgUi);
