---
capability: rest-data-v2-routing
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.v2.registry.AgentSpec@7f4f1c235f
  - cosa.rest.v2.registry.CommandClass@560b644185
  - cosa.rest.v2.registry.canonical_command@c7914231fa
  - cosa.rest.v2.router_client.RouterClient@f984c5f7e0
  - cosa.rest.v2.router_prompt_generator.main@071c6166c6
  - cosa.rest.v2.router_prompt_generator.render_router_prompt@04b3ac4ec2
  - cosa.rest.v2.router_prompt_generator.speakable_commands@f75db967dd
  - cosa.rest.v2.router_prompt_generator.write_router_prompt@008a21239c
  - cosa.rest.v2.request_context.get_bearer_token@1a4522c122
  - cosa.rest.v2.request_context.reset_bearer_token@bcddc9bf7c
  - cosa.rest.v2.request_context.set_bearer_token@00b89a953e
---
# V2 routing

How a v2 request turns a sentence into a command: the command table, the router call, the router's prompt and the caller's token. The flow that uses them is in [[v2-ask-flow]].

## What it does
- `AgentSpec` is one row of the registry: the full routing string, its aliases and the agent factory. It also says whether results are snapshotable and carries the dropdown and spoken labels. It is frozen.
- `CommandClass` labels each row `conversational`, `agentic`, `control` or `none`. The template groups are derived from it.
- `AgentSpec.required_args` is read in this order: the agent's own `declared_args()`, then `JOB_ARG_CONTRACTS`, then the spec's literal tuple.
- `canonical_command( command )` maps an alias such as `math` to its full routing string. An unknown string or `None` comes back unchanged. It never raises.
- `RouterClient( config_mgr )` builds only an `LlmClientFactory`. `route( question )` returns `( command, args )` by calling `get_routing_command`, and `( "unknown", "" )` when the router's XML cannot be parsed. A missing prompt template or an LLM error raises.
- `render_router_prompt` returns the router prompt: fixed text plus one `<command>` line per `speakable` registry row. `write_router_prompt( path=None )` writes it and returns the path. `main` does that to the checked-in file and prints the path and the command count.
- `speakable_commands` returns those commands in the served order, which a fixed tuple sets. Membership comes from the registry.
- `set_bearer_token( token )` stores the caller's JWT for this request and returns a reset handle. `get_bearer_token` reads it, `reset_bearer_token( handle )` undoes it.

## Don't
- Don't edit `agent-router-template-completion.txt` by hand. Regenerate it with `PYTHONPATH=src python -m cosa.rest.v2.router_prompt_generator`.
- Don't pass a token through `AskFlow.submit`. It would widen a signature with many callers, so a context variable carries it.

## Invariants
- `speakable_commands` raises `ValueError` when the served order and the registry's speakable set disagree in either direction.
- `get_bearer_token` returns `None` when nothing set it. `/api/v2/submit` sets it from the Authorization header, calls the flow through `run_in_threadpool`, then resets it. The worker thread sees it because anyio copies the context.
- The generated prompt leaves `{voice_command}` as a literal for the router to fill at serve time.
