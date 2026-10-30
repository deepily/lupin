---
capability: semdup-proof-label-loader
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.semdup.proof.label_load.key_rows@18eed9d6c1
  - cosa.repo.semdup.proof.label_load.pair_key_labels@83ea19795a
  - cosa.repo.semdup.proof.label_load.third_votes@ce4a654a08
  - cosa.repo.semdup.proof.label_load.disputed_items@61090437b8
  - cosa.repo.semdup.proof.label_load.resolved_labels@b1c6e6ae2b
---
# Duplicate checker proof: the label loader

Turns the reviewers' pair labels and the answer key into the `{ pair key: bool }` that `proof_run` takes. The packets and key come from [[semdup-proof-label-packets]]; the label rule is in [[labelling-pair-labels]].

## What it does
- `key_rows` reads the item rows of the answer key.
- `pair_key_labels` turns one reviewer's labels file into `{ pair key: bool }`, with the key written as `label_key` writes it. An unsure label counts at its leaning choice.
- `pair_key_labels` refuses labels for an item the key does not know.
- `resolved_labels` settles every pair from two reviewers with `resolve_label`. A third rater's file may settle each disagreement; that rater labels only the disputed pairs.
- `disputed_items` lists the items the two reviewers labelled differently. `third_votes` turns the third rater's file into votes on them, and an unsure label is a vote of `None`.
- A sure third label outranks a ruling. An unsure one leaves the pair to the ruling, passed in as `{ pair key: bool }`.

## Don't
- Don't start a proof run on one reviewer's labels. `resolved_labels` names the pairs either reviewer has not labelled, and the disagreements that have no ruling, and returns nothing until both are settled.
