// A page of its own for a test, in the real browser the runner (run.mjs) drives: an iframe whose document is written from ``html``.
// The page's scripts and stylesheets are not loaded, as the tests load the scripts they need themselves with ``run`` (helpers.js).
// So the page is laid out unstyled: a test can rely on a line having a height, not on where Fusion's stylesheet puts it.
'use strict';

/** Take the scripts and stylesheet links out of ``html``: the test runs the scripts it wants, and nothing is fetched. */
function bare(html) {
  return html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '').replace(/<link\b[^>]*>/gi, '');
}

class PageWindow {
  constructor(html) {
    const frame = document.createElement('iframe');
    frame.style.cssText = 'position:fixed;left:0;top:0;width:1024px;height:768px;border:0';
    document.body.appendChild(frame);   // the runner takes every frame away when the test ends
    const win = frame.contentWindow;
    const doc = frame.contentDocument;
    doc.open();
    doc.write(bare(html));   // written, not loaded from srcdoc: the page is there at once
    doc.close();
    // An error the page's own code throws later (a timer, an event) must fail the test, not scroll by in a console.
    win.addEventListener('error', (event) => window.__mfgPageErrors.push(event.error || new Error(event.message)));
    win.addEventListener('unhandledrejection', (event) => window.__mfgPageErrors.push(event.reason));
    this.window = win;
  }
}

module.exports = { PageWindow: PageWindow };
