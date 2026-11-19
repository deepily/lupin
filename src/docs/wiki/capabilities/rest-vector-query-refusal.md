---
capability: rest-vector-query-refusal
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.rest.db.vector_errors.QueryVectorRefused@124e91cae6
  - cosa.rest.db.repositories.prediction_decision_repository.refuse_unusable_cosine_query@5664ba723f
---
# Refusing an unusable cosine query vector

A cosine search over the prediction decisions ([[rest-data-repos-proxy-predictions]]) refuses a query vector it cannot score, instead of returning a ranking built on nothing.

## What it does
- `QueryVectorRefused` is an `Exception` with the reason kept as `reason` and as its text. It lives in `vector_errors`, a module with no imports.
- `refuse_unusable_cosine_query( query_embedding )` returns None for a usable vector. It raises `QueryVectorRefused` for a missing, wrong-dimension, non-finite, zero-norm or out-of-band vector.
- A zero vector is named as having zero norm, where the freshness check would file it under the retired unit-norm model.
