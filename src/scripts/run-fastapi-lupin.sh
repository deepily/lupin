#! /bin/bash

cd /var/lupin/src

# Load LoRA model paths (auto-updated by peft_trainer.py)
[ -f ~/.lora_env ] && source ~/.lora_env

#export LUPIN_CONFIG_MGR_CLI_ARGS="config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Development"

# `exec` so the server REPLACES this bash wrapper and becomes the container's PID 1
# (Dockerfile CMD is `/bin/bash run-fastapi-lupin.sh`). Without it, bash is PID 1,
# and on `docker stop` the kernel gives PID 1 no default action for an un-handled
# SIGTERM while bash also never forwards it to this child — so uvicorn is never
# signalled, rides the full 10s grace, and is SIGKILLed (137) with ZERO shutdown
# lines: the lifespan shutdown (and the R4 managed-bounce warning in it) never runs
# (bug AC6, diagnosed 2026-08-02). With exec, uvicorn.run installs its own SIGTERM
# handler and graceful shutdown runs.
# ⚠️ UNVERIFIED: with LUPIN_RELOAD=1 uvicorn spawns a reloader subprocess; whether
# SIGTERM reaches the worker's lifespan on that path is not yet tested. Reload is
# OFF by default, so exec fixes the default path; the reload path is a follow-up.
exec python3 -m lupin_app.main