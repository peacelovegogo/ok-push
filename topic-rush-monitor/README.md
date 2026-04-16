# 热点雷达监控

这个子项目只监控 Binance Web3 Topic Rush / 热点雷达，不再包含“已迁移”代币推送。

默认会同时监控：

- `Latest`
- `Rising`
- `Viral`

## 运行

进入目录后使用：

```bash
npm run snapshot
npm run monitor
```

也可以按榜单单独启动：

```bash
npm run latest-monitor
npm run rising-monitor
npm run viral-monitor
```

默认状态文件会写到当前项目自己的 `.state/binance-topic-rush-bsc.json`。
本地 Telegram 配置默认读取当前目录下的 `.env`。
可先复制 `.env.example` 为 `.env`，再填入你自己的配置。

## 常用参数

```bash
python3 binance_topic_rush_monitor.py --once
python3 binance_topic_rush_monitor.py --feeds topic-latest
python3 binance_topic_rush_monitor.py --telegram-test-message "topic rush test"
```

默认不会继承你给“已迁移代币”项目配置的全局 `TELEGRAM_*` / `TG_*` 环境变量，避免热点雷达误用同一个 bot；它会优先读取当前目录下的 `.env`。

如果你想在当前目录 `.env` 之外显式指定热点雷达的 Telegram 配置，也可以使用这些环境变量：

```bash
TOPIC_TELEGRAM_BOT_TOKEN=xxx TOPIC_TELEGRAM_CHAT_ID=yyy npm run monitor
```
