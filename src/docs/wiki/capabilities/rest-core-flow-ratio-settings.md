---
capability: rest-core-flow-ratio-settings
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.flow_ratio_settings.override_path@7408f4df33
  - cosa.rest.flow_ratio_settings.get_window_hours@9a72604fae
  - cosa.rest.flow_ratio_settings.get_allow_below@8ab5c1f391
  - cosa.rest.flow_ratio_settings.get_enforcement_active@74f3e59fae
  - cosa.rest.flow_ratio_settings.set_overrides@4bcbd8dc1e
  - cosa.rest.flow_ratio_settings.clear_overrides@1087dde9bd
  - cosa.rest.flow_ratio_settings.current_settings@d9aafa7dc2
---
# Flow-ratio settings

The window, threshold and enforcement switch for the closed-to-new task ratio gate. One module holds them so the endpoint header and the create gate cannot disagree. The task store is on [[task-store]].

## Layers
- A persisted override file wins. A non-numeric stored window or threshold skips the INI and takes the built-in fallback. The INI keys `task flow ratio window hours`, `task flow ratio allow below` and `task flow ratio enforcement active` are the boot default. A built-in fallback is last.
- `override_path` is `$LUPIN_FLOW_RATIO_DIR/flow-ratio-settings.json` when that variable is set, else `flow-ratio/flow-ratio-settings.json` under the fleet data root.

## Reads
- `get_window_hours` returns an int inside the allowed range.
- `get_allow_below` returns a float inside the allowed range. The gate opens on a ratio strictly below it.
- `get_enforcement_active` says whether a create is refused or only warned about. An unparseable INI value gives `False`, so a broken config warns rather than blocking writes. A stored override is read with `bool()`, so the string `"false"` reads as true.
- `current_settings` returns the window, threshold and enforcement flag, with a source for each, `override` or `config`. An operator can see a masked INI edit.

## Writes
- `set_overrides( window_hours, allow_below, enforcement_active )` validates, clamps and writes atomically, and can raise `ValueError` or `OSError`. A value left as `None` is unchanged.
- `clear_overrides` deletes the file, so the INI governs again, and returns the live pair. A missing file is not an error, but other `OSError`s propagate.

## Don't
- Don't hard-code the window or threshold at a call site. Read them here.
