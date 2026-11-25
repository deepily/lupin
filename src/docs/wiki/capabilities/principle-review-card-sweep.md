---
capability: principle-review-card-sweep
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.principle_learner.extractor_prompt.extractor_version_of@229a644ae0
  - cosa.agents.principle_learner.review_card_sweep.DetachedDispatcher@925b395a5b
  - cosa.agents.principle_learner.review_card_sweep.ReviewCardSweepJob@1a77fd8ae2
  - cosa.agents.principle_learner.review_card_sweep.apply_splits@0a141941b9
  - cosa.agents.principle_learner.review_card_sweep.contested_items@e677e6d9c9
  - cosa.agents.principle_learner.review_card_sweep.forget_sends@5b87617af1
  - cosa.agents.principle_learner.review_card_sweep.sweep_job_after@94e182895e
  - cosa.agents.principle_learner.review_card_sweep.sweep_review_cards@231c177354
---
# Principle review card sweep

Finds the owner's contested principles and sends one card, within the cap. The extractor stays silent, so this is a separate job the queue runs right after an extractor job ([[principle-extractor-job]]). Card rules are in [[principle-review-cards]].

## What it does
- `sweep_review_cards` splits first. A contested principle a card feature can separate is split, and no card is sent for it.
- Then it sends one batched card for the rest, unless the cap is reached or nothing is contested. It returns the split, contested, sent, deferred and sent-in-window counts.
- A card counts against the cap when it is sent, not when it is answered. The send is also recorded in this process, so a sweep that runs again before the card is stored sees it.
- `forget_sends` clears that record, so the next sweep counts only cards found in the database.
- `apply_splits` adds two evidence rows for each split, with source `split_step`. One refines with the supporting side's condition and one contradicts with the other side's. Existing rows are never changed.
- `contested_items` builds one item per contested principle: the statement and the owner's earliest supporting and contradicting answers. A principle already on a recent unanswered card is left out.
- `DetachedDispatcher` wraps a dispatcher so `present_choices` starts the real call on a daemon thread and returns None at once. A failure is printed and swallowed.
- The answer door, not this call, records the ruling when the owner answers.
- `extractor_prompt.extractor_version_of( model, tags )` names the extractor version as `<model>:<prompt version>`, with `+<tag>` added for each tag. With no tags it is the plain version. The sweep asks for `current_extractor_version`, so it reads the rows the extractor writes under the live switches ([[principle-extractor-prompt-and-rules]]).
- `ReviewCardSweepJob` runs the sweep as a job of its own. It reads the cap, the extractor model and the wait from the INI file when it runs.
- `sweep_job_after( extractor )` builds the sweep job for the same owner. `last_question_asked` shows `[Review card sweep]` and the owner's id.
