---
capability: dataframe-crud
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.crud_for_dataframes.agent.CrudForDataFramesAgent@16f724f251
  - cosa.crud_for_dataframes.agent.CrudForDataFramesAgent.run_code@c773563ecc
  - cosa.crud_for_dataframes.xml_models.CRUDIntent.needs_confirmation@0e8aa96e45
  - cosa.crud_for_dataframes.dispatcher.dispatch@12402b9dc5
  - cosa.crud_for_dataframes.dispatcher.extract_intent_xml@279881dcd7
  - cosa.crud_for_dataframes.storage.DataFrameStorage@e38d1458ce
  - cosa.crud_for_dataframes.crud_operations.add_item@ed511dc774
  - cosa.crud_for_dataframes.crud_operations.delete_item@5435f06c26
  - cosa.crud_for_dataframes.intent_extractor.extract_intent_via_claude_code@b0f3ed7284
  - cosa.crud_for_dataframes.todo_crud_agent.TodoCrudAgent@664396cb1d
---
# DataFrame CRUD

A voice request such as "add milk to my groceries list" becomes a stored change to a per-user parquet table. `CrudForDataFramesAgent` is the entry point, and `TodoCrudAgent` and `CalendarCrudAgent` subclass it.

## What it does
- `run_prompt` asks the configured LLM for an `<intent>` block. `extract_intent_xml` cuts it out of the reply and `CRUDIntent.from_xml` parses it.
- `run_code` generates no code. It passes the `CRUDIntent` to `dispatch`, which calls one `crud_operations` function by operation name.
- The nine operations are `add`, `delete`, `update`, `query`, `mark_done`, `create_list`, `delete_list`, `list_lists` and `get_schema_info`.
- `DataFrameStorage` keeps one file per user and schema at `<base>/<user_email>/<schema_type>.parquet`. The base comes from `crud for dataframes output path`.
- The schema types are `todo`, `calendar` and `generic`. `schemas.py` holds their columns, defaults and dedup keys.
- `run_formatter` builds the spoken answer with `format_result_for_voice`, with no second LLM call.

## Don't
- Don't match on `id`, `list_name` or `created_at` in `match_fields`. They are infrastructure columns and the match is refused.
- Don't assume `update_item` guards against many matches. Only `delete_item` refuses a `match_fields` delete that hits more than one row.
- Don't skip the confirmation for `delete`, `delete_list` or `update`. `needs_confirmation` is true for those exact lowercase names whatever the model says. `dispatch` lowercases and strips the operation, but `is_destructive` does not. So `Delete` runs unconfirmed unless the model also set `requires_confirmation` to true. It is tracked on bug row 1143336c-f840-4cfe-aeb9-246c3695e99b.

## Invariants
- A confirmation asks by voice with a 30 second wait. Denial, timeout or error all mean no. A job traced to a test suite takes no without asking.
- If `dispatch` raises or returns status `error`, `run_code` asks `claude -p` for the intent again, with a 30 second limit, and dispatches that. When both fail it raises `CodeGenerationFailedException`.
- `add_item` returns status `duplicate` when the schema's dedup key matches an item in the same list. The keys are `todo_item`, `event` with `start_date`, and `name`.
- `update_item` never changes `id` or `created_at`. `DataFrameStorage` raises `ValueError` for a blank email or an unknown schema type.
- Date and datetime columns are converted to native types on save. Time columns stay as strings.
