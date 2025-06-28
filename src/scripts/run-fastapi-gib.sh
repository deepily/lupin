#! /bin/bash

cd /var/genie-in-the-box/src

#export GIB_CONFIG_MGR_CLI_ARGS="config_path=/src/conf/gib-app.ini splainer_path=/src/conf/gib-app-splainer.ini config_block_id=Genie+in+the+Box:+Development"

python3 -m fastapi_app.main