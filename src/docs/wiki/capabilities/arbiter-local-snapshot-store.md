---
capability: arbiter-local-snapshot-store
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_arbiter_app.local_snapshot_store.LocalSnapshotStore@2188d3215a
---
# Arbiter local snapshot store

This is the in-process, section-keyed store behind `GET /state` on the 8001 service. Each loop writes its own named section, and the route reads the whole composite.

## What it does
- `LocalSnapshotStore` holds a map from section name to value. `set_section( name, value )` replaces that one section only.
- `get_section( name )` returns one section, or None when it is unset. `get` returns a shallow copy of the whole map. `clear` empties it.
- The health watcher, the fleet arbiter and the context-pressure writer each write their own section of one shared instance. None overwrites another.
- The fleet arbiter writes through a sink adapter pointed at its `fleet_arbiter` section, so its own code is unchanged.
- A lock serialises the loop threads that write and the route that reads.

## Don't
- Don't put a value in a section that cannot be turned into JSON. The route returns it as JSON.
- Don't use this store for anything that must survive a restart. It holds memory only.

## Invariants
- It does no file I/O and no network calls.
- It never imports the dev server's snapshot singleton, so the fleet-stall path works whether or not that server is up.
