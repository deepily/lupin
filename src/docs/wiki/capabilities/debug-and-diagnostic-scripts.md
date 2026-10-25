---
capability: debug-and-diagnostic-scripts
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.debug.debug_proxy_script_matcher.banner@0d2c6f1838
  - scripts.debug.debug_proxy_script_matcher.pass_fail@474e6a9543
  - scripts.debug.debug_proxy_script_matcher.instrumented_run@49958a9562
  - scripts.debug.debug_queue_endpoint.test_queue_endpoint@daa7f3cd25
  - scripts.debug.debug_queue_state_monitoring.test_queue_state_monitoring_debug@28bbed5006
  - scripts.debug.debug_websocket_auth_validation.test_websocket_auth_validation@1964061112
  - scripts.debug.debug_websocket_connection.test_basic_connection@2784eb6574
  - scripts.test_websocket_notification.login_user@a426da6adf
  - scripts.test_websocket_notification.check_websocket_state_via_admin_api@7f7030163d
  - scripts.test_websocket_notification.send_notification@b3ec2bbc20
  - scripts.test_websocket_notification.main@dfc2f51299
---
# Debug and diagnostic scripts
Standalone diagnostics under `src/scripts/`. None needs pytest.
- `debug_proxy_script_matcher.py` reproduces the notification proxy's script-matching call for a CRUD delete. `banner` prints a numbered step, `pass_fail` a result mark, and `instrumented_run` wraps the client's run to print the prompt and keep the raw response.
- `test_queue_endpoint` in `debug_queue_endpoint.py` tests the queue endpoint to debug a 500 error.
- `test_queue_state_monitoring_debug` replicates the queue state monitoring test that failed.
- `test_websocket_auth_validation` and `test_basic_connection` test WebSocket authentication and a basic connection.
- `test_websocket_notification.py` diagnoses a `user_not_available` answer to a notification. `login_user` returns a token and user id.
- `check_websocket_state_via_admin_api` reads the connection state from the admin API. `send_notification` sends one notification and returns the response. `main` runs the flow.
