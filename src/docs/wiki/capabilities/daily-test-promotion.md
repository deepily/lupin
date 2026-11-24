---
capability: daily-test-promotion
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - lupin_mcp.daily_test_promotion.run_command@a527b067c4
  - lupin_mcp.daily_test_promotion.Vm@ae33149811
  - lupin_mcp.daily_test_promotion.app_zone@e031c76b17
  - lupin_mcp.daily_test_promotion.due@3f37e475b2
  - lupin_mcp.daily_test_promotion.row_payload@3e2f5b0afd
  - lupin_mcp.daily_test_promotion.pick_sha@133bd46536
  - lupin_mcp.daily_test_promotion.with_ref@2b0a221483
  - lupin_mcp.daily_test_promotion.holds_commit@8459d49b48
  - lupin_mcp.daily_test_promotion.deploy_and_smoke@b7375d926e
  - lupin_mcp.daily_test_promotion.behind_state@7a0a16ad66
  - lupin_mcp.daily_test_promotion.stale_due@5a11d4c356
  - lupin_mcp.daily_test_promotion.promote@dcdfa84854
  - lupin_mcp.daily_test_promotion.settle@6dba8aa66b
  - lupin_mcp.daily_test_promotion.decide@cba445859e
  - lupin_mcp.daily_test_promotion.conclude@08bf058178
  - lupin_mcp.daily_test_promotion.run@7963fc3ba4
  - lupin_mcp.daily_test_promotion.main@f23110400d
  - lupin_mcp.daily_test_promotion.registry_owner@47fddd468a
---
# Daily test promotion

`lupin_mcp.daily_test_promotion` moves the newest merged build to the cloud test VM once a day and smokes it. It is the registry job `test-promotion`, run through `cron-job.sh` and `job_run`, and its switch `cron job test-promotion enabled` ships false.

## One run
- `run` takes a lock, then asks `due`. A cron or hand entry is always due. A boot entry runs only when no attempt follows the latest 18:00 slot. `job_cron.cron_last` finds it in the zone `app_zone` reads from the `app timezone` key.
- `pick_sha` takes the tip of the working branch. A stored `last_promoted_sha` equal to it ends the run with no VM call.
- Otherwise `decide` starts the VM if it is not running and reads the sha it runs. That is the first field of the first output line that starts with a 40-digit sha. The wrapper's own `[lupin-vm] + ...` echo line is skipped. An equal sha ends the run. A busy or unknown test server defers it. The VM goes back to its earlier power state.

## Deploy and rollback
- `promote` puts a temporary branch `promote/test-<sha>` at the pick, runs `lupin-vm.sh deploy` on it, then smokes. `with_ref` deletes the branch whether the action returns or raises.
- The smoke is the VM's own post preflight plus a venue-idle read. The tester login is checked on the VM from its own secret files, so this job holds no credential.
- A failed deploy or smoke redeploys the sha the VM ran before the deploy, then smokes again. A previous sha this checkout lacks makes the rollback fail, and the row says so.

## Rows
- `main` gets the failure-row owner from `registry_owner`, the registry's `test-promotion` owner as a store persona key, unless `--owner` is given. A registry with no such entry raises `ValueError`. A `--check` run files no row and needs no owner.
- `conclude` writes the job summary and the state, and files at most one row through `row_payload`, at priority P5. The store lets a worker file only at P5, and a manager raises it. The key names the kind and the sha, so a repeat is one row. Kinds are failed, rollback-failed, vm-unreachable and stale. `behind_state` and `stale_due` file stale once per stretch, after 3 days behind, counting deferrals.
