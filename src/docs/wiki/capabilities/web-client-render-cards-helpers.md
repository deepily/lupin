---
capability: web-client-render-cards-helpers
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.pressHoldGuard.wirePressHoldGuard@00915eca37
  - src.lupin_app.static.js.multiplexer.render.scrollReveal.scrollRevealElement@e46a9c8dc0
  - src.lupin_app.static.js.multiplexer.render.markdown.ensureGlobals@698132e692
  - src.lupin_app.static.js.multiplexer.render.markdown.postProcessAnchors@8e9fc5d67d
  - src.lupin_app.static.js.multiplexer.render.markdown.renderMarkdown@17e29924fc
  - src.lupin_app.static.js.multiplexer.render.markdown.renderMarkdownInline@27700fe42c
  - src.lupin_app.static.js.multiplexer.render.time.formatCountdown@67b3864c05
  - src.lupin_app.static.js.multiplexer.render.time.formatHM@cfb5792481
  - src.lupin_app.static.js.multiplexer.render.time.formatDateKey@e97b0fba41
  - src.lupin_app.static.js.multiplexer.render.time.formatDuration@4f9ba03ddb
---
# Render helpers

Small shared helpers for the multiplexer renderers: a press guard, a scroll reveal, markdown rendering and time formatting.

## Interaction
- `wirePressHoldGuard( container, opts )` returns an object with `hold( paint )` and `dispose()`. While a mouse press is in flight, `hold` keeps the latest paint and returns true. The Task List, Holding Area and Epic Board renderers use it.
- The held paint runs once after `mouseup` (one timer tick later), at `mouseleave`, or on a window blur.
- `scrollRevealElement( el )` resolves at once for null or an element fully in view. Otherwise it scrolls smoothly and resolves after 300 ms.

## Markdown
- `renderMarkdown( text )` parses with the page's `marked`, sanitizes with the allowlist in `DOMPURIFY_CONFIG`, runs `postProcessAnchors` and returns a raw value. `renderMarkdownInline` strips a leading `<p>` and a trailing `</p>`, so a text of several paragraphs keeps inner tags.
- `ensureGlobals` is private and throws when either library is missing from the window.
- `postProcessAnchors` is private. It adds a new-tab target and a noopener rel to links lacking a target, but leaves in-app doc links bare.

## Time
- `formatCountdown( ms )` returns `MM:SS`, zero-padded, and `00:00` for zero or negative input. `formatHM( ts, tz )` returns 24-hour `HH:MM`, or `--:--` for a non-finite value.
- `formatDateKey( ts, tz )` returns a year-month-day key in the given zone, or browser-local time without one. Non-finite input gives ten dashes.
- `formatDuration( start, end )` returns seconds, minutes or hours text. With no end it reads the clock and prefixes "running for". Non-finite input gives `--`.

Markdown output goes straight into `html` template slots, so the sanitizer is the only barrier. The time functions are pure except the running case of `formatDuration`.
