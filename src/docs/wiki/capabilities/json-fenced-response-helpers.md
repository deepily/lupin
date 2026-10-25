---
capability: json-fenced-response-helpers
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.io_models.utils.json_object_recovery.strip_json_fence@708dde0a0c
  - cosa.agents.io_models.utils.json_object_recovery.parse_fenced_json@b246377d6b
  - cosa.agents.io_models.utils.json_object_recovery.extract_json_metadata@1cb77a3c14
---
# Fenced JSON response helpers

Three plain helpers for a model reply that holds one JSON document inside a code fence. The chatty-reply recovery is `recover_json_object`, in [[xml-io-models]].

## What it does
- `strip_json_fence( text, single_leading=False )` removes one leading `json` fence marker and one trailing marker, then strips whitespace. Text without a fence comes back stripped.
- With `single_leading` false, a `json` marker followed directly by a bare marker loses both. With it true, only the `json` marker goes.
- `parse_fenced_json( text, label )` strips the fence and calls `json.loads`. A failure raises `ValueError` that starts `Could not parse <label> response as JSON`.
- `extract_json_metadata( text, defaults )` returns each key of `defaults` from the parsed object, with its default when the key is absent. It returns `{}` when the text is not JSON.

## Don't
- Don't use `strip_json_fence` to drop prose after the closing fence. It does not. `recover_json_object` does.

## Invariants
- `strip_json_fence` never raises.
- `extract_json_metadata` raises `AttributeError` when the JSON is valid but is not an object.
