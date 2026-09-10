/* c8 ignore next */ // tsx phantom-branch artifact on the file-header line.
// Multiplexer notification history window (2026-09-10, P0 5ebd2aff — Rick's
// ruling 1, "match legacy": the history-window picker comes back).
//
// Ports the legacy client's picker MODEL verbatim: the options and the stored
// value parsing (notifications.js:407-429), the effective query hours
// (notifications.js:19658-19666) and the display label (notifications.js:20551-20563).
// The storage key is the legacy client's RAW localStorage key, shared with it,
// so either client's last pick is the other's value — the same arrangement as
// the TTS preview slider (TtsPreviewSliderRenderer.ts LEGACY_TTS_FRACTION_KEY).
//
// Parity inventory: src/rnd/2026.09.10-mux-cc-notifications-accordion-parity.md

// The legacy client's raw key (notifications.js:408), shared with it.
export const HISTORY_WINDOW_KEY = "notifications_history_window";

// null → "All time" (no hours filter) · "today" → since local midnight · number → fixed hours.
export type HistoryWindow = number | "today" | null;

export interface HistoryWindowOption {
  label : string;
  hours : HistoryWindow;
}

// notifications.js:422-429 — labels, order and values verbatim.
export const HISTORY_WINDOW_OPTIONS: ReadonlyArray<HistoryWindowOption> = [
  { label: "Today",         hours: "today" },
  { label: "Last 24 hours", hours: 24 },
  { label: "Last 2 days",   hours: 48 },
  { label: "Last week",     hours: 168 },
  { label: "Last month",    hours: 720 },
  { label: "All time",      hours: null },
];

// Legacy's virgin default — notifications.js:420 (`parseInt( storedWindow ) || 48`).
// The 2026-06-11 ruling chose the same 48 h rolling window as a SILENT default
// with no selector; Rick's 2026-09-10 ruling 1 restores the selector and keeps
// 48 h as what a browser with no stored pick sees.
export const DEFAULT_HISTORY_WINDOW_HOURS = 48;

// The senders-visible response fills the strip, the sender records, and the
// list of senders whose history loads. The strip only has icons for senders
// inside the window the server was asked for, while the history list applies
// the picker's window itself, in the browser (NotificationStore.hydrateHistory).
// So the fetch may be wider than the picker but never narrower than this, or
// "Today" just after midnight (1 h) would empty the focus bar.
export const SENDERS_VISIBLE_MIN_HOURS = 48;

/**
 * The senders-visible path for a user, with an hours window.
 *
 * Without `hours` the server looks up two persona badges for every sender it
 * has ever seen: measured 2026-09-10 at 51.9 s for Rick's 5,180 senders, with
 * the dev server's event loop blocked the whole time. `?hours=48` took 1.0 s
 * (src/rnd/2026.09.10-senders-visible-stalls-dev-server.md).
 *
 * Requires:
 *   - email is a non-empty string
 * Ensures:
 *   - hours null ("All time") → no `hours` param, the same as legacy
 *   - otherwise `?hours=` the larger of hours and SENDERS_VISIBLE_MIN_HOURS
 *   - the email is URI-encoded
 */
export function sendersVisiblePath(email: string, hours: number | null): string {
  const base = `/api/notifications/senders-visible/${encodeURIComponent(email)}`;
  return hours === null ? base : `${base}?hours=${String(Math.max(hours, SENDERS_VISIBLE_MIN_HOURS))}`;
}

/**
 * Parse the legacy client's stored window value.
 *
 * Requires:
 *   - raw is the string under HISTORY_WINDOW_KEY, or null when absent
 * Ensures:
 *   - "all" and "" → null (legacy also migrates the pre-fix empty string)
 *   - "today" → "today"
 *   - anything else → its leading integer, or DEFAULT_HISTORY_WINDOW_HOURS when
 *     that integer is missing or zero (legacy `parseInt( raw ) || 48`)
 */
export function parseStoredHistoryWindow(raw: string | null): HistoryWindow {
  if (raw === "all" || raw === "") return null;
  if (raw === "today") return "today";
  return Number.parseInt(raw ?? "", 10) || DEFAULT_HISTORY_WINDOW_HOURS;
}

/**
 * Serialize a window for HISTORY_WINDOW_KEY (legacy `hours === null ? 'all' : hours.toString()`).
 *
 * Ensures:
 *   - null → "all"; "today" → "today"; a number → its decimal string
 *   - parseStoredHistoryWindow(serializeHistoryWindow(w)) === w for every option
 */
export function serializeHistoryWindow(w: HistoryWindow): string {
  return w === null ? "all" : String(w);
}

/**
 * The hours to send on a query (legacy getEffectiveHoursForQuery).
 *
 * Requires:
 *   - now is the current local time
 * Ensures:
 *   - null → null (the caller omits the `hours` param entirely)
 *   - "today" → whole hours since local midnight, rounded up, never below 1
 *   - a number → that number
 */
export function effectiveHoursForQuery(w: HistoryWindow, now: Date): number | null {
  if (w === null) return null;
  if (w === "today") {
    const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    return Math.max(1, Math.ceil((now.getTime() - midnight.getTime()) / 3_600_000));
  }
  return w;
}

/**
 * The picker's display label (legacy getFilterLabel).
 *
 * Ensures:
 *   - an option's own label when the window is one of HISTORY_WINDOW_OPTIONS
 *   - "Last N hours" for any other number
 */
export function historyWindowLabel(w: HistoryWindow): string {
  const option = HISTORY_WINDOW_OPTIONS.find(o => o.hours === w);
  return option !== undefined ? option.label : `Last ${String(w)} hours`;
}
