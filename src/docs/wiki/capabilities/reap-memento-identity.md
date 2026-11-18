---
capability: reap-memento-identity
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - lupin_mcp.reap_memento.identity_bits@0135dd5f9d
---
# Reap memento: identity bits

A helper of [[reap-memento-checks]]: it reads who a seat is from the identity captured before a reap.

## What it does
- `identity_bits( ident )` returns `( persona_name, session_id )` from a captured reap identity.
- The persona is the `name` of a voice-persona dict, or a bare string. It returns None for any missing piece and never raises.
