# Binance Web3 监控工作区

这个仓库现在已经拆成两个独立子项目：

- `migrated-monitor/`
  只监控 Binance Web3 Meme Rush 的“已迁移”代币，并发送代币卡片推送
- `topic-rush-monitor/`
  只监控 Binance Web3 Topic Rush / 热点雷达，并推送热点主题消息

根目录保留了一份共享运行引擎 `binance_migrated_monitor.py`，两个子项目都通过自己的入口脚本调用它，所以后续修接口、修 Telegram 模板时不需要维护两套重复代码。

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
└── binance_migrated_monitor.py
```

## 从根目录启动

```bash
npm run migrated:snapshot
npm run migrated:monitor

npm run topic:snapshot
npm run topic:monitor

npm run start
npm run status
npm run stop
```

如果你更习惯进入子项目目录，也可以分别进入：

- `migrated-monitor/README.md`
- `topic-rush-monitor/README.md`

## 状态文件

两个子项目默认分别使用自己的状态文件：

- `migrated-monitor/.state/binance-migrated-bsc.json`
- `topic-rush-monitor/.state/binance-topic-rush-bsc.json`

这样“已迁移”与“热点雷达”的基线、去重和推送节奏不会互相影响。

## Telegram 约定

- `migrated-monitor/` 默认读取自己目录下的 `.env`
- `topic-rush-monitor/` 默认读取自己目录下的 `.env`
- `topic-rush-monitor/` 不会继承 `migrated-monitor/` 使用的全局 Telegram 配置
- 热点雷达已经是单独推送；如果需要显式指定它的 Telegram 配置，可使用 `TOPIC_TELEGRAM_BOT_TOKEN` / `TOPIC_TELEGRAM_CHAT_ID`

## 服务脚本

- `start_monitors.sh` 同时启动两个监控
- `stop_monitors.sh` 停止两个监控
- `status_monitors.sh` 查看两个监控状态和最近日志
