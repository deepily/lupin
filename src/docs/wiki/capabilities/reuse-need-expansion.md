---
capability: reuse-need-expansion
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - lupin_mcp.reuse_expansion.ask_model@87c1f1f8b1
  - lupin_mcp.reuse_expansion.make_expander@24aab46aa1
---
# Reuse need expansion

The optional first step of a candidate lookup. One text-only model call rewrites the need as paraphrases and identifier words. The candidate stage searches them too ([[candidate-stage]]).

## What it does
- `make_expander( ask=None, model=None, out=print )` returns the function the stage calls for each lookup. It takes the ranking text and returns `{ paraphrases, identifiers }`: three paraphrases and one to five identifier words.
- The model sees the need sentence and nothing else. Tools are off and no repository file is read. The prompt and the reader are `expansion_replay`'s, so a live lookup asks what the measured replay asked.
- A failed call, a spent cap or a reply of the wrong shape returns None after one line to `out`. The lookup then runs as it would without expansion.
- `ask_model( model, system, user )` sends the prompt on a worker thread of its own. It is safe inside the lookup's running event loop. It raises `ModelCallError` or `CallBudgetExceeded` when the call fails.
- With no `ask`, the model is `model`, else the INI key `reuse candidate need expansion model` read when the expander is built (`claude-opus-5-5`). It is the expander's own key and the drafter's key (`reuse need drafter model`) is left alone, so the checker-differs-from-drafter rule does not touch it. There is no model id in the code. The 5 Nov replay's expansions came from Fable.

## Where it is switched on
- The INI key `reuse candidate need expansion enabled` turns it on, and it ships `true`. With it off the stage is built with no expander and nothing changes.
- The key `reuse candidate need expansion protected head` is read only when the switch is on. See [[repo-tools-candidate-storage-paths]].
- The expansion and the protected head are recorded in the receipt's `candidate_stage` block. A replay and a widening reuse them and call no model. See [[reuse-need-check-and-stage-client]].

## Don't
- Don't call `make_expander` from a replay. A replay passes the recorded expansion, and the stage never asks the expander with `cache_only`.
- Don't send anything but the need sentence to the model.
