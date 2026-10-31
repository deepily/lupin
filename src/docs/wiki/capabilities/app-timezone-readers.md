---
capability: app-timezone-readers
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.config.app_timezone.InvalidAppTimezoneError@07c4aa3130
  - cosa.config.app_timezone.get_zone_for_key@fb1b5bc0d1
  - cosa.config.app_timezone.get_app_timezone@03183a0b2c
  - cosa.config.app_timezone.get_arbiter_journal_timezone@ed535a1757
  - cosa.config.app_timezone.read_arbiter_journal_timezone@2890049c0e
  - cosa.config.app_timezone.get_decision_proxy_timezone@e3b9b8e3bd
  - cosa.config.app_timezone.read_decision_proxy_timezone@118c715055
---
# Time zone keys and their one reader

`cosa.config.app_timezone` is the only reader of the three INI keys that name a time zone. It has no default, and no caller may supply one. See [[configuration]].

## Keys
- The keys are `app timezone`, `arbiter journal local timezone` and `decision proxy timezone`.
- `get_zone_for_key( config_mgr, key )` reads a key with `get_required` and checks the value against `zoneinfo`. It returns the stripped name.
- It raises `MissingConfigKeyError` for an absent or blank key. It raises `InvalidAppTimezoneError` for a name `zoneinfo` does not know.

## Wrappers
- `get_app_timezone`, `get_arbiter_journal_timezone` and `get_decision_proxy_timezone` fix the key for a manager the caller holds.
- `read_arbiter_journal_timezone` and `read_decision_proxy_timezone` build the manager from `LUPIN_CONFIG_MGR_CLI_ARGS` first. They raise `ValueError` when no configuration is loaded.

## Don't
- Do not catch these errors to fall back to a zone. A missing zone is meant to stop the caller.
- `InvalidAppTimezoneError` is a `ValueError`, so an `except ValueError` also catches it.
