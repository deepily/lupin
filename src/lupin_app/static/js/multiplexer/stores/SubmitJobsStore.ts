/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Parity B-2 (row key B-2) — SubmitJobsStore, the Submit Agentic Jobs model.
//
// Four cards, and they are NOT four copies of one shape. The differences below are
// legacy's, each one measured at its own call site rather than inferred from the
// neighbour that looks like it:
//
//                 door                          success line        on success
//   CC            /api/v2/submit                no position         prompt KEPT
//   Research      /api/v2/submit                no position         topic CLEARED
//   Test Suite    /api/test-suite/submit        HAS a position      input kept
//   TFE           /api/test-fix-expediter/…     two-outcome         cleared on resume
//
// 🔴 THE TEST SUITE CARD IS THE ONE THAT DOES NOT POST TO /api/v2/submit, and it is
// also the only one whose success line prints a queue position. Both are deliberate
// in the lead: the v2 response carries no queue_position and is not being widened
// for one ("a place in the queue changes as the queue moves, so a number frozen at
// the instant of submission was stale the moment it was printed"), while
// /api/test-suite/submit does return one.
//
// LEGACY SOURCES, cited by symbol:
//   submitClaudeCodeToQueue     — the CC door, and refreshAllQueues() after it
//   submitResearchJob           — the command-picks-by-checkbox rule, topic cleared
//   submitTestSuiteJob          — validation, the combined pytest args, the position
//   submitTFEResume             — the alert(), ambiguous vs resumed
//   _renderTFEResumeCandidates  — the candidate rows
//   _getSchedulingParams        — scheduled_at + monopolize, both TOP-LEVEL
//   FILE_DRIVEN_TEST_TYPES      — the two types that require a file path
//
// ⚠️ `websocket_id` IS THE QUEUE SESSION ID, AND LEGACY'S CC CARD GETS THIS WRONG.
// It sends `this.sessionId`, a field never assigned, so the key drops out of the
// JSON and the server falls back to `api-<uid>`. §6a ruling 13, ratified by Rick
// 2026-09-19: that is a defect in the lead and is NOT back-ported. Every card here
// sends the queue session id.

import type { EventBus } from "../shared/EventBus";
import type { StoreSubmitJobsChangedPayload } from "../shared/types";

// ---------------------------------------------------------------------------
// Wire shapes
// ---------------------------------------------------------------------------

/** The /api/v2/submit and /api/test-suite/submit success bodies (the fields read). */
export interface SubmitResult {
  job_id?         : string;
  queue_position? : number;
  detail?         : string;
  [k: string]     : unknown;
}

/** One candidate in an `ambiguous` TFE resume response. */
export interface TfeCandidate {
  job_id      : string;
  confidence? : number | null;
  stalled_at? : string | null;
  summary?    : string | null;
  reason?     : string | null;
  [k: string] : unknown;
}

/** The /api/test-fix-expediter/resume-from body. */
export interface TfeResumeResult {
  status?            : string;
  candidates?        : ReadonlyArray<TfeCandidate>;
  source_type?       : string | null;
  phase_name?        : string | null;
  resume_from_phase? : number | string | null;
  resumed_job_id?    : string | null;
  [k: string]        : unknown;
}

// ---------------------------------------------------------------------------
// Card inputs — what the renderer reads off the DOM and hands over
// ---------------------------------------------------------------------------

/**
 * The scheduling pair every card carries (legacy `_getSchedulingParams`).
 *
 * ⚠️ BOTH STAY TOP-LEVEL IN THE BODY, never inside `args`. They are directives to
 * the QUEUE — when to run the work and whether it runs alone — and `args` is checked
 * against the command's own argument contract, which names neither.
 */
export interface SchedulingInput {
  /** The checkbox. `scheduled_at` is emitted only when this AND `time` are set. */
  scheduled    : boolean;
  /** The datetime-local value, as the input gives it. */
  time         : string;
  /** The 🔒 exclusive-mode box. Absent on the test-suite card (always-on server-side). */
  monopolize?  : boolean;
}

export interface CcSubmitInput {
  prompt     : string;
  project    : string;
  taskType   : string;
  dryRun     : boolean;
  scheduling : SchedulingInput;
}

export interface ResearchSubmitInput {
  topic            : string;
  budget           : string;
  withPodcast      : boolean;
  withPresentation : boolean;
  dryRun           : boolean;
  scheduling       : SchedulingInput;
}

export interface TestSuiteSubmitInput {
  testTypes  : string;
  filePath   : string;
  failFast   : boolean;
  pytestArgs : string;
  dryRun     : boolean;
  autoFix    : boolean;
  scheduling : SchedulingInput;
}

// ---------------------------------------------------------------------------
// Card state — what the renderer paints
// ---------------------------------------------------------------------------

/** One card's status line: its words and legacy's colour for them. */
export interface CardStatus {
  text  : string;
  color : string;
}

export type CardKey = "cc" | "research" | "testSuite" | "tfe";

export interface SubmitJobsApiClient {
  post<T>( path: string, body: unknown, opts?: { headers?: Readonly<Record<string, string>> } ): Promise<T>;
}

export interface SubmitJobsStore {
  /** A card's status line. Empty text until something is submitted (B10). */
  status( card: CardKey ): CardStatus;
  /** Is this card's submit in flight? The button is disabled and its spinner shows. */
  busy( card: CardKey ): boolean;
  /** The outstanding TFE disambiguation list — empty when there is none. */
  tfeCandidates(): ReadonlyArray<TfeCandidate>;
  /** The auto-fix box's value, resolved from the INI at config load (J20). */
  autoFixDefault(): boolean;
  /** Apply the INI's `test fix expediter auto fix enabled` (the boot config seam). */
  setAutoFixDefault( enabled: boolean ): void;

  /** CC card. Resolves true when a job was submitted. */
  submitCc( input: CcSubmitInput ): Promise<boolean>;
  /** Research card. Resolves true when a job was submitted — the topic then clears. */
  submitResearch( input: ResearchSubmitInput ): Promise<boolean>;
  /** Test Suite card. Resolves true when a job was submitted. */
  submitTestSuite( input: TestSuiteSubmitInput ): Promise<boolean>;
  /** TFE card. Resolves true when a job was RESUMED — ambiguous is not a success. */
  submitTfeResume( resumeFrom: string ): Promise<boolean>;
}

export interface SubmitJobsStoreOptions {
  bus       : EventBus;
  api       : SubmitJobsApiClient;
  /** The queue socket's session id — `websocket_id` and the `X-Session-ID` header. */
  sessionId : () => string;
  /**
   * Called after a SUCCESSFUL CC submit and after nothing else (B8). Legacy calls
   * refreshAllQueues() there and does not call it from the other three cards.
   */
  onCcSubmitted?: () => void;
  nowFn?    : () => number;
}

// Legacy's status colours, by symbol rather than by eye:
// '#dc3545' the refusals and errors, '#28a745' the successes, '#666' in flight.
const COLOR_ERROR   = "#dc3545";
const COLOR_SUCCESS = "#28a745";
const COLOR_BUSY    = "#666";

const EMPTY_STATUS: CardStatus = { text: "", color: COLOR_BUSY };

/**
 * The two test types that are driven by a FILE rather than by discovery, so the
 * card refuses without a path and the path is prepended to the pytest args.
 * Legacy `FILE_DRIVEN_TEST_TYPES`.
 */
export const FILE_DRIVEN_TEST_TYPES: ReadonlySet<string> = new Set( [ "smoke_direct", "pytest_direct" ] );

/** Legacy's research budget fallback: `parseFloat( value ) || 3.00`. */
export const RESEARCH_BUDGET_DEFAULT = 3.0;

/**
 * The three research commands, picked by the two checkboxes.
 *
 * ⚠️ PRESENTATION WINS WHEN BOTH ARE TICKED, and the ARGS agree with that choice.
 * Legacy's command chain tests presentation first; its args chain tests podcast
 * first, so with both ticked it sends the presentation command carrying the
 * PODCAST's languages argument. That asymmetry is not reproduced — one predicate
 * decides both here — because the renderer makes the boxes mutually exclusive at
 * runtime (J11), so "both ticked" is a state the operator cannot reach, and the one
 * reading it would be a bug rather than a behaviour.
 */
export const RESEARCH_COMMAND_PLAIN        = "agent router go to deep research";
export const RESEARCH_COMMAND_PODCAST      = "agent router go to research to podcast";
export const RESEARCH_COMMAND_PRESENTATION = "agent router go to research to presentation";

class SubmitJobsStoreImpl implements SubmitJobsStore {
  private readonly bus       : EventBus;
  private readonly api       : SubmitJobsApiClient;
  private readonly sessionId : () => string;
  private readonly onCcSubmitted: ( () => void ) | null;
  private readonly nowFn     : () => number;

  private statuses : Record<CardKey, CardStatus> = {
    cc: EMPTY_STATUS, research: EMPTY_STATUS, testSuite: EMPTY_STATUS, tfe: EMPTY_STATUS,
  };
  private inFlight : Record<CardKey, boolean> = {
    cc: false, research: false, testSuite: false, tfe: false,
  };
  private candidates : ReadonlyArray<TfeCandidate> = [];
  private autoFix    = false;

  constructor( opts: SubmitJobsStoreOptions ) {
    this.bus       = opts.bus;
    this.api       = opts.api;
    this.sessionId = opts.sessionId;
    this.onCcSubmitted = opts.onCcSubmitted ?? null;
    /* c8 ignore next */ // production-default fallback: Date.now() is the runtime clock; tests inject nowFn.
    this.nowFn     = opts.nowFn ?? ( () => Date.now() );
  }

  status( card: CardKey ): CardStatus            { return this.statuses[ card ]; }
  busy( card: CardKey ): boolean                 { return this.inFlight[ card ]; }
  tfeCandidates(): ReadonlyArray<TfeCandidate>   { return this.candidates; }
  autoFixDefault(): boolean                      { return this.autoFix; }

  setAutoFixDefault( enabled: boolean ): void {
    if ( enabled === this.autoFix ) return;
    this.autoFix = enabled;
    this.emitChanged();
  }

  /**
   * The Claude Code card.
   *
   * Ensures:
   *   - an empty prompt is refused in red, with NO request and no debounce (J5) —
   *     unlike the Q&A box, this card has no cooldown
   *   - `max_turns` is 200 for INTERACTIVE and 50 otherwise (J3)
   *   - the job's own arguments ride in `args`; `websocket_id`, `scheduled_at` and
   *     `monopolize` stay TOP-LEVEL, because `args` is checked against the command's
   *     argument contract and none of the three is in it
   *   - on success the status names the job id and NO queue position (J7), the prompt
   *     is KEPT, and the queues are refreshed — the only card that refreshes (B8)
   */
  async submitCc( input: CcSubmitInput ): Promise<boolean> {
    const prompt = input.prompt.trim();
    if ( prompt === "" ) {
      this.setStatus( "cc", "⚠️ Please enter a task prompt.", COLOR_ERROR );
      return false;
    }
    return await this.run( "cc", "Submitting to CJ Flow queue...", async () => {
      const result = await this.postJson<SubmitResult>( "/api/v2/submit", {
        command : "agent router go to claude code",
        args    : {
          prompt,
          project   : input.project,
          task_type : input.taskType,
          max_turns : input.taskType === "INTERACTIVE" ? 200 : 50,
          dry_run   : input.dryRun,
        },
        question     : prompt,
        websocket_id : this.sessionId(),
        ...schedulingParams( input.scheduling ),
      } );
      this.setStatus( "cc", `✓ Claude Code job submitted! Job ID: ${result.job_id}`, COLOR_SUCCESS );
      // B8 — legacy calls refreshAllQueues() HERE and from no other card.
      if ( this.onCcSubmitted !== null ) this.onCcSubmitted();
      return true;
    } );
  }

  /**
   * The Research card.
   *
   * Ensures:
   *   - an empty topic is refused in red with no request
   *   - the two checkboxes pick a COMMAND, not a URL: the three research endpoints
   *     they used to choose between answer 410 naming /api/v2/submit
   *   - the budget falls back to 3.00 on anything unparseable (legacy `|| 3.00`),
   *     which also catches a literal 0 — legacy's `||` does, so this does
   *   - the extra argument follows the same predicate that picked the command
   *   - on success the topic input CLEARS, which the CC card does not do
   */
  async submitResearch( input: ResearchSubmitInput ): Promise<boolean> {
    const topic = input.topic.trim();
    if ( topic === "" ) {
      this.setStatus( "research", "⚠️ Please enter a research topic.", COLOR_ERROR );
      return false;
    }
    return await this.run( "research", "Submitting research job...", async () => {
      const budget = parseFloat( input.budget ) || RESEARCH_BUDGET_DEFAULT;
      const args: Record<string, unknown> = { query: topic, budget, dry_run: input.dryRun };

      let command  = RESEARCH_COMMAND_PLAIN;
      let jobType  = "Research";
      if ( input.withPresentation ) {
        command = RESEARCH_COMMAND_PRESENTATION;
        jobType = "Research→Presentation";
        args.target_duration_minutes = 15;
      } else if ( input.withPodcast ) {
        command = RESEARCH_COMMAND_PODCAST;
        jobType = "Research→Podcast";
        args.target_languages = [ "en", "es-MX" ];
      }

      const result = await this.postJson<SubmitResult>( "/api/v2/submit", {
        command, args, question: topic, ...schedulingParams( input.scheduling ),
      } );
      this.setStatus( "research", `✓ ${jobType} job submitted! Job ID: ${result.job_id}`, COLOR_SUCCESS );
      return true;
    } );
  }

  /**
   * The Test Suite card.
   *
   * Ensures:
   *   - a file-driven type with no path is refused with legacy's exact sentence, and
   *     the refusal happens BEFORE the in-flight state, so the button never flickers
   *   - the file path is PREPENDED to the pytest args and `--fail-fast` APPENDED, so
   *     a run carrying both reads `<path> <args> --fail-fast`
   *   - `--fail-fast` rides only when the type is exactly `all`
   *   - empty pytest args are OMITTED from the body rather than sent empty
   *   - it posts /api/test-suite/submit, NOT /api/v2/submit
   *   - `monopolize` is not sent: it is always-on server-side for this door
   *   - the success line DOES print the queue position, unlike the two v2 cards
   */
  async submitTestSuite( input: TestSuiteSubmitInput ): Promise<boolean> {
    const filePath   = input.filePath.trim();
    const pytestArgs = input.pytestArgs.trim();
    const fileDriven = FILE_DRIVEN_TEST_TYPES.has( input.testTypes );

    if ( fileDriven && filePath === "" ) {
      this.setStatus( "testSuite", `✗ Error: ${input.testTypes} requires a test file path`, COLOR_ERROR );
      return false;
    }

    let combined = pytestArgs;
    if ( fileDriven ) combined = combined === "" ? filePath : `${filePath} ${combined}`;
    if ( input.testTypes === "all" && input.failFast ) {
      combined = combined === "" ? "--fail-fast" : `${combined} --fail-fast`;
    }

    return await this.run( "testSuite", "Submitting test suite job...", async () => {
      const body: Record<string, unknown> = {
        test_types          : input.testTypes,
        dry_run             : input.dryRun,
        auto_fix_on_failure : input.autoFix,
      };
      if ( combined !== "" ) body.pytest_args = combined;
      // The schedule half only. `monopolize` is always-on server-side on this door,
      // so the card has no box for it and the body must not carry one.
      const scheduledAt = scheduledAtOf( input.scheduling );
      if ( scheduledAt !== null ) body.scheduled_at = scheduledAt;

      const result = await this.postJson<SubmitResult>( "/api/test-suite/submit", body );
      this.setStatus(
        "testSuite",
        `✓ Test suite job submitted! Job ID: ${result.job_id}, Position: ${result.queue_position}`,
        COLOR_SUCCESS,
      );
      return true;
    } );
  }

  /**
   * The TFE resume card.
   *
   * ⚠️ AN EMPTY INPUT IS THE ONE REFUSAL THAT IS NOT A STATUS LINE. Legacy raises a
   * browser `alert()` here (J26) while every sibling card writes inline. That is
   * legacy's, it is reproduced, and it is why the caller — not this store — owns the
   * alert: a store that called `alert()` could not be unit-tested without a DOM, and
   * the divergence would be invisible in the model.
   *
   * Ensures:
   *   - an empty input asks for NOTHING and returns false, leaving the alert to the
   *     renderer
   *   - `ambiguous` publishes the candidate list and is NOT a success — the input is
   *     kept so the operator can pick or retype
   *   - `resumed` writes legacy's exact sentence and clears the candidate list
   *   - any other status leaves the card as it was rather than claiming an outcome
   */
  async submitTfeResume( resumeFrom: string ): Promise<boolean> {
    const text = resumeFrom.trim();
    if ( text === "" ) return false;

    this.candidates = [];
    return await this.run( "tfe", "Resolving...", async () => {
      const data = await this.postJson<TfeResumeResult>(
        "/api/test-fix-expediter/resume-from", { resume_from: text },
      );

      if ( data.status === "ambiguous" ) {
        const found = data.candidates ?? [];
        this.candidates = found;
        this.setStatus( "tfe", `Found ${found.length} possible matches — pick one.`, COLOR_BUSY );
        return false;
      }
      if ( data.status === "resumed" ) {
        const sourceType = data.source_type ?? "unknown";
        const phase      = data.phase_name ?? `phase ${data.resume_from_phase}`;
        this.setStatus( "tfe", `✓ Resumed via ${sourceType}: ${data.resumed_job_id} from ${phase}`, COLOR_SUCCESS );
        return true;
      }
      return false;
    } );
  }

  // ── internals ─────────────────────────────────────────────────────────────

  /**
   * The shape all four cards share: disable, say what is happening, run, and release
   * whatever happened.
   *
   * Ensures:
   *   - the error line is legacy's `✗ Error: <message>` for the three status-line
   *     cards; the TFE card's own is `✗ <message>`, which is a DIFFERENT string and
   *     is passed in rather than unified
   *   - the in-flight flag is always released, on success and on failure alike
   */
  private async run(
    card    : CardKey,
    busyText: string,
    body    : () => Promise<boolean>,
  ): Promise<boolean> {
    this.inFlight[ card ] = true;
    this.setStatus( card, busyText, COLOR_BUSY );
    try {
      return await body();
    } catch ( e ) {
      const prefix = card === "tfe" ? "✗" : "✗ Error:";
      this.setStatus( card, `${prefix} ${errorText( e )}`, COLOR_ERROR );
      return false;
    } finally {
      this.inFlight[ card ] = false;
      this.emitChanged();
    }
  }

  /**
   * Every card's POST, carrying the session header.
   *
   * `X-Session-ID` rides ALONGSIDE the Authorization header (J14) — legacy sends both
   * on all four doors. The client's per-call header hook cannot displace the auth
   * header, so this cannot become a request sent as somebody else.
   */
  private async postJson<T>( path: string, body: unknown ): Promise<T> {
    return await this.api.post<T>( path, body, { headers: { "X-Session-ID": this.sessionId() } } );
  }

  private setStatus( card: CardKey, text: string, color: string ): void {
    this.statuses = { ...this.statuses, [ card ]: { text, color } };
    this.emitChanged();
  }

  private emitChanged(): void {
    this.bus.emit<StoreSubmitJobsChangedPayload>( {
      type    : "store_submit_jobs_changed",
      payload : {},
      source  : "SubmitJobsStore",
      ts      : this.nowFn(),
    } );
  }
}

/**
 * `scheduled_at`, or null when the pair is incomplete (legacy `_getSchedulingParams`).
 *
 * ⚠️ BOTH HALVES ARE REQUIRED. The checkbox alone, or a time with the box unticked,
 * emits NOTHING — a job that silently acquired a schedule from a half-filled form
 * would run at a time nobody chose.
 */
function scheduledAtOf( s: SchedulingInput ): string | null {
  if ( !s.scheduled || s.time === "" ) return null;
  return new Date( s.time ).toISOString();
}

/** The top-level scheduling directives for a v2 body. */
function schedulingParams( s: SchedulingInput ): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  const scheduledAt = scheduledAtOf( s );
  if ( scheduledAt !== null ) params.scheduled_at = scheduledAt;
  if ( s.monopolize === true ) params.monopolize = true;
  return params;
}

/** The message a caller should show for a thrown value of unknown shape. */
function errorText( e: unknown ): string {
  return e instanceof Error ? e.message : String( e );
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createSubmitJobsStore( opts: SubmitJobsStoreOptions ): SubmitJobsStore {
  return new SubmitJobsStoreImpl( opts );
}
