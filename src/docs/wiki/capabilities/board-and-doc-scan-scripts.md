---
capability: board-and-doc-scan-scripts
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.fix_api_md_tables.join_split_rows@d7605cec42
  - scripts.fix_api_md_tables.main@08c26d9cad
  - scripts.scan-epic-key-drift.fetch_board@004f641af7
  - scripts.scan-epic-key-drift.fetch_known_epic_keys@865253f836
  - scripts.scan-epic-key-drift.render@7d9db1ca43
  - scripts.scan-epic-key-drift.main@56b59d4bef
  - scripts.scan-prose-task-refs.fetch_board@c6db60b232
  - scripts.scan-prose-task-refs.main@f8224a4150
---
# Task board and API doc scan scripts
Scripts that run a detector against the live task board or repair a generated doc.
- `scan-epic-key-drift.py` runs the epic-key drift detector against the live board. `fetch_board` pages the board and says whether it was cut short.
- `fetch_known_epic_keys` reads the hand-kept epic keys from the API, and returns None when it cannot. `render` prints the report, with how far the scan reached.
- `scan-prose-task-refs.py` runs the prose task-reference detector. Its `fetch_board` pages the whole board, terminal rows included.
- `fix_api_md_tables.py` joins the table rows that `openapi-to-markdown` breaks across two lines. `join_split_rows` does the join.
- Each `main` is the command line entry. The last one rewrites a file only when a row was joined.
