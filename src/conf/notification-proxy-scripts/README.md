# Notification Proxy Q&A Scripts

## Purpose

Q&A scripts define the scripted answers that the Notification Proxy Agent returns when auto-answering expediter questions during automated testing. Instead of brittle keyword matching, the proxy uses local Phi-4 LLM inference to fuzzy-match incoming questions to script entries.

## How It Works

1. The proxy loads a Q&A script at startup based on the `--profile` flag
2. When a notification arrives, the proxy sends the question + script entries to Phi-4
3. Phi-4 fuzzy-matches the question to the best script entry using semantic similarity
4. The scripted answer from the matched entry is returned as the response

## JSON Format

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `profile_name` | string | Profile identifier (matches `--profile` CLI flag) |
| `description` | string | Human-readable description of this script |
| `entries` | array | List of question-answer pairs |

### Entry Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `question_pattern` | string | Yes | The question text to match against (semantic, not exact) |
| `answer` | string | Yes | The scripted answer to return when matched |
| `arg_name` | string | Yes | The CLI argument name this answers |
| `response_types` | array | Yes | Which response types this entry applies to: `open_ended`, `open_ended_batch`, `multiple_choice`, `yes_no` |
| `agents` | array | No | Agent names this entry applies to (for multi-agent scripts only) |

## Profile-to-Script Mapping

The `--profile` flag maps to script files by replacing underscores with dashes:

```
--profile deep_research       →  deep-research.json
--profile podcast             →  podcast.json
--profile research_to_podcast →  research-to-podcast.json
--profile all_agents          →  all-agents.json
--profile minimal             →  minimal.json
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

Add your profile to the `--profile` choices in `__main__.py` and add a matching
entry in `config.py` `TEST_PROFILES` (for backward compatibility with the rules strategy).

## Multi-Agent Scripts

For testing multiple agents in a single run (e.g., the 13-scenario smoke test), use `all-agents.json`. Entries can be scoped to specific agents using the `agents` tag:

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
| `_template.json` | Copy-and-modify starter template |
