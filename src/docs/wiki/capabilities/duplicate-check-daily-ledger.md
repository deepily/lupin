---
capability: duplicate-check-daily-ledger
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.duplicate_check.proof.proof_cli.daily_ledger@d6cba5c36e
  - cosa.repo.duplicate_check.proof.proof_cli.StampedLedger@21e8828a11
  - cosa.repo.duplicate_check.proof.proof_cli.StampedLedger.settle@1937f8f032
---
# Duplicate-check daily ledger

The judge ledger of the daily and baseline runs. It keeps every ruling when Claude Code updates itself, so an update does not make the job judge again what it already judged. It sits beside [[duplicate-check-daily-run]] and [[duplicate-check-proof-command]].

## What it does
- `daily_ledger` opens `judge-ledger.jsonl` in the daily folder and returns a `StampedLedger`. The ledger is bound to the Claude Code path, the backend and the server, with no version in the binding.
- `StampedLedger` writes each new ruling with a `cli` field holding the version that wrote it. A binding line is written as it is.
- `settle` accepts a recorded binding that differs in the version alone and appends the version-free binding as the newest one. Nothing is renamed or rewritten.
- A ruling is read back when its key matches. The key holds the definition and candidate hashes, the prompt version, the model id and the slot, and never the version.

## Don't
- Don't use it for the proof. `proof_ledger` keeps the version in the binding so a measured run never mixes binaries.
- Don't expect a Fable ruling to answer an Opus run: the model id is in the key.
- Don't look for `ledger_rotated` in a run file: no ledger is renamed aside any more.
