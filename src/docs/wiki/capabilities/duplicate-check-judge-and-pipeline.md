---
capability: duplicate-check-judge-and-pipeline
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.duplicate_check.judge.MaxPlanBackend@5cd98e2615
  - cosa.repo.duplicate_check.judge.WorkServerBackend@b57813f170
  - cosa.repo.duplicate_check.judge.build_prompt@929dcbf40c
  - cosa.repo.duplicate_check.judge.judge_run@0df5519297
  - cosa.repo.duplicate_check.judge.ledger_binding@176c22d9f9
  - cosa.repo.duplicate_check.judge.parse_reply@a4690fda14
  - cosa.repo.duplicate_check.judge.prompt_parts@a14ac429b6
  - cosa.repo.duplicate_check.pipeline.judge_all@e2d3d55aaa
  - cosa.repo.duplicate_check.score_run.aggregate_runs@3ebf5a13a3
  - cosa.repo.duplicate_check.score_run.main@a728498f59
  - cosa.repo.duplicate_check.score_run.score_run@cd812d42a2
  - cosa.repo.duplicate_check.smoke.TimedBackend@46a5b65411
  - cosa.repo.duplicate_check.smoke.build_record@c7117c421c
  - cosa.repo.duplicate_check.smoke.percentile@eb31d21753
  - cosa.repo.duplicate_check.smoke.write_record@1932406a34
  - cosa.repo.duplicate_check.smoke.configure_cli@7e271974b4
---
# Duplicate checker: judge and scoring
The judge makes one blind, ledgered model call per new definition and rules on each of its candidates.
- `build_prompt` builds the system and user prompts, with random-suffix tags around every block. `prompt_parts` returns the three texts behind the prompt version.
- `parse_reply` parses a reply strictly into one verdict per label. `judge_run` judges each definition once and resumes from the ledger. A model call that raises `ModelCallError` leaves its definition unjudged as `JUDGE_CALL_FAILED`, is not ledgered, and the other definitions go on.
- `ledger_binding` names what a ledger is bound to, so another binary or server is refused.
- `MaxPlanBackend` uses bounded Claude Code, which has no temperature setting. `WorkServerBackend` uses Rick's work server and passes temperature 0.
- `judge_all` drops server definitions that carry a scrub token, then embeds the pool, picks each definition's candidates and judges them once. `breaching_ids` finds those definitions and returns only their sorted ids, with no count. `judge_all` returns the count and ids under `dropped`. The scorer and the proof both call `judge_all`.
- `score_run` scores one run's client and reports the dropped definitions as `dropped_from_pool`. `aggregate_runs` hands the reports to the named unscorable-run policy and refuses when none is named.
- `main` scores the run directory named on the command line and writes its report there.
- `TimedBackend` wraps a backend and times each call. `build_record` and `write_record` keep the live smoke record, with each rate as an unreduced fraction string. `percentile` is nearest-rank.
- `configure_cli` in `smoke.py` points later model calls at a named Claude Code binary. It returns the first line of the binary's version output, which `ledger_binding` takes, and raises `ValueError` for a path that is not an executable file.
