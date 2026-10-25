---
capability: reuse-tools-transport-and-screening
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_tools.append_call_log@13cbe4da35
  - lupin_mcp.reuse_tools.LiveJevTransport@7d78a6e851
  - lupin_mcp.reuse_tools.RefusalBreaker@65c246e71a
  - lupin_mcp.reuse_tools.JevCache@6eba1d0642
  - lupin_mcp.reuse_tools.blank_string_defaults@7102e67f36
  - lupin_mcp.reuse_tools.c1_hits@39a15437a8
  - lupin_mcp.reuse_tools.entry_text@7972400a6e
  - lupin_mcp.reuse_tools.parse_answer@0b3dfc56c6
  - lupin_mcp.reuse_tools.usage_of@fb38c47c62
  - lupin_mcp.reuse_tools.attempt_counts@0988e9ffc3
  - lupin_mcp.reuse_tools.transport_summary@d44b87d07a
---
# Reuse tools: transport, screening and telemetry

What leaves the machine, how it is sent, and what is counted afterwards. The question itself is in [[reuse-tools-request-and-context]].

## Screening
- `blank_string_defaults` replaces any signature default holding a quote with an ellipsis. A quoted string in an annotation is not a default and stays.
- `c1_hits` names the patterns found in a symbol's id, signature and docstring lines. It also checks its purpose line when it has one. The patterns are email, url, ip, path and credential. A `/app` or `/data` path counts only when it names a file.
- `sendable` applies both. A symbol that still matches after blanking is dropped, and no module or language is excluded. `entry_text` is what Jev sees of one symbol: id, signature and first docstring line. It adds the whole docstring and purpose line when they differ or exist. `sendable_report` also names the ids dropped under an excluded prefix.

## Transport
- `LiveJevTransport` reads the key from the environment on each post and never stores it. Once Jev refuses the key, later posts raise with no HTTP call. A 422 refuses only its own request.
- With a budget, every HTTP attempt takes one from it, retries included. A spent budget raises without sending.
- `RefusalBreaker` counts distinct refused keys since the last answer and stops at its limit. Resending the halves of a refused pack under one key counts once.
- `RefusalBreaker.mismatched` stops it at once and keeps the first wrong model name served. Every method is safe across threads.
- `JevCache` stores each response under its request hash, with the response's own sha1. A missing entry gives `None`; an unreadable or altered one raises `CACHE_CORRUPT`. An entry is never rewritten.

## Reading answers and counting
- `parse_answer` returns the probabilities of one response, or `None` when the shape is wrong.
- `usage_of` returns input and output token counts only when both are whole numbers of zero or more. A bool does not count.
- `attempt_counts` totals requests, attempts, 429s, 529s, timeouts, resets, other 5xx errors and attempts that carried a request id.
- `transport_summary` counts live responses by model, status and attempts. It adds the largest retry-after and latency as min, max, mean, median and 95th percentile.

## Call log
- `append_call_log` adds one line to the session's file under `call-log` in a single append, so concurrent writers never interleave. It refuses a session id with path characters.
