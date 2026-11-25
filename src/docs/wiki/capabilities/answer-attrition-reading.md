---
capability: answer-attrition-reading
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - scripts.answer_attrition_table.norm_id@0d83671af6
  - scripts.answer_attrition_table.as_json@babb5c0bd2
  - scripts.answer_attrition_table.set_read_only@db75b93e18
  - scripts.answer_attrition_table.clean_row@3b5036023e
  - scripts.answer_attrition_table.read_tables@d8d5bf640c
  - scripts.answer_attrition_table.open_archive_session@a06814c92a
  - scripts.answer_attrition_table.provenance@f631d8891d
  - scripts.answer_attrition_table.schema_of@441cefe2bb
  - scripts.answer_attrition_table.field_units@2ae11d3ab5
  - scripts.answer_attrition_table.answers_map@3bcd665e04
  - scripts.answer_attrition_table.is_timeout@7eddfd440b
  - scripts.answer_attrition_table.timeout_units@51909495ca
  - scripts.answer_attrition_table.stance_units@b359c178c3
  - scripts.answer_attrition_table.production_units@8dd6ad2757
  - scripts.answer_attrition_table.plain_units@5be40632b0
---
# Answer attrition table: reading the answers

`src/scripts/answer_attrition_table.py` counts how much of each of Rick's answers survives each step of the prediction pipeline. This page covers how it reads the rows and splits an answer into units. The steps are in [[answer-attrition-steps]] and the run in [[answer-attrition-run]].

## Reading, never writing
- Every database is read through a session whose first statement makes the transaction read-only (`set_read_only`). The transaction is always rolled back. A dialect with no read-only statement raises `ValueError`.
- `read_tables( session )` reads the answered notifications, the evidence rows and the reveal log. `clean_row` shapes a notification row as the pipeline reads it, and `as_json` decodes a stored JSON column.
- `norm_id` makes the archive's hyphen-free ids and the app's hyphenated ids compare equal. `open_archive_session( path )` opens the run 2 archive through a read-only SQLite address.
- `provenance()` names the run time and the git sha, or `unknown` when git cannot say.

## Units
- A unit is one piece of an answer: the stance, the comment, typed Other text or one multi-select pick. An explicit empty selection, a timeout with its default, open-ended text and one batch field are units too.
- `field_units` classifies one field's value without calling the code under test. `schema_of` and `answers_map` read the card's schema and the stored answers map.
- `is_timeout` asks `attribution_tier` whether the answer is a timeout default. `timeout_units` names the timeout and the default it fell back to.
- `production_units` reads the answer with the production readers. `plain_units` reads it with a plain first-word reader, as the control. `stance_units` uses the production yes/no parser.
