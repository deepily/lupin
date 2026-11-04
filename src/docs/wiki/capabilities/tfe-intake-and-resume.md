---
capability: tfe-intake-and-resume
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.test_fix_expediter.config.TestFixExpediterConfig@f7f07fcd0d
  - cosa.agents.test_fix_expediter.snapshot_loader.SnapshotLoadError@b02487617a
  - cosa.agents.test_fix_expediter.snapshot_loader.load_from_path@ae60ef0413
  - cosa.agents.test_fix_expediter.snapshot_loader.load_from_artifacts@262a7c7f8d
  - cosa.agents.test_fix_expediter.cluster.heuristic_seed@445ca0a75c
  - cosa.agents.test_fix_expediter.resume_resolver.ResumeTarget@f32f24a9ef
  - cosa.agents.test_fix_expediter.resume_resolver.list_resume_candidates@f11dc861e8
  - cosa.agents.test_fix_expediter.resume_resolver.fuzzy_match_candidates@2fb1c019ff
---
# Test fix expediter intake and resume

How a run starts from a failed test suite job, how failures are first grouped, and how a resume request finds its job. See [[fix-expediter-tfe]].

## What it does
- `load_from_path` reads a remediation snapshot file and returns a `TestRemediationContext`. `load_from_artifacts` takes the parsed snapshot from a job's artifacts.
- Both require schema version 1.0 and a non-empty failures list, and they redact absolute paths and email addresses in tracebacks.
- `SnapshotLoadError` is raised for a missing file, bad `json`, an unsupported version, or a missing or empty field.
- `heuristic_seed` groups failures by test class and the first frame outside pytest. Cluster ids are the letter `C` plus a position, counted from one in order of first appearance.
- Every failure index lands in exactly one seed cluster, with a baseline confidence of 0.7.
- `list_resume_candidates` returns the user's stalled test fix jobs first, then recent others, as flat dictionaries.
- `fuzzy_match_candidates` ranks those candidates against a free-text description through a model and adds `confidence` and `reason`.
- `ResumeTarget` is the result of resolving a resume request: job id, source type, matched path, confidence, candidates and a diagnostic.
- `TestFixExpediterConfig` holds 25 settings. `from_config` loads them through `load_kwargs_from_ini` ([[agent-ini-config-loader]]), and pushing the fix branch is off unless switched on.

## Invariants
- `list_resume_candidates` and `fuzzy_match_candidates` return an empty list on any error and never raise.
- Trust mode is one of `inherit`, `shadow`, `fixed_l1` or `fixed_l3`.
