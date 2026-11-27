#!/bin/bash
# 一键安装 hop-mcp 运行环境
set -e
cd "$(dirname "$0")"
rm -rf .venv
python3 -m venv .venv
./.venv/bin/pip install -U pip
# server.py 基于 mcp 1.x 的 FastMCP API，2.x 已改名为 MCPServer，故锁定 <2
./.venv/bin/pip install "mcp[cli]<2" requests
echo "安装完成：$(pwd)/.venv/bin/python"
