#!/bin/bash
cd /home/kavia/workspace/code-generation/video-upload-platform-6838-6847/video_upload_backend
source venv/bin/activate
flake8 .
LINT_EXIT_CODE=$?
if [ $LINT_EXIT_CODE -ne 0 ]; then
  exit 1
fi

