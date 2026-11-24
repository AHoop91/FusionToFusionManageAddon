# Validation: validators and refusals

Two ways a wrong value is caught. The browser checks the validators Fusion Manage puts on a field before anything is sent (`shared/js/validators.js`). Fusion Manage refuses what is still wrong, and the add-in reads the refusal and shows it beside the field it names (`refusal.py`). Both end in the same place on the form: a message under a field, and a message for the whole form.

Each shape named here is marked as seen in a real answer or assumed in "The refusal Fusion Manage sends" below.

## What Fusion Manage said: `src/fm/refusal.py`

`FmApiError` (`src/fm/client.py`) carries `status` and `body`, the start of what Fusion Manage answered (`ERROR_BODY_BYTES`, 8000). `read_refusal(exc, known, general)` turns it into something the form can show:

| Step | Rule |
| --- | --- |
| Read | `exc.body` is parsed as JSON. With no body, no JSON, or no message in it, `exc` itself is returned unchanged. |
| Find messages | `_walk` visits every object in the answer, to a depth of `MAX_DEPTH` (6), and takes each string `message` in it. |
| Tie to a field | A message belongs to a field when another value in the same object is a known field id, or a link ending in `/fields/<id>` (`_field_named`). Else when the message text contains a known id as a whole word, the longest id winning (`_field_in`), so `PLANNED_DATE_10` is not taken for `PLANNED_DATE_1`. |
| Result | An `FmRefused` whose `fields` is `{field id: first message for it}` and whose text is the messages tied to no field, joined by a space, else `general`. Its `status` is the original status. |

`known` is the set of field ids of the form, and `general` is what to say for the whole form when the refusal names only fields.

## How it reaches the page

1. `ProductService.create` and `update` (`src/publish/products.py`) catch the `FmApiError` and raise `read_refusal(exc, set(sections), t("app.product_refused"))`, where `sections` is `SectionService.field_sections(workspace)`, so `known` is every field the workspace has.
2. `PickerReads._finish` (`src/ui/actions/search_actions.py`) puts the exception's text in the answer's `message`, and its `fields` (when the exception has them) in the answer's `fields`.
3. A plain `FmApiError` with status 400 and no `fields` is shown as `app.bad_search` ("Fusion Manage did not accept this search"). Any write that can be refused with a 400 must therefore raise `FmRefused`, or change the status, or the person is told it was a bad search.
4. In the page, `refused(answer)` in `products-page.js` shows `answer.message` in the alert above the form (`formError`), puts `answer.fields[id]` under each field of that id, marks it invalid, and moves to the first one (`goTo`). A field with no control on the form (an `auto` or `info` field) has no place to show a message, so only the form-wide text carries it.

Variant rows (the Grid tab) use a different path. `ProductService._send_row` catches the refusal and `_refused` builds `FmApiError(t("app.product_variant_refused", reason=...))`, where `reason` is `read_refusal(exc, set(), "")` as text (with no known ids, every message is form-wide). The status is changed from 400 to 422 (`UNPROCESSABLE`) so step 3 does not call it a bad search. The page shows it with `showError`.

## What the real answers say

The only refusal in the add-in log is of a Grid row, not of an item. It is not a shape `read_refusal` ties to a field:

- The message is `"{0} is required."`, with the field's title in `arguments` (`["Title"]`). Nothing in the code fills the `{0}`.
- `field` is an object (`{"value": null, "isSystemField": false}`) with no id, and `_field_named` only looks at string values.
- The top-level `message` is `"HTTP 400 Bad Request"`, which is taken as a form-wide message too.

So for that answer the person reads `HTTP 400 Bad Request {0} is required.` with nothing marked on a field. The tests (`tests/test_refusal.py`) use refusals shaped `{"message", "errors": [{"field": "TITLE", "message"}]}`, which are assumed. Do not build on the field tie-in for a real refusal until an item refusal has been seen; if you do see one, add its shape to "The refusal Fusion Manage sends" and extend `_walk` (for example to use `arguments`) with a test.

## What the browser checks: `src/ui/web/shared/js/validators.js`

`ns.validators.check(field, value, lookup)` answers the first problem with a value as words, or `''`. `field` is `{title, required, validators}`, `value` is what the form would send, and `lookup(id)` gives `{title, value}` of another field on the form, or null. A check that names a field that is not on the form is skipped, and a validator the browser does not know is left to Fusion Manage.

Rules the Python side applies before the field reaches the browser (`workspace_form.py`):

| Rule | Where |
| --- | --- |
| Required: the field's `fieldValidators` hold a validator named `required` (any case). The field's own `required` key is not read. | `_required` gives `required`; `check` then reports `products.required_field` for a blank value |
| Blank means `''`, null, undefined, `false` (an unticked box) or an empty list | `blank` |
| Maximum length: the smaller positive of the `maxlength` validator and `fieldLength`, for `text` and `textarea` only | `_max_length` gives `max_length`; the control stops at it (`counted`) |
| `required` and `maxlength` are removed from `validators` | `_validators` |

Checked in the browser (`checks`). Each is skipped for a blank value unless its description says otherwise:

| Validator | Fails when | Variables |
| --- | --- | --- |
| `minlength` | The text is shorter than `minlength` | `minlength` |
| `maxlength` | The text is longer than `maxlength`. Never reached for a field from `workspace_form.py`, which removes it. | `maxlength` |
| `integer`, `long` | The text is not a whole number | none |
| `float` | The text is not a number | none |
| `floatRange` | The number is outside `min` and `max` (either may be empty) | `min`, `max` |
| `email` | The text is not shaped `a@b.c` | none |
| `mask` | The text does not match the pattern (`RegExp.test`, not anchored by the code). A mask that is not a pattern is left to Fusion Manage. | `mask` |
| `csvMask` | A comma separated part does not match the pattern | `mask` |
| `dateNotBefore` | The date is earlier than a filled date in one of the named fields (dates compare as `YYYY-MM-DD` text) | `otherDateFields`, comma separated |
| `bothOrNone` | Only one of this field and the other is filled | `secondProperty` |
| `ifOneThanOther` | This field is filled and the other is blank | `secondProperty` |
| `conditionallyRequired` | This field is blank and the other's text equals `constrainingValue` | `secondProperty`, `constrainingValue` |
| `oneOrTheOtherNotBoth` | Both blank or both filled | `secondProperty` |
| `identical` | This field is filled and its text differs from the other's | `secondProperty` |

Left to Fusion Manage: every other validator name. The header of `validators.js` names a value that must be unique, a credit card number, a list of values of a set length, and the number of decimals. One real name that is not checked is `date`, seen on a Grid column. A link or list value (a picklist or link field) has no text, so the text checks pass it.

Each message is an i18n key (`products.v_*`, `products.required_field`). A new check needs its key in `resources/languages/en.json` and a literal `t()` call.

## How the form shows an error

| Where | What shows | When |
| --- | --- | --- |
| Under the field (`error` paragraph, `pf-error`, role alert) and the `invalid` class on the field | `showState(record)`: the message of `check` | A non-empty field loses focus; an invalid field changes; every field on Save; or `refused` with Fusion Manage's text |
| The alert above the form (`products-form-error`, `formError`) | `products.fix_fields` when Save finds a problem; else Fusion Manage's form-wide text | Save, or a refusal |
| The footer | The count of what is open, from `readiness()`, and the checklist behind it | Live, on every input, debounced |
| The wizard Details step | Each column's message under the column; Next stays disabled until every column passes | `syncAssign` |

An empty required field is not marked until the person has left it or pressed Save, so a form is not red when it opens (`watchFocus`).

## The refusal Fusion Manage sends

**Seen** means the key is in a real answer written to the add-in log (`%LOCALAPPDATA%\MfgToFm\logs\MfgToFm.log` and its `.1`, `.2` and `.3` rotations, read on 2026-11-17, workspace 343 "Products" and workspace 57). **Assumed** means the code or a test relies on it but no logged answer shows it; treat it as a guess until it is seen. Do not add a key you have not seen. Where the code accepts an answer as a list or as an object holding the list, it goes through `rows_in(data, key)` (`src/core/shapes.py`).

What Fusion Manage answered to a write it did not accept, as `FmApiError.body` holds it. Two shapes are in the log, both for a `POST` of a Grid row, both with status 400.

A validation refusal (seen once per rejected attempt, pretty-printed):

| Key | Value seen | Status |
| --- | --- | --- |
| `statusCode` | `400` | Seen; not read |
| `errors[].message` | `"{0} is required."` (the `{0}` is not filled in) | Seen; read by `read_refusal` |
| `errors[].code` | `"errors.required"` | Seen; not read |
| `errors[].arguments` | `["Title"]` (the field's title, not its id) | Seen; not read |
| `errors[].field` | `{"value": null, "isSystemField": false}`: an object with no id | Seen; not read |
| `message` (top level) | `"HTTP 400 Bad Request"` | Seen; read as a form-wide message |

A schema refusal:

| Key | Value seen |
| --- | --- |
| `errorCode` | `"GEN_INVALID_INPUT_SCHEMA"` |
| `message` | `"Incorrect payload"` |
| `params`, `url` | `null` |
| `errorClass` | `"APIError"` |

How `read_refusal` treats these, and what that means for ties to a field, is in the sections above. The shapes with `errors[].field` as a string id, or an entry with a field link, are what `tests/test_refusal.py` assumes; they are not in the log. No refusal of an item write (`POST` to `/items`) is in the log.

### Lessons

| Lesson | Evidence |
| --- | --- |
| A 400 that is a refusal of a payload must not reach the panel as a plain 400, or the person reads "did not accept this search". `_refused` changes the status to 422. | The code and `tests/test_products.py` (`test_a_refusal_of_a_row_is_said_in_words_and_not_sent_again`) |

## Reusing it

To check a value in a new place, call `ns.validators.check` with a spec from `parse_form` or `grid_form`; do not write another check. To show a refusal beside fields, raise `read_refusal(exc, known_ids, general)` where the write happens and render `answer.fields` the way `refused` does. For example, a new write that sends `{field id: value}` for a workspace:

```python
try:
    client.send_json("POST", url, body)
except FmApiError as exc:
    raise read_refusal(exc, set(field_ids), t("app.my_refused")) from exc
```

The page then reads `answer.message` and `answer.fields` from the status poll.
