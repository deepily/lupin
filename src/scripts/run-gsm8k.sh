#! /bin/bash

export GENIE_IN_THE_BOX_ROOT=/var/model/genie-in-the-box
export GIB_CONFIG_MGR_CLI_ARGS="config_path=/src/conf/gib-app.ini splainer_path=/src/conf/gib-app-splainer.ini config_block_id=Genie+in+the+Box:+Development"
export GENIE_IN_THE_BOX_TGI_SERVER=http://192.168.1.21:3000/v1

cd /var/model/genie-in-the-box/src

echo ""
echo "export GENIE_IN_THE_BOX_ROOT=/var/model/genie-in-the-box"
echo "export GIB_CONFIG_MGR_CLI_ARGS=\"config_path=/src/conf/gib-app.ini splainer_path=/src/conf/gib-app-splainer.ini config_block_id=Genie+in+the+Box:+Development\""
echo "export GENIE_IN_THE_BOX_TGI_SERVER=http://192.168.1.21:3000/v1"
echo ""
echo "Running: python3 -m ephemera.notebooks.cosa.gsm8k --help"
echo ""
python3 -m ephemera.notebooks.cosa.gsm8k --help