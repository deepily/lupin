---
capability: reuse-stage-two-negatives
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_stage2_negatives.words@a6020a00c2
  - lupin_mcp.reuse_stage2_negatives.surface_words@6b638797aa
  - lupin_mcp.reuse_stage2_negatives.package_of@525c2a875f
  - lupin_mcp.reuse_stage2_negatives.jaccard@8ebdcc9d9e
  - lupin_mcp.reuse_stage2_negatives.lexical_negatives@1afcb85f88
  - lupin_mcp.reuse_stage2_negatives.old_random_by_member@f4834ada8f
  - lupin_mcp.reuse_stage2_negatives.select_negatives@5be6e214f2
  - lupin_mcp.reuse_stage2_negatives.main@1c381ec9c1
---
# Reuse stage-two negatives

Picks look-alike non-twins for each member of a twin group, for the labelled-pair run. No model chooses and nothing is sent anywhere, so the selection cannot favour either question. [[reuse-stage-two-run]] consumes the record.

## Word overlap
- `words` splits text into lower-case identifier words at underscores, dots, digits and case changes. A run of capitals such as HTTP is one word. Words under three characters, digits and stop words are left out.
- `surface_words` takes the words of a symbol's own name, signature and first docstring line, never its path.
- `jaccard` is the size of the intersection over the size of the union of two word sets, or 0.0 when both are empty.
- `package_of` is the first two dotted parts of an id. A shorter id is its own package.

## Choosing
- `lexical_negatives` picks up to `n` neighbours of one member from the same language and package. They exclude the member and its twins, and need an overlap above zero and below 0.9.
- Neighbours at or above 0.9 are held out for a person to read, since they may be true twins the manifest missed. There is no top-up from another package, so a small package gives a short list.
- `old_random_by_member` reads the random negatives the first labelled run drew, leaving out twins and repeats.
- `select_negatives` keeps each member's old random draws that are still in the index and below the bar. It adds up to 25 lexical neighbours and does not depend on input order. An unknown member or twin raises `ValueError`.

## Writing
- `main` reads the manifest, symbols and the first run's pairs, screens the symbols through `sendable`, and writes the record. The record holds the input hashes, constants and summary.
- It raises `FileExistsError` if the output exists, so a recorded selection is never overwritten.
