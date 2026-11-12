---
capability: duplicate-check-filing
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_filing.correlation_key@0c74ec30fe
  - lupin_mcp.duplicate_check_filing.for_record@630a473baf
  - lupin_mcp.duplicate_check_filing.NoTriageOwner@022bda2814
  - lupin_mcp.duplicate_check_filing.triage_owner@3dd54aeadb
  - lupin_mcp.duplicate_check_filing.run_key@176353e748
  - lupin_mcp.duplicate_check_filing.triage_payload@0e998a8fdb
  - lupin_mcp.duplicate_check_filing.triage_payloads@d5742c7adc
  - lupin_mcp.duplicate_check_filing.fit_body@88ea131cfc
  - lupin_mcp.duplicate_check_filing.read_pending@90d2acdec8
  - lupin_mcp.duplicate_check_filing.write_pending@593f4e0294
  - lupin_mcp.duplicate_check_filing.send_row@935ac438df
  - lupin_mcp.duplicate_check_filing.gated@eaa079cb6c
  - lupin_mcp.duplicate_check_filing.read_triaged@d0fab6e23f
  - lupin_mcp.duplicate_check_filing.append_triaged@f2f7870125
  - lupin_mcp.duplicate_check_filing.file_findings@c568749ba4
  - lupin_mcp.duplicate_check_filing.LiveStore@e40bee82b7
---
# Duplicate check filing
`lupin_mcp.duplicate_check_filing` files the triage rows for each run of the daily check, listing the duplicates it found. To file a saved result again, see [[duplicate-check-refile]].

## What it does
- `correlation_key( id, text )` is `epic:dupcheck-` and 16 hex digits of the sha256 of the id and the sha256 of the definition's text. It holds no date. `for_record( finding )` drops the text and adds the key, so a result file can be refiled with no source to hand.
- `triage_owner( declared, roster )` returns the lowercase persona key of the roster entry that matches the configured manager, whatever the case or accent. It never guesses. An empty roster raises `NoTriageOwner`, and so does a configured name that is blank, a role label or not on the roster. A row never lands on a role label or on a seat of another project.
- `run_key( keys )` is `epic:dupcheck-run-` and 16 hex digits of the sha256 of the sorted finding keys. The same findings give the same row key.
- `triage_payload( findings, owner, day )` builds one P5 task with no status, so the store's holding default applies. The title starts with `[LUPIN] Duplicate check <day>:` and asks whether the new functions should reuse existing ones.
- The body says why the row exists and what to do: a `DUPCHECK-VERDICT` line per function, see [[duplicate-check-verdict-lines]]. It names the owner. It lists up to 200 findings, each with up to 5 of the definitions it repeats and a count of the rest. `created_by` is "<owner> (duplicate-check-daily)" with no session id.
- The payload also carries `finding_keys`, every finding's key, so the filer can mark them triaged. The key is removed before the create.
- `triage_payloads` splits a run into as many rows as it takes. Each row lists its findings in at most 200 findings and 30000 characters. With more than one row each title ends "(part n of m)".
- `fit_body( body )` cuts a body at a line boundary to the limit and ends with a line counting what was left out. `send_row` applies it, so a spooled row is cut too.
- `file_findings` leaves out findings already in `triaged.jsonl` or in a spooled row. It sends the spooled rows first, then the new ones. It writes the findings of a row the store took, or already held, to `triaged.jsonl`.
- A spooled row with no `finding_keys` is in the retired one-row-per-definition shape. It is never sent, and is listed under `retired_shape`. A spooled row over the limit is listed under `oversize_body` and not sent, and its findings are not marked seen. Both stay in the spool for a person to remove.
- `send_row( payload, store )` asks the store for the key before the create. It answers `already_filed`, `filed`, `queued_for_retry` or `refused`, with the first 300 characters of the store's answer as detail on the last two.
- A probe that does not answer ok queues the row. So does a create with no status, or a 422 whose `detail` or `error` contains `New tickets are gated`; `gated( body )` makes that test.
- `read_pending` and `write_pending` read and write the spool, `pending-rows.jsonl` in the record folder. `read_triaged` and `append_triaged` read and append the triaged keys.
- `LiveStore` ([[utils-task-store-adapter]]) is the store over HTTP with the hooks' own client. It needs no MCP session. `query` asks for every state, held rows included, and never raises. `amend( row_id, note )` appends a note to a row; [[duplicate-check-verdict-lines]] uses it.
