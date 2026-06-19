#! /bin/bash

cd /var/lupin/src

# Load LoRA model paths (auto-updated by peft_trainer.py)
[ -f ~/.lora_env ] && source ~/.lora_env

#export LUPIN_CONFIG_MGR_CLI_ARGS="config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Development"

python3 -m lupin_app.main