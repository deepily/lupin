// WS3 — Layout-Parity Oracle: component-isolation harness entry.
//
// A tiny browser bundle that mounts the MUX contract components (one
// `.sender-card` per scenario sender) inside the standard `.container` at a
// fixed viewport, for apples-to-apples Tier 2/3 comparison against the legacy
// golden (Doc 01 — "Component-isolation vs full-page scope"). No transports, no
// stores, no auth — the multiplexer templates are pure functions, so isolation
// is just `toMuxModel(scenario)` → `renderSenderCard(...)`.
//
// The scenario is injected by the test (Python reads the canonical fixture and
// calls `window.__parityMount(scenario)`), mirroring the phase6b visual-fixture
// injection idiom — no web-served fixture JSON, no build-time coupling.
//
// Exposed test surface:
//   window.__parityHarnessReady : true once the entry has wired the mount fn
//   window.__parityMount(scenario) : mounts the cards; returns the rendered count
//   window.__parityModel : the last MuxParityModel mounted (directions etc.)

import { renderSenderCard } from "../render/templates/senderCard";
import { toMuxModel, toSendersVisible, toConversationByDate } from "./parityFixture";
import type {
  ParityScenario,
  MuxParityModel,
  SendersVisibleRow,
  ConversationByDate,
} from "./parityFixture";

const APP_TIMEZONE = "UTC";

interface LegacyShapes {
  sendersVisible    : SendersVisibleRow[];
  conversationByDate: ConversationByDate;
}

interface ParityHarnessWindow {
  __parityHarnessReady?: boolean;
  __parityMount?: ( scenario: ParityScenario ) => number;
  __parityModel?: MuxParityModel;
  // Single-source legacy stub bodies — the golden-capture script reads these
  // (computed by the SAME TS adapter) to route-stub legacy's senders-visible +
  // conversation-by-date, so legacy and mux render from one canonical scenario.
  __parityLegacyShapes?: ( scenario: ParityScenario ) => LegacyShapes;
}

function mount( scenario: ParityScenario ): number {
  const container = document.getElementById( "sender-cards-container" );
  /* c8 ignore next */ // defensive: the harness page always provides the mount node; the throw guards a malformed page and is not exercised by the happy-path tests.
  if ( container === null ) throw new Error( "parity-harness: #sender-cards-container not found" );

  // Idempotent re-mount — clear any prior render so repeated injections are clean.
  container.replaceChildren();

  const model = toMuxModel( scenario );
  for ( const sender of model.senders ) {
    /* c8 ignore next */ // `?? []` is a noUncheckedIndexedAccess type-guard; toMuxModel always sets notificationsBySender[sender.sender_id] for every sender it emits, so the [] fallback is unreachable.
    const notifications = model.notificationsBySender[ sender.sender_id ] ?? [];
    container.appendChild( renderSenderCard( sender, notifications, { appTimezone: APP_TIMEZONE } ) );
  }

  ( window as unknown as ParityHarnessWindow ).__parityModel = model;
  return model.senders.length;
}

function legacyShapes( scenario: ParityScenario ): LegacyShapes {
  return {
    sendersVisible    : toSendersVisible( scenario ),
    conversationByDate: toConversationByDate( scenario ),
  };
}

const w = window as unknown as ParityHarnessWindow;
w.__parityMount = mount;
w.__parityLegacyShapes = legacyShapes;
w.__parityHarnessReady = true;
console.log( "[parity-harness] ready" );
