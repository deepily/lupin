---
capability: utils-iso-timestamp
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.iso_timestamp.parse_iso@1f810d5498
---
# ISO-8601 timestamp parser

One function the arbiter modules share to read a stamp out of a JSON file or a row. The hook library keeps its own twin in `heartbeat_hold.py`, because a hook must not import `cosa`.

## What it does
- `parse_iso( value )` returns a datetime, or `None` when the value cannot be read.
- A trailing `Z` reads as `+00:00`, and whitespace around the text is ignored.
- A stamp with no zone is read as UTC.
- `dependency_graph`, `fleet_data_model` and `operator_gate_routing` keep the name `_parse_iso` as an alias of it.

## Don't
- Don't use it where a zone-less stamp must be refused. `respin_wake_check`, `self_respin_observer` and `reap_memento` keep their own readers, which return `None` for a naive stamp.

## Invariants
- It never raises. `None`, a blank or non-string value and unparseable text all give `None`.
