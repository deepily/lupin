---
capability: needset-drafter-plumbing
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.draft.drafter_call@3d7248385d
  - lupin_mcp.reuse_needset.draft.make_ledger@e56913d1c7
  - lupin_mcp.reuse_needset.draft.SharedLedger@1aadd4a4ed
  - lupin_mcp.reuse_needset.draft.ask_ledgered@bec0020e1d
  - lupin_mcp.reuse_needset.draft.prompt_version@69de92e0ce
  - lupin_mcp.reuse_needset.draft.parse_reply@7b25e811f4
  - lupin_mcp.reuse_needset.draft.stripped_input@1728603449
  - lupin_mcp.reuse_needset.draft.leak_check@ffc5213853
  - lupin_mcp.reuse_needset.draft.rewrite_request@4f32cd3143
---
# Need set: drafter plumbing

The parts of drafting that send one prompt, check the reply and keep a ledger. Every model call goes through a ledger, so a stopped run resumes without repeating a call. The drafting flows are on [[needset-drafting-flows]].

## Sending
- `drafter_call` builds the function that sends one system and user prompt to the drafter and blocks until the reply arrives. It must not be called from a running event loop.
- `make_ledger` opens the drafting ledger, bound to the Claude Code binary's reported version, or `bundled` for the SDK's own binary, and then the server label. A ledger written under another binary or label is refused.
- `SharedLedger` is a ledger several threads may read and write, with one lock per call.
- `ask_ledgered` asks the drafter once, or reads the ledger's answer to the same question. The key holds the text, prompt, version, model and slot.
- `prompt_version` names the prompt the drafter sends, so a change to it is a different version. It covers the system template, the two prompt builders, the rewrite note and the reply parser.

## Reading and checking
- `parse_reply` reads the one sentence out of a reply. It trims quotes and ticks and collapses whitespace. An empty reply, a reply of more than one line or one with a code fence returns `None`.
- `stripped_input` turns a stripped member into the input the need writer's prompt builder reads.
- `leak_check` runs the need check on a sentence against the seed and every key symbol. It returns the failures: form, identifier, member text run and twin text run. An empty list means the sentence may go to the second model.
- `rewrite_request` turns leak failures into what the writer may be told. It returns the failure kinds and bare lower-case words the sentence used, and never the failure details, which can name a key symbol.
