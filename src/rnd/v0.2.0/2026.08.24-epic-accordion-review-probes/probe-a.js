// (a) ONE FETCH, ONE CLOCK — attacked by COUNTING requests at the transport,
// not by trusting the comment. Real fetchTaskList + real fetchEpicStories +
// real refreshTaskList; only authedFetch and the two DOM renderers are stubbed.

global.document = { readyState: "complete", addEventListener() {} };
global.window   = { LUPIN_TASK_LIST_QUERY: "/api/tasks?limit=500&unscoped_audit=true&hide_parked=false&char_budget=0" };
global.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };

const NotificationsUI = require( "./klass.js" );
const P = NotificationsUI.prototype;

const hits = [];   // every URL that reaches the transport

const ui = Object.assign( Object.create( P ), {
    EPIC_KEY_PREFIX          : "epic:",
    EPIC_UNASSIGNED_KEY      : "epic:unassigned",
    EPIC_ON_RICK_KEY         : "__on_rick__",
    EPIC_DRIFT_KEY           : "__drift__",
    EPIC_BLOCKER_OF_INTEREST : "rick",
    EPIC_BOARD_STATE_KEY     : "lupin.epicBoard.groupState",
    _epicStories             : {},
    _epicStoriesFetched      : false,
    _taskListFetchInFlight   : false,
    TASK_LIST_POLL_INTERVAL_MS : 60000,
    log()   {},
    error() {},
    // transport stub — records, then answers plausibly
    async authedFetch( url ) {
        hits.push( url );
        if ( url.startsWith( "/api/epic-stories" ) ) {
            return { ok: true, status: 200, json: async () => ( { stories: {} } ) };
        }
        return { ok: true, status: 200, json: async () => ( { status: "ok", tasks: [
            { id: "a", correlation_key: "epic:one", title: "t", status: "queued", priority: "P1" }
        ] } ) };
    },
    // DOM renderers stubbed OUT — the point is transport counting, and a real
    // renderer would need a DOM (which is exactly what we are told not to walk).
    renderedTaskList  : 0,
    renderedEpicBoard : 0,
    renderTaskList()  { this.renderedTaskList++;  },
    renderEpicBoard() { this.renderedEpicBoard++; }
} );

let fails = 0;
const check = ( name, ok, detail ) => {
    console.log( ( ok ? "PASS  " : "FAIL  " ) + name + ( ok ? "" : "   -> " + JSON.stringify( detail ) ) );
    if ( !ok ) fails++;
};

( async () => {
    const tasksHits   = () => hits.filter( u => u.startsWith( "/api/tasks" ) ).length;
    const storiesHits = () => hits.filter( u => u.startsWith( "/api/epic-stories" ) ).length;

    await ui.refreshTaskList();
    check( "a1 one refresh cycle -> exactly ONE /api/tasks request", tasksHits() === 1, hits );
    check( "a2 both panes rendered off that ONE fetch",
           ui.renderedTaskList === 1 && ui.renderedEpicBoard === 1,
           { t: ui.renderedTaskList, e: ui.renderedEpicBoard } );

    await ui.refreshTaskList();
    await ui.refreshTaskList();
    check( "a3 three cycles -> exactly THREE /api/tasks requests (1:1, no doubling)", tasksHits() === 3, hits );
    check( "a4 epic-stories is a ONE-SHOT, not a poll (still 1 after 3 cycles)", storiesHits() === 1, hits );
    check( "a5 epic board rendered every cycle off the shared composite", ui.renderedEpicBoard === 3, ui.renderedEpicBoard );

    // How many timers exist against this endpoint? Count them for real.
    const realSetInterval = global.setInterval;
    const timers = [];
    global.setInterval = ( fn, ms ) => { timers.push( ms ); return { fake: true }; };
    ui.taskListPollIntervalHandle = null;
    ui.startTaskListPolling();
    global.setInterval = realSetInterval;
    // startTaskListPolling fires an un-awaited immediate refresh; let it settle
    // before the next check, or the in-flight debounce eats the following cycle.
    while ( ui._taskListFetchInFlight ) await new Promise( r => setImmediate( r ) );
    check( "a6 startTaskListPolling installs exactly ONE timer", timers.length === 1, timers );
    check( "a7 that timer is the 60s task-list poll", timers[ 0 ] === 60000, timers );

    // Does the epic board own any timer/fetch entry point of its own?
    const proto = Object.getOwnPropertyNames( P ).filter( n => /epic/i.test( n ) );
    const epicFetchers = proto.filter( n => /^fetch|^refresh|^start.*Poll/i.test( n ) );
    check( "a8 epic board exposes NO refresh/poll entry point of its own — only the one-shot story fetch",
           epicFetchers.length === 1 && epicFetchers[ 0 ] === "fetchEpicStories", epicFetchers );

    // Break it: make the story endpoint hard-fail and confirm the shared clock survives.
    ui._epicStoriesFetched = false;
    ui._epicStories = {};
    const good = ui.authedFetch;
    ui.authedFetch = async function ( url ) {
        hits.push( url );
        if ( url.startsWith( "/api/epic-stories" ) ) throw new Error( "ECONNREFUSED" );
        return good.call( ui, url );
    };
    const before = ui.renderedEpicBoard;
    await ui.refreshTaskList();
    check( "a9 story endpoint DOWN -> refresh still completes and still renders both panes",
           ui.renderedEpicBoard === before + 1, ui.renderedEpicBoard );
    check( "a10 a DOWN story endpoint is not retried every cycle (memoized failure)",
           ( await ( async () => { const s = storiesHits(); await ui.refreshTaskList(); return storiesHits() === s; } )() ), hits );

    console.log( "\nrequests seen: " + JSON.stringify( hits.reduce( ( m, u ) => { const k = u.split( "?" )[ 0 ]; m[ k ] = ( m[ k ] || 0 ) + 1; return m; }, {} ) ) );
    console.log( "FAILURES: " + fails );
    process.exit( fails === 0 ? 0 : 1 );
} )();
