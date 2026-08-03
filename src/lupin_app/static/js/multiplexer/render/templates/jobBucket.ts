/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 6a — jobs-bucket template (`.jobs-bucket`).
//
// Per Pass 1 F1: each bucket renders its own per-bucket section with header +
// (collapsible) cards container. Default expansion per Q-A2 ratification:
// todo + running expanded; done + dead + history collapsed.
//
// Per Q-A1 (strict ratification): when a bucket is empty, render a per-bucket
// "No <name> jobs." div under the header. NO global "all empty" fallback;
// 5 empty buckets render 5 empty-state divs.
//
// Per Pass 2 F30 (WAI-ARIA 1.2 §5.4 contract for role="button"): the bucket
// header gets a keydown handler for Enter + Space (preventDefault on Space to
// stop page scroll). aria-expanded reflects the cards-container collapsed
// state and updates on every toggle. aria-controls references the cards
// container's id.
//
// Per design § "Render strategy": the cards container holds the keyed list
// of `.job-card` elements; the JobsPaneRenderer feeds it via keyedListMerge
// keyed by `data-id-hash`.

import { html } from "../html";
import { keyedListMerge } from "../dom";
import { renderJobCard } from "./jobCard";
import type { Job, JobBucket } from "../../shared/types";

interface RenderOptions {
  appTimezone?: string;
  // W3/W4 — history-bucket controls (consumed ONLY when bucketName === "history";
  // the renderer computes them from JobStore + passes them on every render). Other
  // buckets ignore them.
  //   - historyWindowDays : the selected time-window; `undefined` = all-time ("all"
  //     option). The renderer always passes it for the history bucket.
  //   - historyLoadedCount / historyTotalCount : Load-More gate (button shown iff
  //     loaded < total) + the history count badge (reflects the server total).
  historyWindowDays?  : number;
  historyLoadedCount? : number;
  historyTotalCount?  : number;
}

// Default-expansion table per Pass 1 F1 (derived from Q-A2):
const DEFAULT_EXPANDED: Record<JobBucket, boolean> = {
  todo    : true,
  running : true,
  done    : false,
  dead    : false,
  history : false,
};

// W3 — history time-window select options (legacy #history-time-window: 1/7/14/
// 30 days + all). `value` is the query `days` param; "all" maps to all-time
// (days omitted). Verbatim legacy set per plan 04 §W3.
const HISTORY_WINDOW_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "1",   label: "Last 24h" },
  { value: "7",   label: "Last 7 days" },
  { value: "14",  label: "Last 14 days" },
  { value: "30",  label: "Last 30 days" },
  { value: "all", label: "All time" },
];

// ---------------------------------------------------------------------------
// renderJobBucket — main template export
// ---------------------------------------------------------------------------

/**
 * Render a single jobs bucket as a `<section>` HTMLElement.
 *
 * Returns the outer `<section>` element so the JobsPaneRenderer can attach
 * delegated event listeners + read `data-bucket` for keyed-merge tracking
 * across the 5-bucket layout.
 *
 * Self-contained widget: this function attaches its OWN click + keydown
 * handlers to `.jobs-bucket-header` so the WAI-ARIA contract for
 * `role="button"` is satisfied without requiring the renderer to
 * double-bind. The renderer is responsible for delegated `.job-card-header`
 * clicks (a sibling concern).
 *
 * Requires:
 *   - `bucketName` is one of `"todo" | "running" | "done" | "dead" | "history"`
 *   - `jobs` is the (possibly empty) ordered list of jobs in this bucket
 *
 * Ensures:
 *   - Outer element carries `data-bucket="${bucketName}"` and class
 *     `.jobs-bucket .jobs-bucket-${bucketName}`
 *   - Header is `role="button" tabindex="0"` with `aria-expanded` reflecting
 *     the cards-container collapsed state; `aria-controls` references the
 *     cards container's unique id
 *   - Empty bucket → renders `<div class="jobs-bucket-empty">No ${bucketName} jobs.</div>`
 *   - Non-empty bucket → renders cards via `keyedListMerge` keyed by `data-id-hash`
 *   - Header click toggles `.collapsed` on the cards container + flips
 *     `aria-expanded`; keydown(Enter or Space) does the same (Space
 *     `preventDefault`s the page-scroll behavior)
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function renderJobBucket(
  bucketName: JobBucket,
  jobs: ReadonlyArray<Job>,
  opts: RenderOptions = {},
): HTMLElement {
  const initiallyExpanded = DEFAULT_EXPANDED[bucketName];
  const cardsContainerId  = `bucket-${bucketName}-content`;

  const root = document.createElement("section");
  root.className = `jobs-bucket jobs-bucket-${bucketName}`;
  root.setAttribute("data-bucket", bucketName);
  // For keyed-merge participation across all 5 buckets in the parent container.
  root.setAttribute("data-id-hash", `bucket:${bucketName}`);

  /* c8 ignore next 11 */ // tagged-template literal: c8 reports phantom branches on $-interpolations; the runtime path is straight-line and exercised by every test that renders a bucket.
  const headerFrag = html`
    <header class="jobs-bucket-header"
            role="button"
            tabindex="0"
            aria-expanded="${initiallyExpanded ? "true" : "false"}"
            aria-controls="${cardsContainerId}">
      <span class="jobs-bucket-label">${bucketName}</span>
      <span class="jobs-bucket-count">(${jobs.length})</span>
      <span class="jobs-bucket-toggle">${initiallyExpanded ? "▼" : "▶"}</span>
    </header>
  ` as DocumentFragment;
  root.appendChild(headerFrag);

  const header = root.querySelector(".jobs-bucket-header") as HTMLElement;

  // W2 (plan 04 §W2) — per-bucket delete-all 🗑. Present on EVERY bucket header
  // (live buckets + history). Built via direct DOM ops (not html``) so the
  // `data-bucket` value threads cleanly. The renderer's root-delegated
  // `.queue-delete-all-btn` handler owns the confirm + DELETE; this template
  // only PLACES the control. Inserted before the chevron so the chevron stays
  // the rightmost affordance.
  const toggleSpan   = header.querySelector(".jobs-bucket-toggle") as HTMLElement;
  const deleteAllBtn = document.createElement("button");
  deleteAllBtn.type        = "button";
  deleteAllBtn.className    = "queue-delete-all-btn";
  deleteAllBtn.textContent  = "🗑";
  deleteAllBtn.setAttribute("data-bucket", bucketName);
  deleteAllBtn.title = `Delete all ${bucketName} jobs`;
  deleteAllBtn.setAttribute("aria-label", `Delete all ${bucketName} jobs`);
  header.insertBefore(deleteAllBtn, toggleSpan);

  // W3 (plan 04 §W3) — history time-window <select> + count-badge-reflects-total.
  // History only: the renderer's root-delegated `change` handler owns the refetch;
  // this template just PLACES the control with the current window selected. The
  // header target-guard (below) keeps a click on it from toggling the bucket.
  if (bucketName === "history") {
    const select = document.createElement("select");
    select.className = "history-time-select";
    select.setAttribute("aria-label", "History time window");
    const selectedValue = opts.historyWindowDays === undefined ? "all" : String(opts.historyWindowDays);
    for (const o of HISTORY_WINDOW_OPTIONS) {
      const optionEl = document.createElement("option");
      optionEl.value       = o.value;
      optionEl.textContent = o.label;
      select.appendChild(optionEl);
    }
    // Set the current window by value AFTER the options are attached (reliable
    // across DOM impls; per-option `.selected` before append is quirky in some).
    select.value = selectedValue;
    header.insertBefore(select, deleteAllBtn);
    // Count badge reflects the server total for the window (plan §W3), when known
    // (falls back to the loaded length the base header already rendered).
    if (opts.historyTotalCount !== undefined) {
      const countEl = header.querySelector(".jobs-bucket-count") as HTMLElement;
      countEl.textContent = `(${opts.historyTotalCount})`;
    }
  }

  if (jobs.length === 0) {
    /* c8 ignore next 4 */ // tagged-template literal: same phantom-branch caveat as the header above.
    const emptyFrag = html`
      <div class="jobs-bucket-empty">No ${bucketName} jobs.</div>
    ` as DocumentFragment;
    root.appendChild(emptyFrag);
  } else {
    // Build the cards container via direct DOM ops — html`` can't concatenate
    // static strings with interpolations inside an attribute value (the
    // ATTR_NAME_REGEX requires the segment to END with `attr="`).
    const cardsContainer = document.createElement("div");
    cardsContainer.id        = cardsContainerId;
    cardsContainer.className = initiallyExpanded ? "jobs-bucket-cards" : "jobs-bucket-cards collapsed";
    root.appendChild(cardsContainer);

    // W5 — terminal cards (dead bucket + history) get the retry ↻ affordance.
    const retryable = bucketName === "dead" || bucketName === "history";
    keyedListMerge({
      parent  : cardsContainer,
      entries : jobs.map(j => ({ idHash: j.id_hash, job: j })),
      create  : (e) => renderJobCard(e.job, { appTimezone: opts.appTimezone, retryable }),
    });
  }

  // W4 (plan 04 §W4) — history Load-More affordance. History only, shown iff
  // fewer rows are loaded than the server total for the window. Sits AFTER the
  // cards (outside the keyed cards container so keyedListMerge never sees it).
  // The renderer's root-delegated `.history-load-more` click owns the append.
  if (bucketName === "history") {
    const loaded = opts.historyLoadedCount ?? 0;
    const total  = opts.historyTotalCount ?? 0;
    if (loaded < total) {
      const loadMore = document.createElement("button");
      loadMore.type        = "button";
      loadMore.className    = "history-load-more";
      loadMore.textContent  = "Load more";
      loadMore.setAttribute("aria-label", "Load more history");
      root.appendChild(loadMore);
    }
  }

  // Self-contained header handlers — F30 keyboard contract.
  //
  // W2 — a click/keydown on an interactive header control (the delete-all 🗑,
  // and, once W3/W4 land, the time-window <select> + Load-More) must NOT toggle
  // the bucket collapse. The header listener is attached DIRECTLY to the header,
  // so it fires during bubbling BEFORE the event reaches root — a root-level
  // stopPropagation cannot un-fire it. Guarding on the event target is the
  // correct mechanism (mirrors the sender-card-header button-guard); the
  // control's own delegated handler on root still runs the action, and native
  // <button>/<select> keyboard activation is left to the control itself.
  header.addEventListener("click", (e: Event) => {
    const target = e.target as Element | null;
    /* c8 ignore next */ // defensive: browser-dispatched clicks always carry a target.
    if (target === null) return;
    if (target.closest("button, select") !== null) return;
    toggleBucket(root);
  });
  header.addEventListener("keydown", (e: Event) => {
    const ke     = e as KeyboardEvent;
    const target = ke.target as Element | null;
    /* c8 ignore next */ // defensive: keydown events always carry a target.
    if (target === null) return;
    if (target.closest("button, select") !== null) return;
    if (ke.key === "Enter" || ke.key === " ") {
      ke.preventDefault();   // Space else scrolls the page
      toggleBucket(root);
    }
  });

  return root;
}

// ---------------------------------------------------------------------------
// toggleBucket — header click/keydown handler body
// ---------------------------------------------------------------------------

/**
 * Toggle a bucket's collapsed state + sync aria-expanded + chevron text.
 *
 * Idempotent on the cards container: if the bucket is empty (no cards
 * container exists), the header still toggles aria-expanded for consistency
 * — empty-state divs are not collapsible but the header click is a visual
 * acknowledgment.
 *
 * Requires:
 *   - `root` is a `.jobs-bucket` element produced by `renderJobBucket`
 *
 * Ensures:
 *   - On non-empty bucket: `.jobs-bucket-cards` toggles its `.collapsed` class
 *   - In all cases: `.jobs-bucket-header[aria-expanded]` flips true ↔ false
 *   - `.jobs-bucket-toggle` text flips ▼ ↔ ▶
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
function toggleBucket(root: HTMLElement): void {
  const header = root.querySelector(".jobs-bucket-header") as HTMLElement;
  const cards  = root.querySelector(".jobs-bucket-cards") as HTMLElement | null;
  const toggle = root.querySelector(".jobs-bucket-toggle") as HTMLElement;

  const wasExpanded = header.getAttribute("aria-expanded") === "true";
  const nowExpanded = !wasExpanded;

  header.setAttribute("aria-expanded", nowExpanded ? "true" : "false");
  toggle.textContent = nowExpanded ? "▼" : "▶";
  if (cards !== null) {
    cards.classList.toggle("collapsed", !nowExpanded);
  }
}
