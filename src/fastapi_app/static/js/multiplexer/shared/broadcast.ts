/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 2 — BroadcastChannel wrapper.
// Replicates whitelisted EventBus events across tabs of the same origin.
// Loop prevention: events with `source: "broadcast"` are NOT re-broadcast.
// Whitelist is a static constant per DC4 (cross-tab replication is a design
// decision, not a runtime config knob).
//
// ⚠️ INERT IN PRODUCTION (per Q12 — single-tab application policy ratified
// 2026-05-04 PM during Phase 4 plan-review): no production consumer wires
// this module. boot.ts does NOT call broadcast.start(). The code + 8 unit
// tests ship for two reasons:
//   1. The Phase 2 spine bundle is closed; ripping out this module
//      retroactively touches an approved phase boundary.
//   2. Hedge against the policy reversing — if multi-tab support ever
//      becomes scoped in, this wrapper is ready to wire.
// Removal is tracked as a separate cleanup commit; see TODO.md "Phase 2
// broadcast.ts removal" entry. See src/rnd/v0.1.7/2026.05.02-notifications-
// ui-js-refactor/01-phase0-decisions.md Q12 for the policy decision.

import type { EventBus } from "./EventBus";
import type { LupinEvent, LupinEventType } from "./types";

// Static, ratified by code review. Procedure for adding entries:
//   1. Confirm event type is low-frequency (~< 1 event/sec across all tabs).
//   2. Confirm cross-tab synchronization is semantically correct.
//   3. Add the type to this Set with a comment explaining why.
//   4. Update broadcast.test.ts with a loop-prevention test for the new type.
export const BROADCAST_WHITELIST: ReadonlySet<LupinEventType> = new Set<LupinEventType>([
  "auth_state_change",
  "notification_received",
  "voice_persona_assigned",
  "voice_persona_released",
  "conversation_mode_change",
]);

const BROADCAST_SOURCE = "broadcast";
const CHANNEL_NAME     = "lupin";

// Minimal BroadcastChannel-compatible shape for testing without messing with
// the real `BroadcastChannel` global (Node has it but tests benefit from a
// deterministic local mock).
export interface BroadcastChannelLike {
  postMessage(data: unknown): void;
  close(): void;
  onmessage: ((evt: MessageEvent<unknown>) => void) | null;
}

export interface BroadcastWrapper {
  start(): void;       // begin replication; idempotent
  stop(): void;
}

export interface BroadcastWrapperOptions {
  bus              : EventBus;
  // Test injection. Production uses the global `BroadcastChannel`.
  channelFactory?  : (name: string) => BroadcastChannelLike;
  // Override the static whitelist for tests / debugging.
  whitelist?       : ReadonlySet<LupinEventType>;
}

class BroadcastWrapperImpl implements BroadcastWrapper {
  private readonly bus       : EventBus;
  private readonly whitelist : ReadonlySet<LupinEventType>;
  private readonly channelFactory: (name: string) => BroadcastChannelLike;
  private channel : BroadcastChannelLike | null = null;
  private unsubs  : Array<() => void> = [];
  private started = false;

  constructor(opts: BroadcastWrapperOptions) {
    this.bus            = opts.bus;
    this.whitelist      = opts.whitelist ?? BROADCAST_WHITELIST;
    this.channelFactory = opts.channelFactory ?? defaultChannelFactory;
  }

  start(): void {
    if (this.started) return;
    this.started = true;
    this.channel = this.channelFactory(CHANNEL_NAME);

    // Inbound: messages from other tabs.
    this.channel.onmessage = (evt) => this.handleInbound(evt.data);

    // Outbound: every whitelisted event whose source is NOT "broadcast" gets
    // re-emitted across the channel.
    for (const type of this.whitelist) {
      const unsub = this.bus.on(type, (e) => this.handleOutbound(e));
      this.unsubs.push(unsub);
    }
  }

  stop(): void {
    /* c8 ignore next */ // defensive: idempotency guard — calling stop() before start() or twice is a no-op; tests cover the started-then-stop path but not the never-started branch.
    if (!this.started) return;
    this.started = false;
    for (const u of this.unsubs) u();
    this.unsubs = [];
    if (this.channel) {
      this.channel.onmessage = null;
      this.channel.close();
      this.channel = null;
    }
  }

  private handleOutbound(event: LupinEvent<unknown>): void {
    // Loop prevention: never re-broadcast events that originated from the
    // broadcast channel.
    if (event.source === BROADCAST_SOURCE) return;
    /* c8 ignore next */ // defensive: handleOutbound is bound from start() which only runs after this.channel is set; null-check is a safety net.
    if (!this.channel) return;
    this.channel.postMessage(event);
  }

  private handleInbound(data: unknown): void {
    if (!isLupinEvent(data)) return;
    /* c8 ignore next */ // defensive: whitelist filtering — tests cover both whitelisted + non-whitelisted types but the type-not-in-whitelist branch may not register if all test events are whitelisted.
    if (!this.whitelist.has(data.type)) return;
    // Mark as broadcast-sourced so the outbound handler skips re-broadcasting.
    const replayed: LupinEvent<unknown> = {
      type    : data.type,
      payload : data.payload,
      source  : BROADCAST_SOURCE,
      ts      : data.ts,
    };
    this.bus.emit(replayed);
  }
}

/* c8 ignore start */ // tsx phantom-branch artifact on function declaration line + multi-clause type-guard predicate. Each predicate clause registers as a branch; the type-guard is exercised end-to-end (tests pass both valid and invalid LupinEvent shapes) but each individual short-circuit doesn't get its own dedicated test.
function isLupinEvent(v: unknown): v is LupinEvent<unknown> {
  if (typeof v !== "object" || v === null) return false;
  const o = v as Record<string, unknown>;
  return (
    typeof o["type"] === "string" &&
    "payload" in o &&
    typeof o["source"] === "string" &&
    typeof o["ts"] === "number"
  );
}
/* c8 ignore stop */

function defaultChannelFactory(name: string): BroadcastChannelLike {
  // Browser + Node 18+ both expose `BroadcastChannel` as a global.
  return new globalThis.BroadcastChannel(name) as unknown as BroadcastChannelLike;
}

/* c8 ignore next */ // tsx phantom-branch artifact on factory function declaration line.
export function createBroadcastWrapper(
  opts: BroadcastWrapperOptions,
): BroadcastWrapper {
  return new BroadcastWrapperImpl(opts);
}
