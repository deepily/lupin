---
capability: reuse-tools-index-helpers
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_tools.sendable_report@f0c11073ef
  - lupin_mcp.reuse_tools.dropped_view@5cd920178f
  - lupin_mcp.reuse_tools.make_refresher@e5fa6fbe4d
  - lupin_mcp.reuse_tools.note_if_slow@49b445414f
---
# Reuse tools: send screen, refresher and slow note
Four helpers of `reuse_tools.py` behind the lookup tools on [[reuse-search-tools]]. The refresher serves the [[candidate-stage]].
- `sendable_report` is the one place that decides what of the index may leave the machine. It returns the kept entries and a map of dropped ids by reason.
- Kept entries are copies, in input order, with string defaults blanked. Every language is kept, and no module is excluded unless the prefix list names it.
- Dropped ids are of two kinds. Sensitive content still present after blanking, and ids under an excluded prefix. Both keys are always present.
- `dropped_view` shapes that map for a result and a receipt: a count and the first few ids per reason. A call that dropped nothing gives an empty map.
- `make_refresher` builds the run-time refresher of a candidate stage. It returns a function that runs the incremental vector build under its lock.
- The build embeds new or changed rows and keeps the rest. It writes no purpose lines and never waits for the job that writes them.
- `note_if_slow` adds a slow-refresh note once per call, when the time since the call began passes the bound. The answer is never held back or changed.
