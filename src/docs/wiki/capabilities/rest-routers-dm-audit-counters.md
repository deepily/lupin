---
capability: rest-routers-dm-audit-counters
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.routers.dm.reset_dm_project_audit@d2992cf823
  - cosa.rest.routers.dm.get_dm_project_audit@6802928ebc
  - cosa.rest.routers.dm.format_dm_project_audit_line@a46596d5d7
  - cosa.rest.routers.dm.reset_dm_length_audit@c16ca1508d
  - cosa.rest.routers.dm.get_dm_length_audit@40998d2d33
  - cosa.rest.routers.dm.format_dm_length_audit_line@b02528cfc8
  - cosa.rest.routers.dm.reset_dm_quality_audit@6239676657
  - cosa.rest.routers.dm.get_dm_quality_audit@eb2f5fd112
  - cosa.rest.routers.dm.format_dm_quality_audit_line@4d83fb15f9
  - cosa.rest.routers.dm.get_dm_project_audit_endpoint@d33766ac94
  - cosa.rest.routers.dm.get_dm_length_audit_endpoint@7fae346ad7
  - cosa.rest.routers.dm.get_dm_quality_audit_endpoint@2dd8ce204b
---
# DM audit counters

In-memory counters in `routers/dm.py` that measure the DM traffic. They live in the server process and reset on restart, so read `since` with every number. Each audit has a reset, a snapshot and a one-line log formatter. See [[rest-routers-dm-send-get-and-list]].

## What it does
- The project audit counts DMs that did and did not carry `sender_project`. `get_dm_project_audit` returns a copy with `projected`, `un_projected` and up to 50 offender sessions. `format_dm_project_audit_line` always prints both counts, zeros included.
- `reset_dm_project_audit` zeroes the counts and restarts `since`.
- The length audit sums characters, words and sentences per DM. `get_dm_length_audit` adds `avg_chars`, `avg_words` and `avg_sentences`, all 0.0 when the count is 0. `reset_dm_length_audit` and `format_dm_length_audit_line` go with it.
- The quality audit sums the judge's grades. `get_dm_quality_audit` adds `avg_length`, `avg_overall` and `avg_overage` over `count`. `avg_directness` and `avg_tone` divide by `qualitative_count`, which counts only grades where both weights are not `None`, and read 0.0 when it is 0. `reset_dm_quality_audit` and `format_dm_quality_audit_line` go with it.
- `get_dm_project_audit_endpoint`, `get_dm_length_audit_endpoint` and `get_dm_quality_audit_endpoint` serve the three snapshots at `/api/dm/project-audit`, `/length-audit` and `/quality-audit`. Each needs an API key or a JWT.

## Don't
- Don't read `un_projected=0` alone. A window with no traffic also shows 0, so check `projected`.
- Don't compare counts across a server restart. The counters start over.
- Don't expect quality counts in a control window. The judge runs only when `dm quality judgment enabled` is true.

## Invariants
- A snapshot is a copy. Holding it never changes the live counters.
