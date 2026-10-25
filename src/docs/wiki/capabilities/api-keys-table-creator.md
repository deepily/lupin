---
capability: api-keys-table-creator
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.create_api_keys_table.create_api_keys_table@1f71d7d883
  - scripts.create_api_keys_table.validate_schema@088a6c5c12
  - scripts.create_api_keys_table.main@c2f5b5e6be
---
# API keys table creator

Creates the `api_keys` table in the existing authentication database, for service-to-service authentication such as the Claude Code command line calling the Lupin server. This is initial table creation, not a migration.

## Functions
- `create_api_keys_table` creates the table with its full schema, seven fields and four indexes, plus the foreign key to the users table. It needs `LUPIN_ROOT` set and the users table present. It returns true on success and false on error.
- Only a missing database folder raises `RuntimeError`. Any error after that, a missing users table included, is printed and the function returns false.
- `validate_schema` verifies the table, the field count and the index count on an open connection. It returns a report holding success, the two counts and an error text.
- `main` runs both and returns 0 on success and 1 on error.
