---
capability: util-console-args-and-xml-helpers
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.utils.util.add_to_path@515434116b
  - cosa.utils.util.generate_domain_names@5bc45fc92c
  - cosa.utils.util.get_name_value_pairs@b4c3d91a27
  - cosa.utils.util.get_name_value_pairs_v2@552209378a
  - cosa.utils.util.init@394b917b41
  - cosa.utils.util.print_banner@13cc8fb6d4
  - cosa.utils.util.print_list@da4fe0aee6
  - cosa.utils.util.print_simple_file_list@a62af1daab
  - cosa.utils.util.print_stack_trace@4878d56af6
  - cosa.utils.util.truncate_string@ede0cb670e
  - cosa.utils.util_xml.get_nested_list@a0fdcee8e1
  - cosa.utils.util_xml.get_value_by_xml_tag_name@b410c0e986
  - cosa.utils.util_xml.get_xml_tag_and_value_by_name@876202fc8c
  - cosa.utils.util_xml.remove_xml_escapes@b037863946
  - cosa.utils.util_xml.rescue_code_using_tick_tick_tick_syntax@8361935f69
  - cosa.utils.util_xml.strip_all_white_space@e46d58d72a
---
# Console printing, name=value arguments and legacy xml helpers

Console and argument helpers in `cosa.utils.util`, and the deprecated `util_xml` tag readers.

## What it does
- `get_name_value_pairs( argv )` and `get_name_value_pairs_v2( argv, decode_spaces=True )` turn `name=value` arguments into a dict and skip element 0. V2 turns `+` into a space and prints every argument.
- `print_banner( msg, expletive, flex, ... )`, `print_list` and `print_simple_file_list( path )` (runs `ls -alh`) print to the console.
- `print_stack_trace( exception, explanation, caller, debug )` always prints the exception type and message. It prints the frames only when `debug=True`.
- `truncate_string( s, max_len=64 )` cuts a string. `generate_domain_names( count )` makes random test names. `add_to_path( path, idx )` adds to `sys.path` once. `init( debug )` sets the debug flag.
- `util_xml` is deprecated and warns on import. New code uses `cosa.agents.io_models.xml_models`. It holds `get_value_by_xml_tag_name`, `get_xml_tag_and_value_by_name`, `remove_xml_escapes` and `strip_all_white_space`.
- `get_nested_list` returns the `<line>` tags inside a parent tag, default `code`. `rescue_code_using_tick_tick_tick_syntax` wraps a fenced python block in `<line>` tags, or returns an empty string.

## Don't
- A value may contain `=`. Both versions split on the first `=` only, so `url=http://h/?a=b` keeps `http://h/?a=b`.
- Do not expect `get_value_by_xml_tag_name` to raise on a missing tag. With no default it returns an `Error:` text.

## Invariants
- `truncate_string` returns up to `max_len + 3` characters, because the three dots are added after the cut. `print_banner( flex=True )` also prints the bar length.
- `get_value_by_xml_tag_name` takes the first `<name>` span. `get_nested_list` only reads lines that carry the whole `<line>...</line>` on one line.
