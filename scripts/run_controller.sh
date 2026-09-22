#!/bin/bash

set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_FILE="/tmp/aws-custom-autoscaling-controller.lock"

cd "$PROJECT_DIR" || exit 1

if [ -f "$PROJECT_DIR/.venv/bin/activate" ]; then
    source "$PROJECT_DIR/.venv/bin/activate"
fi

flock -n "$LOCK_FILE" \
    python3 "$PROJECT_DIR/controller/controller.py"

EXIT_CODE=$?

if [ "$EXIT_CODE" -eq 1 ]; then
    echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") - Controller already running. Cycle skipped."
fi

exit 0
