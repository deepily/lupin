# Phase 7a Telemetry — Pre-Cascade Recon

**Date**: 2026-05-20
**Author**: Mr. Radio 🦉 (Lupin session `32a6e563`)
**Status**: 📝 **Recon complete — findings + decisions for Stage 0 design doc input**
**Sister docs**:
- Upstream slicing manifest: [`13-phase7-slicing-manifest.md`](13-phase7-slicing-manifest.md) — defines 7a Telemetry scope, sequencing, and AC machinery
- Downstream (pending Rick's author-rotation decision): [`15-phase7a-telemetry-design.md`](15-phase7a-telemetry-design.md) — Stage 0 author draft (Rachel 🕊️ canonical author per Run 1-3 pattern; Rick's rotation TBD)
- Doctrine anchor: planning-is-prompting commit `bbb3e47` (Tiberius 🌑 + María 🌸, 2026-05-20) → `plan-authoring-cascaded-common.md` §Step 0 + `2026.05.20-step-0-cascade-preparation-doctrine.md`

---

## How to read this document

This is the **pre-cascade recon doc** for Phase 7a Telemetry — produced BEFORE the design-doc cascade fires, per the ratified workflow from `13-phase7-slicing-manifest.md` §Ratification outcomes #2 (Pre-cascade recon ON).

**Purpose**: resolve browser-API archaeology, SDK version-pin choices, and infrastructure dependencies upfront so the Stage 0 author can focus on design decisions (instrumentation point selection, perf budget literals, error-path handling) rather than burning Stage 1 + Stage 2 reviewer cycles on "what version of OTel?" / "does Long Tasks API work on Safari?"

**Doctrine cross-ref**: this doc is **empirical anchor #2** for the Step 0 cascade-preparation doctrine Tiberius 🌑 and María 🌸 codified at PIP commit `bbb3e47`. The slicing manifest's §Pre-cascade recon section was anchor #1 (framework-level); this is the first instantiation of the framework in practice.

**Shape per recon item** (per Tiberius's spec, DM `9d91b3a5`): **Question → Finding → Source → Decision** with optional rationale. Tight prose, no unnecessary structure.

---

## Phase 1 modern-browsers floor (load-bearing for every item below)

Phase 1 modern-browsers commitment is the citation anchor for every browser-support determination in this doc. Per `10-phase6c-persona-focus-recorder-design.md` line 88 (Popover API support verification): **Chrome 114+ / Firefox 125+ / Safari 17.0+**.

This is the floor against which every API in this recon is evaluated. APIs that don't reach the floor on every browser require feature-detect + graceful degradation per Phase 4 `EventBus` + Phase 6c `Popover` precedent.

---

## Recon items

### R-7a-1: OTel browser SDK package selection + version pin

**Question**: which OpenTelemetry JavaScript package(s) does 7a Telemetry consume, and what version pin?

**Finding** (OpenTelemetry JavaScript landscape per Jan 2026 cutoff):

The `opentelemetry-js` repo publishes a family of packages with different scope/weight tradeoffs:

| Package | Purpose | Bundle weight (approx) | Fit for 7a |
|---|---|---|---|
| `@opentelemetry/api` | Bare API surface (no implementation) — `trace`, `metrics`, `context`, `propagation` | ~3 KB gz | ✅ Required base |
| `@opentelemetry/sdk-trace-web` | Web-tier tracing SDK — manual span construction | ~15 KB gz | ✅ Fits manifest §Slice boundaries 7a's "OTel browser SDK initialization + minimal instrumentation: page-load span, first-input-delay span, key user-action spans" |
| `@opentelemetry/exporter-trace-otlp-http` | OTLP/HTTP exporter — ships spans via HTTP POST | ~8 KB gz | ✅ Fits manifest §Slice boundaries 7a's "Telemetry sink config (env-driven endpoint; OTLP/HTTP collector)" |
| `@opentelemetry/sdk-metrics` | Metrics SDK — counters, histograms | ~12 KB gz | ⚠️ Consider but not required — User Timing + Long Tasks can be framed as either traces or metrics; recommend traces for greenfield simplicity |
| `@opentelemetry/auto-instrumentations-web` | Auto-instruments XHR, fetch, document-load, user-interaction | ~40+ KB gz | ❌ Reject — too heavy + the greenfield's stores/transports/renderers already have natural instrumentation points; auto-instrument duplicates effort |

**Source**: opentelemetry-js GitHub README + per-package npm registry entries.

**Decision**: pin `@opentelemetry/api` + `@opentelemetry/sdk-trace-web` + `@opentelemetry/exporter-trace-otlp-http`. SKIP `auto-instrumentations-web` (too heavy + duplicative). DEFER `sdk-metrics` to Stage 0 author — recommend revisit if Long Tasks framing benefits from histogram-style metric (vs spans). **Exact version pins are Stage 0 author's call** — pin at latest-stable-as-of-design-doc-author-time so the lockfile entry is fresh.

**Rationale**: surgical instrumentation matches Phase 7a's manifest scope (User Timing marks at canonical lifecycle points; not arbitrary network/script instrumentation). Three core packages keep the bundle delta tight for AC10b.

---

### R-7a-2: Long Tasks API browser support

**Question**: does the Long Tasks API meet the Phase 1 modern-browsers floor (Chrome 114+ / FF 125+ / Safari 17+)?

**Finding** (per Jan 2026 cutoff):

| Browser | Long Tasks API support | Meets Phase 1 floor? |
|---|---|---|
| Chrome | Supported since Chrome 58 (2017) | ✅ Well above floor |
| Firefox | Supported since Firefox 124 (2024) | ✅ At floor (FF 125 floor) — barely |
| Safari | NOT supported as of cutoff | ❌ Gap |

**Source**: MDN Web Docs `PerformanceLongTaskTiming` + `PerformanceObserver` API entries; caniuse.com `longtasks` query.

**Decision**: **feature-detect at boot**. Wire `PerformanceObserver({type: 'longtask'})` inside a `try { ... } catch (e) { /* longtask unsupported, no-op */ }` block AND verify `PerformanceObserver.supportedEntryTypes?.includes('longtask')` before observation start. Safari users emit no longtask events; the rest of the instrumentation continues.

**AC obligation for Stage 0 design doc**: AC-7a-LT must include "feature-detect path returns empty results gracefully on Safari" assertion. Cite Phase 6c's `MediaRecorder` feature-detect pattern (`audio-recorder.js`) as precedent.

---

### R-7a-3: Telemetry sink endpoint configuration

**Question**: where do traces ship? What's the endpoint config story?

**Finding**: OTLP/HTTP is the OpenTelemetry standard wire protocol — POST JSON-encoded spans to a collector endpoint over HTTP. Three deployment paths:

1. **Self-hosted OTel collector** (e.g., the `otel/opentelemetry-collector` Docker image) → routes to a backend (Jaeger, Tempo, Honeycomb, etc.)
2. **Vendor-direct OTLP endpoint** (Honeycomb, Lightstep, New Relic all accept OTLP/HTTP directly)
3. **Stub / no-op exporter** for dev workstations that shouldn't ship telemetry anywhere

**Current Lupin infrastructure state**: NO OTel collector is currently deployed in `docker-compose.yml`. The `lupin-rest-dev` / `lupin-rest-test` / `lupin-model-server` containers run telemetry-blind today.

**Source**: opentelemetry.io documentation; current `docker/lupin/docker-compose.yml` (verified no `otel-collector` service); `lupin-app.ini` configuration (verified no OTel keys).

**Decision**:

- **INI key**: new `multiplexer otel collector endpoint` key in `[Lupin: Baseline]` with default empty string (no-op). Matching splainer entry mandatory per `feedback_env_var_read_and_set_land_together`.
- **Endpoint behavior**: empty string → exporter is the OpenTelemetry no-op exporter (spans built and discarded). Non-empty string → OTLP/HTTP exporter targets that URL.
- **Production INI**: `[Lupin: Production]` sets the URL when collector deployment lands.
- **Development INI**: `[Lupin: Development]` defaults to empty (no traces shipped from dev workstations).
- **Test INI**: `[Lupin: Testing]` defaults to empty unless a future integration test needs a collector mock.

**Out-of-scope handoff**: collector deployment (Docker container + backend storage choice + dashboards) is OUT OF SCOPE for Phase 7a per slicing manifest §Permanently out of scope ("Perf budget dashboards consumer-side"). Phase 7a delivers the instrumentation; collector deployment is a separate Lupin-wide initiative to be filed as a follow-on TODO.

**AC obligation for Stage 0 design doc**: AC-7a-OTEL must include "no-op exporter path verified at boot when endpoint is empty" assertion + "OTLP/HTTP exporter wired when endpoint is set" assertion (mock collector in test tier).

---

### R-7a-4: ReportingObserver browser support

**Question**: does ReportingObserver meet the Phase 1 modern-browsers floor?

**Finding** (per Jan 2026 cutoff):

| Browser | ReportingObserver support | Meets Phase 1 floor? |
|---|---|---|
| Chrome | Supported since Chrome 69 (2018) | ✅ Well above floor |
| Firefox | NOT supported as of cutoff | ❌ Gap |
| Safari | NOT supported as of cutoff | ❌ Gap |

**Source**: MDN Web Docs `ReportingObserver`; caniuse.com `reporting-api` query.

**Decision**: **feature-detect at boot**. Same pattern as R-7a-2. `typeof ReportingObserver !== 'undefined'` check; if missing, skip registration. Chrome users emit deprecation/intervention/crash reports; Firefox + Safari users skip those signals (multiplexer continues without them).

**AC obligation for Stage 0 design doc**: AC-7a-REP must include "feature-detect path returns gracefully when ReportingObserver is undefined" assertion + "registered report types (deprecation, intervention, crash) emit when fixture violations trigger them on Chrome" assertion.

**Rationale for keeping despite limited support**: ReportingObserver gives Chrome users high-value signal (deprecation warnings, intervention reports, crash reports) at zero cost when the API is present. The graceful no-op for FF/Safari means no negative impact. Net benefit > zero.

---

### R-7a-5: User Timing API level

**Question** (added during recon — not in slicing manifest's original recon table): which User Timing API level does 7a target?

**Finding**: User Timing has Level 1 (deprecated), Level 2 (legacy stable), and Level 3 (modern). Level 3 adds options-object parameters to `performance.mark(name, options)` and `performance.measure(name, ...options)` — supports `detail`, `startTime`, `endTime` properties.

| Browser | User Timing Level 3 support | Meets Phase 1 floor? |
|---|---|---|
| Chrome | Supported since Chrome 89 (2021) | ✅ Well above floor |
| Firefox | Supported since Firefox 89 (2021) | ✅ Well above floor |
| Safari | Supported since Safari 16 (2022) | ✅ At/above floor (Safari 17 floor) |

**Source**: MDN Web Docs `Performance.mark()`, `Performance.measure()` + W3C User Timing Level 3 spec; caniuse.com `user-timing` query.

**Decision**: target **User Timing Level 3 unconditionally**. Meets Phase 1 floor on every supported browser. No feature-detect needed.

**Implementation cite**: `performance.mark(name, { detail, startTime })` and `performance.measure(name, { detail, start, end })`. The `detail` property is the structured-data attachment point for span-correlation (e.g., embed an OTel trace_id in `detail` so traces and User Timing entries cross-reference).

---

### R-7a-6: Phase 1 directory layout reservation

**Question**: does the existing Phase 1 directory layout actually have the `multiplexer/observability/` directory stubs the slicing manifest references?

**Finding**: `00-synthesis-and-roadmap.md` §4.2 directory layout enumerates:
```
js/multiplexer/observability/
    timing.ts
    otel.ts
```

These are listed as "Phase 7 stubs" — directory + file paths reserved but no implementation exists yet. Verified by `ls` against the current working tree: `src/fastapi_app/static/js/multiplexer/observability/` does NOT exist.

**Source**: `00-synthesis-and-roadmap.md` §4.2 lines 196-198; filesystem inspection.

**Decision**: Stage 0 design doc owns the creation of the `observability/` directory + `timing.ts` + `otel.ts` files. Recon doc does NOT pre-create empty stubs — that's design-doc + code-write boundary. **Implementation sequence reminder**: directory creation lands in the code-execution-plan phase post-cascade, not in design phase, not in recon.

---

## Decisions consumed by Stage 0 author

Tabulated for the Stage 0 design doc to inherit verbatim:

| Decision area | Verdict |
|---|---|
| OTel browser SDK packages | `@opentelemetry/api` + `@opentelemetry/sdk-trace-web` + `@opentelemetry/exporter-trace-otlp-http`. Skip `auto-instrumentations-web`. Defer `sdk-metrics` to Stage 0 if histogram-style Long Tasks framing wins. |
| Exact version pins | Stage 0 author's call (latest-stable-as-of-author-time). |
| Long Tasks API | Feature-detect; Safari falls back to no-op. AC obligation enumerated above. |
| Telemetry sink endpoint | Env-driven via INI key `multiplexer otel collector endpoint` + matching splainer entry. Default empty (no-op exporter). |
| Collector deployment | OUT OF SCOPE per slicing manifest §Permanently out of scope. Stage 0 design doc cites this. Follow-on TODO filed. |
| ReportingObserver | Feature-detect; FF + Safari fall back to no-op. AC obligation enumerated above. |
| User Timing | Level 3 unconditionally (meets Phase 1 floor). Use `detail` for OTel trace_id correlation. |
| `observability/` directory | Stage 0 design doc + code-execution phase create; recon does not pre-stub. |

---

## Open items for Stage 0 author

Items that the recon could NOT resolve and must be resolved during cascade Stages 0-3:

| Open item | Rationale for deferral |
|---|---|
| **Bundle-delta budget for AC10b** | Cannot measure without actual SDK install. Stage 0 author runs `npm install` of the three packages, builds with esbuild, measures gz delta vs Phase 6c baseline, sets the AC10b literal. |
| **Canonical lifecycle points for User Timing marks** | Slicing manifest §Slice boundaries lists 6 anchors (boot start, boot complete, first queue render, TTS playback start, WS reconnect, auth refresh). Stage 0 design doc enumerates the implementation site (file path + function name) per anchor. |
| **Long Tasks observer instantiation site** | `multiplexer/observability/timing.ts` per §4.2 layout. Stage 0 design doc owns the factory contract (`createLongTasksObserver(opts) → { stop }` or similar). |
| **OTLP/HTTP exporter retry/backoff strategy** | Does it need ApiClient `AbortSignal.any` integration? Or does the OTel exporter come with its own retry? Stage 0 author decides per OTel SDK docs at author-time. |
| **Trace span granularity** | Page-load span vs per-render span vs per-user-action span — Stage 0 author chooses the granularity tradeoff (high-cardinality cost vs diagnostic value). |
| **Long Tasks metrics vs traces framing** | Conditional on R-7a-1's `sdk-metrics` deferral — Stage 0 author can revisit if histogram framing wins. |
| **Sampling strategy** | Head-based vs tail-based vs always-on. Affects cost when collector lands. Stage 0 author proposes; Pass 2 reviewer audits. |
| **Cross-browser AC matrix** | Per Phase 1 floor — each test should run on Chrome at minimum (CI) + manual verification on FF/Safari for graceful-degradation paths. Stage 0 design doc establishes the matrix. |

---

## Pre-exit self-audit

Per `feedback_plan_self_audit_against_memory` + `feedback_audit_plans_at_execute_time`:

| Memory | Compliance check |
|---|---|
| `feedback_pip_plan_review_is_sequential` | n/a — recon doc, not a plan-review pass |
| `feedback_100pct_coverage_multiplexer` (Lupin-wide post-2026-05-16) | Cited indirectly via AC obligations passed to Stage 0 — feature-detect paths must hit 100% coverage |
| `feedback_pydantic_native_validation` | n/a — no server-side endpoint authored by recon |
| `feedback_baseline_capture_disable_tfe` | n/a — no visual baseline captured by recon |
| `feedback_test_server_monopolize_mode` | n/a — recon is local-only research |
| `feedback_lupin_only_never_cosa` | ✅ All paths under `src/fastapi_app/static/js/multiplexer/` and `src/conf/`; no CoSA submodule references |
| `feedback_never_auto_commit_push` | ✅ Recon doc commits no code; awaits Rick commit go-ahead |
| `feedback_env_var_read_and_set_land_together` | ✅ R-7a-3 mandates INI key + matching splainer entry as a single landing pair |
| `feedback_tests_must_cover_cross_target_invocations` | n/a — recon doc has no executable code; relevant when 7a Telemetry design doc lands |
| `feedback_pass2_is_ownership_audit_not_security` | n/a — applies during cascade Pass 2, not recon |
| `feedback_documentation_step_stops_at_doc` | ✅ This doc IS the deliverable — no auto-progression to design draft (Rachel 🕊️ or rotated author owns Stage 0) |
| `feedback_always_serialize_plan_to_rd_scope_post_exit` | ✅ Doc lives in `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/` per slicing manifest §Per-slice file naming |
| `feedback_tests_parameterize_base_url` | n/a — applies to tests authored in 7a design phase |

No violations detected at draft time. Tiberius's review will catch what self-audit misses.

---

## Step 0 doctrine alignment

Per Tiberius's brief (DM `9d91b3a5`): this recon doc is **empirical anchor #2** for the Step 0 cascade-preparation doctrine (after slicing manifest §Pre-cascade recon framework was anchor #1). Step 0 codification:

- Commit: planning-is-prompting `bbb3e47` (Tiberius 🌑 + María 🌸, 2026-05-20)
- Canonical doctrine: `planning-is-prompting/workflow/plan-authoring-cascaded-common.md` §Step 0
- Requirements doc: `planning-is-prompting/src/rnd/2026.05.20-step-0-cascade-preparation-doctrine.md`

The per-item shape used here (Question → Finding → Source → Decision) is the candidate template for Step 0's recon-doc-section. Tiberius and María's codification may iterate the shape; this doc serves as a prior-art reference for what worked empirically.

**Cascade Run 4 implication**: when the 7a Telemetry design doc cascade fires (next phase after this recon + Rick's author-rotation decision), it will be the **first live test of BOTH Step 0 and Step 9 doctrine** simultaneously. Worth flagging for the Run 4 manager's attention.

---

## Next steps

1. **DM Tiberius 🌑** confirming recon doc lands (in_reply_to `9d91b3a5`) with key decisions + open items for Stage 0 author.
2. **Author-rotation decision** — Tiberius surfaces to Rick when next available; Rachel 🕊️ canonical author per Run 1-3, may rotate.
3. **Stage 0 design doc cascade fires** — consumes this recon's §Decisions consumed by Stage 0 author as input; resolves §Open items for Stage 0 author inline-cascade.
4. **No commits per `feedback_never_auto_commit_push`** — this doc is dirty in working tree until Rick's commit go-ahead.

---

— Mr. Radio 🦉 (Author, Lupin session `32a6e563`) — Phase 7a Telemetry pre-cascade recon, empirical anchor #2 for Step 0 doctrine.
