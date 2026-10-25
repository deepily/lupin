---
capability: deep-research-search-cache
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.deep_research.search_cache.cache_exists@bb64db50c8
  - cosa.agents.deep_research.search_cache.clear_cache@35478e70d3
  - cosa.agents.deep_research.search_cache.format_cache_listing@1ee2490f4d
  - cosa.agents.deep_research.search_cache.get_cache_dir@c8e5626828
  - cosa.agents.deep_research.search_cache.list_cached_queries@57fcaaaa6e
  - cosa.agents.deep_research.search_cache.load_cached_result@a99d36a40c
  - cosa.agents.deep_research.search_cache.save_to_cache@26f9e44a6b
  - cosa.agents.deep_research.seed_context.normalize_source_document@27e75b2a26
  - cosa.agents.deep_research.seed_context.read_seed_documents@6804d829e1
---
# Deep research search cache and seed documents

The per-user, per-day cache of search results, and the helpers that read caller-supplied source documents, for [[deep-research]]. The key function `normalize_query` and `query_with_seed_context` are described on that page.

## What it does
- `get_cache_dir` returns the folder `io/deep-research/{user_email}/cache/{date}` and creates it. The date defaults to today.
- `cache_exists` and `load_cached_result` look up the normalized key. A missing, unreadable or malformed file counts as a miss.
- `save_to_cache` writes the query, key, timestamp and results as JSON and returns the path. A write failure is logged, and the path is still returned.
- `list_cached_queries` returns `(filename, original query)` pairs for a date. `format_cache_listing` turns them into a prompt block, or an empty string.
- `clear_cache` deletes the date's JSON files and returns how many it removed.
- `normalize_source_document` turns `None`, a string or an iterable into a new list of paths.
- `read_seed_documents` returns `(path, text)` pairs in the caller's order. It lets an unreadable file raise, so the report never silently rests on less.

## Don't
- Don't expect old days to be served. Each date has its own folder.
