---
capability: v2-eval-run-and-report
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.v2_eval.HttpAskClient@52109eafeb
  - scripts.v2_eval.resolve_base_url@3923ec76af
  - scripts.v2_eval.running_in_container@cf13e618f9
  - scripts.v2_eval.read_running_server_sha@c827d44fc0
  - scripts.v2_eval.EligibleCommandsUnavailable@d925712ce4
  - scripts.v2_eval.load_mappable_commands@9849c23c50
  - scripts.v2_eval.terminal_waiting_ask@53b9e4a758
  - scripts.v2_eval.run_pass@f2859a3fd0
  - scripts.v2_eval.render_report@cbaf4201d9
  - scripts.v2_eval.dump_records_early@068d6280f5
  - scripts.v2_eval.write_outputs@33f82cf412
  - scripts.v2_eval.build_arg_parser@fc1de55f89
  - scripts.v2_eval.main@8408606601
  - scripts.v2_eval.make_attempt_logger@a5064701d1
---
# CJ Flow v2 eval: the run and its report
The driving half of `src/scripts/v2_eval.py`: asking the server, running both passes and writing the report. Scoring is on [[v2-eval-metrics-and-guards]].
- `HttpAskClient` posts to `/api/v2/ask` with a bearer token. `make_attempt_logger` builds the sink that appends its start, end and error rows as JSON lines.
- `resolve_base_url` picks the address that works from where the run executes. `running_in_container` tests for `/.dockerenv`. An explicit `--base-url` always wins.
- `read_running_server_sha` asks `/api/code-identity` which git sha the server booted from, so numbers trace to a tree.
- `load_mappable_commands` reads the routing commands both arms score from a frozen checked-in list. `EligibleCommandsUnavailable` is raised when it cannot, instead of scoring a wider set.
- `terminal_waiting_ask` wraps an ask so a record's span ends at the observed completion, not at the enqueue acknowledgement.
- `run_pass` runs one cold or warm pass and attaches the expected command to each record. `dump_records_early` writes the raw records before any guard can refuse.
- `render_report` makes the markdown report, with the seed and sample size. `write_outputs` writes `report.md` and `records.jsonl`.
- `build_arg_parser` defines the command line. `main` runs cold then warm, applies the guards and writes under `io/v2-flow/eval-<timestamp>/`. It raises `ValueError` unless passes is 2.
