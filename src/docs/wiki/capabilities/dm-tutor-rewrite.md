---
capability: dm-tutor-rewrite
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.dm_tutor.agent.DmTutorAgent@0df11d62f4
  - cosa.agents.dm_tutor.agent.rewrite_dm@e214cc20a9
  - cosa.agents.dm_tutor.xml_models.DmTutorResponse@188ffffb85
  - cosa.agents.dm_tutor.tutor.build_prompt@37c8633209
  - cosa.agents.dm_tutor.tutor.extract@f146983f4e
  - cosa.agents.dm_tutor.tutor.rewrite_to_form@321ad34eb6
  - cosa.agents.dm_tutor.tutor.gate@d4640f96ed
  - cosa.agents.dm_tutor.tutor.literal_violations@c786d87524
  - cosa.agents.dm_tutor.tutor.attribution_bindings@01ede89dc5
  - cosa.agents.dm_tutor.tutor.attribution_violations@5aabd29202
---
# DM tutor rewrite

The tutor rewrites a long direct message into a fixed form: a headline, two supporting sentences and a canned P.S. It asks for a form, not a size ratio. Sentence counting is in [[dm-tutor-sentences]].

## What it does
- `rewrite_dm` is the entry point for the send path. It returns the distilled lines, or `None`, and never raises. `None` means deliver the original.
- `DmTutorAgent` is the `AgentBase` agent behind it. It makes one model call and does no synchronous retry.
- `DmTutorResponse` carries `thoughts`, a declaration or question, two supporting statements and a path or URL. The XML tags are hyphenated and the fields use underscores.
- `build_prompt` places the body between two fence markers. `extract` returns the text between the markers, or `None` when one is missing.
- `rewrite_to_form` returns `(delivered, error, attempted)`. A body already at or under the sentence limit is left alone with an "under limit" error.
- `attempted` keeps the model's rewrite even when the gate rejects it, so a rejection can be judged.
- `gate` returns `(ok, reason)`. It checks the form and the literals, and has no minimum-saving rule.
- `literal_violations` lists literals that appear more often than they were sent, or were never sent. A dropped literal is legal.
- `attribution_bindings` finds each name bound to a speech-act verb. `attribution_violations` returns names the rewrite binds that the original did not.

## Don't
- Don't use the rewrite when `rewrite_dm` returns `None`. The original is the safe answer.
- Don't expect the gate to catch a literal moved to the wrong claim. It catches omission and mutation only.
