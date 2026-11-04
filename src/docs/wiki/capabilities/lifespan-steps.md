---
capability: lifespan-steps
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_app.lifespan_steps.print_migration_banner@9858fdf3b2
  - lupin_app.lifespan_steps.build_snapshot_manager_config@b6ea3172c9
  - lupin_app.lifespan_steps.recover_interrupted_jobs@fd4ab31704
  - lupin_app.lifespan_steps.restore_jobs_at_boot@3942ba8eee
  - lupin_app.lifespan_steps.probe_model_server@ec9250b87f
  - lupin_app.lifespan_steps.load_local_models@5edf7d481e
  - lupin_app.lifespan_steps.load_models@9aa910e39b
  - lupin_app.lifespan_steps.build_commons_owner_resolver@2c98c6c832
  - lupin_app.lifespan_steps.install_llm_disambiguator@36e675b3c5
  - lupin_app.lifespan_steps.start_commons@7d41f9acde
  - lupin_app.lifespan_steps.init_commons@09de028eab
  - lupin_app.lifespan_steps.start_websocket_maintenance_tasks@c5a6fbd19e
  - lupin_app.lifespan_steps.start_notification_sweep_task@d9254f3b5e
  - lupin_app.lifespan_steps.schedule_all_clear@4ea46590f4
  - lupin_app.lifespan_steps.print_all_clear_receipt@e433965323
  - lupin_app.lifespan_steps.record_clean_shutdown@688f951127
  - lupin_app.lifespan_steps.cancel_background_task@ac52604348
  - lupin_app.lifespan_steps.shutdown_fcm_wake@38f5890955
  - lupin_app.lifespan_steps.drain_agentic_pool@768b55ba7f
  - lupin_app.lifespan_steps.stop_consumer_thread@b0a82f9638
  - lupin_app.lifespan_steps.cancel_peer_watchers@ab4e920093
  - lupin_app.lifespan_steps.stop_commons_watcher@d7907803ea
---
# Lifespan steps

`src/lupin_app/lifespan_steps.py` holds the startup and shutdown steps that `lifespan` in `main.py` calls. Each step takes its collaborators as arguments, so a unit test drives every branch without a server.

## Startup
- `load_models` reads `speech to text provider`. The value `model-server` declares remote-only and calls `probe_model_server`; any other value calls `load_local_models`.
- `init_commons` calls `start_commons` when `commons enabled` is true. It keeps whatever was built before a failure on the state object it was given.
- `start_websocket_maintenance_tasks` and `start_notification_sweep_task` read their INI switches. The sweep switch defaults to false.
- `schedule_all_clear`, `recover_interrupted_jobs`, `restore_jobs_at_boot` and `print_migration_banner` each catch a failure and print a warning, so boot goes on.

## Shutdown
- `cancel_background_task` and `stop_commons_watcher` accept `None` and do nothing. The other stop steps print a line when they fail and carry on.
