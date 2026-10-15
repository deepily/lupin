---
capability: decision-proxy-presence
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.decision_proxy.user_presence.fetch_sessions@52fe969de2
  - cosa.agents.decision_proxy.user_presence.responder_presence_kwargs@a8ba4cd7cb
  - cosa.agents.decision_proxy.user_presence.sessions_feed@2d0c45ac81
  - cosa.agents.decision_proxy.user_presence.user_connected_or_default@a7f6689e5c
---
# Decision proxy presence

The proxy asks whether the named human is connected before it answers for them. These helpers build that answer from the server's session list. The router that uses it is in [[decision-proxy]].

## What it does
- `sessions_feed` returns a callable that is true when the human has a live session other than the proxy's own. The match is on `user_id`, and the proxy's session id is excluded.
- The feed calls `/api/websocket-sessions` and sends an `Authorization` header only when the token function returns one.
- An empty human user id is never connected and makes no request.
- An answer is reused for `ttl_seconds` (10 by default). A failed fetch is not cached.
- `fetch_sessions` does one GET with a 5 second timeout, raises on an HTTP error and returns the JSON.
- `user_connected_or_default` returns the feed's answer as a bool. If the feed raises, it logs a warning and returns `FEED_FAILURE_MEANS_CONNECTED`, which is `False`.
- `responder_presence_kwargs` reads the active hours, the timezone and `decision proxy human user id` from the INI. It returns the keyword arguments the responder takes, including the feed.

## Don't
- Don't read a failed feed as the human being away by accident. The constant is a ruling: when presence is unknown, the proxy acts as before.
- Don't pass a token value. Pass a function, because the token is read at each fetch.
