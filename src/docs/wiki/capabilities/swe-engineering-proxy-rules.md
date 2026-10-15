---
capability: swe-engineering-proxy-rules
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.swe_team.proxy.config.swe_proxy_config_from_config_mgr@1940be9eac
  - cosa.agents.swe_team.proxy.engineering_categories.get_category_cap_level@d39407b242
  - cosa.agents.swe_team.proxy.engineering_categories.get_category_names@6c1cdea90c
  - cosa.agents.swe_team.proxy.engineering_classifier.EngineeringClassifier@faea58d4e1
---
# SWE engineering proxy rules

The SWE profile for the [[decision-proxy]] sorts a question into one of six engineering categories and caps how far trust can rise in each. The strategy that uses these is `EngineeringStrategy`, described there.

## What it does
- The six categories are `deployment`, `testing`, `deps`, `architecture`, `destructive` and `general`. Each has keywords, a cap level and a description.
- `get_category_names` lists them. `get_category_cap_level` returns a category's cap, and 5 for a name it does not know.
- By default `deployment`, `destructive` and `architecture` cap at level 3. `testing`, `deps` and `general` cap at 5.
- `swe_proxy_config_from_config_mgr` reads five keys that start with `swe engineering proxy`: the accepted senders, three cap levels and `ask before act`. The senders default to the lead, coder and tester addresses.
- `EngineeringClassifier.classify` matches each category's keywords as substrings of the lowercased question. The `general` category has no keywords and is not scored.
- Confidence starts at 0.5 plus 0.1 per matched keyword, capped at 0.95. A sender hint that matches the category adds 0.15, capped at 0.98.
- With no match, a sender hint gives that category at 0.45. With no hint the result is `general` at 0.3.
- The only sender hint is `swe.tester`, which means `testing`. `get_categories` returns the whole table.

## Don't
- Don't expect word boundaries. A keyword such as `ship` also matches inside another word.
