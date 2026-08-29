// Degrade-path attack. NO real DOM: getElementById returns plain objects with
// textContent/innerHTML, so nothing here is a DOM node and no node can land in
// an assertion.
const els = {};
const fake = id => ( els[ id ] = els[ id ] || { id, textContent: "", innerHTML: "" } );

global.document = {
    readyState: "complete",
    addEventListener() {},
    getElementById: id => ( id === "epic-board-container" || id === "epic-board-count"
                            || id === "task-list-container" || id === "task-list-count"
                            || id === "epic-board-updated" ) ? fake( id ) : null,
    querySelectorAll: () => []
};
global.window = {};
global.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };

const P = require( "./klass.js" ).prototype;
const ui = Object.assign( Object.create( P ), {
    EPIC_KEY_PREFIX:"epic:", EPIC_UNASSIGNED_KEY:"epic:unassigned", EPIC_ON_RICK_KEY:"__on_rick__",
    EPIC_DRIFT_KEY:"__drift__", EPIC_BLOCKER_OF_INTEREST:"rick",
    EPIC_BOARD_STATE_KEY:"lupin.epicBoard.groupState", TASK_TITLE_TRUNCATE_LEN:60,
    _epicStories:{}, _epicBoardAccordionWired:true, _taskListLastGoodTasks:null,
    log(){}, error(){},
    _stampEpicBoardUpdated(){}, _stampTaskListUpdated(){}, _formatFleetTimestamp(){ return "x"; }
} );

let fails = 0;
const check = ( n, ok, d ) => { console.log( ( ok ? "PASS  " : "FAIL  " ) + n + ( ok ? "" : "   -> " + String( d ) ) ); if ( !ok ) fails++; };

const GOOD = { status: "ok", tasks: [
    { id: "1", correlation_key: "epic:a", status: "queued", priority: "P1", title: "t" },
    { id: "2", correlation_key: "epic:b", status: "queued", priority: "P1", title: "t" }
] };

// 1) a good render seeds the count
ui.renderEpicBoard( GOOD );
check( "g1 good render sets the epic count to the number of EPICS", fake( "epic-board-count" ).textContent === "2", fake( "epic-board-count" ).textContent );

// 2) now the store goes unreachable
ui.renderEpicBoard( { status: "unreachable", tasks: null } );
const bodyAfter  = fake( "epic-board-container" ).innerHTML;
const countAfter = fake( "epic-board-count" ).textContent;
console.log( `\n  after outage:  body = ${JSON.stringify( bodyAfter.slice( 0, 60 ) )}  count = "${countAfter}"` );
check( "g2 header count is reset when the pane is emptied by an outage",
       countAfter === "0", `pane is empty but the header still reads "${countAfter}"` );

// the sibling branches in the SAME method DO reset it — so this is an omission,
// not a policy.
ui.renderEpicBoard( GOOD );
ui.renderEpicBoard( { status: "auth_required" } );
check( "g3 (control) the auth_required branch DOES reset the count", fake( "epic-board-count" ).textContent === "0", fake( "epic-board-count" ).textContent );
ui.renderEpicBoard( GOOD );
ui.renderEpicBoard( { status: "query_unavailable" } );
check( "g4 (control) the query_unavailable branch DOES reset the count", fake( "epic-board-count" ).textContent === "0", fake( "epic-board-count" ).textContent );

console.log( "\nFAILURES: " + fails );
