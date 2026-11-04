---
capability: dm-compression-pipeline
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.dm_compression.pipeline.compress_dm@343e1ffe61
  - cosa.agents.dm_compression.compressor.DmCompressionAgent@e95e554bc9
  - cosa.agents.dm_compression.xml_models.DmCompressionResponse@0774de615f
---
# DM compression pipeline

`compress_dm` shortens one direct message body, or hands it back unchanged. It joins the freeze protocol ([[dm-compression-freeze]]) to a rewriting agent. Any path that is not a clean success delivers the original.

## What it does
- `compress_dm` freezes the body, asks the agent for a rewrite, validates it, restores the literals and returns `(text, fallback_reason)`. The reason is `None` only when a compressed body is delivered.
- A body the freeze step marks as bypass goes back unchanged with a `bypass:` reason, and no model is called.
- A model error, an empty answer or a failed validation each give the original and a reason. The function never raises.
- A rewrite that saves less than five percent of the length is also dropped, because a longer or equal message only adds delay.
- `agent_factory` lets a caller inject a stand-in. It takes the frozen text and returns an object with `run_prompt`.
- `DmCompressionAgent` is an `AgentBase` agent that sends one frozen body to the model. It does no synchronous retry.
- `band_target` adds a line to the prompt naming a target reduction and word count for that message.
- `DmCompressionResponse` holds `thoughts` and `compressed`. An empty compressed body is rejected, which puts the message on the fallback path.

## Don't
- Don't give the agent an empty `frozen_text`. It raises `ValueError`.
- Don't build the prompt with `str.format`. Bodies carry literal braces, so the agent substitutes with `replace`.
