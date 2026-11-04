---
capability: agent-ini-config-loader
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.shared.config_loader.load_kwargs_from_ini@839c0330d0
  - cosa.agents.shared.config_loader.load_dataclass_from_ini@f1b8c67fc9
---
# Agent INI config loader

The one loop the expediter and swe-team config dataclasses share to read their fields from the INI file. The INI itself is in [[configuration]].

## What it does
- `load_kwargs_from_ini( cls, config_mgr, key_map, debug=False, label=None )` reads one INI value per mapped field and returns them as constructor keywords.
- The read type follows the field type: `boolean` for bool, `int` for int, `float` for float and `string` for anything else. A type written as a string such as `bool` counts too.
- A field missing from the INI takes its dataclass default. With `debug` it prints one line per field naming the INI key.
- `load_dataclass_from_ini` calls the same loop and returns `cls( **kwargs )`.

## Don't
- Don't map a name that is not a field of the class. It raises `KeyError`.

## Invariants
- Every mapped field must have a default, because the default is passed to the reader.
- `BugFixExpediterConfig`, `SweTeamConfig` and `TestFixExpediterConfig` use it.
