---
capability: swe-team-roles
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.swe_team.agent_definitions.AgentRole@4ceafe38df
  - cosa.agents.swe_team.agent_definitions.get_agent_roles@de2e1e74ca
  - cosa.agents.swe_team.agent_definitions.get_model_for_role@ac3878b8dd
  - cosa.agents.swe_team.agent_definitions.get_sender_id@557f95340f
---
# SWE team roles and sender ids

Each team role is an `AgentRole`: a name, a description, a system prompt, a tool list, a model tier and an active flag. The orchestrator in [[swe-team-orchestrator]] reads them to build its agents.

## What it does
- `AgentRole.model_tier` is `lead` or `worker`, and `active` defaults to false.
- `get_agent_roles` returns all six roles: lead, architect, coder, reviewer, tester and debugger. The lead's prompt carries the configured failure limit.
- `get_model_for_role` returns `lead_model` for a lead-tier role and `worker_model` for the rest, from the given config or a default one.
- `get_sender_id( role, session_id )` here returns `swe.<role>@lupin.deepily.ai`, with `#<session id>` added when a session id is given.
- The orchestrator passes this sender id to the decision proxy when it evaluates a question.

## Don't
- Don't mix it up with `cosa_interface.get_sender_id`. That one uses the detected project in the domain and cuts a session id at `::`. See [[swe-team-notifications]].
- Don't count on the architect, reviewer or debugger running. They are defined and inactive.
