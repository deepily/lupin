/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Parity B-1 (row key B-1) — QaStore, the Q&A Interface's model.
//
// Ports the legacy Q&A card's non-DOM half: the agent list, the one-shot route
// status line, the sticky voice-mode badge, the two submit doors, the inline
// argument interview's resume turn, the job-completion writer for the response
// pane, and the TTT/TTFA/RTT stamps the metrics strip renders.
//
// LEGACY SOURCES, cited by symbol so an edit above them does not rot the pointer:
//   loadAgentSelect          notifications.js:26104  (GET /api/v2/agents, cache, render)
//   updateOneShotRouteStatus notifications.js:26153  (the status line, one-shot language)
//   setModeStatus            notifications.js:26168
//   submitQA                 notifications.js:3099   (debounce, doors, spinner, clear)
//   handleQAResult           notifications.js:3236   (interview vs raw dump)
//   submitArgAnswer          notifications.js:3271   (POST /api/v2/resume, re-entry)
//   setAgentMode             notifications.js:26176  (POST /api/mode/current)
//   getAgentMode             notifications.js:26214  (GET  /api/mode/current)
//   updateModeUI             notifications.js:26252  (badge visibility; select untouched)
//   handleJobCompletion      notifications.js:4011   ("Job completed: …" + TTT)
//
// WHY THE SELECT IS NOT STATE HERE. Ruling 2 of the 2026.08.22 plan makes the agent
// choice a ONE-SHOT per-request route, not a persisted mode, so the `<select>`'s own
// value IS the state and the store never mirrors it. Legacy says the same thing at
// updateModeUI: "THE SELECT IS NO LONGER DRIVEN FROM HERE." The renderer passes the
// chosen value in on each submit.
//
// 🔴 THE BADGE AND THE SELECT ARE DIFFERENT THINGS, and conflating them is the defect
// legacy's comment was written to prevent. The badge shows the STICKY VOICE mode from
// /api/mode/current; the select routes the NEXT typed question. A click on the badge
// clears the voice mode and must not touch the select.

import type { EventBus } from "../shared/EventBus";
import type {
  StoreQaChangedPayload,
  TtsJobRequestPayload,
} from "../shared/types";
import {
  AGENTS_ENDPOINT,
  isAutoRoute,
  argsForCommand,
} from "../../shared/agent-select.js";
import { isAnswerable, resumeBody } from "../../shared/arg-interview.js";

// ---------------------------------------------------------------------------
// Wire shapes
// ---------------------------------------------------------------------------

// 🔴 THE WIRE SHAPES ARE ALIASES, NOT COPIES. Both are already written down, in the
// shared modules that read them — `AgentsPayload` in agent-select.js and `FlowResult`
// in arg-interview.js, each transcribed from the server's own Pydantic model rather
// than guessed. A second hand-written copy here would be a fourth description of the
// same bytes, and the first cut of this file WAS one: it typechecked against itself
// and failed at every call into those modules, which is the cheap version of the
// failure a structurally-compatible copy would have produced later and silently.

/** One agent row in the GET /api/v2/agents body. */
export type QaAgent = import( "../../shared/agent-select.js" ).AgentEntry;

/** The GET /api/v2/agents body. `auto_route` carries the sentinel option's value. */
export type QaAgentsPayload = import( "../../shared/agent-select.js" ).AgentsPayload;

/**
 * One /api/v2/ask · /api/v2/submit · /api/v2/resume response body, as
 * `v2_ask.py:AskResponse` serialises it.
 */
export type QaFlowResult = import( "../../shared/arg-interview.js" ).FlowResult;

/** The GET/POST /api/mode/current body (`mode` + its human name). */
export interface QaModeResult {
  mode?         : string | null;
  display_name? : string | null;
  message?      : string | null;
  [k: string]   : unknown;
}

// ---------------------------------------------------------------------------
// Store-facing types
// ---------------------------------------------------------------------------

/** The status line under the agent select: its words and the colour legacy paints. */
export interface QaModeStatus {
  text  : string;
  color : string;
}

/**
 * The three stamps the metrics strip renders (parity Q7). `null` is legacy's `--`.
 *
 * 🔴 THE THREE ARE MEASURED FROM TWO DIFFERENT CLOCKS, and reading them as one is
 * the easy mistake — the first cut of this file made it. Legacy
 * (updateMetricsTTT / updateMetricsTTFA / updateMetricsRTT):
 *
 *   TTT  — submit → the completion text arrived
 *   TTFA — THE TTS REQUEST START → the first audio chunk played. NOT from submit:
 *          its own comment says "audio generation only", and that is the point of
 *          the metric — it isolates the speech pipeline from the thinking that
 *          preceded it. Measured from submit it would silently fold TTT into TTFA
 *          and the two numbers would stop meaning different things.
 *   RTT  — submit → the FIRST AUDIO, the full round trip (legacy: "≈ TTT + TTFA").
 *          Not submit → audio ENDED, which would grow with the length of the
 *          utterance and measure the speaking, not the latency.
 *
 * ⚠️ B-1 OWNS THE STRIP AND THE TTT STAMP ONLY. `noteTtsRequested` and
 * `noteFirstAudio` are the seams B-1b wires from wireTtsPlayback and AudioStore
 * (§6a ruling 12); until that row lands they are never called and the two audio
 * metrics read `--`, which is exactly what legacy shows before its own audio path
 * reports.
 */
export interface QaMetrics {
  ttt  : number | null;
  ttfa : number | null;
  rtt  : number | null;
}

/** What is currently being asked of the operator, if anything (the inline interview). */
export interface QaInterview {
  result : QaFlowResult;
}

/** The slice of ApiClient this store drives. */
export interface QaApiClient {
  get<T>( path: string ): Promise<T>;
  post<T>( path: string, body: unknown ): Promise<T>;
}

export interface QaStore {
  /** The cached GET /api/v2/agents body, or null until it lands (or if it failed). */
  agentsPayload(): QaAgentsPayload | null;
  /** The status line under the select. */
  modeStatus(): QaModeStatus;
  /** The sticky voice-mode badge's label, or null when there is no sticky mode. */
  voiceModeLabel(): string | null;
  /** True while a submit is in flight — the button is disabled and the spinner shows. */
  submitting(): boolean;
  /** What the response pane shows. */
  responseText(): string;
  /** The outstanding interview question, or null when none is. */
  interview(): QaInterview | null;
  /** The three metric stamps. */
  metrics(): QaMetrics;

  /** Fetch the agent list and paint the status line. Never throws. */
  loadAgents(): Promise<void>;
  /** Fetch the sticky voice mode and paint the badge. Never throws. */
  loadVoiceMode(): Promise<void>;
  /** Clear the sticky voice mode (the badge's click). Never throws. */
  clearVoiceMode(): Promise<void>;
  /** Re-paint the status line for a new one-shot selection. */
  noteAgentSelected( value: string | null, label: string | null ): void;
  /**
   * Submit one question. `chosen` is the select's value, `label` its option text.
   * Returns false when the submit was refused (empty text, debounce, already in
   * flight) and true when one was attempted.
   */
  submit( text: string, chosen: string | null ): Promise<boolean>;
  /** Answer the outstanding interview question. A blank answer is ignored. */
  answerInterview( answer: string ): Promise<void>;
  /** B-1b seam — the speech request for this question's answer went out. */
  noteTtsRequested(): void;
  /**
   * B-1b seam — the first audio chunk played. Stamps TTFA (from the request) and
   * RTT (from the submit); each is stamped only if its own clock started.
   */
  noteFirstAudio(): void;
  /** Release the bus subscription. */
  dispose(): void;
}

export interface QaStoreOptions {
  bus       : EventBus;
  api       : QaApiClient;
  /** The queue socket's session id — the `websocket_id` every v2 door is handed. */
  sessionId : () => string;
  /** Test injection for the clock. Defaults to `Date.now`. */
  nowFn?    : () => number;
  /** Test injection for the debounce window. Defaults to legacy's 2000 ms. */
  debounceMs?: number;
}

// Legacy notifications.js:3111 — "2 second cooldown between submissions".
const DEFAULT_DEBOUNCE_MS = 2000;

// Legacy's three status-line colours (notifications.js:26160, :26167, :26124).
const STATUS_GREY = "#6c757d";
const STATUS_BLUE = "#0d6efd";
const STATUS_RED  = "#dc3545";

const AUTO_ROUTE_STATUS: QaModeStatus = { text: "Auto-routing enabled", color: STATUS_GREY };

// Legacy's empty state, notifications.html:157 (`<div id="response-text">`).
export const QA_EMPTY_RESPONSE = "No response yet...";

class QaStoreImpl implements QaStore {
  private readonly bus        : EventBus;
  private readonly api        : QaApiClient;
  private readonly sessionId  : () => string;
  private readonly nowFn      : () => number;
  private readonly debounceMs : number;
  private readonly busOff     : () => void;

  private agents         : QaAgentsPayload | null = null;
  private status         : QaModeStatus = AUTO_ROUTE_STATUS;
  private voiceMode      : string | null = null;
  private inFlight       = false;
  private response       : string = QA_EMPTY_RESPONSE;
  private question       : QaInterview | null = null;
  private lastSubmitAt   : number | null = null;
  // The metric clock: every stamp is measured from the submit that started it.
  private submitAt       : number | null = null;
  // The SECOND clock: when the speech request went out. TTFA is measured from here,
  // never from submitAt — see the QaMetrics docstring.
  private ttsRequestedAt : number | null = null;
  private metricState    : QaMetrics = { ttt: null, ttfa: null, rtt: null };

  constructor( opts: QaStoreOptions ) {
    this.bus        = opts.bus;
    this.api        = opts.api;
    this.sessionId  = opts.sessionId;
    /* c8 ignore next */ // production-default fallback: Date.now() is the runtime clock; tests inject nowFn.
    this.nowFn      = opts.nowFn ?? ( () => Date.now() );
    this.debounceMs = opts.debounceMs ?? DEFAULT_DEBOUNCE_MS;
    // The response pane's OTHER writer. Legacy routes tts_job_request into
    // handleJobCompletion, which writes "Job completed: …" over whatever the submit
    // left there and takes the TTT stamp (notifications.js:4035-4041).
    this.busOff = this.bus.on<TtsJobRequestPayload>(
      "tts_job_request",
      ( e ) => this.onJobCompletion( e.payload ),
    );
  }

  agentsPayload(): QaAgentsPayload | null { return this.agents; }
  modeStatus(): QaModeStatus              { return this.status; }
  voiceModeLabel(): string | null         { return this.voiceMode; }
  submitting(): boolean                   { return this.inFlight; }
  responseText(): string                  { return this.response; }
  interview(): QaInterview | null         { return this.question; }
  metrics(): QaMetrics                    { return this.metricState; }

  /**
   * Fetch the agent list.
   *
   * Ensures:
   *   - on success the payload is cached and the status line reads the one-shot
   *     sentence for the sentinel (the select renders Auto-Route selected)
   *   - on ANY failure the payload stays null and the status line SAYS SO in red.
   *     Legacy's comment is the reason: "A shortened list looks exactly like a
   *     working one", so this fails visibly rather than falling back to a list
   *   - never throws — a dead agent list must not take the pane down with it
   */
  async loadAgents(): Promise<void> {
    try {
      this.agents = await this.api.get<QaAgentsPayload>( AGENTS_ENDPOINT );
      this.setStatus( AUTO_ROUTE_STATUS );
    } catch ( e ) {
      this.agents = null;
      this.setStatus( { text: `Agent list unavailable — ${errorText( e )}`, color: STATUS_RED } );
    }
  }

  /**
   * Read the sticky voice mode and paint the badge.
   *
   * Ensures:
   *   - a mode of `"system"`, null or absent leaves the badge hidden, matching
   *     legacy's updateModeUI test (`mode && mode !== 'system'`)
   *   - the badge's label is the server's display_name, falling back to the mode key
   *   - the SELECT IS NOT TOUCHED (legacy's ruling-2 comment) and the status line is
   *     left to the one-shot selection, which is the thing the operator is reading
   *   - never throws
   */
  async loadVoiceMode(): Promise<void> {
    try {
      this.applyVoiceMode( await this.api.get<QaModeResult>( "/api/mode/current" ) );
    } catch {
      // Legacy logs and returns null; there is no badge to paint either way.
      this.setVoiceMode( null );
    }
  }

  /**
   * Clear the sticky voice mode — the badge's own click (legacy `setAgentMode(null)`).
   *
   * Ensures:
   *   - POSTs `{ mode: null }` and repaints the badge from the SERVER's answer, never
   *     from the optimistic assumption that it cleared
   *   - a refusal leaves the badge as it was; never throws
   */
  async clearVoiceMode(): Promise<void> {
    try {
      this.applyVoiceMode( await this.api.post<QaModeResult>( "/api/mode/current", { mode: null } ) );
    } catch {
      // Legacy returns false and leaves the badge alone.
    }
  }

  /**
   * Repaint the status line for the CURRENT one-shot selection.
   *
   * Ensures:
   *   - the sentinel (or a missing payload) reads "Auto-routing enabled"
   *   - any other value names where the NEXT question goes, in one-shot language, so
   *     the line cannot be read as a mode that will persist
   */
  noteAgentSelected( value: string | null, label: string | null ): void {
    if ( isAutoRoute( value, this.agents ) ) {
      this.setStatus( AUTO_ROUTE_STATUS );
      return;
    }
    this.setStatus( { text: `Next question goes to ${label ?? value ?? ""}`, color: STATUS_BLUE } );
  }

  /**
   * Submit one question through the door the select picked.
   *
   * Requires:
   *   - text is what the operator typed; chosen is the select's current value
   *
   * Ensures:
   *   - an empty or whitespace-only question is refused without a request (false)
   *   - a second submit inside the debounce window is refused (false), as is one
   *     while a submit is already in flight
   *   - Auto-Route POSTs /api/v2/ask with { question, websocket_id }; a named agent
   *     POSTs /api/v2/submit with { command, args, question, websocket_id }, the args
   *     derived by the shared module rather than guessed here
   *   - the response pane reads "Submitting Q&A..." for the duration, the metric
   *     clock restarts, and the result goes through the same handler the interview's
   *     resume turn re-enters
   *   - a transport failure renders `Error: …` and leaves no interview box up
   *   - `submitting()` is false again whatever happened
   */
  async submit( text: string, chosen: string | null ): Promise<boolean> {
    const question = text.trim();
    if ( question === "" ) return false;
    if ( this.inFlight ) return false;

    const now = this.nowFn();
    if ( this.lastSubmitAt !== null && ( now - this.lastSubmitAt ) < this.debounceMs ) return false;
    this.lastSubmitAt = now;

    this.inFlight = true;
    this.response = "Submitting Q&A...";
    // The metric clock restarts on every submit, and the three stamps clear with it —
    // legacy resetMetricsDisplay at the same point (notifications.js:3138).
    this.submitAt       = now;
    this.ttsRequestedAt = null;
    this.metricState    = { ttt: null, ttfa: null, rtt: null };
    this.emitChanged();

    const autoRoute = isAutoRoute( chosen, this.agents );
    const wsId      = this.sessionId();
    const url       = autoRoute ? "/api/v2/ask" : "/api/v2/submit";
    const body      = autoRoute
      ? { question, websocket_id: wsId }
      : {
          command      : chosen,
          args         : argsForCommand( chosen, question, this.agents ),
          question,
          websocket_id : wsId,
        };

    try {
      this.applyResult( await this.api.post<QaFlowResult>( url, body ) );
    } catch ( e ) {
      this.question = null;
      this.response = `Error: ${errorText( e )}`;
    } finally {
      this.inFlight = false;
      this.emitChanged();
    }
    return true;
  }

  /**
   * Answer the outstanding interview question — POST /api/v2/resume.
   *
   * Ensures:
   *   - a blank answer is ignored rather than posted; resume 422s on an empty answer
   *     and the operator would get a validation dump instead of the question they
   *     still have to answer
   *   - an answer with no question outstanding is ignored
   *   - the result RE-ENTERS the same handler, so a second missing argument renders
   *     as the next question and the loop closes when the flow terminates
   *   - a transport failure leaves the box UP with the error beside it: the pending
   *     entry is still parked server-side, so the answer is still wanted
   */
  async answerInterview( answer: string ): Promise<void> {
    const text    = answer.trim();
    const pending = this.question;
    if ( text === "" || pending === null ) return;

    try {
      const body = resumeBody( pending.result, text, this.sessionId() );
      this.applyResult( await this.api.post<QaFlowResult>( "/api/v2/resume", body ) );
    } catch ( e ) {
      // The box STAYS — `this.question` is untouched here on purpose.
      this.response = `Error: ${errorText( e )}`;
    }
    this.emitChanged();
  }

  noteTtsRequested(): void {
    this.ttsRequestedAt = this.nowFn();
  }

  noteFirstAudio(): void {
    // Legacy guards each stamp on ITS OWN clock having started, so a first-audio
    // with no request behind it (a replay, another client's speech) still stamps RTT
    // and leaves TTFA at `--`, rather than both or neither.
    const at = this.nowFn();
    let next = this.metricState;
    if ( this.ttsRequestedAt !== null ) next = { ...next, ttfa: at - this.ttsRequestedAt };
    if ( this.submitAt !== null )       next = { ...next, rtt : at - this.submitAt };
    if ( next === this.metricState ) return;
    this.metricState = next;
    this.emitChanged();
  }

  dispose(): void {
    this.busOff();
  }

  // ── internals ─────────────────────────────────────────────────────────────

  /**
   * The job-completion writer (legacy handleJobCompletion).
   *
   * Ensures:
   *   - the response pane reads "Job completed: <text>", or legacy's
   *     "No text provided" when the frame carries none
   *   - TTT is stamped from the submit that asked for it; a frame arriving with no
   *     submit behind it (another client's job, a cold reload) writes the pane and
   *     stamps nothing
   */
  private onJobCompletion( payload: TtsJobRequestPayload ): void {
    const text = typeof payload.text === "string" && payload.text !== ""
      ? payload.text
      : "No text provided";
    this.response = `Job completed: ${text}`;
    if ( this.submitAt !== null ) {
      this.metricState = { ...this.metricState, ttt: this.nowFn() - this.submitAt };
    }
    this.emitChanged();
  }

  /**
   * Render one flow result: an inline question when it is answerable, the result
   * otherwise (legacy handleQAResult).
   *
   * Ensures:
   *   - an ANSWERABLE needs_input (one carrying a pending_id) becomes the outstanding
   *     question, and the pane shows the flow's own prose
   *   - every other outcome CLEARS any outstanding question first, so a completed
   *     interview does not leave its last question sitting under the answer
   *   - a needs_input WITHOUT a pending_id — the submit door's non-parking refusal,
   *     and an expired park — renders as a result, never as a box whose submit
   *     cannot succeed
   */
  private applyResult( result: QaFlowResult ): void {
    if ( !isAnswerable( result ) ) {
      this.question = null;
      this.response = JSON.stringify( result, null, 2 );
      return;
    }
    // No `?? ""` here, and that is the point: `isAnswerable` is a TYPE PREDICATE that
    // already required a truthy `answer`, so a fallback would be a branch no test
    // could ever take — an untestable line, which under a 100% gate becomes a pragma
    // nobody can justify. Let the narrowing do the work the check already did.
    this.question = { result };
    this.response = result.answer;
  }

  private applyVoiceMode( data: QaModeResult ): void {
    const mode = typeof data.mode === "string" ? data.mode : null;
    if ( mode === null || mode === "system" ) {
      this.setVoiceMode( null );
      return;
    }
    this.setVoiceMode( typeof data.display_name === "string" ? data.display_name : mode );
  }

  private setVoiceMode( label: string | null ): void {
    if ( label === this.voiceMode ) return;
    this.voiceMode = label;
    this.emitChanged();
  }

  private setStatus( status: QaModeStatus ): void {
    this.status = status;
    this.emitChanged();
  }

  private emitChanged(): void {
    this.bus.emit<StoreQaChangedPayload>( {
      type    : "store_qa_changed",
      payload : {},
      source  : "QaStore",
      ts      : this.nowFn(),
    } );
  }
}

/** The message a caller should show for a thrown value of unknown shape. */
function errorText( e: unknown ): string {
  return e instanceof Error ? e.message : String( e );
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createQaStore( opts: QaStoreOptions ): QaStore {
  return new QaStoreImpl( opts );
}
