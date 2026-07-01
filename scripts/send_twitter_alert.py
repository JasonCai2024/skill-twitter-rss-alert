#!/usr/bin/env python3
"""
推特 RSS 消息飞书推送脚本。
支持单独查询博主并推送，或者运行定时批量任务。
"""
import argparse
import sys
import os
import json
import time
import uuid
import asyncio
from datetime import datetime, timezone
import httpx

# 添加项目根目录到 Python 模块路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 导入必要模块
try:
    from backend.config.settings import settings
except ImportError:
    # 兼容没有 settings 时的基准目录
    settings = None

def load_env():
    # 手动解析 .env 并加载到 os.environ 中
    env_file = os.path.join(project_root, ".env")
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        val = v.strip().strip("'").strip('"')
                        os.environ[k.strip()] = val
        except Exception:
            pass

def get_base_url() -> str:
    # 尝试连接本地，如果成功则使用本地开发服务，否则 fallback 到生产环境域名
    try:
        # 使用 httpx 同步请求检测本地服务是否在线
        with httpx.Client(timeout=1.0) as client:
            resp = client.get("http://127.0.0.1:8000/api/health")
            if resp.status_code == 200:
                return "http://127.0.0.1:8000"
    except Exception:
        pass
    return "https://www.ccailab.top"

async def fetch_rss_tweets(blogger: str, start_date: str = None) -> dict:
    url = f"{get_base_url()}/api/video/rss-twitter-data"
    payload = {
        "username": "25741114@qq.com",
        "passtoken": "456789",
        "screen_name": blogger,
        "url_process_type": "update"
    }
    if start_date:
        payload["start_date"] = start_date

    print(f"正在请求接口: {url}，博主: @{blogger}, start_date: {start_date or '无'}")
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code != 200:
            print(f"请求失败: 状态码={resp.status_code}, 内容={resp.text[:500]}")
            resp.raise_for_status()
        return resp.json()

def build_feishu_card(blogger: str, blogger_name: str, posts: list, filter_date: str = None) -> dict:
    elements = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"👤 **博主**: @{blogger} ({blogger_name})\n⏰ **统计时间**: {filter_date or '最新消息'}"
            }
        },
        {"tag": "hr"}
    ]

    for i, post in enumerate(posts):
        text = post.get("text") or ""
        if len(text) > 400:
            text = text[:400] + "..."
        created_at = post.get("created_at") or ""
        tweet_id = post.get("tweet_id") or ""
        tweet_url = f"https://x.com/{blogger}/status/{tweet_id}" if tweet_id else ""

        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"📝 **推文 [{i+1}]**:\n{text}\n\n⏰ 发布时间: {created_at}"
            }
        })
        
        if tweet_url:
            elements.append({
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "🔗 查看原文"},
                        "type": "default",
                        "url": tweet_url
                    }
                ]
            })

        elements.append({"tag": "hr"})

    if elements and elements[-1].get("tag") == "hr":
        elements.pop()

    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"🐦 推特 RSS 新帖通知 ({blogger})"},
                "template": "blue"
            },
            "elements": elements
        }
    }

async def send_to_feishu(webhook_url: str, card: dict):
    print(f"正在发送消息到飞书机器人: {webhook_url}")
    async with httpx.AsyncClient() as client:
        resp = await client.post(webhook_url, json=card, timeout=30.0)
        data = resp.json() if resp.content else {}
        if resp.status_code != 200 or data.get("code") != 0:
            raise RuntimeError(f"飞书推送失败: status={resp.status_code}, body={data}")
        print("发送成功！")

async def run_cron_batch():
    load_env()
    config_file = os.path.join(project_root, "subscribed_bloggers.json")
    
    # 优先从环境变量获取 webhook
    webhook_url = os.environ.get("FEISHU_WEBHOOK_URL")
    bloggers = []
    
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                sub_config = json.load(f)
                if not webhook_url:
                    webhook_url = sub_config.get("webhook_url")
                bloggers = sub_config.get("bloggers") or []
        except Exception:
            pass

    if not webhook_url:
        print("错误: 未配置飞书 webhook_url (请指定环境变量 FEISHU_WEBHOOK_URL 或在配置文件中配置)")
        sys.exit(1)

    threshold_time = time.time() - 86400
    print(f"开始批量获取关注博主最近 24 小时新帖: {bloggers}")

    for blogger in bloggers:
        blogger = blogger.strip().lstrip("@")
        if not blogger:
            continue
        try:
            res = await fetch_rss_tweets(blogger)
            posts = res.get("posts") or []
            blogger_info = res.get("blogger") or {}
            blogger_name = blogger_info.get("name") or blogger

            # 过滤最近 24 小时
            recent_posts = [p for p in posts if p.get("create_time", 0) >= threshold_time]
            if recent_posts:
                print(f"博主 @{blogger} 有 {len(recent_posts)} 条新推文，正在推送飞书。")
                card = build_feishu_card(blogger, blogger_name, recent_posts, filter_date="最近 24 小时")
                await send_to_feishu(webhook_url, card)
            else:
                print(f"博主 @{blogger} 最近 24 小时内无新推文。")
        except Exception as e:
            print(f"处理博主 @{blogger} 失败: {e}")

async def main_async():
    load_env()
    parser = argparse.ArgumentParser(description="推特 RSS 消息飞书推送工具")
    parser.add_argument("--blogger", type=str, help="推特博主 screen_name，如 tdinh_me")
    parser.add_argument("--date", type=str, help="指定日期，如 20260701，获取该日期及以前的数据")
    parser.add_argument("--webhook", type=str, help="可选：指定的飞书机器人 webhook 链接")
    parser.add_argument("--cron-run", action="store_true", help="运行每日定时批量推送任务（读取 subscribed_bloggers.json）")

    args = parser.parse_args()

    if args.cron_run:
        await run_cron_batch()
        return

    if not args.blogger:
        parser.print_help()
        sys.exit(1)

    # 优先级：1. 命令行参数 --webhook  2. 环境变量 FEISHU_WEBHOOK_URL  3. 配置文件
    webhook_url = args.webhook
    if not webhook_url:
        webhook_url = os.environ.get("FEISHU_WEBHOOK_URL")
    
    if not webhook_url:
        config_file = os.path.join(project_root, "subscribed_bloggers.json")
        if os.path.exists(config_file):
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    sub_config = json.load(f)
                    webhook_url = sub_config.get("webhook_url")
            except Exception:
                pass

    if not webhook_url:
        print("错误: 必须指定 --webhook，或者配置环境变量 FEISHU_WEBHOOK_URL，或者在 subscribed_bloggers.json 中配置 webhook_url")
        sys.exit(1)

    try:
        res = await fetch_rss_tweets(args.blogger, args.date)
        posts = res.get("posts") or []
        blogger_info = res.get("blogger") or {}
        blogger_name = blogger_info.get("name") or args.blogger

        if posts:
            card = build_feishu_card(args.blogger, blogger_name, posts, filter_date=args.date)
            await send_to_feishu(webhook_url, card)
        else:
            print(f"博主 @{args.blogger} 在指定日期前无推文返回。")
    except Exception as e:
        print(f"执行失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main_async())
