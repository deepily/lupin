/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Lane E WP15 — MissedBadgeRenderer (F7).
//
// Subscribes to `store_missed_changed` and paints the "N missed while away"
// badge + Reset button. Mirrors the TtsChromeRenderer lifecycle contract
// (atomic replaceChildren render; throw on double-mount; idempotent unmount).
//
// Visibility parity with legacy (notifications.js:14709-14722): the badge +
// Reset button show ONLY while count > 0. At 0 the renderer paints an empty
// root (badge + button vanish).
//
// Reset click → `store.reset()`. On rejection the count is left unchanged by
// the store, so the badge stays for a retry; the renderer swallows the
// rejection (no uncaught promise) — parity with the legacy alert-and-keep path
// minus the modal.

import type { EventBus } from "../shared/EventBus";
import type { StoreMissedChangedPayload } from "../shared/types";
import { renderMissedBadge } from "./templates/missedBadge";

export interface MissedStoreLike {
  count(): number;
  reset(): Promise<number>;
}

export interface MissedBadgeRendererStores {
  missed : MissedStoreLike;
}

export interface MissedBadgeRenderer {
  /** Mount onto `root`. Throws on a second mount without unmount(). */
  mount( root: HTMLElement ): void;
  /** Detach: unsubscribe + clear children. Idempotent. */
  unmount(): void;
  /** Test helper — synchronously trigger a full re-render. */
  forceRenderForTesting(): void;
}

export interface MissedBadgeRendererOptions {
  eventBus : EventBus;
  stores   : MissedBadgeRendererStores;
}

class MissedBadgeRendererImpl implements MissedBadgeRenderer {
  private readonly bus    : EventBus;
  private readonly stores : MissedBadgeRendererStores;
  private readonly unsubscribers: Array<() => void> = [];

  private root    : HTMLElement | null = null;
  private mounted = false;

  constructor( opts: MissedBadgeRendererOptions ) {
    this.bus    = opts.eventBus;
    this.stores = opts.stores;
  }

  mount( root: HTMLElement ): void {
    if ( this.mounted ) {
      throw new Error( "MissedBadgeRenderer already mounted" );
    }
    this.mounted = true;
    this.root = root;

    this.renderNow();
    this.unsubscribers.push(
      this.bus.on<StoreMissedChangedPayload>(
        "store_missed_changed",
        () => this.renderNow(),
      ),
    );
  }

  unmount(): void {
    for ( const off of this.unsubscribers ) off();
    this.unsubscribers.length = 0;
    if ( this.root !== null ) {
      this.root.replaceChildren();
      this.root = null;
    }
    this.mounted = false;
  }

  forceRenderForTesting(): void {
    if ( this.mounted ) this.renderNow();
  }

  private renderNow(): void {
    /* c8 ignore next */ // defensive: subscriptions are detached in unmount BEFORE root is nulled.
    if ( this.root === null ) return;
    const count = this.stores.missed.count();
    if ( count <= 0 ) {
      // Hidden state — empty root (badge + Reset button vanish).
      this.root.replaceChildren();
      return;
    }
    const badge = renderMissedBadge(
      { count },
      { onReset: (): void => this.onReset() },
    );
    this.root.replaceChildren( badge );
  }

  private onReset(): void {
    // Swallow rejection: the store leaves the count unchanged on failure, so
    // the badge stays. void-catch avoids an unhandled promise rejection.
    void this.stores.missed.reset().catch( () => { /* keep badge for retry */ } );
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createMissedBadgeRenderer(
  opts: MissedBadgeRendererOptions,
): MissedBadgeRenderer {
  return new MissedBadgeRendererImpl( opts );
}
