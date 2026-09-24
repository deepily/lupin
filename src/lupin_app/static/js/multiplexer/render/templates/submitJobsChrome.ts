/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Parity B-2 — the Submit Agentic Jobs pane's DOM, built once.
//
// Ports legacy's markup (notifications.html § "Job Submission Section") in structure
// and in every visible string: four cards, their controls, their schedule rows and
// their status lines.
//
// 🔴 THE FOURTH CARD HAS NO TOGGLE AND IS ALWAYS OPEN (B9). The first three are
// `.section-content collapsed` in legacy's markup with a ▶ chevron each; the TFE card
// has no chevron and no collapsed class. That asymmetry is legacy's and it is
// reproduced — a fourth chevron "for consistency" would be a behaviour change nobody
// asked for.
//
// ⚠️ AND THE COLLAPSE IS NOT PERSISTED (B9). The cards are collapsed in MARKUP, which
// means they start collapsed on every load; none of them consults storage. Wiring the
// A-2 #6 persist key here would be a silent divergence.
//
// The schedule time input starts hidden and is revealed by its checkbox — legacy does
// this with an inline `onchange` attribute, which this file cannot use (no inline
// handlers in the multiplexer); the renderer wires it instead.

/** The controls of one scheduling row (every card but TFE has one). */
export interface ScheduleEls {
  row        : HTMLDivElement;
  checkbox   : HTMLInputElement;
  time       : HTMLInputElement;
  monopolize : HTMLInputElement | null;
}

export interface CcCardEls {
  card      : HTMLDivElement;
  header    : HTMLDivElement;
  toggle    : HTMLButtonElement;
  body      : HTMLDivElement;
  project   : HTMLSelectElement;
  micBtn    : HTMLButtonElement;
  prompt    : HTMLTextAreaElement;
  taskType  : HTMLSelectElement;
  dryRun    : HTMLInputElement;
  submitBtn : HTMLButtonElement;
  spinner   : HTMLSpanElement;
  status    : HTMLDivElement;
  schedule  : ScheduleEls;
}

export interface ResearchCardEls {
  card         : HTMLDivElement;
  header       : HTMLDivElement;
  toggle       : HTMLButtonElement;
  body         : HTMLDivElement;
  micBtn       : HTMLButtonElement;
  topic        : HTMLInputElement;
  budget       : HTMLInputElement;
  podcast      : HTMLInputElement;
  presentation : HTMLInputElement;
  dryRun       : HTMLInputElement;
  submitBtn    : HTMLButtonElement;
  spinner      : HTMLSpanElement;
  status       : HTMLDivElement;
  schedule     : ScheduleEls;
}

export interface TestSuiteCardEls {
  card         : HTMLDivElement;
  header       : HTMLDivElement;
  toggle       : HTMLButtonElement;
  body         : HTMLDivElement;
  types        : HTMLSelectElement;
  filePathRow  : HTMLDivElement;
  filePath     : HTMLInputElement;
  failFastRow  : HTMLLabelElement;
  failFast     : HTMLInputElement;
  pytestArgs   : HTMLInputElement;
  dryRun       : HTMLInputElement;
  autoFix      : HTMLInputElement;
  submitBtn    : HTMLButtonElement;
  spinner      : HTMLSpanElement;
  status       : HTMLDivElement;
  schedule     : ScheduleEls;
}

export interface TfeCardEls {
  card       : HTMLDivElement;
  body       : HTMLDivElement;
  input      : HTMLTextAreaElement;
  submitBtn  : HTMLButtonElement;
  spinner    : HTMLSpanElement;
  status     : HTMLDivElement;
  candidates : HTMLDivElement;
}

export interface SubmitJobsChromeElements {
  /** The collapsible body — carries `.section-content` for the shared collapse rule. */
  body      : HTMLDivElement;
  cc        : CcCardEls;
  research  : ResearchCardEls;
  testSuite : TestSuiteCardEls;
  tfe       : TfeCardEls;
}

// ---------------------------------------------------------------------------
// Small builders
// ---------------------------------------------------------------------------

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K, className?: string, testid?: string,
): HTMLElementTagNameMap[ K ] {
  const node = document.createElement( tag );
  if ( className !== undefined ) node.className = className;
  if ( testid !== undefined ) node.setAttribute( "data-testid", testid );
  return node;
}

function checkbox( id: string, testid: string, checked: boolean ): HTMLInputElement {
  const box = document.createElement( "input" );
  box.type    = "checkbox";
  box.id      = id;
  box.checked = checked;
  box.setAttribute( "data-testid", testid );
  return box;
}

// No trailing-text parameter: the first cut had one and NOTHING passed it, so it was
// a branch no caller could reach — and under a 100% gate an unreachable branch becomes
// a pragma somebody has to justify. Deleted rather than tested.
function labelled( text: string, control: HTMLElement ): HTMLLabelElement {
  const label = document.createElement( "label" );
  label.append( control, ` ${text}` );
  return label;
}

function statusLine( id: string, testid: string ): HTMLDivElement {
  const div = el( "div", "job-submit-status", testid );
  div.id = id;
  return div;
}

/** A submit button with legacy's inline spinner inside it. */
function submitButton( id: string, testid: string, text: string, spinnerId: string ): {
  button: HTMLButtonElement; spinner: HTMLSpanElement;
} {
  const button = document.createElement( "button" );
  button.type = "button";
  button.id   = id;
  button.setAttribute( "data-testid", testid );
  button.append( text );

  const spinner = el( "span", "loading" );
  spinner.id     = spinnerId;
  spinner.hidden = true;
  spinner.appendChild( el( "span", "spinner" ) );
  button.appendChild( spinner );
  return { button, spinner };
}

/**
 * One card's header bar and its ▶ chevron.
 *
 * The three toggling cards start COLLAPSED, which is legacy's markup state, so the
 * chevron ships as ▶ rather than ▼.
 */
function cardHeader( title: string, toggleId: string ): {
  header: HTMLDivElement; toggle: HTMLButtonElement;
} {
  const header = el( "div", "job-submit-card-header" );
  const h4 = document.createElement( "h4" );
  h4.textContent = title;

  const toggle = document.createElement( "button" );
  toggle.type        = "button";
  toggle.className   = "toggle-button";
  toggle.id          = toggleId;
  toggle.textContent = "▶";
  toggle.setAttribute( "aria-label", "Toggle card" );

  header.append( h4, toggle );
  return { header, toggle };
}

/**
 * A card's schedule row.
 *
 * The time input starts hidden; the renderer reveals it on the checkbox. `monopolize`
 * is omitted for the test-suite card, whose door is always-on monopolize server-side.
 */
function scheduleRow( prefix: string, withMonopolize: boolean ): ScheduleEls {
  const row = el( "div", "schedule-section", `multiplexer-${prefix}-schedule-section` );

  const check = checkbox( `${prefix}-schedule`, `multiplexer-${prefix}-schedule-checkbox`, false );
  const time  = document.createElement( "input" );
  time.type   = "datetime-local";
  time.id     = `${prefix}-scheduled-time`;
  time.hidden = true;
  time.setAttribute( "data-testid", `multiplexer-${prefix}-scheduled-time` );

  row.append( labelled( "Schedule for later", check ), time );

  let monopolize: HTMLInputElement | null = null;
  if ( withMonopolize ) {
    monopolize = checkbox( `${prefix}-monopolize`, `multiplexer-${prefix}-monopolize-checkbox`, false );
    row.append( labelled( "🔒 Exclusive mode", monopolize ) );
  }

  return { row, checkbox: check, time, monopolize };
}

function option( value: string, label: string, selected = false, disabled = false ): HTMLOptionElement {
  const o = document.createElement( "option" );
  o.value       = value;
  o.textContent = label;
  if ( selected ) o.selected = true;
  if ( disabled ) o.disabled = true;
  return o;
}

// ---------------------------------------------------------------------------
// Card 1 — Claude Code
// ---------------------------------------------------------------------------

function buildCcCard(): CcCardEls {
  const card = el( "div", "job-submit-card", "multiplexer-cc-card" );
  card.id = "claude-code-submit-card";
  const { header, toggle } = cardHeader( "🤖 Submit Claude Code Task", "claude-code-toggle" );

  const body = el( "div", "section-content collapsed", "multiplexer-cc-card-body" );
  body.id = "claude-code-section";

  // J1 — three STATIC options, `lupin` selected. Unlike the Q&A agent select, this
  // list is markup in legacy and is not fetched.
  const project = document.createElement( "select" );
  project.id = "cc-project";
  project.setAttribute( "data-testid", "multiplexer-cc-project-select" );
  project.append( option( "lupin", "lupin", true ), option( "cosa", "cosa" ), option( "plan", "plan" ) );

  const micBtn = el( "button", "stt-button", "multiplexer-cc-stt-btn" );
  micBtn.type        = "button";
  micBtn.id          = "cc-stt-button";
  micBtn.title       = "Click to record (30s max, ESC to cancel)";
  micBtn.textContent = "🎤";

  const prompt = document.createElement( "textarea" );
  prompt.id          = "cc-prompt";
  prompt.rows        = 2;
  prompt.placeholder = "Enter task prompt...";
  prompt.setAttribute( "data-testid", "multiplexer-cc-prompt-textarea" );

  // J3 — INTERACTIVE is present and DISABLED, carrying legacy's explanation. Omitting
  // it would hide that the mode exists and is coming back.
  const taskType = document.createElement( "select" );
  taskType.id = "cc-task-type";
  taskType.setAttribute( "data-testid", "multiplexer-cc-task-type-select" );
  const interactive = option( "INTERACTIVE", "Interactive (coming back later)", false, true );
  interactive.title = "Returns when ClaudeCodeJob.inject/interrupt/end_session ship "
    + "— see TODO.md 'CC DISPATCH RETIREMENT — Follow-ups'";
  taskType.append( option( "BOUNDED", "Bounded", true ), interactive );

  // J4 — checked by default, so a mis-click costs nothing.
  const dryRun = checkbox( "cc-dry-run", "multiplexer-cc-dry-run-checkbox", true );

  const { button, spinner } = submitButton(
    "cc-submit", "multiplexer-cc-submit-btn", "Submit to Queue", "cc-loading" );
  const status = statusLine( "cc-submit-status", "multiplexer-cc-submit-status" );

  const schedule = scheduleRow( "cc", true );

  body.append(
    labelled( "Project", project ),
    el( "div", "cc-prompt-row" ),
    micBtn, prompt,
    labelled( "Task type", taskType ),
    labelled( "Dry run", dryRun ),
    button, status, schedule.row,
  );
  card.append( header, body );

  return {
    card, header, toggle, body, project, micBtn, prompt, taskType, dryRun,
    submitBtn: button, spinner, status, schedule,
  };
}

// ---------------------------------------------------------------------------
// Card 2 — Research
// ---------------------------------------------------------------------------

function buildResearchCard(): ResearchCardEls {
  const card = el( "div", "job-submit-card", "multiplexer-research-card" );
  card.id = "research-submit-card";
  const { header, toggle } = cardHeader( "🔬 Submit Research Job", "research-submit-toggle" );

  const body = el( "div", "section-content collapsed", "multiplexer-research-card-body" );
  body.id = "research-submit-section";

  const micBtn = el( "button", "stt-button", "multiplexer-research-stt-btn" );
  micBtn.type        = "button";
  micBtn.id          = "research-stt-button";
  micBtn.title       = "Click to record (30s max, ESC to cancel)";
  micBtn.textContent = "🎤";

  const topic = document.createElement( "input" );
  topic.type        = "text";
  topic.id          = "research-topic";
  topic.placeholder = "Enter your research question...";
  topic.setAttribute( "data-testid", "multiplexer-research-topic-input" );

  // J10 — the range and step are legacy's; the 3.00 fallback lives in the store.
  const budget = document.createElement( "input" );
  budget.type  = "number";
  budget.id    = "research-budget";
  budget.value = "3.00";
  budget.min   = "0.50";
  budget.max   = "20.00";
  budget.step  = "0.50";
  budget.setAttribute( "data-testid", "multiplexer-research-budget-input" );

  const podcast      = checkbox( "research-with-podcast", "multiplexer-research-podcast-checkbox", false );
  const presentation = checkbox( "research-with-presentation", "multiplexer-research-presentation-checkbox", false );
  const dryRun       = checkbox( "research-dry-run", "multiplexer-research-dry-run-checkbox", true );

  const { button, spinner } = submitButton(
    "submit-research-job", "multiplexer-research-submit-btn", "Submit Research Job", "research-loading" );
  const status = statusLine( "research-submit-status", "multiplexer-research-submit-status" );

  const schedule = scheduleRow( "research", true );

  body.append(
    micBtn, topic,
    labelled( "Budget ($)", budget ),
    labelled( "With podcast", podcast ),
    labelled( "With presentation", presentation ),
    labelled( "Dry run", dryRun ),
    schedule.row, button, status,
  );
  card.append( header, body );

  return {
    card, header, toggle, body, micBtn, topic, budget, podcast, presentation, dryRun,
    submitBtn: button, spinner, status, schedule,
  };
}

// ---------------------------------------------------------------------------
// Card 3 — Test Suite
// ---------------------------------------------------------------------------

/** J17 — four optgroups, twelve options, `integration,e2e` selected. */
const TEST_SUITE_GROUPS: ReadonlyArray<readonly [ string, ReadonlyArray<readonly [ string, string ]> ]> = [
  [ "Aggregate", [
    [ "all",              "All (unit → smoke → websocket → integration → e2e)" ],
    [ "integration,e2e",  "Both (Integration + E2E)" ],
  ] ],
  [ "Individual suites", [
    [ "unit",          "Unit Tests" ],
    [ "smoke",         "Smoke Tests (pytest discovery)" ],
    [ "smoke_direct",  "Smoke Direct (python-main-style, needs file path)" ],
    [ "pytest_direct", "Pytest Direct (arbitrary pytest file, needs file path)" ],
    [ "websocket",     "WebSocket Tests" ],
    [ "integration",   "Integration Only" ],
    [ "e2e",           "E2E Only" ],
  ] ],
  [ "Combined", [
    [ "unit,smoke",           "Fast Tier (Unit + Smoke)" ],
    [ "unit,smoke,websocket", "Non-server-hotswap (Unit + Smoke + WebSocket)" ],
  ] ],
  [ "Agentic Regression", [
    [ "presentation", "Presentation Regression (render-only + Sonnet)" ],
  ] ],
];

const TEST_SUITE_DEFAULT = "integration,e2e";

function buildTestSuiteCard(): TestSuiteCardEls {
  const card = el( "div", "job-submit-card", "multiplexer-test-suite-card" );
  card.id = "test-suite-submit-card";
  const { header, toggle } = cardHeader( "🧪 Run Test Suite", "test-suite-submit-toggle" );

  const body = el( "div", "section-content collapsed", "multiplexer-test-suite-card-body" );
  body.id = "test-suite-submit-section";

  const types = document.createElement( "select" );
  types.id = "test-suite-types";
  types.setAttribute( "data-testid", "multiplexer-test-suite-types-select" );
  for ( const [ label, entries ] of TEST_SUITE_GROUPS ) {
    const group = document.createElement( "optgroup" );
    group.label = label;
    for ( const [ value, text ] of entries ) {
      group.appendChild( option( value, text, value === TEST_SUITE_DEFAULT ) );
    }
    types.appendChild( group );
  }

  // J18 — both conditional rows start hidden; the renderer reveals each on its own
  // predicate, which are NOT the same predicate.
  const filePathRow = el( "div", "test-suite-conditional-row", "multiplexer-test-suite-file-path-row" );
  filePathRow.id     = "test-suite-file-path-row";
  filePathRow.hidden = true;
  const filePath = document.createElement( "input" );
  filePath.type        = "text";
  filePath.id          = "test-suite-file-path";
  filePath.placeholder = "src/tests/integration/test_tfe_resume_e2e.py";
  filePath.setAttribute( "data-testid", "multiplexer-test-suite-file-path-input" );
  filePathRow.append( labelled( "Test file path", filePath ) );

  const failFast = checkbox( "test-suite-fail-fast", "multiplexer-test-suite-fail-fast-checkbox", false );
  const failFastRow = document.createElement( "label" );
  failFastRow.id        = "test-suite-fail-fast-row";
  failFastRow.className = "test-suite-conditional-row";
  failFastRow.hidden    = true;
  failFastRow.setAttribute( "data-testid", "multiplexer-test-suite-fail-fast-row" );
  failFastRow.append( failFast, " Stop at the first failing tier" );

  const pytestArgs = document.createElement( "input" );
  pytestArgs.type        = "text";
  pytestArgs.id          = "test-suite-pytest-args";
  pytestArgs.placeholder = "-v -k test_auth  (or --auto-proxy --cost-cap-usd 2.00 for smoke_direct)";
  pytestArgs.setAttribute( "data-testid", "multiplexer-test-suite-pytest-args-input" );

  const dryRun = checkbox( "test-suite-dry-run", "multiplexer-test-suite-dry-run-checkbox", true );
  // J20 — UNCHECKED here, which is legacy's markup default, and overwritten at config
  // load from the INI. §6 item 14 specifies the pre-resolve value, and it is this one:
  // a box that painted itself checked before the config landed would be claiming a
  // setting nobody had read yet.
  const autoFix = checkbox( "test-suite-auto-fix", "multiplexer-test-suite-auto-fix-checkbox", false );

  const { button, spinner } = submitButton(
    "submit-test-suite-job", "multiplexer-test-suite-submit-btn", "Run Test Suite", "test-suite-loading" );
  const status = statusLine( "test-suite-submit-status", "multiplexer-test-suite-submit-status" );

  // No monopolize box: this door is always-on monopolize server-side.
  const schedule = scheduleRow( "test-suite", false );

  body.append(
    labelled( "Test types", types ),
    filePathRow, failFastRow,
    labelled( "Pytest args", pytestArgs ),
    labelled( "Dry run", dryRun ),
    labelled( "Auto-fix on failure", autoFix ),
    schedule.row, button, status,
  );
  card.append( header, body );

  return {
    card, header, toggle, body, types, filePathRow, filePath, failFastRow, failFast,
    pytestArgs, dryRun, autoFix, submitBtn: button, spinner, status, schedule,
  };
}

// ---------------------------------------------------------------------------
// Card 4 — TFE resume
// ---------------------------------------------------------------------------

function buildTfeCard(): TfeCardEls {
  const card = el( "div", "job-submit-card", "multiplexer-tfe-resume-card" );
  card.id = "tfe-resume-submit-card";

  const header = el( "div", "job-submit-card-header" );
  const h4 = document.createElement( "h4" );
  h4.textContent = "🔄 Resume Stalled TFE Job";
  header.appendChild( h4 );
  // 🔴 NO CHEVRON, and the body is NOT `.collapsed` (B9). Legacy's fourth card has no
  // toggle and is always open; adding one "for consistency" would change behaviour.

  const body = el( "div", "section-content", "multiplexer-tfe-resume-card-body" );

  // J25 — a free-form textarea and NO voice button, unlike its three siblings.
  const input = document.createElement( "textarea" );
  input.id          = "tfe-resume-input";
  input.rows        = 2;
  input.placeholder = "tfe-7c25082a  OR  io/swe-team/plans/.../c1-plan.md  OR  'the stalled one from today'";
  input.setAttribute( "data-testid", "multiplexer-tfe-resume-input" );

  const { button, spinner } = submitButton(
    "submit-tfe-resume-job", "multiplexer-tfe-resume-submit-btn", "Resume", "tfe-resume-loading" );
  const status = statusLine( "tfe-resume-submit-status", "multiplexer-tfe-resume-submit-status" );

  const candidates = el( "div", "tfe-resume-candidates", "multiplexer-tfe-resume-candidates" );
  candidates.id     = "tfe-resume-candidates";
  candidates.hidden = true;

  body.append( input, button, status, candidates );
  card.append( header, body );

  return { card, body, input, submitBtn: button, spinner, status, candidates };
}

// ---------------------------------------------------------------------------

/**
 * Build the Submit Agentic Jobs body.
 *
 * Ensures:
 *   - the first three cards are COLLAPSED with a ▶ chevron; the fourth has neither a
 *     chevron nor the collapsed class (B9)
 *   - every `*-submit-status` starts empty (B10) and every spinner starts hidden
 *   - both of the test-suite card's conditional rows start hidden, as does every
 *     schedule time input
 *   - the dry-run box is CHECKED on all three cards that have one, and the auto-fix
 *     box is UNCHECKED until the config resolves it (J20)
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function renderSubmitJobsChrome(): SubmitJobsChromeElements {
  const body = el( "div", "section-content submit-jobs-content", "multiplexer-submit-jobs-body" );
  body.id = "job-submit-section";

  const cc        = buildCcCard();
  const research  = buildResearchCard();
  const testSuite = buildTestSuiteCard();
  const tfe       = buildTfeCard();

  body.append( cc.card, research.card, testSuite.card, tfe.card );
  return { body, cc, research, testSuite, tfe };
}
