#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
touch stop.request
echo '已请求停止。正在执行的模型准备/推理会在安全返回后退出，请等待启动窗口结束。'
