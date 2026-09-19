/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Parity A-2 #8 (row c1bb2be7) — the Holding Area's flow-ratio gate: the header readout
// and the operator cluster.
//
// Ported from legacy notifications.html (#task-list-flow-ratio in the Holding Area
// header, and the #flow-ratio-controls cluster inside #holding-area-section) and from
// notifications.js _paintFlowRatioClause, _paintFlowRatioVerdict,
// _paintFlowRatioSettings, _paintManagerPull and _bindFlowRatioControls. The class
// names are legacy's: the multiplexer page links legacy task-list.css, which already
// styles them, `.flow-ratio-controls[hidden]` included.
//
// The cluster is built ONCE and its listeners bound ONCE, here, on elements this module
// made. Legacy needed a bound-flag because it bound from the tick.

import type { EventBus } from "../shared/EventBus";
import type { StoreFlowRatioChangedPayload } from "../shared/types";
import type { FlowRatioSettingsPatch } from "../stores/FlowRatioStore";
import {
  flowRatioIsOpen,
  flowRatioLongForm,
  flowRatioReadoutText,
  flowRatioSettingsUsable,
  flowRatioSourceLine,
  flowRatioThreshold,
  flowRatioWindowDays,
  type FlowRatioPayload,
  type FlowRatioSettings,
  type ManagerPullState,
} from "./flowRatioModel";

export interface FlowRatioStoreLike {
  ratio(): FlowRatioPayload | null;
  settings(): FlowRatioSettings | null;
  managerPull(): ManagerPullState | null;
  controlsMessage(): string | null;
  saveSettings( patch: FlowRatioSettingsPatch ): Promise<void>;
  saveManagerPull( disabled: boolean ): Promise<void>;
  resetSettings(): Promise<void>;
}

export interface FlowRatioPanel {
  /** The header readout. The caller places it after the count and the request badge. */
  readout  : HTMLSpanElement;
  /** The cluster, a `.section-content` so the pane's collapse hides it with the rows. */
  controls : HTMLDivElement;
  dispose(): void;
}

interface Els {
  threshold      : HTMLInputElement;
  thresholdValue : HTMLOutputElement;
  window         : HTMLInputElement;
  windowValue    : HTMLOutputElement;
  managerPull    : HTMLInputElement;
  reset          : HTMLButtonElement;
  status         : HTMLSpanElement;
}

function output( testid: string ): HTMLOutputElement {
  const o = document.createElement( "output" );
  o.setAttribute( "data-testid", testid );
  o.textContent = "—";
  return o;
}

function range( id: string, min: string, max: string, step: string, title: string ): HTMLInputElement {
  const r = document.createElement( "input" );
  r.type = "range";
  r.id = id;
  r.setAttribute( "data-testid", id );
  r.min = min;
  r.max = max;
  r.step = step;
  r.title = title;
  return r;
}

/** One `.flow-ratio-field`: a label holding its readout, then its slider, kept together on wrap. */
function field( labelText: string, forId: string, out: HTMLOutputElement, control: HTMLInputElement ): HTMLSpanElement {
  const span = document.createElement( "span" );
  span.className = "flow-ratio-field";
  const label = document.createElement( "label" );
  label.htmlFor = forId;
  label.append( `${labelText} `, out );
  span.append( label, control );
  return span;
}

/**
 * Build the cluster: hidden, and with no slider values, until settings arrive.
 *
 * ⚠️ THE CHECKBOX IS CHECKED IN THE MARKUP, AS LEGACY'S IS. Checked means the pull is
 * FROZEN, so an unreachable server cannot read as "pull is allowed".
 */
function buildControls(): { root: HTMLDivElement; els: Els } {
  const root = document.createElement( "div" );
  root.className = "section-content flow-ratio-controls";
  root.setAttribute( "data-testid", "multiplexer-flow-ratio-controls" );
  root.hidden = true;

  const thresholdValue = output( "multiplexer-flow-ratio-threshold-value" );
  const threshold = range( "multiplexer-flow-ratio-threshold", "0", "200", "10",
    "Percentage the create gate opens below, FLEET-WIDE — every project and every priority, not only this pane. "
    + "Higher = more permissive. At 0% nothing is below the threshold, so the gate never opens and every new ticket is refused." );
  const windowValue = output( "multiplexer-flow-ratio-window-value" );
  const windowEl = range( "multiplexer-flow-ratio-window", "1", "14", "1",
    "Days the ratio is counted over. The SAME board can pass at 1d and fail at 7d." );

  const pullField = document.createElement( "span" );
  pullField.className = "flow-ratio-field";
  const pullLabel = document.createElement( "label" );
  const managerPull = document.createElement( "input" );
  managerPull.type = "checkbox";
  managerPull.id = "multiplexer-manager-pull-toggle";
  managerPull.setAttribute( "data-testid", "multiplexer-manager-pull-toggle" );
  managerPull.checked = true;
  pullLabel.append( managerPull, " Freeze manager pull" );
  pullField.append( pullLabel );

  const reset = document.createElement( "button" );
  reset.type = "button";
  reset.setAttribute( "data-testid", "multiplexer-flow-ratio-reset" );
  reset.title = "Drop the saved override and use the configured defaults";
  reset.textContent = "Reset";

  const status = document.createElement( "span" );
  status.className = "flow-ratio-controls-status";
  status.setAttribute( "data-testid", "multiplexer-flow-ratio-controls-status" );

  root.append(
    field( "Gate opens below", threshold.id, thresholdValue, threshold ),
    field( "Window", windowEl.id, windowValue, windowEl ),
    pullField, reset, status,
  );
  return { root, els: { threshold, thresholdValue, window: windowEl, windowValue, managerPull, reset, status } };
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createFlowRatioPanel( opts: { bus: EventBus; store: FlowRatioStoreLike } ): FlowRatioPanel {
  const { bus, store } = opts;

  const readout = document.createElement( "span" );
  readout.className = "task-list-flow-ratio";
  readout.setAttribute( "data-testid", "multiplexer-flow-ratio" );

  const { root, els } = buildControls();

  // The settings body the sliders were last painted from. A tick that brings the SAME
  // body back must not repaint the sliders, or a drag in progress would jump.
  let paintedSettings: FlowRatioSettings | null = null;
  let paintedPull: ManagerPullState | null = null;

  const paintClause = ( provisionalDays?: number ): void => {
    readout.textContent = flowRatioReadoutText( store.ratio(), provisionalDays );
    readout.title       = flowRatioLongForm( store.ratio() );
  };

  const paintVerdict = ( provisionalThreshold?: number ): void => {
    const provisional = provisionalThreshold !== undefined;
    const threshold   = provisional ? provisionalThreshold : flowRatioThreshold( store.settings(), store.ratio() );
    const open        = flowRatioIsOpen( store.ratio(), threshold );
    readout.classList.toggle( "flow-ratio-open", open );
    readout.classList.toggle( "flow-ratio-closed", !open );
    readout.classList.toggle( "flow-ratio-preview", provisional );
  };

  const paintSettings = (): void => {
    const settings = store.settings();
    if ( !flowRatioSettingsUsable( settings ) ) {
      root.hidden = true;
      paintedSettings = null;
      return;
    }
    root.hidden = false;
    if ( settings !== paintedSettings ) {
      paintedSettings = settings;
      const pct  = Math.round( ( settings.allow_below as number ) * 100 );
      const days = flowRatioWindowDays( settings.window_hours ) as number;
      els.threshold.value            = String( pct );
      els.thresholdValue.textContent = `${pct}%`;
      els.window.value               = String( days );
      els.windowValue.textContent    = `${days}d`;
    }
    els.status.textContent = store.controlsMessage() ?? flowRatioSourceLine( settings );
  };

  const paintPull = (): void => {
    const pull = store.managerPull();
    // An unread state leaves the box as it is: checked, i.e. FROZEN, from the markup.
    if ( pull === null || pull === paintedPull ) return;
    paintedPull = pull;
    els.managerPull.checked = pull.disabled === true;
  };

  const paintAll = (): void => {
    paintClause();
    paintVerdict();
    paintSettings();
    paintPull();
  };

  // 🔴 WRITES ARE ON `change`, NEVER `input`. `input` fires continuously while a handle
  // moves; it previews only — the colour against the dragged threshold, "recounting…"
  // against the dragged window — and says nothing to the server.
  els.threshold.addEventListener( "input", () => {
    const pct = Number( els.threshold.value );
    els.thresholdValue.textContent = `${pct}%`;
    paintVerdict( pct / 100 );
  } );
  els.threshold.addEventListener( "change", () => {
    void store.saveSettings( { allow_below: Number( els.threshold.value ) / 100 } );
  } );
  els.window.addEventListener( "input", () => {
    els.windowValue.textContent = `${els.window.value}d`;
    paintClause( Number( els.window.value ) );
  } );
  els.window.addEventListener( "change", () => {
    void store.saveSettings( { window_hours: Number( els.window.value ) * 24 } );
  } );
  els.managerPull.addEventListener( "change", () => {
    void store.saveManagerPull( els.managerPull.checked );
  } );
  els.reset.addEventListener( "click", () => {
    void store.resetSettings();
  } );

  // A write's answer, or the re-read after a failed write, is a NEW settings body, so the
  // sliders repaint from it. A tick keeps the body it already holds, so they do not.
  const off = bus.on<StoreFlowRatioChangedPayload>( "store_flow_ratio_changed", () => paintAll() );

  paintAll();
  return { readout, controls: root, dispose: off };
}
