---
capability: reuse-search-tools
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.cosa_voice_mcp.check_exists@5bbf00b3d4
  - lupin_mcp.cosa_voice_mcp.fetch_similar@32876a143b
  - lupin_mcp.cosa_voice_mcp.read_capability@9cbb0f24b2
  - lupin_mcp.cosa_voice_mcp.replay@ccfe9d03f8
  - lupin_mcp.reuse_tools.prepare@cb63b067e8
  - lupin_mcp.reuse_tools.sendable@6d563314ce
  - lupin_mcp.reuse_tools.sweep@6b56c2af23
  - lupin_mcp.reuse_tools.LiveJevTransport.post@05ba74d3cf
  - cosa.repo.symindex.verdict.decide@22df0ebc3b
  - lupin_mcp.reuse_call_log_middleware.ReuseCallLogMiddleware.on_call_tool@729af9d8d7
---
# Reuse search tools

Four MCP tools ask whether a new definition already exists. They read the [[symbol-index]] and the wiki, and send short symbol descriptions to the Jev model. They never edit code, but a stale index is rebuilt first, which writes `src/docs/index`.

## The four tools
- `check_exists( need, language )` redacts the need, then asks Jev about index entries of one language. The language is `py`, `ts`, `dart` or `all`, has no default, and a missing or unknown one answers `LANGUAGE_REQUIRED` or `LANGUAGE_INVALID` before any request. It returns a verdict, a shortlist capped at 10, the nearest entries and a receipt id. An empty need answers `EMPTY_NEED`.
- `fetch_similar( entry, language )` uses one indexed symbol as the need and asks about every other entry of that language. The language is required and never inferred from the entry. It returns the same shape with `uncertain` in place of a verdict.
- Its id is looked up among all definitions, private ones included. `UNKNOWN_ENTRY` means no definition, only while the index is healthy. `EXCLUDED_SENSITIVE_CONTENT` or `EXCLUDED_PREFIX` means it may not be sent.
- `read_capability( names )` reads `capabilities/<name>.md` and makes no Jev call. A bad or missing name is `BAD_NAME` or `NOT_FOUND` per name.
- `replay( receipt_id )` re-runs a receipt on cached answers only, then at the current tree, and returns both results and the differences. A receipt of the removed page route answers `ROUTE_RETIRED`.
- Receipts, snapshots, Jev cache entries and the per-session call log live under the fleet data root's reuse-review folder, never overwritten. `LUPIN_REUSE_DATA_DIR` moves them. A call-log middleware appends one line per tool call and never fails the call.
- Without pack settings, `check_exists` sends one request per sendable entry, route `full`. With `LUPIN_REUSE_JEV_PACK_SIZE`, `LUPIN_REUSE_JEV_TOKEN_CEILING` and `LUPIN_REUSE_JEV_RUN_NAME` set, requests are packed and the [[candidate-stage]] picks the entries, route `candidates`.
- A candidate stage that fails on its first call answers `UNCERTAIN_READ_SOURCE` with `CALL_FAILED` in its causes and asks nothing. The `cause` field is the first cause in the fixed order, so `DEPENDENCY_MISSING` outranks it. A policy with a band can widen the shortlist to 512; the shipped policy has none (Rick ruled the band off). If the widening call fails, the first sweep's decision stands with `CALL_FAILED` added and `widen_error` set.

## What is sent to Jev
- Without pack settings, each request holds the redacted need and one symbol's id, signature and first docstring line. With them, a pack holds the need once and one question per entry, on every route. Source bodies are never sent. A repeated question is answered from the cache.
- `sendable` blanks string defaults, then drops any symbol whose id, signature or docstring line holds an email, URL, IP address, path or credential-shaped token. Dropped ids are not reported. So `NO_MATCH` means nothing matched among sendable symbols.
- Without pack settings, a sweep runs 32 workers and tries each entry up to three times. A 429 or 529 is retried. With them, every sweep is packed, `fetch_similar`'s too. It runs 6 workers (4 to 8) and posts each pack once. Its transport sends up to four times, and also retries 408, 500, 502, 503 and 504. Each call times out at 60 seconds.
- One call spends at most 9,000 HTTP attempts. `LUPIN_REUSE_JEV_CALL_BUDGET` can lower it; a value outside 1 to 9,000 is refused, and the tool answers `REUSE_TOOLS_UNAVAILABLE` with `BAD_BUDGET` in `detail`. Once spent, cached answers still serve and unasked entries count as `not_checked`.
- A 401 or 403 stops later calls. Without pack settings, a 422 refuses only its own entry. With them, a 422 splits the pack in half and resends; only a one-entry pack fails an entry. Five refusals in a row stop the sweep. A pack and its halves count as one. The key comes from `JEV_API_TOASTER`.

## The verdict
- Any cause beats `REUSE` and `EXTEND`. The verdict is then `UNCERTAIN_READ_SOURCE`, with a cause from `NOT_LUPIN_TREE`, `INDEX_STALE`, `DEPENDENCY_MISSING`, `KEY_UNREADABLE`, `CALL_FAILED`, `MALFORMED_ANSWER`, `LOW_CONFIDENCE`, `NEAR_CUTOFF` or `NO_MATCH`.
- `LOW_CONFIDENCE` holds when a symbol has 0.3 overlap or more and confidence under 0.9, unless a strong match (both at 0.9 or more) exists. `CALL_FAILED` holds when any call failed or any entry was never asked.
- With no other cause, no symbol reaching 0.3 overlap holds `NO_MATCH` alone, so the reviewer reads the nearest entries. Otherwise `REUSE` means one of those symbols chose reuse, and `EXTEND` means none did. With a strong match, only the strong entries decide. A policy without `no_new` still answers `NEW`.
