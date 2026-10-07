---
capability: db-repositories
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.rest.db.repositories.base.BaseRepository@6839b17f66
  - cosa.rest.db.repositories.base.BaseRepository.create@992f632f47
  - cosa.rest.db.repositories.base.BaseRepository.update@72bd449052
  - cosa.rest.db.database.get_db@63596843e9
  - cosa.rest.db.repositories.vector_search.dot_topk@0e6969973e
---
# Database repositories

Most Postgres tables have one repository class, all built on one generic base. Four have none: `job_history`, `server_lifecycle`, `task_events` and `task_promotion_tickets`. `TaskRepository` writes the `task_events` rows itself. This page is a map from each repository to the capability that uses it; the behaviour of a repository is described by the capability, not here. [[db-session-and-schema]] owns the engine, the models and schema drift.

## What it does
- `BaseRepository( model, session )` gives every table `get_by_id`, `get_all`, `create`, `update`, `delete`, `count` and `exists`. Each subclass adds the queries its capability needs.
- `create` and `update` call `flush()`, so the new id is visible, but never `commit()`. `update` sets only attribute names the model has and skips the rest without an error.
- `get_db()` is the commit point: it commits when the block exits cleanly and always closes the session. It rolls back on any `Exception`; a `BaseException` such as `KeyboardInterrupt` skips the rollback.
- `vector_search.dot_topk` is the nearest-neighbour query shared by `InputAndOutputRepository`, `PredictionDecisionRepository` and `SolutionSnapshotRepository`.

## Who uses which repository
| Repository | Capability |
|---|---|
| `UserRepository`, `ApiKeyRepository`, `RefreshTokenRepository`, the other token, login-attempt and audit repositories | [[auth-and-accounts]] |
| `TaskRepository` | [[task-store]] |
| `ApprovalSettingRepository` | [[task-promotion-gate]] |
| `NotificationRepository`, `FcmTokenRepository` | [[notification-delivery]] |
| `ProxyDecisionRepository`, `TrustStateRepository`, `PredictionDecisionRepository` | [[decision-proxy]] |
| `SolutionSnapshotRepository`, `QuestionEmbeddingRepository`, `EmbeddingCacheRepository`, `CanonicalSynonymRepository`, `GistCacheRepository` | [[solution-memory]], [[question-gist-and-synonyms]] |
| `InputAndOutputRepository`, `QueryLogRepository`, `PredictionLogRepository` | the `cosa.memory` tables of those names and the prediction engine |

## Invariants
- A repository never commits. Open the session with `get_db()`, or commit it yourself, or the write is lost.
- `dot_topk` ranks by inner product by default, and `similarity_pct` is `dot * 100`. That equals cosine only when both vectors have unit length.
- Pass `metric="cosine"` when either side may be unnormalized. Any other metric value raises `ValueError`.
- `dot_topk` does not check vector length. Both engines in `cosa.memory.local_embedding_engine` now L2-normalize their output, so the default is correct for today's embeddings. The `vector_search` docstring records a query norm of 19.809 against stored rows at 1.000 that turned a true cosine of 0.517 into 1024.15%.

## How to extend
- Subclass `BaseRepository[ThatModel]` under `cosa.rest.db.repositories`. One module per repository is the convention, not a rule: `TrustStateRepository` shares `proxy_decision_repository.py`. Put its model in `cosa.rest.postgres_models` or `cosa.rest.db.vector_store_models`. The first holds the tasks, notifications, auth, proxy-decision, trust, approval-setting, push-token, prediction-log, job-history and server-lifecycle models. The second holds the input-and-output rows, embeddings, snapshots, query log, gist cache, synonyms and prediction decisions.
- The package `__init__` re-exports only ten names (the base, the auth and token repositories, and the proxy-decision pair), loaded lazily. Import any other repository from its submodule.
