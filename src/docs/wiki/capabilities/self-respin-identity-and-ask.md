---
capability: self-respin-identity-and-ask
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.self_respin_core.SelfRespinResult@6c8c181db2
  - lupin_mcp.self_respin_core.self_respin_from_bridge@0945f200f5
  - lupin_mcp.self_respin_core.resolve_identity_from_cc_meta@17132a9060
  - lupin_mcp.self_respin_core.resolve_own_identity@ed095de777
  - lupin_mcp.self_respin_core.lookup_persona_record@49baefea4e
  - lupin_mcp.self_respin_core.parse_own_pressure@2b3464799c
  - lupin_mcp.self_respin_core.confirmation_text@6cb74cb84a
  - lupin_mcp.self_respin_core.confirmation_kwargs@71ad707c49
  - lupin_mcp.self_respin_core.gate_proceed@4f1b137bf0
  - lupin_mcp.self_respin_core.last_call_verdict@152c264efe
---
# Self re-spin: identity, pressure and the ask
`self_respin` lets a seat at its context ceiling clear its own pane and wake as the same seat ([[mcp-session-spawn-and-reap]]). This page covers who is asking and whether to go. The engine is in `self_respin_core.py`.
- `SelfRespinResult` is the outcome. Its `status` is `scheduled`, `declined` or `aborted`, and `warnings` never change it.
- `self_respin_from_bridge` resolves the seat's own identity and context pressure, then runs the verb. The id comes from the bridge, never from the caller.
- `resolve_identity_from_cc_meta` returns the session id and persona, with the stable id first. `resolve_own_identity` falls back to a default when the bridge call raises.
- `lookup_persona_record` finds a seat in the pressure roster, ignoring capitalisation. An exact key wins.
- `parse_own_pressure` returns the status and percent of window for one persona from the pressure section.
- `confirmation_text` is the spoken ask, in the third person, so the listener knows which seat is asking.
- `confirmation_kwargs` holds every argument of that ask, so tests can pin them. It defaults to yes, so an absent human does not strand a seat.
- `gate_proceed` turns the answer into proceed or abort. A real no aborts, and a defaulted answer proceeds.
- `last_call_verdict` returns skip, proceed or unknown, and never raises. Marker and clear steps are on [[self-respin-memento-and-clear]].
