#!/bin/bash
export PYTHONPATH="$LUPIN_ROOT/src"
exec python $LUPIN_ROOT/src/cosa/cli/notify_user.py "$@"