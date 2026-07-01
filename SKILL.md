---
name: skill-twitter-rss-alert
description: 获取指定推特博主的最新消息，以飞书卡片格式发送到群聊机器人，可选参数包括推特博主、以及日期。
disable-model-invocation: true
user-invocable: true
argument-hint: [file-or-input]
---

# Twitter RSS 飞书自动监控提醒技能

## Goal
利用本地部署的 RSSHub 抓取指定 Twitter/X 博主的最新推文，清洗转换并构造为精致的飞书互动消息卡片，自动投递到飞书群聊机器人。

## Required Inputs
- `blogger` (或 `screen_name`): 必填，Twitter 博主账号名（如 `tdinh_me`），支持带有 `@` 前缀自动净化。
- `date` (或 `start_date`): 可选，8位数字格式（YYYYMMDD，如 `20260701`），指定截止日期（只获取该日期及该日期以前的数据）。若不提供，默认返回当前请求时间及以前的数据。
- `webhook` (或 `webhook_url`): 可选，飞书机器人群组 Webhook URL。若未提供，将使用默认配置或配置文件 `subscribed_bloggers.json` 中的 `webhook_url`。

## Workflow
1. **输入清洗**：去除 `blogger` 前后的空格及 `@` 字符。
2. **环境及状态检测**：
   - 检测本地 ServiceHub API (127.0.0.1:8000) 状态。
   - 若本地服务不在线，则自动将 API 基准地址 Fallback 至生产环境 API（`https://www.ccailab.top`）。
3. **接口调用（先落库后查询）**：
   - 构造请求体，调用 `POST /api/video/rss-twitter-data` 接口。
   - 接口首先在后端服务中通过 RSSHub 拉取博主最新消息写入数据库（落库），再进行日期过滤并从数据库返回相应推文。
4. **消息过滤**：
   - 若提供了 `date`，则筛选发表时间 `pub_date` 小于等于指定日期 end-of-day 的推文。
   - 若运行的是批量定时脚本，则只筛选最近 24 小时（即 `timestamp >= now - 86400`）发布的新推文。
5. **消息卡片构建**：
   - 遍历过滤后的推文，每条推文提取 `text`（限制400字以防报文溢出）、发布时间 `created_at`、推文链接 `https://x.com/{blogger}/status/{tweet_id}`。
   - 组装成包含互动按钮的飞书卡片。
6. **机器人推送**：
   - 通过 POST 请求将飞书卡片推送至群机器人 webhook URL。

## Decision Rules
- **是否推送判断**：若博主在指定条件（指定日期或最近 24 小时）内没有新推文，则跳过推送，不发送空消息。
- **频次与异常控制**：如果遭遇 RSSHub 因 Twitter 反爬回包 503，脚本将捕获异常并记录，继续处理队列中其他博主，防止任务崩溃。

## Output Requirements
- 运行成功后，终端将输出：
  `正在请求接口...`
  `正在发送消息到飞书机器人...`
  `发送成功！`
- 推送至飞书群的卡片模板包含：蓝色顶部标题头（含有博主名）、博主基本信息、推文列表（带数字序号）及“查看原文”跳转按钮。

## Validation
- **接口可达性验证**：发起请求前校验 API `/api/health`。
- **数据结构校验**：返回的 JSON response 必须包含 `posts` (数组) 和 `blogger` (字典)。

## Fallback
- 若本地开发环境 API 连接失败，自动无缝降级切换到线上生产域名 `https://www.ccailab.top`。
- 若无法获取任何 Webhook URL，脚本将报错退出并提示 `必须指定 --webhook，或者在 subscribed_bloggers.json 中配置 webhook_url`。

## Examples
- 场景一：查询单个博主并推送到飞书：
  ```powershell
  python scripts/send_twitter_alert.py --blogger tdinh_me
  ```
- 场景二：查询单个博主、设定日期过滤并使用自定义 Webhook：
  ```powershell
  python scripts/send_twitter_alert.py --blogger tdinh_me --date 20260701 --webhook https://open.feishu.cn/open-apis/bot/v2/hook/xxx
  ```
- 场景三：运行批量监控关注博主的定时任务：
  ```powershell
  python scripts/send_twitter_alert.py --cron-run
  ```
