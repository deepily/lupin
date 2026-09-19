// Parity A-2 #8 (row c1bb2be7) — the flow-ratio gate mounted in the Holding Area: the
// readout after the count, the operator cluster above the rows, the truncation banner
// leading them. Legacy: the #task-list-flow-ratio readout, notifications.html:968-970,
// and the cluster inside #holding-area-section, notifications.html:1003-1077.
// Behaviour from these methods (unnamed in io/phase2/A9.md): _paintFlowRatioClause ·
// _paintFlowRatioVerdict · _paintFlowRatioSettings · _paintManagerPull ·
// _bindFlowRatioControls. io/phase2/A9.md rows B7, H11, H12.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createHoldingAreaRenderer } from "../../../../lupin_app/static/js/multiplexer/render/HoldingAreaRenderer";
import type { FlowRatioStoreLike } from "../../../../lupin_app/static/js/multiplexer/render/flowRatioPanel";
import type { FlowRatioPayload, FlowRatioSettings, ManagerPullState } from "../../../../lupin_app/static/js/multiplexer/render/flowRatioModel";
import type { FlowRatioSettingsPatch } from "../../../../lupin_app/static/js/multiplexer/stores/FlowRatioStore";
import type { TaskListComposite } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const RATIO: FlowRatioPayload    = { created: 12, closed: 10, ratio: 1.2, close_needed: 2, window_hours: 24, allow_below: 1 };
const SETTINGS: FlowRatioSettings = { allow_below: 1, window_hours: 24, window_source: "config", threshold_source: "config" };

interface FakeFlow extends FlowRatioStoreLike {
  r : FlowRatioPayload | null;
  s : FlowRatioSettings | null;
  p : ManagerPullState | null;
  m : string | null;
  saves  : FlowRatioSettingsPatch[];
  pulls  : boolean[];
  resets : number;
}

function mount( opts: { composite?: TaskListComposite | null; withFlow?: boolean } = {} ) {
  const bus = createEventBusForTesting();
  const flow: FakeFlow = {
    r: null, s: null, p: null, m: null, saves: [], pulls: [], resets: 0,
    ratio           : () => flow.r,
    settings        : () => flow.s,
    managerPull     : () => flow.p,
    controlsMessage : () => flow.m,
    saveSettings    : async ( patch ) => { flow.saves.push( patch ); },
    saveManagerPull : async ( d ) => { flow.pulls.push( d ); },
    resetSettings   : async () => { flow.resets += 1; },
  };
  const composite = opts.composite === undefined ? { tasks: [], count: 0, total: 0 } : opts.composite;
  const renderer = createHoldingAreaRenderer( {
    eventBus : bus,
    store    : {
      composite         : () => composite,
      refresh           : async () => {},
      refreshAfterWrite : async () => {},
      transitionTask    : async () => ( { ok: true } ),
      patchTask         : async () => ( { ok: true } ),
    },
    ...( opts.withFlow === false ? {} : { flowRatio: flow } ),
  } );
  const root = document.createElement( "section" );
  renderer.mount( root );
  const q = ( id: string ) => root.querySelector( `[data-testid="${id}"]` ) as HTMLElement | null;
  const els = {
    readout        : q( "multiplexer-flow-ratio" )!,
    controls       : q( "multiplexer-flow-ratio-controls" )!,
    threshold      : q( "multiplexer-flow-ratio-threshold" ) as HTMLInputElement,
    thresholdValue : q( "multiplexer-flow-ratio-threshold-value" )!,
    window         : q( "multiplexer-flow-ratio-window" ) as HTMLInputElement,
    windowValue    : q( "multiplexer-flow-ratio-window-value" )!,
    pull           : q( "multiplexer-manager-pull-toggle" ) as HTMLInputElement,
    reset          : q( "multiplexer-flow-ratio-reset" )!,
    status         : q( "multiplexer-flow-ratio-controls-status" )!,
    count          : q( "multiplexer-holding-area-count" )!,
    container      : q( "multiplexer-holding-area-container" )!,
  };
  const changed = (): void => bus.emit( { type: "store_flow_ratio_changed", payload: {}, source: "test", ts: 0 } );
  return { root, renderer, flow, els, q, changed };
}

test( "the readout follows the count in the header; the cluster sits between the header and the rows", () => {
  const { els } = mount();
  assert.ok( els.readout.previousElementSibling === els.count, "count · Gate, as legacy's <h3>" );
  assert.ok( els.controls.nextElementSibling === els.container, "above the rows" );
  assert.ok( els.controls.classList.contains( "section-content" ), "the pane's collapse hides it" );
  assert.ok( els.readout.classList.contains( "task-list-flow-ratio" ), "legacy's class, legacy's styling" );
} );

test( "the cluster is hidden, the checkbox CHECKED (frozen) and the sliders unset, until settings arrive (html:1003-1004)", () => {
  const { els, flow, changed } = mount();
  assert.equal( els.controls.hidden, true );
  assert.equal( els.pull.checked, true, "unreachable must not read as 'pull is allowed'" );
  assert.equal( els.thresholdValue.textContent, "—" );
  assert.equal( els.readout.textContent, "", "no ratio, no clause" );

  flow.s = { allow_below: 1 };                  // unusable
  changed();
  assert.equal( els.controls.hidden, true );
} );

test( "a paint sets both sliders, their readouts and the source line (_paintFlowRatioSettings)", () => {
  const { els, flow, changed } = mount();
  flow.s = { ...SETTINGS, window_hours: 168 };
  changed();
  assert.equal( els.controls.hidden, false );
  assert.equal( els.threshold.value, "100" );
  assert.equal( els.thresholdValue.textContent, "100%" );
  assert.equal( els.window.value, "7" );
  assert.equal( els.windowValue.textContent, "7d" );
  assert.equal( els.status.textContent, "from config" );

  flow.s = { ...SETTINGS, threshold_source: "override" };
  changed();
  assert.equal( els.status.textContent, "saved override" );
  flow.m = "not saved — admin only";
  changed();
  assert.equal( els.status.textContent, "not saved — admin only", "a write's message outranks the source line" );
} );

test( "the readout text, hover and colour; the colour holds without settings (defect 5)", () => {
  const { els, flow, changed } = mount();
  flow.r = RATIO;
  changed();
  assert.equal( els.readout.textContent, " · Gate: 12 created / 10 closed  over 1d = 120%  · CLOSE 2" );
  assert.ok( els.readout.title.startsWith( "Closed vs New Ratio — " ) );
  assert.ok( els.readout.classList.contains( "flow-ratio-closed" ), "1.2 is not below the payload's own 1.0" );
  assert.ok( !els.readout.classList.contains( "flow-ratio-open" ) );

  flow.s = { ...SETTINGS, allow_below: 1.5 };
  changed();
  assert.ok( els.readout.classList.contains( "flow-ratio-open" ), "the settings' threshold wins once usable" );
} );

test( "threshold: input previews the colour only; change saves the fraction once (_bindFlowRatioControls)", () => {
  const { els, flow, changed } = mount();
  flow.r = RATIO;
  flow.s = SETTINGS;
  changed();
  els.threshold.value = "150";
  els.threshold.dispatchEvent( new Event( "input" ) );
  assert.equal( els.thresholdValue.textContent, "150%" );
  assert.ok( els.readout.classList.contains( "flow-ratio-open" ) && els.readout.classList.contains( "flow-ratio-preview" ) );
  assert.deepEqual( flow.saves, [], "input never writes" );
  els.threshold.dispatchEvent( new Event( "change" ) );
  assert.deepEqual( flow.saves, [ { allow_below: 1.5 } ] );
} );

test( "window: input shows 'recounting…' against the new window; change saves hours", () => {
  const { els, flow, changed } = mount();
  flow.r = RATIO;
  flow.s = SETTINGS;
  changed();
  els.window.value = "5";
  els.window.dispatchEvent( new Event( "input" ) );
  assert.equal( els.windowValue.textContent, "5d" );
  assert.equal( els.readout.textContent, " · Gate: recounting…  over 5d" );
  assert.ok( !els.readout.classList.contains( "flow-ratio-preview" ), "the window preview is text, not colour" );
  els.window.dispatchEvent( new Event( "change" ) );
  assert.deepEqual( flow.saves, [ { window_hours: 120 } ] );
} );

test( "a tick bringing back the SAME settings body does not move a slider being dragged", () => {
  const { els, flow, changed } = mount();
  flow.s = SETTINGS;
  changed();
  els.threshold.value = "40";                    // the operator's finger is here
  changed();                                     // a tick, same body
  assert.equal( els.threshold.value, "40" );
  flow.s = { ...SETTINGS };                      // a write's answer: a new body
  changed();
  assert.equal( els.threshold.value, "100", "the server's answer repaints" );
} );

test( "manager pull: change writes the box; the box follows the server; an unread state leaves it", () => {
  const { els, flow, changed } = mount();
  els.pull.checked = false;
  els.pull.dispatchEvent( new Event( "change" ) );
  assert.deepEqual( flow.pulls, [ false ] );

  flow.p = { disabled: true };
  changed();
  assert.equal( els.pull.checked, true );
  els.pull.checked = false;                      // an identical tick must not undo a click
  changed();
  assert.equal( els.pull.checked, false );
  flow.p = { disabled: false };
  changed();
  assert.equal( els.pull.checked, false );
  flow.p = null;
  changed();
  assert.equal( els.pull.checked, false, "null leaves the box alone" );
} );

test( "Reset calls the reset", () => {
  const { els, flow } = mount();
  els.reset.dispatchEvent( new Event( "click" ) );
  assert.equal( flow.resets, 1 );
} );

test( "the truncation banner leads the rows, fed the pane's own query; a sentinel shows none", () => {
  const cut = mount( { composite: { tasks: [], count: 0, total: 40 } } );
  const first = cut.els.container.firstElementChild!;
  assert.equal( first.textContent, "✂️ Board truncated: showing 0 of 40 — 40 not displayed." );
  assert.ok( first.nextElementSibling !== null && first.nextElementSibling.classList.contains( "holding-area-empty" ),
    "the banner leads the empty message" );

  const down = mount( { composite: { status: "unreachable" } } );
  assert.equal( down.els.container.querySelectorAll( ".task-list-truncated" ).length, 0 );
} );

test( "unmount stops painting; a pane built without the store has no readout and no cluster", () => {
  const { renderer, flow, els, changed } = mount();
  renderer.unmount();
  flow.s = SETTINGS;
  changed();
  assert.equal( els.controls.hidden, true );

  const bare = mount( { withFlow: false } );
  assert.ok( bare.q( "multiplexer-flow-ratio" ) === null, "no readout" );
  assert.ok( bare.q( "multiplexer-flow-ratio-controls" ) === null, "no cluster" );
} );
