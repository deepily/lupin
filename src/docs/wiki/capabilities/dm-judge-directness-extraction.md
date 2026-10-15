---
capability: dm-judge-directness-extraction
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.dm_quality_judge.xml_models_v2.DmDirectnessExtraction@70f07cf59b
  - cosa.agents.dm_quality_judge.xml_models_v2.ExtractionError@59af7dd17b
  - cosa.agents.dm_quality_judge.xml_models_v2.code_weight@5f1d71eddc
  - cosa.agents.dm_quality_judge.xml_models_v2.directness_weight@5c3b13d396
  - cosa.agents.dm_quality_judge.xml_models_v2.number_sentences@e3f560627a
  - cosa.agents.dm_quality_judge.xml_models_v2.parse_index@8530ed0615
  - cosa.agents.dm_quality_judge.xml_models_v2.parse_indices@5f33386aa7
  - cosa.agents.dm_quality_judge.xml_models_v2.position_weight@92cf9245d1
  - cosa.agents.dm_quality_judge.xml_models_v2.split_sentences@fda29f3d2b
  - cosa.agents.dm_quality_judge.xml_models_v2.structural_code@c79c685cd1
  - cosa.agents.dm_quality_judge.xml_models_v2.validate_extraction@d9c72ca4dd
---
# DM judge directness extraction

Version 2 does not ask the model for a directness grade. It asks where the first sentence that states the point sits, then checks that answer against the text and computes the weight in Python. The judge is in [[dm-quality-judge]].

## What it does
- `split_sentences` is the only sentence splitter. It splits on `.`, `!` and `?` followed by whitespace, and skips decimals, known abbreviations and single-letter initials.
- `number_sentences` renders the list as numbered lines, which is what the model sees. The validator checks against the same list.
- `DmDirectnessExtraction` holds three text fields: the quoted sentence, its index and the list of stray later sentences. It has no grade field.
- `parse_index` accepts a number, a trailing dot, or `none`, `n/a`, `na`, `null` and blank, which mean 0. `parse_indices` accepts comma, space or bracket lists. Anything else raises `ExtractionError`.
- `validate_extraction` rejects an index out of range and a quote given with index 0.
- It also rejects a quote that is not the whole numbered sentence, and a repeat that is not the first copy.
- It rejects a stray index that is repeated, out of range or not after the payload.
- `ExtractionError` is a refusal, not a grade. The judge retries and then returns the unverified non-answer.
- `position_weight` gives 2 for sentence 1, 1 for sentence 2, -1 for sentence 3 or later and -2 for none.
- `structural_code` names the shape: `lead_clean`, `lead_one_stray`, `mixed`, `late` or `missing`. `code_weight` maps each to a weight.
- `directness_weight` returns the position weight, because the concision flag is off. With the flag on it uses the structural weight.

## Don't
- Don't score the stray list. The model's stray judgement is the one part the checks cannot verify, so it is reported and not scored.
