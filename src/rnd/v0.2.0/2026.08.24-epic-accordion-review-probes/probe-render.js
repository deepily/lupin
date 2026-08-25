// Render-path attack — STRING IN, STRING OUT. No DOM node is created, so no
// DOM node can appear on either side of an assert.
global.document = { readyState: "complete", addEventListener() {} };
global.window   = {};
const store = {};
global.localStorage = { getItem: k => ( k in store ? store[ k ] : null ), setItem: ( k, v ) => { store[ k ] = String( v ); }, removeItem: k => { delete store[ k ]; } };

const P = require( "./klass.js" ).prototype;
const ui = Object.assign( Object.create( P ), {
    EPIC_KEY_PREFIX:"epic:", EPIC_UNASSIGNED_KEY:"epic:unassigned", EPIC_ON_RICK_KEY:"__on_rick__",
    EPIC_DRIFT_KEY:"__drift__", EPIC_BLOCKER_OF_INTEREST:"rick",
    EPIC_BOARD_STATE_KEY:"lupin.epicBoard.groupState", TASK_TITLE_TRUNCATE_LEN:60,
    _epicStories:{}, log(){}, error(){}
} );
const call = ( m, ...a ) => P[ m ].apply( ui, a );

let fails = 0;
const check = ( n, ok, d ) => { console.log( ( ok ? "PASS  " : "FAIL  " ) + n + ( ok ? "" : "   -> " + String( d ).slice( 0, 300 ) ) ); if ( !ok ) fails++; };

const XSS = '<script>alert(1)</script>';

// hostile rows: script in title, in epic key, in status, in priority, in id
const rows = [
    { id: XSS, correlation_key: "epic:" + XSS, title: XSS, status: XSS, priority: XSS },
    { id: "b", correlation_key: null, title: '"><img src=x onerror=alert(1)>', status: "queued", priority: "P0" }
];
ui._epicStories = { [ "epic:" + XSS ]: { title: XSS, story: XSS } };

const model = call( "groupTasksByEpic", rows );
const html  = call( "renderEpicBoardTable", model, {} );

check( "r1 no raw <script> tag survives anywhere in the rendered HTML",
       !/<script/i.test( html ), html.match( /.{0,80}<script.{0,80}/i ) );
check( "r2 no raw onerror= handler survives", !/onerror=/i.test( html ), html.match( /.{0,80}onerror=.{0,80}/i ) );
check( "r3 the hostile text IS present, escaped (not silently dropped)",
       html.includes( "&lt;script&gt;" ), "escaped form missing" );

// drift renders even when EMPTY
const clean = call( "renderEpicBoardTable", call( "groupTasksByEpic", [ { id: "a", correlation_key: "epic:e" } ] ), {} );
check( "r4 drift section renders as a green all-clear when there is NO drift",
       clean.includes( "✅ No drift" ) && clean.includes( "epic-group-drift" ), "drift section vanished" );

// empty board
const empty = call( "renderEpicBoardTable", call( "groupTasksByEpic", [] ), {} );
check( "r5 zero rows still renders a table + the drift all-clear, no throw",
       empty.includes( "epic-board-table" ) && empty.includes( "✅ No drift" ), empty.slice( 0, 200 ) );

// collapse markup follows the choice map
const openState = { "epic:e": true };
const openHtml  = call( "renderEpicBoardTable", call( "groupTasksByEpic", [ { id: "a", correlation_key: "epic:e" } ] ), openState );
const shutHtml  = call( "renderEpicBoardTable", call( "groupTasksByEpic", [ { id: "a", correlation_key: "epic:e" } ] ), { "epic:e": false } );
check( "r6 a recorded OPEN choice renders expanded (aria-expanded=true, no .collapsed)",
       openHtml.includes( 'aria-expanded="true"' ) && !/epic-group[^"]*collapsed[^"]*"[^>]*data-epic="epic:e"/.test( openHtml ), "not expanded" );
check( "r7 a recorded CLOSED choice renders collapsed", shutHtml.includes( "collapsed" ), "not collapsed" );
check( "r8 NO recorded choice -> collapsed by default (plan §6)",
       call( "renderEpicBoardTable", call( "groupTasksByEpic", [ { id: "a", correlation_key: "epic:e" } ] ), {} ).includes( "collapsed" ), "default was open" );

// id slug collision: two different keys must not collide into one DOM id
const s1 = call( "_epicGroupIdSlug", "epic:a-b" );
const s2 = call( "_epicGroupIdSlug", "epic:a:b" );
check( "r9 NOTE distinct epic keys can collide into one element id", s1 !== s2, `${s1} vs ${s2}` );

console.log( "\nFAILURES: " + fails );
process.exit( fails === 0 ? 0 : 1 );
