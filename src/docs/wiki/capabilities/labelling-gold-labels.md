---
capability: labelling-gold-labels
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.repo.labelling.gold_store.default_path@d776884144
  - cosa.repo.labelling.gold_store.check_line@f97a9b51b4
  - cosa.repo.labelling.gold_store.read_gold@509c1cf1d5
  - cosa.repo.labelling.gold_store.append_gold@c74affe1db
  - cosa.repo.labelling.gold_store.latest_lines@838b7e9005
  - cosa.repo.labelling.gold_store.settled@4b7968e708
  - cosa.repo.labelling.gold_store.human_card_counts@b43bae176a
  - cosa.repo.labelling.agreement_report.kappa_or_none@f3e416351f
  - cosa.repo.labelling.agreement_report.relations_by_item@39625e4b54
  - cosa.repo.labelling.agreement_report.rick_blind_share@92fa8263f9
  - cosa.repo.labelling.agreement_report.compare@71ef2aeccc
  - cosa.repo.labelling.agreement_report.report@78da2f51eb
  - cosa.repo.labelling.agreement_report.main@9b39a6d81a
---
# Answer-meaning gold labels and their agreement report

The store of gold labels for answer-meaning cards, written by Rick and by two AI readers, and the report of how far they agree. Items and labels use the format of [[labelling-tools]]. Rick's labels arrive through [[labelling-rick-page]] and [[labelling-voice-batches]].

## The store
- The store is one append-only JSON Lines file, `io/gold-labels/answer-meaning-gold.jsonl` under the project root (`default_path`). Run from a worktree, it names that worktree's copy.
- A line holds exactly `item_id`, `notification_id`, `field_key`, `relation`, `card_stance`, `source`, `reader`, `batch_id` and `ts`, each a non-empty string. `source` is `human` or `ai_reader`, `relation` is one of the answer labels and `card_stance` is one of yes, no, neither and none. `check_line` raises `BAD_LABEL` naming the first field that breaks this.
- `read_gold( path )` returns every line in file order, or none for a missing file. A last line with no end of line is refused as torn; nothing is skipped.
- `append_gold( path, lines )` checks every line before it writes any. It holds an exclusive file lock beside an in-process lock. It writes all lines at the end in one write, then syncs the file and its folder. Another process holding the file raises `STORE_LOCKED` and nothing is written.
- `latest_lines` keeps one line per item, source and reader: the last one in the file.
- `settled( lines )` gives each card its label. Two or more AI readers whose latest relations agree settle it (`readers_agreed`). Otherwise Rick's latest line settles it (`rick_tiebreak`). A card with neither is listed as unsettled and is not gold. The settled label is worked out on each read and never stored.
- `human_card_counts` counts the cards Rick has labelled, per stance class, with every class present.

## The agreement report
- `kappa_or_none( pairs )` returns the count, Cohen's kappa over the answer labels, the raw agreement and whether kappa meets the 0.7 bar. With no pairs, or one label used throughout, kappa is None with the reason, never 0 or 1.
- `relations_by_item( lines, source, reader, batch_suffix )` gives one labeller's latest relation per item. With a batch suffix, only lines of matching batches count, so a later line from another batch cannot override.
- `rick_blind_share` is Rick's labels from his blind-share batches only. His labels on reader disagreements are not blind and are left out.
- `compare( first, second, types )` reports kappa over the items both labelled, overall and for each card type.
- `report( lines, types )` compares Rick's blind share with each reader, which is the figure the bar applies to. It also compares the two readers with each other, as a check that the reading repeats, not as a human bar.
- `main` takes `--types`, the item-to-card-type file, and optional `--store` and `--out`. It prints the report as JSON with the types file's sha256. It writes `--out` only when that file does not exist yet. A file it cannot read, or an existing `--out`, returns 2.
