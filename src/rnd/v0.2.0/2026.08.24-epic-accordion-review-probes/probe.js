// Adversarial probe — PURE logic only. No DOM, no happy-dom, no equality assert
// with a DOM node on either side. Feeds hostile input to the epic-board methods.

global.document = { readyState: "complete", addEventListener() {} };
global.window   = {};

const store = {};
global.localStorage = {
    getItem( k ) { return Object.prototype.hasOwnProperty.call( store, k ) ? store[ k ] : null; },
    setItem( k, v ) { store[ k ] = String( v ); },
    removeItem( k ) { delete store[ k ]; }
};

const NotificationsUI = require( "./klass.js" );
const P = NotificationsUI.prototype;

// Stub `this` — only the constants the epic methods read.
const ui = Object.assign( Object.create( P ), {
    EPIC_KEY_PREFIX          : "epic:",
    EPIC_UNASSIGNED_KEY      : "epic:unassigned",
    EPIC_ON_RICK_KEY         : "__on_rick__",
    EPIC_DRIFT_KEY           : "__drift__",
    EPIC_BLOCKER_OF_INTEREST : "rick",
    EPIC_BOARD_STATE_KEY     : "lupin.epicBoard.groupState",
    _epicStories             : {},
    log()   {},
    error() {}
} );

let fails = 0;
function check( name, fn ) {
    try {
        const r = fn();
        console.log( ( r === true ? "PASS  " : "FAIL  " ) + name + ( r === true ? "" : "   -> " + JSON.stringify( r ) ) );
        if ( r !== true ) fails++;
    } catch ( e ) {
        console.log( "THREW " + name + "   -> " + e );
        fails++;
    }
}

const call = ( m, ...a ) => P[ m ].apply( ui, a );

// ---------- (b) collapse-state persistence: shape + hostile input ----------
console.log( "\n== (b) collapse state ==" );

check( "b1 round-trip: toggle persists as a CHOICE MAP object", () => {
    store[ ui.EPIC_BOARD_STATE_KEY ] = undefined; delete store[ ui.EPIC_BOARD_STATE_KEY ];
    call( "toggleEpicCollapsed", "epic:seal-the-test-tier" );
    const raw = localStorage.getItem( ui.EPIC_BOARD_STATE_KEY );
    const p   = JSON.parse( raw );
    return raw === '{"epic:seal-the-test-tier":true}'
        && !Array.isArray( p ) && typeof p === "object" ? true : raw;
} );

check( "b2 survives reload: reload reads back the recorded choice", () => {
    const s = call( "loadEpicGroupState" );
    return s[ "epic:seal-the-test-tier" ] === true
        && call( "_epicGroupIsExpanded", "epic:seal-the-test-tier", s ) === true ? true : s;
} );

check( "b3 UNKNOWN key degrades to default, does not throw", () => {
    const s = call( "loadEpicGroupState" );
    return call( "_epicGroupIsExpanded", "epic:never-seen", s ) === false ? true : "expanded!";
} );

check( "b4 ARRAY payload rejected -> {} (not treated as a map)", () => {
    store[ ui.EPIC_BOARD_STATE_KEY ] = JSON.stringify( [ "epic:a", "epic:b" ] );
    const s = call( "loadEpicGroupState" );
    return ( !Array.isArray( s ) && Object.keys( s ).length === 0 ) ? true : s;
} );

check( "b5 garbled JSON -> {} , never throws", () => {
    store[ ui.EPIC_BOARD_STATE_KEY ] = "{not json";
    const s = call( "loadEpicGroupState" );
    return Object.keys( s ).length === 0 ? true : s;
} );

check( "b6 null payload -> {}", () => {
    store[ ui.EPIC_BOARD_STATE_KEY ] = "null";
    return Object.keys( call( "loadEpicGroupState" ) ).length === 0 ? true : "kept";
} );

check( "b7 non-boolean values dropped defensively", () => {
    store[ ui.EPIC_BOARD_STATE_KEY ] = JSON.stringify( { "epic:a": "yes", "epic:b": 1, "epic:c": true } );
    const s = call( "loadEpicGroupState" );
    return ( Object.keys( s ).length === 1 && s[ "epic:c" ] === true ) ? true : s;
} );

check( "b8 prototype-pollution key __proto__ does not corrupt", () => {
    store[ ui.EPIC_BOARD_STATE_KEY ] = '{"__proto__":true,"epic:z":false}';
    const s = call( "loadEpicGroupState" );
    return ( {} ).polluted === undefined ? true : "polluted";
} );

check( "b9 localStorage THROWS on read -> {} , never throws", () => {
    const orig = global.localStorage.getItem;
    global.localStorage.getItem = () => { throw new Error( "SecurityError" ); };
    let out;
    try { out = call( "loadEpicGroupState" ); } finally { global.localStorage.getItem = orig; }
    return Object.keys( out ).length === 0 ? true : out;
} );

check( "b10 localStorage THROWS on write -> save swallows, no throw", () => {
    const orig = global.localStorage.setItem;
    global.localStorage.setItem = () => { throw new Error( "QuotaExceeded" ); };
    try { call( "saveEpicGroupState", { "epic:a": true } ); } finally { global.localStorage.setItem = orig; }
    return true;
} );

check( "b11 on-Rick sentinel defaults OPEN, epics + drift default CLOSED", () => {
    return call( "_epicDefaultExpanded", "__on_rick__" ) === true
        && call( "_epicDefaultExpanded", "epic:anything" ) === false
        && call( "_epicDefaultExpanded", "__drift__" ) === false ? true : "wrong default";
} );

// ---------- (c) missing story entry must DE-SLUG, never error ----------
console.log( "\n== (c) missing story entry ==" );

ui._epicStories = {};
check( "c1 empty story map -> de-slugged label", () => {
    const l = call( "_epicTitleLabel", "epic:seal-the-test-tier" );
    return l === "seal the test tier" ? true : l;
} );

check( "c2 empty story map -> story text is empty string, not throw", () => {
    return call( "_epicStoryText", "epic:seal-the-test-tier" ) === "" ? true : "not empty";
} );

check( "c3 entry present but title BLANK -> falls back to de-slug", () => {
    ui._epicStories = { "epic:x-y": { title: "", story: "" } };
    const l = call( "_epicTitleLabel", "epic:x-y" );
    ui._epicStories = {};
    return l === "x y" ? true : l;
} );

check( "c4 entry is NULL -> de-slug, no throw", () => {
    ui._epicStories = { "epic:x-y": null };
    const l = call( "_epicTitleLabel", "epic:x-y" );
    ui._epicStories = {};
    return l === "x y" ? true : l;
} );

check( "c5 entry is a STRING (wrong shape) -> de-slug, no throw", () => {
    ui._epicStories = { "epic:x-y": "just a string" };
    const l = call( "_epicTitleLabel", "epic:x-y" );
    ui._epicStories = {};
    return l === "x y" ? true : l;
} );

check( "c6 grouping with ZERO stories still groups + never throws", () => {
    ui._epicStories = {};
    const m = call( "groupTasksByEpic", [
        { id: "a", correlation_key: "epic:no-story-at-all", title: "t", status: "queued", priority: "P1" },
        { id: "b", correlation_key: null, title: "t2", status: "queued", priority: "P2" }
    ] );
    return ( m.groups.length === 1 && m.drift.length === 1 && m.totalCount === 2 ) ? true : m;
} );

// ---------- (a)-adjacent + general degrade ----------
console.log( "\n== degrade / grouping ==" );

check( "d1 non-array input -> empty model, no throw", () => {
    const m = call( "groupTasksByEpic", null );
    return ( m.totalCount === 0 && m.groups.length === 0 && m.drift.length === 0 ) ? true : m;
} );

check( "d2 falsy rows collapse to drift, no throw", () => {
    const m = call( "groupTasksByEpic", [ null, undefined, 0, "" ] );
    return ( m.totalCount === 4 && m.drift.length === 4 ) ? true : m;
} );

check( "d3 cc-task: key counts as DRIFT not an epic", () => {
    const m = call( "groupTasksByEpic", [ { id: "a", correlation_key: "cc-task:123" } ] );
    return ( m.drift.length === 1 && m.groups.length === 0 ) ? true : m;
} );

check( "d4 epic:unassigned sorts LAST among epics", () => {
    const m = call( "groupTasksByEpic", [
        { id: "1", correlation_key: "epic:unassigned" },
        { id: "2", correlation_key: "epic:unassigned" },
        { id: "3", correlation_key: "epic:unassigned" },
        { id: "4", correlation_key: "epic:small" }
    ] );
    return m.groups[ m.groups.length - 1 ].epicKey === "epic:unassigned" ? true : m.groups.map( g => g.epicKey );
} );

check( "d5 waiting-on-Rick is a HIGHLIGHT, row ALSO stays in its epic", () => {
    const m = call( "groupTasksByEpic", [
        { id: "a", correlation_key: "epic:e", blocked_by: [ { kind: "user", id: "Rick" } ] }
    ] );
    return ( m.onRick.length === 1 && m.groups.length === 1 && m.groups[ 0 ].tasks.length === 1 ) ? true : m;
} );

check( "d6 blocked_by kind=persona ALSO counts (generator parity)", () => {
    const m = call( "groupTasksByEpic", [
        { id: "a", correlation_key: "epic:e", blocked_by: [ { kind: "persona", id: " rick " } ] }
    ] );
    return m.onRick.length === 1 ? true : m.onRick;
} );

check( "d7 blocked_by garbage (string/non-array/null members) -> no throw", () => {
    const m = call( "groupTasksByEpic", [
        { id: "a", correlation_key: "epic:e", blocked_by: "rick" },
        { id: "b", correlation_key: "epic:e", blocked_by: [ null, "rick", 7 ] }
    ] );
    return m.onRick.length === 0 ? true : m.onRick;
} );

console.log( "\nFAILURES: " + fails );
process.exit( fails === 0 ? 0 : 1 );
