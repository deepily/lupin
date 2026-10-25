---
capability: needset-second-check
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.check.matched_prompt@f878f4a0cd
  - lupin_mcp.reuse_needset.check.none_check_prompt@87b6303a43
  - lupin_mcp.reuse_needset.check.parse_check@cc5d877af3
  - lupin_mcp.reuse_needset.check.prompt_version@f20cdfd0ab
  - lupin_mcp.reuse_needset.check.second_check@e40403fa9d
  - lupin_mcp.reuse_needset.check.disputed@298fb71d20
  - lupin_mcp.reuse_needset.check.check_needs@7cab5a6c9d
---
# Need set: second-model check

A second model checks each drafted need. For a matched need it asks whether the proposed key does the job. For a nothing-exists need it asks whether anything in the search hits does. A need the second model does not agree with is disputed, and people settle every disputed need.

## Prompts
- `matched_prompt` asks whether the proposed key does the job of a need. The need and key sources sit between tags that end in one random suffix found in none of them.
- `none_check_prompt` asks whether nothing in a hit list does the job. Here agree means no listed definition does the job.
- Both ask for one JSON object with a result of agree, disagree or unsure and a one-line note, and nothing else.
- `prompt_version` names the check prompts and the reply parser, so an edit is a new ledger key.

## Reading and running
- `parse_check` accepts a reply only if it is exactly one JSON object with those two fields. An extra field, text around the object or a note over 300 characters returns `None`.
- `second_check` checks one drafted need and returns a copy at status `checked` with the check block. The id, key and sentence are unchanged.
- An unreadable reply is asked again once, and both unreadable raises `UNREADABLE_REPLY`. The reply is stored in the ledger before it is used, so a resume repeats no call.
- A model equal to the drafter's raises `CHECKER_EQUALS_DRAFTER` before any call.
- `disputed` is true when the second model said disagree or unsure.
- `check_needs` checks several needs, up to a parallel limit at once, and returns them in input order. A failure stops the needs not yet started and is raised once those in flight finish.
