---
capability: xml-io-models
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.agents.io_models.utils.util_xml_pydantic.BaseXMLModel@887c5745e8
  - cosa.agents.io_models.utils.util_xml_pydantic.BaseXMLModel.from_xml@ca0234c9fa
  - cosa.agents.io_models.utils.util_xml_pydantic.XMLParsingError@ee5156e1fc
  - cosa.agents.io_models.utils.xml_parser_factory.XmlParserFactory.parse_agent_response@254bd01546
  - cosa.agents.io_models.utils.xml_parser_factory.PydanticXmlParser.parse_xml_response@e49c7ce400
  - cosa.agents.io_models.utils.prompt_template_processor.PromptTemplateProcessor@01f5a736f5
  - cosa.agents.io_models.xml_models.CodeResponse@7e3c5c85e9
  - cosa.agents.io_models.utils.json_object_recovery.recover_json_object@a4f876bc5e
  - cosa.agents.io_models.utils.json_object_recovery.extract_json_object@d7acf5ea59
  - cosa.agents.io_models.utils.fuzzy_file_prefilter.prefilter_docs_map_by_keywords@ea791b6269
---
# XML models and JSON recovery

Agents ask a model for XML, and `BaseXMLModel` subclasses turn the reply into validated fields. The JSON helper does the same job for the generators that ask for JSON.

## What it does
- `BaseXMLModel.from_xml( text )` parses, `to_xml()` writes (it leaves out `None` fields). The shared models are in `io_models/xml_models.py`. Nine other packages keep their own `xml_models.py` (calculator, decision_proxy, dm_compression, dm_quality_judge (also `xml_models_v2.py`), dm_tutor, notification_proxy, prediction_engine, runtime_argument_expeditor, crud_for_dataframes), and `lupin_mcp/commons_xml_models.py` is one more.
- `XmlParserFactory.parse_agent_response( xml, routing_command, tag_names )` is the entry point. `PydanticXmlParser` maps a routing command such as `agent router go to math` to a model class and returns `model_dump()` (fields use underscores, `rephrased_answer` for `<rephrased-answer>`).
- `PromptTemplateProcessor` fills the XML example in a prompt from each model's `get_example_for_template()`, from its own command-to-model map.
- `recover_json_object( text )` pulls a JSON value out of a chatty reply. The podcast generator raises when it returns `None`; the presentation generator's four callers do the same.
- `prefilter_docs_map_by_keywords` narrows a path map to the best 50 before an LLM picks a file. Its one production caller is the runtime-argument expeditor; the podcast router function its docstring names, `match_research_docs`, is defined nowhere in `src`.

## Invariants
- `from_xml` cuts text before `<?xml`, or else before `<response>`, `<result>` or `<output>` (tried in that order), and, trying `</response>`, `</result>`, `</output>` in that order, after the first occurrence of the first one present anywhere in the text (not the earliest closing tag). It escapes a bare `&`, keeps whitespace so code indentation survives, and raises `XMLParsingError` for bad XML and for validation failures alike.
- `PydanticXmlParser.parse_xml_response` (reached through `XmlParserFactory.parse_agent_response`, not `from_xml`) raises `ValueError` for a routing command with no entry in its model map; there is no default model.
- `recover_json_object` never raises: it returns `None` after logging the raw body at ERROR. If the text starts with a code fence it drops that line, and it cuts at the last triple-backtick it finds (`rfind`), whichever fence that is. It then tries the whole text, and only then the last balanced `{...}`.
- It repairs only unescaped `\n`, `\r` and `\t` inside strings; any other control character or structural error stays a failure.

## How to extend
- Subclass `BaseXMLModel`, add it to `PydanticXmlParser.agent_model_map` and to `PromptTemplateProcessor.MODEL_MAPPING`; they are two separate maps.

## Don't
- Don't treat `None` from `recover_json_object` as an empty result; the caller must decide to fail.
- Don't assume Deep Research uses this helper: it keeps its own `extract_json_object`, which returns a `dict`, where the shared one returns the substring.
