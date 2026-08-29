# What's New — archive

Release highlights for earlier versions, in the narrative form they were written in.

**The current release's highlights live in [README.md](README.md).** Only the newest version is kept there; everything before it is moved here as each release ships.

For the terser per-version summaries, see [VERSION-HISTORY.md](VERSION-HISTORY.md). For the older per-feature changelog, see [CHANGELOG.md](CHANGELOG.md).

---

## What's New in v0.1.9 — off LanceDB, onto the cloud, and instruments you can believe

v0.1.9 (June–August 2026) replaced the vector store under the whole platform, moved Lupin onto a real GCP deployment, and spent a lot of its effort on a less glamorous question: **how do you know a green test is telling the truth?**

- **LanceDB → PostgreSQL + pgvector, live.** The vector store was swapped out in four lanes — ORM models + Alembic migration, eight per-table repositories behind a runtime backend flag, consumer routing, then the backfill. Cutover ran 2026-07-07: ~202,000 vectors backfilled, dual-engine equivalence proven against the legacy call sites, and exact scan chosen over HNSW once the keystone table turned out to be 97.2% duplicate vectors. `vector store backend = postgres` is live on both servers with a one-flag rollback still in place. Beforehand, the 90.46 GB LanceDB table with the broken version chain was rebuilt to 1.07 GB — ~89 GB reclaimed, all 176,877 rows preserved.
- **GCP deployment went from "validated" to operator-usable.** The CPU-VM app-restore arc completed and was verified end to end (an MTU 1500→1460 mismatch was the last blocker); the GPU model server was costed and split onto Cloud Run; the VM got an IAP browser tunnel, a live fleet arbiter, repo-sync tooling, its own pgvector bring-up, and a written bring-up runbook. A 38-hour `/embeddings/generate` outage was closed by separating one key file that had been serving two consumers with incompatible authorities — a defect that was invisible on the dev box precisely because dev's two values coincided by accident.
- **Fleet liveness, hardened by measurement rather than by guessing.** A 3,000-notification flood, a tmux fleet-killer, a Claude Code Stop-phase wedge (a fire-and-forget `notify()` that hung a turn for 54 minutes), arbiter double-delivery, DM double-stamping, ping storms, phantom blocks, and advisory loop-fire were each root-caused and fixed. The heartbeat-hold janitor's sweep reach went from 4 holds to 44 once it was pointed at the right root.
- **The unified task store grew verbs and guards.** `task_edit` and `task_reassign` shipped; a closed row can now carry a post-terminal addendum so a gate verdict written after a worker self-closes has somewhere to go; rows can be *parked* with a self-expiring chase so the owed-work count stops being fiction; and a bare unscoped board query now hard-fails with an educational error instead of dragging the whole fleet's history back.
- **The TypeScript multiplexer reached parity and shipped.** An adversarial gap matrix, a layout-parity oracle, and focus-bar parity work closed the distance to the legacy notifications UI — 724 TypeScript test cases across 114 files, still behind a hard 100% c8 gate on lines, branches, and functions.
- **Instrument rigor became a first-class discipline.** A hash-chained, append-only tier-run attestation ledger now answers "did this tier actually run?"; the first execution of 8,799 previously-ungated CoSA tests found 4 real failures behind two years of assumed health; a bridge-contact guard and an import-discipline detector caught guards that fired without saying what to fix. The running rule this milestone earned: **a null is not evidence until the instrument is proven, and a green tier cannot vouch for an ungated twin.**
- **Model and data plumbing.** Mistral Small 3.2 24B stood up on GPU1 (vLLM pinned at 0.16.0 — 0.26.0 is CUDA-13-only and this driver can't run it); `DEEPILY_DATA_DIR` moved 449 runtime files out of the repo and out of `git clean -xdf`'s reach; and an embedding-regeneration pipeline was built for all 578,364 logged texts with an adaptive GPU batch budget — gated, with zero live rows written.
- **The test suite roughly tripled** — 12,436 unit tests (from 3,549), 432 integration, 678 Playwright E2E, 724 TypeScript.

---

## What's New in v0.1.8 — the self-managing fleet, ready for the cloud

v0.1.8 turns the multi-session voice cockpit into a **self-coordinating engineering fleet** and prepares Lupin for GCP deployment:

- **Unified task-store + fleet liveness** — a single durable task store (`task_create` / `task_query` / `task_transition`) is now the one source of truth for owed work across every session, read by three consumers (the Stop-hook self-poke, the `:8001` fleet arbiter, and a human UI card). Sessions declare honored heartbeat *holds* so a parked worker is never falsely re-poked; the store-only cutover retired the legacy transcript mirror. Full design: `src/docs/fleet-liveness-and-task-store-architecture.md`.
- **Manager / worker fleet lifecycle** — managers spawn worker crews into isolated git worktrees, drive a review queue (fresh-critical, reproduce-don't-trust), merge reviewer-approved work held on the branch, and reap workers at steady state with continuity-preserving mementos and re-spin.
- **Notification-native AI↔AI messaging** — peer sessions now DM each other over `dm_send` with the body delivered inline (~18× cheaper than the retired commons-DM claim-check path), a major step in the cosa-voice token-reduction endgame.
- **JS→TS multiplexer migration** — the notifications client is being ported to a typed, esbuild-bundled multiplexer behind a hard 100% c8 gate: the audio cluster (`SequentialAudioManager`, `TtsAudioCache`, `JobCompletionCache`), `lupin-nav`, and `websocket-diagnostic` ported via a reusable standalone-entry pattern; reconnect-parity and an auth-handshake-timeout watchdog brought to legacy parity.
- **Bounded-CC agent migrations** — Podcast, Presentation, and Deep Research generators migrated from the firewalled Anthropic SDK to in-process bounded Claude Code (`sdk_query`), shifting metered per-token spend onto already-paid Max-plan fixed cost.
- **Alembic migration integrity** — a true baseline migration (empty-DB `upgrade head` works without a stamp), all-column NULL/NOT-NULL ORM-drift reconciliation, and hermetic create_all→upgrade-head idempotency regression tests guarding the migration merge gate.
- **GCP cloud-test deployment validated** — model server, OAuth-backed bounded CC, and a 17-table Cloud-SQL round-trip proven end-to-end via IAP tunnel; runbooks under `src/rnd/v0.1.8/2026.05.30-gcp-deployment/`.

---

## What's New in v0.1.7 — the multi-session voice cockpit

Lupin's voice loop grew from a single session into a **chorus of named AI collaborators working side by side**:

- **Per-session voice personas + chorus mode** — every Claude Code session is allocated a distinct named voice (Mr. Radio, Rio, Tiberius, María, Krishna...). In chorus mode the voice *is* the disambiguator: you hear which session is speaking. Personas survive `/clear`, `/compact`, and resume; an overflow pool covers more sessions than named slots; the new `request_persona` MCP tool lets a session reclaim its identity.
- **Inter-session commons** — concurrent sessions now talk to each other: a shared blackboard (`commons_post` / `commons_read` / `commons_who`), direct messages (`commons_send_to`), and cross-session questions (`commons_ask_async` / `commons_ask_sync`) — all surfaced in a live Recent Activity stream and broadcast panel in the browser.
- **Manager-spawned headless reviewers** — one session can spin up N headless Claude Code reviewer sessions on demand (`spawn_sessions` / `dismiss_sessions` / `list_spawned_sessions`), automating the cascaded plan-review workflow with idle-TTL reaping and manifest lineage.
- **Speakerphone mode (solo / chorus)** — the renamed, hardened successor to conversation mode, driven by a per-turn hook rider that adapts TTS brevity and interactive-tool routing to the live session state.
- **Notifications UI rebuilt in TypeScript** — the notifications surface was re-implemented as a typed, esbuild-bundled multiplexer behind a hard **100% c8 coverage gate** (lines + branches + functions), with a dedicated Jobs pane.
- **Multi-repo document viewer** — the in-browser doc viewer now serves whitelisted files from N registered repos via path-prefix routing, JWT-gated, with a universal secrets blocklist and inline source-code + image rendering.
- **CJ Flow async multi-lane** — long-running agentic jobs now run in a dedicated `ThreadPoolExecutor` pool with a ghost-job sweeper, a centralized `ApiResourceManager` for per-provider rate limiting, and a `GET /api/queue/pool-status` observability endpoint — fast-lane sync agents are never blocked.
- **Bounded Claude Code = zero per-token cost** — empirically confirmed (2026-05-12): bounded `ClaudeCodeJob` work runs on Max-plan OAuth at zero metered cost. BFE and TFE migrated, with a documented cost model for choosing bounded-CC vs. firewalled SDK.
- **Heartbeat-poker** — a generic liveness / keep-alive abstraction for long-running jobs, riding the commons for cross-session check-ins.
- **100% coverage mandate, Lupin-wide** — line + branch + function coverage is now a hard merge gate across the entire Lupin codebase.

Lupin is now a **multi-user platform preparing for GCP deployment**.
