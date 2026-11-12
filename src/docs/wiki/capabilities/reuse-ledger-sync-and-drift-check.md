---
capability: reuse-ledger-sync-and-drift-check
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_ledger_sync.LedgerDrift@f10299888b
  - lupin_mcp.reuse_ledger_sync.check_drift@6e320e49ac
  - lupin_mcp.reuse_ledger_sync.sync@ce22b8ba5c
  - lupin_mcp.reuse_ledger_sync.repo_root@e70045a1ab
  - lupin_mcp.reuse_ledger_sync.check_repo@6925117bb7
  - lupin_mcp.reuse_ledger_sync.main@b69554e549
---
# Jev ledger sync and drift check

`lupin_mcp.reuse_ledger_sync` makes the INI key `external repo <name> jev token limit` the single source of a repo's Jev limit. It writes the ledger's limit row from the key and fails loud when the two differ. It sends nothing. The ledger itself is in [[reuse-token-ceiling-and-spend-ledger]]; the key is read by [[repo-tools-code-health-settings]].

## Rules
- `sync` creates a missing ledger with the key's limit, appends a new limit row when the limit differs, and leaves a matching ledger untouched. Earlier limit rows stay in the file. Nobody edits a limit row by hand.
- `check_drift` compares the ledger's latest limit row with the key and raises `LedgerDrift` on any difference, even one token. The message names the key, both numbers and the sync command.
- `check_repo` reads the key through `code_health_settings` and runs the check on the repo's ledger. A blank key is refused with the key named; there is no code default.
- `repo_root` finds lupin's root from the project root and any other repo's from its `external repo <name> path` key, refused when blank with `CodeHealthSettingError`.
- `main` is `python -m lupin_mcp.reuse_ledger_sync sync|check --repo <name>`. Exit 0 done, 1 drift, 2 refused.
- A packed live run on the repo's own ledger runs the check first, in `reuse_tools._packed_settings`. A drifted key refuses the run with `LEDGER_DRIFT` before the ledger admits it.
- A ledger named by `LUPIN_REUSE_LEDGER_PATH` is not checked. A missing ledger is refused later by `begin_run`.
- The installer's onboarding check (step ph1-s7 onward) is not wired yet.
