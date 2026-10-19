---
capability: cc-hook-context-clear-marker
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.register_session.emit_context_clear_marker@095c2a651d
---
# Hook context-clear marker

A context reset leaves no trace in the logs by itself. The SessionStart hook writes one marker line when the session was cleared, so a reset can be matched with a change in behaviour.

## What it does
- `emit_context_clear_marker( payload )` reads `payload["source"]`, which is one of startup, resume, clear or compact.
- When the source is `clear` it writes a `{"marker": "context_cleared", "source": "clear"}` line to the `session_start` log stream and returns True.
- For any other source, or none, it writes nothing and returns False.
- The source is the authoritative lifecycle signal. The heuristic that watches the session id rotate under-reports.

## Don't
- Don't infer a clear from a changed session id. Use the payload's `source`.

## Invariants
- At most one marker line per call.
