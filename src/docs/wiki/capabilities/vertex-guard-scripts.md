---
capability: vertex-guard-scripts
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.verify_vertex_logging.make_bq_query_fn@e1f4149200
  - scripts.verify_vertex_logging.print_plan@a7c1c468ee
  - scripts.verify_vertex_logging.print_emit@f0b7330b38
  - scripts.verify_vertex_logging.run_verify@fa184a03b5
  - scripts.verify_vertex_logging.build_parser@590b0892bd
  - scripts.verify_vertex_logging.main@be44e68994
  - scripts.vertex_publisher_config_guard.find_missing_keys@de2af7210d
  - scripts.vertex_publisher_config_guard.find_added_keys@d180b64ee1
  - scripts.vertex_publisher_config_guard.check_payload@1f9b79359c
  - scripts.vertex_publisher_config_guard.main@221a188adc
  - scripts.vertex_publisher_config_guard.quick_smoke_test@9b77bfbd00
---
# Vertex logging and publisher config scripts
Two scripts for the Vertex publisher model. Neither fires a prediction call or a cloud write on its own.
- `verify_vertex_logging.py` renders the verdict of the request-response logging check. The prediction calls and cloud writes belong to the authorized seat.
- `make_bq_query_fn` builds a BigQuery query function backed by the `bq` command. `print_plan` prints the live-call manifest and fires nothing.
- `print_emit` mints the sentinels and prints the exact commands for the authorized seat. `run_verify` reads BigQuery only and renders the verdict.
- `build_parser` defines the options, with the free plan as the default. `main` returns 1 on `INADMISSIBLE`.
- `vertex_publisher_config_guard.py` refuses a config write that would wipe live settings, because `setPublisherModelConfig` sets the whole object.
- `find_missing_keys` lists keys in the live config that the candidate lacks. `find_added_keys` lists keys the candidate adds.
- `check_payload` decides whether a candidate may proceed. `main` prints `ALLOW` or `REFUSED`. `quick_smoke_test` checks the three verdict shapes.
