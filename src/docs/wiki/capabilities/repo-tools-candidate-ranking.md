---
capability: repo-tools-candidate-ranking
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.symindex.candidates.bm25.Bm25Index@3bad2da693
  - cosa.repo.symindex.candidates.bm25.build_bm25@9906a03583
  - cosa.repo.symindex.candidates.bm25.entry_words@d1f4571022
  - cosa.repo.symindex.candidates.bm25.rank_scored@b14d47d01e
  - cosa.repo.symindex.candidates.bm25.rank@4e48c1e3ec
  - cosa.repo.symindex.candidates.identifier_split.split_identifier@aec169a24e
  - cosa.repo.symindex.candidates.rank_fusion.fuse@56ddd16d86
  - cosa.repo.symindex.candidates.wiki_list.wiki_ranked_ids@9e64de1ecc
  - cosa.repo.symindex.candidates.errors.CandidateError@f4834e24b7
---
# Candidate ranking: words, BM25, fusion, wiki list

The candidate stage cuts the symbol index to a shortlist before the Jev judge sees it. This page is the ranking half. Every step is deterministic: one index and one need give one order. The plan is in [[candidate-stage]].

## Words and BM25
- `split_identifier( text )` gives lowercase words. It breaks on anything that is not a letter or digit, and at a lower-to-upper change. An acronym stays whole and each digit run is a word: `getUserProfile` gives get, user, profile.
- `build_bm25( entries, fields )` returns a frozen `Bm25Index` (k1 1.2, b 0.75). Entries need a unique `id`; documents are ordered by id. `CODE_FIELDS` are id, file, module, name, sig; `PROSE_FIELDS` are doc, purpose. `entry_words( entry, fields )` collects an entry's words.
- `rank_scored( index, query )` returns `( id, score )` pairs, scores rounded to 6 places, best first, ties by id. Only documents sharing a word appear. `rank( index, query )` returns the ids alone.

## Fusion and the wiki list
- `fuse( lists, k=60, depth=512, head=5, limit=None )` adds 1 / ( k + position ) per list and never reads a score. With `limit` it keeps the top `head` ids of every list first, then the best of the rest. It raises `HEAD_EXCEEDS_LIMIT` when the heads alone do not fit.
- `wiki_ranked_ids( need, pages )` ranks capability pages ( `slug`, `text`, `pins` ) by BM25 over their text. Each page's pinned ids follow it in id order, an id once. It is a ranking input, never a gate.

## Errors
- `CandidateError( code, detail )` carries a stable `code`; `str( exc )` is the code, then `: detail`. Most codes live in `errors.py`, for example `ENGINE_MISMATCH`, `VECTOR_SET_CORRUPT`, `STAGE_UNKNOWN`, `PATH_REFUSED`, `BUILD_LOCK_HELD`. A module that raises its own code names it, for example `rank_fusion.HEAD_EXCEEDS_LIMIT`. Catch the code, not the message.
