#!/bin/bash
# 切换到脚本所在目录
CDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$CDIR"

# 运行推送脚本
python3 send_twitter_alert.py --cron-run
