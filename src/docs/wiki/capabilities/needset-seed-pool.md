---
capability: needset-seed-pool
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.pool.read_pool_symbols@bf3ba07224
  - lupin_mcp.reuse_needset.pool.is_test_path@cacfe6ec9b
  - lupin_mcp.reuse_needset.pool.Measure@f619491589
  - lupin_mcp.reuse_needset.pool.nth_record@37ae47604d
  - lupin_mcp.reuse_needset.pool.measure@5e44955c7e
  - lupin_mcp.reuse_needset.pool.eligible@117ac3fcf7
  - lupin_mcp.reuse_needset.pool.index_id@a769c3e70f
  - lupin_mcp.reuse_needset.pool.dups_manifest@669e7f08fc
  - lupin_mcp.reuse_needset.pool.twin_map@227d0cc962
  - lupin_mcp.reuse_needset.pool.cell_pool@358f669749
---
# Need set: seed pool

Decides which index symbols may seed a need, and in which kind-by-language cell. Twin groups come from the structural duplicate finder, through the grouping that already exists. The draw from this pool is on [[needset-records-and-quota]].

## Reading and eligibility
- `read_pool_symbols` reads the searchable symbols, public and private, from an index generation and names the reader. The manifest records the reader, because a draw made from other symbols would differ under the same seed.
- `is_test_path` is true for a path with a `tests`, `test` or `__tests__` directory, a `test_` file name, or a `.test.` or `.spec.` file name.
- `Measure` holds one definition's node count and structural shingles. `measure` computes it for every index record found in its source.
- Python records are measured from the AST. Script records use the compiler's node kinds, as the duplicate finder does.
- `nth_record` matches a script definition to the Nth record of its name in a file, because the compiler's shapes carry no line.
- `eligible` keeps the records that may seed a need. It counts the dropped ones under their first reason: other language, test, unmeasured, small or no docstring.

## Twins
- `index_id` maps an id of the duplicate finder to the id the index gives the same definition. A script id becomes its dotted file stem and name, and a repeat suffix becomes the index's number suffix.
- `dups_manifest` turns the finder's output into the manifest shape that the twin grouping reads.
- `twin_map` maps each definition to the other members of its twin group.

## Cells
- `cell_pool` builds the pool the census and the draw read, keyed by kind and language.
- A near copy needs a kept seed with at least one twin in the index.
- Work-alike and cross-language cells take every kept seed of that language.
- The `nothing` cell takes the files that hold at least three kept symbols of that language.
