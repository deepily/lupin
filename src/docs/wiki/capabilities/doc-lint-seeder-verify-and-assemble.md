---
capability: doc-lint-seeder-verify-and-assemble
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.doc_lint.labelled_set_seeder.read_failed_ids@fffc934d2b
  - cosa.repo.doc_lint.labelled_set_seeder.redraw_pairs@fb29b6d2f9
  - cosa.repo.doc_lint.labelled_set_seeder.cmd_redraw@9adfa5746e
  - cosa.repo.doc_lint.labelled_set_seeder.checked_outputs@032ae73f3b
  - cosa.repo.doc_lint.labelled_set_seeder.cmd_verify@55cecb6dea
  - cosa.repo.doc_lint.labelled_set_seeder.check_verification@61a0aa5e26
  - cosa.repo.doc_lint.labelled_set_seeder.recount@9bf2457715
  - cosa.repo.doc_lint.labelled_set_seeder.cmd_assemble@f72df6f4ac
  - cosa.repo.doc_lint.labelled_set_seeder.cmd_manifest@78fbdb059c
  - cosa.repo.doc_lint.labelled_set_seeder.cmd_natural@0488185aa6
---
# Doc-lint seeder verify and assemble

The last phases of the labelled-set seeding script: redraw failed pairs, hand the second seat its input, and assemble the pairs, keys and manifest. Writing is in [[doc-lint-seeder-writer-and-checks]].

## Redraw
- `read_failed_ids` reads the pair ids a second reader failed. They may be of any kind and may pass rule 1.
- `redraw_pairs` chooses a replacement for each failing pair, keeping its kind, class, shortness and stratum. A docstring used by a kept pair is never reused.
- `cmd_redraw` writes the redrawn plan to a new folder and says first how many writer calls it needs. It returns 2 when the pool is not the one the plan was drawn from, or a floor lacks a replacement.

## Second seat
- `checked_outputs` returns each task's output text for the plan, or raises. `cmd_verify` writes the second seat's input without kind labels, plus a separate span file.
- `cmd_verify` refuses with 2 while a task has no output or rule 1 fails a seeded pair. So the second seat never reads a pair the script knows is broken.
- `check_verification` returns the problems in the second seat's file. A seeded pair needs `claim_absent_in_new` true, an unseeded one `no_claim_missing` true, and every pair `grammar_ok`.

## Assemble
- `cmd_assemble` joins the plan, writer output and the second seat's file into pairs, keys and split info. It returns 2 for a missing or false verification row or a missing output.
- `recount` counts seeded pairs per kind by span-word band, 2 to 3, 4 to 6 and 7 or more, and per weaken class.
- `cmd_manifest` writes the dev-visible `MANIFEST.json`, which holds the dev files and shas and never the gate seed or split seed. It returns 2 when the commit is not 40 hex digits.
- `cmd_natural` validates `natural.jsonl` and writes it as its own arm of hand-labelled real removals. The whole file is refused when one span does not occur once or is not quotable.
