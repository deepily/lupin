---
capability: reuse-tie-to-lookup
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_tie.commit_facts@bff1db45c9
  - lupin_mcp.reuse_tie.find_tie@2b17d408b3
---
# Reuse: tie a duplicate to the lookup that should have caught it
`lupin_mcp.reuse_tie` answers one question for a duplicate found in the code: which lookup receipt, and which session, should have caught it? It writes no file, sends nothing and runs no model. The finding step uses the session to find a manager ([[reuse-merge-gate]]).

## What it does
- `find_tie( symbol, rows, records, root, sha )` tries two ways in order and returns `{ tie, receipt_id, session, tool }`.
- First, a review document's ruling line names the receipt. `rows` are the refusal records from `reuse_behaviour.read_refusals`, each with `pairs` of symbol id and receipt id. The latest record that pairs the symbol with a real receipt id wins, and a token such as `excluded` is not a receipt. The tie is `ruling`. `session` and `tool` are None when the call log does not hold the receipt. The commit is not read.
- Failing that, it takes the writing seat's latest `check_exists` receipt made before the commit. The writer is found from the persona name in the commit message, among personas that appear as callers in the call log. The tie is `heuristic`, with the persona added. It is a guess.
- A message that names no lookup persona, or more than one, gives tie `none` with a reason. The writer cannot be told from a reviewer. A persona with no earlier `check_exists` lookup also gives `none`.
- `tool` tells the caller whether the receipt holds a need text. Only `check_exists` does.
- `commit_facts( root, sha )` reads the commit's time (an aware datetime) and full message through `git show`. It raises `ValueError` when the commit is not in the repository.
