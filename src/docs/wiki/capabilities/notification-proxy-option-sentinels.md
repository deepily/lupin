---
capability: notification-proxy-option-sentinels
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.notification_proxy.option_sentinels.encode_multi_select@09227a787f
  - cosa.agents.notification_proxy.option_sentinels.is_sentinel@f272f9abb9
  - cosa.agents.notification_proxy.option_sentinels.looks_like_a_sentinel@c66dbfd170
  - cosa.agents.notification_proxy.option_sentinels.option_labels@e53e99a7c3
  - cosa.agents.notification_proxy.option_sentinels.unasked_headers@ecec7f1355
  - cosa.agents.notification_proxy.option_sentinels.unoffered_values@b5f63d2de8
---
# Notification proxy option sentinels

A script entry may answer with a position instead of a label, because the labels on some cards are only known at run time. These helpers turn such a position into a real option label, and check answers against the card. The responder that calls them is in [[notification-proxy]].

## What it does
- The sentinels are `__first_option__`, `__last_option__` and `__all__`. `is_sentinel` matches one exactly, after stripping spaces, and the match is case-sensitive.
- `looks_like_a_sentinel` is true for any stripped `__word__`, including a typo. The resolver raises on a near miss, so a typo cannot reach the card as a label.
- `option_labels` lists every non-empty option label on a card, in order, from `response_options.questions`.
- `__all__` resolves through `encode_multi_select`. It returns JSON with the card's header as key and the labels as a list. It returns `None` unless the card has exactly one question with a header.
- `unasked_headers` lists the keys of a JSON `answers` map that the card never asked under. A bare label gives an empty list.
- `unoffered_values` lists every answer value that is not one of the card's option labels, one pick at a time for a multi-select answer. A card with no options rejects every value.

## Don't
- Don't match loosely. Both checks compare exactly after stripping, because the receiving agent does the same.
- Don't submit a sentinel string. When a sentinel cannot resolve, `resolve` returns `None` so the caller skips the card.
- Don't use these on a human's answer. They are for the automated responder only.
