# Phase 1 Design — Multiplexer Scaffolding

**Date**: 2026-05-03
**Status**: DRAFT — pending user approval before any Phase 1 code lands
**Phase**: 1 of 9 (per `01-execution-plan.md` §"Phase plan")
**Predecessors**: `00-synthesis-and-roadmap.md`, `01-execution-plan.md`, `01-phase0-decisions.md`
**Companion**: `90-execution-log.md` (Phase 1 section opens after approval)

---

## Context

Phase 0 captured all 11 strategic decisions (`01-phase0-decisions.md`). Phase 1 builds the minimum scaffolding needed to prove the toolchain end-to-end: a new URL serves a new HTML shell that loads a TypeScript-compiled bundle that prints "hello multiplexer" to the console, and a dev-tools card lets the user click into it.

Phase 1 ships **no application logic** — no auth, no transport, no stores, no rendering of real data. Just plumbing. The plumbing must be production-grade: strict TypeScript config, content-hashed build output, ESLint guard against the `window.X` global pattern that infected `notifications.js`. Getting these right in Phase 1 saves cleanup work in every later phase.

## Strategic posture (recap)

Per `00-synthesis-and-roadmap.md` §1: parallel greenfield rebuild. Current `notifications.html` enters maintenance freeze; multiplexer builds at a new URL with all review lessons baked in from line one. Cutover happens at Phase 9.

## Out of scope for Phase 1

- Authentication (Phase 2 — `AuthManager`)
- HTTP client (Phase 2 — `ApiClient`)
- WebSocket transport (Phase 3 — port of `ws-channel.js`)
- Domain stores (Phase 4)
- Rendering (Phase 5)
- Any feature parity with `notifications.html` (Phase 6)
- Any modification to `notifications.html` / `notifications.js` (frozen until cutover)

## Files created / edited

| Path | Change | Owner | Rationale |
|---|---|---|---|
| `src/fastapi_app/static/html/multiplexer.html` | NEW | Lupin | Shell entry. Loads `dist/multiplexer/boot.js` via `<script type="module">`. Minimal `<body>` with `<h1>Multiplexer</h1>` placeholder. No inline handlers (greenfield ban from line one). |
| `src/cosa/rest/routers/pages.py` | EDIT | **CoSA — user commits** | Add `"/app/multiplexer" : "html/multiplexer.html"` entry to `_ROUTE_TABLE` (mirror line 26) + add handler function (mirror lines 69-71). |
| `tsconfig.json` (project root) | NEW | Lupin | First TypeScript config. `strict: true`, `noUncheckedIndexedAccess: true`, `target: "es2022"`, `module: "esnext"`, `moduleResolution: "bundler"`, `rootDir: "src/fastapi_app/static/js/multiplexer"`, `outDir: "src/fastapi_app/static/dist/multiplexer"`, `include: ["src/fastapi_app/static/js/multiplexer/**/*.ts"]`. |
| `src/scripts/build-multiplexer.sh` | NEW | Lupin | esbuild driver. Bundles `src/fastapi_app/static/js/multiplexer/boot.ts` → `src/fastapi_app/static/dist/multiplexer/boot.js`. Default mode: production (minified + sourcemap). `--watch` flag enables dev mode. Content-hashed output filename (`boot.<hash>.js`) so HTML can reference the latest build without `?v=` rituals. |
| `src/fastapi_app/static/js/multiplexer/boot.ts` | NEW | Lupin | Minimal entry. Logs `console.log("hello multiplexer")` and sets `document.title` to `"Multiplexer"`. No globals exported. |
| `src/fastapi_app/static/js/multiplexer/.eslintrc.json` | NEW | Lupin | Bans `window.notificationsUI`, `window.multiplexerUI`, and any `window.X` global access. Forces all module-to-module communication through the EventBus that Phase 2 will introduce. **Canonical rule snippet** (Pass 1 finding #3 resolution): `{"rules": {"no-restricted-properties": [2, {"object": "window", "property": "notificationsUI", "message": "Use EventBus instead of window.notificationsUI globals (multiplexer no-globals rule, Phase 1)."}, {"object": "window", "property": "multiplexerUI", "message": "Use EventBus instead of window.multiplexerUI globals (multiplexer no-globals rule, Phase 1)."}], "no-restricted-globals": [2, {"name": "notificationsUI", "message": "Use EventBus instead of bare notificationsUI global."}, {"name": "multiplexerUI", "message": "Use EventBus instead of bare multiplexerUI global."}]}}`. Add to the rule set as new global names appear. |
| `src/fastapi_app/static/html/dev-tools.html` | EDIT | Lupin | Add "Multiplexer (next-gen)" card. **Section-resolution order** (Pass 1 finding #4 resolution): (1) grep for `Notifications & UI` in `dev-tools.html`; if found, add the card there. (2) If not found, fall back to `Audio & TTS` section (the existing convention used by the voice-persona-reference card). (3) If neither exists, create a new `Next-Gen Features` section at the end of the page. Increment any visible card-count counter on the page header. |

**CoSA edit policy**: Only one CoSA file is touched in Phase 1 — `pages.py`. Per `feedback_lupin_only_never_cosa` and `feedback_cosa_edit_vs_manage_git`: editing the file is fine; the user commits in CoSA context after Phase 1 lands. The Lupin-side `90-execution-log.md` references the CoSA commit hash for traceability.

## Acceptance criteria (definition of done for Phase 1)

1. `curl -I http://localhost:7999/app/multiplexer` returns `200 OK` with `Content-Type: text/html`.
2. `bash src/scripts/build-multiplexer.sh` exits 0 and produces `src/fastapi_app/static/dist/multiplexer/boot.<hash>.js` with non-zero size.
3. `bash src/scripts/build-multiplexer.sh --watch` starts and watches `src/fastapi_app/static/js/multiplexer/**/*.ts` (exit on Ctrl-C).
4. **EXECUTOR: AI** (Playwright headless): Navigate to `http://localhost:7999/app/multiplexer`. AI asserts (a) `document.title === "Multiplexer"`; (b) the placeholder body element exists; (c) the browser console contains the line `"hello multiplexer"`. Test produces pass/fail output programmatically — no human screen-watching.
5. **EXECUTOR: AI**: `npx tsc --noEmit -p tsconfig.json` against the multiplexer module tree exits 0 with zero errors.
6. **EXECUTOR: AI**: `npx eslint src/fastapi_app/static/js/multiplexer/` exits 0 with zero errors (the `.eslintrc.json` rules don't trigger on the minimal `boot.ts`).
7. **EXECUTOR: AI** (Playwright headless): Navigate to `/app/admin/dev-tools`. AI asserts (a) the "Multiplexer (next-gen)" card element exists; (b) clicking the card navigates the browser to `/app/multiplexer` (URL assertion). Test produces pass/fail output programmatically.

## Verification (Claude-executed per `01-working-contract.md`)

The user is never the tester. Claude executes every verification step and reports results in tabular form.

### :7999 (AI-discretionary, immediately after each file edit)

| Step | Command / Action | Pass criterion |
|---|---|---|
| Bootstrap (idempotent) | `[ -d node_modules ] \|\| npm install` (run once per fresh checkout; no-op if already installed) | `node_modules/` exists; `npm install` exits 0 |
| Build script smoke | `bash src/scripts/build-multiplexer.sh` | Exit 0; output file exists; size > 0 |
| TypeScript check | `npx tsc --noEmit -p tsconfig.json` (run from project root) | Zero errors |
| ESLint check | `npx eslint src/fastapi_app/static/js/multiplexer/` | Zero errors |
| Route smoke | `curl -I http://localhost:7999/app/multiplexer` | 200; `text/html` |
| Page-load smoke | Playwright headless: navigate to `/app/multiplexer`, assert `document.title === "Multiplexer"`, assert console has `"hello multiplexer"` | All assertions pass |
| Dev-tools card smoke | Playwright headless: navigate to `/app/admin/dev-tools`, click "Multiplexer (next-gen)" card, assert URL becomes `/app/multiplexer` | Assertion passes |
| Watch mode smoke | `bash src/scripts/build-multiplexer.sh --watch` for 3 seconds, then send SIGINT | Process starts, watches expected paths, exits cleanly on signal |

All `LUPIN_API_URL`-aware tests use the env var per `feedback_tests_parameterize_base_url`; default `http://localhost:7999`.

### :8000 (scheduled — N/A for Phase 1)

Phase 1 introduces no destructive state, no LLM spend, no monopoly requirement. All verification fits the :7999 envelope. :8000 work begins at Phase 6 (E2E parity) per `01-execution-plan.md` §4.5.

## Rollback procedure

If Phase 1 needs to be reverted:

1. Remove new files: `multiplexer.html`, `tsconfig.json`, `build-multiplexer.sh`, `js/multiplexer/` (entire directory), `static/dist/multiplexer/` (entire directory).
2. Revert `pages.py` (CoSA — user does this in CoSA context): remove the `multiplexer` entry from `_ROUTE_TABLE` and the corresponding handler.
3. Revert `dev-tools.html`: remove the "Multiplexer (next-gen)" card.
4. **EXECUTOR: AI**: `curl -I http://localhost:7999/app/notifications` returns 200 OK (regression check on the legacy surface — confirms rollback didn't break the existing notifications UI).

No DB migrations to roll back; no shared state mutations; no config keys added.

## Open questions — RESOLVED 2026-05-04 (REUSE pre-pass + DC3)

Target was zero. Both Open Questions resolved during REUSE pre-pass (DC3 in `90-execution-log.md` Spine Bundle Review):

1. **`npx` vs vendored binaries** — **RESOLVED: option (a)** — Phase 1 introduces `package.json` + `package-lock.json` at the project root with `esbuild`, `typescript`, and `eslint` as `devDependencies`. One-time `npm install` per fresh checkout. No vitest, no jest, no other test-side deps in Phase 1 (Phase 2 commits to `tsx --test` + `c8`, both pulled via the same `package.json`).
2. **ESLint vendoring** — **RESOLVED: option (a)** — ESLint ships in the Phase 1 `package.json` so the global-ban rule lands from line one (the whole point of having ESLint from Phase 1 was to enforce no-`window.X`-globals).

**Phase 1 `package.json` `devDependencies`** (canonical):
- `esbuild` — bundling
- `typescript` — `tsc --noEmit` for type-checking (esbuild transpiles but doesn't type-check)
- `tsx` — TypeScript execution (used by Phase 2's `tsx --test` test runner via `node:test`)
- `eslint` — lint (Phase 1 ban rule)
- `c8` — coverage tool (used by Phase 2 to verify 100% line coverage acceptance criterion; AC was originally `≥ 90%` and upgraded to `100%` with two narrowly-scoped `c8 ignore` exceptions in session ec746144 — see `03-phase2-foundation-design.md` AC#4 + `90-execution-log.md` Phase 2 Notes "Coverage AC upgrade")
- `@typescript-eslint/parser` + `@typescript-eslint/eslint-plugin` — required for ESLint to parse `.ts` files

This makes Phase 2's coverage acceptance criterion immediately verifiable. If Phase 7 hardening review wants Vitest, add then.

## Prior art referenced (from REUSE pre-pass 2026-05-04)

Per PIP §4: extend-existing + genuinely-new-with-prior-art findings, captured for traceability.

| Phase 1 component | Prior art (file:line) | Verdict |
|---|---|---|
| `/app/multiplexer` route registration in `pages.py` | `src/cosa/rest/routers/pages.py:24-40` (route table + handler factory pattern) | extend-existing — add new `_ROUTE_TABLE` entry + handler following the existing pattern |
| dev-tools.html "Multiplexer" card | `src/fastapi_app/static/html/dev-tools.html` (existing card structure under "Audio & TTS" / appropriate group) | extend-existing — add new card following the existing pattern, increment count |
| `tsconfig.json` (project root) | none | genuinely-new — first TS config in project |
| esbuild build script (`src/scripts/build-multiplexer.sh`) | `src/scripts/cloud-run-build.sh` exists but is cloud-run-specific, not JS bundling | genuinely-new — first JS bundling infrastructure |
| ESLint configuration | none | genuinely-new — first ESLint config in project |

## Self-audit (against feedback memory, draft time)

| Memory | Compliance |
|---|---|
| `feedback_phase0_serialization_prominence` | ✅ Phase 0 already shipped (`01-phase0-decisions.md`); this doc is Phase 1 |
| `feedback_documentation_first_protocol` | ✅ This design doc lands BEFORE any Phase 1 code |
| `feedback_audit_plans_at_execute_time` | ✅ Open Questions section flags re-audit on `npx` vs vendoring choice |
| `feedback_lupin_only_never_cosa` | ✅ `pages.py` edit explicitly flagged as CoSA-context user commit |
| `feedback_never_auto_commit_push` | ✅ No commit-on-completion language; user owns commit cadence |
| `feedback_comprehensive_automated_testing` | ✅ Verification section covers build smoke, TS check, ESLint check, route smoke, page-load smoke (Playwright), dev-tools card smoke (Playwright), watch-mode smoke |
| `feedback_tests_parameterize_base_url` | ✅ All :7999 verification reads `LUPIN_API_URL` |
| `feedback_test_server_monopolize_mode` | ✅ Phase 1 needs no :8000 work; Phase 6+ scheduling reserved for parity tests |
| `feedback_skip_rnd_doc_for_trivial_fixes` | n/a — Phase 1 scaffolding is non-trivial (introduces TS toolchain) |
| `feedback_no_green_in_persona_pool` | n/a — no persona-color decisions |
| `feedback_audit_plans_at_execute_time` (re-audit obligation) | ✅ Will re-audit this section against memory at execute time before any code edit |

## Approval coupling — spine bundle (Phases 1-3)

Per Q10 amendment in `01-phase0-decisions.md` (2026-05-04): **this design doc does NOT land alone**. Phases 1, 2, and 3 design docs (`02-phase1-scaffolding-design.md` + `03-phase2-foundation-design.md` + `04-phase3-transport-design.md`) are bundled as the **spine** — a single plan-review pass + single user approval gate covers all three. Implementation cadence within the bundle stays per-phase: Phase 1 implements + verifies + commits before Phase 2 code starts; same for Phase 2 → Phase 3.

Why bundled: the toolchain decisions in this doc (TS strictness, ESLint rule, esbuild output shape) constrain Phase 2 service contracts, which constrain Phase 3 transport wrappers. Reviewing them as a unit catches cross-phase contract gaps that serial single-phase reviews would miss.

## Plan-review pointer — canonical PIP machinery

Per Q11 amendment in `01-phase0-decisions.md` (2026-05-04): plan-review uses the canonical workflow at `planning-is-prompting/workflow/plan-review.md` (REUSE pre-pass → Pass 1 Fitness → Pass 2 Adversarial; parametrized via `{{slots}}`). No milestone-specific clone of the review prompts is needed.

For the spine bundle (covers this doc + 03-phase2 + 04-phase3 in a single pass), the slots resolve as:

| Slot | Value |
|---|---|
| `{{MILESTONE_NAME}}` | `Multiplexer Notifications UI Rebuild — Spine Bundle (Phases 1-3)` |
| `{{BRANCH_NAME}}` | active branch (currently `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe`) |
| `{{ANCHOR_FILES}}` | `~/.claude/CLAUDE.md` (Layer 1 — TEST OWNERSHIP MANDATE + DOCUMENTATION-FIRST PROTOCOL); `src/rnd/v0.1.7/2026.05.03-testing-and-fitness-prompts/01-working-contract.md` (Layer 2 — multiplexer-specific) |
| `{{DESIGN_ANCHOR_FILE}}` | `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/01-phase0-decisions.md` |
| `{{DECISION_ANCHOR_FORMAT}}` | `Q1-Q11 frozen 2026-05-03 (with Q10/Q11 amendments 2026-05-04)` |
| `{{PLAN_DOC_PATHS}}` | `02-phase1-scaffolding-design.md`, `03-phase2-foundation-design.md`, `04-phase3-transport-design.md` |
| `{{CODEBASE_ROOTS}}` | `src/fastapi_app/static/`, `src/cosa/rest/routers/` |
| `{{GREP_TARGETS}}` | `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/` |
| `{{TBD_QUESTIONS}}` | enumerated from each design doc's "Open Questions" section at invocation time (this doc currently flags 2: npx vs vendoring; ESLint vendoring) |

The single bundled review pass replaces what would otherwise be three separate per-phase reviews (one each for Phases 1, 2, 3). After the bundle passes review and the user approves, the spine implementation proceeds per-phase (this doc → Phase 1 implementation → 03-phase2 → Phase 2 implementation → 04-phase3 → Phase 3 implementation).

## Approval gate

Phase 1 implementation begins ONLY after explicit user approval of this design doc. Per Q10 (per-phase gate). Per `feedback_never_auto_commit_push`.
