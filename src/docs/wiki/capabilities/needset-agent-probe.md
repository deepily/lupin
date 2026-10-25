---
capability: needset-agent-probe
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.agent_probe.build_prompt@632c4b41f1
  - lupin_mcp.reuse_needset.agent_probe.rulings@3dadd2ed80
  - lupin_mcp.reuse_needset.agent_probe.read_files@4a2a531283
  - lupin_mcp.reuse_needset.agent_probe.serialize@b640dfb71d
  - lupin_mcp.reuse_needset.agent_probe.reply_text@0494c804df
  - lupin_mcp.reuse_needset.agent_probe.covers@9fdda94e2c
  - lupin_mcp.reuse_needset.agent_probe.probe_profile@9b6af8bc10
  - lupin_mcp.reuse_needset.agent_probe.prompt_version@8684948c6b
  - lupin_mcp.reuse_needset.agent_probe.probe_options@b2970b75d0
  - lupin_mcp.reuse_needset.agent_probe.run_probe@3257a85cf8
---
# Need set: agent probe

The tools-on agent step: it reads each shortlisted candidate and rules it the same job or not. The agent runs under the isolation profile of the model transport with one tool, Read. Its rulings are not made under the operator's instructions, memory or hooks.

## Prompt and reply
- `build_prompt` makes the user prompt from the need sentence and the checker's shortlist: the instruction, the need and one JSON line per candidate. Each line omits the candidate's text, so the agent reads the source. The key, the seed and the drafter's verdict are never in the prompt.
- `rulings` reads lines of the form `RULING id :: ruling`, with the rulings `DUPLICATE`, `EXTEND` or `DISTINCT`. A candidate ruled twice with different rulings is left out, so it reads as unruled.
- `reply_text` returns the text of the last assistant message that holds text, or an empty string.
- `serialize` turns the assistant messages into plain dicts a ledger can hold, one per text block and tool call.

## Reads
- `read_files` lists the Read calls the agent made, each with path, offset and limit. An offset or limit of `None` means the whole file.
- `covers` says whether one Read call shows a symbol's whole definition. An offset starts at line 1, and a call with no limit shows 2000 lines at most.

## Running
- `probe_options` builds options with the Read tool only, the hermetic isolation arguments and no setting source. The working directory is the read-only tree of the need's source commit.
- `probe_profile` returns the text naming the tools and turn limit. `prompt_version` hashes it with the system text, instruction, prompt builder and reply parser, so a change to any is a new version.
- `run_probe` lets the agent read and rule. It returns the reply, rulings, reads and transcript. An unreadable reply is asked again once, and none holding a ruling raises `PROBE_UNREADABLE`.
