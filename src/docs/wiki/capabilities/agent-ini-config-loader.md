---
capability: agent-ini-config-loader
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.shared.config_loader.load_kwargs_from_ini@9abdcb142b
  - cosa.agents.shared.config_loader.load_dataclass_from_ini@d57cdf477c
---
# Agent INI config loader

The one loop the expediter, swe-team and deep research config dataclasses share to read their fields from the INI file. The INI itself is in [[configuration]].

## What it does
- `load_kwargs_from_ini( cls, config_mgr, key_map, debug=False, label=None, silent=False )` reads one INI value per mapped field and returns them as constructor keywords.
- The read type follows the field type: `boolean` for bool, `int` for int, `float` for float and `string` for anything else. A type written as a string such as `bool` counts too.
- A field missing from the INI takes its dataclass default. With `debug` it prints one line per field naming the INI key.
- With `silent=True` every read passes `silent=True`, so the manager prints no banner for a key the INI lacks. With `silent=False` the argument is left out.
- `load_dataclass_from_ini` calls the same loop and returns `cls( **kwargs )`.

## Don't
- Don't map a name that is not a field of the class. It raises `KeyError`.

## Invariants
- Every mapped field must have a default, because the default is passed to the reader.
- `BugFixExpediterConfig`, `SweTeamConfig` and `TestFixExpediterConfig` use it.
- `ResearchConfig` reads through `load_kwargs_from_ini` with `silent=True`, then turns a blank `audience_context` into `None` and prints its own one debug line.
