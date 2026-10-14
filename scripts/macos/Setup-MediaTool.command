#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  echo '需要 Apple Silicon macOS；请关闭终端的 Rosetta 模式。' >&2
  exit 1
fi
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"
if ! command -v brew >/dev/null 2>&1; then
  echo '请先从 https://brew.sh 安装 Homebrew，再重新运行本脚本。' >&2
  exit 1
fi
brew install python@3.12 node@24 ffmpeg-full
export PATH="$(brew --prefix node@24)/bin:$PATH"
PYTHON="$(brew --prefix python@3.12)/bin/python3.12"
"$PYTHON" -c 'import platform; assert platform.machine() == "arm64", "需要 ARM64 Python"'
if [[ ! -d .venv-macos ]]; then
  "$PYTHON" -m venv .venv-macos
fi
.venv-macos/bin/python -c 'import platform,sys; assert platform.machine() == "arm64" and sys.version_info[:2] == (3,12), "请检查已有 .venv-macos 的架构和版本"'
.venv-macos/bin/python -m pip install -r backend/requirements.txt
(cd frontend && npm ci && npm run build)
chmod +x scripts/macos/Start-MediaTool.command scripts/macos/Stop-MediaTool.command
.venv-macos/bin/python scripts/macos/start.py --check
echo '安装完成。双击 scripts/macos/Start-MediaTool.command 启动；首次识别需要下载所选模型。'
