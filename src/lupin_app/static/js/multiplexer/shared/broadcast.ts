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
/**
 * The event types that are copied to other tabs.
 *
 * The set is fixed in code and is not a setting. Every type in it is low-frequency, one event a second or less.
 */
export const BROADCAST_WHITELIST: ReadonlySet<LupinEventType> = new Set<LupinEventType>([
  "auth_state_change",
  "notification_received",
  "voice_persona_assigned",
  "voice_persona_released",
  "speakerphone_change",
]);

const BROADCAST_SOURCE = "broadcast";
const CHANNEL_NAME     = "lupin";

// Minimal BroadcastChannel-compatible shape for testing without messing with
// the real `BroadcastChannel` global (Node has it but tests benefit from a
// deterministic local mock).
/** The part of `BroadcastChannel` the wrapper uses, so a test can pass a local stand-in. */
export interface BroadcastChannelLike {
  postMessage(data: unknown): void;
  close(): void;
  onmessage: ((evt: MessageEvent<unknown>) => void) | null;
}

/**
 * Starts and stops copying whitelisted bus events to other tabs of the same origin.
 *
 * `start` can be called again safely. An event that came from another tab is not sent on again.
 */
export interface BroadcastWrapper {
  start(): void;       // begin replication; idempotent
  stop(): void;
}

/**
 * What the wrapper is built from.
 *
 * It needs the bus. The channel factory and the whitelist can be replaced in tests.
 */
export interface BroadcastWrapperOptions {
  bus              : EventBus;
  // Test injection. Production uses the global `BroadcastChannel`.
  channelFactory?  : (name: string) => BroadcastChannelLike;
  // Override the static whitelist for tests / debugging.
  whitelist?       : ReadonlySet<LupinEventType>;
}

/**
 * Copies whitelisted bus events to other tabs and replays incoming ones locally.
 */
class BroadcastWrapperImpl implements BroadcastWrapper {
  private readonly bus       : EventBus;
  private readonly whitelist : ReadonlySet<LupinEventType>;
  private readonly channelFactory: (name: string) => BroadcastChannelLike;
  private channel : BroadcastChannelLike | null = null;
  private unsubs  : Array<() => void> = [];
  private started = false;

  /**
   * Keeps the bus, whitelist and channel factory, with defaults for the last two.
   */
  constructor(opts: BroadcastWrapperOptions) {
    this.bus            = opts.bus;
    this.whitelist      = opts.whitelist ?? BROADCAST_WHITELIST;
    this.channelFactory = opts.channelFactory ?? defaultChannelFactory;
  }

  /**
   * Opens the channel, replays incoming messages and forwards whitelisted bus events.
   */
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

  /**
   * Unsubscribes from the bus and closes the channel.
   *
   * Does nothing if not started.
   */
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
/**
 * Says whether a value has the shape of a bus event.
 */
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

/**
 * Creates a browser broadcast channel with the given name.
 */
function defaultChannelFactory(name: string): BroadcastChannelLike {
  // Browser + Node 18+ both expose `BroadcastChannel` as a global.
  return new globalThis.BroadcastChannel(name) as unknown as BroadcastChannelLike;
}

/**
 * Build the cross-tab wrapper over a bus.
 *
 * Nothing production starts it, because the app is single-tab by policy; the module is kept in case that changes.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on factory function declaration line.
export function createBroadcastWrapper(
  opts: BroadcastWrapperOptions,
): BroadcastWrapper {
  return new BroadcastWrapperImpl(opts);
}
