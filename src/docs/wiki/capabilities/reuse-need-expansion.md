---
capability: reuse-need-expansion
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_expansion.ask_model@87c1f1f8b1
  - lupin_mcp.reuse_expansion.make_expander@472fc6770a
---
# Reuse need expansion

The optional first step of a candidate lookup. One text-only model call rewrites the need as paraphrases and identifier words. The candidate stage searches them too ([[candidate-stage]]).

## What it does
- `make_expander( ask=None, model=EXPANSION_MODEL, out=print )` returns the function the stage calls for each lookup. It takes the ranking text and returns `{ paraphrases, identifiers }`: three paraphrases and one to five identifier words.
- The model sees the need sentence and nothing else. Tools are off and no repository file is read. The prompt and the reader are `expansion_replay`'s, so a live lookup asks what the measured replay asked.
- A failed call, a spent cap or a reply of the wrong shape returns None after one line to `out`. The lookup then runs as it would without expansion.
- `ask_model( model, system, user )` sends the prompt on a worker thread of its own. It is safe inside the lookup's running event loop. It raises `ModelCallError` or `CallBudgetExceeded` when the call fails.
- `EXPANSION_MODEL` is the model the measured replay's expansions came from.

## Where it is switched on
- The INI key `reuse candidate need expansion enabled` turns it on, and it ships `false`. With it off the stage is built with no expander and nothing changes.
- The key `reuse candidate need expansion protected head` is read only when the switch is on. See [[repo-tools-candidate-storage-paths]].
- The expansion and the protected head are recorded in the receipt's `candidate_stage` block. A replay and a widening reuse them and call no model. See [[reuse-need-check-and-stage-client]].

## Don't
- Don't call `make_expander` from a replay. A replay passes the recorded expansion, and the stage never asks the expander with `cache_only`.
- Don't send anything but the need sentence to the model.
