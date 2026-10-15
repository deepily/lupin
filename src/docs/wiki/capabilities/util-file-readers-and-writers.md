---
capability: util-file-readers-and-writers
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.utils.util.find_files_with_prefix_and_suffix@4617985c84
  - cosa.utils.util.get_api_key@cdbd01816e
  - cosa.utils.util.get_file_as_dictionary@355b9e3104
  - cosa.utils.util.get_file_as_json@5291b44f0a
  - cosa.utils.util.get_file_as_list@96ab9e208f
  - cosa.utils.util.get_file_as_source_code_with_line_numbers@224ad871ce
  - cosa.utils.util.get_file_as_string@36fbf091ce
  - cosa.utils.util.get_files_as_strings@afef89f66c
  - cosa.utils.util.get_source_code_with_line_numbers@d89731a047
  - cosa.utils.util.is_jsonl@47b544a001
  - cosa.utils.util.sanity_check_file_path@99e81383ca
  - cosa.utils.util.write_lines_to_file@0c43460a67
  - cosa.utils.util.write_string_to_file@653c6e87d3
---
# File readers and writers in cosa.utils.util

Small functions in `cosa.utils.util` that read and write files. Path helpers are in [[shared-utilities]].

## What it does
- `get_file_as_string( path )` reads a whole file with the platform default encoding. `get_file_as_json( path )` parses JSON. `get_files_as_strings( paths )` reads several, in order.
- `get_file_as_list( path, ... )` reads UTF-8 lines. Flags: `lower_case`, `clean`, `strip_newlines`, `skip_empty`, `skip_comments` (lines starting `#`) and `randomize` (shuffled with `seed`, default 42).
- `get_file_as_dictionary( path )` parses `key = value` lines, split on the string `" = "`. It skips `#` and `//` comments and removes a leading or trailing `|`.
- `write_string_to_file` and `write_lines_to_file` overwrite the file. The lines version joins with a newline and can drop blank lines. With `world_read_write=True` it runs `chmod 0o666`.
- `get_file_as_source_code_with_line_numbers( path )` and `get_source_code_with_line_numbers( lines, join_str="" )` prefix each line with a 3-digit number and a space.
- `find_files_with_prefix_and_suffix( directory, prefix, suffix )` lists one directory level, not recursively. `sanity_check_file_path( path, silent )` is an `assert` that the file exists.
- `get_api_key( key_name )` reads `<root>/src/conf/keys/<key_name>` and strips it. It returns None after printing a banner when the file is missing.
- `is_jsonl( s )` is True when every line parses with `json.loads`.

## Don't
- Do not rely on `get_file_as_dictionary` for values that contain ` = `. It keeps only the piece before the next separator.
- Do not pass a list you still need to `get_source_code_with_line_numbers`. It rewrites the list items in place.
- Do not use `get_file_as_string` for non-ASCII files on a host whose default encoding is not UTF-8. `get_file_as_list` forces UTF-8.

## Invariants
- `is_jsonl` returns True for an empty string and False when any line, including a blank one, fails `json.loads`.
