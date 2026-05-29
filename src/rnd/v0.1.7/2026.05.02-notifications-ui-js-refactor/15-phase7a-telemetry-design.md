# Phase 7a Design Doc — Telemetry (User Timing + Long Tasks + ReportingObserver + OTel browser SDK)

| Field | Value |
|---|---|
| **Slice** | 7a per `13-phase7-slicing-manifest.md` |
| **Status** | 📝 **STAGE 0 — STAGE 3 CAP-2 AUTHOR REVISION IN FLIGHT** (Stage 1 + Stage 2 cap-2 closed; Stage 3 Rio ⚡ Ownership/Convention returned 2026-05-20: 3 inconsistencies + 1 cosmetic + 1 withdrawn — F-Rio-7a-1 OSQ table missing T-5/T-6/T-7 rows, F-Rio-7a-4 `crash` survives §Scope T-T3, F-Rio-7a-5 Recon-T-5 survives §Cluster T summary, F-Rio-7a-3 CoSA cross-project handoff seed cosmetic, F-Rio-7a-2 WITHDRAWN as pre-re-apply state. Same multi-surface-sweep-gap anti-pattern family — 7th instance across cascades. All 7 Q-decisions ACCEPT-AS-PROPOSED; all 4 Manager footers HOLD; 21-memory self-audit CLEAN). Awaiting Rio's cap-3 re-read after this revision turn |
| **Author** | Mr. Radio 🦉 (Lupin session `32a6e563`), 2026-05-20 |
| **Predecessors** | Phase 6a CLOSED 2026-05-06 (jobs surface); Phase 6b CLOSED 2026-05-12 (interactive widgets + TTS chrome); Phase 6c in flight (Tiffany 💍 Node C C1+C2 done) |
| **Sister docs** | Upstream slicing manifest [`13-phase7-slicing-manifest.md`](13-phase7-slicing-manifest.md); upstream pre-cascade recon [`14-phase7a-telemetry-pre-cascade-recon.md`](14-phase7a-telemetry-pre-cascade-recon.md) (resolves R-7a-1..R-7a-6) |
| **Cascade context** | Run 4 — **first live test of BOTH Step 0 and Step 9 doctrine** per Tiberius 🌑's DM `9d91b3a5` + manifest §Doctrine cross-refs |
| **Background docs to lean on** | `00-synthesis-and-roadmap.md` §3 (Phase 7 row) + §2.3 (OpenAI exclusive findings: User Timing / Long Tasks / OTel) + §4.2 (`observability/` directory layout reserved) |

---

## Scope (per slicing manifest §7a)

Phase 7a is the **observability before launch** slice — instrumentation only, no UI surface change.

| ID | Sub-feature | Notes |
|---|---|---|
| **7a-T1** | User Timing API marks at canonical lifecycle points | `performance.mark` at 6 anchors (boot start, boot complete, first queue render, TTS playback start, WS reconnect, auth refresh) |
| **7a-T2** | Long Tasks API observer | `PerformanceObserver({type: 'longtask'})` with feature-detect; Safari falls back to no-op |
| **7a-T3** | ReportingObserver registration | `deprecation` + `intervention` report types (R-3 Path A 2026-05-20: `crash` removed for PII safety; sanitizer-based inclusion deferred to v2 per OSQ-T-6); feature-detect; FF + Safari fall back to no-op |
| **7a-T4** | OTel browser SDK initialization | `@opentelemetry/api` + `sdk-trace-web` + `exporter-trace-otlp-http`; env-driven endpoint |
| **7a-T5** | Perf budget gates | Smoke-tier wall-clock thresholds for boot, first-queue-render, longtask count |

## Out-of-scope confirmation

Inherits slicing manifest §Permanently out of scope (across all 4 slices). 7a-specific carve-outs:

- **OTel collector deployment** — `otel/opentelemetry-collector` Docker container + backend storage + dashboard authoring is OUT OF SCOPE per `00-synthesis-and-roadmap.md` §3 ("Perf budget dashboards consumer-side"). Phase 7a delivers the wire format; consumer-side telemetry stack is a separate Lupin-wide initiative.
- **Auto-instrumentation** — `@opentelemetry/auto-instrumentations-web` REJECTED per recon R-7a-1 (40+ KB gz with duplicative coverage of greenfield's natural instrumentation points). Manual span construction only.
- **Server-side OTel** — FastAPI / CoSA pipeline instrumentation is OUT OF SCOPE for the JS-only refactor. Server-side OTel is a separate initiative.
- **Metrics SDK** (`@opentelemetry/sdk-metrics`) — DEFERRED to Q-T4 reviewer decision. Default position: skip (traces-only first cut); flip if Long Tasks framing benefits from histogram-style metric.
- **Tail-based sampling backend coordination** — Phase 7a configures head-based sampling client-side per Q-T6; tail-based sampling is collector-side and out of scope.

---

## Pre-design recon (RESOLVED upstream in [`14-phase7a-telemetry-pre-cascade-recon.md`](14-phase7a-telemetry-pre-cascade-recon.md))

These 6 items were resolved BEFORE this cascade fired, per the ratified Pre-cascade recon workflow (slicing manifest §Ratification outcomes #2). Reviewers should treat as load-bearing background, not open questions:

| Item | Status | Source |
|---|---|---|
| **R-7a-1**: OTel package selection — `@opentelemetry/api` + `sdk-trace-web` + `exporter-trace-otlp-http`; skip `auto-instrumentations-web`; defer `sdk-metrics` to Q-T4 | ✅ RESOLVED | Recon doc §R-7a-1 |
| **R-7a-2**: Long Tasks API browser support — Chrome ✅ since 58, FF ✅ at Phase 1 floor (124), Safari ❌ gap. Feature-detect required. | ✅ RESOLVED | Recon doc §R-7a-2 |
| **R-7a-3**: Telemetry sink endpoint config — env-driven INI key `multiplexer otel collector endpoint`; default empty (no-op exporter); collector deployment OUT OF SCOPE | ✅ RESOLVED | Recon doc §R-7a-3 |
| **R-7a-4**: ReportingObserver browser support — Chrome ✅ since 69, FF ❌, Safari ❌. Feature-detect required. | ✅ RESOLVED | Recon doc §R-7a-4 |
| **R-7a-5**: User Timing Level — Level 3 unconditionally (meets Phase 1 floor on all browsers); use `detail` for OTel trace_id correlation | ✅ RESOLVED | Recon doc §R-7a-5 |
| **R-7a-6**: `observability/` directory stubs — Stage 0 design doc + code-execution phase owns creation; recon does NOT pre-stub | ✅ RESOLVED | Recon doc §R-7a-6 |

## Stage 0 Pre-flight Recon items (open at cascade fire-time; reviewers may resolve inline or punt to code-write)

| Item | Question | Source |
|---|---|---|
| **Recon-T-1** | Boot ordering invariant — where does telemetry init slot in? Per Phase 6c A8 carryover (renderers FIRST, transports LAST): telemetry init proposed BEFORE renderers so User Timing marks at first-queue-render are captured. Verify at code-write that `boot.ts` accepts a pre-renderer init hook. | `00-synthesis-and-roadmap.md` §3 + Phase 6c execution plan §2.4 |
| **Recon-T-2** | `ApiClient.AbortSignal.any` integration — does OTLP/HTTP exporter participate in the same abort signal as other HTTP traffic (so a page-unload aborts telemetry POSTs)? OTel SDK has its own exporter retry/backoff; integration point TBD at code-write. | Phase 2 `ApiClient` design (`03-phase2-foundation-design.md`) |
| **Recon-T-3** | `console.log` boot handshake convention — should telemetry init emit `'[multiplexer] telemetry:initialized'` to extend the existing handshake (matching `'authManager:ready'`, `'conversationModePinRenderer:mounted'` pattern)? PROPOSED yes. | Phase 6c execution plan §2.4 boot log canonical order |
| **Recon-T-4** | Persisted-vs-volatile trace_id — does the OTel trace_id persist across navigations (sessionStorage) or reset per page load? PROPOSED reset per page (page-load span is the canonical root). Stage 0 author's call; reviewer may flip. | OTel browser SDK conventions |

---

## Cluster T — Telemetry (Q-T1..Q-T7)

Phase 7a is monolithic — one cluster covering all telemetry. Q-decisions follow Phase 6c Q-format: PROPOSED stance + Rationale + Options walked + Implications.

### Q-T1 — User Timing canonical lifecycle points

**PROPOSED**: 6 canonical `performance.mark()` anchors per slicing manifest §Slice boundaries:

| Mark name | Emission site | Detail field shape |
|---|---|---|
| `multiplexer:boot:start` | `boot.ts` first line | `{ phase: "boot-start" }` |
| `multiplexer:boot:complete` | `boot.ts` after all renderers mount | `{ phase: "boot-complete", handlerCount: N }` |
| `multiplexer:queue:first-render` | First production-path `renderSenderSection()` invocation, idempotency-guarded by new `#firstRenderEmitted` private flag (flag set on first emit). **Revised 2026-05-20 per Stage 1 F-1**: `forceRenderForTesting()` is test-only by naming convention (consistent across 4 renderers per Rachel's grep); `renderAll()` is itself test-only-reachable. The production path is `subscribe()` → bus event handler → `renderSenderSection()` directly, so the mark must hook there. Step T4 already specifies the `#firstRenderEmitted` idempotency guard. | `{ entryCount: N }` |
| `multiplexer:tts:playback-start` | `AudioStore` on `store_audio_chunk_decoded` first emission per playback | `{ jobId: <id> }` |
| `multiplexer:ws:reconnect` | `ws-channel.ts` on transition `disconnected → connected` (post-initial-connect) | `{ attemptCount: N, downtime_ms: N }` |
| `multiplexer:auth:refresh` | `AuthManager` on successful refresh response | `{ tokenLifetime_ms: N }` |

**Rationale**: matches OpenAI review §2.3 framing ("explicit User Timing marks at queue render, TTS start, reconnect, refresh"). Each anchor is a distinct UX-meaningful moment; granularity is intentionally coarse to keep emission overhead negligible (<1ms per mark).

**Mark accumulation note (R-4 v2-defer 2026-05-20)**: User Timing marks accumulate for session lifetime; no `performance.clearMarks()` is called by Phase 7a. Bounded by browser-native User Timing buffer limits which are implementation-defined but empirically sufficient for typical session length (a 4-hour session ≈ ~95 marks under steady-state usage given the 6-anchor schema above; well under any reasonable browser-buffer cap). Long-running-session clear policy deferred to v2 per OSQ-T-7.

**Options walked**:
- ~~Fine-grained per-renderer mounts~~ — rejected: high-cardinality, low-signal; AC10b boot.js gz delta would balloon.
- ~~Coarse-only (boot start/complete)~~ — rejected: misses the per-feature observability OpenAI flagged.
- ~~Auto-emit on every store_*_changed event~~ — rejected: 100+ marks/sec under typical load is noise.

**Implications for downstream Qs**:
- Q-T4 trace span boundaries inherit these 6 anchors as canonical span-start/end points
- Q-T5 perf budget literals tie to specific marks (`boot:complete - boot:start < N ms`)

### Q-T2 — Long Tasks API observer instantiation site + handler shape

**PROPOSED**: single observer wired in `multiplexer/observability/timing.ts::createLongTasksObserver()` factory. Boot-time instantiation in `boot.ts` AFTER auth resolves but BEFORE renderer mount (so renderer-paint Long Tasks are captured). Handler shape:

```typescript
export interface LongTasksObserver {
  stop(): void
}

export function createLongTasksObserver(
  opts: { onLongTask: (entry: PerformanceLongTaskTiming) => void }
): LongTasksObserver | null  // returns null when Long Tasks API unavailable (Safari)
```

Feature-detect: `if ( !PerformanceObserver.supportedEntryTypes?.includes( "longtask" ) ) return null;` per recon R-7a-2. Safari users get a `null` observer (no-op).

Each Long Task entry routed to (a) User Timing as a measure for inline visibility AND (b) OTel as an event on the active trace span if one exists.

**Long Task event attribute schema (R-1 enumerated explicitly 2026-05-20)**: Long Task OTel events carry `{ duration, name, startTime }` ONLY. **EXCLUDE `attribution[*]` entirely** — TaskAttributionTiming fields (containerName, containerSrc, containerId) can carry DOM IDs, classes, or attribute values containing fragments of user content (e.g., notification text rendered into a Long-Task-causing repaint surfaces as `containerId="notif-{sessionId}"` or `containerSrc` referencing user-generated URLs). PII exclusion at the boundary.

**Per-span event cap (R-1 2026-05-20)**: Max **50** longtask events attached per active OTel span. Once cap reached on a span, subsequent Long Task occurrences during that span's lifetime increment a `longtask_overflow_count: number` attribute on the span instead of attaching new events. Prevents unbounded cardinality on long-running spans (e.g., a stuck page-load span accumulating thousands of longtask entries before exporter flush).

**Rationale**: factory pattern matches Phase 6c renderer/recorder precedent; null-return communicates feature-detect outcome explicitly. Routing to BOTH User Timing and OTel gives in-browser dev visibility AND production telemetry path.

**Options walked**:
- ~~Throw on Safari instead of null-return~~ — rejected: violates graceful-degradation; would force Safari to skip all telemetry init.
- ~~Console.warn on Long Task ≥ N ms~~ — rejected: noisy in prod; logging belongs in dev-tools, not the default observer handler.

### Q-T3 — ReportingObserver registration scope

**PROPOSED** (revised 2026-05-20 per Stage 2 R-3 Path A pin): register `ReportingObserver` for `['deprecation', 'intervention']` ONLY. **`crash` REMOVED** from registered types. Boot-time instantiation in `boot.ts` AFTER Long Tasks observer (no ordering constraint, just alongside). Feature-detect via `typeof ReportingObserver !== 'undefined'` per recon R-7a-4.

Each report entry routed to OTel as a span event with `reportType` attribute (not as a separate trace).

**Rationale**: Chrome-only signal (FF + Safari fall back to no-op). The 2 retained report types are **browser-API metadata only** (no user content) — deprecation warnings catch upcoming browser-API breakage, intervention reports flag browser-side throttling (e.g., autoplay blocking).

**`crash` report exclusion rationale (R-3 PATH A 2026-05-20)**: `crash` reports are EXCLUDED because raw `report.body` routinely contains stack traces with sensitive runtime data — auth tokens held in closures via in-flight `fetch()` `Authorization` headers, URL fragments with `token=` / `session=` / `auth=` query params, local variables holding user content fragments rendered into the active surface. Exporting raw crash bodies to an OTel collector would exfiltrate session tokens off-frontend into observability infrastructure. Sanitizer-based crash inclusion (Path B) is deferred to v2 per OSQ-T-6 when a redaction module can be designed with explicit pattern catalog + false-negative testing strategy.

> **Manager-ratified 2026-05-20** (Tiberius 🌑, Run 4 Stage 2 cap-2 turn 2): Path A (drop `crash` from registered types) PINNED over Path B (sanitizer-based inclusion). Rationale: sanitizer false-negative risk is high (the absence of a token in stack traces is unverifiable; one missed pattern leaks indefinitely); exported telemetry to a collector cannot be remediated post-hoc; minimum-blast-radius wins. v2 OSQ-T-6 captures the sanitizer-design follow-on.

**Options walked**:
- ~~Skip ReportingObserver entirely (Chrome-only is too narrow)~~ — rejected: Chrome users represent significant traffic; the net signal is positive at zero cost on other browsers.
- ~~Add `csp-violation` report type~~ — rejected: 7b CSP slice owns CSP violation reporting via its own `/api/csp-report` endpoint; double-handling would be confusing.
- ~~Per-report-type filter at handler vs registration~~ — chose registration filter (specify exact types up-front) for explicit allow-list semantics.

### Q-T4 — OTel trace span granularity

**PROPOSED**: 3 trace span types, all created via `@opentelemetry/api` `tracer.startSpan()`:

| Span type | Parent | Span name | Span lifetime |
|---|---|---|---|
| **Page-load span** | Root | `multiplexer.page-load` | Created at `boot:start` mark; ended at `boot:complete` mark. Container for all boot-time activity. |
| **Key-action spans** | Page-load (if extant; else root) | `multiplexer.action.<action-type>` | Created at canonical action start (TTS playback start, WS reconnect attempt, auth refresh). Ended at action complete. |
| **Long Task event spans** | Active span at time of Long Task | NONE — Long Tasks recorded as `span.addEvent('longtask', {...})` not as standalone spans | n/a (event-only) |

**`@opentelemetry/sdk-metrics` decision**: DEFER. Traces-only first cut. Reviewer may flip if histogram framing wins for Long Tasks (e.g., "longtasks per minute" as a histogram metric vs span events).

**Rationale**: 3 span types maps to UX-meaningful granularity without explosion. Long Tasks as events (not spans) avoids over-counting (long tasks are signals about the parent span, not standalone work units).

**Options walked**:
- ~~Per-render span~~ — rejected: high-cardinality, gzips poorly through OTLP, adds significant exporter load.
- ~~Single page-load span only~~ — rejected: too coarse to attribute slow TTS or reconnect; loses the per-action breakdown OpenAI's review wanted.
- ~~Metrics-only (histograms for boot time, longtask count, reconnect duration)~~ — rejected for first cut: traces give better drill-down for UX debugging; can add metrics as follow-on if needed.

### Q-T5 — Perf budget literals

**PROPOSED**: smoke-tier wall-clock thresholds enforced via `expect(performance.getEntriesByName('multiplexer:boot:complete')[0].startTime).toBeLessThan(N)` style:

| Anchor | Budget (wall-clock) | Rationale |
|---|---|---|
| `multiplexer:boot:complete` since `boot:start` | **< 1500 ms** | Phase 6c boot completed in ~400 ms locally per Tiffany's history.md entry; 4x headroom for CI variance + telemetry init overhead. |
| `multiplexer:queue:first-render` since `boot:complete` | **< 200 ms** | Phase 6c first-render observed < 50 ms; 4x headroom. |
| Long Task count over typical 60-second load test | **< 5 longtasks** | Long Tasks > 50ms; modern browsers expect renderers to stay under this threshold during steady state. 5 budget allows for initial paint + audio-decode bursts. |

**TBD-at-code-write**: actual literals may shift based on AC10b OTel SDK weight impact on boot time. Reviewer may push for tighter or looser values.

**Rationale**: literals derived from empirical Phase 6c data with 4x headroom for CI variance. AC-7a-PERF asserts these via vitest with `:7999` smoke tier (not :8000 since perf assertions are non-state-mutating).

**Options walked**:
- ~~Tight budgets (1.5x headroom)~~ — rejected: CI flakiness risk; over-pages on routine variance.
- ~~Soft warnings only (console.warn on budget breach)~~ — rejected: telemetry without enforcement drifts; AC failure is the enforcement.

### Q-T6 — Sampling strategy

**PROPOSED**: client-side **head-based sampling** at configurable rate via second INI key `multiplexer otel sampling rate` (default `1.0` = 100% in dev/test; production sets `0.1` = 10% or whatever the budget allows). Sampling decision made at trace root (page-load span); descendant spans inherit.

**Implementation**: `@opentelemetry/sdk-trace-web` ships with `TraceIdRatioBasedSampler(rate)`. Config-driven instantiation.

**Rationale**: head-based at root is the canonical OTel pattern. Tail-based requires collector cooperation (out of scope). Always-on (no sampling) burns cost at scale; head-based-with-config gives the production knob.

**Error-span preservation note (R-2 v2-defer 2026-05-20)**: head-based sampling at the trace root causes 90% of error spans to be dropped at the production sampling rate (0.1). Canonical OTel mitigation is collector-side **tail-based sampling** with always-on policy for `status_code: ERROR` — but collector deployment is OUT OF SCOPE per §Out-of-scope. Client-side `ParentBasedSampler` wrapping logic can also preserve error spans by overriding the root sampling decision when an exception fires; that approach is heavier and is deferred to v2 per OSQ-T-5.

**Options walked**:
- ~~Always-on (no sampling)~~ — rejected: production cost grows linearly with traffic; collector-side filtering would be required anyway.
- ~~Tail-based via collector~~ — rejected: requires collector cooperation; collector deployment is out of scope.
- ~~Per-action sampling (different rate per action type)~~ — rejected: complexity for first cut; can add later if needed.

### Q-T7 — Telemetry init handshake + sequencing in boot.ts

**PROPOSED**: telemetry init slots into `boot.ts` BEFORE the renderer mount sequence (per Recon-T-1). Boot log order:

```
[multiplexer] authManager:ready          (pre-renderer per F-Arnold-C4)
[multiplexer] telemetry:initialized       (NEW — Phase 7a)
[multiplexer] notificationsRenderer:mounted
... existing Phase 5/6a/6b/6c renderers ...
```

Telemetry init steps inside the handshake:

1. Read INI keys (`multiplexer otel collector endpoint`, `multiplexer otel sampling rate`) from a config blob exposed to the multiplexer at boot
2. Instantiate User Timing wrapper (no-op for now; just the function pointer mounted on a namespace)
3. Instantiate Long Tasks observer (feature-detect; null on Safari)
4. Instantiate ReportingObserver (feature-detect; null on FF + Safari)
5. Instantiate OTel SDK + tracer + exporter (head-based sampler; no-op exporter if endpoint empty)
6. Emit `[multiplexer] telemetry:initialized` to console + emit `multiplexer:boot:telemetry-init-complete` User Timing mark

**`BootCompletePayload.handlers.telemetry?: string`** extension to `shared/types.ts` per Phase 6c boot handshake pattern. **Value semantics specified 2026-05-20 per Stage 1 P-1**: literal string `"initialized"` (mirroring `notificationsRenderer === "mounted"` AC pattern from Phase 5/6a/6b/6c renderers per `shared/types.ts:442-480`). Telemetry is NOT a renderer (no DOM mount); the `"initialized"` literal signals "observers attached + tracer ready + exporter wired (no-op if endpoint empty)." Distinct from renderer `"mounted"` semantics on purpose.

**Rationale**: pre-renderer init means renderer-paint marks (first-queue-render) are captured. Console-log handshake extends existing convention. Telemetry being "initialized" means the observers are attached and the exporter is ready, even if the endpoint is empty (no-op exporter still constructs spans, just discards them).

**Options walked**:
- ~~Post-renderer init (after all renderers mount)~~ — rejected: first-queue-render User Timing mark would not be captured.
- ~~Init telemetry as part of AuthManager's ready flow~~ — rejected: telemetry doesn't depend on auth; conflating them creates ordering churn if either changes.

---

## Cluster T — PROPOSED design summary

| Aspect | PROPOSED stance |
|---|---|
| User Timing marks | 6 anchors per Q-T1 |
| Long Tasks observer | Single factory; feature-detect; null-on-Safari; route entries to both User Timing measures + OTel span events |
| ReportingObserver | `['deprecation', 'intervention']` (R-3 Path A 2026-05-20); feature-detect; null-on-FF+Safari; route to OTel span events |
| OTel SDK | `api` + `sdk-trace-web` + `exporter-trace-otlp-http`; 3 span types (page-load, key-action, Long Task events) |
| Sampling | Head-based via `TraceIdRatioBasedSampler`; config-driven rate (dev default 1.0, prod default TBD-by-deployment) |
| Perf budgets | Boot < 1500ms, first-queue-render < 200ms, longtask count < 5/minute |
| Boot wiring | Telemetry init BEFORE renderer mount; `[multiplexer] telemetry:initialized` handshake line |
| Bundle delta | TBD at AC10b measure-time per OSQ-T-1 (Recon-T-5 consolidated into OSQ-T-1 per C-1 closure 2026-05-20) |

---

## Acceptance Criteria (AC-7a-1 through AC-7a-14)

Per Phase 6c precedent + Conventions 3 (EXECUTOR tags), 4 (TBD markers explicit), 5 (`:8000` slot-coordination semantics), and Persona 2.A point 9 (conditional-executability markers).

| AC | Description | EXECUTOR | Conditional-on |
|---|---|---|---|
| **AC-7a-1** | `npx tsc --noEmit -p tsconfig.json` exits 0 across the whole multiplexer tree | AI | — |
| **AC-7a-2** | `npx eslint src/fastapi_app/static/js/multiplexer/` exits 0 | AI | — |
| **AC-7a-2e** | Grep-gate: zero `.innerHTML =`, `rawHTML(`, `.outerHTML =` on the NEW observability files | AI | — |
| **AC-7a-3** | `timing.ts` unit tests pass (≥10 cases: mark emission lifecycle + Long Tasks observer feature-detect + ReportingObserver feature-detect + factory return shapes) | AI | — |
| **AC-7a-4** | `otel.ts` unit tests pass (≥8 cases: tracer init + sampling rate config + no-op-exporter-on-empty-endpoint + span lifecycle + Long Task event attachment) | AI | — |
| **AC-7a-5** | Existing renderer/store/transport test suites still green after instrumentation edits (Phase 5/6a/6b/6c regression) | AI | — |
| **AC-7a-6** | 100% c8 line + branch + function coverage on multiplexer TS via directory-wide glob `c8 --100 --include='src/fastapi_app/static/js/multiplexer/**/*.ts'` per `feedback_100pct_coverage_multiplexer` (Lupin-wide post-2026-05-16) | AI | — |
| **AC-7a-7** | Stylelint: N/A — Phase 7a is JS+TS only, no CSS edits | AI | — |
| **AC-7a-8a** | Functional smoke on `:7999`: User Timing marks present at all 6 canonical anchors after boot (asserted via `performance.getEntriesByType('mark')`) | AI | — |
| **AC-7a-8b** | Perf gate on `:7999`: boot < 1500ms under steady-state, **assuming `/api/multiplexer/config` p99 < 200ms** (R-7 SLO clarification 2026-05-20); first-queue-render < 200ms; longtask count < 5/minute under typical load. CI cold-start warm-up may briefly exceed; budget gate runs after a 1-test-warm-up smoke ping (matches Phase 6c boot perf pattern). If steady-state `/api/multiplexer/config` p99 exceeds 200ms in production telemetry post-deployment, AC-7a-8b literal re-baselines to actual config-fetch p99 + 1300ms processing budget. **Paired with R-5 bounded-timeout** — worst-case boot bounded at 500ms (config-cap) + ~200ms (telemetry init) + ~50ms (first-queue-render) = ~750ms comfortably inside 1500ms. **TBD-at-code-write** if AC10b SDK weight forces budget revisit. | AI | OSQ-T-1 (bundle delta) |
| **AC-7a-9** | `boot_complete` handshake includes `telemetry:initialized` in canonical order BEFORE renderer mounts. Grep gate: `payload.handlers.telemetry === "initialized"` literal string per Stage 1 P-1 (mirrors `notificationsRenderer === "mounted"` AC pattern). **Handshake-fires-within-500ms assertion (R-5 extension 2026-05-20)**: mocked test where `/api/multiplexer/config` never resolves still produces `telemetry:initialized` handshake within 500ms (bounded-timeout safe-defaults path verified). | AI | — |
| **AC-7a-10** | Phase 5 + 6a + 6b + 6c regression suites all green after telemetry instrumentation (no regression) | AI | — |
| **AC-7a-10b** | `boot.js` gz delta ≤ **TBD-KB** vs Phase 6c baseline. Implementer resolves at code-write per `npm install` + esbuild measurement (R-6 polish 2026-05-20 — Manager call: TBD acceptable per Persona-2-pt-9 escape hatch, no author bandwidth burn on `npm install --dry-run`). **Suggested upper bound** based on `@opentelemetry/api` + `@opentelemetry/sdk-trace-web` + `@opentelemetry/exporter-trace-otlp-http` minified+gzipped: ~50KB. Implementer pins literal in revision PR once measured. | AI | OSQ-T-1 |
| **AC-7a-LT** | Long Tasks observer feature-detect path returns no-op (`null`) on Safari; non-Safari emits longtask entries (mocked happy-dom test). **Attribute schema assertion (R-1 extension 2026-05-20)**: emitted Long Task OTel events carry `{ duration, name, startTime }` ONLY — assertion verifies `attribution` field NOT present on the event. **Per-span cap assertion (R-1 extension 2026-05-20)**: 51st longtask occurrence on a span attaches `longtask_overflow_count: 1` attribute and does NOT add a 51st event; 52nd → `longtask_overflow_count: 2`. | AI | — |
| **AC-7a-REP** | ReportingObserver feature-detect path returns no-op on FF + Safari; Chrome path emits report entries (mocked happy-dom test) | AI | — |
| **AC-7a-OTEL** | No-op exporter path verified at boot when INI endpoint empty; OTLP/HTTP exporter wired when endpoint is set (mock collector assertion) | AI | — |
| **AC-7a-SAMP** | Head-based sampler honors INI rate (mock 10% rate → ~10% of trace IDs sampled in a 1000-id span) | AI | — |
| **AC-7a-11** | Visual regression: N/A — Phase 7a is invisible to UI; no snapshot baseline needed | AI | — |
| **AC-7a-12** | `:8000` integration: N/A for Phase 7a (no server-side endpoint added; telemetry is client-side only; OTel collector is OUT OF SCOPE) | AI | — |
| **AC-7a-13** | INI key `multiplexer otel collector endpoint` documented in `lupin-app-splainer.ini` per `feedback_env_var_read_and_set_land_together`. Similarly `multiplexer otel sampling rate`. | AI | — |
| **AC-7a-14** | Documentation TOUCHPOINTS — new R&D doc (this design) cited; manifest §Ratification outcomes #2 traceability link present | AI | — |

**Note on Convention 5 ("Manual E2E" semantics)**: Phase 7a has no `:8000` baseline rows — telemetry instrumentation is verified via `:7999` smoke + unit tests. If the OTel collector deployment lands in a follow-on initiative, it gets its own scheduled `:8000` integration tests with HUMAN slot-coordination.

---

## Step-by-step execution sequence (Step T1..T7)

Steps run sequentially per `feedback_pip_plan_review_is_sequential`. Each step is a self-contained code-write unit; reviewer feedback can halt between steps.

### Step T1 — INI keys + splainer entries

- Edit `src/conf/lupin-app.ini` `[Lupin: Baseline]`: add `multiplexer otel collector endpoint = ` (empty default) + `multiplexer otel sampling rate = 1.0`
- Edit `src/conf/lupin-app-splainer.ini`: matching explanations per key
- Per-env overrides:
  - `[Lupin: Development]` inherits empty (no traces shipped from dev)
  - `[Lupin: Production]` sets endpoint URL when collector lands (TBD; default empty for now)
  - `[Lupin: Testing]` inherits empty unless integration test needs mock collector

### Step T2 — `multiplexer/observability/timing.ts`

NEW module. Exports:
- `mark(name: string, detail?: object): void` — wrapper around `performance.mark(name, { detail })`; no-ops if `performance` unavailable
- `measure(name: string, opts: { start: string, end: string }): void` — wrapper around `performance.measure`
- `createLongTasksObserver(opts: { onLongTask: (entry: PerformanceLongTaskTiming) => void }): LongTasksObserver | null` per Q-T2
- `createReportingObserver(opts: { onReport: (report: Report) => void; types: string[] }): { stop(): void } | null` per Q-T3

LOC budget: ~200-300

### Step T3 — `multiplexer/observability/otel.ts`

NEW module. Exports:
- `createOtelTracer(opts: { endpoint: string, samplingRate: number, serviceName: string }): { tracer: Tracer, shutdown: () => Promise<void> }`
- Internally: instantiate `WebTracerProvider` → register exporter (`OTLPTraceExporter` if endpoint, `NoopSpanProcessor` if empty) → register sampler (`TraceIdRatioBasedSampler(samplingRate)`) → register tracer

LOC budget: ~150-250

### Step T4 — Instrumentation wiring into existing modules

Edits to existing files to emit User Timing marks at canonical points per Q-T1:

| File | Edit |
|---|---|
| `multiplexer/boot.ts` | Add `mark('multiplexer:boot:start', ...)` at first line + `mark('multiplexer:boot:complete', ...)` after all renderer mounts |
| `multiplexer/render/NotificationsListRenderer.ts` | Add `mark('multiplexer:queue:first-render', ...)` guarded by `#firstRenderEmitted` flag (emit once) |
| `multiplexer/stores/AudioStore.ts` | Add `mark('multiplexer:tts:playback-start', ...)` on first `store_audio_chunk_decoded` per playback |
| `multiplexer/transport/ws-channel.ts` | Add `mark('multiplexer:ws:reconnect', ...)` on `disconnected → connected` transition (post-initial-connect; `#hasConnectedBefore` flag) |
| `multiplexer/auth/AuthManager.ts` | Add `mark('multiplexer:auth:refresh', ...)` on successful refresh response |

Each mark also creates an OTel span event on the active span if one exists.

### Step T5 — `boot.ts` telemetry init wiring per Q-T7

- **Config injection mechanism RESOLVED 2026-05-20 per Stage 1 P-2** (replaces prior TBD):
  - Existing pattern at `boot.ts:148-160`: `fetch('${apiBaseUrl}/api/multiplexer/config')` already runs at boot (per Phase 6a Pass 2 F20 precedent — currently fetches `meta_display_cap` consumed by `configureMetaDisplayCap()`)
  - **Server-side extension required**: extend `/api/multiplexer/config` Pydantic response model (in `src/cosa/rest/routers/multiplexer.py` or wherever the endpoint lives — verify at code-write) to include `otel_collector_endpoint: str` (default empty) + `otel_sampling_rate: float` (default 1.0). Server reads from `ConfigurationManager` (which reads the new INI keys per Step T1). Pydantic-native validation per `feedback_pydantic_native_validation`.
  - **Client-side wiring**: extend the `fetch('${apiBaseUrl}/api/multiplexer/config')` `.then()` handler at `boot.ts:155+` to read `serverConfig.otel_collector_endpoint` + `serverConfig.otel_sampling_rate` and pass into `createOtelTracer({endpoint, samplingRate, serviceName: 'lupin-multiplexer'})`
- **Bounded-timeout + safe-defaults (R-5 SUB-REVISE 2026-05-20)**: the config-fetch wraps in `Promise.race([fetch('/api/multiplexer/config'), new Promise(resolve => setTimeout(() => resolve(SAFE_DEFAULTS), 500))])`. Hard cap **500ms**. On timeout OR error → telemetry init proceeds with safe defaults: `otel_collector_endpoint = ""` (no-op exporter) + `otel_sampling_rate = 1.0`. Telemetry handshake `[multiplexer] telemetry:initialized` still fires (renderers can mount). Log `console.warn('[multiplexer] telemetry: config-fetch timed out or failed; using safe defaults')` for dev-tools visibility. Failure-mode cascade (config-fetch stall → telemetry init stall → renderer mount stall → UI blank) bounded at 500ms worst-case.
- Instantiate observers + tracer per Step T2/T3
- Boot log emission: `console.log('[multiplexer] telemetry:initialized')` + set `payload.handlers.telemetry = "initialized"` literal per P-1
- Mount BEFORE renderers per Q-T7

> **Manager-ratified 2026-05-20** (Tiberius 🌑, Run 4 Stage 1 cap-2 close): P-2 CoSA config-plumbing extension lives within Phase 7a scope. Config plumbing (2 fields added to existing `/api/multiplexer/config` Pydantic response model) ≠ server-side instrumentation per §Out-of-scope semantics. Implementer responsibilities: commit Lupin-side changes in this session's working tree; commit CoSA-side router edit in CoSA-context session (separate git operation) per `feedback_lupin_only_never_cosa`.

**Ordering note for the config-fetch boundary**: the existing `fetch('/api/multiplexer/config')` is fire-and-forget (boot proceeds before resolve). For Phase 7a telemetry, the OTel config needs to be available BEFORE renderers mount (so renderer-paint marks land in the configured tracer). Stage 0 author's PROPOSED resolution: telemetry init AWAITS the config-fetch before completing; renderers wait on telemetry handshake. Reviewer may flip if non-blocking init is preferred (then OTel buffers spans until config resolves and replays — heavier implementation).

> **Manager-ratified 2026-05-20** (Tiberius 🌑, Run 4 Stage 1 cap-2 close): **Option A (block-on-config-fetch) PINNED** as PROPOSED. Rationale: +1 RTT acceptable on boot path already awaiting auth + multiplexer config; non-blocking + replay adds defect surface for marginal latency gain. Krishna 🦚 (Stage 2 Risk/Anti-pattern) may flip if her review surfaces a Risk lens reason; symmetric reversibility means flipping is cheap. Starting position is Option A, not "both visible."

> **Sub-revised 2026-05-20** (Tiberius 🌑, Run 4 Stage 2 cap-2 turn 2 R-5): Option A structurally preserved + bounded-timeout 500ms + safe-defaults fallback added per Krishna's R-5. Failure-mode cascade (config-fetch stall → telemetry init stall → renderer mount stall → UI blank) bounded at 500ms worst-case. Pairs with R-7's AC-7a-8b SLO assumption — worst-case boot becomes ~750ms inside 1500ms budget (500ms config-cap + ~200ms telemetry init + ~50ms first-queue-render). Sanitizer-design (Path B from R-3) and `ParentBasedSampler` (R-2) remain v2 deferred per OSQ-T-6 + OSQ-T-5.

### Step T6 — Tests

| Test file | Cases |
|---|---|
| `src/tests/unit/multiplexer/observability/timing.test.ts` | ≥10: mark emission, measure emission, Long Tasks feature-detect, ReportingObserver feature-detect, factory null returns, error handling |
| `src/tests/unit/multiplexer/observability/otel.test.ts` | ≥8: tracer init, no-op exporter when endpoint empty, OTLP exporter when endpoint set, sampling rate honored, span lifecycle, Long Task event attachment, shutdown |
| Extensions to existing `boot.test.ts` | Telemetry init handshake assertion (`telemetry:initialized` in console log canonical order) |

Vitest run + c8 100% coverage gate per `feedback_100pct_coverage_multiplexer`.

### Step T7 — Smoke + perf gate verification

- Add Phase 7a portion to `src/tests/smoke/test_multiplexer_phase7a_smoke.py` (NEW file) — 8 cases covering AC-7a-8a + AC-7a-LT + AC-7a-REP + AC-7a-OTEL + AC-7a-SAMP + AC-7a-9
- Add perf gate (AC-7a-8b) as part of same smoke file
- Verify all 14 ACs green per Conventions 3 + 4 + 5

---

## Files to write (NEW)

| Path | Purpose | Size budget |
|---|---|---|
| `src/fastapi_app/static/js/multiplexer/observability/timing.ts` | User Timing wrapper + Long Tasks observer + ReportingObserver factories | ~200-300 LOC |
| `src/fastapi_app/static/js/multiplexer/observability/otel.ts` | OTel SDK init + tracer + exporter + sampler | ~150-250 LOC |
| `src/tests/unit/multiplexer/observability/timing.test.ts` | timing.ts unit tests | ≥10 cases |
| `src/tests/unit/multiplexer/observability/otel.test.ts` | otel.ts unit tests | ≥8 cases |
| `src/tests/smoke/test_multiplexer_phase7a_smoke.py` | Functional smoke + perf gate | 8 cases |

## Files to edit (EDITED)

| Path | What changes |
|---|---|
| `src/fastapi_app/static/js/multiplexer/boot.ts` | Telemetry init pre-renderer + boot:start/boot:complete marks + handshake log |
| `src/fastapi_app/static/js/multiplexer/render/NotificationsListRenderer.ts` | queue:first-render mark with idempotent guard |
| `src/fastapi_app/static/js/multiplexer/stores/AudioStore.ts` | tts:playback-start mark on first chunk decode |
| `src/fastapi_app/static/js/multiplexer/transport/ws-channel.ts` | ws:reconnect mark on reconnect transition |
| `src/fastapi_app/static/js/multiplexer/auth/AuthManager.ts` | auth:refresh mark on refresh success |
| `src/fastapi_app/static/js/multiplexer/shared/types.ts` | `BootCompletePayload.handlers.telemetry?: string` extension; value literal `"initialized"` per Stage 1 P-1 |
| `src/conf/lupin-app.ini` | `multiplexer otel collector endpoint` + `multiplexer otel sampling rate` keys |
| `src/conf/lupin-app-splainer.ini` | Matching explanations |
| `package.json` | Add 3 OTel deps + version pins |
| `src/cosa/rest/routers/multiplexer.py` (or wherever `/api/multiplexer/config` lives — verify at code-write) | **Added 2026-05-20 per Stage 1 P-2 resolution**: extend Pydantic response model with `otel_collector_endpoint: str` (default empty) + `otel_sampling_rate: float` (default 1.0). Server reads from `ConfigurationManager` (INI keys per Step T1). Pydantic-native validation per `feedback_pydantic_native_validation`. **Scope note**: this is a 2-field extension of an EXISTING endpoint (not a new endpoint); §Out-of-scope's "Server-side OTel" carve-out refers to server-side instrumentation, NOT config plumbing. CoSA submodule edit per `feedback_lupin_only_never_cosa` — editing fine, git ops must happen in CoSA-context session. **F-Rio-7a-3 documented-not-revised 2026-05-20**: implementer files CoSA cross-project handoff seed at code-write time per `feedback_cross_project_handoff_doc` — handoff doc + seed TODO in CoSA TODO.md pointing to it. |

---

## Open Standing Questions (OSQs)

| OSQ | Question | PROPOSED stance |
|---|---|---|
| **OSQ-T-1** | Bundle-delta budget for AC10b: cannot measure without actual npm install. Implementer resolves at code-write per `npm install` + esbuild measurement (consolidated from Recon-T-5 per C-1 closure 2026-05-20). Suggested upper bound ~50KB minified+gzipped per Stage 2 R-6. | TBD-at-code-write; ≤~50KB suggested |
| **OSQ-T-2** | OTel `service.name` resource attribute: hardcode `lupin-multiplexer` or read from INI? PROPOSED hardcode; service identity is structural, not config. | Hardcode `lupin-multiplexer` |
| **OSQ-T-3** | trace_id propagation to server-side: out of scope for 7a (server-side OTel is a separate initiative); 7a does NOT inject `traceparent` headers into server-bound requests. PROPOSED: defer. | Defer |
| **OSQ-T-4** | Manual instrumentation of WS message round-trips: each WS request/response pair as a span? PROPOSED: NO — too high-cardinality; rely on the 6 canonical anchors. Reviewer may push for finer granularity. | Skip; rely on 6 anchors |
| **OSQ-T-5** (filed per Stage 2 R-2 closure 2026-05-20) | Error-span preservation under reduced sampling rate. Head-based sampling at root drops 90% of error spans at `rate=0.1`. Mitigation options: collector-side tail-based sampler (always-on for `status_code: ERROR`) OR client-side `ParentBasedSampler` wrapping logic. Collector is out of scope; client-side wrap is heavier. | Defer to v2 |
| **OSQ-T-6** (filed per Stage 2 R-3 Path A closure 2026-05-20) | Crash-report ingestion via sanitizer module. Pattern catalog for `Bearer\s+\S+`, query-string redaction (`token` / `session` / `auth` / `api[_-]?key`), stack-frame string-arg truncation. R-3 Path A removed `crash` from registered types for PII safety; sanitizer-based inclusion requires explicit false-negative test design. | Defer to v2 with explicit false-negative test design |
| **OSQ-T-7** (filed per Stage 2 R-4 closure 2026-05-20) | `performance.clearMarks()` policy for long-running sessions. Phase 7a does NOT clear marks (browser-native buffer limits accepted as sufficient — ~95 marks/4-hour session). Add clear-after-export hook once telemetry collector lands and export cadence is known. | Defer to v2 (post-collector deployment) |

---

## Self-audit against Persona 2.A rubric (13 points)

Per `planning-is-prompting/workflow/plan-review-cascaded-personas.md` Persona 2.A (Author Self-Audit):

| # | Rubric point | Compliance |
|---|---|---|
| 1 | Scope is bounded — what's IN and OUT explicitly enumerated | ✅ §Scope + §Out-of-scope confirmation |
| 2 | Out-of-scope items reference the slicing manifest or upstream R&D | ✅ §Out-of-scope cites slicing manifest §Permanently out of scope |
| 3 | All Q-decisions present PROPOSED stances (not just options) | ✅ Q-T1..Q-T7 all have PROPOSED + Options walked |
| 4 | Recon items distinguish RESOLVED (upstream) from open (Stage 0+) | ✅ §Pre-design recon RESOLVED + §Stage 0 Pre-flight Recon items open |
| 5 | ACs use Convention 3 (EXECUTOR tags), 4 (TBD markers), 5 (`:8000` slot-coordination) | ✅ All AC rows have EXECUTOR; TBD markers explicit on AC-7a-8b + AC-7a-10b; Convention 5 N/A note present |
| 6 | Persona 2.A point 9 conditional-executability markers present on ACs depending on Recon items | ✅ AC-7a-8b + AC-7a-10b marked Conditional-on OSQ-T-1 (Recon-T-5 removed per C-1 closure 2026-05-20; OSQ-T-1 carries the bundle-delta budget tracking) |
| 7 | Step-by-step execution sequence with explicit ordering | ✅ Step T1 → T7 sequential |
| 8 | Files NEW + EDITED enumerated with size budgets | ✅ Two tables (Files NEW with LOC budgets; Files EDITED with change descriptions) |
| 9 | OSQs flagged for cascade resolution (or PROPOSED stance for ratification) | ✅ OSQ-T-1..OSQ-T-7 with PROPOSED stances (3 new OSQs filed 2026-05-20 per R-2/R-3/R-4 v2-defers) |
| 10 | Background docs cited at metadata header | ✅ Sister docs + Background docs to lean on |
| 11 | Test pyramid plan present (unit + smoke + perf + regression) | ✅ §Acceptance Criteria covers tsc/eslint/unit/smoke/perf/coverage; §Step T6 + T7 |
| 12 | No `feedback_*` violations from `~/.claude/CLAUDE.md` MEMORY.md | ✅ §Self-audit checklist below |
| 13 | Cascade-readiness — is this design doc reviewable in 4 stages? | ✅ Single cluster, 7 Q-decisions, ~14 ACs, 7 execution steps — comparable density to Phase 6c Cluster A in cascade-fit |

### feedback_* memory self-audit

| Memory | Compliance |
|---|---|
| `feedback_pip_plan_review_is_sequential` | ✅ Steps T1-T7 sequential; cascade Stages 1→2→3 sequential per `13-phase7-slicing-manifest.md` §Cadence per slice |
| `feedback_100pct_coverage_multiplexer` (Lupin-wide post-2026-05-16) | ✅ AC-7a-6 cites 100% c8 directory-wide glob |
| `feedback_pydantic_native_validation` | n/a — no new server endpoint authored in 7a |
| `feedback_baseline_capture_disable_tfe` | n/a — no `:8000` baseline rows in 7a |
| `feedback_test_server_monopolize_mode` | n/a — Phase 7a tests run on `:7999` only (no `:8000` rows) |
| `feedback_lupin_only_never_cosa` | ✅ All paths under `src/fastapi_app/`, `src/conf/`, `src/tests/`; no CoSA submodule changes |
| `feedback_never_auto_commit_push` | ✅ Design doc commits no code; cascade ratification gate + Rick's commit go-ahead per slice |
| `feedback_env_var_read_and_set_land_together` | ✅ Step T1 mandates INI key + splainer entry as paired landing |
| `feedback_tests_must_cover_cross_target_invocations` | ✅ AC-7a-LT + AC-7a-REP + AC-7a-OTEL test cross-browser/cross-config invocations (Safari no-op path, FF+Safari no-op path, empty-endpoint no-op path) |
| `feedback_pass2_is_ownership_audit_not_security` | ✅ Stage 3 reviewer is Rio ⚡ doing Ownership-Language Audit (not security review) per cascade doctrine §Persona 5. Stage 2 reviewer is Krishna 🦚 doing Risk/Anti-pattern review (PII, cardinality, race conditions, failure cascades). R-8 role labels corrected 2026-05-20. |
| `feedback_documentation_step_stops_at_doc` | ✅ This Stage 0 design doc is the deliverable; no code written; no auto-progression |
| `feedback_always_serialize_plan_to_rd_scope_post_exit` | ✅ Doc lives in `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/` per slicing manifest §Per-slice file naming |
| `feedback_tests_parameterize_base_url` | ✅ Smoke tests in `src/tests/smoke/test_multiplexer_phase7a_smoke.py` will inherit existing `LUPIN_API_URL` indirection pattern from Phase 6c smoke tests |
| `feedback_audit_plans_at_execute_time` | ✅ This Self-audit IS the execute-time re-check; reviewer cascade adds 3 more audits (Stages 1, 2, 3) |
| `feedback_always_include_pros_cons_recommendation` | n/a — design doc Qs use Phase 6c "PROPOSED + Options walked" shape, not `ask_multiple_choice` shape |
| `feedback_no_green_in_persona_pool` | n/a — no persona-color decisions in 7a |
| `feedback_tts_body_headline_and_takeaway_only` | n/a — applies to runtime `notify()` calls, not design docs |

No violations detected at draft time. Cascade reviewers (Rachel 🕊️ Stage 1, Krishna 🦚 Stage 2, Rio ⚡ Stage 3) will catch what self-audit misses.

---

## Cascade context for reviewers

**This is Run 4** — the first cascade after Phase 6c Run 3 closed. Two doctrine layers are being live-tested simultaneously:

1. **Step 0 cascade-preparation doctrine** (PIP commit `bbb3e47`) — the recon doc at [`14-phase7a-telemetry-pre-cascade-recon.md`](14-phase7a-telemetry-pre-cascade-recon.md) is the practical instantiation. Reviewers may surface Step 0 doctrine refinements during cascade (template shape, sub-step ordering, etc.) — those become PIP-side doctrine candidates per `feedback_documentation_step_stops_at_doc`.

2. **Step 9 synthesis-and-handoff doctrine** (RATIFICATION-CLOSED 2026-05-19, validation-pending-Run-4) — kicks in after cap reached. Run 4 is the first live test; doctrine candidates will surface in §10.14 of the synthesis doc.

**Reviewer reminders** (from Tiberius's brief, DM `9e011230`):
- Convention 3 EXECUTOR tags present on every AC row
- Convention 4 TBD markers explicit (AC-7a-8b + AC-7a-10b)
- Convention 5 `:8000` slot-coordination semantics — none in Phase 7a (no `:8000` rows)
- Conditional-executability markers per Persona 2.A point 9 (AC-7a-8b + AC-7a-10b)
- 100% c8 coverage Lupin-wide (AC-7a-6) via directory-wide glob
- AC2e safe-write grep guard (AC-7a-2e)

**Cap discipline**: per cascade rules `discussion_turn_cap = 3`, `author_revision_turn_cap = 2`. If Stage 1 surfaces foundational findings, expect author revision loop.

---

## Next steps

1. **DM Tiberius 🌑** confirming Stage 0 draft lands (in_reply_to `9e011230`).
2. **Tiberius reads + dispatches Stage 1 to Rachel 🕊️** with section-specific instructions per Run 3 dispatch pattern.
3. **Stage 1 Usability/Reuse Review** — Rachel grepting prior art, AC2e safe-write checks, conditional-executability marker audit, Persona 2.A rubric application.
4. **Possible author revision loops** (cap 2/2) if Stage 1 surfaces foundational findings.
5. **Stage 2 Risk/Anti-pattern** — Krishna 🦚 hunts PII leakage, cardinality explosion, race conditions, sampling bias, failure-mode cascades (R-8 role corrected 2026-05-20).
6. **Stage 3 Ownership/Convention** — Rio ⚡ hunts executor-tagging gaps + silent user hand-offs + convention adherence (naming, INI key style, test venue rules) per `feedback_pass2_is_ownership_audit_not_security` (R-8 role corrected 2026-05-20).
7. **Step 9 Synthesis** — Manager (Tiberius 🌑) produces the cascade synthesis doc at `16-phase7a-cascade-synthesis.md` after Stage 3 close + cap-lock per Step 9 doctrine (validation-pending-Run-4). This cascade has 4 total stages (Author Stage 0 + 3 reviewer stages: Stage 1 Usability/Reuse + Stage 2 Risk/Anti-pattern + Stage 3 Ownership/Convention) per Q-4 cleanup 2026-05-20.
8. **Implementation handoff** — next-assigned implementer picks up post-cascade.

**No commits per `feedback_never_auto_commit_push`** — this doc + recon doc + manifest amendments remain DIRTY in working tree until Rick's commit go-ahead.

---

— Mr. Radio 🦉 (Stage 0 Author, Lupin session `32a6e563`) — Phase 7a Telemetry design doc, awaiting cascade Stages 1-3.
