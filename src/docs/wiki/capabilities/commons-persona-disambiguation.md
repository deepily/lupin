---
capability: commons-persona-disambiguation
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.commons_xml_models.PersonaInfo@046381c0cd
  - lupin_mcp.commons_xml_models.PersonaDisambiguationRequest@481d1de3ef
  - lupin_mcp.commons_xml_models.PersonaDisambiguationResponse@a5599879bc
  - lupin_mcp.commons_llm_disambiguator.CommonsLlmDisambiguator@cfec7d542f
  - lupin_mcp.commons_persona_matcher.configure_llm_disambiguator@a875952935
  - lupin_mcp.commons_persona_matcher.disambiguate_via_llm@c7fc1ae5d3
---
# Commons persona disambiguation

When a typed or spoken persona name matches no one mechanically, the commons asks an LLM which active persona is meant ([[voice-persona-allocation]]).

## Request and response
- `PersonaInfo` is one active persona: a name up to 64 characters and an icon up to 8. Both come from server configuration, so they are not sanitised.
- `PersonaDisambiguationRequest` holds a non-empty persona list, an `ambiguous_reference` up to 256 characters and an optional `context` up to 2,048. The two user-controlled fields are rejected for control characters and XML-escaped.
- Its `to_xml` writes the nested `<persona>` shape the model expects, and omits the context block when there is none.
- `PersonaDisambiguationResponse` holds a `matched_persona`, None when empty, and a `confidence` from 0.0 to 1.0. An out-of-range confidence raises before any logic acts on it.

## The disambiguator
- `CommonsLlmDisambiguator.disambiguate` asks the model named by `llm spec key for commons persona disambiguator`, with a timeout and a confidence floor read from the INI keys. The default floor is 0.7.
- It returns a persona name only if it is in the active list and confident enough. A validation error, timeout, parse error or the stubbed fallback returns None.
- `commons llm disambiguator log decisions` switches on a printed record of each decision, for tuning the floor.
- `configure_llm_disambiguator` installs the single disambiguator at startup, or clears it with None. `disambiguate_via_llm` calls it, and returns None with no call when none is installed.
