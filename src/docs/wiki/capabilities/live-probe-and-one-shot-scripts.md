---
capability: live-probe-and-one-shot-scripts
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.backfill_bridge_sender_id.classify@dfe6f18565
  - scripts.backfill_bridge_sender_id.main@beb4673fb5
  - scripts.migrate-dm-topic-case.migrate_directory@2d2bbfa600
  - scripts.migrate-dm-topic-case.main@aae4c6a1d8
  - scripts.observe_gate_b_admission.login@b69b8f0207
  - scripts.observe_gate_b_admission.check_mount@472b53c730
  - scripts.observe_gate_b_admission.check_prior_yaml@2ce9fe79b8
  - scripts.observe_gate_b_admission.check_idle@a9472130cc
  - scripts.observe_gate_b_admission.qualifies@2718e1f7af
  - scripts.observe_gate_b_admission.watch@57706e2ca0
  - scripts.observe_gate_b_admission.main@5e7c601fed
  - scripts.probe_broadcast_ack_two_sided.main@3fb79e9f05
  - scripts.probe_commons_post_direct.make_body@1bf88811d2
  - scripts.probe_commons_post_direct.run_probe@ec96b63b32
  - scripts.tfe_to_cc_phase3_live.main@02ef6048cd
  - scripts.ws_job_listener.EvalIntegrityError@53a46fbfc7
  - scripts.ws_job_listener.parse_transitions@6f852c1448
  - scripts.ws_job_listener.WsJobEventListener@7e379de527
  - scripts.ws_job_listener.make_ws_recv_events@c9574b229d
---
# Live probes and one-shot fix scripts
Scripts under `src/scripts/` that probe a live system or fix state once. Run each on the owner's word.
- `observe_gate_b_admission.py` watches Gate B admit a lineage child through a monopoly hold on `:8000`. `login` gets a token.
- `check_mount`, `check_prior_yaml` and `check_idle` refuse to start unless the container is on the main checkout, a prior YAML exists and `:8000` is free.
- `watch` polls pool status and writes each sample to disk as it arrives. `qualifies` is true only when all three admission clauses hold in one sample.
- `ws_job_listener.py` holds the queue WebSocket listener. `WsJobEventListener` buffers `job_state_transition` frames by job id.
- `parse_transitions` reduces one job's frames to a transitions dict. `make_ws_recv_events` starts a listener and returns it with its receive function.
- `EvalIntegrityError` there is raised when a precondition for a trustworthy measurement fails.
- `tfe_to_cc_phase3_live.py` is the live run of the third TFE-to-CC stage over the 11-fix set. `probe_broadcast_ack_two_sided.py` reads a saved broadcast ack back through both doors.
- `probe_commons_post_direct.py` posts bodies of rising length to the store directly. `make_body` builds a body of exact length, and `run_probe` runs it.
- `backfill_bridge_sender_id.py` adds `sender_id` to old session bridges. `classify` decides what to do with each. It writes only with `--write`.
- `migrate-dm-topic-case.py` renames and merges case-variant DM topic files. `migrate_directory` handles one commons directory and returns its counts.
