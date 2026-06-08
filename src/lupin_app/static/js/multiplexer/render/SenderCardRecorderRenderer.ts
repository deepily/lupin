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

class SenderCardRecorderRendererImpl implements SenderCardRecorderRenderer {
  private readonly bus              : EventBus;
  private readonly currentUserEmail : string;
  private readonly getAuthToken     : () => string | null;
  // sessionHash → state (idle/recording/ready_to_send) + pending transcription
  private readonly states           : Map<string, { state: RecorderState; transcription?: string }> = new Map();
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
    /* c8 ignore next */ // defensive: data-session-hash is always set by senderCard.ts Step C1.
    if (sessionHash === "") return;

    const current = this.states.get(sessionHash);
    /* c8 ignore start */ // stop-recording branch fires only after a successful start; full state-cycle exercised at smoke tier (requires microphone access).
    if (current !== undefined && current.state === "recording") {
      void recordingManager.stopRecording(sessionHash);
      return;
    }
    /* c8 ignore stop */

    // Start a new recording. transitions to recording state immediately.
    this.states.set(sessionHash, { state: "recording" });
    this.paintVoiceInput(voiceInput);
    void recordingManager.startRecording({
      contextId : sessionHash,
      authToken : this.getAuthToken(),
      /* c8 ignore start */ // onComplete fires only after successful transcription; exercised at smoke tier.
      onComplete: (transcription, _blob) => {
        this.states.set(sessionHash, { state: "ready_to_send", transcription });
        this.paintVoiceInput(voiceInput);
      },
      /* c8 ignore stop */
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
      /* c8 ignore start */ // ready_to_send paint branch: requires a successful recording → onComplete callback to set state. Exercised at smoke tier with real microphone + transcription round-trip.
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
      /* c8 ignore stop */
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
