---
capability: repo-tools-candidate-search
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.symindex.candidates.search.is_count@56a9ad94d3
  - cosa.repo.symindex.candidates.search.validate_request@0b2484c56e
  - cosa.repo.symindex.candidates.search.cosine_ranked@1ddfdf614f
  - cosa.repo.symindex.candidates.search.read_purposes@870095c165
  - cosa.repo.symindex.candidates.search.answer@3e0a9ce5a7
  - cosa.repo.symindex.candidates.search.answer_for_stage@53ace63e03
  - cosa.repo.symindex.candidates.search.default_loader@40bb70e85e
  - cosa.repo.symindex.candidates.search.main@abd00c678c
---
# Candidate search process

`cosa.repo.symindex.candidates.search` reads one JSON request on standard input and writes one JSON answer on standard output. It holds no state between calls. Run it with `python -m cosa.repo.symindex.candidates.search`.

## Request and answer
- A request holds `need`, `K` and `index_dir`, and may hold `purposes` (a purpose file path), `fusion` ( `k`, `depth`, `head` ) and `wiki` (ids). `vectors_dir` comes with `query_vectors`.
- `validate_request( request, with_index=True )` checks the shape first and raises `BAD_SEARCH_REQUEST` naming the first wrong key. `is_count( value, minimum )` is its integer test and refuses a bool.
- `answer( request, load_vectors )` reads the index folder and purpose file, builds the stage, then calls `answer_for_stage`. An unreadable folder or file is `INDEX_UNREADABLE`.
- `answer_for_stage( request, stage, load_vectors )` ranks by BM25 over code and prose, and by cosine over each stored matrix (`vector_prose`, `vector_code`, `vector_concat`). The wiki list joins them. It returns `shortlist`, `ranking`, `lists`, `scores`, `K`, `manifest_hash`, `bm25` and `index_ids_without_vectors`. A vector id missing from the index raises `VECTOR_IDS_NOT_IN_INDEX`.

## Helpers
- `cosine_ranked( ids, matrix, query )` returns `( id, score )` pairs rounded to 6 places, ties by id. A zero row or query scores 0.0.
- `read_purposes( path )` returns `{ pin: purpose }`, the first row for a pin winning, or `{}` for None.
- `default_loader( vectors_dir )` calls `vector_store.load_vectors`.
- `main( stdin, stdout, load_vectors )` writes the answer and returns 0, or writes `{ error, detail }` and returns 2 for a `CandidateError`. Input that is not a JSON object also returns 2.
