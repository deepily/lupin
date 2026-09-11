/**
 * A manager's promote/demote REQUEST, as both boards show it — shared by both clients.
 *
 * Row c9fafb9d. Rick, 2026-09-08: "it is me and me alone not managers that gets to promote
 * and demote … Only thing managers can do is request And there's requests default to no".
 * A manager files a request (`POST /api/tasks/{id}/request`, MCP `task_request`); it waits
 * on Rick's board with no expiry; his Approve performs the move (his Q2, 2026-09-10) and
 * his Deny leaves the row exactly where it is. Design:
 * src/rnd/2026.09.10-request-door-design.md §6.
 *
 * WHY A SHARED MODULE. Mr. Radio's D4 ruled BOTH clients, and two copies of "what does a
 * pending request look like, and what does approving one send" would drift the way
 * `taskVerbs.ts` drifted from `task-verbs.js` (row 507183ff). This file is the one source,
 * in the shape `task-lookup.js` already uses: an ES module for the esbuild bundle,
 * published on `window` for the classic-script page that cannot `import`.
 *
 * ⚠️ NOTHING HERE IS A CONTROL. Every viewer sees Approve and Deny; the verdict door refuses
 * anyone but Rick's account. Hiding the buttons would be presentation, and the server is
 * the control.
 */

export const REQUEST_PENDING = "pending";
export const MOVE_ADMIT      = "admit";
export const MOVE_DEMOTE     = "demote";
export const VERDICT_APPROVED = "approved";
export const VERDICT_DENIED   = "denied";

/** The two badge counts `GET /api/tasks/request-badges` returns. Never summed. */
export const BADGE_HOLDING_AREA = "holding_area";
export const BADGE_TASK_AREA    = "task_area";

export const REQUEST_BADGES_PATH = "/api/tasks/request-badges";

/** Label for the triage date an approved demote needs, matching the demote verb's own. */
export const TRIAGE_DATE_LABEL = "Triage this by";

export const DEMOTE_NEEDS_TRIAGE_DATE_MESSAGE =
    "Approving a demote moves the row into the holding area, so it needs a triage-by date — the same date your own Demote asks for.";

const MOVE_TEXT = {
    [ MOVE_ADMIT ]  : "Promote requested",
    [ MOVE_DEMOTE ] : "Demote requested",
};

/**
 * `"/api/tasks/<id>/request-verdict"`.
 *
 * @param {string} taskId
 * @returns {string}
 */
export function requestVerdictPath( taskId ) {
    return `/api/tasks/${encodeURIComponent( taskId )}/request-verdict`;
}

/**
 * How long a request has waited, in words short enough for a chip.
 *
 * @param {string | null | undefined} requestTs  ISO timestamp the request was filed
 * @param {number} nowMs                         the caller's clock, injected so tests pin it
 * @returns {string}  "just now", "12m", "3h" or "2d"; "" when there is no parseable time
 */
export function requestAge( requestTs, nowMs ) {
    if ( typeof requestTs !== "string" || requestTs === "" ) return "";
    const filedMs = Date.parse( requestTs );
    if ( Number.isNaN( filedMs ) ) return "";
    const minutes = Math.floor( Math.max( 0, nowMs - filedMs ) / 60000 );
    if ( minutes < 1 )  return "just now";
    if ( minutes < 60 ) return `${minutes}m`;
    const hours = Math.floor( minutes / 60 );
    if ( hours < 24 )   return `${hours}h`;
    return `${Math.floor( hours / 24 )}d`;
}

/**
 * What the pending-request chip on a row says, or null when the row has nothing pending.
 *
 * 🔴 ONLY `pending` IS SHOWN. An approved request has already moved the row and a denied one
 * is finished; a chip for either would keep an answered question in front of Rick — the
 * same reason the server's badge counts only pending requests.
 *
 * @param {{ request_state?: string | null, request_move?: string | null, request_ts?: string | null }} row
 * @param {number} nowMs
 * @returns {null | { move: string, text: string, age: string, needsTriageDate: boolean }}
 */
export function pendingRequestChip( row, nowMs ) {
    if ( row === null || typeof row !== "object" ) return null;
    if ( row.request_state !== REQUEST_PENDING ) return null;
    const move = row.request_move;
    if ( move !== MOVE_ADMIT && move !== MOVE_DEMOTE ) return null;
    return {
        move,
        text            : MOVE_TEXT[ move ],
        age             : requestAge( row.request_ts, nowMs ),
        needsTriageDate : move === MOVE_DEMOTE,
    };
}

/**
 * The body a verdict click sends, or the reason it cannot be sent yet.
 *
 * @param {string} verdict  VERDICT_APPROVED or VERDICT_DENIED
 * @param {string} move     the pending request's move
 * @param {{ triageByIso?: string | null, reason?: string | null }} [extras]
 * @returns {{ ok: true, body: { verdict: string, next_chase_ts?: string, reason?: string } } | { ok: false, message: string }}
 */
export function requestVerdictBody( verdict, move, extras = {} ) {
    /** @type {{ verdict: string, next_chase_ts?: string, reason?: string }} */
    const body   = { verdict };
    const reason = typeof extras.reason === "string" ? extras.reason.trim() : "";
    if ( reason !== "" ) body.reason = reason;
    if ( verdict === VERDICT_APPROVED && move === MOVE_DEMOTE ) {
        const triage = extras.triageByIso;
        if ( typeof triage !== "string" || triage === "" ) {
            return { ok: false, message: DEMOTE_NEEDS_TRIAGE_DATE_MESSAGE };
        }
        body.next_chase_ts = triage;
    }
    return { ok: true, body };
}

/** The audit-trail transition a filing appends. Mirror of `apply_request_filing`. */
export const REQUEST_FILED_TRANSITION = "request_filed";

/**
 * The separator `TaskRepository.apply_request_filing` puts between its own preamble and the
 * manager's words: `move: 'admit' (prior request: None) | reason: <the manager's reason>`.
 * Pinned against that f-string by the shared test, so a reworded preamble fails loudly.
 */
export const REQUEST_REASON_SEPARATOR = " | reason: ";

/**
 * `"/api/tasks/<id>/events"` — where the filer and reason of a request live.
 *
 * @param {string} taskId
 * @returns {string}
 */
export function requestEventsPath( taskId ) {
    return `/api/tasks/${encodeURIComponent( taskId )}/events`;
}

/**
 * Who filed the row's CURRENT request and why, read off its audit trail.
 *
 * WHY THE TRAIL AND NOT THE ROW. The row carries `request_state`, `request_move` and
 * `request_ts` and nothing else; the filer and the reason were written onto the
 * `request_filed` event, and adding columns for them would be a migration for text only
 * this chip reads (design §6.2).
 *
 * 🔴 THE LAST FILING, NOT THE FIRST. A row can be re-filed after a denial, and the chip is
 * about the request that is pending now; the older filing's reason answers a question
 * Rick already answered.
 *
 * ⚠️ A REASON WITHOUT THE SEPARATOR IS SHOWN WHOLE rather than dropped — an unparsed
 * sentence is still the manager's words, and an empty reason reads as "no reason given".
 *
 * @param {{ events?: unknown } | null | undefined} eventsBody  the `/events` response
 * @returns {null | { filer: string, reason: string }}
 */
export function requestFiledDetail( eventsBody ) {
    const events = eventsBody !== null && typeof eventsBody === "object" ? eventsBody.events : undefined;
    if ( !Array.isArray( events ) ) return null;
    for ( let i = events.length - 1; i >= 0; i -= 1 ) {
        const event = events[ i ];
        if ( event === null || typeof event !== "object" || event.transition !== REQUEST_FILED_TRANSITION ) continue;
        const filer = typeof event.actor === "string" ? event.actor : "";
        const text  = typeof event.reason === "string" ? event.reason : "";
        const at    = text.indexOf( REQUEST_REASON_SEPARATOR );
        return { filer, reason: at === -1 ? text : text.slice( at + REQUEST_REASON_SEPARATOR.length ) };
    }
    return null;
}

/**
 * A badge chip's text for one of the two counts, or "" when nothing is waiting.
 *
 * @param {Record<string, unknown> | null | undefined} counts  the request-badges response
 * @param {string} badge                                       BADGE_HOLDING_AREA or BADGE_TASK_AREA
 * @returns {string}
 */
export function requestBadgeText( counts, badge ) {
    const n = counts !== null && typeof counts === "object" ? counts[ badge ] : undefined;
    if ( typeof n !== "number" || !Number.isInteger( n ) || n <= 0 ) return "";
    return n === 1 ? "1 request" : `${n} requests`;
}

// The classic-script bridge, mirroring task-lookup.js: notifications.js reads these at
// CALL time. See window-globals.d.ts for the declaration that keeps this typechecking.
if ( typeof window !== "undefined" ) {
    window.LUPIN_TASK_REQUEST = {
        REQUEST_BADGES_PATH, BADGE_HOLDING_AREA, BADGE_TASK_AREA,
        VERDICT_APPROVED, VERDICT_DENIED, TRIAGE_DATE_LABEL,
        requestVerdictPath, requestAge, pendingRequestChip, requestVerdictBody, requestBadgeText,
        requestEventsPath, requestFiledDetail,
    };
}
