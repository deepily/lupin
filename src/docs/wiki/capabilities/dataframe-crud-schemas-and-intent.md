---
capability: dataframe-crud-schemas-and-intent
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.crud_for_dataframes.schemas.get_schema@4c2233901a
  - cosa.crud_for_dataframes.schemas.get_columns@6cb78d9d12
  - cosa.crud_for_dataframes.schemas.get_defaults@15918fe0c0
  - cosa.crud_for_dataframes.schemas.get_date_columns@d0b77c4499
  - cosa.crud_for_dataframes.schemas.get_time_columns@664a2c4104
  - cosa.crud_for_dataframes.schemas.get_datetime_columns@a0053355ca
  - cosa.crud_for_dataframes.schemas.get_dedup_keys@f61fa40124
  - cosa.crud_for_dataframes.schemas.validate_schema_type@e65640cf71
  - cosa.crud_for_dataframes.xml_models.CRUDIntent@6954a19b86
  - cosa.crud_for_dataframes.intent_extractor.build_claude_prompt@a6a3156d22
---
# DataFrame CRUD schemas and intent

The column definitions and the parsed intent behind [[dataframe-crud]]. Operations are in [[dataframe-crud-operations]].

## What it does
- Three schemas exist: `todo`, `calendar` and `generic`. All carry `id`, `list_name` and `created_at`. The todo adds `todo_item`, `due_date`, `priority`, `completed` and `tags`. The calendar adds `event` with date, time and recurrence columns, and the generic adds `name` and `value`.
- `get_schema` returns one schema's `columns` and `defaults`, and raises `ValueError` for an unknown type. `get_columns` lists names in definition order, and `get_defaults` returns a copy of the defaults.
- `get_date_columns`, `get_time_columns` and `get_datetime_columns` pick columns by dtype. `get_dedup_keys` returns the "same item" columns, or `[]` for a type with no key.
- `validate_schema_type` answers true or false and never raises.
- `CRUDIntent` holds twelve string fields, because the model answers in text. An empty XML tag becomes an empty string for every field but `operation`.
- `get_match_dict`, `get_fields_dict` and `get_filters_dict` parse the JSON fields. A blank, invalid or non-object value gives `{}`.
- `get_confidence_float` clamps to 0.0–1.0 and gives 0.0 on bad text. `get_limit_int` gives `None` for a blank, non-numeric or non-positive limit.
- `to_xml` uses `intent` as its root tag. `get_example_for_template` builds an intent made of bracketed placeholders.
- `build_claude_prompt` is what `extract_intent_via_claude_code` sends. It lists the nine operations, the three schema types, the user's lists and that placeholder block, and asks for the XML only.

## Don't
- Don't edit what `get_schema` returns. It is the stored schema itself, not a copy.
- Don't expect a bad JSON field to raise. A malformed `match_fields` reads as empty, so an update with no id then fails with "Provide item_id or match_fields".

## Invariants
- `VALID_OPERATIONS` has the nine operation names. `DESTRUCTIVE_OPERATIONS` is `delete`, `delete_list` and `update`.
- The placeholder intent parses back to the same field values, and its confidence reads as 0.0.
