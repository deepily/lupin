---
capability: reuse-stage-two-run
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_stage2_run.spec_for@3f1a54612d
  - lupin_mcp.reuse_stage2_run.load_plan@84a0149f29
  - lupin_mcp.reuse_stage2_run.ask_old_pairs@937c235001
  - lupin_mcp.reuse_stage2_run.ask_new_pairs@10eb8386ae
  - lupin_mcp.reuse_stage2_run.rows_from_run@8a9e4833ff
  - lupin_mcp.reuse_stage2_run.write_rows@02c5be4914
  - lupin_mcp.reuse_stage2_run.main@e8fe743c84
  - lupin_mcp.reuse_stage2_run.cli@84660494d1
---
# Reuse stage-two run

The labelled-pair driver. It asks both questions about each member's candidates and joins the answers into the rows the fit script reads. [[reuse-stage-two-negatives]] supplies the candidates.

## Plan and spec
- `load_plan` reads the negatives record and checks its hash and format. Each member's candidates are its twins, lexical neighbours and random draws, once each and never the member. The member's own entry text is the need.
- It raises `FrozenInputRefused` for a wrong hash or format, an id not in the index, or a member with no candidate.
- `spec_for` gives the end-to-end engine its spec: the `s2` prefix, the member count and the token estimate.

## Asking
- `ask_old_pairs` asks the old three-way question about the member's candidates only. Each row holds the overlap probability, the malformed reason and whether the candidate went unasked.
- `ask_new_pairs` asks the pair question the same way. Each row holds provides, coverage and score. The pair question is wired to `reuse_pack.pair_ask`, and `DriverRefused` is raised only when `NEW_PAIR_ASK` is `None`.
- Both results are engine-shaped, with a shortlist cut at 0.5 and the nearest rows by rank.

## Rows
- `rows_from_run` joins the two questions for every member that has both. A candidate is labelled true when it is a twin. The malformed reasons are joined, and unasked is true when either question left it unasked.
- `write_rows` runs the fit script's own row check first, then writes the file whole or not at all.

## Command
- `main` runs `status`, `canary`, `approve`, `run` or a rows step. It refuses before creating or sending anything.
- `cli` turns the runner, driver, frozen-input and ledger refusals into one line and exit code 2. Any other error propagates.
