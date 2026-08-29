# Notification Proxy Q&A Scripts

## Purpose

Q&A scripts define the scripted answers that the Notification Proxy Agent returns when auto-answering expediter questions during automated testing. Instead of brittle keyword matching, the proxy uses local Phi-4 LLM inference to fuzzy-match incoming questions to script entries.

## How It Works

1. The proxy loads a Q&A script at startup based on the `--profile` flag
2. When a notification arrives, the proxy sends the question + script entries to Phi-4
3. Phi-4 fuzzy-matches the question to the best script entry using semantic similarity
4. The scripted answer from the matched entry is returned as the response

## Script Architecture

There are two types of Q&A script files:

### Standalone Scripts (one per agent)

Each agent/service gets its own JSON file with its specific question-answer pairs:

- `deep-research.json` — deep research agent only
- `podcast.json` — podcast generator only
- `research-to-podcast.json` — chained research + podcast workflow

**When adding a new agent, always create a standalone file first.** Copy `_template.json` and fill in your agent's entries.

### Union Script (for combined testing)

`all-agents.json` combines entries from multiple agents into a single file for running multi-agent test suites in one proxy session. It uses the `"agents"` field to scope entries.

**Do NOT add new agent entries directly to `all-agents.json`.** Create a standalone file first, then optionally duplicate entries into the union script for combined testing.

## JSON Format

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `profile_name` | string | Profile identifier (matches `--profile` CLI flag) |
| `description` | string | Human-readable description of this script |
| `sender_ids` | array | List of sender ID prefixes this script handles (without `#suffix`) |
| `entries` | array | List of question-answer pairs |

### Sender ID Filtering

The `sender_ids` field declares which notification senders this script can respond to. Each entry is a sender ID prefix — the proxy strips any `#session` suffix before matching.

```json
"sender_ids": [ "arg.expeditor@lupin.deepily.ai" ]
```

To handle notifications from multiple senders, add more entries:

```json
"sender_ids": [
    "arg.expeditor@lupin.deepily.ai",
    "workflow.orchestrator@lupin.deepily.ai"
]
```

If the field is missing from a script file, the proxy falls back to the default sender: `arg.expeditor@lupin.deepily.ai`. Adding a new sender requires only a JSON edit — no Python code changes.

### Entry Fields

An entry is keyed on ONE of two things, and which one decides what else it needs.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `question_pattern` | string | Prose entries | The question text to match against (semantic, not exact) |
| `card_id` | string | Card entries | The id the card names itself by. Matched EXACTLY, before the model is asked anything |
| `answer` | string | Yes | The scripted answer to return when matched |
| `arg_name` | string | Prose entries | The CLI argument name this answers |
| `response_types` | array | Yes | Which response types this entry applies to: `open_ended`, `open_ended_batch`, `multiple_choice`, `yes_no` |
| `agents` | array | No | Agent names this entry applies to (for multi-agent scripts only) |

### Prose entries vs card entries

A **prose entry** matches on `question_pattern` and names the argument it fills. The
match is semantic, done by the model.

A **card entry** matches on `card_id`. Some cards are shown by many agents and phrase
their question in the calling agent's own terms — the document choice card asks "…for
the podcast" or "…for the presentation" depending on who is asking. Keying those on
prose meant one byte-identical entry per agent, and a wording change in the code left
every card unanswered with no error anywhere. A card entry carries no
`question_pattern` and no `arg_name`: the id says which card, and the answer says what
to do. The id is compared exactly and claims the entry before any model call, so
nothing about it is fuzzy.

⚠️ **Profiles do not inherit.** Each profile file still needs its own copy of the
entry — a new agent copies the generic entry VERBATIM into its profile. What the id
buys is that the copy is identical rather than re-derived: no per-agent question to
keep in step with the code, and nothing to get wrong except forgetting it, which
`test_file_arg_card_contract.py` fails on.

The document choice card's id is `document_choice`, defined as
`DOCUMENT_CHOICE_CARD_ID` in `cosa/agents/runtime_argument_expeditor/expeditor.py`.

### Positional answers (sentinels)

Some cards cannot be answered with a fixed string, because their option labels are
discovered while the run is in flight — the document choice card offers whatever
filenames matched, and TFE's proposal gate offers whatever fixes it proposed. A
**sentinel** names a POSITION instead of a value, and
`cosa/agents/notification_proxy/option_sentinels.py` turns it into real labels using
the options that arrive with the notification.

| Sentinel | Means | Submits |
|---|---|---|
| `__first_option__` | the first selectable option | that option's label |
| `__last_option__` | the last selectable option | that option's label |
| `__all__` | every selectable option (multi-select cards) | `{"answers": {"<header>": [labels…]}}` |

The Describe and Cancel escapes are never selectable by any of them — picking Cancel
would read as the user declining, a run that looks answered and did nothing.

**The match is exact and case-sensitive.** A value that merely LOOKS like a sentinel —
`__frist_option__`, `__FIRST_OPTION__` — is refused rather than forwarded as a literal,
because forwarding it reaches the card as a label it never offered.

⚠️ **`__all__` submits a JSON envelope, not a joined string, and that is load-bearing.**
A multi-select card's reader looks the answer up under the question's own `header`; a
non-JSON value is wrapped under the header `"response"` instead, so the real header
reads as ABSENT and the agent concludes the user selected nothing. Silent, and
indistinguishable from a human declining. `__all__` is refused (a visible skip) on a
card with more than one question or a question with no header, because there is then no
unambiguous key to answer under.

## Profile-to-Script Mapping

The `--profile` flag maps to script files by replacing underscores with dashes:

```
--profile deep_research       →  deep-research.json
--profile podcast             →  podcast.json
--profile research_to_podcast →  research-to-podcast.json
--profile all_agents          →  all-agents.json
--profile minimal             →  minimal.json
--profile expeditor_smoke    →  expeditor-smoke.json
```

## Creating a New Script

### Step 1: Find Your Agent's Questions

Look up your agent in the agent registry:

```python
# src/cosa/agents/runtime_argument_expeditor/agent_registry.py
AGENTIC_AGENTS = {
    "agent router go to <your agent>": {
        "fallback_questions": {
            "arg_name": "Question text that will be asked...",
            ...
        }
    }
}
```

### Step 2: Copy the Template

```bash
cp _template.json your-agent.json
```

### Step 3: Fill In Entries

For each `fallback_questions` entry in the registry, create a script entry:
- `question_pattern`: Copy the question text from the registry
- `answer`: The value you want the proxy to return during testing
- `arg_name`: The argument name (key from `fallback_questions`)
- `response_types`: Usually `["open_ended", "open_ended_batch"]`

### Step 4: Add Confirmation Entry

Always include a yes/no confirmation entry:

```json
{
    "question_pattern": "Would you like to proceed with these settings?",
    "answer": "yes",
    "arg_name": "confirmation",
    "response_types": ["yes_no"]
}
```

### Step 5: Register the Profile

Add your profile to `TEST_PROFILES` in `config.py`. This is required for:
- CLI validation (`--profile` flag uses `choices = list( TEST_PROFILES.keys() )`)
- Startup banner display
- Rules strategy backward compatibility

You do **not** need to edit `__main__.py` — profile choices are auto-derived
from `TEST_PROFILES.keys()`.

## Multi-Agent Scripts

> **Note**: Always create a standalone script for your agent first (see "Creating a
> New Script"). Only add entries to `all-agents.json` after your standalone script is
> working — and only if you need combined multi-agent testing.

For testing multiple agents in a single run, use `all-agents.json`. Entries can be scoped to specific agents using the `agents` tag:

```json
{
    "question_pattern": "What topic?",
    "answer": "quantum computing",
    "agents": ["deep_research", "research_to_podcast"]
}
```

Entries without an `agents` tag are universal and apply to any agent.

The proxy extracts the agent name from the notification's `abstract` field and filters script entries accordingly.

## Matching Behavior

- **Semantic matching**: Questions do NOT need to match exactly. Phi-4 understands paraphrasing.
- **Confidence threshold**: The LLM returns a confidence score; low-confidence matches may be rejected.
- **Fallback**: If no script entry matches, the proxy falls through to the next strategy in the chain.

## Files

| File | Description |
|------|-------------|
| `deep-research.json` | Deep research agent (query, budget, audience) |
| `podcast.json` | Podcast generator (research doc, languages, audience) |
| `research-to-podcast.json` | Chained workflow (query, budget, audience, languages) |
| `all-agents.json` | Union script for multi-agent testing |
| `minimal.json` | Bare minimum — required args only |
| `expeditor-smoke.json` | Dedicated script for 13-scenario expeditor smoke test |
| `_template.json` | Copy-and-modify starter template |
