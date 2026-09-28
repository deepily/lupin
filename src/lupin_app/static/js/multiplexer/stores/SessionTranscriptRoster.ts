/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Console tee — SessionTranscriptRoster (row 27760534, plan §4 "Roster and identity", slice 7).
//
// 🔴 THE CHIP CANNOT SUPPLY THE WATCH KEY, SO THE ROSTER IS THE JOIN. A seat chip is keyed on
// `sender_id` = `claude.code@<project>#<8hex>`, which carries only the first 8 hex characters
// of the seat's id. The console watches by the FULL `stable_session_id` (plan §3). So a chip
// is resolved against the admin roster (`/api/cc-transcript-roster`, a projection of the
// arbiter's fleet-state), and the roster row's full id is what the watch sends — never the
// chip's 8-hex (B4.4b).
//
// 🔴 AN 8-HEX PREFIX IS NOT UNIQUE BY CONSTRUCTION. Two live seats can share it, and a client
// that took the first prefix match would open the WRONG seat's console without a sound. So a
// prefix is only a candidate filter: the project must agree, and when more than one candidate
// survives the persona name must pick exactly one. Anything still ambiguous resolves to
// nothing, and the chip offers no console rather than a guess (B4.4c).
//
// Populations differ (plan §4): a chip can outlive its seat (no roster row → no affordance),
// and a seat that never sent a notification has no chip (accepted for v1, ruling OSQ-8).

import type { EventBus } from "../shared/EventBus";

export interface SessionTranscriptRosterApiClient {
  get<T>( path: string ): Promise<T>;
}

/** One roster row, as `/api/cc-transcript-roster` projects it. */
export interface TranscriptRosterRow {
  session_id           : string;
  persona?             : string | null;
  project?             : string | null;
  transcript_watchable : boolean;
}

/** What a chip knows about its seat. */
export interface TranscriptChipIdentity {
  senderId    : string;
  personaName : string | null;
}

export interface SessionTranscriptRoster {
  /** Re-read the roster. A non-admin never reads it — the endpoint would refuse anyway. */
  refresh(): Promise<void>;
  /** The chip's seat's FULL stable id, or null when it cannot be resolved to exactly one. */
  resolve( chip: TranscriptChipIdentity ): string | null;
  /** "ok" once a read landed, "unreachable" when the arbiter is down, null before any read. */
  status(): string | null;
  destroy(): void;
}

export interface SessionTranscriptRosterOptions {
  bus       : EventBus;
  api       : SessionTranscriptRosterApiClient;
  isAdmin   : () => boolean;
  endpoint? : string;
  logFn?    : ( message: string ) => void;
}

export const SESSION_TRANSCRIPT_ROSTER_ENDPOINT = "/api/cc-transcript-roster";

interface RosterBody {
  status? : unknown;
  seats?  : unknown;
}

/**
 * Split a chip's `sender_id` into its project and its 8-hex id prefix.
 *
 * Ensures:
 *   - returns null for anything not shaped `<who>@<project>#<hex>`
 *   - the prefix is lower-cased, so the comparison is on the id, not on its spelling
 */
export function parseSenderId( senderId: string ): { project: string; prefix: string } | null {
  const match = /^[^@#]+@([^#]+)#([0-9a-fA-F]+)$/.exec( senderId );
  if ( match === null ) return null;
  return { project : match[ 1 ] as string, prefix : ( match[ 2 ] as string ).toLowerCase() };
}

/**
 * Resolve a chip to exactly one watchable roster row's full id.
 *
 * Requires:
 *   - rows is the latest roster read
 *
 * Ensures:
 *   - returns a row's FULL `session_id`, never the chip's prefix
 *   - candidates are watchable rows whose id starts with the chip's prefix, in the chip's
 *     project (a row with no project is not excluded on that ground)
 *   - two or more candidates are narrowed by persona name, case-insensitively
 *   - returns null unless exactly one candidate remains — never a guess
 */
export function resolveTranscriptSeat(
  chip : TranscriptChipIdentity,
  rows : ReadonlyArray<TranscriptRosterRow>,
): string | null {
  const parsed = parseSenderId( chip.senderId );
  if ( parsed === null ) return null;

  let candidates = rows.filter( ( row ) =>
    row.transcript_watchable
    && row.session_id.toLowerCase().startsWith( parsed.prefix )
    && ( !row.project || row.project === parsed.project ) );

  if ( candidates.length > 1 && chip.personaName ) {
    const wanted = chip.personaName.toLowerCase();
    candidates   = candidates.filter( ( row ) => ( row.persona ?? "" ).toLowerCase() === wanted );
  }
  return candidates.length === 1 ? ( candidates[ 0 ] as TranscriptRosterRow ).session_id : null;
}

function rowsOf( value: unknown ): TranscriptRosterRow[] {
  if ( !Array.isArray( value ) ) return [];
  return value.filter( ( row ): row is TranscriptRosterRow =>
    typeof row === "object" && row !== null && typeof ( row as TranscriptRosterRow ).session_id === "string" );
}

class SessionTranscriptRosterImpl implements SessionTranscriptRoster {
  private readonly bus      : EventBus;
  private readonly api      : SessionTranscriptRosterApiClient;
  private readonly isAdmin  : () => boolean;
  private readonly endpoint : string;
  private readonly logFn    : ( message: string ) => void;
  private readonly unsubscribers: Array<() => void> = [];

  private rows        : TranscriptRosterRow[] = [];
  private statusValue : string | null = null;

  constructor( opts: SessionTranscriptRosterOptions ) {
    this.bus      = opts.bus;
    this.api      = opts.api;
    this.isAdmin  = opts.isAdmin;
    this.endpoint = opts.endpoint ?? SESSION_TRANSCRIPT_ROSTER_ENDPOINT;
    /* c8 ignore next */ // production-default fallback: a silent log; tests inject a collector.
    this.logFn    = opts.logFn ?? ( () => { /* silent by default */ } );

    // A seat that appears on the strip usually has just started, so its roster row is new too.
    this.unsubscribers.push(
      this.bus.on( "auth_success", () => { void this.refresh(); } ),
      this.bus.on<{ changeKind?: string }>( "store_session_strip_changed", ( e ) => {
        const kind = e.payload?.changeKind;
        if ( kind === "added" || kind === "hydrated" ) void this.refresh();
      } ),
    );
  }

  async refresh(): Promise<void> {
    if ( !this.isAdmin() ) return;
    let body: RosterBody;
    try {
      body = await this.api.get<RosterBody>( this.endpoint );
    } catch ( error ) {
      this.logFn( `SessionTranscriptRoster: roster read failed: ${ String( error ) }` );
      return;
    }
    this.statusValue = typeof body.status === "string" ? body.status : null;
    this.rows        = rowsOf( body.seats );
    this.bus.emit( {
      type    : "store_session_transcript_roster_changed",
      payload : { status : this.statusValue, seatCount : this.rows.length },
      source  : "SessionTranscriptRoster",
      ts      : Date.now(),
    } );
  }

  resolve( chip: TranscriptChipIdentity ): string | null {
    return resolveTranscriptSeat( chip, this.rows );
  }

  status(): string | null { return this.statusValue; }

  destroy(): void {
    for ( const off of this.unsubscribers ) off();
    this.unsubscribers.length = 0;
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on the exported factory line.
export function createSessionTranscriptRoster( opts: SessionTranscriptRosterOptions ): SessionTranscriptRoster {
  return new SessionTranscriptRosterImpl( opts );
}
