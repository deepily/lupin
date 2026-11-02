---
capability: needset-expansion-replay
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.expansion_replay.expansion_prompt@73ce117187
  - lupin_mcp.reuse_needset.expansion_replay.parse_expansion@1e40dd7c56
  - lupin_mcp.reuse_needset.expansion_replay.queries_for@23c07cab3d
  - lupin_mcp.reuse_needset.expansion_replay.expand_need@9269fceb15
  - lupin_mcp.reuse_needset.expansion_replay.union_rank@4b196ef066
  - lupin_mcp.reuse_needset.expansion_replay.replay@806255e01e
  - lupin_mcp.reuse_needset.expansion_replay.summarize@73899e66c4
---
# Need set: expansion replay

A draft, not yet run. It asks whether three paraphrases and five identifier words lift a known answer in the search. It takes the model and the search as arguments and makes no call of its own. The trace it compares against is [[needset-loss-trace]].

## Expanding
- `expansion_prompt` holds the need sentence and nothing from the code, so the key cannot leak into the reply.
- `parse_expansion` accepts three paraphrases and one to five identifier words, and returns None for any other shape.
- `expand_need` asks once and saves the reply before reading it, so an unreadable reply is not paid for twice.
- `queries_for` lists five searches: the need, the three paraphrases, then the identifier words joined into one.

## Ranking
- `union_rank` fuses the lists of the first search for the rank before, and every list of every search for the rank after. It also says whether each rank is inside the 128 shortlist.
- `replay` does this for each need, and a row with an unreadable reply is marked and never searched.
- `summarize` counts per group how many answers entered the shortlist before and after, were lifted or lowered, or had no readable reply.
