---
capability: agents-xml-models-field-validators
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.io_models.field_validators.none_to_empty@bec1f863aa
  - cosa.agents.io_models.field_validators.require_nonempty@5a4a3efda4
---
# Shared field checks for the xml_models files

`cosa.agents.io_models.field_validators` holds the two checks that the agents' response models repeat. xmltodict parses an empty tag such as `<reasoning></reasoning>` as None.
A pydantic str field rejects None.

## Rules
- `none_to_empty` turns None into an empty string. A field named in `keep_none`, such as a required `operation`, stays None.
- `require_nonempty` refuses None, empty and whitespace-only text with the caller's message. It returns the stripped text, or the text unchanged when `strip` is False.
- Each model keeps its own pydantic validator method, its own field list and its own message. The method body calls the helper.
- Nine files call the helpers: calculator, crud, prediction engine, notification proxy, quality judge, argument expeditor, DM compression, DM tutor and io_models.
- `ScriptMatcherResponse` keeps its own validator, because it also consults another field before it coerces a None answer.
