---
capability: unit-network-guard-and-collection-diagnosis
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.unit_network_guard.arm@0e3323395a
  - cosa.utils.unit_network_guard.caller_frames@3ab6212010
  - cosa.utils.unit_network_guard.is_loopback@f0375e8f1b
  - cosa.utils.unit_network_guard.network_guard@99a07f7768
  - cosa.utils.unit_network_guard.set_current_test@519e6308db
  - cosa.utils.pytest_collection_diagnosis.diagnose@b6bbbdf393
  - cosa.utils.pytest_collection_diagnosis.main@41c131061e
  - cosa.utils.pytest_collection_diagnosis.render@d45e3f999b
---
# Unit network guard and collection diagnosis

Two helpers for reading a unit run: one catches a test that dials out, the other explains a pytest collection failure. Venues are in [[scheduled-test-suite]].

## What it does
- `unit_network_guard` holds the outbound-dial guard state in one module.
- `arm()` patches `socket.connect` and `connect_ex` once. It returns True only when it did.
- `set_current_test( node_id, exempt )` records the running test. `network_guard( real )` wraps one socket method.
- `is_loopback` treats non-tuple addresses, `127.*`, `::1`, `localhost`, `0.0.0.0` and `""` as local. That is correct on Linux, where a connect to the wildcard address reaches this host.
- `caller_frames` names up to six non-library frames.
- `diagnose( exit_code, output, project_root=None, where_hint=None )` returns a dict or None. The dict has `state`, `where`, `cause_class`, `detail`, `remedy` and `uncommitted_suspects`.
- `render` prints the block. `main` is the shell entry with `--exit-code`, `--output-file`, `--project-root` and `--where-hint`.

## Don't
- Don't expect the guard to act without `LUPIN_UNIT_NETWORK=count` or `block`. The default is `off`, and the mode is read once at import.
- Don't read exit code 4 as a conftest failure unless `conftest` is in the output. `diagnose` returns None otherwise.
- Don't expect `main` to carry the verdict. It always returns 0, even on bad arguments.

## Invariants
- In block mode a routed dial raises `RuntimeError` naming the test, address and frames.
