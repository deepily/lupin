---
capability: reuse-search-tools
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - lupin_mcp.cosa_voice_mcp.check_exists@5bbf00b3d4
  - lupin_mcp.cosa_voice_mcp.fetch_similar@32876a143b
  - lupin_mcp.cosa_voice_mcp.read_capability@9cbb0f24b2
  - lupin_mcp.cosa_voice_mcp.replay@ccfe9d03f8
  - lupin_mcp.reuse_tools.prepare@cb63b067e8
  - lupin_mcp.reuse_tools.sendable@6d563314ce
  - lupin_mcp.reuse_tools.sweep@6b56c2af23
  - lupin_mcp.reuse_tools.LiveJevTransport.post@05ba74d3cf
  - cosa.repo.symindex.verdict.decide@1d8b27ba16
  - lupin_mcp.reuse_call_log_middleware.ReuseCallLogMiddleware.on_call_tool@729af9d8d7
---
# Reuse search tools

Four MCP tools ask whether a new definition already exists. They read the [[symbol-index]] and the wiki, and send short symbol descriptions to the Jev model. They never edit code, but a stale index is rebuilt first, which writes `src/docs/index`.

## The four tools
- `check_exists( need )` redacts the need, then asks Jev about index entries. It returns a verdict, a shortlist capped at 10, the nearest entries and a receipt id. An empty need answers `EMPTY_NEED`.
- `fetch_similar( entry )` uses one indexed symbol as the need and asks about every other entry. It returns the same shape with `uncertain` in place of a verdict.
- Its id is looked up among all definitions, private ones included. `UNKNOWN_ENTRY` means no definition, only while the index is healthy. `EXCLUDED_SENSITIVE_CONTENT` or `EXCLUDED_PREFIX` means it may not be sent.
- `read_capability( names )` reads `capabilities/<name>.md` and makes no Jev call. A bad or missing name is `BAD_NAME` or `NOT_FOUND` per name.
- `replay( receipt_id )` re-runs a receipt on cached answers only, then at the current tree, and returns both results and the differences. A receipt of the removed page route answers `ROUTE_RETIRED`.
- Receipts, snapshots, Jev cache entries and the per-session call log live under the fleet data root's reuse-review folder, never overwritten. `LUPIN_REUSE_DATA_DIR` moves them. A call-log middleware appends one line per tool call and never fails the call.
- Without pack settings, `check_exists` sends one request per sendable entry, route `full`. With `LUPIN_REUSE_JEV_PACK_SIZE`, `LUPIN_REUSE_JEV_TOKEN_CEILING` and `LUPIN_REUSE_JEV_RUN_NAME` set, requests are packed and the [[candidate-stage]] picks the entries, route `candidates`.
- A failed candidate stage answers `UNCERTAIN_READ_SOURCE` with cause `CALL_FAILED` and asks nothing. A policy with a band can widen the shortlist to 512; the shipped policy has none.

## What is sent to Jev
- Each request holds the redacted need and one symbol's id, signature and first docstring line. Source bodies are never sent. A repeated question is answered from the cache.
- `sendable` blanks string defaults, then drops any symbol whose id, signature or docstring line holds an email, URL, IP address, path or credential-shaped token. Dropped ids are not reported. So `NEW` means new among sendable symbols.
- A sweep runs 32 workers and tries each entry up to three times. A 429 or 529 is retried, and each call times out at 60 seconds.
- One call spends at most 9,000 HTTP attempts. `LUPIN_REUSE_JEV_CALL_BUDGET` can lower it; a value outside 1 to 9,000 is refused with `BAD_BUDGET`. Once spent, cached answers still serve and unasked entries count as `not_checked`.
- A 401 or 403 stops later calls. A 422 refuses only its own entry, and five distinct refusals in a row stop the sweep. The key comes from `JEV_API_TOASTER`.

## The verdict
- Any cause beats the three outcomes. The verdict is then `UNCERTAIN_READ_SOURCE`, with a cause from `NOT_LUPIN_TREE`, `INDEX_STALE`, `DEPENDENCY_MISSING`, `KEY_UNREADABLE`, `CALL_FAILED`, `MALFORMED_ANSWER`, `LOW_CONFIDENCE` or `NEAR_CUTOFF`.
- `LOW_CONFIDENCE` holds when a symbol has 0.3 overlap or more and confidence under 0.9, unless a strong match (both at 0.9 or more) exists. `CALL_FAILED` holds when any call failed or any entry was never asked.
- With no cause, `NEW` means no symbol reaches 0.3 overlap. Otherwise `REUSE` means one of those symbols chose reuse, and `EXTEND` means none did.
