---
capability: rest-services-promotion-cards-and-deadlines
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.task_promotion_gate.promotion_ask_text@889551c42c
  - cosa.rest.task_promotion_gate.promotion_ask_sender_id@363bce682e
  - cosa.rest.task_promotion_gate.promotion_ask_kwargs@1394a6018a
  - cosa.rest.task_promotion_gate.unpark_ask_text@dcbe458307
  - cosa.rest.task_promotion_gate.unpark_ask_payload@31b9a50542
  - cosa.rest.task_promotion_gate.approval_card_id@68c79a46e2
  - cosa.rest.task_promotion_gate.unpark_card_refusal@9bb106915f
  - cosa.rest.task_promotion_resolver.get_notification_grace_seconds@f5e2eea04b
  - cosa.rest.task_promotion_resolver.resolves_by_for@ed57e15480
  - cosa.rest.task_promotion_resolver.PromotionDeadlines@5d8bb5f1ca
  - cosa.rest.task_promotion_resolver.deadlines_for@15729698e8
  - cosa.rest.task_promotion_resolver.TransitionIntent@5ddd51d918
  - cosa.rest.task_promotion_resolver.sweep_stalled_tickets@a952d81028
---
# Promotion ask cards, un-park cards and ticket deadlines

The text and arguments of the owner's yes/no card, the un-park card check, and the deadlines that decide when a pending promotion ticket is orphaned. Gate decisions are in [[rest-services-promotion-gate-ask]].

## What it does
- `promotion_ask_text( actor, task_id, title, move )` returns `( question, abstract )`. The question names the row by title and never carries the id, which a voice would spell out. The abstract has the id and ends with the silence rule.
- `promotion_ask_sender_id( session_id )` names the requesting session, or a `promotion-gate` sender when there is none.
- `promotion_ask_kwargs` is every argument the ask fires with. Its answer default is no, and `human_only=True` keeps the auto-answer proxy from answering for the owner.
- `unpark_ask_text` and `unpark_ask_payload` build the un-park card and its `{ kind, task_id, move }` binding.
- `approval_card_id( receipt_refs )` returns the cited `approval_card` as a UUID, or `None`.
- `unpark_card_refusal( card, task_id, parked_since, used_card_ids )` returns `None` only when a person answered yes on the operator's login and the card names this row. The card must also be newer than the park and unused by any earlier transition.
- `deadlines_for( requested_at, timeout_fn, grace_fn )` returns a `PromotionDeadlines` with `answer_by` (the ask timeout) and `resolves_by` (answer window plus notification grace plus apply margin). `resolves_by_for` gives the second alone, and `get_notification_grace_seconds` reads the grace.
- `TransitionIntent` is the stored shape of a caller's transition; `as_payload` and `from_payload` convert both ways. Account identity is not stored.
- `sweep_stalled_tickets` marks pending tickets past their stored `resolves_by` as stalled and returns their ids.

## Don't
- Don't re-derive a deadline from today's config; the sweeper uses the value stored on the row.

## Invariants
- `deadlines_for` reads the ask timeout once, so both stamps come from one value.
