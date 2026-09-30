/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Parity B-1 — the Q&A Interface pane's DOM, built once.
//
// Ports legacy's markup verbatim in structure and in every visible string
// (notifications.html:102-159): the agent-mode row (label · select · badge ·
// status), the input row (🎤 · text · TTS-mode select · Submit + spinner), the
// metrics strip, the interview container and the response pane.
//
// 🔴 THE AGENT SELECT SHIPS EMPTY, DELIBERATELY. Legacy's element carries a long
// comment saying so and a python test — test_qa_agent_select_is_not_hand_written.py
// — that reddens if an `<option>` reappears. Every option is rendered at runtime
// from GET /api/v2/agents, including the Auto-Route entry, which arrives as a
// sentinel in that response. A hand-written option would be a short mode key that
// /api/v2/submit cannot route.
//
// The TTS-mode select is the opposite case: its two options ARE markup in legacy
// (notifications.html:134-137), they are not persisted, and `instant` is selected.
//
// Ids are the legacy ids where legacy has one, because the parity register's
// anchors and the E2E selectors both name them; testids are prefixed
// `multiplexer-` as every other mux pane does.

export interface QaChromeElements {
  /** The collapsible body — carries `.section-content` for the shared collapse rule. */
  body         : HTMLDivElement;
  agentSelect  : HTMLSelectElement;
  modeBadge    : HTMLSpanElement;
  modeStatus   : HTMLSpanElement;
  micBtn       : HTMLButtonElement;
  input        : HTMLInputElement;
  ttsModeSelect: HTMLSelectElement;
  submitBtn    : HTMLButtonElement;
  spinner      : HTMLSpanElement;
  metrics      : HTMLDivElement;
  metricTtt    : HTMLSpanElement;
  metricTtfa   : HTMLSpanElement;
  metricRtt    : HTMLSpanElement;
  interview    : HTMLDivElement;
  response     : HTMLDivElement;
}

function metricSpan( label: string, valueId: string, testid: string ): {
  wrapper: HTMLSpanElement;
  value  : HTMLSpanElement;
} {
  const wrapper = document.createElement( "span" );
  wrapper.className = "metric";

  const labelEl = document.createElement( "span" );
  labelEl.className   = "metric-label";
  labelEl.textContent = label;

  const value = document.createElement( "span" );
  value.id          = valueId;
  value.setAttribute( "data-testid", testid );
  value.textContent = "--";

  wrapper.append( labelEl, " ", value );
  return { wrapper, value };
}

/**
 * Build the Q&A pane's body.
 *
 * Ensures:
 *   - the agent select is EMPTY (see the file header) and the TTS-mode select
 *     carries legacy's two options with `instant` selected
 *   - the badge, the spinner and the metrics strip start hidden, and the interview
 *     container starts `hidden` — its hidden state is the single signal of whether
 *     an interview is in progress, which is the contract arg-interview.js documents
 *   - the response pane starts on legacy's empty string
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line (same as sectionHeader.ts).
export function renderQaChrome(): QaChromeElements {
  const body = document.createElement( "div" );
  body.className = "section-content qa-section-content";
  body.setAttribute( "data-testid", "multiplexer-qa-body" );

  // ── agent-mode row ────────────────────────────────────────────────────────
  const modeRow = document.createElement( "div" );
  modeRow.className = "mode-selector-container";

  const modeLabel = document.createElement( "label" );
  modeLabel.htmlFor    = "agent-mode";
  modeLabel.textContent = "Agent Mode:";

  const agentSelect = document.createElement( "select" );
  agentSelect.id        = "agent-mode";
  agentSelect.className = "agent-mode-select";
  agentSelect.setAttribute( "data-testid", "multiplexer-qa-mode-select" );

  const modeBadge = document.createElement( "span" );
  modeBadge.id        = "mode-badge";
  modeBadge.className = "mode-badge";
  modeBadge.setAttribute( "data-testid", "multiplexer-qa-mode-badge" );
  modeBadge.title     = "Click to return to System mode";
  modeBadge.hidden    = true;

  const modeStatus = document.createElement( "span" );
  modeStatus.id = "mode-status";
  modeStatus.setAttribute( "data-testid", "multiplexer-qa-mode-status" );
  modeStatus.textContent = "Auto-routing enabled";

  modeRow.append( modeLabel, agentSelect, modeBadge, modeStatus );

  // ── input row ─────────────────────────────────────────────────────────────
  const inputRow = document.createElement( "div" );
  inputRow.className = "form-group qa-form-group";

  const micBtn = document.createElement( "button" );
  micBtn.type      = "button";
  micBtn.id        = "qa-stt-button";
  micBtn.className = "qa-stt-button";
  micBtn.title     = "Click to record (30s max, ESC to cancel)";
  micBtn.setAttribute( "data-testid", "multiplexer-qa-stt-btn" );
  micBtn.textContent = "🎤";

  const input = document.createElement( "input" );
  input.type        = "text";
  input.id          = "qa-input";
  input.placeholder = "Type your question here...";
  input.setAttribute( "data-testid", "multiplexer-qa-input" );

  const ttsModeSelect = document.createElement( "select" );
  ttsModeSelect.id = "tts-mode";
  ttsModeSelect.setAttribute( "data-testid", "multiplexer-qa-tts-mode-select" );
  for ( const [ value, label ] of [
    [ "instant",  "Instant (11labs Streaming)" ],
    [ "reliable", "Reliable (OpenAI Batch)" ],
  ] as ReadonlyArray<readonly [ string, string ]> ) {
    const option = document.createElement( "option" );
    option.value       = value;
    option.textContent = label;
    ttsModeSelect.appendChild( option );
  }
  ttsModeSelect.value = "instant";

  const submitBtn = document.createElement( "button" );
  submitBtn.type = "button";
  submitBtn.id   = "submit-qa";
  submitBtn.setAttribute( "data-testid", "multiplexer-qa-submit-btn" );
  submitBtn.append( "Submit Q&A" );

  const spinner = document.createElement( "span" );
  spinner.id        = "submit-loading";
  spinner.className = "loading";
  spinner.setAttribute( "data-testid", "multiplexer-qa-submit-loading" );
  spinner.hidden    = true;
  const spinnerDot = document.createElement( "span" );
  spinnerDot.className = "spinner";
  spinner.appendChild( spinnerDot );
  submitBtn.appendChild( spinner );

  inputRow.append( micBtn, input, ttsModeSelect, submitBtn );

  // ── metrics strip ─────────────────────────────────────────────────────────
  const metrics = document.createElement( "div" );
  metrics.id        = "qa-metrics";
  metrics.className = "qa-metrics";
  metrics.setAttribute( "data-testid", "multiplexer-qa-metrics" );
  metrics.hidden    = true;

  const ttt  = metricSpan( "TTT:",  "metric-ttt",  "multiplexer-qa-metric-ttt" );
  const ttfa = metricSpan( "TTFA:", "metric-ttfa", "multiplexer-qa-metric-ttfa" );
  const rtt  = metricSpan( "RTT:",  "metric-rtt",  "multiplexer-qa-metric-rtt" );
  metrics.append( ttt.wrapper, ttfa.wrapper, rtt.wrapper );

  // ── interview + response ──────────────────────────────────────────────────
  const interview = document.createElement( "div" );
  interview.id        = "qa-arg-interview";
  interview.className = "qa-arg-interview";
  interview.setAttribute( "data-testid", "multiplexer-qa-arg-interview" );
  interview.hidden    = true;

  const response = document.createElement( "div" );
  response.id = "response-text";
  response.setAttribute( "data-testid", "multiplexer-qa-response-text" );
  response.textContent = "No response yet...";

  body.append( modeRow, inputRow, metrics, interview, response );

  return {
    body, agentSelect, modeBadge, modeStatus,
    micBtn, input, ttsModeSelect, submitBtn, spinner,
    metrics, metricTtt: ttt.value, metricTtfa: ttfa.value, metricRtt: rtt.value,
    interview, response,
  };
}
