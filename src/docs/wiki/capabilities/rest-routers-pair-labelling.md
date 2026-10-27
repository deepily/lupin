---
capability: rest-routers-pair-labelling
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.routers.pair_labelling.LabelUpload@98f8fd6b17
  - cosa.rest.routers.pair_labelling.packets_dir@a598427cb3
  - cosa.rest.routers.pair_labelling.packet_for@5c71103c44
  - cosa.rest.routers.pair_labelling.read_state@8ee85c8ab9
  - cosa.rest.routers.pair_labelling.state@adc2a4f3a7
  - cosa.rest.routers.pair_labelling.item@c746b06ac3
  - cosa.rest.routers.pair_labelling.label@2233e95178
  - cosa.rest.routers.pages.page_pair_labelling@8d27146041
---
# Pair labelling router

The `/api/pair-labelling` door that a reviewer's browser page uses to label blind `semdup_pair` items one at a time. The label rule and file are in [[labelling-pair-labels]].

## What it does
- `page_pair_labelling` serves the page at `/app/pair-labelling`. The page reads `?reviewer=` and defaults to rick.
- `state` (`GET /state`) answers `{ reviewer, total, labelled, unsure, resume }`. `resume` is the first unlabelled position, else the first unsure one, else null.
- `item` (`GET /item?position=n`) answers `{ position, total, labelled, item_id, a, b, label }`. It never sends a type or an origin.
- `label` (`POST /label`) takes `LabelUpload`, writes the label to disk before it answers, and then answers as `state` does.
- `packets_dir` names the packets folder: `LUPIN_PAIR_LABELLING_DIR` when set, otherwise the default run's folder.
- `packet_for` returns a reviewer's `packet-<reviewer>.jsonl`, and `read_state` reads the packet and the labels so far.
- All three routes accept an API key or a JWT.

## Don't
- Don't point `LUPIN_PAIR_LABELLING_DIR` at the key folder. The router reads only the packet.

## Invariants
- A reviewer name is letters, digits, `_` and `-`, so it cannot leave the packets folder.
- An unknown reviewer, pair or position answers 404, and a bad name or a long note 422.
- A packet or labels file that fails validation answers 500.
