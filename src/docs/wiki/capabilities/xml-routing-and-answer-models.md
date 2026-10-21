---
capability: xml-routing-and-answer-models
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.io_models.xml_models.AgentRouterResponse@d877a4236e
  - cosa.agents.io_models.xml_models.CommandResponse@891bd933b9
  - cosa.agents.io_models.xml_models.VoxCommandResponse@c4b099ca6a
  - cosa.agents.io_models.xml_models.YesNoResponse@c09f5a4447
  - cosa.agents.io_models.xml_models.ConfirmationResponse@9f8605b83e
  - cosa.agents.io_models.xml_models.QualifierClassification@c8abb4d2ce
  - cosa.agents.io_models.xml_models.SimpleResponse@0bed142066
  - cosa.agents.io_models.xml_models.GistResponse@163e7606ff
  - cosa.agents.io_models.xml_models.FuzzyFileMatchResponse@b416b307a3
  - cosa.agents.io_models.xml_models.TFEResumeMatchResponse@072983bbca
  - cosa.agents.io_models.utils.fuzzy_file_prefilter.dominant_keyword_match@19ac08064f
---
# XML routing and answer models

These are the small response shapes a model fills in for routing, yes or no answers, summaries and file matching. Each is a Pydantic model read from XML. The larger code-generation shapes are in [[xml-agent-response-models]].

## What it does
- `AgentRouterResponse` and `VoxCommandResponse` each hold a `command` and its `args`. `CommandResponse` has the same two fields for older templates.
- The command validators accept any string. An unknown command is not rejected, and the router response strips whitespace.
- `YesNoResponse` holds an `answer`, lowercased on read. `is_yes` is true for yes, y and true.
- `ConfirmationResponse` holds one `decision` field for yes, no or ambiguous.
- `QualifierClassification` holds an `intent`, a `confidence` and the `reasoning`. `is_question` is true for the intent `question`. A `None` field becomes an empty string.
- `SimpleResponse` holds one dynamically named string field. `create` builds one and `get_content` returns the first string field.
- `GistResponse` holds the `gist` text of a summary.
- `FuzzyFileMatchResponse` holds a comma-separated `matches` string, and `get_matches_list`, from `CommaListMixin` ([[xml-model-mixins]]), returns trimmed, non-empty names.
- `TFEResumeMatchResponse` has the same shape for job ids ranked by relevance. An empty string means no match.
- `dominant_keyword_match` returns the one path whose keyword overlap with a description strictly beats the rest. A tie or no overlap returns `None`.

## Don't
- Don't rely on these models to reject an unknown command. Check it where it is used.
