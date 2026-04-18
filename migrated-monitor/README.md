# 已迁移代币监控

这个子项目只监控 Binance Web3 Meme Rush 的“已迁移”代币榜，并把新增代币推送到 Telegram 或 Webhook。

## 运行

进入目录后使用：

```bash
npm run snapshot
npm run monitor
```

也可以直接执行：

```bash
python3 binance_migrated_monitor.py --once
python3 binance_migrated_monitor.py
```

默认状态文件会写到当前项目自己的 `.state/binance-migrated-bsc.json`，不会和热点雷达项目混用。
本地 Telegram 配置默认读取当前目录下的 `.env`。
可先复制 `.env.example` 为 `.env`，再填入你自己的配置。
为避免历史老币因接口抖动重新进入榜单时被误推送，默认只通知最近 1 小时内完成迁移的代币；更早的条目会写入状态文件，但不会发送 Telegram / Webhook。

如果你在浏览器里能看到“已迁移”列表，但脚本日志持续显示 `当前 0 条`，通常是 Binance 对非浏览器请求返回了空列表。
这时可以把浏览器该请求里的完整 `Cookie` 头复制到 `.env` 中的 `MIGRATED_COOKIE_HEADER`，让脚本复用已通过网页验证的会话。

## 常用参数

```bash
python3 binance_migrated_monitor.py --interval 15
python3 binance_migrated_monitor.py --limit 100
python3 binance_migrated_monitor.py --telegram-test-message "migrated monitor test"
```

这个项目默认读取当前目录下的 `.env`，也支持外部环境变量覆盖：

```bash
TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=yyy npm run monitor
```
