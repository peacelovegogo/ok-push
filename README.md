# Binance Web3 监控

这个仓库存放两个独立服务目录：

- `migrated-monitor/`
  只监控 Binance Web3 Meme Rush 的“已迁移”代币，并发送代币卡片推送
- `topic-rush-monitor/`
  只监控 Binance Web3 Topic Rush / 热点雷达，并推送热点主题消息

两个目录都可以独立运行和部署。

## 目录结构

```text
.
├── migrated-monitor/
│   ├── README.md
│   ├── package.json
│   └── binance_migrated_monitor.py
├── topic-rush-monitor/
│   ├── README.md
│   ├── package.json
│   └── binance_topic_rush_monitor.py
```

## 使用方式

直接进入对应目录查看说明并启动：

- `migrated-monitor/README.md`
- `topic-rush-monitor/README.md`

如果你只想单独部署其中一个服务，直接复制对应子项目目录即可。

## 状态文件

两个子项目默认分别使用自己的状态文件：

- `migrated-monitor/.state/binance-migrated-bsc.json`
- `topic-rush-monitor/.state/binance-topic-rush-bsc.json`

两个服务分别维护自己的基线、去重记录和推送节奏。

## Telegram 约定

- `migrated-monitor/` 默认读取自己目录下的 `.env`
- `topic-rush-monitor/` 默认读取自己目录下的 `.env`
- `topic-rush-monitor/` 也支持 `TOPIC_TELEGRAM_BOT_TOKEN` / `TOPIC_TELEGRAM_CHAT_ID`

根目录不提供统一运行入口；每个服务都在自己的目录内维护配置、状态文件和启动方式。
