---
capability: embedding-engine-info
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.memory.embedding_provider.embedding_dimensions@d9850234a6
  - cosa.memory.embedding_provider.EmbeddingProvider.describe_engines@03211386fd
  - cosa.memory.local_embedding_engine.ProseEmbeddingEngine.describe@a5dab2b585
  - cosa.memory.local_embedding_engine.CodeEmbeddingEngine.describe@2d544f5e9e
  - cosa.memory.embedding_provider.init_embedding_table_config@38076f5b44
---
# Embedding engine info

This capability reports what an embedding vector means: its dimension, and each engine's model, dtype and device. A vector build reads it and refuses an engine whose revision is null.

## What it does
- `embedding_dimensions( config_mgr )` is the one read of the INI key `embedding dimensions`. It returns an int and defaults to 768.
- The provider, the embedding manager and the cache, synonym, question-embedding, query-log, input-and-output and solution tables all call it. `init_embedding_table_config` gives a new table its debug and verbose flags, a configuration manager and the dimension from `embedding_dimensions`.
- Each engine's `describe` returns its model, revision, dtype, device, prefixes and dimensions. It never loads the model and never touches the GPU.
- `revision` is None until the model is loaded. `dtype` is the INI value before load and the loaded parameters' dtype after.
- `EmbeddingProvider.describe_engines` returns the code and prose `describe` dicts, the device class and the library versions.
- A process that does not own the engines, with a model server to ask, returns the model server's engines block instead. That is the FastAPI app in remote mode.

## Don't
- Don't read `embedding dimensions` straight from the config. Call `embedding_dimensions`, so the default lives in one place.
- Don't treat a null `revision` from a non-owner process as a fault in the engine. Ask the model server, which `describe_engines` already does.

## Invariants
- `describe_engines` never loads a model.
- On the remote path it raises `RuntimeError` when the key is missing, the answer is not 200, or the answer names no engines block.
- A model server older than role support has no engines block, and the error says so.
