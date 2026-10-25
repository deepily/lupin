---
capability: presentation-gate-silence-proof
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.presentation-gate-silence-proof.prove_gate_silence.register_and_login@b686afac4a
  - scripts.presentation-gate-silence-proof.prove_gate_silence.SilentConnectedUser@61224f42b8
  - scripts.presentation-gate-silence-proof.prove_gate_silence.submit_build@12e3e91756
  - scripts.presentation-gate-silence-proof.prove_gate_silence.read_notification_state@f6ca755613
  - scripts.presentation-gate-silence-proof.prove_gate_silence.pool_status@a8b314a563
  - scripts.presentation-gate-silence-proof.prove_gate_silence.require_lock_clear@e21741ac3e
  - scripts.presentation-gate-silence-proof.prove_gate_silence.lock_clear_banner@9229bdf3aa
  - scripts.presentation-gate-silence-proof.prove_gate_silence.poll_until_terminal@354413a79f
  - scripts.presentation-gate-silence-proof.prove_gate_silence.build_verdict_direction_a@a4be911f58
  - scripts.presentation-gate-silence-proof.prove_gate_silence.main@fcc81978f7
---
# Presentation gate silence proof

Proves that presentation review gates reach a connected user, who answers them. All four presentation gates fail open: the default is Approve after a 600 second timeout. An earlier overnight run finished through the delivery-failed path, where the notify call answered 503 for lack of a session. The connected-session path had never been exercised.

## Verdict
- `build_verdict_direction_a` passes only if five checks hold. Every gate was delivered and answered, and resolved as responded. The user stayed connected, and the job reached done.
- Delivered means a `notification_queue_update` frame reached the session. Timing is not the discriminator. The final notification state is: responded with a real value means a human answered, and expired means a declared-default timeout.
- The log source label cannot separate the paths, because a delivered-but-silent timeout is stamped as a dispatch failure too.

## Running
- `register_and_login` registers a fresh user and returns the token, email and user id. If the email exists, it logs in instead.
- A fresh non-service user is both submitter and gate target. The tester account is a configured gate service account, and delivering to the operator's real inbox is off limits.
- `SilentConnectedUser` holds an authenticated queue WebSocket open, records every gate ask as delivery proof and samples liveness. In answer mode it posts a response for each gate.
- `submit_build` submits a real presentation build through `/api/v2/submit`. `poll_until_terminal` polls the run, done and dead queues until the job is done or dead, or time runs out.
- `read_notification_state` reads one gate notification's state and response value without changing anything.

## Precondition and venue
- `require_lock_clear` raises `RuntimeError` unless no monopolizer holds the pool, because a deferred job would deadlock and burn the window. `pool_status` reads the pool.
- `lock_clear_banner` names the field it read and its blind spot: it cannot see shared-pool jobs in flight. The venue question is answered by the idle check.
- `main` runs answer mode against `:8000` in monopolize mode. The build costs about 15 minutes of tokens.
