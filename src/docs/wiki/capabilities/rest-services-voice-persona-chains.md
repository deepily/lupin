---
capability: rest-services-voice-persona-chains
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.voice_persona_helpers.display_name_for@ce21bdcb12
  - cosa.rest.voice_persona_helpers.load_overflow_persona_from_config@5faaf4cdf4
  - cosa.rest.voice_persona_helpers.allocate_persona_for_session@825d961b5b
  - cosa.rest.voice_persona_helpers.allocate_requested_persona_for_session@9fca137929
  - cosa.rest.voice_persona_helpers.pick_requested_persona@6be0cefad5
  - cosa.rest.voice_persona_helpers.parse_persona_chain@9ef10a184b
  - cosa.rest.voice_persona_helpers.parse_declared_managers@cdee2dc5b8
  - cosa.rest.voice_persona_helpers.pick_persona_chain_from_env@a791f8f5e8
  - cosa.rest.voice_persona_helpers.pick_declared_managers_from_env@668372bfd9
  - cosa.rest.voice_persona_helpers.resolve_session_start_persona_chain@65e9a8b249
---
# Voice persona chains, managers and allocation

The helpers that turn environment settings into a persona choice for a new session. The allocation route and pool rules are in [[voice-persona-allocation]].

## What it does
- `display_name_for( pool_name )` turns a pool key into its display form: `"mr radio"` becomes `"Mr. Radio"`, `"maria"` becomes `"María"`, an empty value gives `""`.
- `load_overflow_persona_from_config` reads the persona handed out when the pool is full (default `sam`). It returns `None` when it has no voice id or the name is set blank.
- `parse_persona_chain( raw )` splits a comma-separated string or list into ordered elements, drops case-insensitive duplicates, and keeps `*` as "then anything free". A JSON list string is read as a list.
- `parse_declared_managers( raw )` parses a manager roster and drops `*`. It de-duplicates by canonical persona key, so `Mr. Radio` and `mr radio` count once, and it does not read a JSON list string.
- `pick_persona_chain_from_env( project )` returns the raw `COSA_VOICE_PREFERRED_PERSONA__<PROJECT>` value, or `None`. `pick_declared_managers_from_env` reads `COSA_VOICE_MANAGERS__<PROJECT>` into a name list. The project is upper-cased with hyphens turned into underscores.
- `resolve_session_start_persona_chain( project, environ )` picks the chain a SessionStart sends. `COSA_VOICE_PERSONA_CHAIN` wins. Next, a headless child (`COSA_VOICE_HEADLESS` is `"1"`) gets `None`. Next comes the per-repo variable. With none set the result is `None` and the server allocates at random.
- `allocate_persona_for_session( config_mgr, stable_session_id, declared_managers )` reads the pool, scans occupied personas, and picks or borrows one. Declared managers are never picked at random. It returns `None` for an empty pool.
- `pick_requested_persona` returns status `ok`, `not_in_pool` or `occupied`, with the free names. `allocate_requested_persona_for_session` wraps it and excludes the requester's own persona, so a swap works.

## Don't
- Don't treat an empty pool as a client error. The allocator returns `None` and callers answer 500.
- Don't let a spawned worker inherit the per-repo manager default; the headless rule exists for that.

## Invariants
- The two parse functions return `[]` for `None`, blank input or a type other than string or list. A list gives its string items.
