---
capability: reuse-tools-question-entry-points
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_tools.run_question@198b0e87aa
  - lupin_mcp.reuse_tools.check_exists_impl@ebeb166ee8
  - lupin_mcp.reuse_tools.sweep_need_impl@42d37fe736
  - lupin_mcp.reuse_tools.unstored_need_impl@30148391b0
  - lupin_mcp.reuse_tools.fetch_similar_impl@4a28930fcf
  - lupin_mcp.reuse_tools.read_capability_impl@9e12c9ae0d
  - lupin_mcp.reuse_tools.replay_impl@af3f456876
---
# Reuse tools: the question entry points

The functions the voice tools call to ask a reuse question. Hashing and receipts are in [[reuse-tools-request-and-context]] and [[reuse-tools-index-and-receipts]].

## Asking
- `run_question` runs one sweep-based question and stores its receipt. A single-use context closes its ledger run when the question ends, however it ends. With `include_tests` the question is always sweep-only, because no vector holds a test record.
- `check_exists_impl` sweeps the index with Jev and applies the decision table. It needs a non-empty need and a language, and it answers `EMPTY_NEED`, `LANGUAGE_REQUIRED` or `LANGUAGE_INVALID` before any request. With `include_tests` it also asks the test files, sweeping every record with no candidate stage.
- The verdict is `REUSE`, `EXTEND` or `UNCERTAIN_READ_SOURCE`. An uncertain verdict always carries a cause, and `NO_MATCH` means nothing relevant was found.
- The result also reports how many entries the candidate stage asked and did not ask, or none when the stage did not run.
- `sweep_need_impl` turns the candidate stage off and asks every entry except `exclude_id`. An id not in the index returns `UNKNOWN_ENTRY` before any request. The language is a required keyword.
- `unstored_need_impl` builds the receipt and does not write it, so a second ask is not handed the first. It asks every entry unless `candidates` is true.
- The `provides` question asks the pair question, which has no candidate stage, so `candidates` is ignored for it.

## Looking up one symbol
- `fetch_similar_impl` returns the shortlist for an indexed symbol, excluding itself. The language is stated by the caller and never inferred from the entry. With `include_tests` it looks among test files too, and accepts a test definition as the entry.
- A definition the screen would not send returns `EXCLUDED_PREFIX` or `EXCLUDED_SENSITIVE_CONTENT` with no receipt. An id in no healthy index returns `UNKNOWN_ENTRY`.
- `read_capability_impl` reads pages by slug with no Jev call. A slug that is not letters, digits, `_` and `-` gives `BAD_NAME`; a missing page gives `NOT_FOUND`.

## Replay
- `replay_impl` returns the stored result, a frozen re-run and a re-run at the current tree, with the differences in verdict, cause and shortlist. It re-runs with test records when the receipt records that it read them.
- The frozen re-run reads only cached Jev answers. It tests that the receipt's inputs reproduce its result, not the model.
- For a candidate route it rebuilds the shortlist from the cached query vector. It refuses when the vector set was replaced or the ids or packs differ.
- A damaged or absent input returns an error name and no verdict. A receipt on the retired page route returns `ROUTE_RETIRED`; a `read_capability` receipt has no re-run.
- `repeat` of 1 or more asks the current-tree run again as a fresh draw and writes no receipt. It needs a packed context, else `REPEAT_NEEDS_PACKED_CONTEXT`.
