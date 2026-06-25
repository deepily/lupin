/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 6c Node C — recordingManager singleton.
//
// TypeScript port of `notifications.js:3491+` recordingManager. Coordinates:
// - Single-active recording (cancel previous before starting new)
// - TTS pause on record start (only if AudioStore says playing); resume on
//   stop AFTER a small delay so users don't hear a blip
// - ESC key cancels active recording
// - Per-context onComplete callbacks (the wrapper renderer fills in
//   transcription/blob handling per sender card)
//
// The singleton wraps an `AudioRecorder` instance — lazily created per
// startRecording() call (matches legacy lazy-per-call pattern).

import { AudioRecorder } from "./AudioRecorder";

export interface RecordingManagerStartOptions {
  /** Required: identifier for the active recording (per sender card session). */
  contextId         : string;
  /** Auth token forwarded to AudioRecorder for the upload Authorization header. */
  authToken?        : string | null;
  /** Optional override for the upload endpoint. */
  uploadEndpoint?   : string;
  /** Called when transcription succeeds. The wrapper renderer typically
   *  fills an input element + transitions UI state to "ready_to_send". */
  onComplete?       : (transcription: string, blob: Blob) => void;
  /** Called on recording errors (typed in AudioRecorder._handleError). */
  onError?          : (err: { type: string; message: string; originalError: unknown }) => void;
  /** Called when the recording starts (UI can flip to "recording" state). */
  onRecordingStart? : () => void;
  /** Called when the recording is CANCELLED (ESC, or auto-cancel of a prior
   *  recording when a new one starts). AudioRecorder.cancel() fires NEITHER
   *  onComplete nor onError, so without this hook every consumer is left with
   *  its mic UI stuck in the "recording" state. Each consumer wires this to
   *  reset its own mic UI back to idle. */
  onCancel?         : () => void;
}

interface ActiveRecording {
  contextId : string;
  recorder  : AudioRecorder;
  options   : RecordingManagerStartOptions;
}

const MAX_DURATION_MS    = 30_000;
const TTS_RESUME_DELAY_MS = 750;

class RecordingManager {
  private active                : ActiveRecording | null = null;
  private escListener           : ((e: KeyboardEvent) => void) | null = null;
  // TTS coordination — only auto-resume if WE caused the pause (never resume
  // a user-initiated pause).
  private ttsPausedByRecording  : boolean = false;
  private resumeTimeoutHandle   : ReturnType<typeof setTimeout> | null = null;

  /** Called by boot wiring to inject the TTS pause/resume + AudioStore-playing
   *  signal hooks. Defaults are no-ops so unit tests don't need to mock them. */
  /* c8 ignore next */ // injection hook; default no-op closures are not invoked under test.
  ttsIsPlaying  : () => boolean       = () => false;
  ttsPause      : () => void          = () => {};
  ttsResume     : () => void          = () => {};

  /**
   * Start recording for the named context. If a recording is already in
   * flight, cancel it first (legacy auto-cancel-previous pattern).
   */
  async startRecording( opts: RecordingManagerStartOptions ): Promise<void> {
    // Cancel any prior recording (single-active invariant).
    if (this.active !== null) {
      this.cancelRecording(this.active.contextId);
    }

    // TTS pause-on-record if currently playing.
    if (this.ttsIsPlaying()) {
      this.ttsPause();
      this.ttsPausedByRecording = true;
    }

    const recorder = new AudioRecorder({
      authToken         : opts.authToken ?? null,
      uploadEndpoint    : opts.uploadEndpoint,
      maxDurationMs     : MAX_DURATION_MS,
      onRecordingStart  : opts.onRecordingStart ?? null,
      /* c8 ignore start */ // onTranscription only fires after a successful upload + transcribe round-trip; exercised at smoke tier.
      onTranscription   : (text) => {
        if (opts.onComplete !== undefined) {
          opts.onComplete(text, new Blob());
        }
      },
      /* c8 ignore stop */
      onError           : opts.onError ?? null,
    });

    this.active = { contextId: opts.contextId, recorder, options: opts };

    // ESC handler — cancel on press.
    this.escListener = (e: KeyboardEvent): void => {
      /* c8 ignore next */ // defensive: only the Escape key path is exercised; other keys are no-ops.
      if (e.key === "Escape") {
        this.cancelRecording(opts.contextId);
      }
    };
    /* c8 ignore next */ // happy-dom provides window + addEventListener; production wires identically.
    if (typeof window !== "undefined") {
      window.addEventListener("keydown", this.escListener);
    }

    await recorder.start();
  }

  /* c8 ignore start */ // stop-with-active path requires a successful start (microphone access + an upload round-trip); exercised at smoke tier. The no-active early-return is unit-covered.
  /** Stop the active recording (uploads + transcribes). */
  async stopRecording( contextId: string ): Promise<void> {
    if (this.active === null || this.active.contextId !== contextId) return;
    await this.active.recorder.stop();
    this.scheduleTtsResume();
    this.detachEscListener();
    this.active = null;
  }
  /* c8 ignore stop */

  /**
   * Cancel the active recording without uploading. AudioRecorder.cancel()
   * fires no onComplete/onError, so we invoke the consumer's onCancel here so
   * its mic UI can reset (capture the callback BEFORE nulling `active`). Also
   * called internally by startRecording to enforce the single-active invariant
   * — in which case the PRIOR recording's consumer is correctly notified.
   */
  cancelRecording( contextId: string ): void {
    if (this.active === null || this.active.contextId !== contextId) return;
    const onCancel = this.active.options.onCancel;
    this.active.recorder.cancel();
    this.scheduleTtsResume();
    this.detachEscListener();
    this.active = null;
    if (onCancel !== undefined) onCancel();
  }

  /** Test seam — returns the contextId of the active recording, or null. */
  getActiveContextId(): string | null {
    return this.active === null ? null : this.active.contextId;
  }

  // -------------------------------------------------------------------------
  // Private
  // -------------------------------------------------------------------------

  /* c8 ignore start */ // TTS resume timer path; production timing-dependent flow exercised at smoke tier with real TTS playback.
  private scheduleTtsResume(): void {
    if (!this.ttsPausedByRecording) return;
    if (this.resumeTimeoutHandle !== null) {
      clearTimeout(this.resumeTimeoutHandle);
    }
    this.resumeTimeoutHandle = setTimeout(() => {
      this.ttsResume();
      this.ttsPausedByRecording = false;
      this.resumeTimeoutHandle  = null;
    }, TTS_RESUME_DELAY_MS);
  }
  /* c8 ignore stop */

  private detachEscListener(): void {
    /* c8 ignore next */ // defensive: only the wired listener is detached; happy-dom + production both support removeEventListener.
    if (this.escListener !== null && typeof window !== "undefined") {
      window.removeEventListener("keydown", this.escListener);
    }
    this.escListener = null;
  }
}

// Singleton (matches legacy this.recordingManager pattern).
/* c8 ignore next */ // tsx phantom-branch artifact on the top-level singleton instantiation (executed on every import; no real branch).
export const recordingManager = new RecordingManager();
