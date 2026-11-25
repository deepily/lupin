---
capability: answer-card-sample-scripts
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - scripts.build_answer_card_sample.counts_as_answer@b2d611d316
  - scripts.build_answer_card_sample.population@a9e62b43ca
  - scripts.build_answer_card_sample.draw@ab0235c8d6
  - scripts.build_answer_card_sample.card_items@5de14a5782
  - scripts.build_answer_card_sample.build@e9bc3dc1c5
  - scripts.build_answer_card_sample.main@541020f80f
  - scripts.build_item_card_types.card_types@739e2e3bc0
  - scripts.build_item_card_types.main@ae484ce1d7
---
# Answer-card sample scripts

Two scripts for Rick's gold labels ([[labelling-rick-page]], [[labelling-voice-batches]]). The first builds the sample of answered cards, and the second records each item's card type for the agreement report ([[labelling-gold-labels]]). Both read the database in a read-only transaction and write their output file once, never over an existing one.

## The sample
- `counts_as_answer( notification )` is True only for a person's own answer: `answer_source_of` must say `human`, so a timeout default or a review card never counts.
- `population( session, cohort_path )` lists the card ids each type may be drawn from. Yes/no and multiple-choice ids come from the checkpoint cohort, less the Stop-hook cards. Open-ended and batch ids are every answered card of that type. Each list is sorted.
- `draw( ids, quota, seed, response_type )` takes a seeded uniform sample of one type. The same seed and type give the same ids in any input order. A type with fewer cards than its quota raises `ValueError`.
- `card_items( notification )` turns one card into one item per answered field. A yes/no or open-ended card gives one item with field key `answer`; a multiple-choice or batch card gives one per answered header. The stance class is read on a yes/no card and is `none` on the others. A blank field is counted and gives no item. An item carries no forecast and no label.
- `build( session, cohort_path, seed, name, quotas )` draws 200 yes/no, 180 multiple-choice, 100 open-ended and 96 batch cards by default. It returns the packet, with every item blind and no disputes, and a receipt of counts per type. The packet is one the voice batches accept.
- `main` writes `io/gold-labels/answer-card-sample-packet.json` and prints the receipt. It returns 2, writing nothing, when the packet file already exists.

## The card types
- `build_item_card_types.card_types( packet, population )` gives every item of the packet the type of its card, from the same population the draw used. An item with no ref, or a card found in no type or in two, raises `BAD_ITEM`.
- Its `main` writes the item-to-type mapping once and prints the file's sha256, the item count per type, and each type's population count and sha256. An unreadable packet, an item with no single type or an existing output file returns 2.
