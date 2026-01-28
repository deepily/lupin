#! /bin/bash

export LUPIN_ROOT=/var/model/lupin
export GIB_CONFIG_MGR_CLI_ARGS="config_path=/src/conf/gib-app.ini splainer_path=/src/conf/gib-app-splainer.ini config_block_id=Genie+in+the+Box:+Development"
export LUPIN_TGI_SERVER=http://192.168.1.21:3000/v1

cd /var/model/lupin/src

echo ""
echo "export LUPIN_ROOT=/var/model/lupin"
echo "export GIB_CONFIG_MGR_CLI_ARGS=\"config_path=/src/conf/gib-app.ini splainer_path=/src/conf/gib-app-splainer.ini config_block_id=Genie+in+the+Box:+Development\""
echo "export LUPIN_TGI_SERVER=http://192.168.1.21:3000/v1"
echo ""
echo "Running: python3 -m ephemera.notebooks.cosa.gsm8k --help"
echo ""
python3 -m ephemera.notebooks.cosa.gsm8k --help