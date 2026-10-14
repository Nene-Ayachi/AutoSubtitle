#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "$(/usr/bin/uname -m)" != arm64 ]]; then
  echo '此版本需要 Apple Silicon Mac，请勿通过 Rosetta 启动。' >&2
  exit 1
fi
VERSION="$(/usr/bin/sw_vers -productVersion)"
if [[ "${VERSION%%.*}" -lt 14 ]]; then
  echo '此版本需要 macOS 14 或更新版本。' >&2
  exit 1
fi
unset PYTHONHOME PYTHONPATH DYLD_LIBRARY_PATH DYLD_FALLBACK_LIBRARY_PATH
export PYTHONNOUSERSITE=1
export PATH="$PWD/tools:/usr/bin:/bin:/usr/sbin:/sbin"
exec "$PWD/runtime/bin/python3" -E -s "$PWD/bootstrap.py" "$@"
