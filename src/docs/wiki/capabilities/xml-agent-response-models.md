---
capability: xml-agent-response-models
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.io_models.xml_models.ReceptionistResponse@dec4fce75e
  - cosa.agents.io_models.xml_models.CalendarResponse@8943198010
  - cosa.agents.io_models.xml_models.BrainstormIdeas@82a38763f8
  - cosa.agents.io_models.xml_models.CodeBrainstormResponse@e1f829911b
  - cosa.agents.io_models.xml_models.WeatherResponse@51e7acac7f
  - cosa.agents.io_models.xml_models.FormatterResponse@7f46e81cbd
  - cosa.agents.io_models.utils.util_xml_pydantic.XMLUtilities@a7e3a8d119
  - cosa.agents.io_models.utils.util_xml_pydantic.remove_xml_escapes@b037863946
  - cosa.agents.io_models.utils.xml_parser_factory.PydanticXmlParser@37fe447a10
  - cosa.agents.io_models.utils.xml_parser_factory.XmlParserFactory@e311f43a65
---
# XML agent response models and parser

These models hold what the agents and their formatters return, and the parser that picks the right model for a routing command. The routing shapes are in [[xml-routing-and-answer-models]].

## What it does
- `ReceptionistResponse` holds `thoughts`, a `category` and an `answer`. The category is `benign`, `humorous` or `salacious`, and `is_safe_content` is false only for the last.
- `BrainstormIdeas` holds three non-empty ideas.
- `CodeBrainstormResponse` holds thoughts, brainstorm ideas, an evaluation, code lines, a return type, an example and an explanation. It is used by the math and date-time agents.
- `CodeBrainstormResponse` rejects an empty code list. `has_imports` and `get_function_name` read the code lines. The code-line handling comes from `CodeLinesMixin` ([[xml-model-mixins]]).
- `CalendarResponse` extends the code response with the original `question`, which must not be blank.
- `FormatterResponse` holds one `rephrased-answer`. Every agent formatter uses it. `WeatherResponse` is the older weather-only form.
- `PydanticXmlParser` maps a routing command to a model class and returns the parsed fields as a dict. An unmapped command raises `ValueError`.
- `XmlParserFactory.parse_agent_response` is the entry point. It wraps one cached `PydanticXmlParser`, and only Pydantic parsing remains.
- `XMLUtilities` checks that XML parses and has the required tags, and compares a parsed value to a baseline string.
- `remove_xml_escapes` turns `&gt;`, `&lt;` and `&amp;` back into characters.

## Invariants
- Parsing errors propagate. The parser does not fall back to another strategy.
