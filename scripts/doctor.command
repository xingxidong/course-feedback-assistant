#!/bin/zsh
set -e
cd "$(dirname "$0")/.."
echo "== 环境 =="
python3 --version
node --version
echo "== 微信桥接 =="
node scripts/wechat-cli.mjs status
echo "== Python语法 =="
python3 -m compileall -q app.py course_feedback
echo "== 单元测试 =="
python3 -m unittest discover -s tests -v
echo "检查完成"
