---
capability: question-gist-and-synonyms
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.memory.normalizer.Normalizer.normalize@2435412d12
  - cosa.memory.gister.Gister.get_gist@124cce9144
  - cosa.memory.gist_normalizer.GistNormalizer.get_normalized_gist@47883efef9
  - cosa.memory.gist_cache_table.GistCacheTable.get_cached_gist@282bffcd3c
  - cosa.memory.canonical_synonyms_table.CanonicalSynonymsTable.add_synonym@97128637c9
  - cosa.memory.canonical_synonyms_table.CanonicalSynonymsTable.find_exact_verbatim@67b21097c6
  - cosa.rest.db.repositories.gist_cache_repository.GistCacheRepository@d5abda0d75
  - cosa.rest.db.repositories.canonical_synonym_repository.CanonicalSynonymRepository@7e7ebe0bb4
  - cosa.rest.multimodal_munger.MultiModalMunger@5c5251c7e8
---
# Question gist and synonyms

A spoken question is reduced three ways: the verbatim text, a normalized form, and a gist. Exact matches on any of them let a repeated question skip the similarity search.

## What it does
- `Normalizer.normalize` expands contractions, lowercases, drops single-word fillers and punctuation, and lemmatizes nouns, verbs, adjectives and adverbs with spaCy. It keeps math operators. Sentence-ending marks are dropped, so sentence breaks leave no trace.
- `Gister.get_gist` asks an LLM for the main intent of an utterance. `GistNormalizer.get_normalized_gist` then normalizes that gist.
- `GistCacheTable` caches gists in Postgres. A lookup tries the verbatim question first, then the normalized one.
- `CanonicalSynonymsTable` maps known question wordings to a snapshot. `find_exact_verbatim`, `find_exact_normalized` and `find_exact_gist` return a snapshot id or `None`.
- The two repositories hold the storage. Each table opens a short database session per call.
- `MultiModalMunger` is a different job. It cleans a raw transcription according to its mode, such as email, Python or SQL punctuation. It does not call the gister.

## Don't
- Don't cache a gist from a custom prompt. `Gister` caches only the default prompt, because other prompts see unique text and would collide.
- Don't let a cache failure lose the gist. A failed read falls through to the LLM, and a failed write still returns the gist.
- Don't assume the synonym table's gist column holds an LLM gist. See the invariants.

## Invariants
- Multi-word entries in `FILLER_WORDS`, such as "you know" and "i mean", never match, because the filter compares one token at a time.
- An utterance with no spaces is returned as its own gist, without an LLM call.
- `get_gist` returns an empty string when the LLM reply cannot be parsed.
- `GistNormalizer` returns an empty string for blank input.
- `add_synonym` sets the gist to the normalized text. The code says the gist normalizer is not wired in yet.
- `add_synonym` returns `False` for an existing verbatim question and on any error. An embedding the API could not produce is stored as NULL.
- The `Normalizer` is a singleton and loads the spaCy model named by `spacy model name`, default `en_core_web_sm`. It raises `RuntimeError` if that model is not installed.
