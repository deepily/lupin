---
capability: reuse-search-tools
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - lupin_mcp.cosa_voice_mcp.check_exists@5bbf00b3d4
  - lupin_mcp.cosa_voice_mcp.fetch_similar@32876a143b
  - lupin_mcp.cosa_voice_mcp.read_capability@9cbb0f24b2
  - lupin_mcp.cosa_voice_mcp.replay@ccfe9d03f8
  - lupin_mcp.reuse_tools.prepare@f9dcbbdae1
  - lupin_mcp.reuse_tools.sendable@6d563314ce
  - lupin_mcp.reuse_tools.sweep@806fa5d2ff
  - lupin_mcp.reuse_tools.LiveJevTransport.post@f51881fc6c
  - cosa.repo.symindex.verdict.decide@1d8b27ba16
  - lupin_mcp.reuse_call_log_middleware.ReuseCallLogMiddleware.on_call_tool@729af9d8d7
---
# Reuse search tools

Four MCP tools ask whether a new definition already exists. They read the [[symbol-index]] and the wiki, and send short symbol descriptions to the Jev model. They never edit code, but a stale index is rebuilt first, which reads every source file and writes `src/docs/index`.

## The four tools
- `check_exists( need )` asks about capability pages first, then sweeps the symbols they cover, then every indexed symbol if that finds nothing. It returns a verdict, a shortlist capped at 10, and a receipt id. An empty need answers `EMPTY_NEED`.
- `fetch_similar( entry )` uses one indexed symbol as the need and leaves that symbol out. It returns the same shape without a verdict. `UNKNOWN_ENTRY` comes back for an id not in the sendable list, only while the index is healthy.
- `read_capability( names )` reads `capabilities/<name>.md` from the wiki and makes no Jev call. A bad or missing name is reported per name, and a receipt is written regardless.
- `replay( receipt_id )` checks the receipt, re-runs a search receipt against the stored snapshot (cache only), then again at the current tree. A receipt stored with a hard flag is copied, not re-run, for the snapshot step. A `read_capability` receipt has no re-run. It returns both results and the differences.
- The search tools write a receipt, a snapshot and Jev cache entries. `read_capability` writes only a receipt. Nothing is overwritten. By default all live under the fleet data root's `reuse-review` folder; `LUPIN_REUSE_DATA_DIR` moves them.

## What is sent to Jev
- `check_exists` first sends one POST per wiki page listed in `INDEX.md` that is pinned and names a package. It sweeps the symbols in up to 5 pages scoring 0.3 overlap or more, and a symbol at 0.5 decides. If none does, every symbol is swept; `fetch_similar` always sweeps all. The receipt records the route.
- Each symbol POST holds the need and the symbol's id, signature and first docstring line. A repeated question is answered from the cache and sends nothing. Source bodies are never sent.
- `sendable` blanks string defaults in signatures. It then drops any symbol whose id, signature or docstring line holds an email, URL, IP address, path or credential-shaped token. Dropped ids are not reported, so `NEW` means new among the sendable symbols.
- The sweep runs 32 workers and tries each symbol up to three times. A 429 or 529 is retried inside a try, and each call times out at 60 seconds. One call spends at most 8,000 HTTP attempts, retries included, across all workers. `LUPIN_REUSE_JEV_CALL_BUDGET` can lower it, and a value outside 1 to 8,000 is refused with `BAD_BUDGET` in the error detail. Once it is spent, cached answers still serve, and entries never attempted are counted as `not_checked` in the receipt.
- A 401, 403 or 422 stops later calls, but calls already in flight can finish. The key comes from the `JEV_API_TOASTER` environment variable. No INI key controls any of this.

## The verdict
- Any flag beats the three outcomes below. `decide` then answers `UNCERTAIN_READ_SOURCE` with a cause: `NOT_LUPIN_TREE`, `INDEX_STALE`, `DEPENDENCY_MISSING`, `KEY_UNREADABLE`, `CALL_FAILED`, `MALFORMED_ANSWER` or `LOW_CONFIDENCE`.
- `LOW_CONFIDENCE` holds when a symbol has 0.3 overlap or more and confidence under 0.9, unless a strong match exists. A strong match has overlap and confidence both at 0.9 or more, and the doubtful symbols are then listed as `doubtful`. `INDEX_STALE` means the index build raised any error. `CALL_FAILED` holds when any call failed or any entry was never asked, budget cut-offs included.
- With no flag, `NEW` means no symbol reaches 0.5 overlap. Otherwise `REUSE` means one of those symbols chose reuse, and `EXTEND` means none did. With a strong match, only the strong symbols are counted for that choice.

## Logging
- The call-log middleware appends a line per call of these tools to `call-log/<session id>.jsonl`. It holds the time, tool, caller, session, receipt id, error and the first 300 characters of the arguments. Logging failures are swallowed.
