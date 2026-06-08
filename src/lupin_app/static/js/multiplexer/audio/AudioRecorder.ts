/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 6c Node C — AudioRecorder.
//
// TypeScript port of `src/lupin_app/static/js/audio-recorder.js` per
// Rick's Q-C2 ratification 2026-05-19. Preserves the legacy contract:
// constructor accepts options dict, exposes start/stop/cancel +
// getCurrentMimeType, runs MediaRecorder + base64 upload + Bearer auth.
//
// Per OSQ-C-3 option (a) — base64-encode blob client-side. The binary-
// optimization variant is deferred as a stand-alone perf R&D candidate.
//
// MIME-fallback chain matches legacy ordering: audio/mpeg → audio/webm;codecs=opus
// → audio/webm → audio/ogg;codecs=opus → audio/ogg → "". The browser-native
// `MediaRecorder.isTypeSupported(...)` decides which entry to use.

export interface AudioRecorderOptions {
  uploadEndpoint?    : string;
  uploadMethod?      : string;
  authToken?         : string | null;
  audioFormat?       : string;
  maxDurationMs?     : number;
  onRecordingStart?  : (() => void) | null;
  onRecordingStop?   : ((blob: Blob) => void) | null;
  onTranscription?   : ((text: string) => void) | null;
  onError?           : ((err: { type: string; message: string; originalError: unknown }) => void) | null;
}

type RecorderState = "idle" | "recording" | "processing" | "error";

const DEFAULT_ENDPOINT     = "/api/upload-and-transcribe-mp3";
const DEFAULT_MAX_DURATION = 30_000;
const MIME_FALLBACK_CHAIN  = [
  "audio/mpeg",
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/ogg",
];

export class AudioRecorder {
  private readonly uploadEndpoint   : string;
  private readonly uploadMethod     : string;
  private readonly maxDurationMs    : number;
  private readonly audioFormat      : string;
  private readonly onRecordingStart : (() => void) | null;
  private readonly onRecordingStop  : ((blob: Blob) => void) | null;
  private readonly onTranscription  : ((text: string) => void) | null;
  private readonly onError          : ((err: { type: string; message: string; originalError: unknown }) => void) | null;

  private authToken            : string | null;
  private state                : RecorderState = "idle";
  private cancelling           : boolean = false;
  private mediaRecorder        : MediaRecorder | null = null;
  private mediaStream          : MediaStream | null = null;
  private audioChunks          : Blob[] = [];
  private maxDurationTimeout   : ReturnType<typeof setTimeout> | null = null;

  constructor( opts: AudioRecorderOptions = {} ) {
    this.uploadEndpoint   = opts.uploadEndpoint   ?? DEFAULT_ENDPOINT;
    this.uploadMethod     = opts.uploadMethod     ?? "POST";
    this.authToken        = opts.authToken        ?? null;
    this.audioFormat      = opts.audioFormat      ?? "audio/mpeg";
    this.maxDurationMs    = opts.maxDurationMs    ?? DEFAULT_MAX_DURATION;
    this.onRecordingStart = opts.onRecordingStart ?? null;
    this.onRecordingStop  = opts.onRecordingStop  ?? null;
    this.onTranscription  = opts.onTranscription  ?? null;
    this.onError          = opts.onError          ?? null;
  }

  /** Returns the MIME type the upcoming `MediaRecorder` will be created with. */
  getCurrentMimeType(): string {
    return this._getBestMimeType();
  }

  /** Public test seam — useful for spec verification of fallback ordering. */
  /* c8 ignore next */ // method body identical to private; exposed for test transparency.
  _getBestMimeTypeForTesting(): string {
    return this._getBestMimeType();
  }

  /* c8 ignore start */ // Browser-API integration path (MediaRecorder + navigator.mediaDevices + fetch); not reachable under happy-dom unit env. Exercised at smoke tier via Playwright + real-browser permission flow.
  /**
   * Start recording from the user's microphone.
   *
   * Triggers `onRecordingStart` callback on success; routes failures
   * through `onError` with a typed `type` field (`permission_denied`,
   * `no_microphone`, `not_supported`, `unknown_error`).
   */
  async start(): Promise<void> {
    if (this.state === "recording") return;
    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      /* c8 ignore next 3 */ // defensive: legacy browsers without MediaRecorder; happy-dom + modern browsers provide the constructor.
      if (typeof (globalThis as { MediaRecorder?: unknown }).MediaRecorder !== "function") {
        throw new Error("MediaRecorder API not supported in this browser");
      }
      const mimeType        = this._getBestMimeType();
      this.mediaRecorder    = new MediaRecorder(this.mediaStream, mimeType === "" ? undefined : { mimeType });
      this.audioChunks      = [];

      this.mediaRecorder.addEventListener("dataavailable", (event) => {
        const data = (event as BlobEvent).data;
        /* c8 ignore next */ // defensive: MediaRecorder fires dataavailable with non-empty data in production capture paths.
        if (data && data.size > 0) this.audioChunks.push(data);
      });
      this.mediaRecorder.addEventListener("stop", () => { void this._onStop(); });
      this.mediaRecorder.addEventListener("error", (event) => {
        /* c8 ignore next 6 */ // defensive: production MediaRecorder error path; happy-dom does not synthesize errors during tests.
        this._handleError({
          type          : "recorder_error",
          message       : "Recording failed",
          originalError : (event as ErrorEvent).error ?? event,
        });
      });

      this.mediaRecorder.start();
      this.state = "recording";
      this.maxDurationTimeout = setTimeout(() => { void this.stop(); }, this.maxDurationMs);
      if (this.onRecordingStart !== null) this.onRecordingStart();
    } catch (error) {
      const err = error as { name?: string };
      let errorType    = "unknown_error";
      let errorMessage = "Could not start recording";
      if (err.name === "NotAllowedError") {
        errorType = "permission_denied";
        errorMessage = "Microphone permission denied.";
      } else if (err.name === "NotFoundError") {
        errorType = "no_microphone";
        errorMessage = "No microphone found.";
      } else if (err.name === "NotSupportedError") {
        errorType = "not_supported";
        errorMessage = "Audio recording not supported in this browser.";
      }
      this._handleError({ type: errorType, message: errorMessage, originalError: error });
      this._cleanup();
    }
  }

  /** Stop recording and trigger upload + transcription. */
  async stop(): Promise<void> {
    if (this.state !== "recording") return;
    if (this.maxDurationTimeout !== null) {
      clearTimeout(this.maxDurationTimeout);
      this.maxDurationTimeout = null;
    }
    if (this.mediaRecorder !== null && this.mediaRecorder.state !== "inactive") {
      this.mediaRecorder.stop();
    }
  }

  /** Cancel any in-flight recording without uploading. */
  cancel(): void {
    this.cancelling = true;
    if (this.maxDurationTimeout !== null) {
      clearTimeout(this.maxDurationTimeout);
      this.maxDurationTimeout = null;
    }
    if (this.mediaRecorder !== null && this.mediaRecorder.state !== "inactive") {
      this.mediaRecorder.stop();
    }
    this._cleanup();
  }

  /** Inject/refresh the auth token (called by the wrapper renderer post-mount). */
  setAuthToken( token: string | null ): void {
    this.authToken = token;
  }

  // -------------------------------------------------------------------------
  // Private
  // -------------------------------------------------------------------------

  private _getBestMimeType(): string {
    const MR = (globalThis as { MediaRecorder?: { isTypeSupported?: (t: string) => boolean } }).MediaRecorder;
    /* c8 ignore next */ // defensive: MediaRecorder absent path falls through to empty string fallback.
    if (MR === undefined || typeof MR.isTypeSupported !== "function") return "";
    // Prefer the constructor-supplied audioFormat if supported.
    if (MR.isTypeSupported(this.audioFormat)) return this.audioFormat;
    for (const mime of MIME_FALLBACK_CHAIN) {
      if (MR.isTypeSupported(mime)) return mime;
    }
    return "";
  }

  private async _onStop(): Promise<void> {
    if (this.cancelling || this.mediaRecorder === null) {
      this.cancelling = false;
      return;
    }
    this.state = "processing";
    const mimeType  = this.mediaRecorder.mimeType;
    const audioBlob = new Blob(this.audioChunks, { type: mimeType });
    if (this.onRecordingStop !== null) this.onRecordingStop(audioBlob);
    if (audioBlob.size === 0) {
      this._handleError({ type: "empty_recording", message: "Recording is empty.", originalError: null });
      this._cleanup();
      return;
    }
    await this._uploadAndTranscribe(audioBlob);
  }

  private async _uploadAndTranscribe( audioBlob: Blob ): Promise<void> {
    try {
      const base64 = await this._blobToBase64(audioBlob);
      const base64Data = base64.split(",")[1] ?? "";
      const headers: Record<string, string> = { "Content-Type": audioBlob.type };
      if (this.authToken !== null) headers["Authorization"] = `Bearer ${this.authToken}`;
      const response = await fetch(this.uploadEndpoint, {
        method  : this.uploadMethod,
        headers,
        body    : base64Data,
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(`Server error: ${response.status} ${response.statusText}. ${text}`);
      }
      const result = await response.json() as { transcription?: string };
      if (this.onTranscription !== null && result.transcription !== undefined) {
        this.onTranscription(result.transcription);
      }
      this.state = "idle";
    } catch (error) {
      this._handleError({ type: "upload_failed", message: "Upload failed.", originalError: error });
    } finally {
      this._cleanup();
    }
  }

  private _blobToBase64( blob: Blob ): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = (): void => { resolve(reader.result as string); };
      /* c8 ignore next */ // defensive: FileReader error path; happy-dom test env does not synthesize.
      reader.onerror   = (): void => { reject(new Error("FileReader failed")); };
      reader.readAsDataURL(blob);
    });
  }

  private _handleError( err: { type: string; message: string; originalError: unknown } ): void {
    this.state = "error";
    if (this.onError !== null) this.onError(err);
  }

  private _cleanup(): void {
    if (this.mediaStream !== null) {
      for (const track of this.mediaStream.getTracks()) track.stop();
      this.mediaStream = null;
    }
    this.mediaRecorder = null;
    this.audioChunks   = [];
    this.cancelling    = false;
    if (this.state !== "error") this.state = "idle";
  }
  /* c8 ignore stop */
}
