---
capability: labelling-rick-page
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.repo.labelling.rick_page.kind_of@b8a12b6471
  - cosa.repo.labelling.rick_page.relations_for@3c62cf406e
  - cosa.repo.labelling.rick_page.ids_sha256@77d798531f
  - cosa.repo.labelling.rick_page.page_id@a3132942d4
  - cosa.repo.labelling.rick_page.draw_share@47c42fc0c1
  - cosa.repo.labelling.rick_page.merge_sections@e26cbeb74d
  - cosa.repo.labelling.rick_page.page_items@2cc7d7133b
  - cosa.repo.labelling.rick_page.read_ids@02dffcbf84
  - cosa.repo.labelling.rick_page.embed_json@5c08e858ab
  - cosa.repo.labelling.rick_page.render_page@920f9e036c
  - cosa.repo.labelling.rick_page.main@cf3230c218
  - cosa.repo.labelling.rick_export.read_export@65741323a0
  - cosa.repo.labelling.rick_export.batch_id_of@0cd0e51008
  - cosa.repo.labelling.rick_export.gold_lines@94ddf7e549
  - cosa.repo.labelling.rick_export.main@1a6bc55a17
---
# Rick's offline labelling page

A one-file page that shows Rick answer-meaning cards to label, and the reader that records his exported answers as gold labels ([[labelling-gold-labels]]). The page shows only the card, never a forecast or another reader's label. The spoken route is [[labelling-voice-batches]], and the packet comes from [[answer-card-sample-scripts]].

## The page
- `draw_share( packet, seed, share )` draws a seeded share of the distinct cards, then one item from each drawn card that has several. The same packet and seed give the same share in any item order.
- `merge_sections` takes named lists of item ids in order and drops an id an earlier section already holds. The draw, when given, is the first section, `blind share`.
- `page_items( packet, sections, card_types )` gives each item its section, card type, card text, options, recommendation, answer, stance class and allowed relations. Each item passes `blind_form`, so a forecast or a label is refused, not stripped.
- `kind_of` names an item `stance`, `choice` or `open`, and `relations_for` gives the labels of that kind. A choice card with no recommendation is offered `no_recommendation_on_card` instead of the labels that compare against one.
- `render_page( items, title )` returns one HTML file with the items embedded as JSON, escaped by `embed_json`. It loads no outside script, style, font or address. `page_id` is the first 12 characters of `ids_sha256`, the hash of the sorted item ids.
- `main` takes `--packet`, then `--draw <seed>` and any `--section name=file`, read by `read_ids`. It prints a receipt and, unless `--receipt-only`, writes the page, its id list and its sections file. Bad input or an existing output file returns 2 and writes nothing.

## Reading the answers back
- `read_export( text )` reads the exported file: a list of lines, or `{ "lines": [...] }`, each with item id, relation, note, seconds and time. A repeated item id or a malformed line is refused.
- `gold_lines( lines, packet, sections )` makes each line a gold line with source `human` and reader `rick`. Its batch id, from `batch_id_of`, names the page and the item's section. A relation that does not suit the item is refused, and the note and seconds are not kept.
- `main` writes the lines to the store and archives the export file under its content hash. Bad input returns 2, and a locked or damaged store returns 3, with nothing written to the store.
