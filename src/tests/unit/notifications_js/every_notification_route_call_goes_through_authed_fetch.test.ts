// EVERY LEGACY CALL TO A NOTIFICATION ROUTE GOES THROUGH `authedFetch`.
//
// Row cc899c44. All 23 handlers in src/cosa/rest/routers/notifications.py now require a
// credential. Measured at 327dcd04 before that change, four legacy notifications.js calls
// sent none — three passed a fake `?api_key=claude_code_simple_key` query the server never
// reads, one sent nothing — and seven more sent a Bearer through `getAuthHeaders()`, which
// never refreshes, so an idle tab's expired token 401s silently. One of the four had been
// reading an already-guarded route since 2026-09-08, so a closed response window filed
// OUTCOME_UNKNOWN for every real recorded answer.
//
// `authedFetch` refreshes the token and attaches it. Mr. Radio ruled (2026-09-10) that the
// guard is the SURFACE, not the sites found: scan the file for every fetch whose URL names
// /api/notif and fail on any not made through `authedFetch`.
//
// HOW THE SCAN READS A URL. A call's first argument is taken by bracket depth, honouring
// strings and template literals. When that argument is a variable (`fetch( url, … )`), the
// nearest preceding `const|let|var <name> =` is substituted, up to three levels, because
// three of the fifteen sites build their URL that way.
//
// ⚠️ WHAT IT CANNOT SEE: a URL arriving as a function PARAMETER, or built in another
// method. Those calls are counted as `unresolved` and reported by the test below, rather
// than passing silently as though they were not notification calls.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

const ROUTE_MARK = "/api/notif";

type Site = { line: number; callee: string; url: string; resolved: boolean };

/** Index just past the string or template literal opening at `i`. */
function skipLiteral( src: string, i: number ): number {
  const quote = src[ i ];
  let j = i + 1;
  while ( j < src.length ) {
    const c = src[ j ];
    if ( c === "\\" ) { j += 2; continue; }
    if ( c === quote ) return j + 1;
    if ( quote === "`" && c === "$" && src[ j + 1 ] === "{" ) {
      j = skipBalanced( src, j + 1 );
      continue;
    }
    j++;
  }
  return j;
}

/** Index just past the bracket group opening at `i`. */
function skipBalanced( src: string, i: number ): number {
  const open = src[ i ];
  const close = open === "(" ? ")" : open === "[" ? "]" : "}";
  let depth = 0;
  let j = i;
  while ( j < src.length ) {
    const c = src[ j ];
    if ( c === "'" || c === '"' || c === "`" ) { j = skipLiteral( src, j ); continue; }
    if ( c === open ) depth++;
    else if ( c === close ) { depth--; if ( depth === 0 ) return j + 1; }
    j++;
  }
  return j;
}

/** The text of the first argument of the call whose `(` sits at `paren`. */
function firstArgument( src: string, paren: number ): string {
  let j = paren + 1;
  while ( j < src.length ) {
    const c = src[ j ];
    if ( c === "'" || c === '"' || c === "`" ) { j = skipLiteral( src, j ); continue; }
    if ( c === "(" || c === "[" || c === "{" ) { j = skipBalanced( src, j ); continue; }
    if ( c === "," || c === ")" ) break;
    j++;
  }
  return src.slice( paren + 1, j ).trim();
}

/** Substitute the nearest preceding declaration of each bare identifier, up to `depth` levels. */
function resolveUrl( src: string, at: number, text: string, depth = 3 ): { url: string; resolved: boolean } {
  const outsideLiterals = text.replace( /`(?:\\.|[^`\\])*`|'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"/g, "" );
  const names = ( outsideLiterals.match( /\b[A-Za-z_$][\w$]*\b/g ) ?? [] )
    .filter( n => ![ "this", "self", "encodeURIComponent", "String" ].includes( n ) );
  const literalNames = [ ...text.matchAll( /\$\{\s*([A-Za-z_$][\w$]*)\s*\}/g ) ].map( m => m[ 1 ] );
  const candidates = [ ...new Set( [ ...names, ...literalNames ] ) ];

  let url = text;
  let resolved = /[`'"]/.test( text ) || candidates.length === 0;
  if ( depth === 0 ) return { url, resolved };

  for ( const name of candidates ) {
    const decl = new RegExp( `\\b(?:const|let|var)\\s+${name.replace( /\$/g, "\\$" )}\\s*=\\s*([^;\\n]+)`, "g" );
    let last: RegExpExecArray | null = null;
    for ( const m of src.slice( 0, at ).matchAll( decl ) ) last = m as RegExpExecArray;
    if ( last === null ) continue;
    const inner = resolveUrl( src, last.index!, last[ 1 ], depth - 1 );   // matchAll always sets index
    url += " ⟶ " + inner.url;
    resolved = resolved || inner.resolved;
  }
  return { url, resolved };
}

/** `src` with every comment line blanked in place, so prose mentioning fetch( is not a call. */
function withoutCommentLines( src: string ): string {
  return src.split( "\n" ).map( l => /^\s*(\/\/|\*|\/\*)/.test( l ) ? "" : l ).join( "\n" );
}

/** Every fetch-shaped call in `src`: bare `fetch(` and `this|self.authedFetch(`. */
function fetchSites( raw: string ): Site[] {
  const src = withoutCommentLines( raw );
  const sites: Site[] = [];
  const call = /(this\.authedFetch|self\.authedFetch|(?<![\w$.])fetch)\s*\(/g;
  for ( const m of src.matchAll( call ) ) {
    const at    = m.index!;   // matchAll always sets index
    const paren = at + m[ 0 ].length - 1;
    const arg   = firstArgument( src, paren );
    const { url, resolved } = resolveUrl( src, at, arg );
    sites.push( { line: src.slice( 0, at ).split( "\n" ).length, callee: m[ 1 ], url, resolved } );
  }
  return sites;
}

const notificationSites = ( src: string ): Site[] => fetchSites( src ).filter( s => s.url.includes( ROUTE_MARK ) );
const bareSites         = ( src: string ): Site[] => notificationSites( src ).filter( s => !s.callee.endsWith( "authedFetch" ) );
const describeSite      = ( s: Site ): string => `L${s.line} ${s.callee}( ${s.url} )`;

/**
 * Why a bare fetch whose URL the scan could not read is NOT a notification call — or null when
 * nothing explains it. Each explanation is a check that runs, never a name on a list.
 */
function explainBlindSite( s: Site, lines: string[], agentSelectSource: string ): string | null {
  // 1. The wrapper's own fetch: its URL is the parameter every authedFetch caller passes.
  const enclosing = lines.slice( 0, s.line ).reverse().find( l => /^\s*async\s+[\w$]+\s*\(/.test( l ) ) ?? "";
  if ( /^\s*async\s+authedFetch\s*\(/.test( enclosing ) ) return "the authedFetch wrapper's own fetch";

  // 2. The agent list: its URL is a constant in agent-select.js, read, not assumed.
  if ( s.url.startsWith( "agentSelect.AGENTS_ENDPOINT" ) ) {
    const value = agentSelectSource.match( /export const AGENTS_ENDPOINT\s*=\s*"([^"]+)"/ );
    if ( value === null || value[ 1 ].includes( ROUTE_MARK ) ) return null;
    return `AGENTS_ENDPOINT is ${value[ 1 ]}`;
  }
  return null;
}

// ---------------------------------------------------------------------------
// THE INSTRUMENT CAN FIND WHAT IT LOOKS FOR — proved before it is trusted
// ---------------------------------------------------------------------------

test( "the scan flags a bare fetch to a notification route, including one whose URL is a variable", () => {
  const snippet = [
    "async a() { await fetch( `/api/notifications/${id}?api_key=${k}` ); }",
    "async b() { const url = `/api/notifications/bulk/${e}?${p}`; await fetch( url, { method: 'DELETE' } ); }",
    "async c() { const base = `/api/notifications/x/${s}`; const url = p ? `${base}?${p}` : base; await fetch( url ); }",
    "async d() { await this.authedFetch( '/api/notify', { method: 'POST' } ); }",
    "async e() { await fetch( '/api/config/client' ); }",
  ].join( "\n" );

  assert.deepEqual( bareSites( snippet ).map( s => s.line ), [ 1, 2, 3 ] );
  assert.equal( notificationSites( snippet ).length, 4, "the authedFetch call is a notification site too" );
} );

test( "the scan reads past escaped quotes and survives source that never closes", () => {
  // An escaped quote must not end the literal early, or the URL after it is lost; and a
  // truncated file must end the walk rather than hang or throw.
  const escaped = "async a() { await fetch( 'it\\'s /api/notifications/x', { method: 'POST' } ); }";
  assert.deepEqual( bareSites( escaped ).map( s => s.url ), [ "'it\\'s /api/notifications/x'" ] );

  assert.deepEqual( bareSites( "fetch( '/api/notifications/open" ).map( s => s.line ), [ 1 ] );
  assert.deepEqual( bareSites( "fetch( `/api/notifications/${ open" ).map( s => s.line ), [ 1 ] );
  assert.deepEqual( bareSites( "fetch( [ '/api/notifications/open'" ).map( s => s.line ), [ 1 ] );

  // A URL built by a call inside the argument is still read whole, commas and all.
  assert.deepEqual( bareSites( "fetch( join( base, '/api/notifications/x' ), { method: 'POST' } )" ).map( s => s.line ), [ 1 ] );

  // An argument with no literal and no identifier has nothing left to resolve: read, not blind.
  assert.equal( fetchSites( "fetch( 42 )" )[ 0 ].resolved, true );
} );

test( "a variable chain deeper than the resolver follows is marked unread, not passed", () => {
  const chain = [
    "const d = '/api/notifications/deep';",
    "const c = d;",
    "const b = c;",
    "const a = b;",
    "async f() { await fetch( a ); }",
  ].join( "\n" );
  const [ site ] = fetchSites( chain );
  assert.equal( site.resolved, false, "three levels of indirection were reported as read" );
  assert.ok( !site.url.includes( ROUTE_MARK ), "the resolver followed past its stated depth" );
} );

test( "a blind site is explained only by a check that passes, and otherwise named", () => {
  const lines   = [ "class X {", "  async authedFetch( url ) {", "    return fetch( url );", "  }", "}" ];
  const wrapper = { line: 3, callee: "fetch", url: "url", resolved: false };
  const agents  = { line: 1, callee: "fetch", url: "agentSelect.AGENTS_ENDPOINT", resolved: false };
  const orphan  = { line: 1, callee: "fetch", url: "someParam", resolved: false };

  assert.equal( explainBlindSite( wrapper, lines, "" ), "the authedFetch wrapper's own fetch" );
  assert.equal( explainBlindSite( agents, [ "x" ], 'export const AGENTS_ENDPOINT = "/api/v2/agents";' ), "AGENTS_ENDPOINT is /api/v2/agents" );
  assert.equal( explainBlindSite( agents, [ "x" ], 'export const AGENTS_ENDPOINT = "/api/notifications/x";' ), null,
    "an agent endpoint pointing at a notification route was explained away" );
  assert.equal( explainBlindSite( agents, [ "x" ], "export const AGENTS_ENDPOINT = buildIt();" ), null,
    "a non-constant endpoint was explained away" );
  assert.equal( explainBlindSite( orphan, [ "x" ], "" ), null );
  assert.equal( describeSite( orphan ), "L1 fetch( someParam )" );
} );

// ---------------------------------------------------------------------------
// THE ARM THIS FILE EXISTS FOR
// ---------------------------------------------------------------------------

test( "every notifications.js call to a notification route is made through authedFetch", ( t ) => {
  const src   = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const found = notificationSites( src );
  t.diagnostic( `notification sites found: ${found.length}` );

  // 15 at the time of writing: the 9 calls to the formerly-anonymous routes, the
  // /response read, the two /api/notify posts, and three already on authedFetch. A floor,
  // not an equality — a new call is welcome, as long as it goes through the wrapper.
  assert.ok( found.length >= 15, `the scan found only ${found.length} notification sites — is it still reading the file?` );

  const bare = bareSites( src );
  assert.deepEqual(
    bare.map( describeSite ), [],
    "these calls reach a notification route without the refreshed credential",
  );
} );

test( "every bare fetch whose URL the scan could not read is proved not to be a notification call", () => {
  // The scan's blind spot is a URL it cannot read off the file. Each such bare fetch must be
  // explained by a check that runs, not by a name on a list: two exist today.
  const src         = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const blind       = fetchSites( src ).filter( s => !s.resolved && !s.callee.endsWith( "authedFetch" ) );
  const lines       = src.split( "\n" );
  const agentSelect = readFileSync( resolve( HERE, "../../../lupin_app/static/js/shared/agent-select.js" ), "utf8" );

  const unexplained = blind.filter( s => explainBlindSite( s, lines, agentSelect ) === null );

  assert.ok( blind.length > 0, "the blind-spot check found nothing to explain — is the scan still marking them?" );
  assert.deepEqual( unexplained.map( describeSite ), [] );
} );

test( "no call still carries the fake query-string key", () => {
  const src = readFileSync( NOTIFICATIONS_JS, "utf8" );
  assert.ok( !src.includes( "claude_code_simple_key" ), "the fake key is back in notifications.js" );
  assert.ok( !src.includes( "api_key=" ), "a query-string api_key is back in notifications.js" );
} );
