---
capability: needset-known-answers
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.known_answers.load_known_answers@b1b4c51199
---
# Needset known answers

`load_known_answers( path, expected_sha )` reads the 512-need manifest of record, as chosen in [[needset-final-set]].

## What it checks
- The file's sha256 must equal `expected_sha`, which defaults to `MANIFEST_SHA`.
- The manifest count must be 512 and the listed ids must number 512.
- The split must be 124 ids in `old124` and 388 in `new388`, with no id repeated.
- The corpus commits must be `OLD_COMMIT` for `old124` and `NEW_COMMIT` for `new388`.

## Result
- It returns the parsed manifest and `need_ids`, the old 124 then the new 388 in file order. The file is opened for reading only.
- A failed check raises `NeedsetError` code `MANIFEST_MISMATCH`. The detail starts with the failed condition: sha, count, split, ids or commit.
