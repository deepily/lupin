---
capability: repo-tools-candidate-vector-build
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.symindex.candidates.vector_build.EndpointClient@5098542e92
  - cosa.repo.symindex.candidates.vector_build.entry_texts@f1e5053a5e
  - cosa.repo.symindex.candidates.vector_build.build_vectors@2f30bcb591
  - cosa.repo.symindex.candidates.vector_build.reuse_mismatches@702e022da1
  - cosa.repo.symindex.candidates.vector_store.check_engines@608e588f45
  - cosa.repo.symindex.candidates.vector_store.query_key@36f39c90b7
  - cosa.repo.symindex.candidates.vector_store.query_vectors@4300a86b11
  - cosa.repo.symindex.candidates.vector_store.clear_stale_queries@781f2043d4
---
# Candidate vector build and query vectors

The build embeds every index entry three ways by posting batches to the FastAPI embeddings endpoints. It loads no model itself. No function body is embedded.

## Build
- `EndpointClient( provider=None, get=None )` has `embed( texts, content_type, role )` and `info()`. `info()` reads `GET /api/embeddings/info` and raises `RuntimeError` for no key or a non-200 answer. Calls are pinned to FastAPI.
- `entry_texts( entry, purpose )` returns `code` (path, name, signature), `prose` (name, purpose, docstring) and `concat` (code, then prose).
- `build_vectors( entries, purposes, client, out_dir, ..., reuse=None, stats=None )` sorts entries by id and warms both engines. It embeds in batches of at most 16 texts with a 0.5 s pause. A batch closes early when its rows times its longest text would pass 32,000 characters. It writes three matrices and a row-text sidecar, and returns the sealed manifest. It raises `ENGINE_NOT_LOADED` when a revision is still null and `EMBEDDING_SHAPE` for a wrong count or ragged row. The caller swaps the folder in.
- `reuse_mismatches( old_manifest, info )` returns `[]` when the live set's engines, device class, libraries and roles match a build made now. Otherwise it names the failing clauses, or `[ "manifest" ]` for a malformed manifest. Only on `[]` are rows with an equal id and text hash copied.

## Query vectors
- `check_engines( manifest, info )` returns None when the server's engines and roles match the set's. It raises `ENGINE_NOT_LOADED` when an engine reports no revision, or `ENGINE_MISMATCH` naming each field that differs.
- `query_vectors( redacted_need, client, cache_dir, manifest )` returns `{ prose, code, concat }`. `query_key( need )` is the sha256 that names the cache file. A cache file serves only under the same manifest hash. On a miss the engines are checked, then the vectors are embedded and cached. An unreadable cache file raises `QUERY_CACHE_CORRUPT`.
- `clear_stale_queries( cache_dir, current_hash )` deletes cache files made under another set, or unreadable, and returns the count.
