---
capability: util-jsonl-file
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.jsonl_file.read_jsonl@5c73d05fa1
---
# JSON Lines file reader

`cosa.utils.jsonl_file.read_jsonl` is the one reader of a whole JSON Lines file. The doc-lint tools, the reuse need-set rejection ledger and the duplicate-check filer all use it.

## Rules
- `read_jsonl( path )` returns the parsed value of every non-blank line, in file order. A line of spaces counts as blank.
- A missing file raises `FileNotFoundError`. With `missing_ok=True` it gives an empty list.
- A line that is not JSON raises `JSONDecodeError`, with or without `missing_ok`. The message names no file or line.
- Lines split on the newline character only, so a raw U+2028 inside a string stays in its record.
- It is not for a ledger that must name the corrupt line: `attestation.read_records` keeps its own reader for that. The `analyze_arms` script keeps its own, because it imports nothing from cosa.
