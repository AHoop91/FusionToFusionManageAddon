// Tooltips that show quickly: the title is held back while the pointer is over an element, shown in the page's own box, and given back.
// Needs jsdom (``npm install jsdom``); without it this test is skipped.
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const { WEB } = require('./helpers');

let JSDOM = null;
try { JSDOM = require('jsdom').JSDOM; } catch (error) { /* skipped below */ }

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

test('a title shows in the page\'s own tooltip after a short pause, and goes back when the pointer leaves', { skip: JSDOM ? false : 'jsdom is not installed' }, async () => {
  const dom = new JSDOM('<body><button id="b" title="Explains the button">Go</button><button id="i" title="Only a title"><svg></svg></button><p id="out">x</p></body>',
    { runScripts: 'outside-only' });
  const w = dom.window;
  w.MfgUi = {};
  w.eval(fs.readFileSync(path.join(WEB, 'shared', 'js', 'tooltip.js'), 'utf8'));
  const $ = (id) => w.document.getElementById(id);
  const over = (el, related) => el.dispatchEvent(new w.MouseEvent('mouseover', { bubbles: true, relatedTarget: related || null }));
  const out = (el, related) => el.dispatchEvent(new w.MouseEvent('mouseout', { bubbles: true, relatedTarget: related || null }));
  const tip = () => w.document.querySelector('.mfg-tip');

  over($('b'));
  assert.ok(!$('b').hasAttribute('title'), 'the browser has no title of its own to show');
  assert.ok(!tip() || tip().hidden, 'nothing yet: the pointer has only just arrived');
  await wait(250);
  assert.strictEqual(tip().textContent, 'Explains the button');
  assert.ok(!tip().hidden && tip().classList.contains('on'));

  out($('b'), $('out'));
  assert.ok(tip().hidden, 'it goes when the pointer leaves');
  assert.strictEqual($('b').getAttribute('title'), 'Explains the button', 'and the title is back on the element');

  over($('b'));
  out($('b'), $('out'));   // gone before the pause is up: no tooltip at all
  await wait(250);
  assert.ok(tip().hidden);

  over($('i'));
  assert.strictEqual($('i').getAttribute('aria-label'), 'Only a title', 'an icon with nothing but a title keeps its name');
  out($('i'), $('out'));
  assert.strictEqual($('i').getAttribute('title'), 'Only a title');
});
