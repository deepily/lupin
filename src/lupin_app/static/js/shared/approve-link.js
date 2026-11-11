/* c8 ignore next */ // tsx phantom-branch artifact on the file-header line, same as task-status-filter.js.
/**
 * One-click ticket approval links, shared by both clients.
 *
 * A manager asking Rick to approve rows writes each as a bullet with an ordinary markdown link:
 * `[approve ☐](/app/tasks/approve?row=<full uuid>) [📋](/app/tasks/view?row=<full uuid>)`.
 * Both links are actions, not destinations. The approve click sends the approve move and draws "approved ✅"
 * where the link was. The 📋 click reads the row and shows it the way the abstract 📋 shows text.
 * A card drawn after a reload is checked once per row id.
 * A row that has left the holding area shows "approved ✅", or its plain status when it was dropped.
 *
 * Plain JS, because notifications.js is a classic script with no build step.
 * It reads this through `window.LUPIN_APPROVE_LINK`.
 * The multiplexer imports the same file, re-exported with types by multiplexer/render/approveLink.ts.
 *
 * Nothing here reaches for a client's own objects: every handler takes its sender, reader and shower as
 * arguments. The sender must always post, never throw, and report a refusal as `{ ok: false, message }`.
 * `HoldingAreaStore.transitionTask` is one; `NotificationsUI._transitionTask` is the other.
 */

// `http://localhost:7999/app/docs?…` and `/app/docs?…` are the same document. Senders emit both,
// so every prefix test runs on a normalized href.
const LOOPBACK_PREFIX_RE = /^https?:\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?/;

/**
 * Strip an absolute loopback origin from an href.
 *
 * @param {string | null} href
 * @returns {string | null}
 *
 * Ensures:
 *     - null for a null or empty href: an `<a>` with no href is ordinary markup, not an error
 */
export function normalizeDocLinkHref( href ) {
  if ( href === null || href === "" ) return null;
  return href.replace( LOOPBACK_PREFIX_RE, "" );
}

/** Every approve link starts here, after loopback normalization. */
export const APPROVE_LINK_PREFIX = "/app/tasks/approve?row=";

// A full lowercase hyphenated row id, the only thing sent to the server.
const ROW_ID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** A priority link ends with this and a level. The server honours it for Rick's login only. */
export const PRIORITY_LINK_PARAM = "&priority=";

const PRIORITY_RE = /^P[0-5]$/;

/** Every 📋 view link starts here, after loopback normalization. */
export const VIEW_LINK_PREFIX = "/app/tasks/view?row=";

/**
 * The row id an approve-link href names, or null when the href is not an approve link.
 *
 * Requires: nothing (null and empty are "not an approve link").
 * Ensures: a malformed or short id is null, so nothing is ever sent for it.
 *
 * @param {string | null} href
 * @returns {string | null}
 */
export function approveRowId( href ) {
  return rowIdAfter( APPROVE_LINK_PREFIX, href );
}

/**
 * The row and level a priority-link href names, or null.
 *
 * The href is `/app/tasks/approve?row=<id>&priority=P0`.
 * Ensures: the plain approve link is null here, and a priority link is null for `approveRowId`, so each click has one handler.
 *
 * @param {string | null} href
 * @returns {import("./approve-link.js").PriorityLink | null}
 */
export function approvePriorityLink( href ) {
  const normalized = normalizeDocLinkHref( href );
  if ( normalized === null ) return null;
  const at = normalized.lastIndexOf( PRIORITY_LINK_PARAM );
  if ( at < 0 ) return null;
  const priority = normalized.slice( at + PRIORITY_LINK_PARAM.length );
  const rowId    = rowIdAfter( APPROVE_LINK_PREFIX, normalized.slice( 0, at ) );
  return rowId !== null && PRIORITY_RE.test( priority ) ? { rowId, priority } : null;
}

/**
 * The row id a 📋 view-link href names, or null when the href is not a view link.
 *
 * @param {string | null} href
 * @returns {string | null}
 */
export function viewRowId( href ) {
  return rowIdAfter( VIEW_LINK_PREFIX, href );
}

/**
 * @param {string} prefix
 * @param {string | null} href
 * @returns {string | null}
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function-declaration line.
function rowIdAfter( prefix, href ) {
  const normalized = normalizeDocLinkHref( href );
  if ( normalized === null || !normalized.startsWith( prefix ) ) return null;
  const id = normalized.slice( prefix.length );
  return ROW_ID_RE.test( id ) ? id : null;
}

/**
 * Handle a click that may be on an approve link. Returns true when the click was claimed.
 *
 * `withPriority` picks which links this call answers: false claims the plain link, true claims the
 * priority link (`&priority=P0`) and sends the level as `promote_priority`. Each click has one handler:
 * a plain call never claims a priority link and a priority call never claims a plain one.
 *
 * Ensures:
 *   - a click this call does not answer is untouched and reports false
 *   - the browser does not follow the link (preventDefault), wherever the link sits
 *   - one request per link: a second click while it is out sends nothing
 *   - success replaces the link with a disabled "approved ✅" ("approved at <level> ✅" for a priority link);
 *     a refusal or pending answer replaces it with the server's message, word for word
 *
 * @param {Event} ev
 * @param {Element} target
 * @param {import("./approve-link.js").ApproveSender} sender
 * @param {boolean} [withPriority]
 * @returns {boolean}
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function-declaration line (same as docLink.ts isPaneResidentAnchor).
export function handleApproveLinkClick( ev, target, sender, withPriority = false ) {
  const anchor = target.closest( "a[href]" );
  if ( anchor === null ) return false;
  const href     = anchor.getAttribute( "href" );
  const priority = withPriority ? approvePriorityLink( href ) : null;
  const rowId    = withPriority ? priority?.rowId ?? null : approveRowId( href );
  if ( rowId === null ) return false;
  ev.preventDefault();
  if ( anchor.getAttribute( "data-approve-state" ) === "pending" ) return true;
  anchor.setAttribute( "data-approve-state", "pending" );
  anchor.setAttribute( "aria-disabled", "true" );
  /** @type {HTMLElement} */ ( anchor ).style.opacity = "0.5";
  /** @type {Record<string, string>} */
  const extras = priority === null ? {} : { promote_priority: priority.priority };
  void sender.transitionTask( rowId, "queued", extras ).then( ( result ) => {
    const outcome = anchor.ownerDocument.createElement( "span" );
    outcome.className   = result.ok ? "approve-link-result approve-link-approved" : "approve-link-result approve-link-refused";
    outcome.textContent = result.ok ? ( priority === null ? APPROVED_TEXT : `approved at ${ priority.priority } ✅` ) : result.message;
    if ( result.ok ) outcome.setAttribute( "aria-disabled", "true" );
    anchor.replaceWith( outcome );
  } );
  return true;
}

/**
 * Handle a click that may be on a priority link. Returns true when the click was claimed.
 *
 * It is `handleApproveLinkClick` answering the priority link; the request is the approve move plus
 * `promote_priority`, and the server decides who may.
 *
 * @param {Event} ev
 * @param {Element} target
 * @param {import("./approve-link.js").ApproveSender} sender
 * @returns {boolean}
 */
export function handleApprovePriorityLinkClick( ev, target, sender ) {
  return handleApproveLinkClick( ev, target, sender, true );
}

/**
 * The reader the 📋 link and the redraw check share, built on the api client.
 *
 * Requires: api.get sends a GET and resolves with the parsed body.
 * Ensures:
 *   - the request is `GET /api/tasks/<id>` with the id percent-encoded, as the legacy card sends it
 *   - any failure reads as null, so the caller leaves the live link or says the read failed
 *
 * @param {{ get( path: string ): Promise<any> }} api
 * @returns {import("./approve-link.js").TaskReader}
 */
export function taskReaderFor( api ) {
  return async ( id ) => {
    try { return await api.get( `/api/tasks/${ encodeURIComponent( id ) }` ); }
    catch { return null; }
  };
}

/** What a disabled, already-approved link reads. */
export const APPROVED_TEXT = "approved ✅";

/** Statuses that mean the row was turned down, shown as plain text and never as approved. */
const CLOSED_STATUSES = new Set( [ "dropped", "wont_fix" ] );

/**
 * One block of text: a row's title, priority, owner, status and body.
 *
 * Requires: row is a task row as the server sent it.
 * Ensures: a missing field reads as a dash, "unowned" or "(no body)", never as "undefined".
 *
 * @param {import("./approve-link.js").ApproveLinkRow} row
 * @returns {string}
 */
export function taskOverlayText( row ) {
  const facts = `Priority: ${ row.priority ?? "—" } · Owner: ${ row.owner_persona ?? "unowned" } · Status: ${ row.status ?? "—" }`;
  return `${ row.title ?? "(no title)" }\n${ facts }\n\n${ row.body ?? "(no body)" }`;
}

/**
 * Handle a click that may be on a 📋 view link. Returns true when the click was claimed.
 *
 * Ensures:
 *   - a non-view click is untouched and reports false
 *   - the browser does not follow the link
 *   - the row is read and handed to `show` (the abstract 📋's own display code); a failed read says so there
 *   - no overlay and no tab opens
 *
 * @param {Event} ev
 * @param {Element} target
 * @param {import("./approve-link.js").TaskReader} reader
 * @param {import("./approve-link.js").AbstractShower} show
 * @returns {boolean}
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function-declaration line.
export function handleViewLinkClick( ev, target, reader, show ) {
  const anchor = target.closest( "a[href]" );
  if ( anchor === null ) return false;
  const rowId = viewRowId( anchor.getAttribute( "href" ) );
  if ( rowId === null ) return false;
  ev.preventDefault();
  void reader( rowId ).then( ( row ) => {
    show( anchor, row === null ? "Could not read this ticket." : taskOverlayText( row ), `Ticket ${ rowId.slice( 0, 8 ) }` );
  } );
  return true;
}

/**
 * Check every unchecked approve link under the given roots, one read per distinct row id.
 *
 * Ensures:
 *   - a link is checked once; one already clicked (pending) is left alone
 *   - not_approved, or a failed read, leaves the live link as it is
 *   - a row that left not_approved for a live or done status becomes a disabled "approved ✅"
 *   - a dropped or wont_fix row becomes plain text naming that status, never "approved"
 *
 * @param {Iterable<Element>} roots
 * @param {import("./approve-link.js").TaskReader} reader
 * @returns {Promise<void>}
 */
export async function markApproveLinks( roots, reader ) {
  const byRow = new Map();
  for ( const root of roots ) {
    const found = root.matches( "a[href]" ) ? [ root ] : Array.from( root.querySelectorAll( "a[href]" ) );
    for ( const anchor of found ) {
      const id = approveRowId( anchor.getAttribute( "href" ) ) ?? approvePriorityLink( anchor.getAttribute( "href" ) )?.rowId ?? null;
      if ( id === null || anchor.hasAttribute( "data-approve-checked" ) ) continue;
      anchor.setAttribute( "data-approve-checked", "1" );
      byRow.set( id, [ ...( byRow.get( id ) ?? [] ), anchor ] );
    }
  }
  await Promise.all( Array.from( byRow, async ( [ id, anchors ] ) => {
    const row = await reader( id );
    if ( row === null || row.status === undefined || row.status === "not_approved" ) return;
    for ( const anchor of anchors ) {
      if ( !anchor.isConnected || anchor.getAttribute( "data-approve-state" ) === "pending" ) continue;
      const verdict = anchor.ownerDocument.createElement( "span" );
      const closed  = CLOSED_STATUSES.has( row.status );
      verdict.className   = closed ? "approve-link-result approve-link-closed" : "approve-link-result approve-link-approved";
      verdict.textContent = closed ? row.status : APPROVED_TEXT;
      if ( !closed ) verdict.setAttribute( "aria-disabled", "true" );
      anchor.replaceWith( verdict );
    }
  } ) );
}

/**
 * Watch a root for newly drawn approve links and check each batch once.
 *
 * Ensures: the links already under root are checked now; the returned function stops the watch.
 *
 * @param {Element} root
 * @param {import("./approve-link.js").TaskReader} reader
 * @returns {() => void}
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function-declaration line.
export function observeApproveLinks( root, reader ) {
  void markApproveLinks( [ root ], reader );
  const observer = new MutationObserver( ( records ) => {
    /** @type {Element[]} */
    const added = [];
    for ( const rec of records ) rec.addedNodes.forEach( ( n ) => { if ( n.nodeType === 1 ) added.push( /** @type {Element} */ ( n ) ); } );
    if ( added.length > 0 ) void markApproveLinks( added, reader );
  } );
  observer.observe( root, { childList: true, subtree: true } );
  return () => observer.disconnect();
}

// ---------------------------------------------------------------------------
// Batch links: one click applies one move to a whole list of held rows
// ---------------------------------------------------------------------------
//
// `/app/tasks/approve?rows=<id>,<id>&move=queued|dropped[&reason=...]` and its 📋 partner
// `/app/tasks/view?rows=<id>,<id>`. The click is the same user_direct move the single link sends,
// once per row, and the answer names every row: a refusal of one never hides the others.

/** Every batch approve link starts here, after loopback normalization. */
export const BATCH_APPROVE_PREFIX = "/app/tasks/approve?rows=";

/** Every batch view link starts here, after loopback normalization. */
export const BATCH_VIEW_PREFIX = "/app/tasks/view?rows=";

/**
 * A comma list of full row ids as an array, or null when the list cannot be trusted.
 *
 * Ensures: null for an empty list, a short or malformed id, or the same id twice, so nothing is sent for it.
 *
 * @param {string | null} list
 * @returns {string[] | null}
 */
export function parseBatchIds( list ) {
  if ( list === null || list === "" ) return null;
  const ids = list.split( "," );
  if ( ids.some( ( id ) => !ROW_ID_RE.test( id ) ) ) return null;
  if ( new Set( ids ).size !== ids.length ) return null;
  return ids;
}

/**
 * The query of a link whose normalized href starts with `prefix`, or null.
 *
 * @param {string} prefix
 * @param {string | null} href
 * @returns {URLSearchParams | null}
 */
function batchParams( prefix, href ) {
  const normalized = normalizeDocLinkHref( href );
  if ( normalized === null || !normalized.startsWith( prefix ) ) return null;
  return new URLSearchParams( normalized.slice( prefix.indexOf( "?" ) + 1 ) );
}

/**
 * What a batch approve-link href asks for, or null when it is not one or cannot be trusted.
 *
 * Ensures: null for a bad id list, a move other than queued or dropped, or a drop with a blank reason.
 *
 * @param {string | null} href
 * @returns {import("./approve-link.js").BatchLink | null}
 */
export function batchLinkOf( href ) {
  const params = batchParams( BATCH_APPROVE_PREFIX, href );
  if ( params === null ) return null;
  const ids  = parseBatchIds( params.get( "rows" ) );
  const move = params.get( "move" );
  if ( ids === null || ( move !== "queued" && move !== "dropped" ) ) return null;
  const reason = ( params.get( "reason" ) ?? "" ).trim();
  if ( move === "dropped" && reason === "" ) return null;
  return { ids, move, reason: move === "dropped" ? reason : null };
}

/**
 * The ids a batch 📋 view-link href names, or null when it is not one or the list is bad.
 *
 * @param {string | null} href
 * @returns {string[] | null}
 */
export function batchViewIds( href ) {
  const params = batchParams( BATCH_VIEW_PREFIX, href );
  return params === null ? null : parseBatchIds( params.get( "rows" ) );
}

/**
 * Apply one move to every listed row, all requests out together.
 *
 * Ensures: returns one line per row in the order given, `<first 8> applied ✅` or `<first 8> refused: <server words>`.
 *
 * @param {import("./approve-link.js").BatchLink} link
 * @param {import("./approve-link.js").ApproveSender} sender
 * @returns {Promise<string[]>}
 */
export async function applyBatch( link, sender ) {
  /** @type {Record<string, string>} */
  const extras = link.reason === null ? {} : { reason: link.reason };
  const results = await Promise.all( link.ids.map( ( id ) => sender.transitionTask( id, link.move, extras ) ) );
  return results.map( ( r, i ) => `${ /** @type {string} */ ( link.ids[ i ] ).slice( 0, 8 ) } ${ r.ok ? "applied ✅" : `refused: ${ r.message }` }` );
}

/**
 * Handle a click that may be on a batch approve link. Returns true if it claimed it.
 *
 * Ensures:
 *   - a click on anything else is untouched and reports false
 *   - a batch link that cannot be trusted (bad, short or repeated id, empty list, odd move, drop without a reason)
 *     is claimed so the browser does not navigate, but sends nothing
 *   - one run per link: a second click while it is out sends nothing
 *   - the link is replaced by a summary line and one line per row
 *
 * @param {Event} ev
 * @param {Element} target
 * @param {import("./approve-link.js").ApproveSender} sender
 * @returns {boolean}
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function-declaration line.
export function handleBatchApproveLinkClick( ev, target, sender ) {
  const anchor = target.closest( "a[href]" );
  if ( anchor === null ) return false;
  const href = anchor.getAttribute( "href" );
  if ( normalizeDocLinkHref( href )?.startsWith( BATCH_APPROVE_PREFIX ) !== true ) return false;
  ev.preventDefault();
  const link = batchLinkOf( href );
  if ( link === null || anchor.getAttribute( "data-approve-state" ) === "pending" ) return true;
  anchor.setAttribute( "data-approve-state", "pending" );
  anchor.setAttribute( "aria-disabled", "true" );
  /** @type {HTMLElement} */ ( anchor ).style.opacity = "0.5";
  void applyBatch( link, sender ).then( ( lines ) => {
    const done    = lines.filter( ( l ) => l.endsWith( "applied ✅" ) ).length;
    const outcome = anchor.ownerDocument.createElement( "span" );
    outcome.className = done === lines.length ? "approve-link-result approve-link-approved" : "approve-link-result approve-link-refused";
    outcome.textContent = [ `${ done } of ${ lines.length } applied`, ...lines ].join( "\n" );
    /** @type {HTMLElement} */ ( outcome ).style.whiteSpace = "pre-line";
    anchor.replaceWith( outcome );
  } );
  return true;
}

/**
 * Handle a click that may be on a batch 📋 view link. Returns true when it claimed the click.
 *
 * Ensures:
 *   - a click on anything else is untouched and reports false
 *   - the browser does not follow the link
 *   - every row is read and `show` gets one line per row, its status and title, in the order given;
 *     a row that could not be read says so, and the rest still show
 *
 * @param {Event} ev
 * @param {Element} target
 * @param {import("./approve-link.js").TaskReader} reader
 * @param {import("./approve-link.js").AbstractShower} show
 * @returns {boolean}
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function-declaration line.
export function handleBatchViewLinkClick( ev, target, reader, show ) {
  const anchor = target.closest( "a[href]" );
  if ( anchor === null ) return false;
  const href = anchor.getAttribute( "href" );
  if ( normalizeDocLinkHref( href )?.startsWith( BATCH_VIEW_PREFIX ) !== true ) return false;
  ev.preventDefault();
  const ids = batchViewIds( href );
  if ( ids === null ) { show( anchor, "This link does not name a clean list of full ticket ids.", "Held rows" ); return true; }
  void Promise.all( ids.map( reader ) ).then( ( rows ) => {
    const lines = rows.map( ( row, i ) => `${ /** @type {string} */ ( ids[ i ] ).slice( 0, 8 ) } · ${ row === null ? "could not be read" : `${ row.status ?? "—" } · ${ row.title ?? "(no title)" }` }` );
    show( anchor, lines.join( "\n" ), `${ ids.length } held rows` );
  } );
  return true;
}

/**
 * Puts the surface on a window object for the classic-script page.
 *
 * @param {any} win
 *
 * Requires:
 *     - win is an object (a window, or a stand-in in a test)
 * Ensures:
 *     - win.LUPIN_APPROVE_LINK carries every export of this module except publishOnWindow
 */
export function publishOnWindow( win ) {
  win.LUPIN_APPROVE_LINK = {
    normalizeDocLinkHref, approveRowId, approvePriorityLink, viewRowId, parseBatchIds, batchLinkOf, batchViewIds,
    taskOverlayText, taskReaderFor, markApproveLinks, observeApproveLinks, applyBatch,
    handleApproveLinkClick, handleApprovePriorityLinkClick, handleViewLinkClick, handleBatchApproveLinkClick, handleBatchViewLinkClick,
  };
}

// The classic-script bridge: notifications.js reads the global when it is called.
// The declaration is in window-globals.d.ts.
/* c8 ignore next */ // tsx adds an empty never-run range at the file tail; the publish line itself is run and asserted.
publishOnWindow( globalThis );
