---
capability: semdup-proof-label-packets
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.semdup.proof.label_prep.monolith_definitions@58c646b082
  - cosa.repo.semdup.proof.label_prep.monolith_candidates@a26021fba3
  - cosa.repo.semdup.proof.label_prep.unordered_key@73bdda79d6
  - cosa.repo.semdup.proof.label_prep.item_id@b6a2e0ea4f
  - cosa.repo.semdup.proof.label_prep.pair_item@60e2f18d36
  - cosa.repo.semdup.proof.label_prep.prepare@f4343902d3
  - cosa.repo.semdup.proof.label_prep.run@bf913bbfef
  - cosa.repo.semdup.proof.label_prep.live_wiring@7a6c7abc06
  - cosa.repo.semdup.proof.label_prep.main@63d7e5c866
---
# Duplicate checker proof: blind packets and the answer key

The second half of `label_prep.py`: the monolith pairs, the blind items, the packets and the command. Planting is on [[semdup-proof-label-planting]]. The labelling tools are on [[labelling-tools]].

## Monolith pairs
- `monolith_definitions( root, min_nodes )` refuses unless `notifications.js` is the pinned blob. It copies the file to a temporary tree at the same path and returns the definitions of that many nodes or more.
- `monolith_candidates` builds candidate pairs from two sources, jscpd over the copy and nearest neighbours by body vector, up to 30 from each. It returns the definitions, the pairs and the blob sha.

## Blind items
- `unordered_key( a, b )` joins two ids sorted. `item_id` hashes that key into an opaque `pair-` id, so an item says nothing about its source, stratum or order.
- `pair_item( first, second, seed )` makes one item holding only the two texts. The seed and the pair key decide which text is a. A key row names the id that is a.

## Packets and key
- `prepare` builds one item per planted pair and monolith pair. It writes `packets/packet-<reviewer>.jsonl`, with the same items in a different order each, and `key/answer-key.json` once. It raises `FileExistsError` if the key exists, before anything is written.
- The key maps each item id to its ids, which side is a, its kind and its stratum or source. A packet holds the item ids and texts only.

## Command
- `run` plants 60 pairs, 60 percent script and 40 percent Python. It saves them to `key/planted.json` before the monolith step, so a later failure costs no model call. It then returns the packets and key path. It also returns planted and failed counts by stratum, and monolith pair counts.
- `live_wiring` builds the real definitions, the three model asks (Fable rewrites, the need-writer model, Opus work-alikes) and the shape readers.
- `main` takes `--out` and an optional `--claude-cli-path`. It checks the frozen configuration against the live one, runs, prints JSON and returns 0. It raises `CONFIG_DRIFT` if they differ.
