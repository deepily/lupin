---
capability: web-search-tools
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.tools.search_kagi.KagiSearch@eae03748e1
  - cosa.tools.search_kagi.KagiSearch.search_fastgpt@cee5e88ce4
  - cosa.tools.search_kagi.KagiSearch.get_summary@76a61de360
  - cosa.tools.search_kagi.kagi_error_is_transient@4d5f2e5889
  - cosa.tools.search_lupin_v010.LupinSearch@e4ba51e941
  - cosa.tools.search_lupin_v010.LupinSearch.get_results@f3234747b9
  - cosa.tools.search_lupin.LupinSearch@e4ba51e941
---
# Web search tools

`KagiSearch` calls the Kagi API for a FastGPT answer or a page summary. `LupinSearch` wraps it behind a vendor-neutral interface that the weather agent and the router fallback use.

## What it does
- `KagiSearch( query=… ).search_fastgpt()` returns a dict with `meta` and `data`. `get_summary()` summarizes a URL with the `agnes` engine.
- `search_fastgpt` retries a transient failure, up to `max_attempts` (default 3) with exponential backoff from `retry_backoff` (default 1 second), capped at four times that.
- Transient means no response at all, or status 408, 425, 429, 500, 502, 503 or 504, decided by `kagi_error_is_transient`.
- `LupinSearch.search_and_summarize_the_web()` runs `search_fastgpt`. `get_results( scope )` returns `all`, `meta`, `data`, `summary` or `references`.
- `weather_agent` and `todo_fifo_queue` import `LupinSearch` from `search_lupin_v010`. `todo_fifo_queue` turns a `RequestException` into a spoken refusal.

## Don't
- Don't retry a 401, 403 or 404. They are raised on the first attempt.
- Don't summarize the last failure. After the final attempt the original exception is re-raised unchanged, and a test requires the weather agent's refusal to name its status code.
- Don't call `get_results` before `search_and_summarize_the_web`. Until then `_results` is `None`: scope `all` returns `None` and every other valid scope raises `TypeError`.
- Don't edit one `LupinSearch` copy and assume it is the one in use. Production imports only `search_lupin_v010`.

## Invariants
- The two `LupinSearch` files have the same code pins. They differ only in docstring text and trailing whitespace.
- No source file outside the tests imports `cosa.tools.search_lupin`, checked with a search for `from cosa.tools.search_lupin import`.
- An invalid `scope` prints an error banner and returns `None`.
- The Kagi key is read from `src/conf/keys/kagi`. A missing file prints an error and returns `None` from `get_api_key`, and `KagiSearch` does not check for it.
- `LupinSearch` builds its `KagiSearch` with the default retry settings.
