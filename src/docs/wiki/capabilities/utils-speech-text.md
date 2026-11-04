---
capability: utils-speech-text
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.speech_text.strip_markdown_links_for_speech@3992ac4526
---
# Speech text clean-up

One helper that turns links into something safe to say aloud. The server's text-to-speech doors ([[rest-routers-speech-tts-streaming]]) and the cosa-voice spoken-length cap both use it, so both read a link the same way.

## What it does
- `strip_markdown_links_for_speech( text )` replaces each markdown link with its label and `URL omitted`. An image becomes its alt text and `URL omitted`. A bare `http` or `https` address becomes `URL omitted`. A link with an empty label becomes `URL omitted`.
- A link target may hold one level of parentheses, a label one level of square brackets, and a `"title"` after the target is dropped. Trailing sentence punctuation is not part of a bare address.
- `[ref][id]` references and text without links come back unchanged.

## Don't
- Don't expect trimmed output. The result keeps its surrounding whitespace; the caller strips.
- Don't pass anything but a `str`. Other types raise `TypeError`.
