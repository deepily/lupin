---
capability: rest-routers-arbiter-switches
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.routers.arbiter.FleetSnapshotIn@d268d47ccb
  - cosa.rest.routers.arbiter.get_fleet_snapshot@f6c8cfc229
  - cosa.rest.routers.arbiter.push_fleet_snapshot@f6577f319e
  - cosa.rest.routers.arbiter.FleetSizeCapIn@d17fd69d33
  - cosa.rest.routers.arbiter.get_fleet_size_cap@7238366e4a
  - cosa.rest.routers.arbiter.refuse_api_key_cap_writer@9d4e167301
  - cosa.rest.routers.arbiter.SkeletonCrewIn@4977e28e7b
  - cosa.rest.routers.arbiter.refuse_api_key_flipper@8300acad49
  - cosa.rest.routers.arbiter.put_skeleton_crew@25f4dc62c1
---
# Arbiter snapshot, fleet-size cap and skeleton crew routes

Three groups of `/api/arbiter` routes: the cached fleet snapshot, the fleet-size dial and the skeleton crew switch. The standalone arbiter itself is in [[heartbeat-arbiter]].

## What it does
- `get_fleet_snapshot` returns the last pushed snapshot, or `{ status: "awaiting", session_count: 0, sessions: [] }` before any push. A cold start is therefore not a zero-session fleet.
- `push_fleet_snapshot` caches a body validated by `FleetSnapshotIn` (`generated_at`, `session_count` of 0 or more, `sessions`) and answers `{ status: "ok", session_count }`. Both routes take an API key or a JWT.
- `get_fleet_size_cap` returns `{ cap, ceiling, live, skeleton_crew }`, read fresh on every call. The disk value of `cap` wins over the cached configuration.
- `FleetSizeCapIn` is the PUT body: one `cap` of 1 or more. The upper bound is the live `cc session fleet size cap maximum`, so a value above it is a 422.
- `put_skeleton_crew` takes `SkeletonCrewIn` (`on`, a strict boolean, no extra fields). It writes the switch file and the configuration file, then tells live sessions by an acknowledged broadcast. It returns the same body as the cap route.
- `refuse_api_key_cap_writer` and `refuse_api_key_flipper` run before the admin check. They answer 403 to a caller that sends an API key and no `Authorization` header.

## Don't
- Don't expect an API key to change the cap or the switch. Only an admin login can.
- Don't read the cap response as an echo. It is re-read from the file, so it shows what was persisted.

## Invariants
- A key missing or defined twice in the configuration file answers 409 with the writer's own message.
- A failed broadcast never fails a skeleton crew flip.
