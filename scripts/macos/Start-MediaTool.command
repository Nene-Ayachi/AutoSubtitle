#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
if [[ ! -x .venv-macos/bin/python ]]; then
  echo '请先运行：bash scripts/macos/Setup-MediaTool.command' >&2
  exit 1
fi
exec .venv-macos/bin/python scripts/macos/start.py "$@"
