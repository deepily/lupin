---
capability: notification-text-helpers
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.utils.notification_utils.convert_open_ended_batch_for_api@926b8d101c
  - cosa.utils.notification_utils.convert_questions_for_api@8418f0b509
  - cosa.utils.notification_utils.extract_qualifier_comment@96264bade5
  - cosa.utils.notification_utils.format_open_ended_batch_for_tts@4706f7082d
  - cosa.utils.notification_utils.format_qualified_response@41d1ccc3ea
  - cosa.utils.notification_utils.format_questions_for_tts@79377e5e82
  - cosa.utils.notification_utils.is_known_project@30e16c65d8
  - cosa.utils.notification_utils.normalize_abstract@8a292f15ee
  - cosa.utils.notification_utils.parse_field_selections@f45f1e54b8
---
# Notification text helpers

`cosa.utils.notification_utils` shapes question and answer text for voice and the api.

## What it does
- `is_known_project( name )` checks the values of `KNOWN_PROJECTS`. `normalize_abstract( text )` turns a literal backslash-n into a newline and passes None through.
- `format_questions_for_tts` returns question text only, with a `Question N of M:` prefix for several and a multi-select hint. `convert_questions_for_api` renames `multiSelect` to `multi_select`.
- `format_open_ended_batch_for_tts` speaks one question, or `I have N questions for you.`, or an empty string for none.
- `convert_open_ended_batch_for_api` adds `input_type: "text"` and keeps `default_value` when present.
- `extract_qualifier_comment( value )` splits `yes [comment: ...]` into `( answer, comment )`. `format_qualified_response( answer, comment )` builds the instruction text sent back to Claude.
- `parse_field_selections( value )` reads a multiple-choice or batch answer as one record per header. A record holds the select mode, the picks and the text as submitted. A yes, no or neither string also gives the stance. It reads an answers map given as a JSON string or a dict, or held as a string under `value`. Anything else gives `None`.

## Don't
- Do not pass an answer other than yes, no or neither to `format_qualified_response`. Anything but `neither` gets the yes/no wording.

## Invariants
- `extract_qualifier_comment` returns `( None, None )` for a string it does not recognise. It never reads a string as the stance its first letters spell.
