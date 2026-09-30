/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Parity B-1 — QaPaneRenderer, the Q&A Interface pane.
//
// The DOM-touching half of the row; QaStore owns the model. Mounts into the
// `#qa-pane` slot B-0 pre-allocated and owns its subtree, as every other mux pane
// renderer does.
//
// THE SECTION CONTRACT (plan §2 B-1, rows B1–B4, B7, B10):
//   B1  open by default
//   B2  header-click toggle + ▼/▶ chevron — the shared wireSectionCollapse
//   B3  NOT persisted (the collapse is session-only; no persist key is passed)
//   B4  toolbar ❓ — allocated by B-0 in templates/sectionToolbar.ts
//   B7  static header (no live count)
//   B10 the response pane's empty state, "No response yet..."
//
// THE Q ROWS:
//   Q1  agent select from GET /api/v2/agents, Auto-Route sentinel, one-shot,
//       updates the status line
//   Q2  sticky voice-mode badge; a click clears the mode and does NOT touch the select
//   Q3  submit on the button or Enter — empty refused, 2 s debounce, button disabled
//       + spinner, Auto-Route -> /api/v2/ask, a named agent -> /api/v2/submit
//   Q4  the inline argument interview, with the raw-JSON fallback
//   Q5  🎤 voice input, 30 s max, Esc cancels — the shared recordingManager already
//       enforces both (recordingManager.ts MAX_DURATION_MS, its Escape listener)
//   Q6  the page-wide #tts-mode select, written into AudioStore (§6a ruling 3)
//   Q7  the #qa-metrics strip, rendered from the stamps B-1b captures
//
// THE FIREFOX UA HACK IS NOT PORTED (§6a ruling 3): legacy forces reliable mode by
// sniffing the user agent (notifications.js:630-660). If Firefox instant playback is
// still broken that gets its own row; it does not get a user-agent branch here.

import type { EventBus } from "../shared/EventBus";
import type { StoreQaChangedPayload } from "../shared/types";
import type { QaStore, QaMetrics } from "../stores/QaStore";
import type { TtsMode } from "../stores/AudioStore";
import type { ActionRequiredMicHandler } from "./actionRequiredMic";
import { renderQaChrome, type QaChromeElements } from "./templates/qaChrome";
import {
  renderSectionHeader,
  wireSectionCollapse,
  type SectionHeaderHandle,
} from "./templates/sectionHeader";
import { renderAgentSelect } from "../../shared/agent-select.js";
import { renderArgQuestion, clearArgQuestion } from "../../shared/arg-interview.js";

/** The one thing this pane writes on AudioStore (§6a ruling 3). */
export interface QaTtsModeWriter {
  setTtsMode( mode: TtsMode ): void;
}

export interface QaPaneRendererStores {
  qa    : QaStore;
  audio : QaTtsModeWriter;
}

export interface QaPaneRenderer {
  mount( root: HTMLElement ): void;
  unmount(): void;
}

export interface QaPaneRendererOptions {
  eventBus : EventBus;
  stores   : QaPaneRendererStores;
  /**
   * The shared card-mic handler (`createActionRequiredMic`). Omitted in tests that
   * do not exercise the mic; the button then does nothing, which is the same state
   * legacy is in when the recorder cannot start.
   */
  micHandler?: ActionRequiredMicHandler;
}

// Legacy's mic context ids are the field they fill (notifications.js:4007-4009 passes
// 'qa-input'); the shared handler keys single-active recording on this string.
const QA_MIC_CONTEXT = "qa-input";

/** Legacy's metric formatting: milliseconds, or `--` before the stamp lands. */
function formatMetric( ms: number | null ): string {
  return ms === null ? "--" : `${ms}ms`;
}

/** Has ANY stamp landed? The strip is hidden until one has (legacy's `display:none`). */
function anyMetric( m: QaMetrics ): boolean {
  return m.ttt !== null || m.ttfa !== null || m.rtt !== null;
}

class QaPaneRendererImpl implements QaPaneRenderer {
  private readonly bus        : EventBus;
  private readonly stores     : QaPaneRendererStores;
  private readonly micHandler : ActionRequiredMicHandler | null;
  private readonly unsubscribers: Array<() => void> = [];

  private root    : HTMLElement | null = null;
  private els     : QaChromeElements | null = null;
  private header  : SectionHeaderHandle | null = null;
  private collapseOff: ( () => void ) | null = null;
  private mounted = false;
  // The agent payload the select was last rendered from. The select is rebuilt only
  // when a NEW payload lands, never on every repaint — a repaint mid-selection would
  // throw away the operator's choice.
  private renderedAgents: unknown = null;
  // Same rule for the interview box: rebuilt per QUESTION, never per paint, so a
  // repaint while the operator is typing cannot discard what they have typed.
  private renderedQuestion: unknown = null;

  constructor( opts: QaPaneRendererOptions ) {
    this.bus        = opts.eventBus;
    this.stores     = opts.stores;
    this.micHandler = opts.micHandler ?? null;
  }

  mount( root: HTMLElement ): void {
    if ( this.mounted ) throw new Error( "QaPaneRenderer already mounted" );
    this.mounted = true;
    this.root    = root;

    // B7 — a static header: no count, no actions. The chevron is the only control.
    const header = renderSectionHeader( {
      icon   : "❓",
      title  : "Q&A Interface",
      testid : "multiplexer-qa-header",
    } );
    this.header = header;

    const els = renderQaChrome();
    this.els  = els;

    root.replaceChildren( header.header, els.body );
    // B1 + B2 + B3 — open, header-click toggle, session-only. No persist key is
    // passed, which is what B3 asks for: legacy's Q&A disclosure is not persisted.
    this.collapseOff = wireSectionCollapse( root, header );

    this.wire( els );
    this.paint();

    this.unsubscribers.push(
      this.bus.on<StoreQaChangedPayload>( "store_qa_changed", () => this.paint() ),
    );

    // Q1 + Q2 — both reads start at mount and paint through the store's event.
    void this.stores.qa.loadAgents();
    void this.stores.qa.loadVoiceMode();
  }

  unmount(): void {
    for ( const off of this.unsubscribers ) off();
    this.unsubscribers.length = 0;
    if ( this.collapseOff !== null ) {
      this.collapseOff();
      this.collapseOff = null;
    }
    if ( this.root !== null ) {
      this.root.replaceChildren();
      this.root = null;
    }
    this.els    = null;
    this.header = null;
    this.renderedAgents = null;
    this.mounted = false;
  }

  // ── wiring ────────────────────────────────────────────────────────────────

  private wire( els: QaChromeElements ): void {
    // Q1 — a new one-shot selection repaints the status line. Nothing is persisted
    // and nothing is posted: the choice rides the NEXT submit.
    els.agentSelect.addEventListener( "change", () => {
      const option = els.agentSelect.selectedOptions[ 0 ];
      this.stores.qa.noteAgentSelected(
        els.agentSelect.value,
        option === undefined ? null : option.textContent,
      );
    } );

    // Q2 — the badge clears the STICKY VOICE mode. It must not touch the select,
    // which routes the next typed question and is a different thing entirely.
    els.modeBadge.addEventListener( "click", () => { void this.stores.qa.clearVoiceMode(); } );

    // Q3 — the button and Enter are one door.
    els.submitBtn.addEventListener( "click", () => { void this.doSubmit( els ); } );
    els.input.addEventListener( "keydown", ( e ) => {
      if ( ( e as KeyboardEvent ).key !== "Enter" ) return;
      e.preventDefault();
      void this.doSubmit( els );
    } );

    // Q5 — the shared card mic, on this pane's own context. The 30 s cap and the Esc
    // cancel live in recordingManager, so they are inherited rather than re-written.
    els.micBtn.addEventListener( "click", () => {
      if ( this.micHandler === null ) return;
      this.micHandler( QA_MIC_CONTEXT, els.micBtn, els.input );
    } );

    // Q6 — the page-wide TTS mode. Written straight through to AudioStore, which is
    // what every playback path reads (§6a ruling 3).
    els.ttsModeSelect.addEventListener( "change", () => {
      this.stores.audio.setTtsMode( els.ttsModeSelect.value as TtsMode );
    } );
  }

  /**
   * One submit turn.
   *
   * Ensures:
   *   - the input is CLEARED only when a submission was actually attempted, so a
   *     refusal (empty, debounced, already in flight) leaves the operator's words
   *     where they typed them
   */
  private async doSubmit( els: QaChromeElements ): Promise<void> {
    const attempted = await this.stores.qa.submit( els.input.value, els.agentSelect.value );
    if ( attempted ) els.input.value = "";
  }

  // ── paint ─────────────────────────────────────────────────────────────────

  private paint(): void {
    const els = this.els;
    /* c8 ignore next */ // defensive: every paint path runs between mount and unmount, where els is non-null.
    if ( els === null ) return;
    const qa = this.stores.qa;

    // Q1 — rebuild the select only when a NEW payload arrived. The module renders the
    // sentinel first and leaves it selected.
    const agents = qa.agentsPayload();
    if ( agents !== null && agents !== this.renderedAgents ) {
      this.renderedAgents = agents;
      renderAgentSelect( els.agentSelect, agents );
    }

    const status = qa.modeStatus();
    els.modeStatus.textContent = status.text;
    els.modeStatus.style.color = status.color;

    // Q2 — the badge shows the sticky voice mode, and only when there is one.
    const voiceLabel = qa.voiceModeLabel();
    els.modeBadge.hidden = voiceLabel === null;
    els.modeBadge.textContent = voiceLabel ?? "";

    // Q3 — the in-flight pair: the button is disabled and the spinner shows.
    const busy = qa.submitting();
    els.submitBtn.disabled = busy;
    els.spinner.hidden     = !busy;

    els.response.textContent = qa.responseText();

    this.paintInterview( els );
    this.paintMetrics( els );
  }

  /**
   * Q4 — the inline argument interview.
   *
   * Ensures:
   *   - an outstanding question renders exactly one box, re-wired to THIS result, and
   *     the box takes focus so the operator can answer without reaching for the mouse
   *   - no outstanding question clears the container, whose `hidden` state is the
   *     single signal of whether an interview is in progress
   *   - the box is rebuilt per question rather than per paint: a repaint while the
   *     operator is typing must not discard what they have typed
   */
  private paintInterview( els: QaChromeElements ): void {
    const question = this.stores.qa.interview();
    if ( question === null ) {
      clearArgQuestion( els.interview );
      this.renderedQuestion = null;
      return;
    }
    if ( question === this.renderedQuestion ) return;
    this.renderedQuestion = question;

    const wired = renderArgQuestion( els.interview, question.result );
    /* c8 ignore next */ // unreachable: the store only exposes a question isAnswerable said yes to, which is the same predicate renderArgQuestion refuses on.
    if ( wired === null ) return;
    wired.button.addEventListener( "click", () => { void this.stores.qa.answerInterview( wired.input.value ); } );
    wired.input.addEventListener( "keydown", ( e ) => {
      if ( ( e as KeyboardEvent ).key !== "Enter" ) return;
      e.preventDefault();
      void this.stores.qa.answerInterview( wired.input.value );
    } );
    wired.input.focus();
  }

  /** Q7 — the strip stays hidden until a stamp lands, then shows all three. */
  private paintMetrics( els: QaChromeElements ): void {
    const m = this.stores.qa.metrics();
    els.metrics.hidden      = !anyMetric( m );
    els.metricTtt.textContent  = formatMetric( m.ttt );
    els.metricTtfa.textContent = formatMetric( m.ttfa );
    els.metricRtt.textContent  = formatMetric( m.rtt );
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createQaPaneRenderer( opts: QaPaneRendererOptions ): QaPaneRenderer {
  return new QaPaneRendererImpl( opts );
}
