---
capability: vertex-logging-probe
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.vertex_logging.LoggingReadout@f490615241
  - cosa.utils.vertex_logging.LoggingReadout.count_rows@e5b705ddff
  - cosa.utils.vertex_logging.LoggingReadout.count_sentinel@614aefeb6b
  - cosa.utils.vertex_logging.LoggingReadout.find_sentinel@d3627199fb
  - cosa.utils.vertex_logging.LoggingReadout.list_tables@9774e04f48
  - cosa.utils.vertex_logging.ProbePlan@0bbc936cfe
  - cosa.utils.vertex_logging.ProbeResult@1c26d5f079
  - cosa.utils.vertex_logging.ProbeResult.is_admissible@72becaf4aa
  - cosa.utils.vertex_logging.VertexLoggingError@03c6fab3d1
  - cosa.utils.vertex_logging.assert_bigquery_location_legal@dac7910bf4
  - cosa.utils.vertex_logging.assert_double_write_retry_safe@d5e8238c3e
  - cosa.utils.vertex_logging.assert_location_pairing_certified@55a1fabc64
  - cosa.utils.vertex_logging.assert_sentinel_wellformed@d30c3811a5
  - cosa.utils.vertex_logging.assert_traffic_config_coupling@503ac6448a
  - cosa.utils.vertex_logging.build_full_config_write_body@d0794cf1d4
  - cosa.utils.vertex_logging.classify_ac_d5@7def4e55d8
  - cosa.utils.vertex_logging.describe_live_calls@79eab5992f
  - cosa.utils.vertex_logging.mint_sentinel@f959526a38
  - cosa.utils.vertex_logging.readout_positive_control_sql@b159f59633
---
# Vertex logging probe

`cosa.utils.vertex_logging` proves that Vertex logged a call. It gives a verdict only when a canary shows the readout was awake. `src/scripts/verify_vertex_logging.py` is its only caller.

## What it does
- `mint_sentinel()` returns `LUPIN-VLOG-` plus 12 hex characters. `assert_sentinel_wellformed` raises `VertexLoggingError` otherwise. `assert_bigquery_location_legal` rejects empty and `global`. `assert_location_pairing_certified` accepts only `( "global", "US" )`. `assert_traffic_config_coupling` raises on an empty or differing region.
- `build_full_config_write_body( fetched_config, mutation )` deep-merges and returns `{ "publisherModelConfig": merged }`. An empty fetch or a dropped leaf raises.
- `LoggingReadout( project_id, dataset="vertex_logging", query_fn=None )` has `list_tables`, `count_rows`, `count_sentinel` and `find_sentinel`. With no `query_fn` it raises on first use. `find_sentinel` returns `( state, tables )`, state `TABLE_ABSENT`, `NO_MATCH` or `MATCH`. `readout_positive_control_sql` returns `( write_sql, verify_sql )` and runs neither. `ProbePlan` needs a canary and an optional subject, fired no later than the canary with its own sentinel. `ProbeResult.is_admissible()` is false only for `INADMISSIBLE`.
- `run_probe( readout, plan, clock, sleeper=None )` polls to `max_wait_s`, default 1800 s every 30 s. Subject found is `PROVEN`, canary only is `REFUTED`, no canary is `INADMISSIBLE`.
- `classify_ac_d5` returns `FIRED`, `NOT_FIRED` or `INDETERMINATE`. `assert_double_write_retry_safe` returns `True` or raises. `describe_live_calls` lists costed calls.

## Don't
- Never report zero rows as "not logged"; the readout may be blind. Never hand-build the config for `build_full_config_write_body`: the API has no update mask, so a partial write wipes the rest.

## Invariants
- Nothing reaches the network unless a caller injects `query_fn`. Queries use `TO_JSON_STRING` over the whole row.
