---
capability: rest-core-error-envelope
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.error_envelope.make_unhandled_exception_handler@e23e3b8f6c
---
# Unhandled-exception envelope

A 500 that tells the caller whose problem it is. During a mid-refactor save a call can exist while its definition does not. `/health` stays 200, so the caller must be told the server failed, not the request.

## Handler
- `make_unhandled_exception_handler( server_started_at )` returns an `( request, exc )` handler that answers HTTP 500 with a JSON body. `lupin_app.main` registers it on the app.
- The body has exactly three keys: `detail`, `exception_class` and `server_started_at`.
- `detail` is the fixed text `Internal Server Error`. The exception message is never included.
- `exception_class` is the exception's class name, so a `NameError` reads as a server fault.
- `server_started_at` is the ISO instant captured at app import and bound when the handler is built. A caller comparing it with its last value learns the process restarted.
- The handler ignores the request, so the body names no route.

## Don't
- Don't compute the start instant per request. It would move on every error and answer nothing.
- Don't add the exception text to the body. What a message exposes on this fleet has not been audited.
