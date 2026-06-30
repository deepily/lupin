# Pass-1 Design Review — LanceDB → PostgreSQL + pgvector Migration

**Reviewer**: Cheech 🌿 (session `ab940049`) · **Date**: 2026-06-30
**For manager**: Mr. Radio 🦉 (session `ef70b5f4`)
**Doc under review**: `src/rnd/v0.2.0/2026.06.30-lancedb-to-postgres-pgvector-migration-design.md`
**Review type**: Adversarial Pass-1 (`/plan-review-cascaded`: REUSE → **Pass-1**)
**Method**: every load-bearing claim verified against LIVE code (file:line cited). Confirm-with-evidence treated as a valid result; no manufactured findings.

---

## VERDICT: **APPROVE-WITH-REVISIONS**

The core architecture is sound and unusually well-grounded: the **additive-Postgres** premise and the **pgvector image gap** are both *correct against live code*, the schema vector-count inventory is *accurate*, and the no-migration-code backfill framing is *doctrine-consistent*. Two correctness/design items (**F1 distance metric**, **F2 index scope**) and a surface-completeness gap (**F3**) must be revised before implementation — but none are architecture-breaking, so this is REVISIONS, not REWORK.

---

## Confirmed-correct claims (positive verification — no action)

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| C1 | **Additive-Postgres** — Lupin already runs Postgres + a full DAO layer; migration reuses it | ✅ CONFIRMED | `src/cosa/rest/db/database.py` (engine/session), `src/cosa/rest/postgres_models.py` (49 KB of models), `src/cosa/rest/db/auto_migrate.py` + alembic, `src/cosa/rest/db/repositories/` (14 repos: user/task/notification/proxy_decision/prediction_log/…). Migration is genuinely additive — no new DB stand-up. |
| C2 | **pgvector image gap** — stock postgres image has no pgvector | ✅ CONFIRMED | `docker-compose.yml:6` = `postgres:16.3-alpine` (no pgvector). Remedy `pgvector/pgvector:pg16` valid; same **PG major 16** → data-volume at `lupin-data/postgresql-dev-data` is compatible (sound). Cloud-SQL pgvector-native claim is reasonable. `--force-recreate` caveat correctly noted. |
| C3 | **Schema vector-count inventory** — 5 tables / 9 vector cols; gist_cache scalar-only | ✅ CONFIRMED | input_and_output ×2 (`:128`,`:131`), question_embeddings ×1 (`:131`), embedding_cache ×1 (`:161`), gist_cache **×0** (`:119-125`), canonical_synonyms ×3 (`:189-191`), query_log ×2 (`:178-179`). Net = **5 tables / 9 vector cols** ✓. |
| C4 | **Embedding dim 768** (no live 1536) | ✅ CONFIRMED (code-level) | `lupin-app.ini:411` `embedding dimensions = 768`; all tables read this key w/ default 768 (`input_and_output_table.py:46`, `canonical_synonyms_table.py:62`). `_validate_embedding_dimensions` *auto-drops* a dim-mismatched table — so a stray 1536 table self-heals. Live-row confirmation appropriately still owed (Q3/Q6 sliver). |
| C5 | **Backfill-vs-fresh framing (§5)** — caches fresh-start; input_and_output one-time OFFLINE utility | ✅ SOUND | Doctrine `feedback_no_migration_code` bans *in-app backward-compat* code, not a one-time off-tree export. Caches → drop+recreate ✓; input_and_output → off-tree utility OR fresh-start, correctly surfaced as Rick's call (Q1). |
| C6 | **HNSW > IVFFlat** for the genuine ANN target | ✅ SOUND (but over-applied — see F2) | Incremental-insert + small/medium row counts is exactly HNSW's sweet spot; IVFFlat centroid-drift reasoning is correct. The *reasoning* is right; the *scope* is wrong (F2). |

---

## Findings (severity-ranked)

### F1 — HIGH — Live distance metric is **`dot` (inner product), NOT cosine**; the doc's whole metric premise is factually wrong

The doc assumes cosine throughout — §4.2 "recommend HNSW (`vector_cosine_ops`)", §4.2 "cosine assumed", §11 risk only contemplates "**L2 not cosine**", Q2 "Confirm LanceDB's current metric is cosine." **Live code uses dot product:**

- `lancedb_solution_manager.py:1382` / `:1503` / `:1625` → `.metric( "dot" )`
- `input_and_output_table.py:303` → `.metric( "dot" )`; `:282` comment "Uses dot product similarity metric"
- inline comments confirm: "With dot metric, `_distance = 1 - dot_product`" (`:1393`, `:1517`, `:1639`)

The doc never contemplates that the actual metric is `dot` — its §11 risk register only worries about L2-vs-cosine, so it would send implementers to "confirm cosine" when they must "confirm **dot**."

**Mitigating fact (verified)**: embeddings are **L2-normalized** — `local_embedding_engine.py:402` (`torch.nn.functional.normalize(p=2,dim=1)`), module docstring "L2-normalized output" (`:8`,`:28`,`:161`,`:250`). For unit vectors, **dot ≡ cosine** (identical ordering). So pgvector `vector_cosine_ops` (`<=>`) will produce the same neighbors as the live `dot` metric **iff every stored/queried vector is unit-norm**. That makes the *cosine operator choice defensible* — but the doc reaches it by a wrong route and never states the load-bearing invariant.

**Revision asks**:
1. Correct §4.2/§11/Q2: live metric is **dot product**, not cosine.
2. State the operator decision explicitly: either `vector_ip_ops`/`<#>` to match dot directly, OR `vector_cosine_ops`/`<=>` **justified by the L2-normalization invariant** (recommended — cosine is robust and ≡ dot under unit-norm).
3. Verify the **OpenAI embedding path** also normalizes (local path is confirmed; OpenAI path passes `normalize_for_cache=True` — `embedding_provider.py:422` — but the OpenAI engine's actual unit-norm guarantee was not located in `cosa/memory/` and must be confirmed). If OpenAI vectors are not unit-norm, cosine ≠ dot for that path.
4. The §7 equivalence harness must compare Postgres results against the **dot** baseline, not cosine.

---

### F2 — HIGH/MEDIUM — Index strategy is over-broad: **~6-7 of 9 vector columns are KV caches / write-only telemetry that are NEVER vector-searched**

The doc proposes "HNSW + cosine" uniformly across the vector surface (§4.2, §8 P1, §10 Q2). Live code shows most vector columns are **stored values retrieved by an exact scalar key**, not ANN search targets:

| Table.column | Retrieval pattern | ANN search target? | Evidence |
|---|---|---|---|
| `embedding_cache.embedding` | `get_cached_embedding(normalized_text)` — KV by text | **No** | `embedding_cache_table.py:205` (no `.search(vector)`/`.metric()` anywhere) |
| `question_embeddings.embedding` | `get_embedding(question)` via `.where(question=…)` | **No** | `question_embeddings_table.py:166`,`:187` |
| `canonical_synonyms.embedding_*` ×3 | "**exact match (NOT search().where() which requires vector)**" | **No** (retrieval) | `canonical_synonyms_table.py:322`,`:371`,`:420` |
| `query_log.embedding_*` ×2 | write-only telemetry; reads are scalar (`get_recent_queries`, `get_cache_hit_stats`) | **No** | `query_log_table.py:198`,`:297`,`:335` |
| `input_and_output.input_embedding` | `.search(vec, vector_column_name="input_embedding").metric("dot")` | **YES** | `input_and_output_table.py:302-303` |
| `input_and_output.output_final_embedding` | stored; no live vector search located | Unverified | — |

**Consequences of indexing all 9**:
- Self-inflicts the §11 "HNSW build memory" risk on columns that gain nothing from an index.
- Misses what these tables *actually* need in Postgres: **btree / unique indexes on the scalar key columns** (`normalized_text`, `question`, exact-text columns) that today's `.where(... = ...)` lookups depend on. The doc has zero mention of scalar indexes.

**Revision asks**:
1. Make the index plan **per-column, gated on "is this column an ANN search target?"** Index HNSW only on columns actually searched (`input_and_output.input_embedding`, plus the CBR / decision-proxy / prediction-engine consumers — see F3, and confirm `output_final_embedding` + `canonical_synonyms` similarity needs).
2. Add the required **scalar/unique indexes** on the exact-match key columns for the KV-cache tables.
3. `query_log` vectors are pure telemetry — store as plain `vector(768)` columns with **no index** (or reconsider storing them at all).

---

### F3 — MEDIUM — Migration-surface inventory is incomplete (P3 "swap call sites" would miss live consumers)

§3 says "Eight modules under `cosa/memory/` … plus two consumers (`proxy_decision_embeddings.py`, `system.py`)." Live grep finds additional real consumers/call-sites the doc omits:

- **`prediction_engine.py`** — a *third* LanceDB consumer with its **own** table config key `prediction engine lancedb table` and `self.lancedb_table`, doing CBR retrieval (`prediction_engine.py:17`,`:62`,`:107`,`:145`). Completely absent from the doc.
- **`main.py:477-480`** — startup wiring instantiates the manager: `manager_type.lower() == "lancedb"` reading `solution snapshots lancedb path` / `… table`. A P3 call-site the doc doesn't list.
- **`solution_manager_factory.py`** — backend factory (`LANCEDB = "lancedb"`, `create_manager("lancedb", …)` — `:19`,`:86`).
- **`gister.py:63`** — opens the LanceDB `db_uri` directly.
- **decision-proxy write path** is in **`responder.py:256-257`,`:331-339`** (initializes the store + writes embeddings), not only `proxy_decision_embeddings.py` — the doc names the wrong/partial module.
- `snapshot_manager_interface.py` (ABC), `file_based_solution_manager.py` (DEPRECATED) — touch the abstraction; lower priority but should be acknowledged.

**Revision ask**: expand the §3 inventory and §8 P3 to enumerate `prediction_engine`, `main.py` startup wiring, `solution_manager_factory`, `gister`, and the `responder.py` write path. Note the "eight modules" count is also internally inconsistent (the §3 table lists only 7 memory modules; live grep shows 11 referencing the token).

---

### F4 — MEDIUM — `gist_cache` table-name error; the doc's own "_tbl-suffix gotcha" P0 finding is itself incomplete

§3 lists gist_cache's table name as **`gist_cache_tbl`**. The actual table name is **`gist_cache`** (no `_tbl`): `gist_cache_table.py:50` (`table_name: str = "gist_cache"`), `:65`, `:130` (`db.create_table( table_name, … )`). Only the *Python variable* is `_gist_cache_tbl`.

So the P0 "gotcha" — "canonical_synonyms and query_log **drop the `_tbl` suffix**" — should read **three** tables: `gist_cache`, `canonical_synonyms`, `query_log`. The doc's signature selling point ("the P0 dump caught the suffix gotchas") missed one of the three. Minor in code terms, but it undermines confidence in the inventory and would yield a wrong table-name mapping if taken at face value.

**Revision ask**: correct §3 row to `gist_cache`; update the P0 finding to name all three suffix-dropping tables.

---

### F5 — LOW/MEDIUM — GCS-backed LanceDB path (cloud-test/prod) not addressed in cutover/teardown

The current snapshot store has a **GCS-synced** dimension in cloud envs (`lancedb_solution_manager.py` + `solution_manager_factory.py` + `cosa/utils/util_gcs.py`, exercised by `test_lancedb_gcs_manager.py` / `test_lancedb_gcs_integration.py`). The doc's "Cloud-SQL needs no image change" correctly handles the Postgres *engine* side, but §6/§11 never address that the *existing* cloud lancedb store + its GCS sync code must also be retired at teardown.

**Revision ask**: add a cloud-env line to §6 cutover/teardown — retire the GCS-synced lancedb store + its sync path, not just the local on-disk store.

---

### F6 — LOW — DDL gotcha: a column name contains a space

`query_log_table.py:190` defines `pa.field( "normalization version", pa.string() )` — a **space** in the column name. In Postgres this needs double-quoting (`"normalization version"`) or, preferably, renaming to `normalization_version` per the project's underscore-naming doctrine. Also `input_and_output` has a `solution_path_wo_root` scalar (`:132`) omitted from the §4.1 example SQL (doc acknowledges "remaining columns" as a Phase-1 task — OK, just confirming).

**Revision ask**: flag the spaced column for rename during the P0 → §4.1 full-schema task.

---

### F7 — LOW — "Eight modules" prose is internally inconsistent

§3 prose says "Eight modules under `cosa/memory/`" but its own table lists 7 memory rows; live grep shows 11 memory modules referencing the token. Cosmetic; reconcile the count when expanding for F3.

---

## Summary for Mr. Radio

- **Verdict**: APPROVE-WITH-REVISIONS. Architecture is sound; the additive premise, image gap, schema counts, dim, and backfill framing all verify clean.
- **Must-fix before implementation**: **F1** (metric is `dot` not cosine — correct the premise + state the L2-norm invariant that rescues cosine + verify OpenAI path), **F2** (index only the columns actually ANN-searched + add scalar/unique indexes for the KV caches), **F3** (enumerate the missing consumers: prediction_engine, main.py wiring, factory, gister, responder write path).
- **Should-fix**: **F4** (gist_cache table-name + complete the suffix-gotcha list), **F5** (GCS teardown).
- **Nice-to-have**: **F6** (spaced column), **F7** (count reconciliation).

No fatal/architecture-breaking defects found. Once F1-F3 are folded in, this is ready for Pass-2 (ownership-language audit).
