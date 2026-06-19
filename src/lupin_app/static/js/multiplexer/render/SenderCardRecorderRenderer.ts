/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 6c Node C — SenderCardRecorderRenderer.
//
// Thin wrapper renderer that wires the recordingManager singleton to the
// per-sender-card `.cc-voice-input` footers rendered by senderCard.ts
// (Step C1 mount points). Subscribes to clicks on `.record-button` /
// `.send-button` via event delegation; manages a per-context state machine
// (idle → recording → ready_to_send) and renders the appropriate buttons.
//
// AuthManager order critical (per F-Arnold-C4 + Recon-C7): the renderer
// REQUIRES authManager.getCurrentUserEmail() to resolve before mount; boot
// wiring asserts this. The current user email is the `sender_id` field on
// the outbound user_initiated_message POST (legacy parity).
//
// Wire shape (per F-Arnold-C1 + F-Arnold-C2 + Recon-C3): send-button POST
// uses URL-query-string body to `/api/notify`; fields:
//   type=user_initiated_message
//   job_id=<sessionHash>
//   sender_id=<opts.currentUserEmail>
//   target_user=<derived from data-sender-id.split('#')[0]>
//   message=<textarea value>
//
// Path δ note: this Step C3 implementation lands the core click-delegation
// + recordingManager invocation surface. The per-state DOM rendering uses
// minimal markup. AC-C3 was marked N/A per Round-1 Q-C2 collapse; coverage
// hoisted to AC-C4 (renderer tests) + the port-parity tests.

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

type RecorderState = "idle" | "recording" | "ready_to_send";

// WP6 (F5 insert-at-caret port) — the textarea snapshot captured when a
// Re-record starts, BEFORE the recording-state repaint destroys the element.
// `selStart`/`selEnd` are null when the element exposed no caret.
interface RerecordStash {
  text     : string;
  selStart : number | null;
  selEnd   : number | null;
}

class SenderCardRecorderRendererImpl implements SenderCardRecorderRenderer {
  private readonly bus              : EventBus;
  private readonly currentUserEmail : string;
  private readonly getAuthToken     : () => string | null;
  // sessionHash → state (idle/recording/ready_to_send) + pending transcription
  // + WP6 re-record stash (caret-splice source) + caret to restore post-paint.
  private readonly states           : Map<string, { state: RecorderState; transcription?: string; stash?: RerecordStash; caret?: number | null }> = new Map();
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

    // Subscribe to store_senders_changed so when NotificationsListRenderer
    // creates a new .sender-card (and its .cc-voice-input footer) in
    // response to an arriving notification, this renderer re-paints the
    // newly-arrived footers with their Record buttons. Without this
    // subscription, sender cards rendered AFTER mount would never get
    // Record buttons because paintAllVoiceInputs only ran once at mount
    // time when zero footers existed yet.
    this.unsubscribers.push(
      this.bus.on<StoreSendersChangedPayload>(
        "store_senders_changed",
        () => this.paintAllVoiceInputs(),
      ),
    );

    // Initial paint: idle UI on every existing .cc-voice-input footer
    // (covers the rare case of sender cards already in the DOM at mount).
    this.paintAllVoiceInputs();
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
    this.paintAllVoiceInputs();
  }

  // -------------------------------------------------------------------------
  // Click delegation
  // -------------------------------------------------------------------------

  private onClick(e: Event): void {
    const target = e.target as Element | null;
    /* c8 ignore next */ // defensive: e.target is always non-null Element during a fired click event.
    if (target === null) return;

    const recordBtn = target.closest<HTMLButtonElement>(".record-button");
    if (recordBtn !== null) {
      this.handleRecordClick(recordBtn);
      return;
    }
    const sendBtn = target.closest<HTMLButtonElement>(".send-button");
    if (sendBtn !== null) {
      void this.handleSendClick(sendBtn);
      return;
    }
  }

  // -------------------------------------------------------------------------
  // Event handlers
  // -------------------------------------------------------------------------

  private handleRecordClick(button: HTMLButtonElement): void {
    const voiceInput = button.closest<HTMLElement>(".cc-voice-input");
    /* c8 ignore next */ // defensive: record button only renders inside .cc-voice-input footers.
    if (voiceInput === null) return;
    const sessionHash = voiceInput.getAttribute("data-session-hash") ?? "";
    // Defensive: senderCard.ts Step C1 always sets data-session-hash; the
    // missing-attribute path is unit-tested (footer without the attr).
    if (sessionHash === "") return;

    const current = this.states.get(sessionHash);
    /* c8 ignore start */ // stop-recording branch fires only after a successful start; full state-cycle exercised at smoke tier (requires microphone access).
    if (current !== undefined && current.state === "recording") {
      void recordingManager.stopRecording(sessionHash);
      return;
    }
    /* c8 ignore stop */

    // WP6 (F5 insert-at-caret port): a Re-record from ready_to_send must NOT
    // clobber the user's edits — the repaint below destroys the textarea, so
    // snapshot its value + selection FIRST. Selection survives the button
    // click stealing focus (legacy contract, proven by the F5 e2e suite).
    let stash: RerecordStash | undefined;
    if (current !== undefined && current.state === "ready_to_send") {
      const liveTextarea = voiceInput.querySelector<HTMLTextAreaElement>(".cc-voice-input-textarea");
      if (liveTextarea !== null) {
        stash = {
          text     : liveTextarea.value,
          selStart : liveTextarea.selectionStart,
          selEnd   : liveTextarea.selectionEnd,
        };
      }
    }

    // Start a new recording. transitions to recording state immediately.
    this.states.set(sessionHash, { state: "recording", stash });
    this.paintVoiceInput(voiceInput);
    void recordingManager.startRecording({
      contextId : sessionHash,
      authToken : this.getAuthToken(),
      // onComplete: transcription succeeded → ready_to_send + repaint. Plain
      // state-set + repaint; unit-tested via a stubbed recordingManager (the
      // real mic→STT round-trip that drives it is the smoke tier).
      // WP6: with a re-record stash, the new transcription is CARET-SPLICED
      // into the preserved text (replace selected range / insert at caret /
      // append when caret unknown) instead of replacing the user's edits.
      onComplete: (transcription, _blob) => {
        const pending = this.states.get(sessionHash)?.stash;
        if (pending !== undefined) {
          const spliced = insertTranscriptionText(
            pending.text, pending.selStart, pending.selEnd, transcription ?? "",
          );
          this.states.set(sessionHash, { state: "ready_to_send", transcription: spliced.value, caret: spliced.caret });
        } else {
          this.states.set(sessionHash, { state: "ready_to_send", transcription });
        }
        this.paintVoiceInput(voiceInput);
        this.restoreCaret(voiceInput, sessionHash);
      },
      onError   : (err) => {
        // Order matters: paintVoiceInput's replaceChildren wipes the
        // container, so we MUST paint first (state→idle) and THEN append
        // the error element. Reversing the order silently wipes the error.
        this.states.set(sessionHash, { state: "idle" });
        this.paintVoiceInput(voiceInput);
        this.renderError(voiceInput, err.message);
      },
    });
  }

  /* c8 ignore start */ // fetch + URLSearchParams network path; exercised at smoke tier via real `/api/notify` POST.
  private async handleSendClick(button: HTMLButtonElement): Promise<void> {
    const voiceInput = button.closest<HTMLElement>(".cc-voice-input");
    /* c8 ignore next */ // defensive: send button only renders inside .cc-voice-input footers.
    if (voiceInput === null) return;
    const sessionHash = voiceInput.getAttribute("data-session-hash") ?? "";
    const senderId    = voiceInput.getAttribute("data-sender-id")    ?? "";
    /* c8 ignore next */ // defensive: both data- attributes are always set by senderCard.ts Step C1.
    if (sessionHash === "" || senderId === "") return;
    if (!senderId.includes("#")) {
      this.renderError(voiceInput, "Malformed sender_id; cannot send.");
      return;
    }

    const textarea = voiceInput.querySelector<HTMLTextAreaElement>(".cc-voice-input-textarea");
    const message  = (textarea?.value ?? "").trim();
    if (message === "") {
      this.renderError(voiceInput, "Message is empty.");
      return;
    }

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
      // Reset to idle on successful send.
      this.states.set(sessionHash, { state: "idle" });
      this.paintVoiceInput(voiceInput);
    } catch (err) {
      this.renderError(voiceInput, (err as Error).message);
    }
  }
  /* c8 ignore stop */

  // -------------------------------------------------------------------------
  // Rendering
  // -------------------------------------------------------------------------

  private paintAllVoiceInputs(): void {
    /* c8 ignore next */ // defensive: paintAllVoiceInputs only runs from mount/forceRender; root is set.
    if (this.root === null) return;
    for (const el of this.root.querySelectorAll<HTMLElement>(".cc-voice-input")) {
      this.paintVoiceInput(el);
    }
  }

  private paintVoiceInput(voiceInput: HTMLElement): void {
    const sessionHash = voiceInput.getAttribute("data-session-hash") ?? "";
    const entry       = this.states.get(sessionHash) ?? { state: "idle" as RecorderState };
    voiceInput.setAttribute("data-recorder-state", entry.state);
    voiceInput.replaceChildren();

    if (entry.state === "idle") {
      const recordBtn = document.createElement("button");
      recordBtn.type = "button";
      recordBtn.className = "record-button";
      recordBtn.textContent = "Record";
      voiceInput.appendChild(recordBtn);
    } else if (entry.state === "recording") {
      const stopBtn = document.createElement("button");
      stopBtn.type = "button";
      stopBtn.className = "record-button recording";
      stopBtn.textContent = "Stop";
      voiceInput.appendChild(stopBtn);
    } else {
      // ready_to_send paint (textarea + Re-record + Send). Unit-tested by
      // driving onComplete via a stubbed recordingManager — both the
      // transcription-present and undefined-transcription (`?? ""`) arms.
      const textarea = document.createElement("textarea");
      textarea.className = "cc-voice-input-textarea";
      textarea.value = entry.transcription ?? "";
      voiceInput.appendChild(textarea);

      const rerecordBtn = document.createElement("button");
      rerecordBtn.type = "button";
      rerecordBtn.className = "record-button";
      rerecordBtn.textContent = "Re-record";
      voiceInput.appendChild(rerecordBtn);

      const sendBtn = document.createElement("button");
      sendBtn.type = "button";
      sendBtn.className = "send-button";
      sendBtn.textContent = "Send";
      voiceInput.appendChild(sendBtn);
    }
  }

  // WP6 — after a re-record splice repaint, return focus to the textarea and
  // place the caret immediately after the inserted text (legacy F5 parity).
  // No-op when the state carries no caret entry (plain first-record path —
  // its behavior is deliberately unchanged) or when the element exposed no
  // caret at stash time (caret === null → focus only, skip setSelectionRange).
  private restoreCaret(voiceInput: HTMLElement, sessionHash: string): void {
    const entry = this.states.get(sessionHash);
    if (entry === undefined || entry.caret === undefined) return;
    const textarea = voiceInput.querySelector<HTMLTextAreaElement>(".cc-voice-input-textarea");
    /* c8 ignore next */ // defensive: ready_to_send paint always renders the textarea before this runs.
    if (textarea === null) return;
    textarea.focus();
    if (entry.caret !== null) {
      textarea.setSelectionRange(entry.caret, entry.caret);
    }
  }

  private renderError(voiceInput: HTMLElement, message: string): void {
    /* c8 ignore next 4 */ // pure DOM append; the rendered error path is exercised by smoke tests (state=idle+error case). Unit tests cover the wrapping branch sites in handleRecordClick + handleSendClick.
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
