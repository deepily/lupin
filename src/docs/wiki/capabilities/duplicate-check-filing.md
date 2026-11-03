---
capability: duplicate-check-filing
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_filing.content_hash@b2cc48627f
  - lupin_mcp.duplicate_check_filing.correlation_key@ed891fbc89
  - lupin_mcp.duplicate_check_filing.for_record@630a473baf
  - lupin_mcp.duplicate_check_filing.manager_for@9a48ea9ec3
  - lupin_mcp.duplicate_check_filing.row_payload@da1516ef49
  - lupin_mcp.duplicate_check_filing.read_pending@3fed62ce79
  - lupin_mcp.duplicate_check_filing.write_pending@c972f92272
  - lupin_mcp.duplicate_check_filing.send_row@9280e1e358
  - lupin_mcp.duplicate_check_filing.file_findings@a001bff541
  - lupin_mcp.duplicate_check_filing.LiveStore@e9a09587a3
---
# Duplicate check filing
`lupin_mcp.duplicate_check_filing` files one store row for each duplicate the daily check finds, once per definition text. To file a saved result again, see [[duplicate-check-refile]].

## What it does
- `content_hash( text )` is the sha256 hex of the definition's text. `correlation_key( id, text )` is `epic:dupcheck-` and 16 hex digits of the sha256 of the id and that hash. It holds no date.
- A repeat run, a run the next day and a run that failed before it advanced file no second row.
- `for_record( finding )` drops the text and adds the key, so the result file can be refiled with no source to hand.
- `manager_for( session_id, declared, roster )` finds the manager from the seat's spawn lineage. If the bridge is gone, it uses the configured manager when that name is on the roster.
- An unresolved finding still goes to the configured manager, with a note saying so. No row is ownerless.
- `row_payload( finding, found )` builds a P5 task with no status, so the store's holding default applies. `created_by` is `duplicate-check-daily`, with no session id.
- `send_row( payload, store )` asks the store for the key before every create. It answers `already_filed`, `filed`, `queued_for_retry` or `refused`.
- A transport failure, on the probe or the create, queues the row. So does a 422 whose error text contains `New tickets are gated`.
- `file_findings` tries the spooled rows first, then new ones. The spool, `pending-rows.jsonl` in the record folder, afterwards holds only the queued rows.
- `read_pending` and `write_pending` read and write the spool. An empty list removes the file.
- `LiveStore` is the store over HTTP with the hooks' own client. It needs no MCP session, and its `query` and `create` never raise.
