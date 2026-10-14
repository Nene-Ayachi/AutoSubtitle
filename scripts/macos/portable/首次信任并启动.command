#!/bin/bash
set -euo pipefail
# Use only macOS system tools: the private Python may still be quarantined.
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
cd -P "$(dirname "$0")"
BUNDLE_DIR="$PWD"
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != --trust-only ) ]]; then
  echo '用法：首次信任并启动.command [--trust-only]' >&2
  exit 2
fi
if [[ "$BUNDLE_DIR" == / || "$BUNDLE_DIR" == "$HOME" ]]; then
  echo '拒绝处理系统目录或个人主目录。' >&2
  exit 1
fi
for entry in bundle-manifest.json Start-MediaTool.command bootstrap.py; do
  if [[ ! -f "$entry" || -L "$entry" ]]; then
    echo "没有找到完整的便携包，或关键入口是符号链接：$entry" >&2
    exit 1
  fi
done
for entry in runtime tools backend web; do
  if [[ ! -d "$entry" || -L "$entry" ]]; then
    echo "没有找到完整的便携包，或组件目录是符号链接：$entry" >&2
    exit 1
  fi
done
cat <<'NOTICE'
Media Tool · 首次本地信任

此软件包尚未经过 Apple 公证。继续表示你已核实来源，并信任包内代码。
本操作仅删除下方目录及其内部文件的 com.apple.quarantine 隔离标记，
让 Python、Metal 和媒体工具不再因该标记逐个请求允许。
不会关闭 Gatekeeper，不会使用 sudo，不会删除其他扩展属性，
不会沿符号链接修改包外文件。此操作不是 Apple 签名或公证。

NOTICE
printf '将处理的目录：\n%s\n\n' "$BUNDLE_DIR"
printf '输入大写 TRUST 并回车以信任此包；其他输入或关闭窗口均取消：'
ANSWER=''
if ! IFS= read -r ANSWER || [[ "$ANSWER" != TRUST ]]; then
  echo '已取消，未修改隔离标记，也未启动程序。'
  exit 0
fi
# -s operates on links themselves, never their external targets.
if ! /usr/bin/xattr -drs com.apple.quarantine "$BUNDLE_DIR"; then
  echo '未能完成信任初始化，程序不会启动。请检查目录权限和上述错误；不要使用 sudo。' >&2
  exit 1
fi
echo '本地信任初始化完成。以后直接双击 Start-MediaTool.command 即可。'
if [[ "${1:-}" != --trust-only ]]; then
  exec /bin/bash "$BUNDLE_DIR/Start-MediaTool.command"
fi
