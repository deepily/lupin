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
import { teardownScaffold } from "./dom";

/** The slice of the missed store the renderer uses: the count and the reset. */
export interface MissedStoreLike {
  count(): number;
  reset(): Promise<number>;
}

/** The stores the missed badge reads: only the missed store. */
export interface MissedBadgeRendererStores {
  missed : MissedStoreLike;
}

/**
 * The "missed while away" badge and its Reset button.
 *
 * Both are shown only while the count is above zero.
 */
export interface MissedBadgeRenderer {
  /** Mount onto `root`. Throws on a second mount without unmount(). */
  mount( root: HTMLElement ): void;
  /** Detach: unsubscribe + clear children. Idempotent. */
  unmount(): void;
  /** Test helper — synchronously trigger a full re-render. */
  forceRenderForTesting(): void;
}

/** Options for `createMissedBadgeRenderer`: the bus and the stores. */
export interface MissedBadgeRendererOptions {
  eventBus : EventBus;
  stores   : MissedBadgeRendererStores;
}

/**
 * Renders the missed notification badge and reset button from the store's count.
 */
class MissedBadgeRendererImpl implements MissedBadgeRenderer {
  private readonly bus    : EventBus;
  private readonly stores : MissedBadgeRendererStores;
  private readonly unsubscribers: Array<() => void> = [];

  private root    : HTMLElement | null = null;
  private mounted = false;

  /**
   * Creates the renderer from its bus and stores.
   */
  constructor( opts: MissedBadgeRendererOptions ) {
    this.bus    = opts.eventBus;
    this.stores = opts.stores;
  }

  /**
   * Attaches to a root element, paints the badge, and listens for count changes.
   */
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

  /**
   * Removes the subscriptions and empties the root element.
   */
  unmount(): void {
    teardownScaffold( this.unsubscribers, null, this.root );
    this.root = null;
    this.mounted = false;
  }

  /**
   * Repaints the badge at once, for tests, when mounted.
   */
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

/**
 * Build the renderer.
 *
 * It paints nothing until `mount()` is called.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createMissedBadgeRenderer(
  opts: MissedBadgeRendererOptions,
): MissedBadgeRenderer {
  return new MissedBadgeRendererImpl( opts );
}
