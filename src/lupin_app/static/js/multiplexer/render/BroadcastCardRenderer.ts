/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Lane C (v0.1.9 focus-bar parity, 2026-06-24) — BroadcastCardRenderer.
//
// Behavior layer for the "Broadcast to all CC sessions" compose card. Builds
// the broadcastCard template into its mount root and wires (all via delegated
// clicks — mux no-globals rule):
//   - #broadcast-submit-header  — collapse/expand the card (persisted via
//     BroadcastStore.setCardOpen).
//   - #broadcast-recipients-refresh (↻) — re-fetch the active-session list.
//   - .broadcast-chip — inject `@<persona> ` (or `@all `) at the textarea caret.
//   - #broadcast-stt-button (🎤) — record → splice the transcription into the
//     textarea at the caret (recordingManager + insertTranscriptionText, the
//     SenderCardRecorderRenderer pattern); click again to stop.
//   - #broadcast-send-button — open a confirm modal → POST the broadcast.
//
// Recipient auto-refresh (legacy `refreshSessions()` on persona lifecycle)
// rides the EXISTING `store_session_strip_changed` event (SessionStripStore
// emits it on voice_persona_assigned/released + session_reaped) — no new
// EventBus event. The renderer is the SOLE consumer of BroadcastStore and
// drives every repaint after awaiting `store.hydrate`.
//
// The recorder is injected (default: the recordingManager singleton) so the
// STT onComplete/onError/recording-toggle paths are deterministic under test —
// the rafFn/nowFn/fetcher injection idiom used across the multiplexer tree.

import type { EventBus } from "../shared/EventBus";
import type { BroadcastStore, BroadcastRecipient } from "../stores/BroadcastStore";
import type { BroadcastSessionsApiClient } from "../stores/BroadcastStore";
import type { BroadcastRequest, BroadcastResult } from "../api/ApiClient";
import { recordingManager } from "../audio/recordingManager";
import type { RecordingManagerStartOptions } from "../audio/recordingManager";
import { insertTranscriptionText } from "./insertTranscriptionText";
import { renderBroadcastCard } from "./templates/broadcastCard";

// Minimal recorder surface the renderer depends on (injectable for tests).
export interface BroadcastRecorderLike {
  startRecording( opts: RecordingManagerStartOptions ): Promise<void>;
  stopRecording( contextId: string ): Promise<void>;
}

// The ApiClient capabilities the card needs: the active-sessions GET (via the
// store) + the broadcast POST. Narrow so tests stub only what they exercise.
export interface BroadcastCardApiClient extends BroadcastSessionsApiClient {
  broadcastToCcSessions( req: BroadcastRequest ): Promise<BroadcastResult>;
}

export interface BroadcastCardRenderer {
  /** Build the card into `root` + wire behavior. Throws on a 2nd mount. */
  mount( root: HTMLElement ): void;
  /** Detach: unsubscribe, drop handlers, remove any open modal, clear root. */
  unmount(): void;
  /** Test helper — re-render the recipient chips + send-button state. */
  forceRenderForTesting(): void;
}

export interface BroadcastCardRendererOptions {
  eventBus      : EventBus;
  store         : BroadcastStore;
  api           : BroadcastCardApiClient;
  /** Optional auth-token getter — production forwards the live JWT. */
  getAuthToken? : () => string | null;
  /** Optional recorder override — production uses the recordingManager singleton. */
  recorder?     : BroadcastRecorderLike;
  /** Trailing-debounce window for the persona-lifecycle recipient refresh
   *  (store_session_strip_changed bursts). Production default 250 ms; tests
   *  override to 0 for single-tick scheduling. */
  recipientsRefreshDebounceMs? : number;
  /** Injection points for deterministic test scheduling. Production wiring
   *  uses `globalThis.setTimeout` / `globalThis.clearTimeout`. */
  setTimeoutFn?   : ( cb: () => void, ms: number ) => unknown;
  clearTimeoutFn? : ( id: unknown ) => void;
}

const STT_CONTEXT_ID = "broadcast";
const DEFAULT_RECIPIENTS_REFRESH_DEBOUNCE_MS = 250;

// The text-input snapshot captured when a record starts (mirrors the
// SenderCardRecorderRenderer F5 caret-splice stash).
interface RerecordStash {
  text     : string;
  selStart : number | null;
  selEnd   : number | null;
}

type ChipState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "list" };

class BroadcastCardRendererImpl implements BroadcastCardRenderer {
  private readonly bus          : EventBus;
  private readonly store        : BroadcastStore;
  private readonly api          : BroadcastCardApiClient;
  private readonly getAuthToken : () => string | null;
  private readonly recorder     : BroadcastRecorderLike;
  private readonly debounceMs     : number;
  private readonly setTimeoutFn   : ( cb: () => void, ms: number ) => unknown;
  private readonly clearTimeoutFn : ( id: unknown ) => void;

  // Monotonic refresh token — only the freshest refresh is allowed to paint
  // (last-request-wins; drops stale out-of-order hydrate resolves).
  private refreshSeq    = 0;
  // Pending trailing-debounce handle for the burst-driven recipient refresh.
  private debounceTimer : unknown = null;

  private mounted = false;
  private root         : HTMLElement | null = null;
  private cardEl       : HTMLElement | null = null;
  private toggleBtn    : HTMLElement | null = null;
  private recipientsRow: HTMLElement | null = null;
  private sttBtn       : HTMLButtonElement | null = null;
  private textarea     : HTMLTextAreaElement | null = null;
  private sendBtn      : HTMLButtonElement | null = null;
  private statusEl     : HTMLElement | null = null;

  private clickHandler : ( ( e: Event ) => void ) | null = null;
  private inputHandler : ( () => void ) | null = null;
  private modalOverlay : HTMLElement | null = null;
  private recording    = false;
  private stash        : RerecordStash | undefined;
  private readonly unsubscribers : Array<() => void> = [];

  constructor( opts: BroadcastCardRendererOptions ) {
    if ( !opts.store ) {
      throw new Error( "BroadcastCardRenderer requires a store" );
    }
    this.bus   = opts.eventBus;
    this.store = opts.store;
    this.api   = opts.api;
    /* c8 ignore next */ // production wiring always supplies getAuthToken; the default returns null (AudioRecorder treats as "no Bearer header").
    this.getAuthToken = opts.getAuthToken ?? ( () => null );
    /* c8 ignore next */ // production-default fallback: the recordingManager singleton is the runtime recorder; tests always inject a deterministic fake.
    this.recorder = opts.recorder ?? recordingManager;
    this.debounceMs     = opts.recipientsRefreshDebounceMs ?? DEFAULT_RECIPIENTS_REFRESH_DEBOUNCE_MS;
    this.setTimeoutFn   = opts.setTimeoutFn   ?? ( ( cb, ms ) => globalThis.setTimeout( cb, ms ) );
    this.clearTimeoutFn = opts.clearTimeoutFn ?? ( ( id )     => globalThis.clearTimeout( id as ReturnType<typeof globalThis.setTimeout> ) );
  }

  // -------------------------------------------------------------------------
  // Lifecycle
  // -------------------------------------------------------------------------

  mount( root: HTMLElement ): void {
    if ( this.mounted ) {
      throw new Error( "BroadcastCardRenderer already mounted" );
    }
    root.appendChild( renderBroadcastCard( this.store.isCardOpen() ) );

    this.root          = root;
    this.cardEl        = root.querySelector( "#broadcast-submit-card" );
    this.toggleBtn     = root.querySelector( "#broadcast-submit-toggle" );
    this.recipientsRow = root.querySelector( "#broadcast-recipients-row" );
    this.sttBtn        = root.querySelector( "#broadcast-stt-button" );
    this.textarea      = root.querySelector( "#broadcast-textarea" );
    this.sendBtn       = root.querySelector( "#broadcast-send-button" );
    this.statusEl      = root.querySelector( "#broadcast-submit-status" );
    this.mounted       = true;

    this.attachDelegation();
    this.subscribe();

    this.renderChips( { kind: "loading" } );
    this.updateSendButton();
    this.performRefresh();   // immediate first paint (no debounce — initial mount)
  }

  unmount(): void {
    if ( !this.mounted ) return;   // idempotent

    // Cancel any in-flight trailing-debounce so it can't fire after teardown.
    if ( this.debounceTimer !== null ) {
      this.clearTimeoutFn( this.debounceTimer );
      this.debounceTimer = null;
    }

    for ( const off of this.unsubscribers ) off();
    this.unsubscribers.length = 0;

    if ( this.root !== null && this.clickHandler !== null ) {
      this.root.removeEventListener( "click", this.clickHandler );
    }
    if ( this.textarea !== null && this.inputHandler !== null ) {
      this.textarea.removeEventListener( "input", this.inputHandler );
    }
    this.clickHandler = null;
    this.inputHandler = null;

    this.removeModal();

    if ( this.root !== null ) this.root.replaceChildren();
    this.root = this.cardEl = this.toggleBtn = this.recipientsRow = null;
    this.statusEl = null;
    this.sttBtn = this.sendBtn = null;
    this.textarea = null;
    this.recording = false;
    this.stash = undefined;
    this.mounted = false;
  }

  forceRenderForTesting(): void {
    this.renderChips( { kind: "list" } );
    this.updateSendButton();
  }

  // -------------------------------------------------------------------------
  // Subscriptions + delegation
  // -------------------------------------------------------------------------

  private subscribe(): void {
    // Recipient auto-refresh on the persona-lifecycle signal (legacy
    // refreshSessions()). SessionStripStore emits this for
    // voice_persona_assigned/released + session_reaped. This signal can BURST
    // (a fleet reap/respawn fires many in quick succession), so it rides the
    // trailing-debounced scheduleRefresh — coalescing the burst into ONE
    // active-sessions GET instead of one per event (nit-2).
    this.unsubscribers.push(
      this.bus.on( "store_session_strip_changed", () => this.scheduleRefresh() ),
    );
  }

  private attachDelegation(): void {
    /* c8 ignore next */ // defensive: root is set in mount() immediately before this runs.
    if ( this.root === null ) return;

    this.clickHandler = ( e: Event ): void => {
      const target = e.target as Element | null;
      /* c8 ignore next */ // defensive: a fired click event always carries a target Element.
      if ( target === null ) return;

      // ↻ refresh (inside the recipients row, NOT the header). A user click is
      // an explicit gesture — refresh IMMEDIATELY (no debounce lag).
      if ( target.closest( "#broadcast-recipients-refresh" ) !== null ) {
        this.performRefresh();
        return;
      }
      // A recipient chip — inject its @mention token.
      const chip = target.closest( ".broadcast-chip" ) as HTMLElement | null;
      if ( chip !== null ) {
        this.injectMentionAtCursor( chip.getAttribute( "data-token" ) ?? "" );
        return;
      }
      // 🎤 STT.
      if ( target.closest( "#broadcast-stt-button" ) !== null ) {
        this.handleMicClick();
        return;
      }
      // Send → confirm modal.
      if ( target.closest( "#broadcast-send-button" ) !== null ) {
        /* c8 ignore next */ // defensive: sendBtn is present whenever a click on it fires; the null arm guards an out-of-band dispatch.
        if ( this.sendBtn !== null && !this.sendBtn.disabled ) this.showConfirmModal();
        return;
      }
      // Card collapse/expand — the header (the toggle button lives inside it).
      if ( target.closest( "#broadcast-submit-header" ) !== null ) {
        this.toggleCard();
      }
    };
    this.root.addEventListener( "click", this.clickHandler );

    this.inputHandler = (): void => this.updateSendButton();
    /* c8 ignore next */ // defensive: textarea is present post-mount per the template invariant.
    if ( this.textarea !== null ) {
      this.textarea.addEventListener( "input", this.inputHandler );
    }
  }

  // -------------------------------------------------------------------------
  // Card collapse/expand
  // -------------------------------------------------------------------------

  private toggleCard(): void {
    const open = !this.store.isCardOpen();
    this.store.setCardOpen( open );
    // Section visibility is CSS-driven off data-card-open (broadcast.css).
    /* c8 ignore next */ // defensive: cardEl/toggleBtn are present post-mount per the template invariant.
    if ( this.cardEl !== null ) this.cardEl.setAttribute( "data-card-open", open ? "true" : "false" );
    /* c8 ignore next */
    if ( this.toggleBtn !== null ) this.toggleBtn.textContent = open ? "▼" : "▶";
  }

  // -------------------------------------------------------------------------
  // Recipients
  // -------------------------------------------------------------------------

  // Trailing-debounce the burst-driven refresh: coalesce a flurry of
  // store_session_strip_changed events into a single active-sessions GET. The
  // chips keep showing the current list until the trailing fetch resolves (no
  // per-event "loading…" flicker). Handles are injected for deterministic tests.
  private scheduleRefresh(): void {
    if ( this.debounceTimer !== null ) this.clearTimeoutFn( this.debounceTimer );
    this.debounceTimer = this.setTimeoutFn( () => {
      this.debounceTimer = null;
      this.performRefresh();
    }, this.debounceMs );
  }

  // Fetch the active-session list NOW and repaint. A monotonic refresh token
  // makes the paint last-request-wins: if a newer refresh started while this
  // hydrate was in flight, this resolve is stale and drops its paint, so an
  // out-of-order response can't clobber the freshest render.
  private performRefresh(): void {
    this.renderChips( { kind: "loading" } );
    const seq = ++this.refreshSeq;
    this.store.hydrate( this.api )
      .then( () => {
        if ( seq !== this.refreshSeq ) return;   // superseded by a newer refresh — drop the stale paint
        this.renderChips( { kind: "list" } );
        this.updateSendButton();
      } )
      .catch( ( err: unknown ) => {
        if ( seq !== this.refreshSeq ) return;   // superseded by a newer refresh — drop the stale error paint
        this.renderChips( { kind: "error", message: errorMessage( err ) } );
        this.updateSendButton();
      } );
  }

  // Rebuild the recipient chip-row, preserving the static label + ↻ refresh
  // button (legacy renderChips). Mirrors the loading / error / empty / list
  // states.
  private renderChips( state: ChipState ): void {
    const row = this.recipientsRow;
    /* c8 ignore next */ // defensive: recipientsRow is present post-mount per the template invariant.
    if ( row === null ) return;

    const label   = row.querySelector( "#broadcast-recipients-label" );
    const refresh = row.querySelector( "#broadcast-recipients-refresh" );
    row.replaceChildren();
    /* c8 ignore next */ // defensive: the label is part of the template and re-appended on every render.
    if ( label !== null ) row.appendChild( label );

    if ( state.kind === "loading" ) {
      row.appendChild( this.buildAtAllChip() );
      row.appendChild( buildStatusChip( "loading…", false ) );
    } else if ( state.kind === "error" ) {
      row.appendChild( buildStatusChip( "failed to load: " + state.message, true ) );
    } else {
      const recipients = this.store.recipients();
      if ( recipients.length === 0 ) {
        row.appendChild( buildStatusChip( "no active sessions", true ) );
      } else {
        row.appendChild( this.buildAtAllChip() );
        for ( const r of recipients ) row.appendChild( this.buildChip( r ) );
      }
    }

    /* c8 ignore next */ // defensive: the refresh button is part of the template and re-appended on every render.
    if ( refresh !== null ) row.appendChild( refresh );
  }

  private buildAtAllChip(): HTMLElement {
    return chipButton( "all", "📣", "@all", "", "Insert @all into the message" );
  }

  private buildChip( recipient: BroadcastRecipient ): HTMLElement {
    const name  = recipient.persona_name || recipient.session_id || "session";
    const icon  = recipient.persona_icon || "👤";
    const color = recipient.persona_color || "";
    return chipButton( name, icon, name, color, "Insert @" + name + " into the message" );
  }

  // Insert `@<token> ` at the textarea caret (legacy injectMentionAtCursor),
  // then refocus + refresh the send-button state.
  private injectMentionAtCursor( token: string ): void {
    /* c8 ignore next */ // defensive: textarea is present post-mount per the template invariant.
    if ( this.textarea === null ) return;
    if ( token === "" ) return;   // a malformed chip with no data-token — no-op
    const ta     = this.textarea;
    const insertText = "@" + token + " ";
    const start  = ta.selectionStart;
    const end    = ta.selectionEnd;
    const before = ta.value.slice( 0, start );
    const after  = ta.value.slice( end );
    ta.value = before + insertText + after;
    const newPos = start + insertText.length;
    ta.setSelectionRange( newPos, newPos );
    ta.focus();
    this.updateSendButton();
  }

  // -------------------------------------------------------------------------
  // Send button state
  // -------------------------------------------------------------------------

  private updateSendButton(): void {
    /* c8 ignore next */ // defensive: textarea + sendBtn are present post-mount per the template invariant.
    if ( this.textarea === null || this.sendBtn === null ) return;
    const hasBody       = this.textarea.value.trim().length > 0;
    const hasRecipients = this.store.recipients().length > 0;
    this.sendBtn.disabled = !( hasBody && hasRecipients );
    this.sendBtn.title    = this.sendBtn.disabled
      ? ( !hasBody ? "type a message first" : "no active sessions to broadcast to" )
      : "send broadcast to all listed sessions";
  }

  // -------------------------------------------------------------------------
  // 🎤 STT — record / stop (folds the caret-splice on completion)
  // -------------------------------------------------------------------------

  private handleMicClick(): void {
    /* c8 ignore next */ // defensive: textarea is present post-mount per the template invariant.
    if ( this.textarea === null ) return;

    if ( this.recording ) {
      void this.recorder.stopRecording( STT_CONTEXT_ID );
      return;
    }

    // Stash the live value + selection BEFORE recording so the transcription
    // splices at the caret rather than clobbering (SenderCardRecorder F5).
    this.stash = {
      text     : this.textarea.value,
      selStart : this.textarea.selectionStart,
      selEnd   : this.textarea.selectionEnd,
    };
    this.recording = true;
    this.setMicRecordingClass( true );

    void this.recorder.startRecording( {
      contextId : STT_CONTEXT_ID,
      authToken : this.getAuthToken(),
      onComplete : ( transcription ) => {
        /* c8 ignore next */ // defensive: a stash is always set above before startRecording runs; the undefined arm guards an out-of-band onComplete.
        const base    = this.stash ?? { text: "", selStart: null, selEnd: null };
        const spliced = insertTranscriptionText(
          base.text, base.selStart, base.selEnd, transcription ?? "",
        );
        this.recording = false;
        this.stash = undefined;
        this.setMicRecordingClass( false );
        this.applyInputValueAndCaret( spliced.value, spliced.caret );
        this.updateSendButton();
      },
      onError : ( err ) => {
        this.recording = false;
        this.stash = undefined;
        this.setMicRecordingClass( false );
        this.setStatus( "recording failed: " + err.message, true );
      },
      // ESC (or auto-cancel by a new recording) fires neither onComplete nor
      // onError — reset the mic UI so it doesn't stay stuck red. The stashed
      // textarea value is left untouched (cancel ≠ transcription).
      onCancel : () => {
        this.recording = false;
        this.stash = undefined;
        this.setMicRecordingClass( false );
      },
    } );
  }

  private setMicRecordingClass( recording: boolean ): void {
    /* c8 ignore next */ // defensive: sttBtn is present post-mount per the template invariant.
    if ( this.sttBtn !== null ) this.sttBtn.classList.toggle( "recording", recording );
  }

  private applyInputValueAndCaret( value: string, caret: number | null ): void {
    /* c8 ignore next */ // defensive: textarea is present before a record can complete.
    if ( this.textarea === null ) return;
    this.textarea.value = value;
    this.textarea.focus();
    // caret === null ⇒ source exposed no caret (append path) → focus only.
    if ( caret !== null ) this.textarea.setSelectionRange( caret, caret );
  }

  // -------------------------------------------------------------------------
  // Confirm modal + POST
  // -------------------------------------------------------------------------

  private showConfirmModal(): void {
    /* c8 ignore next */ // defensive: showConfirmModal is gated on !sendBtn.disabled, which requires a non-empty textarea.
    if ( this.textarea === null ) return;
    const message = this.textarea.value;
    const recipients = this.store.recipients();
    /* c8 ignore next */ // defensive: the send button is disabled (no modal) when there are no recipients.
    if ( recipients.length === 0 ) return;

    // Never stack overlays — drop any prior one first (the full-screen overlay
    // normally intercepts clicks, but guard against a double-open leaking the
    // first overlay into document.body).
    this.removeModal();

    const overlay = document.createElement( "div" );
    overlay.id = "broadcast-confirm-modal-overlay";
    overlay.setAttribute( "data-testid", "multiplexer-broadcast-confirm-overlay" );

    const modal = document.createElement( "div" );
    modal.id = "broadcast-confirm-modal";

    const heading = document.createElement( "h4" );
    heading.textContent = "Send broadcast to " + recipients.length +
      " session" + ( recipients.length === 1 ? "" : "s" ) + "?";
    modal.appendChild( heading );

    const recipientsDiv = document.createElement( "div" );
    recipientsDiv.className = "modal-recipients";
    for ( const r of recipients ) {
      const name = r.persona_name || r.session_id || "session";
      recipientsDiv.appendChild( chipButton( name, r.persona_icon || "👤", name, r.persona_color || "", "", false ) );
    }
    modal.appendChild( recipientsDiv );

    const previewDiv = document.createElement( "div" );
    previewDiv.className = "modal-preview";
    // textContent (NOT innerHTML) — the preview is unsanitized user input.
    previewDiv.textContent = message;
    modal.appendChild( previewDiv );

    const buttonsDiv = document.createElement( "div" );
    buttonsDiv.className = "modal-buttons";

    const cancelBtn = document.createElement( "button" );
    cancelBtn.className   = "btn-cancel";
    cancelBtn.type        = "button";
    cancelBtn.textContent = "Cancel";
    cancelBtn.addEventListener( "click", () => this.removeModal() );

    const confirmBtn = document.createElement( "button" );
    confirmBtn.className   = "btn-confirm";
    confirmBtn.type        = "button";
    confirmBtn.setAttribute( "data-testid", "multiplexer-broadcast-confirm-btn" );
    confirmBtn.textContent = "Confirm + Send";
    confirmBtn.addEventListener( "click", () => {
      void this.onConfirmSend( confirmBtn, message );
    } );

    buttonsDiv.appendChild( cancelBtn );
    buttonsDiv.appendChild( confirmBtn );
    modal.appendChild( buttonsDiv );

    overlay.appendChild( modal );
    overlay.addEventListener( "click", ( e: Event ): void => {
      if ( e.target === overlay ) this.removeModal();
    } );
    document.body.appendChild( overlay );
    this.modalOverlay = overlay;
  }

  private async onConfirmSend( confirmBtn: HTMLButtonElement, message: string ): Promise<void> {
    confirmBtn.disabled    = true;
    confirmBtn.textContent = "sending…";
    this.setStatus( "submitting…" );
    try {
      const result = await this.api.broadcastToCcSessions( {
        message,
        require_ack        : true,
        include_originator : true,
      } );
      this.removeModal();
      if ( this.textarea !== null ) this.textarea.value = "";
      this.updateSendButton();
      this.setStatus( formatSendStatus( result ) );
    } catch ( err ) {
      confirmBtn.disabled    = false;
      confirmBtn.textContent = "Confirm + Send";
      this.setStatus( "send failed: " + errorMessage( err ), true );
    }
  }

  private removeModal(): void {
    if ( this.modalOverlay !== null ) {
      this.modalOverlay.remove();
      this.modalOverlay = null;
    }
  }

  private setStatus( msg: string, isError = false ): void {
    /* c8 ignore next */ // defensive: statusEl is present post-mount per the template invariant.
    if ( this.statusEl === null ) return;
    this.statusEl.textContent = msg;
    this.statusEl.classList.toggle( "is-error", isError );
  }
}

// ---------------------------------------------------------------------------
// Pure DOM helpers
// ---------------------------------------------------------------------------

// A clickable (or static) recipient chip. `token` rides on `data-token` for the
// delegated injectMentionAtCursor lookup; non-clickable chips (confirm modal)
// omit the type + title.
function chipButton(
  token        : string,
  icon         : string,
  label        : string,
  color        : string,
  title        : string,
  clickable    = true,
): HTMLElement {
  const chip = document.createElement( clickable ? "button" : "span" );
  chip.className = clickable ? "broadcast-chip" : "broadcast-chip broadcast-chip-static";
  chip.setAttribute( "data-token", token );
  if ( clickable ) {
    ( chip as HTMLButtonElement ).type = "button";
    chip.title = title;
  }
  if ( color !== "" ) chip.style.borderColor = color;
  const iconEl = document.createElement( "span" );
  iconEl.className   = "broadcast-chip-icon";
  iconEl.textContent = icon;
  const nameEl = document.createElement( "span" );
  nameEl.textContent = label;
  chip.appendChild( iconEl );
  chip.appendChild( nameEl );
  return chip;
}

// A non-clickable status pill in the chip-row (loading / error / empty).
function buildStatusChip( text: string, isNoRecipients: boolean ): HTMLElement {
  const el = document.createElement( "span" );
  el.className   = isNoRecipients ? "broadcast-chip no-recipients" : "broadcast-chip";
  el.textContent = text;
  return el;
}

// Compose the post-send status line, surfacing the filtered_out fanout
// receipts (F3) so a silent broadcast miss is visible (legacy postBroadcast).
function formatSendStatus( result: BroadcastResult ): string {
  let filteredNote = "";
  if ( result.filtered_out.length > 0 ) {
    const reasons = result.filtered_out
      .map( f => f.reason + ": " + String( f.session_id ).slice( 0, 8 ) )
      .join( ", " );
    filteredNote = " — " + result.filtered_out.length + " filtered out (" + reasons + ")";
  }
  return "sent to " + result.recipients + " session" +
    ( result.recipients === 1 ? "" : "s" ) +
    " (broadcast_id " + result.broadcast_id.slice( 0, 8 ) + "…)" +
    filteredNote;
}

function errorMessage( err: unknown ): string {
  return err instanceof Error ? err.message : String( err );
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createBroadcastCardRenderer( opts: BroadcastCardRendererOptions ): BroadcastCardRenderer {
  return new BroadcastCardRendererImpl( opts );
}
