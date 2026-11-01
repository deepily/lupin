---
capability: semdup-proof-flag-items
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.semdup.proof.flag_items.owed_pairs@c0798914e4
  - cosa.repo.semdup.proof.flag_items.label_id_defs@7301c7ae71
  - cosa.repo.semdup.proof.flag_items.build_flag_items@1f03ba7ca1
  - cosa.repo.semdup.proof.flag_items.stage@970d02a46e
  - cosa.repo.semdup.proof.flag_items.packet_lines@330c41c3d1
  - cosa.repo.semdup.proof.flag_items.rows_sha@533b8f3128
  - cosa.repo.semdup.proof.flag_items.sha_of@4594631e0b
  - cosa.repo.semdup.proof.flag_items.tail_state@f0b853c780
  - cosa.repo.semdup.proof.flag_items.verify@1e02f0bebc
  - cosa.repo.semdup.proof.flag_items.swap@2718ef7d21
  - cosa.repo.semdup.proof.flag_items.discard@f2be8d9100
  - cosa.repo.semdup.proof.flag_items.main@d2b75fb97f
---
# Duplicate checker proof: the owed flag pairs

An unofficial run lists in `owed` the pairs the checker flagged that no reviewer labelled. This command adds them to the labelling run as new items. It sits beside [[semdup-proof-command]], whose pool it reuses.

## What it does
- Run `python -m cosa.repo.semdup.proof.flag_items --run-dir <run> --record <proof-unofficial/N.json> [--check]`. `--check` stages and verifies, then removes the staged files.
- It builds the pool as the proof does, so each item holds the definition the proof judged. A monolith side made over as new keeps its original id (`label_id_defs`).
- Items come from `label_prep.pair_item`. Each key row has kind and stratum `flag`, which `monolith_spec` and `load_run` ignore.
- `stage` writes `*.flags-new` copies of the key and both packets, and `verify` checks them. `packet_lines` puts the new items in one reviewer's order. Original bytes and rows must be unchanged, and new lines in blind form.
- `swap` then replaces the packets first, in reviewer order, and the key last. The output holds the sha of the original rows and packet bytes, before and after, made by `rows_sha` and `sha_of`.

## Interrupted swap
- A crash between the replaces leaves packets with the new items and a key without their rows.
- A re-run finishes it. `tail_state` skips a packet whose last lines are the new items, and the output lists it under `recovered`.
- A packet with only some of the items, or with them away from its end, is refused.

## Reviewers
- The new items sit at the end of each packet as one group, in a seeded order per reviewer (seed `<run seed>|flags|<reviewer>`).
- That position is all a reviewer can see about them, because the items carry no verdict, stratum, kind or reason.
- Both reviewers must label them: `resolved_labels` lists them as unlabelled until they do.

## Don't
- Don't run it after the second reviewer has labels. It also refuses a pair already in the key or a definition missing from the pool.
