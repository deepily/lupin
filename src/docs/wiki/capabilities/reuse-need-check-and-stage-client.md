---
capability: reuse-need-check-and-stage-client
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_need_check.entry_text_of@e084f98b33
  - lupin_mcp.reuse_need_check.file_sha256@263a4ccc40
  - lupin_mcp.reuse_need_check.twin_groups@ae524d039f
  - lupin_mcp.reuse_need_check.identifier_tokens@cc312d2b3d
  - lupin_mcp.reuse_need_check.name_pieces@416af78e49
  - lupin_mcp.reuse_need_check.need_words@c306ba5567
  - lupin_mcp.reuse_need_check.shared_run@17f47257b3
  - lupin_mcp.reuse_need_check.check_form@2c1f3743e8
  - lupin_mcp.reuse_need_check.check_need@2671e72842
  - lupin_mcp.reuse_need_check.check_all@5849ba8498
  - lupin_mcp.reuse_need_check.resend_list@cd30bae735
  - lupin_mcp.reuse_need_check.load_sample_ids@25bfe75f1d
  - lupin_mcp.reuse_need_check.load_needs@a7ba0c2e72
  - lupin_mcp.reuse_need_check.load_index@9fae1cc3ff
  - lupin_mcp.reuse_need_check.main@e9bfcadee0
  - lupin_mcp.reuse_candidates.canonical@335bf66db1
  - lupin_mcp.reuse_candidates.CandidateStage@1f35b7f484
---
# Reuse need check and candidate stage client
Two pieces of the end-to-end run ([[reuse-end-to-end-run]]). The need check tests that a need sentence describes its member without handing Jev the answer. The stage client asks the Lupin server for a shortlist.

## Need check
- A need may hold no identifier of its member or of a twin. It may share no run of four words with the text Jev sees of either, and it must have the required form.
- `twin_groups( manifest )` joins exact clusters and near pairs into connected groups, so two members linked through a third are twins. It maps each member to every other member of its group.
- `identifier_tokens` returns a record's lowercase identifier tokens: its dotted id parts, file stem and argument names, each whole. `name_pieces` splits those names into words of four letters or more. `entry_text_of` is what Jev sees of one symbol.
- `need_words` maps each word of the need, after the opening phrase, to the whole word as written. `shared_run( need, text )` returns the first four-word run they share. `check_form` returns None for a well-formed sentence.
- `check_need( member_id, need, index, groups )` returns the failed checks against the member and its twins. `check_all` checks every sampled member and fails a sample id with no need.
- `resend_list( results )` builds the entries for the need writer: member, failed checks and `avoid_words`. Both run checks show as `text_run`, so the writer is not told a twin exists.
- `load_sample_ids`, `load_needs` and `load_index` read the sample, the needs document and `symbols.jsonl`. `file_sha256` hashes a file. `main` writes `check-results.json` and `resend-list.json`, and returns 0 only if all pass.

## Candidate stage client
- `CandidateStage` is the client of the resident search for one vector set. The cosa-voice process cannot import numpy, so the search runs on the Lupin server.
- Before a lookup it brings the live vector set up to the index and checks that the manifest hashes to itself. It uploads the entries once per index. It then asks for the shortlist by key. A failure is a named `CandidateError`, never a silent sweep. A failing refresher is tolerated. The lookup then answers from the set on disk and reports the state `stale`.
- `canonical( obj )` is sorted-key JSON with no spaces after separators.
