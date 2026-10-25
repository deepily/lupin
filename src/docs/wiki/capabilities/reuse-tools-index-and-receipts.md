---
capability: reuse-tools-index-and-receipts
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_tools.module_of@c144285c7e
  - lupin_mcp.reuse_tools.scope_of_line@f957248139
  - lupin_mcp.reuse_tools.in_scope@06a204547a
  - lupin_mcp.reuse_tools.page_candidates@e79a42cea6
  - lupin_mcp.reuse_tools.pages_digest@482ad52b6b
  - lupin_mcp.reuse_tools.l0_lines@c26117957c
  - lupin_mcp.reuse_tools.index_sha@8ba0304f41
  - lupin_mcp.reuse_tools.save_snapshot@904c9675b2
  - lupin_mcp.reuse_tools.load_snapshot@e6cb174f8c
  - lupin_mcp.reuse_tools.store_receipt@158c25f8a3
  - lupin_mcp.reuse_tools.load_receipt@2b70d7341f
  - lupin_mcp.reuse_tools.known_routes_of@aa5f7f0b6b
  - lupin_mcp.reuse_tools.unscreened_path_count@1ed284be20
---
# Reuse tools: index, snapshots and receipts

How a reuse question finds its pages, freezes the index it judged, and stores the answer. The question itself is in [[reuse-tools-request-and-context]].

## Page scope
- `module_of` turns a `src/` Python file into its dotted module, or `None`. `scope_of_line` reads the module paths an index line covers. A package with a parenthesised module list covers only those modules. A package with no list, or with prose in the parenthesis, covers the whole package.
- `in_scope` is true when a file is an entry of the scope, whatever its language. Otherwise it is true for a Python file whose module, or a package above it, matches a scope path.
- `page_candidates` returns one entry per index bullet whose page exists and pins at least one indexed symbol. The scope adds the file of each pin the line does not already cover. A line the egress screen would drop is left out.

## Index and snapshot
- `l0_lines` returns the wiki index lines. `index_sha` hashes the symbols, those lines and the page pins, plus the tests hash when test records are read. Every receipt records it. `pages_digest` hashes each page's slug and scope.
- `save_snapshot` stores the searchable listing a call judged, public and private, compressed and written once. A call that read test records stores them after the others. It is not filtered by language; the receipt's language is applied again at replay.
- `load_snapshot` returns the entries and index lines. It raises `SNAPSHOT_MISSING` for no file and `SNAPSHOT_CORRUPT` for a damaged one or an entry short of its fields.

## Receipts
- `store_receipt` writes the receipt once. If one with that id already exists, that one is returned, so two callers asking the same question read one receipt.
- `load_receipt` refuses a bad id, then checks the field types. It recomputes the id from the stored inputs.
- Errors are `RECEIPT_MISSING`, `RECEIPT_CORRUPT`, and `RECEIPT_ID_MISMATCH` when the recomputed id or the tool version does not match.

## Paths sent to Jev
- `known_routes_of` reads the route paths from an index generation. With none, or an unreadable file, it returns no routes and the source `none`, so every absolute path is redacted.
- `unscreened_path_count` counts entries whose id, signature or docstring line still holds an absolute path that is not a known route. It remembers each verdict in a table that resets past a size limit.
