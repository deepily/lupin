# Fleet Liveness & Unified Task-Store — Architecture (Top to Bottom)

How the Lupin fleet tracks owed work and keeps sessions alive: the unified task store, its three readers (heartbeat poke, arbiter, human UI card), the writers, and the migration.

## Contents

This page is an index. The reference itself is in the parts below, in document order.

- [1. Why this exists](fleet-liveness-and-task-store-architecture/01-why-and-the-one-store.md#1-why-this-exists)
- [2. The core: one store, three readers](fleet-liveness-and-task-store-architecture/01-why-and-the-one-store.md#2-the-core-one-store-three-readers)
- [3. Reader 1 — the heartbeat self-poke (Stop-hook liveness path)](fleet-liveness-and-task-store-architecture/02-readers-heartbeat-arbiter-card.md#3-reader-1--the-heartbeat-self-poke-stop-hook-liveness-path)
- [4. Reader 2 — the arbiter (`:8001`, out-of-band fleet watcher)](fleet-liveness-and-task-store-architecture/02-readers-heartbeat-arbiter-card.md#4-reader-2--the-arbiter-8001-out-of-band-fleet-watcher)
- [5. Reader 3 — the human UI card](fleet-liveness-and-task-store-architecture/02-readers-heartbeat-arbiter-card.md#5-reader-3--the-human-ui-card)
- [6. Writers — the manager/worker session lifecycle](fleet-liveness-and-task-store-architecture/03-writers-migration-and-file-map.md#6-writers--the-managerworker-session-lifecycle)
- [7. The migration & cutover machinery](fleet-liveness-and-task-store-architecture/03-writers-migration-and-file-map.md#7-the-migration--cutover-machinery)
- [8. File map / source-of-truth](fleet-liveness-and-task-store-architecture/03-writers-migration-and-file-map.md#8-file-map--source-of-truth)
- [9. Open follow-ups (see the dedicated plan)](fleet-liveness-and-task-store-architecture/03-writers-migration-and-file-map.md#9-open-follow-ups-see-the-dedicated-plan)

## Parts

| Part | Covers |
|---|---|
| [01-why-and-the-one-store.md](fleet-liveness-and-task-store-architecture/01-why-and-the-one-store.md) | why the page exists and the core design: one store, three readers |
| [02-readers-heartbeat-arbiter-card.md](fleet-liveness-and-task-store-architecture/02-readers-heartbeat-arbiter-card.md) | reader 1 (heartbeat self-poke), reader 2 (the arbiter) and reader 3 (the human UI card) |
| [03-writers-migration-and-file-map.md](fleet-liveness-and-task-store-architecture/03-writers-migration-and-file-map.md) | the writers, the migration and cutover machinery, the file map and the open follow-ups |
