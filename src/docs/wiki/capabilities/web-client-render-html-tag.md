---
capability: web-client-render-html-tag
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.html.getTrustedTypes@d066610da4
  - src.lupin_app.static.js.multiplexer.render.html.ensurePolicy@6a413e8768
  - src.lupin_app.static.js.multiplexer.render.html.resetForTesting@270c4a3550
  - src.lupin_app.static.js.multiplexer.render.html.raw@2695b329a7
  - src.lupin_app.static.js.multiplexer.render.html.isRaw@45320bf92b
  - src.lupin_app.static.js.multiplexer.render.html.appendValue@ddbcf70d0b
  - src.lupin_app.static.js.multiplexer.render.html.makeRawTemplateStrings@50b69cc1e8
  - src.lupin_app.static.js.multiplexer.render.html.assemble@1692ed8adb
  - src.lupin_app.static.js.multiplexer.render.html.applyAttributes@19e10b49da
  - src.lupin_app.static.js.multiplexer.render.html.applyChildren@66ffab655b
  - src.lupin_app.static.js.multiplexer.render.html.html@4693ab7e9b
---
# The html template tag

`html` builds a DocumentFragment from a tagged template and escapes every interpolated value as text. The multiplexer renderers use it in place of `innerHTML`.

## What it does
- `html` joins the template strings, parses them with a `<template>` element, fills attributes and children, and returns the fragment. Each call returns a new fragment.
- `appendValue` turns a value into DOM. Strings and numbers become text nodes. Arrays flatten recursively. A `Node` is appended as it is. `null`, `undefined`, `true` and `false` add nothing.
- `assemble` swaps each interpolation for a marker. A value that follows `name="` or `name='` becomes an attribute marker. Any other value becomes a comment marker.
- `applyAttributes` sets the attribute through `setAttribute`: `false`, `null` and `undefined` omit it, `true` sets an empty value, and a `Node` or array is dropped.
- `applyChildren` finds the comment markers with a tree walker and replaces each with the DOM that `appendValue` builds.
- `raw` wraps a string so `appendValue` parses it as HTML and `applyAttributes` writes it verbatim; `isRaw` is the check for that wrapper.
- `getTrustedTypes` returns `globalThis.trustedTypes` when it exists. `ensurePolicy` creates a policy named `lupin-html` once.
- `makeRawTemplateStrings` builds a one-string template array for a `raw` payload and registers it as known.
- `resetForTesting` sets the cached policy to null. It does not touch the known-template set.

## How the parts work together
`html` calls `ensurePolicy`, registers its strings as known and runs `assemble`. It parses the result, then runs `applyAttributes` and `applyChildren` on the content. When Trusted Types exists, the policy refuses to mint HTML for a template array it never registered. So only tagged templates and `raw` payloads reach the parser.

## Don't
- Don't pass unsanitized text to `raw`. It bypasses the escaping this tag exists to provide.
- Don't interpolate inside a longer quoted attribute value, such as `class="a ${b}"`. The value is treated as a child and a comment marker lands in the attribute text.
