---
capability: shadow-pending-reid
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.shadow_pending_reid.ReidRefused@04b31f320f
  - lupin_mcp.shadow_pending_reid.read_items@4c35406b12
  - lupin_mcp.shadow_pending_reid.make_plan@462660ea62
  - lupin_mcp.shadow_pending_reid.apply_plan@d4c5d37417
  - lupin_mcp.shadow_pending_reid.parse_code@47cc9eb65b
  - lupin_mcp.shadow_pending_reid.main@d9431fd32d
---
# Shadow pending: one-off re-id repair
`python -m lupin_mcp.shadow_pending_reid <folder>` repairs shadow-audit queue items that still carry the daily check's own `d-` id as `exclude_id`. The sweep's index does not know that id, so each drain refuses the item as `UNKNOWN_ENTRY` and drops it on the third try. The queueing side is in [[duplicate-check-audit]]; the queue is in [[repo-tools-candidate-shadow-audit-queue]].

## What it does
- It lists a plan and changes nothing unless `--apply` is given. Exit 0 means the plan was listed or applied. Exit 3 means it was refused and nothing was changed.
- `--code d-id=file:name` rewrites that item to the index id of the named definition. `--drop d-id` removes that item. Removing with `--apply` needs `--reason`, which goes in the log.
- `read_items` reads every `*.json` file in the folder, sorted by name. A file that is not a queue item raises `ReidRefused`, so a corrupt file is never skipped over.
- `make_plan` gives each item one step, `rewrite` or `remove`. `ReidRefused` follows for an item whose `exclude_id` is not a `d-` id, is in neither list, or is in both. It also follows for a definition the index does not hold exactly once by file and name, so no line number is guessed.
- `apply_plan` writes a rewritten item as a new file, named by the queue's own id rule. The new file has the new `exclude_id` and `attempts` 0. Then the old file is removed. A new name that already exists stops the run. A removed item's file is removed. Each step appends one JSON line to `shadow-pending-reid.log` in the sibling `shadow-audit` folder.
- `parse_code` reads the `--code` pairs and raises `ReidRefused` for one that is not `d-id=file:name`.
- `main` takes its index records from the lookup tool's own context unless a caller supplies them.

## Don't
- Don't run it as routine. It exists for the items queued before the daily check began queuing index ids.
