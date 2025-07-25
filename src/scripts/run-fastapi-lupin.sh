#! /bin/bash

cd /var/lupin/src

#export LUPIN_CONFIG_MGR_CLI_ARGS="config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Development"

python3 -m fastapi_app.main