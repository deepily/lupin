---
capability: semdup-proof-command
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.semdup.proof.proof_cli.load_run@a22e18d0ab
  - cosa.repo.semdup.proof.proof_cli.monolith_spec@dd3b46a501
  - cosa.repo.semdup.proof.proof_cli.check_originals@18cf7cbebe
  - cosa.repo.semdup.proof.proof_cli.plant_failures@04b771fe12
  - cosa.repo.semdup.proof.proof_cli.rewrite_sources@73c700fda3
  - cosa.repo.semdup.proof.proof_cli.staged_name@9954b3a871
  - cosa.repo.semdup.proof.proof_cli.stage_pool@814d647043
  - cosa.repo.semdup.proof.proof_cli.check_found@ace172d09d
  - cosa.repo.semdup.proof.proof_cli.staged_pairs@32885ab64f
  - cosa.repo.semdup.proof.proof_cli.structural_source@c48304283b
  - cosa.repo.semdup.proof.proof_cli.build_spec@e9b1f4cf2b
  - cosa.repo.semdup.proof.proof_cli.label_state@4f0ff0beb7
  - cosa.repo.semdup.proof.proof_cli.unofficial_state@87cba5dc3c
  - cosa.repo.semdup.proof.proof_cli.live_parts@80c9d8e35a
  - cosa.repo.semdup.proof.proof_cli.proof_ledger@de8052782c
  - cosa.repo.semdup.proof.proof_cli.main@26a968d594
  - cosa.repo.semdup.proof.proof_cli.json_stdout@8fc89b4c01
---
# Duplicate checker proof: the command

Builds `proof_run`'s spec and wiring from a labelling run folder, then checks them (`--check`) or runs the proof once. The run folder comes from [[semdup-proof-label-packets]] and [[semdup-proof-label-planting]]; the labels from [[semdup-proof-label-loader]]; the run itself is [[semdup-proof-run]].

## What it does
- `load_run` reads `key/planted.json` and `key/answer-key.json`. `monolith_spec` turns the key's monolith items into pairs, and names any id the pinned monolith does not define.
- `check_originals` refuses a tree whose planted originals changed since planting. `build_spec` assembles the spec and calls it.
- `plant_failures` lists the planted pairs both reviewers labelled False; a pair either has not labelled is not one. `label_state` reads the two labels files, and a third rater's file when given, and says what is still owed. `unofficial_state` does the same for the one file of an unofficial run.
- `rewrite_sources` finds each rewrite's file under `key/rewrites/<NNN>/`. `stage_pool` copies the pool into one temporary tree: server and monolith files under `tree/`, each rewrite under `proof-new/<NNN>/`, so a rewrite never overwrites its original.
- `staged_pairs` finds the structural clone pairs of the whole pool in that tree and maps them back to pool ids. It hands dups every staged definition, because dups numbers a repeated name `~2` before the node cut. It keys a staged definition by file and line span, not name, because a class-member rewrite is recorded as `destroy` but extracted as `PlantedWrapper.destroy`. `check_found` raises if a pool definition is missing from the staged tree.
- `structural_source` caches `staged_pairs` by the pool's ids, so the second slot stages nothing. `live_parts` wires the real tree and writes nothing; `main` is the command.
- `proof_ledger` makes the record folder and the judge ledger, bound with `judge.ledger_binding`. The folder is the proof's own unless an unofficial run names one. Only a real run calls it, and a real run needs `--claude-cli-path`.
- `main` prints its JSON through `json_stdout`, and banners go to stderr, so `json.loads` of stdout works. The owed flag pairs are added by [[semdup-proof-flag-items]].

## Don't
- Don't run without `--check` first; it prints the pool, pair and label counts, makes no model call and writes nothing.
- Don't give `main` a run folder planted under another `config_sha`; it refuses.
