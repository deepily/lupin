/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Lane C (v0.1.9 focus-bar parity, 2026-06-24) — BroadcastStore.
//
// Backing model for the "Broadcast to all CC sessions" compose card. Ports the
// data half of the legacy `broadcast-panel.js` (`recipientCache` + the
// persisted `notifications_broadcast_card_open` flag) into the multiplexer
// store idiom.
//
// Holds two pieces of state:
//   1. The recipient list — fetched from GET /api/commons/active-sessions
//      (the SAME endpoint the legacy panel reads). `hydrate(api)` replaces the
//      cache; the renderer decides WHEN to fetch (mount / ↻ refresh / on the
//      `store_session_strip_changed` persona-lifecycle signal). On a transport
//      failure the cache is cleared (parity with legacy's catch → `[]`) so the
//      Send button correctly disables and the chip-row shows the error state.
//   2. The card-open flag — persisted via StorageService (legacy parity:
//      collapse state survives reload). Default OPEN (legacy default-expanded).
//
// UNLIKE the other stores, BroadcastStore emits NO EventBus event: it has no
// live-WS update path (recipients arrive only via REST), and the
// BroadcastCardRenderer is its sole consumer + drives every repaint after
// awaiting `hydrate`. Recipient auto-refresh rides the EXISTING
// `store_session_strip_changed` event (SessionStripStore) — no new event type.

import type { StorageService } from "../shared/StorageService";

// ---------------------------------------------------------------------------
// Storage envelope
// ---------------------------------------------------------------------------

const STORAGE_KEY            = "broadcast:card-open";
const STORAGE_SCHEMA_VERSION = 1;
const DEFAULT_CARD_OPEN      = true;   // legacy broadcast card is default-expanded

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

// One recipient chip's backing data — the subset of the active-sessions
// projection the chip-row renders (server `project_session_response`:
// session_id / persona_name / persona_icon / persona_color / last_seen_iso /
// speakerphone_on). The store keeps only what the chips need.
export interface BroadcastRecipient {
  session_id     : string;
  persona_name?  : string | null;
  persona_icon?  : string | null;
  persona_color? : string | null;
}

// GET /api/commons/active-sessions response shape (`{ sessions: [...] }`).
interface ActiveSessionsResponse {
  sessions ?: ReadonlyArray<BroadcastRecipient>;
}

// The persisted card-open envelope payload.
interface CardOpenEnvelope {
  open : boolean;
}

// Loose ApiClient surface for hydrate — BroadcastStore only needs `get<T>`.
// Production passes the canonical ApiClient; tests pass a stub.
export interface BroadcastSessionsApiClient {
  get<T>(path: string): Promise<T>;
}

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

export interface BroadcastStore {
  /** Cached recipient list (defensive copy), in server order. */
  recipients(): ReadonlyArray<BroadcastRecipient>;
  /** Current persisted card-open state. */
  isCardOpen(): boolean;
  /** Persist + update the card-open state. */
  setCardOpen( open: boolean ): void;
  /**
   * Fetch GET /api/commons/active-sessions and replace the recipient cache.
   * Resolves once the cache is updated. On transport failure the cache is
   * cleared and the rejection propagates (caller floats + .catch, like
   * CommonsActivityRenderer).
   */
  hydrate( api: BroadcastSessionsApiClient ): Promise<void>;
}

export interface BroadcastStoreOptions {
  storage : StorageService;
}

// ---------------------------------------------------------------------------
// Implementation
// ---------------------------------------------------------------------------

const ACTIVE_SESSIONS_URL = "/api/commons/active-sessions";

class BroadcastStoreImpl implements BroadcastStore {
  private readonly storage : StorageService;

  private recipientCache : BroadcastRecipient[] = [];
  private cardOpen       : boolean;

  constructor( opts: BroadcastStoreOptions ) {
    this.storage  = opts.storage;
    this.cardOpen = this.hydrateCardOpen();
  }

  recipients(): ReadonlyArray<BroadcastRecipient> {
    return [ ...this.recipientCache ];   // defensive copy (Rachel nit-1) — callers never alias the cache
  }

  isCardOpen(): boolean {
    return this.cardOpen;
  }

  setCardOpen( open: boolean ): void {
    this.cardOpen = open;
    this.storage.setJSON<CardOpenEnvelope>( STORAGE_KEY, { open }, STORAGE_SCHEMA_VERSION );
  }

  async hydrate( api: BroadcastSessionsApiClient ): Promise<void> {
    try {
      const resp = await api.get<ActiveSessionsResponse>( ACTIVE_SESSIONS_URL );
      this.recipientCache = Array.isArray( resp.sessions ) ? [ ...resp.sessions ] : [];
    } catch ( err ) {
      // Parity with legacy fetchActiveSessions catch (recipientCache = []): a
      // failed load disables Send + surfaces the chip-row error state. Clear
      // the cache, THEN re-raise so the renderer can paint the failure.
      this.recipientCache = [];
      throw err;
    }
  }

  // -------------------------------------------------------------------------
  // Persistence
  // -------------------------------------------------------------------------

  private hydrateCardOpen(): boolean {
    const env = this.storage.getJSON<CardOpenEnvelope>( STORAGE_KEY, STORAGE_SCHEMA_VERSION );
    if ( env === null || typeof env.open !== "boolean" ) return DEFAULT_CARD_OPEN;
    return env.open;
  }
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createBroadcastStore( opts: BroadcastStoreOptions ): BroadcastStore {
  return new BroadcastStoreImpl( opts );
}
