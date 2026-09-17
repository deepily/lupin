// THE TASK LIST PANE MUST READ AFTER A ROW WRITE — §6 item 18, row 645a7da5.
//
// 🔴 WHAT WAS WRONG. `HoldingAreaRenderer` wraps both row verbs in `rowWrite`,
// whose `done` awaits `refreshAfterWrite()` — a read guaranteed to have STARTED
// after the write. `TaskListRenderer` passed the SAME two verbs straight to the
// shared `taskRowController` with no wrapper and no read at all, so after a row
// mutation this pane showed whatever the last poll had fetched, for up to a full
// poll interval. One controller serves both panes and contains ZERO `refresh`
// occurrences: the entire difference is the two wiring lines.
//
// ⚠️ WHY THE OBVIOUS ASSERTION PROVES NOTHING HERE, AND THIS IS THE WHOLE
// DESIGN OF THIS FILE. `TaskListStore.patchTask` paints an OPTIMISTIC row before
// the PATCH is even sent. So "change the priority, assert the new priority is on
// screen" goes GREEN against the broken build — the optimistic clone put it
// there, and no read happened at all. A test that asserts the value the operator
// just typed is asserting the operator's own keystroke.
//
// ⇒ The discriminator is a SECOND row that the operator did not touch. The
// server's copy of row B changes (another seat, an agent, an approval landing);
// the optimistic path cannot know about it, because it merges only the fields of
// the row being edited. If the pane repaints with B's new title, a read happened.
// If it does not, the pane is stale — which is the defect, stated as a test.
//
// Driven through the REAL renderer, the REAL shared row controller, the REAL
// store and the REAL row template, clicking the REAL Update button. Only the
// ApiClient is faked, because it is the only thing that would reach the network.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/task_list_renderer_reads_after_a_row_write.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createTaskListRenderer } from "../../../../lupin_app/static/js/multiplexer/render/TaskListRenderer";
import { createTaskListStore } from "../../../../lupin_app/static/js/multiplexer/stores/TaskListStore";
import type { TaskItem } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );
beforeEach( () => { localStorage.clear(); } );

const FIXED_DATE = (): Date => new Date( "2026-09-17T16:00:00Z" );

const ROW_A = "aaaaaaaa-0000-0000-0000-00000000000a";
const ROW_B = "bbbbbbbb-0000-0000-0000-00000000000b";

/** The two rows as the server holds them at mount. */
function serverRows(): TaskItem[] {
  return [
    { id: ROW_A, title: "The row the operator edits",  status: "queued", owner_persona: "maya",  priority: "P2" },
    { id: ROW_B, title: "The row a PEER edits",        status: "queued", owner_persona: "maya",  priority: "P3" },
  ] as unknown as TaskItem[];
}

interface Harness {
  root        : HTMLElement;
  /** How many times the fake server was READ. */
  gets        : () => number;
  /** How many PATCHes it received. */
  patches     : () => number;
  /** Change the server's copy of a row, as a peer seat would. */
  serverEdit  : ( id: string, fields: Partial<TaskItem> ) => void;
  titles      : () => string[];
  prioritySelect : ( id: string ) => HTMLSelectElement;
  /** The TEXT the priority cell is showing — the selected option's own label. */
  priorityText   : ( id: string ) => string;
  updateButton   : ( id: string ) => HTMLButtonElement;
  settle      : () => Promise<void>;
  unmount     : () => void;
}

function mount(): Harness {
  const bus  = createEventBusForTesting();
  let rows   = serverRows();
  let gets   = 0;
  let patches = 0;

  const api = {
    get : async <T,>(): Promise<T> => {
      gets += 1;
      // A fresh deep copy each read, exactly as a real fetch gives: the store
      // must not be able to "see" a server edit by holding a shared reference.
      return { status: "", tasks: rows.map( ( t ) => ( { ...t } ) ), count: rows.length } as unknown as T;
    },
    patch : async <T,>( _path: string, body: unknown ): Promise<T> => {
      patches += 1;
      const fields = body as Record<string, unknown>;
      rows = rows.map( ( t ) => ( t.id === ROW_A
        ? { ...t, ...( fields.priority !== undefined ? { priority: String( fields.priority ) } : {} ) }
        : t ) );
      return {} as T;
    },
    post : async <T,>(): Promise<T> => ( {} as T ),
  };

  const store = createTaskListStore( {
    bus, api, endpoint: "/api/tasks",
    setIntervalFn : () => 0,          // NO POLLING — every read in this file is a read the write asked for
    clearIntervalFn : () => {},
    actorProvider : () => "maya",
  } );

  const renderer = createTaskListRenderer( {
    eventBus: bus, stores: { taskList: store }, nowDateFn: FIXED_DATE,
  } );
  const root = document.createElement( "div" );
  renderer.mount( root );
  // The first read. `setIntervalFn` above is inert, so this is the ONLY read
  // nobody asked for — every later one is a read some write went and took.
  store.startPolling();

  // ⚠️ RESOLVED BY THE CONTROL'S OWN `data-task-id`, NOT BY WALKING UP FROM THE
  // VISIBLE ROW. A disclosed task is THREE sibling <tr>s — the visible row, the
  // controls row and the error stripe — so `closest()` from the visible row can
  // never reach the select, which lives in the next <tr>.
  const control = <T extends Element>( sel: string, id: string ): T => {
    const el = root.querySelector<T>( `${ sel }[data-task-id="${ id }"]` );
    assert.notEqual( el, null, `${ sel } for row ${ id } is not on screen — the fixture never painted` );
    return el as T;
  };

  return {
    root,
    gets    : () => gets,
    patches : () => patches,
    serverEdit : ( id, fields ) => { rows = rows.map( ( t ) => ( t.id === id ? { ...t, ...fields } : t ) ); },
    titles  : () => Array.from( root.querySelectorAll( ".task-title" ) ).map( ( el ) => ( el.textContent ?? "" ).trim() ),
    prioritySelect : ( id ) => control<HTMLSelectElement>( "select.task-priority-select", id ),
    priorityText   : ( id ) => {
      const sel = control<HTMLSelectElement>( "select.task-priority-select", id );
      // ⚠️ THE SELECTED OPTION'S TEXT, NOT `select.value`. A value is a property the
      // template set; the text is what the operator can actually read off the row.
      return ( sel.selectedOptions[ 0 ]?.textContent ?? "" ).trim();
    },
    updateButton   : ( id ) => control<HTMLButtonElement>( "button.task-priority-update", id ),
    settle  : async () => { for ( let i = 0; i < 8; i += 1 ) await new Promise( ( r ) => setTimeout( r, 0 ) ); },
    unmount : () => renderer.unmount(),
  };
}

/** Stage a new priority on a row and click its Update button — the operator's real path. */
function editPriority( h: Harness, id: string, value: string ): void {
  const select = h.prioritySelect( id );
  assert.notEqual( select, null, "no priority select on this row" );
  select.value = value;
  select.dispatchEvent( new Event( "change", { bubbles: true } ) );
  const update = h.updateButton( id );
  assert.equal( update.disabled, false, "Update stayed disabled — the staged edit never registered" );
  update.click();
}

test( "positive control: the pane paints both rows and the edit really reaches the server", async () => {
  const h = mount();
  await h.settle();
  assert.deepEqual( h.titles(), [ "The row the operator edits", "The row a PEER edits" ],
    "without two painted rows, nothing below proves anything" );

  editPriority( h, ROW_A, "P0" );
  await h.settle();
  assert.equal( h.patches(), 1, "the Update button did not send a PATCH — the driver is broken, not the code" );
  h.unmount();
} );

test( "🔴 A ROW WRITE TAKES A READ — the peer's edit is on screen with no poll tick", async () => {
  const h = mount();
  await h.settle();
  const readsAfterMount = h.gets();

  // A peer changes row B server-side. The operator knows nothing about it and
  // touches only row A.
  h.serverEdit( ROW_B, { title: "The peer's NEW title" } as Partial<TaskItem> );

  editPriority( h, ROW_A, "P0" );
  await h.settle();

  assert.ok( h.gets() > readsAfterMount,
    "no read was taken after the write — the pane can only be showing the last poll's rows" );
  assert.ok( h.titles().includes( "The peer's NEW title" ),
    "the Task List pane is STALE after a row mutation: it still shows the pre-write board, "
    + "and will until the next poll tick. This is §6 item 18." );
  h.unmount();
} );

test( "the edited row itself shows the value the SERVER stored, not just the optimistic one", async () => {
  // Weaker than the test above on purpose — the optimistic paint alone satisfies
  // it — but it pins that routing the write through the read did not BREAK the
  // painted result, which is the regression a careless fix would introduce.
  const h = mount();
  await h.settle();

  editPriority( h, ROW_A, "P0" );
  await h.settle();

  assert.equal( h.priorityText( ROW_A ), "P0", "the edited row lost its new priority" );
  h.unmount();
} );
