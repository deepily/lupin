---
capability: api-key-and-account-scripts
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.create_admin_test_account.main@9286cd2357
  - scripts.create_service_account_postgres.generate_api_key@6698d96841
  - scripts.create_service_account_postgres.get_or_create_service_account@90bdda1bfc
  - scripts.create_service_account_postgres.store_api_key@6f914d69d9
  - scripts.create_service_account_postgres.write_key_to_file@e31a425027
  - scripts.create_service_account_postgres.main@069ce25eb5
  - scripts.mint-model-server-api-key.generate_model_server_key@0ca34068df
  - scripts.mint-model-server-api-key.key_fingerprint@3696f73f22
  - scripts.mint-model-server-api-key.key_file_path@a4121a23b9
  - scripts.mint-model-server-api-key.write_key@741a766fbb
  - scripts.mint-model-server-api-key.main@884ebd664a
  - scripts.reset_user_password.reset_password@e148a49211
---
# Service account, API key and password scripts
One-off scripts under `src/scripts/` that create accounts and keys. Each writes secrets, so run them on the owner's word.
- `generate_api_key` makes a `ck_live_` key of 70 characters from a secure random source. `get_or_create_service_account` finds or creates the service user in Postgres.
- `store_api_key` stores the key's hash in the database. `write_key_to_file` writes the plaintext key to an environment-specific file under `src/conf/keys`.
- `generate_model_server_key` makes a model-server key. That server has no database, so nothing is inserted.
- `key_fingerprint` gives a stable one-way identifier for a key. The server computes it the same way.
- `key_file_path` is the destination, `src/conf/keys/model-server-api`. `write_key` writes it at mode 600 and refuses to overwrite unless forced.
- `main` in `create_admin_test_account` creates or promotes the dedicated admin test account named by the environment.
- `reset_password` resets one user's password, to a given one or the original.
