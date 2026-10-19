---
capability: cc-bookmark-janitors
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.bookmark_janitor.BookmarkFamily@c35a3fcf89
  - lupin_cli.claude_code.hooks.lib.bookmark_janitor.family_session_fragment@b5f12821b8
  - lupin_cli.claude_code.hooks.lib.bookmark_janitor.classify_bookmark_file@22c260b0bb
  - lupin_cli.claude_code.hooks.lib.bookmark_janitor.report_bookmark_files@a6f947acb3
  - lupin_cli.claude_code.hooks.lib.bookmark_janitor.sweep_and_reclaim_bookmark_files@168e8741cf
  - lupin_cli.claude_code.hooks.lib.dm_inbox_hwm_janitor.hwm_sid8@56142af01f
  - lupin_cli.claude_code.hooks.lib.dm_inbox_hwm_janitor.classify_hwm_file@2d059a0894
  - lupin_cli.claude_code.hooks.lib.dm_inbox_hwm_janitor.report_hwm_files@057d7739bd
  - lupin_cli.claude_code.hooks.lib.dm_inbox_hwm_janitor.sweep_and_reclaim_hwm_files@7415d8c66b
---
# Bookmark file janitors
Reclaim per-session bookmark files once their sessions are gone. Bookmarks are meant to survive `/clear`, so they are deleted only when provably dead.
## What it does
- `BookmarkFamily` names one family by prefix and suffix, plus sentinel ids that name no session. Its `glob` is the prefix, a star and the suffix.
- The owned families are the ask-answer marks, the task-store maps and the heartbeat acked ledgers.
- `family_session_fragment` pulls the session id fragment out of a filename, or None for a foreign file.
- `classify_bookmark_file` is the keep-or-prunable rule. A file is prunable only with a live-session set, a non-sentinel fragment absent from it, and mtime age past the grace window.
- `report_bookmark_files` classifies and tallies without deleting. `sweep_and_reclaim_bookmark_files` deletes what the rule proves orphaned and aged.
- `dm_inbox_hwm_janitor` does the same for `.dm-inbox-hwm-<sid8>.json`: `hwm_sid8`, `classify_hwm_file`, `report_hwm_files` and `sweep_and_reclaim_hwm_files`.
## Don't
- Don't compare full session ids. The filenames hold the first eight characters.
## Invariants
- The janitors bias to keep. No live-session set keeps everything, and an empty set is never read as nothing alive.
- An unreadable or future mtime is not provable age and is kept.
- Report and sweep share one classifier, so the dry run matches the delete.
