/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer — AckStore (row 4f320c27 M1).
//
// The per-broadcast acknowledgement tally: which seats acked a user broadcast,
// with what status. Ports the tally half of the legacy `broadcast-panel.js`
// (`activeAggregate.receivedAcks`), which the multiplexer never received —
// BroadcastStore ported only the COMPOSE half.
//
// TWO SOURCES, ONE FOLD:
//   1. LIVE — `commons_broadcast_ack` bus events, re-emitted by NotificationStore
//      after it intercepts the frame BEFORE normalize(). The server sends an ack
//      with `message: ""` and the identity in `payload`, and normalize() both
//      rejects an empty message and drops raw-only fields, so the intercept is
//      the only way the payload survives.
//   2. HYDRATED — GET /api/notifications/broadcast-acks/{broadcast_id}, the
//      persisted rows. This is what makes the tally SURVIVE A RELOAD, which is
//      the entire point of the server half: before it, closing the page lost the
//      acks outright.
//
// 🔴 LATEST-PER-SESSION, AND THE RULE MUST MATCH THE SERVER'S. A seat re-acks when
// its status changes (pending, then completed), so a tally that appended would
// count that seat twice. Keying by `session_id` collapses it — the same rule
// `NotificationRepository.get_latest_acks_for_broadcast` applies server-side. If
// the two ever disagree, a reload silently CHANGES the tally, which is worse than
// either rule alone: the number would be stable until the moment it was reloaded.
// Legacy keyed its Map by session_id for the same reason (broadcast-panel.js
// handleAck), so all three agree.
//
// An ack with NO session_id is kept under a per-ack synthetic key rather than
// collapsed with every other unattributed ack — they are unattributable, not
// duplicates of each other. Same choice the server's fold makes.

import type { EventBus } from "../shared/EventBus";
import {
  COMMONS_BROADCAST_ACK_TYPE,
  type BroadcastAckPayload,
  type StoreBroadcastAcksChangedPayload,
} from "../shared/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

// One folded ack. `session_id` is the fold key when present.
export interface BroadcastAck {
  session_id    : string | null;
  persona_name  : string | null;
  persona_icon  : string | null;
  persona_color : string | null;
  status        : string | null;
  body_summary  : string;
}

// The S4 wire row (`_project_broadcast_ack`). `ack_status` rather than `status`:
// the server lifts the payload's `status` onto the envelope under a name that does
// not collide with the row's own delivery `state`.
interface ServerAckRow {
  broadcast_id  ?: string | null;
  session_id    ?: string | null;
  persona_name  ?: string | null;
  persona_icon  ?: string | null;
  persona_color ?: string | null;
  ack_status    ?: string | null;
  body_summary  ?: string | null;
}

interface BroadcastAcksResponse {
  acks ?: ReadonlyArray<ServerAckRow>;
}

// Loose ApiClient surface — AckStore only needs `get<T>`.
export interface BroadcastAcksApiClient {
  get<T>( path: string ): Promise<T>;
}

export interface AckStore {
  /** The folded acks for one broadcast, one per acking session. Defensive copy. */
  acksFor( broadcastId: string ): ReadonlyArray<BroadcastAck>;
  /** How many distinct sessions have acked this broadcast. */
  countFor( broadcastId: string ): number;
  /** Replace this broadcast's tally from the persisted rows. */
  hydrate( api: BroadcastAcksApiClient, broadcastId: string ): Promise<void>;
  /** Drop one broadcast's tally (the card was dismissed). */
  clear( broadcastId: string ): void;
  /** Subscribe to the live bus event. Returns an unsubscribe. */
  start(): () => void;
}

export interface AckStoreOptions {
  bus : EventBus;
}

// ---------------------------------------------------------------------------
// Implementation
// ---------------------------------------------------------------------------

const ACKS_URL_PREFIX = "/api/notifications/broadcast-acks/";

function foldKey( sessionId: string | null | undefined, ordinal: number ): string {
  // An unattributed ack gets its own key so several of them cannot collapse into
  // one. `ordinal` is stable within a hydrate and monotonic across live arrivals.
  return sessionId ? `sid:${sessionId}` : `anon:${ordinal}`;
}

function normalizeText( value: string | null | undefined ): string | null {
  return typeof value === "string" ? value : null;
}

class AckStoreImpl implements AckStore {
  private readonly bus : EventBus;
  // broadcast_id → (foldKey → ack). A Map of Maps: insertion order is the render
  // order, and re-acking a session replaces in place rather than appending.
  private readonly byBroadcast = new Map<string, Map<string, BroadcastAck>>();
  private anonCounter = 0;

  constructor( options: AckStoreOptions ) {
    this.bus = options.bus;
  }

  acksFor( broadcastId: string ): ReadonlyArray<BroadcastAck> {
    const fold = this.byBroadcast.get( broadcastId );
    return fold ? Array.from( fold.values() ) : [];
  }

  countFor( broadcastId: string ): number {
    const fold = this.byBroadcast.get( broadcastId );
    return fold ? fold.size : 0;
  }

  clear( broadcastId: string ): void {
    if ( !this.byBroadcast.delete( broadcastId ) ) return;
    this.emit( "cleared", broadcastId );
  }

  start(): () => void {
    return this.bus.on<BroadcastAckPayload>(
      COMMONS_BROADCAST_ACK_TYPE,
      ( e ) => this.onLiveAck( e.payload ),
    );
  }

  async hydrate( api: BroadcastAcksApiClient, broadcastId: string ): Promise<void> {
    const body = await api.get<BroadcastAcksResponse>(
      `${ACKS_URL_PREFIX}${encodeURIComponent( broadcastId )}` );
    const rows = Array.isArray( body?.acks ) ? body.acks : [];

    // REPLACE rather than merge. A hydrate is the authoritative persisted answer,
    // and merging would let a stale live ack from a previous mount survive it.
    const fold = new Map<string, BroadcastAck>();
    rows.forEach( ( row, index ) => {
      fold.set( foldKey( row.session_id, index ), {
        session_id    : normalizeText( row.session_id ),
        persona_name  : normalizeText( row.persona_name ),
        persona_icon  : normalizeText( row.persona_icon ),
        persona_color : normalizeText( row.persona_color ),
        status        : normalizeText( row.ack_status ),
        body_summary  : normalizeText( row.body_summary ) ?? "",
      } );
    } );
    this.byBroadcast.set( broadcastId, fold );
    this.emit( "hydrated", broadcastId );
  }

  private onLiveAck( payload: BroadcastAckPayload | undefined ): void {
    // A frame with no broadcast_id cannot be folded into anything — there is no
    // tally it belongs to. Dropped rather than bucketed under a placeholder.
    if ( !payload || !payload.broadcast_id ) return;

    const broadcastId = payload.broadcast_id;
    let fold = this.byBroadcast.get( broadcastId );
    if ( !fold ) {
      fold = new Map<string, BroadcastAck>();
      this.byBroadcast.set( broadcastId, fold );
    }

    const key     = foldKey( payload.session_id, this.anonCounter++ );
    const existed = fold.has( key );
    fold.set( key, {
      session_id    : normalizeText( payload.session_id ),
      persona_name  : normalizeText( payload.persona_name ),
      persona_icon  : normalizeText( payload.persona_icon ),
      persona_color : normalizeText( payload.persona_color ),
      status        : normalizeText( payload.status ),
      body_summary  : normalizeText( payload.body_summary ) ?? "",
    } );
    this.emit( existed ? "updated" : "added", broadcastId );
  }

  private emit( changeKind: StoreBroadcastAcksChangedPayload[ "changeKind" ], broadcastId: string ): void {
    this.bus.emit<StoreBroadcastAcksChangedPayload>( {
      type   : "store_broadcast_acks_changed",
      payload: { changeKind, broadcast_id: broadcastId },
      source : "ack-store",
      ts     : Date.now(),
    } );
  }
}

export function createAckStore( options: AckStoreOptions ): AckStore {
  return new AckStoreImpl( options );
}
