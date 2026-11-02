---
capability: needset-control-bare-arm
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.first_thousand.original_entries@8805a49333
  - lupin_mcp.reuse_needset.first_thousand.NoModelCall@60aaf06b51
  - lupin_mcp.reuse_needset.first_thousand.RefusingTransport@5c041cd9db
  - lupin_mcp.reuse_needset.first_thousand.RefusingTransport.post_with_meta@554d2fa909
  - lupin_mcp.reuse_needset.control_report.reading@296d7511f5
---
# Need set: the control's bare arm and its original guard

The control plants 20 rewrites and checks each against its original. This page covers the second planted stage and the guard. Scoring is on [[needset-control-scoring]]; the command is on [[needset-first-thousand-command]].

## The original stays in the pool
- `original_entries` finds each pair's original in the index by file and name, and returns its id and stored purpose line.
- A pair's own original id matches no index id, so the checker leaves nothing out. The original competes with the plant in one search.
- It raises `CONTROL_ORIGINAL_EXCLUDED` if a pair's original id is an index id. It raises `CONTROL_ORIGINAL_UNRESOLVED` if no index entry has the original's file and name.

## The bare arm
- The same needs are searched a second time against a planted stage with no purpose lines. This gives `retrieval_bare`, the plants found without a line.
- `RefusingTransport` serves that arm. Every request raises `NoModelCall`, so the arm makes no model call.
- `reading` turns one id's place in the checker's answer and receipt into retrieved, accepted and ranks.
