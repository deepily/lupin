---
capability: podcast-prompts
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.podcast_generator.prompts.personality.create_personality_from_description@2440f72cf7
  - cosa.agents.podcast_generator.prompts.personality.get_dynamic_duo_description@4593091a9d
  - cosa.agents.podcast_generator.prompts.personality.get_personality_prompt_section@8306cbfff7
  - cosa.agents.podcast_generator.prompts.personality.get_prosody_guidelines@8f571b6fc5
  - cosa.agents.podcast_generator.prompts.script_generation.extract_prosody_from_text@2c2718cd53
  - cosa.agents.podcast_generator.prompts.script_generation.get_content_analysis_prompt@d514cf537a
  - cosa.agents.podcast_generator.prompts.script_generation.get_script_generation_prompt@bec05bfe8a
  - cosa.agents.podcast_generator.prompts.script_generation.get_script_revision_prompt@727242410f
  - cosa.agents.podcast_generator.prompts.script_generation.parse_analysis_response@224e303f42
  - cosa.agents.podcast_generator.prompts.script_generation.parse_script_response@5e9fd06d72
---
# Podcast prompt builders

The functions in `prompts/personality.py` and `prompts/script_generation.py` build the text sent to the model in [[podcast-generation]], and parse what comes back. They send nothing themselves.

## What it does
- `get_content_analysis_prompt` builds the analysis request. It clips the research to `max_source_chars` when given, and adds audience guidelines and context.
- `get_script_generation_prompt` builds the script request from the analysis, the two host profiles, a target duration and an exchange range. For a language other than `en` it adds a native-writing instruction that keeps pacing markers and host names unchanged.
- `get_script_revision_prompt` embeds the current script, the user's feedback and the revision number, and asks for the same JSON format back.
- `parse_analysis_response` recovers a JSON object leniently. When none is found it returns a default analysis with the topic "Unknown Topic".
- `parse_script_response` returns the recovered object with `segments` and `title` filled in when missing. It raises `ValueError` when no JSON object can be recovered, so an empty script never reaches approval.
- `extract_prosody_from_text` returns the text with `*[note]*` markers removed and spaces collapsed, plus the lowercased notes.
- `get_personality_prompt_section` renders one host's profile with the curious or expert behaviour block and up to five example phrases. `get_dynamic_duo_description` joins both hosts with an interaction-dynamics block.
- `create_personality_from_description` picks tone, expertise and curiosity from keywords in a free-text description.
- `get_prosody_guidelines` returns the marker guide: `<break time="x.xs"/>` pauses, ellipsis, dash and capitalised emphasis. It says bracketed emotion tags are ignored.

## Don't
- Don't rely on `create_personality_from_description` to understand text: it only looks for keywords such as "enthusiastic" or "professor".
