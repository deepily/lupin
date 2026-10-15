---
capability: rest-services-promotion-gate-ask
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.task_promotion_gate.get_ask_timeout_seconds@5e43dd74e5
  - cosa.rest.task_promotion_gate.get_asynchronous_enabled@22c54357cb
  - cosa.rest.task_promotion_gate.promotion_is_asynchronous@fdc4a00e2f
  - cosa.rest.task_promotion_gate.promotion_precheck@6dac526b8f
  - cosa.rest.task_promotion_gate.approval_from_the_ask@038e62214e
  - cosa.rest.task_promotion_gate.AskOutcome@6219c87a47
  - cosa.rest.task_promotion_gate.PromotionApproval@9158d6e974
  - cosa.rest.task_promotion_gate.answer_posted_by_the_operator@a641340147
  - cosa.rest.task_promotion_gate.describe_who_answered@39dcdb42cd
---
# Promotion gate: precheck, ask and approval

The pieces of the holding-area promotion gate that decide whether to ask the owner and how to read the answer. The overall flow is on [[task-promotion-gate]].

## What it does
- `get_ask_timeout_seconds()` is how long the owner has to answer. It never decides whether the owner is asked. `get_asynchronous_enabled()` is the operator's switch for the asynchronous path and fails closed when absent.
- `promotion_is_asynchronous( requested, enabled_fn )` is true only when that switch is on and the caller passed exactly `True`. Silence, or a non-bool, keeps the synchronous behaviour.
- `promotion_precheck` runs everything decidable without asking. It refuses a caller who is not a manager and has no login account mapped to an approver. It allows an ask-exempt caller, stamped `self`. It returns `None` when the ask must fire, and it fires no ask itself.
- `approval_from_the_ask` asks the owner and reads the answer. Only an answer starting with `yes` allows; a real no, any other answer and a timed-out default all refuse.
- `AskOutcome` carries one answer, a real boolean `default_used`, and `answered_by`, the stamp the server saw.
- `PromotionApproval` is the decision. `authority_suffix` is the text added to the transition's `authority`, empty when nothing was blessed. `reason_with_suffix` appends it to the operator's own reason and never replaces it.
- `answer_posted_by_the_operator( answered_by )` is true only for a `jwt` answer whose account maps to an ask-exempt persona. `describe_who_answered` names the poster in plain words for a refusal.

## Don't
- Don't call `approval_from_the_ask` before `promotion_precheck` returned `None`; it does not re-check credentials.
- Don't pass `ask_fn=None`. A gate with no ask is the failure this module exists to prevent.

## Invariants
- A yes counts only if the server saw it arrive on the operator's own login.
