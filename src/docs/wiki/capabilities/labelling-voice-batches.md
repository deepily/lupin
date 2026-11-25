---
capability: labelling-voice-batches
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.repo.labelling.voice_batches.short_ids@0858994591
  - cosa.repo.labelling.voice_batches.batch_id@386840ebf5
  - cosa.repo.labelling.voice_batches.voice_batches@2b99a18ddb
  - cosa.repo.labelling.voice_batches.read_answers@4713d4087a
  - cosa.repo.labelling.voice_batches.main@b5b2ac7660
---
# Voice-card labelling batches

The spoken route for Rick's answer-meaning labels: batches of cards out through the voice tools, and his spoken answers back as gold labels ([[labelling-gold-labels]]). The offline route is [[labelling-rick-page]].

## Batches out
- Code cannot call the voice tools. `voice_batches( packet, seed, chase_start )` builds what a seat passes to `ask_open_ended_batch` and to `task_create`.
- A batch holds up to 20 cards. The blind ones come first, and a blind card never shares a batch with a dispute card.
- Batch i is chased one day per index after `chase_start`. The same packet, seed and start always give the same batches and ids.
- A spoken text of 400 characters or more, a repeated id or a field a reviewer may not see is refused.
- `short_ids` gives each card the shortest prefix of its id's sha256 that is still unique, at least four characters. `batch_id` is 12 hex characters of a hash of the packet name, the seed and the batch index.

## Answers back
- `read_answers( batch, answers )` matches the tool's answers to the batch's cards by header. Spoken aliases are accepted for labels whose name is not how a person says it.
- It returns the labels, the cards left unlabelled with what was said, and the headers that match no card.
- `main read` writes one gold line per labelled card and prints a summary. An unknown batch, a missing ref or an unreadable file returns 2. A locked or damaged store returns 3, and nothing is written.
