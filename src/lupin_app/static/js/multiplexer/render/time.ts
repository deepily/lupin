/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 5 — time formatters.
//
// Per D-H ratification 2026-05-05: `formatCountdown(ms)` is a PURE formatter.
// Input is pre-corrected ms from `ActionRequiredStore` (`:157, :302, :347`
// already apply server-clock offset). Output is zero-padded MM:SS string. NO
// `Date.now()` access, NO offset math, NO global state. Renderer's tick
// handler can call this idempotently without re-applying the store's offset.
//
// `formatHM(ts)` ports `getLocalTimeDisplay` logic from
// `notifications.js:10107-10121` (D-J corrected citation).
//
// `formatDateKey(ts)` ports `getDateString` + `extractDateFromTimestamp` from
// `notifications.js:10068-10074` + `:10084-10098` (D-J corrected citation).
// `appTimezone`-awareness reuses the legacy timezone resolution path; in the
// absence of a configured server timezone, every formatter shows UTC and the
// clock formatters label it UTC. The browser's own zone is never used.

/**
 * Return the zone every time display uses: the server zone, else UTC.
 *
 * Requires:
 *   - `appTimezone` is an IANA zone name, or empty / null / undefined when the server sent none
 *
 * Ensures:
 *   - returns `appTimezone` when it is non-empty, else "UTC"
 */
export function displayZone(appTimezone?: string | null): string {
  return appTimezone || "UTC";
}

/**
 * Return the label that marks a displayed time as UTC.
 *
 * Ensures:
 *   - returns "" when a server zone is in use, else " UTC"
 */
export function zoneLabel(appTimezone?: string | null): string {
  return appTimezone ? "" : " UTC";
}

/**
 * Format the time of day of a date in the display zone, labelled when that zone is UTC.
 *
 * Requires:
 *   - `date` is a valid Date; `locale` and `options` are as for `toLocaleTimeString`
 *
 * Ensures:
 *   - the formatter's own `timeZone` option is always the display zone
 */
export function formatClock(
  date        : Date,
  appTimezone?: string | null,
  locale?     : string,
  options     : Intl.DateTimeFormatOptions = {},
): string {
  return date.toLocaleTimeString(locale, { ...options, timeZone: displayZone(appTimezone) }) + zoneLabel(appTimezone);
}

/**
 * Count the whole hours since midnight in the display zone, rounded up, never below 1.
 *
 * Requires:
 *   - `now` is a valid Date
 *
 * Ensures:
 *   - midnight is the display zone's, not the browser's
 */
export function hoursSinceMidnight(now: Date, appTimezone?: string | null): number {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone  : displayZone(appTimezone),
    hourCycle : "h23",
    hour      : "numeric",
    minute    : "numeric",
    second    : "numeric",
  }).formatToParts(now);
  const part = (type: string): number => Number(parts.find((p) => p.type === type)!.value);
  return Math.max(1, Math.ceil((part("hour") * 3600 + part("minute") * 60 + part("second") + now.getMilliseconds() / 1000) / 3600));
}

/**
 * Format a millisecond duration as `MM:SS`. Pure formatter (per D-H).
 *
 * Requires:
 *   - `ms` is the remaining countdown in milliseconds (caller pre-corrected
 *     for any clock offset)
 *
 * Ensures:
 *   - returns `MM:SS` zero-padded; negative or zero input → "00:00"
 *   - no global state read; no `Date.now()` access; idempotent for same input
 */
export function formatCountdown(ms: number): string {
  const safe = Math.max(0, ms | 0);
  const totalSeconds = Math.floor(safe / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  const mm = String(minutes).padStart(2, "0");
  const ss = String(seconds).padStart(2, "0");
  return `${mm}:${ss}`;
}

/**
 * Format a millisecond epoch timestamp as `HH:MM` (24-hour).
 *
 * The server zone (`appTimezone`), else UTC with a trailing " UTC" label.
 * Legacy `getLocalTimeDisplay` semantics (`notifications.js:10107-10121`).
 *
 * Requires:
 *   - `ts` is a finite ms-epoch timestamp
 *
 * Ensures:
 *   - returns a 5-character zero-padded `HH:MM` string, plus " UTC" when no server zone is set
 *   - NaN / Infinity input → "--:--"
 */
export function formatHM(ts: number, appTimezone?: string): string {
  if (!Number.isFinite(ts)) return "--:--";
  return formatClock(new Date(ts), appTimezone, "en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
}

/**
 * Format a millisecond epoch timestamp as `YYYY-MM-DD` (date-accordion key).
 *
 * Ports `getDateString` + `extractDateFromTimestamp` semantics from
 * `notifications.js:10068-10098` (D-J corrected citation). The date boundary
 * follows the server-configured TZ, else UTC. The key carries no label.
 *
 * Requires:
 *   - `ts` is a finite ms-epoch timestamp
 *
 * Ensures:
 *   - returns 10-character `YYYY-MM-DD` string
 *   - NaN / Infinity input → "----------"
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function formatDateKey(ts: number, appTimezone?: string): string {
  if (!Number.isFinite(ts)) return "----------";
  // en-CA emits ISO-style YYYY-MM-DD natively.
  return new Intl.DateTimeFormat("en-CA", {
    year     : "numeric",
    month    : "2-digit",
    day      : "2-digit",
    timeZone : displayZone(appTimezone),
  }).format(new Date(ts));
}

/**
 * Format the elapsed duration between two epoch ms timestamps for human display.
 *
 * Phase 6a Pass 2 F24 — Genuinely New formatter (sibling of formatHM/formatDateKey).
 * Used by `jobCard.ts` for the `.job-timing` field on each job card.
 *
 * Output forms:
 *   - `endTs` undefined           → "running for Ns" / "running for 5m 12s" / "running for 1h 47m"
 *   - `endTs` finite, < 60s       → "Ns"        (e.g., "23s")
 *   - `endTs` finite, < 1h        → "Nm Ms"     (e.g., "5m 12s")
 *   - `endTs` finite, ≥ 1h        → "Nh Mm"     (e.g., "1h 47m")
 *   - `startTs` or `endTs` non-finite → "--"
 *
 * Requires:
 *   - `startTs` is a finite ms-epoch timestamp; `endTs` is undefined OR a finite ms-epoch.
 *
 * Ensures:
 *   - returns a humanized elapsed string per the table above.
 *   - reads `Date.now()` only when `endTs` is undefined (running case); otherwise pure on inputs.
 *   - never returns the empty string; non-finite input returns the literal "--".
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function formatDuration(startTs: number, endTs?: number): string {
  if (!Number.isFinite(startTs)) return "--";
  if (endTs !== undefined && !Number.isFinite(endTs)) return "--";

  const isRunning      = endTs === undefined;
  const effectiveEnd   = isRunning ? Date.now() : (endTs as number);
  const elapsedSeconds = Math.max(0, Math.floor((effectiveEnd - startTs) / 1000));

  let humanized: string;
  if (elapsedSeconds < 60) {
    humanized = `${elapsedSeconds}s`;
  } else if (elapsedSeconds < 3600) {
    const minutes = Math.floor(elapsedSeconds / 60);
    const seconds = elapsedSeconds % 60;
    humanized = `${minutes}m ${seconds}s`;
  } else {
    const hours   = Math.floor(elapsedSeconds / 3600);
    const minutes = Math.floor((elapsedSeconds % 3600) / 60);
    humanized = `${hours}h ${minutes}m`;
  }

  return isRunning ? `running for ${humanized}` : humanized;
}
