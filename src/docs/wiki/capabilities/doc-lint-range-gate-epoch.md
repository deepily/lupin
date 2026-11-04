---
capability: doc-lint-range-gate-epoch
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.doc_lint.range_gate.parse_blocking_epoch@3166c7d9ef
  - cosa.repo.doc_lint.range_gate.read_blocking_epoch@67185e29f8
  - cosa.repo.doc_lint.range_gate.working_epoch_text@c80186bd49
  - cosa.repo.doc_lint.range_gate.committed_epoch_text@4b6d1a5a70
  - cosa.repo.doc_lint.range_gate.require_commit@85f54b50e2
  - cosa.repo.doc_lint.range_gate.require_one_value@009b6af6c2
  - cosa.repo.doc_lint.range_gate.resolve_blocking_epoch@cd66c84f43
  - cosa.repo.doc_lint.range_gate.descends@c817c2cd3d
  - cosa.repo.doc_lint.range_gate.is_held@657beb6eeb
  - cosa.repo.doc_lint.range_gate.other_parents@28358c358a
  - cosa.repo.doc_lint.range_gate.incoming_path@978f7bd072
---
# Doc-lint range gate epoch

The blocking epoch decides which commits of a range the replay holds to `--blocking`. It is one commit sha recorded in a file. These helpers read it and settle which value a range is judged under.

## Reading the epoch
- `parse_blocking_epoch` returns the sha when exactly one line holds a value, and `None` when no line does. Blank lines and `#` lines are skipped. `read_blocking_epoch` does this for a working tree, and `None` means no commit is held.
- `working_epoch_text` and `committed_epoch_text` return the file's text from a working tree or from a commit's tree, or `None` when the file is missing.
- `require_commit` accepts only the sha of a commit object. A tag is refused even when it points at a commit.

## Settling the value
- `resolve_blocking_epoch` judges a range under the value its base records, and the head's tree must record the same one. So a range cannot lift its own blocking by emptying or moving the file.
- When the base records none, the head's value is used. `require_one_value` then refuses a range whose commits record two values, or a value that its head drops.
- A head that holds the file must match the working copy, and a malformed value refuses the range. All of these raise `RangeRefused`.

## Holding a commit
- `descends` says whether one commit is another or descends from it. `is_held` is true when the commit's first parent is the epoch or descends from it, and false when no epoch is recorded.
- `other_parents` lists the parents after the first, which a merge replays as its incoming commits. `incoming_path` names the `MERGE_HEAD` file of a working tree's own git directory.
