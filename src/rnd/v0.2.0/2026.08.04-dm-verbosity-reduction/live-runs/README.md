# live-runs — the data moved OUT of the repo (2026-08-13)

The six `.jsonl` run files that used to sit here are **not lost** — they were tracked
in git, which Rick ruled was wrong for accumulating corpus data, so they now live at:

```
/mnt/DATA01/include/www.deepily.ai/projects-data/lupin/dm-corpus/live-runs/
```

That is the same fleet data root every other runtime artifact uses (hold files, task-store
maps). The files were copied and verified byte-identical (`cmp`) before being removed here.

## Why out of the tree

A gitignored path *inside* a checkout is on `git clean -xdf`'s kill list, not shielded by
it — the same reasoning that moved the fleet's runtime state out (rows `8758d0b1` / `f56fc63b`).
Tracking them additionally meant every corpus append showed up as a source change.

## Where the LIVE corpus is written now

```
$LUPIN_DM_CORPUS_DIR/dm_traffic.jsonl          # containers: /var/lupin/dm-corpus
<fleet data root>/dm-corpus/dm_traffic.jsonl   # host-side derivation
```

Both names resolve to `<projects-data>/lupin/dm-corpus/`, bind-mounted into `:7999` and
`:8000`. Path resolution lives in `_resolve_dm_corpus_dir()` — `src/cosa/rest/routers/dm.py`.

⚠️ The mount and `LUPIN_DM_CORPUS_DIR` resolve at container **CREATE**, so picking them up
needs `docker compose up -d --force-recreate`, never a plain restart.

## Reading a row

Every row written from 2026-08-13 carries `corpus_schema_version: 3` and a provenance block
(`boot_id`, `pid`, `host`, `server_port`, `git_sha`, `writer`) identifying exactly which
process wrote it, plus both the **submitted** and **delivered** bodies and the tutor's
outcome. Rows written before that date have neither, and carry only the naive `sentences`
count rather than the canonical `claims` count.
