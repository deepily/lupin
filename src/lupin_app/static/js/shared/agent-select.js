/* c8 ignore next */ // tsx phantom-branch artifact on file-header line (same as multiplexer/wireTtsIntent.ts:1).
/**
 * The Q&A card's agent dropdown, built from GET /api/v2/agents.
 *
 * WHY THIS FILE EXISTS. The dropdown used to be sixteen hand-typed <option> tags in
 * notifications.html — one of five hand-maintained lists describing the same set of
 * agents, and the only one a user could see. The registry has been the single source
 * of truth for the other four since the 2026.08.15 phase-1 work; this module is how
 * the fifth stops being written by hand (2026.08.22 plan §5.2, phase 3).
 *
 * WHY A MODULE AND NOT A METHOD ON NotificationsUI. notifications.js is a classic
 * script, so nothing in it can be imported by a test — the render would be reachable
 * only through a live browser. Same shape as shared/task-list-query.js: an ES module
 * the page loads with type="module", exported for `tsx --test` and published on
 * `window` for the classic-script consumer, read at CALL time so module execution
 * order cannot matter.
 *
 * THE OPTION VALUE IS THE ROUTING COMMAND, VERBATIM. Today's values are short mode
 * keys ("math", "deep_research") that a server-side map translates back into
 * commands. Emitting the command removes that translation layer, and with it the one
 * place drift could hide: a guard that set-equals option values against the registry
 * is meaningless if the two are written in different vocabularies.
 */

export const AGENTS_ENDPOINT = "/api/v2/agents";

/**
 * The shapes GET /api/v2/agents actually returns.
 *
 * These are not a guess at the payload — they are a transcription of the response
 * models in `src/cosa/rest/routers/v2_ask.py` (`AgentOption`, `AutoRouteOption`,
 * `AgentsResponse`), field for field, with `Optional[str]` written as `string|null`
 * because that is what a Pydantic optional serialises to. Only the fields this
 * module reads are listed; the rest of the projection is real but irrelevant here.
 *
 * `payload` is typed nullable everywhere below because a failed fetch is a state
 * this module already handles — see the "Returns [] on a missing or malformed
 * payload" clause on buildAgentSelectOptions.
 *
 * @typedef {Object} AgentEntry
 * @property {string} command
 * @property {string} display_name
 * @property {string} cls
 * @property {string|null} [description]
 * @property {boolean} [user_initiable]
 * @property {string[]} [required_args]
 */

/**
 * @typedef {Object} AutoRouteSentinel
 * @property {string} value
 * @property {string} label
 * @property {string} description
 */

/**
 * @typedef {Object} AgentsPayload
 * @property {AutoRouteSentinel} [auto_route]
 * @property {AgentEntry[]} [agents]
 */

/**
 * One rendered <option>, as buildAgentSelectOptions returns it.
 *
 * @typedef {Object} AgentSelectOption
 * @property {string} value
 * @property {string} label
 * @property {string|null|undefined} description
 * @property {string|null} group
 */

/**
 * Which heading each command class renders under.
 *
 * A map of CLASS names to headings — four entries that change when the CommandClass
 * enum changes — and deliberately not a list of agents. The two headings that
 * survive are the ones the hand-written select already used.
 *
 * `none` maps to "Quick Agents" for ONE STATED REASON — Rick's ruling 3, 2026-08-22.
 * The receptionist is classed `none` because that describes how the ROUTER reaches
 * it: the else-branch you land on when nothing matches. It says nothing about whether
 * a person may pick it on purpose, and Rick ruled that they may — "it is both an
 * agent that you can call because you want to call it, and it is also the else case
 * when you get bounced". So it renders with the conversational agents rather than
 * under a heading named after the failure path it shares a class with. That is why
 * the grouping is NOT a plain projection of `cls`: an exception with a written
 * reason, not an accident.
 *
 * Typed string-keyed rather than as a closed union of the four class names, because
 * the lookup below already writes `|| agent.cls`. That fallback IS the statement that
 * an unrecognised class is expected and rendered under its own name; a closed type
 * would contradict code that is already there.
 *
 * @type {Record<string, string>}
 */
const GROUP_HEADINGS = {
    conversational : "Quick Agents",
    agentic        : "Agentic Processes",
    control        : "Mode Control",
    none           : "Quick Agents"
};

/**
 * Build the option list for the Q&A card's select.
 *
 * Requires:
 *     - payload is a GET /api/v2/agents body:
 *       { auto_route: {value,label,description},
 *         agents: [ {command,display_name,cls,description,user_initiable,...} ] }
 *
 * Ensures:
 *     - Returns [ { value, label, description, group } ] — the Auto-Route sentinel
 *       FIRST with group null, then one entry per user_initiable command
 *     - Filters on `user_initiable` and on nothing else. Not on `speakable`, which
 *       answers "belongs in the voice router prompt" and is a different question: a
 *       command that is typeable but not sayable belongs here and in no voice prompt.
 *       Not on `cls` either — see the receptionist exception above
 *     - Reads `display_name` for the option text, never `label`. `label` is the
 *       SPOKEN string ("date and time"); rendering it here is what turned
 *       "Math Agent" into "math" in the first cut
 *     - Group order follows first appearance, so the server's declaration order is
 *       what the user sees; within a group, payload order
 *     - Returns [] on a missing or malformed payload rather than throwing into a
 *       page-load path — the caller renders the failure, see renderAgentSelect
 *
 * @param {AgentsPayload|null|undefined} payload
 * @returns {AgentSelectOption[]}
 */
export function buildAgentSelectOptions( payload ) {
    const autoRoute = payload && payload.auto_route;
    if ( !autoRoute || !autoRoute.value ) return [];

    // Annotated because the first element's `group` is null and every later one is a
    // string — inferred from the literal alone, the array would be typed as
    // null-group-only and the push below would read as an error in correct code.
    /** @type {AgentSelectOption[]} */
    const options = [ {
        value       : autoRoute.value,
        label       : autoRoute.label,
        description : autoRoute.description,
        group       : null
    } ];

    const agents = Array.isArray( payload.agents ) ? payload.agents : [];
    for ( const agent of agents ) {
        if ( !agent.user_initiable ) continue;
        options.push( {
            value       : agent.command,
            label       : agent.display_name,
            description : agent.description,
            group       : GROUP_HEADINGS[ agent.cls ] || agent.cls
        } );
    }
    return options;
}

/**
 * Replace a <select>'s contents with the options built from a payload.
 *
 * Requires:
 *     - selectEl is a <select> element; payload is as buildAgentSelectOptions takes
 *
 * Ensures:
 *     - The select ends up holding EXACTLY the built options — every prior child is
 *       removed first, so a second render cannot double the list
 *     - Grouped options land inside an <optgroup> carrying the group's heading; the
 *       sentinel sits at top level and is selected
 *     - Each option carries its description as a title attribute, which is the only
 *       place that help text has ever been visible to a user
 *     - An empty option list leaves the select EMPTY rather than half-rendered, so a
 *       failed fetch reads as "nothing loaded" instead of a silently shortened list
 *       of agents — the failure mode that matters here is a MISSING agent, and a
 *       shortened list looks exactly like a working one
 *     - Returns the option values in render order, so a caller (and a test) can read
 *       what was rendered without walking the DOM
 *
 * @param {HTMLSelectElement} selectEl
 * @param {AgentsPayload|null|undefined} payload
 * @returns {string[]}
 */
export function renderAgentSelect( selectEl, payload ) {
    const options = buildAgentSelectOptions( payload );
    selectEl.replaceChildren();

    /** @type {Map<string, HTMLOptGroupElement>} */
    const groups = new Map();
    for ( const option of options ) {
        const element = selectEl.ownerDocument.createElement( "option" );
        element.value       = option.value;
        element.textContent = option.label;
        if ( option.description ) element.title = option.description;

        if ( option.group === null ) {
            // No explicit `selected` — a <select> with no marked option already
            // selects its first, and buildAgentSelectOptions puts the sentinel there.
            // Setting it anyway measured as dead code: removing the line left every
            // assertion green, which is the shape of an assertion that cannot fail.
            // The property the caller actually depends on is selectEl.value being the
            // sentinel after a render, and that is what the test asserts.
            selectEl.appendChild( element );
            continue;
        }
        let group = groups.get( option.group );
        if ( !group ) {
            group = selectEl.ownerDocument.createElement( "optgroup" );
            group.label = option.group;
            groups.set( option.group, group );
            selectEl.appendChild( group );
        }
        group.appendChild( element );
    }
    return options.map( ( option ) => option.value );
}

/**
 * Is this select value the Auto-Route sentinel rather than a routing command?
 *
 * Requires:
 *     - payload is the same body the select was rendered from
 *
 * Ensures:
 *     - Returns true for the sentinel, false for any command
 *     - Returns true when NO sentinel was named at all — a missing payload, a body
 *       with no auto_route, or an auto_route carrying no `value` string. A page whose
 *       fetch failed falls back to auto-routing (/api/v2/ask) rather than posting a
 *       bare sentinel to /api/v2/submit as though it were a command
 *     - A sentinel that WAS named but is the empty string is compared, not waved
 *       through: "" is a legitimate option value (it is the conventional HTML
 *       no-selection value), and the equality already answers it correctly — "" is
 *       the sentinel, anything else is a command
 *
 * WHY THE TEST IS `typeof … !== "string"` AND NOT `!autoRoute.value`. The falsy check
 * collapsed two different situations: "there is no sentinel to compare against"
 * (an absent measurement — fail open) and "the sentinel is empty" (a present value —
 * comparable). Under the falsy check a blank sentinel made this return true for
 * EVERY pick, so the command the user chose was silently discarded and everything
 * auto-routed. Nothing errored and nothing looked wrong. The unit guard could not see
 * it either: `assert auto["value"] == AUTO_ROUTE_VALUE` reads the same constant on
 * both sides, so it stayed green with the sentinel blanked (measured 2026-08-23; a
 * truthiness assert now sits beside it in test_v2_agents_endpoint.py).
 *
 * `value` is nullable because the call site's own variable is: notifications.js reads
 * `selectEl ? selectEl.value : null`. The null never arrives — the same expression
 * short-circuits on `!selectEl` first — but the signature describes what the code
 * accepts, and a null compared against a string sentinel is simply not the sentinel.
 *
 * @param {string|null} value
 * @param {AgentsPayload|null|undefined} payload
 * @returns {boolean}
 */
export function isAutoRoute( value, payload ) {
    const autoRoute = payload && payload.auto_route;
    if ( !autoRoute || typeof autoRoute.value !== "string" ) return true;
    return value === autoRoute.value;
}

/**
 * The args to submit alongside a chosen command, given the typed question.
 *
 * Requires:
 *     - payload is the same body the select was rendered from; command is an option
 *       value that is not the sentinel; text is what the user typed
 *
 * Ensures:
 *     - Returns { <the one required arg>: text } when the command needs exactly one
 *       argument — which is what every submit card being retired already does: one
 *       textarea feeding one contract argument
 *     - Returns {} when the command needs none (test suite) or when it needs two or
 *       more, because a single text box cannot honestly fill two named arguments and
 *       guessing which one gets it would be worse than asking. A command with
 *       missing args comes back needs_input, which phase 4 turns into an inline
 *       question; until then it renders in the response pane as it does today
 *     - Returns {} for an unknown command rather than throwing
 *
 * `command` is nullable for the same reason as isAutoRoute's `value`, and an
 * unmatched command already returns {} — the documented unknown-command path.
 *
 * @param {string|null} command
 * @param {string} text
 * @param {AgentsPayload|null|undefined} payload
 * @returns {Record<string, string>}
 */
export function argsForCommand( command, text, payload ) {
    const agents = ( payload && Array.isArray( payload.agents ) ) ? payload.agents : [];
    const agent  = agents.find( ( candidate ) => candidate.command === command );
    if ( !agent || !Array.isArray( agent.required_args ) ) return {};
    if ( agent.required_args.length !== 1 ) return {};
    // The cast states what the `length !== 1` check one line up already guarantees:
    // element 0 exists. `noUncheckedIndexedAccess` types every array read as
    // possibly-undefined and cannot see that check. A runtime guard here would be
    // a new branch no caller can reach — this asserts, it does not defend.
    return { [ /** @type {string} */ ( agent.required_args[ 0 ] ) ]: text };
}

/**
 * Publish this module's surface for the classic-script consumer.
 *
 * notifications.js is a classic script and cannot import, so this global IS the
 * seam — without it the page loads the module and nothing can call it. Read at CALL
 * time there, never at load time, so module execution order cannot matter; the same
 * contract shared/task-list-query.js uses.
 *
 * It is an exported FUNCTION rather than a bare `if ( typeof window ... )` block
 * because a load-time conditional is only reachable in whichever environment the
 * test file happens to import under — measured, the no-window arm ran and the
 * publish itself never did. A named seam is callable from both.
 *
 * Requires:
 *     - target is the global object to publish onto, or null/undefined off-browser
 *
 * Ensures:
 *     - Returns false and writes nothing when there is no target
 *     - Otherwise sets target.LUPIN_AGENT_SELECT to the full surface and returns true
 *
 * @param {(Window & typeof globalThis)|null|undefined} target
 * @returns {boolean}
 */
export function publishOnWindow( target ) {
    if ( !target ) return false;
    target.LUPIN_AGENT_SELECT = {
        AGENTS_ENDPOINT, buildAgentSelectOptions, renderAgentSelect, isAutoRoute, argsForCommand
    };
    return true;
}

// `globalThis.window` and not a `typeof window` ternary: the ternary's browser arm is
// unreachable under the node test harness (the module loads before happy-dom
// registers), so it read as a permanently-uncovered branch. A plain property read is
// undefined off-browser, which publishOnWindow already handles as "nothing to write to".
/* c8 ignore next */ // tsx phantom-branch artifact on a top-level call statement; the line has no branch in source.
publishOnWindow( globalThis.window );
