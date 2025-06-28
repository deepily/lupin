#! /bin/bash

if [ $# -eq 1 ]; then

  # remember where we are so we can return later
  CWD=$(pwd)

  # activate virtual environment
  cd "$DEEPILY_PROJECTS_DIR"/models
  echo "Activating virtual environment..."
  source .venv/bin/activate

  # download the model
  echo "Downloading [$1] from Huggingface..."
  cd "$DEEPILY_PROJECTS_DIR"/genie-in-the-box/src
  python -m cosa.training.hf_downloader "$1"

  # deactivate virtual environment
  echo "Deactivating virtual environment..."
  deactivate

  # return to the original directory
  cd $CWD

else

  echo "Usage: download-from-huggingface.sh <repo_id>"

fi