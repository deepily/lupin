---
capability: labelling-tools
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.labelling.adjudicate.differs@d5229f59c9
  - cosa.repo.labelling.adjudicate.disputes@cb16a603a1
  - cosa.repo.labelling.adjudicate.resolve@5e98394810
  - cosa.repo.labelling.agreement.agreement_report@da74bb44ae
  - cosa.repo.labelling.agreement.cohen_kappa@33af69eb3a
  - cosa.repo.labelling.agreement.paired@e6121fead9
  - cosa.repo.labelling.confirm.blind_sample_ids@1fd3a10983
  - cosa.repo.labelling.confirm.confirm_report@66bc76e06e
  - cosa.repo.labelling.confirm.export_confirm_packet@bf87535a2a
  - cosa.repo.labelling.confirm.manifest_path@ed665aa68b
  - cosa.repo.labelling.confirm.read_manifest@b91470f58b
  - cosa.repo.labelling.errors.LabellingError@e96e9bf625
  - cosa.repo.labelling.items.make_item@f76ca4c1ea
  - cosa.repo.labelling.items.validate_item@683123c7d4
  - cosa.repo.labelling.packets.blind_form@9b4f75c2f2
  - cosa.repo.labelling.packets.export_packets@e1209de41a
  - cosa.repo.labelling.packets.packet_path@fb53e6f8ac
  - cosa.repo.labelling.packets.read_labels@ab7625589b
  - cosa.repo.labelling.packets.seeded_order@7bdd443cfd
---
# Blind labelling tools
Two human reviewers label items without seeing the model's verdict. In blind mode they never see each other's label. In confirm mode the second reviewer sees Rick's label on all but a seeded 20%. The same format serves the need-set labelling and the duplicate checker.
- `make_item` builds an item, a need with its proposed key or a pair of definitions, and `validate_item` checks one against the `labelling-item-1` format.
- `export_packets` writes one blind packet per reviewer at the path `packet_path` gives. `blind_form` validates an item and returns only its id, type and payload. It raises `PACKET_LEAK` naming any extra field, and strips nothing.
- `seeded_order` orders the items for the next reviewer, and `read_labels` reads back the labels one reviewer sent.
- `paired` joins two reviewers' labels by item. `cohen_kappa` and `agreement_report` measure how far they agree.
- Confirm mode builds the second reviewer's packet. `blind_sample_ids` draws a seeded 20% of the items, half rounded up, and `export_confirm_packet` leaves those blind and shows Rick's label on the rest.
- `export_confirm_packet` also writes a manifest at `manifest_path`, which `read_manifest` reads back. It refuses a round that draws no blind item, and a second reviewer who is Rick.
- `confirm_report` computes kappa over the blind sample only and says so, with the sample size and the seed. It counts the other items as confirmed or disputed and lists the disputes of both parts for Rick.
- `differs` says whether two labels of one item disagree on the choice or the symbols. `disputes` lists the items the reviewers did not settle.
- `resolve` gives every item its final label. `LabellingError` carries a stable code for each failure.
- The package imports neither the reuse checker nor the need-set tools. No `semdup` module imports it yet.
