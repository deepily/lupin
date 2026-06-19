/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 6c Node A — PersonaModalRenderer.
//
// Maintains a popover per sender with a voice persona, mounted into
// `#persona-modal-portal`. The popover's id matches the
// `popovertarget` on the corresponding `.sender-persona-badge` button
// rendered by senderCard.ts (Step A1).
//
// Lifecycle (per execution plan §3.A.4 Step A3):
//   - mount(root): query #persona-modal-portal; subscribe to
//     store_senders_changed; create popovers for senders that already
//     have a voice_persona (initial paint).
//   - unmount(): unsubscribe + remove all owned popovers from the portal.
//   - forceRenderForTesting(): synchronous full reconcile pass.
//
// Subscription model (per F1 closure): single subscription on
// `store_senders_changed`. The reducer dispatches on `changeKind`:
//   - "added"   → create popover if sender has voice_persona
//   - "updated" → if sender has voice_persona, re-render in place
//                 (replaceChildren preserves the OPEN state per F-Arnold-5);
//                 if voice_persona was just removed, delete the popover
//   - "removed" → delete popover from portal
//
// Storm-safety scope (per F-Arnold-6): the renderer only reacts to changes
// affecting the persona slot. The wire model collapses persona events
// through `store_senders_changed` so every emission could theoretically
// touch persona, but the reconcile is idempotent — re-rendering the same
// content is a cheap no-op visually.
//
// Event-driven only — NO requestAnimationFrame, NO setInterval, NO polling.
// `#mounted` boolean guard prevents double-mount (Phase 6a F-26 pattern).

import type { EventBus } from "../shared/EventBus";
import type { SenderRecord, StoreSendersChangedPayload, LupinEvent } from "../shared/types";
import { renderPersonaPopover, type PersonaPopoverInput } from "./templates/personaModal";

interface SenderStoreLike {
  get(senderId: string): SenderRecord | undefined;
  list(): ReadonlyArray<SenderRecord>;
}

export interface PersonaModalRenderer {
  mount( root: HTMLElement ): void;
  unmount(): void;
  forceRenderForTesting(): void;
}

export interface PersonaModalRendererOptions {
  eventBus : EventBus;
  stores   : { senders: SenderStoreLike };
}

class PersonaModalRendererImpl implements PersonaModalRenderer {
  private readonly bus           : EventBus;
  private readonly stores        : { senders: SenderStoreLike };
  private readonly unsubscribers : Array<() => void> = [];
  // sender_id → popover element. Used for fast lookup on update/remove.
  private readonly popovers      : Map<string, HTMLElement> = new Map();

  private root    : HTMLElement | null = null;
  private portal  : HTMLElement | null = null;
  private mounted : boolean = false;

  constructor( opts: PersonaModalRendererOptions ) {
    this.bus    = opts.eventBus;
    this.stores = opts.stores;
  }

  mount( root: HTMLElement ): void {
    if (this.mounted) throw new Error("PersonaModalRenderer.mount: already mounted");
    const portal = root.querySelector<HTMLElement>("#persona-modal-portal");
    if (portal === null) throw new Error("PersonaModalRenderer.mount: #persona-modal-portal not found");

    this.root    = root;
    this.portal  = portal;
    this.mounted = true;

    this.unsubscribers.push(
      this.bus.on<StoreSendersChangedPayload>(
        "store_senders_changed",
        (e) => this.onStoreChange(e),
      ),
    );

    // Initial paint: create popovers for senders already in the store with personas.
    for (const sender of this.stores.senders.list()) {
      if (sender.voice_persona !== undefined) {
        this.createOrUpdatePopover(sender);
      }
    }
  }

  unmount(): void {
    for (const off of this.unsubscribers) off();
    this.unsubscribers.length = 0;

    // Remove all owned popovers from the portal.
    for (const popover of this.popovers.values()) {
      popover.remove();
    }
    this.popovers.clear();

    this.root    = null;
    this.portal  = null;
    this.mounted = false;
  }

  forceRenderForTesting(): void {
    this.reconcileAll();
  }

  // -------------------------------------------------------------------------
  // Reducer
  // -------------------------------------------------------------------------

  private reconcileAll(): void {
    // Full reconcile: re-create or update every popover based on current store.
    if (this.portal === null) return;
    const seenIds = new Set<string>();
    for (const sender of this.stores.senders.list()) {
      if (sender.voice_persona !== undefined) {
        this.createOrUpdatePopover(sender);
        seenIds.add(sender.sender_id);
      }
    }
    // Remove popovers for senders no longer in the store / without persona.
    for (const id of Array.from(this.popovers.keys())) {
      if (!seenIds.has(id)) this.removePopover(id);
    }
  }

  private onStoreChange(e: LupinEvent<StoreSendersChangedPayload>): void {
    /* c8 ignore next */ // defensive: subscription is detached in unmount() BEFORE portal is nulled.
    if (this.portal === null) return;
    const { changeKind, sender_id: senderId } = e.payload;
    // Cold-load hydration (2026-06-11): "hydrated" is a whole-snapshot change
    // with NO single sender_id — reconcile every popover from store.list().
    if (changeKind === "hydrated" || senderId === undefined) {
      this.reconcileAll();
      return;
    }
    if (changeKind === "removed") {
      this.removePopover(senderId);
      return;
    }
    // added | updated — look up the current sender state.
    const sender = this.stores.senders.get(senderId);
    if (sender === undefined) {
      // Edge: store says updated but get returns undefined. Treat as remove.
      this.removePopover(senderId);
      return;
    }
    if (sender.voice_persona === undefined) {
      // Persona was released — remove the popover if we had one.
      this.removePopover(senderId);
      return;
    }
    this.createOrUpdatePopover(sender);
  }

  // -------------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------------

  private createOrUpdatePopover(sender: SenderRecord): void {
    /* c8 ignore next */ // defensive — onStoreChange / mount filter out the undefined-persona case before invoking this.
    if (sender.voice_persona === undefined) return;
    const input: PersonaPopoverInput = {
      sender_id : sender.sender_id,
      name      : sender.voice_persona.name,
      voice_id  : sender.voice_persona.voice_id,
      icon      : sender.voice_persona.icon,
      color     : sender.voice_persona.color,
      borrowed  : sender.voice_persona.borrowed,
    };
    const existing = this.popovers.get(sender.sender_id);
    if (existing !== undefined) {
      // Update in place: re-render content but keep the popover root element
      // (preserves its OPEN state per F-Arnold-5 — replacing the root would
      // close any open popover, losing the user's view context).
      const fresh = renderPersonaPopover(input);
      existing.replaceChildren(...Array.from(fresh.childNodes));
      return;
    }
    /* c8 ignore next */ // defensive: portal is set in mount() before this method is reachable; onStoreChange's portal guard short-circuits before here.
    if (this.portal === null) return;
    const popover = renderPersonaPopover(input);
    this.portal.appendChild(popover);
    this.popovers.set(sender.sender_id, popover);
  }

  private removePopover(senderId: string): void {
    const popover = this.popovers.get(senderId);
    if (popover === undefined) return;
    popover.remove();
    this.popovers.delete(senderId);
  }
}

/**
 * Factory — production code constructs via `createPersonaModalRenderer`.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createPersonaModalRenderer(
  opts: PersonaModalRendererOptions,
): PersonaModalRenderer {
  return new PersonaModalRendererImpl(opts);
}
