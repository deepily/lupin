---
capability: voice-persona-allocation
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.rest.voice_persona_helpers.load_persona_pool_from_config@3194ca9821
  - cosa.rest.voice_persona_helpers.pick_unallocated_persona@3a5cf8dba3
  - cosa.rest.voice_persona_helpers.borrowed_persona_for_sid@8afa17e241
  - cosa.rest.voice_persona_helpers.allocate_persona_chain_for_session@423b5d8f3d
  - cosa.rest.routers.voice_persona.allocate_voice_persona_endpoint@9527ca55f8
  - cosa.rest.routers.speakerphone.set_speakerphone_endpoint@28d19bf3e7
  - lupin_mcp.persona_normalization.canonical_persona_key@2d2cdf3a9b
  - lupin_mcp.persona_normalization.normalize_for_match@49bc823e64
  - lupin_mcp.commons_persona_matcher.match_persona@62e4b1e574
  - lupin_mcp.commons_llm_disambiguator.CommonsLlmDisambiguator.disambiguate@015c52a9b8
---
# Voice persona allocation

Each Claude Code session gets a named voice, so parallel sessions can be told apart by ear. This page covers the allocation, the speakerphone switch beside it, and the name normalization every persona lookup shares. Persona rows in the store are keyed by the same normalized names ([[task-store]]).

## What it does
- The pool is the comma-separated list in `cc session voice persona pool`. Each name needs a voice id in the INI; a name with no voice id is skipped. Its icon, colour and profile are optional and default to a microphone emoji, `#888888` and an empty profile. The list resolved to 14 names on 2026-10-07.
- `pick_unallocated_persona` draws uniformly at random from the pool, minus the names in use and minus any declared manager names. The caller passes the names in use; `allocate_persona_for_session` reads them fresh from the live bridge files on every call. A persona-bearing bridge older than `cc session voice persona stale threshold seconds` (43200) does not count unless its process is proven alive. A live process keeps its bridge occupied. The age decides only when liveness cannot be checked: inside a container, or when the bridge filename carries no process id.
- With no free name left in the random draw, a session gets the overflow persona (`cc session voice persona overflow name`, `arnold`). Declared-manager names are held out of that draw, so they can empty it before the pool is full. A second overflow session gets an "Extra N" persona with the lowest free N. A blank overflow name, or one with no voice id, counts as no overflow. With no overflow configured, `borrowed_persona_for_sid` picks by a sha256 of the session id, so a session borrows the same voice after a restart.
- `routers.voice_persona` serves `GET /api/cosa-voice/voice-persona/pool`, `GET .../voice-persona/{session_id}` (reads the bridge, 404 if none), `POST .../{session_id}/allocate`, `POST .../{session_id}/release` and `POST .../sample`. `allocate` takes no request, a requested name, or a `persona_chain`.
- `routers.speakerphone` serves `GET` and `POST /api/cosa-voice/speakerphone/{session_id}`. In solo mode an activation displaces other active sessions. In chorus mode it displaces none. The default is off in solo and on in chorus.
- `match_persona` resolves a typed or spoken name to a candidate: mechanical match first, then the LLM disambiguator that `main.py` installs at startup.

## Invariants
- The bridge file is the single source of truth. There is no registry in memory, and the router holds one lock around the scan, pick and write.
- `allocate` with no request returns the persona the session already holds. A requested name that is not in the pool answers 422. So does a request that sends both a name and a chain, and so does a chain with no elements. A name held by another session answers 409 and lists the free names. A chain used up without a `*` also answers 409. An empty or misconfigured pool answers 500, and so does a failed bridge write. A session with no bridge answers 404.
- A `persona_chain` is tried in order and the first free name wins; `*` means any free name. A chain that runs out without `*` answers 409 and leaves the session without a persona. A chain never overrides an existing allocation.
- `release` is idempotent: releasing an empty slot answers 200 with `released=False`.
- Compare persona names with `canonical_persona_key`, never a bare `.lower()`: `María` and `Mr. Radio` become `maria` and `mr radio`. `normalize_for_match` is for typed text and gives `mrradio`. `persona_slug` is for file and topic names and gives `mr-radio`.
- The disambiguator's answer must be in the active persona list, or the result is `None`.
- `persona_key_backfill` rewrites stored persona values that are not canonical. It is a dry run unless `--apply` is passed, and a second run changes nothing.

## How to extend
- Add a voice by adding its name to the pool key and its voice id to the INI. Add an icon, colour and profile if the defaults will not do. A plain name needs no code change. A name with an accent needs an entry in `_DISPLAY_OVERRIDES`.
- Pass every persona string through `canonical_persona_key` at each store write and query seam.
