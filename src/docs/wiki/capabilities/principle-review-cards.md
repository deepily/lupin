---
capability: principle-review-cards
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.principle_learner.review_cards.review_card_cap@8f614eef47
  - cosa.agents.principle_learner.review_cards.split_step@93263afe0c
  - cosa.agents.principle_learner.review_cards.resolve_conflict@78402458d5
  - cosa.agents.principle_learner.review_cards.cards_in_window@2b2872cb18
  - cosa.agents.principle_learner.review_cards.plan_card@f73a22a780
  - cosa.agents.principle_learner.review_cards.build_card@e8e6489d60
  - cosa.agents.principle_learner.review_cards.send_review_card@afca357cc1
  - cosa.agents.principle_learner.review_cards.review_card_times@6a555e44e1
  - cosa.agents.principle_learner.review_cards.record_card_answer@abc6290677
---
# Principle review cards

How a contested principle goes to its owner, and how the answer becomes a ruling. The card carries the review-card marker, so it is never forecast, never read by the extractor and never stored as a case. The job that sends it is in [[principle-review-card-sweep]].

## Deciding what to ask
- `split_step( side_a, side_b )` looks for a card feature that separates two sets of supporting episodes. A feature separates them when every episode has it and no value occurs on both sides.
- It returns the first such feature in name order, with a condition for each side. A condition reads `<feature> is <value>`. It returns None for an empty set or when no feature separates.
- `resolve_conflict` returns a split when a feature separates the sets. Otherwise the principle is contested and goes to the owner. Nothing is written here.
- `review_card_cap` reads the number of cards one owner may be sent in a rolling 24 hours. A missing key raises.
- `cards_in_window( sent_times, now )` counts cards sent in the 24 hours ending now. A card sent exactly 24 hours ago no longer counts.
- `plan_card` plans one batched card per call. It sends at most `batch_max` items, and defers everything when the window already holds the cap.
- `review_card_times` lists when cards were last sent to an owner, from the marked asks inside the window.

## Sending and recording
- `build_card( items )` builds one multiple-choice question per item, with four options. The header of the n-th question is `P<n>`. The extras carry `review_card` true and a header-to-principle map.
- `send_review_card` sends one batched card through the dispatcher unless the cap is reached. With no card planned, the dispatcher is not called.
- `record_card_answer( session, notification_id, now )` turns an answer into one ruling row per header, with source `review_card`. The options map to supports, contradicts, or refines with a written condition.
- An answer that is not the owner's own from their screen writes nothing. A timeout default, a proxy and another account all count as not the owner's.
- An unknown header or option is rejected. An answer recorded twice writes nothing the second time.
