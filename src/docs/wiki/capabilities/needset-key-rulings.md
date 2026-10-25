---
capability: needset-key-rulings
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.keys.cut@897fbfc7c6
  - lupin_mcp.reuse_needset.keys.same_job_prompt@b18a1cd240
  - lupin_mcp.reuse_needset.keys.parse_choice@6511026869
  - lupin_mcp.reuse_needset.keys.ruled@f23de250e1
  - lupin_mcp.reuse_needset.keys.confirm_same_job@c4b92fefa0
  - lupin_mcp.reuse_needset.keys.find_key@56003651cb
  - lupin_mcp.reuse_needset.keys.absence_evidence@a71903c053
  - lupin_mcp.reuse_needset.keys.absence_prompt@82067ccc29
  - lupin_mcp.reuse_needset.keys.absence_verdict@c114fc3094
---
# Need set: key rulings

Asks a model whether a neighbour does the seed's job, and whether anything does a nothing-exists need's job. Neighbour lists are on [[needset-key-neighbours]]. Every ruling is stored in a ledger before it is returned.

## Same-job rulings
- `cut` leaves a definition unchanged up to 6000 characters. Above that it keeps the first 6000 and adds a note of the cut.
- `same_job_prompt` asks whether two definitions do the same job. Each sits between tags that end in one random suffix found in neither text, so a body cannot close its own section.
- `parse_choice` returns yes or no only when the reply is exactly one JSON object holding that field with one of those values. Anything else returns `None`.
- `ruled` gets one yes or no ruling, from the ledger when it was asked before. An unreadable reply is asked again once, and two unreadable raise `UNREADABLE_REPLY`.
- `confirm_same_job` asks whether the seed and another definition do the same job.
- `find_key` asks about the candidates in order and stops at the first yes. It returns the key or `None`, the route, how many candidates were ruled on, and their sources.

## Absence
- `absence_evidence` lists what the index's word search and vector search find for a capability, up to a given number of ids each, best first. The word list fuses the code and prose word searches as the shortlist stage does.
- `absence_prompt` asks whether any listed definition does a job, again between random-suffix tags.
- `absence_verdict` rules on a nothing-exists need. One yes from the second model rejects it, and the remaining lists are not asked.
