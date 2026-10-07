---
capability: configuration
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.config.configuration_manager.singleton@1206695711
  - cosa.config.configuration_manager.ConfigurationManager.__init__@06546422b1
  - cosa.config.configuration_manager.ConfigurationManager.init@a7dbb70162
  - cosa.config.configuration_manager.ConfigurationManager.get@4823b81d18
  - cosa.config.configuration_manager.ConfigurationManager.get_required@05c9dab6fc
  - cosa.config.cache_registry.register_invalidator@5a214bf5f2
  - cosa.config.cache_registry.invalidate_all@180d5fb949
  - cosa.rest.dependencies.config.get_config_manager@003624209d
---
# Configuration manager

`ConfigurationManager` reads one block of `src/conf/lupin-app.ini`. For the API key side see [[utils-config-secrets-and-vertex]].

## Building it
- `singleton` wraps the class, so the name is a function. The first construction wins and later arguments are ignored. `_reset_singleton=True` rebuilds it, and there is no lock.
- Callers pass `env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS"`. Its value is space-separated `name=value` tokens and must carry `config_path`, `splainer_path` and `config_block_id`. Text after a second `=` in a token is dropped.
- Both paths get the project root in front: `LUPIN_ROOT`, else a warning and `/var/lupin`. In `config_block_id`, `+` becomes a space, so `Lupin:+Development` is `Lupin: Development`.
- At construction only that token picks the block, and `LUPIN_ENV` does not. `/api/init` later switches it. The INI holds Production, Development, Testing, Testing-GCS and Baseline, plus a `default` block with one key.
- Passing no arguments, or both an env name and paths, raises `ValueError`. A missing INI file or block raises `AssertionError`.

## Overrides and defaults
- Extra tokens set keys through `set_config`, which writes memory only. Tokens split on spaces, so a key containing a space cannot be overridden. Most INI keys contain spaces.
- Values may hold `${VAR}`. `get` and `get_required` expand it on every read, and an unset variable stays literal.
- A block may `inherits` another block or an INI file. The `default` block is copied over every other block, replacing its values, though the docstring says it does not. Today `default` holds one key, so nothing shows.
- `init()` re-reads the file in place. It drops the token overrides and any `set_config` values.

## Reading
- `get( key, default, silent, return_type )` with a missing key and a default prints a banner unless `silent` or `mute_splainer`, then returns the converted default. With no default it prints a banner and returns `None`, whatever `silent` or `mute_splainer` say. A missing key never raises. A bad `return_type` raises `ValueError`, except for a missing key with no default, which returns `None` first.
- `get_required` raises `MissingConfigKeyError` for an absent key or a blank value.
- `return_type` is `boolean`, `float`, `int`, `string`, `list-string`, `json` or `dict`. `bool` raises `ValueError`. Boolean is true only for the text `true`, so `yes` and `1` read false. Any type starting `int` or `str` is accepted.
- The splainer text never loads in this mode. Its path gets the root prefix twice, so measured sections were 0 at `363de9427`.

## Cache invalidation and the app
- `register_invalidator` stores a named function and raises `ValueError` for an empty name, `TypeError` for a non-callable. `invalidate_all` runs each outside the lock, catches `BaseException` per function and returns the names that succeeded.
- Three register at import: `dm_length_thresholds`, `prediction_engine` and `scope_registry`. `snapshot_mgr` registers in the app's startup. Only the `/api/init` handler calls `invalidate_all`, right after `init()`.
- `get_config_manager` in `cosa.rest.dependencies.config` builds one manager lazily in a module global. The speech and voice persona routers define their own functions of that name.
