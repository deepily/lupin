---
capability: needset-key-neighbours
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.keys.twins_of@e792508cf7
  - lupin_mcp.reuse_needset.keys.assign_routes@fc0df60129
  - lupin_mcp.reuse_needset.keys.KeyContext@dd000d6769
  - lupin_mcp.reuse_needset.keys.unlike@f9522a990b
  - lupin_mcp.reuse_needset.keys.target_lang@6b73cb183e
  - lupin_mcp.reuse_needset.keys.vector_candidates@b345d7d4df
  - lupin_mcp.reuse_needset.keys.sampled_candidates@1248cceda5
  - lupin_mcp.reuse_needset.keys.work_alike_candidates@7970c582b2
---
# Need set: key neighbours

Finds the neighbours of a seed symbol that might do its job. A work-alike seed gets a route. The vector route ranks by the stored vectors, and the sampled route uses none of them. The rulings that follow are on [[needset-key-rulings]].

## Twins and routes
- `twins_of` lists the other members of the seed's twin group that are in the index, sorted. Ids the index lacks are left out.
- `assign_routes` gives each work-alike seed a route, half and half, with the vector route taking the first of an odd count. The same ids and seed always give the same answer, whatever order the ids arrive in.
- `KeyContext` holds what the neighbour search reads: the pool, measures, bodies, vectors and the seed.
- `target_lang` is the seed's own language, or the other one for a cross-language need.
- `unlike` keeps the ids, in order and without the seed, whose shingle overlap with the seed is under 0.5.

## Candidate lists
- `vector_candidates` ranks neighbours by cosine over the stored vectors. It uses the seed's own stored row as the query, so no text is embedded. It returns up to ten unlike neighbours in the target language, nearest first.
- It raises `SEED_NOT_VECTORISED` when there is no vector set or the seed has no row in it.
- `sampled_candidates` chooses neighbours without vectors from three sources: word overlap, the same directory and a random draw. Each gives up to ten, without repeats.
- The order is a seeded shuffle of all three, so the first ones asked about are not the word-search hits. The directory and random picks depend only on the draw seed and the seed symbol.
- `work_alike_candidates` lists the neighbours for the vector or the sampled route, with the source of each id. The sampled route never reads the vector set. Any other route raises `BAD_ROUTE`.
