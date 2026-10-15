---
capability: rest-routers-embeddings-and-test-stubs
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.routers.embeddings.EmbedRequest@d41170c6d1
  - cosa.rest.routers.embeddings.EmbedBatchRequest@53339721db
  - cosa.rest.routers.embeddings.EmbedResponse@036cc8c027
  - cosa.rest.routers.embeddings.EmbedBatchResponse@dea15ab169
  - cosa.rest.routers.embeddings.EmbedInfoResponse@3e01d25c27
  - cosa.rest.routers.embeddings.generate_embedding@2725c9bfda
  - cosa.rest.routers.embeddings.generate_embeddings_batch@5d37400a00
  - cosa.rest.routers.embeddings.get_info@99da32374b
  - cosa.rest.routers.jobs.get_static_dir@afe0b3c731
  - cosa.rest.routers.jobs.delete_snapshot@c557af3503
  - cosa.rest.routers.jobs.get_answer@0ffdcd93e3
  - cosa.rest.routers.mock_job.mock_job_health@15e0d0b062
---
# Embeddings routes and test stubs

The `/api/embeddings` HTTP door to the server's embedding provider, plus three stubs that return canned answers. The provider itself is in [[embedding-pipeline]].

## What it does
- `generate_embedding` takes `EmbedRequest` (`text`, `content_type` of `prose` or `code`, optional `role` of `query` or `document`) and returns `EmbedResponse` (`embedding`, `dimensions`).
- `generate_embeddings_batch` takes `EmbedBatchRequest` and returns `EmbedBatchResponse` (`embeddings`, `dimensions`, `count`). An empty `texts` list answers 400.
- `get_info` (`GET /api/embeddings/info`) returns `EmbedInfoResponse`: `provider`, `dimensions`, `status` (always `ready`) and the `engines` block. It loads no model.
- All three accept an API key or a JWT. Inference runs off the event loop. On generate and batch, a role the provider cannot honour answers 422. `get_info` takes no role.
- `mock_job_health` (`GET /api/mock-job/health`) returns `{ status: "ok", available: true, description }` and queues nothing.
- `get_static_dir` returns `static_dir` from `lupin_app.main`. No route in `jobs.py` depends on it.
- `delete_snapshot` and `get_answer` are stubs. `delete_snapshot` (`GET /api/delete-snapshot/{id}`) reports a deletion, and answers 404 for an empty id or one starting with `invalid`. `get_answer` (`GET /get-answer/{id}`) serves `gentle-gong.mp3`, or 404 if that file is missing.

## Don't
- Don't treat `delete_snapshot` or `get_answer` as real. They delete nothing and return a placeholder.

## Invariants
- `dimensions` in a batch comes from the first vector, and is 0 for no vectors.
