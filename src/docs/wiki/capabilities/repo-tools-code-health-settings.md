---
capability: repo-tools-code-health-settings
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.code_health_settings.CodeHealthSettingError@3886071770
  - cosa.repo.code_health_settings.repo_key@30bc8ac55c
  - cosa.repo.code_health_settings.read_text@4dbb975cea
  - cosa.repo.code_health_settings.read_entries@6ebd7bf72f
  - cosa.repo.code_health_settings.read_positive_int@d3ba262ce5
  - cosa.repo.code_health_settings.check_relative@cc2a90655b
  - cosa.repo.code_health_settings.index_languages@22d62174b6
  - cosa.repo.code_health_settings.relative_paths@c9b0c77bdb
  - cosa.repo.code_health_settings.index_exclude@cacd233598
  - cosa.repo.code_health_settings.wiki_dir@8f4c509f54
  - cosa.repo.code_health_settings.filed_title_prefix@2ee0b01577
  - cosa.repo.code_health_settings.duplicate_check_ceiling@43d8bd203d
  - cosa.repo.code_health_settings.jev_token_limit@1314be1287
  - cosa.repo.code_health_settings.data_subdir@074c3255ea
  - cosa.repo.code_health_settings.data_dir@0e71aba9d8
  - cosa.repo.code_health_settings.repo_settings@298caa839f
  - cosa.repo.code_health_settings.registry_repo_names@17742a2b75
  - cosa.repo.code_health_settings.name_mismatches@07f8a1b7c2
  - cosa.repo.code_health_settings.check_registry_names@c4061ea4ba
  - cosa.repo.symindex.spec.detected_spec@7a0be26984
  - cosa.repo.symindex.spec.configured_dirs@c4d697d6ed
  - cosa.repo.symindex.spec.check_module_base@3c8c9be41b
  - cosa.repo.symindex.spec.override_spec@f7380a240d
---
# Code-health settings: per-repo keys in Lupin's INI
`cosa.repo.code_health_settings` reads the code-health settings of one repo through `ConfigurationManager`. Each per-repo key is named `external repo <name> <kind>`, and one global key, `code health data subdir`, names the data folder. Every key has a twin in `src/conf/lupin-app-splainer.ini`.

## Rules
- A blank or absent detection key (`index languages`, `index source dirs`, `index test dirs`, `index exclude`, `wiki dir`) means detect. The reader returns an empty list, or None for `wiki dir`.
- `filed title prefix` falls back to the repo name in capitals inside brackets. `data_subdir` falls back to `code-health`, and `data_dir( root )` is `<fleet data root>/<data subdir>`, outside the repo tree.
- `duplicate check ceiling` and `jev token limit` have no code default. `read_positive_int` refuses a blank, zero, negative or non-numeric value and names the key.
- A path entry is refused when it is absolute or holds `..`. An `index exclude` entry is refused when it holds a slash. A language outside py, ts and dart is refused.
- `registry_repo_names` lists the repos with a row in `src/conf/job-registry.json`, and `name_mismatches` reports a name that differs from its checkout's directory name. `check_registry_names( registry, config )` raises, naming each repo whose name differs from its directory name or that lacks `external repo <name> path`. An empty registry also raises.
- `spec_for( root, config, name )` and `tests_spec( root, config, name )` read the four `index` keys. With no config they return the detected spec, `detected_spec`.
- `override_spec` applies the keys field by field. Source dirs go to the roots of each listed language: py to `py_roots`, ts to `js_roots`, dart to `dart_roots`. A source or test dir that is not a directory is refused, naming the key.
- Exclude names replace the skip set, and `tests_spec` still lets `tests` through. The librarian, filing and daily-check modules adopt the other keys in later steps. `module_base` stays derived: `src` for a lupin tree, the root otherwise, with no INI key. `check_module_base` refuses source dirs that all lie under `src/` in another tree.
