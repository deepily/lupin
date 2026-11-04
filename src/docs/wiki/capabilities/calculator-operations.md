---
capability: calculator-operations
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.calculator.calc_operations.arithmetic@967a828eef
  - cosa.agents.calculator.calc_operations.compare_prices@1d0b3c3710
  - cosa.agents.calculator.calc_operations.convert@d2eee00d74
  - cosa.agents.calculator.calc_operations.mortgage@94231cfe02
  - cosa.agents.calculator.conversion_tables.find_category@3947951ee2
  - cosa.agents.calculator.conversion_tables.resolve_alias@23d7564be3
  - cosa.agents.calculator.dispatcher.dispatch@82a1c77171
  - cosa.agents.calculator.dispatcher.extract_calc_intent_xml@ceecc80a1a
  - cosa.agents.calculator.dispatcher.format_result_for_voice@4065d1225e
  - cosa.agents.calculator.xml_models.CalcIntent@7b3af6281a
---
# Calculator operations

The calculator turns a spoken request into one of four exact calculations: arithmetic, unit conversion, price comparison or a mortgage payment. The language model only extracts an intent. Plain functions do the sums.

## What it does
- `CalcIntent` is the extracted intent. Every field is a string, because model output is text. Empty tags arrive as `None` and are coerced to empty strings.
- `extract_calc_intent_xml` pulls the `calc_intent` block out of a raw reply, ignoring code fences and text around it. It calls the shared `extract_tagged_xml` with the tag `calc_intent`, and raises `ValueError` when there is no block.
- `dispatch` routes an intent to `arithmetic`, `convert`, `compare_prices` or `mortgage`. An unknown operation raises `ValueError`.
- `format_result_for_voice` turns a result dict into a spoken sentence. An error result becomes "Sorry, there was a problem" plus the message.
- `arithmetic` folds the operands left to right. Add and multiply take any count. Whole results come back as `int`, and the others are rounded to six places.
- `convert` handles temperature with explicit formulas and every other category through a common base unit. Different categories give an error.
- `compare_prices` puts every item on one unit, sorts by unit price ascending and names the cheapest. Mixed categories and temperature units give an error.
- `mortgage` uses the standard amortization formula on the principal minus the down payment. It returns the monthly payment, total paid and total interest.
- `resolve_alias` lowercases a unit name and maps it to its canonical name. An unknown name is returned as is.
- `find_category` returns the unit table and category name for a canonical unit, or `(None, None)`.

## Invariants
- Operations never raise for bad input. They return a dict with `status` set to `error` and a `message`.
- Division or modulo by zero, and a result with no real number, give an error.
