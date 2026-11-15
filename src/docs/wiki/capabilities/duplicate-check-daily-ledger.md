---
capability: duplicate-check-daily-ledger
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.repo.duplicate_check.proof.proof_cli.daily_ledger@d6cba5c36e
  - cosa.repo.duplicate_check.proof.proof_cli.StampedLedger@21e8828a11
  - cosa.repo.duplicate_check.proof.proof_cli.StampedLedger.settle@1937f8f032
  - cosa.repo.duplicate_check.ledger_merge.version_of@d501e12ccc
  - cosa.repo.duplicate_check.ledger_merge.rotated_files@71d072f032
  - cosa.repo.duplicate_check.ledger_merge.strip_version@470f6f3b4e
  - cosa.repo.duplicate_check.ledger_merge.merge_rotated@e262738bf3
  - cosa.repo.duplicate_check.ledger_reuse.saved_rulings@eca173b739
  - cosa.repo.duplicate_check.ledger_reuse.lookup@0060f8dbd5
---
# Duplicate-check daily ledger

The judge ledger of the daily and baseline runs. It keeps every ruling when Claude Code updates itself, so an update does not make the job judge again what it already judged. It sits beside [[duplicate-check-daily-run]] and [[duplicate-check-proof-command]].

## What it does
- `daily_ledger` opens `judge-ledger.jsonl` in the daily folder and returns a `StampedLedger`. The ledger is bound to the Claude Code path, the backend and the server, with no version in the binding.
- `StampedLedger` writes each new ruling with a `cli` field holding the version that wrote it. A binding line is written as it is.
- `settle` accepts a recorded binding that differs in the version alone and appends the version-free binding as the newest one. Nothing is renamed or rewritten.
- A ruling is read back when its key matches. The key holds the definition and candidate hashes, the prompt version, the model id and the slot, and never the version.

## Rescuing rulings of another model
- `merge_rotated` copies the rulings of every rotated ledger into the live one. A dry run writes nothing. A key keeps its model id and gets a `cli` stamp from its file. The newest version wins a clash. A rotated file is never changed. A file bound to another binary, backend or server is refused before any copy.
- `saved_rulings` indexes a ledger by definition. `lookup` answers from it. It returns the whole ruling when the candidates' text is the same. Otherwise it builds one verdict per candidate, when each has exactly one.
- A reused ruling is never written to the ledger. Each carries the `model` that ruled it, and the run's rows and manifest line name it as `reused_from_model`.

## Don't
- Don't use it for the proof. `proof_ledger` keeps the version in the binding so a measured run never mixes binaries.
- Don't expect the exact key to match across models: the model id is in the key. The reuse lookup below is what lets a Fable ruling answer an Opus run.
- Don't look for `ledger_rotated` in a run file: no ledger is renamed aside any more.
