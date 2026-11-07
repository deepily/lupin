---
capability: duplicate-check-filing
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_filing.correlation_key@0c74ec30fe
  - lupin_mcp.duplicate_check_filing.for_record@630a473baf
  - lupin_mcp.duplicate_check_filing.NoTriageOwner@022bda2814
  - lupin_mcp.duplicate_check_filing.triage_owner@0b90ebd7c1
  - lupin_mcp.duplicate_check_filing.run_key@176353e748
  - lupin_mcp.duplicate_check_filing.triage_payload@857553a740
  - lupin_mcp.duplicate_check_filing.read_pending@3fed62ce79
  - lupin_mcp.duplicate_check_filing.write_pending@593f4e0294
  - lupin_mcp.duplicate_check_filing.send_row@2f4f15f5b4
  - lupin_mcp.duplicate_check_filing.gated@eaa079cb6c
  - lupin_mcp.duplicate_check_filing.read_triaged@453a0be918
  - lupin_mcp.duplicate_check_filing.append_triaged@f2f7870125
  - lupin_mcp.duplicate_check_filing.file_findings@46e1f049b7
  - lupin_mcp.duplicate_check_filing.LiveStore@e40bee82b7
---
# Duplicate check filing
`lupin_mcp.duplicate_check_filing` files one triage row for each run of the daily check, listing the duplicates it found. To file a saved result again, see [[duplicate-check-refile]].

## What it does
- `correlation_key( id, text )` is `epic:dupcheck-` and 16 hex digits of the sha256 of the id and the sha256 of the definition's text. It holds no date.
- `for_record( finding )` drops the text and adds the key, so the result file can be refiled with no source to hand.
- `triage_owner( declared, roster )` returns the lowercase persona key of the roster entry that matches the configured manager, whatever the case or accent. Otherwise it returns the first roster persona and the note says so. An empty roster raises `NoTriageOwner`: a row never lands on a role label.
- `run_key( keys )` is `epic:dupcheck-run-` and 16 hex digits of the sha256 of the sorted finding keys. The same findings give the same row key.
- `triage_payload( findings, owner, day )` builds a P5 task with no status, so the store's holding default applies. The title starts with `[LUPIN] Duplicate check <day>:` and asks whether the new functions should reuse existing ones.
- The body says why the row exists and what to do: a `DUPCHECK-VERDICT` line per function, see [[duplicate-check-verdict-lines]]. It also names the owner and lists the first 200 findings with what they repeat, then counts the rest and names the result file. Every finding key is still recorded as triaged. `created_by` is `duplicate-check-daily`, with no session id.
- The row's title day is the findings' `day` field, else today; a refile sets it from the result file's date.
- `file_findings` leaves out findings already in `triaged.jsonl` or in a spooled row. With none left it files nothing. Otherwise it sends the spooled rows, then the new one, and writes the findings of a row the store took to `triaged.jsonl`.
- `send_row( payload, store )` asks the store for the key before the create. It answers `already_filed`, `filed`, `queued_for_retry` or `refused`.
- A probe that does not answer ok queues the row. A create with no status, a transport failure, queues it too. So does a 422 whose `detail` or `error` text contains `New tickets are gated`; `gated( body )` makes that test.
- `read_pending` and `write_pending` read and write the spool, `pending-rows.jsonl` in the record folder. An empty list removes the file. The spool is written by temporary file and rename. A row spooled before the triage row existed has no finding keys and is still sent.
- `read_triaged` and `append_triaged` read and append the triaged keys.
- `LiveStore` ([[utils-task-store-adapter]]) is the store over HTTP with the hooks' own client. It needs no MCP session, and its `query` and `create` never raise. `query` asks for every state, held rows included. `amend( row_id, note )` appends a note to a row; [[duplicate-check-verdict-lines]] uses it.
