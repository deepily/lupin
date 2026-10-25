---
capability: reuse-tools-request-and-context
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_tools.canonical@667fb38877
  - lupin_mcp.reuse_tools.sha@4706b44864
  - lupin_mcp.reuse_tools.prompt_template_hash@4b356b8077
  - lupin_mcp.reuse_tools.build_request@5359857ebb
  - lupin_mcp.reuse_tools.request_hash@40ae28d835
  - lupin_mcp.reuse_tools.language_error@730faffd76
  - lupin_mcp.reuse_tools.in_language@6b08792599
  - lupin_mcp.reuse_tools.receipt_id@6eef4a64c0
  - lupin_mcp.reuse_tools.write_once@2bf4318ae9
  - lupin_mcp.reuse_tools.call_budget_cap_for@ac99c25d0c
  - lupin_mcp.reuse_tools.ReuseError@d93dd15bda
  - lupin_mcp.reuse_tools.ReuseContext@ea5878584c
  - lupin_mcp.reuse_tools.context_from_environment@f0ef2b8cf0
---
# Reuse tools: request identity and context

The helpers at the top of `reuse_tools.py` fix what one Jev question is and how it is named. They also build the environment it runs in. [[reuse-search-tools]] covers the tools built on them.

## Request and receipt identity
- `canonical` is sorted-key compact JSON. `sha` is a sha1 hex, cut to `n` characters when given. Every hash below goes through them.
- `prompt_template_hash` gives 12 hex characters for the Jev instructions and criteria.
- `build_request` holds only the need and the candidate's signature and first docstring line. It refuses a model name ending in `-latest`. `request_hash` of the body keys the response cache.
- `receipt_id` gives 16 hex characters for one question. The tool version, query, index, model, policy, template and uncertainty causes all change it.
- A sweep-only question, an excluded symbol, a candidate stage, a language and the test flag each add their own field. A question with none of them keeps the id the old path produced.
- `write_once` writes through a temporary file and a hard link. An existing file is never overwritten, and it returns whether this call wrote it.

## Language and budget
- `language_error` accepts `py`, `ts`, `dart` and `all`. `None` gives `LANGUAGE_REQUIRED`; any other value gives `LANGUAGE_INVALID`. Both list the choices.
- `in_language` keeps the entries of one language in order. `all` keeps every entry.
- `call_budget_cap_for` gives an arm's cap on HTTP attempts: the entry count plus a percentage, rounded up. It never falls below the base cap.

## Context
- `ReuseError` carries a name and detail. Callers get it back as an error dict, never as a verdict.
- `ReuseContext` holds the root, the data directory and the injected parts: transport, sweeper, candidate stage and policy. It raises `BAD_BUDGET` for a call budget that is not a whole number in range. It also holds `tests_gen`, set by `prepare` for a call that reads test records.
- `context_from_environment` builds one for the git toplevel and excludes no module. A directory that is not a repository is used as it is, and the tools then answer `NOT_LUPIN_TREE`.
- `LUPIN_REUSE_DATA_DIR` and `LUPIN_REUSE_OUT_DIR` relocate the data directory and the generated index. A `LUPIN_REUSE_JEV_CALL_BUDGET` above the cap is refused, not clamped.
