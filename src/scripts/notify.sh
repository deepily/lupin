#!/bin/bash
export PYTHONPATH=/mnt/DATA01/include/www.deepily.ai/projects/genie-in-the-box/src
exec python -m cosa.cli.notify_user "$@"