/* c8 ignore next */ // tsx phantom-branch artifact on file-header line (TypeScript module-init transpile artifact in c8's source-map view; no actual code on this line).
// Multiplexer Phase 5 — sender card template (`.sender-card`).
//
// Per Q-C: legacy class names verbatim — `.sender-card`, `.sender-card-header`,
// `.sender-card-dates`, `.sender-active-indicator`, `.persona-badge`,
// `.sender-new-count`, `.sender-message-count`, `.sender-last-activity`.
//
// Persona color flows through the `--persona-color` CSS custom property via
// `element.style.setProperty()` POST-render — design doc § DOM grouping
// explicitly avoids inline `style="${...}"` interpolation in the helper.
// Per F12: the outer element carries `data-id-hash="${sender.sender_id}"`.
//
// Date grouping is the renderer's responsibility (sender → date → messages).
// `renderSenderCard` accepts a list of notifications already filtered to this
// sender; it groups by `formatDateKey(ts)` internally.

import { html } from "../html";
import { keyedListMerge } from "../dom";
import { formatDateKey, formatHM } from "../time";
import { renderDateAccordion } from "./dateAccordion";
import { slugifySenderId } from "./slugify";
import type { PredictionVoteIntegration } from "./predictionVoteControls";
import type { SenderRecord, Notification } from "../../shared/types";

interface RenderOptions {
  appTimezone?: string;
  // WS4/G4 (2026-06-22): injectable wall-clock for the activity-recency status
  // glyph (`.sender-status`). Defaults to Date.now() at the call site; tests
  // pass a fixed value so `senderStatusGlyph` stays deterministic.
  now?: number;
  // WP14 (F8) — forwarded verbatim to renderDateAccordion → renderNotificationItem
  // (the prediction-vote orchestrator bridge). Absent in the parity harness.
  predictionVote?: PredictionVoteIntegration;
}

/**
 * Render a `.sender-card` for one sender + their notifications.
 *
 * Requires:
 *   - `sender` has `sender_id`, `display_name`
 *   - `notifications` is the list of messages from this sender (already
 *     filtered upstream); may be empty (renders chrome only)
 *
 * Ensures:
 *   - Returned element carries `data-id-hash="${sender.sender_id}"` (F12)
 *     AND `data-sender-id="${sender.sender_id}"` (legacy attribute name)
 *   - Voice-persona color applied via `style.setProperty("--persona-color", ...)`
 *     when sender carries a persona — NO inline `style=` interpolation
 *   - Notifications grouped by date, descending; date accordions carry their
 *     own keyed-merge IDs for re-render stability
 */
export function renderSenderCard(
  sender: SenderRecord,
  notifications: ReadonlyArray<Notification>,
  opts: RenderOptions = {},
): HTMLElement {
  const root = document.createElement("div");
  root.className = "sender-card";
  root.setAttribute("data-id-hash",  sender.sender_id);
  root.setAttribute("data-sender-id", sender.sender_id);
  // Worker-badge silencing (Rick 2026-06-24, gap list §6 Decision A/B): mark
  // managed-worker cards so the shared sheet (notifications-surface.css, linked
  // by BOTH clients) hides the .sender-new-count number and renders a faint
  // activity dot via `.sender-stats-group::after`. is_worker is set in
  // SenderStore from the same manager_persona signal SessionStripStore reads.
  if (sender.is_worker === true) {
    root.setAttribute("data-worker", "true");
  }

  const persona = sender.voice_persona;
  if (persona !== undefined) {
    root.style.setProperty("--persona-color", persona.color);
    // CSS-parity 2026-06-17: the header gradient, card box-shadow ring, and
    // `.sender-message.incoming` gradient all consume `--persona-color-rgb`
    // (an "r, g, b" triplet inside `rgb(...)/rgba(...)`). Only `--persona-color`
    // (hex) was being set, so every persona-tinted surface silently fell back
    // to the neutral default. Derive + set the triplet so the tint engages.
    const rgbTriplet = hexToRgbTriplet(persona.color);
    if (rgbTriplet !== null) {
      root.style.setProperty("--persona-color-rgb", rgbTriplet);
    }
  }

  // Header chrome. Persona-badge class is computed before template
  // interpolation because the helper only supports whole-attribute
  // interpolation (not mid-attribute concatenation).
  //
  // Phase 6c Node A Step A1 (2026-05-19): the badge was renamed from
  // `.persona-badge` (span) to `.sender-persona-badge` (button) per
  // F-Arnold-3 (rule-rename-in-place). The button carries `popovertarget`
  // pointing at the matching persona-popover modal id (constructed via the
  // same `slugifySenderId` helper personaModal.ts uses for the popover's
  // `id` attribute — single source of truth per Recon-A5).
  //
  // Lane-2 skin revert (2026-07-02, plan 06 §5, Rick Q2 full-revert): the R4
  // glyph-only badge is reverted back to the legacy inline icon + NAME — the
  // button now emits `.persona-badge-icon` + `.persona-badge-name` children
  // (legacy notifications.js:10818-10823; VoicePersona has no display_name, so
  // the label is `persona.name`). The button + `popovertarget` are RETAINED:
  // the popover stays an on-demand affordance, not the sole name surface. Child
  // styling lives mux-side in notifications-list.css (byte-faithful from legacy
  // notifications.css:1765-1771); the shared union rule already supplies the
  // inline-flex + gap layout so icon and name lay out horizontally.
  //
  // F-Arnold-4: when sender has NO voice_persona, the badge element is
  // omitted entirely (not rendered as empty/stub). The `if (persona !==
  // undefined)` guard covers this — `personaBadge` stays null and the
  // header template's `${personaBadge}` interpolation skips it.
  let personaBadge: DocumentFragment | null = null;
  if (persona !== undefined) {
    const badgeClass    = persona.borrowed ? "sender-persona-badge borrowed" : "sender-persona-badge";
    const popoverTarget = `persona-popover-${slugifySenderId(sender.sender_id)}`;
    personaBadge = html`<button class="${badgeClass}" type="button" popovertarget="${popoverTarget}"><span class="persona-badge-icon">${persona.icon}</span><span class="persona-badge-name">${persona.name}</span></button>` as DocumentFragment;
  }

  const lastActivityText = sender.last_active_ts > 0
    ? `Last: ${formatHM(sender.last_active_ts, opts.appTimezone)}`
    : "";

  // WS4/G4 (2026-06-22) — CC-session sender-card HEADER CHROME (Category-3
  // structure parity; legacy notifications.js:13523-13542). Legacy emits a
  // richer header than the mux did: a status dot, the project label, a session
  // block (id + copy + gist + editable name), a delete button and a collapse
  // toggle. Re-expressed here in mux idioms: NO inline onclick / globals — the
  // copy / gist / rename / delete / toggle handlers are wired via delegated
  // listeners in NotificationsListRenderer. All values come from the typed
  // SenderRecord (no senderId string-parsing for content).
  //
  // RENAME SEAM CLOSED (per notifications-list.css:81-84 "→ WS2/WS4"): the
  // positional project-label slot was the mux-only `.sender-display-name`; it
  // is renamed to the legacy-verbatim `.sender-project-name` so structure
  // matches (content still `display_name` — a Category-4 content choice).
  const statusGlyph = senderStatusGlyph(sender.last_active_ts, opts.now ?? Date.now());

  // Session block renders only for claude.code sessions (sender_id carries a
  // `#<sessionHash>`); persona-less external advisories (no `#`) render the
  // header WITHOUT it, mirroring legacy (parseSenderId → sessionId null).
  //
  // FLAG (class-name discrepancy, raised to Rachel/oracle): the brief lists
  // `.sender-session-id-copy`; legacy emits `.sender-session-copy copy-btn`
  // (notifications.js:13457). Emitting legacy-verbatim per Q-C ("legacy class
  // names verbatim"); revisit if the oracle contract expects `-id-copy`.
  //
  // `.sender-session-name` shows the session name/topic (R5, 2026-07-01):
  // SenderRecord.session_name is populated from `session_topic` control
  // notifications (SenderStore, localStorage-mirrored) — mirrors legacy
  // `${sessionName || ''}` (notifications.js refreshSessionNameDisplay). Empty
  // string when no name has arrived. (Manual click-to-rename — R5b — deferred.)
  //
  // VOICE-INPUT ROW (F5 lane, 2026-06-22 — Rick-ratified MATCH-LEGACY rebuild):
  // CC sessions ALSO emit the legacy inline `.cc-voice-input` > `.cc-voice-input-row`
  // (conv-mode toggle + mic + text input + send), positioned BETWEEN the header
  // and `.sender-card-dates` (legacy notifications.js:13504-13521). Mux idiom: NO
  // inline onclick — SenderCardRecorderRenderer wires all four via delegated
  // clicks. This is STATIC structure so the component-isolation parity harness
  // (which renders renderSenderCard alone, NO recorder mount) sees the row; the
  // recorder renderer adds only behavior + recording-state, operating on these
  // existing elements. The single shared `sessionHash` feeds both the session
  // block and the voice row.
  const isCCSession = sender.sender_id.includes("#");
  let sessionBlock:  DocumentFragment | null = null;
  let voiceInputRow: DocumentFragment | null = null;
  if (isCCSession) {
    /* c8 ignore next */ // `?? ""` is a noUncheckedIndexedAccess type-guard; isCCSession guarantees a '#', so split("#")[1] is always a string (possibly "" for a trailing '#') — the ?? branch is unreachable at runtime.
    const sessionHash = sender.sender_id.split("#")[1] ?? "";
    sessionBlock = html`
      <span class="sender-session-copy copy-btn" role="button" tabindex="0" title="Copy session ID">📋</span>
      <button class="sender-gist-btn" type="button" title="Generate smart gist from conversation">✨</button>
      <span class="sender-session-name" role="button" tabindex="0" title="Click to rename">${sender.session_name ?? ""}</span>
    ` as DocumentFragment;
    voiceInputRow = renderVoiceInputRow(sender, sessionHash);
  }

  const headerFrag = html`
    <div class="sender-card-header" role="button" tabindex="0">
      <span class="sender-active-indicator">●</span>
      <span class="sender-status">${statusGlyph}</span>
      <span class="sender-project-name">${sender.display_name || sender.sender_id}</span>
      ${sessionBlock}
      <span class="sender-stats-group">
        ${personaBadge}
        ${sender.unread_count > 0 && sender.is_worker !== true
          ? html`<span class="sender-new-count">${sender.unread_count}</span>`
          : null}
        <span class="sender-message-count">(${notifications.length})</span>
        <span class="sender-last-activity">${lastActivityText}</span>
      </span>
      <button class="sender-delete-btn" type="button" title="Delete all">×</button>
      <span class="sender-toggle">▼</span>
    </div>
    ${voiceInputRow}
    <div class="sender-card-dates"></div>
  ` as DocumentFragment;
  root.appendChild(headerFrag);

  // Bug#1 — elect ONE head per progress group, then pre-filter the non-head
  // members OUT of the flat render list. Without this, EVERY member of a
  // progress group renders its own `.progress-group-head` (the 176× bug). The
  // election runs on the FULL per-sender list BEFORE date-grouping, so a group
  // whose members straddle a date boundary still elects exactly ONE head (the
  // cross-date multi-head hazard). Election is deterministic — the first-arrived
  // (earliest `ts`) member per `progress_group_id`, ties broken by `id_hash` —
  // so the same head is chosen on every re-render. Non-heads are removed HERE,
  // not suppressed downstream: `keyedListMerge.create` is typed
  // `(entry) => Element` and cannot return null. The collapsed members still
  // surface via `NotificationsListRenderer.buildHistoryFragment`, which reads the
  // full notification store (not this filtered render list).
  //
  // INVARIANT (verified): a `progress_group_id` is single-sender by construction
  // — its purpose is to update ONE in-place DOM element (notifications.py §539),
  // and each group is emitted by one job/session (e.g. deep_research's single
  // `research_group_id`) so every member resolves to the same `sender_id`. Hence
  // this per-sender election equals the global result, and buildHistoryFragment's
  // global `progress_group_id` filter consumes THIS elected head (via the single
  // rendered `.progress-group-head`) by construction.
  const headByGroup = new Map<string, Notification>();
  for (const n of notifications) {
    const gid = n.progress_group_id;
    if (typeof gid !== "string" || gid.length === 0) continue;
    const cur = headByGroup.get(gid);
    if (cur === undefined || n.ts < cur.ts || (n.ts === cur.ts && n.id_hash < cur.id_hash)) {
      headByGroup.set(gid, n);
    }
  }
  const renderList = notifications.filter(n => {
    const gid = n.progress_group_id;
    if (typeof gid !== "string" || gid.length === 0) return true;   // non-progress row — always keep
    return headByGroup.get(gid)!.id_hash === n.id_hash;             // progress row — keep only the elected head
  });

  // Group notifications by date key.
  const datesContainer = root.querySelector(".sender-card-dates") as HTMLElement;
  const groupedByDate = groupByDateKey(renderList, opts.appTimezone);

  keyedListMerge({
    parent  : datesContainer,
    entries : groupedByDate.map(g => ({ idHash: g.dateKey, group: g })),
    create  : (e) => renderDateAccordion(e.group.dateKey, e.group.items, opts),
  });

  return root;
}

/**
 * Render the legacy inline `.cc-voice-input` > `.cc-voice-input-row` for a CC
 * session (F5 lane, MATCH-LEGACY rebuild). Legacy-verbatim markup
 * (notifications.js:13504-13521) in mux idiom (NO inline onclick — the
 * SenderCardRecorderRenderer wires the conv-mode toggle / mic / send via
 * delegated clicks and drives recording-state on these existing elements):
 *   - `.sender-conversation-mode-btn` (+ `is-active` when conversation mode is on),
 *     `data-session-id`, glyph 🔊 (active) / 🤭 (idle).
 *   - `.stt-button.cc-session-stt`, id `cc-session-stt-<hash>`, 🎤.
 *   - `<input type="text" class="cc-session-msg-input">`, id `cc-session-input-<hash>`.
 *   - `.response-submit-button.cc-session-send`, id `cc-session-send-<hash>`.
 *
 * The `id` attributes are PRE-COMPOSED whole strings because the `html` helper
 * only interpolates whole attribute values (its ATTR regex matches `attr="` at a
 * segment end — mid-attribute `id="prefix-${x}"` concatenation is NOT supported).
 *
 * Requires:
 *   - `sessionHash` is the CC session's 8-char hash (sender_id after the `#`).
 * Ensures:
 *   - Returns a `.cc-voice-input` fragment carrying `data-session-hash` +
 *     `data-sender-id` (the recorder's click-delegation + state keys), with the
 *     conv-mode button reflecting `sender.conversation_mode_active`.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line (TypeScript return-type erasure produces a fake branch in c8's source-map view; the body is always entered when called).
function renderVoiceInputRow(sender: SenderRecord, sessionHash: string): DocumentFragment {
  const active       = sender.conversation_mode_active === true;
  const convBtnClass = active ? "sender-conversation-mode-btn is-active" : "sender-conversation-mode-btn";
  const convIcon     = active ? "🔊" : "🤭";
  const convTitle    = active
    ? "Conversation mode ON — click to silence (quiet)"
    : "Conversation mode OFF — click to enable (speakerphone)";
  const sttId   = `cc-session-stt-${sessionHash}`;
  const inputId = `cc-session-input-${sessionHash}`;
  const sendId  = `cc-session-send-${sessionHash}`;
  return html`
    <div class="cc-voice-input" data-session-hash="${sessionHash}" data-sender-id="${sender.sender_id}">
      <div class="cc-voice-input-row">
        <button type="button" class="${convBtnClass}" data-session-id="${sessionHash}" title="${convTitle}">${convIcon}</button>
        <button type="button" class="stt-button cc-session-stt" id="${sttId}" title="Click to record (30s max, ESC to cancel)">🎤</button>
        <input type="text" class="cc-session-msg-input" id="${inputId}" placeholder="Send voice/text to CC session..." />
        <button type="button" class="response-submit-button cc-session-send" id="${sendId}">Send</button>
      </div>
    </div>
  ` as DocumentFragment;
}

/**
 * Activity-recency status glyph for the `.sender-status` header element —
 * mirrors legacy `getSenderStatusIndicator` (notifications.js:13169-13176).
 *
 * Requires:
 *   - `lastActiveTs` is a ms-epoch timestamp (0 / negative ⇒ "no activity")
 *   - `now` is a ms-epoch wall-clock (injected so the result is deterministic)
 * Ensures:
 *   - returns "🟢" when active within the last hour
 *   - returns "🟡" when active within the last day
 *   - returns "⚪" when inactive (>24h) or no activity recorded
 */
export function senderStatusGlyph(lastActiveTs: number, now: number): string {
  if (lastActiveTs <= 0) return "⚪";
  const hoursSince = (now - lastActiveTs) / 3_600_000;
  if (hoursSince < 1) return "🟢";
  if (hoursSince < 24) return "🟡";
  return "⚪";
}

interface DateGroup {
  dateKey : string;
  items   : Notification[];
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line (TypeScript optional-param + return-type erasure produces a fake branch).
function groupByDateKey(notifications: ReadonlyArray<Notification>, appTimezone?: string): DateGroup[] {
  const buckets = new Map<string, Notification[]>();
  for (const n of notifications) {
    const key = formatDateKey(n.ts, appTimezone);
    let arr = buckets.get(key);
    if (arr === undefined) {
      arr = [];
      buckets.set(key, arr);
    }
    arr.push(n);
  }
  // Sort each bucket newest-first (legacy `.date-accordion-messages` order).
  for (const arr of buckets.values()) {
    arr.sort((a, b) => b.ts - a.ts);
  }
  // Sort dates descending (newest date at top — legacy `.sender-card-dates` order).
  const groups: DateGroup[] = [];
  for (const [dateKey, items] of buckets) {
    groups.push({ dateKey, items });
  }
  groups.sort((a, b) => b.dateKey.localeCompare(a.dateKey));
  return groups;
}

/**
 * Convert a CSS hex color to an "r, g, b" triplet string for use inside
 * `rgb(...)` / `rgba(...)`. Accepts `#RGB`, `#RRGGBB`, or the same without the
 * leading `#`. Returns null for unparseable input so the caller skips setting
 * `--persona-color-rgb` (leaving the stylesheet's neutral fallback in place).
 *
 * Requires:
 *   - `hex` is a string
 * Ensures:
 *   - returns "r, g, b" with 0-255 decimal channels for valid 3/6-digit hex
 *   - returns null for any input that is not a valid 3/6-digit hex color
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line (TypeScript return-type erasure produces a fake branch in c8's source-map view; the body is always entered when called — same convention as groupByDateKey above).
export function hexToRgbTriplet(hex: string): string | null {
  let h = hex.trim();
  if (h.startsWith("#")) h = h.slice(1);
  // Expand shorthand #RGB → RRGGBB (each char doubled; avoids indexed access
  // for strict noUncheckedIndexedAccess).
  if (h.length === 3) {
    h = h.replace(/./g, (c) => c + c);
  }
  if (h.length !== 6 || /[^0-9a-fA-F]/.test(h)) return null;
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `${r}, ${g}, ${b}`;
}
