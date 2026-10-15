---
capability: doc-lint-ts-count-tables
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.doc_lint.ts_counts.counted_paths@d758a4cd25
  - cosa.repo.doc_lint.ts_counts.extract@1c54dfb3a4
  - cosa.repo.doc_lint.ts_counts.scratch_names@303176e4a0
  - cosa.repo.doc_lint.ts_counts.count_records@d4945d206c
  - cosa.repo.doc_lint.ts_counts.counts_for@811b5be1c0
  - cosa.repo.doc_lint.ts_counts.census@5619636a25
  - cosa.repo.doc_lint.ts_counts.rules_stamp@a79318fe74
  - cosa.repo.doc_lint.ts_counts.main@3b52b97b36
  - cosa.repo.doc_lint.ts_doc_exists.counted_paths@4371fa2410
  - cosa.repo.doc_lint.ts_doc_exists.run_extractor@4ef8b250b2
  - cosa.repo.doc_lint.ts_doc_exists.missing@fd43497e2c
  - cosa.repo.doc_lint.ts_doc_exists.extract@8586aaa633
  - cosa.repo.doc_lint.ts_doc_exists.count_record@aeb3b20e17
  - cosa.repo.doc_lint.ts_doc_exists.counts_for@90267b774f
  - cosa.repo.doc_lint.ts_doc_exists.census_of_texts@61b1c5a329
  - cosa.repo.doc_lint.ts_doc_exists.census@2d7ef2a97f
  - cosa.repo.doc_lint.ts_doc_exists.raises@5b91ba892e
  - cosa.repo.doc_lint.ts_doc_exists.rules_stamp@a79318fe74
  - cosa.repo.doc_lint.ts_doc_exists.report@e1edfd54c6
  - cosa.repo.doc_lint.ts_doc_exists.main@1a66aff3b1
---
# Doc-lint TypeScript count tables

Two count tables hold the TypeScript and JavaScript files the [[doc-lint-ts-dart-linters]] read: comment findings per file, and exported symbols with no doc comment.

## Comment findings (`ts_counts`)
- `counted_paths` lists the tracked files `tsdoc_lint.in_scope` accepts, from git. `extract` runs the Node extractor over supplied texts, so a staged text is judged and not the disk copy.
- `scratch_names` gives a path Node cannot read, or one that starts with a dash, a stand-in name that keeps its suffix.
- `count_records` counts the findings no waiver covers, and `counts_for` counts several texts in one run. `census` counts the whole tree and returns the number of files walked.
- `rules_stamp` hashes the rule files. `main` takes `--write` and `--check`.

## Exports without a comment (`ts_doc_exists`)
- `counted_paths` is the same population less the excluded prefixes. `run_extractor` and `extract` return one export record per file, and refuse a file that came back with none.
- `missing` lists the undocumented exports of a record. `count_record` gives one finding each and no waiver, since a missing comment has no line to carry one.
- `counts_for`, `census_of_texts` and `census` count texts or a tree. `raises` lists files whose count rose above the table. `rules_stamp` hashes the rule files and `report` renders a census.
- `main` takes `--list`, `--write` and `--check`. A file that did not parse makes `--check` answer not-checked, since a lost export would read as a fall.
