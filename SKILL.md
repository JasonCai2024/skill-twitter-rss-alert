---
name: skill-twitter-rss-alert
description: 获取指定推特博主的最新消息，以飞书卡片格式发送到群聊机器人，可选参数包括推特博主、以及日期。
disable-model-invocation: true
user-invocable: true
argument-hint: [file-or-input]
---

# Twitter RSS 数据同步与推送技能

## Goal
调用 ServiceHub API 获取指定 Twitter/X 博主的推文数据（可指定开始日期进行过滤），若未配置 Webhook，则将结果以 JSON 格式输出至标准输出供智能体在对话中读取、总结并呈现给用户；若配置了 Webhook，则将数据以交互式卡片的形式推送至飞书群机器人。

## Required Inputs
- `blogger` (或 `screen_name`): 必填，Twitter 博主账号名（如 `tdinh_me`），支持带有 `@` 前缀自动过滤。
- `date` (或 `start_date`): 可选，8位数字格式（YYYYMMDD，如 `20260701`），指定截止日期（只获取该日期及该日期以前的数据）。若不提供，默认返回当前请求时间及以前的数据。
- `webhook` (或 `webhook_url`): 可选，飞书机器人群组 Webhook URL。**注意**：在普通的智能体对话中，请保持此项为空，直接获取 JSON 数据进行对话排版；在定时任务脚本中，传入该参数以直接推送飞书。

## Workflow
1. **输入清洗**：去除 `blogger` 前后的空格及 `@` 字符。
2. **环境及状态检测**：
   - 检测本地 ServiceHub API (127.0.0.1:8000) 状态。
   - 若本地服务不在线，则自动将 API 基准地址 Fallback 至生产环境 API（`https://www.ccailab.top`）。
3. **接口调用（先落库后查询）**：
   - 构造请求体，调用 `POST /api/video/rss-twitter-data` 接口。
   - 接口首先在后端服务中通过 RSSHub 拉取博主最新消息写入数据库（落库），再进行日期过滤并从数据库返回相应推文。
4. **输出处理决策**：
   - **分支 A（常规对话场景，无 Webhook）**：将获取到的博主基本信息和推文数据以标准 JSON 格式输出到 stdout。智能体读取 JSON 后，应在对话窗口中主动对推文内容进行翻译、排版和摘要展示给用户。
   - **分支 B（自动推送场景，有 Webhook）**：根据推文数据构建飞书消息交互卡片，并 POST 请求推送至飞书群机器人 Webhook。

## Decision Rules
- **同步模式决策**：始终以 `update`（更新）模式调用后端接口以获取最实时的推文数据并强制落库。因为 RSSHub 对该接口没有额外的 API 调用点数消耗或账单成本，查询缓存的 `extract` 模式在此技能中不应被采用。
- **空数据处理判断**：若博主在指定条件内没有新推文，如果是推送分支则跳过推送；如果是对话分支，则返回提示信息。
- **频次与异常控制**：如果遭遇 RSSHub 因 Twitter 反爬回包 503，脚本将捕获异常并输出错误信息，智能体应告知用户稍后重试。

## Output Requirements
- 在常规对话场景下，输出必须是标准 JSON 字符串，包含 `posts` 数组和 `blogger` 信息。
- 在飞书推送场景下，终端输出 `发送成功！`。

## Validation
- **接口可达性验证**：发起请求前校验 API `/api/health`。
- **数据结构校验**：返回的 JSON response 必须包含 `posts` (数组) 和 `blogger` (字典)。

## Fallback
- 若本地开发环境 API 连接失败，自动无缝降级切换到线上生产域名 `https://www.ccailab.top`。

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
