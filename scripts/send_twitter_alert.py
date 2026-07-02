#!/usr/bin/env python3
"""
推特 RSS 消息飞书推送脚本。
支持单独查询博主并推送，或者运行定时批量任务。
定时批量任务会将所有博主的最新消息聚合并调用大模型生成中文总结简报后，以单条消息形式推送到飞书。
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

async def generate_chinese_summary(posts: list) -> str:
    api_key = os.environ.get("MINIMAX_API_KEY")
    base_url = os.environ.get("MINIMAX_BASE_URL") or "https://api.minimaxi.com/v1"
    model = os.environ.get("MINIMAX_MODEL") or "MiniMax-M2.7-highspeed"
    
    if not api_key:
        print("警告: 未配置 MINIMAX_API_KEY，跳过大模型总结阶段。")
        return "⚠️ *提示：未配置大模型 API 凭据，无法生成每日动态摘要。请在 .env 中配置以开启此功能。*"
        
    formatted_tweets = []
    for idx, post in enumerate(posts):
        formatted_tweets.append(
            f"[{idx+1}] 博主 @{post['blogger']} ({post.get('blogger_name')}) 于 {post.get('created_at')} 发布：\n{post.get('text')}\n"
        )
    tweets_text = "\n".join(formatted_tweets)
    
    prompt = (
        "你是一个专业的自媒体助手与独立开发（Indie Hacker）情报分析师。请阅读以下独立开发者博主在过去24小时内发布的英文推文，撰写一份简洁、专业且富有启发性的中文每日动态简报总结（约300-500字）。\n"
        "总结要求：\n"
        "1. 归纳这些开发者近期关注的核心技术、产品功能更新、最新的营收变动数据或营销玩法；\n"
        "2. 总结核心要点，言简意赅，不要按序号逐条翻译推文，而是做横向归纳提炼；\n"
        "3. 排版必须使用清晰优美的 Markdown 列表（无粗体外层括号或冗余的开头客套话），每条总结前可用符合情境的 Emoji 润色。\n\n"
        f"以下是全部英文推文内容：\n{tweets_text}"
    )
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是一个推特独立开发情报简报助手，生成专业且提炼度极高的中文汇报总结。"},
            {"role": "user", "content": prompt}
        ]
    }
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers, timeout=60.0)
            if resp.status_code == 200:
                result = resp.json()
                return result["choices"][0]["message"]["content"]
            else:
                print(f"MiniMax 总结请求失败: {resp.status_code} - {resp.text}")
                return "❌ 生成中文总结简报失败：大模型服务响应异常。"
    except Exception as e:
        print(f"生成总结简报过程发生异常: {e}")
        return f"❌ 生成中文总结简报时发生异常: {e}"

def build_unified_feishu_card(summary: str, posts: list) -> dict:
    elements = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"💡 **AI 简报中文总结 (AI Summary)**:\n\n{summary}"
            }
        },
        {"tag": "hr"},
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "📋 **最新推文明细 (Tweet Details)**"
            }
        },
        {"tag": "hr"}
    ]
    
    # 限制明细最多展示 12 条推文以防超出卡片限制
    display_limit = 12
    display_posts = posts[:display_limit]
    
    for i, post in enumerate(display_posts):
        blogger = post.get("blogger") or ""
        blogger_name = post.get("blogger_name") or blogger
        text = post.get("text") or ""
        if len(text) > 300:
            text = text[:300] + "..."
        created_at = post.get("created_at") or ""
        tweet_id = post.get("tweet_id") or ""
        tweet_url = f"https://x.com/{blogger}/status/{tweet_id}" if tweet_id else ""
        
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"👤 **@{blogger}** ({blogger_name}) · {created_at}\n{text}"
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
        
    if len(posts) > display_limit:
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"💡 *注：本日共计 {len(posts)} 条推文，因卡片长度限制，明细中已隐藏剩余 {len(posts) - display_limit} 条。*"
            }
        })
    elif elements and elements[-1].get("tag") == "hr":
        elements.pop()
        
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "🐦 推特独立开发日报 (24h动态汇总)"},
                "template": "orange"
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

    all_recent_posts = []

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
            for p in recent_posts:
                p["blogger"] = blogger
                p["blogger_name"] = blogger_name
                all_recent_posts.append(p)
                
            print(f"博主 @{blogger} 最近 24 小时内有 {len(recent_posts)} 条推文。")
        except Exception as e:
            print(f"处理博主 @{blogger} 失败: {e}")

    if all_recent_posts:
        # 按发布时间倒序排列
        all_recent_posts.sort(key=lambda x: x.get("create_time", 0), reverse=True)
        print(f"合并所有推文，共计 {len(all_recent_posts)} 条。开始生成 AI 中文总结报告...")
        summary = await generate_chinese_summary(all_recent_posts)
        print("AI 总结生成成功，正在组装并发送统一消息卡片...")
        card = build_unified_feishu_card(summary, all_recent_posts)
        await send_to_feishu(webhook_url, card)
    else:
        print("所有关注博主在最近 24 小时内均无新推文，跳过发送。")

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

    # 优先级：1. 命令行参数 --webhook  2. 环境变量 FEISHU_WEBHOOK_URL
    webhook_url = args.webhook
    if not webhook_url:
        webhook_url = os.environ.get("FEISHU_WEBHOOK_URL")

    try:
        res = await fetch_rss_tweets(args.blogger, args.date)
        posts = res.get("posts") or []
        blogger_info = res.get("blogger") or {}
        blogger_name = blogger_info.get("name") or args.blogger

        if webhook_url:
            if posts:
                card = build_feishu_card(args.blogger, blogger_name, posts, filter_date=args.date)
                await send_to_feishu(webhook_url, card)
            else:
                print(f"博主 @{args.blogger} 在指定日期前无推文返回。")
        else:
            # 未指定 webhook 时，直接打印 JSON 结果到标准输出，由智能体在对话中读取和排版
            print(json.dumps(res, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"执行失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main_async())
