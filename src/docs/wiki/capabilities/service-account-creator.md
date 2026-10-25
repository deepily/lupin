---
capability: service-account-creator
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.create_service_account.generate_api_key@6698d96841
  - scripts.create_service_account.get_or_create_service_account@06355e93ab
  - scripts.create_service_account.store_api_key@c5840056ec
  - scripts.create_service_account.write_key_to_file@e31a425027
  - scripts.create_service_account.main@8dd25f3a98
---
# Service account creator

Creates a service account user in the authentication database and generates a secure API key for programmatic access to the notification endpoints. It takes `--env`, an optional `--email` and an optional `--description`.

## Functions
- `generate_api_key` makes a key of the form `ck_live_` followed by 64 base64url characters, 72 in all, from the `secrets` module. It has 384 bits of entropy from 48 random bytes. The script's own docstring says 70 and 288, which is wrong.
- `get_or_create_service_account` returns the user id of the service account for an email, creating it with the `service_account` role if it does not exist. It raises `RuntimeError` if the user exists but is not a service account.
- `store_api_key` stores a bcrypt hash of the key, never the plaintext, sets the created time and enables the key. It returns the new record id.
- `write_key_to_file` writes the plaintext key to `notification-api-claude-code-<env>` under `src/conf/keys/`, creating the folder if needed. The file mode is 600, owner read and write only. `LUPIN_ROOT` must be set.
- `main` runs the whole flow and returns 0 on success and 1 on error.
