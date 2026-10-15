---
capability: repo-tools-symindex-core-routes-diff-dups
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.symindex.routes.resolve@0cd5fe056b
  - cosa.repo.symindex.routes.route_decorators@a7ab915c88
  - cosa.repo.symindex.routes.scan_file@0e0801163e
  - cosa.repo.symindex.diff.diff_generations@3eb03df69a
  - cosa.repo.symindex.diff.diff_symbols@ec99b87165
  - cosa.repo.symindex.dups.find_duplicates@3d7d8aa77c
  - cosa.repo.symindex.dups.normalised@101cc1f5bc
  - cosa.repo.symindex.dups.shingles@dfe8deda0f
  - cosa.repo.symindex.dups.shingles_of@7f505af0ab
---
# Symbol index: routes, diff and duplicates

Three smaller readers over the same tree. `routes.md` comes from the first, `diff` and `dups` are CLI subcommands ([[symbol-index]]).

## Routes (`routes.py`)
- `route_decorators( node )` lists `( receiver, method, path )` for each `@x.get/post/put/patch/delete/websocket( "literal" )` on a def. A first argument that is not a string literal is skipped.
- `scan_file( tree )` returns `( routers, includes, imports )`. Those are the prefix of each `APIRouter` or `FastAPI` variable, the `include_router` calls as `( base, attr, prefix )`, and import aliases. A call whose first argument is not a name or `name.attr` is skipped.
- `resolve( per_file )` returns sorted lines `METHOD /path -> symbol  (file)`. An include prefix applies only to the router it names, and a receiver that is not a known router makes no route. The live app is never imported.

## Diff (`diff.py`)
- `diff_symbols( old, new )` compares two record lists by id and returns `added`, `removed` and `changed` (`id`, `was`, `now`). A symbol is changed when its pin differs.
- `diff_generations( old_gen, new_gen, all_symbols=False )` reads two folders. If their pin algorithms differ it returns only `algorithm_changed` with `was` and `now`. With `all_symbols` it also compares private and nested definitions.

## Duplicates (`dups.py`)
- `find_duplicates( spec, paths, min_nodes=25, threshold=0.85, js_files=(), include_private=True )` returns `provenance`, `exact` and `near`. Definitions under `min_nodes` AST nodes are left out.
- `normalised( node )` erases docstrings, names, constants and decorators; two defs of the same language with equal normalised trees are an exact group.
- `shingles( node )` and `shingles_of( seq )` hash 5-long windows over the pre-order node-type list. A near pair is two defs whose shingle sets reach the Jaccard threshold and whose trees differ. Only pairs that share one of each definition's rarest shingles are compared, so a pair above the threshold can be missed.
- Python and script definitions are never grouped or paired together. A repeated id is numbered `~2`, `~3`.
