---
capability: rest-routers-voice-and-speakerphone
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.routers.speakerphone.get_notification_queue@419a0b0054
  - cosa.rest.routers.speakerphone.SpeakerphoneBody@0f990c653f
  - cosa.rest.routers.speakerphone.get_speakerphone_endpoint@369a88b108
  - cosa.rest.routers.voice_persona.get_notification_queue@419a0b0054
  - cosa.rest.routers.voice_persona.get_config_manager@ce7d0e35b7
  - cosa.rest.routers.voice_persona.get_voice_persona_pool@7807b69fbc
  - cosa.rest.routers.voice_persona.get_voice_persona_endpoint@0b5050b505
  - cosa.rest.routers.voice_persona.release_voice_persona_endpoint@bbf490b347
  - cosa.rest.routers.voice_persona.VoicePersonaSampleRequest@7de00d499f
  - cosa.rest.routers.voice_persona.voice_persona_sample@baa9abadfa
---
# Voice persona and speakerphone routes

The `/api/cosa-voice` routes that read and change a session's voice persona and speakerphone flag, both kept on the session bridge file. Every route takes an API key or a JWT. See [[voice-persona-allocation]].

## What it does
- `get_voice_persona_pool` (`GET /voice-persona/pool`) returns the configured pool, occupied names, free names and the active sessions holding a persona. A dead-PID bridge counts as free. It takes no session id.
- `get_voice_persona_endpoint` (`GET /voice-persona/{session_id}`) returns a session's persona, or null.
- `release_voice_persona_endpoint` (`POST /voice-persona/{session_id}/release`) clears the persona and broadcasts `voice_persona_released`. It answers `released: false` when none was set, and 500 when the bridge write fails.
- `allocate_voice_persona_endpoint` (`POST /voice-persona/{session_id}/allocate`, no pin here) takes the query fields `requested_persona_name`, `persona_chain`, `declared_managers` and `previous_persona_name`. With neither of the first two it returns an existing persona unchanged, or picks a free one. A requested name that is already held answers 409 and one outside the pool 422. A `persona_chain` (comma-separated, `*` for any free one) takes the first free name, and an exhausted chain is 409. Both fields together, or an empty chain, is 422. `declared_managers` keeps those names out of the random and `*` picks. An empty pool is 500, and so is a failed bridge write.
- `VoicePersonaSampleRequest` (`voice_id`, `text`) feeds `voice_persona_sample` (`POST /voice-persona/sample`), which returns `audio/mpeg`. A voice outside the pool, or a blank `voice_id` or `text`, is 400. A missing ElevenLabs key or an upstream failure is 503.
- `get_config_manager` builds a `ConfigurationManager` for these routes.
- `get_notification_queue` (in both routers) hands the notification queue from the main module to a route.
- `get_speakerphone_endpoint` (`GET /speakerphone/{session_id}`) returns `{ session_id, on }`. A bridge with no flag gets the mode default: false in solo, true in chorus.
- `POST /speakerphone/{session_id}` takes a `SpeakerphoneBody` (`on`) and writes the flag to the bridge. It broadcasts `speakerphone_changed` and returns `broadcast_delivered` and `displaced_sessions`. In solo mode, turning it on first turns it off on every other active session. In chorus mode nothing is displaced.

## Don't
- Don't pass an arbitrary `voice_id` to the sample route. Only pool voices and the overflow persona's voice are served.
- Don't treat a failed broadcast as a failed write. The bridge write is the state, and a push failure is only logged.

## Invariants
- A session id with no bridge answers 404 on the per-session routes. The pool and sample routes take no session id.
