---
capability: dm-tutor-sentences
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.dm_tutor.sentences.prose_lines@a2c9e1a5d2
  - cosa.agents.dm_tutor.sentences.count_sentences@673af1d0fc
  - cosa.agents.dm_tutor.sentences.over_limit@4ab28a33f4
  - cosa.agents.dm_tutor.sentences.pointer_tokens@1209e9fe55
  - cosa.agents.dm_tutor.sentences.restorable_pointers@6bfc3a1001
  - cosa.agents.dm_tutor.sentences.is_bare_identifier@5feb68a0ed
  - cosa.agents.dm_tutor.sentences.is_bare_row_id@0b1421681c
---
# DM tutor sentence counting

These helpers decide whether a direct message is too long for the tutor ([[dm-tutor-rewrite]]) and which path tokens to put back after a rewrite. Structure such as code and pointer lines does not count as a claim.

## What it does
- `prose_lines` returns the lines that carry claims. Fenced and inline code go first. A bullet or quote marker is stripped and its prose kept.
- `count_sentences` counts those claims. A prose line with no end punctuation still counts as one.
- `over_limit` is the tutor's trigger. It is true only when the body carries more than `limit` claims, three by default.
- `pointer_tokens` returns paths, URLs, bare filenames and row ids found anywhere in a body. The order is first seen and duplicates are dropped.
- `is_bare_identifier` is true for an eight-character hex row id, which tells a reader nowhere to look. It is false for URLs, slashed paths and filenames.
- `restorable_pointers` is `pointer_tokens` minus the bare identifiers. Only this set is restored after a rewrite.
- `is_bare_row_id` asks the same question of a raw string. It is safe on untrusted input and false for `None`.

## Invariants
- None of these raise.
- `pointer_tokens` itself is not narrowed, because the sentence counter shares its pattern.
