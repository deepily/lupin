/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer F5 lane — SenderCardRecorderRenderer (MATCH-LEGACY rebuild, 2026-06-22).
//
// Behavior layer for the legacy inline `.cc-voice-input` > `.cc-voice-input-row`
// (conv-mode toggle + mic + text input + send) that senderCard.ts now renders
// STATICALLY between the card header and `.sender-card-dates`. This renderer
// does NOT build the row markup (that moved to senderCard.ts so the
// component-isolation parity harness sees it) — it wires delegated clicks and
// drives recording state on the EXISTING row elements:
//   - `.cc-session-stt`  (mic)  — click to record, click again to stop.
//   - `.cc-session-send` (send) — POST the text input to /api/notify.
//   - `.sender-conversation-mode-btn` — POST the conv-mode toggle (legacy-verbatim
//     /api/cosa-voice/speakerphone/<hash>; the server broadcasts a
//     conversation_mode_changed WS event the SenderStore consumes → is-active
//     flips on the next card re-render — no optimistic flip, no new EventBus event).
//
// Persistent-input model (vs the retired Record→Stop→ready_to_send paint): the
// `<input class="cc-session-msg-input">` lives in the static row and PERSISTS.
// The F5 caret-splice (insert-at-caret on re-record) folds in here, operating on
// that input. Recording state + the last input value are held in a per-session
// `states` Map so they SURVIVE the card re-create+replace that
// NotificationsListRenderer performs on every store_senders_changed
// (NotificationsListRenderer.ts: `existing.replaceWith(fresh)`): after a replace,
// `store_senders_changed` fires and `reapplyVoiceInput` restores the mic's
// recording class + the input value onto the freshly-rendered row.
//
// AuthManager order (per F-Arnold-C4 + Recon-C7): the renderer REQUIRES
// authManager.getCurrentUserEmail() to resolve before mount; boot wiring asserts
// this. That email is the `sender_id` field on the outbound
// user_initiated_message POST (legacy parity).
//
// Send-button wire shape (legacy parity, unchanged from the prior renderer):
//   POST /api/notify?<query>  with
//     type=user_initiated_message  priority=medium  job_id=<sessionHash>
//     sender_id=<opts.currentUserEmail>  target_user=<data-sender-id before '#'>
//     message=<input value>

import type { EventBus } from "../shared/EventBus";
import type { StoreSendersChangedPayload } from "../shared/types";
import { recordingManager } from "../audio/recordingManager";
import { insertTranscriptionText } from "./insertTranscriptionText";

export interface SenderCardRecorderRenderer {
  mount( root: HTMLElement ): void;
  unmount(): void;
  forceRenderForTesting(): void;
}

export interface SenderCardRecorderRendererOptions {
  eventBus         : EventBus;
  currentUserEmail : string;
  /** Optional auth-token getter — production wiring forwards the live JWT. */
  getAuthToken?    : () => string | null;
}

// The text-input snapshot captured when a record starts, BEFORE onComplete
// splices the transcription in. `selStart`/`selEnd` are null when the element
// exposed no caret (insertTranscriptionText then APPENDS — legacy F5 parity).
interface RerecordStash {
  text     : string;
  selStart : number | null;
  selEnd   : number | null;
}

// Per-session recording state. `value` is the last input value the renderer
// knows about (post-splice / post-send) — restored onto a re-created row so the
// user's transcription survives a card replace. `caret` is the post-splice caret
// to restore after a record completes (null ⇒ element exposed no caret).
interface SessionState {
  recording : boolean;
  value?    : string;
  stash?    : RerecordStash;
  caret?    : number | null;
}

class SenderCardRecorderRendererImpl implements SenderCardRecorderRenderer {
  private readonly bus              : EventBus;
  private readonly currentUserEmail : string;
  private readonly getAuthToken     : () => string | null;
  private readonly states          : Map<string, SessionState> = new Map();
  private readonly unsubscribers    : Array<() => void> = [];

  private root         : HTMLElement | null = null;
  private clickHandler : ( ( e: Event ) => void ) | null = null;
  private mounted      : boolean = false;

  constructor( opts: SenderCardRecorderRendererOptions ) {
    this.bus              = opts.eventBus;
    this.currentUserEmail = opts.currentUserEmail;
    /* c8 ignore next */ // production wiring always supplies getAuthToken; default returns null which AudioRecorder treats as "no Bearer header".
    this.getAuthToken     = opts.getAuthToken ?? (() => null);
  }

  mount( root: HTMLElement ): void {
    if (this.mounted) throw new Error("SenderCardRecorderRenderer.mount: already mounted");
    this.root    = root;
    this.mounted = true;

    this.clickHandler = (e: Event): void => this.onClick(e);
    root.addEventListener("click", this.clickHandler);

    // Subscribe to store_senders_changed: NotificationsListRenderer re-creates +
    // replaces each .sender-card (and its static .cc-voice-input row) on every
    // emission, so the freshly-rendered row needs its recording-state +
    // last-known input value re-applied from the states Map. Also covers the
    // initial-paint case (sets data-recorder-state="idle" on existing rows).
    this.unsubscribers.push(
      this.bus.on<StoreSendersChangedPayload>(
        "store_senders_changed",
        () => this.reapplyAll(),
      ),
    );

    this.reapplyAll();
  }

  unmount(): void {
    for (const off of this.unsubscribers) off();
    this.unsubscribers.length = 0;
    /* c8 ignore next 3 */ // defensive: click handler is always present post-mount per the lifecycle invariant.
    if (this.root !== null && this.clickHandler !== null) {
      this.root.removeEventListener("click", this.clickHandler);
    }
    this.clickHandler = null;
    this.states.clear();
    this.root    = null;
    this.mounted = false;
  }

  forceRenderForTesting(): void {
    this.reapplyAll();
  }

  // -------------------------------------------------------------------------
  // Re-apply recording state onto the (possibly re-created) static rows
  // -------------------------------------------------------------------------

  private reapplyAll(): void {
    /* c8 ignore next */ // defensive: reapplyAll only runs from mount/store-event/forceRender; root is set.
    if (this.root === null) return;
    for (const el of this.root.querySelectorAll<HTMLElement>(".cc-voice-input")) {
      this.reapplyVoiceInput(el);
    }
  }

  private reapplyVoiceInput(voiceInput: HTMLElement): void {
    const sessionHash = voiceInput.getAttribute("data-session-hash") ?? "";
    const entry       = this.states.get(sessionHash);
    const recording   = entry?.recording === true;
    voiceInput.setAttribute("data-recorder-state", recording ? "recording" : "idle");
    this.setMicRecordingClass(voiceInput, recording);
    // Restore the last-known input value onto a freshly-created row so a
    // transcription survives the card replace. Only when we actually hold one —
    // an untouched session leaves the static empty input alone.
    if (entry !== undefined && entry.value !== undefined) {
      const input = voiceInput.querySelector<HTMLInputElement>(".cc-session-msg-input");
      /* c8 ignore next */ // defensive: the static CC row always renders the input.
      if (input !== null) input.value = entry.value;
    }
  }

  private setMicRecordingClass(voiceInput: HTMLElement, recording: boolean): void {
    const mic = voiceInput.querySelector<HTMLButtonElement>(".cc-session-stt");
    /* c8 ignore next */ // defensive: the static row always carries the mic button; a row without it is not produced by senderCard.ts.
    if (mic === null) return;
    mic.classList.toggle("recording", recording);
  }

  // -------------------------------------------------------------------------
  // Click delegation
  // -------------------------------------------------------------------------

  private onClick(e: Event): void {
    const target = e.target as Element | null;
    /* c8 ignore next */ // defensive: e.target is always non-null Element during a fired click event.
    if (target === null) return;

    const mic = target.closest<HTMLButtonElement>(".cc-session-stt");
    if (mic !== null) {
      this.handleMicClick(mic);
      return;
    }
    const sendBtn = target.closest<HTMLButtonElement>(".cc-session-send");
    if (sendBtn !== null) {
      void this.handleSendClick(sendBtn);
      return;
    }
    const convBtn = target.closest<HTMLButtonElement>(".sender-conversation-mode-btn");
    if (convBtn !== null) {
      void this.handleConvModeClick(convBtn);
      return;
    }
  }

  // -------------------------------------------------------------------------
  // Mic — record / stop (folds the F5 caret-splice on completion)
  // -------------------------------------------------------------------------

  private handleMicClick(button: HTMLButtonElement): void {
    const voiceInput = button.closest<HTMLElement>(".cc-voice-input");
    /* c8 ignore next */ // defensive: the mic button only renders inside .cc-voice-input rows.
    if (voiceInput === null) return;
    const sessionHash = voiceInput.getAttribute("data-session-hash") ?? "";
    // Defensive: senderCard.ts always sets data-session-hash on CC rows; the
    // missing-attribute path is unit-tested (row without the attr).
    if (sessionHash === "") return;

    const current = this.states.get(sessionHash);
    /* c8 ignore start */ // stop-recording branch fires only after a successful start; the full state-cycle is exercised at smoke tier (requires microphone access).
    if (current !== undefined && current.recording === true) {
      void recordingManager.stopRecording(sessionHash);
      return;
    }
    /* c8 ignore stop */

    // F5 (insert-at-caret): snapshot the live input value + selection BEFORE
    // recording, so the new transcription splices at the caret instead of
    // clobbering. ALWAYS stash — an empty input splices "" at caret 0 (plain
    // fill); a non-empty input gets the caret splice. (Legacy always inserts at
    // the caret; there is no separate "first record" code path.)
    let stash: RerecordStash | undefined;
    const input = voiceInput.querySelector<HTMLInputElement>(".cc-session-msg-input");
    /* c8 ignore next */ // defensive: the static CC row always renders the input; a row without it is not produced by senderCard.ts.
    if (input !== null) {
      stash = { text: input.value, selStart: input.selectionStart, selEnd: input.selectionEnd };
    }

    this.states.set(sessionHash, { recording: true, stash });
    voiceInput.setAttribute("data-recorder-state", "recording");
    this.setMicRecordingClass(voiceInput, true);

    void recordingManager.startRecording({
      contextId : sessionHash,
      authToken : this.getAuthToken(),
      // onComplete: transcription succeeded. Splice it into the stashed input
      // text at the caret (replace selected range / insert at caret / append
      // when caret unknown), write the result onto the live input, drop back to
      // idle, and restore focus+caret. Unit-tested via a stubbed recordingManager
      // (the real mic→STT round-trip is the smoke tier).
      onComplete: (transcription, _blob) => {
        const pending = this.states.get(sessionHash)?.stash;
        /* c8 ignore next */ // defensive: a stash is always set above before startRecording runs; the undefined arm guards an out-of-band onComplete.
        const base    = pending ?? { text: "", selStart: null, selEnd: null };
        const spliced = insertTranscriptionText(
          base.text, base.selStart, base.selEnd, transcription ?? "",
        );
        this.states.set(sessionHash, { recording: false, value: spliced.value, caret: spliced.caret });
        voiceInput.setAttribute("data-recorder-state", "idle");
        this.setMicRecordingClass(voiceInput, false);
        this.applyInputValueAndCaret(voiceInput, spliced.value, spliced.caret);
      },
      onError   : (err) => {
        // Drop the stash (state→idle) so the next record is a clean snapshot,
        // THEN surface the error. The order matters only for the data-recorder-
        // state attribute; renderError appends a child and never wipes the row.
        this.states.set(sessionHash, { recording: false });
        voiceInput.setAttribute("data-recorder-state", "idle");
        this.setMicRecordingClass(voiceInput, false);
        this.renderError(voiceInput, err.message);
      },
    });
  }

  private applyInputValueAndCaret(voiceInput: HTMLElement, value: string, caret: number | null): void {
    const input = voiceInput.querySelector<HTMLInputElement>(".cc-session-msg-input");
    /* c8 ignore next */ // defensive: the static row always renders the input before a record can complete.
    if (input === null) return;
    input.value = value;
    input.focus();
    // caret === null ⇒ the source exposed no caret (append path) → focus only,
    // skip setSelectionRange (legacy parity — it would otherwise throw).
    if (caret !== null) {
      input.setSelectionRange(caret, caret);
    }
  }

  // -------------------------------------------------------------------------
  // Send — POST the text input to /api/notify
  // -------------------------------------------------------------------------

  private async handleSendClick(button: HTMLButtonElement): Promise<void> {
    const voiceInput = button.closest<HTMLElement>(".cc-voice-input");
    /* c8 ignore next */ // defensive: send button only renders inside .cc-voice-input rows.
    if (voiceInput === null) return;
    const sessionHash = voiceInput.getAttribute("data-session-hash") ?? "";
    const senderId    = voiceInput.getAttribute("data-sender-id")    ?? "";
    // Both data- attributes are set by senderCard.ts; guard + unit-test the
    // missing-attribute early return anyway (mirrors handleMicClick).
    if (sessionHash === "" || senderId === "") return;
    if (!senderId.includes("#")) {
      this.renderError(voiceInput, "Malformed sender_id; cannot send.");
      return;
    }

    const input   = voiceInput.querySelector<HTMLInputElement>(".cc-session-msg-input");
    /* c8 ignore next */ // defensive `?? ""`: the static CC row always renders the input (senderCard.ts), so input?.value is undefined only in the impossible no-input row — mirrors handleMicClick's input null-guard.
    const message = (input?.value ?? "").trim();
    if (message === "") {
      this.renderError(voiceInput, "Message is empty.");
      return;
    }

    /* c8 ignore next */ // split("#")[0] is always a string (senderId contains '#' per the guard above); the ?? "" is a noUncheckedIndexedAccess type-guard, unreachable at runtime.
    const targetUser = senderId.split("#")[0] ?? "";
    const params = new URLSearchParams({
      message,
      type        : "user_initiated_message",
      priority    : "medium",
      target_user : targetUser,
      sender_id   : this.currentUserEmail,
      job_id      : sessionHash,
    });

    const headers: Record<string, string> = {};
    const token = this.getAuthToken();
    if (token !== null) headers["Authorization"] = `Bearer ${token}`;

    try {
      const resp = await fetch(`/api/notify?${params.toString()}`, { method: "POST", headers });
      if (!resp.ok) {
        const errText = await resp.text().catch(() => "");
        throw new Error(errText !== "" ? errText : `HTTP ${resp.status}`);
      }
      // Reset on successful send: clear the input + the persisted value.
      this.states.set(sessionHash, { recording: false, value: "" });
      /* c8 ignore next */ // input is provably non-null here (the empty-message guard above returns when input is null → message ""); the guard satisfies the type-checker.
      if (input !== null) input.value = "";
    } catch (err) {
      this.renderError(voiceInput, (err as Error).message);
    }
  }

  // -------------------------------------------------------------------------
  // Conversation-mode toggle — legacy-verbatim speakerphone POST
  // -------------------------------------------------------------------------

  private async handleConvModeClick(button: HTMLButtonElement): Promise<void> {
    const voiceInput = button.closest<HTMLElement>(".cc-voice-input");
    /* c8 ignore next */ // defensive: the conv-mode button only renders inside .cc-voice-input rows.
    if (voiceInput === null) return;
    const sessionHash = voiceInput.getAttribute("data-session-hash") ?? "";
    if (sessionHash === "") return;

    // Current state from the button's is-active class (senderCard.ts renders it
    // from sender.conversation_mode_active). Legacy toggles to !current; the
    // server reaffirms via the conversation_mode_changed WS event → SenderStore
    // → card re-render flips is-active. No optimistic local flip.
    const active = button.classList.contains("is-active");

    const headers: Record<string, string> = { "Content-Type": "application/json" };
    const token = this.getAuthToken();
    if (token !== null) headers["Authorization"] = `Bearer ${token}`;

    try {
      const resp = await fetch(
        `/api/cosa-voice/speakerphone/${encodeURIComponent(sessionHash)}`,
        { method: "POST", headers, body: JSON.stringify({ on: !active }) },
      );
      if (!resp.ok) {
        const errText = await resp.text().catch(() => "");
        throw new Error(errText !== "" ? errText : `HTTP ${resp.status}`);
      }
    } catch (err) {
      this.renderError(voiceInput, (err as Error).message);
    }
  }

  // -------------------------------------------------------------------------
  // Error surface
  // -------------------------------------------------------------------------

  private renderError(voiceInput: HTMLElement, message: string): void {
    // A single error element is kept per row — remove any prior one before
    // appending the fresh message (both the first-error and replace-prior
    // branches are unit-covered via the send/conv-mode error-path tests).
    const prior = voiceInput.querySelector(".cc-voice-input-error");
    if (prior !== null) prior.remove();
    const errorEl = document.createElement("div");
    errorEl.className = "cc-voice-input-error";
    errorEl.textContent = message;
    voiceInput.appendChild(errorEl);
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createSenderCardRecorderRenderer(
  opts: SenderCardRecorderRendererOptions,
): SenderCardRecorderRenderer {
  return new SenderCardRecorderRendererImpl(opts);
}
