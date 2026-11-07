---
capability: reuse-refusals-record
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_refusals.scanned_lines@677691b7bc
  - lupin_mcp.reuse_refusals.judge@847c61de03
  - lupin_mcp.reuse_refusals.record@8f8aa010ab
  - lupin_mcp.reuse_refusals.default_data_dir@e630be9686
  - lupin_mcp.reuse_refusals.not_checked@dcdd0200f7
  - lupin_mcp.reuse_refusals.main@bec73e4e08
---
# Reuse: judging a document and keeping the record
`lupin_mcp.reuse_refusals` runs the checks of [[reuse-outcome-line-checks]] on each outcome line of one document and appends what happened to `refusals.jsonl` in the data folder. A line that passed is recorded too, so a later count reads the whole corpus ([[reuse-behaviour-weekly-page]]). It sends nothing and runs no model.

## What it does
- `scanned_lines( text )` returns `{ n, line, outcome }` for every line that opens with the keyword and is not a template line. `n` counts from 1. `outcome` is None when the line does not match the shape.
- `judge` returns `{ n, line, status, reasons, pairs }` per line, `accepted` or `refused`. A line that does not match is refused with no pairs. Any other line gets the token, call-log and pairing reasons, each run on that line alone. `pairs` lists [ symbol id, receipt id ] for the rulings that cite its receipt.
- `record( data_dir, text, verdicts )` appends one JSON line per verdict, once per document hash (a sha256 of the text) and line number. A second run on the same text adds nothing. It holds an exclusive lock from reading the keys to the last write. It writes each record with one write. It starts on a new line after a last line with no newline. It returns the number appended.
- `default_data_dir( root )` is `LUPIN_REUSE_DATA_DIR` when set, else the repository's data directory.
- `main` takes a document path and `--diff`, `--root`, `--data-dir`, `--log-dir`. It prints the document hash, lines scanned, lines refused, records appended, the refusal reasons and the new definitions with no outcome line.

## Exit codes
- 0: every line accepted and no definition missing.
- 1: a line was refused or a definition has no outcome line.
- 3: it could not check (`not_checked` prints the error). Causes: an unreadable or unwritable file, a diff that is not a symbol index diff, or one that reports `algorithm_changed`. It is neither a pass nor a refusal.
