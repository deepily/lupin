---
capability: bounce-control-scripts
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.bounce_dev_warn.main@813d05dcac
  - scripts.capture-bounce-resubmit.parse_test_types@ba7a844a6a
  - scripts.capture-bounce-resubmit.build_capture_record@d0a0d4e400
  - scripts.capture-bounce-resubmit.QueueClient@db8b79546a
  - scripts.capture-bounce-resubmit.capture@c4cc90ee5e
  - scripts.capture-bounce-resubmit.save_capture@57202677da
  - scripts.capture-bounce-resubmit.resubmit@42d535be6a
  - scripts.capture-bounce-resubmit.run_capture_bounce_resubmit@235605c29d
  - scripts.capture-bounce-resubmit.format_report@ec464d881b
  - scripts.capture-bounce-resubmit.main@48e89fdc14
  - scripts.compose_drift_probe.compose_tmpfs@328800b350
  - scripts.compose_drift_probe.compose_mounts@ab88babe8d
  - scripts.compose_drift_probe.inspect_mounts@65370334c8
  - scripts.compose_drift_probe.inspect_env@6049eb4b38
  - scripts.compose_drift_probe.drifted_fields@d1002af11c
  - scripts.compose_drift_probe.run_json@a48f9396f3
  - scripts.compose_drift_probe.compose_argv@a9c3e13752
  - scripts.compose_drift_probe.probe@a5354e75e8
  - scripts.compose_drift_probe.main@9c17bfd4f9
---
# Server bounce control scripts
Scripts that guard a container bounce ([[dev-server-lifecycle]]). A bounce of the `:8000` test container destroys its in-memory queue.
- `capture-bounce-resubmit.py` captures the pending queue, bounces, and resubmits every job, including other owners' jobs. It is a dry run unless `--apply` is given.
- `parse_test_types` recovers the suite names from a queued job's display string. `build_capture_record` turns one queue entry into a capture record.
- `QueueClient` is its HTTP client. `capture`, `save_capture` and `resubmit` list, persist and resend the jobs.
- `run_capture_bounce_resubmit` runs the whole control, `format_report` renders it, and `main` returns 0 for ok, 2 for missing credentials and 1 when the bounce fails.
- `bounce_dev_warn.py` posts the pre-bounce warning and waits for each recipient to ack. Its `main` is the entry point.
- `compose_drift_probe.py` compares a running container with the compose service that built it. A restart keeps old tmpfs, mounts and environment values.
- `compose_tmpfs`, `compose_mounts`, `inspect_mounts` and `inspect_env` put both sides in one shape. `drifted_fields` names every compose value the container lacks.
- `run_json` and `compose_argv` run the docker commands. `probe` makes the comparison, and `main` prints the verdict with a `RECREATE_ARG=` line per drifted value.
