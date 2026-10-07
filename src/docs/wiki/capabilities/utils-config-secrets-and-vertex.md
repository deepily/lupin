---
capability: utils-config-secrets-and-vertex
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.utils.config_loader.get_api_config@f203b10f56
  - cosa.utils.config_loader.load_api_key@fa98e2e3d1
  - cosa.utils.config_loader.validate_api_config@552b32fecc
  - cosa.utils.secret_redaction.credential_env_values@a67b47cde8
  - cosa.utils.secret_redaction.redact_text@8ac443f634
  - cosa.utils.secret_redaction.redact_report@c7181a52b2
  - cosa.utils.vertex_spend_ceiling.binding_daily_usd@2e48f049b0
  - cosa.utils.vertex_spend_ceiling.clamp_tpm_for_daily_budget@547ff5492e
---
# Config loader, secret redaction and Vertex spend ceiling

Three helpers in `cosa.utils`. The first two are widely used. The third has no caller outside its tests.

## API config loader
- `get_api_config( env )` returns the API url and key-file path. The environment branch runs only when `LUPIN_API_KEY_FILE` or `LUPIN_API_KEY` is set, and `LUPIN_API_URL` or `LUPIN_API_KEY` is set. A lone url or a lone key file falls through to `~/.lupin/config`.
- On the environment branch the `env` argument is ignored and nothing is validated. The url defaults to `http://localhost:7999`, and the key file becomes the placeholder `__direct__` when only a key is set. `LUPIN_DEV_EMAIL` is read on this branch only.
- The file branch reads `~/.lupin/config`, which must have an `[environments]` section or `ValueError` follows. The block is the `env` argument, else `LUPIN_ENV`, else that section's `default` key, else `local`. A missing file raises `FileNotFoundError`; a missing block or key raises `ValueError`.
- Direct callers pass `LUPIN_ENV` with `local` as the default. The arbiter passes its INI key `arbiter live notify config env`, shipped as `development`. That file is user-local, and no shipped INI has an `[environments]` section.
- `load_api_key( file )` returns `LUPIN_API_KEY` when it matches `ck_live_` plus 64 or more characters. A malformed one is silently ignored and the file is read. With `__direct__` that read fails as "file not found".
- `validate_api_config` ignores `LUPIN_API_KEY` and rejects `__direct__`. Its only caller outside tests is `scripts/lupin_config.py`.

## Secret redaction
- `redact_report` scrubs pytest reports. Only two hooks in `src/conftest.py` call it: every run report, and failed collection reports.
- `credential_env_values` keeps environment values of 6 or more characters whose variable name contains a credential word, such as password, secret, token or api key. The match is a substring, and the longest values come first.
- `redact_text` replaces those values wherever they appear. It then masks quoted values assigned to a key that holds a credential word. Unquoted values and empty quotes are left alone.
- A function argument named like a credential has its whole value replaced, whatever it holds. The report's locals, crash message, chained exceptions and captured sections are all walked.
- The module catches nothing itself. The run-report hook catches a failure, prints a warning and leaves the report unredacted. The collection hook has no guard, so a failure there propagates.

## Vertex spend ceiling
- Pure arithmetic over a `ModelPrice`. Claude Opus 4.8 is priced at 5 dollars in and 25 out per million tokens, marked in its note as the best estimate. The two MaaS models are unpriced.
- `clamp_tpm_for_daily_budget` turns a daily dollar budget into tokens per minute, using the output price only and rounding down. An unpriced model raises `UnpricedModelError` before any other check.
- `binding_daily_usd` returns the lower of the daily budget and the monthly budget over 31 days. No caller outside tests passes a different month length.
- It calls no quota API and no code reads it, so it clamps nothing by itself.
