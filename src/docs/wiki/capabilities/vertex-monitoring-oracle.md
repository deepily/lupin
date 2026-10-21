---
capability: vertex-monitoring-oracle
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.utils.vertex_monitoring_oracle.MonitoringOracle@54bf31b135
  - cosa.utils.vertex_monitoring_oracle.MonitoringOracle.await_canary@48409865ce
  - cosa.utils.vertex_monitoring_oracle.MonitoringOracle.derived_spend@53760d9b5b
  - cosa.utils.vertex_monitoring_oracle.MonitoringOracle.time_series@bb7c2cb8d8
  - cosa.utils.vertex_monitoring_oracle.MonitoringOracle.verify_no_leak_into_default_path@b246d59e65
  - cosa.utils.vertex_monitoring_oracle.MonitoringOracle.verify_ran_on_vertex@c5f7951283
  - cosa.utils.vertex_monitoring_oracle.OracleInadmissible@141a30ea4d
  - cosa.utils.vertex_monitoring_oracle.Verdict@3bdae5a476
  - cosa.utils.vertex_monitoring_oracle.build_google_auth_transport@22d953583a
  - cosa.utils.vertex_monitoring_oracle.resolve_project_and_region@df585481b2
---
# Vertex monitoring oracle

`cosa.utils.vertex_monitoring_oracle` reads Cloud Monitoring v3 over REST to show a call ran on Vertex and what it cost. It gives a verdict only after a canary proves the counter was awake. Nothing outside the tests uses it.

## What it does
- `MonitoringOracle( project_id, transport, clock, token_provider=None )` has `time_series`, `await_canary`, `verify_ran_on_vertex`, `verify_no_leak_into_default_path` and `derived_spend`. `verify_ran_on_vertex` fails a series whose `resource_container` is neither the project id nor `projects/<id>`; a longer id that contains ours does not pass. It also fails a wrong region, a wrong model and a rejected response code.
- Each method returns a `Verdict` of `PASS`, `FAIL` or `INADMISSIBLE`. `await_canary` raises `OracleInadmissible` instead.
- `build_google_auth_transport()` is the only call that reaches Google Cloud.
- `resolve_project_and_region( env=None )` reads `LUPIN_GCP_PROJECT_ID` and `LUPIN_VERTEX_REGION`. It raises `KeyError` when one is absent.

## Don't
- Don't read a silent counter as "$0". Without a canary it means the oracle was blind.

## Invariants
- The oracle reaches the network only through the injected transport.
- `verify_no_leak_into_default_path` fails on a Vertex key in the environment, with or without a canary. Only a silent counter needs the canary.
