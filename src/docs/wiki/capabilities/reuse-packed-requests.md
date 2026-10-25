---
capability: reuse-packed-requests
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_pack.question_key@69eaf5db8b
  - lupin_mcp.reuse_pack.pack_request@9a8322fd1a
  - lupin_mcp.reuse_pack.pack_answers@c32aa94344
  - lupin_mcp.reuse_pack.stage1_key@e34163a60d
  - lupin_mcp.reuse_pack.replay_key@916a0e85cb
  - lupin_mcp.reuse_pack.candidate_key@8518e0ee7d
  - lupin_mcp.reuse_pack.pair_key@a3ca0b202d
  - lupin_mcp.reuse_pack.pack_key@15ca5d57ee
  - lupin_mcp.reuse_pack.send_pack@df708a5669
  - lupin_mcp.reuse_pack.sweep_packed@81f165e571
  - lupin_mcp.reuse_pack.pair_ask@270e98b674
  - lupin_mcp.reuse_pack.packed_sweeper@eceaa642b1
  - lupin_mcp.reuse_pair.pair_answers@6916d026ed
  - lupin_mcp.reuse_pair_request.template_hash@491d9998e0
  - lupin_mcp.reuse_pair_request.pair_request@e62d6cb588
  - lupin_mcp.reuse_pair_request.estimate_tokens@77c0247d87
  - lupin_mcp.reuse_pair_request.split_for_size@fc05c63770
  - lupin_mcp.reuse_pair_fake.words@e562e86bde
  - lupin_mcp.reuse_pair_fake.candidate_of@60b2233b5e
  - lupin_mcp.reuse_pair_fake.provides_of@7adafe328d
  - lupin_mcp.reuse_pair_fake.level_of@0bf16566be
  - lupin_mcp.reuse_pair_fake.noul_answer@cdc5a4e6b4
  - lupin_mcp.reuse_pair_fake.score_answer@056bed0e1a
  - lupin_mcp.reuse_pair_fake.PairFake@e6941704b7
---
# Packed Jev requests
One request to Jev holds the need once and one question per candidate. These modules build it, read the answers and key the cache. See [[reuse-search-tools]].
- `pack_request( need, entries )` builds the three-way body and a map from entry id to `question_key`. Each question carries only its own candidate's text. A repeated id, an empty pack or a `-latest` model raises `ValueError`.
- `pack_answers( response, qmap )` returns the entries answered and those unasked. An entry is answered only when its question has a probabilities mapping, and an unasked one is never read as unrelated.
- `candidate_key`, `stage1_key`, `replay_key` and `pair_key` name a cached answer by need, candidate text, model and template hash. The measurement and replay keys also hold the run index or repeat number, so no arm reads another's answer. `pack_key` keys a whole body.
- `send_pack` sends one pack and accounts for every entry in it. `sweep_packed` asks about all entries in packs with 4 to 8 workers. `packed_sweeper` makes the sweeper a context takes.
- `pair_request( need, entries )` is the two-question body: a Noul for how much the candidate provides and a Score for coverage. `template_hash` identifies both questions and their four levels.
- `estimate_tokens( body )` is the body length over four, rounded up. `split_for_size` halves a pack until every piece fits the limit. An entry too big alone is reported and never sent.
- `pair_answers` reads a two-question response into provides, coverage and score per entry, or lists the entry as unasked or malformed. `pair_ask` runs it for the stage-two driver.
- `PairFake` is a stand-in transport that answers from word overlap and never reaches Jev. Its helpers `words`, `candidate_of`, `provides_of`, `level_of`, `noul_answer` and `score_answer` build those answers.
