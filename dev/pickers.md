# Pickers and drop-downs

Every page of the add-in uses one picker: `ns.picker` in `src/ui/web/shared/js/picker.js`, styled by `src/ui/web/shared/css/picker.css` (classes `pk-*`). Do not build another drop-down, combo box, searchable list or chip box. If the picker cannot do what a page needs, extend the picker.

A native `<select>` is not used because its popup was slow to open in Fusion's embedded browser.

## What it gives you

- A button that opens a list laid out in the window, so a scrolling card does not cut it off. The list opens up or down, whichever has room.
- Arrow keys, Enter, Space and Escape, with ARIA listbox roles.
- A search box (at the top of the list, or typed into the field itself with `inlineSearch`, as the form controls do), a clear entry, greyed-out taken items, and groups with headings.
- A single value, or several values shown as chips (`multi`).
- Items the page holds, or items read from somewhere else in batches.

## Loading it

A page needs `shared/css/picker.css` after `components.css`, and `shared/js/picker.js` after `auth.js` and before its own scripts. Settings, Products and Publish already do.

## Calling it

`ns.picker.make(cfg, selected)` returns a wrapper element. It fires a `pick` event when the choice changes. The wrapper has `refresh()`, `rebuildOpen()`, `setPicked([{value, label}])` and `getPicked()`.

Items come from one of two places in `cfg`:

| Config | Use it for |
| --- | --- |
| `groups(current, wrap)` returns `[{title, items: [{value, label, detail}]}]` | A list the page already holds. The search box filters it. |
| `source(text, offset, done)` | A long list read elsewhere. It is asked as the search box changes and as the list is scrolled. Call `done({items, next, total})` or `done({error})`. |

Labels are never built into the picker. Pass `placeholder`, `search`, `empty(wrap)`, `label(value)` and `text` (`clear`, `taken`, `loading`, `showing`) from the caller, so each page keeps its own strings and the shared code has no `settings.*`, `products.*` or `publish.*` keys.

Other options: `multi`, `required` (no clear entry), `searchFrom` (show the search box from this many items on), `takenValues(wrap)`, `alignRight`, `onOpen(wrap)`, `valueClass` (a hidden input carries the value), `className` and `buttonClass` (for a page's own look), `tip()` and `ariaLabel`. The full list is in the header comment of `picker.js`.

A row can carry small buttons of its own: give an item `actions`, a list of `{label, icon, className, run(item)}` (`icon` is a list of svg paths). They show when the row is pointed at or has the arrow keys, the arrow keys step through them too, and pressing one closes the list and runs `run`. `footer(wrap)` adds an entry after the items that is an action rather than a choice (`{label, icon, run}`, or null for none).

## Where it is used

| Caller | Kind |
| --- | --- |
| `settings/js/workspaces.js`, `settings/js/make-or-buy.js`, `settings/js/language.js` | Grouped static lists, taken items, clear entry |
| `products/js/filters.js` (`dropdown`) | Short required or clearable list |
| `shared/js/form-controls.js` (`linkPicker`) | `source` with batches, single or `multi` |
| `shared/js/form-controls.js` (`selectPicker`) | Fixed choices of a form field, clear entry, search from 8 items |
| `products/js/products-page.js` (`makeViewPicker`) | The view of the list: required, `actions` on each view (rename, delete), a `footer` to create one (the dialogs are `product-views.js`) |
| `item/js/bom.js` | The BOM view of the item: required, no search |
| `publish/js/add-items.js` (`versionPicker`, `combo`) | Required static list, and `source` with a round clear button |

Copy the nearest caller when you add a new one.

## What is not a picker

`settings/js/hub-picker.js` browses hub folders and files in a dialog. It is not a drop-down and stays separate.

The action menus (the Actions menu of the Products list, the item actions, the account menu) run commands and hold no choice, so they are not pickers.

## Rules for changes

- Style a page's picker with a small skin on `className` or `buttonClass`, not with new menu markup.
- Do not add a second open-menu, outside-click or position routine to a page.
- If you add a behavior to the picker, add it for every caller or behind a config option.
