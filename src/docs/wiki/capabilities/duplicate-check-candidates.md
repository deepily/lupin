---
capability: duplicate-check-candidates
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.duplicate_check.body_vectors.body_text@c765892c19
  - cosa.repo.duplicate_check.body_vectors.engine_tag@73eaf52263
  - cosa.repo.duplicate_check.body_vectors.ensure_vectors@971fcf34b4
  - cosa.repo.duplicate_check.candidates.build_pool@5aa79c432f
  - cosa.repo.duplicate_check.candidates.candidate_rows@e914cff432
  - cosa.repo.duplicate_check.candidates.candidates_for@ae0ccf4fb7
  - cosa.repo.duplicate_check.candidates.embedding_list@08d3a13581
  - cosa.repo.duplicate_check.candidates.outside_pool@c4669d0ab8
  - cosa.repo.duplicate_check.candidates.partner_map@4fbdce1f26
  - cosa.repo.duplicate_check.candidates.same_slot@f80b350738
  - cosa.repo.duplicate_check.candidates.structural_list@c856824456
  - cosa.repo.duplicate_check.candidates.word_index@89acdb2f6b
  - cosa.repo.duplicate_check.candidates.word_list@c4866ab787
  - cosa.repo.duplicate_check.structural.clone_pairs@7e597bc8a3
  - cosa.repo.duplicate_check.structural.parse_jscpd@d21faa33ba
  - cosa.repo.duplicate_check.structural.python_clones@594a21c09a
  - cosa.repo.duplicate_check.structural.run_jscpd@bef582c77d
  - cosa.repo.duplicate_check.structural.script_clones@0706048594
---
# Duplicate checker: candidate stage
For each new definition, three ranked lists are joined by rank fusion into a short candidate row for the judge.
- `body_text` returns the text that is embedded and whether it was cut. `engine_tag` names the engine, so another engine's vectors are never reused.
- `ensure_vectors` embeds every definition and reads earlier embeddings from a cache keyed by text sha. Each batch is written to the cache as it returns, so a crash part way keeps the batches already done.
- `build_pool` gathers the definitions a candidate may come from, with unit-length vectors. `same_slot` says whether two are one definition or its redefinition.
- `embedding_list` lists the nearest by cosine. `word_index` and `word_list` rank by shared words with BM25.
- `structural_list` lists structural clones. `partner_map` turns clone pairs into partners, and `outside_pool` counts partners not in the pool.
- `candidates_for` fuses the three lists for one definition. `candidate_rows` does so for every new definition.
- `run_jscpd` runs the installed jscpd with the frozen maximum file size, because jscpd skips a larger file without a word. `parse_jscpd` turns its report into pairs.
- `python_clones` and `script_clones` map the pairs of `dups` onto Python and script definitions. A script definition pairs with script definitions only.
- `clone_pairs` merges the pair lists of both sources. The index-side ranking is on [[candidate-stage]].
