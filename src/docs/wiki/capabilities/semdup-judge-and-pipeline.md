---
capability: semdup-judge-and-pipeline
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.semdup.judge.MaxPlanBackend@5cd98e2615
  - cosa.repo.semdup.judge.WorkServerBackend@b57813f170
  - cosa.repo.semdup.judge.build_prompt@929dcbf40c
  - cosa.repo.semdup.judge.judge_run@558f4bd4d2
  - cosa.repo.semdup.judge.ledger_binding@176c22d9f9
  - cosa.repo.semdup.judge.parse_reply@a4690fda14
  - cosa.repo.semdup.judge.prompt_parts@a14ac429b6
  - cosa.repo.semdup.pipeline.judge_all@6c48390e37
  - cosa.repo.semdup.score_run.aggregate_runs@cc7ffc8e3d
  - cosa.repo.semdup.score_run.main@a728498f59
  - cosa.repo.semdup.score_run.score_run@7d43cc51b2
  - cosa.repo.semdup.smoke.TimedBackend@46a5b65411
  - cosa.repo.semdup.smoke.build_record@c8e0ef1c23
  - cosa.repo.semdup.smoke.percentile@eb31d21753
  - cosa.repo.semdup.smoke.write_record@1932406a34
---
# Duplicate checker: judge and scoring
The judge makes one blind, ledgered model call per new definition and rules on each of its candidates.
- `build_prompt` builds the system and user prompts, with random-suffix tags around every block. `prompt_parts` returns the three texts behind the prompt version.
- `parse_reply` parses a reply strictly into one verdict per label. `judge_run` judges each definition once and resumes from the ledger.
- `ledger_binding` names what a ledger is bound to, so another binary or server is refused.
- `MaxPlanBackend` uses bounded Claude Code, which has no temperature setting. `WorkServerBackend` uses Rick's work server and passes temperature 0.
- `judge_all` embeds the pool, picks each definition's candidates and judges them once. The scorer and the proof both call it.
- `score_run` scores one run's client. `aggregate_runs` hands the reports to the named unscorable-run policy and refuses when none is named.
- `main` scores the run directory named on the command line and writes its report there.
- `TimedBackend` wraps a backend and times each call. `build_record` and `write_record` keep the live smoke record, and `percentile` is nearest-rank.
