# Fusion Manage Item Management

## Rules for this repository

- Reuse before you build: read `dev/glossary.md` before writing any new feature. It lists what is already built, by what you need to do (search for an item, read a design, check a permission, show a form, and so on). Then read the matching note in `dev/` (see `dev/README.md`). If a row fits, call it; if it nearly fits, extend it; add a row for anything new in the same commit.
- Pickers and drop-downs: use the shared picker, `ns.picker` in `src/ui/web/shared/js/picker.js`. Never write another one. See `dev/pickers.md`.
- Run tests with `uv run python -m unittest discover -s tests -t .` (`python` is not on the path). `tests.test_paths` has a known error, a DataDirError.
- Strings: every key in `resources/languages/en.json` must be used, `t()` keys must be literal, and the `data-i18n` fallback text in HTML must equal the `en.json` value.
- Do not add fallback logic that guesses an answer's shape. Read the shape Fusion Manage really gives, and let errors surface.
