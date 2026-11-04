---
capability: spend-ceiling-prices-and-report-redaction
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.secret_redaction.redact_longrepr@f47df8a366
  - cosa.utils.vertex_spend_ceiling.ModelPrice@b4d17905d4
  - cosa.utils.vertex_spend_ceiling.ModelPrice.is_priced@cd810f06c7
  - cosa.utils.vertex_spend_ceiling.UnpricedModelError@109b0524ad
  - cosa.utils.vertex_spend_ceiling.max_daily_usd_at_tpm@5751407bed
---
# Spend-ceiling prices and report redaction

Two small pieces beside [[utils-config-secrets-and-vertex]]. `ModelPrice` carries a model's published price, and `redact_longrepr` scrubs one pytest report's traceback.

## What it does
- `ModelPrice` is a frozen record: `model_id`, `usd_per_mtok_input`, `usd_per_mtok_output`, `source_url` and `source_note`. A price of `None` records that no primary source publishes one.
- `ModelPrice.is_priced` is a property, true only when both the input and output prices are not `None`.
- `UnpricedModelError` is a `ValueError`. The clamp functions raise it when `is_priced` is false.
- `max_daily_usd_at_tpm( price, tpm, minutes_per_day=1440 )` is the inverse of the clamp. It bills every token at the output price and returns dollars per day.
- It raises `UnpricedModelError` first, then `ValueError` for a negative `tpm` or a `minutes_per_day` of zero or less. A `tpm` of zero is allowed.
- `redact_longrepr( longrepr, values )` takes a pytest repr object, a string or `None`. A string comes back redacted, so assign it back. An object is mutated in place and returned.
- For an object it covers traceback source lines, locals, the function-argument header, the crash message and every link of a chained exception. `None` returns `None`.

## Don't
- Don't fill in a price to make an unpriced model clampable. The error is the finding.
- Don't ignore the return value of `redact_longrepr`. A string is immutable and the call cannot update it for you.

## Invariants
- A value under a credential-named argument is replaced whole, quotes included. Other text is redacted by value and by quoted assignment.
