---
capability: duplicate-check-proof-ledger-agreement
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.duplicate_check.proof.ledger_agreement.read_ledger@b7a66d6c0e
  - cosa.repo.duplicate_check.proof.ledger_agreement.paired@f5b41167a7
  - cosa.repo.duplicate_check.proof.ledger_agreement.flag_table@05d453f086
  - cosa.repo.duplicate_check.proof.ledger_agreement.kappa@73740b7122
  - cosa.repo.duplicate_check.proof.ledger_agreement.ac1@99971b85f3
  - cosa.repo.duplicate_check.proof.ledger_agreement.positive_negative@e0f5e11081
  - cosa.repo.duplicate_check.proof.ledger_agreement.weighted_kappa@7e2fde8656
  - cosa.repo.duplicate_check.proof.ledger_agreement.exact@be677f1aae
  - cosa.repo.duplicate_check.proof.ledger_agreement.statistics@a367bf5b03
  - cosa.repo.duplicate_check.proof.ledger_agreement.bootstrap@bffb1bfc8d
  - cosa.repo.duplicate_check.proof.ledger_agreement.against_labels@d4c380c8cb
  - cosa.repo.duplicate_check.proof.ledger_agreement.compare@7cc5d070b2
  - cosa.repo.duplicate_check.proof.ledger_agreement.main@23b11c7348
---
# Duplicate checker proof: agreement between two judge ledgers

The proof judges every pair twice with one model. This script compares any two judge ledgers pair by pair, for example Fable against Opus. It sits beside [[duplicate-check-proof-run]], whose ledgers it reads, and makes no model call.

## What it does
- Run `python -m cosa.repo.duplicate_check.proof.ledger_agreement --first <ledger> --second <ledger>`. Add `--first-model`, `--first-slot`, `--second-model` and `--second-slot` to pick one pass out of a ledger that holds several (`read_ledger`).
- A ledger line keys on `semdup|<a>|<b>|<prompt version>|<model id>|<pass>`. A pair is the key without model and pass, plus the candidate. `paired` keeps the pairs ruled in both ledgers and counts the rest.
- A flag is `near_duplicate` or `duplicate`. `flag_table` counts both, first only, second only and neither. `kappa`, `ac1` and `positive_negative` read that table. `weighted_kappa` reads the four levels, and `exact` counts equal verdict words. `statistics` returns all of them.
- `bootstrap` gives each figure a 95% interval by resampling whole definitions, because about ten pairs share one definition. The interval ends come from `percentile`, and the exact McNemar test from `mcnemar_exact`, both imported from `lupin_mcp` rather than rewritten. A draw where a figure is undefined is left out of that figure.
- `compare` returns the figures, intervals and flag table. Given `--labels`, `--pair-map` and `--strata`, `against_labels` also scores both ledgers as the proof does. Recall is over the planted and monolith true pairs, and precision is over labelled flags. `--exclude` drops the plant failures. McNemar's test runs on the pairs where the two flags differ.
- It prints one JSON document. `main` returns 0.

## Reading the label scores
- The label pair map cannot come from the ledger, because a ledger key holds hashes of the texts. It is built by replaying the judge in the tree the proof ran from.
- The McNemar test over all labelled pairs favours the ledger whose flags chose the pairs. The test over the true pairs alone is the fair one.
- Flagged pairs with no label are counted as `unlabelled_flags` and left out of precision.

## Don't
- Don't use `read_ledger` on a ledger holding several passes without `--*-slot`: it refuses a pair ruled twice.
- Don't read a missing interval as zero. `None` means the figure was undefined in every draw.
