// WS3 — Layout-Parity Oracle: dual-adapter unit tests.
//
// Drives the canonical fixture (the REAL JSON, so the fixture is validated as a
// side effect) plus a small crafted edge scenario, to 100% c8 (lines/branches/
// functions) on parityFixture.ts. No DOM — the adapter is pure.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  toMuxModel,
  toConversationByDate,
  toSendersVisible,
  FIELD_MAP,
  RESPONSE_ID_SUFFIX,
} from "../../../../lupin_app/static/js/multiplexer/testkit/parityFixture";
import type { ParityScenario } from "../../../../lupin_app/static/js/multiplexer/testkit/parityFixture";

const SCENARIO: ParityScenario = JSON.parse(
  readFileSync(
    new URL( "../../../e2e_ui/fixtures/notifications-parity-scenario.json", import.meta.url ),
    "utf-8",
  ),
) as ParityScenario;

const TIBERIUS = "claude.code@lupin.deepily.ai#parity01";
const ARBITER  = "lupin-arbiter-app-8001";

// Crafted edge scenario — exercises the response_value branches the canonical
// fixture does not (empty value, explicit null, value-without-responded_at).
const EDGE: ParityScenario = {
  schema_version: 1,
  description   : "edge",
  app_timezone  : "UTC",
  senders       : [
    {
      sender_id      : "edge",
      display_name   : "edge",
      last_activity  : "2026-06-20T10:00:00.000Z",
      new_count      : 0,
      voice_persona  : null,
      manager_persona: null,
      notifications  : [
        { id: "empty-val",      message: "e", timestamp: "2026-06-20T10:00:00.000Z", response_value: { value: "" } },
        { id: "null-val",       message: "n", timestamp: "2026-06-20T10:01:00.000Z", response_value: null },
        { id: "val-no-respat",  message: "v", timestamp: "2026-06-20T10:02:00.000Z", response_value: { value: "ok" } },
      ],
    },
  ],
};

// ---------------------------------------------------------------------------
// toMuxModel
// ---------------------------------------------------------------------------

test( "toMuxModel: one SenderRecord per sender; persona present iff non-null", () => {
  const { senders } = toMuxModel( SCENARIO );
  assert.equal( senders.length, 2 );

  const tib = senders.find( ( s ) => s.sender_id === TIBERIUS )!;
  assert.equal( tib.display_name, "Tiberius" );
  assert.equal( tib.unread_count, 4 );
  assert.equal( tib.conversation_mode_active, false );
  assert.equal( tib.last_active_ts, Date.parse( "2026-06-20T14:04:30.000Z" ) );
  assert.deepEqual( tib.voice_persona, {
    name: "Tiberius", voice_id: "vid_parity_tiberius", icon: "👑", color: "#7E57C2", borrowed: false,
  } );

  const ext = senders.find( ( s ) => s.sender_id === ARBITER )!;
  assert.equal( ext.voice_persona, undefined );
} );

test( "toMuxModel: D3 responded-split → incoming prompt + synthetic outgoing", () => {
  const { notificationsBySender, directions } = toMuxModel( SCENARIO );
  const list = notificationsBySender[ TIBERIUS ]!;

  // 4 originals + 1 synthetic response = 5 rows.
  assert.equal( list.length, 5 );

  const prompt   = list.find( ( n ) => n.id_hash === "parity-responded-1" )!;
  const response = list.find( ( n ) => n.id_hash === "parity-responded-1" + RESPONSE_ID_SUFFIX )!;

  assert.equal( directions[ prompt.id_hash ], "incoming" );
  assert.equal( directions[ response.id_hash ], "outgoing" );
  assert.equal( response.message, "yes" );
  assert.equal( response.ts, Date.parse( "2026-06-20T14:04:30.000Z" ) );  // responded_at
  // The synthetic row sits immediately after its prompt (legacy ordering).
  assert.equal( list.indexOf( response ), list.indexOf( prompt ) + 1 );
} );

test( "toMuxModel: abstract + was_expired carried only when present", () => {
  const { notificationsBySender } = toMuxModel( SCENARIO );
  const list = notificationsBySender[ TIBERIUS ]!;

  const withAbstract = list.find( ( n ) => n.id_hash === "parity-abstract-1" )!;
  assert.equal( withAbstract.abstract, "Detailed context that surfaces via the 📋 abstract-indicator on click." );

  const expired = list.find( ( n ) => n.id_hash === "parity-expired-1" )!;
  assert.equal( expired.was_expired, true );

  const plain = list.find( ( n ) => n.id_hash === "parity-plain-1" )!;
  assert.equal( plain.abstract, undefined );
  assert.equal( plain.was_expired, undefined );
} );

test( "toMuxModel: empty / null / responded_at-less response_value branches", () => {
  const { notificationsBySender, directions } = toMuxModel( EDGE );
  const list = notificationsBySender[ "edge" ]!;

  // empty-val (value "") and null-val (null) produce NO outgoing split.
  assert.equal( directions[ "empty-val" + RESPONSE_ID_SUFFIX ], undefined );
  assert.equal( directions[ "null-val" + RESPONSE_ID_SUFFIX ], undefined );

  // val-no-respat DOES split; outgoing ts falls back to the original timestamp.
  const resp = list.find( ( n ) => n.id_hash === "val-no-respat" + RESPONSE_ID_SUFFIX )!;
  assert.equal( resp.message, "ok" );
  assert.equal( resp.ts, Date.parse( "2026-06-20T10:02:00.000Z" ) );

  // 3 originals + 1 split = 4 rows.
  assert.equal( list.length, 4 );
} );

// ---------------------------------------------------------------------------
// toConversationByDate
// ---------------------------------------------------------------------------

test( "toConversationByDate: date-grouped; responded row carries split inputs", () => {
  const byDate = toConversationByDate( SCENARIO );

  const tib = byDate[ TIBERIUS ]!;
  const rows = tib[ "2026-06-20" ]!;
  assert.equal( rows.length, 4 );

  const responded = rows.find( ( r ) => r.id === "parity-responded-1" )!;
  assert.deepEqual( responded.response_value, { value: "yes" } );
  assert.equal( responded.responded_at, "2026-06-20T14:04:30.000Z" );
  assert.equal( responded.state, "responded" );

  const plain = rows.find( ( r ) => r.id === "parity-plain-1" )!;
  assert.equal( plain.response_value, undefined );
  assert.equal( plain.state, undefined );

  const withAbstract = rows.find( ( r ) => r.id === "parity-abstract-1" )!;
  assert.equal( withAbstract.abstract, "Detailed context that surfaces via the 📋 abstract-indicator on click." );

  const expired = rows.find( ( r ) => r.id === "parity-expired-1" )!;
  assert.equal( expired.was_expired, true );

  // Arbiter sender groups under its own date.
  assert.ok( byDate[ ARBITER ]![ "2026-06-20" ]!.length === 1 );
} );

test( "toConversationByDate: explicit-null response_value sets row.response_value but NOT state", () => {
  const byDate = toConversationByDate( EDGE );
  const rows = byDate[ "edge" ]![ "2026-06-20" ]!;

  const nullVal = rows.find( ( r ) => r.id === "null-val" )!;
  assert.equal( nullVal.response_value, null );
  assert.equal( nullVal.state, undefined );      // != null guard → no responded state
} );

// ---------------------------------------------------------------------------
// toSendersVisible
// ---------------------------------------------------------------------------

test( "toSendersVisible: persona'd row carries assigned_at; persona-less is null", () => {
  const rows = toSendersVisible( SCENARIO );
  assert.equal( rows.length, 2 );

  const tib = rows.find( ( r ) => r.sender_id === TIBERIUS )!;
  assert.equal( tib.count, 4 );
  assert.equal( tib.new_count, 4 );
  assert.equal( tib.voice_persona!.assigned_at, "2026-06-20T14:04:30.000Z" );
  assert.equal( tib.voice_persona!.icon, "👑" );

  const ext = rows.find( ( r ) => r.sender_id === ARBITER )!;
  assert.equal( ext.voice_persona, null );
  assert.equal( ext.count, 1 );
} );

// ---------------------------------------------------------------------------
// FIELD_MAP
// ---------------------------------------------------------------------------

test( "FIELD_MAP: documents the canonical↔legacy↔mux mapping", () => {
  assert.ok( FIELD_MAP.length >= 5 );
  for ( const e of FIELD_MAP ) {
    assert.ok( e.canonical.length > 0 && e.legacy.length > 0 && e.mux.length > 0 && e.note.length > 0 );
  }
  assert.ok( FIELD_MAP.some( ( e ) => e.canonical === "notification.response_value" ) );
} );
