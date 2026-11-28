---
capability: bundle-and-bridge-check-scripts
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - scripts.check_bundle_freshness.BuildScriptError@2649363c08
  - scripts.check_bundle_freshness.short_sha@6892a5a2ef
  - scripts.check_bundle_freshness.parse_build_script@ff4d1045a3
  - scripts.check_bundle_freshness.consumers_of@19eab3ade1
  - scripts.check_bundle_freshness.discover_bundles@a141456a94
  - scripts.check_bundle_freshness.discover_harness_bundles@e285aab1bf
  - scripts.check_bundle_freshness.check_harness_bundle@8d22969e49
  - scripts.check_bundle_freshness.current_sha@ab7d539fe2
  - scripts.check_bundle_freshness.remedy@8812934aeb
  - scripts.check_bundle_freshness.format_report@a9527e455d
  - scripts.check_bundle_freshness.main@bd3361e88c
  - scripts.bridge_pin_sweep.helper_bodies@ecddf59ec2
  - scripts.bridge_pin_sweep.functions@4f5bd3acaf
  - scripts.bridge_pin_sweep.classify@3a6cb5c350
  - scripts.bridge_pin_sweep.self_test@76e82c55a6
---
# Bundle freshness and bridge pin check scripts
Two check scripts under `src/scripts/`. Each reports and changes nothing.
- `check_bundle_freshness.py` asks whether a rebuild would change the delivered bytes of a web bundle, by a dry-run build into a temporary directory.
- `parse_build_script` reads a `build-*.sh` driver and extracts what reproduces its production build, so the check cannot drift from the build.
- `BuildScriptError` is raised when a driver cannot be turned into a dry-run command. `short_sha` is the twelve-character sha256 prefix the build scripts use.
- `discover_bundles` finds each driver that emits a manifest, in sorted name order. A driver without a manifest is skipped here. `discover_harness_bundles` finds those: a driver such as `build-parity-harness.sh` that names each output in an `OUTFILE=` line. `check_harness_bundle` rebuilds one into a temp directory and compares it byte for byte with the shipped file, so a stale `parity-harness.js` is refused.
- `consumers_of` lists tracked files that load a bundle's output, not those that only name it. That tells a dormant port from a live 404.
- `current_sha` names the commit the report was taken at, short by default and in full with `short=False` ([[prediction-rerun-phases-script]]). `format_report` gives every bundle's name, source count and both hashes. Whenever a bundle was judged, it also says that a fresh bundle speaks only for this tree.
- `remedy( root, name )` gives the line that rebuilds one stale bundle: its `build-<name>.sh` driver, and `npm run build` only when `package.json` runs that driver.
- `main` returns the fresh code only when at least one bundle was judged and all were fresh. A stale bundle wins over one that could not be checked. A crash inside the checker returns exit 3 with a traceback. Python's own exit for an uncaught exception is 1, which would read as stale.
- `bridge_pin_sweep.py` finds tests that read live session-bridge state without pinning it. Such a test is green on one machine and red on another.
- `helper_bodies` maps each private helper to its body, so a pin inside a shared helper is seen. `functions` yields each test function and its body.
- `classify` returns the label, test name, drivers and unpinned names for one source. `self_test` proves the detector still fires and still stays quiet.
