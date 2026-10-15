---
capability: rest-data-vector-store-models
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.db.vector_store_models.InputAndOutput@6bccfe1654
  - cosa.rest.db.vector_store_models.QuestionEmbedding@13408158ca
  - cosa.rest.db.vector_store_models.EmbeddingCache@ff2aa39221
  - cosa.rest.db.vector_store_models.GistCache@b1cd39113b
  - cosa.rest.db.vector_store_models.CanonicalSynonym@0265d10e94
  - cosa.rest.db.vector_store_models.QueryLog@63c01a1e29
  - cosa.rest.db.vector_store_models.PredictionDecision@b553864db6
  - cosa.rest.db.vector_store_models.SolutionSnapshot@cf2912b408
---
# Vector store models

Eight SQLAlchemy models for the pgvector tables, registered on the same `Base` as `cosa.rest.postgres_models`, so alembic autogenerate and the empty-database bootstrap see them. Every vector column is 768 wide (`EMBEDDING_DIM`). The repositories that query them are in [[db-repositories]], the engine and migrations in [[db-session-and-schema]].

## What it does
| Model | Table | Key | Holds |
|---|---|---|---|
| `InputAndOutput` | `input_and_output` | `id`, bigint | one question and answer with `input_embedding` and `output_final_embedding` |
| `QuestionEmbedding` | `question_embeddings` | `id`, bigint | question text and one vector; btree on `question` |
| `EmbeddingCache` | `embedding_cache` | `id`, bigint | `normalized_text` and one vector; btree on the text |
| `GistCache` | `gist_cache` | `id`, bigint | verbatim, normalized and gist questions, no vector |
| `CanonicalSynonym` | `canonical_synonyms` | `id`, string | three embeddings and a confidence for exact-match lookup |
| `QueryLog` | `query_log` | `id`, string | write-only telemetry with three vectors and cache-hit flags |
| `PredictionDecision` | `prediction_decisions` | `id`, string | the decision proxy's question, category, value and `question_embedding` |
| `SolutionSnapshot` | `solution_snapshots` | `id_hash`, string | answer, code and summary text with seven vectors |

## Don't
- Don't search with cosine. The vectors are built for dot product, so the index operator class is `vector_ip_ops` and the operator `<#>`.
- Don't expect an index on every vector. Only `prediction_decisions.question_embedding` and the snapshot `question_embedding` and `code_embedding` carry HNSW indexes (`HNSW_DOT_INDEXES`).
- Don't assume date columns are timestamps. `GistCache.created_date`, `PredictionDecision.created_at` and the snapshot dates are text.

## Invariants
- `input_and_output.input_embedding` has no vector index: most rows are duplicates, which gave wrong neighbours under HNSW, and an exact scan returns the right ones.
- `SolutionSnapshot.code` and `non_synonymous_questions` are text arrays; `synonymous_questions` is one string.
