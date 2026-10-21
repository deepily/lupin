---
capability: dataframe-crud-operations
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.crud_for_dataframes.calendar_crud_agent.CalendarCrudAgent@294f366013
  - cosa.crud_for_dataframes.agent.smoke_check_schema_agent@045f6df4d8
  - cosa.crud_for_dataframes.crud_operations.create_list@3e206733df
  - cosa.crud_for_dataframes.crud_operations.delete_list@ef702b377a
  - cosa.crud_for_dataframes.crud_operations.list_lists@b898a9146e
  - cosa.crud_for_dataframes.crud_operations.update_item@35487ff1f7
  - cosa.crud_for_dataframes.crud_operations.mark_done@5d51469825
  - cosa.crud_for_dataframes.crud_operations.query_items@4abf20dd94
  - cosa.crud_for_dataframes.crud_operations.get_schema_info@0466fee799
  - cosa.crud_for_dataframes.dispatcher.format_result_for_voice@e8be676ea0
---
# DataFrame CRUD operations

The list, query and voice-answer functions behind [[dataframe-crud]]. Each takes a `DataFrameStorage` and returns a status dict. Schemas and intent parsing are in [[dataframe-crud-schemas-and-intent]].

## What it does
- `create_list` checks the name and schema type, then writes an empty file if none exists. A list exists only while an item carries its name, so nothing is stored for it. A name already in use returns `exists`.
- `delete_list` removes every row with that list name and returns `deleted_count`. `list_lists` returns each list with its row count, for one schema type or for all.
- `update_item` changes every row that matches the id or the `match_fields`. Values are compared as text. A column the table lacks is skipped without an error.
- `mark_done` is `update_item` with `completed` set to `yes`, under the same id or `match_fields` rules.
- `query_items` filters by list name, then by exact text match on each filter column. It then sorts by one column with missing values last and applies `limit`. `total_count` is taken before the limit. A filter column the table lacks is skipped.
- `get_schema_info` returns each column's name, dtype and default, with `(required)` where there is none.
- `format_result_for_voice` picks a sentence by operation and status. A pair it does not know falls back to the message. A query reads at most five items, then `...and N more.`
- `CalendarCrudAgent` is `CrudForDataFramesAgent` with the class constant `DEFAULT_SCHEMA_TYPE` set to `calendar`. The base `__init__` copies it to `default_schema_type`. Its default routing command is the base agent's.
- `smoke_check_schema_agent( agent_cls, schema_type )` is the smoke check both domain agents share. It confirms the constant and the base class, prints the result and returns `True` or `False`. A failure prints a traceback and is returned, never raised. It does not run the constructor, which needs config and an LLM.

## Don't
- Don't expect `delete_list` to check the schema type. `DataFrameStorage` raises `ValueError` for an unknown one.
- Don't read `normal priority` in a spoken query as an error. A todo defaults to priority `normal`, and the summary leaves out only `medium`.
- Don't count on `updated_count` meaning a change. It counts matched rows, even when every update was skipped.

## Invariants
- `query_items` returns every value as text and a missing value as an empty string, so the result is JSON-safe.
- An unknown schema type gives status `error` from `create_list`, `list_lists`, `query_items` and `get_schema_info`.
- An empty table gives `not_found` from `delete_list` and `update_item`, and an empty `items` list from `query_items`.
