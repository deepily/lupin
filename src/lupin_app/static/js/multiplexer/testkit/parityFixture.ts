/* c8 ignore next */ // tsx phantom-branch artifact on file-header line (TypeScript module-init transpile artifact in c8's source-map view; no actual code on this line — same convention as render/templates/*.ts).
// WS3 — Layout-Parity Oracle: canonical fixture dual adapter.
//
// The ONE canonical scenario (fixtures/notifications-parity-scenario.json) is
// the source of truth; this thin adapter maps it BOTH ways so the legacy
// notifications.js client and the multiplexer render the SAME logical content
// (Doc 01 — "The shared fixture"). Because the data models diverged (legacy
// reads `notification.timestamp` + parses a `senderId` string; the multiplexer
// consumes typed `SenderRecord` + `ts`), the adapter is the written-down
// field-mapping (FIELD_MAP below) that doubles as the eventual field-name
// unification to-do (Doc 00 §3 Premise C).
//
// THREE derived shapes, all PURE (no DOM, no globals — unit-testable to 100%):
//   - toMuxModel(scenario)         → SenderRecord[] + Notification[] per sender
//                                     + a direction map, for the component-isolation
//                                     harness's direct renderSenderCard() calls.
//   - toConversationByDate(scenario) → the /api/notifications/conversation-by-date
//                                     REST shape that BOTH clients hydrate from
//                                     (legacy loadDateGroupedNotificationsForSender;
//                                     mux NotificationStore.hydrateHistory) — the
//                                     natural "same input" for full-page tiers +
//                                     golden-capture.
//   - toSendersVisible(scenario)   → the /api/notifications/senders-visible REST
//                                     shape (mux cold-load + golden-capture).
//
// D3 (Rick 2026-06-20) — `.outgoing` is a DAY-ONE capability. Legacy splits a
// responded notification into an incoming prompt + a synthetic `{id}-response`
// outgoing bubble off `response_value.value` (notifications.js:14317-14330).
// toMuxModel mirrors that split so the responded pair exercises BOTH
// `.sender-message.incoming` and `.sender-message.outgoing` — putting outgoing
// styling under the oracle from the start. (The renderer's direction param is a
// WS2/C2-d seam; the adapter's model is direction-correct regardless.)

import type { SenderRecord, Notification, VoicePersona } from "../shared/types";

// ---------------------------------------------------------------------------
// Canonical scenario shape (matches notifications-parity-scenario.json).
// ---------------------------------------------------------------------------

export interface ParityVoicePersona {
  name     : string;
  voice_id : string;
  icon     : string;
  color    : string;
  borrowed : boolean;
}

export interface ParityScenarioNotification {
  id                 : string;
  message            : string;
  timestamp          : string;            // ISO-8601 UTC
  abstract          ?: string;
  was_expired       ?: boolean;
  response_requested?: boolean;
  response_type     ?: string;
  response_options  ?: ReadonlyArray<string>;
  responded_at      ?: string;            // ISO-8601 UTC — outgoing bubble timestamp
  response_value    ?: { value: string } | null;
}

export interface ParityScenarioSender {
  sender_id      : string;
  display_name   : string;
  last_activity  : string;                // ISO-8601 UTC
  new_count      : number;
  voice_persona  : ParityVoicePersona | null;
  manager_persona: unknown | null;
  notifications  : ReadonlyArray<ParityScenarioNotification>;
}

export interface ParityScenario {
  schema_version: number;
  description   : string;
  app_timezone  : string;
  senders       : ReadonlyArray<ParityScenarioSender>;
}

// ---------------------------------------------------------------------------
// Mux model (component-isolation harness — direct render calls).
// ---------------------------------------------------------------------------

export type ParityDirection = "incoming" | "outgoing";

export interface MuxParityModel {
  senders              : SenderRecord[];
  // Mux Notification[] per sender_id, in the order legacy emits them (original
  // incoming, then its synthetic outgoing response immediately after).
  notificationsBySender: Record<string, Notification[]>;
  // Expected direction per Notification id_hash — the Layout-Contract referee
  // for `.sender-message.incoming | .outgoing` (Doc 01). A row whose rendered
  // class disagrees with this map is exactly the WS2/C2-d gap the oracle reports.
  directions           : Record<string, ParityDirection>;
}

// Synthetic-outgoing id suffix — verbatim legacy convention (`${id}-response`).
export const RESPONSE_ID_SUFFIX = "-response";

function muxPersona( p: ParityVoicePersona ): VoicePersona {
  // Explicit 5-field projection (D-E canonical shape) — no assigned_at on the
  // client VoicePersona.
  return {
    name     : p.name,
    voice_id : p.voice_id,
    icon     : p.icon,
    color    : p.color,
    borrowed : p.borrowed,
  };
}

function muxSenderRecord( s: ParityScenarioSender ): SenderRecord {
  const record: SenderRecord = {
    sender_id                : s.sender_id,
    display_name             : s.display_name,
    last_active_ts           : Date.parse( s.last_activity ),
    unread_count             : s.new_count,
    conversation_mode_active : false,
  };
  if ( s.voice_persona !== null ) {
    record.voice_persona = muxPersona( s.voice_persona );
  }
  return record;
}

function muxIncoming( senderId: string, n: ParityScenarioNotification ): Notification {
  const norm: Notification = {
    id_hash         : n.id,
    ts              : Date.parse( n.timestamp ),
    sender_id       : senderId,
    message         : n.message,
    action_required : false,        // historical conversation view — never a live prompt
    direction       : "incoming",   // C2-c (Clayton d0aaa767): renderNotificationItem reads notification.direction
  };
  if ( n.abstract !== undefined )    norm.abstract    = n.abstract;
  if ( n.was_expired !== undefined ) norm.was_expired = n.was_expired;
  return norm;
}

function muxOutgoing( senderId: string, n: ParityScenarioNotification, value: string ): Notification {
  // Synthetic outgoing response — mirrors legacy notifications.js:14321-14328.
  return {
    id_hash         : n.id + RESPONSE_ID_SUFFIX,
    ts              : Date.parse( n.responded_at ?? n.timestamp ),
    sender_id       : senderId,
    message         : value,
    action_required : false,
    direction       : "outgoing",   // C2-c (Clayton d0aaa767): drives .sender-message.outgoing
  };
}

/**
 * Map the canonical scenario to the multiplexer component-isolation model.
 *
 * Requires:
 *   - `scenario` conforms to ParityScenario
 * Ensures:
 *   - one SenderRecord per scenario sender (voice_persona present iff non-null)
 *   - notificationsBySender[sender_id] holds each original message as an
 *     incoming Notification, and — for any message carrying a non-empty
 *     response_value.value — a synthetic `{id}-response` outgoing Notification
 *     immediately after it (D3 responded-split)
 *   - directions maps every emitted id_hash to "incoming" | "outgoing"
 */
export function toMuxModel( scenario: ParityScenario ): MuxParityModel {
  const senders              : SenderRecord[]               = [];
  const notificationsBySender: Record<string, Notification[]> = {};
  const directions           : Record<string, ParityDirection> = {};

  for ( const s of scenario.senders ) {
    senders.push( muxSenderRecord( s ) );
    const list: Notification[] = [];
    for ( const n of s.notifications ) {
      const incoming = muxIncoming( s.sender_id, n );
      list.push( incoming );
      directions[ incoming.id_hash ] = "incoming";

      const value = n.response_value?.value;
      if ( value !== undefined && value !== "" ) {
        const outgoing = muxOutgoing( s.sender_id, n, value );
        list.push( outgoing );
        directions[ outgoing.id_hash ] = "outgoing";
      }
    }
    notificationsBySender[ s.sender_id ] = list;
  }

  return { senders, notificationsBySender, directions };
}

// ---------------------------------------------------------------------------
// Legacy / shared REST shapes (full-page tiers + golden-capture).
// ---------------------------------------------------------------------------

// One row of /api/notifications/conversation-by-date — the shape BOTH clients
// hydrate from. Carries the legacy responded-split inputs (response_value +
// responded_at) so legacy's render-time split fires under golden-capture.
export interface ConversationRow {
  id              : string;
  sender_id       : string;
  message         : string;
  timestamp       : string;
  abstract       ?: string;
  was_expired    ?: boolean;
  state          ?: string;
  responded_at   ?: string;
  response_value ?: { value: string } | null;
}

// { sender_id → { "YYYY-MM-DD" → ConversationRow[] } }
export type ConversationByDate = Record<string, Record<string, ConversationRow[]>>;

function conversationRow( senderId: string, n: ParityScenarioNotification ): ConversationRow {
  const row: ConversationRow = {
    id        : n.id,
    sender_id : senderId,
    message   : n.message,
    timestamp : n.timestamp,
  };
  if ( n.abstract !== undefined )       row.abstract       = n.abstract;
  if ( n.was_expired !== undefined )    row.was_expired    = n.was_expired;
  if ( n.responded_at !== undefined )   row.responded_at   = n.responded_at;
  if ( n.response_value !== undefined ) row.response_value = n.response_value;
  if ( n.response_value != null )       row.state          = "responded";
  return row;
}

/**
 * Map the canonical scenario to the /api/notifications/conversation-by-date
 * REST shape (per-sender, date-grouped) that both clients hydrate from.
 *
 * Ensures:
 *   - rows grouped by their `timestamp` calendar date ("YYYY-MM-DD")
 *   - responded rows carry response_value + responded_at + state="responded"
 */
export function toConversationByDate( scenario: ParityScenario ): ConversationByDate {
  const out: ConversationByDate = {};
  for ( const s of scenario.senders ) {
    const byDate: Record<string, ConversationRow[]> = {};
    for ( const n of s.notifications ) {
      const dateKey = n.timestamp.slice( 0, 10 );
      let bucket = byDate[ dateKey ];
      if ( bucket === undefined ) {
        bucket = [];
        byDate[ dateKey ] = bucket;
      }
      bucket.push( conversationRow( s.sender_id, n ) );
    }
    out[ s.sender_id ] = byDate;
  }
  return out;
}

// One row of /api/notifications/senders-visible (mux cold-load + golden-capture).
export interface SendersVisibleRow {
  sender_id      : string;
  last_activity  : string;
  count          : number;
  new_count      : number;
  voice_persona  : ( ParityVoicePersona & { assigned_at: string } ) | null;
  manager_persona: unknown | null;
}

/**
 * Map the canonical scenario to the /api/notifications/senders-visible REST
 * shape. `count` = total messages for the sender; persona'd senders carry
 * assigned_at (= last_activity) for fidelity with the live shape.
 */
export function toSendersVisible( scenario: ParityScenario ): SendersVisibleRow[] {
  return scenario.senders.map( ( s ) => ( {
    sender_id      : s.sender_id,
    last_activity  : s.last_activity,
    count          : s.notifications.length,
    new_count      : s.new_count,
    voice_persona  : s.voice_persona === null
      ? null
      : { ...s.voice_persona, assigned_at: s.last_activity },
    manager_persona: s.manager_persona,
  } ) );
}

// ---------------------------------------------------------------------------
// Field map — the written-down canonical↔legacy↔mux mapping (parity spec +
// field-unification to-do, Doc 01 / Doc 00 §3 Premise C).
// ---------------------------------------------------------------------------

export interface FieldMapEntry {
  canonical: string;
  legacy   : string;
  mux      : string;
  note     : string;
}

/* c8 ignore start */ // pure-data literal; c8 reports a phantom statement/branch on the array's closing `];` line (tsx source-map artifact). Contents ARE asserted by parity_fixture.test.ts "FIELD_MAP" — the ignore suppresses only the bookend phantom.
export const FIELD_MAP: ReadonlyArray<FieldMapEntry> = [
  { canonical: "notification.timestamp",      legacy: "notification.timestamp (ISO)",        mux: "Notification.ts (ms epoch)",        note: "legacy parses ISO at render; mux normalizes to ms epoch in the store" },
  { canonical: "notification.id",             legacy: "notification.id",                     mux: "Notification.id_hash",              note: "DB row id ↔ keyed-merge id_hash" },
  { canonical: "notification.response_value", legacy: "notification.response_value.value",   mux: "(WS2/C2-d: synthetic {id}-response Notification)", note: "legacy splits at render; mux model splits in toMuxModel" },
  { canonical: "sender.display_name",         legacy: "parsed senderId → project name",      mux: "SenderRecord.display_name",         note: "legacy derives from the senderId string; mux carries a typed field" },
  { canonical: "sender.new_count",            legacy: "card newCount",                       mux: "SenderRecord.unread_count",         note: "per-sender unread badge" },
  { canonical: "sender.last_activity",        legacy: "card last-activity",                  mux: "SenderRecord.last_active_ts (ms)",  note: "ISO ↔ ms epoch" },
  { canonical: "sender.voice_persona",        legacy: "senderPersonaMap[senderId]",          mux: "SenderRecord.voice_persona",        note: "5-field D-E shape; mux drops assigned_at" },
];
/* c8 ignore stop */
