---
capability: doc-lint-seeder-plan
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.doc_lint.labelled_set_seeder.Shortfall@9322d98720
  - cosa.repo.doc_lint.labelled_set_seeder.pick@eab6e5a276
  - cosa.repo.doc_lint.labelled_set_seeder.draw_split@1ac017ee89
  - cosa.repo.doc_lint.labelled_set_seeder.build_docs@8261b9b611
  - cosa.repo.doc_lint.labelled_set_seeder.seed_search@0662a2d4bb
  - cosa.repo.doc_lint.labelled_set_seeder.make_pair@bf7092e863
  - cosa.repo.doc_lint.labelled_set_seeder.build_split_plan@07304567be
  - cosa.repo.doc_lint.labelled_set_seeder.cmd_plan@0259ae69e8
  - cosa.repo.doc_lint.labelled_set_seeder.refuse_gate_out_in_repo@7def30bbb9
  - cosa.repo.doc_lint.labelled_set_seeder.check_writer_model@b1678bd823
  - cosa.repo.doc_lint.labelled_set_seeder.task_sha@433ba7ac92
  - cosa.repo.doc_lint.labelled_set_seeder.prompt_hash@cd8ed8622b
  - cosa.repo.doc_lint.labelled_set_seeder.plan_hash@3c5e23a678
  - cosa.repo.doc_lint.labelled_set_seeder.check_plan_hash@09b51734f8
  - cosa.repo.doc_lint.labelled_set_seeder.check_reserve_plan_hash@dd3087c01d
---
# Doc-lint seeder plan

The plan phase of the labelled-set seeding script. It draws the dev, gate and reserve splits and the writer tasks, and makes no model call. Candidates come from [[doc-lint-seeder-candidates]].

## Drawing
- `build_docs` returns the usable docstrings by kind with their candidates, and the sorted units. A docstring under 3 lines or in the exclude list is left out, and so is a kind with no candidate.
- `pick` picks docstrings for a kind with a candidate each, meeting the short, class and stratum quotas. A floor is never relaxed: it raises `Shortfall` naming what is missing.
- `draw_split` draws one split's picks per kind from the units it owns. `seed_search` tries split seeds until dev, gate and reserve can each fill every kind and stratum.

## Pairs and tasks
- `make_pair` returns the pair record of one pick and adds its writer tasks. `build_split_plan` assigns ids `p000..` after a seeded shuffle across kinds, so id order says nothing about kind.
- Task ids are random-looking and unrelated to pair ids, and the writer sees one text per task.
- `cmd_plan` writes `plan.json` and `writer_tasks.jsonl` per split. It returns 0, or 2 when refused, and gate and reserve files go outside the repo.

## Refusals and hashes
- `refuse_gate_out_in_repo` raises `ValueError` when an output directory is the project root or under it. `check_writer_model` refuses an empty writer id or one equal to a judge, extractor or escalation model.
- `task_sha` ties an output to its task by hashing the instruction and text. `prompt_hash` hashes the writer system prompt and the two instruction strings.
- `plan_hash` hashes the units, the picks and every task's content sha. `check_plan_hash` refuses a plan whose stored hash is not its content hash now.
- `check_reserve_plan_hash` compares the reserve plan with the hash `plan` wrote beside it. It catches an edit of `plan.json` alone, not an edit of both files.
