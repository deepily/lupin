---
capability: test-suite-container-gates-and-voice
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.test_suite.job.running_in_container@2ce99374e9
  - cosa.agents.test_suite.job.container_refusal@4b1bef40d6
  - cosa.agents.test_suite.job.suites_left_out@6bfe8203e6
  - cosa.agents.test_suite.job.tables_with_fk_into@6f46db0008
  - cosa.agents.test_suite.cosa_interface.notify_progress@fb11b5d63c
  - cosa.agents.test_suite.cosa_interface.ask_yes_no@0a1a91041a
  - cosa.agents.test_suite.voice_io.reconfigure@8265f4719a
---
# Test suite container gates and voice

Rules about which suites a containerized server offers, a check on the database reset list, and the voice functions of the test suite agent. Scheduling is in [[scheduled-test-suite]].

## What it does
- `running_in_container` is true when `LUPIN_IN_CONTAINER` is `1`, `true` or `yes`, or when `/.dockerenv` exists.
- `container_refusal` returns a message when a request names `unit` or `docker_smoke` and the process runs in a container. Otherwise it returns `None`.
- The refusal names the host command that runs the suite and the suites offered here.
- `suites_left_out` returns each host-only suite with the text `not run here, host tier`. It does so only for a container request that names `all`.
- `tables_with_fk_into` returns the sorted tables outside a list that hold a foreign key into the list. An empty result means a truncate is closed under foreign keys.
- `notify_progress` sends a non-blocking progress message. `ask_yes_no` blocks and returns `yes` or `no`.
- `voice_io.reconfigure` binds the shared voice layer to this agent's `cosa_interface` again.

## Don't
- Don't read `all` as listing `unit` or `docker_smoke` in a container. They run on the host.
