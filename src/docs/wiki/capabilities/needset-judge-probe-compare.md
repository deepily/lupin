---
capability: needset-judge-probe-compare
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.judge_probe_read.moves@a18a259bdf
  - lupin_mcp.reuse_needset.judge_probe_read.compare@4798f9de5f
  - lupin_mcp.reuse_needset.judge_probe_read.flips@ff591423cc
  - lupin_mcp.reuse_needset.judge_probe_read.read_cues@d36d8b1000
  - lupin_mcp.reuse_needset.judge_probe_read.proof_of@3a5ef8454e
  - lupin_mcp.reuse_needset.judge_probe_read.analyze@61676fe21c
  - lupin_mcp.reuse_needset.judge_probe_read.splits_of@9c1d328093
  - lupin_mcp.reuse_needset.judge_probe_read.filtered@5306006715
  - lupin_mcp.reuse_needset.judge_probe_read.render@842bd2482d
  - lupin_mcp.reuse_needset.judge_probe_read.parse_args@df58452e1b
  - lupin_mcp.reuse_needset.judge_probe_read.main@ed0e1b133a
---
# Need set: reading the judge probe, comparisons

Scores arm-to-arm comparisons against the mark. The figures are on [[needset-judge-probe-figures]]. It decides no label beyond those the mark defines.

## Comparisons
- `moves` counts pairs that move toward separation between two arms. A not-same plant going from accepted to rejected counts +1, and so does a same-job plant going the other way.
- `compare` scores one comparison on five conditions. D must rise by 0.40, every repeat must agree, and the net must be 2 pairs or more.
- The other two conditions are that same-job acceptance is not lower everywhere, and that the rise exceeds arm 0's spread.
- The label is `worse`, `moved`, `within noise`, `noise-dominated` or `not run`. The comparisons are N (plant line to shaped id), L (shaped id to both lines) and A (baseline to plant line).
- `flips` lists the plants that flip between two arms, per repeat number.
- `proof_of` gives the proof that posts were fresh and separate, and that no arm 0 row was answered with no tokens.
- `analyze` computes every figure from a report. A run with no results returns empty parts, never an error.

## Cues and output
- `read_cues` reads Chloe's tab-separated cue file, one row per pair.
- `splits_of` recomputes N without the name-cue pairs and L without the near-identical-line pairs. A split decides no label.
- `filtered` drops those pairs from the cells.
- `render` writes the analysis as markdown. `parse_args` takes `report`, `cues` and `out`, and `main` prints or writes the read.
