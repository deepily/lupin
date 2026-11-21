---
capability: preference-replay-service-embeddings
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.research.preference_replay.service_embeddings.CachedServiceEmbedder@b4806664ef
  - cosa.research.preference_replay.service_embeddings.CachedServiceEmbedder.flush@1cd5942d48
  - cosa.research.preference_replay.service_embeddings.CacheSentinelMismatch@2484387e90
  - cosa.research.preference_replay.service_embeddings.EmbeddingServiceUnavailable@78d482271b
  - cosa.research.preference_replay.service_embeddings.WrongVectorWidth@60b21768fa
  - cosa.research.preference_replay.service_embeddings.cache_key@49637d8ffc
  - cosa.research.preference_replay.service_embeddings.record_neighbour_cosines@b5a34b4626
---
# Preference replay: service embeddings and the vector cache

Gives the extractor replay the vectors the live extractor makes, through a side cache ([[preference-replay-extractor-replay]]). No call here loads a model or touches a GPU.

## What it does
- `CachedServiceEmbedder( cache_path )` embeds a text through the live extractor's `default_embed` and keeps each vector in a JSON file. A cached text makes no call.
- `cache_key( text, encoder )` is the sha256 of the encoder, a newline and the text, so a new encoder version never reads an old vector.
- Construction makes one probe call. An empty cache is stamped with the probe vector. A cache with vectors and no probe raises `CacheSentinelMismatch`. So does a stored probe whose cosine with the fresh one is under 0.999.
- A vector of the wrong length raises `WrongVectorWidth` and is never cached.
- A failed call raises `EmbeddingServiceUnavailable`, which stops the replay. The cache keeps every vector already made.
- `flush` writes the file through a temporary one, so a crash keeps the old file whole. `calls` and `hits` count service calls and cache answers.
- `record_neighbour_cosines( log )` wraps `fetch_neighbours` while the block runs. It appends the best cosine of each neighbour the model is shown, and restores the original on exit, even after an error.
