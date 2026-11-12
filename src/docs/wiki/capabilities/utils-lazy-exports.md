---
capability: utils-lazy-exports
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.lazy_exports.lazy_exports@e8d5f211e3
---
# Lazy package re-exports

One helper that the `cosa.rest.db` and `cosa.rest.db.repositories` packages share, to re-export names without importing their submodules at package load.

## What it does
- `lazy_exports( package_name, package_globals, lazy_map )` returns a `__getattr__` and a `__dir__` for a package to bind at its top level.
- The first read of a mapped name imports its submodule, stores the name in the package's globals and returns it. Later reads skip the hook.
- A name that is not in the map raises `AttributeError`, so a real submodule import still resolves the normal way.
- `__dir__` lists the real attributes and the lazy names together.

## Don't
- Don't use it where a name must exist at import time. Reading `__all__` is fine; reading the name loads the submodule.

## Invariants
- Importing the package never imports a mapped submodule, so a spec lookup on any submodule stays light and does not load SQLAlchemy ([[db-repositories]]).
