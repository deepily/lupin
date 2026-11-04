---
capability: rest-routers-poke-mute-and-fcm-pause
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.routers.fcm.RegisterTokenRequest@1511eb3889
  - cosa.rest.routers.fcm.UnregisterTokenRequest@4faa4595c6
  - cosa.rest.routers.fcm.register_fcm_token@d0cbe741b7
  - cosa.rest.routers.fcm.unregister_fcm_token@bf42c12d7e
  - cosa.rest.routers.fcm.PushPauseRequest@b2dc25fbd6
  - cosa.rest.routers.fcm.set_push_pause@f9f9f0b7c1
  - cosa.rest.routers.fcm.get_push_pause@bd6a8ee3cc
  - cosa.rest.routers.heartbeat.PokeMuteRequest@ea442fc847
  - cosa.rest.routers.heartbeat.derived_poke_mute_state@bdfba123ac
  - cosa.rest.routers.heartbeat.refuse_api_key_writer@c1072d2742
  - cosa.rest.routers.heartbeat.get_poke_mute@0c87612a3e
---
# Poke mute and mobile push routes

The fleet switch for the heartbeat Stop poke (`/api/heartbeat`) and the mobile wake-push registry and pause (`/api/fcm`). See [[heartbeat-arbiter]] and [[notification-delivery]].

## What it does
- `get_poke_mute` (`GET /api/heartbeat/poke-mute`) returns the derived state from `derived_poke_mute_state`, for an API key or a JWT.
- `derived_poke_mute_state` reads the switch file and skeleton crew. `muted` is true when either is on, and `source` is `file`, `skeleton_crew`, `both` or `none`. It writes nothing.
- `PokeMuteRequest` is the body of `PUT /api/heartbeat/poke-mute` (`put_poke_mute`, on [[heartbeat-arbiter]]): one strict boolean, `muted`. `refuse_api_key_writer` answers 403 to an API-key-only caller before the admin check.
- `register_fcm_token` (`POST /api/fcm/register-token`) upserts a device token for the authenticated user. `RegisterTokenRequest` holds `token`, `platform` (only `android`) and `user_email`.
- `unregister_fcm_token` (`POST /api/fcm/unregister-token`) removes a token and answers 200 even when none existed. `UnregisterTokenRequest` holds the `token`.
- `set_push_pause` (`POST /api/fcm/push-pause`) is admin only. `PushPauseRequest` holds `paused` and `minutes`. A pause lasts until the timer, a resume or a restart.
- `get_push_pause` (`GET /api/fcm/push-pause`, also admin only) reports the state, including the live `push_enabled` key.

## Don't
- Don't pass `minutes` outside 1 to 1440 with `paused: true`. The handler answers 400.
- Don't look for the pause in the INI file. It lives in memory only.

## Invariants
- A token is bound to the authenticated user id, not to the body's `user_email`.
