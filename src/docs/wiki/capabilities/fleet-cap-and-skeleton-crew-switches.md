---
capability: fleet-cap-and-skeleton-crew-switches
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - lupin_mcp.fleet_cap_ini_io.KeyNotFound@478ea2b537
  - lupin_mcp.fleet_cap_ini_io.KeyDefinedTwice@60defb02e4
  - lupin_mcp.fleet_cap_ini_io.Definition@cefce6894a
  - lupin_mcp.fleet_cap_ini_io.find_definitions@40074d6f89
  - lupin_mcp.fleet_cap_ini_io.active_block@0927aefa89
  - lupin_mcp.fleet_cap_ini_io.inherit_chain@17d49b7bc9
  - lupin_mcp.fleet_cap_ini_io.pick_definition@e002252da8
  - lupin_mcp.fleet_cap_ini_io.locate_key@7791427bc7
  - lupin_mcp.fleet_cap_ini_io.read_value_from_disk@d345ad9907
  - lupin_mcp.fleet_cap_ini_io.read_int_from_disk@470828e9b2
  - lupin_mcp.fleet_cap_ini_io.write_int_to_disk@8c0473c409
  - lupin_mcp.fleet_cap_ini_io.write_bool_to_disk@271f8efd90
  - lupin_mcp.skeleton_crew.ini_path@a8c886309f
  - lupin_mcp.skeleton_crew.read_state_from_disk@ab841679f5
  - lupin_mcp.skeleton_crew.default_disk_skeleton_reader@291437c7fe
  - lupin_mcp.skeleton_crew.refusal_text@90f978faea
  - lupin_mcp.skeleton_crew.skeleton_crew_is_on@e99353cd8b
  - lupin_mcp.skeleton_crew.skeleton_crew_refusal@c7fba702e6
  - lupin_mcp.skeleton_crew.state_path@5a36d046a9
  - lupin_mcp.skeleton_crew.write_state_file@8a01cbb252
  - lupin_mcp.skeleton_crew.read_state_file@c16f1d59f6
  - lupin_mcp.skeleton_crew.settings_json_poke_muted@6606f1f1e3
  - lupin_mcp.skeleton_crew.describe@1f9a5878d3
  - lupin_mcp.skeleton_crew.is_on_quietly@07b95cb868
---
# Fleet cap and skeleton crew switches

Two operator dials live as single keys in `lupin-app.ini`. `fleet_cap_ini_io` reads and writes such keys, and `skeleton_crew` is the switch built on it. See [[seat-lifecycle]].

- `find_definitions( lines, key )` lists every line that defines the key, comments excluded. `locate_key( path, key )` returns the one `Definition` (line, section, raw text). That is the sole definition, or the one `pick_definition` chooses when several blocks define the key. It raises `KeyNotFound` when the key is absent. It raises `KeyDefinedTwice`, which names every line, when no definition is in the active block's chain or the nearest block defines it twice. `active_block` is the block this process loaded: the `config_block_id` in `LUPIN_CONFIG_MGR_CLI_ARGS` (a `+` reads as a space), else `Lupin: Development`. `inherit_chain( lines, block )` lists that block and each block it inherits from, nearest first, and ends on a cycle. `pick_definition( lines, found )` returns the definition in the nearest block of that chain, so a VM-only override beats the base. It returns None when it cannot choose.
- `read_value_from_disk` and `read_int_from_disk` parse the key fresh and return None when it is absent or unreadable, or when `pick_definition` cannot choose among several definitions. A non-integer reads as None, so the spawn path falls back to the configuration manager.
- `write_int_to_disk` and `write_bool_to_disk` replace only the value, atomically, under the config write lock ([[mcp-server-plumbing]]). They return what a re-read of the file says. A missing or duplicate key raises before any write. `write_bool_to_disk` can insert an absent key after the line of `insert_after`. Without that argument an absent key is refused.
- `ini_path` is the main checkout's configuration file, or the env override, so a seat in a worktree reads the live file. `read_state_from_disk` returns True or False, and True for a present value that is not a clean boolean. It returns None for an absent, duplicate or unreadable key. `default_disk_skeleton_reader` is that read for the live gates, and `is_on_quietly` is the same read without printing. Any failure reads as off.
- `skeleton_crew_is_on` takes the disk answer first, then the configuration manager, and defaults to off. `skeleton_crew_refusal( door )` returns the refusal text for a `spawn` or `launch`, or None when the switch is off. `refusal_text` words it.
- `state_path` is the attribution file beside the write lock, or beside the override file when the configuration file is overridden. `write_state_file( on, set_by )` records who flipped the switch, before the configuration file is written. `read_state_file` returns it or None.
- `settings_json_poke_muted` says whether the Stop poke is muted in the user's settings, or None when the file is unreadable. `describe` reports `on`, `since`, `set_by` and `settings_mute_while_off`. `since` and `set_by` show only while the record agrees with the file. On a disagreement `set_by` is the unknown-setter text.
