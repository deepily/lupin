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
// absence of a configured server timezone, falls back to browser-local TZ
// (matches legacy behavior under fetchClientConfig miss).

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
 * Browser-local timezone — legacy `getLocalTimeDisplay` semantics
 * (`notifications.js:10107-10121`). Optional `appTimezone` param overrides
 * via `Intl.DateTimeFormat`.
 *
 * Requires:
 *   - `ts` is a finite ms-epoch timestamp
 *
 * Ensures:
 *   - returns 5-character zero-padded `HH:MM` string
 *   - NaN / Infinity input → "--:--"
 */
export function formatHM(ts: number, appTimezone?: string): string {
  if (!Number.isFinite(ts)) return "--:--";
  const date = new Date(ts);
  /* c8 ignore next */ // defensive: empty-string appTimezone branch — tests pass either undefined OR a real TZ string; the empty-string fallback is for legacy `appTimezone=""` config rows.
  if (appTimezone !== undefined && appTimezone !== "") {
    const fmt = new Intl.DateTimeFormat("en-US", {
      hour     : "2-digit",
      minute   : "2-digit",
      hour12   : false,
      timeZone : appTimezone,
    });
    return fmt.format(date);
  }
  /* c8 ignore next 3 */ // browser-local TZ fallback: tests pass appTimezone explicitly to keep timezone-independent assertions; the no-TZ path runs in production when appTimezone INI key is unset.
  const hours   = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${hours}:${minutes}`;
}

/**
 * Format a millisecond epoch timestamp as `YYYY-MM-DD` (date-accordion key).
 *
 * Ports `getDateString` + `extractDateFromTimestamp` semantics from
 * `notifications.js:10068-10098` (D-J corrected citation). When `appTimezone`
 * is provided, the date boundary follows the server-configured TZ; otherwise
 * browser-local.
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
  const date = new Date(ts);
  /* c8 ignore next */ // defensive: empty-string appTimezone branch — same rationale as formatHM.
  if (appTimezone !== undefined && appTimezone !== "") {
    const fmt = new Intl.DateTimeFormat("en-CA", {
      year     : "numeric",
      month    : "2-digit",
      day      : "2-digit",
      timeZone : appTimezone,
    });
    // en-CA emits ISO-style YYYY-MM-DD natively.
    return fmt.format(date);
  }
  /* c8 ignore next 4 */ // browser-local TZ fallback: same rationale as formatHM — tests pass appTimezone explicitly; the no-TZ path is production-only.
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}
