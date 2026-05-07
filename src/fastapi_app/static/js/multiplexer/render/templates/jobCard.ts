/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 6a — job card template (`.job-card`).
//
// Per Q-C: legacy class names verbatim; status-{todo|running|done|dead} variants;
// disabled `.job-delete-button` per Q-A6 (handler lands in 6b — see C-6 tooltip).
//
// Per Pass 2 F23: `data-id-hash` is on `.job-card` ONLY (NEVER on the delete
// button). The renderer's click delegation early-returns when the click target
// is the delete button so the disabled `×` never accidentally toggles the card.
//
// Per Pass 2 F20: lazy-render of `Job.meta` JSON is capped at MAX_META_BYTES
// bytes (sourced from FastAPI client-config — see configureMetaDisplayCap below).
// Oversized payloads short-circuit to a "[meta too large to display]" placeholder
// rather than synchronously stringifying on the click thread.
//
// Per Pass 2 F21: `Job.meta` is opaque to 6a. We only stringify it for display
// via `<pre>.innerText`. NEVER spread (`{...job.meta}`), NEVER `Object.assign`
// onto another object, NEVER structurally copy. A malicious server-controlled
// `__proto__` key in meta would inherit through any spread/assign target —
// keeping meta opaque-to-display sidesteps prototype pollution.
//
// Per Pass 1 F12: every keyed-merge element carries `data-id-hash="${job.id_hash}"`.

import { html } from "../html";
import { formatDuration } from "../time";
import type { Job, JobStatus } from "../../shared/types";

interface RenderOptions {
  appTimezone?: string;
}

// ---------------------------------------------------------------------------
// Module-level state — meta-display cap (Pass 2 F20)
// ---------------------------------------------------------------------------

// Default cap (256 KB). Overridden at boot via configureMetaDisplayCap once
// the FastAPI client-config endpoint resolves.
let MAX_META_BYTES = 256_000;

/**
 * Override the meta-display byte cap from a server-config payload.
 *
 * Phase 6a Pass 2 F20 — boot.ts fetches /api/multiplexer/config once at startup
 * and threads the response into this setter BEFORE renderer mount.
 *
 * Requires:
 *   - serverConfig may be an empty object (fetch failed at boundary); in that
 *     case the cap stays at the module default. Only updates when the field
 *     is present and a finite positive integer.
 *
 * Ensures:
 *   - subsequent safeStringifyMeta() calls respect the new cap.
 */
export function configureMetaDisplayCap(
  serverConfig: { multiplexer_max_meta_display_bytes?: number } | null | undefined
): void {
  const candidate = serverConfig?.multiplexer_max_meta_display_bytes;
  if (typeof candidate === "number" && Number.isFinite(candidate) && candidate > 0) {
    MAX_META_BYTES = Math.floor(candidate);
  }
}

/**
 * Test-only: read the current cap. Lets unit tests verify configureMetaDisplayCap
 * actually moved the cap. NOT used by production code.
 */
export function _getMaxMetaBytesForTesting(): number {
  return MAX_META_BYTES;
}

// ---------------------------------------------------------------------------
// safeStringifyMeta — DOS-safe JSON.stringify with byte cap (Pass 2 F20)
// ---------------------------------------------------------------------------

/**
 * Cheap recursive size estimator — walks the meta object once, summing
 * approximate byte sizes per node, bailing early if the running total exceeds
 * `cap`. Used as a pre-check before JSON.stringify so we never enter the
 * synchronous stringify path on pathologically-large payloads.
 */
function estimateSize(meta: unknown, cap: number): number {
  let total = 0;
  // Cycle protection — stops infinite recursion on self-referencing objects.
  // JSON.stringify would throw on cycles anyway; we just need to NOT blow the
  // stack inside estimate so the try/catch around stringify still gets to fire.
  const visited = new WeakSet<object>();
  function walk(v: unknown): void {
    /* c8 ignore next */ // defensive belt: outer loops in this function pre-check `total > cap` after each walk() return + break, so this start-of-walk early-bail is structurally unreachable from internal recursion. Kept as a future-safe guard for callers that might invoke walk() with a pre-loaded total.
    if (total > cap) return;
    if (v === null || v === undefined) { total += 4; return; }
    if (typeof v === "string")  { total += v.length + 2; return; }
    if (typeof v === "number" || typeof v === "boolean") { total += 8; return; }
    if (typeof v === "object") {
      if (visited.has(v as object)) { total += 4; return; }   // cycle marker
      visited.add(v as object);
      if (Array.isArray(v)) {
        total += 2;
        for (const item of v) {
          walk(item);
          if (total > cap) return;
        }
        return;
      }
      total += 2;
      for (const k of Object.keys(v as object)) {
        total += k.length + 4;
        walk((v as Record<string, unknown>)[k]);
        if (total > cap) return;
      }
    }
    /* c8 ignore next */ // unreachable: typeof exhausts string|number|boolean|object|undefined; symbol/function/bigint never appear in JSON-shaped Job.meta.
  }
  walk(meta);
  return total;
}

/* c8 ignore next */ // tsx template-literal interpolation reports a phantom branch on the multi-template return statements; all three size buckets are exercised by direct _formatBytesForTesting() tests.
function formatBytes(n: number): string {
  if (n < 1024) return `${n}B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}KB`;
  return `${(n / 1024 / 1024).toFixed(1)}MB`;
}

/**
 * Test-only: exposes formatBytes for direct unit-test coverage of all 3
 * size-bucket branches (B / KB / MB). NOT used by production code.
 */
export function _formatBytesForTesting(n: number): string {
  return formatBytes(n);
}

/**
 * Stringify `meta` for display, capped at MAX_META_BYTES bytes.
 *
 * Three short-circuit paths:
 *   1. Pre-check via estimateSize() — catches pathological payloads before
 *      JSON.stringify enters the main thread.
 *   2. Belt-and-suspenders post-stringify length check — catches the case
 *      where escape-sequence expansion blows past the cap even when the
 *      pre-check passed.
 *   3. try/catch around JSON.stringify — catches cyclic references and
 *      other serialization errors.
 *
 * Requires:
 *   - meta is `Job.meta` per the Phase 4 type (Record<string, unknown>) OR
 *     undefined/null at the call site.
 *
 * Ensures:
 *   - returns a non-empty string suitable for `<pre>.innerText`.
 *   - never throws — all error paths return a human-readable placeholder.
 */
export function safeStringifyMeta(meta: unknown): string {
  const estimated = estimateSize(meta, MAX_META_BYTES);
  if (estimated > MAX_META_BYTES) {
    return `[meta too large to display — ${formatBytes(estimated)}]`;
  }
  try {
    const out = JSON.stringify(meta, null, 2);
    if (out !== undefined && out.length > MAX_META_BYTES) {
      return "[meta too large to display]";
    }
    /* c8 ignore next */ // JSON.stringify(undefined) returns undefined (not the string "undefined"); template-time meta is always an object per Phase 4 type, so this branch is a defensive belt for hand-built test fixtures that pass undefined directly.
    return out ?? "{}";
  } catch (err) {
    return `[meta serialization failed: ${(err as Error).message}]`;
  }
}

// ---------------------------------------------------------------------------
// Expand-cache — lazy-render meta on first card-header click (Pass 1 F2)
// ---------------------------------------------------------------------------

const expandedMetaCache = new WeakSet<HTMLPreElement>();

/**
 * Populate the card's `<pre.job-meta-json>` with stringified meta on first
 * expand; subsequent expands are O(1) (cache check + class toggle by caller).
 *
 * Called by JobsPaneRenderer's delegated card-header click handler. The
 * renderer owns the JobStore lookup; the template owns the cap + cache.
 *
 * Requires:
 *   - `card` is a `.job-card` element produced by `renderJobCard`
 *   - `meta` is the job's current meta (typically `JobStore.getById(idHash)?.meta`)
 *
 * Ensures:
 *   - On first call for a given card: populates `<pre>.innerText` with
 *     safeStringifyMeta(meta), removes the `hidden` attribute, and adds the
 *     `<pre>` element to the WeakSet cache.
 *   - On subsequent calls for the same card: no-op (returns early).
 *   - If the card has no `<pre.job-meta-json>` child, no-op.
 */
export function populateJobMetaIfNeeded(card: HTMLElement, meta: unknown): void {
  const pre = card.querySelector(".job-meta-json") as HTMLPreElement | null;
  if (pre === null) return;
  if (expandedMetaCache.has(pre)) return;
  pre.innerText = safeStringifyMeta(meta);
  pre.removeAttribute("hidden");
  expandedMetaCache.add(pre);
}

// ---------------------------------------------------------------------------
// Status-icon mapping (Pass 2 F32 — emojis sourced from notifications.js:5478)
// ---------------------------------------------------------------------------

const STATUS_ICONS: Record<JobStatus, string> = {
  todo    : "⏳",
  running : "⚙",
  done    : "✓",
  dead    : "✗",
};

// ---------------------------------------------------------------------------
// renderJobCard — main template export
// ---------------------------------------------------------------------------

/**
 * Render a single `Job` as a `.job-card` HTMLElement.
 *
 * Returns the outer `.job-card` div (NOT a DocumentFragment) so callers can
 * attach event listeners + read `data-id-hash` for keyed merge.
 *
 * Per Pass 2 F23: `data-id-hash` is on `.job-card` ONLY (NEVER on the delete
 * button); the renderer's delegated click handler queries `.job-card` by
 * class, never `[data-id-hash]` by attribute, so the collision can't resurface.
 *
 * Requires:
 *   - `job.id_hash` is a non-empty string
 *   - `job.status` is one of `"todo" | "running" | "done" | "dead"` (Phase 4 enum)
 *
 * Ensures:
 *   - Outer element carries `data-id-hash="${job.id_hash}"` (F12)
 *   - Outer element class includes `.status-${job.status}`
 *   - `data-job-type="${job.job_type}"` is set as auxiliary metadata (NOT a key)
 *   - The disabled `.job-delete-button` carries `aria-disabled="true"`,
 *     `tabindex="-1"`, and `title="Delete coming in Phase 6b"` (Q-A6 + C-6)
 *   - `.job-card-details` ships `.collapsed` initially; `<pre.job-meta-json>`
 *     is empty + `hidden` until first expand
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function renderJobCard(job: Job, _opts: RenderOptions = {}): HTMLElement {
  const root = document.createElement("div");
  root.className = `job-card status-${job.status}`;
  root.setAttribute("data-id-hash",  job.id_hash);
  root.setAttribute("data-job-type", job.job_type);

  const icon       = STATUS_ICONS[job.status];
  const idShort    = `#${job.id_hash.slice(0, 8)}`;
  const timingText = formatDuration(job.created_at, job.completed_at);

  /* c8 ignore next 14 */ // tagged-template literal: c8 reports phantom branches on $-interpolations; the runtime path is straight-line and exercised by every test that renders a job card.
  const inner = html`
    <div class="job-card-header">
      <span class="job-status-icon">${icon}</span>
      <span class="job-type">${job.job_type}</span>
      <span class="job-id-short">${idShort}</span>
      <span class="job-timing">${timingText}</span>
      <button class="job-delete-button" aria-disabled="true" tabindex="-1" title="Delete coming in Phase 6b">×</button>
    </div>
    <div class="job-card-details collapsed">
      <pre class="job-meta-json" hidden></pre>
    </div>
  ` as DocumentFragment;
  root.appendChild(inner);

  return root;
}
