---
capability: utils-admin-script-helpers
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.utils.admin_script_helpers.run_create_script@7de41643d5
  - cosa.utils.admin_script_helpers.validate_table@3ed9c85bf4
  - cosa.utils.admin_script_helpers.write_key_file@b738ee1324
---
# Admin script helpers

Three helpers shared by the one-off admin scripts under `src/scripts`. The table-creation and service-account scripts use them instead of repeating the same code.

## What it does
- `run_create_script( title, subtitle, success_label, create_fn )` prints a banner, calls `create_fn` and prints a success or failure banner. It returns 0 when `create_fn` returns true and 1 otherwise.
- When `create_fn` raises, it prints the error and a traceback to stderr and returns 1.
- `validate_table( conn, table, expected_fields, expected_indexes )` checks a SQLite table. It returns a dict with `success` and the field and index counts.
- A missing table, a wrong count or a failed query gives `success` false with an `error` text.
- `write_key_file( project_root, api_key, env )` writes the key and a newline to `src/conf/keys/notification-api-claude-code-<env>`. It returns the file path.

## Don't
- Don't pass a table name from user input to `validate_table`. The name goes into a `PRAGMA` call, which cannot bind it.

## Invariants
- The automatic primary-key index is not counted by `validate_table`.
- The key file is replaced whole and gets mode 600. The key folder is created when missing.
- Each script keeps its own public function names and passes its own banner text.
