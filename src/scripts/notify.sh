#!/bin/bash
export PYTHONPATH="/mnt/DATA01/include/www.deepily.ai/projects/genie-in-the-box/src:$PYTHONPATH"
exec python $COSA_CLI_PATH/cosa/cli/notify_user.py "$@"