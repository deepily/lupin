---
capability: notification-proxy-model-answers
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.notification_proxy.xml_models.BatchScriptMatcherResponse@9a3839a310
  - cosa.agents.notification_proxy.xml_models.ScriptMatcherResponse@78aa83812f
  - cosa.agents.notification_proxy.xml_models.VerificationResponse@8f8fc5a1d8
  - cosa.agents.notification_proxy.verification.LlmAnswerVerifier@829b30f0e2
  - cosa.agents.notification_proxy.verification.NoReplyVerification@0406d731f6
  - cosa.agents.notification_proxy.strategies.llm_fallback.LLMFallbackStrategy@863d4c0152
  - cosa.agents.notification_proxy.strategies.llm_script_matcher.resolve_script_path@8d143f4375
  - cosa.agents.notification_proxy.strategies.llm_script_matcher.strip_surrounding_quotes@2f2b54575d
  - cosa.agents.io_models.utils.number_fields.float_or_zero@94843d2cd3
  - cosa.agents.io_models.utils.number_fields.clamp_unit@0373d177ff
  - cosa.agents.llm_client_init.init_llm_client@a8ac2aa59f
---
# Notification proxy model answers

The proxy asks a language model for an answer in three places: the script matcher, the cloud fallback and the answer verifier. These are the response shapes and the helpers around them. The strategies are in [[notification-proxy]].

## Matcher responses
- `ScriptMatcherResponse` has `matched_entry`, `answer`, `confidence` and `reasoning`. `is_match` is true when the entry is not `none` and the answer is not blank.
- `get_confidence_float` clamps the confidence to 0 to 1 and gives 0.0 when it cannot parse it.
- `BatchScriptMatcherResponse` holds a list of entries, each with a header, a matched index and an answer. `get_answers_dict` maps header to answer and skips entries without a header.
- Its validator accepts one entry or many from the XML parser. `is_match` is true when any entry has a non-blank answer.
- `strip_surrounding_quotes` removes one pair of double quotes that wraps the whole answer, unless that would leave nothing or a quote sits inside.
- `resolve_script_path` maps a profile name to `src/conf/notification-proxy-scripts/<name with dashes>.json`.

## Cloud fallback
- `LLMFallbackStrategy` builds one prompt from the title, question, abstract and response type, and sends it to the Anthropic SDK. It returns the trimmed text, or `None` on an error or an empty reply.

## Answer verifier
- `VerificationResponse` holds `match` (`true` or `false`), a confidence and a reason. `is_match` is true only for `true`.
- `LlmAnswerVerifier.verify` returns a perfect match for two answers equal after trimming and lowercasing, with no model call.
- Otherwise it asks the model up to 3 times, with 0.5 and 1.0 second pauses. A final failure returns `false` with confidence 0.0.
- `NoReplyVerification` marks the case where all 3 replies were empty. It is a `VerificationResponse`, so callers read it the same way.
- In `src`, only tests call the verifier.
