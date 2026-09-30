/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Parity A-2 #8 (row c1bb2be7) — the Holding Area's flow-ratio gate: pure formatting.
//
// Ported line for line from legacy notifications.js: _formatFlowRatio,
// _flowRatioRoomText, _flowRatioPercentText, _flowRatioWindowDays, _flowRatioLongForm
// and _flowRatioIsOpen (the methods just above fetchFlowRatio). No DOM, no fetch:
// the store holds the payloads and the renderer paints them.

/** The body of GET /api/tasks/flow-ratio. Optional fields: this is what the server SENT. */
export interface FlowRatioPayload {
  created?      : number;
  closed?       : number;
  ratio?        : number | null;
  close_needed? : number;
  room_for?     : number;
  window_hours? : number;
  allow_below?  : number;
  verdict?      : string;
}

/** The body of GET/PATCH/DELETE /api/tasks/flow-ratio/settings. */
export interface FlowRatioSettings {
  window_hours?     : number;
  allow_below?      : number;
  window_source?    : string;
  threshold_source? : string;
}

/** The body of GET/PATCH /api/tasks/manager-pull. `disabled` true = the pull is FROZEN. */
export interface ManagerPullState {
  disabled? : boolean;
  source?   : string;
}

const isNum = ( v: unknown ): v is number => typeof v === "number" && Number.isFinite( v );

/** Whole days for a window in hours, never below 1; null for an unusable window. */
export function flowRatioWindowDays( hours: unknown ): number | null {
  if ( !isNum( hours ) || hours <= 0 ) return null;
  return Math.max( 1, Math.round( hours / 24 ) );
}

/** The percent, or ∞ when nothing closed but something was created, or — when neither. */
export function flowRatioPercentText( payload: FlowRatioPayload ): string {
  if ( isNum( payload.ratio ) ) return `${Math.round( payload.ratio * 100 )}%`;
  return isNum( payload.created ) && payload.created > 0 ? "∞" : "—";
}

/**
 * The room clause, read from the payload and never computed here.
 *
 * ⚠️ `room_for`, NOT `headroom`. Being one lower than headroom is Rick's ruling,
 * and it is what makes FULL reachable.
 */
export function flowRatioRoomText( payload: FlowRatioPayload ): string {
  if ( isNum( payload.close_needed ) && payload.close_needed > 0 ) return `  · CLOSE ${payload.close_needed}`;
  if ( isNum( payload.room_for ) && payload.room_for > 0 ) return `  · Room for ${payload.room_for} more`;
  if ( payload.room_for === 0 ) return "  · FULL";
  return "";
}

/**
 * The clause after "Gate: ", or "" when the payload is unusable.
 *
 * With `provisionalDays` (the window slider mid-drag) the counts and percent are
 * WITHHELD: they belong to the old window, and printing them beside the new one
 * would show numbers the server never computed for it.
 */
export function formatFlowRatio( payload: FlowRatioPayload | null, provisionalDays?: number ): string {
  if ( payload === null || typeof payload !== "object" ) return "";
  const provisional = isNum( provisionalDays );
  const days        = provisional ? provisionalDays : flowRatioWindowDays( payload.window_hours );
  if ( days === null ) return "";
  if ( provisional ) return `recounting…  over ${days}d`;
  const counts = ( isNum( payload.created ) && isNum( payload.closed ) )
    ? `${payload.created} created / ${payload.closed} closed  over ` : "";
  return `${counts}${days}d = ${flowRatioPercentText( payload )}${flowRatioRoomText( payload )}`;
}

/** The readout's full text: " · Gate: <clause>", or "" to omit it. */
export function flowRatioReadoutText( payload: FlowRatioPayload | null, provisionalDays?: number ): string {
  const clause = formatFlowRatio( payload, provisionalDays );
  return clause ? ` · Gate: ${clause}` : "";
}

/** The hover text, carrying the scope caveat the short form has no room for. */
export function flowRatioLongForm( payload: FlowRatioPayload | null ): string {
  if ( payload === null || typeof payload !== "object" || !isNum( payload.window_hours ) ) return "";
  const clause = formatFlowRatio( payload );
  return clause
    ? `Closed vs New Ratio — ${clause}\nCounts creation across EVERY project and priority, not only this pane.`
    : "";
}

/** Whether the gate is open. Exactly at the threshold reads CLOSED (strict `<`). */
export function flowRatioIsOpen( payload: FlowRatioPayload | null, threshold: number ): boolean {
  if ( !isNum( threshold ) ) return true;
  if ( payload === null || !isNum( payload.ratio ) ) {
    return !( payload !== null && isNum( payload.created ) && payload.created > 0 );
  }
  return payload.ratio < threshold;
}

/** Whether a settings body carries both numbers the controls paint from. */
export function flowRatioSettingsUsable( settings: FlowRatioSettings | null ): settings is FlowRatioSettings {
  return settings !== null && isNum( settings.allow_below ) && isNum( settings.window_hours );
}

/**
 * The threshold the readout's colour is judged against.
 *
 * 🔴 FIXED FROM LEGACY (defect 5): legacy judged against the settings' threshold
 * only, which is undefined until the settings arrive, and an undefined threshold
 * reads OPEN, so the gate painted green on the first tick and stayed green if the
 * settings never loaded, whatever the ratio said. The ratio payload carries the
 * same `allow_below`, so it is the fallback.
 */
export function flowRatioThreshold( settings: FlowRatioSettings | null, payload: FlowRatioPayload | null ): number {
  if ( flowRatioSettingsUsable( settings ) ) return settings.allow_below as number;
  if ( payload !== null && isNum( payload.allow_below ) ) return payload.allow_below;
  return Number.NaN;
}

/** The controls' status line when no action has spoken: where the numbers came from. */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line: the never-run CJS export annotation `0&&(module.exports=…)` maps onto the last function.
export function flowRatioSourceLine( settings: FlowRatioSettings ): string {
  return settings.window_source === "override" || settings.threshold_source === "override"
    ? "saved override" : "from config";
}
