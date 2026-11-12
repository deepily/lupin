---
capability: utils-http-json
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.http_json.send_json@9ea157de9f
---
# JSON request over urllib

One helper that five modules share to send a JSON body and read the answer. The hook library keeps its own copies, because a hook must not import `cosa`.

## What it does
- `send_json( url, payload, headers, timeout, method, opener )` sends one request and returns `( status, text, reply_headers )`.
- `payload` may be `None` for an empty body, a dict or list encoded as JSON, or text or bytes already encoded.
- It sets `Content-Type: application/json` unless the caller's headers name another type.
- `opener` replaces `urllib.request.urlopen`, which is the test seam.
- `model_window`, `jev_transport`, `hook_link_tick`, `arbiter_live_notify` and `reuse_candidates` call it. Each keeps its own return or error contract on top.

## Don't
- Don't expect it to raise on a 4xx or 5xx. Read `status`.

## Invariants
- An HTTP error status is returned with its body, because the body carries the reason.
- It raises only when no HTTP answer came: a refused connection, a timeout or a failed name lookup.
