---
capability: reuse-need-redaction
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_redact.routes_from_text@939fa88900
  - lupin_mcp.reuse_redact.redact_need@fc6d8b971f
---
# Reuse need redaction

`redact_need` blanks what must not leave the machine in a need before Jev sees it. It uses the standard library only, because the voice server runs in a light virtual environment. [[reuse-search-tools]] calls it on every need.

## What it blanks
- It replaces each email, URL, IP address, absolute path and credential-shaped token with `[email]`, `[url]`, `[ip]`, `[path]` or `[secret]`. The rest of the text is kept byte for byte.
- It returns the redacted text, a ranking text and a list of hit counts by kind. In the ranking text each blanked span becomes one space, so no placeholder word reaches a ranker.
- When spans overlap, the earlier kind in the order url, path, email, secret, ip wins. A path that holds an email is one `[path]`.
- It never raises on a string, and redacting its own output returns it unchanged.

## Known routes
- A path that is a known route of this project is kept. `routes_from_text` reads those routes from the index file `routes.md`, one per line shaped like `METHOD /path -> symbol`, and skips other lines.
- A `{parameter}` segment of a route matches exactly one segment of the token. A prefix that ends at a segment also matches.
- A route with a query string or fragment is not kept, because a query is data. A token that holds an email, URL, IP address or credential is never a route.
- With no routes, every absolute path is redacted.
