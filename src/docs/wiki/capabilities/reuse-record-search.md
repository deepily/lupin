---
capability: reuse-record-search
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.cosa_voice_mcp.record_search@00a510f72c
  - lupin_mcp.reuse_search.record_search_impl@962a684aa1
  - lupin_mcp.reuse_search.search_terms@37285d41fb
  - lupin_mcp.reuse_search.map_hits@dbfc56a626
  - lupin_mcp.reuse_search.rank_candidates@cd9320d75e
  - lupin_mcp.reuse_search.search_record_id@f42f3aef38
---
# Reuse recorded search

The `record_search` MCP tool searches the working tree for the nearest existing code and records the search. It asks no model. See [[reuse-search-tools]] for the tools that build the shortlist.

## What it does
- Give exactly one of `receipt_id` and `entry`. A receipt brings its own language. An entry has none, so `language` is required: `py`, `ts`, `dart` or `all`.
- It takes three to six terms from the receipt's text or the entry's text, plus any `extra_terms`. Each term is searched with `git grep` over the indexed files of that language.
- Each hit is mapped to the indexed definition whose lines hold it. The five nearest definitions come back with a `search_id` of the form `rs-` and ten hex characters.
- The record is written once under `search-records` in the reuse data folder. The same search on the same tree is a no-op.
- The exit gate `lupin_mcp.reuse_exit_gate` reads these records: a `DISTINCT` ruling passes only when it cites a search logged for its symbol.
- A hit that falls in no definition is counted in `dropped_hits`. A TypeScript JSDoc sits above its definition's first line, so a term found only there is dropped.

## Errors
- `BAD_SEARCH_KEY`: both or neither of `receipt_id` and `entry`, a language beside a receipt, or `extra_terms` that is not a list of strings.
- `UNKNOWN_ENTRY`, `NOT_LUPIN_TREE` and `INDEX_STALE` carry their usual meaning. A language error answers as `check_exists` does.
- The call log records the `search_id` of each call.
