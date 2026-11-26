# Architecture and code standards

A developer must be able to open any module and understand its purpose at once. This note sets the layers, the rules between them, and the guardrails for functions. The guardrails are not absolute laws: a function that breaks one needs a written reason in a comment, not necessarily a rewrite.

## Layers

```
                  UI layer
       Application (orchestration) layer
        Domain layer  |  Integration layer
```

| Layer | Holds | Python | JavaScript |
| --- | --- | --- | --- |
| UI | What the user sees and does: pages, panels, dialogs, DOM, event wiring, text shown | `ui/` (palette and dialog classes) | `ui/web/**/js/` rendering and event code |
| Application | Sequences a use case: which reads, in which order, and what to do with the answers. Owns background work, cancellation and progress | `ui/actions/`, `publish/` run and section loading | the page controllers |
| Domain | Business rules: what a BOM line is, what a plan moves, how two items compare. Pure, with no network, no Fusion and no DOM | `core/` (shapes, units, backoff), `publish/` pure builders, `sync/` compare | `mbom-structure.js`, `mbom-plan.js` |
| Integration | Talks to the outside: Fusion Manage REST, the Manufacturing Data Model, files, OAuth, the logger | `fm/`, `fusion_mfg/`, `auth/`, `config/` storage | `shared/js/bridge.js` |

### The rules

1. The UI holds no business rules. It asks a question and shows the answer.
2. Domain code never knows about the DOM, Fusion's UI, HTTP or the file system.
3. Integration code never decides how the UI behaves. It returns data or raises an error, and the application layer decides what the user sees.
4. A layer calls only the layer at its own level or below. Nothing calls up.
5. Modules talk through a small, named interface: a function or class with a docstring or header comment that says what it takes and gives back. No reaching into another module's private names.
6. Every module opens with a one-paragraph comment: what it is for and which layer it belongs to.

`mbom-structure.js` and `mbom-plan.js` are the model: structure and plan are pure data code, the viewer renders. Keep that split and copy it.

## Function guardrails

| Measure | Ideal | Limit |
| --- | --- | --- |
| Length | 10 to 40 lines | 80 lines, exceptions justified |
| Cyclomatic complexity | | 10 or less |
| Nesting | | 3 levels |
| Parameters | 4 or fewer | pass a named object for more |
| Unused variables | zero | zero |
| Unhandled promises | zero | zero |

Also: a name says what the function does, as a verb phrase. Prefer plain, straightforward code to a clever one-liner. Do not add fallback logic that guesses the shape of an answer (see CLAUDE.md).

## Measuring

`uv run python tools/measure_code.py` lists every Python function that breaks a guardrail (`--json` for the factory). `npm install` once, then `node tools/measure_js.mjs` does the same for the JavaScript under `src/ui/web` (it skips the function that wraps a whole file, and needs acorn, the only dev dependency). Both exit 1 while a function breaks a guardrail. The JavaScript tests run inside the Python suite (`tests/test_panel_js.py`).

## The factory

`.claude/agents/` holds the roles: `arch-developer` changes one module, `arch-reviewer` checks it and has no edit tools. The orchestrator takes one module at a time, in this order: measure, plan, develop, review, test, repeat on rejection (at most 2 rounds), then hand the diff to the user. Behaviour must not change: the full test suite must pass before and after each module, and no user-visible text or `en.json` key may change without a reason.
