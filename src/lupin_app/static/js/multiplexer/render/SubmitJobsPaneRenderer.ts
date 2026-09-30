/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Parity B-2 — SubmitJobsPaneRenderer, the Submit Agentic Jobs pane.
//
// The DOM-touching half; SubmitJobsStore owns the four submit paths. Mounts into the
// `#submit-jobs-pane` slot B-0 pre-allocated.
//
// THE SECTION CONTRACT (plan §2 B-2):
//   B1–B3  open, unpersisted, and NO keyboard handler on the section header
//   B4     toolbar 📝 — freed by A-2 #1 moving Jobs to 📋, allocated by B-0
//   B7     static header
//   B8     a successful CC submit refreshes the queues; the other three do not
//   B9     three card accordions collapsed and unpersisted, plus a fourth TFE card
//          with no toggle, always open
//   B10    each `*-submit-status` starts empty
//
// 🔴 THE THREE SUBMIT GESTURES ARE THREE DIFFERENT GESTURES, and that is the parity:
//   CC          click or Ctrl+Enter in the textarea  (J5)
//   Research    click or plain Enter in the input     (J13)
//   Test Suite  click only                            (J24 reads the schedule inline)
//   TFE         click only                            (J26)
// A shared "submit on Enter" helper would quietly give the CC textarea a plain-Enter
// submit, which would make it impossible to type a multi-line prompt.
//
// ⚠️ THE TFE CARD'S EMPTY-INPUT REFUSAL IS A BROWSER `alert()` (J26), not an inline
// status like its three siblings. It lives here rather than in the store so the store
// stays unit-testable without a DOM — and so the divergence is visible at the seam.

import type { EventBus } from "../shared/EventBus";
import type { StoreSubmitJobsChangedPayload } from "../shared/types";
import type { SubmitJobsStore, CardKey, TfeCandidate } from "../stores/SubmitJobsStore";
import { FILE_DRIVEN_TEST_TYPES } from "../stores/SubmitJobsStore";
import type { ScheduleEls } from "./templates/submitJobsChrome";
import type { ActionRequiredMicHandler } from "./actionRequiredMic";
import {
  renderSubmitJobsChrome,
  type SubmitJobsChromeElements,
} from "./templates/submitJobsChrome";
import {
  renderSectionHeader,
  wireSectionCollapse,
  type SectionHeaderHandle,
} from "./templates/sectionHeader";

export interface SubmitJobsPaneRendererStores {
  submitJobs : SubmitJobsStore;
}

export interface SubmitJobsPaneRenderer {
  mount( root: HTMLElement ): void;
  unmount(): void;
}

export interface SubmitJobsPaneRendererOptions {
  eventBus : EventBus;
  stores   : SubmitJobsPaneRendererStores;
  /** The shared card-mic handler. Omitted ⇒ the two 🎤 buttons do nothing. */
  micHandler?: ActionRequiredMicHandler;
  /**
   * The empty-TFE-input refusal (J26). Injected so a test can observe it without a
   * window, and named for what it is rather than hidden behind "notify".
   */
  alertFn? : ( message: string ) => void;
}

/** Legacy's mic contexts, named for the field each one fills. */
const CC_MIC_CONTEXT       = "cc-prompt";
const RESEARCH_MIC_CONTEXT = "research-topic";

/** J26 — legacy's exact sentence. */
const TFE_EMPTY_ALERT = "Enter a job ID, plan path, or description.";

/** Read one card's scheduling pair off the DOM. */
function schedulingOf( s: ScheduleEls ): { scheduled: boolean; time: string; monopolize?: boolean } {
  return s.monopolize === null
    ? { scheduled: s.checkbox.checked, time: s.time.value }
    : { scheduled: s.checkbox.checked, time: s.time.value, monopolize: s.monopolize.checked };
}

class SubmitJobsPaneRendererImpl implements SubmitJobsPaneRenderer {
  private readonly bus        : EventBus;
  private readonly store      : SubmitJobsStore;
  private readonly micHandler : ActionRequiredMicHandler | null;
  private readonly alertFn    : ( message: string ) => void;
  private readonly unsubscribers: Array<() => void> = [];
  private readonly teardown   : Array<() => void> = [];

  private root    : HTMLElement | null = null;
  private els     : SubmitJobsChromeElements | null = null;
  private header  : SectionHeaderHandle | null = null;
  private collapseOff: ( () => void ) | null = null;
  private mounted = false;
  /** The candidate list last painted, so a repaint does not rebuild an identical one. */
  private paintedCandidates: ReadonlyArray<TfeCandidate> | null = null;
  // J20 — the auto-fix default AS LAST APPLIED to the box, so a repaint can tell an
  // arriving config from a redundant re-write. null until the first paint. See paint().
  private appliedAutoFix: boolean | null = null;

  constructor( opts: SubmitJobsPaneRendererOptions ) {
    this.bus        = opts.eventBus;
    this.store      = opts.stores.submitJobs;
    this.micHandler = opts.micHandler ?? null;
    /* c8 ignore next */ // production-default fallback: the browser's own alert; tests inject a spy.
    this.alertFn    = opts.alertFn ?? ( ( m ) => { window.alert( m ); } );
  }

  mount( root: HTMLElement ): void {
    if ( this.mounted ) throw new Error( "SubmitJobsPaneRenderer already mounted" );
    this.mounted = true;
    this.root    = root;

    // B7 — a static header. No count, no actions.
    const header = renderSectionHeader( {
      icon   : "📝",
      title  : "Submit Agentic Jobs",
      testid : "multiplexer-submit-jobs-header",
    } );
    this.header = header;

    const els = renderSubmitJobsChrome();
    this.els  = els;

    root.replaceChildren( header.header, els.body );
    // B1–B3 — open, header-click toggle, session-only. No persist key.
    this.collapseOff = wireSectionCollapse( root, header );

    this.wire( els );
    this.paint();

    this.unsubscribers.push(
      this.bus.on<StoreSubmitJobsChangedPayload>( "store_submit_jobs_changed", () => this.paint() ),
    );
  }

  unmount(): void {
    for ( const off of this.unsubscribers ) off();
    this.unsubscribers.length = 0;
    for ( const off of this.teardown ) off();
    this.teardown.length = 0;
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
    this.paintedCandidates = null;
    // Per-MOUNT, like paintedCandidates above it: unmount throws the DOM away, so the next
    // mount's fresh box is at the markup default and the store's value must be applied to
    // it again (María 🌸's B-2 review).
    this.appliedAutoFix    = null;
    this.mounted = false;
  }

  // ── wiring ────────────────────────────────────────────────────────────────

  private wire( els: SubmitJobsChromeElements ): void {
    // B9 — three card toggles. Session-only: nothing is written to storage, because
    // legacy's cards are collapsed in MARKUP and consult no persistence.
    for ( const card of [ els.cc, els.research, els.testSuite ] ) {
      const onToggle = (): void => {
        const collapsed = card.body.classList.toggle( "collapsed" );
        card.toggle.textContent = collapsed ? "▶" : "▼";
      };
      card.header.addEventListener( "click", onToggle );
      this.teardown.push( () => card.header.removeEventListener( "click", onToggle ) );
    }

    // Every schedule checkbox reveals its own time input. Legacy does this with an
    // inline `onchange` attribute, which the multiplexer does not use.
    for ( const s of [ els.cc.schedule, els.research.schedule, els.testSuite.schedule ] ) {
      const onChange = (): void => { s.time.hidden = !s.checkbox.checked; };
      s.checkbox.addEventListener( "change", onChange );
      this.teardown.push( () => s.checkbox.removeEventListener( "change", onChange ) );
    }

    this.wireCc( els );
    this.wireResearch( els );
    this.wireTestSuite( els );
    this.wireTfe( els );
  }

  private wireCc( els: SubmitJobsChromeElements ): void {
    const submit = (): void => {
      void this.store.submitCc( {
        prompt     : els.cc.prompt.value,
        project    : els.cc.project.value,
        taskType   : els.cc.taskType.value,
        dryRun     : els.cc.dryRun.checked,
        scheduling : schedulingOf( els.cc.schedule ),
      } );
      // J7 — the prompt is NOT cleared on success, unlike the research topic.
    };
    els.cc.submitBtn.addEventListener( "click", submit );
    // J5 — Ctrl+Enter, because a plain Enter has to put a newline in a textarea.
    els.cc.prompt.addEventListener( "keydown", ( e ) => {
      const ev = e as KeyboardEvent;
      if ( ev.key !== "Enter" || !ev.ctrlKey ) return;
      ev.preventDefault();
      submit();
    } );
    els.cc.micBtn.addEventListener( "click", () => {
      if ( this.micHandler === null ) return;
      this.micHandler( CC_MIC_CONTEXT, els.cc.micBtn, els.cc.prompt as unknown as HTMLInputElement );
    } );
  }

  private wireResearch( els: SubmitJobsChromeElements ): void {
    const submit = (): void => {
      void this.store.submitResearch( {
        topic            : els.research.topic.value,
        budget           : els.research.budget.value,
        withPodcast      : els.research.podcast.checked,
        withPresentation : els.research.presentation.checked,
        dryRun           : els.research.dryRun.checked,
        scheduling       : schedulingOf( els.research.schedule ),
      } ).then( ( submitted ) => {
        // J15 — the topic CLEARS on success. The CC prompt does not.
        if ( submitted ) els.research.topic.value = "";
      } );
    };
    els.research.submitBtn.addEventListener( "click", submit );
    // J13 — a plain Enter, because this one is a single-line input.
    els.research.topic.addEventListener( "keydown", ( e ) => {
      const ev = e as KeyboardEvent;
      if ( ev.key !== "Enter" ) return;
      ev.preventDefault();
      submit();
    } );
    els.research.micBtn.addEventListener( "click", () => {
      if ( this.micHandler === null ) return;
      this.micHandler( RESEARCH_MIC_CONTEXT, els.research.micBtn, els.research.topic );
    } );

    // J11 — mutually exclusive AT RUNTIME, which is where legacy enforces it: the
    // markup lets both be ticked and the submit path then disagrees with itself about
    // which one won. Ticking one unticks the other, so that state is unreachable.
    const exclusive = ( a: HTMLInputElement, b: HTMLInputElement ) => (): void => {
      if ( a.checked ) b.checked = false;
    };
    els.research.podcast.addEventListener( "change", exclusive( els.research.podcast, els.research.presentation ) );
    els.research.presentation.addEventListener( "change", exclusive( els.research.presentation, els.research.podcast ) );
  }

  private wireTestSuite( els: SubmitJobsChromeElements ): void {
    // J18 — TWO conditional rows on TWO DIFFERENT predicates. The file-path row keys
    // on membership of the file-driven set; the fail-fast row on the type being
    // EXACTLY `all`. One predicate for both would be wrong for every non-`all` type.
    const reconcile = (): void => {
      const type = els.testSuite.types.value;
      els.testSuite.filePathRow.hidden = !FILE_DRIVEN_TEST_TYPES.has( type );
      els.testSuite.failFastRow.hidden = type !== "all";
    };
    els.testSuite.types.addEventListener( "change", reconcile );
    reconcile();

    els.testSuite.submitBtn.addEventListener( "click", () => {
      void this.store.submitTestSuite( {
        testTypes  : els.testSuite.types.value,
        filePath   : els.testSuite.filePath.value,
        failFast   : els.testSuite.failFast.checked,
        pytestArgs : els.testSuite.pytestArgs.value,
        dryRun     : els.testSuite.dryRun.checked,
        autoFix    : els.testSuite.autoFix.checked,
        scheduling : schedulingOf( els.testSuite.schedule ),
      } );
    } );
  }

  private wireTfe( els: SubmitJobsChromeElements ): void {
    els.tfe.submitBtn.addEventListener( "click", () => { void this.submitTfe(); } );
  }

  /**
   * One TFE turn.
   *
   * Ensures:
   *   - an empty input raises legacy's browser alert and asks for nothing (J26)
   *   - a successful resume CLEARS the input (J30); an ambiguous answer does not,
   *     because the operator still has to pick
   */
  private async submitTfe(): Promise<void> {
    const els = this.els;
    /* c8 ignore next */ // defensive: every gesture path runs between mount and unmount.
    if ( els === null ) return;
    if ( els.tfe.input.value.trim() === "" ) {
      this.alertFn( TFE_EMPTY_ALERT );
      return;
    }
    const resumed = await this.store.submitTfeResume( els.tfe.input.value );
    if ( resumed ) els.tfe.input.value = "";
  }

  // ── paint ─────────────────────────────────────────────────────────────────

  private paint(): void {
    const els = this.els;
    /* c8 ignore next */ // defensive: every paint path runs between mount and unmount.
    if ( els === null ) return;

    this.paintCard( "cc",        els.cc.status,        els.cc.submitBtn,        els.cc.spinner );
    this.paintCard( "research",  els.research.status,  els.research.submitBtn,  els.research.spinner );
    this.paintCard( "testSuite", els.testSuite.status, els.testSuite.submitBtn, els.testSuite.spinner );
    this.paintCard( "tfe",       els.tfe.status,       els.tfe.submitBtn,       els.tfe.spinner );

    // J20 — the INI's value, once the config resolves.
    //
    // 🔴 ON CHANGE, NOT ON EVERY PAINT (María 🌸's B-2 review). The first cut wrote the
    // box unconditionally here, to solve a real problem: a config landing after mount
    // must still reach the box. But the store emits store_submit_jobs_changed for ANY
    // card's status or in-flight change, so submitting on the CC card repainted this one
    // and silently re-ticked a box the operator had just unticked — and the next
    // test-suite submit then carried auto_fix_on_failure against their explicit choice.
    //
    // Applying it when the VALUE CHANGES satisfies both: a late config is a change and
    // still lands; a repaint at an unchanged default does not touch the operator's box.
    const autoFixDefault = this.store.autoFixDefault();
    if ( autoFixDefault !== this.appliedAutoFix ) {
      els.testSuite.autoFix.checked = autoFixDefault;
      this.appliedAutoFix           = autoFixDefault;
    }

    this.paintTfeCandidates( els );
  }

  private paintCard(
    card     : CardKey,
    statusEl : HTMLElement,
    button   : HTMLButtonElement,
    spinner  : HTMLElement,
  ): void {
    const status = this.store.status( card );
    statusEl.textContent = status.text;
    statusEl.style.color = status.color;

    const busy = this.store.busy( card );
    button.disabled = busy;
    spinner.hidden  = !busy;
  }

  /**
   * J28/J29 — the disambiguation list.
   *
   * Ensures:
   *   - each row shows the confidence as a whole percent, the job id, the stalled
   *     stamp, the summary and the reason
   *   - a missing confidence reads `?` rather than `NaN%`
   *   - 🔴 every field goes in as TEXT, never as markup. Legacy builds these rows by
   *     string-concatenating into innerHTML and escapes by hand; a summary or reason
   *     is server-supplied text, so one missed escape there is an injection. Building
   *     nodes removes the question rather than answering it
   *   - clicking a row writes its id into the input and RE-SUBMITS (J29)
   *   - the list is rebuilt only when it CHANGES, so a repaint cannot drop a click
   */
  private paintTfeCandidates( els: SubmitJobsChromeElements ): void {
    const candidates = this.store.tfeCandidates();
    if ( candidates === this.paintedCandidates ) return;
    this.paintedCandidates = candidates;

    if ( candidates.length === 0 ) {
      els.tfe.candidates.replaceChildren();
      els.tfe.candidates.hidden = true;
      return;
    }

    const intro = document.createElement( "div" );
    intro.className   = "tfe-resume-candidates-intro";
    intro.textContent = "Click a candidate to resume it:";

    const rows = candidates.map( ( c ) => {
      const row = document.createElement( "div" );
      row.className = "tfe-resume-candidate";
      row.setAttribute( "data-testid", "multiplexer-tfe-resume-candidate" );
      row.setAttribute( "data-job-id", c.job_id );

      const conf = document.createElement( "strong" );
      conf.textContent = c.confidence === null || c.confidence === undefined
        ? "?"
        : `${Math.round( c.confidence * 100 )}%`;

      const id = document.createElement( "code" );
      id.textContent = c.job_id;

      const stalled = document.createElement( "span" );
      stalled.className   = "tfe-resume-candidate-stalled";
      stalled.textContent = c.stalled_at === null || c.stalled_at === undefined || c.stalled_at === ""
        ? ""
        : `stalled ${c.stalled_at}`;

      const detail = document.createElement( "div" );
      detail.className = "tfe-resume-candidate-detail";
      const summary = c.summary ?? "";
      const reason  = c.reason ?? "";
      detail.textContent = reason === "" ? summary : `${summary} — ${reason}`;

      row.append( conf, " · ", id, " ", stalled, detail );
      row.addEventListener( "click", () => {
        els.tfe.input.value = c.job_id;
        void this.submitTfe();
      } );
      return row;
    } );

    els.tfe.candidates.replaceChildren( intro, ...rows );
    els.tfe.candidates.hidden = false;
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createSubmitJobsPaneRenderer(
  opts: SubmitJobsPaneRendererOptions,
): SubmitJobsPaneRenderer {
  return new SubmitJobsPaneRendererImpl( opts );
}
