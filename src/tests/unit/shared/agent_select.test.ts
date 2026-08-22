// Q&A card agent dropdown — the HTTP→DOM half of gate 3 (2026.08.22 plan §6).
//
// THE GATE THIS FILE CARRIES. Gate 3 as the plan shipped it read: "for each
// `speakable` command, the rendered select contains an option whose value is that
// command." Two defects, both named in Mr. Radio's review: it tested `speakable`
// while the dropdown is governed by `user_initiable` — so a typeable-but-not-sayable
// command could be missing entirely with the gate green — and its falsification was
// a COUNT, which the plan's own warning disqualifies three lines later. Rewritten
// here as a set-equality on the governing field.
//
// WHY IT LIVES HERE AND NOT IN A PYTHON TEST. After phase 3 the static
// notifications.html holds NO options at all, so a set-equality read from the file
// on disk would compare against an empty set and pass forever. The select only
// exists after render, so the gate has to read a rendered one. The Python half
// (test_v2_agents_endpoint.py) proves the ENDPOINT matches the TABLE; this half
// proves the DOM matches the ENDPOINT. Chained, they cover registry→dropdown without
// a 17-minute Playwright run.
//
// Run: npx tsx --test src/tests/unit/shared/agent_select.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import {
  buildAgentSelectOptions,
  renderAgentSelect,
  isAutoRoute,
  argsForCommand,
  publishOnWindow,
  AGENTS_ENDPOINT,
} from "../../../lupin_app/static/js/shared/agent-select.js";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

const SENTINEL = "__auto_route__";

// A payload in the shape GET /api/v2/agents actually returns, carrying one command
// per interesting case: forked conversational, plain conversational, agentic,
// receptionist (cls "none" but pickable), and the three that must NOT render — the
// two expediters and the control command.
function payload() {
  return {
    auto_route: { value: SENTINEL, label: "System (Auto-Route)", description: "Normal LLM-based routing" },
    agents: [
      { command: "agent router go to math", display_name: "Math Agent", label: "math",
        cls: "conversational", description: "Direct math calculations",
        speakable: true, user_initiable: true, aliases: ["math"], required_args: [], arg_questions: {}, job_prefix: null },
      { command: "agent router go to weather", display_name: "Weather", label: "weather",
        cls: "conversational", description: "Weather queries",
        speakable: true, user_initiable: true, aliases: ["weather"], required_args: ["location"],
        arg_questions: { location: "What location?" }, job_prefix: null },
      { command: "agent router go to deep research", display_name: "Deep Research", label: "Deep Research",
        cls: "agentic", description: "Investigate a topic in depth",
        speakable: true, user_initiable: true, aliases: [], required_args: ["query"],
        arg_questions: { query: "What should I research?" }, job_prefix: "dr" },
      { command: "agent router go to test suite", display_name: "Test Suite", label: "Test Suite",
        cls: "agentic", description: "Run integration and E2E tests",
        speakable: true, user_initiable: true, aliases: [], required_args: [], arg_questions: {}, job_prefix: "ts" },
      { command: "agent router go to receptionist", display_name: "Receptionist", label: "receptionist",
        cls: "none", description: "General assistance",
        speakable: true, user_initiable: true, aliases: [], required_args: [], arg_questions: {}, job_prefix: null },
      // NOT user_initiable — a job id produced by a job that already failed.
      { command: "agent router go to bug fix expediter", display_name: "Bug Fix Expediter", label: "Bug Fix Expediter",
        cls: "agentic", description: "Fix a job that died",
        speakable: false, user_initiable: false, aliases: [], required_args: ["dead_job_id"], arg_questions: {}, job_prefix: "bfe" },
      // NOT user_initiable, and SPEAKABLE — the pair that makes the two fields
      // provably different sets, so a render filtering on `speakable` goes red.
      { command: "agent router go to automatic", display_name: "agent router go to automatic",
        label: "agent router go to automatic", cls: "control", description: "Normal LLM-based routing",
        speakable: true, user_initiable: false, aliases: [], required_args: [], arg_questions: {}, job_prefix: null },
    ],
  };
}

function freshSelect(): HTMLSelectElement {
  const select = document.createElement("select");
  select.id = "agent-mode";
  document.body.replaceChildren(select);
  return select;
}

function renderedValues(select: HTMLSelectElement): string[] {
  return Array.from(select.querySelectorAll("option")).map((o) => (o as HTMLOptionElement).value);
}

// ===========================================================================
// GATE 3 (client half) — the rendered set is governed by `user_initiable`
// ===========================================================================

test("gate 3: rendered option values set-equal the payload's user_initiable commands, plus the sentinel", () => {
  const body   = payload();
  const select = freshSelect();
  renderAgentSelect(select, body);

  const rendered = new Set(renderedValues(select));
  const expected = new Set([
    SENTINEL,
    ...body.agents.filter((a) => a.user_initiable).map((a) => a.command),
  ]);
  assert.deepEqual(rendered, expected);
});

test("gate 3: a command that is user_initiable but NOT speakable still renders", () => {
  // The hole the original gate could not see. Nothing in today's registry is in this
  // state, which is exactly why the gate has to be written for it: the first command
  // that is typeable-but-not-sayable would otherwise go missing in silence.
  const body = payload();
  body.agents.push({
    command: "agent router go to typed only", display_name: "Typed Only", label: "typed only",
    cls: "agentic", description: "Typeable, not sayable",
    speakable: false, user_initiable: true, aliases: [], required_args: [], arg_questions: {}, job_prefix: "to",
  });
  const select = freshSelect();
  renderAgentSelect(select, body);
  assert.ok(renderedValues(select).includes("agent router go to typed only"));
});

test("gate 3: a command that is speakable but NOT user_initiable does not render", () => {
  // The other direction, and the one that proves the render is not reading
  // `speakable`: `agent router go to automatic` is speakable and must stay out.
  const select = freshSelect();
  renderAgentSelect(select, payload());
  assert.ok(!renderedValues(select).includes("agent router go to automatic"));
});

test("neither expediter is offered", () => {
  const select = freshSelect();
  renderAgentSelect(select, payload());
  assert.ok(!renderedValues(select).includes("agent router go to bug fix expediter"));
});

test("option values are full routing commands, never short mode keys", () => {
  // The translation layer today's select carries ("math" → a server-side map → the
  // command) is where drift could hide, and it is what makes a set-equality against
  // the registry meaningless. Every value except the sentinel must be a command.
  const select = freshSelect();
  renderAgentSelect(select, payload());
  for (const value of renderedValues(select)) {
    if (value === SENTINEL) continue;
    assert.ok(value.startsWith("agent router go to "), `not a routing command: ${value}`);
  }
});

// ===========================================================================
// The sentinel — blocker fix (b)
// ===========================================================================

test("the Auto-Route sentinel is rendered first, ungrouped, and is what the select reads as", () => {
  // The property the caller depends on is `select.value`, not an option's `selected`
  // flag: submitQA reads the value to choose between /api/v2/ask and /api/v2/submit,
  // so a card that came up defaulted to an agent would silently submit jobs for
  // questions. Asserting `first.selected` instead measured as unfalsifiable — a
  // <select> with nothing marked already reports its first option as selected, so
  // deleting the line that set it left the assertion green.
  const select = freshSelect();
  renderAgentSelect(select, payload());
  const first = select.querySelector("option") as HTMLOptionElement;
  assert.equal(first.value, SENTINEL);
  assert.equal(first.parentElement?.tagName, "SELECT");   // top level, not inside an optgroup
  assert.equal(select.value, SENTINEL);
  assert.equal(isAutoRoute(select.value, payload()), true);
});

test("the sentinel comes from the payload, so the page hand-writes no option", () => {
  // Blocker fix (b): with Auto-Route rendered like every other option there is
  // nothing for the front-end guard to exempt — and an exemption without a written
  // reason is how these guards get quietly widened later.
  const body = payload();
  body.auto_route.value = "__something_else__";
  const select = freshSelect();
  renderAgentSelect(select, body);
  assert.equal((select.querySelector("option") as HTMLOptionElement).value, "__something_else__");
});

// ===========================================================================
// Grouping — including the one stated exception
// ===========================================================================

test("the receptionist renders with the Quick Agents, not under a heading of its own", () => {
  // Rick's ruling 3. Classed `none` because that is how the ROUTER reaches it; a
  // person may still pick it on purpose, so it must not be filed under the failure
  // path it shares a class with.
  const select = freshSelect();
  renderAgentSelect(select, payload());
  const option = Array.from(select.querySelectorAll("option"))
    .find((o) => (o as HTMLOptionElement).value === "agent router go to receptionist") as HTMLOptionElement;
  assert.equal((option.parentElement as HTMLOptGroupElement).label, "Quick Agents");
});

test("conversational and agentic commands land under their own headings", () => {
  const select = freshSelect();
  renderAgentSelect(select, payload());
  const groupOf = (command: string) => {
    const option = Array.from(select.querySelectorAll("option"))
      .find((o) => (o as HTMLOptionElement).value === command) as HTMLOptionElement;
    return (option.parentElement as HTMLOptGroupElement).label;
  };
  assert.equal(groupOf("agent router go to math"), "Quick Agents");
  assert.equal(groupOf("agent router go to deep research"), "Agentic Processes");
});

test("an unknown class falls back to the class name rather than dropping the option", () => {
  // A new CommandClass must never make an agent vanish from the dropdown in silence;
  // an unlabelled group is visible, a missing agent is not.
  const body = payload();
  body.agents.push({
    command: "agent router go to novel", display_name: "Novel", label: "novel",
    cls: "brand_new_class", description: "", speakable: false, user_initiable: true,
    aliases: [], required_args: [], arg_questions: {}, job_prefix: null,
  });
  const select = freshSelect();
  renderAgentSelect(select, body);
  const option = Array.from(select.querySelectorAll("option"))
    .find((o) => (o as HTMLOptionElement).value === "agent router go to novel") as HTMLOptionElement;
  assert.equal((option.parentElement as HTMLOptGroupElement).label, "brand_new_class");
});

// ===========================================================================
// Option text and help
// ===========================================================================

test("option text is display_name, never the spoken label", () => {
  // The regression Mr Radio caught: rendering `label` turns "Math Agent" into "math".
  const select = freshSelect();
  renderAgentSelect(select, payload());
  const option = Array.from(select.querySelectorAll("option"))
    .find((o) => (o as HTMLOptionElement).value === "agent router go to math") as HTMLOptionElement;
  assert.equal(option.textContent, "Math Agent");
});

test("the description rides along as the option's title", () => {
  const select = freshSelect();
  renderAgentSelect(select, payload());
  const option = Array.from(select.querySelectorAll("option"))
    .find((o) => (o as HTMLOptionElement).value === "agent router go to deep research") as HTMLOptionElement;
  assert.equal(option.title, "Investigate a topic in depth");
});

test("an option with no description carries no title attribute", () => {
  const body = payload();
  body.agents[0].description = "";
  const select = freshSelect();
  renderAgentSelect(select, body);
  const option = select.querySelector("optgroup option") as HTMLOptionElement;
  assert.equal(option.hasAttribute("title"), false);
});

// ===========================================================================
// Re-render and failure
// ===========================================================================

test("rendering twice does not double the list", () => {
  const select = freshSelect();
  renderAgentSelect(select, payload());
  const first = renderedValues(select);
  renderAgentSelect(select, payload());
  assert.deepEqual(renderedValues(select), first);
});

test("rendering over a hand-written select removes what was there", () => {
  // The migration case: the page ships with an empty select, but a stale cached
  // notifications.html would not. Leaving old options behind would put short mode
  // keys back in the dropdown, which /api/v2/submit cannot route.
  const select = freshSelect();
  const stale  = document.createElement("option");
  stale.value  = "math";
  select.appendChild(stale);
  renderAgentSelect(select, payload());
  assert.ok(!renderedValues(select).includes("math"));
});

test("a failed fetch leaves the select EMPTY, not shortened", () => {
  // The failure that matters is a MISSING agent, and a shortened list looks exactly
  // like a working one. Empty is a failure a user can see.
  const select = freshSelect();
  assert.deepEqual(renderAgentSelect(select, null), []);
  assert.equal(select.children.length, 0);
});

test("a payload with no auto_route renders nothing at all", () => {
  const select = freshSelect();
  assert.deepEqual(renderAgentSelect(select, { agents: payload().agents } as never), []);
  assert.equal(select.children.length, 0);
});

test("a payload whose agents field is not a list still renders the sentinel", () => {
  const select = freshSelect();
  const values = renderAgentSelect(select, { auto_route: payload().auto_route, agents: null } as never);
  assert.deepEqual(values, [SENTINEL]);
});

test("buildAgentSelectOptions returns the sentinel first with a null group", () => {
  const options = buildAgentSelectOptions(payload());
  assert.equal(options[0].value, SENTINEL);
  assert.equal(options[0].group, null);
});

// ===========================================================================
// isAutoRoute — which door a submission goes through
// ===========================================================================

test("the sentinel routes to ask; a command does not", () => {
  const body = payload();
  assert.equal(isAutoRoute(SENTINEL, body), true);
  assert.equal(isAutoRoute("agent router go to math", body), false);
});

test("a BLANK sentinel does not silently auto-route every chosen agent", () => {
  // Clayton's catch, 2026-08-22. isAutoRoute treats a falsy sentinel as "nothing to
  // compare against" and answers true, so a blank value would send every named agent
  // to /api/v2/ask as though nobody had picked one. The render already refuses to
  // build options from a blank sentinel, so the system fails CLOSED (an empty
  // dropdown, visible) rather than open — this pins that pairing so a later change to
  // either half cannot quietly open it.
  const body = payload();
  body.auto_route.value = "";
  assert.deepEqual(buildAgentSelectOptions(body), [], "a blank sentinel must render nothing");
  const select = freshSelect();
  assert.deepEqual(renderAgentSelect(select, body), []);
  assert.equal(select.children.length, 0);
});

test("a missing payload falls back to auto-routing", () => {
  // If the fetch failed there is no sentinel to compare against, and posting an
  // unrecognised value to /api/v2/submit as though it were a command is worse than
  // routing the question normally.
  assert.equal(isAutoRoute("anything", null), true);
  assert.equal(isAutoRoute("anything", { agents: [] } as never), true);
});

// ===========================================================================
// argsForCommand — the typed text becomes the command's one argument
// ===========================================================================

test("a command with exactly one required arg receives the typed text", () => {
  // Which is what every submit card being retired already does: one textarea
  // feeding one contract argument.
  assert.deepEqual(
    argsForCommand("agent router go to deep research", "octopus cognition", payload()),
    { query: "octopus cognition" },
  );
  assert.deepEqual(
    argsForCommand("agent router go to weather", "Boston", payload()),
    { location: "Boston" },
  );
});

test("a command with no required args receives none", () => {
  assert.deepEqual(argsForCommand("agent router go to test suite", "go", payload()), {});
});

test("a command needing two or more args receives none, and will come back needs_input", () => {
  // A single text box cannot honestly fill two named arguments, and guessing which
  // one gets it is worse than asking. Nothing in today's registry needs two, which
  // is why this is written against a synthetic entry rather than left untested.
  const body = payload();
  body.agents.push({
    command: "agent router go to two args", display_name: "Two Args", label: "two args",
    cls: "agentic", description: "", speakable: false, user_initiable: true,
    aliases: [], required_args: ["a", "b"], arg_questions: {}, job_prefix: "ta",
  });
  assert.deepEqual(argsForCommand("agent router go to two args", "text", body), {});
});

test("an unknown command yields no args rather than throwing", () => {
  assert.deepEqual(argsForCommand("agent router go to nowhere", "text", payload()), {});
  assert.deepEqual(argsForCommand("agent router go to math", "text", null), {});
});

test("a command whose required_args is malformed yields no args", () => {
  const body = payload();
  (body.agents[0] as { required_args: unknown }).required_args = "not a list";
  assert.deepEqual(argsForCommand("agent router go to math", "text", body), {});
});

test("the endpoint path is exported so no caller retypes it", () => {
  assert.equal(AGENTS_ENDPOINT, "/api/v2/agents");
});

// ===========================================================================
// The window publish — how the classic script reaches this module at all
// ===========================================================================

test("publishOnWindow puts the full surface on the target", () => {
  // The seam the page depends on. A publish that quietly dropped one export would
  // fail at the call site in a browser and nowhere else.
  const target: Record<string, Record<string, unknown>> = {};
  assert.equal(publishOnWindow(target), true);
  const published = target.LUPIN_AGENT_SELECT;
  assert.equal(published.AGENTS_ENDPOINT, "/api/v2/agents");
  for (const name of ["buildAgentSelectOptions", "renderAgentSelect", "isAutoRoute", "argsForCommand"]) {
    assert.equal(typeof published[name], "function", `window publish is missing ${name}`);
  }
});

test("publishOnWindow writes nothing when there is no global to write to", () => {
  // The module is imported by this test file under node with no window, and by the
  // page with one. Off-browser it must not throw and must not invent a global.
  assert.equal(publishOnWindow(null), false);
  assert.equal(publishOnWindow(undefined), false);
});
