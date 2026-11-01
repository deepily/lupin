---
capability: needset-hardness
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.hardness.build_index@a8f7d67401
  - lupin_mcp.reuse_needset.hardness.rank_of@391d06e0ee
  - lupin_mcp.reuse_needset.hardness.is_hard@e5d0ced136
  - lupin_mcp.reuse_needset.hardness.source_hard@1186524685
  - lupin_mcp.reuse_needset.hardness.yield_report@d2712a011a
---
# Need set: hardness

Finds real code that a plain word search misses. A work-alike seed for Set B counts only when a BM25 search over identifiers and docstrings does not list it in its top 10. Nothing is planted and no pair is mined.

## Measuring
- `build_index` builds the BM25 index over the id, module, name, signature and docstring fields.
- `rank_of` gives the 1-based position of a target in the search for a need, with excluded ids removed first. It gives none when the target is not listed.
- `is_hard` is true for an unlisted target or one ranked below the cut-off, which is 10.

## Sourcing
- `source_hard` measures each candidate row `{ seed, need, targets, lang }`. The seed is left out of the ranking, as the checker leaves it out. A row is hard only when every target is missed, and its missed targets are listed.
- A row with no targets raises `BAD_NEED`. A row whose seed is one of its own targets raises `SEED_IS_TARGET`.
- `yield_report` counts the hard rows per language and gives the hard rows per 100 seeds. That is the natural yield the plan measures before it sizes the set.
