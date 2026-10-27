---
capability: labelling-pair-labels
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.labelling.pair_labels.build_label@9ca7866a8e
  - cosa.repo.labelling.pair_labels.is_unsure@927c41f6a4
  - cosa.repo.labelling.pair_labels.labels_path@60a1c8e122
  - cosa.repo.labelling.pair_labels.load_items@e365b20857
  - cosa.repo.labelling.pair_labels.now_text@543bdc3430
  - cosa.repo.labelling.pair_labels.progress@5b3d94d6d1
  - cosa.repo.labelling.pair_labels.read_existing@ee5fb8e3f7
  - cosa.repo.labelling.pair_labels.reviewer_of@2f4fa173c2
  - cosa.repo.labelling.pair_labels.same_job@6f6b724e6e
  - cosa.repo.labelling.pair_labels.same_job_labels@c15a304dee
  - cosa.repo.labelling.pair_labels.save_label@5b3fe0a05b
  - cosa.repo.labelling.pair_labels.user_note@479896b83b
---
# Pair labels

How a `semdup_pair` uses the three labelling choices, and the store a reviewer's page writes. The format is in [[labelling-tools]].

## What it does
- `SAME_JOB_OF_CHOICE` fixes the rule. The as-proposed choice means the two definitions do the same job. The none-choice means they do not.
- Symbols stay empty, and the other-choice is never used for a pair.
- Unsure is not a choice. It is the leaning choice plus a note that starts `UNSURE:`. `is_unsure` tests that note and `user_note` strips the prefix.
- `same_job` reads one label as a boolean, and `same_job_labels` reads a whole labels file as `{ item id: bool }`.
- `reviewer_of` and `labels_path` name a packet's reviewer and the `labels-<reviewer>.jsonl` beside it.
- `load_items` reads a packet for display as id, a and b only. `read_existing` reads the labels so far.
- `progress` counts the labels and names the position to resume: the first unlabelled pair, else the first unsure one.
- `build_label` makes one label line, and `now_text` gives its time.
- `save_label` builds the whole file in a temp file, checks it with `read_labels`, and renames it over the old one. A re-answer replaces that pair's line.

## Don't
- Don't append to a labels file. `read_labels` refuses an item labelled twice.

## Invariants
- The labels file passes `read_labels` whenever `save_label` returns, and a failed write leaves the old file as it was. See [[rest-routers-pair-labelling]].
