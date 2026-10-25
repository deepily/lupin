---
capability: self-respin-memento-and-clear
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.self_respin_core.build_nonce_line@be111eec22
  - lupin_mcp.self_respin_core.stamp_nonce_into@7a1f52439e
  - lupin_mcp.self_respin_core.verify_memento_content@2f594a6e82
  - lupin_mcp.self_respin_core.build_wake_text@c5ef75a4ea
  - lupin_mcp.self_respin_core.pane_idle_rule@329563e03f
  - lupin_mcp.self_respin_core.build_guarded_clear_argv@1bac5cd21d
  - lupin_mcp.self_respin_core.parse_marker_schema_version@8e47414708
  - lupin_mcp.self_respin_core.loaded_marker_schema_version@374d6e16c6
  - lupin_mcp.self_respin_core.stale_module_warning@ca3dcfba3c
  - lupin_mcp.self_respin_core.marker_field_warning@346cfe4312
---
# Self re-spin: memento proof and the clear
After the go, the verb proves the memento is complete and fresh, then types the clear into its own pane. Identity and the ask are on [[self-respin-identity-and-ask]].
- `build_nonce_line` returns the stamp line `SELF-RESPIN-NONCE: <uuid> @ <time>` that the memento must carry.
- `stamp_nonce_into` is retired and always raises `ValueError` naming the replacement. Nothing calls it.
- `verify_memento_content` returns a verdict and a reason. It fails an empty file, a blank nonce, or a body under the minimum size once nonce lines are removed.
- It also fails when the exact nonce line is missing, or its time is unparseable or outside the cycle window. It never raises.
- `build_wake_text` builds the one-line rehydrate prompt typed after the clear. It asks the seat to write a wake proof file only if it did rehydrate.
- `pane_idle_rule` returns the idle-prompt rule of the DM injector, read from the listener and not copied.
- `build_guarded_clear_argv` builds the detached command that types the text into the pane. It first consumes a one-shot fire token, so the clear cannot fire twice.
- `parse_marker_schema_version` reads `MARKER_SCHEMA_VERSION` from observer source. `loaded_marker_schema_version` reads it from the loaded module, and gives 0 when absent.
- `stale_module_warning` warns when the disk declares a newer version than the loaded one. It never refuses.
- `marker_field_warning` warns when the marker just written lacks a contracted field.
