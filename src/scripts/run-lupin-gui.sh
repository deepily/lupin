#! /bin/bash
# This script runs the Lupin GUI on my Mac(s)

# Activate the virtual environment
source ~/Projects/local-interpreter-python3.10/venv/bin/activate

# Change to the directory containing the Lupin GUI using SSHFS:
cd ~/Projects/projects-sshfs/lupin/src
# echo "Current directory: $(pwd)"

LUPIN_ROOT=~/Projects/projects-sshfs/lupin
export LUPIN_ROOT

# Pass all command line arguments
python3.10 lib/clients/lupin_client_gui.py "$@"
