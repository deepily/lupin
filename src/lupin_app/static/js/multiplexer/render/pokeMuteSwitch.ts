/* c8 ignore next */ // tsx phantom-branch artifact on the file-header line.
// The stop poke switch (row 3526fb95): one toolbar button that shows whether the
// heartbeat Stop poke is on or muted fleet-wide, and lets an admin flip it.
//
// Rick's ruling: a plain on/off toggle with a simple indicator, admin role only, no
// timers. The server enforces the admin rule; this button only declines to offer a
// non-admin something that would be refused.
//
// The indicator always shows what the server said. A failed read paints "unknown"; a
// flip paints the state the server read back, not the one that was asked for.
//
// Legacy twin: notifications.js _paintPokeMute / refreshPokeMute / togglePokeMute. Same
// endpoint, same request body, same three faces.

/** The server's stop-poke state: whether it is muted, and who set it and when. */
export interface PokeMuteState {
  muted  : boolean;
  set_by : string | null;
  set_at : string | null;
}

// The two ApiClient verbs this needs; production passes the canonical ApiClient.
/** The two API calls the switch uses: `get` to read the state and `put` to change it. */
export interface PokeMuteApiLike {
  get<T>(path: string): Promise<T>;
  put<T>(path: string, body: unknown): Promise<T>;
}

/**
 * What the switch is built from.
 *
 * `isAdmin` decides whether the button is enabled. `onError` receives a failed read or flip.
 */
export interface PokeMuteSwitchOptions {
  api      : PokeMuteApiLike;
  isAdmin  : () => boolean;
  // Where a failed read or flip is reported. Production passes console.error.
  onError? : (message: string, error: unknown) => void;
}

/**
 * The switch's button, with `refresh` to read the state and `toggle` to flip it.
 *
 * Both resolve to the state the server reports, or null on failure.
 */
export interface PokeMuteSwitchHandle {
  element : HTMLButtonElement;
  refresh(): Promise<PokeMuteState | null>;
  toggle(): Promise<PokeMuteState | null>;
}

/** The endpoint that reads the stop-poke state (GET) and sets it (PUT). */
export const POKE_MUTE_PATH = "/api/heartbeat/poke-mute";

/**
 * Checks whether a value is an object with a boolean muted field.
 */
function isState( value: unknown ): value is PokeMuteState {
  return typeof value === "object" && value !== null
      && typeof ( value as { muted?: unknown } ).muted === "boolean";
}

/**
 * Build the stop-poke button.
 *
 * It shows the state the server last reported, or "unknown" if the read failed. It is created hidden,
 * because the skeleton-crew toggle in the Fleet Status pane now covers the same control.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the exported factory line; the body below is fully covered.
export function createPokeMuteSwitch( opts: PokeMuteSwitchOptions ): PokeMuteSwitchHandle {
  const onError = opts.onError ?? ( (): void => {} );

  const btn = document.createElement( "button" );
  btn.type      = "button";
  btn.className = "notifications-bounce-server notifications-poke-mute";
  btn.id        = "poke-mute";
  btn.setAttribute( "data-testid", "multiplexer-poke-mute" );
  // Row 6f72dc83: the skeleton crew toggle in the Fleet Status pane now mutes the poke, so
  // this separate control is hidden, not removed. Its paint and handlers stay, so a revert
  // is deleting this one line.
  btn.hidden    = true;

  function paint( state: unknown ): void {
    if ( !isState( state ) ) {
      btn.textContent   = "❔ Poke";
      btn.dataset.muted = "unknown";
      btn.disabled      = true;
      btn.title         = "Heartbeat stop poke: state unknown (could not reach the server)";
      return;
    }
    const admin = opts.isAdmin();
    const who   = state.set_by ? ` by ${state.set_by}` : "";
    const what  = state.muted ? `MUTED${who}` : "ON";
    const hint  = admin
      ? ( state.muted ? "Click to turn it back on." : "Click to mute it for the whole fleet." )
      : "Only an admin can change it.";

    btn.textContent   = state.muted ? "🔕 Poke muted" : "🔔 Poke on";
    btn.dataset.muted = String( state.muted );
    btn.disabled      = !admin;
    btn.title         = `Heartbeat stop poke: ${what}. ${hint}`;
  }

  async function refresh(): Promise<PokeMuteState | null> {
    try {
      const state = await opts.api.get<unknown>( POKE_MUTE_PATH );
      paint( state );
      return isState( state ) ? state : null;
    } catch ( error ) {
      onError( "[poke-mute] read failed", error );
      paint( null );
      return null;
    }
  }

  async function toggle(): Promise<PokeMuteState | null> {
    if ( btn.dataset.muted !== "true" && btn.dataset.muted !== "false" ) return null;
    const wanted = btn.dataset.muted !== "true";
    btn.disabled = true;
    try {
      const state = await opts.api.put<unknown>( POKE_MUTE_PATH, { muted: wanted } );
      paint( state );
      return isState( state ) ? state : null;
    } catch ( error ) {
      onError( "[poke-mute] flip refused or failed", error );
      return refresh();
    }
  }

  paint( null );
  btn.addEventListener( "click", () => void toggle() );
  return { element: btn, refresh, toggle };
}
