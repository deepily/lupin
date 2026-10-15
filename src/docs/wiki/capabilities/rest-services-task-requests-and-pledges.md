---
capability: rest-services-task-requests-and-pledges
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.task_request_lifecycle.is_terminal@c069f10b84
  - cosa.rest.task_request_lifecycle.grants_the_move@72d3de2469
  - cosa.rest.task_request_lifecycle.requires_a_refile@fa2721a0a6
  - cosa.rest.task_request_lifecycle.refusal_for_verdict@c9c784a932
  - cosa.rest.task_request_lifecycle.refusal_for_filing@5994ee09ad
  - cosa.rest.task_request_lifecycle.request_is_stale@3a9be49bba
  - cosa.rest.task_request_lifecycle.refusal_for_refiling@b2bef8d252
  - cosa.rest.task_request_lifecycle.badge_for_move@2375f36714
  - cosa.rest.task_request_lifecycle.badge_counts@d1777c96aa
  - cosa.rest.task_request_pledge.pledge_is_dead@50a4c6160a
  - cosa.rest.task_request_pledge.pledge_changed_hands@ad816546fb
  - cosa.rest.task_request_pledge.request_is_stranded_by_its_pledge@5064439671
  - cosa.rest.task_request_pledge.refusal_for_consuming_pledge@613e5c4e2a
---
# Task requests and deletion pledges

A manager files a request to admit a held row or demote a live one, and the operator answers it. With the pledge switch on, an admit also names a ticket the requester owns, which is dropped to pay for it. See [[task-promotion-gate]] and [[task-store]].

## What it does
- A request is `pending`, `approved` or `denied`. `is_terminal` is true for the last two. `grants_the_move` is true only for `approved`. `requires_a_refile` is true only for `denied`.
- `refusal_for_verdict( state, verdict, actor_is_operator )` returns `None` only when the operator records approved or denied on a pending request. The three refusals are not the operator, already answered, and not a verdict.
- `refusal_for_filing( move, current_status )` allows `admit` only out of the holding area and `demote` only from a live status. `refusal_for_refiling` refuses a second filing while one is pending.
- `request_is_stale` is true for a pending request whose move can no longer be filed against the row's new status. An answered request is never stale.
- `badge_for_move` maps demote to the task-area badge and admit to the holding-area badge, and raises for any other move. `badge_counts( requests )` counts pending requests per badge and always returns both keys.
- `pledge_is_dead( pledge_status )` is true when the pledged row is gone or terminal. `pledge_changed_hands( owner, pledged_by )` is true when the owner differs, or when no pledger was recorded.
- `request_is_stranded_by_its_pledge` is true for a pending admit whose pledge is dead or changed hands, so the manager may re-file it.
- `refusal_for_consuming_pledge` answers `( 409, detail )` for a dead or reassigned pledge, so approval never admits unpaid.

## Don't
- Don't add a clock to the lifecycle functions. Silence never grants and never denies.

## Invariants
- Approval admits the target and drops the pledged row in one transaction, or neither happens.
